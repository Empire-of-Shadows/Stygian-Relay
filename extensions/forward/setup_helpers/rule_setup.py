"""
Forwarding rule configuration helpers.
"""
from typing import Dict, Any, List, Tuple
import discord


class RuleSetupHelper:
    """Handles forwarding rule configuration during setup."""

    async def create_initial_rule(self, source_channel_id: int,
                                  destination_channel_id: int,
                                  rule_name: str = None) -> Dict[str, Any]:
        """
        Create an initial forwarding rule with default settings.

        Args:
            source_channel_id: Channel to watch
            destination_channel_id: Channel to forward to
            rule_name: Optional custom name for the rule

        Returns:
            Rule configuration dictionary
        """
        if not rule_name:
            rule_name = f"Forward from #{source_channel_id} to #{destination_channel_id}"

        rule = {
            "name": rule_name,
            "source_channel_id": source_channel_id,
            "destination_channel_id": destination_channel_id,
            "is_active": True,
            "message_types": {
                "text": True,
                "media": True,
                "links": True,
                "embeds": True,
                "files": True,
                "stickers": False
            },
            "filters": {
                "require_keywords": [],
                "block_keywords": [],
                "min_length": 0,
                "max_length": 2000
            },
            "formatting": {
                "include_author": True,
                "add_prefix": "",
                "add_suffix": "",
                "forward_attachments": True,
                "forward_embeds": True,
                "forward_style": "c_v2"
            },
            "advanced_options": {
                "case_sensitive": False,
                "whole_word_only": False
            }
        }

        return rule

    async def validate_rule_configuration(self, rule: Dict[str, Any],
                                          guild: discord.Guild) -> Tuple[bool, List[str]]:
        """
        Validate a rule configuration.

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        # Check source channel
        source_channel = guild.get_channel(rule["source_channel_id"])
        if not source_channel:
            errors.append("Source channel not found")
        elif not isinstance(source_channel, discord.TextChannel):
            errors.append("Source channel must be a text channel")

        # Check destination channel
        dest_channel = guild.get_channel(rule["destination_channel_id"])
        if not dest_channel:
            errors.append("Destination channel not found")
        elif not isinstance(dest_channel, discord.TextChannel):
            errors.append("Destination channel must be a text channel")

        # Check if channels are different
        if rule["source_channel_id"] == rule["destination_channel_id"]:
            errors.append("Source and destination channels cannot be the same")

        # Check rule name
        if not rule["name"] or len(rule["name"]) > 100:
            errors.append("Rule name must be between 1 and 100 characters")

        # Check message types - at least one must be enabled
        enabled_types = [t for t, enabled in rule["message_types"].items() if enabled]
        if not enabled_types:
            errors.append("At least one message type must be enabled")

        return len(errors) == 0, errors

    async def create_rule_preview_embed(self, rule: Dict[str, Any],
                                        guild: discord.Guild) -> discord.Embed:
        """
        Create an embed preview of a forwarding rule.

        Args:
            rule: The rule configuration
            guild: The guild

        Returns:
            discord.Embed showing rule details
        """
        source_channel = guild.get_channel(rule["source_channel_id"])
        dest_channel = guild.get_channel(rule["destination_channel_id"])

        embed = discord.Embed(
            title="📋 Forwarding Rule Preview",
            description=f"**{rule['name']}**",
            color=discord.Color.green()
        )

        # Channel information
        embed.add_field(
            name="🔍 Source Channel",
            value=source_channel.mention if source_channel else "Unknown",
            inline=True
        )

        embed.add_field(
            name="📤 Destination Channel",
            value=dest_channel.mention if dest_channel else "Unknown",
            inline=True
        )

        # Message types
        enabled_types = []
        for msg_type, enabled in rule["message_types"].items():
            if enabled:
                enabled_types.append(f"• {msg_type.title()}")

        embed.add_field(
            name="📨 Message Types",
            value="\n".join(enabled_types) if enabled_types else "• None",
            inline=False
        )

        # Formatting options
        formatting_info = []
        if rule["formatting"]["include_author"]:
            formatting_info.append("• Include author")
        if rule["formatting"]["add_prefix"]:
            formatting_info.append(f"• Prefix: {rule['formatting']['add_prefix']}")
        if rule["formatting"]["add_suffix"]:
            formatting_info.append(f"• Suffix: {rule['formatting']['add_suffix']}")

        # Add forward style to preview
        style = rule["formatting"].get("forward_style", "c_v2")
        style_map = {
            "c_v2": "Component v2",
            "embed": "Embed",
            "text": "Plain Text"
        }
        formatting_info.append(f"• Style: {style_map.get(style, 'Unknown')}")

        embed.add_field(
            name="🎨 Formatting",
            value="\n".join(formatting_info) if formatting_info else "• Default formatting",
            inline=False
        )

        return embed

    async def get_rule_setup_buttons(self) -> discord.ui.View:
        """Get buttons for rule setup step."""
        from .button_manager import button_manager

        buttons = [
            {
                "label": "Create Rule",
                "style": button_manager.SUCCESS,
                "custom_id": "rule_create",
                "emoji": "✅"
            },
            {
                "label": "Edit Settings",
                "style": button_manager.PRIMARY,
                "custom_id": "rule_edit",
                "emoji": "⚙️"
            },
            {
                "label": "Back",
                "style": button_manager.SECONDARY,
                "custom_id": "rule_back",
                "emoji": "⬅️"
            },
            {
                "label": "Cancel",
                "style": button_manager.DANGER,
                "custom_id": "rule_cancel",
                "emoji": "✖️"
            }
        ]

        return button_manager.create_button_row(buttons)


# Global rule setup helper instance
rule_setup_helper = RuleSetupHelper()