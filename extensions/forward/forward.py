import asyncio
import discord
from discord.ext import commands
from discord import app_commands, ui
from database import guild_manager
import logging
import random
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def normalize_channel_id(channel_id):
    """
    Normalize channel ID from various formats (int, str, BSON) to int.
    Handles MongoDB BSON format: {"$numberLong": "123456"}
    """
    if isinstance(channel_id, dict) and "$numberLong" in channel_id:
        return int(channel_id["$numberLong"])
    return int(channel_id) if channel_id else None


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
        """
        Callback for the channel select menu.
        This method is called when the user selects a destination channel.
        """
        self.destination_channel = interaction.data['values'][0]
        # The value is a channel ID; we need the actual channel object.
        self.destination_channel = interaction.guild.get_channel(int(self.destination_channel))
        await interaction.response.defer()

    async def forward_button_callback(self, interaction: discord.Interaction):
        """
        Callback for the forward button.
        This method is called when the user clicks the forward button.
        """
        if not self.destination_channel:
            await interaction.response.send_message("Please select a destination channel.", ephemeral=True)
            return

        if not isinstance(self.destination_channel, discord.TextChannel):
            await interaction.response.send_message("Please select a valid text channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Use default formatting for manual forwards, only changing the style.
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

            # Disable the view after successful forwarding.
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(view=self)
        except Exception as e:
            logger.error(f"Error forwarding message from view: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while forwarding the message.", ephemeral=True)

class Forwarding(commands.Cog):
    """
    Cog for handling message forwarding based on guild-specific rules.
    This cog is responsible for listening for messages, checking them against
    forwarding rules, and forwarding them to the appropriate channels.
    It also provides a context menu command for manually forwarding messages.
    """

    # Branding configuration
    BRANDING_PROBABILITY = 0.20  # 20% chance to show branding
    BRANDING_COOLDOWN_MINUTES = 10  # Minimum 10 minutes between branding messages

    def __init__(self, bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name='Forward Message',
            callback=self.forward_message_context_menu,
        )
        self.bot.tree.add_command(self.ctx_menu)

        # Track last branding time per guild to prevent back-to-back branding
        # Format: {guild_id: datetime}
        self._last_branding_time = {}

    async def cog_unload(self):
        """
        Called when the cog is unloaded.
        This method removes the context menu command from the bot's tree.
        """
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    async def forward_message_context_menu(self, interaction: discord.Interaction, message: discord.Message):
        """
        Context menu command to manually forward a single message.
        This command displays a view with options for forwarding the message.
        """
        view = ForwardOptionsView(message, self)
        await interaction.response.send_message("Select forwarding options:", view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Listens for new messages and processes them against active forwarding rules.
        This is the entry point for all automatic message forwarding.
        """
        # Ignore messages from bots and DMs.
        if message.author.bot or not message.guild:
            logger.debug(
                "Ignoring message %s from %s (id=%s, bot=%s, guild=%s, channel=%s)",
                message.id,
                str(message.author),
                message.author.id,
                message.author.bot,
                message.guild.id if message.guild else "DM",
                message.channel.id if message.channel else "Unknown",
            )
            return

        # Enhanced URL embed detection and waiting
        if self._contains_embeddable_url(message.content) and not message.embeds:
            # Wait longer for embeds to load, with multiple checks
            for attempt in range(3):
                await asyncio.sleep(2 + attempt)  # 2s, 3s, 4s
                try:
                    message = await message.channel.fetch_message(message.id)
                    if message.embeds:
                        break
                except (discord.NotFound, discord.Forbidden):
                    return

        try:
            # Retrieve guild-specific settings from the database.
            guild_settings = await guild_manager.get_guild_settings(str(message.guild.id))

            # Check if the forwarding feature is enabled for this guild.
            if not guild_settings.get("features", {}).get("forwarding_enabled", False):
                return

            rules = guild_settings.get("rules", [])
            if not rules:
                return

            # Iterate through all rules for the guild.
            for rule in rules:
                # A rule is processed only if it's active and for the correct source channel.
                source_channel_id = normalize_channel_id(rule.get("source_channel_id"))
                if not rule.get("is_active") or source_channel_id != message.channel.id:
                    continue

                # Enforce the daily message forwarding limit for the guild (premium-aware).
                guild_limits = await guild_manager.get_guild_limits(str(message.guild.id))
                daily_limit = guild_limits.get("daily_limit", 100)
                daily_count = await guild_manager.get_daily_message_count(str(message.guild.id))
                if daily_count >= daily_limit:
                    if guild_settings.get("features", {}).get("notify_on_error", True):
                        await message.channel.send(f"Daily message forwarding limit of {daily_limit} reached.", delete_after=60)
                    break  # Stop processing all rules since the guild-wide daily limit is reached.

                # If the rule matches, process it and log the result.
                if await self.process_rule(rule, message, guild_settings):
                    log_data = {
                        "guild_id": str(message.guild.id),
                        "rule_id": rule.get("rule_id"),
                        "source_channel_id": str(message.channel.id),
                        "destination_channel_id": str(rule.get("destination_channel_id")),
                        "original_message_id": str(message.id),
                        "success": True
                    }
                    await guild_manager.log_forwarded_message(log_data)

        except Exception as e:
            logger.error(f"Error in on_message for guild {message.guild.id}: {e}", exc_info=True)

    def _should_show_branding(self, guild_id: int) -> bool:
        """
        Determines if branding should be shown for this message.

        Uses a combination of:
        1. Random probability (BRANDING_PROBABILITY chance)
        2. Cooldown period to prevent back-to-back branding

        Args:
            guild_id: The guild ID to check

        Returns:
            bool: True if branding should be shown, False otherwise
        """
        # Check if we're still in cooldown period
        last_branding = self._last_branding_time.get(guild_id)
        if last_branding:
            time_since_last = datetime.now(timezone.utc) - last_branding
            if time_since_last < timedelta(minutes=self.BRANDING_COOLDOWN_MINUTES):
                # Still in cooldown, don't show branding
                return False

        # Random chance to show branding
        return random.random() < self.BRANDING_PROBABILITY

    def _contains_embeddable_url(self, content: str) -> bool:
        """
        Check if content contains URLs that typically generate embeds.
        """
        import re

        # Common platforms that generate embeds
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
        """
        Process a single rule against a message.
        This method checks the message type and filters, and if they match,
        it forwards the message to the destination channel.
        Returns True if forwarded, False otherwise.
        """
        settings = rule.get("settings", {})
        if not self.check_message_type(settings.get("message_types", {}), message):
            return False

        if not self.check_filters(settings.get("filters", {}), message, settings.get("advanced_options", {})):
            return False

        destination_channel_id = normalize_channel_id(rule.get("destination_channel_id"))
        destination_channel = self.bot.get_channel(destination_channel_id)

        if not destination_channel:
            logger.warning(f"Destination channel {destination_channel_id} not found for rule {rule.get('rule_id')}")
            return False

        await self.forward_message(settings.get("formatting", {}), message, destination_channel)
        return True

    def check_message_type(self, message_types: dict, message: discord.Message) -> bool:
        """
        Check if the message type is allowed by the rule.
        This method checks the message content, attachments, embeds, and stickers
        to determine if the message should be forwarded.
        """
        # Handle text content
        if message.content and message_types.get("text", False):
            return True

        # Handle attachments (images, videos, files)
        if message.attachments:
            if message_types.get("media", False):
                return True
            if message_types.get("files", False):
                return True

        # Handle embeds (including URL previews, videos, etc.)
        if message.embeds:
            if message_types.get("embeds", False):
                return True
            # Also check if embeds contain media content
            if message_types.get("media", False):
                for embed in message.embeds:
                    if embed.image or embed.video or embed.thumbnail:
                        return True

        # Handle stickers
        if message.stickers and message_types.get("stickers", False):
            return True

        # Handle links in content
        if message.content and "http" in message.content and message_types.get("links", False):
            return True

        # Allow messages without text content if they have other allowed content types
        if not message.content:
            return True

        return False


    def check_filters(self, filters: dict, message: discord.Message, advanced: dict) -> bool:
        """
        Check keyword and length filters.
        This method checks the message content against the filters defined in the rule.
        """
        content = message.content
        case_sensitive = advanced.get("case_sensitive", False)
        whole_word = advanced.get("whole_word_only", False)

        if not case_sensitive:
            content = content.lower()

        min_len = filters.get("min_length", 0)
        max_len = filters.get("max_length", 2000)
        if not (min_len <= len(message.content) <= max_len):
            return False

        require_keywords = filters.get("require_keywords", [])
        block_keywords = filters.get("block_keywords", [])

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
        Replicates Discord's true native forward behavior with quoted message format.
        Discord's native forward quotes the original content and lets Discord regenerate
        fresh embeds from URLs, keeping video functionality intact.
        """
        # Build the quoted message content
        quote_lines = []

        # Add author line in the quote
        if formatting.get("include_author", True):
            quote_lines.append(f"> -# **{message.author.display_name}** - ([original post]({message.jump_url}))")

        # Add the message text content with quote formatting
        if message.content:
            # Split content into lines and add quote prefix to each
            content_lines = message.content.split('\n')
            for line in content_lines:
                quote_lines.append(f"> {line}")

        # Join all quote lines
        quoted_content = '\n'.join(quote_lines)

        # Prepare files to forward if attachment forwarding is enabled
        files_to_send = []
        omitted_attachments = False
        if formatting.get("forward_attachments", True) and message.attachments:
            max_size = formatting.get("max_attachment_size", 25) * 1024 * 1024  # MB to bytes
            if destination.guild.premium_tier >= 2:
                max_total_size = 50 * 1024 * 1024  # 50MB for boosted servers
            else:
                max_total_size = 10 * 1024 * 1024  # 10MB for non-boosted servers
            total_attachment_size = 0
            allowed_types = formatting.get("allowed_attachment_types")

            for attachment in message.attachments:
                if total_attachment_size + attachment.size > max_total_size:
                    omitted_attachments = True
                    logger.warning(f"Total attachment size exceeds {max_total_size} bytes. "
                                   f"Stopping attachment forwarding.")
                    break  # Stop adding more attachments

                try:
                    if attachment.size > max_size:
                        continue

                    if allowed_types and not any(attachment.filename.lower().endswith(ext) for ext in allowed_types):
                        continue

                    f = await attachment.to_file(spoiler=attachment.is_spoiler())
                    files_to_send.append(f)
                    total_attachment_size += attachment.size
                except discord.HTTPException as e:
                    logger.warning(f"Failed to forward attachment {attachment.filename}: {e}")

        if omitted_attachments:
            quoted_content += "\n*(Some attachments were not forwarded due to size limits.)*"

        # Add "Powered by" footer for non-premium guilds (occasionally, with cooldown)
        is_premium = await guild_manager.is_premium_guild(str(destination.guild.id))
        if not is_premium and self._should_show_branding(destination.guild.id):
            # Discord server invite link for Empire of Shadows community
            # Angle brackets suppress embed preview
            server_invite_link = "https://discord.gg/NaK74Wf7vE"
            quoted_content += f"\n-# Powered by Empire of Shadows\n-# Gaming Community • <{server_invite_link}>"

            # Update last branding time for this guild
            self._last_branding_time[destination.guild.id] = datetime.now(timezone.utc)

        # The key insight: Send the quoted content as text along with the original files
        # Discord will automatically detect URLs in the quoted content and generate fresh embeds
        # This preserves video functionality while maintaining the quoted appearance
        try:
            await self._send_with_enhanced_handling(
                destination=destination,
                message=message,
                content=quoted_content,
                files=files_to_send,
                formatting=formatting
            )
        finally:
            # Ensure file handles are properly closed even if an exception occurs
            for file in files_to_send:
                try:
                    if hasattr(file, 'close'):
                        file.close()
                except Exception as cleanup_error:
                    logger.debug(f"Error closing file handle: {cleanup_error}")

    async def forward_message(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        """
        Forwards a message using the native Discord-style forwarding.
        This method is the entry point for all message forwarding.
        Other styles will be available in the future
        """
        # Always use native style for forwarding for now
        await self.forward_as_native_style(formatting, message, destination)

    async def _parse_template_variables(self, text: str, message: discord.Message) -> str:
        """
        Parse template variables in text with enhanced variables.
        This method replaces variables like {author} and {channel} with their
        corresponding values from the message.
        """
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
        """
        Determines the embed color based on a hierarchy:
        1. A custom color defined in the rule's formatting.
        2. The author's top role color (if in the same server).
        3. The message content type (e.g., green for images, purple for embeds).
        """
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
        """
        Check if an embed should be filtered out based on a set of rules.
        This method is used to prevent forwarding unwanted embeds, such as
        ads or empty embeds.
        """
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
        """
        Creates a safe, clean copy of an embed to prevent issues with forwarding
        embeds from other bots, which can have problematic fields or references.
        It also truncates fields to their maximum allowed lengths.
        """
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
        """
        Wrapper for `destination.send` that includes advanced error handling,
        such as message chunking and smart retries for oversized content.
        """
        formatting = send_kwargs.pop('formatting', {})

        # If forwarding to the same channel, send as a reply.
        if message.channel.id == destination.id:
            send_kwargs["reference"] = message
            send_kwargs["mention_author"] = formatting.get("mention_author", False)

        try:
            await destination.send(**send_kwargs)
        except discord.HTTPException as e:
            # Handle payload too large error by retrying without files
            if e.code == 40005:  # Discord error code for "Request entity too large"
                logger.warning(f"Payload too large for message {message.id}. Retrying without attachments. Error: {e}")
                send_kwargs.pop('files', None)

                content = send_kwargs.get('content', '')
                if "attachments were not forwarded" not in content.lower():
                    content += "\n\n*(Attachments were not forwarded due to size limits.)*"
                send_kwargs['content'] = content

                try:
                    await destination.send(**send_kwargs)
                except discord.HTTPException as e2:
                    logger.error(f"Failed to send forwarded message {message.id} even after removing attachments: {e2}")
                    await self._send_minimal_version(destination, message, formatting)

            # If the message content is too long, try to handle it gracefully.
            elif "message content too long" in str(e).lower():
                logger.error(f"Failed to send forwarded message: {e}")
                await self._handle_oversized_message(destination, message, send_kwargs, formatting)

            else:
                logger.error(f"Failed to send forwarded message: {e}")
                # For other errors, try sending a minimal version.
                send_kwargs.pop('reference', None)
                send_kwargs.pop('files', None)
                await destination.send(
                    content="📨 *Message forwarded (some content omitted due to size limits)*",
                    embeds=send_kwargs.get('embeds', [])[:1]
                )


    async def _handle_oversized_message(self, destination: discord.TextChannel, message: discord.Message,
                                        send_kwargs: dict, formatting: dict):
        """
        Handles messages that exceed Discord's size limits by trying different strategies:
        1. Split content into multiple messages (chunking).
        2. Reduce the number of embeds.
        3. Send a summary of files instead of the files themselves.
        4. As a last resort, send a minimal text-only version.
        """
        content = send_kwargs.get('content', '')
        embeds = send_kwargs.get('embeds', [])
        files = send_kwargs.get('files', [])

        if content and len(content) > 2000:
            await self._send_chunked_content(destination, message, content, embeds, files, formatting)
            return

        if embeds and len(embeds) > 10:
            await self._send_reduced_embeds(destination, message, content, embeds, files, formatting)
            return

        if files and sum(f.size for f in files) > 25 * 1024 * 1024:  # 25MB total
            await self._send_compressed_files(destination, message, content, embeds, files, formatting)
            return

        await self._send_minimal_version(destination, message, formatting)


    async def _send_chunked_content(self, destination: discord.TextChannel, message: discord.Message,
                                    content: str, embeds: list, files: list, formatting: dict):
        """
        Splits large content into multiple messages, sent as replies.
        This method is used when the message content exceeds the 2000 character limit.
        """
        chunks = self._split_content(content, max_length=1900)

        first_chunk = chunks[0]
        if len(chunks) > 1:
            first_chunk += f"\n\n*(Message continued... {len(chunks)} parts total)*"

        try:
            # Send the first part with the most important attachments/embeds.
            first_message = await destination.send(
                content=first_chunk,
                embeds=embeds[:1] if embeds else [],
                files=files[:1] if files else []
            )
        except discord.HTTPException:
            await self._send_ultra_minimal(destination, message, formatting)
            return

        # Send subsequent parts as replies to the first message.
        for i, chunk in enumerate(chunks[1:], 2):
            chunk_content = f"**Part {i}/{len(chunks)}:**\n{chunk}"
            if i == len(chunks):  # On the last chunk, add remaining media.
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
        """
        Handles messages with too many embeds by sending the first 10 and a summary.
        This method is used when the message has more than 10 embeds.
        """
        omitted_count = len(embeds) - 10
        summary_text = f"\n\n*📊 {omitted_count} additional embeds omitted*"

        try:
            await destination.send(
                content=content + summary_text,
                embeds=embeds[:10],
                files=files[:10]
            )
        except discord.HTTPException:
            # If still too large, reduce further.
            await destination.send(
                content=content + summary_text,
                embeds=embeds[:5],
                files=files[:3]
            )


    async def _send_compressed_files(self, destination: discord.TextChannel, message: discord.Message,
                                     content: str, embeds: list, files: list, formatting: dict):
        """
        Handles messages where the total file size is too large by sending a summary.
        This method is used when the total size of the attachments exceeds 25MB.
        """
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
            embeds=embeds[:10]
        )


    async def _send_minimal_version(self, destination: discord.TextChannel, message: discord.Message,
                                    formatting: dict):
        """
        Sends a minimal, text-only version of the message as a fallback.
        This method is used when all other sending attempts fail.
        """
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
        """
        Sends the absolute most minimal version when all other sending attempts fail.
        This method is used as a last resort when all other sending attempts fail.
        """
        ultra_minimal = (
            f"📨 **Message from {message.author.display_name}**\n"
            f"Content: {len(message.content)} chars"
            f"{f' | {len(message.attachments)} files' if message.attachments else ''}"
            f"{f' | {len(message.embeds)} embeds' if message.embeds else ''}\n"
            f"🔗 [View Original]({message.jump_url})"
        )

        await destination.send(content=ultra_minimal)


    def _split_content(self, content: str, max_length: int = 1900) -> list:
        """
        Splits a string into chunks of a maximum length, attempting to preserve
        paragraphs, sentences, and words.

        This uses a multi-pass approach:
        1. Splits by paragraphs (`\n\n`).
        2. If a paragraph is too long, it's split by sentences.
        3. If a sentence is too long, it's split by words.
        """
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
    """Setup function to add the cog to the bot."""
    await bot.add_cog(Forwarding(bot))
    logger.info("Forwarding cog loaded.")
