# ---------------------------------------------------------------------------
# VENDORED from admin_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/admin_engine/ and run:
#     python tools/sync_admin_engine.py
# Drift is enforced by:  python tools/sync_admin_engine.py --check
# ---------------------------------------------------------------------------
"""
admin_engine - "not set up yet" notices (vendored engine module).

One place to build the message a bot shows when a feature is used before it has been
configured. Every such notice carries the same three things in the same order:

1. what is missing,
2. that ``/admin panel`` is where it gets fixed, and
3. **who can actually fix it right now**.

Point 3 is the reason this is engine code rather than a string in each bot. On a fresh
install no roles have been delegated, so the only people who can open the panel are the
server owner and anyone with Manage Server. Telling a regular member to "run /admin
panel" is dead advice. The notice names the owner instead and points them at the panel's
role-access node, so they can hand access to their staff and stop being the only person
who can configure anything.

Nothing here pings: the owner is rendered as a plain display name, never a mention.
These notices can fire on any member's command, and some bots send them into a channel
rather than as an ephemeral reply.

Backend reads go through the bindings seam (``settings/bindings.py``), lazily inside the
functions, matching ``auth.py`` - so bindings can import this module without a cycle.
Role ids are coerced with ``int()`` because bots differ on whether they store panel role
ids as ints or strings.

Per-bot customization, all optional, read from ``settings/bindings.py``:

- ``ROLE_ACCESS_PATH`` - breadcrumb to the panel's role-access node when a bot's tree
  labels it differently (ImperialReminder: ``"Panel Access -> Panel Access Roles"``).
- ``PANEL_COMMAND`` - the panel command, if a bot ever renames it.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Set

import discord

logger = logging.getLogger("AdminSetupNotice")

# Defaults; a bot overrides either by defining the same name in its bindings seam.
DEFAULT_PANEL_COMMAND = "`/admin panel`"
DEFAULT_ROLE_ACCESS_PATH = "Role Configuration -> Panel Access Roles"

ADMIN_ROLES_PATH = "roles.admin_role_ids"
MOD_ROLES_PATH = "roles.mod_role_ids"


def _binding(name: str, default):
    """Read an optional constant from the bindings seam, falling back to the default."""
    try:
        from .settings import bindings  # lazy: avoid bindings<->setup_notice cycle
        return getattr(bindings, name, default)
    except Exception:
        return default


def panel_command() -> str:
    """The bot's admin panel command, as inline code."""
    return _binding("PANEL_COMMAND", DEFAULT_PANEL_COMMAND)


def role_access_path() -> str:
    """Breadcrumb to the panel node that grants panel access by role."""
    return _binding("ROLE_ACCESS_PATH", DEFAULT_ROLE_ACCESS_PATH)


def _as_ids(values: Any) -> Set[int]:
    """Coerce a stored role-id list to ints, dropping anything unparseable.

    Bots disagree on the storage type (ImperialReminder stores strings, TheCodex and
    TheHost ints) while discord.py always hands back ints, so both sides meet here.
    """
    out: Set[int] = set()
    for v in values or []:
        try:
            out.add(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _owner_name(guild: Optional[discord.Guild]) -> str:
    """Owner's display name, as plain text. Falls back when the member is uncached."""
    owner = getattr(guild, "owner", None)
    if owner is not None:
        return f"**{owner.display_name}**"
    return "the server owner"


async def _audience_line(
    guild: Optional[discord.Guild],
    viewer: Optional[discord.Member],
) -> str:
    """The "who can fix this" sentence, tailored to the guild and the viewer.

    Fails soft: if config cannot be read we assume access has been delegated, which
    yields the neutral "ask an admin" wording rather than wrongly nagging the owner.
    """
    if guild is None:
        return ""

    delegated = True
    viewer_has_access = False
    try:
        from .settings.bindings import config_get  # lazy: see module docstring

        admin_roles = _as_ids(await config_get(guild.id, ADMIN_ROLES_PATH, default=[]))
        mod_roles = _as_ids(await config_get(guild.id, MOD_ROLES_PATH, default=[]))
        delegated = bool(admin_roles or mod_roles)

        perms = getattr(viewer, "guild_permissions", None)
        if perms and perms.manage_guild:
            viewer_has_access = True
        elif viewer is not None:
            viewer_role_ids = {role.id for role in getattr(viewer, "roles", [])}
            viewer_has_access = bool(viewer_role_ids & admin_roles)
    except Exception as e:
        logger.warning("Could not read panel roles for guild %s: %s", guild.id, e)

    panel = panel_command()

    if viewer_has_access:
        line = "You have panel access, so you can set this up yourself."
        if not delegated:
            # The one person who can fix it is reading: also nudge them to share the
            # load, since right now nobody else can configure anything.
            line += (
                f"\nNo one else can yet - add your staff roles under {panel} -> "
                f"**{role_access_path()}** so they can help."
            )
        return line

    if not delegated:
        return (
            f"Only {_owner_name(guild)} and members with **Manage Server** can open the "
            f"panel right now.\n"
            f"{_owner_name(guild)}: add your staff roles under {panel} -> "
            f"**{role_access_path()}** so they can help set the server up."
        )

    return f"Ask an admin or moderator to run {panel}."


async def setup_notice_text(
    guild: Optional[discord.Guild],
    *,
    what: str,
    path: str,
    viewer: Optional[discord.Member] = None,
    detail: str = "",
) -> str:
    """Build the plain-text form of a setup notice.

    Args:
        guild:  The guild the notice is about.
        what:   What is missing, as a noun phrase - "bump reminders", "a suggestions
                channel". It is phrased into the opening sentence, so it reads
                naturally whether singular or plural.
        path:   Breadcrumb inside the admin panel, e.g. "WYR Settings -> WYR Channel".
        viewer: Who will read this, so the notice can address them directly when they
                already have panel access.
        detail: Optional extra sentence appended after the opening line.
    """
    parts = [f"This server has not set up **{what}** yet."]
    if detail:
        parts.append(detail)
    parts.append(f"**Set it up:** {panel_command()} -> **{path}**")

    audience = await _audience_line(guild, viewer)
    if audience:
        parts.append(audience)

    return "\n\n".join(parts)


async def setup_notice_embed(
    guild: Optional[discord.Guild],
    *,
    what: str,
    path: str,
    viewer: Optional[discord.Member] = None,
    detail: str = "",
    title: str = "Not Set Up Yet",
) -> discord.Embed:
    """The embed form of the same notice."""
    description = await setup_notice_text(
        guild, what=what, path=path, viewer=viewer, detail=detail
    )
    return discord.Embed(
        title=title,
        description=description,
        color=discord.Color.orange(),
    )


async def send_setup_notice(
    interaction: discord.Interaction,
    *,
    what: str,
    path: str,
    detail: str = "",
    title: str = "Not Set Up Yet",
) -> None:
    """Send a setup notice ephemerally, respecting whether the interaction was answered."""
    embed = await setup_notice_embed(
        interaction.guild,
        what=what,
        path=path,
        viewer=interaction.user if isinstance(interaction.user, discord.Member) else None,
        detail=detail,
        title=title,
    )
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException as e:
        logger.debug("Could not deliver setup notice: %s", e)


async def permission_notice_embed(
    guild: Optional[discord.Guild],
    *,
    action: str,
    admin_only: bool = False,
) -> discord.Embed:
    """Notice for a staff-only command run by someone without the tier.

    Beyond "you can't", this explains how the tier is granted, since on a fresh install
    the honest answer is "nobody has delegated it yet" rather than "you were denied".
    """
    tier = (
        "the configured **Panel Access** role" if admin_only
        else "a configured **Panel Access** or **Mod Access** role"
    )
    parts = [f"You need **Administrator** or {tier} to {action}."]

    delegated = True
    try:
        if guild is not None:
            from .settings.bindings import config_get  # lazy: see module docstring

            admin_roles = _as_ids(await config_get(guild.id, ADMIN_ROLES_PATH, default=[]))
            mod_roles = _as_ids(await config_get(guild.id, MOD_ROLES_PATH, default=[]))
            delegated = bool(admin_roles or mod_roles)
    except Exception as e:
        logger.warning(
            "Could not read panel roles for guild %s: %s", getattr(guild, "id", "?"), e
        )

    if not delegated:
        parts.append(
            f"No staff roles have been set up yet, so only {_owner_name(guild)} and "
            f"members with **Manage Server** can use this.\n"
            f"{_owner_name(guild)}: assign them under {panel_command()} -> "
            f"**{role_access_path()}**."
        )

    return discord.Embed(
        title="Permission Denied",
        description="\n\n".join(parts),
        color=discord.Color.red(),
    )
