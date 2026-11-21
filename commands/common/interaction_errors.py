"""Support-aware on_error for the bot's own Views, LayoutViews and Modals.

An exception that no callback caught otherwise reaches the member only as
Discord's bare "This interaction failed", with nothing telling them where to
report it. These mixins replace discord.py's default ``on_error`` with one that
logs the exception with its traceback (as the default does) and then sends the
member an EPHEMERAL failure message ending with the support-server line.

Put the mixin FIRST in the bases so its ``on_error`` wins:

    class RelayHelpView(SupportAwareViewMixin, ui.LayoutView): ...
    class SomeModal(SupportAwareModalMixin, discord.ui.Modal): ...

Factory-built interactive layouts use ``SupportAwareLayoutView`` in place of a
bare ``ui.LayoutView()``. A ``DynamicItem`` callback never reaches any view's
``on_error`` (discord.py logs and drops it), so such an item would call
``send_unexpected_failure`` from its own ``except`` (relay has none today).

Plain module (no ``setup()``), so the cog loader leaves it alone. The admin
panel's seam uses the admin engine's own equivalents (``SupportAwareView``,
``SupportAwareModal``, ``support_aware`` in ``admin/views/base.py``).
"""
from __future__ import annotations

from typing import Any

import discord
from discord import ui

from commands.help.help_content import SUPPORT_LINE
from storage.log import get_logger

logger = get_logger("InteractionErrors")

UNEXPECTED_FAILURE_TEXT = "Something went wrong. That did not go through. Please try again."


def unexpected_failure_message() -> str:
    """The member-facing text for an uncaught interaction error."""
    return f"{UNEXPECTED_FAILURE_TEXT}\n\n{SUPPORT_LINE}"


async def send_unexpected_failure(
    interaction: discord.Interaction, error: BaseException, where: str
) -> None:
    """Log an exception nothing else caught, then tell the member it failed.

    Ephemeral, through ``followup.send`` when the interaction was already
    answered and ``response.send_message`` otherwise. Never raises: it runs as
    an error handler, and raising here would bury the original failure.
    """
    logger.error(
        f"Ignoring exception in {where}",
        exc_info=(type(error), error, error.__traceback__),
    )
    try:
        message = unexpected_failure_message()
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception:
        logger.exception(f"Could not send the failure notice for {where}")


class SupportAwareViewMixin:
    """``on_error`` for a View or LayoutView subclass. List it before the base."""

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: Any, /
    ) -> None:
        await send_unexpected_failure(
            interaction, error, f"view {type(self).__name__} for item {item!r}"
        )


class SupportAwareModalMixin:
    """``on_error`` for a Modal subclass. List it before the base."""

    async def on_error(self, interaction: discord.Interaction, error: Exception, /) -> None:
        await send_unexpected_failure(interaction, error, f"modal {type(self).__name__}")


class SupportAwareLayoutView(SupportAwareViewMixin, ui.LayoutView):
    """A plain LayoutView with the support-aware ``on_error``, for factory builders."""
