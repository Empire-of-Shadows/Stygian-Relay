"""
Bot-permission pre-checks for panel channel/role configuration.

Validates that the bot has the necessary Discord permissions in the target
channel/role before saving, preventing silent runtime failures.
"""

import discord


CHANNEL_PERMISSION_REQUIREMENTS: dict[str, list[str]] = {
    "log_channel": ["view_channel", "send_messages", "embed_links"],
}

ROLE_MANAGE_REQUIREMENTS: dict[str, bool] = {}

_PERM_DISPLAY_NAMES: dict[str, str] = {
    "send_messages": "Send Messages",
    "embed_links": "Embed Links",
    "manage_channels": "Manage Channels",
    "manage_messages": "Manage Messages",
    "manage_roles": "Manage Roles",
    "read_message_history": "Read Message History",
    "add_reactions": "Add Reactions",
    "view_channel": "View Channel",
}


def check_channel_permissions(guild: discord.Guild, channel_id: int, config_key: str) -> tuple[bool, str | None]:
    required = CHANNEL_PERMISSION_REQUIREMENTS.get(config_key)
    if not required:
        return True, None

    channel = guild.get_channel(channel_id)
    if channel is None:
        return False, "Could not find that channel. It may have been deleted."

    perms = channel.permissions_for(guild.me)
    missing = [name for name in required if not getattr(perms, name, False)]
    if not missing:
        return True, None

    missing_display = ", ".join(f"**{_PERM_DISPLAY_NAMES.get(p, p)}**" for p in missing)
    return False, (
        f"The bot is missing permissions in <#{channel_id}>:\n"
        f"{missing_display}\n\n"
        f"Grant these permissions to the bot in that channel's settings, then try again."
    )


def check_role_permissions(guild: discord.Guild, role_id: int, config_key: str) -> tuple[bool, str | None]:
    if not ROLE_MANAGE_REQUIREMENTS.get(config_key):
        return True, None

    if not guild.me.guild_permissions.manage_roles:
        return False, (
            "The bot is missing the **Manage Roles** server permission.\n\n"
            "Grant it in Server Settings > Roles, then try again."
        )

    role = guild.get_role(role_id)
    if role is None:
        return False, "Could not find that role. It may have been deleted."

    if role >= guild.me.top_role:
        bot_role = guild.me.top_role
        return False, (
            f"The bot's highest role must be **above** **@{role.name}** in the role hierarchy.\n\n"
            f"**@{role.name}** is at position {role.position}, but the bot's top role "
            f"(**@{bot_role.name}**) is at position {bot_role.position}."
        )

    return True, None
