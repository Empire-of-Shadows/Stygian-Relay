"""
Stygian-Relay Discord bot — main orchestrator.

Unified startup sequence (mirrors Ecom / TheHost / TheCodex / ImperialReminder):
    1. Load env
    2. setup_logging  → error reporter + root logging
    3. main(): banner + Python/discord.py versions
    4. _async_main(): install signal handlers → init database (db_core) → start error
       notifier loop → start health endpoint (50005)
    5. start_services(): bot.start raced against shutdown_event
    6. on_ready (idempotent via _init_done):
       Systems Initialization → Cog Loading → Command Sync → Status Setup
    7. shutdown_handler(): health → error notifier → database → bot
"""

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

import discord
from dotenv import load_dotenv

from startup.bot import get_bot, set_error_notifier, initialize_existing_guilds
from startup.sync import load_cogs, log_all_commands
from startup.phases import log_startup_summary, startup_phase
from logger.log_config import setup_logging
from status.idle import rotate_status
from database import db_core, guild_manager
from health_endpoint import initialize_health_server, stop_health_server

_env_dir = Path(__file__).parent / "docker"
if (_env_dir / ".env").exists():
    load_dotenv(_env_dir / ".env")
else:
    load_dotenv()
# Dev override: docker/.env.local (gitignored) wins when present.
load_dotenv(_env_dir / ".env.local", override=True)

# --- Configuration ---
import os  # noqa: E402

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

APPLICATION_NAME = "discord-bot-relay"
HEALTH_PORT = 50005

bot = get_bot()

error_notifier = setup_logging(
    app_name=APPLICATION_NAME,
    bot_instance=bot,
    default_level=logging.INFO,
)
set_error_notifier(error_notifier)

logger = logging.getLogger("main")

# Background task handle for the error-notifier loop (started in _async_main).
_error_task: "asyncio.Task | None" = None


async def on_ready():
    """
    Handle bot readiness. Idempotent across gateway reconnects via _init_done.

    On first ready: scan existing guilds, load cogs, sync commands, set status,
    log startup summary. On reconnect: just refresh presence and return.
    """
    if getattr(bot, "_init_done", False):
        try:
            await bot.change_presence(status=discord.Status.online)
            logger.info("🔁 Reconnect detected — presence refreshed, init skipped.")
        except Exception as e:
            logger.error(f"❌ Error refreshing presence on reconnect: {e}")
        return

    logger.info(f"🚀 Bot logged in as {bot.user}")
    logger.info(
        f"📊 Connected to {len(bot.guilds)} guilds with "
        f"{sum(g.member_count or 0 for g in bot.guilds)} total members"
    )

    try:
        async with startup_phase("Database Attachment"):
            await initialize_existing_guilds()
    except Exception:
        logger.error("❌ Error during database attachment", exc_info=True)

    try:
        async with startup_phase("Cog Loading"):
            await load_cogs()
    except Exception as cog_error:
        logger.error(f"❌ Error during cog loading: {cog_error}", exc_info=True)

    try:
        async with startup_phase("Command Sync"):
            synced_global = await bot.tree.sync()
            logger.info(f"🔄 Resynced global commands: {len(synced_global)} registered.")
    except Exception as sync_error:
        logger.error(f"❌ Error during command sync: {sync_error}", exc_info=True)

    try:
        async with startup_phase("Status Setup"):
            await bot.change_presence(status=discord.Status.online)
            if not rotate_status.is_running():
                rotate_status.start()
    except Exception as status_error:
        logger.error(f"❌ Error during status setup: {status_error}", exc_info=True)

    log_startup_summary()
    logger.info("🎉 Bot is fully online and operational!")

    try:
        await log_all_commands(bot)
    except Exception as cmd_log_error:
        logger.error(f"❌ Error logging commands: {cmd_log_error}")

    bot._init_done = True


bot.event(on_ready)


async def shutdown_handler():
    """Graceful shutdown: health → error notifier → database → bot."""
    shutdown_start = time.perf_counter()
    logger.info("🛑 Initiating graceful shutdown...")

    try:
        stop_health_server()
    except Exception as e:
        logger.error(f"❌ Error stopping health server: {e}")

    if _error_task and not _error_task.done():
        _error_task.cancel()
    try:
        if error_notifier:
            await error_notifier.shutdown()
            logger.info("✅ Error notifier shut down")
    except Exception as e:
        logger.error(f"❌ Error shutting down error notifier: {e}")

    try:
        logger.info("🔄 Closing database connections...")
        await db_core.close()
        logger.info("✅ Database connections closed")
    except Exception as e:
        logger.error(f"❌ Error during database cleanup: {e}")

    try:
        if not bot.is_closed():
            await bot.close()
            logger.info("✅ Bot connection closed")
    except Exception as shutdown_error:
        logger.error(f"❌ Error during bot shutdown: {shutdown_error}")

    duration = time.perf_counter() - shutdown_start
    logger.info(f"🏁 Graceful shutdown completed in {duration:.2f}s")


async def start_services(shutdown_event: asyncio.Event):
    """Start the bot and await either its exit or a shutdown signal."""
    bot_task = asyncio.create_task(bot.start(DISCORD_TOKEN), name="bot_task")
    shutdown_wait = asyncio.create_task(shutdown_event.wait(), name="shutdown_wait")

    try:
        done, pending = await asyncio.wait(
            [bot_task, shutdown_wait], return_when=asyncio.FIRST_COMPLETED
        )

        if shutdown_wait in done:
            logger.info("🛑 Shutdown signal received, stopping services...")
        elif bot_task in done:
            try:
                bot_task.result()
            except Exception as e:
                logger.error(f"💥 Bot stopped unexpectedly: {e}")

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    except asyncio.CancelledError:
        logger.info("🔄 Services cancelled during shutdown")
    finally:
        if bot_task and not bot_task.done():
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
        await shutdown_handler()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, shutdown_event: asyncio.Event):
    """Install SIGINT/SIGTERM handlers (graceful no-op on Windows)."""
    def _signal_handler(sig_name: str):
        logger.info(f"📡 Received {sig_name} signal, initiating shutdown...")
        shutdown_event.set()

    signals_to_handle = []
    if hasattr(signal, "SIGINT"):
        signals_to_handle.append(signal.SIGINT)
    if hasattr(signal, "SIGTERM"):
        signals_to_handle.append(signal.SIGTERM)

    for sig in signals_to_handle:
        try:
            loop.add_signal_handler(sig, _signal_handler, sig.name)
        except NotImplementedError:
            pass
        except Exception as e:
            logger.warning(f"⚠️ Failed to register signal handler for {sig.name}: {e}")


async def _async_main(shutdown_event: asyncio.Event):
    """Async entry: install signals, init DB, start error loop + health, start services."""
    global _error_task

    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop, shutdown_event)

    try:
        logger.info("🔄 Initializing database manager...")
        success = await db_core.initialize()
        if not success:
            raise RuntimeError("Database initialization returned failure")
        await guild_manager.initialize_default_settings()
        logger.info("✅ Database manager initialized successfully")
    except Exception as e:
        logger.critical(f"💥 Failed to initialize database manager: {e}")
        raise

    if error_notifier:
        _error_task = asyncio.create_task(error_notifier.start_loop(), name="error_notifier_task")
        logger.info("✅ Error notification loop started")

    try:
        initialize_health_server(port=HEALTH_PORT, bot=bot, db_manager=db_core)
        logger.info("✅ Health check endpoint initialized")
    except Exception as e:
        logger.error(f"❌ Failed to start health endpoint: {e}")

    await start_services(shutdown_event)


def main():
    """Process entry point."""
    logger.info(f"=== Starting {APPLICATION_NAME} ===")
    logger.info(f"🐍 Python version: {sys.version}")
    logger.info(f"🤖 Discord.py version: {discord.__version__}")

    if not DISCORD_TOKEN or not DISCORD_TOKEN.strip():
        logger.error("❌ DISCORD_TOKEN is missing or empty. Set it before starting the bot.")
        sys.exit(1)

    shutdown_event = asyncio.Event()

    try:
        asyncio.run(_async_main(shutdown_event))
    except KeyboardInterrupt:
        logger.info("⌨️ Keyboard interrupt received.")
    except Exception:
        logger.critical("💥 Fatal error occurred in main execution", exc_info=True)
        raise
    finally:
        logger.info(f"=== {APPLICATION_NAME} shutdown complete ===")


if __name__ == "__main__":
    main()
