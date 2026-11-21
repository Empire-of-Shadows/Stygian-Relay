"""Global slash-command error handler for Stygian-Relay.

Until 2026-11-07 relay had none: an exception escaping a command body (a Mongo
outage under ``/premium status``, say) was logged by discord.py's default
``tree.on_error`` and the member was left with "The application did not respond"
or a reply that never arrived after the defer, and no idea where to report it.

This cog takes over ``bot.tree.on_error``. It still logs every unexpected error
with its traceback (what the default did), and now answers the member with one
EPHEMERAL message:

  - expected refusals (cooldown, missing permissions, server-only, a failed
    check) get a plain reason and no support link;
  - anything unexpected gets the generic failure text ending with the
    support-server line from ``commands/help/help_content.py``.

A command with its own error handler (``@cmd.error``, an overridden
``Group.on_error`` or ``cog_app_command_error``) has already answered by the time
discord.py calls ``tree.on_error``, so the member reply is skipped there; the log
line is still written.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from commands.common.interaction_errors import unexpected_failure_message
from storage.log import get_logger

logger = get_logger("ErrorHandler")


def _perm_names(perms) -> str:
    return ", ".join(p.replace("_", " ").title() for p in perms)


class ErrorHandler(commands.Cog):
    """Answers the member once for any slash-command error nothing else handled."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Kept so unloading the cog restores the handler that was there before.
        self._previous_on_error = bot.tree.on_error
        bot.tree.on_error = self.on_app_command_error

    async def cog_unload(self):
        self.bot.tree.on_error = self._previous_on_error

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
        command = getattr(getattr(interaction, "command", None), "qualified_name", "unknown")

        if isinstance(error, app_commands.CommandNotFound):
            logger.debug(f"Command not found: {command}")
            return

        if isinstance(error, app_commands.CommandOnCooldown):
            await self._reply(
                interaction,
                f"This command is on cooldown. Try again in **{round(error.retry_after, 1)}** seconds.",
            )
            return

        if isinstance(error, app_commands.MissingPermissions):
            await self._reply(
                interaction,
                f"You need these permissions to use this command: **{_perm_names(error.missing_permissions)}**",
            )
            return

        if isinstance(error, app_commands.BotMissingPermissions):
            await self._reply(
                interaction,
                f"I need these permissions to run this command: **{_perm_names(error.missing_permissions)}**. "
                "Ask a server admin to grant them to my role.",
            )
            return

        if isinstance(error, app_commands.NoPrivateMessage):
            await self._reply(interaction, "This command can only be used in a server.")
            return

        if isinstance(error, app_commands.CheckFailure):
            # A check that refused usually answered the member itself.
            if not interaction.response.is_done():
                await self._reply(interaction, "This command cannot be used right now.")
            return

        if isinstance(original, discord.NotFound) and getattr(original, "code", None) == 10062:
            # Unknown interaction: the token expired, so there is nobody to answer.
            logger.warning(f"Interaction expired before /{command} could answer: {original}")
            return

        logger.error(
            f"Unhandled error in /{command}: {type(original).__name__}: {original}",
            exc_info=(type(original), original, original.__traceback__),
        )
        await self._reply(interaction, unexpected_failure_message())

    @staticmethod
    def _answered_by_own_handler(interaction: discord.Interaction) -> bool:
        """True when the failing command has its own error handler, which has replied.

        discord.py 2.7 runs the command's own ``on_error`` (``@cmd.error``), an
        overridden parent or grandparent ``Group.on_error``, and the cog's overridden
        ``cog_app_command_error`` BEFORE ``tree.on_error``, so a reply here as well
        answers the member twice. ``Command._has_any_error_handlers`` is the exact
        check discord.py's default ``tree.on_error`` uses to stay quiet, and it covers
        all three. Any such handler added to this bot must reply on every path it
        handles. If the check is unavailable, reply anyway - a second message is
        better than none.
        """
        command = getattr(interaction, "command", None)
        check = getattr(command, "_has_any_error_handlers", None)
        if check is None:
            return False
        try:
            return bool(check())
        except Exception:
            return False

    async def _reply(self, interaction: discord.Interaction, text: str) -> None:
        """Send ``text`` to the member, ephemeral. Never raises.

        Every relay command defers ephemerally, so a followup after a defer stays
        private too.
        """
        if self._answered_by_own_handler(interaction):
            return
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except Exception:
            logger.exception("Could not send the command error reply")


async def setup(bot: commands.Bot):
    await bot.add_cog(ErrorHandler(bot))
