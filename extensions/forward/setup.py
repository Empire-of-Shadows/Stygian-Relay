"""
Main setup wizard for message forwarding configuration.
"""
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional

# Import setup helpers
from .setup_helpers.state_manager import state_manager
from .setup_helpers.button_manager import button_manager
from .setup_helpers.permission_check import permission_checker
from .setup_helpers.channel_select import channel_selector
from .setup_helpers.rule_setup import rule_setup_helper
from .models.setup_state import SetupState, SETUP_STEPS
from database import guild_manager


class RuleSelectView(discord.ui.View):
    """A view to select a rule to edit."""

    def __init__(self, rules: list, cog: 'ForwardCog'):
        super().__init__(timeout=180)
        self.cog = cog
        # Store rules in a dict for easy lookup
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
        """Callback for when a rule is selected from the dropdown."""
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

        from .setup_helpers.rule_creation_flow import rule_creation_flow
        await rule_creation_flow.show_rule_preview_step(interaction, session)


class FormattingSettingsView(discord.ui.View):
    """A view for editing formatting-specific settings of a rule."""
    def __init__(self, session: SetupState, cog: 'ForwardCog'):
        super().__init__(timeout=300)
        self.session = session
        self.cog = cog

        # --- Style Select ---
        settings = self.session.current_rule.setdefault("settings", {})
        formatting_settings = settings.setdefault("formatting", {})
        current_style = formatting_settings.get("forward_style", "c_v2")
        
        style_select = discord.ui.Select(
            placeholder="Choose a forwarding style...",
            options=[
                discord.SelectOption(label="Component v2", value="c_v2", default=current_style == "c_v2"),
                discord.SelectOption(label="Embed", value="embed", default=current_style == "embed"),
                discord.SelectOption(label="Plain Text", value="text", default=current_style == "text"),
            ],
            row=0
        )
        style_select.callback = self.style_select_callback
        self.add_item(style_select)

        # --- Navigation ---
        back_button = discord.ui.Button(label="Back to Main Settings", style=discord.ButtonStyle.primary, row=4)
        back_button.callback = self.back_to_main_settings_callback
        self.add_item(back_button)

    def create_embed(self) -> discord.Embed:
        """Creates the embed for the formatting settings view."""
        embed = discord.Embed(title="🎨 Edit Formatting", description="Adjust how forwarded messages appear.")
        style = self.session.current_rule.get("settings", {}).get("formatting", {}).get("forward_style", "c_v2")
        embed.add_field(name="Current Style", value=style)
        return embed

    async def style_select_callback(self, interaction: discord.Interaction):
        select = interaction.data['values'][0]
        
        settings = self.session.current_rule.setdefault("settings", {})
        formatting_settings = settings.setdefault("formatting", {})
        formatting_settings["forward_style"] = select

        await state_manager.update_session(str(interaction.guild_id), {
            "current_rule": self.session.current_rule
        })

        view = FormattingSettingsView(self.session, self.cog)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def back_to_main_settings_callback(self, interaction: discord.Interaction):
        view = RuleSettingsView(self.session, self.cog)
        embed = await view.create_settings_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)


class RuleSettingsView(discord.ui.View):
    """A hub view for editing all settings of a rule."""
    def __init__(self, session: SetupState, cog: 'ForwardCog'):
        super().__init__(timeout=300)
        self.session = session
        self.cog = cog

        # --- General Settings ---
        name_button = discord.ui.Button(label="Name", style=discord.ButtonStyle.secondary, emoji="📝")
        name_button.callback = self.edit_name_callback
        self.add_item(name_button)

        channels_button = discord.ui.Button(label="Channels", style=discord.ButtonStyle.secondary, emoji="🔄")
        channels_button.callback = self.edit_channels_callback
        self.add_item(channels_button)
        
        active_label = "Deactivate" if self.session.current_rule.get("is_active", True) else "Activate"
        active_style = discord.ButtonStyle.danger if self.session.current_rule.get("is_active", True) else discord.ButtonStyle.success
        active_button = discord.ui.Button(label=active_label, style=active_style, emoji="⚡")
        active_button.callback = self.toggle_active_callback
        self.add_item(active_button)

        # --- Detailed Settings ---
        formatting_button = discord.ui.Button(label="Formatting", style=discord.ButtonStyle.secondary, emoji="🎨")
        formatting_button.callback = self.edit_formatting_callback
        self.add_item(formatting_button)

        # --- Navigation ---
        save_button = discord.ui.Button(label="Save and Exit", style=discord.ButtonStyle.success, row=4)
        save_button.callback = self.save_and_exit_callback
        self.add_item(save_button)

        back_button = discord.ui.Button(label="Back to Preview", style=discord.ButtonStyle.primary, row=4)
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
                # Handle BSON Long type
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
        from .models.rule_modals import RuleNameModal
        
        async def modal_callback(modal_interaction: discord.Interaction, name: str):
            self.session.current_rule["rule_name"] = name
            await state_manager.update_session(str(modal_interaction.guild_id), {"current_rule": self.session.current_rule})
            
            view = RuleSettingsView(self.session, self.cog)
            embed = await view.create_settings_embed(modal_interaction.guild)
            await modal_interaction.response.edit_message(embed=embed, view=view)

        modal = RuleNameModal(modal_callback, current_name=self.session.current_rule.get("rule_name"))
        await interaction.response.send_modal(modal)

    async def edit_channels_callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("Editing channels is not implemented yet. This will be added in a future update.", ephemeral=True)

    async def toggle_active_callback(self, interaction: discord.Interaction):
        current_status = self.session.current_rule.get("is_active", True)
        self.session.current_rule["is_active"] = not current_status
        await state_manager.update_session(str(interaction.guild_id), {"current_rule": self.session.current_rule})

        new_view = RuleSettingsView(self.session, self.cog)
        embed = await new_view.create_settings_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=new_view)

    async def edit_formatting_callback(self, interaction: discord.Interaction):
        view = FormattingSettingsView(self.session, self.cog)
        embed = view.create_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    async def back_to_preview_callback(self, interaction: discord.Interaction):
        from .setup_helpers.rule_creation_flow import rule_creation_flow
        await rule_creation_flow.show_rule_preview_step(interaction, self.session)

    async def save_and_exit_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()

        success, message = await self.cog.update_final_rule(interaction, self.session)
        
        if success:
            await state_manager.cleanup_session(str(interaction.guild_id))
            await interaction.message.delete()
            await interaction.followup.send("✅ Rule updated successfully!", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Save failed: {message}", ephemeral=True)


class ForwardCog(commands.Cog):
    """Cog for setting up and managing message forwarding."""
    forward = app_commands.Group(name="forward", description="Commands for message forwarding", guild_only=True)

    def __init__(self, bot):
        self.bot = bot
        self.logger = None  # Will be set in on_ready
        self.guild_manager = guild_manager

    async def cog_load(self):
        """Called when the cog is loaded."""
        # Initialize logger
        from logger.logger_setup import get_logger
        self.logger = get_logger("Forward", level=20, json_format=False, colored_console=True)
        self.logger.info("Forward cog loaded")

    @forward.command(name="edit", description="Edit an existing forwarding rule.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def edit(self, interaction: discord.Interaction):
        """Starts an interactive session to edit a forwarding rule."""
        try:
            rules = await self.guild_manager.get_all_rules(str(interaction.guild_id))

            if not rules:
                await interaction.response.send_message(
                    "🤔 No forwarding rules found for this server. Use `/forward setup` to create one.",
                    ephemeral=True
                )
                return

            view = RuleSelectView(rules, self)
            await interaction.response.send_message(
                "Please select a rule to edit:",
                view=view,
                ephemeral=True
            )

        except Exception as e:
            self.logger.error(f"Error starting edit session: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while trying to edit a rule. Please try again.",
                ephemeral=True
            )

    @forward.command(name="setup", description="Start interactive setup for message forwarding")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        """Start the interactive setup wizard."""
        try:
            # Check if user has permission
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "❌ You need the 'Manage Server' permission to run setup.",
                    ephemeral=True
                )
                return

            # Create or get setup session
            session = await state_manager.create_session(str(interaction.guild_id), interaction.user.id)

            # Start with welcome step
            await self.show_welcome_step(interaction, session)

        except Exception as e:
            self.logger.error(f"Error starting setup: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred starting setup. Please try again.",
                ephemeral=True
            )

    async def show_welcome_step(self, interaction: discord.Interaction, session: SetupState):
        """Show the welcome step of setup."""
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

        # Show progress
        progress = session.get_progress()
        embed.add_field(
            name="📊 Progress",
            value=f"{progress:.0%} complete",
            inline=True
        )

        embed.set_footer(text="Click 'Start Setup' to begin!")

        # Send initial message with buttons
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=button_manager.get_welcome_buttons())
            else:
                await interaction.response.send_message(embed=embed, view=button_manager.get_welcome_buttons())
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=button_manager.get_welcome_buttons())
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=button_manager.get_welcome_buttons(),
                                                    ephemeral=True)
            else:
                raise e

        # Update session
        await state_manager.update_session(interaction.guild_id, {
            "step": "welcome",
            "setup_message_id": interaction.message.id if interaction.message else None,
            "setup_channel_id": interaction.channel_id
        })

    async def show_permission_step(self, interaction: discord.Interaction, session: SetupState):
        """Show the permission check step."""
        guild = interaction.guild

        # Check permissions
        can_proceed, reason = await permission_checker.can_proceed_with_setup(guild)
        permission_embed = await permission_checker.create_permission_embed(guild)

        # Create main embed
        embed = discord.Embed(
            title="🔐 Permission Check",
            color=discord.Color.green() if can_proceed else discord.Color.orange()
        )

        embed.description = reason

        # Add progress
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

        # Send or update message
        view = self._get_permission_step_buttons(can_proceed)

        # Check if interaction has been responded to
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e):
                # Try to edit the original response instead
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    # If that fails too, send a followup message
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

        # Update session
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
        """Show the log channel setup step."""
        embed = await channel_selector.create_channel_embed(interaction.guild, "log_channel")

        # Add progress
        progress = session.get_progress()
        embed.add_field(
            name="📊 Progress",
            value=f"{progress:.0%} complete",
            inline=True
        )

        # Create channel selection menu
        view = await channel_selector.create_channel_select_menu(interaction.guild, "text", "log_channel_select")

        # Check if interaction has already been responded to
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view)
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower():
                # Try to edit the original response instead
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    # If that fails too, send a followup message
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

        # Update session
        await state_manager.update_session(interaction.guild_id, {
            "step": "log_channel"
        })

    async def show_first_rule_step(self, interaction: discord.Interaction, session: SetupState):
        """Show the first forwarding rule setup step."""
        embed = discord.Embed(
            title="🔄 Create Your First Forwarding Rule",
            description=(
                "Let's create your first message forwarding rule!\n\n"
                "**What is a forwarding rule?**\n"
                "A rule tells me to watch a specific channel and automatically "
                "forward messages to another channel.\n\n"
                "We'll set up:\n"
                "• Source channel (where to watch)\n"
                "• Destination channel (where to forward)\n"
                "• Basic settings\n"
            ),
            color=discord.Color.blue()
        )

        # Add progress
        progress = session.get_progress()
        embed.add_field(
            name="📊 Progress",
            value=f"{progress:.0%} complete",
            inline=True
        )

        # Get buttons for rule setup
        view = await rule_setup_helper.get_rule_setup_buttons()

        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view)
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

        # Update session
        await state_manager.update_session(interaction.guild_id, {
            "step": "first_rule"
        })

    async def show_learn_more(self, interaction: discord.Interaction, session: SetupState):
        """Show more information about the bot."""
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

        view = button_manager.create_button_row([
            {
                "label": "Start Setup",
                "style": button_manager.SUCCESS,
                "custom_id": "setup_start",
                "emoji": "🚀"
            },
            {
                "label": "Back to Welcome",
                "style": button_manager.SECONDARY,
                "custom_id": "learn_back",
                "emoji": "⬅️"
            }
        ])

        await interaction.response.edit_message(embed=embed, view=view)

    async def show_rule_name_modal(self, interaction: discord.Interaction, session):
        """Show modal for entering rule name."""
        from .models.rule_modals import RuleNameModal

        async def modal_callback(modal_interaction: discord.Interaction, name: str):
            try:
                self.logger.info(f"Rule name modal submitted: '{name}' for guild {modal_interaction.guild_id}")
                # Update session with rule name
                session.current_rule["rule_name"] = name
                session.current_rule["step"] = "rule_preview"

                await state_manager.update_session(modal_interaction.guild_id, {
                    "current_rule": session.current_rule
                })
                self.logger.debug(f"Session updated with rule name: {name}")

                # Show rule preview
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.show_rule_preview_step(modal_interaction, session)
            except Exception as e:
                self.logger.error(f"Error in rule name modal callback: {e}", exc_info=True)
                await modal_interaction.followup.send(
                    "❌ An error occurred while saving the rule name. Please try again.",
                    ephemeral=True
                )

        modal = RuleNameModal(modal_callback)

        # Check if the interaction has already been responded to
        if interaction.response.is_done():
            self.logger.warning(
                f"Cannot show modal - interaction already acknowledged for guild {interaction.guild_id}")
            # Interaction already acknowledged - cannot send modal
            await interaction.followup.send(
                "❌ Cannot open name input dialog (interaction already processed). Please use 'Auto-generated Name' instead.",
                ephemeral=True
            )
        else:
            self.logger.debug(f"Showing rule name modal for guild {interaction.guild_id}")
            await interaction.response.send_modal(modal)
            self.logger.info(f"Rule name modal displayed successfully for guild {interaction.guild_id}")

    async def show_rule_edit_step(self, interaction: discord.Interaction, session: SetupState):
        """Show the rule settings editor."""
        view = RuleSettingsView(session, self)
        embed = await view.create_settings_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=view)

    async def handle_button_interaction(self, interaction: discord.Interaction):
        """Handle button interactions from setup messages."""
        custom_id = interaction.data.get('custom_id', 'unknown')
        self.logger.info(
            f"Button interaction received: {custom_id} from user {interaction.user.id} in guild {interaction.guild_id}")

        try:
            # Get the session
            session = await state_manager.get_session(str(interaction.guild_id))
            if not session:
                self.logger.warning(f"No session found for guild {interaction.guild_id}")
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(
                            "❌ Setup session expired or not found. Please run `/setup` again.",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            "❌ Setup session expired or not found. Please run `/setup` again.",
                            ephemeral=True
                        )
                except discord.HTTPException as e:
                    if "already been acknowledged" in str(e).lower():
                        await interaction.followup.send(
                            "❌ Setup session expired or not found. Please run `/setup` again.",
                            ephemeral=True
                        )
                    else:
                        raise e
                return

            # Update activity
            session.update_activity()
            self.logger.debug(f"Session activity updated for guild {interaction.guild_id}")

            # Handle different button types based on custom_id
            # === SETUP FLOW BUTTONS ===
            if custom_id == "setup_start":
                self.logger.info(f"Starting permission step for guild {interaction.guild_id}")
                await self.show_permission_step(interaction, session)

            elif custom_id == "setup_learn_more":
                self.logger.info(f"Showing learn more for guild {interaction.guild_id}")
                await self.show_learn_more(interaction, session)

            elif custom_id == "learn_back":
                self.logger.info(f"Returning to welcome step for guild {interaction.guild_id}")
                await self.show_welcome_step(interaction, session)

            # === PERMISSION STEP BUTTONS ===
            elif custom_id == "perms_continue":
                self.logger.info(f"Permission check passed, continuing to log channel for guild {interaction.guild_id}")
                await self.show_log_channel_step(interaction, session)

            elif custom_id == "perms_check_again":
                self.logger.info(f"Rechecking permissions for guild {interaction.guild_id}")
                await self.show_permission_step(interaction, session)

            # === RULE CREATION BUTTONS ===
            elif custom_id == "rule_create":
                self.logger.info(f"Starting rule creation for guild {interaction.guild_id}")
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.start_rule_creation(interaction, session)

            elif custom_id == "rule_source_continue":
                self.logger.info(f"Source channel selected, showing destination for guild {interaction.guild_id}")
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.show_destination_channel_step(interaction, session)

            # Add specific handler for rule_source_back
            elif custom_id == "rule_source_back":
                self.logger.info(f"Going back from source selection for guild {interaction.guild_id}")
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.handle_rule_back(interaction, session, "source")

            # Add handler for rule_dest_back
            elif custom_id == "rule_dest_back":
                self.logger.info(f"Going back from destination selection for guild {interaction.guild_id}")
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.handle_rule_back(interaction, session, "destination")

            elif custom_id == "rule_dest_continue":
                self.logger.info(f"Destination channel selected, showing rule name for guild {interaction.guild_id}")
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.show_rule_name_step(interaction, session)

            elif custom_id == "rule_auto_name":
                self.logger.info(f"Using auto-generated rule name for guild {interaction.guild_id}")
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.handle_auto_name(interaction, session)

            elif custom_id == "rule_name_input":
                self.logger.info(f"Showing rule name input modal for guild {interaction.guild_id}")
                await self.show_rule_name_modal(interaction, session)

            elif custom_id == "rule_final_create":
                if session.is_editing:
                    self.logger.info(f"Updating final rule for guild {interaction.guild_id}")
                    success, message = await self.update_final_rule(interaction, session)
                else:
                    self.logger.info(f"Creating final rule for guild {interaction.guild_id}")
                    from .setup_helpers.rule_creation_flow import rule_creation_flow
                    success, message = await rule_creation_flow.create_final_rule(interaction, session)

                if success:
                    self.logger.info(f"Rule operation successful for guild {interaction.guild_id}")
                    await self.show_setup_complete(interaction, session, is_editing=session.is_editing)
                else:
                    self.logger.error(f"Rule operation failed for guild {interaction.guild_id}: {message}")
                    try:
                        if interaction.response.is_done():
                            await interaction.followup.send(
                                f"❌ {message}",
                                ephemeral=True
                            )
                        else:
                            await interaction.response.send_message(
                                f"❌ {message}",
                                ephemeral=True
                            )
                    except discord.HTTPException as e:
                        if "already been acknowledged" in str(e).lower():
                            await interaction.followup.send(
                                f"❌ {message}",
                                ephemeral=True
                            )
                        else:
                            raise e

            elif custom_id == "rule_edit_settings":
                self.logger.info(f"Showing rule edit screen for guild {interaction.guild_id}")
                await self.show_rule_edit_step(interaction, session)

            elif custom_id == "rule_start_over":
                self.logger.info(f"Restarting rule creation for guild {interaction.guild_id}")
                # Reset rule creation and start over
                session.current_rule = None
                await state_manager.update_session(interaction.guild_id, {
                    "current_rule": None
                })
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.start_rule_creation(interaction, session)

            # === NAVIGATION BUTTONS ===
            elif custom_id in ["nav_back", "perms_back", "channel_back", "rule_back"]:
                self.logger.info(f"Back button pressed for guild {interaction.guild_id}")
                await self.handle_back_button(interaction, session)

            # Handle rule-specific back buttons
            elif custom_id.startswith("rule_") and custom_id.endswith("_back"):
                step = custom_id.replace("rule_", "").replace("_back", "")
                self.logger.info(f"Rule-specific back button: {step} for guild {interaction.guild_id}")
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.handle_rule_back(interaction, session, step)

            # === CANCEL BUTTONS ===
            elif custom_id in ["setup_cancel", "perms_cancel", "channel_cancel", "rule_cancel", "nav_cancel"]:
                self.logger.info(f"Cancel button pressed for guild {interaction.guild_id}")
                await self.handle_cancel_button(interaction, session)

            # Handle rule-specific cancel buttons
            elif custom_id.startswith("rule_") and custom_id.endswith("_cancel"):
                self.logger.info(f"Rule-specific cancel button for guild {interaction.guild_id}")
                await self.handle_cancel_button(interaction, session)

            # === SETUP COMPLETION BUTTONS ===
            elif custom_id == "setup_test_rule":
                self.logger.info(f"Test rule requested for guild {interaction.guild_id}")
                await self.handle_test_rule(interaction, session)

            elif custom_id == "setup_manage_rules":
                self.logger.info(f"Manage rules requested for guild {interaction.guild_id}")
                await self.handle_manage_rules(interaction, session)

            else:
                self.logger.warning(f"Unhandled button custom_id: {custom_id} for guild {interaction.guild_id}")
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(
                            f"This button (`{custom_id}`) isn't implemented yet. Please use the navigation buttons.",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            f"This button (`{custom_id}`) isn't implemented yet. Please use the navigation buttons.",
                            ephemeral=True
                        )
                except discord.HTTPException as e:
                    if "already been acknowledged" in str(e).lower():
                        await interaction.followup.send(
                            f"This button (`{custom_id}`) isn't implemented yet. Please use the navigation buttons.",
                            ephemeral=True
                        )
                    else:
                        raise e

        except Exception as e:
            self.logger.error(f"Error handling button interaction ({custom_id}): {e}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ An error occurred. Please run `/setup` again.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ An error occurred. Please run `/setup` again.",
                        ephemeral=True
                    )
            except discord.HTTPException as e:
                if "already been acknowledged" in str(e).lower():
                    await interaction.followup.send(
                        "❌ An error occurred. Please run `/setup` again.",
                        ephemeral=True
                    )
                else:
                    # Log the error but don't re-raise to avoid further issues
                    self.logger.error(f"Failed to send error message: {e}")

    async def handle_select_menu(self, interaction: discord.Interaction):
        """Handle select menu interactions."""
        try:
            session = await state_manager.get_session(str(interaction.guild_id))
            if not session:
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(
                            "Setup session expired. Please run `/setup` again.",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            "Setup session expired. Please run `/setup` again.",
                            ephemeral=True
                        )
                except discord.HTTPException as e:
                    if "already been acknowledged" in str(e).lower():
                        await interaction.followup.send(
                            "Setup session expired. Please run `/setup` again.",
                            ephemeral=True
                        )
                    else:
                        raise e
                return

            custom_id = interaction.data.get('custom_id')
            values = interaction.data.get('values', [])

            if not values:
                return

            if custom_id == "log_channel_select":
                # Handle log channel selection
                channel_id = int(values[0])
                is_valid, message = await channel_selector.validate_channel_access(interaction.guild, channel_id)

                if is_valid:
                    await state_manager.update_session(interaction.guild_id, {
                        "master_log_channel": channel_id
                    })

                    # Send confirmation message
                    try:
                        if interaction.response.is_done():
                            await interaction.followup.send(
                                f"✅ Log channel set to {interaction.guild.get_channel(channel_id).mention}",
                                ephemeral=True
                            )
                        else:
                            await interaction.response.send_message(
                                f"✅ Log channel set to {interaction.guild.get_channel(channel_id).mention}",
                                ephemeral=True
                            )
                    except discord.HTTPException as e:
                        if "already been acknowledged" in str(e).lower():
                            await interaction.followup.send(
                                f"✅ Log channel set to {interaction.guild.get_channel(channel_id).mention}",
                                ephemeral=True
                            )
                        else:
                            raise e

                    await self.show_first_rule_step(interaction, session)
                else:
                    try:
                        if interaction.response.is_done():
                            await interaction.followup.send(
                                f"❌ {message}",
                                ephemeral=True
                            )
                        else:
                            await interaction.response.send_message(
                                f"❌ {message}",
                                ephemeral=True
                            )
                    except discord.HTTPException as e:
                        if "already been acknowledged" in str(e).lower():
                            await interaction.followup.send(
                                f"❌ {message}",
                                ephemeral=True
                            )
                        else:
                            raise e

            elif custom_id == "rule_source_select":
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.handle_channel_selection(interaction, session, "source", int(values[0]))

            elif custom_id == "rule_dest_select":
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.handle_channel_selection(interaction, session, "destination", int(values[0]))

        except Exception as e:
            self.logger.error(f"Error handling select menu: {e}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ An error occurred. Please try again.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ An error occurred. Please try again.",
                        ephemeral=True
                    )
            except discord.HTTPException as e:
                if "already been acknowledged" in str(e).lower():
                    await interaction.followup.send(
                        "❌ An error occurred. Please try again.",
                        ephemeral=True
                    )
                else:
                    # Log the error but don't re-raise to avoid further issues
                    self.logger.error(f"Failed to send error message: {e}")

    async def handle_back_button(self, interaction: discord.Interaction, session: SetupState):
        """Handle back button navigation."""
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
        """Updates the final rule in the database."""
        rule = session.current_rule
        if not rule or not rule.get("rule_id"):
            return False, "Rule data is missing or invalid."

        rule_id = rule["rule_id"]
        
        # We pass the entire rule dictionary as the update payload.
        # The guild_manager's update_rule method is expected to handle this.
        success = await self.guild_manager.update_rule(rule_id, rule)
        
        if success:
            return True, "Rule updated successfully."
        else:
            return False, "Failed to update the rule in the database."

    async def show_setup_complete(self, interaction: discord.Interaction, session: SetupState, is_editing: bool = False):
        """Show the final setup completion message."""
        title = "✅ Rule Updated!" if is_editing else "✅ Setup Complete!"
        description = "Your message forwarding rule has been updated." if is_editing else "Your message forwarding rules are now active."
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.green()
        )
        
        # Clean up session
        await state_manager.cleanup_session(str(interaction.guild_id))
        
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=None)
            else:
                await interaction.response.edit_message(embed=embed, view=None)
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=None)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                raise e

    async def handle_test_rule(self, interaction: discord.Interaction, session: SetupState):
        """Handle the test rule button."""
        await interaction.response.send_message("Testing rules is not yet implemented.", ephemeral=True)

    async def handle_manage_rules(self, interaction: discord.Interaction, session: SetupState):
        """Handle the manage rules button."""
        await interaction.response.send_message("Managing rules is not yet implemented.", ephemeral=True)

    async def handle_cancel_button(self, interaction: discord.Interaction, session: SetupState):
        """Handle cancel button."""
        # Clean up session
        await state_manager.cleanup_session(interaction.guild_id)

        embed = discord.Embed(
            title="❌ Setup Cancelled",
            description="Your setup progress has been cancelled. You can run `/setup` again anytime.",
            color=discord.Color.red()
        )

        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=None)
            else:
                await interaction.response.edit_message(embed=embed, view=None)
        except discord.HTTPException as e:
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=None)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                raise e

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Listen for interactions and handle setup components."""
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get('custom_id', '')

            if custom_id.endswith('_select'):
                await self.handle_select_menu(interaction)

            elif custom_id.startswith(('setup_', 'perms_', 'channel_', 'rule_', 'nav_', 'option_')):
                await self.handle_button_interaction(interaction)

async def setup(bot):
    """Setup function for the forward extension."""
    await bot.add_cog(ForwardCog(bot))