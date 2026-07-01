"""Collection registry — Stygian-Relay (bot-owned, NOT vendored).

Registers relay's collections so the engine builds a ``CollectionManager`` (and typed accessor,
see ``database_properties.py``) for each. All live in the single ``discord_forwarding_bot``
database (name preserved so existing data is reused — no migration).

Indexes are intentionally **omitted** here: relay's index shapes are created by
``GuildManager.initialize_default_settings()`` / ``_ensure_indexes()`` (the historical source of
truth, including the TTL indexes), and declaring them again here would risk duplicate-name
conflicts. Registering the collections still gives the engine awareness + typed access.

Template: ``EmpireSystems/storage_engine/define_collections_reference.py``.
"""

from storage.core.collection_config import CollectionConfig
from storage.logging import get_logger

logger = get_logger("DefineCollections")

# Relay's single application database (preserved name — data reused, no migration).
RELAY_DB = "discord_forwarding_bot"

# Collections owned by relay's domain layer (storage/bot_specific/relay/guild_manager.py).
# Mirrors database/constants.REQUIRED_COLLECTIONS.
_RELAY_COLLECTIONS = [
    "guild_settings",
    "message_logs",
    "error_logs",
    "rate_limits",
    "bot_settings",
    "user_permissions",
    "premium_subscriptions",
    "premium_codes",
    "audit_logs",
    "runtime_state",
    "daily_counters",
    "setup_sessions",
]


class DefineCollections:
    def _define_collection_configs(self):
        """Register relay's collections (indexes owned by GuildManager — see module docstring)."""
        for name in _RELAY_COLLECTIONS:
            self._collection_configs[name] = CollectionConfig(
                name=name,
                database=RELAY_DB,
                connection="primary",
                indexes=[],
            )
