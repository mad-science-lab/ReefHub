"""MQTT side: publish state, parse commands, optional Home Assistant discovery.

Topic layout (base is `reefhub` by default):

    <base>/status                    online | offline   (broker last-will)
    <base>/controller                online | offline   (can we reach the Apex?)
    <base>/state                     one JSON document with everything
    <base>/outlet/<did>/mode         OFF | AUTO | ON
    <base>/outlet/<did>/energized    ON | OFF
    <base>/outlet/<did>/state        raw Apex state: AON | AOF | ON | OFF | TBL
    <base>/outlet/<did>/percent      0-100, only for outlets that report a level
    <base>/outlet/<did>/pump_mode    MXM pumps only: the mode text the Apex reports
    <base>/outlet/<did>/set          <- OFF | AUTO | ON
    <base>/probe/<did>               value (ON/OFF for digital inputs)
    <base>/feed/mode                 OFF | A | B | C | D
    <base>/feed/remaining            seconds left in the running cycle
    <base>/feed/set                  <- A | B | C | D | CANCEL
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiomqtt

from .config import Config
from .model import FEED_LETTERS, Snapshot, group_default_name, group_key

_LOG = logging.getLogger("reefhub.mqtt")

OUTLET_MODES = ("OFF", "AUTO", "ON")
FEED_COMMANDS = {"A": 1, "B": 2, "C": 3, "D": 4, "1": 1, "2": 2, "3": 3, "4": 4}
FEED_CANCEL = {"CANCEL", "STOP", "OFF", "0"}


@dataclass(frozen=True)
class OutletCommand:
    did: str
    mode: str


@dataclass(frozen=True)
class FeedCommand:
    cycle: int  # 1..4 start, 0 cancel


Command = OutletCommand | FeedCommand


class Mqtt:
    """One broker connection. Use as `async with`; build a new one to reconnect."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._base = cfg.base_topic
        self._client: aiomqtt.Client | None = None
        self._sent: dict[str, str] = {}  # topic -> last payload, to skip repeats
        self._percent_seen: set[str] = set()
        self._mode_seen: set[str] = set()

    async def __aenter__(self) -> Mqtt:
        c = self._cfg
        self._client = aiomqtt.Client(
            hostname=c.mqtt_host,
            port=c.mqtt_port,
            username=c.mqtt_username,
            password=c.mqtt_password,
            identifier=f"{c.base_topic}-hub",
            will=aiomqtt.Will(f"{self._base}/status", "offline", qos=1, retain=True),
        )
        await self._client.__aenter__()
        await self._client.publish(f"{self._base}/status", "online", qos=1, retain=True)
        await self._client.subscribe(f"{self._base}/outlet/+/set", qos=1)
        await self._client.subscribe(f"{self._base}/feed/set", qos=1)
        _LOG.info("connected to %s:%s", c.mqtt_host, c.mqtt_port)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            try:
                await self._client.publish(f"{self._base}/status", "offline", qos=1, retain=True)
            except aiomqtt.MqttError:
                pass
            await self._client.__aexit__(*exc)
            self._client = None

    async def _put(self, topic: str, payload: str, *, retain: bool = True) -> None:
        if self._sent.get(topic) == payload:
            return
        assert self._client is not None
        await self._client.publish(topic, payload, qos=1, retain=retain)
        self._sent[topic] = payload

    # -- state --------------------------------------------------------------

    async def publish_controller(self, online: bool) -> None:
        await self._put(f"{self._base}/controller", "online" if online else "offline")

    async def publish_snapshot(self, snap: Snapshot) -> None:
        b = self._base
        doc: dict[str, Any] = {
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "controller": {
                "serial": snap.serial,
                "hostname": snap.hostname,
                "software": snap.software,
                "hardware": snap.hardware,
            },
            "feed": {
                "mode": snap.feed.mode,
                "seconds_remaining": snap.feed.seconds_remaining,
            },
            "outlets": {},
            "probes": {},
        }
        for o in snap.outlets:
            doc["outlets"][o.did] = {
                "name": o.apex_name,
                "mode": o.mode,
                "energized": o.energized,
                "state": o.raw_state,
                "percent": o.percent,
                "pump_mode": o.pump_mode,
                "type": o.type,
                "device": group_key(o.did, o.module),
            }
            await self._put(f"{b}/outlet/{o.did}/mode", o.mode)
            await self._put(f"{b}/outlet/{o.did}/energized", "ON" if o.energized else "OFF")
            await self._put(f"{b}/outlet/{o.did}/state", o.raw_state)
            if o.percent is not None:
                self._percent_seen.add(o.did)
                await self._put(f"{b}/outlet/{o.did}/percent", str(o.percent))
            elif o.did in self._percent_seen:
                await self._put(f"{b}/outlet/{o.did}/percent", "unknown")
            if o.pump_mode is not None:
                self._mode_seen.add(o.did)
                await self._put(f"{b}/outlet/{o.did}/pump_mode", o.pump_mode)
            elif o.did in self._mode_seen:
                await self._put(f"{b}/outlet/{o.did}/pump_mode", "unknown")

        for p in snap.probes:
            doc["probes"][p.did] = {
                "name": p.apex_name,
                "type": p.type,
                "value": p.value,
                "device": group_key(p.did),
            }
            if p.value is None:
                continue
            text = ("ON" if p.value else "OFF") if isinstance(p.value, bool) else f"{p.value:g}"
            await self._put(f"{b}/probe/{p.did}", text)

        await self._put(f"{b}/feed/mode", snap.feed.mode)
        await self._put(f"{b}/feed/remaining", str(snap.feed.seconds_remaining))
        await self._put(f"{b}/state", json.dumps(doc, sort_keys=True))

    # -- Home Assistant discovery -------------------------------------------

    async def publish_discovery(self, snap: Snapshot) -> None:
        """One HA device per Apex module, plus a Feed device."""
        if not self._cfg.ha_discovery:
            return
        b, prefix = self._base, self._cfg.ha_prefix
        uid = re.sub(r"\W+", "_", f"reefhub_{snap.serial}").lower()

        avail = {
            "availability": [{"topic": f"{b}/status"}, {"topic": f"{b}/controller"}],
            "availability_mode": "all",
        }

        def make_device(key: str, name: str, model: str) -> dict[str, Any]:
            return {
                "identifiers": [f"{uid}_{key}"],
                "name": name,
                "manufacturer": "Neptune Systems",
                "model": model,
            }

        async def entity(
            component: str, dev: dict[str, Any], key: str, body: dict[str, Any]
        ) -> None:
            slug = re.sub(r"\W+", "_", key).lower()
            object_id = f"{dev['identifiers'][0]}_{slug}"
            body = {"unique_id": object_id, **avail, "device": dev, **body}
            await self._put(f"{prefix}/{component}/{object_id}/config", json.dumps(body))

        devices: dict[str, dict[str, Any]] = {}

        def device_for(key: str) -> dict[str, Any]:
            if key not in devices:
                if key[:1] == "m" and key[1:].isdigit():
                    model = snap.modules.get(int(key[1:])) or "Module"
                else:
                    model = snap.system_type or "Apex"
                devices[key] = make_device(
                    key, group_default_name(key, snap), model
                )
            return devices[key]

        for o in snap.outlets:
            dev = device_for(group_key(o.did, o.module))
            name = o.apex_name
            await entity("select", dev, f"outlet_{o.did}", {
                "name": name,
                "options": list(OUTLET_MODES),
                "state_topic": f"{b}/outlet/{o.did}/mode",
                "command_topic": f"{b}/outlet/{o.did}/set",
                "icon": "mdi:power-socket-us",
            })
            await entity("binary_sensor", dev, f"outlet_{o.did}_on", {
                "name": f"{name} energized",
                "state_topic": f"{b}/outlet/{o.did}/energized",
                "device_class": "power",
            })
            await entity("sensor", dev, f"outlet_{o.did}_state", {
                "name": f"{name} state",
                "state_topic": f"{b}/outlet/{o.did}/state",
                "icon": "mdi:state-machine",
            })
            if o.percent is not None or o.did in self._percent_seen:
                await entity("sensor", dev, f"outlet_{o.did}_percent", {
                    "name": f"{name} power",
                    "state_topic": f"{b}/outlet/{o.did}/percent",
                    "unit_of_measurement": "%",
                    "state_class": "measurement",
                    "icon": "mdi:gauge",
                })
            if o.pump_mode is not None or o.did in self._mode_seen:
                await entity("sensor", dev, f"outlet_{o.did}_pump_mode", {
                    "name": f"{name} mode",
                    "state_topic": f"{b}/outlet/{o.did}/pump_mode",
                    "icon": "mdi:waves",
                })

        for p in snap.probes:
            dev = device_for(group_key(p.did))
            name = p.apex_name
            body: dict[str, Any] = {"name": name, "state_topic": f"{b}/probe/{p.did}"}
            if p.type == "digital":
                await entity("binary_sensor", dev, f"probe_{p.did}", body)
                continue
            body["state_class"] = "measurement"
            if p.type == "Temp":
                body["device_class"] = "temperature"
                v = p.value if isinstance(p.value, float) else None
                # The Apex reports both scales with no unit field.
                body["unit_of_measurement"] = "°C" if v is not None and v <= 45 else "°F"
            elif p.type == "Amps":
                body.update(device_class="current", unit_of_measurement="A")
            elif p.type == "pwr":
                body.update(device_class="power", unit_of_measurement="W")
            elif p.type == "volts":
                body.update(device_class="voltage", unit_of_measurement="V")
            elif p.type == "pH":
                body["unit_of_measurement"] = "pH"
            await entity("sensor", dev, f"probe_{p.did}", body)

        feed = make_device("feed", "ReefHub Feed", "Feed cycles")
        await entity("sensor", feed, "mode", {
            "name": "Feed mode",
            "state_topic": f"{b}/feed/mode",
            "icon": "mdi:fish",
        })
        await entity("sensor", feed, "remaining", {
            "name": "Feed time remaining",
            "state_topic": f"{b}/feed/remaining",
            "unit_of_measurement": "s",
            "device_class": "duration",
            "icon": "mdi:timer-sand",
        })
        for letter in (*FEED_LETTERS.values(), "CANCEL"):
            default = "Cancel feed" if letter == "CANCEL" else f"Feed {letter}"
            await entity("button", feed, f"button_{letter}", {
                "name": default,
                "command_topic": f"{b}/feed/set",
                "payload_press": letter,
                "icon": "mdi:close-octagon" if letter == "CANCEL" else "mdi:fish-food",
            })

    # -- commands -----------------------------------------------------------

    async def commands(self) -> AsyncIterator[Command]:
        assert self._client is not None
        async for msg in self._client.messages:
            topic = str(msg.topic)
            cmd = parse_command(self._base, topic, msg.payload)
            if cmd is not None:
                yield cmd


def parse_command(base: str, topic: str, payload: Any) -> Command | None:
    text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
    body = text.strip().strip('"').upper()

    if topic == f"{base}/feed/set":
        if body in FEED_COMMANDS:
            return FeedCommand(FEED_COMMANDS[body])
        if body in FEED_CANCEL:
            return FeedCommand(0)
        _LOG.warning("ignoring feed command %r (use A, B, C, D or CANCEL)", text)
        return None

    m = re.fullmatch(re.escape(base) + r"/outlet/([^/]+)/set", topic)
    if m:
        if body in OUTLET_MODES:
            return OutletCommand(did=m.group(1), mode=body)
        _LOG.warning("ignoring outlet command %r for %s (use OFF, AUTO or ON)", text, m.group(1))
    return None
