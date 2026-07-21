# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""BatchWriter — coalesce high-frequency writes into batched ``bulk_write`` flushes.

Promoted from EcomRebuild ``ecom_system/helpers/batch_writer.py``. Differences from the
original (which keyed by ``id(collection)`` over raw motor collections):

* Pending writes are keyed by **(collection registry key, filter)**, so the buffer is
  decoupled from collection objects and survives reconnects.
* Flushes route through the engine's ``CollectionManager.bulk_write`` (via a resolver the
  ``DatabaseManagerBase`` supplies), inheriting its retry, ``updated_at`` stamping, and
  cache invalidation — no separate motor path.

Merging semantics (unchanged): multiple updates to the same ``(collection, filter)`` are
merged before flush — ``$inc`` values are summed, ``$set`` values last-write-wins,
``$push`` arrays concatenated.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from pymongo import UpdateOne

from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger

logger = get_logger("BatchWriter")


@dataclass
class _PendingWrite:
    """A buffered upsert against one collection registry key."""

    collection_key: str
    filter_doc: Dict[str, Any]
    update_doc: Dict[str, Any]
    created_at: float = field(default_factory=time.time)

    def key(self) -> str:
        # Same document (same collection + filter) merges into one pending write.
        return f"{self.collection_key}:{sorted(self.filter_doc.items())}"


class BatchWriter:
    """Buffers and merges document writes, flushing on size or interval.

    Args:
        collection_resolver: ``(collection_key) -> CollectionManager``. In a
            ``DatabaseManagerBase`` this is ``db_manager.get_collection_manager``.
        max_batch_size: pending-write count that triggers an immediate flush.
        flush_interval: background auto-flush cadence, in seconds.
        max_queue_size: hard cap on pending writes; ``queue_update`` returns ``False`` when
            full so the caller can fall back to a direct write.
    """

    def __init__(
        self,
        collection_resolver: Callable[[str], CollectionManager],
        *,
        max_batch_size: int = 50,
        flush_interval: float = 1.0,
        max_queue_size: int = 1000,
    ):
        self._resolve = collection_resolver
        self.max_batch_size = max_batch_size
        self.flush_interval = flush_interval
        self.max_queue_size = max_queue_size

        self.pending_writes: Dict[str, _PendingWrite] = {}
        self.stats = {
            "total_queued": 0,
            "total_flushed": 0,
            "total_merged": 0,
            "total_errors": 0,
            "flush_count": 0,
            "currently_pending": 0,
        }
        self._flushing = False
        self._flush_task: Optional[asyncio.Task] = None
        # Serialize flush() so a threshold-triggered flush and the auto-loop can't
        # both clear pending_writes at once.
        self._flush_lock = asyncio.Lock()
        # Strong refs to threshold-triggered flush tasks so they aren't GC'd mid-flight.
        self._inflight: set = set()

    # ── enqueue ──────────────────────────────────────────────────────────────

    def queue_update(
        self, collection_key: str, filter_doc: Dict[str, Any], update_doc: Dict[str, Any]
    ) -> bool:
        """Queue an upsert, merging into any pending write for the same document.

        Returns ``False`` (without queuing) when the buffer is full, so the caller can
        write directly and retry buffering later."""
        if len(self.pending_writes) >= self.max_queue_size:
            logger.warning(f"Batch write queue full ({self.max_queue_size}); rejecting (caller should write directly)")
            return False

        write = _PendingWrite(collection_key, filter_doc, update_doc)
        key = write.key()

        existing = self.pending_writes.get(key)
        if existing is not None:
            existing.update_doc = self._merge_updates(existing.update_doc, update_doc)
            self.stats["total_merged"] += 1
        else:
            self.pending_writes[key] = write
            self.stats["total_queued"] += 1

        self.stats["currently_pending"] = len(self.pending_writes)

        if len(self.pending_writes) >= self.max_batch_size:
            # Keep a strong reference so the task isn't garbage-collected mid-flush;
            # flush() itself is serialized by _flush_lock against the auto-loop.
            task = asyncio.create_task(self.flush())
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)
        return True

    @staticmethod
    def _push_elements(value: Any) -> list:
        """Normalize a ``$push`` field value to the list of elements it pushes.

        MongoDB semantics: ``{"$push": {f: X}}`` pushes X as ONE element, while
        ``{"$push": {f: {"$each": [...]}}}`` pushes each element of the list. A bare
        list is a single element, NOT spread."""
        if isinstance(value, dict) and "$each" in value:
            return list(value["$each"])
        return [value]

    @classmethod
    def _merge_updates(cls, existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """Combine two update documents operator-by-operator (``$inc`` sums, ``$set``
        last-wins, ``$push`` concatenates via ``$each``)."""
        merged = {op: dict(fields) for op, fields in existing.items()}
        for operator, fields in new.items():
            bucket = merged.setdefault(operator, {})
            if operator == "$inc":
                for f, v in fields.items():
                    bucket[f] = bucket.get(f, 0) + v
            elif operator == "$push":
                # Normalize both sides to $each element lists and concatenate, so
                # two buffered pushes to the same field don't overwrite each other
                # (the old code dropped the earlier $each) and a bare list isn't
                # wrongly spread.
                for f, v in fields.items():
                    prev = cls._push_elements(bucket[f]) if f in bucket else []
                    bucket[f] = {"$each": prev + cls._push_elements(v)}
            else:  # $set and any other operator: later value wins
                bucket.update(fields)
        return merged

    # ── flush ────────────────────────────────────────────────────────────────

    async def flush(self) -> int:
        """Write all pending operations, grouped into one ``bulk_write`` per collection."""
        # Serialize concurrent flushes (auto-loop vs threshold-triggered task) so
        # they can't both snapshot-and-clear pending_writes and double-write.
        async with self._flush_lock:
            return await self._flush_locked()

    async def _flush_locked(self) -> int:
        if not self.pending_writes:
            return 0

        writes_to_flush = list(self.pending_writes.values())
        self.pending_writes.clear()
        self.stats["currently_pending"] = 0

        by_collection: Dict[str, List[_PendingWrite]] = defaultdict(list)
        for write in writes_to_flush:
            by_collection[write.collection_key].append(write)

        flushed = 0
        errors = 0
        for collection_key, writes in by_collection.items():
            ops = [UpdateOne(w.filter_doc, w.update_doc, upsert=True) for w in writes]
            try:
                manager = self._resolve(collection_key)
                await manager.bulk_write(ops, ordered=False)
                flushed += len(ops)
            except Exception as e:
                errors += len(writes)
                # Failed writes are dropped (not re-queued) to avoid an infinite retry loop;
                # buffered data is non-critical counters by contract.
                logger.error(f"Batch flush error for {collection_key} ({len(writes)} ops): {e}", exc_info=True)

        self.stats["total_flushed"] += flushed
        self.stats["total_errors"] += errors
        self.stats["flush_count"] += 1
        if flushed:
            logger.debug(f"Batch flush complete: {flushed} writes, {errors} errors")
        return flushed

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background auto-flush loop (idempotent)."""
        if self._flushing:
            return
        # Set the flag synchronously (not inside the task): two start() calls in
        # quick succession would otherwise both see False before _loop scheduled
        # and spawn two loops, orphaning the first task.
        self._flushing = True

        async def _loop():
            logger.info(f"BatchWriter auto-flush started (interval={self.flush_interval}s, max_batch={self.max_batch_size})")
            while self._flushing:
                try:
                    await asyncio.sleep(self.flush_interval)
                    if self.pending_writes:
                        await self.flush()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"BatchWriter auto-flush error: {e}", exc_info=True)

        self._flush_task = asyncio.create_task(_loop())

    def stop(self) -> None:
        """Stop the background auto-flush loop (does not flush — use ``shutdown``)."""
        self._flushing = False
        if self._flush_task:
            self._flush_task.cancel()
            self._flush_task = None
        for task in list(self._inflight):
            task.cancel()
        self._inflight.clear()

    async def shutdown(self) -> None:
        """Stop the loop and flush everything still pending. Call before closing the DB."""
        self.stop()
        flushed = await self.flush()
        logger.info(f"BatchWriter shutdown complete, flushed {flushed} pending writes")

    def get_stats(self) -> Dict[str, Any]:
        """Return queue/merge/flush counters plus derived merge and error rates."""
        queued = self.stats["total_queued"]
        flushed = self.stats["total_flushed"]
        flushes = self.stats["flush_count"]
        return {
            **self.stats,
            "merge_rate": self.stats["total_merged"] / queued if queued else 0,
            "error_rate": self.stats["total_errors"] / flushed if flushed else 0,
            "avg_batch_size": flushed / flushes if flushes else 0,
        }
