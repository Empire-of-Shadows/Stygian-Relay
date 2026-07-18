# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""discord — opt-in Discord object snapshotting built on the generic ``snapshots`` core.

This subpackage is the ONLY part of the engine that imports discord.py, and it is imported on
demand (a bot does ``from storage.discord import ...``); the top-level ``storage`` package never
imports it, so the engine core stays discord-free and vendors cleanly into non-Discord consumers.

Typical use in a Discord bot::

    from storage.discord import create_guild_snapshot_service, GuildSnapshotConfig

    guild_snapshots = create_guild_snapshot_service(
        db_manager, config=GuildSnapshotConfig(timezone="America/Chicago"))
    await guild_snapshots.cache_all(guild)
"""

from .config import (
    DEFAULT_KEYS,
    DANGEROUS_PERMISSIONS,
    MODERATION_PERMISSIONS,
    GuildSnapshotConfig,
    build_specs,
)
from .service import GuildSnapshotService, create_guild_snapshot_service

__all__ = [
    "GuildSnapshotConfig",
    "GuildSnapshotService",
    "create_guild_snapshot_service",
    "build_specs",
    "DEFAULT_KEYS",
    "DANGEROUS_PERMISSIONS",
    "MODERATION_PERMISSIONS",
]
