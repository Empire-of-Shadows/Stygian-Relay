import asyncio
import discord
from discord.ext import commands
from discord import app_commands, ui
from database import guild_manager
from logger.logger_setup import get_logger

logger = get_logger(__name__, level=20)


class ForwardOptionsView(ui.View):
    """
    A view that provides options for manually forwarding a message.
    It allows the user to select a destination channel and a formatting style
    before confirming the forward action.
    This view is used by the `forward_message_context_menu` command.
    """
    def __init__(self, original_message: discord.Message, cog_instance):
        super().__init__(timeout=180)
        self.original_message = original_message
        self.cog_instance = cog_instance
        self.forward_style = "native"
        self.destination_channel = None

        style_select = ui.Select(
            placeholder="Choose a forwarding style...",
            options=[
                discord.SelectOption(label="Native Style", value="native",
                                     description="Closest to Discord's forward feature."),
                discord.SelectOption(label="Component v2", value="c_v2", description="A modern, structured layout."),
                discord.SelectOption(label="Embed", value="embed", description="A standard Discord embed."),
                discord.SelectOption(label="Plain Text", value="text", description="A simple text-based message."),
            ]
        )

        style_select.callback = self.style_select_callback
        self.add_item(style_select)

        channel_select = ui.ChannelSelect(
            placeholder="Select destination channel...",
            channel_types=[discord.ChannelType.text]
        )
        channel_select.callback = self.channel_select_callback
        self.add_item(channel_select)

        forward_button = ui.Button(label="Forward", style=discord.ButtonStyle.primary, row=2)
        forward_button.callback = self.forward_button_callback
        self.add_item(forward_button)

    async def style_select_callback(self, interaction: discord.Interaction):
        """
        Callback for the style select menu.
        This method is called when the user selects a forwarding style.
        """
        self.forward_style = interaction.data['values'][0]
        await interaction.response.defer()

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

    def __init__(self, bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name='Forward Message',
            callback=self.forward_message_context_menu,
        )
        self.bot.tree.add_command(self.ctx_menu)

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
                if not rule.get("is_active") or str(rule.get("source_channel_id")) != str(message.channel.id):
                    continue

                # Enforce the daily message forwarding limit for the guild.
                daily_limit = guild_settings.get("limits", {}).get("daily_messages", 100)
                daily_count = await guild_manager.get_daily_message_count(str(message.guild.id))
                if daily_count >= daily_limit:
                    if guild_settings.get("features", {}).get("notify_on_error", True):
                        await message.channel.send(f"Daily message forwarding limit of {daily_limit} reached.", delete_after=60)
                    continue  # Stop processing this rule and any subsequent ones for this message.

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

        destination_channel_id = rule.get("destination_channel_id")
        destination_channel = self.bot.get_channel(int(destination_channel_id))

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
            quote_lines.append(f"> **{message.author.display_name}**")

        # Add the message text content with quote formatting
        if message.content:
            # Split content into lines and add quote prefix to each
            content_lines = message.content.split('\n')
            for line in content_lines:
                quote_lines.append(f"> {line}")

        # Add the original message link within the quote
        quote_lines.append(f"> -# ([original post]({message.jump_url}))")

        # Join all quote lines
        quoted_content = '\n'.join(quote_lines)

        # Prepare files to forward if attachment forwarding is enabled
        files_to_send = []
        if formatting.get("forward_attachments", True) and message.attachments:
            max_size = formatting.get("max_attachment_size", 25) * 1024 * 1024  # MB to bytes
            allowed_types = formatting.get("allowed_attachment_types")

            for attachment in message.attachments:
                try:
                    if attachment.size > max_size:
                        continue

                    if allowed_types and not any(attachment.filename.lower().endswith(ext) for ext in allowed_types):
                        continue

                    f = await attachment.to_file(spoiler=attachment.is_spoiler())
                    files_to_send.append(f)
                except discord.HTTPException as e:
                    logger.warning(f"Failed to forward attachment {attachment.filename}: {e}")

        # The key insight: Send the quoted content as text along with the original files
        # Discord will automatically detect URLs in the quoted content and generate fresh embeds
        # This preserves video functionality while maintaining the quoted appearance
        await self._send_with_enhanced_handling(
            destination=destination,
            message=message,
            content=quoted_content,
            files=files_to_send,
            formatting=formatting
        )

    async def forward_message(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        """
        Dispatches to the correct forwarding method based on style.
        This method is the entry point for all message forwarding.
        """
        forward_style = formatting.get("forward_style", "native")  # Default to native style

        if forward_style == "text":
            await self.forward_as_text(formatting, message, destination)
        elif forward_style == "embed":
            await self.forward_as_embed(formatting, message, destination)
        elif forward_style == "c_v2":
            await self.forward_as_component_v2(formatting, message, destination)
        else:  # "native" or default
            await self.forward_as_native_style(formatting, message, destination)

    async def forward_as_text(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        """
        Constructs and sends the forwarded message as plain text.
        This method handles dynamic variables in prefix/suffix, author information,
        source context, content truncation, and attachment handling.
        """
        content_parts = []
        embeds_to_send = []
        files_to_send = []
        failed_attachments = []

        if prefix := formatting.get("add_prefix"):
            prefix = await self._parse_template_variables(prefix, message)
            content_parts.append(prefix)

        if formatting.get("include_author", True):
            author_format = formatting.get("author_format", "**From {mention}:**")
            author_text = author_format.format(
                mention=message.author.mention,
                name=message.author.display_name,
                id=message.author.id,
                discriminator=message.author.discriminator
            )
            content_parts.append(author_text)

        if formatting.get("include_source", False):
            source_text = f"*in {message.channel.mention}*"
            if message.guild and message.guild.id != destination.guild.id:
                source_text += f" | *{message.guild.name}*"
            content_parts.append(source_text)

        if message.content:
            content = message.content
            max_length = formatting.get("max_content_length", 2000)
            if len(content) > max_length:
                content = content[:max_length - 3] + "..."
                content_parts.append(content)
                content_parts.append(f"*(message truncated, {len(message.content)} chars total)*")
            else:
                content_parts.append(content)

        if suffix := formatting.get("add_suffix"):
            suffix = await self._parse_template_variables(suffix, message)
            content_parts.append(suffix)

        separator = formatting.get("separator", "\n")
        final_content = separator.join(filter(None, content_parts))

        if formatting.get("forward_embeds", True) and message.embeds:
            embed_filter = formatting.get("embed_filter", [])
            for embed in message.embeds:
                if not self._should_filter_embed(embed, embed_filter):
                    embeds_to_send.append(embed)

        if formatting.get("forward_attachments", True) and message.attachments:
            max_size = formatting.get("max_attachment_size", 25) * 1024 * 1024  # MB to bytes
            allowed_types = formatting.get("allowed_attachment_types")

            for attachment in message.attachments:
                try:
                    if attachment.size > max_size:
                        continue

                    if allowed_types and not any(attachment.filename.lower().endswith(ext) for ext in allowed_types):
                        continue

                    f = await attachment.to_file(spoiler=attachment.is_spoiler())
                    files_to_send.append(f)
                except discord.HTTPException as e:
                    logger.warning(f"Failed to forward attachment {attachment.filename}: {e}")
                    failed_attachments.append("Failed to process file")

        # Only show failure count, not specific filenames
        if failed_attachments:
            final_content += f"\n\n⚠️ **{len(failed_attachments)} file(s) could not be forwarded**"

        await self._send_with_enhanced_handling(
            destination=destination,
            message=message,
            content=final_content if final_content.strip() else None,
            embeds=embeds_to_send,
            files=files_to_send,
            formatting=formatting
        )

    async def forward_as_embed(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        """
        Constructs and sends the forwarded message as a rich embed.
        This method handles dynamic colors, author/source info, metadata in the footer,
        and smart handling of attachments and subsequent embeds.
        """
        embed_color = self._get_embed_color(formatting, message)

        embed = discord.Embed(
            description=message.content,
            color=embed_color,
            timestamp=message.created_at
        )

        if formatting.get("include_author", True):
            author_config = formatting.get("author_config", {})
            embed.set_author(
                name=author_config.get("name", f"Message from {message.author.display_name}"),
                icon_url=message.author.display_avatar.url,
                url=message.jump_url
            )

        if formatting.get("include_source", True):
            source_value = f"[Jump to message]({message.jump_url})"
            if message.guild:
                source_value += f" • {message.channel.mention}"
                if message.guild.id != destination.guild.id:
                    source_value += f" • {message.guild.name}"
            embed.add_field(name="Source", value=source_value, inline=False)

        if prefix := formatting.get("add_prefix"):
            prefix = await self._parse_template_variables(prefix, message)
            embed.title = prefix

        footer_parts = []
        if suffix := formatting.get("add_suffix"):
            suffix = await self._parse_template_variables(suffix, message)
            footer_parts.append(suffix)

        if formatting.get("include_metadata", True):
            metadata = []
            if message.edited_at:
                metadata.append(f"✏️ {message.edited_at.strftime('%Y-%m-%d %H:%M')}")
            if message.reactions:
                metadata.append(f"❤️ {len(message.reactions)}")
            if metadata:
                footer_parts.append(" | ".join(metadata))

        if footer_parts:
            embed.set_footer(text=" • ".join(filter(None, footer_parts)))

        embeds_to_send = [embed]
        files_to_send = []
        if formatting.get("forward_attachments", True) and message.attachments:
            # Prepare all attachments to be sent as files first.
            for attachment in message.attachments:
                try:
                    f = await attachment.to_file(spoiler=attachment.is_spoiler())
                    files_to_send.append(f)
                except discord.HTTPException as e:
                    logger.warning(f"Failed to prepare attachment {attachment.filename}: {e}")
                    embed.add_field(
                        name="⚠️ Attachment Failed",
                        value=f"`{attachment.filename}`",
                        inline=True
                    )

            # Filter for image attachments to embed them visually.
            image_attachments = [
                att for att in message.attachments
                if att.content_type and att.content_type.startswith('image/')
            ]

            if image_attachments:
                # The first image goes into the main embed.
                main_image = image_attachments.pop(0)
                embed.set_image(url=f"attachment://{'SPOILER_' if main_image.is_spoiler() else ''}{main_image.filename}")

                # Create additional embeds for other images, up to the Discord limit.
                for image in image_attachments:
                    if len(embeds_to_send) < 10:
                        img_embed = discord.Embed(
                            url=message.jump_url,  # Link back to the original message
                            color=embed_color
                        )
                        img_embed.set_image(url=f"attachment://{'SPOILER_' if image.is_spoiler() else ''}{image.filename}")
                        embeds_to_send.append(img_embed)

        # Stack original embeds from the source message below the main one.
        if formatting.get("forward_embeds", True) and message.embeds:
            max_embeds = formatting.get("max_embeds", 10)
            # Account for embeds we've already created for images.
            remaining_embed_slots = max_embeds - len(embeds_to_send)
            if remaining_embed_slots > 0:
                for original_embed in message.embeds[:remaining_embed_slots]:
                    safe_embed = self._sanitize_embed(original_embed)
                    embeds_to_send.append(safe_embed)

        await self._send_with_enhanced_handling(
            destination=destination,
            message=message,
            embeds=embeds_to_send,
            files=files_to_send,
            formatting=formatting
        )

    async def forward_as_component_v2(self, formatting: dict, message: discord.Message,
                                      destination: discord.TextChannel):
        """
        Constructs and sends the forwarded message using Discord's modern "Components v2".
        This creates a structured layout with sections, thumbnails, and interactive buttons.
        Note: This uses an experimental or less common part of the API.
        """
        layout = ui.LayoutView()
        files_to_send = []
        embeds_to_send = []
        failed_attachments = []

        container = ui.Container()

        if prefix := formatting.get("add_prefix"):
            prefix = await self._parse_template_variables(prefix, message)
            container.add_item(ui.TextDisplay(f"## {prefix}"))

        # Create a section for author info, including their avatar.
        if formatting.get("include_author", True):
            author_accessory = None
            if message.author.display_avatar:
                author_accessory = ui.Thumbnail(media=message.author.display_avatar.url)

            author_section = ui.Section(accessory=author_accessory)

            author_text = f"**{message.author.display_name}**"
            if formatting.get("include_timestamp", True):
                author_text += f" • <t:{int(message.created_at.timestamp())}:R>"

            author_section.add_item(ui.TextDisplay(author_text))

            source_text = f"in {message.channel.mention}"
            if message.guild and message.guild.id != destination.guild.id:
                source_text += f" • {message.guild.name}"
            author_section.add_item(ui.TextDisplay(source_text))

            container.add_item(author_section)
            container.add_item(ui.Separator())

        if message.content:
            content_display = ui.TextDisplay(message.content)
            container.add_item(content_display)

        # Add interactive buttons like "View Original".
        action_row = ui.ActionRow()
        if formatting.get("include_jump_link", True):
            action_row.add_item(
                ui.Button(
                    style=discord.ButtonStyle.link,
                    label="View Original",
                    url=message.jump_url
                )
            )
        # Example of a custom interaction button.
        if message.guild and message.guild.id == destination.guild.id:
            action_row.add_item(
                ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label="👍",
                    custom_id=f"quick_react_thumbs_up:{message.id}"
                )
            )
        if len(action_row.children) > 0:
            container.add_item(action_row)

        if suffix := formatting.get("add_suffix"):
            suffix = await self._parse_template_variables(suffix, message)
            container.add_item(ui.Separator())
            container.add_item(ui.TextDisplay(suffix))

        layout.add_item(container)

        # Handle media (images, videos) in a separate gallery component.
        if formatting.get("forward_attachments", True) and message.attachments:
            media_attachments = [att for att in message.attachments
                                 if att.content_type and
                                 (att.content_type.startswith('image/') or
                                  att.content_type.startswith('video/') or
                                  att.content_type.startswith('audio/'))]

            other_attachments = [att for att in message.attachments if att not in media_attachments]

            if media_attachments:
                layout.add_item(ui.Separator())
                media_gallery = ui.MediaGallery()
                for attachment in media_attachments:
                    try:
                        f = await attachment.to_file(spoiler=attachment.is_spoiler())
                        files_to_send.append(f)
                        media_gallery.add_item(media=f"attachment://{'SPOILER_' if attachment.is_spoiler() else ''}{attachment.filename}")
                    except discord.HTTPException as e:
                        logger.warning(f"Failed to forward media {attachment.filename}: {e}")
                        failed_attachments.append(attachment.filename)
                if len(media_gallery.items) > 0:
                    layout.add_item(media_gallery)

            # Handle other file types in a simple list.
            if other_attachments:
                for attachment in other_attachments:
                    try:
                        f = await attachment.to_file(spoiler=attachment.is_spoiler())
                        files_to_send.append(f)
                    except discord.HTTPException as e:
                        logger.warning(f"Failed to forward file {attachment.filename}: {e}")
                        failed_attachments.append(
                            attachment.filename)

            if other_attachments:
                layout.add_item(ui.Separator())
                file_container = ui.Container()
                file_container.add_item(ui.TextDisplay(f"## Files ({len(other_attachments)})"))
                for attachment in other_attachments:
                    try:
                        f = await attachment.to_file(spoiler=attachment.is_spoiler())
                        files_to_send.append(f)
                        file_container.add_item(
                            ui.TextDisplay(f"📎 {attachment.filename} ({attachment.size // 1024}KB)")
                        )
                    except discord.HTTPException as e:
                        logger.warning(f"Failed to forward file {attachment.filename}: {e}")
                        failed_attachments.append(attachment.filename)
                layout.add_item(file_container)

        if failed_attachments:
            layout.add_item(ui.Separator())
            error_container = ui.Container()
            error_container.add_item(ui.TextDisplay("## ⚠️ Failed to Forward"))
            for filename in failed_attachments:
                error_container.add_item(ui.TextDisplay(f"`{filename}`"))
            layout.add_item(error_container)

        # Original embeds are sent after the main component layout.
        if formatting.get("forward_embeds", True) and message.embeds:
            layout.add_item(ui.Separator())
            embed_container = ui.Container()
            embed_container.add_item(ui.TextDisplay("## Original Embeds"))
            embed_container.add_item(
                ui.TextDisplay(f"{len(message.embeds)} embed(s) included below.")
            )
            layout.add_item(embed_container)
            for embed in message.embeds[:5]:  # Limit embeds in components
                safe_embed = self._sanitize_embed(embed)
                embeds_to_send.append(safe_embed)

        # The `send` call expects `view`, not `layout`.
        await self._send_with_enhanced_handling(
            destination=destination,
            message=message,
            view=layout,
            files=files_to_send,
            embeds=embeds_to_send,
            formatting=formatting
        )

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
            logger.error(f"Failed to send forwarded message: {e}")

            # If the message is too long, try to handle it gracefully.
            if "message content too long" in str(e).lower():
                await self._handle_oversized_message(destination, message, send_kwargs, formatting)
            else:
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
