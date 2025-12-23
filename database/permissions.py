"""
Permission checking utilities for guild settings management.

This module provides helper functions to check if a user has permission
to manage guild settings, including both administrator permissions and
the designated manager role.
"""
import discord
from typing import Optional
from database import guild_manager
import logging

logger = logging.getLogger(__name__)


async def can_manage_guild_settings(
    interaction: discord.Interaction,
    guild_id: Optional[str] = None
) -> bool:
    """
    Check if a user has permission to manage guild settings.

    A user can manage settings if they either:
    1. Have the Administrator permission in the guild, OR
    2. Have the designated manager role (if configured)

    Args:
        interaction: The Discord interaction object
        guild_id: Optional guild ID (defaults to interaction.guild_id)

    Returns:
        bool: True if the user can manage settings, False otherwise
    """
    if not interaction.guild:
        logger.warning("Interaction has no guild context")
        return False

    # Use provided guild_id or get from interaction
    gid = guild_id or str(interaction.guild_id)

    # Check if user is an administrator
    if interaction.user.guild_permissions.administrator:
        return True

    # Check if user has the manager role
    try:
        guild_settings = await guild_manager.get_guild_settings(gid)
        manager_role_id = guild_settings.get("manager_role_id")

        if manager_role_id:
            # Check if user has the manager role
            user_role_ids = [role.id for role in interaction.user.roles]
            if int(manager_role_id) in user_role_ids:
                logger.info(
                    f"User {interaction.user.id} has manager role {manager_role_id} "
                    f"in guild {gid}"
                )
                return True
    except Exception as e:
        logger.error(f"Error checking manager role: {e}", exc_info=True)

    return False


async def get_permission_error_message(
    interaction: discord.Interaction,
    guild_id: Optional[str] = None
) -> str:
    """
    Get an appropriate error message when a user lacks permission.

    Args:
        interaction: The Discord interaction object
        guild_id: Optional guild ID (defaults to interaction.guild_id)

    Returns:
        str: Error message explaining permission requirements
    """
    gid = guild_id or str(interaction.guild_id)

    try:
        guild_settings = await guild_manager.get_guild_settings(gid)
        manager_role_id = guild_settings.get("manager_role_id")

        if manager_role_id:
            # Get the role name
            guild = interaction.guild
            manager_role = guild.get_role(int(manager_role_id))
            role_mention = manager_role.mention if manager_role else f"<@&{manager_role_id}>"

            return (
                f"❌ You need to be a server administrator or have the {role_mention} "
                f"role to manage server settings."
            )
    except Exception as e:
        logger.error(f"Error getting permission error message: {e}", exc_info=True)

    # Default message if no manager role is configured
    return "❌ You need to be a server administrator to manage server settings."
