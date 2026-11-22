# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""
Status Push - reports one process's status to an Uptime Kuma push monitor.

Replaces polling by the HealthCheck service (owner ruling 2026-08-20, built 2026-11-09 with
TheCodex first). Kuma hands out one URL per push monitor. The process calls it on a timer
with ``status=up|down``, a short ``msg`` and a ``ping`` in milliseconds. When no call arrives
inside the monitor's heartbeat interval, Kuma marks the monitor down by itself, so a crashed
process, a dead container or a wedged event loop all show as down without any code running.

**Every process pushes its OWN monitor** (owner ruling 2026-11-09): the bot for the bot, the
dashboard for the dashboard. A bot reporting for its dashboard would paint a healthy dashboard
red whenever the bot itself died.

**Kuma has only up and down.** The fleet health contract has a third state, ``degraded``. It is
mapped here as: degraded pushes ``up`` (with its message) while it is young, and ``down`` once it
has lasted longer than ``degraded_grace`` seconds. A Discord gateway reconnect is normal for a
few seconds; a bot that has been reconnecting for minutes is down as far as members can tell.
``unhealthy`` pushes ``down`` at once, and so does a status check that raises.

**INERT unless a push URL is configured.** ``start_status_push`` with an empty URL logs one line
and returns ``None``, so vendoring this file changes nothing until a bot sets its env var.

**The message lands on a PUBLIC status page.** Callers pass plain status words only - never
exception text, hostnames or connection strings, the same rule as ``/health``. The push URL
carries the monitor's token, so it is never logged either.

Stdlib only, so the bot and the dashboard process can both import it with no extra dependency.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Awaitable, Callable, NamedTuple, Optional, Union

logger = logging.getLogger(__name__)

HEALTHY = "healthy"
DEGRADED = "degraded"
UNHEALTHY = "unhealthy"

# Push every 30 s. Set the Kuma monitor's heartbeat interval to 60 s, so a single late or lost
# push never turns the monitor red on its own.
PUSH_INTERVAL_SECONDS = 30
# How long a degraded state may last before it is reported as down.
DEGRADED_GRACE_SECONDS = 120
# One push may take this long before it counts as failed.
PUSH_TIMEOUT_SECONDS = 10
# Kuma stores the message per heartbeat; keep it short and bounded.
MAX_MESSAGE_LENGTH = 200

# Shown when the status check itself raised. Plain words, nothing from the exception.
CHECK_FAILED_MESSAGE = "Status check failed"


class Verdict(NamedTuple):
    """What one status check found: a contract status, a plain message, and a latency."""

    status: str
    message: str
    ping_ms: Optional[float] = None


Collector = Callable[[], Union[Verdict, tuple, Awaitable[Union[Verdict, tuple]]]]


def is_push_url(push_url: Optional[str]) -> bool:
    """Whether ``push_url`` is an absolute http(s) URL with a host."""
    try:
        parts = urllib.parse.urlsplit((push_url or "").strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def build_push_url(push_url: str, *, up: bool, message: str, ping_ms: Optional[float]) -> str:
    """The push URL with this beat's status, message and ping.

    Kuma shows its push URL with a sample query (``?status=up&msg=OK&ping=``), and that whole
    URL is what gets pasted into the env file, so any existing query is dropped and rebuilt.
    """
    parts = urllib.parse.urlsplit(push_url.strip())
    query = {
        "status": "up" if up else "down",
        "msg": (message or "")[:MAX_MESSAGE_LENGTH],
    }
    if ping_ms is not None:
        query["ping"] = str(max(0, round(ping_ms)))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), "")
    )


class PushRejected(Exception):
    """Kuma answered, but refused the push (wrong token, monitor paused or deleted)."""


def _http_get(url: str) -> None:
    """Send one push. Raises when Kuma is unreachable or refuses it."""
    request = urllib.request.Request(url, headers={"User-Agent": "EmpireOfShadows-StatusPush/1"})
    try:
        with urllib.request.urlopen(request, timeout=PUSH_TIMEOUT_SECONDS) as response:
            body = response.read(2048)
    except urllib.error.HTTPError as e:
        # Kuma answers an unknown or paused monitor with 404 and a JSON reason.
        raise PushRejected(f"HTTP {e.code}{_kuma_reason(e.read(2048))}") from None
    try:
        answer = json.loads(body or b"{}")
    except ValueError:
        return  # 200 with a body that is not JSON: treat the push as delivered.
    if isinstance(answer, dict) and answer.get("ok") is False:
        raise PushRejected(f"refused{_kuma_reason(body)}")


def _kuma_reason(body: bytes) -> str:
    """Kuma's own short reason (e.g. "Monitor not found or not active."), if it sent one."""
    try:
        reason = json.loads(body or b"{}").get("msg")
    except (ValueError, AttributeError):
        return ""
    return f": {str(reason)[:120]}" if reason else ""


class StatusPusher:
    """Runs one process's status check on a timer and pushes the result to Kuma."""

    def __init__(
        self,
        push_url: str,
        collect: Collector,
        *,
        label: str,
        interval: float = PUSH_INTERVAL_SECONDS,
        degraded_grace: float = DEGRADED_GRACE_SECONDS,
        send: Optional[Callable[[str], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._push_url = push_url.strip()
        self._collect = collect
        self.label = label
        self.interval = interval
        self.degraded_grace = degraded_grace
        # Resolved here, not as a default argument, so the module-level sender is looked up
        # when the pusher is built rather than frozen when this module was imported.
        self._send = send if send is not None else _http_get
        self._clock = clock
        self._degraded_since: Optional[float] = None
        self._failing = False

    def decide(self, verdict: Verdict) -> bool:
        """Map a contract status onto Kuma's up/down, honouring the degraded grace."""
        if verdict.status == HEALTHY:
            self._degraded_since = None
            return True
        if verdict.status == DEGRADED:
            now = self._clock()
            if self._degraded_since is None:
                self._degraded_since = now
            return now - self._degraded_since <= self.degraded_grace
        # unhealthy, or a status this module does not know: down. A later degraded spell
        # starts its own grace.
        self._degraded_since = None
        return False

    async def _verdict(self) -> Verdict:
        try:
            result = self._collect()
            if inspect.isawaitable(result):
                result = await result
            return Verdict(*result)
        except Exception:
            logger.warning("Status check for %s raised; reporting down", self.label, exc_info=True)
            return Verdict(UNHEALTHY, CHECK_FAILED_MESSAGE)

    async def push_once(self) -> bool:
        """Check, decide, push. Returns whether Kuma accepted the push. Never raises."""
        verdict = await self._verdict()
        up = self.decide(verdict)
        url = build_push_url(self._push_url, up=up, message=verdict.message, ping_ms=verdict.ping_ms)
        try:
            await asyncio.to_thread(self._send, url)
        except Exception as e:
            # Log the first failure of a streak only, and never the URL (it carries the token).
            if not self._failing:
                detail = str(e) if isinstance(e, PushRejected) else type(e).__name__
                logger.warning("Status push for %s failed (%s); retrying every %ss",
                               self.label, detail, self.interval)
            self._failing = True
            return False
        if self._failing:
            logger.info("Status push for %s is reaching Uptime Kuma again", self.label)
        self._failing = False
        return True

    async def run(self) -> None:
        logger.info("Status push for %s started (every %ss)", self.label, self.interval)
        while True:
            await self.push_once()
            await asyncio.sleep(self.interval)


def start_status_push(
    push_url: Optional[str],
    collect: Collector,
    *,
    label: str,
    interval: float = PUSH_INTERVAL_SECONDS,
    degraded_grace: float = DEGRADED_GRACE_SECONDS,
) -> Optional[asyncio.Task]:
    """Start pushing ``collect()``'s verdict to Kuma. Call from inside the running loop.

    ``collect`` is a zero-argument callable, sync or async, returning a :class:`Verdict` or a
    ``(status, message, ping_ms)`` tuple. Returns the background task, or ``None`` when no
    push URL is configured (the feature is off) or the URL is not an http(s) URL.
    """
    if not (push_url or "").strip():
        logger.info("Status push for %s is off: no push URL configured", label)
        return None
    if not is_push_url(push_url):
        logger.warning("Status push for %s is off: the push URL is not an http(s) URL", label)
        return None
    pusher = StatusPusher(push_url, collect, label=label, interval=interval,
                          degraded_grace=degraded_grace)
    return asyncio.create_task(pusher.run(), name=f"status_push:{label}")


async def stop_status_push(task: Optional[asyncio.Task]) -> None:
    """Cancel a task from :func:`start_status_push` and wait for it. ``None`` is a no-op.

    Deliberately pushes nothing on the way out: a redeploy that is back inside the heartbeat
    interval should not leave a red bar on the public page. Planned downtime belongs in a
    Kuma maintenance window.
    """
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("Status push task ended with an error", exc_info=True)
