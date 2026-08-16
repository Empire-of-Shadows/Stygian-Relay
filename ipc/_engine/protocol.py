# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""The wire contract both ends of an IPC call agree on.

One rule shapes everything here:

    A BUSINESS REJECTION IS A SUCCESSFUL CALL.

"Your powerup bag is full" is an ANSWER. It comes back as HTTP 200 with
``ok: false`` and a member-readable reason. A non-200 means the provider never
answered - it was unreachable, the secret was wrong, the capability does not
exist, or the handler blew up. That distinction is the whole point of the
protocol, because it is what the caller uses to decide between "tell the member
why and refund" and "we do not know what happened".

The envelope::

    POST /ipc/v1/call/<capability>
    X-IPC-Service: ecom                 # who is calling
    X-IPC-Key: <shared secret>          # constant-time compared
    Idempotency-Key: inv_7c1e...        # optional, see below
    {"params": {...}}

    200 {"ok": true,  "data": {...}}
    200 {"ok": false, "code": "inventory_full", "reason": "Your bag is full."}
    401 / 404 / 400 / 500 / 503  -> the call did not happen (or may have)

``Idempotency-Key`` is how a retry after a timeout stops being dangerous. The
server serializes calls sharing a key, remembers the answer, and replays it
instead of doing the work twice. Give it a value that is unique to the unit of
work, never to the attempt - a shop inventory ``instance_id``, not a fresh uuid
per request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

PROTOCOL_VERSION = "1"

# Path prefix for every route this engine serves.
ROUTE_PREFIX = f"/ipc/v{PROTOCOL_VERSION}"

# Headers. Named here so the client and server cannot drift apart.
HEADER_SERVICE = "X-IPC-Service"
HEADER_KEY = "X-IPC-Key"
HEADER_IDEMPOTENCY = "Idempotency-Key"

# Requests larger than this are refused unread. Capability params are small
# JSON objects; anything bigger is a mistake or an attack.
MAX_BODY_BYTES = 64 * 1024


class Reason:
    """Codes the ENGINE produces. Capabilities add their own domain codes.

    Everything from ``UNREACHABLE`` down means the call was not answered, so the
    caller must treat the outcome as unknown rather than as a refusal.
    """

    # Answered, but refused by the engine rather than by a capability.
    UNKNOWN_CAPABILITY = "unknown_capability"
    BAD_REQUEST = "bad_request"

    # Not answered.
    UNAUTHORIZED = "unauthorized"
    NOT_READY = "not_ready"
    HANDLER_ERROR = "handler_error"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    UNKNOWN_SERVICE = "unknown_service"
    BAD_RESPONSE = "bad_response"


#: Codes produced by the ENGINE rather than by a capability. Their ``reason``
#: text is written for a developer reading a log, so a consumer must NOT show it
#: to a member - substitute a friendly line and log the real one.
ENGINE_CODES = frozenset(
    value for name, value in vars(Reason).items() if not name.startswith("_")
)


def is_engine_code(code: str) -> bool:
    """True when ``code`` came from the transport, not from a capability."""
    return str(code) in ENGINE_CODES or str(code).startswith("http_")


@dataclass
class IpcResult:
    """The outcome of one call, on both sides of the wire.

    ``answered`` is the field that matters most. False means the provider never
    gave us a verdict, so we do not know whether the work happened; a caller
    holding money must treat that as a failure but log it as ambiguous, not as
    a clean refusal.
    """

    ok: bool
    code: str = ""
    reason: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    answered: bool = True

    def to_payload(self) -> Dict[str, Any]:
        """The JSON body the server sends back."""
        if self.ok:
            return {"ok": True, "data": self.data}
        return {"ok": False, "code": self.code, "reason": self.reason, "data": self.data}

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "IpcResult":
        """Parse a provider's body. Malformed bodies are NOT answers."""
        if not isinstance(payload, dict) or "ok" not in payload:
            return cls(
                ok=False,
                code=Reason.BAD_RESPONSE,
                reason="The other service sent a response we could not read.",
                answered=False,
            )
        data = payload.get("data")
        return cls(
            ok=bool(payload.get("ok")),
            code=str(payload.get("code") or ""),
            reason=str(payload.get("reason") or ""),
            data=data if isinstance(data, dict) else {},
            answered=True,
        )


def ok(**data: Any) -> IpcResult:
    """A capability succeeded. Keyword args become the ``data`` object."""
    return IpcResult(ok=True, data=dict(data))


def reject(code: str, reason: str, **data: Any) -> IpcResult:
    """A capability refused, for a reason the caller may show to a member.

    ``reason`` is read by a human in Discord, so write it that way: "Your
    powerup bag is full", not "cap exceeded (5/5)".
    """
    return IpcResult(ok=False, code=str(code), reason=str(reason), data=dict(data))


def unanswered(code: str, reason: str) -> IpcResult:
    """No verdict was received. Only the client and the transport build these."""
    return IpcResult(ok=False, code=code, reason=reason, answered=False)


@dataclass
class ParamSpec:
    """One parameter a capability takes.

    Published by the discovery endpoint so a CONSUMER's admin UI can render the
    right fields without hardcoding another service's domain. Same role as the
    shop's ``PayloadField``, and deliberately the same shape.
    """

    key: str
    label: str
    kind: str = "string"  # string | int | float | bool | snowflake
    description: str = ""
    required: bool = True
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    # Allowed values, each ``{"value", "label", "description"}``. Rich rather
    # than bare strings because the consumer renders these to an admin who has
    # never seen this service's internals - a raw key like "step_x2" in a
    # dropdown is a worse experience than "Step x2 - count by 2s".
    choices: Tuple[Dict[str, str], ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "description": self.description,
            "required": self.required,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "choices": [dict(c) for c in self.choices],
        }


@dataclass
class CapabilityContext:
    """Everything a handler needs that is not one of its params.

    Handlers are stateless singletons held by the registry, so the live bot,
    database and caller identity are threaded in per call - the same shape the
    shop's ``FulfilmentContext`` uses.
    """

    bot: Any
    db: Any
    caller: str                      # the X-IPC-Service value, already authenticated
    capability: str
    idempotency_key: Optional[str] = None


class Capability(ABC):
    """One thing this bot will do on another service's behalf.

    Owns its key, its admin-facing metadata, its parameter list and its
    validation, exactly like a shop fulfilment handler owns its item kind. A
    capability is the ONLY place a cross-service behaviour is defined; adding
    one is a single file in ``ipc/capabilities/``.

    Handlers must not raise for an expected refusal - return ``reject(...)`` so
    the caller gets a verdict it can act on. An exception is reported as
    ``handler_error``, which tells the caller the outcome is UNKNOWN, and that
    is a much worse answer than "no".
    """

    key: str = ""
    display_name: str = ""
    description: str = ""
    params: Tuple[ParamSpec, ...] = ()

    @abstractmethod
    async def handle(self, ctx: CapabilityContext, params: Dict[str, Any]) -> IpcResult:
        """Do the work. Return ``ok(...)`` or ``reject(code, reason)``."""

    def metadata(self) -> Dict[str, Any]:
        """What the discovery endpoint publishes for this capability."""
        return {
            "key": self.key,
            "display_name": self.display_name,
            "description": self.description,
            "params": [p.to_dict() for p in self.params],
        }

    # ---- shared param helpers ----

    @staticmethod
    def require_str(params: Dict[str, Any], key: str) -> Optional[str]:
        raw = params.get(key)
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None

    @staticmethod
    def require_int(params: Dict[str, Any], key: str) -> Optional[int]:
        raw = params.get(key)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return None
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def require_snowflake(params: Dict[str, Any], key: str) -> Optional[int]:
        """Discord ids cross the wire as strings and land as ints.

        Bots do not agree on this: the storage convention stores ids as strings,
        while some domain layers key their documents by int. Converting HERE, at
        the boundary, is what keeps that disagreement from leaking into either
        side's business logic.
        """
        raw = params.get(key)
        text = str(raw).strip() if raw is not None else ""
        if not text.isdigit() or not (17 <= len(text) <= 20):
            return None
        return int(text)
