"""Premium status and code redemption API."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dashboard import db
from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.services.premium import get_guild_limits, get_premium_subscription

logger = logging.getLogger(__name__)
router = APIRouter(tags=["premium"])


class RedeemRequest(BaseModel):
    code: str


@router.get("/guilds/{guild_id}/premium")
async def get_premium(guild_id: str, session: dict = Depends(get_current_user)):
    await require_panel_access(session, guild_id)
    gid = str(guild_id)

    sub = await get_premium_subscription(gid)
    limits = await get_guild_limits(gid)

    if sub is None:
        return {
            "guild_id": gid,
            "tier": "free",
            "is_premium": False,
            "is_lifetime": False,
            "expires_at": None,
            "max_rules": limits["max_rules"],
            "daily_limit": limits["daily_limit"],
        }

    expires_at = sub.get("expires_at")
    if isinstance(expires_at, datetime):
        expires_at = expires_at.isoformat()

    return {
        "guild_id": gid,
        "tier": "lifetime" if sub.get("is_lifetime") else "premium",
        "is_premium": True,
        "is_lifetime": bool(sub.get("is_lifetime")),
        "expires_at": expires_at,
        "max_rules": limits["max_rules"],
        "daily_limit": limits["daily_limit"],
    }


@router.post("/guilds/{guild_id}/premium/redeem")
async def redeem_code(
    guild_id: str,
    body: RedeemRequest,
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)

    gid = str(guild_id)
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Code is required.")

    now = datetime.now(timezone.utc)
    code_doc = await db.premium_codes().find_one(
        {"code": code, "is_redeemed": False}
    )
    if code_doc is None:
        raise HTTPException(status_code=400, detail="Invalid or already redeemed code.")

    duration_days = code_doc.get("duration_days", 0)
    is_lifetime = bool(code_doc.get("is_lifetime", False))

    existing = await get_premium_subscription(gid)
    if existing and existing.get("is_lifetime"):
        raise HTTPException(status_code=400, detail="Guild already has a lifetime subscription.")

    expires_at = None if is_lifetime else (
        now + __import__("datetime").timedelta(days=duration_days)
    )

    sub_doc = {
        "guild_id": gid,
        "code": code,
        "is_active": True,
        "is_lifetime": is_lifetime,
        "expires_at": expires_at,
        "redeemed_at": now,
        "redeemed_by": str(session["user_data"]["id"]),
    }
    await db.premium_subscriptions().insert_one(sub_doc)

    await db.premium_codes().update_one(
        {"code": code},
        {"$set": {"is_redeemed": True, "redeemed_at": now, "redeemed_guild_id": gid}},
    )

    if existing:
        await db.premium_subscriptions().update_many(
            {"guild_id": gid, "is_active": True, "_id": {"$ne": sub_doc.get("_id")}},
            {"$set": {"is_active": False}},
        )

    return {
        "ok": True,
        "tier": "lifetime" if is_lifetime else "premium",
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
