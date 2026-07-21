# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""SnapshotEventLog - generic append-only event trail with an in-memory recency ring.

Promoted from the event-logging half of TheCodex's ``GuildCacheManager``. Discord-free:
partitions are identified by a plain id, events are ``(event_type, data)`` pairs. Each write
goes to Mongo (via ``CollectionManager.create_one``, which stamps ``created_at``/``updated_at``
datetimes) and is also kept in a bounded in-memory ``deque`` for cheap recency reads. Window
queries use the manager-stamped ``created_at`` datetime as a real range query (the legacy code
compared pendulum ISO strings, which is fragile).

Retention of the collection itself is a TTL index on ``created_at`` (declared in the bot's
``define_collections``), not this writer's job.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Deque, Dict, List

from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger

logger = get_logger("SnapshotEventLog")


class SnapshotEventLog:
    """Append events for a partition; keep the last ``memory_limit`` per partition in memory.

    Args:
        manager: ``CollectionManager`` for the events collection.
        partition_field: document field holding the partition id (e.g. ``"guild_id"``).
        memory_limit: per-partition in-memory ring size.
        now_provider: injectable aware-UTC clock (for tests).
    """

    def __init__(
        self,
        manager: CollectionManager,
        *,
        partition_field: str = "guild_id",
        memory_limit: int = 100,
        now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._mgr = manager
        self._partition_field = partition_field
        self._memory_limit = memory_limit
        self._now = now_provider
        self._recent: Dict[Any, Deque[Dict[str, Any]]] = {}

    async def log(self, partition_id: Any, event_type: str, data: Dict[str, Any]) -> bool:
        """Append one event. Best-effort - logs and returns ``False`` on error, never raises."""
        record = {
            self._partition_field: partition_id,
            "event_type": event_type,
            "data": data,
        }
        try:
            await self._mgr.create_one(dict(record))
        except Exception as e:
            logger.error(f"Failed to log event {event_type!r} for {partition_id}: {e}")
            return False
        ring = self._recent.get(partition_id)
        if ring is None:
            ring = deque(maxlen=self._memory_limit)
            self._recent[partition_id] = ring
        ring.append(record)
        return True

    def recent(self, partition_id: Any) -> List[Dict[str, Any]]:
        """The in-memory recent events for a partition (oldest first)."""
        return list(self._recent.get(partition_id, ()))

    async def activity_summary(self, partition_id: Any, window: timedelta) -> Dict[str, Any]:
        """Count events by type within ``window`` (a real ``created_at`` range query)."""
        cutoff = self._now() - window
        try:
            events = await self._mgr.find_many(
                {self._partition_field: partition_id, "created_at": {"$gte": cutoff}}
            )
        except Exception as e:
            logger.error(f"Failed to summarize activity for {partition_id}: {e}")
            return {}
        breakdown: Dict[str, int] = defaultdict(int)
        for event in events:
            breakdown[event.get("event_type", "unknown")] += 1
        return {
            self._partition_field: partition_id,
            "total_events": len(events),
            "event_breakdown": dict(breakdown),
            "since": cutoff,
        }

    def forget(self, partition_id: Any) -> None:
        """Drop the in-memory recency ring for a partition (does not touch the database)."""
        self._recent.pop(partition_id, None)
