"""
Constants and configuration for database operations.
"""

# Global database mapping storage
DATABASE_MAPPINGS = {}
COLLECTION_REGISTRY = {}

# Required collections for the Discord Forwarding Bot
REQUIRED_COLLECTIONS = {
    'guild_settings',
    'forwarding_rules',
    'message_logs',
    'error_logs',
    'rate_limits',
    'bot_settings',
    'user_permissions',
    'premium_subscriptions'
}

# Default bot settings
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
    "rules": {
    }
}