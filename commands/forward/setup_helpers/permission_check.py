from typing import List, Tuple
import discord


class PermissionChecker:
    """Verifies bot has necessary permissions for operation."""

    # Required permissions for basic functionality
    BASIC_PERMISSIONS = [
        "view_channel",
        "send_messages",
        "read_message_history",
        "attach_files",
        "embed_links"
    ]

    # Required permissions for advanced features
    ADVANCED_PERMISSIONS = [
        "manage_webhooks",  # For better forwarding
        "manage_messages",  # For cleanup operations
        "add_reactions"  # For interactive features
    ]

    async def check_guild_permissions(self, guild: discord.Guild) -> Tuple[bool, List[str], List[str]]:
        """
        Check if bot has required permissions in the guild.
        This method is used to check the bot's permissions at the guild level.

        Returns:
            Tuple of (has_basic_permissions, missing_basic, missing_advanced)
        """
        bot_member = guild.me
        if not bot_member:
            return False, self.BASIC_PERMISSIONS, self.ADVANCED_PERMISSIONS

        bot_permissions = bot_member.guild_permissions

        missing_basic = []
        missing_advanced = []

        # Check basic permissions
        for perm in self.BASIC_PERMISSIONS:
            if not getattr(bot_permissions, perm, False):
                missing_basic.append(perm)

        # Check advanced permissions
        for perm in self.ADVANCED_PERMISSIONS:
            if not getattr(bot_permissions, perm, False):
                missing_advanced.append(perm)

        has_basic = len(missing_basic) == 0
        return has_basic, missing_basic, missing_advanced

    async def check_channel_permissions(self, channel: discord.TextChannel,
                                        required_perms: List[str] = None) -> Tuple[bool, List[str]]:
        """
        Check if bot has required permissions in a specific channel.
        This method is used to check the bot's permissions in a specific channel.

        Args:
            channel: The channel to check
            required_perms: List of permission names to check

        Returns:
            Tuple of (has_permissions, missing_permissions)
        """
        if required_perms is None:
            required_perms = self.BASIC_PERMISSIONS

        bot_member = channel.guild.me
        if not bot_member:
            return False, required_perms

        channel_perms = channel.permissions_for(bot_member)

        missing_perms = []
        for perm in required_perms:
            if not getattr(channel_perms, perm, False):
                missing_perms.append(perm)

        return len(missing_perms) == 0, missing_perms

    def format_missing_permissions(self, missing_perms: List[str]) -> str:
        """
        Format missing permissions into a user-friendly message.
        This method is used to create a user-friendly message that lists the
        missing permissions.
        """
        if not missing_perms:
            return "✅ All required permissions are granted!"

        # Convert permission names to readable format
        permission_names = {
            "view_channel": "View Channels",
            "send_messages": "Send Messages",
            "read_message_history": "Read Message History",
            "attach_files": "Attach Files",
            "embed_links": "Embed Links",
            "manage_webhooks": "Manage Webhooks",
            "manage_messages": "Manage Messages",
            "add_reactions": "Add Reactions"
        }

        readable_perms = [permission_names.get(perm, perm.replace('_', ' ').title())
                          for perm in missing_perms]

        return "❌ Missing permissions:\n• " + "\n• ".join(readable_perms)

    async def create_permission_embed(self, guild: discord.Guild) -> discord.Embed:
        """
        Create an embed showing current permission status.
        This embed is shown to the user during the setup wizard.
        """
        has_basic, missing_basic, missing_advanced = await self.check_guild_permissions(guild)

        embed = discord.Embed(
            title="🔐 Permission Check",
            color=discord.Color.green() if has_basic else discord.Color.orange()
        )

        # Basic permissions status
        if has_basic:
            embed.add_field(
                name="✅ Basic Permissions",
                value="All required permissions are granted!",
                inline=False
            )
        else:
            embed.add_field(
                name="❌ Basic Permissions",
                value=self.format_missing_permissions(missing_basic),
                inline=False
            )

        # Advanced permissions status
        if missing_advanced:
            embed.add_field(
                name="⚠️ Recommended Permissions",
                value=self.format_missing_permissions(missing_advanced),
                inline=False
            )
            embed.add_field(
                name="💡 Note",
                value="Recommended permissions enable additional features but aren't required for basic functionality.",
                inline=False
            )
        else:
            embed.add_field(
                name="✅ Advanced Permissions",
                value="All recommended permissions are granted!",
                inline=False
            )

        return embed

    async def can_proceed_with_setup(self, guild: discord.Guild) -> Tuple[bool, str]:
        """
        Check if setup can proceed based on permissions.
        This method is used to determine if the setup wizard can proceed to the
        next step.

        Returns:
            Tuple of (can_proceed, reason_message)
        """
        has_basic, missing_basic, _ = await self.check_guild_permissions(guild)

        if not has_basic:
            return False, (
                "I don't have the basic permissions needed to function properly. "
                "Please grant me the required permissions and try again.\n\n"
                f"{self.format_missing_permissions(missing_basic)}"
            )

        return True, "✅ All required permissions are granted! Setup can continue."


# Global permission checker instance
permission_checker = PermissionChecker()