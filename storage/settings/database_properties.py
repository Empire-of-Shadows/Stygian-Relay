"""Typed collection accessors — Stygian-Relay (bot-owned, NOT vendored).

Convenience ``CollectionManager`` properties over the keys registered in
``define_collections.py``. Relay's domain layer (``storage/bot_specific/relay/``) reaches Mongo
through the engine's raw collections for its richer queries; these typed accessors are the
idiomatic surface for new/simple call sites (and a future dashboard).

Template: ``EmpireSystems/storage_engine/database_properties_reference.py``.
"""

from storage.core.collection_manager import CollectionManager


class DatabaseProperties:
    @property
    def guild_settings(self) -> CollectionManager:
        """Per-guild settings + nested forwarding rules."""
        return self.get_collection_manager("guild_settings")

    @property
    def message_logs(self) -> CollectionManager:
        """Forwarded-message audit log (TTL 90 days)."""
        return self.get_collection_manager("message_logs")

    @property
    def entitlements(self) -> CollectionManager:
        """Raw premium entitlement records (one per entitlement id; incl. manual grants)."""
        return self.get_collection_manager("entitlements")

    @property
    def premium_state(self) -> CollectionManager:
        """Derived per-scope premium status (folded from entitlements)."""
        return self.get_collection_manager("premium_state")

    @property
    def audit_logs(self) -> CollectionManager:
        """Admin/premium/settings audit trail (TTL 365 days)."""
        return self.get_collection_manager("audit_logs")
