# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""The outbound side: every call this bot makes to a sibling service.

There is one client, it is a singleton, and it owns one ``aiohttp`` session for
the process. Nothing else in a bot should be constructing sessions or URLs to
reach another service - if a second place starts doing that, the "all the
cross-service code is in one directory" property is gone and it does not come
back.

Retry policy, which is the only interesting decision in this file:

  * A VERDICT is never retried. "Your bag is full" does not become "yes" on a
    second ask, and retrying a refusal just wastes the provider's time.
  * A NON-VERDICT is retried once, and ONLY when the call carries an
    idempotency key. Without that key a retry could do the work twice, which is
    strictly worse than reporting an unknown outcome.

So the caller's contract is simple: pass a stable idempotency key for anything
that changes state, and treat ``answered=False`` as "we do not know" rather
than as "no".
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

import aiohttp

from storage.log import get_logger

from . import config
from .protocol import (
    HEADER_IDEMPOTENCY,
    HEADER_KEY,
    HEADER_SERVICE,
    ROUTE_PREFIX,
    IpcResult,
    Reason,
    unanswered,
)

logger = get_logger("IPC")

# Statuses where the provider definitively did NOT do the work. Treating these
# as answers lets a caller compensate with confidence instead of guessing.
_DEFINITIVE_REFUSALS = {400, 401, 404}

_RETRY_BACKOFF_SECONDS = 0.25


class IpcClient:
    """Calls capabilities on other services."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def call(
        self,
        service: str,
        capability: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> IpcResult:
        """Call ``capability`` on ``service``. Never raises.

        Every failure - unknown peer, unreachable host, timeout, bad response -
        comes back as an ``IpcResult``, because a caller that has already taken
        a member's currency cannot be handed an exception mid-transaction.
        """
        base = config.peer_url(service)
        if not base:
            logger.error(f"IPC call to unknown service {service!r} - not in the PEERS map")
            return unanswered(
                Reason.UNKNOWN_SERVICE,
                "That service is not configured on this bot.",
            )

        url = f"{base}{ROUTE_PREFIX}/call/{capability}"
        headers = {
            HEADER_SERVICE: config.service_name(),
            HEADER_KEY: config.shared_secret(),
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers[HEADER_IDEMPOTENCY] = str(idempotency_key)

        body = {"params": dict(params or {})}
        client_timeout = aiohttp.ClientTimeout(total=timeout or config.default_timeout())
        attempts = 2 if idempotency_key else 1

        last: IpcResult = unanswered(Reason.UNREACHABLE, "That service did not respond.")
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                logger.info(f"IPC retrying {service}/{capability} (key={idempotency_key!r})")
            last = await self._attempt(url, headers, body, client_timeout, service, capability)
            if last.answered:
                return last
        return last

    async def _attempt(
        self,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
        client_timeout: aiohttp.ClientTimeout,
        service: str,
        capability: str,
    ) -> IpcResult:
        try:
            session = await self._get_session()
            async with session.post(
                url, json=body, headers=headers, timeout=client_timeout
            ) as response:
                if response.status == 200:
                    try:
                        payload = await response.json()
                    except Exception:
                        logger.error(f"IPC {service}/{capability} returned unreadable JSON")
                        return unanswered(
                            Reason.BAD_RESPONSE,
                            "That service sent a response we could not read.",
                        )
                    return IpcResult.from_payload(payload)

                text = (await response.text())[:500]
                definitive = response.status in _DEFINITIVE_REFUSALS
                code, reason = _decode_error(text, response.status)
                logger.error(
                    f"IPC {service}/{capability} -> HTTP {response.status} "
                    f"({code}): {reason}"
                )
                return IpcResult(
                    ok=False, code=code, reason=reason, answered=definitive
                )
        except asyncio.TimeoutError:
            logger.error(f"IPC {service}/{capability} timed out")
            return unanswered(Reason.TIMEOUT, "That service did not respond in time.")
        except aiohttp.ClientError as exc:
            logger.error(f"IPC {service}/{capability} transport failure: {exc}")
            return unanswered(Reason.UNREACHABLE, "That service could not be reached.")

    async def capabilities(
        self, service: str, *, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch a peer's capability catalogue, or None if it cannot be read.

        Used by admin UIs that let someone pick a capability from a list rather
        than typing another service's internal keys by hand.
        """
        base = config.peer_url(service)
        if not base:
            return None
        headers = {
            HEADER_SERVICE: config.service_name(),
            HEADER_KEY: config.shared_secret(),
        }
        client_timeout = aiohttp.ClientTimeout(total=timeout or config.default_timeout())
        try:
            session = await self._get_session()
            async with session.get(
                f"{base}{ROUTE_PREFIX}/capabilities", headers=headers, timeout=client_timeout
            ) as response:
                if response.status != 200:
                    logger.warning(
                        f"IPC catalogue for {service!r} -> HTTP {response.status}"
                    )
                    return None
                return await response.json()
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            logger.warning(f"IPC catalogue for {service!r} unavailable: {exc}")
            return None


def _decode_error(text: str, status: int) -> tuple[str, str]:
    """Pull ``code``/``reason`` out of an error body, with sane fallbacks."""
    try:
        import json

        payload = json.loads(text)
        if isinstance(payload, dict):
            return (
                str(payload.get("code") or f"http_{status}"),
                str(payload.get("reason") or f"HTTP {status}"),
            )
    except Exception:
        pass
    return f"http_{status}", f"HTTP {status}"


_client: Optional[IpcClient] = None


def get_client() -> IpcClient:
    """The process-wide client."""
    global _client
    if _client is None:
        _client = IpcClient()
    return _client


async def close_client() -> None:
    """Close the shared session. Call from the entrypoint's shutdown handler."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


__all__ = ["IpcClient", "close_client", "get_client"]
