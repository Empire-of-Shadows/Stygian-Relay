# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""SingletonLock — single live process per database (advisory lock).

Capability: single-instance advisory lock. Promoted from TheHost's ``InstanceLock``: enforce
that exactly one bot process owns the data, so in-process write-back caches and per-channel
serialization stay correct (a second instance would double-process and corrupt state).

Design (unchanged): one document keyed ``_id=<lock_id>``; acquire inserts if absent, else
steals only when the existing lock is expired (crashed holder) or already ours; a heartbeat
refreshes ``expires_at``; release deletes it. **Fail-open** — a lock subsystem error lets
startup proceed rather than bricking the bot; only a clearly-live competitor blocks.

Genericized: takes the lock ``CollectionManager`` plus configurable ``lock_id`` / TTL /
heartbeat. Uses the manager's raw collection for atomic ``insert_one`` /
``find_one_and_update`` semantics (engine-internal raw access is fine; the "no raw access"
rule is for feature code).
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Optional

from pymongo.errors import DuplicateKeyError

from ..core.collection_manager import CollectionManager
from ..logging_compat import get_logger

logger = get_logger("SingletonLock")


class SingletonLock:
    """Advisory single-instance lock over one collection document.

    Args:
        manager: the ``CollectionManager`` for the lock collection.
        lock_id: ``_id`` of the lock document (one per logical singleton).
        ttl_seconds: how long a held lock stays valid without a heartbeat.
        heartbeat_seconds: refresh cadence (must be well below ``ttl_seconds``).
    """

    def __init__(self, manager: CollectionManager, *, lock_id: str = "bot_singleton",
                 ttl_seconds: float = 45.0, heartbeat_seconds: float = 15.0):
        self._mgr = manager
        self._lock_id = lock_id
        self._ttl = float(ttl_seconds)
        self._hb_interval = float(heartbeat_seconds)
        self._instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._task: Optional[asyncio.Task] = None
        self._held = False

    @property
    def _col(self):
        # Raw async collection for atomic insert / find_one_and_update / delete.
        return self._mgr.collection

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def acquire(self, wait_timeout: float = 90.0) -> bool:
        """Capability: become the single live instance. Returns ``True`` if acquired (or if the
        lock subsystem errored — fail-open), ``False`` only when a live competitor holds it."""
        deadline = monotonic() + wait_timeout
        while True:
            now = datetime.now(timezone.utc)
            expires = now + timedelta(seconds=self._ttl)
            doc = {"_id": self._lock_id, "owner": self._instance_id,
                   "acquired_at": now, "expires_at": expires}

            # 1. Fast path: no lock present yet.
            try:
                await self._col.insert_one(doc)
                self._held = True
                logger.info(f"Singleton lock '{self._lock_id}' acquired by {self._instance_id}")
                return True
            except DuplicateKeyError:
                pass
            except Exception as e:
                logger.error(f"Singleton lock acquire errored; proceeding without it: {e}", exc_info=True)
                return True

            # 2. Steal only if expired (crashed holder) or already ours.
            try:
                stolen = await self._col.find_one_and_update(
                    {"_id": self._lock_id, "$or": [
                        {"expires_at": {"$lt": now}},
                        {"owner": self._instance_id},
                    ]},
                    {"$set": {"owner": self._instance_id, "acquired_at": now, "expires_at": expires}},
                )
            except Exception as e:
                logger.error(f"Singleton lock steal errored; proceeding without it: {e}", exc_info=True)
                return True

            if stolen is not None:
                self._held = True
                logger.info(f"Singleton lock '{self._lock_id}' acquired (took over stale/own lock) by {self._instance_id}")
                return True

            # 3. A live foreign lock holds it. Wait and retry until the deadline.
            if monotonic() >= deadline:
                try:
                    current = await self._col.find_one({"_id": self._lock_id})
                except Exception:
                    current = None
                owner = current.get("owner") if current else "unknown"
                logger.critical(
                    f"Another instance holds singleton lock '{self._lock_id}' (owner={owner}); "
                    f"refusing to start to protect state."
                )
                return False
            await asyncio.sleep(2.0)

    async def start_heartbeat(self) -> None:
        """Begin refreshing ``expires_at`` while we hold the lock (idempotent)."""
        if not self._held or (self._task and not self._task.done()):
            return
        self._task = asyncio.create_task(self._heartbeat_loop(), name="SingletonLockHeartbeat")

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._hb_interval)
                now = datetime.now(timezone.utc)
                try:
                    res = await self._col.update_one(
                        {"_id": self._lock_id, "owner": self._instance_id},
                        {"$set": {"expires_at": now + timedelta(seconds=self._ttl)}},
                    )
                    if res.matched_count == 0:
                        logger.warning(f"Singleton lock '{self._lock_id}' missing during heartbeat; re-acquiring")
                        self._held = False
                        await self.acquire(wait_timeout=0.0)
                except Exception as e:
                    logger.error(f"Singleton lock heartbeat failed: {e}", exc_info=True)
        except asyncio.CancelledError:
            pass

    async def release(self) -> None:
        """Stop the heartbeat and delete our lock document (if we still own it)."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self._held:
            try:
                await self._col.delete_one({"_id": self._lock_id, "owner": self._instance_id})
                logger.info(f"Singleton lock '{self._lock_id}' released")
            except Exception as e:
                logger.warning(f"Failed to release singleton lock: {e}", exc_info=True)
            self._held = False
