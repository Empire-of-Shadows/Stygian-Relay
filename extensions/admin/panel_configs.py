"""
PanelNode trees for the Stygian-Relay settings panel.

Defines four sections (core, features, forwarding_rules, premium) wired to
database.guild_manager. Each successful write also writes an audit_log entry.
"""

import discord

from database import audit_log, guild_manager

from .views.panel_engine import PanelNode


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _settings(guild_id: int) -> dict:
    return await guild_manager.get_guild_settings(str(guild_id))


# ─── Core: manager role ──────────────────────────────────────────────────────

async def _get_manager_role(guild_id: int) -> list:
    v = (await _settings(guild_id)).get("manager_role_id")
    return [int(v)] if v else []


async def _set_manager_role(guild_id: int, values: list) -> bool:
    val = str(values[0]) if values else None
    ok = await guild_manager.update_guild_settings(str(guild_id), {"manager_role_id": val})
    if ok:
        await audit_log.log(
            "settings", str(guild_id), "panel",
            "set_manager_role" if val else "remove_manager_role",
            {"role_id": val},
        )
    return ok


async def _clear_manager_role(guild_id: int) -> bool:
    ok = await guild_manager.update_guild_settings(str(guild_id), {"manager_role_id": None})
    if ok:
        await audit_log.log("settings", str(guild_id), "panel", "remove_manager_role", {})
    return ok


# ─── Core: log channel ───────────────────────────────────────────────────────

async def _get_log_channel(guild_id: int) -> list:
    v = (await _settings(guild_id)).get("master_log_channel_id")
    return [int(v)] if v else []


async def _set_log_channel(guild_id: int, values: list) -> bool:
    val = str(values[0]) if values else None
    ok = await guild_manager.update_guild_settings(str(guild_id), {"master_log_channel_id": val})
    if ok:
        await audit_log.log(
            "settings", str(guild_id), "panel",
            "set_log_channel" if val else "remove_log_channel",
            {"channel_id": val},
        )
    return ok


async def _clear_log_channel(guild_id: int) -> bool:
    ok = await guild_manager.update_guild_settings(str(guild_id), {"master_log_channel_id": None})
    if ok:
        await audit_log.log("settings", str(guild_id), "panel", "remove_log_channel", {})
    return ok


# ─── Core: command prefix ────────────────────────────────────────────────────

async def _get_prefix(guild_id: int) -> list:
    v = (await _settings(guild_id)).get("command_prefix")
    return [v] if v else []


async def _set_prefix(guild_id: int, values: list) -> bool:
    val = values[0] if values else "!"
    ok = await guild_manager.update_guild_settings(str(guild_id), {"command_prefix": val})
    if ok:
        await audit_log.log("settings", str(guild_id), "panel", "set_prefix", {"prefix": val})
    return ok


async def _clear_prefix(guild_id: int) -> bool:
    ok = await guild_manager.update_guild_settings(str(guild_id), {"command_prefix": "!"})
    if ok:
        await audit_log.log("settings", str(guild_id), "panel", "reset_prefix", {})
    return ok


def _validate_prefix(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return False, None, "Prefix cannot be empty."
    if any(c.isspace() for c in raw):
        return False, None, "Prefix cannot contain whitespace."
    if len(raw) > 5:
        return False, None, "Prefix must be 5 characters or fewer."
    return True, raw, None


# ─── Feature toggles ─────────────────────────────────────────────────────────

def _make_toggle_get(feature_key: str):
    async def _get(guild_id: int) -> bool:
        s = await _settings(guild_id)
        return bool(s.get("features", {}).get(feature_key, True))
    return _get


def _make_toggle_set(feature_key: str):
    async def _set(guild_id: int, enabled: bool) -> bool:
        ok = await guild_manager.update_guild_settings(
            str(guild_id), {f"features.{feature_key}": enabled}
        )
        if ok:
            await audit_log.log(
                "settings", str(guild_id), "panel",
                f"toggle_{feature_key}", {"new_value": enabled},
            )
        return ok
    return _set


# ─── Async descriptions for read-only / informational sections ───────────────

async def _forwarding_rules_description(guild: discord.Guild) -> str:
    gid = str(guild.id)
    rules = await guild_manager.get_guild_rules(gid)
    limits = await guild_manager.get_guild_limits(gid)
    daily = await guild_manager.get_daily_message_count(gid)
    active = [r for r in rules if r.get("is_active")]

    parts = [
        f"**Active rules:** {len(active)} / {limits.get('max_rules', 3)}",
        f"**Messages forwarded today:** {daily:,} / {limits.get('daily_limit', 100):,}",
    ]
    if active:
        parts.append("")
        parts.append("**Rules:**")
        for r in active[:10]:
            src = r.get("source_channel_id")
            dst = r.get("destination_channel_id")
            name = r.get("rule_name") or "(unnamed)"
            parts.append(f"• **{name}** — <#{src}> → <#{dst}>")
        if len(active) > 10:
            parts.append(f"…and {len(active) - 10} more.")
    else:
        parts.append("")
        parts.append("*No active rules. Open **Forwarding Rules** in the panel below to create one.*")
    return "\n".join(parts)


async def _premium_description(guild: discord.Guild) -> str:
    gid = str(guild.id)
    is_prem = await guild_manager.is_premium_guild(gid)
    sub = await guild_manager.get_premium_subscription(gid)

    if not is_prem:
        return (
            "**Status:** Free Tier\n\n"
            "Upgrade by redeeming a premium code with `/redeem-code`.\n"
            "Run `/premium-status` for full details."
        )
    if sub and sub.get("is_lifetime"):
        return "**Status:** ✨ Lifetime Premium\n\nRun `/premium-status` for full details."

    expires = sub.get("expires_at") if sub else None
    expiry_str = expires.strftime("%Y-%m-%d %H:%M UTC") if expires else "Unknown"
    return (
        f"**Status:** Premium\n"
        f"**Expires:** {expiry_str}\n\n"
        f"Extend by redeeming another code with `/redeem-code`."
    )


# ─── Tree ────────────────────────────────────────────────────────────────────

CORE_NODE = PanelNode(
    key="core",
    label="Core",
    kind="menu",
    description="Manager role, log channel, and command prefix.",
    children={
        "manager_role": PanelNode(
            key="manager_role",
            label="Manager Role",
            kind="role_select",
            description="Members with this role can manage bot settings (in addition to admins).",
            get_values=_get_manager_role,
            set_values=_set_manager_role,
            clear_values=_clear_manager_role,
            min_values=0,
            max_values=1,
        ),
        "log_channel": PanelNode(
            key="log_channel",
            label="Log Channel",
            kind="channel_select",
            description="Channel where the bot posts log messages (premium redeems, errors).",
            get_values=_get_log_channel,
            set_values=_set_log_channel,
            clear_values=_clear_log_channel,
            channel_types=[discord.ChannelType.text],
            min_values=0,
            max_values=1,
        ),
        "command_prefix": PanelNode(
            key="command_prefix",
            label="Command Prefix",
            kind="modal_input",
            description="Prefix for legacy text commands. Defaults to `!`.",
            get_values=_get_prefix,
            set_values=_set_prefix,
            clear_values=_clear_prefix,
            modal_title="Set Command Prefix",
            modal_label="Prefix",
            modal_placeholder="e.g. !",
            modal_min_length=1,
            modal_max_length=5,
            modal_validator=_validate_prefix,
        ),
    },
)

FEATURES_NODE = PanelNode(
    key="features",
    label="Feature Toggles",
    kind="menu",
    description="Enable or disable individual bot features.",
    children={
        "forwarding": PanelNode(
            key="forwarding",
            label="Message Forwarding",
            kind="menu",
            description="Master switch for the message-forwarding feature. When disabled, no rules fire.",
            toggle_get=_make_toggle_get("forwarding_enabled"),
            toggle_set=_make_toggle_set("forwarding_enabled"),
        ),
        "notify_on_error": PanelNode(
            key="notify_on_error",
            label="Error Notifications",
            kind="menu",
            description="When enabled, the bot posts in-channel notices on forwarding errors and rate-limit hits.",
            toggle_get=_make_toggle_get("notify_on_error"),
            toggle_set=_make_toggle_set("notify_on_error"),
        ),
    },
)

FORWARDING_RULES_NODE = PanelNode(
    key="forwarding_rules",
    label="Forwarding Rules",
    kind="menu",
    description="View and manage your forwarding rules.",
    async_description=_forwarding_rules_description,
)

PREMIUM_NODE = PanelNode(
    key="premium",
    label="Premium",
    kind="menu",
    description="Premium subscription status (read-only).",
    async_description=_premium_description,
)

MAIN_PANEL = PanelNode(
    key="main",
    label="Stygian-Relay Settings",
    kind="menu",
    description="Configure the bot for this server.",
    children={
        "core": CORE_NODE,
        "features": FEATURES_NODE,
        "forwarding_rules": FORWARDING_RULES_NODE,
        "premium": PREMIUM_NODE,
    },
)
