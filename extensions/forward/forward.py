import discord
from discord.ext import commands
from discord import app_commands, ui
from database import guild_manager
from logger.logger_setup import get_logger
import asyncio

logger = get_logger(__name__, level=20)


class ForwardOptionsView(ui.View):
    def __init__(self, original_message: discord.Message, cog_instance):
        super().__init__(timeout=180)
        self.original_message = original_message
        self.cog_instance = cog_instance
        self.forward_style = "c_v2"
        self.destination_channel = None

        # Style select
        style_select = ui.Select(
            placeholder="Choose a forwarding style...",
            options=[
                discord.SelectOption(label="Component v2 (Default)", value="c_v2", description="A modern, structured layout."),
                discord.SelectOption(label="Embed", value="embed", description="A standard Discord embed."),
                discord.SelectOption(label="Plain Text", value="text", description="A simple text-based message."),
            ]
        )
        style_select.callback = self.style_select_callback
        self.add_item(style_select)

        # Channel select
        channel_select = ui.ChannelSelect(
            placeholder="Select destination channel...",
            channel_types=[discord.ChannelType.text]
        )
        channel_select.callback = self.channel_select_callback
        self.add_item(channel_select)

        # Forward button
        forward_button = ui.Button(label="Forward", style=discord.ButtonStyle.primary, row=2)
        forward_button.callback = self.forward_button_callback
        self.add_item(forward_button)

    async def style_select_callback(self, interaction: discord.Interaction):
        self.forward_style = interaction.data['values'][0]
        await interaction.response.defer()

    async def channel_select_callback(self, interaction: discord.Interaction):
        self.destination_channel = interaction.data['values'][0]
        # Get the actual channel object
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
    Cog for handling message forwarding based on guild-specific rules.
    """

    def __init__(self, bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name='Forward Message',
            callback=self.forward_message_context_menu,
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    async def forward_message_context_menu(self, interaction: discord.Interaction, message: discord.Message):
        """
        Context menu command to forward a message.
        """
        view = ForwardOptionsView(message, self)
        await interaction.response.send_message("Select forwarding options:", view=view, ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Listen for messages and forward them if they match any rules.
        """
        if message.author.bot or not message.guild:
            return

        try:
            guild_settings = await guild_manager.get_guild_settings(str(message.guild.id))

            if not guild_settings.get("features", {}).get("forwarding_enabled", False):
                return

            rules = guild_settings.get("rules", [])
            if not rules:
                return

            for rule in rules:
                if not rule.get("is_active") or str(rule.get("source_channel_id")) != str(message.channel.id):
                    continue

                # Check daily message limit
                daily_limit = guild_settings.get("limits", {}).get("daily_messages", 100)
                daily_count = await guild_manager.get_daily_message_count(str(message.guild.id))
                if daily_count >= daily_limit:
                    if guild_settings.get("features", {}).get("notify_on_error", True):
                        await message.channel.send(f"Daily message forwarding limit of {daily_limit} reached.", delete_after=60)
                    continue # Stop processing this rule

                if await self.process_rule(rule, message, guild_settings):
                    # Log forwarded message
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

    async def process_rule(self, rule: dict, message: discord.Message, guild_settings: dict) -> bool:
        """
        Process a single rule against a message.
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
        """Check if the message type is allowed by the rule."""
        if message.content and message_types.get("text", False):
            return True
        if message.attachments and message_types.get("media", False): # Simplified: media covers general attachments
            return True
        if message.attachments and message_types.get("files", False):
            return True
        if message.embeds and message_types.get("embeds", False):
            return True
        if message.stickers and message_types.get("stickers", False):
            return True
        if "http" in message.content and message_types.get("links", False): # simple link check
            return True
        # If message content is empty, but there is something else, we should not block it if text is not required.
        if not message.content:
            return True

        return False


    def check_filters(self, filters: dict, message: discord.Message, advanced: dict) -> bool:
        """Check keyword and length filters."""
        content = message.content
        case_sensitive = advanced.get("case_sensitive", False)
        whole_word = advanced.get("whole_word_only", False)

        if not case_sensitive:
            content = content.lower()

        # Length filters
        min_len = filters.get("min_length", 0)
        max_len = filters.get("max_length", 2000)
        if not (min_len <= len(message.content) <= max_len):
            return False

        # Keyword filters
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

    async def forward_message(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        """Dispatches to the correct forwarding method based on style."""
        forward_style = formatting.get("forward_style", "c_v2")  # Default to component v2

        if forward_style == "text":
            await self.forward_as_text(formatting, message, destination)
        elif forward_style == "embed":
            await self.forward_as_embed(formatting, message, destination)
        else:  # "c_v2" or default
            await self.forward_as_component_v2(formatting, message, destination)

    async def forward_as_text(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        """Construct and send the forwarded message as plain text."""
        content_parts = []
        embeds_to_send = []
        files_to_send = []

        # Prefix
        if prefix := formatting.get("add_prefix"):
            content_parts.append(prefix)

        # Author
        if formatting.get("include_author", True):
            content_parts.append(f"**From {message.author.mention}:**")

        # Message content
        if message.content:
            content_parts.append(message.content)

        # Suffix
        if suffix := formatting.get("add_suffix"):
            content_parts.append(suffix)

        final_content = "\n".join(content_parts)

        # Embeds
        if formatting.get("forward_embeds", True) and message.embeds:
            embeds_to_send.extend(message.embeds)

        # Attachments
        if formatting.get("forward_attachments", True) and message.attachments:
            for attachment in message.attachments:
                try:
                    f = await attachment.to_file()
                    files_to_send.append(f)
                except discord.HTTPException as e:
                    logger.warning(f"Failed to forward attachment {attachment.filename}: {e}")
                    final_content += f"\n(Attachment failed to forward: {attachment.filename})"

        # Send the message
        send_kwargs = {
            "content": final_content if final_content else None,
            "embeds": embeds_to_send,
            "files": files_to_send
        }
        if message.channel.id == destination.id:
            send_kwargs["reference"] = message
            try:
                await destination.send(**send_kwargs)
            except discord.HTTPException as e:
                logger.error(f"Failed to send forwarded message to {destination.id} with reference: {e}")
                if "reference" in send_kwargs:
                    del send_kwargs["reference"]
                await destination.send(**send_kwargs)
        else:
            try:
                await destination.send(**send_kwargs)
            except discord.HTTPException as e:
                logger.error(f"Failed to send forwarded message to {destination.id}: {e}")

    async def forward_as_embed(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        """Construct and send the forwarded message as an embed."""
        embed = discord.Embed(
            description=message.content,
            color=discord.Color.blue(),
            timestamp=message.created_at
        )

        if formatting.get("include_author", True):
            embed.set_author(
                name=f"Forwarded from {message.author.display_name}",
                icon_url=message.author.display_avatar.url
            )
            embed.add_field(name="Source", value=f"[Jump to message]({message.jump_url})", inline=False)

        if prefix := formatting.get("add_prefix"):
            embed.title = prefix

        if suffix := formatting.get("add_suffix"):
            embed.set_footer(text=suffix)

        files_to_send = []
        # Handle attachments
        if formatting.get("forward_attachments", True) and message.attachments:
            image_set = False
            for attachment in message.attachments:
                try:
                    f = await attachment.to_file()
                    if not image_set and attachment.content_type and attachment.content_type.startswith('image/'):
                        embed.set_image(url=f"attachment://{f.filename}")
                        image_set = True
                    files_to_send.append(f)
                except discord.HTTPException as e:
                    logger.warning(f"Failed to forward attachment {attachment.filename}: {e}")
                    embed.add_field(name="Attachment Failed", value=attachment.filename)

        embeds_to_send = [embed]
        if formatting.get("forward_embeds", True) and message.embeds:
            embeds_to_send.extend(message.embeds)
            embeds_to_send = embeds_to_send[:10]

        # Send the message
        send_kwargs = {
            "embeds": embeds_to_send,
            "files": files_to_send
        }
        if message.channel.id == destination.id:
            send_kwargs["reference"] = message
            try:
                await destination.send(**send_kwargs)
            except discord.HTTPException as e:
                logger.error(f"Failed to send forwarded message to {destination.id} with reference: {e}")
                if "reference" in send_kwargs:
                    del send_kwargs["reference"]
                await destination.send(**send_kwargs)
        else:
            try:
                await destination.send(**send_kwargs)
            except discord.HTTPException as e:
                logger.error(f"Failed to send forwarded message to {destination.id}: {e}")

    async def forward_as_component_v2(self, formatting: dict, message: discord.Message, destination: discord.TextChannel):
        """Construct and send the forwarded message using Components v2."""
        layout = ui.LayoutView()
        files_to_send = []
        embeds_to_send = []

        # Main container for the forwarded message
        container = ui.Container()

        # Prefix
        if prefix := formatting.get("add_prefix"):
            container.add_item(ui.TextDisplay(prefix))

        # Author section
        if formatting.get("include_author", True):
            author_section = ui.Section(accessory=ui.Thumbnail(media=message.author.display_avatar.url))
            author_section.add_item(ui.TextDisplay(f"**From {message.author.mention} in {message.channel.mention}:**"))
            container.add_item(author_section)

        # Message content
        if message.content:
            container.add_item(ui.TextDisplay(message.content))

        # Suffix
        if suffix := formatting.get("add_suffix"):
            container.add_item(ui.TextDisplay(suffix))

        layout.add_item(container)

        # Embeds
        if formatting.get("forward_embeds", True) and message.embeds:
            embeds_to_send.extend(message.embeds)

        # Attachments
        failed_attachments = []
        if formatting.get("forward_attachments", True) and message.attachments:
            media_gallery = ui.MediaGallery()
            for attachment in message.attachments:
                try:
                    f = await attachment.to_file()
                    files_to_send.append(f)
                    if attachment.content_type and \
                       (attachment.content_type.startswith('image/') or attachment.content_type.startswith('video/')):
                        media_gallery.add_item(media=f"attachment://{f.filename}")
                except discord.HTTPException as e:
                    logger.warning(f"Failed to forward attachment {attachment.filename}: {e}")
                    failed_attachments.append(attachment.filename)

            if media_gallery.items:
                layout.add_item(ui.Separator())
                layout.add_item(media_gallery)

        if failed_attachments:
            failed_files_text = "\n".join([f"(Attachment failed to forward: {filename})" for filename in failed_attachments])
            layout.add_item(ui.TextDisplay(failed_files_text))

        # Send the message
        send_kwargs = {
            "view": layout,
            "files": files_to_send,
            "embeds": embeds_to_send,
            "content": None
        }

        if message.channel.id == destination.id:
            send_kwargs["reference"] = message
            try:
                await destination.send(**send_kwargs)
            except discord.HTTPException as e:
                logger.error(f"Failed to send forwarded message to {destination.id} with reference: {e}")
                # Fallback to sending without reference if it fails
                if "reference" in send_kwargs:
                    del send_kwargs["reference"]
                await destination.send(**send_kwargs)
        else:
            try:
                await destination.send(**send_kwargs)
            except discord.HTTPException as e:
                logger.error(f"Failed to send forwarded message to {destination.id}: {e}")


async def setup(bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(Forwarding(bot))
    logger.info("Forwarding cog loaded.")
