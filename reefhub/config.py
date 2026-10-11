"""Configuration: environment variables only. No config file to hand-edit."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    pass


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        if default is None:
            raise ConfigError(f"{name} is required")
        return default
    return value


def _flag(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    apex_host: str
    apex_username: str
    apex_password: str
    poll_seconds: int
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    base_topic: str
    ha_discovery: bool
    ha_prefix: str
    log_level: str


def load() -> Config:
    try:
        poll = int(_env("POLL_SECONDS", "15"))
        mqtt_port = int(_env("MQTT_PORT", "1883"))
    except ValueError as exc:
        raise ConfigError(f"expected a whole number: {exc}") from exc
    if poll < 5:
        # The Apex rate-limits; hammering it is how you get 429s.
        raise ConfigError("POLL_SECONDS must be at least 5")
    return Config(
        apex_host=_env("APEX_HOST"),
        apex_username=_env("APEX_USERNAME", "admin"),
        apex_password=_env("APEX_PASSWORD", ""),
        poll_seconds=poll,
        mqtt_host=_env("MQTT_HOST"),
        mqtt_port=mqtt_port,
        mqtt_username=os.environ.get("MQTT_USERNAME") or None,
        mqtt_password=os.environ.get("MQTT_PASSWORD") or None,
        base_topic=_env("MQTT_BASE_TOPIC", "reefhub").strip("/"),
        ha_discovery=_flag("HA_DISCOVERY", True),
        ha_prefix=_env("HA_DISCOVERY_PREFIX", "homeassistant").strip("/"),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
    )
