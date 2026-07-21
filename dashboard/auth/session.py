"""Session CRUD for the shared SharedSessions collection (cross-bot SSO).

Schema (shared across Host/Codex/Ecom/ImperialReminder/TheDecree + main site):
    token            opaque random Mongo lookup id (token_urlsafe(48))
    user_id          Discord user id (string)
    user_data        Discord /users/@me payload
    guilds           Discord /users/@me/guilds payload (refreshed on staleness)
    access_token     OAuth access token (server-side only; never returned to client)
    refresh_token    OAuth refresh token (rotates on each refresh)
    token_expires_at when the access token expires (UTC datetime, may be None)
    guilds_fetched_at, created_at, last_accessed, expires_at  (UTC datetimes)
    csrf_token       per-session CSRF token (lazy-initialized)
    schema_version   2
"""

import asyncio
import logging
import secrets
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from dashboard import db
from dashboard.config import (
    DASHBOARD_CLIENT_ID,
    DASHBOARD_CLIENT_SECRET,
    DISCORD_API_BASE,
    SESSION_MAX_AGE_DAYS,
)

logger = logging.getLogger(__name__)

SESSION_SCHEMA_VERSION = 2

# How long a session's cached guild list is trusted before a transparent refresh.
GUILDS_REFRESH_TTL_SECONDS = 300

_TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"
_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Single-flight locks per session token so concurrent requests don't stampede
# Discord. Bounded LRU: a token seen once would otherwise leave a Lock in memory
# for the process lifetime. Evicting an *idle* lock is safe -- a lock only needs
# to exist for the brief refresh window; worst case after eviction is a rare
# duplicate refresh (the pre-lock behavior).
_MAX_REFRESH_LOCKS = 2048
_refresh_locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()


def _get_refresh_lock(token: str) -> asyncio.Lock:
    """Return this token's single-flight lock, creating it on first use and
    evicting the oldest idle locks once over the cap."""
    lock = _refresh_locks.get(token)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[token] = lock
    else:
        _refresh_locks.move_to_end(token)
    # Evict oldest-idle locks when over the cap. Never evict a held lock.
    while len(_refresh_locks) > _MAX_REFRESH_LOCKS:
        old_token, old_lock = next(iter(_refresh_locks.items()))
        if old_lock.locked():
            _refresh_locks.move_to_end(old_token)
            break
        _refresh_locks.pop(old_token, None)
    return lock


async def create_session(
    user_data: dict,
    guilds: list[dict],
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_in: int | None = None,
) -> str:
    token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    token_expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
    doc = {
        "token": token,
        "user_id": user_data["id"],
        "user_data": user_data,
        "guilds": guilds,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": token_expires_at,
        "guilds_fetched_at": now,
        "created_at": now,
        "last_accessed": now,
        "expires_at": now + timedelta(days=SESSION_MAX_AGE_DAYS),
        "schema_version": SESSION_SCHEMA_VERSION,
    }
    await db.shared_sessions().insert_one(doc)
    return token


async def get_session(token: str) -> dict[str, Any] | None:
    """Look up session, slide expiration, return doc or None."""
    doc = await db.shared_sessions().find_one({"token": token})
    if doc is None:
        return None
    now = datetime.now(timezone.utc)
    expires_at = doc.get("expires_at", datetime.min)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        await delete_session(token)
        return None
    new_expires = now + timedelta(days=SESSION_MAX_AGE_DAYS)
    await db.shared_sessions().update_one(
        {"token": token},
        {"$set": {"last_accessed": now, "expires_at": new_expires}},
    )
    doc["last_accessed"] = now
    doc["expires_at"] = new_expires
    return doc


async def delete_session(token: str):
    await db.shared_sessions().delete_one({"token": token})
    _refresh_locks.pop(token, None)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _is_stale(fetched_at: datetime | None, ttl: int = GUILDS_REFRESH_TTL_SECONDS) -> bool:
    fetched_at = _as_utc(fetched_at)
    if fetched_at is None:
        return True
    return (datetime.now(timezone.utc) - fetched_at).total_seconds() >= ttl


async def _refresh_access_token(refresh_token: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": DASHBOARD_CLIENT_ID,
                    "client_secret": DASHBOARD_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as e:
        logger.warning("OAuth token refresh error: %s", e)
        return None
    if resp.status_code != 200:
        logger.info("OAuth token refresh failed: %s", resp.status_code)
        return None
    return resp.json()


async def _backoff(token: str, session: dict, updates: dict | None = None) -> dict:
    set_doc = dict(updates or {})
    set_doc["guilds_fetched_at"] = datetime.now(timezone.utc) - timedelta(
        seconds=GUILDS_REFRESH_TTL_SECONDS - 60
    )
    await db.shared_sessions().update_one({"token": token}, {"$set": set_doc})
    session.update(set_doc)
    return session


async def refresh_guilds_if_stale(session: dict) -> dict:
    """Best-effort refresh of the session's cached Discord guild list."""
    token = session.get("token")
    if not token or not session.get("access_token"):
        return session
    if not _is_stale(session.get("guilds_fetched_at")):
        return session

    async with _get_refresh_lock(token):
        latest = await db.shared_sessions().find_one({"token": token})
        if latest is None:
            return session
        if not _is_stale(latest.get("guilds_fetched_at")):
            session["guilds"] = latest.get("guilds", session.get("guilds"))
            session["guilds_fetched_at"] = latest.get("guilds_fetched_at")
            return session

        access_token = latest.get("access_token")
        refresh_token = latest.get("refresh_token")
        token_expires_at = _as_utc(latest.get("token_expires_at"))
        updates: dict = {}

        if access_token and token_expires_at and token_expires_at <= datetime.now(timezone.utc):
            if not refresh_token:
                return await _backoff(token, session)
            new_tokens = await _refresh_access_token(refresh_token)
            if not new_tokens:
                return await _backoff(token, session)
            access_token = new_tokens.get("access_token", access_token)
            updates["access_token"] = access_token
            if new_tokens.get("refresh_token"):
                updates["refresh_token"] = new_tokens["refresh_token"]
            if new_tokens.get("expires_in"):
                updates["token_expires_at"] = datetime.now(timezone.utc) + timedelta(
                    seconds=int(new_tokens["expires_in"])
                )

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{DISCORD_API_BASE}/users/@me/guilds",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as e:
            logger.warning("Guild refresh error: %s", e)
            return await _backoff(token, session, updates)

        if resp.status_code != 200:
            logger.info("Guild refresh failed: %s", resp.status_code)
            return await _backoff(token, session, updates)

        updates["guilds"] = resp.json()
        updates["guilds_fetched_at"] = datetime.now(timezone.utc)
        await db.shared_sessions().update_one({"token": token}, {"$set": updates})
        session.update(updates)
        return session


OAUTH_STATE_TTL_SECONDS = 600


async def ensure_oauth_state_ttl_index() -> None:
    """Create TTL index on WebSessions.OAuthStates.created_at (10 min)."""
    await db.oauth_states().create_index(
        "created_at",
        expireAfterSeconds=OAUTH_STATE_TTL_SECONDS,
        name="oauth_state_ttl",
    )


async def store_oauth_state(state: str, redirect_url: str) -> None:
    await db.oauth_states().insert_one({
        "state": state,
        "redirect_url": redirect_url,
        "created_at": datetime.now(timezone.utc),
    })


async def consume_oauth_state(state: str) -> str | None:
    """Atomically retrieve + delete an OAuth state. Returns redirect_url or None."""
    doc = await db.oauth_states().find_one_and_delete({"state": state})
    return doc.get("redirect_url") if doc else None
