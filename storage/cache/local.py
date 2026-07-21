# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""LocalCache - the default in-process CacheBackend (TTL + bounded LRU).

This is the fast path for single-process bots: a plain in-memory store with per-key TTL,
LRU eviction (so it can never grow unbounded - fixing the unbounded dict the old
CollectionManager used), substring pattern invalidation, and hit/miss stats.

For the lower-level reusable primitive see ``storage_engine.helpers.lru_cache``.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Optional, Tuple

from .backend import CacheBackend

# Sentinel so a cached ``None`` value is distinguishable from "absent".
_MISSING = object()


class LocalCache(CacheBackend):
    """In-process TTL + LRU cache. Not shared across processes (use Redis for that)."""

    def __init__(self, max_size: int = 5000, default_ttl: int = 300):
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self.default_ttl = default_ttl
        # key -> (value, expiry_epoch | None)
        self._store: "OrderedDict[str, Tuple[Any, Optional[float]]]" = OrderedDict()
        self._hits = 0
        self._misses = 0

    # ── reads ────────────────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        entry = self._store.get(key, _MISSING)
        if entry is _MISSING:
            self._misses += 1
            return default
        value, expiry = entry
        if expiry is not None and time.time() > expiry:
            # expired
            self._store.pop(key, None)
            self._misses += 1
            return default
        self._hits += 1
        self._store.move_to_end(key)  # mark as recently used
        return value

    # ── writes ───────────────────────────────────────────────────────────────
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl = self.default_ttl if ttl is None else ttl
        expiry = (time.time() + ttl) if ttl and ttl > 0 else None
        if key in self._store:
            self._store.move_to_end(key)
        elif len(self._store) >= self.max_size:
            self._store.popitem(last=False)  # evict least-recently-used
        self._store[key] = (value, expiry)

    def delete(self, key: str) -> bool:
        return self._store.pop(key, _MISSING) is not _MISSING

    def invalidate(self, pattern: Optional[str] = None) -> int:
        if pattern is None:
            count = len(self._store)
            self._store.clear()
            return count
        keys = [k for k in self._store if pattern in k]
        for k in keys:
            self._store.pop(k, None)
        return len(keys)

    def clear(self) -> None:
        self._store.clear()
        self._hits = 0
        self._misses = 0

    # ── introspection ──────────────────────────────────────────────────────────
    def __contains__(self, key: str) -> bool:
        return self.get(key, _MISSING) is not _MISSING

    def __len__(self) -> int:
        return len(self._store)

    def get_stats(self) -> dict:
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total else 0.0
        return {
            "backend": "local",
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._store),
            "max_size": self.max_size,
            "hit_rate": round(hit_rate, 2),
        }
