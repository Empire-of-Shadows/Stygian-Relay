# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
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


def check_bot_guild_permission(
    guild: discord.Guild,
    permission: str,
) -> tuple[bool, str | None]:
    """Check that the bot itself holds a server-wide permission.

    Used by create-entity flows (standard §11) to refuse at the button click -
    before the admin types anything - rather than failing after modal submit.
    ``permission`` is the attribute name on ``discord.Permissions``
    ("manage_roles", "manage_channels", ...).

    Returns (True, None) if OK, (False, error_message) otherwise.
    """
    if getattr(guild.me.guild_permissions, permission, False):
        return True, None
    return False, (
        f"The bot is missing the **{_display(permission)}** server permission.\n\n"
        f"Grant it to the bot's role in Server Settings > Roles, then try again."
    )


def check_assignable_role(
    guild: discord.Guild,
    role_id: int,
) -> tuple[bool, str | None]:
    """Check unconditionally that the bot could assign the given role to a member.

    This is the whole "requires_role_manage" rule set, independent of any node, so
    flows that always need it (a dict_editor whose values are roles) can call it
    directly. `check_role_permissions` delegates here once a node opts in.

    Rejects, in order: no Manage Roles server permission, a role that no longer
    exists, @everyone, an integration-managed role (bot roles, the booster role -
    Discord never lets anyone assign these), and a role that is not below the
    bot's top role.

    Returns (True, None) if OK, (False, error_message) otherwise.
    """
    if not guild.me.guild_permissions.manage_roles:
        return False, (
            "The bot is missing the **Manage Roles** server permission.\n\n"
            "Grant it in Server Settings > Roles, then try again."
        )

    role = guild.get_role(role_id)
    if role is None:
        return False, "Could not find that role. It may have been deleted."

    if role.is_default():
        return False, (
            "**@everyone** cannot be used here - every member already has it, and "
            "Discord does not allow it to be assigned or removed.\n\n"
            "Pick a normal role instead."
        )

    if role.managed:
        return False, (
            f"**@{role.name}** is managed by an integration (a bot role, the "
            f"Server Booster role, or a subscription role), so Discord does not "
            f"allow anyone to assign it.\n\n"
            f"Pick a normal role instead."
        )

    if role >= guild.me.top_role:
        bot_role = guild.me.top_role
        return False, (
            f"The bot's highest role must be **above** **@{role.name}** in the role hierarchy.\n\n"
            f"**@{role.name}** is at position {role.position}, but the bot's top role "
            f"(**@{bot_role.name}**) is at position {bot_role.position}.\n"
            f"Move the bot's role higher in Server Settings > Roles."
        )

    return True, None


def check_delegation_role(
    guild: discord.Guild,
    role_id: int,
) -> tuple[bool, str | None]:
    """Check that a role is a sane target for DELEGATION (access/permission lists).

    For roles the bot never assigns - it only checks membership (panel access,
    command access). The hierarchy rule deliberately does NOT apply: admin and
    staff roles normally sit above every bot, and blocking them would break the
    setting's primary purpose. What IS rejected:

    - a role that no longer exists,
    - **@everyone** - every member holds it, so delegating to it silently grants
      the permission to the whole server,
    - an integration-managed role (bot roles, Server Booster, subscription
      roles) - Discord grants these automatically, so membership is not under
      the admins' control and the delegation self-extends.

    Returns (True, None) if OK, (False, error_message) otherwise.
    """
    role = guild.get_role(role_id)
    if role is None:
        return False, "Could not find that role. It may have been deleted."

    if role.is_default():
        return False, (
            "**@everyone** cannot be used here - every member holds it, so this "
            "would grant access to the entire server.\n\n"
            "Pick a normal role instead."
        )

    if role.managed:
        return False, (
            f"**@{role.name}** is managed by an integration (a bot role, the "
            f"Server Booster role, or a subscription role). Discord grants it "
            f"automatically, so access through it would not be under your "
            f"control.\n\nPick a normal role instead."
        )

    return True, None


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
    Manage Roles server perm, the role is unassignable by anyone (@everyone or
    integration-managed), or the role outranks the bot's top role.
    """
    if not node.requires_role_manage:
        return True, None

    return check_assignable_role(guild, role_id)
