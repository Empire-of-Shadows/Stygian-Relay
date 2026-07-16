"""PremiumCog - entitlement listeners, reconciliation loop, and premium admin commands.

Portable across bots: everything bot-specific comes from the `settings` seam. The cog is a thin
discord.py layer over the storage master's `PremiumManager` (attached as `bot.premium_manager`):
it converts entitlement payloads to dicts, drives the reconcile safety net, runs side effects
(roles / log posts / owner notices), dispatches bot-internal `premium_*` events, and exposes the
admin commands. No premium data logic lives here.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from storage.bot_specific.relay.premium import (
    SCOPE_GUILD,
    SCOPE_USER,
    SOURCE_EVENT,
    SOURCE_INTERACTION,
    SOURCE_MANUAL,
)

from . import events
from .entitlements import normalize
from .reconcile import Reconciler
from .settings import config as _config
from .settings import load_settings

logger = logging.getLogger("Premium")

# Resolved at import so the management group can be guild-restricted at class-definition time
# (discord.py applies `guild_ids` when the group is created). When empty, the group registers
# globally instead and relies on the runtime owner check.
_ADMIN_GUILD_IDS = [int(g) for g in (getattr(_config, "ADMIN_GUILD_IDS", []) or [])]


class PremiumCog(commands.Cog):
    """Detects Discord premium entitlements, persists them, and exposes premium admin tooling."""

    # Public: `/premium status`, synced globally so anyone can check their server.
    premium = app_commands.Group(name="premium", description="Premium subscription status")
    # Management: `/premium-admin ...`, guild-scoped to PREMIUM_ADMIN_GUILD_IDS and owner-gated at
    # runtime. A separate group (not the `premium` group) because a group's scope is all-or-nothing
    # and `status` must stay global. Falls back to a global group when no admin guild is set.
    premium_admin = app_commands.Group(
        name="premium-admin",
        description="Premium management (owner only)",
        guild_ids=_ADMIN_GUILD_IDS or None,
    )
    test = app_commands.Group(
        name="test", description="Premium test entitlements (owner)", parent=premium_admin
    )

    def __init__(self, bot):
        self.bot = bot
        self.settings = load_settings()
        # Attached in attach_databases() before cogs load; fall back to the facade singleton.
        self.premium_manager = getattr(bot, "premium_manager", None)
        if self.premium_manager is None:
            from storage.bot_specific.relay import premium_manager as _pm
            self.premium_manager = _pm
        # Feed the per-bot tier ordering into the (bot-agnostic) manager.
        self.premium_manager.tier_priority = self.settings.tier_priority
        self.guild_manager = getattr(bot, "guild_manager", None)
        self.audit_log = getattr(bot, "audit_log", None)
        self.reconciler = Reconciler(bot, self.premium_manager, self.settings)
        self._startup_task: Optional[asyncio.Task] = None
        self._guild_sync_task: Optional[asyncio.Task] = None
        # Cap the in-process interaction-backfill dedupe set so it can't grow unbounded.
        self._seen_interaction_ids: set[str] = set()
        logger.info(
            "Premium cog initialized (configured=%s, test_mode=%s, owners=%s)",
            self.settings.is_configured, self.settings.test_mode, self.settings.owner_ids,
        )

    # ── lifecycle ─────────────────────────────────────────────────────────────────

    async def cog_load(self):
        if self.settings.is_configured:
            self._reconcile_loop.change_interval(minutes=self.settings.reconcile_interval_minutes)
            if self.settings.reconcile_on_startup:
                self._startup_task = asyncio.create_task(self._startup_reconcile())
            self._reconcile_loop.start()
        else:
            logger.info("Premium reconcile loop not started (manual-grant-only mode)")
        # The `premium-admin` group is guild-scoped, so the entrypoint's global tree.sync() does
        # not push it. Sync each admin guild ourselves (keeps the cog self-contained/portable).
        if self.settings.admin_guild_ids:
            self._guild_sync_task = asyncio.create_task(self._sync_admin_guilds())

    async def cog_unload(self):
        self._reconcile_loop.cancel()
        if self._startup_task:
            self._startup_task.cancel()
        if self._guild_sync_task:
            self._guild_sync_task.cancel()

    async def _sync_admin_guilds(self):
        await self.bot.wait_until_ready()
        for gid in self.settings.admin_guild_ids:
            try:
                await self.bot.tree.sync(guild=discord.Object(id=int(gid)))
                logger.info("Synced /premium-admin commands to guild %s", gid)
            except Exception as e:
                logger.warning("Failed to sync /premium-admin commands to guild %s: %s", gid, e)

    async def _startup_reconcile(self):
        await self.bot.wait_until_ready()
        try:
            await self.reconciler.run(trigger="startup")
        except Exception as e:
            logger.warning("Startup reconcile failed (non-fatal): %s", e)

    @tasks.loop(minutes=60)
    async def _reconcile_loop(self):
        try:
            await self.reconciler.run(trigger="loop")
        except Exception as e:
            logger.warning("Scheduled reconcile failed (non-fatal): %s", e)

    @_reconcile_loop.before_loop
    async def _before_reconcile(self):
        await self.bot.wait_until_ready()

    # ── entitlement events ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_entitlement_create(self, entitlement: discord.Entitlement):
        await self._handle_entitlement(entitlement, event="create")

    @commands.Cog.listener()
    async def on_entitlement_update(self, entitlement: discord.Entitlement):
        await self._handle_entitlement(entitlement, event="update")

    @commands.Cog.listener()
    async def on_entitlement_delete(self, entitlement: discord.Entitlement):
        await self._handle_entitlement(entitlement, event="delete")

    async def _handle_entitlement(self, entitlement: discord.Entitlement, *, event: str):
        try:
            record = normalize(entitlement, self.settings)
            if event == "delete":
                record["deleted"] = True
            scope, scope_id = record["scope"], record["scope_id"]

            old_state = await self.premium_manager.get_state(scope, scope_id)
            stored = await self.premium_manager.record_entitlement(record, source=SOURCE_EVENT)
            new_state = await self.premium_manager.get_state(scope, scope_id)

            await self._maybe_consume(entitlement, record, stored)
            # A time-driven update that drops premium is a lapse; a delete is an active removal.
            await self._apply_side_effects(
                scope, scope_id, old_state, new_state, source=event, lapsed=(event == "update"),
            )
            logger.info("Entitlement %s (%s) -> %s:%s premium=%s",
                        entitlement.id, event, scope, scope_id, new_state.is_premium)
        except Exception as e:
            logger.error("Failed handling entitlement %s (%s): %s",
                         getattr(entitlement, "id", "?"), event, e, exc_info=True)

    async def _maybe_consume(self, entitlement, record, stored):
        """Consume + record fulfilment for a one-time consumable SKU, exactly once."""
        if not self.settings.is_consumable(record["sku_id"]):
            return
        if stored and stored.get("fulfilled"):
            return
        try:
            await entitlement.consume()
            await self.premium_manager.mark_fulfilled(record["entitlement_id"], consumed=True)
            logger.info("Consumed one-time entitlement %s (sku %s)", record["entitlement_id"], record["sku_id"])
        except discord.HTTPException as e:
            logger.warning("Failed to consume entitlement %s: %s", record["entitlement_id"], e)

    # ── interaction backfill ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        ents = getattr(interaction, "entitlements", None)
        if not ents:
            return
        for ent in ents:
            eid = str(ent.id)
            if eid in self._seen_interaction_ids:
                continue
            self._seen_interaction_ids.add(eid)
            if len(self._seen_interaction_ids) > 5000:
                self._seen_interaction_ids.clear()
            try:
                record = normalize(ent, self.settings)
                await self.premium_manager.record_entitlement(record, source=SOURCE_INTERACTION)
            except Exception as e:
                logger.debug("Interaction backfill skipped for entitlement %s: %s", eid, e)

    # ── side effects ──────────────────────────────────────────────────────────────

    async def _apply_side_effects(self, scope, scope_id, old_state, new_state, *, source, lapsed):
        event_name = events.dispatch_transition(self.bot, old_state, new_state, lapsed=lapsed)
        if event_name is None:
            return
        if scope == SCOPE_GUILD:
            await self._sync_roles(scope_id, old_state, new_state)
        await self._post_change(scope, scope_id, new_state, event_name, source)
        if self.settings.notify_owners_on_change:
            await self._notify_owners(scope, scope_id, new_state, event_name)

    async def _sync_roles(self, guild_id, old_state, new_state):
        if not self.settings.premium_role_ids:
            return
        guild = self.bot.get_guild(int(guild_id))
        if not guild or not guild.owner:
            return
        gained = set(new_state.tiers) - set(old_state.tiers)
        lost = set(old_state.tiers) - set(new_state.tiers)
        for tier in gained:
            role = guild.get_role(self.settings.role_for_tier(tier) or 0)
            if role:
                try:
                    await guild.owner.add_roles(role, reason=f"Premium tier {tier} granted")
                except discord.HTTPException as e:
                    logger.warning("Failed to add role %s in guild %s: %s", role.id, guild_id, e)
        for tier in lost:
            role = guild.get_role(self.settings.role_for_tier(tier) or 0)
            if role:
                try:
                    await guild.owner.remove_roles(role, reason=f"Premium tier {tier} removed")
                except discord.HTTPException as e:
                    logger.warning("Failed to remove role %s in guild %s: %s", role.id, guild_id, e)

    async def _resolve_log_channel(self, guild_id) -> Optional[discord.abc.Messageable]:
        channel_id = self.settings.log_channel_id
        if not channel_id and self.guild_manager:
            try:
                gs = await self.guild_manager.get_guild_settings(str(guild_id))
                channel_id = gs.get("master_log_channel_id")
            except Exception:
                channel_id = None
        if not channel_id:
            return None
        return self.bot.get_channel(int(channel_id))

    async def _post_change(self, scope, scope_id, state, event_name, source):
        if scope != SCOPE_GUILD:
            return
        channel = await self._resolve_log_channel(scope_id)
        if channel is None:
            return
        titles = {
            events.EVENT_GRANTED: "✅ Premium activated",
            events.EVENT_UPGRADED: "⬆️ Premium tier changed",
            events.EVENT_EXPIRED: "⌛ Premium expired",
            events.EVENT_REVOKED: "🚫 Premium removed",
        }
        colors = {
            events.EVENT_GRANTED: discord.Color.gold(),
            events.EVENT_UPGRADED: discord.Color.blurple(),
            events.EVENT_EXPIRED: discord.Color.dark_grey(),
            events.EVENT_REVOKED: discord.Color.red(),
        }
        embed = discord.Embed(
            title=titles.get(event_name, "Premium updated"),
            color=colors.get(event_name, discord.Color.blurple()),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Status", value="Premium" if state.is_premium else "Free", inline=True)
        if state.is_premium:
            embed.add_field(name="Tier", value=", ".join(state.tiers) or state.tier, inline=True)
            embed.add_field(
                name="Expires",
                value=(f"<t:{int(state.expires_at.timestamp())}:R>" if state.expires_at else "Never"),
                inline=True,
            )
        embed.set_footer(text=f"source: {source}")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            logger.warning("Failed to post premium change to channel for guild %s: %s", scope_id, e)

    async def _notify_owners(self, scope, scope_id, state, event_name):
        text = f"Premium {event_name.replace('premium_', '')} for {scope} {scope_id} (tier: {state.tier})."
        for owner_id in self.settings.owner_ids:
            try:
                user = self.bot.get_user(owner_id) or await self.bot.fetch_user(owner_id)
                if user:
                    await user.send(text)
            except discord.HTTPException:
                pass

    # ── permission helpers ────────────────────────────────────────────────────────

    def _is_owner(self, interaction: discord.Interaction) -> bool:
        return self.settings.is_owner(interaction.user.id)

    # ── commands ──────────────────────────────────────────────────────────────────

    @premium.command(name="status", description="Check this server's premium status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid = str(interaction.guild_id)
        state = await self.premium_manager.get_guild_state(gid)
        limits = await self.guild_manager.get_guild_limits(gid) if self.guild_manager else {}

        embed = discord.Embed(
            title="Premium Status",
            color=discord.Color.gold() if state.is_premium else discord.Color.blurple(),
        )
        if state.is_premium:
            embed.add_field(name="Status", value="✅ Premium Active", inline=True)
            embed.add_field(name="Tier", value=", ".join(state.tiers) or state.tier, inline=True)
            embed.add_field(
                name="Expires",
                value=(f"<t:{int(state.expires_at.timestamp())}:R>" if state.expires_at else "🌟 Never"),
                inline=True,
            )
            embed.set_footer(text="Thank you for supporting Stygian Relay!")
        else:
            embed.add_field(name="Status", value="Free Tier", inline=True)
            embed.description = (
                "Upgrade to Premium to unlock more forwarding rules, higher daily limits, and "
                "ad-free forwards."
            )
        if limits:
            embed.add_field(name="Max Rules", value=str(limits.get("max_rules", "-")), inline=True)
            embed.add_field(name="Daily Limit", value=str(limits.get("daily_limit", "-")), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @premium_admin.command(name="reconcile", description="Force a premium reconciliation with Discord")
    async def reconcile(self, interaction: discord.Interaction):
        if not self._is_owner(interaction):
            await interaction.response.send_message("This command is owner-only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if not self.settings.is_configured:
            await interaction.followup.send(
                "No Discord monetization SKUs are configured, so there is nothing to reconcile. "
                "Premium is granted manually with `/premium-admin grant`.",
                ephemeral=True,
            )
            return
        try:
            summary = await self.reconciler.run(trigger="manual")
            await interaction.followup.send(
                f"Reconcile complete: **{summary['added']}** new, **{summary['updated']}** updated, "
                f"**{summary['expired']}** expired, **{summary['seen']}** active.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"Reconcile failed: {e}", ephemeral=True)

    @premium_admin.command(name="health", description="Show premium reconciliation health")
    async def health(self, interaction: discord.Interaction):
        if not self._is_owner(interaction):
            await interaction.response.send_message("This command is owner-only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        health = await self.premium_manager.get_reconcile_health()
        embed = discord.Embed(title="Premium Reconcile Health", color=discord.Color.blurple())
        embed.add_field(name="Mode", value="configured" if self.settings.is_configured else "manual-only", inline=True)
        embed.add_field(name="Loop running", value=str(self._reconcile_loop.is_running()), inline=True)
        if health:
            last = health.get("last_run_at")
            if isinstance(last, datetime):
                embed.add_field(name="Last run", value=f"<t:{int(last.timestamp())}:R>", inline=True)
            embed.add_field(name="Last status", value=str(health.get("last_status", "-")), inline=True)
            embed.add_field(
                name="Last counts",
                value=f"+{health.get('added', 0)} / ~{health.get('updated', 0)} / -{health.get('expired', 0)}",
                inline=True,
            )
            if health.get("error"):
                embed.add_field(name="Error", value=str(health["error"])[:1000], inline=False)
        else:
            embed.description = "No reconciliation has run yet."
        await interaction.followup.send(embed=embed, ephemeral=True)

    @premium_admin.command(name="list", description="List stored entitlements for a server")
    @app_commands.describe(guild_id="Inspect another server by id (default: this server)")
    async def list_entitlements(self, interaction: discord.Interaction, guild_id: Optional[str] = None):
        if not self._is_owner(interaction):
            await interaction.response.send_message("This command is owner-only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        target = str(guild_id).strip() if guild_id else str(interaction.guild_id)

        records = await self.premium_manager.list_entitlements(scope=SCOPE_GUILD, scope_id=target, limit=25)
        if not records:
            await interaction.followup.send(f"No stored entitlements for guild `{target}`.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Entitlements - guild {target}", color=discord.Color.blue())
        for rec in records[:25]:
            ends = rec.get("ends_at")
            ends_str = f"<t:{int(ends.timestamp())}:R>" if isinstance(ends, datetime) else "never"
            embed.add_field(
                name=f"{rec.get('tier', '?')} · {rec.get('source', '?')}",
                value=(f"sku `{rec.get('sku_id')}` · id `{rec.get('entitlement_id')}`\n"
                       f"ends {ends_str}"),
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @premium_admin.command(name="grant", description="[Owner] Manually grant premium to a server")
    @app_commands.describe(
        tier="Tier label to grant (default: top configured tier)",
        days="Duration in days (omit or 0 = indefinite/lifetime)",
        guild_id="Target server id (default: this server)",
    )
    async def grant(
        self,
        interaction: discord.Interaction,
        tier: Optional[str] = None,
        days: Optional[int] = None,
        guild_id: Optional[str] = None,
    ):
        if not self._is_owner(interaction):
            await interaction.response.send_message("This command is owner-only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        target = str(guild_id).strip() if guild_id else str(interaction.guild_id)
        tier = tier or (self.settings.tier_priority[0] if self.settings.tier_priority else "premium")
        duration = days if (days and days > 0) else None

        record = await self.premium_manager.grant_manual(
            SCOPE_GUILD, target, tier, duration_days=duration, actor_id=str(interaction.user.id),
        )
        if self.audit_log:
            await self.audit_log.log(
                category="premium", guild_id=target, actor_id=str(interaction.user.id),
                action="grant", payload={"tier": tier, "days": duration, "entitlement_id": record["entitlement_id"]},
            )
        dur_str = "indefinitely" if duration is None else f"for {duration} days"
        await interaction.followup.send(
            f"Granted **{tier}** premium to guild `{target}` {dur_str}.", ephemeral=True
        )

    @premium_admin.command(name="revoke", description="[Owner] Remove manually-granted premium from a server")
    @app_commands.describe(guild_id="Target server id (default: this server)")
    async def revoke(self, interaction: discord.Interaction, guild_id: Optional[str] = None):
        if not self._is_owner(interaction):
            await interaction.response.send_message("This command is owner-only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        target = str(guild_id).strip() if guild_id else str(interaction.guild_id)
        count = await self.premium_manager.revoke_manual(SCOPE_GUILD, target)
        if self.audit_log:
            await self.audit_log.log(
                category="premium", guild_id=target, actor_id=str(interaction.user.id),
                action="revoke", payload={"revoked": count},
            )
        if count:
            await interaction.followup.send(
                f"Revoked {count} manual grant(s) from guild `{target}`. "
                "(Real Discord entitlements, if any, are unaffected.)", ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Guild `{target}` had no manual grants to revoke.", ephemeral=True
            )

    @test.command(name="grant", description="[Owner] Create a Discord test entitlement")
    @app_commands.describe(
        sku_id="SKU id to grant a test entitlement for",
        owner_type="Whether the entitlement is owned by a guild or a user",
        target_id="Owner id (default: this guild)",
    )
    @app_commands.choices(owner_type=[
        app_commands.Choice(name="guild", value="guild"),
        app_commands.Choice(name="user", value="user"),
    ])
    async def test_grant(
        self,
        interaction: discord.Interaction,
        sku_id: str,
        owner_type: Optional[app_commands.Choice[str]] = None,
        target_id: Optional[str] = None,
    ):
        if not self._is_owner(interaction) or not self.settings.test_mode:
            await interaction.response.send_message(
                "Owner-only and requires TEST_MODE.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        otype = (owner_type.value if owner_type else "guild")
        owner_id = target_id.strip() if target_id else str(interaction.guild_id)
        try:
            owner_enum = (discord.EntitlementOwnerType.guild if otype == "guild"
                          else discord.EntitlementOwnerType.user)
            await self.bot.create_entitlement(
                discord.Object(id=int(sku_id)), discord.Object(id=int(owner_id)), owner_enum,
            )
            await interaction.followup.send(
                f"Created test entitlement for SKU `{sku_id}` -> {otype} `{owner_id}`. "
                "The gateway create event will record it shortly.", ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"Failed to create test entitlement: {e}", ephemeral=True)

    @test.command(name="revoke", description="[Owner] Delete a Discord test entitlement by id")
    @app_commands.describe(entitlement_id="The entitlement id to delete")
    async def test_revoke(self, interaction: discord.Interaction, entitlement_id: str):
        if not self._is_owner(interaction) or not self.settings.test_mode:
            await interaction.response.send_message(
                "Owner-only and requires TEST_MODE.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        eid = entitlement_id.strip()
        try:
            found = None
            async for ent in self.bot.entitlements(exclude_deleted=False, limit=None):
                if str(ent.id) == eid:
                    found = ent
                    break
            if found is None:
                await interaction.followup.send(f"No entitlement `{eid}` found.", ephemeral=True)
                return
            await found.delete()
            await interaction.followup.send(
                f"Deleted test entitlement `{eid}`. The delete event will update state shortly.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"Failed to delete entitlement: {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(PremiumCog(bot))
    logger.info("Premium cog loaded")
