"""
Stygian-Relay Discord bot — main orchestrator.

Unified startup sequence (mirrors Ecom / TheHost / TheCodex / ImperialReminder):
    1. Load env from docker/.env (+ .env.local override)
    2. setup_application_logging (shared storage.logging) + root sink + email ErrorReporter
    3. main(): banner + Python/discord.py versions
    4. _async_main(): install signal handlers → init database (db_manager) → start error
       notifier loop → start health endpoint (50013)
    5. start_services(): bot.start raced against shutdown_event
    6. on_ready (idempotent via _init_done):
       Database Attachment → Cog Loading → Command Sync → Status Setup
    7. shutdown_handler(): health → error notifier → database → bot
"""

import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path

# Load env from docker/.env (with root .env fallback) before importing anything that reads env.
from dotenv import load_dotenv
_env_dir = Path(__file__).parent / "docker"
if (_env_dir / ".env").exists():
    load_dotenv(_env_dir / ".env")
else:
    load_dotenv()
# Dev override: docker/.env.local (gitignored) wins when present.
load_dotenv(_env_dir / ".env.local", override=True)

import discord

from startup.bot import get_bot, set_error_notifier, initialize_existing_guilds
from startup.sync import load_cogs, attach_databases, log_all_commands
from startup.phases import log_startup_summary, startup_phase
from storage.logging import setup_application_logging
from logger.error_reporter import ErrorReporter, ReportingHandler
from status.idle import rotate_status
from storage.settings.manager import db_manager
from health_endpoint import initialize_health_server, stop_health_server

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

APPLICATION_NAME = "discord-bot-relay"
HEALTH_PORT = 50013

bot = get_bot()


def _configure_logging():
    """Adopt the shared storage.logging engine while keeping relay's email ErrorReporter.

    storage.logging configures per-named loggers (get_logger) and leaves the root logger
    unconfigured. Relay's code base (including the ported domain layer) logs through plain
    ``logging.getLogger(...)`` in many modules, so we also configure the ROOT logger with the
    engine's console+file formatters — every module emits in the identical line format used by
    the sibling bots. get_logger-created loggers (the app/performance loggers + the vendored
    engine) own their handlers, so we stop them propagating to root to avoid double lines.

    Returns the email ErrorReporter (or None when EMAIL/PASSWORD are unset).
    """
    from logging.handlers import RotatingFileHandler

    from storage.logging.factory import LoggerManager
    from storage.logging.formatters import ColoredConsoleFormatter, IndentedFormatter

    # App logger + JSON performance logger + the shared
    # "Application logging initialized for: discord-bot-relay" line (sibling parity).
    setup_application_logging(
        app_name=APPLICATION_NAME,
        log_level=logging.INFO,
        log_dir="logs",
        enable_performance_logging=True,
        max_file_size=20 * 1024 * 1024,
        backup_count=10,
    )

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Root logger: catch-all sink for the bot's plain logging.getLogger(...) modules.
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(ColoredConsoleFormatter(fmt))
    root.addHandler(console)

    os.makedirs("logs", exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join("logs", f"{APPLICATION_NAME}.log"),
        maxBytes=20 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(IndentedFormatter(fmt))
    root.addHandler(file_handler)

    # get_logger loggers carry their own handlers; stop them double-printing through root.
    for _named in LoggerManager().get_all_loggers().values():
        _named.propagate = False

    # Quiet noisy driver loggers (match sibling behavior).
    for _noisy in (
        "pymongo", "pymongo.connection", "pymongo.serverSelection",
        "pymongo.topology", "motor",
    ):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    # Relay's email ErrorReporter stays a bot-owned add-on: route ERROR+ records to it.
    notifier = None
    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")
    if email and password:
        notifier = ErrorReporter(email=email, app_password=password, bot_instance=bot)
        reporting_handler = ReportingHandler(notifier=notifier)
        reporting_handler.setLevel(logging.ERROR)
        root.addHandler(reporting_handler)
        logging.info("Error reporter initialized and handler added.")
    else:
        logging.warning("Email or password not found; email error reporting disabled.")
    return notifier


error_notifier = _configure_logging()
set_error_notifier(error_notifier)

logger = logging.getLogger("main")

# Background task handle for the error-notifier loop (started in _async_main).
_error_task: "asyncio.Task | None" = None


async def on_ready():
    """
    Handle bot readiness. Idempotent across gateway reconnects via _init_done.

    On first ready: attach storage managers, scan existing guilds, load cogs, sync commands,
    set status, log startup summary. On reconnect: just refresh presence and return.
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
            await attach_databases()
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
        await db_manager.close()
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
        await db_manager.initialize()
        logger.info("✅ Database manager initialized successfully")
    except Exception as e:
        logger.critical(f"💥 Failed to initialize database manager: {e}")
        raise

    if error_notifier:
        _error_task = asyncio.create_task(error_notifier.start_loop(), name="error_notifier_task")
        logger.info("✅ Error notification loop started")

    try:
        initialize_health_server(port=HEALTH_PORT, bot=bot, db_manager=db_manager)
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
