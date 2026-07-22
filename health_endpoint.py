# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""
Health Endpoint Module - centralized health-monitoring HTTP endpoint.

Bot-agnostic: the entrypoint passes the bot name / service label / port to
``initialize_health_server``. Every service exposes ``GET /health`` on its 500xx port
(see portsRules.md); HealthCheck polls it and classifies healthy / degraded / down from the
reported ``status`` (liveness is not correctness; the contract lives in
``.docs/HealthCheck/HEALTH_ENDPOINT_CONTRACT.md``).

Never leak internals here - the endpoint is public. No pids, interpreter/library versions,
platform strings, account ids, hostnames, or exception text; counts (guilds, cogs,
commands) and latencies only. Bots with extra SAFE metrics (e.g. TheHost's premium-guild
count) pass an ``extra_fields`` callable instead of forking this file.

Status semantics (per the contract):
  - Discord gateway disconnected  -> ``degraded`` (HTTP 200, amber card; the process is
    alive and usually reconnecting).
  - Database down (or its probe fails) -> ``unhealthy`` (HTTP 503, red card; the bot
    cannot do real work without its data).
  - No db_manager wired at all -> ``degraded`` (a wiring gap, not a hard-down).
"""

import http.server
import json
import logging
import math
import socketserver
import threading
import time

logger = logging.getLogger(__name__)

_health_server = None
_start_time = time.time()


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _safe_latency_ms(bot) -> float | None:
    """Gateway latency in ms, or None while it is NaN/inf (pre-ready or reconnecting)."""
    try:
        latency = bot.latency
    except Exception:
        return None
    if latency is None or math.isnan(latency) or math.isinf(latency):
        return None
    return round(latency * 1000, 2)


class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler for health check requests"""

    # Set by initialize_health_server().
    bot_instance = None
    db_manager = None
    bot_name = "Bot"
    service = "Discord bot"
    # Optional zero-arg callable returning a dict of additional SAFE fields to merge
    # into the payload (counts/latencies only - never secrets or identifiers).
    extra_fields = None

    def do_GET(self):
        if self.path != '/health':
            self.send_response(404)
            self.end_headers()
            return

        status = "healthy"
        checks = {}
        gateway_latency_ms = None
        response = {
            "timestamp": time.time(),
            "bot": self.bot_name,
            "service": self.service,
            "uptime": int(time.time() - _start_time),
        }

        bot = self.bot_instance
        if bot:
            try:
                connected = bot.is_ready()
                gateway_latency_ms = _safe_latency_ms(bot)
                response["discord_connected"] = connected
                response["latency_ms"] = gateway_latency_ms
                response["guilds"] = len(bot.guilds) if hasattr(bot, 'guilds') else 0
                if getattr(bot, "shard_count", None):
                    response["shard_count"] = bot.shard_count
                cogs = getattr(bot, "cogs", None)
                if cogs is not None:
                    response["cogs_loaded"] = len(cogs)
                try:
                    response["commands_registered"] = len(bot.tree.get_commands())
                except Exception:
                    pass
                checks["discord"] = {
                    "status": "healthy" if connected else "unhealthy",
                    "latency_ms": gateway_latency_ms,
                }
                if not connected:
                    status = "degraded"
            except Exception as e:
                logger.warning(f"Failed to get bot status: {e}")
                response["discord_connected"] = False
                checks["discord"] = {"status": "unhealthy"}
                status = "degraded"
        else:
            response["discord_connected"] = False
            checks["discord"] = {"status": "unhealthy"}
            status = "degraded"

        # The db manager may be passed explicitly or hang off the bot. Prefer the richer
        # is_healthy probe and fall back to is_connected. A dead database is a hard-down
        # (unhealthy -> 503) per the health contract; a missing manager is only degraded.
        db_manager = self.db_manager or getattr(self.bot_instance, "db_manager", None)
        if db_manager:
            try:
                healthy_attr = getattr(db_manager, "is_healthy", None)
                connected_attr = getattr(db_manager, "is_connected", None)
                if healthy_attr is not None:
                    db_ok = bool(healthy_attr() if callable(healthy_attr) else healthy_attr)
                elif connected_attr is not None:
                    db_ok = bool(connected_attr() if callable(connected_attr) else connected_attr)
                else:
                    db_ok = False
                response["database_connected"] = db_ok
                checks["database"] = {"status": "healthy" if db_ok else "unhealthy"}
                if not db_ok:
                    status = "unhealthy"
            except Exception as e:
                logger.warning(f"Failed to get database status: {e}")
                response["database_connected"] = False
                checks["database"] = {"status": "unhealthy"}
                status = "unhealthy"
        else:
            response["database_connected"] = False
            checks["database"] = {"status": "unhealthy"}
            status = "degraded"

        if self.extra_fields is not None:
            try:
                extra = self.extra_fields()
                if isinstance(extra, dict):
                    response.update(extra)
            except Exception as e:
                logger.warning(f"Failed to collect extra health fields: {e}")

        if gateway_latency_ms is not None:
            response["gateway_latency_ms"] = gateway_latency_ms
        response["checks"] = checks
        response["status"] = status
        # Degraded must return 200 so the monitor parses the body and renders
        # amber; non-200 is read as DOWN. Only hard-down returns 503.
        code = 503 if status == "unhealthy" else 200

        try:
            payload = json.dumps(response).encode()
        except Exception as e:
            logger.error(f"Failed to serialize health payload: {e}")
            self.send_response(500)
            self.end_headers()
            return

        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        """Disable default logging to reduce noise"""
        pass


def stop_health_server():
    """Shut down the health check server if running."""
    global _health_server
    if _health_server:
        _health_server.shutdown()
        _health_server.server_close()
        _health_server = None
        logger.info("Health check server stopped")


def initialize_health_server(port, bot=None, db_manager=None, bot_name="Bot",
                             service="Discord bot", extra_fields=None):
    """
    Initialize the health server in a background thread.

    Args:
        port (int): Port to listen on (the bot's 500xx health port).
        bot: Discord bot instance (optional).
        db_manager: Database manager instance (optional).
        bot_name (str): Human-readable bot name for the /health payload.
        service (str): Short service description for the /health payload.
        extra_fields: Optional zero-arg callable returning a dict of additional
            SAFE fields (counts/latencies only) merged into the payload.

    Returns:
        threading.Thread: The health server thread (or None on bind failure).
    """
    global _health_server

    HealthCheckHandler.bot_instance = bot
    HealthCheckHandler.db_manager = db_manager
    HealthCheckHandler.bot_name = bot_name
    HealthCheckHandler.service = service
    HealthCheckHandler.extra_fields = extra_fields

    try:
        _health_server = ReusableTCPServer(("0.0.0.0", port), HealthCheckHandler)
    except Exception as e:
        logger.error(f"Failed to start health server on port {port}: {e}")
        return None

    health_thread = threading.Thread(target=_health_server.serve_forever, daemon=True, name="HealthCheckServer")
    health_thread.start()
    logger.info(f"Health check server running on port {port}")
    return health_thread
