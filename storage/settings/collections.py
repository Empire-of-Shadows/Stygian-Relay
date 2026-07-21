"""storage_engine - collection registry + manager for Stygian-Relay (bot-owned, NOT vendored).

This one file declares relay's collections AND constructs the shared ``db_manager`` the rest of
the bot imports (``from storage.settings.collections import db_manager``). It replaces the old
``define_collections`` + ``manager`` pair: the engine base builds its own per-collection accessor
map (``db_manager.<registry_key>``) from the registry at construction, so no ``DefineCollections``
mixin (or ``database_properties.py``) is needed.

All collections live in the single ``discord_forwarding_bot`` database (name preserved so
existing data is reused - no migration). Indexes are intentionally omitted: relay's index shapes
are created by ``GuildManager.initialize_default_settings()`` / ``_ensure_indexes()`` (the
historical source of truth, including the TTL indexes); re-declaring them here would risk
duplicate-name conflicts. Registering the collections still gives the engine awareness + access.

Relay's domain layer (``storage/bot_specific/relay/{guild,audit}``) was carried over from the
retired bespoke ``database/`` package and expresses its queries against a motor-style collection
handle. The two thin back-compat accessors on ``DatabaseManager`` let that proven logic run
unchanged on the engine's pymongo connection: ``get_collection`` aliases ``get_raw_collection``,
and ``db_client`` exposes the primary ``AsyncMongoClient`` (the engine owns the pool).

ENGINE CONTRACT: the registry is a ``dict[str, CollectionConfig]`` passed as
``collection_configs=``. The dict key is the *registry key* passed to
``db_manager.get_collection_manager(key)`` and listed in ``bindings.WATCHED_COLLECTIONS``.

Template: ``EmpireSystems/Settings/storage/collections_reference.py``.
"""

from __future__ import annotations

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from storage.core.collection_config import CollectionConfig
from storage.database_manager import DatabaseManagerBase
from . import bindings

# Relay's single application database (preserved name - data reused, no migration).
RELAY_DB = "discord_forwarding_bot"

# Collections owned by relay's domain layer (storage/bot_specific/relay/guild/guild_manager.py).
# Mirrors database/constants.REQUIRED_COLLECTIONS.
_RELAY_COLLECTIONS = [
    "guild_settings",
    "message_logs",
    "error_logs",
    "rate_limits",
    "bot_settings",
    "user_permissions",
    # Entitlement-backed premium: raw `entitlements` records fold into the derived
    # `premium_state` doc per scope (indexes owned by PremiumManager._ensure_indexes).
    "entitlements",
    "premium_state",
    # Retired code-redemption store. Kept registered so the one-shot legacy migration can
    # read it; no new writes. `premium_codes` is dropped - codes are no longer issued.
    "premium_subscriptions",
    "audit_logs",
    "runtime_state",
    "daily_counters",
    "setup_sessions",
]

# registry_key -> CollectionConfig. Relay's registry keys and Mongo collection names are
# identical, so the auto-derived accessors reproduce the old typed access byte-for-byte.
COLLECTIONS: dict[str, CollectionConfig] = {
    name: CollectionConfig(name=name, database=RELAY_DB, connection="primary", indexes=[])
    for name in _RELAY_COLLECTIONS
}


class DatabaseManager(DatabaseManagerBase):
    """Relay's MongoDB manager: engine core + compat seam for the motor-era domain layer."""

    def get_collection(self, database_name: str, collection_name: str) -> AsyncCollection:
        """Back-compat alias for the engine's ``get_raw_collection`` (motor-era API)."""
        return self.get_raw_collection(database_name, collection_name)

    @property
    def db_client(self) -> AsyncMongoClient:
        """Back-compat: the primary pymongo client (the engine owns the connection pool)."""
        return self.get_client()


# Global database manager instance (shared across the bot; initialized at startup in Relay.py).
db_manager = DatabaseManager(
    primary_uri=bindings.MONGO_URIS["primary"],
    cache=bindings.build_cache(),
    watched_collections=bindings.WATCHED_COLLECTIONS,
    collection_configs=COLLECTIONS,
)
