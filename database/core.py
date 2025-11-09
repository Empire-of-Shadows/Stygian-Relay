import os
import asyncio
import signal
import json
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

from logger.logger_setup import get_logger, PerformanceLogger, log_performance, log_context
from .exceptions import DatabaseConnectionError, DatabaseOperationError
from .constants import REQUIRED_COLLECTIONS

# Load environment variables
load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")

logger = get_logger("DatabaseManager", level=20, json_format=False, colored_console=True)


class DatabaseCore:
    """
    Core database connection management with health monitoring and basic operations.
    """

    def __init__(
            self,
            connection_timeout: int = 10000,
            server_selection_timeout: int = 5000,
            max_pool_size: int = 50,
            min_pool_size: int = 10,
            max_idle_time: int = 30000,
            retry_writes: bool = True,
            retry_reads: bool = True,
            heartbeat_frequency: int = 10000,
            health_check_interval: int = 30,
            auto_discover: bool = True
    ):
        """
        Initialize DatabaseCore with connection settings.
        """
        # Connection settings
        self.connection_timeout = connection_timeout  # Max time in ms to wait for a connection
        self.server_selection_timeout = server_selection_timeout  # Max time in ms to find a suitable server
        self.max_pool_size = max_pool_size  # Max number of concurrent connections
        self.min_pool_size = min_pool_size  # Min number of concurrent connections
        self.max_idle_time = max_idle_time  # Max time in ms a connection can be idle
        self.retry_writes = retry_writes  # Retry write operations on network errors
        self.retry_reads = retry_reads  # Retry read operations on network errors
        self.heartbeat_frequency = heartbeat_frequency  # Frequency of server heartbeats in ms
        self.health_check_interval = health_check_interval  # Interval for health checks in seconds
        self.auto_discover = auto_discover  # Auto-discover and map all databases

        # Connection state
        self.db_client: Optional[AsyncIOMotorClient] = None
        self._initialized = False
        self._connection_healthy = False
        self._health_check_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Database registry
        self.databases: Dict[str, Any] = {}
        self.collections: Dict[str, Any] = {}

        # Metrics tracking
        self.metrics = {
            "connection_attempts": 0,
            "successful_connections": 0,
            "failed_connections": 0,
            "reconnection_attempts": 0,
            "health_check_failures": 0,
            "last_connection_time": None,
            "last_health_check": None,
            "total_operations": 0,
            "failed_operations": 0,
            "databases_discovered": 0,
            "collections_discovered": 0
        }

        logger.info("DatabaseCore initialized")
        self._log_configuration()

    def _log_configuration(self):
        """Log current configuration settings"""
        config_info = {
            "connection_timeout": f"{self.connection_timeout}ms",
            "server_selection_timeout": f"{self.server_selection_timeout}ms",
            "max_pool_size": self.max_pool_size,
            "min_pool_size": self.min_pool_size,
            "max_idle_time": f"{self.max_idle_time}ms",
            "retry_writes": self.retry_writes,
            "retry_reads": self.retry_reads,
            "heartbeat_frequency": f"{self.heartbeat_frequency}ms",
            "health_check_interval": f"{self.health_check_interval}s",
            "auto_discover": self.auto_discover
        }
        logger.info(f"Database configuration: {config_info}")

    @log_performance("database_initialization")
    async def initialize(self, max_retries: int = 3, retry_delay: float = 2.0) -> bool:
        """
        Initialize database connections with comprehensive error handling.
        """
        if self._initialized:
            logger.info("DatabaseCore already initialized, skipping initialization")
            return True

        logger.info("Starting DatabaseCore initialization...")

        with log_context(logger, "DatabaseCore initialization", level=20):
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"Connection attempt {attempt}/{max_retries}")

                    success = await self._attempt_connection()
                    if success:
                        # Ensure required database structure first
                        await self.ensure_database_structure()

                        # Then auto-discover other databases if enabled
                        if self.auto_discover:
                            await self._auto_discover_databases()

                        await self._verify_databases()
                        self._start_health_monitoring()

                        self._initialized = True
                        self._connection_healthy = True
                        self.metrics["successful_connections"] += 1
                        self.metrics["last_connection_time"] = datetime.now(timezone.utc)

                        logger.info("✅ DatabaseCore initialization completed successfully")
                        self._log_connection_metrics()
                        return True

                except DatabaseConnectionError as e:
                    self.metrics["failed_connections"] += 1
                    logger.error(f"❌ Connection attempt {attempt} failed: {e}")

                    if attempt < max_retries:
                        logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 1.5
                    else:
                        logger.critical(f"💥 All connection attempts failed after {max_retries} retries")
                        raise

                except Exception as e:
                    self.metrics["failed_connections"] += 1
                    logger.error(f"💥 Unexpected error during initialization attempt {attempt}: {e}", exc_info=True)

                    if attempt < max_retries:
                        logger.info(f"⏳ Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 1.5
                    else:
                        logger.critical(f"💥 Initialization failed after {max_retries} attempts")
                        raise DatabaseConnectionError(f"Failed to initialize after {max_retries} attempts") from e

        return False
    async def _attempt_connection(self) -> bool:
        """
        Attempt to establish database connection with comprehensive error handling.
        """
        if not MONGODB_URI:
            raise DatabaseConnectionError("MONGODB_URI environment variable not set")

        logger.debug("Validating MongoDB URI format...")
        if not MONGODB_URI.startswith(('mongodb://', 'mongodb+srv://')):
            raise DatabaseConnectionError("Invalid MongoDB URI format")

        self.metrics["connection_attempts"] += 1

        try:
            logger.info("Creating MongoDB client connection...")

            with PerformanceLogger(logger, "mongodb_client_creation"):
                self.db_client = AsyncIOMotorClient(
                    MONGODB_URI,
                    maxPoolSize=self.max_pool_size,
                    minPoolSize=self.min_pool_size,
                    maxIdleTimeMS=self.max_idle_time,
                    serverSelectionTimeoutMS=self.server_selection_timeout,
                    connectTimeoutMS=self.connection_timeout,
                    retryWrites=self.retry_writes,
                    retryReads=self.retry_reads,
                    heartbeatFrequencyMS=self.heartbeat_frequency,
                    maxConnecting=5,
                    waitQueueTimeoutMS=10000,
                    socketTimeoutMS=20000,
                    appname="Discord-Forwarding-Bot"
                )

            logger.info("Testing database connection...")

            with PerformanceLogger(logger, "connection_test"):
                await self.db_client.admin.command('ping')

            logger.info("✅ Database connection established successfully")
            return True

        except Exception as e:
            error_msg = f"Unexpected database connection error: {e}"
            logger.error(error_msg, exc_info=True)
            raise DatabaseConnectionError(error_msg) from e

    async def _ensure_required_collections(self):
        """Ensure all required collections for the bot exist and are mapped."""
        logger.info("🔧 Ensuring required collections exist...")

        if not self.db_client:
            raise DatabaseConnectionError("Database client not initialized")

        db = self.db_client["discord_forwarding_bot"]

        # First, create collections if they don't exist
        for collection_name in REQUIRED_COLLECTIONS:
            if collection_name not in await db.list_collection_names():
                logger.info(f"Creating collection: {collection_name}")
                await db.create_collection(collection_name)
            else:
                logger.debug(f"Collection exists: {collection_name}")

        # After ensuring collections exist, map them to the registry
        await self._map_database_collections("discord_forwarding_bot")

        logger.info("✅ All required collections verified and mapped")

    async def _auto_discover_databases(self):
        """Auto-discover all databases and their collections."""
        logger.info("🔍 Starting auto-discovery of databases and collections...")

        try:
            with PerformanceLogger(logger, "database_auto_discovery"):
                database_list = await self.db_client.list_database_names()
                user_databases = [db for db in database_list if db not in ['admin', 'local', 'config']]

                # Filter out the main database if it's already been mapped
                if "discord_forwarding_bot" in self.databases:
                    user_databases = [db for db in user_databases if db != "discord_forwarding_bot"]

                self.metrics["databases_discovered"] = len(user_databases) + (
                    1 if "discord_forwarding_bot" in self.databases else 0)

                logger.info(f"📁 Found {len(user_databases)} additional databases to discover: {user_databases}")

                for db_name in user_databases:
                    await self._map_database_collections(db_name)

                from .constants import DATABASE_MAPPINGS, COLLECTION_REGISTRY
                DATABASE_MAPPINGS.update(self.databases)
                COLLECTION_REGISTRY.update(self._build_collection_registry())

                logger.info(
                    f"✅ Auto-discovery completed: {self.metrics['collections_discovered']} total collections mapped")

        except Exception as e:
            logger.error(f"❌ Auto-discovery failed: {e}", exc_info=True)
            raise DatabaseConnectionError(f"Database auto-discovery failed: {e}") from e

    async def _map_database_collections(self, db_name: str):
        """Map all collections for a specific database."""
        logger.debug(f"Mapping collections for database: {db_name}")

        # Check if database is already mapped to avoid duplicates
        if db_name in self.databases:
            logger.debug(f"Database {db_name} already mapped, updating collections...")

        database = self.db_client[db_name]
        self.databases[db_name] = database

        try:
            collections_info = await database.list_collections()
            collections = []

            async for collection_info in collections_info:
                collection_name = collection_info['name']

                if collection_name.startswith('system.'):
                    logger.debug(f"  ⏭️  Skipping system collection: {collection_name}")
                    continue

                collections.append(collection_name)
                attr_name = f"{db_name.lower()}_{collection_name.lower()}"

                # Only increment counter if this is a new collection mapping
                if attr_name not in self.collections:
                    self.metrics["collections_discovered"] += 1

                collection_ref = database[collection_name]
                self.collections[attr_name] = collection_ref
                setattr(self, attr_name, collection_ref)

                logger.debug(f"  📄 Mapped: {db_name}.{collection_name} -> {attr_name}")

            logger.info(f"✅ Database '{db_name}': {len(collections)} collections mapped")

        except Exception as e:
            logger.error(f"❌ Failed to map collections for database '{db_name}': {e}")

    def _build_collection_registry(self) -> Dict[str, Dict[str, Any]]:
        """Build a registry of all collections organized by database."""
        registry = {}

        for attr_name, collection in self.collections.items():
            parts = attr_name.split('_', 1)
            if len(parts) == 2:
                db_name, coll_name = parts

                if db_name not in registry:
                    registry[db_name] = {}

                registry[db_name][coll_name] = collection

        return registry

    async def _verify_databases(self):
        """Verify databases and collections are accessible."""
        logger.info("Verifying database and collection accessibility...")

        verification_stats = {
            "databases": 0,
            "collections": 0,
            "total_documents": 0
        }

        try:
            for db_name, database in self.databases.items():
                with PerformanceLogger(logger, f"verify_{db_name}"):
                    collections = await database.list_collection_names()
                    verification_stats["databases"] += 1
                    verification_stats["collections"] += len(collections)

                    if collections:
                        sample_collection = database[collections[0]]
                        count = await sample_collection.estimated_document_count()
                        verification_stats["total_documents"] += count

                    logger.info(f"✅ Database '{db_name}': {len(collections)} collections verified")

        except Exception as e:
            logger.error(f"Database verification failed: {e}", exc_info=True)
            raise DatabaseConnectionError(f"Database verification failed: {e}") from e

        logger.info(f"📊 Verification Summary:")
        logger.info(f"  • Databases: {verification_stats['databases']}")
        logger.info(f"  • Collections: {verification_stats['collections']}")
        logger.info(f"  • Total documents: {verification_stats['total_documents']:,}")

    def _start_health_monitoring(self):
        """Start background health monitoring task"""
        if self._health_check_task and not self._health_check_task.done():
            logger.debug("Health monitoring already running")
            return

        logger.info(f"🔄 Starting database health monitoring (interval: {self.health_check_interval}s)")
        self._health_check_task = asyncio.create_task(self._health_monitor())

    async def _health_monitor(self):
        """Background task to monitor database health"""
        logger.debug("Health monitoring task started")

        try:
            while not self._shutdown_event.is_set():
                try:
                    await asyncio.sleep(self.health_check_interval)

                    if self._shutdown_event.is_set():
                        break

                    await self._perform_health_check()

                except asyncio.CancelledError:
                    logger.info("Health monitoring task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Health check error: {e}", exc_info=True)
                    self.metrics["health_check_failures"] += 1

        except Exception as e:
            logger.error(f"Health monitoring task error: {e}", exc_info=True)
        finally:
            logger.debug("Health monitoring task ended")

    async def _perform_health_check(self):
        """Perform database health check"""
        logger.debug("Performing database health check...")

        try:
            with PerformanceLogger(logger, "health_check"):
                await asyncio.wait_for(
                    self.db_client.admin.command('ping'),
                    timeout=5.0
                )

                if not self._connection_healthy:
                    logger.info("✅ Database connection recovered")

                self._connection_healthy = True
                self.metrics["last_health_check"] = datetime.now(timezone.utc)
                logger.debug("✅ Database health check passed")

        except asyncio.TimeoutError:
            logger.warning("⚠️ Database health check timed out")
            self._connection_healthy = False
            self.metrics["health_check_failures"] += 1

        except Exception as e:
            logger.warning(f"⚠️ Database health check failed: {e}")
            self._connection_healthy = False
            self.metrics["health_check_failures"] += 1

    @asynccontextmanager
    async def operation_context(self, operation_name: str):
        """Context manager for database operations with error tracking"""
        logger.debug(f"Starting database operation: {operation_name}")
        self.metrics["total_operations"] += 1

        try:
            with PerformanceLogger(logger, f"db_operation_{operation_name}"):
                yield
                logger.debug(f"✅ Database operation completed: {operation_name}")
        except Exception as e:
            self.metrics["failed_operations"] += 1
            logger.error(f"❌ Database operation failed: {operation_name} - {e}", exc_info=True)
            raise DatabaseOperationError(f"Operation '{operation_name}' failed: {e}") from e

    async def execute_with_retry(self, operation, operation_name: str, max_retries: int = 3):
        """
        Execute database operation with automatic retry logic
        """
        logger.debug(f"Executing operation with retry: {operation_name}")

        for attempt in range(1, max_retries + 1):
            try:
                async with self.operation_context(f"{operation_name}_attempt_{attempt}"):
                    result = await operation()

                if attempt > 1:
                    logger.info(f"✅ Operation succeeded after {attempt} attempts: {operation_name}")

                return result

            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"⚠️ Operation attempt {attempt} failed, retrying: {operation_name}")
                    await asyncio.sleep(0.5 * attempt)
                else:
                    logger.error(f"❌ Operation failed after {max_retries} attempts: {operation_name}")
                    raise

        raise DatabaseOperationError(f"Operation '{operation_name}' failed after {max_retries} attempts")

    def _log_connection_metrics(self):
        """Log current connection and performance metrics"""
        logger.info("📊 Database Connection Metrics:")
        logger.info(f"  • Connection attempts: {self.metrics['connection_attempts']}")
        logger.info(f"  • Successful connections: {self.metrics['successful_connections']}")
        logger.info(f"  • Failed connections: {self.metrics['failed_connections']}")
        logger.info(f"  • Reconnection attempts: {self.metrics['reconnection_attempts']}")
        logger.info(f"  • Health check failures: {self.metrics['health_check_failures']}")
        logger.info(f"  • Total operations: {self.metrics['total_operations']}")
        logger.info(f"  • Failed operations: {self.metrics['failed_operations']}")
        logger.info(f"  • Databases discovered: {self.metrics['databases_discovered']}")
        logger.info(f"  • Collections discovered: {self.metrics['collections_discovered']}")

        success_rate = (
            (self.metrics['successful_connections'] / self.metrics['connection_attempts'] * 100)
            if self.metrics['connection_attempts'] > 0 else 0
        )
        logger.info(f"  • Connection success rate: {success_rate:.1f}%")

        if self.metrics['total_operations'] > 0:
            operation_success_rate = (
                ((self.metrics['total_operations'] - self.metrics['failed_operations']) /
                 self.metrics['total_operations'] * 100)
            )
            logger.info(f"  • Operation success rate: {operation_success_rate:.1f}%")

    @log_performance("database_reconnection")
    async def reconnect(self) -> bool:
        """
        Attempt to reconnect to the database
        """
        logger.info("🔄 Attempting database reconnection...")
        self.metrics["reconnection_attempts"] += 1

        try:
            if self.db_client:
                logger.debug("Closing existing database connection...")
                self.db_client.close()

            self._initialized = False
            self._connection_healthy = False

            success = await self.initialize(max_retries=3, retry_delay=1.0)

            if success:
                logger.info("✅ Database reconnection successful")
            else:
                logger.error("❌ Database reconnection failed")

            return success

        except Exception as e:
            logger.error(f"❌ Database reconnection error: {e}", exc_info=True)
            return False

    def is_healthy(self) -> bool:
        """
        Check if database connection is healthy
        """
        return self._initialized and self._connection_healthy

    def get_connection_info(self) -> Dict[str, Any]:
        """
        Get current connection information
        """
        return {
            "initialized": self._initialized,
            "healthy": self._connection_healthy,
            "metrics": self.metrics.copy(),
            "config": {
                "max_pool_size": self.max_pool_size,
                "min_pool_size": self.min_pool_size,
                "connection_timeout": self.connection_timeout,
                "server_selection_timeout": self.server_selection_timeout,
            },
            "databases_count": len(self.databases),
            "collections_count": len(self.collections)
        }

    @log_performance("database_status_check")
    async def get_database_status(self) -> Dict[str, Any]:
        """
        Get comprehensive database status information
        """
        logger.debug("Gathering database status information...")

        status = {
            "connection": {
                "initialized": self._initialized,
                "healthy": self._connection_healthy,
                "uri_configured": bool(MONGODB_URI)
            },
            "metrics": self.metrics.copy(),
            "databases": {},
            "server_info": {}
        }

        if self._initialized and self.db_client:
            try:
                with PerformanceLogger(logger, "server_status_check"):
                    server_status = await self.db_client.admin.command("serverStatus")
                    status["server_info"] = {
                        "version": server_status.get("version"),
                        "uptime": server_status.get("uptime"),
                        "connections": server_status.get("connections", {})
                    }

                for db_name, database in self.databases.items():
                    status["databases"][db_name] = {
                        "collections": await database.list_collection_names(),
                        "collection_count": len([c for c in self.collections.keys() if c.startswith(db_name.lower())])
                    }

            except Exception as e:
                logger.error(f"Error gathering database status: {e}")
                status["error"] = str(e)

        logger.debug("Database status information gathered")
        return status

    @log_performance("database_cleanup")
    async def close(self):
        """
        Close database connections with comprehensive cleanup
        """
        logger.info("🔄 Starting database cleanup and connection closure...")

        try:
            with log_context(logger, "database_cleanup", level=20):
                self._shutdown_event.set()

                if self._health_check_task and not self._health_check_task.done():
                    logger.debug("Cancelling health monitoring task...")
                    self._health_check_task.cancel()

                    try:
                        await asyncio.wait_for(self._health_check_task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        logger.debug("Health monitoring task cancelled/timed out")

                if self.db_client:
                    logger.info("Closing MongoDB client connection...")
                    with PerformanceLogger(logger, "mongodb_client_close"):
                        self.db_client.close()
                    logger.info("✅ MongoDB client closed")

                self.db_client = None
                self.databases.clear()
                self.collections.clear()
                self._initialized = False
                self._connection_healthy = False

                from .constants import DATABASE_MAPPINGS, COLLECTION_REGISTRY
                DATABASE_MAPPINGS.clear()
                COLLECTION_REGISTRY.clear()

                logger.info("📊 Final Database Manager Statistics:")
                self._log_connection_metrics()

        except Exception as e:
            logger.error(f"❌ Error during database cleanup: {e}", exc_info=True)
        finally:
            logger.info("✅ Database cleanup completed")

    def setup_shutdown_handlers(self):
        """Setup signal handlers for graceful shutdown"""

        def signal_handler(signum, frame):
            logger.info(f"📡 Received signal {signum}, initiating graceful shutdown...")
            asyncio.create_task(self.close())

        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            logger.info("📡 Shutdown signal handlers registered")
        except Exception as e:
            logger.warning(f"⚠️ Could not register signal handlers: {e}")

    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    def get_collection(self, database_name: str, collection_name: str) -> Any:
        """
        Get a collection reference by database and collection names.
        """
        attr_name = f"{database_name.lower()}_{collection_name.lower()}"

        if attr_name in self.collections:
            return self.collections[attr_name]
        else:
            raise DatabaseOperationError(
                f"Collection '{database_name}.{collection_name}' not found. Available collections: {list(self.collections.keys())}")

    def list_databases(self) -> List[str]:
        """Get list of all discovered databases."""
        return list(self.databases.keys())

    def list_collections(self, database_name: str = None) -> Dict[str, List[str]]:
        """
        Get collections for a specific database or all databases.
        """
        if database_name:
            db_key = database_name.lower()
            collections = [attr.split('_', 1)[1] for attr in self.collections.keys() if attr.startswith(f"{db_key}_")]
            return {database_name: collections}
        else:
            result = {}
            for db_name in self.databases:
                db_key = db_name.lower()
                result[db_name] = [attr.split('_', 1)[1] for attr in self.collections.keys() if
                                   attr.startswith(f"{db_key}_")]
            return result

    async def ensure_database_structure(self):
        """
        Ensure the complete database structure exists for the bot.
        This method creates the main database and all required collections if they don't exist.
        """
        logger.info("🏗️ Ensuring complete database structure...")

        if not self.db_client:
            raise DatabaseConnectionError("Database client not initialized")

        try:
            # Ensure the main database exists by creating a collection in it
            db = self.db_client["discord_forwarding_bot"]

            # Create all required collections
            created_collections = []
            existing_collections = await db.list_collection_names()

            for collection_name in REQUIRED_COLLECTIONS:
                if collection_name not in existing_collections:
                    logger.info(f"Creating collection: discord_forwarding_bot.{collection_name}")
                    await db.create_collection(collection_name)
                    created_collections.append(collection_name)
                else:
                    logger.debug(f"Collection exists: discord_forwarding_bot.{collection_name}")

            # Map the database and all its collections
            await self._map_database_collections("discord_forwarding_bot")

            if created_collections:
                logger.info(f"✅ Created {len(created_collections)} new collections: {created_collections}")

            logger.info("✅ Database structure verification completed")

        except Exception as e:
            logger.error(f"❌ Failed to ensure database structure: {e}", exc_info=True)
            raise DatabaseConnectionError(f"Failed to ensure database structure: {e}") from e