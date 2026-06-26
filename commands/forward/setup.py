"""
This module contains the primary user-facing setup wizard for configuring
message forwarding rules. It uses a state machine and various discord.ui
components to guide the user through a multi-step configuration process.
"""
import asyncio
import discord
import json
from discord.ext import commands

import logging
from .setup_helpers.state_manager import state_manager
from .setup_helpers.button_manager import button_manager
from .setup_helpers.permission_check import permission_checker
from .setup_helpers.channel_select import channel_selector
from .setup_helpers.rule_creation_flow import RuleCreationFlow
from .setup_helpers.interaction_utils import safe_respond
from .models.setup_state import SetupState
from .views import CustomView
from database import guild_manager
from database.permissions import can_manage_guild_settings, get_permission_error_message

logger = logging.getLogger(__name__)


def normalize_channel_id(channel_id):
    """
    Normalize channel ID from various formats (int, str, BSON) to int.
    Handles MongoDB BSON format: {"$numberLong": "123456"}
    """
    if isinstance(channel_id, dict) and "$numberLong" in channel_id:
        return int(channel_id["$numberLong"])
    return int(channel_id) if channel_id else None


class RuleDeleteView(CustomView):
    """
    A view that displays a dropdown menu for selecting a rule to delete.
    This view is used by the `/forward delete_rule` command.
    """

    def __init__(self, rules: list, cog: 'ForwardCog'):
        super().__init__(timeout=180)
        self.cog = cog
        self.rules = {str(rule['rule_id']): rule for rule in rules}

        # Create select options for each rule
        options = []
        for rule in rules[:25]:  # Discord limit of 25 options
            rule_name = rule.get('rule_name', f"Rule {rule['rule_id'][:8]}...")

            # Get channel names for description
            source_channel = cog.bot.get_channel(int(rule.get("source_channel_id", 0)))
            destination_channel = cog.bot.get_channel(int(rule.get("destination_channel_id", 0)))

            source_name = f"#{source_channel.name}" if source_channel else "Unknown Channel"
            dest_name = f"#{destination_channel.name}" if destination_channel else "Unknown Channel"

            status = "🟢" if rule.get("is_active", False) else "🔴"

            options.append(
                discord.SelectOption(
                    label=f"{status} {rule_name}"[:100],
                    value=str(rule['rule_id']),
                    description=f"From {source_name} → {dest_name}"[:100]
                )
            )

        if not options:
            # Add a disabled option if no rules
            self.add_item(discord.ui.Button(label="No rules found to delete", disabled=True))
            return

        rule_select = discord.ui.Select(
            placeholder="Choose a rule to delete...",
            options=options,
            custom_id="rule_delete_select"
        )
        rule_select.callback = self.select_callback
        self.add_item(rule_select)

        # Add cancel button
        cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            emoji="❌"
        )
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def select_callback(self, interaction: discord.Interaction):
        """
        Callback for when a rule is selected for deletion.
        Shows a confirmation dialog before deleting.
        """
        rule_id = interaction.data['values'][0]
        selected_rule = self.rules.get(rule_id)

        if not selected_rule:
            await interaction.response.send_message("❌ Could not find the selected rule.", ephemeral=True)
            return

        # Create confirmation view
        confirm_view = RuleDeleteConfirmView(selected_rule, self.cog)

        # Get channel info for display
        source_channel = self.cog.bot.get_channel(int(selected_rule.get("source_channel_id", 0)))
        destination_channel = self.cog.bot.get_channel(int(selected_rule.get("destination_channel_id", 0)))

        source_name = source_channel.mention if source_channel else f"<#{selected_rule.get('source_channel_id')}>"
        dest_name = destination_channel.mention if destination_channel else f"<#{selected_rule.get('destination_channel_id')}>"

        rule_name = selected_rule.get('rule_name', 'Unnamed Rule')
        status = "🟢 Active" if selected_rule.get("is_active", False) else "🔴 Inactive"

        embed = discord.Embed(
            title="⚠️ Confirm Rule Deletion",
            description="Are you sure you want to delete this forwarding rule? This action cannot be undone.",
            color=discord.Color.orange()
        )

        embed.add_field(name="Rule Name", value=rule_name, inline=False)
        embed.add_field(name="Status", value=status, inline=True)
        embed.add_field(name="Rule ID", value=f"`{rule_id}`", inline=True)
        embed.add_field(name="Source Channel", value=source_name, inline=False)
        embed.add_field(name="Destination Channel", value=dest_name, inline=False)

        await interaction.response.edit_message(embed=embed, view=confirm_view)

    async def cancel_callback(self, interaction: discord.Interaction):
        """Cancel the deletion process"""
        embed = discord.Embed(
            title="❌ Deletion Cancelled",
            description="No rules were deleted.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class RuleDeleteConfirmView(discord.ui.LayoutView):
    """
    Confirmation LayoutView (Components v2) for rule deletion with
    Deactivate / Permanently Delete / Cancel options.
    """

    def __init__(self, rule: dict, cog: 'ForwardCog', on_exit=None):
        super().__init__(timeout=60)
        self.rule = rule
        self.cog = cog
        self.on_exit = on_exit

        rule_name = rule.get("rule_name", "Unnamed Rule")
        self.add_item(discord.ui.TextDisplay("## ⚠️ Confirm Rule Deletion"))
        self.add_item(discord.ui.TextDisplay(
            f"Are you sure you want to delete **{rule_name}**?\n\n"
            "**Deactivate** keeps the rule but stops it from forwarding.\n"
            "**Permanently Delete** removes the rule entirely (cannot be undone)."
        ))
        self.add_item(discord.ui.Separator())

        row = discord.ui.ActionRow()
        deactivate_button = discord.ui.Button(
            label="Deactivate Rule", style=discord.ButtonStyle.secondary, emoji="🔴"
        )
        deactivate_button.callback = self.deactivate_callback
        row.add_item(deactivate_button)

        delete_button = discord.ui.Button(
            label="Permanently Delete", style=discord.ButtonStyle.danger, emoji="🗑️"
        )
        delete_button.callback = self.delete_callback
        row.add_item(delete_button)

        cancel_button = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.primary, emoji="❌"
        )
        cancel_button.callback = self.cancel_callback
        row.add_item(cancel_button)
        self.add_item(row)

    async def deactivate_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            rule_id = self.rule.get('rule_id')
            success = await guild_manager.delete_rule(rule_id)
            if success:
                logger.info(f"Rule {rule_id} deactivated in guild {interaction.guild.id}")
                await state_manager.cleanup_session(interaction.guild_id)
                if self.on_exit is not None:
                    await self.on_exit(interaction)
                    return
                await self._show_terminal(
                    interaction,
                    "## ✅ Rule Deactivated",
                    f"**{self.rule.get('rule_name', 'Unnamed Rule')}** is now inactive and will not forward messages.",
                )
            else:
                await self._show_error(interaction, "Failed to deactivate the rule.")
        except Exception as e:
            logger.error(f"Error deactivating rule: {e}", exc_info=True)
            await self._show_error(interaction, "An error occurred while deactivating the rule.")

    async def delete_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            rule_id = self.rule.get('rule_id')
            guild_id = str(interaction.guild.id)
            success = await guild_manager.permanently_delete_rule(guild_id, rule_id)
            if success:
                logger.info(f"Rule {rule_id} permanently deleted from guild {guild_id}")
                await state_manager.cleanup_session(interaction.guild_id)
                if self.on_exit is not None:
                    await self.on_exit(interaction)
                    return
                await self._show_terminal(
                    interaction,
                    "## ✅ Rule Permanently Deleted",
                    f"**{self.rule.get('rule_name', 'Unnamed Rule')}** has been removed from the database.",
                )
            else:
                await self._show_error(interaction, "Failed to permanently delete the rule.")
        except Exception as e:
            logger.error(f"Error permanently deleting rule: {e}", exc_info=True)
            await self._show_error(interaction, "An error occurred while deleting the rule.")

    async def cancel_callback(self, interaction: discord.Interaction):
        if self.on_exit is not None:
            session = await state_manager.get_session(interaction.guild_id)
            if session and session.current_rule:
                view = RuleSettingsView(session, self.cog, interaction.guild)
                await interaction.response.edit_message(view=view)
                return
        await self._show_terminal(
            interaction,
            "## ❌ Action Cancelled",
            "No changes were made to the rule.",
            edit=True,
        )

    async def _show_terminal(self, interaction: discord.Interaction, title: str, body: str, edit: bool = False):
        layout = discord.ui.LayoutView()
        layout.add_item(discord.ui.TextDisplay(title))
        layout.add_item(discord.ui.TextDisplay(body))
        if edit:
            await interaction.response.edit_message(view=layout)
        else:
            await interaction.edit_original_response(view=layout)

    async def _show_error(self, interaction: discord.Interaction, message: str):
        await self._show_terminal(interaction, "## ❌ Error", message)

class LearnMoreView(CustomView):
    """View for the Learn More section with proper button callbacks"""

    def __init__(self, cog: 'ForwardCog', session: SetupState):
        super().__init__(timeout=300)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Start Setup", style=discord.ButtonStyle.success, emoji="🚀") # Type: Ignore
    async def start_setup_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle Start Setup button"""
        try:
            await interaction.response.defer(ephemeral=True)
            await self.cog.show_permission_step(interaction, self.session)
        except Exception as e:
            self.cog.logger.error(f"Error in start setup button: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)

    @discord.ui.button(label="Back to Welcome", style=discord.ButtonStyle.secondary, emoji="⬅️") # Type: Ignore
    async def back_to_welcome_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle Back to Welcome button"""
        try:
            await interaction.response.defer(ephemeral=True) # Type: Ignore
            await self.cog.show_welcome_step(interaction, self.session)
        except Exception as e:
            self.cog.logger.error(f"Error in back to welcome button: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)


class RuleSelectView(CustomView):
    """
    A view that displays a dropdown menu for selecting a rule to edit.
    This view is used by the `/forward edit` command.
    """

    def __init__(self, rules: list, cog: 'ForwardCog'):
        super().__init__(timeout=180)
        self.cog = cog
        self.rules = {str(rule['rule_id']): rule for rule in rules}

        options = [
            discord.SelectOption(
                label=rule.get('rule_name', f"Rule {rule['rule_id']}")[:100],
                value=str(rule['rule_id'])
            )
            for rule in rules
        ]

        if not options:
            self.add_item(discord.ui.Button(label="No rules found to edit.", disabled=True))
            return

        rule_select = discord.ui.Select(
            placeholder="Choose a rule to edit...",
            options=options,
            custom_id="rule_edit_select"
        )
        rule_select.callback = self.select_callback
        self.add_item(rule_select)

    async def select_callback(self, interaction: discord.Interaction):
        """
        Callback for when a rule is selected. It loads the selected rule
        into the user's session and transitions them to the rule preview step.
        """
        rule_id_str = interaction.data['values'][0]
        selected_rule = self.rules.get(rule_id_str)

        if not selected_rule:
            await interaction.followup.send("❌ Could not find the selected rule.", ephemeral=True)
            return

        session = await state_manager.create_session(interaction.guild_id, interaction.user.id)
        session.current_rule = selected_rule
        session.is_editing = True

        await state_manager.update_session(interaction.guild_id, {
            "current_rule": session.current_rule,
            "is_editing": True,
            "step": "rule_preview"
        })

        await self.cog.rule_creation_flow.show_rule_preview_step(interaction, session)


class EditChannelsView(discord.ui.LayoutView):
    """Components v2 LayoutView for editing source/destination channels of a rule."""

    def __init__(self, session: SetupState, cog: 'ForwardCog'):
        super().__init__(timeout=300)
        self.session = session
        self.cog = cog
        self._build()

    def _build(self):
        source_id = normalize_channel_id(self.session.current_rule.get("source_channel_id"))
        dest_id = normalize_channel_id(self.session.current_rule.get("destination_channel_id"))
        src_text = f"<#{source_id}>" if source_id else "Not Set"
        dst_text = f"<#{dest_id}>" if dest_id else "Not Set"

        self.add_item(discord.ui.TextDisplay("## 🔄 Edit Channels"))
        self.add_item(discord.ui.TextDisplay(
            "Select new source and destination channels for this rule."
        ))
        self.add_item(discord.ui.Separator())
        self.add_item(discord.ui.TextDisplay(
            f"**Current Source:** {src_text}\n**Current Destination:** {dst_text}"
        ))
        self.add_item(discord.ui.Separator())

        source_select = discord.ui.ChannelSelect(
            placeholder="Select new source channel...",
            channel_types=[discord.ChannelType.text],
        )
        source_select.callback = self.source_select_callback
        src_row = discord.ui.ActionRow()
        src_row.add_item(source_select)
        self.add_item(src_row)

        dest_select = discord.ui.ChannelSelect(
            placeholder="Select new destination channel...",
            channel_types=[discord.ChannelType.text],
        )
        dest_select.callback = self.dest_select_callback
        dst_row = discord.ui.ActionRow()
        dst_row.add_item(dest_select)
        self.add_item(dst_row)

        nav_row = discord.ui.ActionRow()
        back_button = discord.ui.Button(
            label="Back to Main Settings", style=discord.ButtonStyle.primary
        )
        back_button.callback = self.back_to_main_settings_callback
        nav_row.add_item(back_button)
        self.add_item(nav_row)

    async def source_select_callback(self, interaction: discord.Interaction):
        channel_id = int(interaction.data['values'][0])
        dest_id = normalize_channel_id(self.session.current_rule.get("destination_channel_id"))

        if channel_id == dest_id:
            await interaction.response.send_message(
                "Source and destination channels cannot be the same.", ephemeral=True
            )
            return

        self.session.current_rule["source_channel_id"] = channel_id
        await state_manager.update_session(
            interaction.guild_id, {"current_rule": self.session.current_rule}
        )

        await interaction.response.edit_message(view=EditChannelsView(self.session, self.cog))

    async def dest_select_callback(self, interaction: discord.Interaction):
        channel_id = int(interaction.data['values'][0])
        source_id = normalize_channel_id(self.session.current_rule.get("source_channel_id"))

        if channel_id == source_id:
            await interaction.response.send_message(
                "Source and destination channels cannot be the same.", ephemeral=True
            )
            return

        self.session.current_rule["destination_channel_id"] = channel_id
        await state_manager.update_session(
            interaction.guild_id, {"current_rule": self.session.current_rule}
        )

        await interaction.response.edit_message(view=EditChannelsView(self.session, self.cog))

    async def back_to_main_settings_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            view=RuleSettingsView(self.session, self.cog, interaction.guild)
        )


class RuleSettingsView(discord.ui.LayoutView):
    """Components v2 LayoutView for editing all settings of a rule."""

    def __init__(self, session: SetupState, cog: 'ForwardCog', guild: discord.Guild | None = None):
        super().__init__(timeout=300)
        self.session = session
        self.cog = cog
        self._guild = guild
        self._build()

    def _build(self):
        rule = self.session.current_rule
        rule_name = rule.get("rule_name", "Not Set")
        is_active_text = "🟢 Active" if rule.get("is_active", True) else "🔴 Inactive"

        source_text = "Not Set"
        dest_text = "Not Set"
        if self._guild:
            source_id = normalize_channel_id(rule.get("source_channel_id"))
            if source_id:
                ch = self._guild.get_channel(source_id)
                source_text = ch.mention if ch else f"ID: {source_id} (Not Found)"
            dest_id = normalize_channel_id(rule.get("destination_channel_id"))
            if dest_id:
                ch = self._guild.get_channel(dest_id)
                dest_text = ch.mention if ch else f"ID: {dest_id} (Not Found)"
        else:
            source_id = normalize_channel_id(rule.get("source_channel_id"))
            dest_id = normalize_channel_id(rule.get("destination_channel_id"))
            if source_id:
                source_text = f"<#{source_id}>"
            if dest_id:
                dest_text = f"<#{dest_id}>"

        self.add_item(discord.ui.TextDisplay(f"## Editing Rule: {rule_name}"))
        self.add_item(discord.ui.TextDisplay(
            "Select a category to edit. Changes are saved to the session automatically.\n"
            "Go back to the preview screen to save them to the database."
        ))
        self.add_item(discord.ui.Separator())
        self.add_item(discord.ui.TextDisplay(
            f"**Status:** {is_active_text}\n"
            f"**Source:** {source_text}\n"
            f"**Destination:** {dest_text}"
        ))
        self.add_item(discord.ui.Separator())

        edit_row = discord.ui.ActionRow()
        name_button = discord.ui.Button(
            label="Name", style=discord.ButtonStyle.secondary, emoji="📝"
        )
        name_button.callback = self.edit_name_callback
        edit_row.add_item(name_button)

        channels_button = discord.ui.Button(
            label="Channels", style=discord.ButtonStyle.secondary, emoji="🔄"
        )
        channels_button.callback = self.edit_channels_callback
        edit_row.add_item(channels_button)

        active_label = "Deactivate" if rule.get("is_active", True) else "Activate"
        active_style = (
            discord.ButtonStyle.danger if rule.get("is_active", True)
            else discord.ButtonStyle.success
        )
        active_button = discord.ui.Button(label=active_label, style=active_style, emoji="⚡")
        active_button.callback = self.toggle_active_callback
        edit_row.add_item(active_button)
        self.add_item(edit_row)

        nav_row = discord.ui.ActionRow()
        save_button = discord.ui.Button(
            label="Save and Exit", style=discord.ButtonStyle.success
        )
        save_button.callback = self.save_and_exit_callback
        nav_row.add_item(save_button)

        back_button = discord.ui.Button(
            label="Back to Preview", style=discord.ButtonStyle.primary
        )
        back_button.callback = self.back_to_preview_callback
        nav_row.add_item(back_button)

        delete_button = discord.ui.Button(
            label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️"
        )
        delete_button.callback = self.delete_callback
        nav_row.add_item(delete_button)
        self.add_item(nav_row)

    async def edit_name_callback(self, interaction: discord.Interaction):
        from .models.rule_modals import RuleNameModal

        async def modal_callback(modal_interaction: discord.Interaction, name: str):
            self.session.current_rule["rule_name"] = name
            await state_manager.update_session(
                modal_interaction.guild_id, {"current_rule": self.session.current_rule}
            )
            await modal_interaction.response.edit_message(
                view=RuleSettingsView(self.session, self.cog, modal_interaction.guild)
            )

        modal = RuleNameModal(
            modal_callback, current_name=self.session.current_rule.get("rule_name")
        )
        await interaction.response.send_modal(modal)

    async def edit_channels_callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=EditChannelsView(self.session, self.cog))

    async def toggle_active_callback(self, interaction: discord.Interaction):
        current_status = self.session.current_rule.get("is_active", True)
        self.session.current_rule["is_active"] = not current_status
        await state_manager.update_session(
            interaction.guild_id, {"current_rule": self.session.current_rule}
        )
        await interaction.response.edit_message(
            view=RuleSettingsView(self.session, self.cog, interaction.guild)
        )

    async def back_to_preview_callback(self, interaction: discord.Interaction):
        await self.cog.rule_creation_flow.show_rule_preview_step(interaction, self.session)

    async def save_and_exit_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        if self.session.is_editing and self.session.current_rule.get("rule_id"):
            success, message = await self.cog.update_final_rule(interaction, self.session)
        else:
            success, message = await self.cog.rule_creation_flow.create_final_rule(
                interaction, self.session
            )
        if success:
            await self.cog.show_setup_complete(
                interaction, self.session, is_editing=self.session.is_editing
            )
        else:
            await interaction.followup.send(f"❌ Save failed: {message}", ephemeral=True)

    async def delete_callback(self, interaction: discord.Interaction):
        rule = self.session.current_rule
        confirm_view = RuleDeleteConfirmView(rule, self.cog, on_exit=self.session.on_exit)
        await interaction.response.edit_message(view=confirm_view)


class ForwardCog(commands.Cog):
    """
    This cog manages the /forward slash command group for setting up and
    editing forwarding rules. It uses a state machine to guide the user
    through a multi-step configuration process.
    """
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("Forward")
        self.guild_manager = guild_manager
        self.rule_creation_flow = RuleCreationFlow(bot, self)

    async def cog_load(self):
        """Called when the cog is loaded."""
        self.logger.info("Forward cog loaded")
        # Idle session eviction is handled by a Mongo TTL index on
        # `setup_sessions.expires_at` (see state_manager.ensure_collection_exists).
        # No Python-side polling loop needed.

    async def show_welcome_step(self, interaction: discord.Interaction, session: SetupState):
        """
        Show the welcome step of setup.
        This is the first step of the setup wizard.
        """
        embed = discord.Embed(
            title="🤖 Welcome to Message Forwarding Setup!",
            description=(
                "I'll help you set up automatic message forwarding between channels.\n\n"
                "**What we'll configure:**\n"
                "• Required permissions check\n"
                "• Log channel for errors and notifications\n"
                "• Your first forwarding rule\n"
                "• Optional advanced features\n\n"
                "This should take about 2-3 minutes to complete."
            ),
            color=discord.Color.blue()
        )

        progress = session.get_progress()
        embed.add_field(
            name="📊 Progress",
            value=f"{progress:.0%} complete",
            inline=True
        )
        embed.set_footer(text="Click 'Start Setup' to begin!")

        view = button_manager.get_welcome_buttons()

        await safe_respond(interaction, embed=embed, view=view)

        await state_manager.update_session(interaction.guild_id, {
            "step": "welcome",
            "setup_message_id": None,  # Will be set if we can get message ID
            "setup_channel_id": interaction.channel_id
        })

    async def show_permission_step(self, interaction: discord.Interaction, session: SetupState):
        """
        Show the permission check step.
        This step checks if the bot has the required permissions to function correctly.
        """
        guild = interaction.guild

        can_proceed, reason = await permission_checker.can_proceed_with_setup(guild)

        embed = discord.Embed(
            title="🔐 Permission Check",
            color=discord.Color.green() if can_proceed else discord.Color.orange()
        )
        embed.description = reason

        progress = session.get_progress()
        embed.add_field(
            name="📊 Progress",
            value=f"{progress:.0%} complete",
            inline=True
        )

        if not can_proceed:
            embed.add_field(
                name="🚫 Cannot Continue",
                value="Please grant the required permissions and click 'Check Again'.",
                inline=False
            )

        view = self._get_permission_step_buttons(can_proceed)

        await safe_respond(interaction, embed=embed, view=view)

        await state_manager.update_session(interaction.guild_id, {
            "step": "permissions"
        })

    def _get_permission_step_buttons(self, can_proceed: bool) -> discord.ui.View:
        """Get buttons for permission step."""
        buttons = []

        if not can_proceed:
            buttons.append({
                "label": "Check Again",
                "style": button_manager.PRIMARY,
                "custom_id": "perms_check_again",
                "emoji": "🔄"
            })

        buttons.append({
            "label": "Back",
            "style": button_manager.SECONDARY,
            "custom_id": "perms_back",
            "emoji": "⬅️"
        })

        if can_proceed:
            buttons.append({
                "label": "Continue",
                "style": button_manager.SUCCESS,
                "custom_id": "perms_continue",
                "emoji": "➡️"
            })

        buttons.append({
            "label": "Cancel",
            "style": button_manager.DANGER,
            "custom_id": "perms_cancel",
            "emoji": "✖️"
        })

        return button_manager.create_button_row(buttons)

    async def show_log_channel_step(self, interaction: discord.Interaction, session: SetupState):
        """
        Show the log channel setup step.
        This step allows the user to select a channel for logging errors and
        notifications.
        """
        embed = await channel_selector.create_channel_embed(interaction.guild, "log_channel")

        # Show current setting if it exists - handle MongoDB BSON format
        if session.master_log_channel:
            channel_id = session.master_log_channel
            # Handle MongoDB BSON format for 64-bit integers
            if isinstance(channel_id, dict) and "$numberLong" in channel_id:
                channel_id = int(channel_id["$numberLong"])

            channel = interaction.guild.get_channel(channel_id)
            if channel:
                embed.add_field(name="Current Log Channel", value=channel.mention, inline=False)
            else:
                embed.add_field(name="Current Log Channel",
                                value=f"ID: {channel_id} (Channel not found or inaccessible)", inline=False)

        progress = session.get_progress()
        embed.add_field(
            name="📊 Progress",
            value=f"{progress:.0%} complete",
            inline=True
        )

        # Create the select menu directly instead of through channel_selector
        # to have better control over the view
        select_options = []
        for channel in interaction.guild.text_channels:
            if channel.permissions_for(interaction.guild.me).send_messages:
                # Get current channel ID for default selection
                current_channel_id = None
                if session.master_log_channel:
                    current_channel_id = session.master_log_channel
                    if isinstance(current_channel_id, dict) and "$numberLong" in current_channel_id:
                        current_channel_id = int(current_channel_id["$numberLong"])

                select_options.append(
                    discord.SelectOption(
                        label=f"#{channel.name}"[:25],
                        value=str(channel.id),
                        description=f"ID: {channel.id}"[:50],
                        default=(channel.id == current_channel_id)
                    )
                )

        # Create the main view
        view = CustomView(timeout=300)

        # Add select menu if we have channels
        if select_options:
            select_menu = discord.ui.Select(
                placeholder="Select a log channel...",
                options=select_options[:25],  # Discord limit
                custom_id="log_channel_select"
            )
            select_menu.callback = self._handle_log_channel_select
            view.add_item(select_menu)
        else:
            # Add disabled button if no channels available
            view.add_item(discord.ui.Button(
                label="No text channels available",
                disabled=True,
                style=discord.ButtonStyle.secondary # Type: Ignore
            ))

        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary, # Type: Ignore
            custom_id="log_channel_back",
            emoji="⬅️",
            row=1
        )
        back_button.callback = self._handle_log_channel_back
        view.add_item(back_button)

        # Only add continue button if log channel is set
        has_log_channel = False
        if session.master_log_channel:
            # Handle MongoDB BSON format
            if isinstance(session.master_log_channel, dict) and "$numberLong" in session.master_log_channel:
                channel_id = int(session.master_log_channel["$numberLong"])
                channel = interaction.guild.get_channel(channel_id)
                has_log_channel = channel is not None
            else:
                channel = interaction.guild.get_channel(session.master_log_channel)
                has_log_channel = channel is not None

        if has_log_channel:
            continue_button = discord.ui.Button(
                label="Continue",
                style=discord.ButtonStyle.success, # Type: Ignore
                custom_id="log_channel_continue",
                emoji="➡️",
                row=1
            )
            continue_button.callback = self._handle_log_channel_continue
            view.add_item(continue_button)

        cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger, # Type: Ignore
            custom_id="channel_cancel",
            emoji="✖️",
            row=1
        )
        cancel_button.callback = self._handle_log_channel_cancel
        view.add_item(cancel_button)

        await safe_respond(interaction, embed=embed, view=view)

        await state_manager.update_session(interaction.guild_id, {
            "step": "log_channel"
        })





    async def _handle_log_channel_select(self, interaction: discord.Interaction):
        """Handle log channel selection"""
        try:
            # Check if interaction is already acknowledged
            if not interaction.response.is_done(): # Type: Ignore
                await interaction.response.defer(ephemeral=True) # Type: Ignore
            else:
                # If already acknowledged, we can't defer, so just proceed
                self.logger.debug("Interaction already acknowledged, proceeding without defer")

            session = await state_manager.get_session(interaction.guild_id)
            if not session:
                await interaction.followup.send("Session expired. Please run `/setup` again.", ephemeral=True)
                return

            channel_id = int(interaction.data['values'][0])

            # Validate channel access
            channel = interaction.guild.get_channel(channel_id)
            if not channel:
                await interaction.followup.send("❌ Channel not found.", ephemeral=True)
                return

            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.followup.send("❌ I don't have permission to send messages in that channel.",
                                                ephemeral=True)
                return

            # Update session
            session.master_log_channel = channel_id
            await state_manager.update_session(interaction.guild_id, {"master_log_channel_id": channel_id})

            # Persist to database
            await self.guild_manager.update_guild_settings(str(interaction.guild_id),
                                                           {"master_log_channel_id": channel_id})

            # Send confirmation message
            await interaction.followup.send(f"✅ Log channel set to {channel.mention}", ephemeral=True)

            # Refresh the view to show the continue button
            await self.show_log_channel_step(interaction, session)

        except Exception as e:
            self.logger.error(f"Error handling log channel select: {e}", exc_info=True)
            try:
                await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except (discord.HTTPException, discord.NotFound, discord.Forbidden) as followup_error:
                self.logger.debug(f"Failed to send error followup message: {followup_error}")

    async def _handle_log_channel_continue(self, interaction: discord.Interaction):
        """Handle continue button in log channel step"""
        try:
            await interaction.response.defer(ephemeral=True) # Type: Ignore

            session = await state_manager.get_session(interaction.guild_id)
            if not session:
                await interaction.followup.send("Session expired. Please run `/setup` again.", ephemeral=True)
                return

            self.logger.info(f"Log channel continue button pressed for guild {interaction.guild_id}")
            await self.show_first_rule_step(interaction, session)

        except Exception as e:
            self.logger.error(f"Error handling log channel continue: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)

    async def _handle_log_channel_cancel(self, interaction: discord.Interaction):
        """Handle cancel button in log channel step"""
        try:
            await interaction.response.defer(ephemeral=True) # Type: Ignore
            await self.handle_cancel_button(interaction, None)  # session will be fetched in handle_cancel_button

        except Exception as e:
            self.logger.error(f"Error handling log channel cancel: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)

    async def show_first_rule_step(self, interaction: discord.Interaction, session: SetupState):
        """
        Show the first rule setup step.
        This step introduces the user to creating their first forwarding rule.
        """
        embed = discord.Embed(
            title="🔄 Create Your First Forwarding Rule",
            description=(
                "Now let's create your first forwarding rule!\n\n"
                "**What is a forwarding rule?**\n"
                "A rule defines how messages flow from one channel to another.\n\n"
                "**You'll need to specify:**\n"
                "• Source channel (where messages come from)\n"
                "• Destination channel (where messages go to)\n"
                "• Rule name (to identify this rule)\n"
            ),
            color=discord.Color.blue()
        )

        progress = session.get_progress()
        embed.add_field(
            name="📊 Progress",
            value=f"{progress:.0%} complete",
            inline=True
        )

        view = button_manager.create_button_row([
            {
                "label": "Create Rule",
                "style": button_manager.SUCCESS,
                "custom_id": "rule_create",
                "emoji": "🔄"
            },
            {
                "label": "Back",
                "style": button_manager.SECONDARY,
                "custom_id": "channel_back",
                "emoji": "⬅️"
            },
            {
                "label": "Cancel",
                "style": button_manager.DANGER,
                "custom_id": "rule_cancel",
                "emoji": "✖️"
            }
        ])

        await safe_respond(interaction, embed=embed, view=view)

        await state_manager.update_session(interaction.guild_id, {
            "step": "first_rule"
        })

    async def show_learn_more(self, interaction: discord.Interaction, session: SetupState):
        """
        Show more information about the bot.
        This step is displayed when the user clicks the "Learn More" button on
        the welcome step.
        """
        embed = discord.Embed(
            title="ℹ️ About Message Forwarding",
            color=discord.Color.blue()
        )

        embed.description = (
            "**What can this bot do?**\n\n"
            "• **Cross-channel forwarding**: Automatically forward messages between channels\n"
            "• **Smart filtering**: Only forward specific types of messages\n"
            "• **Content filtering**: Filter by keywords, users, or content type\n"
            "• **Custom formatting**: Modify how forwarded messages appear\n"
            "• **Multiple rules**: Create as many rules as you need\n\n"
            "**Common use cases:**\n"
            "• Forward announcements to multiple channels\n"
            "• Archive important messages\n"
            "• Cross-post between community channels\n"
            "• Create message mirrors\n"
        )

        embed.set_footer(text="Ready to set up your first rule?")

        # Use the dedicated view with proper callbacks
        view = LearnMoreView(self, session)

        await safe_respond(interaction, embed=embed, view=view, edit=True)

    async def show_rule_name_modal(self, interaction: discord.Interaction, session):
        """
        Show modal for entering rule name.
        This modal is displayed when the user clicks the "Enter Name" button
        when creating a new rule.
        """
        from .models.rule_modals import RuleNameModal

        async def modal_callback(modal_interaction: discord.Interaction, name: str):
            try:
                self.logger.info(f"Rule name modal submitted: '{name}' for guild {modal_interaction.guild_id}")

                # Validate session and current_rule exist
                if not session or not session.current_rule:
                    self.logger.error(f"Session or current_rule is None in modal callback for guild {modal_interaction.guild_id}")
                    await modal_interaction.followup.send(
                        "❌ Session expired. Please run `/forward setup` again.",
                        ephemeral=True
                    )
                    return

                session.current_rule["rule_name"] = name
                session.current_rule["step"] = "rule_preview"

                await state_manager.update_session(modal_interaction.guild_id, {
                    "current_rule": session.current_rule
                })
                self.logger.debug(f"Session updated with rule name: {name}")

                await self.rule_creation_flow.show_rule_preview_step(modal_interaction, session)
            except Exception as e:
                self.logger.error(f"Error in rule name modal callback: {e}", exc_info=True)
                await modal_interaction.followup.send(
                    "❌ An error occurred while saving the rule name. Please try again.",
                    ephemeral=True
                )

        modal = RuleNameModal(modal_callback)

        if interaction.response.is_done(): # Type: Ignore
            self.logger.warning(
                f"Cannot show modal - interaction already acknowledged for guild {interaction.guild_id}")
            await interaction.followup.send(
                "❌ Cannot open name input dialog (interaction already processed). Please use 'Auto-generated Name' instead.",
                ephemeral=True
            )
        else:
            self.logger.debug(f"Showing rule name modal for guild {interaction.guild_id}")
            await interaction.response.send_modal(modal) # Type: Ignore
            self.logger.info(f"Rule name modal displayed successfully for guild {interaction.guild_id}")

    async def show_rule_edit_step(self, interaction: discord.Interaction, session: SetupState):
        """
        Show the rule settings editor (Components v2).
        Displayed when the user clicks "Edit Settings" in the rule preview step.
        """
        view = RuleSettingsView(session, self, interaction.guild)
        await safe_respond(interaction, view=view, edit=True)

    async def _handle_log_channel_back(self, interaction: discord.Interaction):
        """Handle back button in log channel step"""
        try:
            # Check if interaction is already acknowledged
            if not interaction.response.is_done(): # Type: Ignore
                await interaction.response.defer(ephemeral=True) # Type: Ignore

            session = await state_manager.get_session(interaction.guild_id)
            if not session:
                await interaction.followup.send("Session expired. Please run `/setup` again.", ephemeral=True)
                return

            await self.show_permission_step(interaction, session)

        except Exception as e:
            self.logger.error(f"Error handling log channel back: {e}", exc_info=True)
            # If we can't send a followup, just log the error
            try:
                await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)
            except:
                pass

    async def handle_button_interaction(self, interaction: discord.Interaction):
        """
        Primary router for all button interactions within the setup wizard.
        """
        custom_id = interaction.data.get('custom_id', 'unknown')
        self.logger.info(
            f"Button interaction received: {custom_id} from user {interaction.user.id} in guild {interaction.guild_id}")

        # Skip handling buttons that have direct callbacks
        if custom_id in ["log_channel_continue", "channel_cancel"]:  # Removed channel_back from this list
            self.logger.debug(f"Skipping {custom_id} as it has direct callback")
            return

        try:
            session = await state_manager.get_session(interaction.guild_id)
            if not session:
                self.logger.warning(f"No session found for guild {interaction.guild_id}")
                # If no session, we can't defer, so send ephemeral message directly
                await interaction.response.send_message(
                    "❌ Setup session expired or not found. Please run `/setup` again.",
                    ephemeral=True
                )
                return

            session.update_activity()
            self.logger.debug(f"Session activity updated for guild {interaction.guild_id}")

            # Special handling for modals: do not defer if we are about to send a modal
            if custom_id == "rule_name_input":
                self.logger.info(f"Showing rule name input modal for guild {interaction.guild_id}")
                # Do NOT defer here, as we are sending a modal directly
                await self.show_rule_name_modal(interaction, session)
                return # Exit after sending modal

            # For all other buttons, defer as an update so the wizard's
            # ephemeral host message is edited in place (not replaced with a
            # new ephemeral followup).
            if not interaction.response.is_done(): # Type: Ignore
                await interaction.response.defer() # Type: Ignore

            # --- Welcome & Learn More Flow ---
            if custom_id == "setup_start":
                self.logger.info(f"Starting permission step for guild {interaction.guild_id}")
                await self.show_permission_step(interaction, session)
            elif custom_id == "setup_learn_more":
                self.logger.info(f"Showing learn more for guild {interaction.guild_id}")
                await self.show_learn_more(interaction, session)
            elif custom_id == "learn_back":
                self.logger.info(f"Returning to welcome step for guild {interaction.guild_id}")
                await self.show_welcome_step(interaction, session)

            # --- Permission Check Flow ---
            elif custom_id == "perms_continue":
                self.logger.info(f"Permission check passed, continuing to log channel for guild {interaction.guild_id}")
                await self.show_log_channel_step(interaction, session)
            elif custom_id == "perms_check_again":
                self.logger.info(f"Rechecking permissions for guild {interaction.guild_id}")
                await self.show_permission_step(interaction, session)

            # --- Log Channel Flow ---
            elif custom_id == "channel_back":
                self.logger.info(f"Channel back button pressed for guild {interaction.guild_id}")
                # Handle back button from first rule step or log channel step
                current_step = session.step
                if current_step == "first_rule":
                    await self.show_log_channel_step(interaction, session)
                elif current_step == "log_channel":
                    await self.show_permission_step(interaction, session)
                else:
                    await self.show_log_channel_step(interaction, session)

            # --- Rule Creation & Editing Flow ---
            elif custom_id == "rule_create":
                self.logger.info(f"Starting rule creation for guild {interaction.guild_id}")
                await self.rule_creation_flow.start_rule_creation(interaction)
            elif custom_id == "rule_source_continue":
                self.logger.info(f"Source channel selected, showing destination for guild {interaction.guild_id}")
                await self.rule_creation_flow.show_destination_channel_step(interaction, session)
            elif custom_id == "rule_dest_continue":
                self.logger.info(f"Destination channel selected, showing rule name for guild {interaction.guild_id}")
                await self.rule_creation_flow.show_rule_name_step(interaction, session)
            elif custom_id == "rule_auto_name":
                self.logger.info(f"Using auto-generated rule name for guild {interaction.guild_id}")
                await self.rule_creation_flow.handle_auto_name(interaction, session)
            elif custom_id == "rule_name_input":
                self.logger.info(f"Showing rule name input modal for guild {interaction.guild_id}")
                await self.show_rule_name_modal(interaction, session)
            elif custom_id == "rule_final_create":
                if session.is_editing:
                    self.logger.info(f"Updating final rule for guild {interaction.guild_id}")
                    success, message = await self.update_final_rule(interaction, session)
                else:
                    self.logger.info(f"Creating final rule for guild {interaction.guild_id}")
                    success, message = await self.rule_creation_flow.create_final_rule(interaction, session)

                if success:
                    self.logger.info(f"Rule operation successful for guild {interaction.guild_id}")
                    await self.show_setup_complete(interaction, session, is_editing=session.is_editing)
                else:
                    self.logger.error(f"Rule operation failed for guild {interaction.guild_id}: {message}")
                    await interaction.followup.send(f"❌ {message}", ephemeral=True)
            elif custom_id == "rule_edit_settings":
                self.logger.info(f"Showing rule edit screen for guild {interaction.guild_id}")
                await self.show_rule_edit_step(interaction, session)
            elif custom_id == "rule_start_over":
                self.logger.info(f"Restarting rule creation for guild {interaction.guild_id}")
                await state_manager.cleanup_session(interaction.guild_id)
                session.current_rule = None
                await state_manager.update_session(interaction.guild_id, {"current_rule": None})
                await self.rule_creation_flow.start_rule_creation(interaction)

            # --- Navigation (Back/Cancel) ---
            elif custom_id in ["nav_back", "perms_back", "rule_back"]:
                self.logger.info(f"Back button pressed for guild {interaction.guild_id}")
                await self.handle_back_button(interaction, session)
            elif custom_id.startswith("rule_") and custom_id.endswith("_back"):
                step = custom_id.replace("rule_", "").replace("_back", "")
                self.logger.info(f"Rule-specific back button: {step} for guild {interaction.guild_id}")
                await self.rule_creation_flow.handle_rule_back(interaction, session, self, step)
            elif custom_id.startswith("rule_") and custom_id.endswith("_cancel"):
                self.logger.info(f"Rule-specific cancel button for guild {interaction.guild_id}")
                await self.handle_cancel_button(interaction, session)
            elif custom_id in ["setup_cancel", "perms_cancel", "rule_cancel", "nav_cancel"]:
                self.logger.info(f"Cancel button pressed for guild {interaction.guild_id}")
                await self.handle_cancel_button(interaction, session)

            # --- Post-Setup Actions ---
            elif custom_id == "setup_test_rule":
                self.logger.info(f"Test rule requested for guild {interaction.guild_id}")
                await self.handle_test_rule(interaction, session)
            elif custom_id == "setup_manage_rules":
                self.logger.info(f"Manage rules requested for guild {interaction.guild_id}")
                await self.handle_manage_rules(interaction, session)

            else:
                self.logger.warning(f"Unhandled button custom_id: {custom_id} for guild {interaction.guild_id}")
                await interaction.followup.send(
                    f"This button (`{custom_id}`) isn't implemented yet.",
                    ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"Error handling button interaction ({custom_id}): {e}", exc_info=True)
            try:
                if not interaction.response.is_done(): # Type: Ignore
                    await interaction.response.send_message("❌ An error occurred. Please run `/setup` again.", # Type: Ignore
                                                            ephemeral=True)
                else:
                    await interaction.followup.send("❌ An error occurred. Please run `/setup` again.", ephemeral=True)
            except discord.HTTPException:
                self.logger.error(f"Failed to send error followup message for interaction {custom_id}.")

    async def handle_select_menu(self, interaction: discord.Interaction):
        """
        Router for all select menu interactions that don't have direct callbacks.
        """
        try:
            # Defer as an update so the wizard's ephemeral host message is
            # edited in place rather than producing a new ephemeral.
            if not interaction.response.is_done(): # Type: Ignore
                await interaction.response.defer() # Type: Ignore

            session = await state_manager.get_session(interaction.guild_id)
            if not session:
                await interaction.followup.send("Setup session expired. Please run `/setup` again.", ephemeral=True)
                return

            custom_id = interaction.data.get('custom_id')
            values = interaction.data.get('values', [])
            if not values:
                return

            # --- Rule Channel Selection ---
            if custom_id == "rule_source_select":
                await self.rule_creation_flow.handle_channel_selection(interaction, session, "source", int(values[0]))
            elif custom_id == "rule_dest_guild_select":
                await self.rule_creation_flow.handle_destination_guild_selection(
                    interaction, session, int(values[0])
                )
            elif custom_id == "rule_dest_select":
                await self.rule_creation_flow.handle_channel_selection(interaction, session, "destination", int(values[0]))
            else:
                self.logger.warning(f"Unhandled select menu: {custom_id}")
                await interaction.followup.send("This select menu isn't implemented yet.", ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error handling select menu: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred. Please try again.", ephemeral=True)

    async def handle_back_button(self, interaction: discord.Interaction, session: SetupState):
        """
        Handle back button navigation.
        This method is called when the user clicks a back button in the setup
        wizard.
        """
        current_step = session.step

        if current_step == "permissions":
            await self.show_welcome_step(interaction, session)
        elif current_step == "log_channel":
            await self.show_permission_step(interaction, session)
        elif current_step == "first_rule":
            await self.show_log_channel_step(interaction, session)
        else:
            await self.show_welcome_step(interaction, session)

    async def update_final_rule(self, interaction: discord.Interaction, session: SetupState) -> (bool, str):
        """
        Updates the final rule in the database.
        This method is called when the user clicks the "Save and Exit" button
        when editing a rule.
        """
        updated_rule = session.current_rule
        if not updated_rule or not updated_rule.get("rule_id"):
            return False, "Rule data is missing or invalid."

        rule_id = updated_rule["rule_id"]

        # Fetch all rules and find the original one for logging
        all_rules = await self.guild_manager.get_all_rules(interaction.guild_id)
        original_rule = None
        if all_rules:
            for r in all_rules:
                if r.get("rule_id") == rule_id:
                    original_rule = r
                    break

        if original_rule:
            # Create string representations for comparison
            before_str = json.dumps(original_rule, indent=2, default=str, sort_keys=True)
            after_str = json.dumps(updated_rule, indent=2, default=str, sort_keys=True)

            if before_str == after_str:
                self.logger.info(f"Rule {rule_id} update requested, but no changes were detected.")
            else:
                self.logger.info(f"Updating rule {rule_id} for guild {interaction.guild_id}.\n"
                                 f"--- BEFORE ---\n{before_str}\n"
                                 f"--- AFTER ---\n{after_str}")
        else:
            self.logger.warning(f"Could not find original rule {rule_id} in DB for diff logging.")

        # The entire rule dictionary is passed as the update payload.
        success = await self.guild_manager.update_rule(rule_id, updated_rule)

        if success:
            self.logger.info(f"Successfully updated rule {rule_id} in database.")
            return True, "Rule updated successfully."
        else:
            self.logger.error(f"Failed to update rule {rule_id} in database.")
            return False, "Failed to update the rule in the database."

    async def show_setup_complete(self, interaction: discord.Interaction, session: SetupState, is_editing: bool = False):
        """
        Show the final setup completion message.
        This method is called when the user has successfully created or edited
        a rule.
        """
        on_exit = getattr(session, "on_exit", None) if session else None
        await state_manager.cleanup_session(interaction.guild_id)

        if on_exit is not None:
            try:
                await on_exit(interaction)
                return
            except Exception as e:
                self.logger.error(f"on_exit callback failed in show_setup_complete: {e}", exc_info=True)

        title = "✅ Rule Updated!" if is_editing else "✅ Setup Complete!"
        description = "Your message forwarding rule has been updated." if is_editing else "Your message forwarding rules are now active."

        layout = discord.ui.LayoutView()
        layout.add_item(discord.ui.TextDisplay(f"## {title}"))
        layout.add_item(discord.ui.TextDisplay(description))

        try:
            await interaction.edit_original_response(view=layout)
        except discord.HTTPException:
            try:
                await interaction.followup.send(view=layout, ephemeral=True)
            except discord.HTTPException as followup_error:
                self.logger.error(f"Failed to send followup message after original response failed: {followup_error}")
        except Exception as e:
            self.logger.error(f"Unexpected error in show_setup_complete: {e}", exc_info=True)

    async def handle_test_rule(self, interaction: discord.Interaction, session: SetupState):
        """
        Handle the test rule button.
        This feature is not yet implemented.
        """
        await interaction.response.send_message("Testing rules is not yet implemented.", ephemeral=True) # Type: Ignore

    async def handle_manage_rules(self, interaction: discord.Interaction, session: SetupState):
        """
        Handle the manage rules button.
        This feature is not yet implemented.
        """
        await interaction.response.send_message("Managing rules is not yet implemented.", ephemeral=True) # Type: Ignore

    async def handle_cancel_button(self, interaction: discord.Interaction, session: SetupState):
        """
        Cleans up the session and shows a cancellation message.
        This method is called when the user clicks a cancel button in the setup
        wizard.
        """
        if session is None:
            session = await state_manager.get_session(interaction.guild_id)
        on_exit = getattr(session, "on_exit", None) if session else None
        await state_manager.cleanup_session(interaction.guild_id)

        if on_exit is not None:
            try:
                await on_exit(interaction)
                return
            except Exception as e:
                self.logger.error(f"on_exit callback failed in handle_cancel_button: {e}", exc_info=True)

        layout = discord.ui.LayoutView()
        layout.add_item(discord.ui.TextDisplay("## ❌ Setup Cancelled"))
        layout.add_item(discord.ui.TextDisplay(
            "Your setup progress has been cancelled. You can run `/setup` again anytime."
        ))

        try:
            await interaction.edit_original_response(view=layout)
        except discord.HTTPException:
            try:
                await interaction.followup.send(view=layout, ephemeral=True)
            except discord.HTTPException as followup_error:
                self.logger.error(f"Failed to send followup message after original response failed: {followup_error}")
        except Exception as e:
            self.logger.error(f"Unexpected error in handle_cancel_button: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """
        Global listener for all interactions.
        This acts as the main entry point for component interactions within this cog,
        delegating them to the appropriate handlers based on their `custom_id`.
        """
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get('custom_id', '')

            # Skip components that have direct callbacks - add rule_delete_select to the list
            if custom_id in ["log_channel_continue", "channel_cancel", "log_channel_select", "rule_edit_select",
                             "rule_delete_select", "edit_source_channel_select", "edit_dest_channel_select"]:
                self.logger.debug(f"Skipping {custom_id} as it has direct callback")
                return

            if custom_id.endswith('_select'):
                await self.handle_select_menu(interaction)
            elif custom_id.startswith(('setup_', 'perms_', 'channel_', 'rule_', 'nav_', 'option_', 'learn_')):
                await self.handle_button_interaction(interaction)

async def setup(bot):
    """Setup function for the forward extension."""
    await bot.add_cog(ForwardCog(bot))