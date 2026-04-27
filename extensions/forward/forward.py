import asyncio
import re
import time
import discord
from collections import Counter
from discord.ext import commands
from discord import app_commands, ui
from database import guild_manager
from database.utils import normalize_channel_id
import logging
import random
from datetime import datetime, timedelta, timezone

# Metric keys exposed via Forwarding.get_metrics(). Centralized so the admin
# panel and the cog agree on names without stringly-typed surprises.
METRIC_FORWARDED = "forwarded"
METRIC_RATE_LIMITED = "rate_limited"
METRIC_DAILY_LIMIT_HIT = "daily_limit_hit"
METRIC_PERM_FAILURE = "perm_failure"
METRIC_OVERSIZED_FALLBACK = "oversized_fallback"
METRIC_AUTO_DEACTIVATED = "auto_deactivated"

logger = logging.getLogger(__name__)


# Pre-compiled once at module load — runs on every message in matching guilds.
_EMBEDDABLE_URL_RE = re.compile(
    r'https?://(?:www\.)?(?:twitter|x|youtube|instagram|tiktok|reddit|github|twitch|spotify)\.(?:com|tv)/\S+'
    r'|https?://youtu\.be/\S+'
    r'|https?://\S+\.(?:jpg|jpeg|png|gif|webp|mp4|webm|mov)\b',
    re.IGNORECASE,
)

# Per-guild concurrency cap for the background forward dispatcher.
_GUILD_CONCURRENCY = 5
# Cooldown between repeat warnings about the same broken rule.
_PERM_WARN_COOLDOWN_SECONDS = 600
# Auto-deactivate a rule after this many consecutive misconfig failures
# (missing destination, missing send_messages). Resets on the next successful
# forward through the rule.
_AUTO_DEACTIVATE_THRESHOLD = 20


class _TokenBucket:
    """Per-guild token bucket. Capacity == burst; refills at rate/sec."""

    __slots__ = ("rate", "capacity", "tokens", "last")

    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last = time.monotonic()

    def take(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class ForwardOptionsView(ui.View):
    """
    A view that provides options for manually forwarding a message.
    It allows the user to select a destination channel before confirming
    the forward action. Messages are always forwarded using native style.
    This view is used by the `forward_message_context_menu` command.
    """
    def __init__(self, original_message: discord.Message, cog_instance):
        super().__init__(timeout=180)
        self.original_message = original_message
        self.cog_instance = cog_instance
        self.destination_channel = None

        channel_select = ui.ChannelSelect(
            placeholder="Select destination channel...",
            channel_types=[discord.ChannelType.text]
        )
        channel_select.callback = self.channel_select_callback
        self.add_item(channel_select)

        forward_button = ui.Button(label="Forward", style=discord.ButtonStyle.primary, row=1)
        forward_button.callback = self.forward_button_callback
        self.add_item(forward_button)

    async def channel_select_callback(self, interaction: discord.Interaction):
        self.destination_channel = interaction.data['values'][0]
        self.destination_channel = interaction.guild.get_channel(int(self.destination_channel))
        await interaction.response.defer()

    async def forward_button_callback(self, interaction: discord.Interaction):
        if not self.destination_channel:
            await interaction.response.send_message("Please select a destination channel.", ephemeral=True)
            return

        if not isinstance(self.destination_channel, discord.TextChannel):
            await interaction.response.send_message("Please select a valid text channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        default_formatting = {
            "add_prefix": None,
            "include_author": True,
            "add_suffix": None,
            "forward_embeds": True,
            "forward_attachments": True,
        }

        try:
            await self.cog_instance.forward_message(default_formatting, self.original_message, self.destination_channel)
            await interaction.followup.send(f"Message forwarded to {self.destination_channel.mention}!", ephemeral=True)

            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(view=self)
        except Exception as e:
            logger.error(f"Error forwarding message from view: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while forwarding the message.", ephemeral=True)


class Forwarding(commands.Cog):
    """
    Listens for messages and applies guild forwarding rules.
    """

    BRANDING_PROBABILITY = 0.20
    DAILY_WARN_COOLDOWN_MINUTES = 10

    def __init__(self, bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name='Forward Message',
            callback=self.forward_message_context_menu,
        )
        self.bot.tree.add_command(self.ctx_menu)

        # Per-guild token buckets for forward rate limiting.
        self._buckets: dict[int, _TokenBucket] = {}
        self._bucket_rate: float = 10.0  # default; resolved on first use from bot_settings
        self._bucket_resolved: bool = False
        self._branding_cooldown_minutes: int = 10  # default; resolved from bot_settings

        # Per-guild semaphore so a noisy guild can't queue unbounded dispatch tasks.
        self._guild_sems: dict[int, asyncio.Semaphore] = {}
        # Strong refs to in-flight dispatch tasks (otherwise GC may drop them).
        self._dispatch_tasks: set[asyncio.Task] = set()
        # rule_id -> monotonic timestamp of last "missing perms" log.
        self._perm_warn: dict[str, float] = {}
        # rule_id -> consecutive misconfig failure count for auto-deactivate.
        self._perm_fail: dict[str, int] = {}
        # Per-guild + global runtime counters. Reset on bot restart by design;
        # for long-term analytics, derive from message_logs / audit_logs.
        self._metrics: dict[int, Counter] = {}
        self._metrics_global: Counter = Counter()

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)
        # Cancel any background dispatch tasks so cog reload is clean.
        for task in list(self._dispatch_tasks):
            task.cancel()

    async def forward_message_context_menu(self, interaction: discord.Interaction, message: discord.Message):
        view = ForwardOptionsView(message, self)
        await interaction.response.send_message("Select forwarding options:", view=view, ephemeral=True)

    async def _ensure_runtime_config(self):
        """Load rate / branding cooldown from bot_settings once per process."""
        if self._bucket_resolved:
            return
        try:
            bot_settings = await guild_manager.db.get_collection(
                "discord_forwarding_bot", "bot_settings"
            ).find_one({"_id": "global_config"})
            if bot_settings:
                self._bucket_rate = float(bot_settings.get("forward_rate_per_second", 10))
                self._branding_cooldown_minutes = int(
                    bot_settings.get("branding_cooldown_minutes", 10)
                )
        except Exception as e:
            logger.warning(f"Failed to load runtime config, using defaults: {e}")
        self._bucket_resolved = True

    def _bucket_for(self, guild_id: int) -> _TokenBucket:
        b = self._buckets.get(guild_id)
        if b is None:
            b = _TokenBucket(rate=self._bucket_rate, capacity=max(self._bucket_rate, 1.0))
            self._buckets[guild_id] = b
        return b

    def _bump_metric(self, guild_id, key: str, n: int = 1) -> None:
        """Increment a per-guild and global counter. Cheap; safe to call hot."""
        try:
            gid = int(guild_id) if guild_id is not None else None
        except (TypeError, ValueError):
            gid = None
        if gid is not None:
            self._metrics.setdefault(gid, Counter())[key] += n
        self._metrics_global[key] += n

    def get_metrics(self, guild_id=None) -> dict:
        """
        Snapshot of forwarding metrics. Pass a guild_id (int or str) for that
        guild's counters; omit for the global aggregate. Returned dict always
        contains every metric key, defaulting to 0, so callers can format
        without `dict.get` boilerplate.
        """
        keys = (
            METRIC_FORWARDED, METRIC_RATE_LIMITED, METRIC_DAILY_LIMIT_HIT,
            METRIC_PERM_FAILURE, METRIC_OVERSIZED_FALLBACK, METRIC_AUTO_DEACTIVATED,
        )
        if guild_id is None:
            source = self._metrics_global
        else:
            try:
                gid = int(guild_id)
            except (TypeError, ValueError):
                return {k: 0 for k in keys}
            source = self._metrics.get(gid, Counter())
        return {k: int(source.get(k, 0)) for k in keys}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        logger.debug(
            f"on_message gid={message.guild.id} ch={message.channel.id} "
            f"author={message.author.id} mid={message.id}"
        )

        # Dispatch off the listener thread — the embed-wait below can sleep
        # several seconds, and the listener should never block on it.
        task = asyncio.create_task(self._dispatch(message))
        self._dispatch_tasks.add(task)
        task.add_done_callback(self._dispatch_tasks.discard)

    async def _dispatch(self, message: discord.Message):
        guild_id = message.guild.id
        sem = self._guild_sems.get(guild_id)
        if sem is None:
            sem = asyncio.Semaphore(_GUILD_CONCURRENCY)
            self._guild_sems[guild_id] = sem
        try:
            async with sem:
                await self._process(message)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error processing message in guild {guild_id}: {e}", exc_info=True)

    async def _process(self, message: discord.Message):
        await self._ensure_runtime_config()
        gid_str = str(message.guild.id)

        # Single cached fetch — settings cache (5-min TTL) covers repeats.
        guild_settings = await guild_manager.get_guild_settings(gid_str)
        if not guild_settings.get("features", {}).get("forwarding_enabled", False):
            logger.debug(f"[{gid_str}] forwarding_enabled=False; skip mid={message.id}")
            return

        rules = guild_settings.get("rules", [])
        if not rules:
            logger.debug(f"[{gid_str}] no rules configured; skip mid={message.id}")
            return

        matching_rules = [
            r for r in rules
            if r.get("is_active") and normalize_channel_id(r.get("source_channel_id")) == message.channel.id
        ]
        if not matching_rules:
            logger.debug(
                f"[{gid_str}] no rule matches ch={message.channel.id}; "
                f"rules={[(r.get('rule_id'), r.get('is_active'), r.get('source_channel_id')) for r in rules]}"
            )
            return

        logger.debug(
            f"[{gid_str}] {len(matching_rules)} rule(s) matched for ch={message.channel.id} mid={message.id}"
        )

        # Wait briefly for URL embeds to populate. Only matching rules pay this cost.
        if not message.embeds and self._contains_embeddable_url(message.content):
            for delay in (2, 3, 4):
                await asyncio.sleep(delay)
                try:
                    refreshed = await message.channel.fetch_message(message.id)
                except (discord.NotFound, discord.Forbidden):
                    return
                message = refreshed
                if message.embeds:
                    break

        # Rate limit per guild.
        if not self._bucket_for(message.guild.id).take():
            self._bump_metric(message.guild.id, METRIC_RATE_LIMITED)
            logger.debug(f"Rate-limited forward for guild {gid_str}")
            return

        guild_limits = await guild_manager.get_guild_limits(gid_str)
        daily_limit = guild_limits.get("daily_limit", 100)
        daily_count = await guild_manager.get_daily_message_count(gid_str)
        if daily_count >= daily_limit:
            self._bump_metric(message.guild.id, METRIC_DAILY_LIMIT_HIT)
            if guild_settings.get("features", {}).get("notify_on_error", True):
                last_warn = await guild_manager.get_runtime_state(gid_str, "daily_warn")
                now = datetime.now(timezone.utc)
                if not last_warn or (now - last_warn) >= timedelta(minutes=self.DAILY_WARN_COOLDOWN_MINUTES):
                    try:
                        await message.channel.send(
                            f"Daily message forwarding limit of {daily_limit} reached.", delete_after=60
                        )
                    except discord.HTTPException:
                        pass
                    await guild_manager.touch_runtime_state(gid_str, "daily_warn")
            return

        # Collect log entries and write them in a single insert_many at the
        # end so a source message that fans out to N rules costs one DB round
        # trip instead of N.
        log_batch: list[dict] = []
        for rule in matching_rules:
            if await self.process_rule(rule, message, guild_settings):
                log_batch.append({
                    "guild_id": gid_str,
                    "rule_id": rule.get("rule_id"),
                    "source_channel_id": str(message.channel.id),
                    "destination_channel_id": str(rule.get("destination_channel_id")),
                    "original_message_id": str(message.id),
                    "success": True,
                })
        if log_batch:
            self._bump_metric(message.guild.id, METRIC_FORWARDED, len(log_batch))
            await guild_manager.log_forwarded_messages(log_batch)

    async def _should_show_branding(self, guild_id: int) -> bool:
        """
        Cooldown via runtime_state (survives restart). Probability gate after cooldown.
        """
        gid_str = str(guild_id)
        last = await guild_manager.get_runtime_state(gid_str, "branding")
        if last:
            elapsed = datetime.now(timezone.utc) - last
            if elapsed < timedelta(minutes=self._branding_cooldown_minutes):
                return False
        return random.random() < self.BRANDING_PROBABILITY

    def _contains_embeddable_url(self, content: str) -> bool:
        if not content:
            return False
        return _EMBEDDABLE_URL_RE.search(content) is not None

    async def process_rule(self, rule: dict, message: discord.Message, guild_settings: dict) -> bool:
        settings = rule.get("settings", {})
        if not self.check_message_type(settings.get("message_types", {}), message):
            return False

        if not self.check_filters(settings.get("filters", {}), message, settings.get("advanced_options", {})):
            return False

        if not self.check_author_filters(settings.get("author_filters"), message):
            return False

        destination_channel_id = normalize_channel_id(rule.get("destination_channel_id"))
        rule_id = rule.get("rule_id", "?")

        # The matching_rules filter already pinned source==message.channel,
        # so a self-referential rule is the only loop we need to guard.
        if destination_channel_id == message.channel.id:
            logger.warning(
                f"Skipping rule {rule_id}: source and destination resolve to the same channel "
                f"({destination_channel_id})."
            )
            return False

        destination_channel = self.bot.get_channel(destination_channel_id)
        if not destination_channel:
            await self._record_rule_misconfig(
                rule, guild_settings,
                f"destination channel {destination_channel_id} not found",
            )
            return False

        # Permission gate — without this, every source message produces a
        # Forbidden + log line. One warning per rule per cooldown window.
        # `me is None` covers two distinct cross-guild failure modes: the
        # bot was kicked from the destination guild, or the destination's
        # member cache hasn't been populated yet.
        target_guild = destination_channel.guild
        me = target_guild.me if target_guild else None
        if me is None:
            await self._record_rule_misconfig(
                rule, guild_settings,
                f"bot is not a member of destination guild "
                f"{getattr(target_guild, 'id', '?')} (channel {destination_channel_id})",
            )
            return False
        if not destination_channel.permissions_for(me).send_messages:
            await self._record_rule_misconfig(
                rule, guild_settings,
                f"missing send_messages in destination {destination_channel_id}",
            )
            return False

        # Cross-guild opt-in gate. Same-guild rules bypass — destination guild
        # is the rule owner, so consent is implicit.
        if target_guild.id != message.guild.id:
            if not await guild_manager.is_inbound_allowed(
                str(target_guild.id), message.guild.id
            ):
                await self._record_rule_misconfig(
                    rule, guild_settings,
                    f"destination guild {target_guild.id} has not opted in to "
                    f"inbound forwards from guild {message.guild.id}",
                )
                return False

        await self.forward_message(settings.get("formatting", {}), message, destination_channel)
        # Successful forward — clear failure counter so a recovered rule
        # doesn't carry stale strikes from before the fix.
        self._perm_fail.pop(rule_id, None)

        # Lazy v3 stamp: legacy rules created before schema v3 lack
        # destination_guild_id. Backfill it now that we've resolved the
        # destination channel — fire-and-forget so the hot path stays clean.
        if not rule.get("destination_guild_id"):
            asyncio.create_task(
                self._stamp_destination_guild(rule_id, target_guild.id)
            )
        return True

    async def _stamp_destination_guild(self, rule_id: str, dest_guild_id: int) -> None:
        """Fire-and-forget update_rule for the lazy v3 destination_guild_id stamp."""
        try:
            await guild_manager.update_rule(rule_id, {"destination_guild_id": int(dest_guild_id)})
        except Exception as e:
            logger.debug(f"Lazy destination_guild_id stamp failed for rule {rule_id}: {e}")

    async def _record_rule_misconfig(self, rule: dict, guild_settings: dict, reason: str) -> None:
        """
        Log a misconfig (rate-limited per rule) and bump the consecutive-failure
        counter. Once the counter hits _AUTO_DEACTIVATE_THRESHOLD, soft-delete
        the rule and notify the guild's master log channel.
        """
        rule_id = rule.get("rule_id", "?")
        self._bump_metric(guild_settings.get("_id"), METRIC_PERM_FAILURE)
        now = time.monotonic()
        last = self._perm_warn.get(rule_id, 0.0)
        if now - last >= _PERM_WARN_COOLDOWN_SECONDS:
            self._perm_warn[rule_id] = now
            logger.warning(f"Rule {rule_id}: {reason}")

        count = self._perm_fail.get(rule_id, 0) + 1
        self._perm_fail[rule_id] = count
        if count >= _AUTO_DEACTIVATE_THRESHOLD:
            await self._auto_deactivate_rule(rule, guild_settings, reason)
            self._perm_fail.pop(rule_id, None)

    async def _auto_deactivate_rule(self, rule: dict, guild_settings: dict, reason: str) -> None:
        """Soft-delete a chronically-broken rule and notify the guild's log channel."""
        rule_id = rule.get("rule_id", "?")
        rule_name = rule.get("rule_name") or rule_id
        try:
            ok = await guild_manager.delete_rule(rule_id)
        except Exception as e:
            logger.error(f"Auto-deactivate failed for rule {rule_id}: {e}", exc_info=True)
            return
        if not ok:
            logger.warning(f"Auto-deactivate of rule {rule_id} reported no modification")
            return
        self._bump_metric(guild_settings.get("_id"), METRIC_AUTO_DEACTIVATED)
        logger.warning(
            f"Rule {rule_id} auto-deactivated after "
            f"{_AUTO_DEACTIVATE_THRESHOLD} consecutive failures: {reason}"
        )

        log_channel_id = guild_settings.get("master_log_channel_id")
        if not log_channel_id:
            return
        channel = self.bot.get_channel(int(log_channel_id))
        if channel is None:
            return
        try:
            embed = discord.Embed(
                title="Forwarding rule auto-deactivated",
                description=(
                    f"Rule **{rule_name}** (`{rule_id}`) was disabled after "
                    f"{_AUTO_DEACTIVATE_THRESHOLD} consecutive failures.\n\n"
                    f"**Reason:** {reason}\n\n"
                    "Re-enable it from `/admin` once the destination channel "
                    "or permissions are fixed."
                ),
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            )
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            logger.warning(f"Failed to post auto-deactivate notice to log channel: {e}")

    def check_message_type(self, message_types: dict, message: discord.Message) -> bool:
        if message.content and message_types.get("text", False):
            return True

        if message.attachments:
            if message_types.get("media", False):
                return True
            if message_types.get("files", False):
                return True

        if message.embeds:
            if message_types.get("embeds", False):
                return True
            if message_types.get("media", False):
                for embed in message.embeds:
                    if embed.image or embed.video or embed.thumbnail:
                        return True

        if message.stickers and message_types.get("stickers", False):
            return True

        if message.content and "http" in message.content and message_types.get("links", False):
            return True

        if not message.content:
            return True

        return False

    def check_filters(self, filters: dict, message: discord.Message, advanced: dict) -> bool:
        content = message.content
        case_sensitive = advanced.get("case_sensitive", False)
        whole_word = advanced.get("whole_word_only", False)

        if not case_sensitive:
            content = content.lower()

        min_len = filters.get("min_length", 0)
        max_len = filters.get("max_length", 2000)
        if not (min_len <= len(message.content) <= max_len):
            return False

        # Defensive cap so a runaway rule (50+ keywords, multi-KB strings) can't
        # turn message handling into O(n*m) over the firehose.
        MAX_KEYWORDS = 50
        MAX_KW_LEN = 100
        require_keywords = [str(k)[:MAX_KW_LEN] for k in filters.get("require_keywords", [])][:MAX_KEYWORDS]
        block_keywords = [str(k)[:MAX_KW_LEN] for k in filters.get("block_keywords", [])][:MAX_KEYWORDS]

        if not case_sensitive:
            require_keywords = [k.lower() for k in require_keywords]
            block_keywords = [k.lower() for k in block_keywords]

        if whole_word:
            words = content.split()
            if block_keywords and any(word in block_keywords for word in words):
                return False
            if require_keywords and not any(word in require_keywords for word in words):
                return False
        else:
            if block_keywords and any(keyword in content for keyword in block_keywords):
                return False
            if require_keywords and not any(keyword in content for keyword in require_keywords):
                return False

        return True

    def check_author_filters(self, filters, message: discord.Message) -> bool:
        """
        Apply per-rule author allow/deny lists.

        Semantics:
        - Deny lists (users + roles) reject outright. A match in either denies.
        - Allow lists are a combined gate: if either allow_user_ids or
          allow_role_ids is non-empty, the author must match at least one
          across both lists. If both allow lists are empty, no allow gate.
        - Missing or non-dict filters mean "no filtering" (returns True).
        """
        if not isinstance(filters, dict) or not filters:
            return True

        author_id = message.author.id
        member = message.author if isinstance(message.author, discord.Member) else None
        role_ids = {r.id for r in member.roles} if member else set()

        def _ints(seq) -> set:
            out = set()
            for x in seq or ():
                try:
                    out.add(int(x))
                except (TypeError, ValueError):
                    continue
            return out

        if author_id in _ints(filters.get("deny_user_ids")):
            return False
        if _ints(filters.get("deny_role_ids")) & role_ids:
            return False

        allow_users = _ints(filters.get("allow_user_ids"))
        allow_roles = _ints(filters.get("allow_role_ids"))
        if allow_users or allow_roles:
            if author_id not in allow_users and not (allow_roles & role_ids):
                return False

        return True

    async def forward_as_native_style(self, formatting: dict, message: discord.Message,
                                      destination: discord.TextChannel):
        """
        Quoted-message style forwarding. Discord regenerates URL embeds in the
        quoted text, preserving video previews. Per-attachment failure reasons
        are surfaced to the user.
        """
        quote_lines = []

        if formatting.get("include_author", True):
            quote_lines.append(f"> -# **{message.author.display_name}** - ([original post]({message.jump_url}))")

        if message.content:
            for line in message.content.split('\n'):
                quote_lines.append(f"> {line}")

        quoted_content = '\n'.join(quote_lines)

        files_to_send = []
        # Detailed reasons per omitted attachment, surfaced to the destination.
        attachment_issues: list[str] = []

        if formatting.get("forward_attachments", True) and message.attachments:
            max_size = formatting.get("max_attachment_size", 25) * 1024 * 1024
            # Destination dictates the upload ceiling — Discord enforces it
            # regardless of source premium. `filesize_limit` already accounts
            # for boost tier, so future Discord tier changes pick up cleanly.
            max_total_size = destination.guild.filesize_limit
            allowed_types = formatting.get("allowed_attachment_types")

            candidates = []
            for attachment in message.attachments:
                if attachment.size > max_size:
                    attachment_issues.append(
                        f"`{attachment.filename}` too large ({attachment.size // 1024} KB > {max_size // 1024} KB)"
                    )
                    continue
                if allowed_types and not any(
                    attachment.filename.lower().endswith(ext) for ext in allowed_types
                ):
                    attachment_issues.append(f"`{attachment.filename}` filetype not allowed")
                    continue
                candidates.append(attachment)

            running_total = 0
            for attachment in candidates:
                if running_total + attachment.size > max_total_size:
                    attachment_issues.append(
                        f"`{attachment.filename}` skipped: total attachment size cap "
                        f"({max_total_size // (1024 * 1024)} MB) reached"
                    )
                    continue

                try:
                    f = await attachment.to_file(spoiler=attachment.is_spoiler())
                    files_to_send.append(f)
                    running_total += attachment.size
                except discord.HTTPException as e:
                    attachment_issues.append(
                        f"`{attachment.filename}` download failed (HTTP {getattr(e, 'status', '?')})"
                    )
                except (OSError, asyncio.TimeoutError) as e:
                    attachment_issues.append(
                        f"`{attachment.filename}` download failed ({type(e).__name__})"
                    )
                except Exception as e:
                    # Unexpected — log full trace but still surface a generic line so
                    # the user sees why the attachment didn't make it.
                    logger.warning(
                        f"Unexpected error downloading {attachment.filename}: {e}",
                        exc_info=True,
                    )
                    attachment_issues.append(
                        f"`{attachment.filename}` download failed ({type(e).__name__})"
                    )

        if attachment_issues:
            # Cap the listed reasons so we don't blow Discord's 2000-char limit.
            shown = attachment_issues[:5]
            extra = len(attachment_issues) - len(shown)
            issue_text = "\n".join(f"-# • {line}" for line in shown)
            if extra > 0:
                issue_text += f"\n-# • ...and {extra} more"
            quoted_content += f"\n-# **Some attachments not forwarded:**\n{issue_text}"

        # Branding (free SOURCE guilds only, with cooldown). A premium source
        # forwards ad-free regardless of where the destination lives — the
        # rule owner pays for the suppression, not the recipient guild.
        source_gid = message.guild.id if message.guild else destination.guild.id
        is_premium = await guild_manager.is_premium_guild(str(source_gid))
        if not is_premium and await self._should_show_branding(source_gid):
            server_invite_link = "https://discord.gg/NaK74Wf7vE"
            quoted_content += f"\n-# Powered by Empire of Shadows\n-# Gaming Community • <{server_invite_link}>"
            await guild_manager.touch_runtime_state(str(source_gid), "branding")

        try:
            await self._send_with_enhanced_handling(
                destination=destination,
                message=message,
                content=quoted_content,
                files=files_to_send,
                formatting=formatting
            )
        finally:
            for file in files_to_send:
                try:
                    if hasattr(file, 'close'):
                        file.close()
                except Exception as cleanup_error:
                    logger.debug(f"Error closing file handle: {cleanup_error}")

    async def forward_message(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        await self.forward_as_native_style(formatting, message, destination)

    async def _send_with_enhanced_handling(self, destination: discord.TextChannel, message: discord.Message,
                                           **send_kwargs):
        formatting = send_kwargs.pop('formatting', {})
        forward_embeds = formatting.get("forward_embeds", True)

        if message.channel.id == destination.id:
            send_kwargs["reference"] = message
            send_kwargs["mention_author"] = formatting.get("mention_author", False)

        # Metrics key off the source guild — that's the rule owner. A premium
        # source guild forwarding into a free destination still attributes
        # oversized fallbacks to source.
        source_gid = message.guild.id if message.guild else destination.guild.id

        try:
            await destination.send(**send_kwargs)
        except discord.HTTPException as e:
            if e.code == 40005:
                self._bump_metric(source_gid, METRIC_OVERSIZED_FALLBACK)
                logger.warning(f"Payload too large for message {message.id}. Retrying without attachments.")
                send_kwargs.pop('files', None)

                content = send_kwargs.get('content', '')
                if "attachments were not forwarded" not in content.lower():
                    content += "\n\n*(Attachments were not forwarded due to size limits.)*"
                send_kwargs['content'] = content

                try:
                    await destination.send(**send_kwargs)
                except discord.HTTPException as e2:
                    logger.error(f"Failed to send forwarded message {message.id} after attachment removal: {e2}")
                    await self._send_minimal_version(destination, message, formatting)

            elif "message content too long" in str(e).lower():
                self._bump_metric(source_gid, METRIC_OVERSIZED_FALLBACK)
                logger.error(f"Failed to send forwarded message: {e}")
                await self._handle_oversized_message(destination, message, send_kwargs, formatting)

            else:
                logger.error(f"Failed to send forwarded message: {e}")
                send_kwargs.pop('reference', None)
                send_kwargs.pop('files', None)
                fallback_embeds = send_kwargs.get('embeds', [])[:1] if forward_embeds else []
                await destination.send(
                    content="📨 *Message forwarded (some content omitted due to size limits)*",
                    embeds=fallback_embeds
                )

    async def _handle_oversized_message(self, destination: discord.TextChannel, message: discord.Message,
                                        send_kwargs: dict, formatting: dict):
        content = send_kwargs.get('content', '')
        embeds = send_kwargs.get('embeds', []) if formatting.get("forward_embeds", True) else []
        files = send_kwargs.get('files', [])

        if content and len(content) > 2000:
            await self._send_chunked_content(destination, message, content, embeds, files, formatting)
            return

        if embeds and len(embeds) > 10:
            await self._send_reduced_embeds(destination, message, content, embeds, files, formatting)
            return

        if files and sum(f.size for f in files) > 25 * 1024 * 1024:
            await self._send_compressed_files(destination, message, content, embeds, files, formatting)
            return

        await self._send_minimal_version(destination, message, formatting)

    async def _send_chunked_content(self, destination: discord.TextChannel, message: discord.Message,
                                    content: str, embeds: list, files: list, formatting: dict):
        chunks = self._split_content(content, max_length=1900)

        first_chunk = chunks[0]
        if len(chunks) > 1:
            first_chunk += f"\n\n*(Message continued... {len(chunks)} parts total)*"

        try:
            first_message = await destination.send(
                content=first_chunk,
                embeds=embeds[:1] if embeds else [],
                files=files[:1] if files else []
            )
        except discord.HTTPException:
            await self._send_ultra_minimal(destination, message, formatting)
            return

        for i, chunk in enumerate(chunks[1:], 2):
            chunk_content = f"**Part {i}/{len(chunks)}:**\n{chunk}"
            if i == len(chunks):
                remaining_embeds = embeds[1:][:9]
                remaining_files = files[1:][:9]

                try:
                    await first_message.reply(
                        content=chunk_content,
                        embeds=remaining_embeds,
                        files=remaining_files,
                        mention_author=False
                    )
                except discord.HTTPException:
                    await first_message.reply(
                        content=chunk_content + "\n\n*(Some files omitted due to size limits)*",
                        embeds=remaining_embeds,
                        mention_author=False
                    )
            else:
                await first_message.reply(
                    content=chunk_content,
                    mention_author=False
                )

    async def _send_reduced_embeds(self, destination: discord.TextChannel, message: discord.Message,
                                   content: str, embeds: list, files: list, formatting: dict):
        omitted_count = len(embeds) - 10
        summary_text = f"\n\n*📊 {omitted_count} additional embeds omitted*"

        try:
            await destination.send(
                content=content + summary_text,
                embeds=embeds[:10],
                files=files[:10]
            )
        except discord.HTTPException:
            await destination.send(
                content=content + summary_text,
                embeds=embeds[:5],
                files=files[:3]
            )

    async def _send_compressed_files(self, destination: discord.TextChannel, message: discord.Message,
                                     content: str, embeds: list, files: list, formatting: dict):
        total_size = sum(f.size for f in files)
        size_mb = total_size / (1024 * 1024)

        file_summary = []
        for file in files:
            file_mb = file.size / (1024 * 1024)
            file_summary.append(f"• {file.filename} ({file_mb:.1f}MB)")

        file_list = "\n".join(file_summary[:5])
        if len(files) > 5:
            file_list += f"\n• ... and {len(files) - 5} more files"

        warning_msg = (
            f"\n\n⚠️ **Files too large to forward ({size_mb:.1f}MB total):**\n"
            f"{file_list}"
        )

        await destination.send(
            content=content + warning_msg,
            embeds=embeds[:10] if formatting.get("forward_embeds", True) else []
        )

    async def _send_minimal_version(self, destination: discord.TextChannel, message: discord.Message,
                                    formatting: dict):
        author_info = f"**From {message.author.display_name}**"
        content_preview = message.content[:500] + "..." if len(message.content) > 500 else message.content

        stats = []
        if message.attachments:
            stats.append(f"{len(message.attachments)} files")
        if message.embeds:
            stats.append(f"{len(message.embeds)} embeds")
        stats_text = f" (*{', '.join(stats)}*)" if stats else ""

        minimal_content = (
            f"{author_info}{stats_text}\n"
            f"{content_preview}\n"
            f"🔗 [View Original]({message.jump_url})"
        )

        await destination.send(content=minimal_content)

    async def _send_ultra_minimal(self, destination: discord.TextChannel, message: discord.Message,
                                  formatting: dict):
        ultra_minimal = (
            f"📨 **Message from {message.author.display_name}**\n"
            f"Content: {len(message.content)} chars"
            f"{f' | {len(message.attachments)} files' if message.attachments else ''}"
            f"{f' | {len(message.embeds)} embeds' if message.embeds else ''}\n"
            f"🔗 [View Original]({message.jump_url})"
        )

        await destination.send(content=ultra_minimal)

    def _split_content(self, content: str, max_length: int = 1900) -> list:
        if len(content) <= max_length:
            return [content]

        chunks = []
        current_chunk = ""

        paragraphs = content.split('\n\n')

        for paragraph in paragraphs:
            if current_chunk and len(current_chunk) + len(paragraph) + 2 > max_length:
                chunks.append(current_chunk.strip())
                current_chunk = ""

            if len(paragraph) > max_length:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""

                sentences = paragraph.replace('. ', '.\n').split('\n')
                for sentence in sentences:
                    if len(sentence) > max_length:
                        words = sentence.split(' ')
                        for word in words:
                            # A single word longer than max_length must be hard-sliced;
                            # otherwise the chunk would exceed the cap and Discord rejects it.
                            if len(word) > max_length:
                                if current_chunk.strip():
                                    chunks.append(current_chunk.strip())
                                current_chunk = ""
                                for i in range(0, len(word), max_length):
                                    piece = word[i:i + max_length]
                                    if i + max_length < len(word):
                                        chunks.append(piece)
                                    else:
                                        current_chunk = piece + " "
                                continue
                            if len(current_chunk) + len(word) + 1 > max_length:
                                chunks.append(current_chunk.strip())
                                current_chunk = ""
                            current_chunk += word + " "
                    else:
                        if len(current_chunk) + len(sentence) + 1 > max_length:
                            chunks.append(current_chunk.strip())
                            current_chunk = ""
                        current_chunk += sentence + " "
            else:
                current_chunk += paragraph + "\n\n"

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks


async def setup(bot):
    await bot.add_cog(Forwarding(bot))
    logger.info("Forwarding cog loaded.")
