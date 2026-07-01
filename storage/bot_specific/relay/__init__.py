"""Stygian-Relay domain layer (bot-owned, NOT vendored).

Carried over from the retired bespoke ``database/`` package. Reaches Mongo through the shared
engine ``db_manager`` (``storage/manager.py``) via its back-compat ``get_collection`` /
``db_client`` accessors, so the proven guild / rule / premium query logic runs unchanged on the
shared engine connection.

Exposes the module-level singletons the rest of the bot imports (same names the old
``database`` package exported, so call sites only change their import path):

    from storage.bot_specific.relay import db_manager, guild_manager, audit_log
"""

from typing import Any, Dict

from storage.manager import db_manager
from .guild_manager import GuildManager
from .audit import AuditLog
from .exceptions import DatabaseConnectionError, DatabaseOperationError

# Domain managers over the shared engine db_manager (constructed at import; the engine is
# initialized later by Relay.py before any of these are used).
guild_manager = GuildManager(db_manager)
audit_log = AuditLog(db_manager)


async def ensure_database_connection() -> bool:
    """Ensure the engine db_manager is initialized (compat shim from the old database package)."""
    if not db_manager.is_connected:
        await db_manager.initialize()
    return db_manager.is_connected


async def setup_new_guild(guild_id: str, guild_name: str) -> Dict[str, Any]:
    """Convenience: create/refresh a guild's settings doc."""
    if not await ensure_database_connection():
        raise DatabaseConnectionError("Could not establish database connection")
    return await guild_manager.setup_new_guild(guild_id, guild_name)


async def get_guild_settings(guild_id: str) -> Dict[str, Any]:
    """Convenience: fetch (or create) a guild's settings doc."""
    if not await ensure_database_connection():
        raise DatabaseConnectionError("Could not establish database connection")
    return await guild_manager.get_guild_settings(guild_id)


__all__ = [
    "db_manager",
    "guild_manager",
    "audit_log",
    "GuildManager",
    "AuditLog",
    "DatabaseConnectionError",
    "DatabaseOperationError",
    "ensure_database_connection",
    "setup_new_guild",
    "get_guild_settings",
]
