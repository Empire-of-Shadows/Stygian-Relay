# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""SnapshotSpec — the plain, backend-agnostic description of one snapshot collection.

A ``SnapshotStore`` is driven entirely by a list of these. The spec carries no domain
knowledge (it never mentions "guild" or "member"); it only says which registry key backs a
logical object type, how to build the upsert filter, which field partitions rows for cascade
deletes, whether this is the freshness "root" doc, and whether to chunk large bulk writes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotSpec:
    """Describes one object type stored as snapshots.

    Args:
        object_type: logical name callers use (e.g. ``"guild"``, ``"members"``).
        collection_key: registry key passed to ``db_manager.get_collection_manager``.
        identity_fields: fields forming the upsert filter (e.g. ``("guild_id", "id")``).
            Every record handed to the store MUST contain these fields.
        partition_field: the field matched to delete every row for one partition
            (a guild's ``"guild_id"``; the root doc's own id field for the root spec).
        is_root: exactly one spec is the root — the doc whose ``updated_at`` drives freshness.
        chunk_size: if set, ``upsert_many`` splits records into chunks of this size per
            ``bulk_write`` (large guilds → ``1000``). ``None`` = one bulk write.
    """

    object_type: str
    collection_key: str
    identity_fields: tuple[str, ...]
    partition_field: str
    is_root: bool = False
    chunk_size: int | None = None
