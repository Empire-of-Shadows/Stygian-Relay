"""
Guild management and event handling for the Discord Forwarding Bot.
"""
import os
import asyncio
from typing import Dict, Any, List, Callable, Optional
from datetime import datetime, timezone
from logger.logger_setup import get_logger
from .exceptions import DatabaseOperationError
from .constants import DEFAULT_BOT_SETTINGS, DEFAULT_GUILD_SETTINGS_TEMPLATE

logger = get_logger("GuildManager", level=20, json_format=False, colored_console=True)


class GuildManager:
    """
    Manages guild settings, auto-setup, and event handling for the Discord bot.
    """

    def __init__(self, database_core):
        self.db = database_core
        self._guild_join_listeners: List[Callable] = []
        self._guild_leave_listeners: List[Callable] = []

        self.metrics = {
            "guilds_auto_configured": 0,
            "guilds_removed": 0,
            "welcome_messages_sent": 0,
            "setup_errors": 0
        }

    def add_guild_join_listener(self, callback: Callable):
        """Add a listener for guild join events."""
        self._guild_join_listeners.append(callback)
        logger.debug(f"Added guild join listener: {callback.__name__}")

    def add_guild_leave_listener(self, callback: Callable):
        """Add a listener for guild leave events."""
        self._guild_leave_listeners.append(callback)
        logger.debug(f"Added guild leave listener: {callback.__name__}")

    async def _notify_guild_join(self, guild_id: str, guild_name: str):
        """Notify all guild join listeners."""
        if not self._guild_join_listeners:
            return

        logger.info(f"Notifying {len(self._guild_join_listeners)} listeners about guild join: {guild_name} ({guild_id})")

        for listener in self._guild_join_listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(guild_id, guild_name)
                else:
                    listener(guild_id, guild_name)
            except Exception as e:
                logger.error(f"Error in guild join listener {listener.__name__}: {e}")

    async def _notify_guild_leave(self, guild_id: str, guild_name: str):
        """Notify all guild leave listeners."""
        if not self._guild_leave_listeners:
            return

        logger.info(f"Notifying {len(self._guild_leave_listeners)} listeners about guild leave: {guild_name} ({guild_id})")

        for listener in self._guild_leave_listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    await listener(guild_id, guild_name)
                else:
                    listener(guild_id, guild_name)
            except Exception as e:
                logger.error(f"Error in guild leave listener {listener.__name__}: {e}")

    async def initialize_default_settings(self):
        """Initialize default bot settings if they don't exist."""
        logger.info("⚙️ Initializing default bot settings...")

        bot_settings = self.db.get_collection("discord_forwarding_bot", "bot_settings")

        default_settings = DEFAULT_BOT_SETTINGS.copy()
        default_settings["_id"] = "global_config"
        default_settings["master_admin_id"] = os.getenv("BOT_OWNER_ID", "")
        default_settings["created_at"] = datetime.now(timezone.utc)
        default_settings["updated_at"] = datetime.now(timezone.utc)

        existing = await bot_settings.find_one({"_id": "global_config"})
        if not existing:
            await bot_settings.insert_one(default_settings)
            logger.info("✅ Default bot settings initialized")
        else:
            update_fields = {}
            for key, value in default_settings.items():
                if key not in existing:
                    update_fields[key] = value

            if update_fields:
                await bot_settings.update_one(
                    {"_id": "global_config"},
                    {"$set": update_fields}
                )
                logger.info(f"✅ Updated bot settings with new fields: {list(update_fields.keys())}")
            else:
                logger.info("✅ Bot settings already exist and are up-to-date")

    async def setup_new_guild(self, guild_id: str, guild_name: str) -> Dict[str, Any]:
        """
        Automatically set up default settings for a new guild.
        """
        logger.info(f"🏰 Setting up default settings for new guild: {guild_name} ({guild_id})")

        try:
            default_settings = DEFAULT_GUILD_SETTINGS_TEMPLATE.copy()
            default_settings["_id"] = guild_id
            default_settings["guild_name"] = guild_name
            default_settings["auto_setup_complete"] = True
            default_settings["setup_date"] = datetime.now(timezone.utc)
            default_settings["created_at"] = datetime.now(timezone.utc)
            default_settings["updated_at"] = datetime.now(timezone.utc)

            collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")

            existing = await collection.find_one({"_id": guild_id})
            if existing:
                logger.info(f"ℹ️ Guild {guild_name} already exists in database, updating...")
                await collection.update_one(
                    {"_id": guild_id},
                    {"$set": {
                        "guild_name": guild_name,
                        "updated_at": datetime.now(timezone.utc),
                        "auto_setup_complete": True
                    }}
                )
                return await collection.find_one({"_id": guild_id})
            else:
                await collection.insert_one(default_settings)
                self.metrics["guilds_auto_configured"] += 1
                logger.info(f"✅ Successfully set up default settings for guild: {guild_name}")

                await self._notify_guild_join(guild_id, guild_name)

                return default_settings

        except Exception as e:
            self.metrics["setup_errors"] += 1
            logger.error(f"❌ Failed to set up guild {guild_name}: {e}")
            raise DatabaseOperationError(f"Failed to set up guild: {e}") from e

    async def remove_guild_data(self, guild_id: str, guild_name: str) -> bool:
        """
        Remove all data for a guild that the bot left.
        """
        logger.info(f"🗑️ Removing data for guild: {guild_name} ({guild_id})")

        try:
            db = self.db.db_client["discord_forwarding_bot"]

            guild_settings = db["guild_settings"]
            await guild_settings.delete_one({"_id": guild_id})

            forwarding_rules = db["forwarding_rules"]
            await forwarding_rules.update_many(
                {"guild_id": guild_id},
                {"$set": {"is_active": False, "deactivated_at": datetime.now(timezone.utc)}}
            )

            user_permissions = db["user_permissions"]
            await user_permissions.delete_many({"guild_id": guild_id})

            await self._notify_guild_leave(guild_id, guild_name)

            self.metrics["guilds_removed"] += 1
            logger.info(f"✅ Successfully removed data for guild: {guild_name}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to remove guild data for {guild_name}: {e}")
            return False

    async def get_guild_settings(self, guild_id: str) -> Dict[str, Any]:
        """Get guild settings or create default if not exists."""
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")

        settings = await collection.find_one({"_id": guild_id})
        if not settings:
            logger.info(f"Guild {guild_id} not found, creating default settings...")
            return await self.setup_new_guild(guild_id, "Unknown Guild")

        return settings

    async def update_guild_settings(self, guild_id: str, updates: Dict[str, Any]) -> bool:
        """Update guild settings."""
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")

        updates["updated_at"] = datetime.now(timezone.utc)
        result = await collection.update_one(
            {"_id": guild_id},
            {"$set": updates}
        )

        return result.modified_count > 0

    async def get_all_guilds(self) -> List[Dict[str, Any]]:
        """
        Get all guilds that have settings in the database.
        """
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        cursor = collection.find({})
        return await cursor.to_list(length=None)

    async def get_guild_count(self) -> int:
        """
        Get total number of guilds in the database.
        """
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        return await collection.count_documents({})

    async def create_forwarding_rule(self, rule_data: Dict[str, Any]) -> str:
        """Create a new forwarding rule."""
        collection = self.db.get_collection("discord_forwarding_bot", "forwarding_rules")

        rule_data["created_at"] = datetime.now(timezone.utc)
        rule_data["updated_at"] = datetime.now(timezone.utc)

        result = await collection.insert_one(rule_data)
        return str(result.inserted_id)

    async def get_guild_forwarding_rules(self, guild_id: str) -> List[Dict[str, Any]]:
        """Get all forwarding rules for a guild."""
        collection = self.db.get_collection("discord_forwarding_bot", "forwarding_rules")

        cursor = collection.find({"guild_id": guild_id, "is_active": True})
        return await cursor.to_list(length=None)

    async def get_rule_by_id(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific forwarding rule by ID."""
        collection = self.db.get_collection("discord_forwarding_bot", "forwarding_rules")
        return await collection.find_one({"_id": rule_id})

    async def update_forwarding_rule(self, rule_id: str, updates: Dict[str, Any]) -> bool:
        """Update a forwarding rule."""
        collection = self.db.get_collection("discord_forwarding_bot", "forwarding_rules")

        updates["updated_at"] = datetime.now(timezone.utc)
        result = await collection.update_one(
            {"_id": rule_id},
            {"$set": updates}
        )

        return result.modified_count > 0

    async def delete_forwarding_rule(self, rule_id: str) -> bool:
        """Soft delete a forwarding rule."""
        return await self.update_forwarding_rule(rule_id, {"is_active": False})

    async def log_forwarded_message(self, log_data: Dict[str, Any]):
        """Log a forwarded message for tracking."""
        collection = self.db.get_collection("discord_forwarding_bot", "message_logs")

        log_data["forwarded_at"] = datetime.now(timezone.utc)
        await collection.insert_one(log_data)

    async def get_daily_message_count(self, guild_id: str, date: datetime = None) -> int:
        """Get number of messages forwarded today for a guild."""
        if date is None:
            date = datetime.now(timezone.utc)

        start_of_day = datetime(date.year, date.month, date.day)

        collection = self.db.get_collection("discord_forwarding_bot", "message_logs")

        count = await collection.count_documents({
            "guild_id": guild_id,
            "forwarded_at": {"$gte": start_of_day},
            "success": True
        })

        return count

    async def is_premium_guild(self, guild_id: str) -> bool:
        """Check if a guild has premium subscription."""
        collection = self.db.get_collection("discord_forwarding_bot", "premium_subscriptions")

        premium = await collection.find_one({
            "guild_id": guild_id,
            "is_active": True,
            "expires_at": {"$gt": datetime.now(timezone.utc)}
        })

        return premium is not None

    async def get_guild_limits(self, guild_id: str) -> Dict[str, Any]:
        """Get guild limits based on premium status."""
        bot_settings = await self.db.get_collection("discord_forwarding_bot", "bot_settings").find_one({"_id": "global_config"})
        is_premium = await self.is_premium_guild(guild_id)

        return {
            "max_rules": bot_settings.get("max_rules_premium" if is_premium else "max_rules_per_guild", 20 if is_premium else 3),
            "daily_limit": bot_settings.get("premium_tier_daily_limit" if is_premium else "free_tier_daily_limit", 5000 if is_premium else 100),
            "is_premium": is_premium
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Get guild management metrics."""
        return self.metrics.copy()

    async def add_forwarding_rule(self, guild_id: int, rule_name: str, source_channel_id: int,
                                  destination_channel_id: int, enabled: bool = True,
                                  settings: dict = None) -> bool:
        """
        Add a new forwarding rule for a guild.

        Args:
            guild_id: The guild ID
            rule_name: Name of the rule
            source_channel_id: Channel to watch
            destination_channel_id: Channel to forward to
            enabled: Whether the rule is enabled
            settings: Additional rule settings

        Returns:
            bool: True if successful, False otherwise
        """
        from logger.logger_setup import get_logger
        logger = get_logger("GuildManager", level=20, json_format=False, colored_console=True)

        try:
            logger.info(f"Adding forwarding rule '{rule_name}' for guild {guild_id}")

            rule_data = {
                "guild_id": str(guild_id),
                "rule_name": rule_name,
                "source_channel_id": source_channel_id,
                "destination_channel_id": destination_channel_id,
                "is_active": enabled,
                "settings": settings or {},
            }

            rule_id = await self.create_forwarding_rule(rule_data)

            if rule_id:
                logger.info(f"✅ Successfully added rule '{rule_name}' for guild {guild_id} with id {rule_id}")
                return True
            else:
                logger.warning(f"Rule creation returned no ID for guild {guild_id}")
                return False

        except Exception as e:
            logger.error(f"❌ Error adding forwarding rule: {e}", exc_info=True)
            return False