# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""CachedLoader - async read-through cache for semi-static content.

Wraps the shared ``TimedLRUCache`` (TTL + bounded LRU) so a caller can say "give me this
content; if it's not cached, load it and remember it." Built for read-heavy, write-rare
payloads (guides, question banks, embed templates) that are wasteful to refetch or rebuild
every request. On a write to the underlying content, call ``invalidate`` / ``invalidate_guild``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from ..helpers.lru_cache import TimedLRUCache
from ..logging_compat import get_logger

logger = get_logger("CachedLoader")

# Sentinel distinguishing "cached value is None" from "key absent". (The loader's None is
# treated as "do not cache" so transient misses aren't pinned.)
_MISS = object()


class CachedLoader:
    """Per-(guild,key) read-through content cache.

    Args:
        max_size: max entries before LRU eviction.
        ttl: seconds before an entry is considered stale.
    """

    def __init__(self, *, max_size: int = 512, ttl: int = 300):
        self._cache = TimedLRUCache(max_size=max_size, timeout=ttl)

    @staticmethod
    def _key(key: str, guild_id: Any = None) -> str:
        return f"{guild_id}:{key}" if guild_id is not None else str(key)

    async def get(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        *,
        guild_id: Any = None,
    ) -> Any:
        """Return the cached value for ``(guild_id, key)``; on a miss, ``await loader()``,
        cache a non-``None`` result, and return it. ``loader`` is only called on a miss."""
        ck = self._key(key, guild_id)
        cached = self._cache.get(ck, _MISS)
        if cached is not _MISS:
            return cached
        value = await loader()
        if value is not None:
            self._cache.set(ck, value)
        return value

    def set(self, key: str, value: Any, *, guild_id: Any = None) -> None:
        """Prime the cache directly (e.g. right after writing new content)."""
        self._cache.set(self._key(key, guild_id), value)

    def invalidate(self, key: str, *, guild_id: Any = None) -> bool:
        """Drop one cached entry. Returns whether it existed."""
        return self._cache.delete(self._key(key, guild_id))

    def invalidate_guild(self, guild_id: Any) -> int:
        """Drop every cached entry for one guild. Returns the count removed."""
        prefix = f"{guild_id}:"
        # Both objects are engine-internal; iterate the underlying ordered store once.
        keys = [k for k in list(self._cache._cache.keys()) if k.startswith(prefix)]
        for k in keys:
            self._cache.delete(k)
        return len(keys)

    def clear(self) -> None:
        """Drop everything."""
        self._cache.clear()

    def get_stats(self) -> dict:
        """Hits / misses / size / hit_rate of the underlying cache."""
        return self._cache.get_stats()
