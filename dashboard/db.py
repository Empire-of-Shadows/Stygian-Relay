"""MongoDB clients for the Stygian-Relay dashboard.

Two independent connections:
- relay: discord_forwarding_bot database (relay bot data)
- shared: WebSessions.SharedSessions, shared with other dashboards for SSO
"""

from pymongo import AsyncMongoClient

from dashboard.config import MONGO_URI, SHARED_SESSIONS_URI

_relay_client: AsyncMongoClient | None = None
_shared_client: AsyncMongoClient | None = None


async def connect():
    global _relay_client, _shared_client
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI environment variable is required")
    if not SHARED_SESSIONS_URI:
        raise RuntimeError("SHARED_SESSIONS_URI environment variable is required")
    _relay_client = AsyncMongoClient(MONGO_URI)
    _shared_client = AsyncMongoClient(SHARED_SESSIONS_URI)
    await _relay_client.admin.command("ping")
    await _shared_client.admin.command("ping")


async def close():
    global _relay_client, _shared_client
    if _relay_client:
        await _relay_client.close()
        _relay_client = None
    if _shared_client:
        await _shared_client.close()
        _shared_client = None


def relay_client() -> AsyncMongoClient:
    if _relay_client is None:
        raise RuntimeError("Relay database not connected - call connect() first")
    return _relay_client


def shared_client() -> AsyncMongoClient:
    if _shared_client is None:
        raise RuntimeError("Shared sessions database not connected - call connect() first")
    return _shared_client


# ── Shared session collections (cross-bot SSO) ────────────────────────────

def shared_sessions():
    """WebSessions.SharedSessions - cross-subdomain OAuth session storage."""
    return shared_client()["WebSessions"]["SharedSessions"]


def oauth_states():
    """WebSessions.OAuthStates - short-lived OAuth state for CSRF protection."""
    return shared_client()["WebSessions"]["OAuthStates"]


# ── Relay collections (discord_forwarding_bot database) ───────────────────

def guild_settings():
    """discord_forwarding_bot.guild_settings - per-guild config + rules."""
    return relay_client()["discord_forwarding_bot"]["guild_settings"]


def message_logs():
    """discord_forwarding_bot.message_logs - forwarded message audit (TTL 90d)."""
    return relay_client()["discord_forwarding_bot"]["message_logs"]


def entitlements():
    """discord_forwarding_bot.entitlements - raw premium entitlement records (per id)."""
    return relay_client()["discord_forwarding_bot"]["entitlements"]


def premium_state():
    """discord_forwarding_bot.premium_state - derived per-scope premium status."""
    return relay_client()["discord_forwarding_bot"]["premium_state"]


def audit_logs():
    """discord_forwarding_bot.audit_logs - admin action audit trail (TTL 365d)."""
    return relay_client()["discord_forwarding_bot"]["audit_logs"]


def daily_counters():
    """discord_forwarding_bot.daily_counters - per-(guild, day) forwarded counts."""
    return relay_client()["discord_forwarding_bot"]["daily_counters"]


def bot_settings():
    """discord_forwarding_bot.bot_settings - global bot configuration."""
    return relay_client()["discord_forwarding_bot"]["bot_settings"]
