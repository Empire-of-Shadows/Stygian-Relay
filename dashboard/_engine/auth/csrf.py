# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""CSRF token management bound to the session document.

A per-session CSRF token is lazily created and stored on the SharedSessions
document. State-changing requests (POST/PUT/PATCH/DELETE) must echo it back
via the `X-CSRF-Token` header (or `csrf_token` form field for HTML form posts).

The token is unguessable and bound to the session, so it stops cross-site
request forgery even if an attacker can trick the browser into sending the
session cookie.
"""

import logging
import secrets

from fastapi import HTTPException, Request

from dashboard import db
from dashboard._engine.auth.signing import unsign_token
from dashboard.config import SESSION_COOKIE_NAME

logger = logging.getLogger(__name__)


def _raw_token(request: Request) -> str | None:
    signed = request.cookies.get(SESSION_COOKIE_NAME)
    if not signed:
        return None
    return unsign_token(signed)


async def get_or_create_csrf_token(session_token: str) -> str | None:
    """Return existing CSRF token for a session, lazily creating one if missing."""
    coll = db.shared_sessions()
    doc = await coll.find_one({"token": session_token}, {"csrf_token": 1})
    if doc and doc.get("csrf_token"):
        return doc["csrf_token"]
    if not doc:
        return None
    csrf = secrets.token_urlsafe(32)
    await coll.update_one({"token": session_token}, {"$set": {"csrf_token": csrf}})
    return csrf


async def _validate(session_token: str, csrf: str) -> bool:
    coll = db.shared_sessions()
    doc = await coll.find_one(
        {"token": session_token, "csrf_token": csrf},
        {"_id": 1},
    )
    return doc is not None


async def verify_csrf(request: Request) -> None:
    """FastAPI dependency: validate CSRF token on state-changing requests."""
    raw = _raw_token(request)
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")

    csrf = request.headers.get("X-CSRF-Token")
    if not csrf:
        try:
            form = await request.form()
            csrf = form.get("csrf_token")
        except Exception as e:  # malformed multipart / oversized body
            logger.debug("CSRF form-parse failed: %s", e)
            csrf = None

    if not csrf:
        raise HTTPException(status_code=403, detail="Missing CSRF token")

    if not await _validate(raw, csrf):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


async def csrf_endpoint(request: Request) -> dict:
    """Return the CSRF token for the authenticated session (401 if not logged in)."""
    raw = _raw_token(request)
    if not raw:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = await get_or_create_csrf_token(raw)
    if not token:
        raise HTTPException(status_code=401, detail="Session not found")
    return {"csrf_token": token}


_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_EXEMPT_PATH_PREFIXES = ("/auth/discord", "/auth/logout")


async def csrf_middleware(request: Request, call_next):
    """Reject unsafe-method requests that carry a session cookie but no valid CSRF."""
    if request.method not in _UNSAFE_METHODS:
        return await call_next(request)

    if any(request.url.path.startswith(p) for p in _EXEMPT_PATH_PREFIXES):
        return await call_next(request)

    raw = _raw_token(request)
    if not raw:
        return await call_next(request)

    csrf = request.headers.get("X-CSRF-Token")
    if not csrf:
        try:
            form = await request.form()
            csrf = form.get("csrf_token")
        except Exception as e:  # malformed multipart / oversized body
            logger.debug("CSRF form-parse failed: %s", e)
            csrf = None

    if not csrf or not await _validate(raw, csrf):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=403, content={"detail": "Invalid or missing CSRF token"})

    return await call_next(request)
