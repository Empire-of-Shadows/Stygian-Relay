import discord
from discord.ext import commands
from discord import app_commands
from database import guild_manager
from datetime import datetime, timezone
import logging
import os

logger = logging.getLogger(__name__)

# Get bot owner ID from environment
BOT_OWNER_ID = os.getenv("BOT_OWNER_ID", "")

# Admin guild ID for owner-only commands
ADMIN_GUILD_ID = 1326375497122320416


class Premium(commands.Cog):
    """
    Premium subscription management cog.

    Provides commands for:
    - Generating premium codes (admin only)
    - Redeeming premium codes
    - Checking premium status
    - Managing premium subscriptions
    """

    def __init__(self, bot):
        self.bot = bot
        logger.info("Premium cog initialized")

    @app_commands.command(name="premium-status", description="Check the premium status of this server")
    async def premium_status(self, interaction: discord.Interaction):
        """Check if the current guild has an active premium subscription."""
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = str(interaction.guild_id)
            is_premium = await guild_manager.is_premium_guild(guild_id)
            subscription = await guild_manager.get_premium_subscription(guild_id)

            embed = discord.Embed(
                title="Premium Status",
                color=discord.Color.gold() if is_premium else discord.Color.blurple()
            )

            if is_premium and subscription:
                expires_at = subscription.get("expires_at")
                activated_at = subscription.get("activated_at")
                is_lifetime = subscription.get("is_lifetime", False)

                # Ensure datetimes are timezone-aware (MongoDB returns naive datetimes)
                if expires_at and expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if activated_at and activated_at.tzinfo is None:
                    activated_at = activated_at.replace(tzinfo=timezone.utc)

                # Display expiration based on whether it's lifetime
                if is_lifetime:
                    expires_str = "🌟 **LIFETIME**"
                elif expires_at:
                    days_remaining = (expires_at - datetime.now(timezone.utc)).days
                    expires_str = f"<t:{int(expires_at.timestamp())}:R> ({days_remaining} days remaining)"
                else:
                    expires_str = "Unknown"

                embed.add_field(name="Status", value="✅ Premium Active", inline=True)
                embed.add_field(name="Expires", value=expires_str, inline=True)

                if activated_at:
                    embed.add_field(
                        name="Activated",
                        value=f"<t:{int(activated_at.timestamp())}:R>",
                        inline=True
                    )

                limits = await guild_manager.get_guild_limits(guild_id)
                embed.add_field(name="Max Rules", value=str(limits.get("max_rules", 20)), inline=True)
                embed.add_field(name="Daily Limit", value=str(limits.get("daily_limit", 5000)), inline=True)

                embed.set_footer(text="Thank you for supporting Stygian Relay!")
            else:
                embed.add_field(name="Status", value="❌ Free Tier", inline=True)

                limits = await guild_manager.get_guild_limits(guild_id)
                embed.add_field(name="Max Rules", value=str(limits.get("max_rules", 3)), inline=True)
                embed.add_field(name="Daily Limit", value=str(limits.get("daily_limit", 100)), inline=True)

                embed.description = "Upgrade to Premium to unlock:\n" \
                                  "• More forwarding rules\n" \
                                  "• Higher daily message limits\n" \
                                  "• Remove branding from forwarded messages\n" \
                                  "• Priority support"

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error checking premium status: {e}", exc_info=True)
            await interaction.followup.send(
                "An error occurred while checking premium status.",
                ephemeral=True
            )

    @app_commands.command(name="premium-redeem", description="Redeem a premium activation code")
    @app_commands.describe(code="The premium activation code (format: XXXX-XXXX-XXXX)")
    async def premium_redeem(self, interaction: discord.Interaction, code: str):
        """Redeem a premium code for the current guild."""
        await interaction.response.defer(ephemeral=True)

        try:
            guild_id = str(interaction.guild_id)
            user_id = str(interaction.user.id)

            # Check if user has permission (admin only)
            if not interaction.user.guild_permissions.administrator:
                await interaction.followup.send(
                    "❌ You must be a server administrator to redeem premium codes.",
                    ephemeral=True
                )
                return

            # Redeem the code
            result = await guild_manager.redeem_premium_code(code, guild_id, user_id)

            # Create success embed
            is_lifetime = result.get("is_lifetime", False)
            embed = discord.Embed(
                title="✅ Premium Activated!",
                description="Successfully activated premium for this server!",
                color=discord.Color.gold()
            )

            if is_lifetime:
                embed.add_field(
                    name="Duration",
                    value="🌟 **LIFETIME**",
                    inline=True
                )
            else:
                expires_at = result.get("expires_at")
                if expires_at:
                    days = result.get("duration_days", 30)
                    embed.add_field(
                        name="Duration",
                        value=f"{days} days",
                        inline=True
                    )
                    embed.add_field(
                        name="Expires",
                        value=f"<t:{int(expires_at.timestamp())}:R>",
                        inline=True
                    )

            embed.set_footer(text=f"Activated by {interaction.user.name}")
            embed.timestamp = datetime.now(timezone.utc)

            await interaction.followup.send(embed=embed, ephemeral=True)

            # Log to guild's log channel if configured
            guild_settings = await guild_manager.get_guild_settings(guild_id)
            log_channel_id = guild_settings.get("master_log_channel_id")
            if log_channel_id:
                log_channel = self.bot.get_channel(int(log_channel_id))
                if log_channel:
                    log_embed = embed.copy()
                    log_embed.add_field(
                        name="Code",
                        value=f"||{code}||",
                        inline=False
                    )
                    try:
                        await log_channel.send(embed=log_embed)
                    except Exception:
                        pass  # Silently fail if we can't send to log channel

        except ValueError as e:
            # Invalid code or already redeemed
            await interaction.followup.send(
                f"❌ {str(e)}",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error redeeming premium code: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while redeeming the premium code.",
                ephemeral=True
            )

    @app_commands.command(name="premium-generate", description="[ADMIN] Generate a premium activation code")
    @app_commands.guilds(ADMIN_GUILD_ID)
    @app_commands.describe(
        duration_days="Duration in days (default: 30, ignored if lifetime=True)",
        restrict_guild="Restrict code to this server only (default: False)",
        lifetime="Generate a lifetime premium code (default: False)"
    )
    async def premium_generate(
        self,
        interaction: discord.Interaction,
        duration_days: int = 30,
        restrict_guild: bool = False,
        lifetime: bool = False
    ):
        """Generate a premium code. Only available to bot owner."""
        await interaction.response.defer(ephemeral=True)

        # Check if user is bot owner
        if str(interaction.user.id) != BOT_OWNER_ID:
            await interaction.followup.send(
                "❌ This command is only available to the bot owner.",
                ephemeral=True
            )
            return

        try:
            guild_id = str(interaction.guild_id) if restrict_guild else None
            user_id = str(interaction.user.id)

            # Generate the code
            code_data = await guild_manager.generate_premium_code(
                duration_days=duration_days,
                created_by=user_id,
                guild_id=guild_id,
                is_lifetime=lifetime
            )

            # Create response embed
            embed = discord.Embed(
                title="✅ Premium Code Generated",
                description=f"A new premium code has been created!",
                color=discord.Color.green()
            )

            embed.add_field(
                name="Code",
                value=f"||{code_data['code']}||",
                inline=False
            )

            # Display duration based on whether it's lifetime
            if lifetime:
                embed.add_field(name="Duration", value="🌟 **LIFETIME**", inline=True)
            else:
                embed.add_field(name="Duration", value=f"{duration_days} days", inline=True)

            if restrict_guild:
                guild_name = interaction.guild.name if interaction.guild else "Unknown"
                embed.add_field(
                    name="Restricted To",
                    value=f"{guild_name} ({guild_id})",
                    inline=False
                )
            else:
                embed.add_field(
                    name="Usable In",
                    value="Any server",
                    inline=False
                )

            embed.set_footer(text=f"Generated by {interaction.user.name}")
            embed.timestamp = datetime.now(timezone.utc)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error generating premium code: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while generating the premium code.",
                ephemeral=True
            )

    @app_commands.command(name="premium-deactivate", description="[ADMIN] Deactivate premium for this server")
    @app_commands.guilds(ADMIN_GUILD_ID)
    async def premium_deactivate(self, interaction: discord.Interaction):
        """Deactivate premium subscription for the current guild. Bot owner only."""
        await interaction.response.defer(ephemeral=True)

        # Check if user is bot owner
        if str(interaction.user.id) != BOT_OWNER_ID:
            await interaction.followup.send(
                "❌ This command is only available to the bot owner.",
                ephemeral=True
            )
            return

        try:
            guild_id = str(interaction.guild_id)
            success = await guild_manager.deactivate_premium(guild_id)

            if success:
                await interaction.followup.send(
                    "✅ Premium subscription has been deactivated for this server.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "ℹ️ This server does not have an active premium subscription.",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error deactivating premium: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while deactivating premium.",
                ephemeral=True
            )

    @app_commands.command(name="premium-codes", description="[ADMIN] List all premium codes")
    @app_commands.guilds(ADMIN_GUILD_ID)
    @app_commands.describe(show_redeemed="Show redeemed codes (default: False)")
    async def premium_codes(self, interaction: discord.Interaction, show_redeemed: bool = False):
        """List all premium codes created by the bot owner."""
        await interaction.response.defer(ephemeral=True)

        # Check if user is bot owner
        if str(interaction.user.id) != BOT_OWNER_ID:
            await interaction.followup.send(
                "❌ This command is only available to the bot owner.",
                ephemeral=True
            )
            return

        try:
            user_id = str(interaction.user.id)
            codes = await guild_manager.list_premium_codes(
                created_by=user_id,
                include_redeemed=show_redeemed
            )

            if not codes:
                await interaction.followup.send(
                    "ℹ️ No premium codes found.",
                    ephemeral=True
                )
                return

            # Create embed with code list
            embed = discord.Embed(
                title="Premium Codes",
                description=f"Showing {'all' if show_redeemed else 'unredeemed'} codes",
                color=discord.Color.blue()
            )

            for i, code in enumerate(codes[:10], 1):  # Limit to 10 codes
                status = "✅ Redeemed" if code.get("is_redeemed") else "⏳ Available"
                is_lifetime = code.get("is_lifetime", False)

                # Display duration
                if is_lifetime:
                    duration_str = "🌟 LIFETIME"
                else:
                    duration = code.get("duration_days", 30)
                    duration_str = f"{duration} days"

                value_lines = [
                    f"**Code:** ||{code['code']}||",
                    f"**Duration:** {duration_str}",
                    f"**Status:** {status}"
                ]

                if code.get("is_redeemed"):
                    redeemed_at = code.get("redeemed_at")
                    if redeemed_at:
                        value_lines.append(f"**Redeemed:** <t:{int(redeemed_at.timestamp())}:R>")

                embed.add_field(
                    name=f"Code #{i}",
                    value="\n".join(value_lines),
                    inline=False
                )

            if len(codes) > 10:
                embed.set_footer(text=f"Showing 10 of {len(codes)} codes")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error listing premium codes: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while listing premium codes.",
                ephemeral=True
            )


async def setup(bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(Premium(bot))
    logger.info("Premium cog loaded")