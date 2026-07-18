# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Entitlement-backed premium engine (bot-agnostic; per-guild now, per-user future-proofed).

Raw ``entitlements`` records fold into a fast-read ``premium_state`` doc per scope. The
application DB name is injected when the manager is constructed, so this package has no per-bot
coupling - a bot wires its own singleton (with its DB name, SKU/tier map, and any opt-in legacy
migration) in its seam and imports the shared types/constants from here::

    from storage.premium import PremiumManager, PremiumState, SCOPE_GUILD

The per-bot SKU map + settings live in the consuming cog's ``premium/settings`` seam, not here.
"""

from .constants import (
    DISCORD_SOURCES,
    ENTITLEMENTS_COLLECTION,
    PREMIUM_STATE_COLLECTION,
    RECONCILE_HEALTH_KEY,
    SCOPE_GUILD,
    SCOPE_USER,
    SOURCE_EVENT,
    SOURCE_INTERACTION,
    SOURCE_MANUAL,
    SOURCE_RECONCILE,
    TIER_FREE,
    TIER_UNKNOWN,
)
from .premium_manager import PremiumManager
from .state import PremiumState, compute_state, entitlement_is_active

__all__ = [
    "PremiumManager",
    "PremiumState",
    "compute_state",
    "entitlement_is_active",
    "ENTITLEMENTS_COLLECTION",
    "PREMIUM_STATE_COLLECTION",
    "RECONCILE_HEALTH_KEY",
    "DISCORD_SOURCES",
    "SCOPE_GUILD",
    "SCOPE_USER",
    "SOURCE_EVENT",
    "SOURCE_RECONCILE",
    "SOURCE_INTERACTION",
    "SOURCE_MANUAL",
    "TIER_FREE",
    "TIER_UNKNOWN",
]
