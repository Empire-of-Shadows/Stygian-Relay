# Global database mapping storage
# This dictionary stores the database name for each bot instance.
DATABASE_MAPPINGS = {}

# This dictionary stores the collection name for each data type.
COLLECTION_REGISTRY = {}

# Required collections for the Discord Forwarding Bot
# These collections are essential for the bot's operation and will be created if they don't exist.
REQUIRED_COLLECTIONS = {
    'guild_settings',
    'message_logs',
    'error_logs',
    'rate_limits',
    'bot_settings',
    'user_permissions',
    'premium_subscriptions',
    'premium_codes'
}

# Default bot settings
# These settings are used to configure the bot's global behavior.
DEFAULT_BOT_SETTINGS = {
    "_id": "global_config",
    "max_rules_per_guild": 3,
    "max_rules_premium": 20,
    "rate_limit_per_channel": 50,
    "default_prefix": "!forward",
    "maintenance_mode": False,
    "premium_enabled": True,
    "free_tier_daily_limit": 100,
    "premium_tier_daily_limit": 5000,
    "auto_setup_new_guilds": True,
    "welcome_message_enabled": True
}

# Default guild settings template
# This template is used to create the settings for a new guild.
DEFAULT_GUILD_SETTINGS_TEMPLATE = {
    "master_log_channel_id": None,
    "is_enabled": True,
    "premium_tier": "free",
    "auto_setup_complete": True,
    "features": {
        "forwarding_enabled": True,
        "logging_enabled": False,
        "auto_cleanup": True,
        "notify_on_error": True
    },
    "limits": {
        "max_rules": 3,
        "daily_messages": 100,
        "rule_creation_enabled": True
    },
    "rules": [
    ]
}