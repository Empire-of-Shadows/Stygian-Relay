# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""RedisCache — RESERVED SLOT (not implemented in v1).

Why it exists now: the cache interface is fixed (``CacheBackend``) so a shared,
cross-process backend can be dropped in later WITHOUT touching engine code or any bot's
storage layer — a bot would only change ``CACHE_BACKEND`` in its ``bindings.py``.

Who actually benefits from Redis here (and why v1 is local-only): single-process Discord
bots gain nothing from a network cache — a local dict is strictly faster and needs no
infra, and MongoDB change streams already give cross-process coherency from the
authoritative source. Redis pays off for multi-worker services (EmpiresWeb), shared SSO
sessions, and genuinely cross-bot shared state (premium flags, global rate limits).

Implementation notes for when this is built:
  * Follow ShadowVeil's dual-backend pattern (``BotSupports/ShadowVeil/shadowveil/cache.py``):
    Redis primary with graceful fallback to ``LocalCache`` on outage.
  * Redis I/O is a network round-trip. Either expose an async variant of ``CacheBackend``
    or wrap a sync ``redis`` client; do not block the event loop.
  * Use native key TTLs (``SETEX``/``EXPIRE``); ``invalidate(pattern)`` maps to ``SCAN``
    + ``DEL`` (avoid ``KEYS`` in production).
  * Serialize values (JSON/pickle) on the way in/out — Redis stores bytes, not live
    Python objects.
"""

from __future__ import annotations

from typing import Any, Optional

from .backend import CacheBackend


class RedisCache(CacheBackend):
    """Placeholder. Construct only once implemented; every method raises for now."""

    def __init__(self, *args, **kwargs):  # noqa: D401
        raise NotImplementedError(
            "RedisCache is a reserved slot and is not implemented in v1. "
            "Use LocalCache (the default). See this module's docstring for the build plan."
        )

    def get(self, key: str, default: Any = None) -> Any:  # pragma: no cover
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:  # pragma: no cover
        raise NotImplementedError

    def delete(self, key: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def invalidate(self, pattern: Optional[str] = None) -> int:  # pragma: no cover
        raise NotImplementedError

    def clear(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def get_stats(self) -> dict:  # pragma: no cover
        raise NotImplementedError
