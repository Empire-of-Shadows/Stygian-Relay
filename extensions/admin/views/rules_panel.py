"""
Forwarding Rules panel — Components v2 LayoutView for the admin panel's
"Forwarding Rules" category.

Renders the active rules and offers Create / Edit / Refresh / Close actions.
Hands control of msg2 to the forward cog's `RuleCreationFlow` /
`RuleSettingsView` for guided creation and editing, and restores itself when
the wizard finishes (via `SetupState.on_exit`).
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

import discord

from database import guild_manager
from .base import PanelLayoutBuilder, create_empty_layout, create_unique_id

logger = logging.getLogger(__name__)


def _rule_label(rule: dict, guild: discord.Guild) -> str:
    name = rule.get("rule_name") or f"Rule {str(rule.get('rule_id', ''))[:8]}"
    status = "🟢" if rule.get("is_active") else "🔴"
    return f"{status} {name}"[:100]


def _rule_description(rule: dict, guild: discord.Guild, bot=None) -> str:
    src_id = rule.get("source_channel_id")
    dst_id = rule.get("destination_channel_id")
    if isinstance(src_id, dict) and "$numberLong" in src_id:
        src_id = int(src_id["$numberLong"])
    if isinstance(dst_id, dict) and "$numberLong" in dst_id:
        dst_id = int(dst_id["$numberLong"])

    src = guild.get_channel(int(src_id)) if src_id else None
    src_name = f"#{src.name}" if src else f"<#{src_id}>"

    # Destination may be cross-guild — fall back to the bot-global channel
    # cache and annotate the foreign guild name so the panel reads sensibly.
    dst = guild.get_channel(int(dst_id)) if dst_id else None
    if dst is not None:
        dst_name = f"#{dst.name}"
    elif bot is not None and dst_id:
        foreign = bot.get_channel(int(dst_id))
        if foreign is not None:
            foreign_guild = getattr(foreign, "guild", None)
            foreign_guild_name = getattr(foreign_guild, "name", None)
            dst_name = (
                f"#{foreign.name} (in {foreign_guild_name})"
                if foreign_guild_name and getattr(foreign_guild, "id", None) != guild.id
                else f"#{foreign.name}"
            )
        else:
            dst_name = f"<#{dst_id}>"
    else:
        dst_name = f"<#{dst_id}>" if dst_id else "<unset>"

    return f"{src_name} → {dst_name}"[:100]


async def build_rules_panel_view(
    *,
    guild: discord.Guild,
    admin_id: int,
    forward_cog,
    restore_callback: Callable[[discord.Interaction], Awaitable[None]],
    refresh_overview: Callable[[], Awaitable[None]] | None,
    on_close: Callable[[discord.Interaction], Awaitable[None]],
) -> discord.ui.LayoutView:
    """Build a fresh rules panel LayoutView from current DB state."""

    gid = str(guild.id)
    rules = await guild_manager.get_guild_rules(gid)
    limits = await guild_manager.get_guild_limits(gid)
    daily = await guild_manager.get_daily_message_count(gid)
    max_rules = limits.get("max_rules", 3)
    daily_limit = limits.get("daily_limit", 100)
    is_premium = limits.get("is_premium", False)

    active = [r for r in rules if r.get("is_active")]
    cap_reached = len(active) >= max_rules

    unique_id = create_unique_id()
    builder = PanelLayoutBuilder()

    builder.add_header("## Forwarding Rules")
    builder.add_text(
        f"**Active rules:** {len(active)} / {max_rules}"
        f" · **Forwarded today:** {daily:,} / {daily_limit:,}"
        + ("  · 💎 Premium" if is_premium else "")
    )

    # Runtime metrics (resets on bot restart) — sourced from the listener cog,
    # which lives separately from forward_cog (slash-commands) we already have.
    listener = forward_cog.bot.get_cog("Forwarding") if getattr(forward_cog, "bot", None) else None
    metrics = listener.get_metrics(guild.id) if listener and hasattr(listener, "get_metrics") else None
    if metrics and any(metrics.values()):
        builder.add_text(
            "**Since last restart:** "
            f"{metrics.get('forwarded', 0):,} forwarded · "
            f"{metrics.get('rate_limited', 0):,} rate-limited · "
            f"{metrics.get('daily_limit_hit', 0):,} daily-cap hits · "
            f"{metrics.get('perm_failure', 0):,} perm fails · "
            f"{metrics.get('oversized_fallback', 0):,} oversized · "
            f"{metrics.get('auto_deactivated', 0):,} auto-disabled"
        )

    builder.add_separator()

    if rules:
        lines = ["**Rules:**"]
        for rule in rules[:25]:
            status = "🟢" if rule.get("is_active") else "🔴"
            name = rule.get("rule_name") or f"Rule {str(rule.get('rule_id', ''))[:8]}"
            lines.append(f"{status} **{name}** — {_rule_description(rule, guild, forward_cog.bot)}")
        if len(rules) > 25:
            lines.append(f"…and {len(rules) - 25} more.")
        builder.add_text("\n".join(lines))
    else:
        builder.add_text("*No rules configured. Click **Create Rule** to add one.*")

    builder.add_separator()

    # Rule select (edit entry point)
    if rules:
        options = [
            discord.SelectOption(
                label=_rule_label(rule, guild),
                value=str(rule["rule_id"]),
                description=_rule_description(rule, guild, forward_cog.bot),
            )
            for rule in rules[:25]
        ]
        rule_select = discord.ui.Select(
            placeholder="Select a rule to edit…",
            options=options,
            custom_id=f"rules_panel_select_{unique_id}",
            min_values=1,
            max_values=1,
        )

        async def _on_select(sel_interaction: discord.Interaction):
            if sel_interaction.user.id != admin_id:
                await sel_interaction.response.send_message(
                    "Only the admin who opened this panel can interact with it.",
                    ephemeral=True,
                )
                return
            rule_id = sel_interaction.data["values"][0]
            rule = next((r for r in rules if str(r.get("rule_id")) == rule_id), None)
            if not rule:
                await sel_interaction.response.send_message(
                    "Rule no longer exists. Refresh the panel.", ephemeral=True
                )
                return
            await _enter_edit_flow(
                sel_interaction, rule, forward_cog, restore_callback,
                refresh_overview, admin_id,
            )

        rule_select.callback = _on_select
        builder.add_select(rule_select)

    # Action row: Create / Refresh / Close
    action_row = discord.ui.ActionRow()

    create_label = "Create Rule" + (" (cap reached)" if cap_reached else "")
    create_btn = discord.ui.Button(
        label=create_label,
        style=discord.ButtonStyle.success if not cap_reached else discord.ButtonStyle.secondary,
        custom_id=f"rules_panel_create_{unique_id}",
        disabled=cap_reached,
    )

    async def _on_create(btn_interaction: discord.Interaction):
        if btn_interaction.user.id != admin_id:
            await btn_interaction.response.send_message(
                "Only the admin who opened this panel can interact with it.",
                ephemeral=True,
            )
            return
        await _enter_create_flow(
            btn_interaction, forward_cog, restore_callback,
            refresh_overview, admin_id,
        )

    create_btn.callback = _on_create
    action_row.add_item(create_btn)

    refresh_btn = discord.ui.Button(
        label="Refresh",
        style=discord.ButtonStyle.secondary,
        custom_id=f"rules_panel_refresh_{unique_id}",
    )

    async def _on_refresh(btn_interaction: discord.Interaction):
        if btn_interaction.user.id != admin_id:
            await btn_interaction.response.send_message(
                "Only the admin who opened this panel can interact with it.",
                ephemeral=True,
            )
            return
        new_layout = await build_rules_panel_view(
            guild=guild,
            admin_id=admin_id,
            forward_cog=forward_cog,
            restore_callback=restore_callback,
            refresh_overview=refresh_overview,
            on_close=on_close,
        )
        await btn_interaction.response.edit_message(view=new_layout, embed=None, attachments=[])

    refresh_btn.callback = _on_refresh
    action_row.add_item(refresh_btn)

    close_btn = discord.ui.Button(
        label="Close",
        style=discord.ButtonStyle.danger,
        custom_id=f"rules_panel_close_{unique_id}",
    )
    close_btn.callback = on_close
    action_row.add_item(close_btn)

    builder.add_item(action_row)
    return builder.build()


async def _enter_create_flow(
    interaction: discord.Interaction,
    forward_cog,
    restore_callback: Callable[[discord.Interaction], Awaitable[None]],
    refresh_overview: Callable[[], Awaitable[None]] | None,
    admin_id: int,
) -> None:
    """Hand off msg2 to RuleCreationFlow.start_rule_creation."""
    from extensions.forward.setup_helpers.state_manager import state_manager

    gid = interaction.guild_id

    # Cap check (defensive — button is disabled when reached, but DB may have changed)
    limits = await guild_manager.get_guild_limits(str(gid))
    rules = await guild_manager.get_guild_rules(str(gid))
    active = [r for r in rules if r.get("is_active")]
    if len(active) >= limits.get("max_rules", 3):
        await interaction.response.send_message(
            f"❌ Active-rule limit reached ({limits.get('max_rules', 3)}). "
            "Disable or delete a rule first.",
            ephemeral=True,
        )
        return

    session = await state_manager.create_session(gid, interaction.user.id)
    session.on_exit = _make_on_exit(restore_callback, refresh_overview)

    # Pre-fill log channel from guild settings (mirrors removed /forward setup).
    try:
        gs = await guild_manager.get_guild_settings(gid)
        if gs:
            log_channel_id = gs.get("master_log_channel_id")
            if log_channel_id:
                session.master_log_channel = log_channel_id
                await state_manager.update_session(
                    gid, {"master_log_channel": log_channel_id}
                )
    except Exception as e:
        logger.debug(f"Pre-fill log channel failed: {e}")

    # Defer ephemerally so the wizard renders into its own ephemeral message
    # rather than overwriting the rules panel (msg2). The Components v2 wizard
    # then edits this ephemeral via edit_original_response on every step.
    await interaction.response.defer(ephemeral=True)
    await forward_cog.rule_creation_flow.start_rule_creation(interaction)


async def _enter_edit_flow(
    interaction: discord.Interaction,
    rule: dict,
    forward_cog,
    restore_callback: Callable[[discord.Interaction], Awaitable[None]],
    refresh_overview: Callable[[], Awaitable[None]] | None,
    admin_id: int,
) -> None:
    """Hand off msg2 to the rule-preview / settings editor."""
    from extensions.forward.setup_helpers.state_manager import state_manager

    gid = interaction.guild_id
    session = await state_manager.create_session(gid, interaction.user.id)
    session.current_rule = rule
    session.is_editing = True
    session.on_exit = _make_on_exit(restore_callback, refresh_overview)

    await state_manager.update_session(gid, {
        "current_rule": session.current_rule,
        "is_editing": True,
        "step": "rule_preview",
    })

    # See _enter_create_flow: wizard runs in a separate ephemeral, not msg2.
    await interaction.response.defer(ephemeral=True)
    await forward_cog.rule_creation_flow.show_rule_preview_step(interaction, session)


def _make_on_exit(
    restore_callback: Callable[[discord.Interaction], Awaitable[None]],
    refresh_overview: Callable[[], Awaitable[None]] | None,
) -> Callable[[discord.Interaction], Awaitable[None]]:
    """Wrap restore_callback with overview refresh after the wizard ends."""

    async def _on_exit(interaction: discord.Interaction) -> None:
        try:
            await restore_callback(interaction)
        finally:
            if refresh_overview is not None:
                try:
                    await refresh_overview()
                except Exception as e:
                    logger.debug(f"refresh_overview after on_exit failed: {e}")

    return _on_exit
