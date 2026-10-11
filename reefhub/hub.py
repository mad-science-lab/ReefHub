"""The whole bridge: poll the Apex, publish to MQTT, act on commands."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

import aiomqtt

from .apex import ApexAuthError, ApexClient, ApexRateLimited
from .config import Config
from .model import Snapshot, parse_status
from .mqtt import Command, FeedCommand, Mqtt, OutletCommand

_LOG = logging.getLogger("reefhub.hub")

_MAX_BACKOFF = 120


class Hub:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.snapshot: Snapshot | None = None
        self.controller_online = False
        self._apex: ApexClient | None = None
        self._mqtt: Mqtt | None = None
        self._poll_now = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    # -- lifecycle ----------------------------------------------------------

    async def run(self) -> None:
        c = self.cfg
        async with ApexClient(c.apex_host, c.apex_username, c.apex_password) as apex:
            self._apex = apex
            while True:
                try:
                    async with Mqtt(c) as mqtt:
                        self._mqtt = mqtt
                        async with asyncio.TaskGroup() as tg:
                            tg.create_task(self._poll_loop(mqtt))
                            tg.create_task(self._command_loop(mqtt))
                except* aiomqtt.MqttError as eg:
                    _LOG.warning("MQTT connection lost (%s) - retrying in 5s", eg.exceptions[0])
                finally:
                    self._mqtt = None
                await asyncio.sleep(5)

    # -- Apex -> MQTT -------------------------------------------------------

    async def _poll_loop(self, mqtt: Mqtt) -> None:
        assert self._apex is not None
        failures = 0
        while True:
            wait = float(self.cfg.poll_seconds)
            try:
                snap = parse_status(await self._apex.get_status())
                failures = 0
                self.snapshot = snap
                if not self.controller_online:
                    _LOG.info("Apex %s reachable (%d outlets, %d probes)",
                              snap.serial, len(snap.outlets), len(snap.probes))
                self.controller_online = True
                await mqtt.publish_controller(True)
                await mqtt.publish_discovery(snap)
                await mqtt.publish_snapshot(snap)
            except ApexRateLimited as exc:
                wait = exc.retry_after
                _LOG.warning("Apex rate-limited us, waiting %.0fs", wait)
            except ApexAuthError:
                _LOG.error("Apex rejected the username/password - check APEX_USERNAME/APEX_PASSWORD")
                failures += 1
                wait = await self._apex_down(mqtt, failures)
            except aiomqtt.MqttError:
                raise
            except Exception as exc:  # network error, bad JSON, timeout
                _LOG.warning("Apex poll failed: %s", exc or type(exc).__name__)
                failures += 1
                wait = await self._apex_down(mqtt, failures)

            try:
                await asyncio.wait_for(self._poll_now.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            self._poll_now.clear()

    async def _apex_down(self, mqtt: Mqtt, failures: int) -> float:
        self.controller_online = False
        await mqtt.publish_controller(False)
        return float(min(self.cfg.poll_seconds * 2 ** min(failures, 5), _MAX_BACKOFF))

    # -- MQTT -> Apex -------------------------------------------------------

    async def _command_loop(self, mqtt: Mqtt) -> None:
        async for cmd in mqtt.commands():
            try:
                await self._dispatch(cmd)
            except ApexRateLimited as exc:
                _LOG.warning("command dropped, Apex rate-limited (%.0fs)", exc.retry_after)
            except aiomqtt.MqttError:
                raise
            except Exception:
                _LOG.exception("command failed: %r", cmd)

    async def _dispatch(self, cmd: Command) -> None:
        assert self._apex is not None
        known = {o.did for o in self.snapshot.outlets} if self.snapshot else set()
        if isinstance(cmd, OutletCommand):
            if known and cmd.did not in known:
                _LOG.warning("no outlet with id %r", cmd.did)
                return
            _LOG.info("outlet %s -> %s", cmd.did, cmd.mode)
            await self._apex.set_outlet(cmd.did, cmd.mode)
        elif isinstance(cmd, FeedCommand):
            if cmd.cycle == 0:
                # Cancelling while idle corrupts the controller's feed block for
                # ~17 hours, so only cancel when a cycle is actually running.
                raw = self.snapshot.feed.raw_name if self.snapshot else None
                if raw == 0:
                    _LOG.info("feed cancel ignored - nothing is running")
                    return
                _LOG.info("feed cancel")
                await self._apex.cancel_feed()
            else:
                _LOG.info("feed cycle %d", cmd.cycle)
                await self._apex.start_feed(cmd.cycle)
        self._later(self._repoll())

    async def _repoll(self) -> None:
        await asyncio.sleep(1.0)  # give the controller a moment to apply it
        self._poll_now.set()

    def _later(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
