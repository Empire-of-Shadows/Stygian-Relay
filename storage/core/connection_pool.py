# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
import time
from typing import Dict, Any, Optional

from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure

from ..logging_compat import get_logger

logger = get_logger("ConnectionPool")

class ConnectionPool:
    """Manages MongoDB connection pooling and health monitoring."""

    def __init__(self, uri: str, pool_config: Dict[str, Any] = None, connection_name: str = "default"):
        self.uri = uri
        self.connection_name = connection_name
        self.config = pool_config or {
            'maxPoolSize': 100,
            'minPoolSize': 10,
            'maxIdleTimeMS': 30000,
            'serverSelectionTimeoutMS': 5000,
            'connectTimeoutMS': 10000,
            'socketTimeoutMS': 20000,
            'retryWrites': True,
            'retryReads': True
        }
        self.client: Optional[AsyncMongoClient] = None
        self._health_check_interval = 30  # seconds
        self._last_health_check = 0

    async def initialize(self) -> AsyncMongoClient:
        """Initialize the connection pool."""
        if self.client is None:
            logger.info(f"Initializing MongoDB connection pool for {self.connection_name}...")
            self.client = AsyncMongoClient(self.uri, **self.config)
            await self._health_check()
            logger.info(f"MongoDB connection pool for {self.connection_name} initialized successfully")
        return self.client

    async def _health_check(self):
        """Perform health check on the connection."""
        try:
            await self.client.admin.command('ping')
            self._last_health_check = time.time()
            logger.debug(f"MongoDB health check passed for {self.connection_name}")
        except Exception as e:
            logger.error(f"MongoDB health check failed for {self.connection_name}: {e}")
            raise ConnectionFailure(f"Database health check failed for {self.connection_name}")

    async def get_client(self) -> AsyncMongoClient:
        """Get a healthy client connection."""
        if self.client is None:
            await self.initialize()

        # Perform periodic health checks
        if time.time() - self._last_health_check > self._health_check_interval:
            await self._health_check()

        return self.client

    async def close(self):
        """Close the connection pool."""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info(f"MongoDB connection pool for {self.connection_name} closed")
