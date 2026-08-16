# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""The inbound side: serve this bot's capabilities to the rest of the fleet.

Runs an aiohttp app on the bot's ``510NN`` IPC port, INSIDE the bot's event
loop. That placement is not a convenience, it is a correctness requirement:
capabilities reach into the bot's own domain layer, and much of that layer is
guarded by in-process ``asyncio.Lock``s over read-modify-write documents. Serve
the same capability from a second process (the dashboard, say) and those locks
guard nothing - two writers interleave and the invariant they protect is gone.
The bot process is the only place the bot's own concurrency guarantees hold.

The port is container-internal by design. Compose must use ``expose``, never
``ports``, so the listener is reachable across ``obsidian_grid`` and from
nowhere else. The public ``500NN`` health endpoint is a separate, deliberately
dumb, unauthenticated listener and stays that way - do not merge them.

Request handling, in order:

  1. shared secret, constant-time compared, plus an optional caller allowlist,
  2. capability lookup,
  3. body parse (bounded),
  4. idempotency replay, under a per-key lock,
  5. the handler,
  6. remember the answer.

Status codes carry the meaning the protocol depends on: 200 for any verdict the
capability reached, including a refusal; anything else means no verdict.
"""

from __future__ import annotations

import hmac
import json
from typing import Any, Optional

from aiohttp import web

from storage.log import get_logger

from . import config
from .idempotency import (
    IdempotencyStore,
    MemoryIdempotencyStore,
    SingleFlight,
)
from .protocol import (
    HEADER_IDEMPOTENCY,
    HEADER_KEY,
    HEADER_SERVICE,
    MAX_BODY_BYTES,
    ROUTE_PREFIX,
    CapabilityContext,
    IpcResult,
    Reason,
)
from .registry import load_registry

logger = get_logger("IPC")

# Typed app keys (aiohttp 3.9+, which discord.py 2.7 already requires).
APP_BOT: web.AppKey[Any] = web.AppKey("ipc_bot")
APP_DB: web.AppKey[Any] = web.AppKey("ipc_db")
APP_IDEMPOTENCY: web.AppKey[IdempotencyStore] = web.AppKey("ipc_idempotency")

_runner: Optional[web.AppRunner] = None
_single_flight = SingleFlight()


def _error(status: int, code: str, reason: str) -> web.Response:
    """A non-verdict. The caller reads any non-200 as "we do not know"."""
    return web.json_response({"ok": False, "code": code, "reason": reason}, status=status)


def _authorize(request: web.Request) -> Optional[web.Response]:
    """Check the shared secret and the optional caller allowlist."""
    expected = config.shared_secret()
    if not expected:
        # Refusing here rather than serving open is deliberate: an unset secret
        # is a deployment mistake, and the failure must be visible, not silent.
        logger.error("IPC request refused - no SHARED_SECRET configured")
        return _error(503, Reason.NOT_READY, "This service is not accepting internal calls.")

    presented = request.headers.get(HEADER_KEY, "")
    if not hmac.compare_digest(presented, expected):
        logger.warning(
            f"IPC request refused - bad key from "
            f"{request.headers.get(HEADER_SERVICE, '?')} at {request.remote}"
        )
        return _error(401, Reason.UNAUTHORIZED, "Not authorized.")

    caller = (request.headers.get(HEADER_SERVICE) or "").strip()
    if not caller:
        return _error(400, Reason.BAD_REQUEST, f"Missing {HEADER_SERVICE}.")

    allowed = config.allowed_callers()
    if allowed is not None and caller not in allowed:
        logger.warning(f"IPC request refused - caller {caller!r} is not on the allowlist")
        return _error(401, Reason.UNAUTHORIZED, "Not authorized.")

    return None


async def _read_params(request: web.Request) -> tuple[Optional[dict], Optional[web.Response]]:
    """Parse ``{"params": {...}}``, bounded. Returns (params, error_response)."""
    raw = await request.content.read(MAX_BODY_BYTES + 1)
    if len(raw) > MAX_BODY_BYTES:
        return None, _error(400, Reason.BAD_REQUEST, "Request body is too large.")
    if not raw:
        return {}, None
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, _error(400, Reason.BAD_REQUEST, "Request body is not valid JSON.")
    if not isinstance(body, dict):
        return None, _error(400, Reason.BAD_REQUEST, "Request body must be a JSON object.")
    params = body.get("params", {})
    if not isinstance(params, dict):
        return None, _error(400, Reason.BAD_REQUEST, "'params' must be a JSON object.")
    return params, None


async def _run_capability(
    app: web.Application,
    handler,
    ctx: CapabilityContext,
    params: dict,
) -> web.Response:
    """Invoke one capability and turn its result into a response."""
    try:
        result = await handler.handle(ctx, params)
    except Exception:
        # An exception leaves the outcome genuinely unknown: the handler may
        # have completed half its work. Say so with a 500 rather than dressing
        # it up as a clean refusal, and make it loud on this side, because this
        # is the one failure mode nobody downstream can reason about.
        logger.exception(
            f"IPC capability {ctx.capability!r} raised for caller {ctx.caller!r} "
            f"(idempotency_key={ctx.idempotency_key!r})"
        )
        return _error(500, Reason.HANDLER_ERROR, "The other service failed to complete this.")

    if not isinstance(result, IpcResult):
        logger.error(
            f"IPC capability {ctx.capability!r} returned {type(result).__name__}, "
            f"not an IpcResult"
        )
        return _error(500, Reason.HANDLER_ERROR, "The other service gave an invalid answer.")

    payload = result.to_payload()
    if ctx.idempotency_key:
        await app[APP_IDEMPOTENCY].put(ctx.idempotency_key, payload)
    return web.json_response(payload, status=200)


async def _handle_call(request: web.Request) -> web.Response:
    denied = _authorize(request)
    if denied is not None:
        return denied

    capability_key = request.match_info.get("capability", "")
    handler = load_registry().get(capability_key)
    if handler is None:
        logger.warning(f"IPC request for unknown capability {capability_key!r}")
        return _error(404, Reason.UNKNOWN_CAPABILITY, "That capability does not exist here.")

    params, denied = await _read_params(request)
    if denied is not None:
        return denied

    app = request.app
    ctx = CapabilityContext(
        bot=app[APP_BOT],
        db=app[APP_DB],
        caller=(request.headers.get(HEADER_SERVICE) or "").strip(),
        capability=capability_key,
        idempotency_key=(request.headers.get(HEADER_IDEMPOTENCY) or "").strip() or None,
    )

    if not ctx.idempotency_key:
        return await _run_capability(app, handler, ctx, params)

    # Serialize on the key so a retry waits for its original instead of racing
    # it, then replay the original verdict if there is one.
    store = app[APP_IDEMPOTENCY]
    lock = _single_flight.lock_for(ctx.idempotency_key)
    try:
        async with lock:
            replayed = await store.get(ctx.idempotency_key)
            if replayed is not None:
                logger.info(
                    f"IPC replaying stored answer for {capability_key!r} "
                    f"(idempotency_key={ctx.idempotency_key!r})"
                )
                return web.json_response(replayed, status=200)
            return await _run_capability(app, handler, ctx, params)
    finally:
        _single_flight.release(ctx.idempotency_key)


async def _handle_catalogue(request: web.Request) -> web.Response:
    """Discovery: what this bot offers, so a caller's admin UI can list it."""
    denied = _authorize(request)
    if denied is not None:
        return denied
    return web.json_response({
        "service": config.service_name(),
        "capabilities": load_registry().catalogue(),
    })


def build_app(bot: Any = None, db_manager: Any = None) -> web.Application:
    """Assemble the aiohttp app. Split out so tests can drive it directly."""
    app = web.Application(client_max_size=MAX_BODY_BYTES)
    app[APP_BOT] = bot
    app[APP_DB] = db_manager
    app[APP_IDEMPOTENCY] = (
        config.build_idempotency_store(db_manager) or MemoryIdempotencyStore()
    )
    app.router.add_post(f"{ROUTE_PREFIX}/call/{{capability}}", _handle_call)
    app.router.add_get(f"{ROUTE_PREFIX}/capabilities", _handle_catalogue)
    return app


async def start_ipc_server(bot: Any = None, db_manager: Any = None) -> Optional[web.AppRunner]:
    """Start the IPC listener, if this bot has anything to serve.

    Returns None (having logged why) rather than raising: a bot that cannot
    serve IPC must still start and run its actual job. A bot with no
    capabilities simply never listens, which is the normal state for a pure
    consumer.
    """
    global _runner
    if _runner is not None:
        logger.warning("IPC server is already running")
        return _runner

    registry = load_registry()
    if len(registry) == 0:
        logger.info("IPC server not started - this bot provides no capabilities")
        return None

    port = config.bind_port()
    if not port:
        logger.error("IPC server not started - BIND_PORT is not set in the bindings seam")
        return None
    if not config.shared_secret():
        logger.error("IPC server not started - SHARED_SECRET is not set")
        return None

    app = build_app(bot=bot, db_manager=db_manager)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        site = web.TCPSite(runner, config.bind_host(), port)
        await site.start()
    except Exception as exc:
        logger.error(f"IPC server failed to bind {config.bind_host()}:{port}: {exc}")
        try:
            await runner.cleanup()
        except Exception:
            pass
        return None

    _runner = runner
    logger.info(
        f"IPC server listening on {config.bind_host()}:{port} as "
        f"{config.service_name()!r} - capabilities: {', '.join(registry.keys())}"
    )
    return runner


async def stop_ipc_server() -> None:
    """Stop the listener. Safe to call when it never started."""
    global _runner
    if _runner is None:
        return
    try:
        await _runner.cleanup()
        logger.info("IPC server stopped")
    except Exception as exc:
        logger.error(f"Error stopping IPC server: {exc}")
    finally:
        _runner = None


__all__ = ["build_app", "start_ipc_server", "stop_ipc_server"]
