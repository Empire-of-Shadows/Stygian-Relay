import os
import asyncio
import uuid
from typing import Dict, Any, List, Callable, Optional
from datetime import datetime, timezone
import logging
from .exceptions import DatabaseOperationError
from .constants import DEFAULT_BOT_SETTINGS, DEFAULT_GUILD_SETTINGS_TEMPLATE

logger = logging.getLogger("GuildManager")


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

    # ==================== Premium Code Management ====================

    async def generate_premium_code(self, duration_days: int = 30, tier: str = "premium",
                                    created_by: str = None, guild_id: str = None) -> Dict[str, Any]:
        """
        Generate a premium activation code.

        Args:
            duration_days: How long the premium subscription lasts (default: 30 days)
            tier: Premium tier ("premium" or "enterprise")
            created_by: User ID who created the code
            guild_id: Optional guild ID to restrict code to specific guild

        Returns:
            Dictionary with code details including the activation code
        """
        import secrets
        import string

        # Generate a secure random code (format: XXXX-XXXX-XXXX)
        code_parts = []
        for _ in range(3):
            part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
            code_parts.append(part)
        activation_code = '-'.join(code_parts)

        collection = self.db.get_collection("discord_forwarding_bot", "premium_codes")

        code_data = {
            "code": activation_code,
            "tier": tier,
            "duration_days": duration_days,
            "is_redeemed": False,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc),
            "redeemed_by": None,
            "redeemed_at": None,
            "redeemed_guild_id": None,
            "restricted_to_guild": guild_id,  # If set, code can only be used in this guild
            "expires_at": None  # Code doesn't expire until redeemed
        }

        try:
            await collection.insert_one(code_data)
            logger.info(f"✅ Generated premium code: {activation_code} (tier: {tier}, duration: {duration_days} days)")
            return code_data
        except Exception as e:
            logger.error(f"❌ Failed to generate premium code: {e}", exc_info=True)
            raise DatabaseOperationError(f"Failed to generate premium code: {e}") from e

    async def redeem_premium_code(self, code: str, guild_id: str, redeemed_by: str) -> Dict[str, Any]:
        """
        Redeem a premium code for a guild.

        Args:
            code: The activation code to redeem
            guild_id: The guild ID to activate premium for
            redeemed_by: User ID who redeemed the code

        Returns:
            Dictionary with subscription details

        Raises:
            ValueError: If code is invalid, already redeemed, or restricted to another guild
        """
        codes_collection = self.db.get_collection("discord_forwarding_bot", "premium_codes")
        subs_collection = self.db.get_collection("discord_forwarding_bot", "premium_subscriptions")

        # Find the code
        code_data = await codes_collection.find_one({"code": code.upper()})

        if not code_data:
            raise ValueError("Invalid premium code")

        if code_data.get("is_redeemed", False):
            raise ValueError("This code has already been redeemed")

        # Check if code is restricted to a specific guild
        if code_data.get("restricted_to_guild") and code_data["restricted_to_guild"] != guild_id:
            raise ValueError("This code is restricted to a different server")

        # Calculate expiration date
        duration_days = code_data.get("duration_days", 30)
        activated_at = datetime.now(timezone.utc)
        from datetime import timedelta
        expires_at = activated_at + timedelta(days=duration_days)

        # Mark code as redeemed
        await codes_collection.update_one(
            {"code": code.upper()},
            {"$set": {
                "is_redeemed": True,
                "redeemed_by": redeemed_by,
                "redeemed_at": activated_at,
                "redeemed_guild_id": guild_id
            }}
        )

        # Create or update premium subscription
        existing_sub = await subs_collection.find_one({"guild_id": guild_id, "is_active": True})

        if existing_sub:
            # Extend existing subscription
            current_expires = existing_sub.get("expires_at", datetime.now(timezone.utc))

            # Ensure current_expires is timezone-aware (MongoDB returns naive datetimes)
            if current_expires and current_expires.tzinfo is None:
                current_expires = current_expires.replace(tzinfo=timezone.utc)

            # If current subscription is still active, add to it
            if current_expires and current_expires > activated_at:
                new_expires = current_expires + timedelta(days=duration_days)
            else:
                new_expires = expires_at

            await subs_collection.update_one(
                {"guild_id": guild_id, "is_active": True},
                {"$set": {
                    "expires_at": new_expires,
                    "tier": code_data.get("tier", "premium"),
                    "updated_at": activated_at
                }}
            )
            logger.info(f"✅ Extended premium subscription for guild {guild_id} until {new_expires}")
        else:
            # Create new subscription
            subscription_data = {
                "guild_id": guild_id,
                "tier": code_data.get("tier", "premium"),
                "is_active": True,
                "activated_at": activated_at,
                "expires_at": expires_at,
                "activated_by": redeemed_by,
                "activation_code": code.upper(),
                "created_at": activated_at,
                "updated_at": activated_at
            }

            await subs_collection.insert_one(subscription_data)
            logger.info(f"✅ Created premium subscription for guild {guild_id} until {expires_at}")

        # Update guild settings to reflect premium status
        await self.update_guild_settings(guild_id, {"premium_tier": code_data.get("tier", "premium")})

        return {
            "tier": code_data.get("tier", "premium"),
            "expires_at": expires_at,
            "duration_days": duration_days
        }

    async def get_premium_subscription(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """
        Get active premium subscription for a guild.

        Returns:
            Subscription data if active, None otherwise
        """
        collection = self.db.get_collection("discord_forwarding_bot", "premium_subscriptions")
        subscription = await collection.find_one({
            "guild_id": guild_id,
            "is_active": True,
            "expires_at": {"$gt": datetime.now(timezone.utc)}
        })
        return subscription

    async def deactivate_premium(self, guild_id: str) -> bool:
        """
        Deactivate premium subscription for a guild.

        Returns:
            True if subscription was deactivated, False otherwise
        """
        collection = self.db.get_collection("discord_forwarding_bot", "premium_subscriptions")

        result = await collection.update_one(
            {"guild_id": guild_id, "is_active": True},
            {"$set": {
                "is_active": False,
                "updated_at": datetime.now(timezone.utc)
            }}
        )

        if result.modified_count > 0:
            await self.update_guild_settings(guild_id, {"premium_tier": "free"})
            logger.info(f"✅ Deactivated premium subscription for guild {guild_id}")
            return True

        return False

    async def get_premium_code_info(self, code: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a premium code without redeeming it.

        Returns:
            Code data if found, None otherwise
        """
        collection = self.db.get_collection("discord_forwarding_bot", "premium_codes")
        code_data = await collection.find_one({"code": code.upper()})
        return code_data

    async def list_premium_codes(self, created_by: str = None, include_redeemed: bool = False) -> List[Dict[str, Any]]:
        """
        List premium codes with optional filtering.

        Args:
            created_by: Filter by creator user ID
            include_redeemed: Whether to include already redeemed codes

        Returns:
            List of code data dictionaries
        """
        collection = self.db.get_collection("discord_forwarding_bot", "premium_codes")

        query = {}
        if created_by:
            query["created_by"] = created_by
        if not include_redeemed:
            query["is_redeemed"] = False

        cursor = collection.find(query).sort("created_at", -1)
        return await cursor.to_list(length=100)