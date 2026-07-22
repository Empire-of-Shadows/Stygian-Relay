# ---------------------------------------------------------------------------
# VENDORED from runtime_engine/ - DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/runtime_engine/ and run:
#     python tools/sync_runtime_engine.py
# Drift is enforced by:  python tools/sync_runtime_engine.py --check
# ---------------------------------------------------------------------------
"""PresenceRotator - config-driven rotating bot presence (engine-owned).

Unifies the idle/presence rotators the bots hand-rolled (TheDecree/ImperialReminder's
IdleManager, Stygian-Relay's weighted status/idle loop, TheHost's category-weighted
rotator): the engine owns the loop, jitter, no-repeat queues, and lifecycle; a bot
supplies only DATA - its phrase pools (and optional weights/status) - typically from a
thin ``Features/idle.py`` seam::

    from startup.presence import PresenceRotator

    class IdleManager(PresenceRotator):
        def __init__(self, bot):
            super().__init__(bot, POOLS, status=discord.Status.dnd)

Pools map an activity-type name (``playing`` / ``watching`` / ``listening`` /
``competing`` / ``streaming``) to a list of phrases. ``streaming`` entries are dicts
(``{"text": ..., "url": ...}``); the rest are strings. Phrases may embed the
placeholders ``{guilds}``, ``{users}`` and ``{latency_ms}``, resolved at set time
(unknown placeholders render literally, so plain braces in copy are safe).

Weighted sub-pools: a pool key may carry a ``:label`` suffix after the activity
type (``playing:promo``, ``playing:flavor``) so one activity type can host
several pools with different ``type_weights`` (TheHost's category-weighted
rotator: promo 3 / info 2 / flavor 1). The suffix only namespaces the pool;
the activity type is everything before the first ``:``. No-repeat shuffling
applies within each sub-pool.

No-repeat: each pool rotates through a shuffled queue and reshuffles only when
exhausted, so a phrase never repeats until its whole pool has been shown.
"""

from __future__ import annotations

import asyncio
import math
import random
from typing import Dict, List, Optional, Union

import discord

from storage.log import get_logger

logger = get_logger("PresenceRotator")

PoolItem = Union[str, Dict[str, str]]


class _SafeDict(dict):
    """format_map helper: unknown placeholders render as-is instead of raising."""

    def __missing__(self, key):  # pragma: no cover - trivial
        return "{" + key + "}"


class PresenceRotator:
    """Rotates the bot's presence through configured phrase pools."""

    def __init__(
        self,
        bot: discord.Client,
        pools: Dict[str, List[PoolItem]],
        *,
        rotation_interval: float = 15.0,
        interval_jitter: float = 3.0,
        status: discord.Status = discord.Status.online,
        type_weights: Optional[Dict[str, float]] = None,
    ):
        """
        :param bot: discord.Client instance
        :param pools: activity-type name -> phrase list (see module docstring)
        :param rotation_interval: base seconds between rotations
        :param interval_jitter: max random ± jitter added to the interval per cycle
        :param status: presence status to use while rotating
        :param type_weights: optional relative weight per pool key (uniform when omitted)
        """
        self.bot = bot
        self.status_pools: Dict[str, List[PoolItem]] = pools
        self.rotation_interval = rotation_interval
        self.interval_jitter = max(0.0, interval_jitter)
        self.default_status = status
        self.type_weights = type_weights or {}

        self._is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        # Per-activity-type shuffled queues to avoid repeats within a cycle
        self._rotation_queues: Dict[str, List] = {}
        self._lock = asyncio.Lock()

    # ------------- Lifecycle -------------

    def start_status_rotation(self) -> None:
        """Starts the background rotation task (idempotent)."""
        if self._task and not self._task.done():
            logger.warning("Status rotation is already running.")
            return
        self._task = asyncio.create_task(self._run_rotation(), name="presence_rotation")
        logger.info("Status rotation started as a background task.")

    def stop_status_rotation(self) -> None:
        """Stops the rotation task and cancels it if running."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._is_running = False
        logger.info("Status rotation stopped.")

    async def _run_rotation(self) -> None:
        """Main rotation loop with readiness wait and graceful cancellation."""
        try:
            self._is_running = True
            await self.bot.wait_until_ready()
            logger.info("Running status rotation task.")
            while self._is_running and not self.bot.is_closed():
                try:
                    activity, status = await self._compute_next_activity()
                    if activity is not None:
                        # Timeout wrapper to avoid hanging forever
                        await asyncio.wait_for(
                            self.bot.change_presence(status=status, activity=activity),
                            timeout=10.0,
                        )
                        logger.info(f"Set bot status: {activity.name} [{status}]")
                except asyncio.TimeoutError:
                    logger.warning("Timed out while changing presence.")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error during presence update: {e}", exc_info=True)

                # Sleep with jitter
                sleep_for = self.rotation_interval
                if self.interval_jitter > 0:
                    sleep_for += random.uniform(-self.interval_jitter, self.interval_jitter)
                sleep_for = max(1.0, sleep_for)
                try:
                    await asyncio.sleep(sleep_for)
                except asyncio.CancelledError:
                    raise

        except asyncio.CancelledError:
            logger.info("Status rotation task cancelled.")
        except Exception as e:
            logger.error(f"Rotation loop crashed: {e}", exc_info=True)
        finally:
            self._is_running = False
            logger.info("Status rotation task stopped.")

    # ------------- Internal helpers -------------

    def _placeholders(self) -> "_SafeDict":
        guilds = list(getattr(self.bot, "guilds", []) or [])
        try:
            latency = self.bot.latency
            latency_ms = (
                None if latency is None or math.isnan(latency) or math.isinf(latency)
                else round(latency * 1000)
            )
        except Exception:
            latency_ms = None
        return _SafeDict(
            guilds=len(guilds),
            users=sum(g.member_count or 0 for g in guilds),
            latency_ms=latency_ms if latency_ms is not None else "?",
        )

    def _format_text(self, text: str) -> str:
        try:
            return text.format_map(self._placeholders())
        except Exception:
            return text

    async def _compute_next_activity(self):
        """Decide the next activity and status using the no-repeat pool queues."""
        async with self._lock:
            activity_type_key = self._choose_activity_type_key()
            if activity_type_key is None:
                return None, self.default_status

            item = self._next_from_pool_queue(activity_type_key)
            if item is None:
                return None, self.default_status

        # Build activity outside the lock. Pool keys may carry a ":label"
        # sub-pool suffix; the activity type is everything before it.
        activity_type = activity_type_key.split(":", 1)[0]
        if activity_type == "streaming":
            act = discord.Streaming(name=self._format_text(item["text"]), url=item["url"])
        else:
            act = discord.Activity(
                type=getattr(discord.ActivityType, activity_type),
                name=self._format_text(item),
            )
        return act, self.default_status

    def _choose_activity_type_key(self) -> Optional[str]:
        """Selects a pool key that has items (weighted when type_weights is set)."""
        candidates = [k for k, v in self.status_pools.items() if v]
        if not candidates:
            logger.warning("No status pools contain items.")
            return None
        if self.type_weights:
            weights = [float(self.type_weights.get(k, 1.0)) for k in candidates]
            return random.choices(candidates, weights=weights, k=1)[0]
        return random.choice(candidates)

    def _next_from_pool_queue(self, key: str):
        """Pops the next item from the pool's shuffled queue; reshuffles when exhausted
        so nothing repeats until the whole pool has been shown."""
        queue = self._rotation_queues.get(key)
        if not queue:
            pool = self.status_pools.get(key, [])
            if not pool:
                return None
            queue = pool.copy()
            random.shuffle(queue)
            self._rotation_queues[key] = queue
        return queue.pop() if queue else None
