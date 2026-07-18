# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Stygian-Relay domain layer (master-owned; vendored into relay only).

Carried over from the retired bespoke ``database/`` package. Reaches Mongo through the shared
engine ``db_manager`` (``storage/manager.py``) via its back-compat ``get_collection`` /
``db_client`` accessors, so the proven guild / rule / premium query logic runs unchanged on the
shared engine connection.

Exposes the module-level singletons the rest of the bot imports (same names the old
``database`` package exported, so call sites only change their import path):

    from storage.bot_specific.relay import db_manager, guild_manager, audit_log
"""

from typing import Any, Dict

from ...settings.manager import db_manager
from ...premium import PremiumManager, PremiumState, SCOPE_GUILD
from .guild.guild_manager import GuildManager
from .audit import AuditLog
from .exceptions import DatabaseConnectionError, DatabaseOperationError

# Domain managers over the shared engine db_manager (constructed at import; the engine is
# initialized later by Relay.py before any of these are used).
guild_manager = GuildManager(db_manager)
audit_log = AuditLog(db_manager)


def _on_premium_state_change(scope: str, scope_id: str) -> None:
    """Drop GuildManager's cached premium/limits for a guild whose state just changed, so a
    grant/revoke/entitlement event is reflected on the next read instead of after the TTL."""
    if scope == SCOPE_GUILD:
        guild_manager._invalidate_premium(str(scope_id))


# Entitlement-backed premium (per-guild today, per-user ready). Recompute invalidates the
# guild premium cache via the hook above. Real tier ordering is supplied by the cog from its
# per-bot SKU map; the master default is unranked.
premium_manager = PremiumManager(
    db_manager,
    db_name="discord_forwarding_bot",
    legacy_subscriptions_collection="premium_subscriptions",
    on_state_change=_on_premium_state_change,
)


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
    "premium_manager",
    "GuildManager",
    "AuditLog",
    "PremiumManager",
    "PremiumState",
    "DatabaseConnectionError",
    "DatabaseOperationError",
    "ensure_database_connection",
    "setup_new_guild",
    "get_guild_settings",
]
