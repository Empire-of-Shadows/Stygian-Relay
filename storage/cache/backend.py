# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""CacheBackend — the one interface every cache backend implements.

The storage layer reads through a CacheBackend FIRST and only falls through to MongoDB
on a miss; writes call ``invalidate`` so the cache never serves stale data after a known
mutation. Real-time coherency for mutations made by OTHER processes is handled by
``ChangeStreamWatcher`` (see ``coherency.py``).

Methods are synchronous: the v1 backend (``LocalCache``) is in-process and effectively
free, so awaiting would only add overhead. A future async-I/O backend (Redis) can expose
an async variant or wrap a sync client; see ``redis_backend.py``.

Key convention used by the storage layer: ``"<collection>:<cache_key>"`` so that
``invalidate("<collection>:")`` drops exactly one collection's entries (substring match).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class CacheBackend(ABC):
    """Abstract cache backend. Backends are chosen per-bot via ``bindings.CACHE_BACKEND``."""

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Return the cached value for ``key``, or ``default`` if missing/expired."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Cache ``value`` under ``key``. ``ttl`` (seconds) overrides the backend default;
        ``None`` uses the backend default."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Drop a single ``key``. Returns whether it existed."""

    @abstractmethod
    def invalidate(self, pattern: Optional[str] = None) -> int:
        """Drop entries whose key contains ``pattern`` (substring match). ``None`` drops
        everything. Returns the number of entries removed."""

    @abstractmethod
    def clear(self) -> None:
        """Drop everything and reset statistics."""

    @abstractmethod
    def get_stats(self) -> dict:
        """Return backend statistics (hits, misses, size, hit_rate, …)."""
