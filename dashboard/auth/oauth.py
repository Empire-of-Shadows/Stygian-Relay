"""Discord OAuth2 routes with cross-subdomain SSO support."""

import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from dashboard.auth.session import (
    consume_oauth_state,
    create_session,
    delete_session,
    store_oauth_state,
)
from dashboard.auth.signing import sign_token, unsign_token
from dashboard.config import (
    COOKIE_DOMAIN,
    DASHBOARD_CLIENT_ID,
    DASHBOARD_CLIENT_SECRET,
    DISCORD_API_BASE,
    IS_PRODUCTION,
    REDIRECT_URI,
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_DAYS,
)

router = APIRouter(tags=["auth"])

_SCOPES = "identify guilds"
_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
_TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"

_ALLOWED_REDIRECT_PATTERN = re.compile(
    r"^https?://(localhost(:\d+)?|127\.0\.0\.1(:\d+)?|([a-z0-9-]+\.)?eosofficial\.club)(/.*)?"
)


def _validate_redirect(url: str | None) -> str:
    if url and _ALLOWED_REDIRECT_PATTERN.match(url):
        return url
    return "/me"


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
    return RedirectResponse(f"{_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/discord/callback")
async def discord_callback(code: str, state: str | None = None):
    if not state:
        return RedirectResponse(url="/login", status_code=302)
    redirect_url = await consume_oauth_state(state)
    if redirect_url is None:
        return RedirectResponse(url="/login", status_code=302)

    async with httpx.AsyncClient() as client:
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

    session_token = await create_session(
        user_data,
        guilds,
        access_token=access_token,
        refresh_token=tokens.get("refresh_token"),
        expires_in=tokens.get("expires_in"),
    )

    redirect = RedirectResponse(url=redirect_url, status_code=302)
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


@router.get("/logout")
async def logout(request: Request):
    signed = request.cookies.get(SESSION_COOKIE_NAME)
    if signed:
        raw = unsign_token(signed)
        if raw:
            await delete_session(raw)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME, domain=COOKIE_DOMAIN)
    return response
