# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""UserPreferenceCache - cached per-user preference / opt-out lookup.

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
        keys: the known flag keys (e.g. per-game opt-out keys). Pass ``None`` for
            DYNAMIC keys: every key saved in the document's flag map is copied
            (EcomRebuild pattern - opt-out flags keyed by guild id).
        global_key: a flag INSIDE ``flags_field`` whose truth means "opted out of
            everything" (default ``"global"``); pass ``None`` to disable.
        global_field: a TOP-LEVEL document field whose truth means "opted out of
            everything" (e.g. EcomRebuild's ``opted_out_all``, a sibling of the
            per-guild ``opted_out_guilds`` map, not a key inside it). ``None`` to
            disable. Either/both of global_key and global_field may be set.
        max_size / ttl: bound and freshness (seconds) of the per-user cache.
    """

    # Reserved cache-map key holding the top-level global flag's value.
    _GLOBAL_FIELD_SLOT = "__global_field__"

    def __init__(
        self,
        manager: CollectionManager,
        *,
        id_field: str = "user_id",
        flags_field: str = "leaderboard",
        keys: Optional[Sequence[str]] = (),
        global_key: Optional[str] = "global",
        global_field: Optional[str] = None,
        max_size: int = 5000,
        ttl: int = 60,
    ):
        self._mgr = manager
        self._id_field = id_field
        self._flags_field = flags_field
        # keys=None => dynamic mode: copy every saved key (per-guild flag maps).
        self._keys = tuple(keys) if keys is not None else None
        self._global_key = global_key
        self._global_field = global_field
        self._cache = TimedLRUCache(max_size=max_size, timeout=ttl)

    def _empty(self) -> dict:
        flags = {k: False for k in self._keys} if self._keys is not None else {}
        if self._global_key:
            flags[self._global_key] = False
        if self._global_field:
            flags[self._GLOBAL_FIELD_SLOT] = False
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
        if self._global_field:
            flags[self._GLOBAL_FIELD_SLOT] = bool(doc.get(self._global_field))
        saved = doc.get(self._flags_field) or {}
        if isinstance(saved, Mapping):
            if self._keys is None:
                # Dynamic mode: mirror the whole saved map (bool-coerced).
                for key, val in saved.items():
                    flags[str(key)] = bool(val)
            else:
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
        """Capability: opt-out check. ``True`` if the user set ``key`` or either global flag."""
        flags = await self.get_flags(user_id)
        if self._global_key and flags.get(self._global_key):
            return True
        if self._global_field and flags.get(self._GLOBAL_FIELD_SLOT):
            return True
        return bool(flags.get(key, False))

    async def is_globally_opted_out(self, user_id: Any) -> bool:
        """``True`` if the user set either global opt-out (gates all data collection)."""
        flags = await self.get_flags(user_id)
        if self._global_key and flags.get(self._global_key):
            return True
        if self._global_field and flags.get(self._GLOBAL_FIELD_SLOT):
            return True
        return False

    def invalidate(self, user_id: Any) -> None:
        """Drop one user's cached flags (call after a preference mutation)."""
        self._cache.delete(str(user_id))

    def invalidate_all(self) -> None:
        """Drop every cached user's flags."""
        self._cache.clear()
