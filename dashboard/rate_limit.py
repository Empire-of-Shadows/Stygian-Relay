"""Lightweight in-process per-IP rate limiting for public/auth endpoints.

Fixed-window counter, no external dependency. Sufficient for a single-worker
uvicorn deployment. If the dashboard is ever scaled to multiple workers or
hosts, swap the in-memory store for a shared one (Redis/Mongo).

Only a small set of unauthenticated, internet-facing routes are limited; the
authenticated API is already gated by session auth and the bot-token Discord
calls are token-bucketed elsewhere.
"""

import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

# Ordered (path-prefix, bucket, max_requests, window_seconds). First match wins,
# so more specific prefixes must come before their parents.
_LIMITS: list[tuple[str, str, int, int]] = [
    ("/auth/discord/callback", "oauth_callback", 10, 60),
    ("/auth/discord", "oauth_start", 20, 60),
    ("/api/me", "me", 100, 60),
]

# key -> (window_start_epoch, count)
_buckets: dict[str, tuple[float, int]] = {}
_last_sweep = 0.0
_SWEEP_INTERVAL = 300.0


def _client_ip(request: Request) -> str:
    # Behind a reverse proxy the real client is the first X-Forwarded-For hop.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _match_limit(path: str) -> tuple[str, int, int] | None:
    for prefix, bucket, max_requests, window in _LIMITS:
        if path.startswith(prefix):
            return bucket, max_requests, window
    return None


def _sweep(now: float) -> None:
    global _last_sweep
    if now - _last_sweep < _SWEEP_INTERVAL:
        return
    _last_sweep = now
    stale = [k for k, (start, _) in _buckets.items() if now - start > 3600]
    for k in stale:
        _buckets.pop(k, None)


def _consume(request: Request, bucket: str, max_requests: int, window: int):
    """Fixed-window per-IP accounting shared by the middleware and the dependency.
    Returns a Retry-After (seconds) if the limit is exceeded, else None."""
    now = time.time()
    _sweep(now)
    key = f"{_client_ip(request)}:{bucket}"
    start, count = _buckets.get(key, (now, 0))
    if now - start >= window:
        start, count = now, 0
    count += 1
    _buckets[key] = (start, count)
    if count > max_requests:
        return max(1, int(window - (now - start)))
    return None


def rate_limit_dependency(bucket: str, max_requests: int, window: int):
    """A FastAPI dependency applying the same per-IP fixed-window limit as the
    middleware, for routes the prefix matcher can't target -- e.g. the per-guild
    stats route, whose path has a dynamic ``{guild_id}`` segment. The security
    standard calls for auth AND stats routes to be rate-limited."""
    async def _dep(request: Request):
        retry_after = _consume(request, bucket, max_requests, window)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(retry_after)},
            )
    return _dep


async def rate_limit_middleware(request: Request, call_next):
    limit = _match_limit(request.url.path)
    if limit is None:
        return await call_next(request)

    bucket, max_requests, window = limit
    now = time.time()
    _sweep(now)

    key = f"{_client_ip(request)}:{bucket}"
    start, count = _buckets.get(key, (now, 0))

    if now - start >= window:
        # Window elapsed - reset.
        start, count = now, 0

    count += 1
    _buckets[key] = (start, count)

    if count > max_requests:
        retry_after = max(1, int(window - (now - start)))
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please slow down."},
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)
