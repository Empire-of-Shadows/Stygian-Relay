# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""Exactly-once delivery for retried calls.

The problem this solves: a provider grants the thing, the response is lost, the
caller times out and cannot tell "never happened" from "happened, reply lost".
Retrying risks granting twice; not retrying risks the caller compensating for
work that actually completed. Neither is acceptable when the caller took the
member's currency first.

The fix is a key that identifies the UNIT OF WORK rather than the attempt (a
shop inventory ``instance_id``, say). The server then:

  1. serializes calls sharing that key, so a retry that races the original waits
     instead of running beside it,
  2. remembers the answer, so the retry gets the ORIGINAL verdict replayed
     rather than doing the work again.

Serialization is an in-process ``asyncio.Lock`` because every IPC call for a bot
lands in that bot's single process - the entrypoint holds a ``SingletonLock``
precisely so a second one cannot exist. The remembered answers need to outlive a
restart, which is why the Mongo-backed store is the one to wire for anything
that moves currency; the in-memory store is the honest default for capabilities
where a double-run is merely wasteful.

Wiring a Mongo store is the seam's job: declare the collection with a TTL index
on ``expires_at`` in the bot's own collections registry, then return a
``MongoIdempotencyStore`` from ``build_idempotency_store()`` in
``ipc/settings/bindings.py``. This engine never creates collections or indexes.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from storage.log import get_logger

logger = get_logger("IPC")

DEFAULT_TTL_SECONDS = 24 * 3600


class IdempotencyStore(ABC):
    """Remembers the answer given for an idempotency key."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        """The stored response payload for ``key``, or None if this is new."""

    @abstractmethod
    async def put(self, key: str, payload: Dict[str, Any]) -> None:
        """Remember ``payload`` as the answer for ``key``."""


class MemoryIdempotencyStore(IdempotencyStore):
    """Process-local store. Forgets everything on restart, by definition."""

    def __init__(self, ttl: int = DEFAULT_TTL_SECONDS, max_entries: int = 10_000):
        self._ttl = int(ttl)
        self._max = int(max_entries)
        self._entries: Dict[str, tuple[float, Dict[str, Any]]] = {}

    def _prune(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._entries.items() if now - ts > self._ttl]
        for key in expired:
            self._entries.pop(key, None)
        # Hard bound as a backstop: drop oldest first if something goes wrong
        # with the TTL assumption. A lost memory is a re-run, never a corruption.
        while len(self._entries) > self._max:
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            self._entries.pop(oldest, None)

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        self._prune()
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, payload = entry
        if time.time() - stored_at > self._ttl:
            self._entries.pop(key, None)
            return None
        return payload

    async def put(self, key: str, payload: Dict[str, Any]) -> None:
        self._entries[key] = (time.time(), payload)
        self._prune()


class MongoIdempotencyStore(IdempotencyStore):
    """Durable store. Survives a restart, which is what currency needs.

    ``collection`` is a raw driver collection. The seam is responsible for
    declaring it with a TTL index on ``expires_at``; without that index the
    documents simply accumulate, which is a housekeeping problem rather than a
    correctness one.
    """

    def __init__(self, collection, ttl: int = DEFAULT_TTL_SECONDS):
        self._col = collection
        self._ttl = int(ttl)

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            doc = await self._col.find_one({"_id": str(key)})
        except Exception as exc:
            # A store that cannot be read must not fail the call. The cost of
            # guessing wrong here is a re-run; the cost of refusing is a member
            # losing their purchase to a housekeeping outage.
            logger.warning(f"idempotency read failed for {key!r}: {exc}")
            return None
        if not doc:
            return None
        payload = doc.get("payload")
        return payload if isinstance(payload, dict) else None

    async def put(self, key: str, payload: Dict[str, Any]) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._ttl)
        try:
            await self._col.update_one(
                {"_id": str(key)},
                {"$set": {"payload": dict(payload), "expires_at": expires_at}},
                upsert=True,
            )
        except Exception as exc:
            logger.warning(f"idempotency write failed for {key!r}: {exc}")


class SingleFlight:
    """Per-key serialization, so a retry never runs beside its original."""

    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._waiters: Dict[str, int] = {}

    def lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        self._waiters[key] = self._waiters.get(key, 0) + 1
        return lock

    def release(self, key: str) -> None:
        """Drop the lock once nobody is holding or waiting for it."""
        remaining = self._waiters.get(key, 1) - 1
        if remaining <= 0:
            self._waiters.pop(key, None)
            self._locks.pop(key, None)
        else:
            self._waiters[key] = remaining


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "IdempotencyStore",
    "MemoryIdempotencyStore",
    "MongoIdempotencyStore",
    "SingleFlight",
]
