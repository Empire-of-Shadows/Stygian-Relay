from typing import Dict, Any, List, Tuple
import discord


class RuleSetupHelper:
    """A collection of static methods to assist with rule configuration."""

    @staticmethod
    async def create_initial_rule(source_channel_id: int,
                                  destination_channel_id: int,
                                  rule_name: str = None) -> Dict[str, Any]:
        """
        Creates a dictionary representing a new forwarding rule with default settings.

        Args:
            source_channel_id: The ID of the channel to watch for messages.
            destination_channel_id: The ID of the channel to forward messages to.
            rule_name: An optional custom name for the rule.

        Returns:
            A dictionary containing the complete default configuration for a new rule.
        """
        if not rule_name:
            rule_name = f"Forward from #{source_channel_id} to #{destination_channel_id}"

        # This dictionary represents the default state for any new rule.
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
                "forward_style": "native"
            },
            "advanced_options": {
                "case_sensitive": False,
                "whole_word_only": False
            }
        }
        return rule

    @staticmethod
    async def validate_rule_configuration(rule: Dict[str, Any],
                                          guild: discord.Guild) -> Tuple[bool, List[str]]:
        """
        Validates a rule configuration to ensure it's logical and complete.
        This method is called before saving a rule to the database.

        Returns:
            A tuple containing a boolean indicating validity and a list of error messages.
        """
        errors = []

        source_channel = guild.get_channel(rule["source_channel_id"])
        if not source_channel:
            errors.append("Source channel not found")
        elif not isinstance(source_channel, discord.TextChannel):
            errors.append("Source channel must be a text channel")

        dest_channel = guild.get_channel(rule["destination_channel_id"])
        if not dest_channel:
            errors.append("Destination channel not found")
        elif not isinstance(dest_channel, discord.TextChannel):
            errors.append("Destination channel must be a text channel")

        if rule["source_channel_id"] == rule["destination_channel_id"]:
            errors.append("Source and destination channels cannot be the same")

        if not rule["name"] or len(rule["name"]) > 100:
            errors.append("Rule name must be between 1 and 100 characters")

        enabled_types = [t for t, enabled in rule["message_types"].items() if enabled]
        if not enabled_types:
            errors.append("At least one message type must be enabled")

        return len(errors) == 0, errors

    @staticmethod
    async def create_rule_preview_embed(rule: Dict[str, Any],
                                        guild: discord.Guild) -> discord.Embed:
        """
        Creates a user-friendly embed that summarizes a rule's configuration.
        This embed is shown to the user before they save a rule.

        Args:
            rule: The rule configuration dictionary.
            guild: The guild where the rule is being created.

        Returns:
            A discord.Embed object for previewing the rule.
        """
        source_channel = guild.get_channel(rule["source_channel_id"])
        dest_channel = guild.get_channel(rule["destination_channel_id"])

        embed = discord.Embed(
            title="📋 Forwarding Rule Preview",
            description=f"**{rule['name']}**",
            color=discord.Color.green()
        )

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

        enabled_types = [f"• {msg_type.title()}" for msg_type, enabled in rule["message_types"].items() if enabled]
        embed.add_field(
            name="📨 Message Types",
            value="\n".join(enabled_types) if enabled_types else "• None",
            inline=False
        )

        formatting_info = []
        if rule["formatting"]["include_author"]:
            formatting_info.append("• Include author")
        if rule["formatting"]["add_prefix"]:
            formatting_info.append(f"• Prefix: {rule['formatting']['add_prefix']}")
        if rule["formatting"]["add_suffix"]:
            formatting_info.append(f"• Suffix: {rule['formatting']['add_suffix']}")

        # Map the internal style name to a user-friendly display name.
        style = rule["formatting"].get("forward_style", "native")
        style_map = {"native": "Native Style", "c_v2": "Component v2", "embed": "Embed", "text": "Plain Text"}
        formatting_info.append(f"• Style: {style_map.get(style, 'Unknown')}")

        embed.add_field(
            name="🎨 Formatting",
            value="\n".join(formatting_info) if formatting_info else "• Default formatting",
            inline=False
        )
        return embed

    @staticmethod
    async def get_rule_setup_buttons() -> discord.ui.View:
        """
        Creates a view with buttons for the rule setup step.
        This view is shown to the user when they are creating a new rule.
        """
        from .button_manager import button_manager

        buttons = [
            {"label": "Create Rule", "style": button_manager.SUCCESS, "custom_id": "rule_create", "emoji": "✅"},
            {"label": "Edit Settings", "style": button_manager.PRIMARY, "custom_id": "rule_edit", "emoji": "⚙️"},
            {"label": "Back", "style": button_manager.SECONDARY, "custom_id": "rule_back", "emoji": "⬅️"},
            {"label": "Cancel", "style": button_manager.DANGER, "custom_id": "rule_cancel", "emoji": "✖️"}
        ]
        return button_manager.create_button_row(buttons)

# Make the helper class available for import.
rule_setup_helper = RuleSetupHelper()