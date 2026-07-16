"""Concrete DatabaseManager for Stygian-Relay (bot-owned, NOT vendored).

Composes the vendored engine base (``DatabaseManagerBase``) with relay's two mixins
(``DefineCollections`` + ``DatabaseProperties``) and instantiates the shared ``db_manager`` the
rest of the bot imports (``from storage.settings.manager import db_manager``).

Relay's domain layer (``storage/bot_specific/relay/{guild_manager,audit}.py``) was carried over
from the retired bespoke ``database/`` package and still expresses its richer queries against a
motor-style collection handle. The two thin back-compat accessors below let that proven logic run
unchanged on the engine's pymongo connection: ``get_collection`` aliases the engine's
``get_raw_collection``, and ``db_client`` exposes the primary ``AsyncMongoClient`` (the engine
owns the pool). The pymongo async CRUD/cursor/transaction surface matches what that code used.
"""

from __future__ import annotations

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection

from storage.database_manager import DatabaseManagerBase
from storage.settings.define_collections import DefineCollections
from storage.settings.database_properties import DatabaseProperties
from storage.settings import bindings


class DatabaseManager(DatabaseManagerBase, DefineCollections, DatabaseProperties):
    """Relay's MongoDB manager: engine core + relay's collection registry + compat seam."""

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
)
