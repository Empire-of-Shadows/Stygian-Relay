"""The member's view of a relay: which routes exist, and which of them carry them.

Owner ruling 2026-08-13: an ordinary member gets to see this. Relay is the one bot in the
fleet that republishes a member's own words into a channel they may not be in - possibly
in a server they are not in - so "where do my messages go" is a question a member is
entitled to an answer to, and the answer is not admin-only information.

WHAT THIS IS ALLOWED TO RETURN, and why it is narrower than the admin rules page:

  - Active routes only. A paused rule is a server's configuration, not a description of
    where a member's messages currently go.
  - Channel NAMES, resolved here, server-side. The member never receives the guild's
    channel listing - that endpoint stays behind ``require_panel_access``.
  - The destination SERVER's name when a route leaves the server, because "your messages
    are copied somewhere else" is meaningless without saying where.
  - Whether each route carries THIS member, computed from their own roles and their own
    id. No other member's filter membership is ever returned, and the filter lists
    themselves are not returned either - only the yes/no answer about the caller.

It never returns rule counts for other people, opted-out members, or any filter contents.

The carries-you answer mirrors ``commands/forward/forward.py::check_author_filters``:
a deny match rejects outright; if either allow list is non-empty the author must match at
least one across both. Divergence here would tell a member something untrue about their
own messages, so the two must move together.

It adds one state the bot does not need: **None, meaning "we could not work it out"**.
The bot always knows a member's roles because it holds the member object; this page has
to fetch them over HTTP, and that fetch can fail. Reporting a failed fetch as an empty
role set is not a smaller version of the truth, it is the opposite of it - an empty set
matches no ``deny_role_ids``, so a blocked member was told they were carried. Any rule
whose verdict depends on roles we could not read returns None, and the counts and the UI
keep None distinct from False all the way to the member.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from dashboard import db
from dashboard._engine.auth.panel_access import member_roles_lookup
from dashboard.config import BOT_TOKEN, DISCORD_API_BASE
from dashboard.routers.dashboard import fetch_guild_channels
from dashboard.services import user_data

logger = logging.getLogger(__name__)

_GUILD_NAME_TTL = 300.0
_guild_name_cache: dict[str, tuple[str | None, float]] = {}


async def _guild_name(guild_id: str) -> str | None:
    """The guild's name via the bot token, cached for five minutes.

    Used only for a route's DESTINATION server, which the member may not be in and so
    cannot be named from their session guild list. Returns None rather than raising when
    the fetch fails - the page then says "another server" without naming it, which is
    still the honest answer.
    """
    key = str(guild_id)
    now = time.monotonic()
    cached = _guild_name_cache.get(key)
    if cached is not None and now - cached[1] < _GUILD_NAME_TTL:
        return cached[0]
    if not BOT_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{DISCORD_API_BASE}/guilds/{key}",
                headers={"Authorization": f"Bot {BOT_TOKEN}"},
            )
    except Exception as e:
        logger.warning("Guild name fetch failed for %s: %s", key, e)
        return None
    name = resp.json().get("name") if resp.status_code == 200 else None
    _guild_name_cache[key] = (name, now)
    return name


def _ids(values) -> set[str]:
    return {str(v) for v in (values or [])}


def carries_author(
    author_filters, user_id: str, role_ids: set[str], *, roles_known: bool
) -> bool | None:
    """Whether a rule with these author filters would carry this member's messages.

    Mirrors ``check_author_filters``: missing or non-dict filters mean no filtering.

    Returns ``None`` for "we could not work it out", which happens when the answer
    genuinely turns on roles and ``roles_known`` is False. This used to answer a
    confident True in that case, and it was answering the OPPOSITE of the truth:
    an unread role set matches no ``deny_role_ids``, so a member who is in fact
    blocked from a route was told their messages are carried. ``roles_known`` is
    keyword-only and has no default on purpose - a caller has to say whether it
    actually read the roles.

    Only a rule that DEPENDS on roles goes unknown. One filtering by user id alone
    is still answered definitively, because the roles never entered into it.
    """
    if not isinstance(author_filters, dict) or not author_filters:
        return True
    uid = str(user_id)
    if uid in _ids(author_filters.get("deny_user_ids")):
        return False

    deny_roles = _ids(author_filters.get("deny_role_ids"))
    if deny_roles:
        if not roles_known:
            return None
        if deny_roles & role_ids:
            return False

    allow_users = _ids(author_filters.get("allow_user_ids"))
    allow_roles = _ids(author_filters.get("allow_role_ids"))
    if allow_users or allow_roles:
        # An explicit allow by user id settles it without needing the roles.
        if uid in allow_users:
            return True
        if allow_roles and not roles_known:
            return None
        if not (allow_roles & role_ids):
            return False
    return True


async def build_member_view(
    user_id: str, guild_ids: list[str], guild_names: dict[str, str]
) -> dict:
    """Assemble the member pane for every guild in ``guild_ids``.

    ``guild_ids`` must already have been filtered to guilds the caller shares with the
    bot - this function does no authorization. ``guild_names`` is the caller's own
    session snapshot, used for the SOURCE server's name.
    """
    uid = str(user_id)

    privacy = await user_data.get_privacy(uid)
    # The master switch and the per-feature switch both stop relaying. Reported as one
    # boolean because that is the only thing the pane needs to say.
    relaying_paused = bool(privacy.get("all") or privacy.get("relay_messages"))
    name_hidden = bool(privacy.get("all") or privacy.get("show_name"))

    out_guilds: list[dict] = []
    for gid in guild_ids:
        doc = await db.guild_settings().find_one(
            {"guild_id": str(gid)},
            {"_id": 0, "guild_id": 1, "is_enabled": 1, "features": 1, "rules": 1},
        )
        if not doc:
            out_guilds.append({
                "guild_id": str(gid),
                "guild_name": guild_names.get(str(gid)),
                "forwarding_enabled": False,
                "has_config": False,
                "routes": [],
                "carrying_you": 0,
                "unknown_you": 0,
            })
            continue

        features = doc.get("features") or {}
        forwarding_enabled = bool(doc.get("is_enabled", True)) and bool(
            features.get("forwarding_enabled", True)
        )
        active = [r for r in (doc.get("rules") or []) if r.get("is_active")]

        # One member fetch per guild, shared by every rule in it. The engine caches it
        # for a minute and rate-limits the bot token, so a member in many servers still
        # costs one fetch per server per minute.
        # The OUTCOME is carried, not just the roles: an empty set from a failed fetch
        # looks exactly like a member who holds no roles, and reading it as the latter
        # made every deny-by-role rule silently stop matching.
        lookup = await member_roles_lookup(str(gid), uid) if active else None
        roles = set(lookup.roles) if lookup is not None else set()
        roles_known = lookup.resolved if lookup is not None else True
        channels = await fetch_guild_channels(str(gid)) if active else []
        names = {c["id"]: c["name"] for c in channels}

        routes: list[dict] = []
        for rule in active:
            destination_guild = str(rule.get("destination_guild_id") or "") or None
            cross_server = destination_guild is not None and destination_guild != str(gid)
            source_id = str(rule.get("source_channel_id") or "")
            destination_id = str(rule.get("destination_channel_id") or "")
            carries = carries_author(
                (rule.get("settings") or {}).get("author_filters"),
                uid,
                roles,
                roles_known=roles_known,
            )
            routes.append({
                "rule_id": str(rule.get("rule_id") or ""),
                "source_channel_id": source_id,
                "source_channel_name": names.get(source_id),
                "destination_channel_id": destination_id,
                # A cross-server destination is in a guild whose channel listing this
                # loop did not fetch, so its name is left null and the page says
                # "a channel in <server>" instead of inventing one.
                "destination_channel_name": (
                    None if cross_server else names.get(destination_id)
                ),
                "cross_server": cross_server,
                "destination_guild_id": destination_guild,
                "destination_guild_name": None,
                "carries_you": carries,
            })

        # Destination server names, one fetch per distinct server rather than per route.
        cross_ids = {r["destination_guild_id"] for r in routes if r["cross_server"]}
        cross_ids.discard(None)
        if cross_ids:
            resolved = await asyncio.gather(
                *(_guild_name(cid) for cid in cross_ids), return_exceptions=True
            )
            name_map = {
                cid: (value if isinstance(value, str) else None)
                for cid, value in zip(cross_ids, resolved)
            }
            for route in routes:
                if route["cross_server"]:
                    route["destination_guild_name"] = name_map.get(
                        route["destination_guild_id"]
                    )

        out_guilds.append({
            "guild_id": str(gid),
            "guild_name": guild_names.get(str(gid)),
            "forwarding_enabled": forwarding_enabled,
            "has_config": True,
            "routes": routes,
            # `is True` and `is None`, not truthiness - an unknown route must not be
            # quietly counted as "not carrying you", which is the whole bug being fixed.
            "carrying_you": sum(1 for r in routes if r["carries_you"] is True),
            "unknown_you": sum(1 for r in routes if r["carries_you"] is None),
        })

    return {
        "guilds": out_guilds,
        "privacy": {
            "relaying_paused": relaying_paused,
            "name_hidden": name_hidden,
        },
    }
