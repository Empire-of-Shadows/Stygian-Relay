"""Per-bot premium settings - THE seam (the only file each bot edits).

Everything premium-specific to THIS bot lives here: which Discord application owns the SKUs,
which SKUs map to which tier, and the operational knobs. Deployment IDs (application, roles,
channels, owners) are read from the environment so nothing secret is committed; the SKU
semantic map is code because it encodes product meaning, not a secret.

Copy `config.example.py` when standing this up for a new bot and fill in the SKUS map. Until
SKUs exist the system runs in manual-grant-only mode (owner `/premium-admin grant`), which is the
current state for Stygian-Relay - no Discord monetization is configured yet.
"""
import os


def _int_or_none(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    return int(raw) if raw.isdigit() else None


def _id_list(*env_vars: str) -> list[int]:
    for var in env_vars:
        raw = os.getenv(var, "")
        ids = [int(p.strip()) for p in raw.split(",") if p.strip().isdigit()]
        if ids:
            return ids
    return []


# Discord application that owns the SKUs/entitlements (entitlements are app-scoped).
APPLICATION_ID = _int_or_none(os.getenv("PREMIUM_APPLICATION_ID") or os.getenv("APPLICATION_ID"))

# sku_id -> {name, kind, tier, consumable?}. `kind` is "subscription" or "one_time"; `tier` is
# the label the rest of the bot keys premium features off of; `consumable` (one-time only)
# marks a SKU that must be consumed after fulfilment. Empty until monetization SKUs exist.
SKUS: dict[str, dict] = {
    # "1234567890123456789": {"name": "Relay Premium (Monthly)", "kind": "subscription", "tier": "premium"},
    # "1234567890123456790": {"name": "Relay Premium (Lifetime)", "kind": "one_time", "tier": "premium"},
}

# Tier labels, best first. Orders PremiumState.tier when a scope holds several entitlements.
TIER_PRIORITY: list[str] = ["premium"]

# Optional role granted/removed in a guild when premium turns on/off, per tier.
PREMIUM_ROLE_IDS: dict[str, int] = {
    # "premium": 123456789012345678,
}

# Where premium grant/lapse/audit notices post (falls back to the guild's own log channel).
LOG_CHANNEL_ID = _int_or_none(os.getenv("PREMIUM_LOG_CHANNEL_ID"))

# Reconciliation loop cadence + whether to run a full pass on startup.
RECONCILE_INTERVAL_MINUTES = int(os.getenv("PREMIUM_RECONCILE_MINUTES", "60"))
RECONCILE_ON_STARTUP = os.getenv("PREMIUM_RECONCILE_ON_STARTUP", "true").strip().lower() != "false"

# Enables the `/premium test` commands and louder logging.
TEST_MODE = os.getenv("PREMIUM_TEST_MODE", "false").strip().lower() == "true"

# DM/ping configured owners on premium changes.
NOTIFY_OWNERS_ON_CHANGE = os.getenv("PREMIUM_NOTIFY_OWNERS", "false").strip().lower() == "true"

# Bot owner(s) allowed to run owner-gated premium commands (grant/revoke/test/etc). Env-first,
# falling back to the shared BOT_OWNER_ID, then relay's owner.
OWNER_IDS = _id_list("PREMIUM_OWNER_IDS", "BOT_OWNER_ID") or [1264236749060575355]

# Guild(s) the management commands (everything except `/premium status`) register into, keeping
# them out of every other guild's command list. Empty = they register globally (runtime-gated).
ADMIN_GUILD_IDS = _id_list("PREMIUM_ADMIN_GUILD_IDS") or [1497083403453989007]
