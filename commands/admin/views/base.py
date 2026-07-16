# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""
Base utilities for Admin Panel Components v2 views.

Provides shared builders and utilities for creating consistent LayoutView layouts.
This is engine code — identical across every bot (vendored from admin_engine/).
It is intentionally a *superset*: helpers that only some bots use still live here
so the engine file stays byte-identical everywhere.
"""

import time
import logging
from typing import Optional, Callable, Awaitable

import discord

logger = logging.getLogger("AdminViews")

# Custom-id namespace prefix. Generic so this file stays byte-identical across bots;
# custom_ids only need to be unique within a single session-bound LayoutView.
BOT_ID = "eos"

# Container accent colors per ADMIN_PANEL_STANDARD.md §4.
READONLY_COLOR = 0x4d0eb3
NOTICE_COLOR = 0xE67E22
PREMIUM_COLOR = 0xF1C40F


def cid(module: str, action: str, node_key: Optional[str] = None) -> str:
    """Build a standardized custom_id per ADMIN_PANEL_STANDARD.md §6."""
    parts = [BOT_ID, module, action]
    if node_key:
        parts.append(node_key)
    return ":".join(parts)


def create_unique_id() -> int:
    """Microsecond-timestamp unique id. Legacy helper for consumer views that
    build their own components; new engine code uses cid()."""
    return int(time.time() * 1000000)


def _container(accent: Optional[int], items) -> discord.ui.Container:
    c = discord.ui.Container(accent_color=accent)
    for it in items:
        c.add_item(it)
    return c


def readonly_container(*items: discord.ui.Item) -> discord.ui.Container:
    """Container with the read-only accent color (#4d0eb3)."""
    return _container(READONLY_COLOR, items)


def editable_container(*items: discord.ui.Item) -> discord.ui.Container:
    """Container with no accent — used for current-value + active editor blocks."""
    return _container(None, items)


def notice_container(*items: discord.ui.Item) -> discord.ui.Container:
    """Container with the notice/error accent color (orange)."""
    return _container(NOTICE_COLOR, items)


def premium_container(*items: discord.ui.Item) -> discord.ui.Container:
    """Container with the premium-gate accent color (gold)."""
    return _container(PREMIUM_COLOR, items)


def build_notice_layout(title: str, body: str = "") -> discord.ui.LayoutView:
    """Standard Message-3 notice layout: a LayoutView wrapping one notice Container."""
    layout = discord.ui.LayoutView()
    text = f"## {title}" + (f"\n{body}" if body else "")
    layout.add_item(notice_container(discord.ui.TextDisplay(text)))
    return layout


def build_premium_layout(title: str, body: str = "") -> discord.ui.LayoutView:
    """Premium-gate layout: LayoutView wrapping one premium Container."""
    layout = discord.ui.LayoutView()
    text = f"## {title}" + (f"\n{body}" if body else "")
    layout.add_item(premium_container(discord.ui.TextDisplay(text)))
    return layout


async def safe_edit(target, **kwargs) -> bool:
    """Run target.edit(**kwargs), swallowing HTTPException per §9."""
    try:
        await target.edit(**kwargs)
        return True
    except discord.HTTPException as exc:
        logger.warning("admin panel edit failed: %s", exc)
        return False


async def safe_followup_notice(interaction: discord.Interaction, title: str, body: str = "") -> None:
    """Send a Message-3 notice via followup, swallowing HTTPException per §9."""
    try:
        await interaction.followup.send(
            view=build_notice_layout(title, body),
            ephemeral=True,
        )
    except discord.HTTPException as exc:
        logger.warning("admin panel notice followup failed: %s", exc)


class LockedLayoutView(discord.ui.LayoutView):
    """LayoutView that enforces author lock via interaction_check (§2.2 / §10.4).

    Pass the panel session's admin_id at construction. Any non-admin interaction
    receives an orange Access Denied notice and the check returns False. (Legacy
    helper; the engine normally locks via PanelSession.register_view.)
    """

    def __init__(self, *, admin_id: int, touch: Optional[Callable[[], None]] = None, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self._admin_id = admin_id
        self._touch = touch

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._admin_id:
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
        if self._touch is not None:
            try:
                self._touch()
            except Exception:
                logger.exception("session.touch() raised in LockedLayoutView")
        return True


def build_header(title: str, description: Optional[str] = None) -> list[discord.ui.Item]:
    """Build a standard header section with title and optional description."""
    items = [discord.ui.TextDisplay(title)]
    if description:
        items.append(discord.ui.TextDisplay(description))
    return items


def build_status_display(status: str) -> discord.ui.TextDisplay:
    """Build a status message display."""
    return discord.ui.TextDisplay(status)


def build_config_display(config_lines: list[str], header: str = "**Current Configuration:**") -> discord.ui.TextDisplay:
    """Build a configuration list display."""
    content = header + "\n" + "\n".join(config_lines)
    return discord.ui.TextDisplay(content)


def build_select_row(select: discord.ui.Select) -> discord.ui.ActionRow:
    """Wrap a Select component in an ActionRow."""
    row = discord.ui.ActionRow()
    row.add_item(select)
    return row


def build_action_buttons(
    save_callback: Callable[[discord.Interaction], Awaitable[None]],
    cancel_callback: Callable[[discord.Interaction], Awaitable[None]],
    save_label: str = "Save",
    cancel_label: str = "Cancel",
    save_style: discord.ButtonStyle = discord.ButtonStyle.green,
    cancel_style: discord.ButtonStyle = discord.ButtonStyle.secondary,
) -> discord.ui.ActionRow:
    """Legacy save/cancel pair for consumer views. New engine code uses the kind builders."""
    uid = create_unique_id()
    save_btn = discord.ui.Button(label=save_label, style=save_style, custom_id=f"save_{uid}")
    save_btn.callback = save_callback
    cancel_btn = discord.ui.Button(label=cancel_label, style=cancel_style, custom_id=f"cancel_{uid}")
    cancel_btn.callback = cancel_callback
    row = discord.ui.ActionRow()
    row.add_item(save_btn)
    row.add_item(cancel_btn)
    return row


def build_confirmation_buttons(
    confirm_callback: Callable[[discord.Interaction], Awaitable[None]],
    cancel_callback: Callable[[discord.Interaction], Awaitable[None]],
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
    confirm_style: discord.ButtonStyle = discord.ButtonStyle.danger,
) -> discord.ui.ActionRow:
    """Legacy confirm/cancel pair for consumer views."""
    return build_action_buttons(
        save_callback=confirm_callback,
        cancel_callback=cancel_callback,
        save_label=confirm_label,
        cancel_label=cancel_label,
        save_style=confirm_style,
        cancel_style=discord.ButtonStyle.secondary,
    )


def build_back_button(
    callback: Callable[[discord.Interaction], Awaitable[None]],
    label: str = "Back",
) -> discord.ui.ActionRow:
    """Legacy single Back button row for consumer views."""
    uid = create_unique_id()
    back_btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"back_{uid}")
    back_btn.callback = callback
    row = discord.ui.ActionRow()
    row.add_item(back_btn)
    return row


def create_empty_layout(message: str = "Operation cancelled.") -> discord.ui.LayoutView:
    """Create an empty layout with a simple message."""
    layout = discord.ui.LayoutView()
    layout.add_item(discord.ui.TextDisplay(message))
    return layout


def create_error_layout(error_message: str) -> discord.ui.LayoutView:
    """Create a layout for displaying errors."""
    layout = discord.ui.LayoutView()
    layout.add_item(discord.ui.TextDisplay("## Error"))
    layout.add_item(discord.ui.TextDisplay(error_message))
    return layout


def create_success_layout(title: str, message: str) -> discord.ui.LayoutView:
    """Create a layout for displaying success messages."""
    layout = discord.ui.LayoutView()
    layout.add_item(discord.ui.TextDisplay(f"## {title}"))
    layout.add_item(discord.ui.TextDisplay(message))
    return layout


class AdminLayoutBuilder:
    """Helper class for building admin panel layouts with consistent styling."""

    def __init__(self, timeout: float = 300.0):
        self.timeout = timeout
        self.items: list[discord.ui.Item] = []

    def add_header(self, title: str, description: Optional[str] = None) -> 'AdminLayoutBuilder':
        """Add a header section."""
        self.items.extend(build_header(title, description))
        return self

    def add_separator(self) -> 'AdminLayoutBuilder':
        """Add a visual separator."""
        self.items.append(discord.ui.Separator())
        return self

    def add_text(self, text: str) -> 'AdminLayoutBuilder':
        """Add a text display."""
        self.items.append(discord.ui.TextDisplay(text))
        return self

    def add_status(self, status: str) -> 'AdminLayoutBuilder':
        """Add a status display."""
        self.items.append(build_status_display(status))
        return self

    def add_config_display(self, config_lines: list[str], header: str = "**Current Configuration:**") -> 'AdminLayoutBuilder':
        """Add a configuration display."""
        self.items.append(build_config_display(config_lines, header))
        return self

    def add_select(self, select: discord.ui.Select) -> 'AdminLayoutBuilder':
        """Add a select component in an ActionRow."""
        self.items.append(build_select_row(select))
        return self

    def add_action_buttons(
        self,
        save_callback: Callable[[discord.Interaction], Awaitable[None]],
        cancel_callback: Callable[[discord.Interaction], Awaitable[None]],
        save_label: str = "Save",
        cancel_label: str = "Cancel",
    ) -> 'AdminLayoutBuilder':
        """Add a legacy save/cancel button row."""
        self.items.append(build_action_buttons(save_callback, cancel_callback, save_label, cancel_label))
        return self

    def add_confirmation_buttons(
        self,
        confirm_callback: Callable[[discord.Interaction], Awaitable[None]],
        cancel_callback: Callable[[discord.Interaction], Awaitable[None]],
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
    ) -> 'AdminLayoutBuilder':
        """Add a legacy confirm/cancel button row."""
        self.items.append(build_confirmation_buttons(confirm_callback, cancel_callback, confirm_label, cancel_label))
        return self

    def add_item(self, item: discord.ui.Item) -> 'AdminLayoutBuilder':
        """Add any UI item directly."""
        self.items.append(item)
        return self

    def add_action_row(self, *items: discord.ui.Item) -> 'AdminLayoutBuilder':
        """Add items wrapped in an ActionRow."""
        row = discord.ui.ActionRow()
        for item in items:
            row.add_item(item)
        self.items.append(row)
        return self

    def build(self) -> discord.ui.LayoutView:
        """Build and return the LayoutView."""
        layout = discord.ui.LayoutView(timeout=self.timeout)
        for item in self.items:
            layout.add_item(item)
        return layout


# Stygian-Relay consumer views refer to PanelLayoutBuilder; it is the same builder.
PanelLayoutBuilder = AdminLayoutBuilder
