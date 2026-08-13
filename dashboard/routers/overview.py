"""Guild overview API - everything the dashboard home renders, in one round trip.

Gated on ``require_panel_access``, the same tier every other guild route in this
dashboard uses: relay is admin-only, and a delegated ``manager_role_id`` counts
as admin.

Read-only. The five sections are built concurrently and EACH one is allowed to
fail on its own - a section that raises is logged and returned as ``null``,
which is why every section is nullable in the frontend contract. One broken
collection must not blank the page.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from dashboard import db
from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.services import overview as overview_service

from storage.log import get_logger

logger = get_logger("dashboard.routers.overview")

router = APIRouter(tags=["overview"])

#: Section name -> the key it occupies in the response, in gather order.
_SECTIONS = ("traffic", "rules", "delivery", "plan", "config")


@router.get("/guilds/{guild_id}/overview")
async def guild_overview(guild_id: str, session: dict = Depends(get_current_user)):
    """Return a ``GuildOverview`` for one guild."""
    await require_panel_access(session, guild_id)
    gid = str(guild_id)

    # Fetched once and handed to the sections that need it, rather than four
    # separate reads of the same document. Only the fields the overview uses.
    settings_doc = await db.guild_settings().find_one(
        {"guild_id": gid},
        {
            "_id": 0,
            "is_enabled": 1,
            "features": 1,
            "master_log_channel_id": 1,
            "manager_role_id": 1,
            "inbound_allowed_guilds": 1,
            "lifetime_forwarded": 1,
            "rules": 1,
        },
    ) or {}

    results = await asyncio.gather(
        overview_service.build_traffic(gid, settings_doc),
        overview_service.build_rules(gid, settings_doc),
        overview_service.build_delivery(gid),
        overview_service.build_plan(gid),
        overview_service.build_config(gid, settings_doc),
        return_exceptions=True,
    )

    sections: dict[str, dict | None] = {}
    for name, result in zip(_SECTIONS, results):
        if isinstance(result, BaseException):
            logger.warning(
                "Overview section '%s' failed for guild %s", name, gid,
                exc_info=result,
            )
            sections[name] = None
        else:
            sections[name] = result

    try:
        # Passed by name, not splatted: the rail reads four of the five sections
        # and a splat of all of them raises TypeError on `plan`, which the
        # except below would swallow into a permanently empty rail.
        features = overview_service.build_features(
            settings_doc,
            traffic=sections["traffic"],
            rules=sections["rules"],
            delivery=sections["delivery"],
            config=sections["config"],
        )
    except Exception:
        # features is not nullable in the contract, so an empty rail is the only
        # shape available here. Logged loudly because an empty rail on a
        # configured guild is a bug, not a state the data can produce.
        logger.error("Overview feature rail failed for guild %s", gid, exc_info=True)
        features = []

    return {"guild_id": gid, "features": features, **sections}
