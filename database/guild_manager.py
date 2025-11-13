import os
import asyncio
import uuid
from typing import Dict, Any, List, Callable, Optional
from datetime import datetime, timezone
from logger.logger_setup import get_logger
from .exceptions import DatabaseOperationError
from .constants import DEFAULT_BOT_SETTINGS, DEFAULT_GUILD_SETTINGS_TEMPLATE

logger = get_logger("GuildManager", level=20, json_format=False, colored_console=True)


class GuildManager:
    """
    Manages all database operations related to guilds, including settings,
    rules, and logging. It also provides an observer pattern for guild events.
    """

    def __init__(self, database_core):
        self.db = database_core
        # Observer pattern listeners: other parts of the bot can subscribe to these events.
        self._guild_join_listeners: List[Callable] = []
        self._guild_leave_listeners: List[Callable] = []

        self.metrics = {
            "guilds_auto_configured": 0,
            "guilds_removed": 0,
            "welcome_messages_sent": 0,
            "setup_errors": 0
        }

    def add_guild_join_listener(self, callback: Callable):
        """
        Add a listener for guild join events.
        The callback will be called with the guild_id and guild_name as arguments.
        """
        self._guild_join_listeners.append(callback)
        logger.debug(f"Added guild join listener: {callback.__name__}")

    def add_guild_leave_listener(self, callback: Callable):
        """
        Add a listener for guild leave events.
        The callback will be called with the guild_id and guild_name as arguments.
        """
        self._guild_leave_listeners.append(callback)
        logger.debug(f"Added guild leave listener: {callback.__name__}")

    async def _notify_guild_join(self, guild_id: str, guild_name: str):
        """Internal method to notify all registered listeners about a guild join."""
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
        """Internal method to notify all registered listeners about a guild leave."""
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
        """
        Ensures the global bot settings document exists in the database.
        If it doesn't exist, it's created. If it exists but is missing fields
        from the default template, it's updated.
        """
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
            # Check for and add any missing fields from the default settings.
            update_fields = {key: value for key, value in default_settings.items() if key not in existing}
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
        Sets up default settings for a new guild. If the guild already exists,
        it updates the name and ensures it's marked as auto-setup complete.
        """
        logger.info(f"🏰 Setting up default settings for new guild: {guild_name} ({guild_id})")
        try:
            collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
            existing = await collection.find_one({"_id": guild_id})

            if existing:
                logger.info(f"ℹ️ Guild {guild_name} already exists in database, ensuring it is up-to-date...")
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
                default_settings = DEFAULT_GUILD_SETTINGS_TEMPLATE.copy()
                default_settings.update({
                    "_id": guild_id,
                    "guild_name": guild_name,
                    "auto_setup_complete": True,
                    "setup_date": datetime.now(timezone.utc),
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                })
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
        Removes all data associated with a guild from the database.
        This includes guild settings and user permissions.
        """
        logger.info(f"🗑️ Removing data for guild: {guild_name} ({guild_id})")
        try:
            db = self.db.db_client["discord_forwarding_bot"]
            await db["guild_settings"].delete_one({"_id": guild_id})
            await db["user_permissions"].delete_many({"guild_id": guild_id})
            await self._notify_guild_leave(guild_id, guild_name)
            self.metrics["guilds_removed"] += 1
            logger.info(f"✅ Successfully removed data for guild: {guild_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to remove guild data for {guild_name}: {e}")
            return False

    async def get_guild_settings(self, guild_id: str) -> Dict[str, Any]:
        """
        Get guild settings or create default if not exists.
        This is the primary method for accessing guild settings.
        """
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        settings = await collection.find_one({"_id": guild_id})
        if not settings:
            logger.info(f"Guild {guild_id} not found, creating default settings...")
            return await self.setup_new_guild(guild_id, "Unknown Guild")
        return settings

    async def update_guild_settings(self, guild_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update top-level fields in a guild's settings document.
        This is used for general settings updates.
        """
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        updates["updated_at"] = datetime.now(timezone.utc)
        result = await collection.update_one(
            {"_id": guild_id},
            {"$set": updates}
        )
        return result.modified_count > 0

    async def get_all_guilds(self) -> List[Dict[str, Any]]:
        """Get all guilds that have settings in the database."""
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        cursor = collection.find({})
        return await cursor.to_list(length=None)

    async def get_all_rules(self, guild_id: str) -> List[Dict[str, Any]]:
        """Get all forwarding rules for a specific guild."""
        logger.debug(f"Fetching all forwarding rules for guild {guild_id}")
        return await self.get_guild_rules(str(guild_id))

    async def get_guild_count(self) -> int:
        """Get total number of guilds in the database."""
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        return await collection.count_documents({})

    async def get_guild_rules(self, guild_id: str) -> List[Dict[str, Any]]:
        """Get all rules for a guild."""
        guild_settings = await self.get_guild_settings(guild_id)
        return guild_settings.get("rules", [])

    async def get_rule_by_id(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific forwarding rule by its unique ID."""
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        result = await collection.find_one({"rules.rule_id": rule_id})
        if result:
            for rule in result.get("rules", []):
                if rule.get("rule_id") == rule_id:
                    return rule
        return None

    async def update_rule(self, rule_id: str, updates: Dict[str, Any]) -> bool:
        """
        Updates fields of a specific rule within a guild's `rules` array.
        """
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        updates["updated_at"] = datetime.now(timezone.utc)

        # This uses the '$' positional operator to update the specific element
        # in the 'rules' array that was matched by the query filter.
        update_fields = {f"rules.$.{key}": value for key, value in updates.items()}

        result = await collection.update_one(
            {"rules.rule_id": rule_id},
            {"$set": update_fields}
        )
        return result.modified_count > 0

    async def delete_rule(self, rule_id: str) -> bool:
        """Soft deletes a rule by setting its `is_active` flag to False."""
        return await self.update_rule(rule_id, {"is_active": False})

    async def permanently_delete_rule(self, guild_id: str, rule_id: str) -> bool:
        """Permanently deletes a rule by removing it from the database."""
        try:
            collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
            result = await collection.update_one(
                {"_id": guild_id},
                {"$pull": {"rules": {"rule_id": rule_id}}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error permanently deleting rule {rule_id} from guild {guild_id}: {e}", exc_info=True)
            return False

    async def log_forwarded_message(self, log_data: Dict[str, Any]):
        """Log a forwarded message for tracking and rate-limiting."""
        collection = self.db.get_collection("discord_forwarding_bot", "message_logs")
        log_data["forwarded_at"] = datetime.now(timezone.utc)
        await collection.insert_one(log_data)

    async def get_daily_message_count(self, guild_id: str, date: datetime = None) -> int:
        """Get number of messages forwarded today for a guild."""
        if date is None:
            date = datetime.now(timezone.utc)
        start_of_day = datetime(date.year, date.month, date.day, tzinfo=timezone.utc)

        collection = self.db.get_collection("discord_forwarding_bot", "message_logs")
        count = await collection.count_documents({
            "guild_id": guild_id,
            "forwarded_at": {"$gte": start_of_day},
            "success": True
        })
        return count

    async def is_premium_guild(self, guild_id: str) -> bool:
        """Check if a guild has an active premium subscription."""
        collection = self.db.get_collection("discord_forwarding_bot", "premium_subscriptions")
        premium = await collection.find_one({
            "guild_id": guild_id,
            "is_active": True,
            "expires_at": {"$gt": datetime.now(timezone.utc)}
        })
        return premium is not None

    async def get_guild_limits(self, guild_id: str) -> Dict[str, Any]:
        """
        Get guild limits based on premium status.
        This method checks the bot's global settings and the guild's premium status
        to determine the limits for the guild.
        """
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

    async def add_rule(self, guild_id: int, rule_name: str, source_channel_id: int,
                                  destination_channel_id: int, enabled: bool = True,
                                  settings: dict = None) -> bool:
        """
        Adds a new forwarding rule to a guild's settings. If the guild document
        does not exist, it will be created first.
        """
        try:
            logger.info(f"Adding forwarding rule '{rule_name}' for guild {guild_id}")
            rule_data = {
                "rule_id": str(uuid.uuid4()),
                "rule_name": rule_name,
                "source_channel_id": source_channel_id,
                "destination_channel_id": destination_channel_id,
                "is_active": enabled,
                "settings": settings or {},
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc)
            }

            collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
            result = await collection.update_one(
                {"_id": str(guild_id)},
                {"$push": {"rules": rule_data}, "$set": {"updated_at": datetime.now(timezone.utc)}}
            )

            if result.modified_count > 0:
                logger.info(f"✅ Successfully added rule '{rule_name}' for guild {guild_id}")
                return True
            else:
                # If the update failed, it might be because the guild document doesn't exist.
                # We'll create it and try adding the rule again.
                logger.warning(f"Guild {guild_id} not found. Creating settings and retrying rule addition.")
                guild_settings = await self.get_guild_settings(str(guild_id))
                if guild_settings:
                    result = await collection.update_one(
                        {"_id": str(guild_id)},
                        {"$push": {"rules": rule_data}, "$set": {"updated_at": datetime.now(timezone.utc)}}
                    )
                    if result.modified_count > 0:
                        logger.info(f"✅ Successfully added rule '{rule_name}' for guild {guild_id} after creating settings.")
                        return True
                logger.error(f"Failed to add rule for guild {guild_id} even after attempting to create settings.")
                return False
        except Exception as e:
            logger.error(f"❌ Error adding forwarding rule: {e}", exc_info=True)
            return False