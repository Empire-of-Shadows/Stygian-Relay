# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""storage_engine — the Empire of Shadows shared MongoDB storage engine.

This is the MASTER copy. It is vendored byte-for-byte into each bot's ``storage/``
directory by ``tools/sync_storage_engine.py``. Like ``admin_engine``, it is an
engine/library package, not a standalone app: the concrete ``DatabaseManager`` and the
collection registry live in each bot (the bot-owned seam; copy the templates from
``EmpireSystems/Settings/storage/``), so this package is intentionally NOT fully
importable on its own. Only the backend-agnostic pieces (``cache``, ``helpers``,
``core.connection_pool``, ``core.collection_config``) import cleanly without a bot present.

The package is imported as ``storage_engine`` in the master and as ``storage`` once
vendored into a bot; engine modules use relative imports so the same code works in both.

Public surface (shown master-relative):
    from storage_engine.core import (
        ConnectionPool, CollectionManager, CollectionConfig, with_retry,
    )
    from storage_engine.database_manager import (
        DatabaseManagerBase, ensure_unique_constraint, paginate_results, batch_upsert,
    )
    from storage_engine.cache import CacheBackend, LocalCache, ChangeStreamWatcher
    from storage_engine.config import GuildConfigStore, normalize_guild_id_to_str
    from storage_engine.buffer import BatchWriter
    from storage_engine.interaction import InteractionStateStore, pack, parse
    from storage_engine.content import CachedLoader
    from storage_engine.services import AuditLog, SetupGate, SingletonLock, UserPreferenceCache
    from storage_engine.snapshots import SnapshotStore, SnapshotSpec, SnapshotEventLog
    from storage_engine.log import get_logger, setup_application_logging

Discord bots only (optional discord.py dependency; NOT imported by the engine core, so the
core stays importable/vendorable without discord.py):
    from storage_engine.discord import (
        GuildSnapshotService, create_guild_snapshot_service, GuildSnapshotConfig,
    )
"""

from .core import CollectionConfig, CollectionManager, ConnectionPool, with_retry
from .cache import CacheBackend, ChangeStreamWatcher, LocalCache
from .config import GuildConfigStore, normalize_guild_id_to_str
from .buffer import BatchWriter
from .interaction import InteractionStateStore, CustomId, pack, parse
from .content import CachedLoader
from .services import AuditLog, SetupGate, SingletonLock, UserPreferenceCache
from .snapshots import SnapshotStore, SnapshotSpec, SnapshotEventLog
from .log import (
    get_logger,
    setup_application_logging,
    log_performance,
    log_context,
)

__all__ = [
    "ConnectionPool",
    "CollectionManager",
    "CollectionConfig",
    "with_retry",
    "CacheBackend",
    "LocalCache",
    "ChangeStreamWatcher",
    "GuildConfigStore",
    "normalize_guild_id_to_str",
    "BatchWriter",
    "InteractionStateStore",
    "CustomId",
    "pack",
    "parse",
    "CachedLoader",
    "AuditLog",
    "SetupGate",
    "SingletonLock",
    "UserPreferenceCache",
    "SnapshotStore",
    "SnapshotSpec",
    "SnapshotEventLog",
    "get_logger",
    "setup_application_logging",
    "log_performance",
    "log_context",
]
