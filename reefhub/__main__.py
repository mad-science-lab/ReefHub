"""Entry point: `python -m reefhub`."""

from __future__ import annotations

import asyncio
import logging
import sys

from . import __version__
from .config import ConfigError, load
from .hub import Hub


def main() -> None:
    try:
        cfg = load()
    except ConfigError as exc:
        sys.exit(f"ReefHub: configuration error: {exc}")
    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("reefhub").info("ReefHub %s starting", __version__)
    try:
        asyncio.run(Hub(cfg).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
