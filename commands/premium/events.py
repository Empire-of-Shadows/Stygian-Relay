"""Bot-internal premium events.

The premium cog dispatches these via `bot.dispatch(...)` so other cogs react to premium
changes without importing or coupling to this cog. Listen with, e.g.:

    @commands.Cog.listener()
    async def on_premium_granted(self, state):   # state: PremiumState
        ...

Events (all carry the fresh PremiumState, plus old_state where a transition is compared):
    premium_granted   - a scope went from not-premium to premium
    premium_upgraded   - already premium, but the tier set changed
    premium_expired   - premium lapsed on its own (subscription ended / grant expired)
    premium_revoked   - premium removed (refund/manual revoke/entitlement delete)
"""
from __future__ import annotations

from typing import Optional

from storage.premium import PremiumState

EVENT_GRANTED = "premium_granted"
EVENT_UPGRADED = "premium_upgraded"
EVENT_EXPIRED = "premium_expired"
EVENT_REVOKED = "premium_revoked"


def dispatch_transition(
    bot,
    old_state: PremiumState,
    new_state: PremiumState,
    *,
    lapsed: bool = False,
) -> Optional[str]:
    """Compare old vs new premium state and dispatch the right event. Returns the event name.

    `lapsed=True` distinguishes a self-expiry (subscription ended) from an active removal so
    a granted -> not-premium transition dispatches `premium_expired` rather than
    `premium_revoked`.
    """
    was, now = old_state.is_premium, new_state.is_premium

    if not was and now:
        bot.dispatch(EVENT_GRANTED, new_state)
        return EVENT_GRANTED
    if was and not now:
        event = EVENT_EXPIRED if lapsed else EVENT_REVOKED
        bot.dispatch(event, new_state)
        return event
    if was and now and set(old_state.tiers) != set(new_state.tiers):
        bot.dispatch(EVENT_UPGRADED, new_state, old_state)
        return EVENT_UPGRADED
    return None
