"""
Panel session — synced timeout across the two-message panel pattern.
"""

import asyncio

import discord


def _build_expired_layout() -> discord.ui.LayoutView:
    expired = discord.ui.LayoutView()
    expired.add_item(discord.ui.TextDisplay("## Settings Panel — Session Expired"))
    expired.add_item(discord.ui.Separator())
    expired.add_item(discord.ui.TextDisplay(
        "This panel has timed out after 5 minutes of inactivity.\n"
        "Use `/settings panel` to open a new session."
    ))
    return expired


class PanelSession:
    """Shared timeout session for the panel's two-message pattern."""

    def __init__(self, original_interaction: discord.Interaction, timeout: float = 300.0):
        self.original_interaction = original_interaction
        self.msg2_message: discord.Message | None = None
        self.msg2_view: discord.ui.LayoutView | None = None
        self._timeout = timeout
        self._timer_task: asyncio.Task | None = None

    def register_view(self, view: discord.ui.LayoutView) -> discord.ui.LayoutView:
        view.timeout = None
        original_check = getattr(view, "interaction_check", None)
        session = self

        async def synced_check(interaction: discord.Interaction) -> bool:
            session.touch()
            if original_check and callable(original_check):
                return await discord.utils.maybe_coroutine(original_check, interaction)
            return True

        view.interaction_check = synced_check
        return view

    def set_msg2(self, view: discord.ui.LayoutView, message: discord.Message) -> None:
        self.msg2_view = view
        self.msg2_message = message

    def clear_msg2(self) -> None:
        if self.msg2_view:
            self.msg2_view.stop()
        self.msg2_view = None
        self.msg2_message = None

    def touch(self) -> None:
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = asyncio.create_task(self._run_timeout())

    async def _run_timeout(self) -> None:
        try:
            await asyncio.sleep(self._timeout)
        except asyncio.CancelledError:
            return
        await self._expire()

    async def _expire(self) -> None:
        try:
            await self.original_interaction.edit_original_response(view=_build_expired_layout())
        except Exception:
            pass

        if self.msg2_message is not None:
            try:
                await self.msg2_message.edit(view=_build_expired_layout())
            except Exception:
                pass

        if self.msg2_view:
            self.msg2_view.stop()
        self.msg2_view = None
        self.msg2_message = None
