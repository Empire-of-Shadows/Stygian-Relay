# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""DatabaseManagerBase — the generic, bot-agnostic Mongo manager.

This is the engine half of the database manager. It owns connection pooling, database
discovery, collection-manager construction, index creation, transactions, the shared
cache + change-stream coherency, health checks, and graceful shutdown.

It is ABSTRACT in practice: it does not know any bot's collections. Each bot supplies
that via two mixins it composes into a concrete ``DatabaseManager`` (exactly how
``admin_cog`` imports ``MAIN_PANEL`` from the bot):

    # bot-owned, NOT vendored — see define_collections_reference.py / database_properties_reference.py
    class DatabaseManager(DatabaseManagerBase, DefineCollections, DatabaseProperties):
        pass

    db_manager = DatabaseManager(watched_collections=WATCHED_COLLECTIONS)

``DefineCollections`` must provide ``_define_collection_configs(self)`` (populates
``self._collection_configs``); ``DatabaseProperties`` provides typed accessors. The base
intentionally does NOT define ``_define_collection_configs`` so the mixin's version wins
via MRO regardless of base ordering.
"""

import os
import asyncio
from typing import Dict, List, Any, Callable, Optional
from datetime import datetime, timedelta, timezone

from pymongo import AsyncMongoClient, UpdateOne
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.asynchronous.collection import AsyncCollection
from dotenv import load_dotenv

from .core.collection_config import CollectionConfig
from .core.collection_manager import CollectionManager
from .core.connection_pool import ConnectionPool
from .cache.backend import CacheBackend
from .cache.local import LocalCache
from .cache.coherency import ChangeStreamWatcher
from .buffer.batch_writer import BatchWriter
from .logging_compat import get_logger

load_dotenv()
logger = get_logger("DatabaseManager")


class DatabaseManagerBase:
    """MongoDB manager with pooling, CRUD, shared cache, coherency, and health checks.

    Subclass with the bot's ``DefineCollections`` + ``DatabaseProperties`` mixins.
    """

    def __init__(self, primary_uri: str = None, secondary_uri: str = None, *,
                 cache: Optional[CacheBackend] = None,
                 cache_defaults: Optional[Dict[str, Any]] = None,
                 watched_collections: Optional[List[str]] = None,
                 **additional_uris):
        self.primary_uri = primary_uri or os.getenv("MONGO_URI")
        self.secondary_uri = secondary_uri
        self.additional_uris = additional_uris

        if not self.primary_uri:
            raise ValueError("Primary MongoDB URI not provided (set MONGO_URI env var)")

        self.connection_pools: Dict[str, ConnectionPool] = {}
        self.connection_pools['primary'] = ConnectionPool(self.primary_uri, connection_name='primary')

        if self.secondary_uri:
            self.connection_pools['secondary'] = ConnectionPool(self.secondary_uri, connection_name='secondary')
            logger.info("Secondary connection pool configured")

        for name, uri in self.additional_uris.items():
            if uri and name.endswith('_uri'):
                conn_name = name.removesuffix('_uri')
                self.connection_pools[conn_name] = ConnectionPool(uri, connection_name=conn_name)
                logger.info(f"{conn_name.capitalize()} connection pool configured")

        # One cache shared by every CollectionManager so the change-stream watcher can
        # invalidate across collections through a single backend.
        self._cache: CacheBackend = cache or LocalCache(**(cache_defaults or {}))
        self._watched_keys: List[str] = list(watched_collections or [])
        self._watcher: Optional[ChangeStreamWatcher] = None
        self._batch_writer: Optional[BatchWriter] = None

        self.databases: Dict[str, AsyncDatabase] = {}
        self.collections: Dict[str, CollectionManager] = {}
        self._collection_configs: Dict[str, CollectionConfig] = {}
        self._initialized = False
        self._lock = asyncio.Lock()

        # The bot's DefineCollections mixin provides _define_collection_configs (populates
        # self._collection_configs). The base deliberately does NOT define it, so the
        # mixin's version always wins via MRO regardless of base ordering; we resolve it by
        # name and raise a clear error if no mixin was composed in.
        define = getattr(self, "_define_collection_configs", None)
        if define is None:
            raise NotImplementedError(
                "Compose a DefineCollections mixin that implements "
                "_define_collection_configs(). See define_collections_reference.py."
            )
        define()

    @property
    def cache(self) -> CacheBackend:
        """The shared cache backend (hit-first on reads)."""
        return self._cache

    @property
    def batch_writer(self) -> BatchWriter:
        """Shared write buffer for high-frequency counters (lazily started).

        Coalesces ``$inc``/``$set`` writes to the same document and flushes them through
        the collection managers on a size/interval trigger. Auto-flushed on ``close()``.
        Use only for deferrable, non-critical writes (see the buffer module docs)."""
        if self._batch_writer is None:
            self._batch_writer = BatchWriter(self.get_collection_manager)
            self._batch_writer.start()
        return self._batch_writer

    @property
    def is_connected(self) -> bool:
        """Check if the database manager is initialized and connected."""
        return self._initialized

    async def initialize(self):
        """Initialize the database manager with connection pooling and collection setup."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            try:
                logger.info("Initializing DatabaseManager...")

                for name, pool in self.connection_pools.items():
                    await pool.initialize()
                    logger.info(f"Initialized {name} connection pool")

                # Discover databases from all connections
                for connection_name, pool in self.connection_pools.items():
                    try:
                        client = await pool.get_client()
                        db_names = await client.list_database_names()
                        non_system_dbs = [db for db in db_names if db not in ['admin', 'local', 'config']]

                        logger.info(
                            f"Found {len(non_system_dbs)} databases in {connection_name} connection: {non_system_dbs}")

                        for db_name in non_system_dbs:
                            db_key = db_name
                            if connection_name != 'primary' and db_name in self.databases:
                                db_key = f"{connection_name}_{db_name}"
                                logger.debug(
                                    f"Database name conflict: {db_name} exists in multiple connections. Using {db_key}")

                            self.databases[db_key] = client[db_name]
                            logger.debug(f"Initialized database '{db_key}' from {connection_name} connection")

                    except Exception as e:
                        logger.warning(f"Error discovering databases from {connection_name} connection: {e}")
                        continue

                await self._initialize_collections()
                await self._create_all_indexes()
                await self._start_coherency()

                self._initialized = True
                logger.info(f"DatabaseManager initialized successfully with {len(self.databases)} databases")

            except Exception as e:
                logger.error(f"Failed to initialize DatabaseManager: {e}")
                raise

    async def _initialize_collections(self):
        """Initialize collection managers (all sharing the one cache backend)."""
        for config_key, config in self._collection_configs.items():
            try:
                connection_name = config.connection
                if connection_name not in self.connection_pools:
                    logger.warning(
                        f"Connection '{connection_name}' not available for {config_key}, falling back to primary")
                    connection_name = 'primary'

                client = await self.connection_pools[connection_name].get_client()
                database = client[config.database]
                collection = database[config.name]

                if config.capped:
                    try:
                        await database.create_collection(
                            config.name,
                            capped=True,
                            size=config.max_size,
                            max=config.max_documents
                        )
                    except Exception:
                        pass  # Collection may already exist or capped creation unsupported

                manager = CollectionManager(collection, config, cache=self._cache)
                self.collections[config_key] = manager

                logger.debug(f"Initialized collection manager for {config_key} on {connection_name} connection")

            except Exception as e:
                logger.error(f"Error initializing collection {config_key}: {e}")
                raise

    async def _create_all_indexes(self):
        """Create indexes for all collections."""
        for config_key, manager in self.collections.items():
            try:
                await manager.create_indexes()
            except Exception as e:
                logger.warning(f"Error creating indexes for {config_key}: {e}")

    async def _start_coherency(self):
        """Attach change-stream coherency to the configured watched collections.

        Degrades to TTL-only automatically when change streams are unavailable
        (e.g. standalone mongod). Never fatal."""
        if not self._watched_keys:
            return
        watch_map: Dict[str, AsyncCollection] = {}
        for key in self._watched_keys:
            mgr = self.collections.get(key)
            if mgr is None:
                logger.warning(f"watched_collections references unknown collection key {key!r}; skipping.")
                continue
            watch_map[mgr.name] = mgr.collection
        if not watch_map:
            return
        self._watcher = ChangeStreamWatcher(lambda n: watch_map[n], self._cache, list(watch_map))
        await self._watcher.start()

    def _ensure_initialized(self):
        """Ensure the database manager is initialized."""
        if not self._initialized:
            raise RuntimeError("DatabaseManager not initialized. Call initialize() first.")

    # Collection Access Methods

    def get_database(self, name: str) -> AsyncDatabase:
        """Get a database by name."""
        self._ensure_initialized()
        if name not in self.databases:
            for connection_name, pool in self.connection_pools.items():
                try:
                    client = pool.client
                    if client is not None:
                        self.databases[name] = client[name]
                        return self.databases[name]
                except Exception:
                    continue
            raise ValueError(f"Database '{name}' not found in any connection")
        return self.databases[name]

    def get_collection_manager(self, collection_key: str) -> CollectionManager:
        """Get a collection manager by key."""
        self._ensure_initialized()
        if collection_key not in self.collections:
            raise ValueError(f"Collection '{collection_key}' not configured")
        return self.collections[collection_key]

    def get_raw_collection(self, database_name: str, collection_name: str) -> AsyncCollection:
        """Get raw collection access for advanced operations."""
        database = self.get_database(database_name)
        return database[collection_name]

    def get_client(self, connection_name: str = 'primary') -> AsyncMongoClient:
        """Get a client for a specific connection."""
        self._ensure_initialized()
        if connection_name not in self.connection_pools:
            raise ValueError(f"Connection '{connection_name}' not configured")
        return self.connection_pools[connection_name].client

    async def get_client_async(self, connection_name: str = 'primary') -> AsyncMongoClient:
        """Get a client for a specific connection asynchronously."""
        self._ensure_initialized()
        if connection_name not in self.connection_pools:
            raise ValueError(f"Connection '{connection_name}' not configured")
        return await self.connection_pools[connection_name].get_client()

    # Transaction Support

    async def start_session(self, connection_name: str = 'primary', **kwargs):
        """Start a new database session for transactions."""
        self._ensure_initialized()
        client = await self.get_client_async(connection_name)
        return await client.start_session(**kwargs)

    async def with_transaction(self, callback: Callable, session_options: Dict = None,
                               connection_name: str = 'primary'):
        """Execute a callback within a transaction."""
        session_options = session_options or {}

        async with await self.start_session(connection_name, **session_options) as session:
            async with session.start_transaction():
                return await callback(session)

    # Utility Methods

    async def cleanup_old_data(self, collection_keys: List[str], days_to_keep: int = 90,
                               status: Optional[str] = None) -> Dict[str, Any]:
        """Delete documents older than ``days_to_keep`` (by ``created_at``) across the
        given collection keys. Optionally restrict to a ``status`` value. Generic: the
        caller chooses which collections to sweep (no hard-coded names)."""
        cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=days_to_keep)
        cleanup_results: Dict[str, Any] = {}

        for collection_key in collection_keys:
            if collection_key in self.collections:
                try:
                    manager = self.collections[collection_key]
                    query: Dict[str, Any] = {'created_at': {'$lt': cutoff_date}}
                    if status is not None:
                        query['status'] = status
                    deleted_count = await manager.delete_many(query)
                    cleanup_results[collection_key] = deleted_count
                    logger.info(f"Cleaned up {deleted_count} old records from {collection_key}")
                except Exception as e:
                    logger.error(f"Error cleaning up {collection_key}: {e}")
                    cleanup_results[collection_key] = f"Error: {e}"

        return cleanup_results

    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check on all connections."""
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.now(tz=timezone.utc).isoformat(),
            'connections': {},
            'collections': {},
            'cache': self._cache.get_stats(),
        }

        try:
            for name, pool in self.connection_pools.items():
                try:
                    client = await pool.get_client()
                    await client.admin.command('ping')
                    health_status['connections'][name] = 'healthy'
                except Exception as e:
                    health_status['connections'][name] = f'error: {e}'
                    health_status['status'] = 'degraded'

            for collection_key, manager in self.collections.items():
                try:
                    await manager.count_documents({})
                    health_status['collections'][collection_key] = 'healthy'
                except Exception as e:
                    health_status['collections'][collection_key] = f'error: {e}'
                    health_status['status'] = 'degraded'

        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['error'] = str(e)

        return health_status

    async def close(self):
        """Close all database connections and cleanup resources."""
        try:
            logger.info("Closing DatabaseManager...")

            # Flush buffered writes BEFORE tearing down collections/pools so no queued
            # counter updates are lost on shutdown.
            if self._batch_writer is not None:
                await self._batch_writer.shutdown()
                self._batch_writer = None

            if self._watcher is not None:
                await self._watcher.stop()
                self._watcher = None

            self._cache.clear()
            self.collections.clear()
            self.databases.clear()

            for name, pool in self.connection_pools.items():
                await pool.close()
                logger.info(f"Closed {name} connection pool")

            self.connection_pools.clear()
            self._initialized = False
            logger.info("DatabaseManager closed successfully")

        except Exception as e:
            logger.error(f"Error closing DatabaseManager: {e}")


# Utility functions

async def ensure_unique_constraint(manager: CollectionManager,
                                   field: str,
                                   value: Any,
                                   exclude_id: Any = None) -> bool:
    """Ensure a field value is unique in the collection."""
    filter_dict = {field: value}
    if exclude_id:
        filter_dict['_id'] = {'$ne': exclude_id}

    existing = await manager.find_one(filter_dict)
    return existing is None


async def paginate_results(manager: CollectionManager,
                           filter_dict: Dict[str, Any] = None,
                           sort: List[tuple] = None,
                           page_size: int = 50,
                           page: int = 1) -> Dict[str, Any]:
    """Paginate query results."""
    filter_dict = filter_dict or {}
    skip = (page - 1) * page_size

    total_count, results = await asyncio.gather(
        manager.count_documents(filter_dict),
        manager.find_many(filter_dict, sort=sort, limit=page_size, skip=skip)
    )

    total_pages = (total_count + page_size - 1) // page_size

    return {
        'results': results,
        'pagination': {
            'current_page': page,
            'page_size': page_size,
            'total_items': total_count,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    }


async def batch_upsert(manager: CollectionManager,
                       documents: List[Dict[str, Any]],
                       match_fields: List[str]) -> Dict[str, int]:
    """Perform batch upsert operations based on matching fields."""
    if not documents or not match_fields:
        return {'inserted': 0, 'updated': 0}

    operations = []
    now = datetime.now(tz=timezone.utc)

    for doc in documents:
        filter_dict = {field: doc[field] for field in match_fields if field in doc}

        update_doc = doc.copy()
        update_doc['updated_at'] = now
        if 'created_at' not in update_doc:
            update_doc['created_at'] = now

        operation = UpdateOne(
            filter_dict,
            {'$set': update_doc},
            upsert=True
        )
        operations.append(operation)

    result = await manager.bulk_write(operations, ordered=False)

    return {
        'inserted': result['inserted_count'] + result.get('upserted_count', 0),
        'updated': result['modified_count']
    }
