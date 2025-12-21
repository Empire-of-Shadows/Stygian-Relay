import traceback
import discord
import os
import asyncio
import logging
from dotenv import load_dotenv
from bot import get_bot, set_error_notifier
from core.sync import load_cogs
from logger.log_config import setup_logging
from logger.error_reporter import ErrorReporter
from logger.reporting_types import Severity
from status.idle import rotate_status
from database import db_core, guild_manager

load_dotenv()

# --- Configuration ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
EMAIL_ADDRESS = os.getenv("EMAIL")
EMAIL_PASSWORD = os.getenv("PASSWORD")
BOT_OWNER_ID = os.getenv("BOT_OWNER_ID")

LOG_DIR = "log"
os.makedirs(LOG_DIR, exist_ok=True)

# --- Setup Logging ---
app_logger = logging.getLogger()

bot = get_bot()

error_notifier = setup_logging(
    app_name="StygianRelay",
    bot_instance=bot,
    default_level=logging.INFO
)
set_error_notifier(error_notifier)


async def initialize_database():
    """Initialize the database connection and setup."""
    try:
        app_logger.info("Initializing database connection...")

        success = await db_core.initialize()
        if not success:
            app_logger.error("Failed to initialize database connection")
            return False

        await guild_manager.initialize_default_settings()

        app_logger.info("✅ Database initialization completed successfully")
        return True

    except Exception as e:
        app_logger.error(f"❌ Database initialization failed: {e}", exc_info=True)
        return False


async def shutdown_database():
    """Cleanly shutdown database connections."""
    try:
        app_logger.info("Shutting down database connections...")
        await db_core.close()
        app_logger.info("✅ Database connections closed")
    except Exception as e:
        app_logger.error(f"❌ Error during database shutdown: {e}")


async def main():
    db_initialized = await initialize_database()
    if not db_initialized:
        app_logger.critical("Database initialization failed. Bot cannot start without database.")
        return

    if not DISCORD_TOKEN:
        app_logger.critical("DISCORD_TOKEN not found in .env file. Please set it to run the bot.")
        print("Error: DISCORD_TOKEN not found. Please set it in the .env file.")
        return

    try:
        app_logger.info("Starting Discord bot...")

        rotate_status.start()
        app_logger.info("Status rotation task started.")

        if error_notifier:
            # Start the error notification loop after the event loop is running
            asyncio.create_task(error_notifier.start_loop())
            app_logger.info("Error notification loop started.")

        await load_cogs()
        app_logger.info("Cogs loaded successfully")

        app_logger.info("Connecting to Discord...")
        await bot.start(DISCORD_TOKEN)

    except discord.LoginFailure:
        app_logger.critical("Failed to log in to Discord. Check your DISCORD_TOKEN.")
        print("Error: Failed to log in. Check your DISCORD_TOKEN.")
    except discord.PrivilegedIntentsRequired:
        app_logger.critical("Privileged intents required. Enable them in the Discord Developer Portal.")
        print("Error: Privileged intents required. Enable them in the Discord Developer Portal.")
    except KeyboardInterrupt:
        app_logger.info("Bot shutdown requested by user (Ctrl+C)")
    except Exception as e:
        app_logger.critical(f"An unexpected error occurred during bot startup: {e}", exc_info=True)
        print(f"Error during bot startup: {e}")
        traceback.print_exc()
    finally:
        await shutdown_bot()


async def shutdown_bot():
    """Cleanly shutdown the bot and all services."""
    app_logger.info("Initiating bot shutdown...")

    try:
        if not bot.is_closed():
            await bot.close()
            app_logger.info("✅ Discord connection closed")

        await shutdown_database()

        if error_notifier:
            try:
                await error_notifier.shutdown()
                app_logger.info("✅ Error notifier shut down")
            except Exception as e:
                app_logger.error(f"Error shutting down error notifier: {e}")

        app_logger.info("👋 Bot shutdown completed successfully")

    except Exception as e:
        app_logger.error(f"❌ Error during bot shutdown: {e}", exc_info=True)


def handle_exception(loop, context):
    """Global exception handler for the asyncio event loop."""
    exception = context.get('exception')
    if exception:
        app_logger.critical(f"Unhandled exception in event loop: {exception}", exc_info=True)

        if error_notifier:
            asyncio.create_task(
                error_notifier.notify_error(
                    "Event Loop Error",
                    str(exception),
                    "Event Loop"
                )
            )
    else:
        app_logger.error(f"Event loop error: {context['message']}")


if __name__ == '__main__':
    # Create a new event loop to avoid deprecation warning in Python 3.10+
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(handle_exception)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        app_logger.info("Bot shutdown requested by user (Ctrl+C)")
    except Exception as e:
        app_logger.critical(f"Fatal error in main: {e}", exc_info=True)
        print(f"Fatal error: {e}")
        traceback.print_exc()
    finally:
        if not loop.is_closed():
            loop.run_until_complete(shutdown_bot())
            loop.close()
        app_logger.info("Application terminated")