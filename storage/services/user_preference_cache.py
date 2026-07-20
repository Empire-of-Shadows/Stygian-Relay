# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""UserPreferenceCache — cached per-user preference / opt-out lookup.

Capability: cached user-preference flags. Promoted from TheHost's ``user_privacy`` module: a
short-TTL, per-user cache of boolean flags (privacy / leaderboard opt-out) so hot write paths
(leaderboard increments, drops) don't hit Mongo on every event.

Genericized: the bot injects the collection key, the document field that holds the flag map
(``"leaderboard"`` for TheHost), the known flag keys, and an optional ``global`` key whose
truth gates everything. ``guild_id``/``user_id`` follow the engine's ``str`` convention is not
forced here (preferences are user-scoped); the id is used as given and cached by ``str(id)``.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from ..helpers.lru_cache import TimedLRUCache
from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger

logger = get_logger("UserPreferenceCache")


class UserPreferenceCache:
    """Cache of per-user boolean preference flags.

    Args:
        manager: the ``CollectionManager`` for the preferences collection.
        id_field: the document field identifying the user (default ``"user_id"``).
        flags_field: the document sub-dict holding the boolean flags (default ``"leaderboard"``).
        keys: the known flag keys (e.g. per-game opt-out keys).
        global_key: a flag whose truth means "opted out of everything" (default ``"global"``);
            pass ``None`` to disable the global short-circuit.
        max_size / ttl: bound and freshness (seconds) of the per-user cache.
    """

    def __init__(
        self,
        manager: CollectionManager,
        *,
        id_field: str = "user_id",
        flags_field: str = "leaderboard",
        keys: Sequence[str] = (),
        global_key: Optional[str] = "global",
        max_size: int = 5000,
        ttl: int = 60,
    ):
        self._mgr = manager
        self._id_field = id_field
        self._flags_field = flags_field
        self._keys = tuple(keys)
        self._global_key = global_key
        self._cache = TimedLRUCache(max_size=max_size, timeout=ttl)

    def _empty(self) -> dict:
        flags = {k: False for k in self._keys}
        if self._global_key:
            flags[self._global_key] = False
        return flags

    async def _load(self, user_id: Any) -> dict:
        flags = self._empty()
        try:
            doc = await self._mgr.find_one({self._id_field: user_id})
        except Exception as e:
            logger.error(f"Failed to load preferences for {user_id}: {e}", exc_info=True)
            return flags
        if not doc:
            return flags
        saved = doc.get(self._flags_field) or {}
        if isinstance(saved, Mapping):
            for key in flags:
                if key in saved:
                    flags[key] = bool(saved[key])
        return flags

    async def get_flags(self, user_id: Any) -> dict:
        """Capability: cached preference flags. Returns the user's flag map, served from cache
        when fresh (defaults to all-``False`` when no document or on error)."""
        ck = str(user_id)
        cached = self._cache.get(ck)
        if cached is not None:
            return cached
        flags = await self._load(user_id)
        self._cache.set(ck, flags)
        return flags

    async def is_opted_out(self, user_id: Any, key: str) -> bool:
        """Capability: opt-out check. ``True`` if the user set ``key`` or the global flag."""
        flags = await self.get_flags(user_id)
        if self._global_key and flags.get(self._global_key):
            return True
        return bool(flags.get(key, False))

    async def is_globally_opted_out(self, user_id: Any) -> bool:
        """``True`` if the user set the global opt-out (gates all data collection)."""
        if not self._global_key:
            return False
        return bool((await self.get_flags(user_id)).get(self._global_key))

    def invalidate(self, user_id: Any) -> None:
        """Drop one user's cached flags (call after a preference mutation)."""
        self._cache.delete(str(user_id))

    def invalidate_all(self) -> None:
        """Drop every cached user's flags."""
        self._cache.clear()
