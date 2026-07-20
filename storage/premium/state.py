# ---------------------------------------------------------------------------
# VENDORED from storage_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ---------------------------------------------------------------------------
"""Pure premium-state computation (no DB, no discord.py).

Given a scope's entitlement records, derive the fast-read ``PremiumState`` the rest of the
bot keys premium features off of. Kept pure so it is trivially testable and so the DB-facing
``PremiumManager`` and any read-only consumer compute identical answers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ._time import ensure_utc
from .constants import TIER_FREE, TIER_UNKNOWN


def entitlement_is_active(record: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True if an entitlement record currently grants access.

    Active means: not deleted, not a spent consumable, started (or no start), and not yet
    ended (or no end). This mirrors Discord's model where an active subscription has
    ``ends_at is None`` until it is cancelled, then lapses once ``ends_at`` passes.
    """
    if record.get("deleted"):
        return False
    if record.get("consumed"):
        # A consumed one-time consumable is spent. Durable purchases and subscriptions are
        # never consumed, so this only ever drops used-up consumables.
        return False
    now = now or datetime.now(timezone.utc)
    starts_at = ensure_utc(record.get("starts_at"))
    if starts_at is not None and starts_at > now:
        return False
    ends_at = ensure_utc(record.get("ends_at"))
    if ends_at is not None and ends_at <= now:
        return False
    return True


@dataclass
class PremiumState:
    """Derived premium status for one scope (a guild today, a user in future)."""

    scope: str
    scope_id: str
    is_premium: bool = False
    tiers: List[str] = field(default_factory=list)
    active_sku_ids: List[str] = field(default_factory=list)
    expires_at: Optional[datetime] = None

    @property
    def tier(self) -> str:
        """Single tier label for callers that want one value (best active tier, else free)."""
        return self.tiers[0] if self.tiers else TIER_FREE

    def to_doc(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Serialize to the persisted ``premium_state`` document shape."""
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "is_premium": self.is_premium,
            "tiers": self.tiers,
            "tier": self.tier,
            "active_sku_ids": self.active_sku_ids,
            "expires_at": self.expires_at,
            "updated_at": now or datetime.now(timezone.utc),
        }

    @classmethod
    def from_doc(cls, doc: Dict[str, Any]) -> "PremiumState":
        return cls(
            scope=doc.get("scope", ""),
            scope_id=str(doc.get("scope_id", "")),
            is_premium=bool(doc.get("is_premium", False)),
            tiers=list(doc.get("tiers", [])),
            active_sku_ids=list(doc.get("active_sku_ids", [])),
            expires_at=ensure_utc(doc.get("expires_at")),
        )


def compute_state(
    scope: str,
    scope_id: str,
    records: List[Dict[str, Any]],
    now: Optional[datetime] = None,
    tier_priority: Optional[List[str]] = None,
) -> PremiumState:
    """Fold a scope's entitlement records into a single ``PremiumState``.

    ``tier_priority`` (highest first) orders the ``tiers`` list so ``state.tier`` returns the
    best active tier; unknown tiers sort last. When omitted, tiers keep first-seen order.
    ``expires_at`` is the latest ``ends_at`` among active records, or ``None`` if any active
    record is indefinite (an uncancelled subscription).
    """
    now = now or datetime.now(timezone.utc)
    active = [r for r in records if entitlement_is_active(r, now)]

    tiers: List[str] = []
    skus: List[str] = []
    indefinite = False
    latest_end: Optional[datetime] = None
    for r in active:
        tier = r.get("tier") or TIER_UNKNOWN
        if tier not in tiers:
            tiers.append(tier)
        sku = r.get("sku_id")
        if sku and sku not in skus:
            skus.append(sku)
        ends_at = ensure_utc(r.get("ends_at"))
        if ends_at is None:
            indefinite = True
        elif latest_end is None or ends_at > latest_end:
            latest_end = ends_at

    if tier_priority:
        rank = {t: i for i, t in enumerate(tier_priority)}
        tiers.sort(key=lambda t: rank.get(t, len(rank)))

    return PremiumState(
        scope=scope,
        scope_id=str(scope_id),
        is_premium=bool(active),
        tiers=tiers,
        active_sku_ids=skus,
        expires_at=None if indefinite else latest_end,
    )
