import discord
from discord.ext import commands
import asyncio

from database import db_core, guild_manager, ensure_database_connection, get_guild_settings

error_notifier = None


def set_error_notifier(notifier):
    """Sets the global error notifier instance from main.py."""
    global error_notifier
    error_notifier = notifier


async def get_prefix(bot, message):
    """A callable to dynamically retrieve the command prefix for a guild."""
    if not message.guild:
        return commands.when_mentioned_or("!")(bot, message)

    try:
        if not await ensure_database_connection():
            return commands.when_mentioned_or("!")(bot, message)

        settings = await get_guild_settings(str(message.guild.id))
        prefix = settings.get("command_prefix", "!")
        return commands.when_mentioned_or(prefix)(bot, message)

    except Exception as e:
        print(f"Error getting prefix for guild {message.guild.id}: {e}")
        return commands.when_mentioned_or("!")(bot, message)


# Define intents required by the bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.AutoShardedBot(
    command_prefix=get_prefix,
    intents=intents,
    help_command=None,
    case_insensitive=True
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
            title="🤖 Stygian Relay",
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


@bot.event
async def on_command_error(ctx, error):
    """Global error handler for commands."""
    if isinstance(error, commands.CommandNotFound):
        return

    print(f'❌ Command error in {ctx.guild.name if ctx.guild else "DM"}: {error}')

    if isinstance(error, commands.BotMissingPermissions):
        await ctx.send("❌ I don't have the required permissions to execute this command.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have the required permissions to use this command.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏰ This command is on cooldown. Try again in {error.retry_after:.1f} seconds.")
    else:
        await ctx.send("❌ An error occurred while executing this command.")

        if error_notifier:
            try:
                await error_notifier.notify_error(
                    f"Command error in {ctx.guild.name if ctx.guild else 'DM'}",
                    str(error),
                    ctx.command.name if ctx.command else "Unknown"
                )
            except Exception as e:
                print(f'❌ Failed to notify error: {e}')


@bot.command(name="ping")
async def ping_command(ctx):
    """Checks bot latency and database connection status."""
    latency = round(bot.latency * 1000)
    db_healthy = db_core.is_healthy()
    db_status = "✅ Connected" if db_healthy else "❌ Disconnected"

    try:
        settings = await get_guild_settings(str(ctx.guild.id))
        prefix = settings.get("command_prefix", "!")
        guild_status = "✅ Configured"
    except Exception as e:
        prefix = "!"
        guild_status = f"❌ Error: {e}"

    embed = discord.Embed(
        title="🏓 Pong!",
        color=discord.Color.blue()
    )
    embed.add_field(name="Bot Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Database", value=db_status, inline=True)
    embed.add_field(name="Guild Settings", value=guild_status, inline=True)
    embed.add_field(name="Prefix", value=prefix, inline=True)
    embed.add_field(name="Shards", value=bot.shard_count, inline=True)
    embed.add_field(name="Guilds", value=len(bot.guilds), inline=True)

    await ctx.send(embed=embed)


@bot.command(name="sync")
@commands.is_owner()
async def sync_commands(ctx):
    """Syncs slash commands globally. Owner only."""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Successfully synced {len(synced)} slash commands globally!")
        print(f"Synced {len(synced)} slash commands globally")

        if synced:
            command_names = [cmd.name for cmd in synced]
            print(f"Synced commands: {', '.join(command_names)}")

    except Exception as e:
        await ctx.send(f"❌ Failed to sync commands: {e}")
        print(f"Failed to sync commands: {e}")


def get_bot():
    return bot