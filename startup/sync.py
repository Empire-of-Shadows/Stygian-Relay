"""
Startup sync seam for Stygian-Relay (bot-owned, NOT vendored).

The generic cog-loading machinery (discovery, priority/parallel loading, attribute
attachment, command-table logging - including the guild-scoped command tables) lives in
the vendored runtime engine at ``startup/loader.py``. This file supplies only what is
relay-specific: the cog discovery roots, the owner-only ``load_cogs`` reload command,
and ``attach_databases()`` (which managers exist and how they wire onto the bot).
``Relay.py`` keeps importing ``load_cogs`` / ``attach_databases`` /
``log_all_commands`` from here.
"""

from discord.ext import commands

from startup.bot import bot, s
from startup.loader import (  # noqa: F401 - log_all_commands is re-exported for Relay.py
    attach_attribute,
    load_cogs as _engine_load_cogs,
    log_all_commands,
)
from storage.log import get_logger

logger = get_logger("Sync")


# Cog discovery roots. Priority cogs load first (sequential) for ordering-sensitive
# setup; the rest load in parallel for a faster boot.
COG_DIRECTORIES = ["commands", "admin"]
PRIORITY_COG_DIRECTORIES: list[str] = []


async def load_cogs():
    """Load all cogs from the configured directories (engine loader)."""
    await _engine_load_cogs(bot, COG_DIRECTORIES, PRIORITY_COG_DIRECTORIES)


@bot.command(name="load_cogs", help="Loads all cogs in the COG_DIRECTORIES list.")
@commands.is_owner()
async def load_cogs_command(ctx):
    """Owner-only runtime cog (re)load."""
    await ctx.send("Loading cogs...")
    await load_cogs()
    await ctx.send("Cogs loaded successfully.")


async def attach_databases():
    """
    Attach relay's storage managers onto the bot so cogs can read them via
    `bot.guild_manager` etc., and emit the shared "database attachment process" boot block
    (identical in shape to the sibling EoS bots).

    The engine `db_manager` is already initialized by Relay.py before on_ready; the
    `initialize()` call here is an idempotent no-op kept for the log line.
    """
    success_logs = [f"{s}🔄 Starting database attachment process...\n"]
    failed_logs = []

    try:
        # Shared engine DatabaseManager (pooled pymongo connections).
        from storage.settings.collections import db_manager
        try:
            await db_manager.initialize()
            result, is_success = await attach_attribute(bot, "db_manager", db_manager)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as db_error:
            failed_logs.append(f"{s}❌ db_manager → Error: {db_error}\n")
            raise  # Can't continue without db_manager

        from storage.bot_specific.relay import guild_manager, audit_log, premium_manager

        # GuildManager - ensure global bot settings + indexes + one-shot migrations (idempotent).
        try:
            await guild_manager.initialize_default_settings()
            result, is_success = await attach_attribute(bot, "guild_manager", guild_manager)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as gm_error:
            failed_logs.append(f"{s}❌ guild_manager → Error: {gm_error}\n")
            raise  # Cogs depend on guild_manager

        # PremiumManager - entitlement indexes + one-shot legacy-subscription migration
        # (idempotent). The premium cog attaches later and drives events/reconcile.
        try:
            await premium_manager.initialize()
            result, is_success = await attach_attribute(bot, "premium_manager", premium_manager)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as pm_error:
            failed_logs.append(f"{s}❌ premium_manager → Error: {pm_error}\n")

        # AuditLog - records guild/premium/setting actions to the audit_logs collection.
        try:
            result, is_success = await attach_attribute(bot, "audit_log", audit_log)
            (success_logs if is_success else failed_logs).append(result)
        except Exception as audit_error:
            failed_logs.append(f"{s}❌ audit_log → Error: {audit_error}\n")
    except Exception as e:
        failed_logs.append(f"{s}❌ Encountered a critical error during database attachment → {e}\n")

    if failed_logs:
        failed_logs.insert(0, f"{s}❌ Failed to attach the following attributes:\n")
    if success_logs:
        success_logs.insert(1 if failed_logs else 0, f"{s}✅ Successfully attached the following attributes:\n")

    final_log = failed_logs + success_logs
    logger.info("\n" + "".join(final_log) + f"{s}✅ Database attachment process completed.\n")
