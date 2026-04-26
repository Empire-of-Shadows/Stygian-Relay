"""
Admin Commands Cog - Multi-Message Config Panel

Main cog with /admin panel command using Discord Components v2 LayoutViews.
Uses the PanelNode engine for all navigation - no per-feature view builders needed.

Message pattern:
  Message 1 (Overview):  Persistent full-detail server config overview. Always visible,
                          updates in-place when settings change.
  Message 2 (Settings):  Sent as followup when a category is selected. All navigation
                          and setting changes happen here. Auto-closed on new selection.
  Message 3 (Notices):   Ephemeral followup for errors, locks, permission failures.
"""

import logging
import time
from collections.abc import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from database import audit_log, guild_manager
from database.permissions import can_manage_guild_settings, get_permission_error_message

from .panel_configs import MAIN_PANEL
from .permission_checks import check_channel_permissions, check_role_permissions
from .views.base import create_empty_layout, create_unique_id
from .views.rules_panel import build_rules_panel_view
from .views.panel_engine import (
    PanelInputModal,
    PanelNode,
    build_dual_modal_trigger_view,
    build_menu_view,
    build_modal_trigger_view,
    build_overview_view,
    build_select_view,
    _child_summary,
    _get_default_option_value,
    _option_label,
)
from .views.panel_views import PanelSession

logger = logging.getLogger(__name__)

SETUP_GUIDE_TEXT = (
    "**Quick Setup Guide**\n"
    "Before using Stygian-Relay, take a moment to configure these basics:\n"
    "\n"
    "**1. Manager Role** — assign a role that may manage settings alongside admins.\n"
    "**2. Log Channel** — pick a channel where the bot posts premium redeems, errors, and rate-limit notices.\n"
    "**3. Command Prefix** — set the prefix for legacy text commands (defaults to `!`).\n"
    "**4. Forwarding Rules** — open **Forwarding Rules** in this panel to create your first source → destination rule.\n"
    "\n"
    "Use the panel below to assign each one."
)


class AdminCog(commands.Cog):
    """
    Administrative commands for managing the Stygian-Relay bot.
    Uses Discord Components v2 LayoutViews with config-driven PanelNode trees.

    Multi-message pattern:
      Message 1 - navigation (main panel / category menus)
      Message 2 - settings (followup for leaf settings / sub-menus)
      Message 3 - notifications (ephemeral errors and lock messages)
    """

    AUTOSAVE_COOLDOWN = 2.0  # seconds between autosaves per (user, node_key)

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._autosave_cooldowns: dict[tuple, float] = {}
        # Per-guild premium-status cache (TTL 60s) so sync _is_premium calls
        # in select-save callbacks don't hit the DB on every interaction.
        self._premium_cache: dict[int, tuple[float, bool]] = {}
        logger.info("AdminCog initialized")

    # -- Command Groups --------------------------------------------------------

    admin_group = app_commands.Group(
        name="admin",
        description="Admin commands for managing bot configuration",
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def _invalidate_guild_caches(self, guild_id: int) -> None:
        """Invalidate guild settings cache after any settings change."""
        try:
            guild_manager.settings_cache.invalidate(str(guild_id))
        except Exception as e:
            logger.debug(f"settings_cache invalidate failed: {e}")
        self._premium_cache.pop(guild_id, None)

    def _is_premium(self, guild_id: int) -> bool:
        """Sync premium check using a 60s in-memory cache. Falls back to False on miss."""
        entry = self._premium_cache.get(guild_id)
        if entry and time.monotonic() - entry[0] < 60.0:
            return entry[1]
        return False  # Conservative default; refreshed by _refresh_premium below.

    async def _refresh_premium(self, guild_id: int) -> bool:
        try:
            val = await guild_manager.is_premium_guild(str(guild_id))
        except Exception:
            val = False
        self._premium_cache[guild_id] = (time.monotonic(), val)
        return val

    async def _resolve_description(self, node: PanelNode, guild: discord.Guild) -> str | None:
        """Run async_description if set; else None to fall back to static."""
        if node.async_description:
            try:
                return await node.async_description(guild)
            except Exception as e:
                logger.warning(f"async_description failed for {node.key}: {e}", exc_info=True)
        return None

    async def _get_guide_hidden(self, guild_id: int) -> bool:
        try:
            s = await guild_manager.get_guild_settings(str(guild_id))
            return bool(s.get("features", {}).get("hide_setup_guide", False))
        except Exception:
            return False

    async def _set_guide_hidden(self, guild_id: int, hidden: bool) -> None:
        try:
            await guild_manager.update_guild_settings(
                str(guild_id), {"features.hide_setup_guide": hidden}
            )
        except Exception as e:
            logger.debug(f"persist guide hidden failed: {e}")

    # -- Master Panel (Message 1 - Overview) -----------------------------------

    @admin_group.command(name="panel", description="Open the admin configuration panel")
    async def admin_panel(self, interaction: discord.Interaction):
        """Open the master admin control panel (message 1 - persistent overview)."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command can only be used in a server.", ephemeral=True
            )
            return

        if not await can_manage_guild_settings(interaction):
            msg = await get_permission_error_message(interaction)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        guild = interaction.guild
        admin_id = interaction.user.id

        logger.info(f"Admin panel opened by {interaction.user} in guild {guild.id}")

        # Warm premium cache.
        await self._refresh_premium(guild.id)

        # Fetch setup guide visibility state.
        guide_state = {"hidden": await self._get_guide_hidden(guild.id)}

        # Config details toggle (compact by default, not persisted).
        details_state = {"expanded": False}

        # Shared session for synced timeout across both messages.
        session = PanelSession(interaction)

        async def on_toggle_guide(toggle_interaction: discord.Interaction):
            if toggle_interaction.user.id != admin_id:
                await toggle_interaction.response.send_message(
                    "Only the admin who opened this panel can interact with it.",
                    ephemeral=True,
                )
                return

            if not self._check_cooldown(admin_id, "setup_guide_toggle"):
                await toggle_interaction.response.send_message(
                    "Please wait a moment before toggling again.",
                    ephemeral=True,
                )
                return

            new_hidden = not guide_state["hidden"]
            guide_state["hidden"] = new_hidden
            await self._set_guide_hidden(guild.id, new_hidden)

            layout = await _build_overview()
            await toggle_interaction.response.edit_message(view=layout)

        async def on_toggle_details(toggle_interaction: discord.Interaction):
            if toggle_interaction.user.id != admin_id:
                await toggle_interaction.response.send_message(
                    "Only the admin who opened this panel can interact with it.",
                    ephemeral=True,
                )
                return

            if not self._check_cooldown(admin_id, "details_toggle"):
                await toggle_interaction.response.send_message(
                    "Please wait a moment before toggling again.",
                    ephemeral=True,
                )
                return

            details_state["expanded"] = not details_state["expanded"]
            layout = await _build_overview()
            await toggle_interaction.response.edit_message(view=layout)

        async def on_main_select(sel_interaction: discord.Interaction, child_key: str):
            if sel_interaction.user.id != admin_id:
                await sel_interaction.response.send_message(
                    "Only the admin who opened this panel can interact with it.",
                    ephemeral=True,
                )
                return
            child = MAIN_PANEL.children.get(child_key)
            if not child:
                return

            # Lock check
            locked = await self._compute_locked_keys(MAIN_PANEL, guild.id)
            if child_key in locked:
                new_locked = await self._compute_locked_keys(MAIN_PANEL, guild.id)
                if child_key in new_locked:
                    reason = MAIN_PANEL.lock_reason or (
                        "Required settings must be configured before "
                        "accessing this option."
                    )
                    embed = discord.Embed(
                        title="Setting Locked",
                        description=reason,
                        color=discord.Color.orange(),
                    )
                    refreshed = await _build_overview()
                    await sel_interaction.response.edit_message(view=refreshed)
                    await sel_interaction.followup.send(embed=embed, ephemeral=True)
                    return

            # Auto-close previous message 2
            if session.msg2_message is not None:
                try:
                    await session.msg2_message.edit(
                        view=create_empty_layout("Setting closed. Use the overview above to continue.")
                    )
                except Exception:
                    pass
                session.clear_msg2()

            # Refresh overview on message 1 so the category Select resets.
            try:
                refreshed = await _build_overview()
                await interaction.edit_original_response(view=refreshed)
            except Exception as e:
                logger.debug(f"Could not refresh overview select state: {e}")

            # Send category as new message 2 (followup)
            await self._show_category_on_msg2(
                sel_interaction, child, guild, interaction, admin_id,
                _build_overview, session,
            )

        async def _build_overview():
            deep_summary = await self._gather_deep_summaries(MAIN_PANEL, guild.id, guild)
            toggle_states = await self._gather_toggle_states(MAIN_PANEL, guild.id)
            locked = await self._compute_locked_keys(MAIN_PANEL, guild.id)

            preamble = None
            if not guide_state["hidden"]:
                guide_container = discord.ui.Container(
                    discord.ui.TextDisplay(SETUP_GUIDE_TEXT),
                )
                preamble = [guide_container]

            guide_btn = discord.ui.Button(
                label="Show Setup Guide" if guide_state["hidden"] else "Hide Setup Guide",
                style=discord.ButtonStyle.secondary,
                custom_id=f"guide_toggle_{create_unique_id()}",
            )
            guide_btn.callback = on_toggle_guide

            details_btn = discord.ui.Button(
                label="Hide Config Details" if details_state["expanded"] else "Show Config Details",
                style=discord.ButtonStyle.secondary,
                custom_id=f"details_toggle_{create_unique_id()}",
            )
            details_btn.callback = on_toggle_details

            layout = build_overview_view(
                MAIN_PANEL, deep_summary, toggle_states, locked,
                on_main_select,
                preamble_items=preamble,
                extra_buttons=[guide_btn, details_btn],
                compact=not details_state["expanded"],
            )
            session.register_view(layout)
            return layout

        layout = await _build_overview()
        await interaction.response.send_message(view=layout, ephemeral=True)
        session.touch()

    # -- Category Menu on Message 2 --------------------------------------------

    async def _show_category_on_msg2(
        self,
        sel_interaction: discord.Interaction,
        category_node: PanelNode,
        guild: discord.Guild,
        original_interaction: discord.Interaction,
        admin_id: int,
        build_overview: Callable[[], Awaitable[discord.ui.LayoutView]],
        session: PanelSession,
    ) -> None:
        """Send a new message 2 (followup) showing a category menu."""

        # Custom-rendered category: Forwarding Rules panel hosts the rule
        # creation/edit flows in place of the read-only async description.
        if category_node.key == "forwarding_rules":
            await self._show_rules_panel_on_msg2(
                sel_interaction, guild, original_interaction, admin_id,
                build_overview, session,
            )
            return

        summary_map = await self._gather_summaries(category_node, guild.id)
        locked_keys = await self._compute_locked_keys(category_node, guild.id)
        _current_locked = [locked_keys]

        toggle_state = None
        if category_node.toggle_get:
            toggle_state = await category_node.toggle_get(guild.id)

        desc_override = await self._resolve_description(category_node, guild)

        async def refresh_nav():
            try:
                new_view = await build_overview()
                await original_interaction.edit_original_response(view=new_view)
            except Exception as e:
                logger.debug(f"Could not refresh overview after save: {e}")

        async def _build_category_view():
            new_summary = await self._gather_summaries(category_node, guild.id)
            new_locked = await self._compute_locked_keys(category_node, guild.id)
            _current_locked[0] = new_locked
            new_toggle = await category_node.toggle_get(guild.id) if category_node.toggle_get else None
            new_desc = await self._resolve_description(category_node, guild)
            return build_menu_view(
                category_node, new_summary, on_child_select, on_back, new_locked,
                toggle_state=new_toggle,
                on_toggle=on_toggle if category_node.toggle_set else None,
                back_label="Close",
                description_override=new_desc,
                guild_id=guild.id,
                guild=guild,
            )

        async def on_child_select(child_interaction: discord.Interaction, child_key: str):
            if child_interaction.user.id != admin_id:
                await child_interaction.response.send_message(
                    "Only the admin who opened this panel can interact with it.",
                    ephemeral=True,
                )
                return
            child = category_node.children.get(child_key)
            if not child:
                return

            # Lock check
            if child_key in _current_locked[0]:
                new_locked = await self._compute_locked_keys(category_node, guild.id)
                if child_key in new_locked:
                    reason = category_node.lock_reason or (
                        "Required settings must be configured before "
                        "accessing this option."
                    )
                    embed = discord.Embed(
                        title="Setting Locked",
                        description=reason,
                        color=discord.Color.orange(),
                    )
                    refreshed = await _build_category_view()
                    await child_interaction.response.edit_message(view=refreshed)
                    await child_interaction.followup.send(embed=embed, ephemeral=True)
                    return
                else:
                    _current_locked[0] = new_locked
                    refreshed = await _build_category_view()
                    await child_interaction.response.edit_message(view=refreshed)
                    return

            # Pre-check gate
            if child.pre_check:
                denied_embed = await child.pre_check(child_interaction, guild.id)
                if denied_embed is not None:
                    refreshed = await _build_category_view()
                    await child_interaction.response.edit_message(view=refreshed)
                    await child_interaction.followup.send(embed=denied_embed, ephemeral=True)
                    return

            # Modal input children handled inline on message 2
            if child.kind == "modal_input":
                await self._handle_inline_modal(
                    child_interaction, child, category_node, guild,
                    summary_map, on_child_select, on_back,
                    refresh_parent=refresh_nav,
                )
            else:
                await self._navigate_to(
                    child_interaction, child, guild,
                    parent_node=category_node,
                    edit=True,
                    refresh_parent=refresh_nav,
                    session=session,
                )

        async def on_back(back_interaction: discord.Interaction):
            if back_interaction.user.id != admin_id:
                await back_interaction.response.send_message(
                    "Only the admin who opened this panel can interact with it.",
                    ephemeral=True,
                )
                return
            session.clear_msg2()
            await back_interaction.response.edit_message(
                view=create_empty_layout(
                    "Setting closed. Use the overview above to continue."
                )
            )

        async def on_toggle(toggle_interaction: discord.Interaction):
            if toggle_interaction.user.id != admin_id:
                await toggle_interaction.response.send_message(
                    "Only the admin who opened this panel can interact with it.",
                    ephemeral=True,
                )
                return
            current = await category_node.toggle_get(guild.id)
            success = await category_node.toggle_set(guild.id, not current)
            if success:
                self._invalidate_guild_caches(guild.id)
                if category_node.on_toggle_callback:
                    await category_node.on_toggle_callback(guild, not current)
                action = "disabled" if current else "enabled"
                logger.info(f"Admin {toggle_interaction.user} {action} {category_node.key} in guild {guild.id}")
                refreshed = await _build_category_view()
                await toggle_interaction.response.edit_message(view=refreshed)
                await refresh_nav()
            else:
                await toggle_interaction.response.send_message(
                    f"Failed to update **{category_node.label}**.", ephemeral=True
                )

        layout = build_menu_view(
            category_node, summary_map, on_child_select, on_back, locked_keys,
            toggle_state=toggle_state,
            on_toggle=on_toggle if category_node.toggle_set else None,
            back_label="Close",
            description_override=desc_override,
            guild_id=guild.id,
            guild=guild,
        )
        session.register_view(layout)
        await sel_interaction.response.send_message(view=layout, ephemeral=True)
        session.set_msg2(layout, await sel_interaction.original_response())

    # -- Forwarding Rules panel (Message 2) -------------------------------------

    async def _show_rules_panel_on_msg2(
        self,
        sel_interaction: discord.Interaction,
        guild: discord.Guild,
        original_interaction: discord.Interaction,
        admin_id: int,
        build_overview: Callable[[], Awaitable[discord.ui.LayoutView]],
        session: PanelSession,
    ) -> None:
        """Render the Forwarding Rules management panel as message 2."""
        forward_cog = self.bot.get_cog("ForwardCog")
        if forward_cog is None:
            await sel_interaction.response.send_message(
                "❌ Forward cog is not loaded. Restart the bot to enable rule management.",
                ephemeral=True,
            )
            return

        async def refresh_overview() -> None:
            self._invalidate_guild_caches(guild.id)
            try:
                new_view = await build_overview()
                await original_interaction.edit_original_response(view=new_view)
            except Exception as e:
                logger.debug(f"refresh_overview failed: {e}")

        async def on_close(close_interaction: discord.Interaction) -> None:
            if close_interaction.user.id != admin_id:
                await close_interaction.response.send_message(
                    "Only the admin who opened this panel can interact with it.",
                    ephemeral=True,
                )
                return
            session.clear_msg2()
            await close_interaction.response.edit_message(
                view=create_empty_layout(
                    "Setting closed. Use the overview above to continue."
                ),
                embed=None,
                attachments=[],
            )

        async def restore_callback(interaction: discord.Interaction) -> None:
            # Wizard runs as a separate ephemeral; close it and refresh
            # msg2 (the rules panel) so the user sees the updated state.
            try:
                if interaction.response.is_done():
                    await interaction.delete_original_response()
                else:
                    await interaction.response.defer()
                    await interaction.delete_original_response()
            except Exception as e:
                logger.debug(f"restore_callback could not delete wizard message: {e}")

            new_layout = await build_rules_panel_view(
                guild=guild,
                admin_id=admin_id,
                forward_cog=forward_cog,
                restore_callback=restore_callback,
                refresh_overview=refresh_overview,
                on_close=on_close,
            )
            session.register_view(new_layout)

            if session.msg2_message is not None:
                try:
                    await session.msg2_message.edit(view=new_layout)
                    session.msg2_view = new_layout
                except Exception as e:
                    logger.warning(f"restore_callback msg2 refresh failed: {e}")

        layout = await build_rules_panel_view(
            guild=guild,
            admin_id=admin_id,
            forward_cog=forward_cog,
            restore_callback=restore_callback,
            refresh_overview=refresh_overview,
            on_close=on_close,
        )
        session.register_view(layout)
        await sel_interaction.response.send_message(view=layout, ephemeral=True)
        session.set_msg2(layout, await sel_interaction.original_response())

    # -- Generic PanelNode Navigator (Message 2) --------------------------------

    async def _navigate_to(
        self,
        interaction: discord.Interaction,
        node: PanelNode,
        guild: discord.Guild,
        *,
        parent_node: PanelNode | None = None,
        grandparent_node: PanelNode | None = None,
        edit: bool = False,
        refresh_parent: Callable[[], Awaitable[None]] | None = None,
        session: PanelSession | None = None,
    ) -> None:
        back_label = "Close" if parent_node is None else "Back"

        if node.kind == "menu":
            await self._show_menu(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)
        elif node.kind in ("role_select", "channel_select", "option_select"):
            await self._show_select(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)
        elif node.kind == "modal_input":
            await self._show_modal_trigger(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)
        elif node.kind == "dual_modal_input":
            await self._show_dual_modal_trigger(interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session)

    # -- Menu nodes -------------------------------------------------------------

    async def _show_menu(self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None):
        summary_map = await self._gather_summaries(node, guild.id)
        locked_keys = await self._compute_locked_keys(node, guild.id)
        _current_locked = [locked_keys]

        toggle_state = None
        if node.toggle_get:
            toggle_state = await node.toggle_get(guild.id)
        desc_override = await self._resolve_description(node, guild)

        async def _build_current_view():
            new_summary = await self._gather_summaries(node, guild.id)
            new_locked = await self._compute_locked_keys(node, guild.id)
            _current_locked[0] = new_locked
            new_toggle = await node.toggle_get(guild.id) if node.toggle_get else None
            new_desc = await self._resolve_description(node, guild)
            return build_menu_view(
                node, new_summary, on_select, on_cancel, new_locked,
                toggle_state=new_toggle,
                on_toggle=on_toggle if node.toggle_set else None,
                back_label=back_label,
                description_override=new_desc,
                guild_id=guild.id,
                guild=guild,
            )

        async def on_select(sel_interaction: discord.Interaction, child_key: str):
            child = node.children.get(child_key)
            if not child:
                return

            if child_key in _current_locked[0]:
                new_locked = await self._compute_locked_keys(node, guild.id)
                if child_key in new_locked:
                    reason = node.lock_reason or (
                        "Required settings must be configured before "
                        "accessing this option."
                    )
                    embed = discord.Embed(
                        title="Setting Locked",
                        description=reason,
                        color=discord.Color.orange(),
                    )
                    refreshed = await _build_current_view()
                    await sel_interaction.response.edit_message(view=refreshed)
                    await sel_interaction.followup.send(embed=embed, ephemeral=True)
                    return
                else:
                    _current_locked[0] = new_locked
                    refreshed = await _build_current_view()
                    await sel_interaction.response.edit_message(view=refreshed)
                    return

            if child.pre_check:
                denied_embed = await child.pre_check(sel_interaction, guild.id)
                if denied_embed is not None:
                    refreshed = await _build_current_view()
                    await sel_interaction.response.edit_message(view=refreshed)
                    await sel_interaction.followup.send(embed=denied_embed, ephemeral=True)
                    return

            if child.kind == "modal_input":
                await self._handle_inline_modal(
                    sel_interaction, child, node, guild,
                    summary_map, on_select, on_cancel,
                    refresh_parent=refresh_parent,
                )
            else:
                await self._navigate_to(
                    sel_interaction, child, guild,
                    parent_node=node, grandparent_node=parent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )

        async def on_cancel(cancel_interaction: discord.Interaction):
            if parent_node:
                await self._navigate_to(
                    cancel_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await cancel_interaction.response.edit_message(
                    view=create_empty_layout(
                        "Setting closed. Use the overview above to continue."
                    )
                )

        async def on_toggle(toggle_interaction: discord.Interaction):
            current = await node.toggle_get(guild.id)
            success = await node.toggle_set(guild.id, not current)
            if success:
                self._invalidate_guild_caches(guild.id)
                if node.on_toggle_callback:
                    await node.on_toggle_callback(guild, not current)
                action = "disabled" if current else "enabled"
                logger.info(f"Admin {toggle_interaction.user} {action} {node.key} in guild {guild.id}")
                refreshed = await _build_current_view()
                await toggle_interaction.response.edit_message(view=refreshed)
                if refresh_parent:
                    await refresh_parent()
            else:
                await toggle_interaction.response.send_message(
                    f"Failed to update **{node.label}**.", ephemeral=True
                )

        layout = build_menu_view(
            node, summary_map, on_select, on_cancel, locked_keys,
            toggle_state=toggle_state,
            on_toggle=on_toggle if node.toggle_set else None,
            back_label=back_label,
            description_override=desc_override,
            guild_id=guild.id,
            guild=guild,
        )
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Select nodes ----------------------------------------------------------

    async def _show_select(self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None):
        current_values = list(await node.get_values(guild.id)) if node.get_values else []
        premium = await self._refresh_premium(guild.id)

        async def on_save(save_interaction: discord.Interaction, values: list):
            if not self._check_cooldown(save_interaction.user.id, node.key):
                await save_interaction.response.send_message(
                    "Saving too quickly, please wait a moment.", ephemeral=True
                )
                return

            await save_interaction.response.defer(ephemeral=True)

            if node.premium_values and not self._is_premium(guild.id):
                blocked = [v for v in values if str(v) in node.premium_values]
                if blocked:
                    embed = discord.Embed(
                        title="Premium Required",
                        description=(
                            "This option requires a **Premium** subscription.\n\n"
                            "Use `/redeem-code` to redeem a premium code."
                        ),
                        color=discord.Color.gold(),
                    )
                    await save_interaction.followup.send(embed=embed, ephemeral=True)
                    return

            if node.kind == "channel_select" and node.premium_max_values is not None:
                if not self._is_premium(guild.id) and len(values) > node.max_values:
                    embed = discord.Embed(
                        title="Premium Required",
                        description=(
                            f"Free servers can select up to **{node.max_values}** channel(s).\n"
                            f"Upgrade to **Premium** to select up to **{node.premium_max_values}**.\n\n"
                            "Use `/redeem-code` to redeem a premium code."
                        ),
                        color=discord.Color.gold(),
                    )
                    await save_interaction.followup.send(embed=embed, ephemeral=True)
                    return

            if node.kind == "channel_select" and values:
                ok, err = check_channel_permissions(guild, int(values[0]), node.key)
                if not ok:
                    await save_interaction.followup.send(err, ephemeral=True)
                    return
            elif node.kind == "role_select" and values:
                for rid in values:
                    ok, err = check_role_permissions(guild, int(rid), node.key)
                    if not ok:
                        await save_interaction.followup.send(err, ephemeral=True)
                        return

            success = await node.set_values(guild.id, values)
            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {save_interaction.user} updated {node.key} in guild {guild.id}")
                new_layout = build_select_view(node, values, guild, on_save, on_back, on_clear_fn, back_label, is_premium=premium)
                await save_interaction.edit_original_response(view=new_layout)
                if node.post_save_hook:
                    await node.post_save_hook(save_interaction, guild.id, values)
                if refresh_parent:
                    await refresh_parent()
            else:
                await save_interaction.followup.send(
                    view=create_empty_layout(f"Failed to save **{node.label}**."),
                    ephemeral=True,
                )

        async def on_back(back_interaction: discord.Interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        on_clear_fn = None
        if node.clear_values:
            async def on_clear(clear_interaction: discord.Interaction):
                if not self._check_cooldown(clear_interaction.user.id, node.key):
                    await clear_interaction.response.send_message(
                        "Saving too quickly, please wait a moment.", ephemeral=True
                    )
                    return

                await clear_interaction.response.defer(ephemeral=True)
                success = await node.clear_values(guild.id)
                if success:
                    self._invalidate_guild_caches(guild.id)
                    logger.info(f"Admin {clear_interaction.user} cleared {node.key} in guild {guild.id}")
                    new_layout = build_select_view(node, [], guild, on_save, on_back, on_clear_fn, back_label, is_premium=premium)
                    await clear_interaction.edit_original_response(view=new_layout)
                    if refresh_parent:
                        await refresh_parent()
                else:
                    await clear_interaction.followup.send(
                        view=create_empty_layout(f"Failed to clear **{node.label}**."),
                        ephemeral=True,
                    )

            on_clear_fn = on_clear

        layout = build_select_view(node, current_values, guild, on_save, on_back, on_clear_fn, back_label, is_premium=premium)
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Modal trigger nodes ---------------------------------------------------

    async def _show_modal_trigger(self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None):
        current_values = list(await node.get_values(guild.id)) if node.get_values else []

        async def on_save(button_interaction, modal_interaction, raw_value):
            if node.modal_validator:
                ok, value, error = node.modal_validator(raw_value)
                if not ok:
                    await modal_interaction.response.send_message(error, ephemeral=True)
                    return
            else:
                value = raw_value

            if not self._check_cooldown(button_interaction.user.id, node.key):
                await modal_interaction.response.send_message(
                    "Saving too quickly, please wait a moment.", ephemeral=True
                )
                return

            await modal_interaction.response.defer(ephemeral=True)

            if not value and node.clear_values:
                success = await node.clear_values(guild.id)
            else:
                success = await node.set_values(guild.id, [value])

            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {button_interaction.user} updated {node.key} in guild {guild.id}")
                new_vals = list(await node.get_values(guild.id)) if node.get_values else []
                new_layout = build_modal_trigger_view(node, new_vals, guild, on_save, on_back, on_clear_fn, back_label)
                await button_interaction.edit_original_response(view=new_layout)
                if node.post_save_hook:
                    await node.post_save_hook(modal_interaction, guild.id, [value])
                if refresh_parent:
                    await refresh_parent()
            else:
                await modal_interaction.followup.send(
                    view=create_empty_layout(f"Failed to save **{node.label}**."),
                    ephemeral=True,
                )

        async def on_back(back_interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        on_clear_fn = None
        if node.clear_values:
            async def on_clear(clear_interaction):
                if not self._check_cooldown(clear_interaction.user.id, node.key):
                    await clear_interaction.response.send_message(
                        "Saving too quickly, please wait a moment.", ephemeral=True
                    )
                    return
                await clear_interaction.response.defer(ephemeral=True)
                success = await node.clear_values(guild.id)
                if success:
                    self._invalidate_guild_caches(guild.id)
                    logger.info(f"Admin {clear_interaction.user} cleared {node.key} in guild {guild.id}")
                    new_layout = build_modal_trigger_view(node, [], guild, on_save, on_back, on_clear_fn, back_label)
                    await clear_interaction.edit_original_response(view=new_layout)
                    if refresh_parent:
                        await refresh_parent()
                else:
                    await clear_interaction.followup.send(
                        view=create_empty_layout(f"Failed to clear **{node.label}**."),
                        ephemeral=True,
                    )

            on_clear_fn = on_clear

        layout = build_modal_trigger_view(node, current_values, guild, on_save, on_back, on_clear_fn, back_label)
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Dual modal trigger nodes ----------------------------------------------

    async def _show_dual_modal_trigger(self, interaction, node, guild, parent_node, grandparent_node, edit, back_label, refresh_parent, session=None):
        current_values = list(await node.get_values(guild.id)) if node.get_values else []

        async def on_save(button_interaction, modal_interaction, val1, val2):
            if not self._check_cooldown(button_interaction.user.id, node.key):
                await modal_interaction.response.send_message(
                    "Saving too quickly, please wait a moment.", ephemeral=True
                )
                return

            await modal_interaction.response.defer(ephemeral=True)
            success = await node.set_values(guild.id, [val1, val2])
            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {button_interaction.user} updated {node.key} in guild {guild.id}")
                new_vals = list(await node.get_values(guild.id)) if node.get_values else []
                new_layout = build_dual_modal_trigger_view(node, new_vals, guild, on_save, on_back, back_label)
                await button_interaction.edit_original_response(view=new_layout)
                if refresh_parent:
                    await refresh_parent()
            else:
                await modal_interaction.followup.send(
                    view=create_empty_layout(f"Failed to save **{node.label}**."),
                    ephemeral=True,
                )

        async def on_back(back_interaction):
            if parent_node:
                await self._navigate_to(
                    back_interaction, parent_node, guild,
                    parent_node=grandparent_node,
                    edit=True,
                    refresh_parent=refresh_parent,
                    session=session,
                )
            else:
                await back_interaction.response.edit_message(
                    view=create_empty_layout(f"{node.label} configuration closed.")
                )

        layout = build_dual_modal_trigger_view(node, current_values, guild, on_save, on_back, back_label)
        if session:
            session.register_view(layout)
        await self._send_or_edit(interaction, layout, edit)

    # -- Inline modal (child of menu) ------------------------------------------

    async def _handle_inline_modal(
        self, sel_interaction, child, parent_menu, guild, summary_map, on_select, on_cancel,
        *, refresh_parent: Callable[[], Awaitable[None]] | None = None,
    ):
        current_str = ""
        if child.get_values:
            try:
                vals = list(await child.get_values(guild.id))
                current_str = str(vals[0]) if vals else ""
            except Exception:
                pass

        async def on_modal_submit(modal_interaction: discord.Interaction, raw_value: str):
            if not raw_value and child.clear_values:
                if not self._check_cooldown(sel_interaction.user.id, child.key):
                    await modal_interaction.response.send_message(
                        "Saving too quickly, please wait a moment.", ephemeral=True
                    )
                    return
                await modal_interaction.response.defer(ephemeral=True)
                success = await child.clear_values(guild.id)
            else:
                if child.modal_validator:
                    ok, value, error = child.modal_validator(raw_value)
                    if not ok:
                        retry_modal = PanelInputModal(
                            title=error if len(error) <= 45 else error[:42] + "...",
                            label=child.modal_label or child.label,
                            placeholder=child.modal_placeholder or "",
                            min_length=child.modal_min_length,
                            max_length=child.modal_max_length,
                            default=raw_value,
                            on_submit_callback=on_modal_submit,
                            paragraph=child.modal_paragraph,
                            required=child.modal_required,
                        )
                        await modal_interaction.response.send_modal(retry_modal)
                        return
                else:
                    value = raw_value

                if not self._check_cooldown(sel_interaction.user.id, child.key):
                    await modal_interaction.response.send_message(
                        "Saving too quickly, please wait a moment.", ephemeral=True
                    )
                    return
                await modal_interaction.response.defer(ephemeral=True)
                success = await child.set_values(guild.id, [value])

            if success:
                self._invalidate_guild_caches(guild.id)
                logger.info(f"Admin {sel_interaction.user} updated {child.key} in guild {guild.id}")
                new_summary = await self._gather_summaries(parent_menu, guild.id)
                locked = await self._compute_locked_keys(parent_menu, guild.id)
                new_desc = await self._resolve_description(parent_menu, guild)
                new_layout = build_menu_view(
                    parent_menu, new_summary, on_select, on_cancel, locked,
                    description_override=new_desc,
                    guild_id=guild.id, guild=guild,
                )
                await sel_interaction.edit_original_response(view=new_layout)
                if refresh_parent:
                    await refresh_parent()
            else:
                await modal_interaction.followup.send(
                    view=create_empty_layout(f"Failed to update **{child.label}**."),
                    ephemeral=True,
                )

        modal = PanelInputModal(
            title=child.modal_title or f"Set {child.label}",
            label=child.modal_label or child.label,
            placeholder=child.modal_placeholder or "",
            min_length=child.modal_min_length,
            max_length=child.modal_max_length,
            default=current_str,
            on_submit_callback=on_modal_submit,
            paragraph=child.modal_paragraph,
            required=child.modal_required,
        )
        await sel_interaction.response.send_modal(modal)

    # -- Helpers ---------------------------------------------------------------

    async def _gather_deep_summaries(
        self, root: PanelNode, guild_id: int, guild: discord.Guild,
    ) -> dict[str, dict[str, str | dict[str, str]]]:
        result: dict[str, dict[str, str | dict[str, str]]] = {}
        for cat_key, cat_node in root.children.items():
            cat_data: dict[str, str | dict[str, str]] = {}
            for child_key, child_node in cat_node.children.items():
                if child_node.kind == "menu":
                    sub_data: dict[str, str] = {}
                    for sub_key, sub_node in child_node.children.items():
                        sub_data[sub_key] = await self._leaf_summary(sub_node, guild_id, guild)
                    cat_data[child_key] = sub_data
                else:
                    cat_data[child_key] = await self._leaf_summary(child_node, guild_id, guild)
            result[cat_key] = cat_data
        return result

    async def _leaf_summary(self, node: PanelNode, guild_id: int, guild: discord.Guild) -> str:
        if not node.get_values:
            return "Not configured"
        try:
            vals = list(await node.get_values(guild_id))
        except Exception:
            return "Not configured"

        if not vals:
            if node.kind == "role_select":
                return "Not assigned"
            return "Not set"

        if node.kind == "channel_select":
            names = []
            for cid in vals:
                ch = guild.get_channel(int(cid))
                names.append(ch.mention if ch else f"Unknown ({cid})")
            return ", ".join(names)

        if node.kind == "role_select":
            names = []
            for rid in vals:
                role = guild.get_role(int(rid))
                names.append(f"@{role.name}" if role else f"Unknown ({rid})")
            return ", ".join(names)

        if node.kind == "option_select":
            default_val = _get_default_option_value(node)
            label = _option_label(node, str(vals[0]))
            if default_val is not None and str(vals[0]) == default_val:
                return f"{label} (Default)"
            return label

        if node.kind in ("modal_input", "dual_modal_input"):
            return str(vals[0]) if vals[0] else "Not set"

        return _child_summary(node, vals)

    async def _gather_toggle_states(self, root: PanelNode, guild_id: int) -> dict[str, bool | None]:
        states: dict[str, bool | None] = {}
        for key, child in root.children.items():
            if child.toggle_get:
                states[key] = await child.toggle_get(guild_id)
            else:
                states[key] = None
        return states

    async def _gather_summaries(self, node: PanelNode, guild_id: int) -> dict[str, list]:
        summary_map: dict[str, list] = {}
        for key, child in node.children.items():
            if child.get_values:
                try:
                    summary_map[key] = list(await child.get_values(guild_id))
                except Exception:
                    summary_map[key] = []
            elif child.kind == "menu":
                customized = []
                has_stored_value = False
                for sub_key, sub_child in child.children.items():
                    if not sub_child.get_values:
                        continue
                    try:
                        vals = list(await sub_child.get_values(guild_id))
                    except Exception:
                        continue
                    if not vals:
                        continue
                    has_stored_value = True
                    if sub_child.kind == "option_select":
                        default_val = _get_default_option_value(sub_child)
                        if default_val is not None and len(vals) == 1 and str(vals[0]) == default_val:
                            continue
                    customized.append(sub_key)

                if len(child.children) == 1:
                    only_child = next(iter(child.children.values()))
                    if only_child.kind == "option_select" and only_child.get_values:
                        try:
                            vals = list(await only_child.get_values(guild_id))
                        except Exception:
                            vals = []
                        if vals:
                            label = _option_label(only_child, str(vals[0]))
                            default_val = _get_default_option_value(only_child)
                            if default_val is not None and str(vals[0]) == default_val:
                                summary_map[key] = [f"Default ({label})"]
                            else:
                                summary_map[key] = [label]
                            continue

                if customized:
                    summary_map[key] = customized
                elif has_stored_value:
                    summary_map[key] = ["__defaults__"]
                else:
                    summary_map[key] = []
            else:
                summary_map[key] = []
        return summary_map

    async def _compute_locked_keys(self, node: PanelNode, guild_id: int) -> set[str]:
        if node.locked_children:
            return await node.locked_children(guild_id)
        return set()

    def _check_cooldown(self, user_id: int, node_key: str) -> bool:
        rl_key = (user_id, node_key)
        now = time.monotonic()
        if now - self._autosave_cooldowns.get(rl_key, 0.0) < self.AUTOSAVE_COOLDOWN:
            return False
        self._autosave_cooldowns[rl_key] = now
        cutoff = now - 60.0
        self._autosave_cooldowns = {
            k: v for k, v in self._autosave_cooldowns.items() if v > cutoff
        }
        return True

    async def _send_or_edit(
        self,
        interaction: discord.Interaction,
        layout: discord.ui.LayoutView,
        edit: bool,
    ) -> None:
        if interaction.response.is_done():
            if edit:
                await interaction.edit_original_response(view=layout)
            else:
                await interaction.followup.send(view=layout, ephemeral=True)
        elif edit:
            await interaction.response.edit_message(view=layout)
        else:
            await interaction.response.send_message(view=layout, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
    logger.info("AdminCog loaded")
