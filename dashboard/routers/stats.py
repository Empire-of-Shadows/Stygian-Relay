"""Per-guild forwarding statistics API."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from dashboard import db
from dashboard.auth.dependencies import get_current_user, require_panel_access
from dashboard.services.premium import get_guild_limits

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stats"])


@router.get("/guilds/{guild_id}/stats")
async def guild_stats(
    guild_id: str,
    days: int = Query(default=30, ge=1, le=90),
    session: dict = Depends(get_current_user),
):
    await require_panel_access(session, guild_id)

    gid = str(guild_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    limits = await get_guild_limits(gid)

    daily_cursor = db.daily_counters().find(
        {"guild_id": gid, "date": {"$gte": cutoff.strftime("%Y-%m-%d")}},
        {"_id": 0, "date": 1, "forwarded": 1, "blocked": 1},
        sort=[("date", 1)],
    )
    daily_docs = await daily_cursor.to_list(length=days + 5)

    total_forwarded = sum(d.get("forwarded", 0) for d in daily_docs)
    total_blocked = sum(d.get("blocked", 0) for d in daily_docs)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_doc = next((d for d in daily_docs if d.get("date") == today_str), None)
    today_forwarded = today_doc.get("forwarded", 0) if today_doc else 0

    per_rule_pipeline = [
        {
            "$match": {
                "guild_id": gid,
                "forwarded_at": {"$gte": cutoff},
            }
        },
        {
            "$group": {
                "_id": "$rule_id",
                "forwarded": {"$sum": 1},
            }
        },
        {"$sort": {"forwarded": -1}},
        {"$limit": 25},
    ]
    rule_cursor = db.message_logs().aggregate(per_rule_pipeline)
    per_rule = [
        {"rule_id": doc["_id"], "forwarded": doc["forwarded"]}
        async for doc in rule_cursor
    ]

    return {
        "guild_id": gid,
        "period_days": days,
        "total_forwarded": total_forwarded,
        "total_blocked": total_blocked,
        "today_forwarded": today_forwarded,
        "daily_limit": limits["daily_limit"],
        "is_premium": limits["is_premium"],
        "daily": [
            {"date": d["date"], "forwarded": d.get("forwarded", 0), "blocked": d.get("blocked", 0)}
            for d in daily_docs
        ],
        "per_rule": per_rule,
    }
