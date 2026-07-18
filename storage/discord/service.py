# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""GuildSnapshotService — discord-facing facade over the generic snapshot core.

Wires the discord extractors to a :class:`~storage_engine.snapshots.store.SnapshotStore` +
:class:`~storage_engine.snapshots.event_log.SnapshotEventLog`, and re-exposes the exact method
names TheCodex's legacy ``GuildCacheManager`` had (``cache_all``, ``cache_members``, …) so call
sites migrate with a one-line repoint. Individual ``cache_*`` write methods do NOT lock or check
freshness (they are event-driven forced writes, matching legacy); only ``cache_all`` and
``delete_guild`` take the per-guild lock.

Adding a new object type later is ``register(object_type, SnapshotSpec, extractor)`` — no change
to the core.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ..logging_compat import get_logger
from ..snapshots.event_log import SnapshotEventLog
from ..snapshots.spec import SnapshotSpec
from ..snapshots.store import SnapshotStore
from . import extractors
from .config import GuildSnapshotConfig, build_specs

logger = get_logger("GuildSnapshotService")


class GuildSnapshotService:
    """Snapshot a ``discord.Guild`` graph into Mongo, with per-guild freshness + cascade delete.

    Args:
        db_manager: initialized DatabaseManager exposing ``get_collection_manager``.
        config: :class:`GuildSnapshotConfig` (timezone, permission sets, thresholds, keys).
    """

    def __init__(self, db_manager, *, config: Optional[GuildSnapshotConfig] = None):
        self._config = config or GuildSnapshotConfig()
        self._store = SnapshotStore(
            db_manager.get_collection_manager,
            build_specs(self._config.keys),
            freshness_ttl=self._config.freshness_ttl,
        )
        self._events = SnapshotEventLog(
            db_manager.get_collection_manager(self._config.keys["events"])
        )
        # object_type -> callable(guild, config) -> record | [records] (async or sync).
        self._extractors: Dict[str, Callable] = {
            "guild": extractors.extract_guild,
            "channels": extractors.extract_channels,
            "roles": extractors.extract_roles,
            "members": extractors.extract_members,
            "analytics": extractors.extract_analytics,
        }

    def register(
        self,
        object_type: str,
        spec: SnapshotSpec,
        extractor: Callable[..., Any],
    ) -> None:
        """Register a new object type: its storage spec + a ``(guild, config) -> record(s)``
        extractor. It is then included in ``cache_all`` snapshots and gets its own collection."""
        self._store.add_spec(spec)
        self._extractors[object_type] = extractor

    async def _extract(self, object_type: str, guild) -> Any:
        result = self._extractors[object_type](guild, self._config)
        if isinstance(result, Awaitable):
            result = await result
        return result

    # ── writes (legacy method names) ─────────────────────────────────────────

    async def cache_all(self, guild, force_refresh: bool = False) -> bool:
        """Snapshot every registered object type for ``guild`` under its lock (freshness-gated)."""
        async def builder() -> Dict[str, Any]:
            payloads: Dict[str, Any] = {}
            for object_type in self._extractors:
                payloads[object_type] = await self._extract(object_type, guild)
            return payloads

        return await self._store.snapshot(guild.id, builder=builder, force=force_refresh)

    async def cache_guild_info(self, guild) -> bool:
        return await self._store.upsert_one("guild", await self._extract("guild", guild))

    async def cache_channels(self, guild) -> Dict[str, Any]:
        return await self._store.upsert_many("channels", await self._extract("channels", guild))

    async def cache_roles(self, guild) -> Dict[str, Any]:
        return await self._store.upsert_many("roles", await self._extract("roles", guild))

    async def cache_members(self, guild) -> Dict[str, Any]:
        return await self._store.upsert_many("members", await self._extract("members", guild))

    async def cache_guild_analytics(self, guild) -> bool:
        """Best-effort (matches legacy: logs and swallows so it never aborts ``cache_all``)."""
        try:
            return await self._store.upsert_one("analytics", await self._extract("analytics", guild))
        except Exception as e:
            logger.error(f"Error caching guild analytics for {getattr(guild, 'id', '?')}: {e}")
            return False

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_cached_guild_info(self, guild_id: int) -> Optional[Dict[str, Any]]:
        return await self._store.get_one("guild", {"id": guild_id})

    async def get_cached_channels(self, guild_id: int, channel_type: str = None) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"guild_id": guild_id}
        if channel_type:
            query["type"] = channel_type
        return await self._store.get_many("channels", query, sort=[("position", 1)])

    async def get_cached_member(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        return await self._store.get_one("members", {"guild_id": guild_id, "id": user_id})

    async def get_guild_statistics(self, guild_id: int) -> Dict[str, Any]:
        """Counts + channel-type breakdown + the latest analytics doc (sorted by date desc)."""
        try:
            stats: Dict[str, Any] = {
                "total_channels": await self._store.count("channels", {"guild_id": guild_id}),
                "total_roles": await self._store.count("roles", {"guild_id": guild_id}),
                "total_members": await self._store.count("members", {"guild_id": guild_id}),
                "bot_members": await self._store.count("members", {"guild_id": guild_id, "bot": True}),
                "human_members": await self._store.count("members", {"guild_id": guild_id, "bot": False}),
                "suspicious_members": await self._store.count("members", {
                    "guild_id": guild_id,
                    "suspicious_indicators": {"$exists": True, "$not": {"$size": 0}},
                }),
            }
            channel_types = await self._store.aggregate("channels", [
                {"$match": {"guild_id": guild_id}},
                {"$group": {"_id": "$type", "count": {"$sum": 1}}},
            ])
            stats["channel_types"] = {ct["_id"]: ct["count"] for ct in channel_types}

            latest = await self._store.get_many(
                "analytics", {"guild_id": guild_id}, sort=[("date", -1)], limit=1
            )
            if latest:
                stats["latest_analytics"] = latest[0]
                stats["analytics_date"] = latest[0].get("date")
            return stats
        except Exception as e:
            logger.error(f"Error getting guild statistics for {guild_id}: {e}")
            return {}

    async def get_member_insights(self, guild_id: int) -> Dict[str, Any]:
        try:
            pipeline = [
                {"$match": {"guild_id": guild_id}},
                {"$group": {
                    "_id": None,
                    "total_members": {"$sum": 1},
                    "bot_count": {"$sum": {"$cond": ["$bot", 1, 0]}},
                    "avg_account_age": {"$avg": "$account_age_days"},
                    "new_accounts": {"$sum": {"$cond": [{"$lte": ["$account_age_days", 7]}, 1, 0]}},
                    "suspicious_count": {"$sum": {"$cond": [{"$gt": [{"$size": "$suspicious_indicators"}, 0]}, 1, 0]}},
                    "premium_members": {"$sum": {"$cond": ["$premium_since", 1, 0]}},
                }},
            ]
            result = await self._store.aggregate("members", pipeline)
            if result:
                insights = result[0]
                insights["human_count"] = insights["total_members"] - insights["bot_count"]
                return insights
            return {}
        except Exception as e:
            logger.error(f"Error getting member insights for {guild_id}: {e}")
            return {}

    # ── events ───────────────────────────────────────────────────────────────

    async def log_guild_event(self, guild_id: int, event_type: str, event_data: Dict[str, Any]) -> bool:
        return await self._events.log(guild_id, event_type, event_data)

    async def get_guild_activity_summary(self, guild_id: int, days: int = 7) -> Dict[str, Any]:
        summary = await self._events.activity_summary(guild_id, timedelta(days=days))
        if not summary:
            return {}
        return {
            "guild_id": guild_id,
            "period_days": days,
            "total_events": summary.get("total_events", 0),
            "event_breakdown": summary.get("event_breakdown", {}),
            "since": summary.get("since"),
        }

    # ── lifecycle / maintenance ──────────────────────────────────────────────

    async def delete_guild(self, guild_id: int) -> Dict[str, int]:
        """Cascade-delete all cached data for a guild and drop its in-memory state."""
        counts = await self._store.delete_partition(guild_id)
        self._events.forget(guild_id)
        logger.info(f"Deleted cached data for guild {guild_id}: {counts}")
        return counts

    def forget(self, guild_id: int) -> None:
        """Drop in-memory state for a departed guild WITHOUT deleting its stored snapshots."""
        self._store.forget(guild_id)
        self._events.forget(guild_id)

    async def cleanup_stale_data(self, max_age_hours: int = 168) -> int:
        """Cascade-delete guilds whose snapshot is older than ``max_age_hours`` (default 1 week).

        Event/analytics retention is best handled by TTL indexes on the collections rather than
        swept here (declare them in ``define_collections``)."""
        return await self._store.cleanup_stale(timedelta(hours=max_age_hours))


def create_guild_snapshot_service(
    db_manager, *, config: Optional[GuildSnapshotConfig] = None
) -> GuildSnapshotService:
    """Factory: build a :class:`GuildSnapshotService` from an initialized DatabaseManager."""
    return GuildSnapshotService(db_manager, config=config)
