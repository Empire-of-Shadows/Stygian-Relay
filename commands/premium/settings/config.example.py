"""Documented template for a bot's premium settings seam.

Copy this to `config.py` and fill it in. `config.py` is the ONLY file that differs between
bots; every other file under `commands/premium/` is portable and copied unchanged.

Every field is optional with a safe default. With an empty SKUS map the cog runs in
manual-grant-only mode: owners grant premium with `/premium-admin grant` and no Discord monetization
is required. Fill SKUS in once your Discord app has monetization SKUs to also pick up real
purchases automatically via gateway events + the reconciliation safety net.
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


# REQUIRED for real entitlements: the Discord application id that owns your SKUs. Entitlements
# are app-scoped, so reconciliation lists `/applications/{APPLICATION_ID}/entitlements`.
APPLICATION_ID = _int_or_none(os.getenv("PREMIUM_APPLICATION_ID") or os.getenv("APPLICATION_ID"))

# The heart of the seam: map each of your Discord SKU ids to what it means.
#   name       - human label shown in admin/logs
#   kind       - "subscription" (recurring) or "one_time" (durable/consumable purchase)
#   tier       - the premium tier this SKU grants; other code keys features off this label
#   consumable - one_time only; True means the entitlement is consumed after fulfilment
SKUS: dict[str, dict] = {
    # "1234567890123456789": {"name": "Gold (Monthly)", "kind": "subscription", "tier": "gold"},
    # "1234567890123456790": {"name": "Gold (Lifetime)", "kind": "one_time",    "tier": "gold"},
    # "1234567890123456791": {"name": "Boost Pack",      "kind": "one_time",    "tier": "gold", "consumable": True},
}

# Tier labels ranked best-first. Determines the single `tier` reported when a scope holds
# multiple active entitlements. Include every tier that appears in SKUS.
TIER_PRIORITY: list[str] = ["gold"]

# Optional: role added/removed in the guild when a tier turns on/off. Omit to skip role sync.
PREMIUM_ROLE_IDS: dict[str, int] = {
    # "gold": 123456789012345678,
}

# Optional: channel id for premium grant/lapse/audit posts. Falls back to the guild's log
# channel when unset.
LOG_CHANNEL_ID = _int_or_none(os.getenv("PREMIUM_LOG_CHANNEL_ID"))

# How often the reconciliation loop runs, and whether to run a full pass at startup. The loop
# is the safety net that recovers any missed gateway event.
RECONCILE_INTERVAL_MINUTES = int(os.getenv("PREMIUM_RECONCILE_MINUTES", "60"))
RECONCILE_ON_STARTUP = os.getenv("PREMIUM_RECONCILE_ON_STARTUP", "true").strip().lower() != "false"

# Enables `/premium test grant|revoke` (create/delete real Discord test entitlements) and
# more verbose logging. Keep False in production.
TEST_MODE = os.getenv("PREMIUM_TEST_MODE", "false").strip().lower() == "true"

# DM/ping configured owners when premium changes.
NOTIFY_OWNERS_ON_CHANGE = os.getenv("PREMIUM_NOTIFY_OWNERS", "false").strip().lower() == "true"

# Owner user ids allowed to run owner-gated commands (grant/revoke/test).
OWNER_IDS = _id_list("PREMIUM_OWNER_IDS", "BOT_OWNER_ID")

# Guild ids the owner-only commands register into (optional; empty registers globally and
# gates at runtime).
ADMIN_GUILD_IDS = _id_list("PREMIUM_ADMIN_GUILD_IDS")
