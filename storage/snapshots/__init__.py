# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""snapshots — generic, discord-free object-snapshotting engine.

A ``SnapshotStore`` bulk-upserts snapshots of related objects into Mongo, gated by a
freshness check and serialized per partition, driven entirely by plain :class:`SnapshotSpec`
records (no domain knowledge). ``SnapshotEventLog`` is a companion append-only event trail.

The discord.py-aware layer that turns ``discord.Guild`` graphs into the dicts these consume is
``storage_engine.discord`` (imported on demand — NOT from the top-level package — so the engine
core keeps its zero-discord invariant).
"""

from .spec import SnapshotSpec
from .store import SnapshotStore
from .event_log import SnapshotEventLog

__all__ = ["SnapshotSpec", "SnapshotStore", "SnapshotEventLog"]
