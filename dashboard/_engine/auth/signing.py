# VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
# Edit the master at EmpireSystems/dashboard_engine/ and run:
#     python EmpireSystems/tools/sync_dashboard_engine.py
# Drift is enforced by:
#     python EmpireSystems/tools/sync_dashboard_engine.py --check
"""Signed cookie helpers using itsdangerous.

The session cookie value is the opaque Mongo lookup token wrapped in an
itsdangerous URLSafeTimedSerializer signature. The server verifies the
signature and TTL before touching Mongo - tampered or expired cookies are
rejected cheaply.

DASHBOARD_SECRET_KEY must be identical across every EoS dashboard so a cookie
set by one service validates on all the others.
"""

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from dashboard.config import SECRET_KEY, SESSION_MAX_AGE_DAYS

_SALT = "eos-session"

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt=_SALT)


def sign_token(raw_token: str) -> str:
    """Sign an opaque session token for safe transport in a cookie."""
    return _serializer.dumps(raw_token)


def unsign_token(signed: str) -> str | None:
    """Verify signature + TTL. Return raw token or None if invalid/expired."""
    try:
        return _serializer.loads(signed, max_age=SESSION_MAX_AGE_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None
