# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Premium domain constants (collection names, scopes, sources, tier sentinels).

Master-owned, bot-agnostic. Real tier labels come from the per-bot SKU map in the cog's
``premium/settings`` seam; only the sentinels ("free"/"unknown") live here.
"""

# Collections (in the relay application DB, discord_forwarding_bot).
ENTITLEMENTS_COLLECTION = "entitlements"
PREMIUM_STATE_COLLECTION = "premium_state"

# Entitlement scope. Guild-level today; user-level is future-proofed by carrying the same
# (scope, scope_id) shape so nothing but a scope value changes when per-user premium lands.
SCOPE_GUILD = "guild"
SCOPE_USER = "user"

# Where a stored entitlement came from.
SOURCE_EVENT = "event"              # gateway ENTITLEMENT_CREATE/UPDATE/DELETE
SOURCE_RECONCILE = "reconcile"      # List Entitlements HTTP reconcile pass
SOURCE_INTERACTION = "interaction"  # interaction.entitlements backfill
SOURCE_MANUAL = "manual"            # owner-granted; not a real Discord entitlement

# Sources that mirror a real Discord entitlement. Reconcile mark-and-sweep may only expire
# these: a manual grant never appears in Discord's list endpoint, so it must never be swept.
DISCORD_SOURCES = (SOURCE_EVENT, SOURCE_RECONCILE, SOURCE_INTERACTION)

# Tier sentinels. A guild with no active entitlement is "free"; an entitlement whose SKU is
# not in the per-bot settings map is stored as "unknown" (and warned about) rather than dropped.
TIER_FREE = "free"
TIER_UNKNOWN = "unknown"

# Reconcile health metadata is stored as a subkey of the bot_settings global_config doc, so no
# extra collection is needed for a single per-bot record.
RECONCILE_HEALTH_KEY = "premium_reconcile"
