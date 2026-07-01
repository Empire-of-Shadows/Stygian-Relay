# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""
Admin Panel Session - Synced timeout expiry across messages.

Provides PanelSession which manages a single shared timeout timer for both
Message 1 (overview) and Message 2 (settings). Any interaction on either
message resets the timer; both expire together.
"""

import asyncio

import discord

from .base import notice_container, build_notice_layout


def _build_expired_layout() -> discord.ui.LayoutView:
    """Build the session-expired LayoutView (orange notice container)."""
    expired = discord.ui.LayoutView()
    expired.add_item(notice_container(
        discord.ui.TextDisplay(
            "## Admin Panel — Session Expired\n"
            "This panel timed out after 5 minutes of inactivity.\n"
            "Use `/admin panel` to open a new session."
        ),
    ))
    return expired


class PanelSession:
    """Shared timeout session for the admin panel's two-message pattern.

    Manages a single asyncio timer that resets on any interaction with either
    message. When the timer fires, both messages are edited to show the
    expired notice.
    """

    def __init__(self, original_interaction: discord.Interaction, timeout: float = 300.0):
        self.original_interaction = original_interaction
        self.admin_id: int = original_interaction.user.id
        # Caller's resolved tier ("admin" | "mod" | "none"); set at panel open so
        # navigation/save handlers can gate by effective mod access without re-resolving.
        self.panel_role: str = "admin"
        self.msg2_message: discord.Message | None = None
        self.msg2_view: discord.ui.LayoutView | None = None
        self._timeout = timeout
        self._timer_task: asyncio.Task | None = None

    def register_view(self, view: discord.ui.LayoutView) -> discord.ui.LayoutView:
        """Register a view with the session.

        Disables the view's built-in timeout and hooks interaction_check
        so any component interaction resets the shared timer.

        Returns the same view for chaining.
        """
        view.timeout = None
        original_check = getattr(view, 'interaction_check', None)

        session = self

        async def synced_check(interaction: discord.Interaction) -> bool:
            if interaction.user.id != session.admin_id:
                try:
                    await interaction.response.send_message(
                        view=build_notice_layout(
                            "Access Denied",
                            "Only the admin who opened this panel can interact with it.",
                        ),
                        ephemeral=True,
                    )
                except discord.HTTPException:
                    pass
                return False
            session.touch()
            if original_check and callable(original_check):
                return await discord.utils.maybe_coroutine(original_check, interaction)
            return True

        view.interaction_check = synced_check
        return view

    def set_msg2(self, view: discord.ui.LayoutView, message: discord.Message) -> None:
        """Track the current Message 2 view and message object."""
        self.msg2_view = view
        self.msg2_message = message

    def clear_msg2(self) -> None:
        """Clear Message 2 tracking (on close/replace)."""
        if self.msg2_view:
            self.msg2_view.stop()
        self.msg2_view = None
        self.msg2_message = None

    def touch(self) -> None:
        """Reset the shared timeout timer."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = asyncio.create_task(self._run_timeout())

    async def _run_timeout(self) -> None:
        """Wait for the timeout duration, then expire both messages."""
        try:
            await asyncio.sleep(self._timeout)
        except asyncio.CancelledError:
            return
        await self._expire()

    async def _expire(self) -> None:
        """Edit both messages to show the expired notice and stop views."""
        expired_msg1 = _build_expired_layout()
        try:
            await self.original_interaction.edit_original_response(view=expired_msg1)
        except Exception:
            pass  # Interaction may have expired or message deleted

        if self.msg2_message is not None:
            try:
                await self.msg2_message.edit(view=_build_expired_layout())
            except Exception:
                pass  # Message may have been deleted

        if self.msg2_view:
            self.msg2_view.stop()
        self.msg2_view = None
        self.msg2_message = None
