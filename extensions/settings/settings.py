import discord
from discord.ext import commands
from discord import app_commands
from database import guild_manager
import logging

logger = logging.getLogger(__name__)


class GuildSettings(commands.Cog):
    """
    Guild settings management cog.

    Provides commands for:
    - Setting manager role
    - Viewing current settings
    - Configuring guild-specific options
    """

    def __init__(self, bot):
        self.bot = bot
        logger.info("GuildSettings cog initialized")

    settings_group = app_commands.Group(
        name="settings",
        description="Manage guild settings",
        guild_only=True
    )

    @settings_group.command(name="set-manager-role", description="Set the role that can manage bot settings")
    @app_commands.describe(role="The role to grant settings management permissions")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_manager_role(self, interaction: discord.Interaction, role: discord.Role):
        """
        Set the manager role for the guild.
        Only administrators can use this command.

        The manager role allows members to manage bot settings without
        needing full administrator permissions.
        """
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = str(interaction.guild_id)

            # Check if the role is @everyone
            if role.is_default():
                await interaction.followup.send(
                    "❌ You cannot set @everyone as the manager role.",
                    ephemeral=True
                )
                return

            # Check if the role is managed (bot role, integration role, etc.)
            if role.managed:
                await interaction.followup.send(
                    "❌ You cannot set a managed role (bot/integration role) as the manager role.",
                    ephemeral=True
                )
                return

            # Update the guild settings
            success = await guild_manager.update_guild_settings(
                guild_id,
                {"manager_role_id": role.id}
            )

            if success:
                embed = discord.Embed(
                    title="✅ Manager Role Updated",
                    description=f"Members with {role.mention} can now manage bot settings.",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="Permissions Granted",
                    value="• Manage forwarding rules\n• Redeem premium codes\n• Configure bot settings",
                    inline=False
                )
                embed.set_footer(text=f"Set by {interaction.user.name}")

                await interaction.followup.send(embed=embed, ephemeral=True)
                logger.info(
                    f"Manager role set to {role.name} ({role.id}) in guild {guild_id} "
                    f"by {interaction.user.id}"
                )
            else:
                await interaction.followup.send(
                    "❌ Failed to update the manager role. Please try again.",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error setting manager role: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while setting the manager role.",
                ephemeral=True
            )

    @settings_group.command(name="remove-manager-role", description="Remove the manager role setting")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_manager_role(self, interaction: discord.Interaction):
        """
        Remove the manager role setting.
        Only administrators can use this command.
        """
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = str(interaction.guild_id)

            # Check if a manager role is currently set
            guild_settings = await guild_manager.get_guild_settings(guild_id)
            current_role_id = guild_settings.get("manager_role_id")

            if not current_role_id:
                await interaction.followup.send(
                    "ℹ️ No manager role is currently set.",
                    ephemeral=True
                )
                return

            # Remove the manager role
            success = await guild_manager.update_guild_settings(
                guild_id,
                {"manager_role_id": None}
            )

            if success:
                embed = discord.Embed(
                    title="✅ Manager Role Removed",
                    description="The manager role has been removed. Only administrators can now manage bot settings.",
                    color=discord.Color.orange()
                )
                embed.set_footer(text=f"Removed by {interaction.user.name}")

                await interaction.followup.send(embed=embed, ephemeral=True)
                logger.info(
                    f"Manager role removed from guild {guild_id} by {interaction.user.id}"
                )
            else:
                await interaction.followup.send(
                    "❌ Failed to remove the manager role. Please try again.",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error removing manager role: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while removing the manager role.",
                ephemeral=True
            )

    @settings_group.command(name="view", description="View current guild settings")
    async def view_settings(self, interaction: discord.Interaction):
        """
        View the current guild settings.
        Available to all members.
        """
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = str(interaction.guild_id)
            guild_settings = await guild_manager.get_guild_settings(guild_id)
            is_premium = await guild_manager.is_premium_guild(guild_id)
            limits = await guild_manager.get_guild_limits(guild_id)

            embed = discord.Embed(
                title=f"⚙️ Settings for {interaction.guild.name}",
                color=discord.Color.gold() if is_premium else discord.Color.blurple()
            )

            # Premium status
            premium_status = "✅ Premium" if is_premium else "❌ Free Tier"
            embed.add_field(name="Premium Status", value=premium_status, inline=True)

            # Manager role
            manager_role_id = guild_settings.get("manager_role_id")
            if manager_role_id:
                manager_role = interaction.guild.get_role(int(manager_role_id))
                role_display = manager_role.mention if manager_role else f"<@&{manager_role_id}> (Role not found)"
            else:
                role_display = "Not set"
            embed.add_field(name="Manager Role", value=role_display, inline=True)

            # Log channel
            log_channel_id = guild_settings.get("master_log_channel_id")
            if log_channel_id:
                log_channel = self.bot.get_channel(int(log_channel_id))
                channel_display = log_channel.mention if log_channel else f"<#{log_channel_id}> (Channel not found)"
            else:
                channel_display = "Not set"
            embed.add_field(name="Log Channel", value=channel_display, inline=True)

            # Limits
            embed.add_field(
                name="Forwarding Rules",
                value=f"{limits.get('max_rules', 3)} max rules",
                inline=True
            )
            embed.add_field(
                name="Daily Message Limit",
                value=f"{limits.get('daily_limit', 100):,} messages/day",
                inline=True
            )

            # Features
            features = guild_settings.get("features", {})
            forwarding_status = "✅ Enabled" if features.get("forwarding_enabled", True) else "❌ Disabled"
            embed.add_field(name="Forwarding", value=forwarding_status, inline=True)

            embed.set_footer(text=f"Guild ID: {guild_id}")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error viewing settings: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while retrieving settings.",
                ephemeral=True
            )


async def setup(bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(GuildSettings(bot))
    logger.info("GuildSettings cog loaded")
