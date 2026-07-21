# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""SnapshotStore — generic, discord-free engine for object snapshots.

Promoted from TheCodex's bot-local ``GuildCacheManager`` (``storage/cache.py``), with all
discord.py coupling stripped out: this layer only ever sees plain dicts. It owns the parts
that are the same for any "snapshot a graph of related objects into Mongo" job —

* per-partition ``asyncio.Lock`` so concurrent refreshes of the same partition serialize,
* a freshness gate driven by the root doc's ``updated_at`` (a real ``datetime`` stamped by
  ``CollectionManager`` — this is the structural fix for the legacy freshness bug, which
  read an ``updated_at`` string the old writer never wrote),
* bulk upserts routed through ``CollectionManager.bulk_write`` (inheriting retry,
  ``updated_at`` stamping and cache invalidation), with optional chunking,
* cascade delete across every spec for one partition, and
* thin read/aggregate/cleanup helpers.

The discord-aware extraction lives in the opt-in ``storage_engine.discord`` layer; this
module imports no discord.py and is safe to vendor everywhere.

Like ``BatchWriter``, it is constructed with a ``collection_resolver`` (i.e.
``db_manager.get_collection_manager``) rather than raw managers, so it survives reconnects.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from pymongo import UpdateOne

from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger
from .spec import SnapshotSpec

logger = get_logger("SnapshotStore")


class SnapshotStore:
    """Stores snapshots of related objects, driven by a list of :class:`SnapshotSpec`.

    Args:
        collection_resolver: ``(collection_key) -> CollectionManager``. In a
            ``DatabaseManagerBase`` this is ``db_manager.get_collection_manager``.
        specs: the object types this store manages. Exactly one should be ``is_root``.
        freshness_ttl: seconds; a partition is "fresh" if its root doc's ``updated_at`` is
            newer than this. Used by :meth:`snapshot` to skip redundant refreshes.
        now_provider: injectable clock returning an aware UTC ``datetime`` (for tests).
    """

    def __init__(
        self,
        collection_resolver: Callable[[str], CollectionManager],
        specs: Sequence[SnapshotSpec],
        *,
        freshness_ttl: float = 3600.0,
        now_provider: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._resolve = collection_resolver
        self._freshness_ttl = freshness_ttl
        self._now = now_provider
        self._specs: Dict[str, SnapshotSpec] = {}
        self._root: Optional[SnapshotSpec] = None
        self._locks: Dict[Any, asyncio.Lock] = {}
        for spec in specs:
            self.add_spec(spec)

    # ── registry ─────────────────────────────────────────────────────────────

    def add_spec(self, spec: SnapshotSpec) -> None:
        """Register (or replace) a spec. The growth path for new object types."""
        self._specs[spec.object_type] = spec
        if spec.is_root:
            self._root = spec

    def _spec(self, object_type: str) -> SnapshotSpec:
        try:
            return self._specs[object_type]
        except KeyError:
            raise KeyError(f"No snapshot spec registered for object_type {object_type!r}")

    def _manager(self, object_type: str) -> CollectionManager:
        return self._resolve(self._spec(object_type).collection_key)

    @staticmethod
    def _filter(spec: SnapshotSpec, record: Dict[str, Any]) -> Dict[str, Any]:
        """Build the upsert/identity filter for one record from its identity fields."""
        return {f: record[f] for f in spec.identity_fields}

    def _lock(self, partition_id: Any) -> asyncio.Lock:
        lock = self._locks.get(partition_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[partition_id] = lock
        return lock

    # ── writes ───────────────────────────────────────────────────────────────

    async def upsert_one(self, object_type: str, record: Dict[str, Any]) -> bool:
        """Upsert a single record, keyed by the spec's identity fields."""
        spec = self._spec(object_type)
        return await self._manager(object_type).update_one(
            self._filter(spec, record), {"$set": record}, upsert=True
        )

    async def upsert_many(self, object_type: str, records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Bulk-upsert records, chunked by ``spec.chunk_size``. Returns aggregated counts."""
        spec = self._spec(object_type)
        if not records:
            return {"upserted_count": 0, "modified_count": 0}

        manager = self._manager(object_type)
        totals: Dict[str, int] = {}
        chunk = spec.chunk_size or len(records)
        for start in range(0, len(records), chunk):
            ops = [
                UpdateOne(self._filter(spec, r), {"$set": r}, upsert=True)
                for r in records[start:start + chunk]
            ]
            result = await manager.bulk_write(ops, ordered=False)
            for key, value in result.items():
                if isinstance(value, int):
                    totals[key] = totals.get(key, 0) + value
        return totals

    # ── freshness + orchestration ────────────────────────────────────────────

    async def is_fresh(self, partition_id: Any) -> bool:
        """True if the root doc for ``partition_id`` was written within ``freshness_ttl``.

        Missing root spec, missing doc, or a non-datetime ``updated_at`` (e.g. legacy string
        data) all return ``False`` so the caller refreshes — never a stale True.
        """
        if self._root is None:
            return False
        doc = await self._manager(self._root.object_type).find_one(
            {self._root.partition_field: partition_id}, projection={"updated_at": 1}
        )
        updated_at = doc.get("updated_at") if doc else None
        if not isinstance(updated_at, datetime):
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return (self._now() - updated_at).total_seconds() < self._freshness_ttl

    async def snapshot(
        self,
        partition_id: Any,
        *,
        payloads: Optional[Dict[str, Any]] = None,
        builder: Optional[Callable[[], Any]] = None,
        force: bool = False,
    ) -> bool:
        """Refresh every object type for one partition, under its lock.

        Provide either ready ``payloads`` (``{object_type: record | [records]}``) or an async
        ``builder`` that produces them; the builder runs INSIDE the lock and only when a write
        is actually needed. Returns ``False`` (no writes) when the partition is fresh and not
        forced, else ``True``. Records that are lists route to ``upsert_many``, dicts to
        ``upsert_one``. Individual type failures are captured and logged (parity with the
        legacy ``asyncio.gather(..., return_exceptions=True)``), so one bad type never aborts
        the rest.
        """
        async with self._lock(partition_id):
            if not force and await self.is_fresh(partition_id):
                return False
            if payloads is None:
                if builder is None:
                    raise ValueError("snapshot() requires either payloads or builder")
                payloads = await builder()

            coros = []
            types: List[str] = []
            for object_type, data in payloads.items():
                types.append(object_type)
                if isinstance(data, list):
                    coros.append(self.upsert_many(object_type, data))
                else:
                    coros.append(self.upsert_one(object_type, data))

            results = await asyncio.gather(*coros, return_exceptions=True)
            for object_type, result in zip(types, results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Snapshot of {object_type!r} for partition {partition_id} failed: {result}"
                    )
            return True

    # ── deletes ──────────────────────────────────────────────────────────────

    async def delete_partition(self, partition_id: Any) -> Dict[str, int]:
        """Cascade-delete every spec's rows for one partition. Returns per-type delete counts."""
        async with self._lock(partition_id):
            types = list(self._specs)
            coros = [
                self._manager(t).delete_many({self._specs[t].partition_field: partition_id})
                for t in types
            ]
            results = await asyncio.gather(*coros, return_exceptions=True)
            counts: Dict[str, int] = {}
            for object_type, result in zip(types, results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Delete of {object_type!r} for partition {partition_id} failed: {result}"
                    )
                    counts[object_type] = 0
                else:
                    counts[object_type] = result
            # Do NOT pop the lock here: it is still held inside this ``async with``,
            # and another coroutine may already hold a reference to the same lock
            # object. Removing it now would let a later caller create a fresh lock
            # for the same partition and run concurrently (mutual exclusion lost).
            # The lock stays registered for reuse; call ``forget`` for teardown.
            return counts

    def forget(self, partition_id: Any) -> None:
        """Drop in-memory state (the per-partition lock) without touching the database."""
        self._locks.pop(partition_id, None)

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_one(
        self,
        object_type: str,
        filter_dict: Dict[str, Any],
        *,
        cache_key: str = None,
        cache_duration: int = None,
    ) -> Optional[Dict[str, Any]]:
        return await self._manager(object_type).find_one(
            filter_dict, cache_key=cache_key, cache_duration=cache_duration
        )

    async def get_many(
        self,
        object_type: str,
        filter_dict: Dict[str, Any],
        *,
        sort: List[tuple] = None,
        limit: int = None,
    ) -> List[Dict[str, Any]]:
        return await self._manager(object_type).find_many(filter_dict, sort=sort, limit=limit)

    async def count(self, object_type: str, filter_dict: Dict[str, Any]) -> int:
        return await self._manager(object_type).count_documents(filter_dict)

    async def aggregate(self, object_type: str, pipeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run an aggregation and return the result list (the manager already ``to_list``s it)."""
        return await self._manager(object_type).aggregate(pipeline)

    # ── maintenance ──────────────────────────────────────────────────────────

    async def cleanup_stale(self, max_age: timedelta) -> int:
        """Cascade-delete every partition whose root doc hasn't been written within ``max_age``.

        Compares the root's ``updated_at`` datetime against a datetime cutoff (the legacy code
        compared it against an ISO string, which no longer matches once ``updated_at`` is a real
        datetime). Returns the number of partitions deleted.
        """
        if self._root is None:
            return 0
        cutoff = self._now() - max_age
        partition_field = self._root.partition_field
        stale = await self._manager(self._root.object_type).find_many(
            {"updated_at": {"$lt": cutoff}}, projection={partition_field: 1}
        )
        deleted = 0
        for doc in stale:
            partition_id = doc.get(partition_field)
            if partition_id is None:
                continue
            await self.delete_partition(partition_id)
            deleted += 1
        return deleted
