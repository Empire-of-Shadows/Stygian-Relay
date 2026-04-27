import discord
from discord.ext import commands

from database import db_core, guild_manager, audit_log

error_notifier = None


def set_error_notifier(notifier):
    """Sets the global error notifier instance from main.py."""
    global error_notifier
    error_notifier = notifier


# Define intents required by the bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.AutoShardedBot(
    command_prefix=commands.when_mentioned,
    intents=intents,
    help_command=None,
    case_insensitive=True,
)


@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    print(f'✅ Logged in as {bot.user} (ID: {bot.user.id})')
    print(f'📊 Connected to {len(bot.guilds)} guilds')
    print('------')

    try:
        if not db_core.is_healthy():
            success = await db_core.initialize()
            if success:
                print('✅ Database connection established')
                await initialize_existing_guilds()
            else:
                print('❌ Failed to connect to database')
        else:
            print('✅ Database connection already healthy')

    except Exception as e:
        print(f'❌ Database connection error: {e}')


async def initialize_existing_guilds():
    """Initialize database settings for all guilds the bot is currently in."""
    print('🏰 Initializing settings for existing guilds...')

    initialized_count = 0
    for guild in bot.guilds:
        try:
            await guild_manager.setup_new_guild(str(guild.id), guild.name)
            initialized_count += 1
        except Exception as e:
            print(f'❌ Failed to initialize guild {guild.name}: {e}')

    print(f'✅ Initialized settings for {initialized_count}/{len(bot.guilds)} guilds')


@bot.event
async def on_guild_join(guild):
    """Called when the bot joins a new guild."""
    print(f'🤖 Bot joined guild: {guild.name} (ID: {guild.id})')

    try:
        settings = await guild_manager.setup_new_guild(str(guild.id), guild.name)
        print(f'✅ Auto-configured guild: {guild.name}')

        await send_welcome_message(guild, settings)

    except Exception as e:
        print(f'❌ Failed to setup guild {guild.name}: {e}')


@bot.event
async def on_guild_role_delete(role):
    """If the deleted role was the manager_role_id, clear it."""
    try:
        guild_id = str(role.guild.id)
        settings = await guild_manager.get_guild_settings(guild_id)
        manager_role_id = settings.get("manager_role_id")
        if manager_role_id and str(manager_role_id) == str(role.id):
            await guild_manager.update_guild_settings(guild_id, {"manager_role_id": None})
            await audit_log.log(
                "settings", guild_id, "system",
                "auto_clear_manager_role",
                {"prior_role_id": str(role.id), "reason": "role deleted"}
            )
            print(f"🧹 Cleared dangling manager_role_id {role.id} for guild {role.guild.name}")
    except Exception as e:
        print(f"❌ Error in on_guild_role_delete: {e}")


@bot.event
async def on_guild_channel_delete(channel):
    """
    Clear master_log_channel_id and deactivate rules referencing this channel.

    Cross-guild rules can live in a different guild than the deleted channel,
    so the rule scan goes through `find_rules_referencing_channel` which
    queries every guild_settings doc by indexed channel id rather than
    only the deleted channel's own guild.
    """
    try:
        local_guild_id = str(channel.guild.id)
        settings = await guild_manager.get_guild_settings(local_guild_id)

        # Clear log channel if it pointed here. (Always local — log channels
        # are stored per-guild and never reference foreign channels.)
        log_channel_id = settings.get("master_log_channel_id")
        if log_channel_id and str(log_channel_id) == str(channel.id):
            await guild_manager.update_guild_settings(local_guild_id, {"master_log_channel_id": None})
            await audit_log.log(
                "settings", local_guild_id, "system",
                "auto_clear_log_channel",
                {"prior_channel_id": str(channel.id), "reason": "channel deleted"}
            )

        # Cross-guild rule scan: a destination in this guild may belong to a
        # rule stored under a different source guild's settings doc.
        affected = await guild_manager.find_rules_referencing_channel(channel.id)
        for owning_guild_id, rule_id in affected:
            await guild_manager.update_rule(rule_id, {"is_active": False})
            await audit_log.log(
                "rule", owning_guild_id, "system",
                "auto_deactivate_rule",
                {"rule_id": rule_id, "reason": "referenced channel deleted",
                 "channel_id": str(channel.id),
                 "deleted_in_guild_id": local_guild_id}
            )

        if affected:
            print(
                f"🧹 Deactivated {len(affected)} rule(s) referencing channel {channel.id} "
                f"(deleted in {channel.guild.name})"
            )
    except Exception as e:
        print(f"❌ Error in on_guild_channel_delete: {e}")


@bot.event
async def on_guild_remove(guild):
    """Called when the bot leaves a guild."""
    print(f'👋 Bot left guild: {guild.name} (ID: {guild.id})')

    try:
        success = await guild_manager.remove_guild_data(str(guild.id), guild.name)
        if success:
            print(f'✅ Removed data for guild: {guild.name}')
        else:
            print(f'⚠️ Partial cleanup for guild: {guild.name}')

    except Exception as e:
        print(f'❌ Error removing guild data for {guild.name}: {e}')


async def send_welcome_message(guild, settings):
    """Sends a welcome message to a new guild if enabled."""
    try:
        bot_settings_collection = db_core.get_collection("discord_forwarding_bot", "bot_settings")
        bot_settings = await bot_settings_collection.find_one({"_id": "global_config"})

        if not bot_settings or not bot_settings.get("welcome_message_enabled", True):
            return

        # Find a suitable channel to send the welcome message.
        # Prioritize the system channel, but fall back to the first available text channel.
        channel = guild.system_channel
        if not (channel and channel.permissions_for(guild.me).send_messages):
            for text_channel in guild.text_channels:
                if text_channel.permissions_for(guild.me).send_messages:
                    channel = text_channel
                    break
            else:
                print(f"⚠️ No suitable channel found for welcome message in {guild.name}")
                return

        embed = discord.Embed(
            title="🤖 Stygian-Relay",
            description="Thanks for adding me to your server! I can forward messages between channels with advanced filtering.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="Getting Started",
            value="Use `/setup` to configure your first forwarding rule or `/help` to see all commands.",
            inline=False
        )
        embed.add_field(
            name="Key Features",
            value="• Cross-channel message forwarding\n• Advanced content filtering\n• Media and link support\n• Premium features available",
            inline=False
        )
        embed.set_footer(text="Use /help for more information")

        await channel.send(embed=embed)
        print(f'📝 Sent welcome message to guild: {guild.name}')

    except Exception as e:
        print(f'❌ Failed to send welcome message to {guild.name}: {e}')


@bot.event
async def close():
    """Called when the bot is shutting down."""
    print('🔄 Bot is shutting down. Cleaning up...')

    try:
        if db_core.is_healthy():
            await db_core.close()
            print('✅ Database connection closed')
    except Exception as e:
        print(f'❌ Error closing database connection: {e}')

    if error_notifier:
        try:
            await error_notifier.shutdown()
            print('✅ Error notifier shut down')
        except Exception as e:
            print(f'❌ Error shutting down error notifier: {e}')

    print('👋 Bot shutdown complete')


def get_bot():
    return bot