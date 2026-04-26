#!/usr/bin/env python3
"""
Health check for Stygian-Relay.

The bot writes a heartbeat file every 30s containing a UTC timestamp and the
current database health flag. This script fails fast if:
  - the heartbeat file is missing,
  - it's older than HEARTBEAT_MAX_AGE_SECONDS, or
  - the bot reports the database is unhealthy.

That way the container is reported unhealthy when the bot has hung, crashed,
or lost its Mongo connection — not just when /app exists.
"""

import json
import os
import sys
import time

HEARTBEAT_PATH = os.environ.get("HEARTBEAT_PATH", "/app/healthcheck.state")
HEARTBEAT_MAX_AGE_SECONDS = int(os.environ.get("HEARTBEAT_MAX_AGE_SECONDS", "90"))


def _fail(reason: str) -> None:
    print(f"UNHEALTHY: {reason}", flush=True)
    sys.exit(1)


def main() -> None:
    if not os.path.exists(HEARTBEAT_PATH):
        _fail(f"heartbeat file missing at {HEARTBEAT_PATH}")

    age = time.time() - os.path.getmtime(HEARTBEAT_PATH)
    if age > HEARTBEAT_MAX_AGE_SECONDS:
        _fail(f"heartbeat stale ({age:.0f}s > {HEARTBEAT_MAX_AGE_SECONDS}s)")

    try:
        with open(HEARTBEAT_PATH, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError) as exc:
        _fail(f"could not read heartbeat: {exc}")

    if not state.get("db_healthy", False):
        _fail("bot reports database unhealthy")

    print(f"HEALTHY (heartbeat age={age:.0f}s)", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
