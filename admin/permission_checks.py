# ───────────────────────────────────────────────────────────────────────────
# VENDORED from admin_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""
Permission pre-checks for admin panel channel/role configuration.

Validates that the bot has the necessary Discord permissions before saving
a channel or role selection, preventing silent runtime failures.

Each check reads requirements from the calling PanelNode itself
(`required_channel_perms`, `requires_role_manage`) so different bots can
declare different perms per node without editing this module.
"""

import discord

from .views.panel_engine import PanelNode


# -- Display Helpers --------------------------------------------------------

_PERM_DISPLAY_NAMES: dict[str, str] = {
    "send_messages": "Send Messages",
    "embed_links": "Embed Links",
    "manage_channels": "Manage Channels",
    "manage_messages": "Manage Messages",
    "manage_roles": "Manage Roles",
    "read_message_history": "Read Message History",
    "add_reactions": "Add Reactions",
    "view_channel": "View Channel",
    "attach_files": "Attach Files",
    "use_external_emojis": "Use External Emojis",
    "mention_everyone": "Mention Everyone",
}


def _display(perm: str) -> str:
    """Return the human-readable label for a permission attribute name."""
    return _PERM_DISPLAY_NAMES.get(perm, perm.replace("_", " ").title())


# -- Validation Hooks -------------------------------------------------------

def check_channel_permissions(
    node: PanelNode,
    guild: discord.Guild,
    channel_id: int,
) -> tuple[bool, str | None]:
    """Check that the bot has every permission listed on `node.required_channel_perms`
    inside the given channel.

    Inputs:
        node:       The channel_select PanelNode being saved. Reads
                    `node.required_channel_perms` (None or empty -> no check).
        guild:      Guild the channel belongs to.
        channel_id: Channel being assigned to this setting.

    Returns (True, None) if OK, (False, error_message) if any perm is missing.
    """
    required = node.required_channel_perms
    if not required:
        return True, None

    channel = guild.get_channel(channel_id)
    if channel is None:
        return False, "Could not find that channel. It may have been deleted."

    perms = channel.permissions_for(guild.me)
    missing = [name for name in required if not getattr(perms, name, False)]

    if not missing:
        return True, None

    missing_display = ", ".join(f"**{_display(p)}**" for p in missing)
    return False, (
        f"The bot is missing permissions in <#{channel_id}>:\n"
        f"{missing_display}\n\n"
        f"Grant these permissions to the bot in that channel's settings, then try again."
    )


def check_role_permissions(
    node: PanelNode,
    guild: discord.Guild,
    role_id: int,
) -> tuple[bool, str | None]:
    """Check that the bot can manage the given role when the node opts in.

    Inputs:
        node:    The role_select PanelNode being saved. When
                 `node.requires_role_manage` is False, the check is skipped.
        guild:   Guild the role belongs to.
        role_id: Role being assigned to this setting.

    Returns (True, None) if OK, (False, error_message) if the bot lacks the
    Manage Roles server perm or the role outranks the bot's top role.
    """
    if not node.requires_role_manage:
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
            f"(**@{bot_role.name}**) is at position {bot_role.position}.\n"
            f"Move the bot's role higher in Server Settings > Roles."
        )

    return True, None
