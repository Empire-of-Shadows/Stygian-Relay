# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""InteractionStateStore — map a Discord message to its feature context.

A single polymorphic collection replaces the per-feature ``message_id → context`` maps that
recur across the bots. Each record is::

    {message_id, guild_id, feature, context: {...}, created_at, expires_at}

* ``record`` upserts the mapping (optionally with a TTL).
* ``get_context`` is the hot path — button handlers call it on every click, so it reads
  hit-first through the manager's shared cache.
* ``iter_active`` lets a cog re-register persistent views on startup (``bot.add_view``).

Expiry is delegated to a **TTL index on ``expires_at``** that the bot declares on the
collection (see ``interaction_state_reference.py``); MongoDB reaps stale rows, replacing the
per-feature cleanup tasks (e.g. TheCodex ``cleanup_old_mappings``). ``guild_id`` and
``message_id`` are normalized to ``str``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger

logger = get_logger("InteractionStateStore")


class InteractionStateStore:
    """Persistent ``message_id → {feature, context}`` store with hit-first reads.

    Args:
        manager: the ``CollectionManager`` for the interaction-state collection (unique
            index on ``message_id``, TTL index on ``expires_at``).
        default_ttl: seconds until a recorded mapping expires when ``record`` is called
            without an explicit ``ttl``. ``None`` means no expiry (persistent views).
        cache_ttl: per-read cache duration override (seconds); ``None`` uses the manager's
            default.
    """

    def __init__(
        self,
        manager: CollectionManager,
        *,
        default_ttl: Optional[int] = None,
        cache_ttl: Optional[int] = None,
    ):
        self._mgr = manager
        self._default_ttl = default_ttl
        self._cache_ttl = cache_ttl

    @staticmethod
    def _mid(message_id: Any) -> str:
        return str(message_id)

    @staticmethod
    def _cache_key(mid: str) -> str:
        return f"msg:{mid}"

    async def record(
        self,
        message_id: Any,
        guild_id: Any,
        feature: str,
        context: Dict[str, Any],
        ttl: Optional[int] = ...,  # sentinel: ... means "use default_ttl"
    ) -> bool:
        """Upsert a message→context mapping. ``ttl`` (seconds) overrides ``default_ttl``;
        pass ``ttl=None`` to make this mapping never expire (persistent view)."""
        mid = self._mid(message_id)
        effective_ttl = self._default_ttl if ttl is ... else ttl
        now = datetime.now(tz=timezone.utc)
        expires_at = now + timedelta(seconds=effective_ttl) if effective_ttl else None

        update = {
            "$set": {
                "guild_id": str(guild_id),
                "feature": feature,
                "context": context,
                "expires_at": expires_at,
            },
            "$setOnInsert": {"message_id": mid, "created_at": now},
        }
        try:
            return await self._mgr.update_one({"message_id": mid}, update, upsert=True)
        except Exception as e:
            logger.error(f"record failed for message {mid}: {e}", exc_info=True)
            return False

    async def get_record(self, message_id: Any, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Return the full stored record (or ``None``), hit-first cached by message id."""
        mid = self._mid(message_id)
        cache_key = self._cache_key(mid) if use_cache else None
        return await self._mgr.find_one(
            {"message_id": mid}, cache_key=cache_key, cache_duration=self._cache_ttl
        )

    async def get_context(self, message_id: Any, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """Hot path: return just the ``context`` dict for a message (or ``None``)."""
        record = await self.get_record(message_id, use_cache=use_cache)
        return record.get("context") if record else None

    async def find_by_feature(self, feature: str, guild_id: Any = None) -> List[Dict[str, Any]]:
        """All active records for a feature, optionally scoped to one guild."""
        query: Dict[str, Any] = {"feature": feature}
        if guild_id is not None:
            query["guild_id"] = str(guild_id)
        return await self._mgr.find_many(query)

    async def iter_active(self, feature: str, guild_id: Any = None) -> AsyncIterator[Dict[str, Any]]:
        """Yield active records for a feature — use at startup to re-register persistent
        views (``bot.add_view``) so their buttons keep working after a restart."""
        for record in await self.find_by_feature(feature, guild_id):
            yield record

    async def delete(self, message_id: Any) -> bool:
        """Remove a mapping (e.g. when its message is deleted or its view is dismissed)."""
        mid = self._mid(message_id)
        try:
            return await self._mgr.delete_one({"message_id": mid})
        except Exception as e:
            logger.error(f"delete failed for message {mid}: {e}", exc_info=True)
            return False

    def invalidate(self, message_id: Any) -> None:
        """Drop one message's cached record."""
        self._mgr._invalidate_cache(self._cache_key(self._mid(message_id)))
