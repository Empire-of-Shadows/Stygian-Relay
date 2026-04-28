import discord
from discord.ext import commands
from discord import app_commands
from database import guild_manager, audit_log
from database.utils import ensure_utc
from datetime import datetime, timezone
import logging
import os
import re

logger = logging.getLogger(__name__)

BOT_OWNER_ID = os.getenv("BOT_OWNER_ID", "")


def _parse_admin_guild_ids() -> list[int]:
    """
    Comma-separated PREMIUM_ADMIN_GUILD_IDS env var. Falls back to the
    historical hard-coded admin guild for backward-compat.
    """
    raw = os.getenv("PREMIUM_ADMIN_GUILD_IDS", "").strip()
    if not raw:
        return [1326375497122320416]
    ids: list[int] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            ids.append(int(piece))
        except ValueError:
            logger.warning(f"Ignoring invalid PREMIUM_ADMIN_GUILD_IDS entry: {piece!r}")
    return ids or [1326375497122320416]


ADMIN_GUILD_IDS = _parse_admin_guild_ids()
_ADMIN_GUILD_OBJS = [discord.Object(id=g) for g in ADMIN_GUILD_IDS]

CODE_REGEX = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}")


class Premium(commands.Cog):
    """Premium subscription commands."""

    premium = app_commands.Group(name="premium", description="Premium subscription commands")

    def __init__(self, bot):
        self.bot = bot
        logger.info(f"Premium cog initialized (admin guilds: {ADMIN_GUILD_IDS})")

    @premium.command(name="status", description="Check the premium status of this server")
    async def premium_status(self, interaction: discord.Interaction):
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
                expires_at = ensure_utc(subscription.get("expires_at"))
                activated_at = ensure_utc(subscription.get("activated_at"))
                is_lifetime = subscription.get("is_lifetime", False)

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

                embed.description = (
                    "Upgrade to Premium to unlock:\n"
                    "• More forwarding rules\n"
                    "• Higher daily message limits\n"
                    "• Remove branding from forwarded messages\n"
                    "• Priority support"
                )

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error checking premium status: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while checking premium status.", ephemeral=True)

    @premium.command(name="redeem", description="Redeem a premium activation code")
    @app_commands.describe(code="The premium activation code (format: XXXX-XXXX-XXXX)")
    async def premium_redeem(self, interaction: discord.Interaction, code: str):
        """Redeem a premium code for the current guild."""
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        user_id = str(interaction.user.id)

        # Quick format reject so we don't audit malformed attempts as errors.
        normalized = code.upper().strip()
        if not CODE_REGEX.fullmatch(normalized):
            await interaction.followup.send(
                "❌ Invalid code format. Expected `XXXX-XXXX-XXXX`.",
                ephemeral=True
            )
            return

        try:
            result = await guild_manager.redeem_premium_code(normalized, guild_id, user_id)

            is_lifetime = result.get("is_lifetime", False)
            embed = discord.Embed(
                title="✅ Premium Activated!",
                description="Successfully activated premium for this server!",
                color=discord.Color.gold()
            )

            if is_lifetime:
                embed.add_field(name="Duration", value="🌟 **LIFETIME**", inline=True)
            else:
                expires_at = result.get("expires_at")
                if expires_at:
                    days = result.get("duration_days", 30)
                    embed.add_field(name="Duration", value=f"{days} days", inline=True)
                    embed.add_field(name="Expires", value=f"<t:{int(expires_at.timestamp())}:R>", inline=True)

            embed.set_footer(text=f"Activated by {interaction.user.name}")
            embed.timestamp = datetime.now(timezone.utc)

            await interaction.followup.send(embed=embed, ephemeral=True)

            await audit_log.log(
                category="premium",
                guild_id=guild_id,
                actor_id=user_id,
                action="redeem",
                payload={"code": normalized, "is_lifetime": is_lifetime,
                         "duration_days": result.get("duration_days")}
            )

            guild_settings = await guild_manager.get_guild_settings(guild_id)
            log_channel_id = guild_settings.get("master_log_channel_id")
            if log_channel_id:
                log_channel = self.bot.get_channel(int(log_channel_id))
                if log_channel:
                    log_embed = embed.copy()
                    log_embed.add_field(name="Code", value=f"||{normalized}||", inline=False)
                    try:
                        await log_channel.send(embed=log_embed)
                    except Exception as log_err:
                        logger.warning(
                            f"Failed to post premium redeem to log channel {log_channel_id} "
                            f"for guild {guild_id}: {log_err}"
                        )

        except ValueError as e:
            await audit_log.log(
                category="premium",
                guild_id=guild_id,
                actor_id=user_id,
                action="redeem_failed",
                payload={"reason": str(e), "code": normalized}
            )
            await interaction.followup.send(f"❌ {str(e)}", ephemeral=True)
        except Exception as e:
            logger.error(f"Error redeeming premium code: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while redeeming the premium code.",
                ephemeral=True
            )

    @app_commands.command(name="premium-generate", description="[ADMIN] Generate a premium activation code")
    @app_commands.guilds(*_ADMIN_GUILD_OBJS)
    @app_commands.describe(
        duration_days="Duration in days (default: 30, ignored if lifetime=True)",
        restrict_guild="Restrict code to this server only (default: False)",
        lifetime="Generate a lifetime premium code (default: False)",
        code_validity_days="How long the unredeemed code is valid (default: 90, 0 = no expiry)"
    )
    async def premium_generate(
        self,
        interaction: discord.Interaction,
        duration_days: int = 30,
        restrict_guild: bool = False,
        lifetime: bool = False,
        code_validity_days: int = 90,
    ):
        await interaction.response.defer(ephemeral=True)

        if str(interaction.user.id) != BOT_OWNER_ID:
            await interaction.followup.send(
                "❌ This command is only available to the bot owner.",
                ephemeral=True
            )
            return

        try:
            guild_id = str(interaction.guild_id) if restrict_guild else None
            user_id = str(interaction.user.id)

            code_data = await guild_manager.generate_premium_code(
                duration_days=duration_days,
                created_by=user_id,
                guild_id=guild_id,
                is_lifetime=lifetime,
                code_validity_days=code_validity_days if code_validity_days > 0 else None,
            )

            embed = discord.Embed(
                title="✅ Premium Code Generated",
                description="A new premium code has been created!",
                color=discord.Color.green()
            )
            embed.add_field(name="Code", value=f"||{code_data['code']}||", inline=False)

            if lifetime:
                embed.add_field(name="Duration", value="🌟 **LIFETIME**", inline=True)
            else:
                embed.add_field(name="Duration", value=f"{duration_days} days", inline=True)

            unredeemed_expiry = code_data.get("expires_at_unredeemed")
            if unredeemed_expiry:
                embed.add_field(
                    name="Code Expires (unredeemed)",
                    value=f"<t:{int(unredeemed_expiry.timestamp())}:R>",
                    inline=True
                )
            else:
                embed.add_field(name="Code Expires (unredeemed)", value="Never", inline=True)

            if restrict_guild:
                guild_name = interaction.guild.name if interaction.guild else "Unknown"
                embed.add_field(name="Restricted To", value=f"{guild_name} ({guild_id})", inline=False)
            else:
                embed.add_field(name="Usable In", value="Any server", inline=False)

            embed.set_footer(text=f"Generated by {interaction.user.name}")
            embed.timestamp = datetime.now(timezone.utc)

            await interaction.followup.send(embed=embed, ephemeral=True)

            await audit_log.log(
                category="premium",
                guild_id=guild_id,
                actor_id=user_id,
                action="generate",
                payload={
                    "code": code_data["code"],
                    "is_lifetime": lifetime,
                    "duration_days": duration_days,
                    "code_validity_days": code_validity_days,
                    "restrict_guild": restrict_guild,
                }
            )

        except Exception as e:
            logger.error(f"Error generating premium code: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while generating the premium code.",
                ephemeral=True
            )

    @app_commands.command(name="premium-deactivate", description="[ADMIN] Deactivate premium for this server")
    @app_commands.guilds(*_ADMIN_GUILD_OBJS)
    async def premium_deactivate(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

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
                await audit_log.log(
                    category="premium",
                    guild_id=guild_id,
                    actor_id=str(interaction.user.id),
                    action="deactivate",
                    payload={}
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
    @app_commands.guilds(*_ADMIN_GUILD_OBJS)
    @app_commands.describe(show_redeemed="Show redeemed codes (default: False)")
    async def premium_codes(self, interaction: discord.Interaction, show_redeemed: bool = False):
        await interaction.response.defer(ephemeral=True)

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
                await interaction.followup.send("ℹ️ No premium codes found.", ephemeral=True)
                return

            from extensions.common.views import PaginatedEmbedView

            def render(page_items, page_idx, total_pages):
                e = discord.Embed(
                    title="Premium Codes",
                    description=f"Showing {'all' if show_redeemed else 'unredeemed'} codes ({len(codes)} total)",
                    color=discord.Color.blue()
                )
                start_no = page_idx * 10 + 1
                for offset, code in enumerate(page_items):
                    status = "✅ Redeemed" if code.get("is_redeemed") else "⏳ Available"
                    is_lifetime = code.get("is_lifetime", False)
                    duration_str = "🌟 LIFETIME" if is_lifetime else f"{code.get('duration_days', 30)} days"

                    value_lines = [
                        f"**Code:** ||{code['code']}||",
                        f"**Duration:** {duration_str}",
                        f"**Status:** {status}",
                    ]

                    unredeemed_expiry = ensure_utc(code.get("expires_at_unredeemed"))
                    if unredeemed_expiry and not code.get("is_redeemed"):
                        value_lines.append(f"**Expires:** <t:{int(unredeemed_expiry.timestamp())}:R>")

                    if code.get("is_redeemed"):
                        redeemed_at = ensure_utc(code.get("redeemed_at"))
                        if redeemed_at:
                            value_lines.append(f"**Redeemed:** <t:{int(redeemed_at.timestamp())}:R>")

                    e.add_field(
                        name=f"Code #{start_no + offset}",
                        value="\n".join(value_lines),
                        inline=False
                    )
                e.set_footer(text=f"Page {page_idx + 1}/{total_pages}")
                return e

            view = PaginatedEmbedView(codes, render, page_size=10, author_id=interaction.user.id)
            await interaction.followup.send(embed=await view.initial_embed(), view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error listing premium codes: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while listing premium codes.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Premium(bot))
    logger.info("Premium cog loaded")
