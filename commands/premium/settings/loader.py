"""Load + validate the per-bot premium settings (portable; do not edit per bot).

Reads `config.py`, applies defaults, validates types, and returns a `PremiumSettings`. On any
problem it logs a clear, actionable error and returns safe manual-grant-only defaults rather
than crashing the bot on load - a broken settings file must never take the whole bot down.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from storage.bot_specific.relay.premium import TIER_UNKNOWN

logger = logging.getLogger("PremiumSettings")

_VALID_KINDS = {"subscription", "one_time"}


@dataclass
class PremiumSettings:
    application_id: Optional[int] = None
    skus: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tier_priority: List[str] = field(default_factory=list)
    premium_role_ids: Dict[str, int] = field(default_factory=dict)
    log_channel_id: Optional[int] = None
    reconcile_interval_minutes: int = 60
    reconcile_on_startup: bool = True
    test_mode: bool = False
    notify_owners_on_change: bool = False
    owner_ids: List[int] = field(default_factory=list)
    admin_guild_ids: List[int] = field(default_factory=list)

    @property
    def is_configured(self) -> bool:
        """True when real Discord entitlements can be listed/reconciled (app + at least one SKU)."""
        return bool(self.application_id and self.skus)

    def sku_ids(self) -> List[str]:
        return list(self.skus.keys())

    def tier_for_sku(self, sku_id: Any) -> str:
        return self.skus.get(str(sku_id), {}).get("tier", TIER_UNKNOWN)

    def kind_for_sku(self, sku_id: Any) -> Optional[str]:
        return self.skus.get(str(sku_id), {}).get("kind")

    def is_consumable(self, sku_id: Any) -> bool:
        entry = self.skus.get(str(sku_id), {})
        return entry.get("kind") == "one_time" and bool(entry.get("consumable"))

    def role_for_tier(self, tier: str) -> Optional[int]:
        return self.premium_role_ids.get(tier)

    def is_owner(self, user_id: Any) -> bool:
        try:
            return int(user_id) in self.owner_ids
        except (TypeError, ValueError):
            return False


def _validate_skus(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        logger.error("premium settings: SKUS must be a dict of sku_id -> {name, kind, tier}; got %r", type(raw))
        return {}
    cleaned: Dict[str, Dict[str, Any]] = {}
    for sku_id, meta in raw.items():
        if not isinstance(meta, dict):
            logger.error("premium settings: SKU %s entry must be a dict; skipping", sku_id)
            continue
        kind = meta.get("kind")
        tier = meta.get("tier")
        if kind not in _VALID_KINDS:
            logger.error("premium settings: SKU %s has invalid kind %r (want %s); skipping",
                         sku_id, kind, _VALID_KINDS)
            continue
        if not tier or not isinstance(tier, str):
            logger.error("premium settings: SKU %s missing a string 'tier'; skipping", sku_id)
            continue
        cleaned[str(sku_id)] = {
            "name": str(meta.get("name", sku_id)),
            "kind": kind,
            "tier": tier,
            "consumable": bool(meta.get("consumable", False)),
        }
    return cleaned


def load_settings() -> PremiumSettings:
    """Load the seam `config.py` into a validated `PremiumSettings` (safe defaults on error)."""
    try:
        from . import config  # the per-bot seam
    except Exception as e:
        logger.error(
            "premium settings: could not import config.py (%s). Running manual-grant-only with "
            "safe defaults; copy config.example.py to config.py to configure.", e, exc_info=True,
        )
        return PremiumSettings()

    def _get(name: str, default: Any) -> Any:
        return getattr(config, name, default)

    try:
        skus = _validate_skus(_get("SKUS", {}))
        tier_priority = list(_get("TIER_PRIORITY", []) or [])
        # Any tier used by a SKU but missing from priority still works (ranked last); warn so it
        # is easy to spot a typo.
        for meta in skus.values():
            if meta["tier"] not in tier_priority and meta["tier"] != TIER_UNKNOWN:
                logger.warning("premium settings: tier %r is used by a SKU but not in TIER_PRIORITY",
                               meta["tier"])

        settings = PremiumSettings(
            application_id=_get("APPLICATION_ID", None),
            skus=skus,
            tier_priority=tier_priority,
            premium_role_ids={str(k): int(v) for k, v in (_get("PREMIUM_ROLE_IDS", {}) or {}).items() if v},
            log_channel_id=_get("LOG_CHANNEL_ID", None),
            reconcile_interval_minutes=max(5, int(_get("RECONCILE_INTERVAL_MINUTES", 60))),
            reconcile_on_startup=bool(_get("RECONCILE_ON_STARTUP", True)),
            test_mode=bool(_get("TEST_MODE", False)),
            notify_owners_on_change=bool(_get("NOTIFY_OWNERS_ON_CHANGE", False)),
            owner_ids=[int(x) for x in (_get("OWNER_IDS", []) or [])],
            admin_guild_ids=[int(x) for x in (_get("ADMIN_GUILD_IDS", []) or [])],
        )
    except Exception as e:
        logger.error("premium settings: config.py is malformed (%s); using safe defaults", e, exc_info=True)
        return PremiumSettings()

    if not settings.is_configured:
        logger.info("premium: no APPLICATION_ID/SKUS configured - running in manual-grant-only mode")
    else:
        logger.info("premium: configured with %d SKU(s) on application %s",
                    len(settings.skus), settings.application_id)
    return settings
