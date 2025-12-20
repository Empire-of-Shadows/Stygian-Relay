from typing import List, Optional, Tuple
import discord

import logging


class ChannelSelector:
    """Handles interactive channel selection."""

    def __init__(self):
        self.logger = logging.getLogger("ChannelSelector")


    async def create_channel_select_menu(self, guild: discord.Guild,
                                         channel_type: str = "text",
                                         custom_id: str = "channel_select",
                                         default_value: Optional[str] = None) -> discord.ui.View:
        """
        Create a channel selection dropdown menu.
        This view is used in the setup wizard to allow the user to select a
        channel.

        Args:
            guild: The guild to get channels from
            channel_type: Type of channels to include ("text", "voice", "category", "all")
            custom_id: Custom ID for the select menu

        Returns:
            discord.ui.View with channel selection
        """
        self.logger.debug(f"Creating channel select menu for guild {guild.id}, type: {channel_type}")
        view = discord.ui.View(timeout=1800)

        # Get appropriate channels based on type
        channels = await self._get_filtered_channels(guild, channel_type)

        if not channels:
            self.logger.warning(f"No channels found for guild {guild.id}, type: {channel_type}")
            # Fallback if no channels available
            select = discord.ui.Select(
                placeholder="No channels available",
                options=[discord.SelectOption(label="No channels found", value="none")],
                disabled=True,
                custom_id=custom_id
            )
        else:
            self.logger.info(f"Found {len(channels)} channels for guild {guild.id}")
            # Create select options from channels
            options = []
            for channel in channels[:25]:  # Discord limit of 25 options
                option = discord.SelectOption(
                    label=f"#{channel.name}"[:100],  # Discord limit
                    value=str(channel.id),
                    description=channel.topic[:100] if hasattr(channel, 'topic') and channel.topic else None,
                    default=str(channel.id) == default_value
                )
                options.append(option)

            select = discord.ui.Select(
                placeholder=f"Select a {channel_type} channel...",
                options=options,
                custom_id=custom_id
            )

        # Don't add a callback - let the main setup handler deal with it
        view.add_item(select)

        return view

    async def _get_filtered_channels(self, guild: discord.Guild, channel_type: str) -> List[discord.abc.GuildChannel]:
        """
        Get channels filtered by type and accessibility.
        This method is used to get a list of channels that can be selected by
        the user.
        """
        channels = []

        for channel in guild.channels:
            # Filter by type
            if channel_type == "text" and isinstance(channel, discord.TextChannel):
                channels.append(channel)
            elif channel_type == "voice" and isinstance(channel, discord.VoiceChannel):
                channels.append(channel)
            elif channel_type == "category" and isinstance(channel, discord.CategoryChannel):
                channels.append(channel)
            elif channel_type == "all":
                channels.append(channel)

        # Sort channels by position
        channels.sort(key=lambda c: c.position)

        return channels

    async def validate_channel_access(self, guild: discord.Guild, channel_id: int) -> Tuple[bool, str]:
        """
        Validate that the bot can access and use a channel.
        This method is used to ensure that the bot has the required permissions
        to use a channel.

        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            channel = guild.get_channel(channel_id)
            if not channel:
                return False, "Channel not found in this server."

            # Check if it's a text channel
            if not isinstance(channel, discord.TextChannel):
                return False, "Please select a text channel."

            # Check bot permissions in the channel
            from .permission_check import permission_checker
            has_perms, missing_perms = await permission_checker.check_channel_permissions(channel)

            if not has_perms:
                return False, f"I don't have permission to use {channel.mention}. Missing: {', '.join(missing_perms)}"

            return True, "✅ Channel is accessible!"

        except Exception as e:
            return False, f"Error accessing channel: {str(e)}"

    async def create_channel_embed(self, guild: discord.Guild, purpose: str) -> discord.Embed:
        """
        Create an embed for channel selection step.
        This embed is shown to the user when they are selecting a channel.

        Args:
            guild: The guild
            purpose: What the channel will be used for

        Returns:
            discord.Embed
        """
        embed = discord.Embed(
            title="📁 Channel Selection",
            color=discord.Color.blue()
        )

        if purpose == "log_channel":
            embed.description = (
                "**Please select a channel where I can send logs and notifications:**\n\n"
                "• Error messages and warnings\n"
                "• Setup completion notices\n"
                "• System notifications\n\n"
                "This should be a channel that server admins can see."
            )
            embed.add_field(
                name="💡 Tip",
                value="Choose a dedicated #bot-logs channel or an admin channel.",
                inline=False
            )

        elif purpose == "source_channel":
            embed.description = (
                "**Please select the channel to watch for messages:**\n\n"
                "This is the channel where messages will be monitored for forwarding."
            )
            embed.add_field(
                name="💡 Tip",
                value="Choose a busy channel like #general or #announcements.",
                inline=False
            )

        elif purpose == "destination_channel":
            embed.description = (
                "**Please select where to forward messages:**\n\n"
                "Messages from the source channel will be sent to this channel."
            )
            embed.add_field(
                name="💡 Tip",
                value="This could be a #archive channel, #crosspost, or any destination you want.",
                inline=False
            )

        # Show available text channels count
        text_channels = [c for c in guild.channels if isinstance(c, discord.TextChannel)]
        embed.set_footer(text=f"{len(text_channels)} text channels available in this server")

        return embed


# Global channel selector instance
channel_selector = ChannelSelector()