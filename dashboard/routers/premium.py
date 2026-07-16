"""Premium status API (read-only; entitlement-backed).

Codes are retired: premium comes from Discord entitlements (real purchases) or the bot owner's
`/premium grant`. The dashboard only reports status.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.services.premium import get_guild_limits, get_premium_status

logger = logging.getLogger(__name__)
router = APIRouter(tags=["premium"])


@router.get("/guilds/{guild_id}/premium")
async def get_premium(guild_id: str, session: dict = Depends(get_current_user)):
    await require_panel_access(session, guild_id)
    gid = str(guild_id)

    status = await get_premium_status(gid)
    limits = await get_guild_limits(gid)

    expires_at = status.get("expires_at")
    if isinstance(expires_at, datetime):
        expires_at = expires_at.isoformat()

    return {
        "guild_id": gid,
        "tier": status["tier"],
        "tiers": status["tiers"],
        "is_premium": status["is_premium"],
        "expires_at": expires_at,
        "max_rules": limits["max_rules"],
        "daily_limit": limits["daily_limit"],
    }
