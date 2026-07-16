# Premium entitlements cog

Detects Discord premium **entitlements**, persists them through the shared storage engine, and
exposes a stable "is this server premium?" API - and never silently misses an entitlement, even
if a gateway event is dropped.

This package is **portable**: to stand it up in another EoS bot, copy `commands/premium/` and
fill in **only** `settings/config.py`. All data logic lives in the storage master
(`storage.bot_specific.relay.premium`), so every bot reads/writes premium identically.

## How it works

```
gateway event / reconcile loop / interaction
        -> entitlements.normalize()        (discord.Entitlement -> dict, SKU -> tier)
        -> premium_manager.record/reconcile (idempotent upsert by entitlement id)
        -> premium_manager.recompute_state  (fold entitlements -> premium_state per scope)
        -> side effects: roles, log channel, bot.dispatch(premium_*)
other cogs read via commands.premium.api
```

Three delivery paths, so a missed gateway event is never fatal:

1. **Gateway events** - `on_entitlement_create/update/delete` record changes in real time.
2. **Reconciliation loop** - periodically (and on startup) lists
   `/applications/{app}/entitlements`, upserts everything, and **mark-and-sweeps** anything
   storage still thinks is active but Discord no longer returns. Never wipes on a failed or
   empty/unbounded fetch.
3. **Interaction backfill** - `interaction.entitlements` on any interaction catches anything
   the cache missed.

Premium is **per-guild** today and **per-user ready** (records carry `scope`/`scope_id`).

## Public API (stable - other cogs depend on it)

```python
from commands.premium.api import is_premium, get_tier, get_premium_state, require_premium

await is_premium(bot, guild_id)          # -> bool
await get_tier(bot, guild_id)            # -> str | None
await get_premium_state(bot, guild_id)   # -> PremiumState

@app_commands.command()
@require_premium(tier="gold")            # blocks non-premium (or wrong tier) guilds
async def fancy(self, interaction): ...
```

Bot-internal events (react without coupling to this cog):
`premium_granted`, `premium_upgraded`, `premium_expired`, `premium_revoked` - each carries the
fresh `PremiumState`.

## Commands

`/premium status` is **global** (any member, any server). Everything else is the **`/premium-admin`**
group, which registers **only** in `ADMIN_GUILD_IDS` and is **owner-gated** at runtime:

- `/premium status` - this server's premium state (public, global)
- `/premium-admin reconcile` - force a reconciliation (owner)
- `/premium-admin health` - last reconcile time / counts / loop status (owner)
- `/premium-admin list [guild_id]` - stored entitlements for a server (owner)
- `/premium-admin grant [tier] [days] [guild_id]` - manually grant premium (owner)
- `/premium-admin revoke [guild_id]` - remove manual grants (owner)
- `/premium-admin test grant|revoke ...` - create/delete real Discord test entitlements (owner + `TEST_MODE`)

`ADMIN_GUILD_IDS` / `OWNER_IDS` live in the settings seam. The management group is guild-scoped, so
the cog syncs those guild(s) itself on load (the entrypoint only runs a global `tree.sync()`). If
`ADMIN_GUILD_IDS` is empty the group registers globally and relies on the runtime owner check.

## Wiring into a new bot

1. Copy `commands/premium/` into the bot's cog directory (auto-discovered via `setup()` in `cog.py`).
2. Ensure the storage master's `bot_specific/<bot>/premium` layer is vendored and
   `premium_manager` is attached in `attach_databases()` (calls `premium_manager.initialize()`).
3. Copy `settings/config.example.py` to `settings/config.py` and fill in `APPLICATION_ID` +
   `SKUS`. With an empty `SKUS` map the cog runs in **manual-grant-only** mode (`/premium-admin grant`)
   and needs no Discord monetization.
