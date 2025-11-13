"""
This module contains the primary user-facing setup wizard for configuring
message forwarding rules. It uses a state machine and various discord.ui
components to guide the user through a multi-step configuration process.
"""
import discord
import json
from discord.ext import commands
from discord import app_commands

from logger.logger_setup import get_logger
from .setup_helpers.state_manager import state_manager
from .setup_helpers.button_manager import button_manager
from .setup_helpers.permission_check import permission_checker
from .setup_helpers.channel_select import channel_selector
from .setup_helpers.rule_setup import rule_setup_helper
from .setup_helpers.rule_creation_flow import RuleCreationFlow
from .models.setup_state import SetupState
from database import guild_manager

logger = get_logger("setup")


class RuleDeleteView(discord.ui.View):
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


class RuleDeleteConfirmView(discord.ui.View):
    """
    Confirmation view for rule deletion with Deactivate/Delete options.
    """

    def __init__(self, rule: dict, cog: 'ForwardCog'):
        super().__init__(timeout=60)
        self.rule = rule
        self.cog = cog

        # Deactivate button (soft delete)
        deactivate_button = discord.ui.Button(
            label="Deactivate Rule",
            style=discord.ButtonStyle.secondary,
            emoji="🔴"
        )
        deactivate_button.callback = self.deactivate_callback
        self.add_item(deactivate_button)

        # Permanently delete button
        delete_button = discord.ui.Button(
            label="Permanently Delete",
            style=discord.ButtonStyle.danger,
            emoji="🗑️"
        )
        delete_button.callback = self.delete_callback
        self.add_item(delete_button)

        # Cancel button
        cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.primary,
            emoji="❌"
        )
        cancel_button.callback = self.cancel_callback
        self.add_item(cancel_button)

    async def deactivate_callback(self, interaction: discord.Interaction):
        """Deactivate (soft delete) the rule"""
        await interaction.response.defer(ephemeral=True)

        try:
            rule_id = self.rule.get('rule_id')
            success = await guild_manager.delete_rule(rule_id)  # This does soft delete

            if success:
                rule_name = self.rule.get('rule_name', 'Unnamed Rule')
                embed = discord.Embed(
                    title="✅ Rule Deactivated",
                    description=f"The forwarding rule **{rule_name}** has been deactivated and will no longer forward messages.\n\n*You can reactivate it later using the edit command.*",
                    color=discord.Color.orange()
                )
                await interaction.edit_original_response(embed=embed, view=None)
                logger.info(f"Rule {rule_id} deactivated in guild {interaction.guild.id}")
            else:
                await self._show_error(interaction, "Failed to deactivate the rule.")
        except Exception as e:
            logger.error(f"Error deactivating rule: {e}", exc_info=True)
            await self._show_error(interaction, "An error occurred while deactivating the rule.")

    async def delete_callback(self, interaction: discord.Interaction):
        """Permanently delete the rule"""
        await interaction.response.defer(ephemeral=True)

        try:
            rule_id = self.rule.get('rule_id')
            guild_id = str(interaction.guild.id)
            success = await guild_manager.permanently_delete_rule(guild_id, rule_id)

            if success:
                rule_name = self.rule.get('rule_name', 'Unnamed Rule')
                embed = discord.Embed(
                    title="✅ Rule Permanently Deleted",
                    description=f"The forwarding rule **{rule_name}** has been permanently deleted from the database.\n\n*This action cannot be undone.*",
                    color=discord.Color.green()
                )
                await interaction.edit_original_response(embed=embed, view=None)
                logger.info(f"Rule {rule_id} permanently deleted from guild {guild_id}")
            else:
                await self._show_error(interaction, "Failed to permanently delete the rule.")
        except Exception as e:
            logger.error(f"Error permanently deleting rule: {e}", exc_info=True)
            await self._show_error(interaction, "An error occurred while deleting the rule.")

    async def cancel_callback(self, interaction: discord.Interaction):
        """Cancel the deletion"""
        embed = discord.Embed(
            title="❌ Action Cancelled",
            description="No changes were made to the rule.",
            color=discord.Color.red()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def _show_error(self, interaction: discord.Interaction, message: str):
        """Helper method to show error messages"""
        embed = discord.Embed(
            title="❌ Error",
            description=message,
            color=discord.Color.red()
        )
        await interaction.edit_original_response(embed=embed, view=None)

class LearnMoreView(discord.ui.View):
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


class RuleSelectView(discord.ui.View):
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

        session = await state_manager.create_session(str(interaction.guild_id), interaction.user.id)
        session.current_rule = selected_rule
        session.is_editing = True

        await state_manager.update_session(str(interaction.guild_id), {
            "current_rule": session.current_rule,
            "is_editing": True,
            "step": "rule_preview"
        })

        await self.cog.rule_creation_flow.show_rule_preview_step(interaction, session)


class FormattingSettingsView(discord.ui.View):
    """
    A view for editing formatting-specific settings of a rule, like the style.
    This view is used when the user clicks the "Formatting" button in the
    `RuleSettingsView`.
    """
    def __init__(self, session: SetupState, cog: 'ForwardCog'):
        super().__init__(timeout=300)
        self.session = session
        self.cog = cog

        settings = self.session.current_rule.setdefault("settings", {})
        formatting_settings = settings.setdefault("formatting", {})
        current_style = formatting_settings.get("forward_style", "c_v2")
        
        style_select = discord.ui.Select(
            placeholder="Choose a forwarding style...",
            options=[
                discord.SelectOption(label="Native Style", value="native", description="Closest to Discord's forward feature.", default=current_style == "native"),
                discord.SelectOption(label="Component v2", value="c_v2", default=current_style == "c_v2"),
                discord.SelectOption(label="Embed", value="embed", description="A standard Discord embed.", default=current_style == "embed"),
                discord.SelectOption(label="Plain Text", value="text", description="A simple text-based message.", default=current_style == "text"),
            ],
            row=0
        )
        style_select.callback = self.style_select_callback
        self.add_item(style_select)

        back_button = discord.ui.Button(label="Back to Main Settings", style=discord.ButtonStyle.primary, row=4) # Type: Ignore
        back_button.callback = self.back_to_main_settings_callback
        self.add_item(back_button)

    def create_embed(self) -> discord.Embed:
        """Creates the embed for the formatting settings view."""
        embed = discord.Embed(title="🎨 Edit Formatting", description="Adjust how forwarded messages appear.")
        style = self.session.current_rule.get("settings", {}).get("formatting", {}).get("forward_style", "c_v2")
        embed.add_field(name="Current Style", value=style)
        return embed

    async def style_select_callback(self, interaction: discord.Interaction):
        """
        Callback for when a style is selected. It updates the rule's
        formatting style in the user's session.
        """
        select = interaction.data['values'][0]
        
        settings = self.session.current_rule.setdefault("settings", {})
        formatting_settings = settings.setdefault("formatting", {})
        formatting_settings["forward_style"] = select

        await state_manager.update_session(str(interaction.guild_id), {
            "current_rule": self.session.current_rule
        })

        view = FormattingSettingsView(self.session, self.cog)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view) # Type: Ignore

    async def back_to_main_settings_callback(self, interaction: discord.Interaction):
        """
        Callback for the back button. It returns the user to the main
        rule settings view.
        """
        view = RuleSettingsView(self.session, self.cog)
        embed = await view.create_settings_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view) # Type: Ignore


class RuleSettingsView(discord.ui.View):
    """
    A hub view for editing all settings of a rule, acting as a control panel.
    This view is used when the user clicks the "Edit Settings" button in the
    rule preview step.
    """
    def __init__(self, session: SetupState, cog: 'ForwardCog'):
        super().__init__(timeout=300)
        self.session = session
        self.cog = cog

        name_button = discord.ui.Button(label="Name", style=discord.ButtonStyle.secondary, emoji="📝") # Type: Ignore
        name_button.callback = self.edit_name_callback
        self.add_item(name_button)

        channels_button = discord.ui.Button(label="Channels", style=discord.ButtonStyle.secondary, emoji="🔄") # Type: Ignore
        channels_button.callback = self.edit_channels_callback
        self.add_item(channels_button)
        
        active_label = "Deactivate" if self.session.current_rule.get("is_active", True) else "Activate"
        active_style = discord.ButtonStyle.danger if self.session.current_rule.get("is_active", True) else discord.ButtonStyle.success
        active_button = discord.ui.Button(label=active_label, style=active_style, emoji="⚡")
        active_button.callback = self.toggle_active_callback
        self.add_item(active_button)

        formatting_button = discord.ui.Button(label="Formatting", style=discord.ButtonStyle.secondary, emoji="🎨") # Type: Ignore
        formatting_button.callback = self.edit_formatting_callback
        self.add_item(formatting_button)

        save_button = discord.ui.Button(label="Save and Exit", style=discord.ButtonStyle.success, row=4) # Type: Ignore
        save_button.callback = self.save_and_exit_callback
        self.add_item(save_button)

        back_button = discord.ui.Button(label="Back to Preview", style=discord.ButtonStyle.primary, row=4) # Type: Ignore
        back_button.callback = self.back_to_preview_callback
        self.add_item(back_button)

    async def create_settings_embed(self, guild: discord.Guild) -> discord.Embed:
        """Creates the embed for the main settings view."""
        rule = self.session.current_rule
        rule_name = rule.get("rule_name", "Not Set")
        is_active = "Active" if rule.get("is_active", True) else "Inactive"
        
        source_channel_mention = "Not Set"
        dest_channel_mention = "Not Set"
        if guild:
            source_id = rule.get("source_channel_id")
            if source_id:
                # MongoDB's BSON format for 64-bit integers may be a dict, so we handle it here.
                if isinstance(source_id, dict) and "$numberLong" in source_id:
                    source_id = int(source_id["$numberLong"])
                ch = guild.get_channel(int(source_id))
                source_channel_mention = ch.mention if ch else f"ID: {source_id} (Not Found)"
            
            dest_id = rule.get("destination_channel_id")
            if dest_id:
                if isinstance(dest_id, dict) and "$numberLong" in dest_id:
                    dest_id = int(dest_id["$numberLong"])
                ch = guild.get_channel(int(dest_id))
                dest_channel_mention = ch.mention if ch else f"ID: {dest_id} (Not Found)"

        embed = discord.Embed(
            title=f"Editing Rule: {rule_name}",
            description="Select a category to edit. Your changes are saved to the session automatically.\n"
                        "Go back to the preview screen to save them to the database.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Status", value=is_active, inline=True)
        embed.add_field(name="Source", value=source_channel_mention, inline=True)
        embed.add_field(name="Destination", value=dest_channel_mention, inline=True)
        
        return embed

    async def edit_name_callback(self, interaction: discord.Interaction):
        """
        Callback for the edit name button. It displays a modal for the user
        to enter a new name for the rule.
        """
        from .models.rule_modals import RuleNameModal
        
        async def modal_callback(modal_interaction: discord.Interaction, name: str):
            self.session.current_rule["rule_name"] = name
            await state_manager.update_session(str(modal_interaction.guild_id), {"current_rule": self.session.current_rule})
            
            view = RuleSettingsView(self.session, self.cog)
            embed = await view.create_settings_embed(modal_interaction.guild)
            await modal_interaction.response.edit_message(embed=embed, view=view) # Type: Ignore

        modal = RuleNameModal(modal_callback, current_name=self.session.current_rule.get("rule_name"))
        await interaction.response.send_modal(modal) # Type: Ignore

    async def edit_channels_callback(self, interaction: discord.Interaction):
        """
        Callback for the edit channels button. This feature is not yet
        implemented.
        """
        await interaction.response.send_message("Editing channels is not implemented yet. This will be added in a future update.", ephemeral=True) # Type: Ignore

    async def toggle_active_callback(self, interaction: discord.Interaction):
        """
        Callback for the toggle active button. It toggles the rule's active
        status in the user's session.
        """
        current_status = self.session.current_rule.get("is_active", True)
        self.session.current_rule["is_active"] = not current_status
        await state_manager.update_session(str(interaction.guild_id), {"current_rule": self.session.current_rule})

        new_view = RuleSettingsView(self.session, self.cog)
        embed = await new_view.create_settings_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=new_view) # Type: Ignore

    async def edit_formatting_callback(self, interaction: discord.Interaction):
        """
        Callback for the edit formatting button. It displays the
        `FormattingSettingsView`.
        """
        view = FormattingSettingsView(self.session, self.cog)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view) # Type: Ignore

    async def back_to_preview_callback(self, interaction: discord.Interaction):
        """
        Callback for the back to preview button. It returns the user to the
        rule preview step.
        """
        await self.cog.rule_creation_flow.show_rule_preview_step(interaction, self.session)

    async def save_and_exit_callback(self, interaction: discord.Interaction):
        """
        Callback for the save and exit button. It saves the rule to the
        database and ends the setup session.
        """
        await interaction.response.defer() # Type: Ignore

        success, message = await self.cog.update_final_rule(interaction, self.session)
        
        if success:
            await self.cog.show_setup_complete(interaction, self.session, is_editing=True)
        else:
            await interaction.followup.send(f"❌ Save failed: {message}", ephemeral=True)


class ForwardCog(commands.Cog):
    """
    This cog manages the /forward slash command group for setting up and
    editing forwarding rules. It uses a state machine to guide the user
    through a multi-step configuration process.
    """
    forward = app_commands.Group(name="forward", description="Commands for message forwarding", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.logger = None
        self.guild_manager = guild_manager
        self.rule_creation_flow = RuleCreationFlow(bot, self)

    async def cog_load(self):
        """Initializes the logger for this cog when it's loaded."""
        from logger.logger_setup import get_logger
        self.logger = get_logger("Forward", level=20, json_format=False, colored_console=True)
        self.logger.info("Forward cog loaded")

    @forward.command(name="edit", description="Edit an existing forwarding rule.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def edit(self, interaction: discord.Interaction):
        """
        Starts an interactive UI to select and edit an existing forwarding rule.
        This command is the entry point for editing rules.
        """
        try:
            rules = await self.guild_manager.get_all_rules(str(interaction.guild_id))

            if not rules:
                await interaction.response.send_message( # Type: Ignore
                    "🤔 No forwarding rules found for this server. Use `/forward setup` to create one.",
                    ephemeral=True
                )
                return

            view = RuleSelectView(rules, self)
            await interaction.response.send_message( # Type: Ignore
                "Please select a rule to edit:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Error starting edit session: {e}", exc_info=True)
            await interaction.response.send_message( # Type: Ignore
                "❌ An error occurred while trying to edit a rule. Please try again.",
                ephemeral=True
            )

    @forward.command(name="setup", description="Start interactive setup for message forwarding")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        """
        Starts the interactive setup wizard for creating a new forwarding rule.
        This command is the entry point for creating new rules.
        """
        try:
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message( # Type: Ignore
                    "❌ You need the 'Manage Server' permission to run setup.",
                    ephemeral=True
                )
                return

            session = await state_manager.create_session(str(interaction.guild_id), interaction.user.id)
            
            # Pre-fill existing settings
            guild_settings = await self.guild_manager.get_guild_settings(str(interaction.guild_id))
            if guild_settings:
                log_channel_id = guild_settings.get("master_log_channel_id")
                if log_channel_id:
                    session.master_log_channel = log_channel_id
                    await state_manager.update_session(str(interaction.guild_id), {"master_log_channel_id": log_channel_id})

            await self.show_welcome_step(interaction, session)

        except Exception as e:
            self.logger.error(f"Error starting setup: {e}", exc_info=True)
            await interaction.response.send_message( # Type: Ignore
                "❌ An error occurred starting setup. Please try again.",
                ephemeral=True
            )

    @forward.command(name="help", description="Get help and information about the forwarding bot.")
    async def help_command(self, interaction: discord.Interaction):
        """
        Provides descriptive help on how to use the message forwarding bot.
        """
        embed = discord.Embed(
            title="🤖 Message Forwarding Bot Help",
            description="This bot helps you automatically forward messages between channels in your Discord server.",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="`/forward setup`",
            value="Starts an interactive wizard to configure new message forwarding rules. "
                  "You'll be guided through setting up permissions, a log channel, and your first rule.",
            inline=False
        )
        embed.add_field(
            name="`/forward edit`",
            value="Allows you to view and modify existing forwarding rules. "
                  "You can change rule names, source/destination channels, activation status, and formatting.",
            inline=False
        )
        embed.add_field(
            name="How it works:",
            value="Once a rule is set up, the bot will monitor the specified **source channel** "
                  "and automatically repost messages to the **destination channel**. "
                  "You can configure various filters and formatting options during setup or editing.",
            inline=False
        )
        embed.add_field(
            name="Need more assistance?",
            value="If you encounter any issues or have further questions, please contact support or refer to the documentation.",
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @forward.command(name="delete_rule", description="Delete a forwarding rule")
    async def delete_forwarding_rule(self, interaction: discord.Interaction):
        """
        Slash command to delete a forwarding rule using a select menu.
        Only users with manage_guild permission can use this command.
        """
        # Check if user has permission to manage the server
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ You need the 'Manage Server' permission to delete forwarding rules.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Get all rules for this guild
            guild_settings = await guild_manager.get_guild_settings(str(interaction.guild.id))
            rules = guild_settings.get("rules", [])

            if not rules:
                await interaction.followup.send(
                    "📋 **No forwarding rules found for this server.**\n"
                    "Create your first rule using `/forward setup`!",
                    ephemeral=True
                )
                return

            # Create the selection view
            view = RuleDeleteView(rules, self)

            embed = discord.Embed(
                title="🗑️ Delete Forwarding Rule",
                description=f"Select a rule to delete from the dropdown below.\n\n"
                            f"**Found {len(rules)} rule(s) in this server.**",
                color=discord.Color.orange()
            )

            embed.set_footer(text="⚠️ Deletion is permanent and cannot be undone!")

            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except Exception as e:
            logger.error(f"Error showing delete rule menu in guild {interaction.guild.id}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while retrieving forwarding rules. Please try again later.",
                ephemeral=True
            )

    @forward.command(name="list_rules", description="List all forwarding rules for this server")
    async def list_forwarding_rules(self, interaction: discord.Interaction):
        """
        Slash command to list all forwarding rules in the current guild.
        This helps users identify rule IDs for deletion.
        """
        # Check if user has permission to manage the server
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ You need the 'Manage Server' permission to view forwarding rules.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Get guild settings and rules
            guild_settings = await guild_manager.get_guild_settings(str(interaction.guild.id))
            rules = guild_settings.get("rules", [])

            if not rules:
                await interaction.followup.send(
                    "📋 **No forwarding rules found for this server.**\n"
                    "Create your first rule to get started!",
                    ephemeral=True
                )
                return

            # Create an embed to display the rules
            embed = discord.Embed(
                title="📋 Forwarding Rules",
                description=f"Found {len(rules)} forwarding rule(s)",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )

            for i, rule in enumerate(rules[:10], 1):  # Limit to 10 rules to avoid embed limits
                rule_id = rule.get("rule_id", "Unknown")
                is_active = "🟢 Active" if rule.get("is_active", False) else "🔴 Inactive"

                source_channel = self.bot.get_channel(int(rule.get("source_channel_id")))
                destination_channel = self.bot.get_channel(int(rule.get("destination_channel_id")))

                source_name = source_channel.mention if source_channel else f"<#{rule.get('source_channel_id')}>"
                destination_name = destination_channel.mention if destination_channel else f"<#{rule.get('destination_channel_id')}>"

                embed.add_field(
                    name=f"Rule #{i} - {is_active}",
                    value=f"**ID:** `{rule_id}`\n**From:** {source_name}\n**To:** {destination_name}",
                    inline=True
                )

            if len(rules) > 10:
                embed.set_footer(text=f"Showing first 10 of {len(rules)} rules")
            else:
                embed.set_footer(text="Use /delete_rule <rule_id> to delete a specific rule")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error listing forwarding rules in guild {interaction.guild.id}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ An error occurred while retrieving forwarding rules. Please try again later.",
                ephemeral=True
            )

    async def cog_unload(self):
        """
        Called when the cog is unloaded.
        This method removes the context menu command from the bot's tree.
        """
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    # ... existing code ...

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

        try:
            if interaction.response.is_done(): # Type: Ignore
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True) # Type: Ignore
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower() or "unknown interaction" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    try:
                        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
                    except discord.HTTPException as followup_error:
                        self.logger.error(f"Failed all interaction response methods: {followup_error}")
            else:
                raise e

        await state_manager.update_session(str(interaction.guild_id), {
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

        try:
            if interaction.response.is_done(): # Type: Ignore
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True) # Type: Ignore
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e):
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

        await state_manager.update_session(str(interaction.guild_id), {
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
        view = discord.ui.View(timeout=300)

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

        # Create button row
        button_row = discord.ui.View(timeout=300)  # Separate view for buttons to ensure proper row layout

        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary, # Type: Ignore
            custom_id="log_channel_back",
            emoji="⬅️",
            row=1
        )
        back_button.callback = self._handle_log_channel_back
        button_row.add_item(back_button)

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
            button_row.add_item(continue_button)

        cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger, # Type: Ignore
            custom_id="channel_cancel",
            emoji="✖️",
            row=1
        )
        cancel_button.callback = self._handle_log_channel_cancel
        button_row.add_item(cancel_button)

        # Combine both views by adding all items to the main view
        for item in button_row.children:
            view.add_item(item)

        try:
            if interaction.response.is_done(): # Type: Ignore
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True) # Type: Ignore
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

        await state_manager.update_session(str(interaction.guild_id), {
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

            session = await state_manager.get_session(str(interaction.guild_id))
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
            await state_manager.update_session(str(interaction.guild_id), {"master_log_channel_id": channel_id})

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
            except:
                pass  # If we can't send followup, just log the error

    async def _handle_log_channel_continue(self, interaction: discord.Interaction):
        """Handle continue button in log channel step"""
        try:
            await interaction.response.defer(ephemeral=True) # Type: Ignore

            session = await state_manager.get_session(str(interaction.guild_id))
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

        try:
            if interaction.response.is_done(): # Type: Ignore
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True) # Type: Ignore
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

        await state_manager.update_session(str(interaction.guild_id), {
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

        try:
            if interaction.response.is_done(): # Type: Ignore
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.edit_message(embed=embed, view=view) # Type: Ignore
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower() or "unknown interaction" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

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
                session.current_rule["rule_name"] = name
                session.current_rule["step"] = "rule_preview"

                await state_manager.update_session(str(modal_interaction.guild_id), {
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
        Show the rule settings editor.
        This step is displayed when the user clicks the "Edit Settings" button
        in the rule preview step.
        """
        view = RuleSettingsView(session, self)
        embed = await view.create_settings_embed(interaction.guild)
        await interaction.edit_original_response(embed=embed, view=view) # Type: Ignore

    async def _handle_log_channel_back(self, interaction: discord.Interaction):
        """Handle back button in log channel step"""
        try:
            # Check if interaction is already acknowledged
            if not interaction.response.is_done(): # Type: Ignore
                await interaction.response.defer(ephemeral=True) # Type: Ignore

            session = await state_manager.get_session(str(interaction.guild_id))
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
            session = await state_manager.get_session(str(interaction.guild_id))
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

            # For all other buttons, defer the interaction
            if not interaction.response.is_done(): # Type: Ignore
                await interaction.response.defer(ephemeral=True) # Type: Ignore

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
                await state_manager.cleanup_session(str(interaction.guild_id))
                session.current_rule = None
                await state_manager.update_session(str(interaction.guild_id), {"current_rule": None})
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
            # Defer the interaction immediately to prevent timeout
            if not interaction.response.is_done(): # Type: Ignore
                await interaction.response.defer(ephemeral=True) # Type: Ignore

            session = await state_manager.get_session(str(interaction.guild_id))
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
        all_rules = await self.guild_manager.get_all_rules(str(interaction.guild_id))
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
        title = "✅ Rule Updated!" if is_editing else "✅ Setup Complete!"
        description = "Your message forwarding rule has been updated." if is_editing else "Your message forwarding rules are now active."

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green()
        )
        await state_manager.cleanup_session(str(interaction.guild_id))

        try:
            await interaction.edit_original_response(embed=embed, view=None)
        except discord.HTTPException:
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
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
        await state_manager.cleanup_session(str(interaction.guild_id))

        embed = discord.Embed(
            title="❌ Setup Cancelled",
            description="Your setup progress has been cancelled. You can run `/setup` again anytime.",
            color=discord.Color.red()
        )

        try:
            await interaction.edit_original_response(embed=embed, view=None)
        except discord.HTTPException:
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
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
                             "rule_delete_select"]:
                self.logger.debug(f"Skipping {custom_id} as it has direct callback")
                return

            if custom_id.endswith('_select'):
                await self.handle_select_menu(interaction)
            elif custom_id.startswith(('setup_', 'perms_', 'channel_', 'rule_', 'nav_', 'option_', 'learn_')):
                await self.handle_button_interaction(interaction)

async def setup(bot):
    """Setup function for the forward extension."""
    await bot.add_cog(ForwardCog(bot))