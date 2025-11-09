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


class SetupCog(commands.Cog):
    """Setup wizard for configuring message forwarding."""

    def __init__(self, bot):
        self.bot = bot
        self.logger = None  # Will be set in on_ready

    async def cog_load(self):
        """Called when the cog is loaded."""
        # Initialize logger
        from logger.logger_setup import get_logger
        self.logger = get_logger("ForwardSetup", level=20, json_format=False, colored_console=True)
        self.logger.info("Forward setup cog loaded")

    @app_commands.command(name="setup", description="Start interactive setup for message forwarding")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_command(self, interaction: discord.Interaction):
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
            session = await state_manager.create_session(interaction.guild_id, interaction.user.id)

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

    async def handle_button_interaction(self, interaction: discord.Interaction):
        """Handle button interactions from setup messages."""
        custom_id = interaction.data.get('custom_id', 'unknown')
        self.logger.info(
            f"Button interaction received: {custom_id} from user {interaction.user.id} in guild {interaction.guild_id}")

        try:
            # Get the session
            session = await state_manager.get_session(interaction.guild_id)
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
                self.logger.info(f"Creating final rule for guild {interaction.guild_id}")
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                success, message = await rule_creation_flow.create_final_rule(interaction, session)

                if success:
                    self.logger.info(f"Rule created successfully for guild {interaction.guild_id}")
                    await self.show_setup_complete(interaction, session)
                else:
                    self.logger.error(f"Rule creation failed for guild {interaction.guild_id}: {message}")
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
                self.logger.info(f"Rule editing requested (not implemented) for guild {interaction.guild_id}")
                # Todo: Implement rule editing
                try:
                    if interaction.response.is_done():
                        await interaction.followup.send(
                            "Rule editing is not yet implemented. Creating rule with default settings.",
                            ephemeral=True
                        )
                    else:
                        await interaction.response.send_message(
                            "Rule editing is not yet implemented. Creating rule with default settings.",
                            ephemeral=True
                        )
                except discord.HTTPException as e:
                    if "already been acknowledged" in str(e).lower():
                        await interaction.followup.send(
                            "Rule editing is not yet implemented. Creating rule with default settings.",
                            ephemeral=True
                        )
                    else:
                        raise e

                # Continue with creation anyway
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                success, message = await rule_creation_flow.create_final_rule(interaction, session)
                if success:
                    await self.show_setup_complete(interaction, session)

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
            session = await state_manager.get_session(interaction.guild_id)
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

    async def show_setup_complete(self, interaction: discord.Interaction, session: SetupState):
        """Show the final setup completion message."""
        embed = discord.Embed(
            title="✅ Setup Complete!",
            description="Your message forwarding rules are now active.",
            color=discord.Color.green()
        )
        
        # Clean up session
        await state_manager.cleanup_session(interaction.guild_id)
        
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
    await bot.add_cog(SetupCog(bot))