"""Premium entitlements cog (portable across EoS bots).

Detects Discord premium entitlements (gateway events + reconciliation safety net + interaction
backfill), persists them through the shared storage system, and exposes a stable
"is this server premium?" API to the rest of the bot. Everything bot-specific lives in the
`settings` seam (`settings/config.py`); every other module here is copied unchanged.

Public API for other cogs:  `from commands.premium.api import is_premium, get_tier, require_premium`
Data/logic:                 shared engine `storage.premium` (PremiumManager); the relay singleton
                            is wired in `storage.bot_specific.relay` and attached as `bot.premium_manager`
"""
