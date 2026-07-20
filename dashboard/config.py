"""Stygian-Relay dashboard configuration.

Loaded at import time - missing required vars raise RuntimeError immediately
so the process fails fast rather than blowing up mid-request.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_env_dir = Path(__file__).parent.parent / "docker"
if (_env_dir / ".env").exists():
    load_dotenv(_env_dir / ".env")
else:
    load_dotenv()
# Dev override: docker/.env.local (gitignored) wins when present.
load_dotenv(_env_dir / ".env.local", override=True)

# ── Discord OAuth (shared GateKeeper credentials for cross-subdomain SSO) ──

GATEKEEPER_CLIENT_ID = os.getenv("GATEKEEPER_CLIENT_ID", "")
GATEKEEPER_CLIENT_SECRET = os.getenv("GATEKEEPER_CLIENT_SECRET", "")

# Aliases the oauth.py router uses (same names as TheHost for portability).
DASHBOARD_CLIENT_ID = GATEKEEPER_CLIENT_ID
DASHBOARD_CLIENT_SECRET = GATEKEEPER_CLIENT_SECRET

BOT_TOKEN = os.getenv("DISCORD_TOKEN", "") or os.getenv("BOT_TOKEN", "")
DISCORD_API_BASE = "https://discord.com/api/v10"

REDIRECT_URI = os.getenv("GATEKEEPER_REDIRECT_URI") or os.getenv(
    "REDIRECT_URI", "https://relay.eosofficial.club/auth/discord/callback"
)

# ── Database ────────────────────────────────────────────────────────────────

MONGO_URI = os.getenv("MONGO_URI", "")
SHARED_SESSIONS_URI = os.getenv("SHARED_SESSIONS_URI", "")

# ── Session ─────────────────────────────────────────────────────────────────

# Must match the key used by TheHost / TheCodex / EcomBackend for SSO to work.
SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "") or os.getenv("SECRET_KEY", "")
SESSION_COOKIE_NAME = "eos_session"
SESSION_MAX_AGE_DAYS = 30

# Production: set to ".eosofficial.club" so one cookie covers every subdomain.
COOKIE_DOMAIN: str | None = os.getenv("COOKIE_DOMAIN") or None

# ── Server ──────────────────────────────────────────────────────────────────

# Production mode drives the Secure flag on the shared session cookie. Accept either
# convention (ENVIRONMENT=production OR IS_PRODUCTION=1/true/yes) so codex and relay
# behave identically regardless of which spelling a deployment sets.
IS_PRODUCTION = (
    os.getenv("ENVIRONMENT", "").lower() == "production"
    or os.getenv("IS_PRODUCTION", "").lower() in ("1", "true", "yes")
)
HOST = os.getenv("DASHBOARD_HOST") or os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT") or os.getenv("PORT", "54013"))

CORS_ORIGINS: list[str] = [
    "http://localhost:5173",
    "https://relay.eosofficial.club",
]

# ── Discord permission flags ─────────────────────────────────────────────────

MANAGE_GUILD_PERMISSION = 0x20
ADMINISTRATOR_PERMISSION = 0x8


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_config() -> None:
    missing: list[str] = []
    if not GATEKEEPER_CLIENT_ID:
        missing.append("GATEKEEPER_CLIENT_ID")
    if not GATEKEEPER_CLIENT_SECRET:
        missing.append("GATEKEEPER_CLIENT_SECRET")
    if not MONGO_URI:
        missing.append("MONGO_URI")
    if not SHARED_SESSIONS_URI:
        missing.append("SHARED_SESSIONS_URI")
    if not SECRET_KEY:
        missing.append("DASHBOARD_SECRET_KEY")
    if missing:
        raise RuntimeError(
            f"Relay dashboard: missing required env vars: {', '.join(missing)}"
        )


_validate_config()
