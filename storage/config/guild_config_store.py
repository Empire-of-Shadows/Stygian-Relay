# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""GuildConfigStore - the shared, dict-level guild configuration store.

Generalized from EcomRebuild ``storage/config_manager.py``. This is the *engine* half:
it standardizes how a per-guild config document is read (hit-first), written (surgical
dotted ``$set`` / ``$unset`` / full-doc upsert), and invalidated. It deliberately knows
nothing about a bot's feature schema - the bot wraps it with its own ``GuildConfig``
dataclass for typed access (see ``docs/storage_engine/guild-config.md``).

Caching & coherency are delegated to the ``CollectionManager`` it is constructed with:
reads pass ``cache_key=f"guild:{gid}"`` so they share the manager's pluggable
``CacheBackend``; every write invalidates that collection's cache namespace, and the
engine's ``ChangeStreamWatcher`` invalidates on external writes when the collection is
listed in ``bindings.WATCHED_COLLECTIONS``. No second cache layer is introduced.

``guild_id`` is coerced to ``str`` at every boundary (the ecosystem-wide convention; run
``config.migration.normalize_guild_id_to_str`` once on bots that stored it as an int).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger

logger = get_logger("GuildConfigStore")

# Canonical panel-role keys (the shape admin_engine's bindings read). Kept here so every
# bot resolves admin/mod roles the same way regardless of its feature schema.
_ADMIN_ROLES_PATH = "roles.admin_role_ids"
_MOD_ROLES_PATH = "roles.mod_role_ids"


class GuildConfigStore:
    """Dict-level guild config CRUD over one ``CollectionManager`` (hit-first cached).

    Args:
        manager: the ``CollectionManager`` for the guild-config collection (one doc per
            guild, unique index on ``id_field``).
        id_field: the document field that holds the guild id. Default ``"guild_id"``.
        default_factory: optional ``(guild_id: str) -> dict`` returning a complete default
            document, so ``get_settings`` never returns ``None`` for an unconfigured guild.
            If omitted, ``get_settings`` returns ``{}`` on a miss.
        cache_ttl: optional per-read cache duration (seconds) override; ``None`` uses the
            manager's default.
    """

    def __init__(
        self,
        manager: CollectionManager,
        *,
        id_field: str = "guild_id",
        default_factory: Optional[Callable[[str], Dict[str, Any]]] = None,
        cache_ttl: Optional[int] = None,
    ):
        self._mgr = manager
        self._id_field = id_field
        self._default_factory = default_factory
        self._ttl = cache_ttl

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _gid(guild_id: Any) -> str:
        """Normalize any guild id to the canonical ``str`` form."""
        return str(guild_id)

    @staticmethod
    def _cache_key(gid: str) -> str:
        return f"guild:{gid}"

    @staticmethod
    def _dig(doc: Dict[str, Any], path: str, default: Any = None) -> Any:
        """Read a dotted path (``"roles.admin_role_ids"``) out of a plain dict."""
        cur: Any = doc
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_doc(self, guild_id: Any, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Return the raw stored document (or ``None``), shared through the manager's
        hit-first cache. Use where callers already handle a missing doc."""
        gid = self._gid(guild_id)
        cache_key = self._cache_key(gid) if use_cache else None
        return await self._mgr.find_one(
            {self._id_field: gid}, cache_key=cache_key, cache_duration=self._ttl
        )

    async def get_settings(self, guild_id: Any, use_cache: bool = True) -> Dict[str, Any]:
        """Return a complete settings dict (never ``None``). Falls back to
        ``default_factory(guild_id)`` (or ``{}``) when the guild has no document yet."""
        gid = self._gid(guild_id)
        doc = await self.get_doc(gid, use_cache=use_cache)
        if doc:
            return doc
        return self._default_factory(gid) if self._default_factory else {}

    async def get_setting(self, path: str, guild_id: Any, default: Any = None) -> Any:
        """Read a single setting by dotted ``path`` (e.g. ``"message.base_xp"``).

        A flat top-level key is honored FIRST (EcomRebuild convention: some legacy
        docs store a literal dotted key at the top level), then the dotted path is
        traversed into the nested doc. Returns ``default`` if neither resolves.
        """
        settings = await self.get_settings(guild_id)
        if path in settings:
            return settings[path]
        return self._dig(settings, path, default)

    async def find_many(self, filter_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Pass-through for multi-doc queries (e.g. all active guilds). Not cached."""
        return await self._mgr.find_many(filter_dict)

    # ── writes (all invalidate the collection's cache namespace via the manager) ─

    async def update(self, guild_id: Any, updates: Dict[str, Any], upsert: bool = True) -> bool:
        """Apply a surgical ``$set`` (dotted keys allowed). ``updated_at`` is stamped by
        the ``CollectionManager``."""
        gid = self._gid(guild_id)
        try:
            return await self._mgr.update_one(
                {self._id_field: gid}, {"$set": updates}, upsert=upsert
            )
        except Exception as e:
            logger.error(f"update failed for guild {gid}: {e}", exc_info=True)
            return False

    async def set_setting(self, path: str, value: Any, guild_id: Any) -> bool:
        """Write a single setting by dotted ``path`` (MongoDB ``$set`` handles dots)."""
        return await self.update(guild_id, {path: value})

    async def set_many(self, settings: Dict[str, Any], guild_id: Any) -> bool:
        """Write several dotted-path settings in one ``$set``."""
        if not settings:
            return False
        return await self.update(guild_id, dict(settings))

    async def unset(self, guild_id: Any, keys: List[str]) -> bool:
        """Remove fields via ``$unset`` (dotted keys allowed)."""
        gid = self._gid(guild_id)
        if not keys:
            return False
        try:
            return await self._mgr.update_one(
                {self._id_field: gid}, {"$unset": {k: "" for k in keys}}, upsert=False
            )
        except Exception as e:
            logger.error(f"unset failed for guild {gid}: {e}", exc_info=True)
            return False

    async def apply(
        self,
        guild_id: Any,
        sets: Optional[Dict[str, Any]] = None,
        unsets: Optional[List[str]] = None,
        upsert: bool = False,
    ) -> bool:
        """Apply a surgical ``$set`` plus ``$unset`` in ONE atomic ``update_one``.

        Built for typed config layers that diff a load-time snapshot against the edited
        state (the BUG-C1 pattern): the changed leaves land as dotted ``$set`` and the
        removed leaves as ``$unset`` in a single operation, so no concurrent write can
        slip between the two halves and the save stays surgical. ``updated_at`` is
        stamped by the ``CollectionManager``. Returns True when there is nothing to
        write (an empty diff is a successful no-op, not an error)."""
        gid = self._gid(guild_id)
        update: Dict[str, Any] = {}
        if sets:
            update["$set"] = dict(sets)
        if unsets:
            update["$unset"] = {k: "" for k in unsets}
        if not update:
            return True
        try:
            return await self._mgr.update_one({self._id_field: gid}, update, upsert=upsert)
        except Exception as e:
            logger.error(f"apply failed for guild {gid}: {e}", exc_info=True)
            return False

    async def save_doc(self, guild_id: Any, doc: Dict[str, Any]) -> bool:
        """Full-document upsert. The ``id_field`` and managed timestamps are handled for
        you (``created_at`` / ``updated_at`` are dropped so the manager owns them)."""
        gid = self._gid(guild_id)
        payload = {k: v for k, v in doc.items() if k not in ("created_at", "updated_at")}
        payload[self._id_field] = gid
        try:
            return await self._mgr.update_one(
                {self._id_field: gid}, {"$set": payload}, upsert=True
            )
        except Exception as e:
            logger.error(f"save_doc failed for guild {gid}: {e}", exc_info=True)
            return False

    async def delete(self, guild_id: Any) -> bool:
        """Delete a guild's config document."""
        gid = self._gid(guild_id)
        try:
            return await self._mgr.delete_one({self._id_field: gid})
        except Exception as e:
            logger.error(f"delete failed for guild {gid}: {e}", exc_info=True)
            return False

    # ── canonical panel roles (admin_engine contract shape) ──────────────────

    @staticmethod
    def _normalize_roles(doc: Dict[str, Any], path: str) -> List[int]:
        """Fold ``roles.{admin,mod}_role_ids`` into an int list."""
        ids = GuildConfigStore._dig(doc, path)
        return [int(r) for r in (ids or [])]

    async def get_admin_role_ids(self, guild_id: Any) -> List[int]:
        """Resolve the guild's admin panel-role ids (canonical shape)."""
        return self._normalize_roles(await self.get_settings(guild_id), _ADMIN_ROLES_PATH)

    async def get_mod_role_ids(self, guild_id: Any) -> List[int]:
        """Resolve the guild's mod panel-role ids (canonical shape)."""
        return self._normalize_roles(await self.get_settings(guild_id), _MOD_ROLES_PATH)

    async def add_role(self, guild_id: Any, kind: str, role_id: int) -> bool:
        """Add a role id to the ``admin`` or ``mod`` canonical list (idempotent).

        Atomic ``$addToSet`` instead of read-modify-write, so two concurrent adds
        can't read the same list and clobber each other (lost update). Role ids are
        stored in the canonical STRING form (readers coerce as needed)."""
        path = _ADMIN_ROLES_PATH if kind == "admin" else _MOD_ROLES_PATH
        gid = self._gid(guild_id)
        try:
            await self._mgr.update_one(
                {self._id_field: gid}, {"$addToSet": {path: str(role_id)}}, upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"add_role failed for guild {gid}: {e}", exc_info=True)
            return False

    async def remove_role(self, guild_id: Any, kind: str, role_id: int) -> bool:
        """Remove a role id from the ``admin`` or ``mod`` canonical list.

        Atomic ``$pull`` instead of read-modify-write. Pulls BOTH the string and int
        forms so a not-yet-normalized legacy element is still removable."""
        path = _ADMIN_ROLES_PATH if kind == "admin" else _MOD_ROLES_PATH
        gid = self._gid(guild_id)
        try:
            await self._mgr.update_one(
                {self._id_field: gid},
                {"$pull": {path: {"$in": [str(role_id), int(role_id)]}}},
                upsert=False,
            )
            return True
        except Exception as e:
            logger.error(f"remove_role failed for guild {gid}: {e}", exc_info=True)
            return False

    # ── cache control ────────────────────────────────────────────────────────

    def invalidate(self, guild_id: Any) -> None:
        """Drop one guild's cached document (e.g. after an out-of-band write)."""
        self._mgr._invalidate_cache(self._cache_key(self._gid(guild_id)))

    def clear(self) -> None:
        """Drop every cached document for this collection's namespace."""
        self._mgr._invalidate_cache()
