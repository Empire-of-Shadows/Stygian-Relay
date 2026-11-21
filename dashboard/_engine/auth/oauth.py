# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""Discord OAuth2 routes with cross-subdomain SSO support.

The redirect allowlist and the default fallback redirect are seam-configured
(``config.OAUTH_REDIRECT_ALLOWLIST`` regex + ``config.OAUTH_DEFAULT_REDIRECT``),
so each bot keeps its own policy without diverging this engine file.
"""

import logging
import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from dashboard._engine.activity import record_actor
from dashboard._engine.auth.session import (
    consume_oauth_state,
    create_session,
    delete_session,
    store_oauth_state,
)
from dashboard._engine.auth.signing import sign_token, unsign_token
from dashboard.config import (
    COOKIE_DOMAIN,
    DASHBOARD_CLIENT_ID,
    DASHBOARD_CLIENT_SECRET,
    DISCORD_API_BASE,
    IS_PRODUCTION,
    OAUTH_DEFAULT_REDIRECT,
    OAUTH_REDIRECT_ALLOWLIST,
    REDIRECT_URI,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_DAYS,
)

logger = logging.getLogger("dashboard.auth.oauth")

router = APIRouter(tags=["auth"])

_SCOPES = "identify guilds"
_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
_TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"

# Seam-configured allowlist. MUST be anchored at both ends (^...$) so only exact
# hosts match; without the trailing anchor, re.match would accept any URL that
# merely *starts* with an allowed host (e.g. "https://eosofficial.club.evil.com/phish")
# - an open-redirect / phishing hole.
_ALLOWED_REDIRECT_PATTERN = re.compile(OAUTH_REDIRECT_ALLOWLIST)


def _validate_redirect(url: str | None) -> str:
    """Validate redirect_to is on an allowed host; else the seam default."""
    if url and _ALLOWED_REDIRECT_PATTERN.match(url):
        return url
    return OAUTH_DEFAULT_REDIRECT


# Login CSRF (security review 2026-11-20). The state used to live only in the
# database, so a callback link for a login an ATTACKER started (their own Discord
# account, last step not followed) worked in anyone's browser and signed the
# victim in as the attacker, on every dashboard at once through the shared
# cookie. The state is now also put in a short-lived cookie in the browser that
# starts the login, and the callback refuses unless the two match. A link from
# someone else carries their state, which this browser has no cookie for.
OAUTH_STATE_COOKIE = "eos_oauth_state"
_OAUTH_STATE_MAX_AGE = 600  # seconds; a login takes well under a minute


def _set_state_cookie(response, state: str) -> None:
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=sign_token(state),
        max_age=_OAUTH_STATE_MAX_AGE,
        httponly=True,
        # Lax still sends it on the top-level redirect back from Discord.
        samesite="lax",
        secure=IS_PRODUCTION,
        domain=COOKIE_DOMAIN,
        path="/auth",
    )


def _clear_state_cookie(response) -> None:
    response.delete_cookie(OAUTH_STATE_COOKIE, domain=COOKIE_DOMAIN, path="/auth")


def _state_matches_browser(request: Request, state: str) -> bool:
    signed = request.cookies.get(OAUTH_STATE_COOKIE)
    if not signed:
        return False
    mine = unsign_token(signed)
    return bool(mine) and secrets.compare_digest(mine, state)


@router.get("/discord")
async def discord_login(redirect_to: str | None = None):
    state = secrets.token_urlsafe(16)
    await store_oauth_state(state, _validate_redirect(redirect_to))
    params = {
        "client_id": DASHBOARD_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
    }
    response = RedirectResponse(f"{_AUTHORIZE_URL}?{urlencode(params)}")
    _set_state_cookie(response, state)
    return response


def _back_to_login() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=302)
    _clear_state_cookie(response)
    return response


@router.get("/discord/callback")
async def discord_callback(request: Request, code: str, state: str | None = None):
    if not state:
        return _back_to_login()
    if not _state_matches_browser(request, state):
        # Not the browser that started this login: someone else's link. Checked
        # BEFORE consuming, so a forged link cannot even burn the real state.
        logger.warning("OAuth callback refused: state not issued to this browser")
        return _back_to_login()
    redirect_url = await consume_oauth_state(state)
    if redirect_url is None:
        # Invalid, expired, or already-used state - reject (CSRF protection).
        return _back_to_login()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            token_resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": DASHBOARD_CLIENT_ID,
                    "client_secret": DASHBOARD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()
            access_token = tokens["access_token"]

            headers = {"Authorization": f"Bearer {access_token}"}
            user_resp = await client.get(f"{DISCORD_API_BASE}/users/@me", headers=headers)
            user_resp.raise_for_status()
            user_data = user_resp.json()

            guilds_resp = await client.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=headers)
            guilds_resp.raise_for_status()
            guilds = guilds_resp.json()
    except httpx.HTTPError as e:
        logger.warning("Discord OAuth exchange failed: %s", e)
        raise HTTPException(status_code=502, detail="Discord OAuth exchange failed")

    session_token = await create_session(
        user_data,
        guilds,
        access_token=access_token,
        refresh_token=tokens.get("refresh_token"),
        expires_in=tokens.get("expires_in"),
    )
    # The callback is the one place the person is known without a session lookup,
    # so name them here rather than logging the login as anonymous.
    record_actor(request, {"user_data": user_data})

    redirect = RedirectResponse(url=redirect_url, status_code=302)
    _clear_state_cookie(redirect)
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sign_token(session_token),
        max_age=SESSION_MAX_AGE_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=IS_PRODUCTION,
        domain=COOKIE_DOMAIN,
    )
    return redirect


@router.post("/logout")
async def logout(request: Request):
    """End the session. POST only, with the CSRF token (security review 2026-11-20):
    as a GET link any website could sign a visitor out of every dashboard at once.
    The csrf middleware checks the token; the page then goes to /login itself."""
    signed = request.cookies.get(SESSION_COOKIE_NAME)
    if signed:
        raw = unsign_token(signed)
        if raw:
            await delete_session(raw)
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE_NAME, domain=COOKIE_DOMAIN)
    return response
