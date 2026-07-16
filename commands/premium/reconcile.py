"""Reconciliation service - the safety net that makes gateway-event loss non-fatal.

Pages the List Entitlements endpoint (via `bot.entitlements(...)`), upserts everything it
returns, and mark-and-sweeps anything storage still thinks is active but Discord no longer
returns. Never wipes on a failed/empty fetch: it only hands results to the store on success,
and the store itself refuses an unbounded empty sweep.
"""
from __future__ import annotations

import logging
from typing import List

import discord

from .entitlements import normalize
from .settings import PremiumSettings

logger = logging.getLogger("PremiumReconcile")


class Reconciler:
    def __init__(self, bot, premium_manager, settings: PremiumSettings):
        self.bot = bot
        self.premium = premium_manager
        self.settings = settings

    async def run(self, *, trigger: str = "loop") -> dict:
        """Run one full reconciliation pass. Returns the store's summary counts.

        Raises on fetch failure so callers can record a reconcile error and leave stored state
        untouched (a failed fetch must never lapse anyone).
        """
        if not self.settings.is_configured:
            logger.debug("Reconcile skipped (%s): no APPLICATION_ID/SKUS configured", trigger)
            return {"added": 0, "updated": 0, "expired": 0, "seen": 0, "skipped": True}

        sku_objs = [discord.Object(id=int(s)) for s in self.settings.sku_ids()]
        records = []
        try:
            # exclude_deleted=True: refunded/removed entitlements simply won't appear, so the
            # sweep marks them deleted. exclude_ended=False: keep lapsed subs so we persist
            # their ends_at and the state fold treats them as inactive.
            async for ent in self.bot.entitlements(
                skus=sku_objs or None,
                exclude_deleted=True,
                exclude_ended=False,
                limit=None,
            ):
                records.append(normalize(ent, self.settings))
        except discord.HTTPException as e:
            logger.warning("Reconcile (%s) fetch failed: %s - leaving stored state intact", trigger, e)
            await self.premium.record_reconcile_error(f"fetch failed: {e}")
            raise

        summary = await self.premium.reconcile(records, sku_ids=self.settings.sku_ids())
        logger.info("Reconcile (%s) complete: %s", trigger, summary)
        return summary
