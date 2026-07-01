# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""LRU Cache primitives — preventing memory leaks in large deployments.

Lifted into the storage engine from EcomRebuild (where it backs the high-throughput
voice-session cache) so it is a single shared primitive across the ecosystem. These are
the low-level building blocks; the engine's CacheBackend implementation
(``storage_engine.cache.local.LocalCache``) is what the storage layer consumes.

Provides a Least Recently Used (LRU) cache with a size limit, plus a time-expiring
variant, both with hit/miss statistics.
"""

import logging
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger("lru_cache")


class LRUCache:
    """A simple LRU (Least Recently Used) cache with a maximum size limit.

    When the cache reaches max_size, the least recently used item is evicted to make
    room for new items.
    """

    def __init__(self, max_size: int = 1000):
        if max_size <= 0:
            raise ValueError("max_size must be positive")

        self.max_size = max_size
        self._cache: "OrderedDict[str, Any]" = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key: str, default: Any = None) -> Any:
        """Get an item from cache, recording a hit/miss."""
        if key in self._cache:
            self._hits += 1
            # Move to end (mark as recently used)
            self._cache.move_to_end(key)
            return self._cache[key]

        self._misses += 1
        return default

    def set(self, key: str, value: Any) -> None:
        """Set an item in cache, evicting the LRU item if at capacity."""
        if key in self._cache:
            # Update existing key and move to end
            self._cache.move_to_end(key)
        elif len(self._cache) >= self.max_size:
            # Evict least recently used item (first item)
            self._cache.popitem(last=False)

        self._cache[key] = value

    def delete(self, key: str) -> bool:
        """Delete an item from cache. Returns True if it existed."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all items and reset statistics."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def get_stats(self) -> dict:
        """Return hits, misses, size, max_size, and hit_rate (percent)."""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "size": len(self._cache),
            "max_size": self.max_size,
            "hit_rate": round(hit_rate, 2),
        }

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._hits = 0
        self._misses = 0


class TimedLRUCache(LRUCache):
    """LRU cache with time-based expiration on top of LRU eviction."""

    def __init__(self, max_size: int = 1000, timeout: int = 300):
        super().__init__(max_size)
        self.timeout = timeout
        self._timestamps: "OrderedDict[str, float]" = OrderedDict()

    def get(self, key: str, default: Any = None) -> Any:
        """Get an item from cache, treating expired entries as misses."""
        if key in self._cache:
            age = time.time() - self._timestamps[key]
            if age > self.timeout:
                logger.debug(
                    f"Cache entry expired: key={key}, age={age:.1f}s, timeout={self.timeout}s"
                )
                self.delete(key)
                self._misses += 1
                return default

            self._hits += 1
            self._cache.move_to_end(key)
            self._timestamps.move_to_end(key)
            return self._cache[key]

        self._misses += 1
        return default

    def set(self, key: str, value: Any) -> None:
        """Set an item with the current timestamp, evicting the LRU item if full."""
        if key in self._cache:
            self._cache.move_to_end(key)
            self._timestamps.move_to_end(key)
            self._timestamps[key] = time.time()
        elif len(self._cache) >= self.max_size:
            evicted_key = next(iter(self._cache))
            self._cache.popitem(last=False)
            self._timestamps.pop(evicted_key, None)

        self._cache[key] = value
        self._timestamps[key] = time.time()

    def delete(self, key: str) -> bool:
        if super().delete(key):
            self._timestamps.pop(key, None)
            return True
        return False

    def clear(self) -> None:
        super().clear()
        self._timestamps.clear()
