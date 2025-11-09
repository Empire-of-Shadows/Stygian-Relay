from typing import Dict, Any

from .core import DatabaseCore
from .guild_manager import GuildManager
from .exceptions import DatabaseConnectionError, DatabaseOperationError
from .constants import DATABASE_MAPPINGS, COLLECTION_REGISTRY

# Global database manager instance
db_core = DatabaseCore(auto_discover=True)
guild_manager = GuildManager(db_core)

# Convenience functions
async def ensure_database_connection() -> bool:
    """
    Ensure database connection is established and healthy.
    This function should be called before any database operation.
    """
    if not db_core.is_healthy():
        from logger.logger_setup import get_logger
        logger = get_logger("Database", level=20, json_format=False, colored_console=True)
        logger.info("Database not healthy, attempting to initialize/reconnect...")
        return await db_core.initialize()
    return True

async def setup_new_guild(guild_id: str, guild_name: str) -> Dict[str, Any]:
    """
    Convenience function to setup a new guild.
    This function will create a new guild document in the database with default settings.
    """
    if not await ensure_database_connection():
        raise DatabaseConnectionError("Could not establish database connection")

    return await guild_manager.setup_new_guild(guild_id, guild_name)

async def get_guild_settings(guild_id: str) -> Dict[str, Any]:
    """
    Convenience function to get guild settings.
    This function will return the guild's settings document from the database.
    If the guild does not exist, it will be created with default settings.
    """
    if not await ensure_database_connection():
        raise DatabaseConnectionError("Could not establish database connection")

    return await guild_manager.get_guild_settings(guild_id)

# Export main components
__all__ = [
    'DatabaseCore',
    'GuildManager',
    'DatabaseConnectionError',
    'DatabaseOperationError',
    'db_core',
    'guild_manager',
    'ensure_database_connection',
    'setup_new_guild',
    'get_guild_settings',
    'DATABASE_MAPPINGS',
    'COLLECTION_REGISTRY'
]