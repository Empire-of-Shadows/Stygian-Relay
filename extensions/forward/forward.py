import asyncio
import time
import discord
from discord.ext import commands
from discord import app_commands, ui
from database import guild_manager
from database.utils import normalize_channel_id
import logging
import random
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


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
        self.forward_style = "native"
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
            "forward_style": self.forward_style
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

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Wait briefly for URL embeds to populate before processing.
        if self._contains_embeddable_url(message.content) and not message.embeds:
            for attempt in range(3):
                await asyncio.sleep(2 + attempt)
                try:
                    message = await message.channel.fetch_message(message.id)
                    if message.embeds:
                        break
                except (discord.NotFound, discord.Forbidden):
                    return

        try:
            await self._ensure_runtime_config()
            gid_str = str(message.guild.id)

            # Single cached fetch — settings cache (5-min TTL) covers repeats.
            guild_settings = await guild_manager.get_guild_settings(gid_str)

            if not guild_settings.get("features", {}).get("forwarding_enabled", False):
                return

            rules = guild_settings.get("rules", [])
            if not rules:
                return

            matching_rules = [
                r for r in rules
                if r.get("is_active") and normalize_channel_id(r.get("source_channel_id")) == message.channel.id
            ]
            if not matching_rules:
                return

            # Rate limit per guild.
            if not self._bucket_for(message.guild.id).take():
                logger.debug(f"Rate-limited forward for guild {gid_str}")
                return

            guild_limits = await guild_manager.get_guild_limits(gid_str)
            daily_limit = guild_limits.get("daily_limit", 100)
            daily_count = await guild_manager.get_daily_message_count(gid_str)
            if daily_count >= daily_limit:
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

            for rule in matching_rules:
                if await self.process_rule(rule, message, guild_settings):
                    log_data = {
                        "guild_id": gid_str,
                        "rule_id": rule.get("rule_id"),
                        "source_channel_id": str(message.channel.id),
                        "destination_channel_id": str(rule.get("destination_channel_id")),
                        "original_message_id": str(message.id),
                        "success": True
                    }
                    await guild_manager.log_forwarded_message(log_data)

        except Exception as e:
            logger.error(f"Error in on_message for guild {message.guild.id}: {e}", exc_info=True)

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
        import re
        embeddable_patterns = [
            r'https?://(?:www\.)?twitter\.com/\S+',
            r'https?://(?:www\.)?x\.com/\S+',
            r'https?://(?:www\.)?youtube\.com/watch\?\S+',
            r'https?://youtu\.be/\S+',
            r'https?://(?:www\.)?instagram\.com/\S+',
            r'https?://(?:www\.)?tiktok\.com/\S+',
            r'https?://(?:www\.)?reddit\.com/\S+',
            r'https?://(?:www\.)?github\.com/\S+',
            r'https?://(?:www\.)?twitch\.tv/\S+',
            r'https?://(?:www\.)?spotify\.com/\S+',
            r'https?://\S+\.(jpg|jpeg|png|gif|webp|mp4|webm|mov)\b'
        ]
        for pattern in embeddable_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

    async def process_rule(self, rule: dict, message: discord.Message, guild_settings: dict) -> bool:
        settings = rule.get("settings", {})
        if not self.check_message_type(settings.get("message_types", {}), message):
            return False

        if not self.check_filters(settings.get("filters", {}), message, settings.get("advanced_options", {})):
            return False

        destination_channel_id = normalize_channel_id(rule.get("destination_channel_id"))
        source_channel_id = normalize_channel_id(rule.get("source_channel_id"))

        if destination_channel_id == source_channel_id or destination_channel_id == message.channel.id:
            logger.warning(
                f"Skipping rule {rule.get('rule_id')}: source and destination resolve to the same channel "
                f"({destination_channel_id})."
            )
            return False

        destination_channel = self.bot.get_channel(destination_channel_id)
        if not destination_channel:
            logger.warning(f"Destination channel {destination_channel_id} not found for rule {rule.get('rule_id')}")
            return False

        await self.forward_message(settings.get("formatting", {}), message, destination_channel)
        return True

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
            if destination.guild.premium_tier >= 2:
                max_total_size = 50 * 1024 * 1024
            else:
                max_total_size = 10 * 1024 * 1024
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

        if attachment_issues:
            # Cap the listed reasons so we don't blow Discord's 2000-char limit.
            shown = attachment_issues[:5]
            extra = len(attachment_issues) - len(shown)
            issue_text = "\n".join(f"-# • {line}" for line in shown)
            if extra > 0:
                issue_text += f"\n-# • ...and {extra} more"
            quoted_content += f"\n-# **Some attachments not forwarded:**\n{issue_text}"

        # Branding (free guilds only, with cooldown).
        is_premium = await guild_manager.is_premium_guild(str(destination.guild.id))
        if not is_premium and await self._should_show_branding(destination.guild.id):
            server_invite_link = "https://discord.gg/NaK74Wf7vE"
            quoted_content += f"\n-# Powered by Empire of Shadows\n-# Gaming Community • <{server_invite_link}>"
            await guild_manager.touch_runtime_state(str(destination.guild.id), "branding")

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

    async def _parse_template_variables(self, text: str, message: discord.Message) -> str:
        base_variables = {
            '{author}': message.author.display_name,
            '{author_mention}': message.author.mention,
            '{author_id}': str(message.author.id),
            '{channel}': message.channel.name,
            '{channel_mention}': message.channel.mention,
            '{guild}': message.guild.name if message.guild else 'DM',
            '{timestamp}': message.created_at.strftime('%Y-%m-%d %H:%M'),
            '{message_id}': str(message.id),
            '{message_url}': message.jump_url,
        }

        if message.guild:
            base_variables['{guild_id}'] = str(message.guild.id)
            base_variables['{guild_icon}'] = str(message.guild.icon.url) if message.guild.icon else ''

        if message.attachments:
            base_variables['{attachment_count}'] = str(len(message.attachments))
            base_variables['{first_attachment}'] = message.attachments[0].filename

        if message.embeds:
            base_variables['{embed_count}'] = str(len(message.embeds))

        for var, replacement in base_variables.items():
            text = text.replace(var, replacement)

        return text

    def _get_embed_color(self, formatting: dict, message: discord.Message) -> discord.Color:
        if custom_color := formatting.get("embed_color"):
            if isinstance(custom_color, str):
                try:
                    return discord.Color.from_str(custom_color)
                except ValueError:
                    pass
            elif isinstance(custom_color, int):
                return discord.Color(custom_color)

        if message.guild and message.author in message.guild.members:
            member = message.guild.get_member(message.author.id)
            if member and member.color != discord.Color.default():
                return member.color

        if message.attachments:
            has_images = any(att.content_type and att.content_type.startswith('image/')
                             for att in message.attachments)
            return discord.Color.green() if has_images else discord.Color.blue()
        elif message.embeds:
            return discord.Color.purple()
        elif len(message.content) > 200:
            return discord.Color.orange()
        else:
            return discord.Color.blurple()

    def _should_filter_embed(self, embed: discord.Embed, filter_rules: list) -> bool:
        if not filter_rules:
            return False

        for rule in filter_rules:
            rule = rule.lower()

            if rule == "empty" and not any([
                embed.title, embed.description, embed.fields,
                embed.image, embed.thumbnail, embed.footer
            ]):
                return True

            if rule == "discord" and embed.author and "discord" in embed.author.name.lower():
                return True

            if rule == "ad" and any(keyword in (embed.title or "").lower()
                                    for keyword in ['sponsor', 'advertisement', 'promoted']):
                return True

        return False

    def _sanitize_embed(self, embed: discord.Embed) -> discord.Embed:
        safe_embed = discord.Embed(
            title=embed.title[:256] if embed.title else None,
            description=embed.description[:4096] if embed.description else None,
            color=embed.color,
            url=embed.url,
            timestamp=embed.timestamp
        )

        if embed.author:
            safe_embed.set_author(
                name=embed.author.name[:256] if embed.author.name else None,
                icon_url=embed.author.icon_url,
                url=embed.author.url
            )

        if embed.footer:
            safe_embed.set_footer(
                text=embed.footer.text[:2048] if embed.footer.text else None,
                icon_url=embed.footer.icon_url
            )

        if embed.image:
            safe_embed.set_image(url=embed.image.url)

        if embed.thumbnail:
            safe_embed.set_thumbnail(url=embed.thumbnail.url)

        for field in embed.fields:
            safe_embed.add_field(
                name=field.name[:256],
                value=field.value[:1024],
                inline=field.inline
            )

        return safe_embed

    async def _send_with_enhanced_handling(self, destination: discord.TextChannel, message: discord.Message,
                                           **send_kwargs):
        formatting = send_kwargs.pop('formatting', {})
        forward_embeds = formatting.get("forward_embeds", True)

        if message.channel.id == destination.id:
            send_kwargs["reference"] = message
            send_kwargs["mention_author"] = formatting.get("mention_author", False)

        try:
            await destination.send(**send_kwargs)
        except discord.HTTPException as e:
            if e.code == 40005:
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
