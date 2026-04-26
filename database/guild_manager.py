import os
import asyncio
import time
import uuid
from typing import Dict, Any, List, Callable, Optional, Tuple
from datetime import datetime, timezone
import logging
import pymongo
from .exceptions import DatabaseOperationError
from .constants import DEFAULT_BOT_SETTINGS, DEFAULT_GUILD_SETTINGS_TEMPLATE

logger = logging.getLogger("GuildManager")


class GuildSettingsCache:
    """In-memory cache for guild settings docs with per-entry TTL."""

    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._store: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    def get(self, guild_id: str) -> Optional[Dict[str, Any]]:
        entry = self._store.get(guild_id)
        if not entry:
            return None
        expiry, data = entry
        if time.monotonic() > expiry:
            self._store.pop(guild_id, None)
            return None
        return data

    def set(self, guild_id: str, data: Dict[str, Any]) -> None:
        self._store[guild_id] = (time.monotonic() + self.ttl, data)

    def invalidate(self, guild_id: str) -> None:
        self._store.pop(guild_id, None)

    def clear(self) -> None:
        self._store.clear()


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

        # Settings cache (5-min TTL) to dedupe redundant fetches in hot paths.
        self.settings_cache = GuildSettingsCache(ttl_seconds=300)

        # Whether MongoDB supports multi-doc transactions (replica set / mongos).
        # Probed on first use; results cached.
        self._transactions_supported: Optional[bool] = None

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

        await self._ensure_indexes()
        await self._probe_transactions()

    async def _ensure_indexes(self):
        """Create indexes used by hot read paths and TTL collections."""
        try:
            db = self.db.db_client["discord_forwarding_bot"]

            await db["guild_settings"].create_index("rules.rule_id")
            await db["guild_settings"].create_index("rules.source_channel_id")

            # message_logs: hot query (guild_id, forwarded_at) + TTL 90 days.
            await db["message_logs"].create_index(
                [("guild_id", pymongo.ASCENDING), ("forwarded_at", pymongo.DESCENDING)]
            )
            await db["message_logs"].create_index(
                "forwarded_at", expireAfterSeconds=90 * 24 * 3600
            )

            await db["premium_codes"].create_index("code", unique=True)
            await db["premium_codes"].create_index("created_by")

            await db["premium_subscriptions"].create_index(
                [("guild_id", pymongo.ASCENDING), ("is_active", pymongo.ASCENDING)]
            )

            # audit_logs: query by (guild_id, created_at) + TTL 365 days.
            await db["audit_logs"].create_index(
                [("guild_id", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)]
            )
            await db["audit_logs"].create_index(
                "created_at", expireAfterSeconds=365 * 24 * 3600
            )

            # runtime_state: ephemeral key/value per guild (branding, daily_warn).
            # TTL 24h on updated_at keeps the collection lean.
            await db["runtime_state"].create_index(
                [("guild_id", pymongo.ASCENDING), ("key", pymongo.ASCENDING)],
                unique=True
            )
            await db["runtime_state"].create_index(
                "updated_at", expireAfterSeconds=24 * 3600
            )

            logger.info("✅ Database indexes verified")
        except Exception as e:
            logger.warning(f"Failed to ensure indexes (non-fatal): {e}")

    async def _probe_transactions(self):
        """Detect whether the connected Mongo deployment supports transactions."""
        try:
            info = await self.db.db_client.admin.command("hello")
            # Replica sets advertise `setName`; sharded clusters report `msg`==`isdbgrid`.
            self._transactions_supported = bool(
                info.get("setName") or info.get("msg") == "isdbgrid"
            )
            if self._transactions_supported:
                logger.info("✅ MongoDB transactions supported")
            else:
                logger.info("ℹ️ MongoDB standalone — transactions disabled, falling back to non-atomic writes")
        except Exception as e:
            self._transactions_supported = False
            logger.warning(f"Transaction probe failed, assuming unsupported: {e}")

    def transactions_supported(self) -> bool:
        return bool(self._transactions_supported)

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

    async def get_guild_settings(self, guild_id: str, use_cache: bool = True) -> Dict[str, Any]:
        """
        Get guild settings or create default if not exists.
        Checks the in-memory cache first; falls through to MongoDB on miss.
        """
        if use_cache:
            cached = self.settings_cache.get(guild_id)
            if cached is not None:
                return cached

        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        settings = await collection.find_one({"_id": guild_id})
        if not settings:
            logger.info(f"Guild {guild_id} not found, creating default settings...")
            settings = await self.setup_new_guild(guild_id, "Unknown Guild")

        if settings is not None:
            self.settings_cache.set(guild_id, settings)
        return settings

    async def update_guild_settings(self, guild_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update top-level fields in a guild's settings document.
        Invalidates the settings cache for this guild.
        """
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        updates["updated_at"] = datetime.now(timezone.utc)
        result = await collection.update_one(
            {"_id": guild_id},
            {"$set": updates}
        )
        self.settings_cache.invalidate(guild_id)
        return result.modified_count > 0

    async def get_all_guilds(self, batch_size: int = 500) -> List[Dict[str, Any]]:
        """
        Get all guilds that have settings in the database.

        Streams in batches to avoid loading the full collection into memory at once.
        """
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        cursor = collection.find({}).batch_size(batch_size)
        guilds: List[Dict[str, Any]] = []
        async for doc in cursor:
            guilds.append(doc)
        return guilds

    async def iter_all_guilds(self, batch_size: int = 500):
        """Async iterator over all guild settings — preferred for large deployments."""
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        cursor = collection.find({}).batch_size(batch_size)
        async for doc in cursor:
            yield doc

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
        Invalidates the cache for the owning guild.
        """
        collection = self.db.get_collection("discord_forwarding_bot", "guild_settings")
        updates["updated_at"] = datetime.now(timezone.utc)

        update_fields = {f"rules.$.{key}": value for key, value in updates.items()}

        # Resolve guild_id first so we can invalidate the right cache key.
        owner = await collection.find_one({"rules.rule_id": rule_id}, {"_id": 1})

        result = await collection.update_one(
            {"rules.rule_id": rule_id},
            {"$set": update_fields}
        )
        if owner:
            self.settings_cache.invalidate(owner["_id"])
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
            self.settings_cache.invalidate(guild_id)
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
        """Check if a guild has an active premium subscription (including lifetime)."""
        collection = self.db.get_collection("discord_forwarding_bot", "premium_subscriptions")

        # Check for lifetime subscription
        lifetime = await collection.find_one({
            "guild_id": guild_id,
            "is_active": True,
            "is_lifetime": True
        })
        if lifetime:
            return True

        # Check for time-limited subscription
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

    # ==================== Runtime state (ephemeral, TTL'd) ====================

    async def get_runtime_state(self, guild_id: str, key: str) -> Optional[datetime]:
        """Return the `updated_at` timestamp for a (guild_id, key) entry, or None."""
        try:
            collection = self.db.get_collection("discord_forwarding_bot", "runtime_state")
            doc = await collection.find_one({"guild_id": guild_id, "key": key})
            if not doc:
                return None
            ts = doc.get("updated_at")
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except Exception as e:
            logger.warning(f"get_runtime_state failed ({guild_id}/{key}): {e}")
            return None

    async def touch_runtime_state(self, guild_id: str, key: str) -> None:
        """Upsert a (guild_id, key) entry with updated_at=now."""
        try:
            collection = self.db.get_collection("discord_forwarding_bot", "runtime_state")
            await collection.update_one(
                {"guild_id": guild_id, "key": key},
                {"$set": {
                    "guild_id": guild_id,
                    "key": key,
                    "updated_at": datetime.now(timezone.utc),
                }},
                upsert=True
            )
        except Exception as e:
            logger.warning(f"touch_runtime_state failed ({guild_id}/{key}): {e}")

    async def add_rule(self, guild_id, rule_name: str, source_channel_id: int,
                                  destination_channel_id: int, enabled: bool = True,
                                  settings: dict = None) -> Tuple[bool, str]:
        """
        Atomically add a forwarding rule, enforcing the per-guild active-rule
        cap from get_guild_limits.

        Returns (success, reason). Reasons: "ok", "limit_reached", "error".
        """
        gid = str(guild_id)
        try:
            limits = await self.get_guild_limits(gid)
            max_rules = int(limits.get("max_rules", 3))

            logger.info(f"Adding forwarding rule '{rule_name}' for guild {gid} (cap={max_rules})")
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

            # Atomic guard: only push if active rule count < cap.
            # $expr with $size lets us count active rules in the same op.
            active_filter = {
                "$expr": {
                    "$lt": [
                        {"$size": {
                            "$filter": {
                                "input": {"$ifNull": ["$rules", []]},
                                "as": "r",
                                "cond": {"$eq": ["$$r.is_active", True]}
                            }
                        }},
                        max_rules
                    ]
                }
            }

            result = await collection.update_one(
                {"_id": gid, **active_filter},
                {"$push": {"rules": rule_data},
                 "$set": {"updated_at": datetime.now(timezone.utc)}}
            )

            if result.modified_count > 0:
                self.settings_cache.invalidate(gid)
                logger.info(f"✅ Added rule '{rule_name}' for guild {gid}")
                return True, "ok"

            # Either the doc doesn't exist, or the cap was reached. Disambiguate.
            existing = await collection.find_one({"_id": gid}, {"rules": 1})
            if existing is None:
                # First-time guild — create defaults and retry once (still atomic on retry).
                logger.warning(f"Guild {gid} not found. Creating defaults and retrying rule addition.")
                await self.get_guild_settings(gid)
                retry = await collection.update_one(
                    {"_id": gid, **active_filter},
                    {"$push": {"rules": rule_data},
                     "$set": {"updated_at": datetime.now(timezone.utc)}}
                )
                if retry.modified_count > 0:
                    self.settings_cache.invalidate(gid)
                    return True, "ok"
                # Still failed — must be cap.
                return False, "limit_reached"

            active_count = sum(1 for r in existing.get("rules", []) if r.get("is_active"))
            if active_count >= max_rules:
                logger.info(f"Rule cap reached for guild {gid} ({active_count}/{max_rules})")
                return False, "limit_reached"

            logger.error(f"add_rule update reported no modification for guild {gid} despite cap not reached")
            return False, "error"
        except Exception as e:
            logger.error(f"❌ Error adding forwarding rule: {e}", exc_info=True)
            return False, "error"

    # ==================== Premium Code Management ====================

    async def generate_premium_code(self, duration_days: int = 30,
                                    created_by: str = None, guild_id: str = None,
                                    is_lifetime: bool = False,
                                    code_validity_days: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate a premium activation code.

        code_validity_days: how long the unredeemed code is valid. Defaults to
        bot_settings.code_default_validity_days (90). 0 or None disables expiry.
        """
        import secrets
        import string

        code_parts = []
        for _ in range(3):
            part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
            code_parts.append(part)
        activation_code = '-'.join(code_parts)

        collection = self.db.get_collection("discord_forwarding_bot", "premium_codes")

        # Resolve default validity from bot_settings if caller didn't override.
        if code_validity_days is None:
            try:
                bot_settings = await self.db.get_collection(
                    "discord_forwarding_bot", "bot_settings"
                ).find_one({"_id": "global_config"})
                code_validity_days = (bot_settings or {}).get("code_default_validity_days", 90)
            except Exception:
                code_validity_days = 90

        from datetime import timedelta
        now = datetime.now(timezone.utc)
        expires_at_unredeemed = (
            now + timedelta(days=int(code_validity_days)) if code_validity_days else None
        )

        code_data = {
            "code": activation_code,
            "duration_days": duration_days if not is_lifetime else None,
            "is_lifetime": is_lifetime,
            "is_redeemed": False,
            "created_by": created_by,
            "created_at": now,
            "redeemed_by": None,
            "redeemed_at": None,
            "redeemed_guild_id": None,
            "restricted_to_guild": guild_id,
            "expires_at": None,
            "expires_at_unredeemed": expires_at_unredeemed,
        }

        try:
            await collection.insert_one(code_data)
            duration_str = "LIFETIME" if is_lifetime else f"{duration_days} days"
            validity_str = f"unredeemed expires {expires_at_unredeemed.isoformat()}" if expires_at_unredeemed else "no unredeemed expiry"
            logger.info(f"✅ Generated premium code: {activation_code} (duration: {duration_str}, {validity_str})")
            return code_data
        except Exception as e:
            logger.error(f"❌ Failed to generate premium code: {e}", exc_info=True)
            raise DatabaseOperationError(f"Failed to generate premium code: {e}") from e

    async def redeem_premium_code(self, code: str, guild_id: str, redeemed_by: str) -> Dict[str, Any]:
        """
        Redeem a premium code for a guild. Atomic where MongoDB supports
        multi-doc transactions; otherwise the claim is atomic but the
        subscription upsert is best-effort.

        Raises ValueError for any user-actionable failure (bad format,
        invalid/expired/redeemed code, guild restriction, lifetime downgrade).
        """
        import re
        from datetime import timedelta

        normalized_code = code.upper().strip()
        if not re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", normalized_code):
            raise ValueError("Invalid code format. Expected XXXX-XXXX-XXXX.")

        codes_collection = self.db.get_collection("discord_forwarding_bot", "premium_codes")
        subs_collection = self.db.get_collection("discord_forwarding_bot", "premium_subscriptions")

        activated_at = datetime.now(timezone.utc)

        # Peek for accurate error messages + expiry compute before atomic claim.
        code_data = await codes_collection.find_one({"code": normalized_code})

        if not code_data:
            raise ValueError("Invalid premium code")

        if code_data.get("is_redeemed", False):
            raise ValueError("This code has already been redeemed")

        if code_data.get("restricted_to_guild") and code_data["restricted_to_guild"] != guild_id:
            raise ValueError("This code is restricted to a different server")

        # Unredeemed-expiry check.
        unredeemed_expiry = code_data.get("expires_at_unredeemed")
        if unredeemed_expiry:
            if unredeemed_expiry.tzinfo is None:
                unredeemed_expiry = unredeemed_expiry.replace(tzinfo=timezone.utc)
            if unredeemed_expiry < activated_at:
                raise ValueError("This code has expired and can no longer be redeemed")

        is_lifetime = code_data.get("is_lifetime", False)

        if is_lifetime:
            expires_at = None
            duration_days = None
        else:
            duration_days = code_data.get("duration_days", 30)
            expires_at = activated_at + timedelta(days=duration_days)

        # Pre-check existing subscription so we can reject lifetime->time-limited
        # downgrades BEFORE consuming the code.
        existing_sub_peek = await subs_collection.find_one({"guild_id": guild_id, "is_active": True})
        if existing_sub_peek and existing_sub_peek.get("is_lifetime") and not is_lifetime:
            raise ValueError("This server already has a lifetime subscription and cannot be downgraded")

        async def _do_redeem(session=None):
            kw = {"session": session} if session else {}

            claim = await codes_collection.find_one_and_update(
                {"code": normalized_code, "is_redeemed": False},
                {"$set": {
                    "is_redeemed": True,
                    "redeemed_by": redeemed_by,
                    "redeemed_at": activated_at,
                    "redeemed_guild_id": guild_id
                }},
                **kw
            )
            if claim is None:
                raise ValueError("This code has already been redeemed")

            existing_sub = await subs_collection.find_one(
                {"guild_id": guild_id, "is_active": True}, **kw
            )

            if existing_sub:
                if is_lifetime:
                    await subs_collection.update_one(
                        {"guild_id": guild_id, "is_active": True},
                        {"$set": {
                            "expires_at": None,
                            "is_lifetime": True,
                            "updated_at": activated_at
                        }},
                        **kw
                    )
                    logger.info(f"✅ Upgraded to LIFETIME premium subscription for guild {guild_id}")
                else:
                    current_expires = existing_sub.get("expires_at") or activated_at
                    if current_expires and current_expires.tzinfo is None:
                        current_expires = current_expires.replace(tzinfo=timezone.utc)
                    new_expires = (
                        current_expires + timedelta(days=duration_days)
                        if current_expires > activated_at
                        else expires_at
                    )
                    await subs_collection.update_one(
                        {"guild_id": guild_id, "is_active": True},
                        {"$set": {"expires_at": new_expires, "updated_at": activated_at}},
                        **kw
                    )
                    logger.info(f"✅ Extended premium subscription for guild {guild_id} until {new_expires}")
            else:
                await subs_collection.insert_one({
                    "guild_id": guild_id,
                    "is_active": True,
                    "is_lifetime": is_lifetime,
                    "activated_at": activated_at,
                    "expires_at": expires_at,
                    "activated_by": redeemed_by,
                    "activation_code": normalized_code,
                    "created_at": activated_at,
                    "updated_at": activated_at
                }, **kw)
                duration_str = "LIFETIME" if is_lifetime else f"until {expires_at}"
                logger.info(f"✅ Created premium subscription for guild {guild_id} {duration_str}")

        if self.transactions_supported():
            try:
                async with await self.db.db_client.start_session() as session:
                    async with session.start_transaction():
                        await _do_redeem(session=session)
            except ValueError:
                raise
            except Exception as e:
                logger.warning(f"Transaction redeem failed, falling back to non-atomic: {e}")
                await _do_redeem()
        else:
            await _do_redeem()

        return {
            "expires_at": expires_at,
            "duration_days": duration_days,
            "is_lifetime": is_lifetime
        }

    async def get_premium_subscription(self, guild_id: str) -> Optional[Dict[str, Any]]:
        """
        Get active premium subscription for a guild (including lifetime).

        Returns:
            Subscription data if active, None otherwise
        """
        collection = self.db.get_collection("discord_forwarding_bot", "premium_subscriptions")

        # Check for lifetime subscription first
        subscription = await collection.find_one({
            "guild_id": guild_id,
            "is_active": True,
            "is_lifetime": True
        })
        if subscription:
            return subscription

        # Check for time-limited subscription
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