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
        if interaction.response.is_done():
            # If we already responded, edit the message
            await interaction.edit_original_response(embed=embed, view=button_manager.get_welcome_buttons())
        else:
            await interaction.response.send_message(embed=embed, view=button_manager.get_welcome_buttons())

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

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

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

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

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

        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

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

    async def start_rule_creation(self, interaction: discord.Interaction, session):
        """Start the rule creation process."""
        from .setup_helpers.rule_creation_flow import rule_creation_flow
        await rule_creation_flow.start_rule_creation(interaction, session)

    async def show_rule_name_modal(self, interaction: discord.Interaction, session):
        """Show modal for entering rule name."""
        from .models.rule_modals import RuleNameModal

        async def modal_callback(interaction: discord.Interaction, name: str):
            # Update session with rule name
            session.current_rule["rule_name"] = name
            session.current_rule["step"] = "rule_preview"

            await state_manager.update_session(interaction.guild_id, {
                "current_rule": session.current_rule
            })

            # Show rule preview
            from .setup_helpers.rule_creation_flow import rule_creation_flow
            await rule_creation_flow.show_rule_preview_step(interaction, session)

        modal = RuleNameModal(modal_callback)
        await interaction.response.send_modal(modal)

    async def handle_test_rule(self, interaction: discord.Interaction, session):
        """Handle test rule button after setup completion."""
        if session.forwarding_rules:
            rule = session.forwarding_rules[0]  # Get first rule
            source_channel = interaction.guild.get_channel(rule["source_channel_id"])

            if source_channel:
                await interaction.response.send_message(
                    f"✅ To test your rule, send a message in {source_channel.mention} and I'll forward it automatically!",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "❌ Could not find the source channel for testing.",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "❌ No rules found to test.",
                ephemeral=True
            )

    async def handle_manage_rules(self, interaction: discord.Interaction, session):
        """Handle manage rules button after setup completion."""
        # Todo: Implement rule management interface
        await interaction.response.send_message(
            "Rule management interface is not yet implemented. Use `/forward` commands to manage rules.",
            ephemeral=True
        )

    async def show_setup_complete(self, interaction: discord.Interaction, session: SetupState):
        """Show setup completion step."""
        embed = discord.Embed(
            title="🎉 Setup Complete!",
            description="Your message forwarding bot is now configured and ready to use!",
            color=discord.Color.green()
        )

        # Show what was configured
        config_summary = []

        if session.master_log_channel:
            log_channel = interaction.guild.get_channel(session.master_log_channel)
            config_summary.append(f"• **Log Channel**: {log_channel.mention if log_channel else 'Not set'}")

        if session.forwarding_rules:
            config_summary.append(f"• **Forwarding Rules**: {len(session.forwarding_rules)} created")

        if config_summary:
            embed.add_field(
                name="📋 Configuration Summary",
                value="\n".join(config_summary),
                inline=False
            )

        # Next steps
        embed.add_field(
            name="🚀 Next Steps",
            value=(
                "• Test your forwarding rule by sending a message in the source channel\n"
                "• Use `/forward` commands to manage your rules\n"
                "• Run `/setup` again to add more rules or change settings"
            ),
            inline=False
        )

        # Clean up session
        await state_manager.cleanup_session(interaction.guild_id)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Test Rule",
            style=discord.ButtonStyle.primary,
            custom_id="setup_test_rule",
            emoji="🧪"
        ))

        view.add_item(discord.ui.Button(
            label="Manage Rules",
            style=discord.ButtonStyle.secondary,
            custom_id="setup_manage_rules",
            emoji="⚙️"
        ))

        await interaction.response.edit_message(embed=embed, view=view)

    async def handle_button_interaction(self, interaction: discord.Interaction):
        """Handle button interactions from setup messages."""
        try:
            # Get the session
            session = await state_manager.get_session(interaction.guild_id)
            if not session:
                await interaction.response.send_message(
                    "❌ Setup session expired or not found. Please run `/setup` again.",
                    ephemeral=True
                )
                return

            # Update activity
            session.update_activity()

            # Handle different button types based on custom_id
            custom_id = interaction.data.get('custom_id')

            # === SETUP FLOW BUTTONS ===
            if custom_id == "setup_start":
                await self.show_permission_step(interaction, session)

            elif custom_id == "setup_learn_more":
                await self.show_learn_more(interaction, session)

            elif custom_id == "learn_back":
                await self.show_welcome_step(interaction, session)

            # === PERMISSION STEP BUTTONS ===
            elif custom_id == "perms_continue":
                await self.show_log_channel_step(interaction, session)

            elif custom_id == "perms_check_again":
                await self.show_permission_step(interaction, session)

            # === RULE CREATION BUTTONS ===
            elif custom_id == "rule_create":
                await self.start_rule_creation(interaction, session)

            elif custom_id == "rule_source_continue":
                await self.handle_rule_continue(interaction, session, "destination_channel")

            elif custom_id == "rule_dest_continue":
                await self.handle_rule_continue(interaction, session, "rule_name")

            elif custom_id == "rule_auto_name":
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                await rule_creation_flow.handle_auto_name(interaction, session)

            elif custom_id == "rule_name_input":
                await self.show_rule_name_modal(interaction, session)

            elif custom_id == "rule_final_create":
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                success, message = await rule_creation_flow.create_final_rule(interaction, session)

                if success:
                    await self.show_setup_complete(interaction, session)
                else:
                    await interaction.response.send_message(
                        f"❌ {message}",
                        ephemeral=True
                    )

            elif custom_id == "rule_edit_settings":
                # Todo: Implement rule editing
                await interaction.response.send_message(
                    "Rule editing is not yet implemented. Creating rule with default settings.",
                    ephemeral=True
                )
                # Continue with creation anyway
                from .setup_helpers.rule_creation_flow import rule_creation_flow
                success, message = await rule_creation_flow.create_final_rule(interaction, session)
                if success:
                    await self.show_setup_complete(interaction, session)

            elif custom_id == "rule_start_over":
                # Reset rule creation and start over
                session.current_rule = None
                await state_manager.update_session(interaction.guild_id, {
                    "current_rule": None
                })
                await self.start_rule_creation(interaction, session)

            # === NAVIGATION BUTTONS ===
            elif custom_id in ["nav_back", "perms_back", "channel_back", "rule_back"]:
                await self.handle_back_button(interaction, session)

            # Handle rule-specific back buttons
            elif custom_id.startswith("rule_") and custom_id.endswith("_back"):
                step = custom_id.replace("rule_", "").replace("_back", "")
                await self.handle_rule_back(interaction, session, step)

            # === CANCEL BUTTONS ===
            elif custom_id in ["setup_cancel", "perms_cancel", "channel_cancel", "rule_cancel", "nav_cancel"]:
                await self.handle_cancel_button(interaction, session)

            # Handle rule-specific cancel buttons
            elif custom_id.startswith("rule_") and custom_id.endswith("_cancel"):
                await self.handle_cancel_button(interaction, session)

            # === SETUP COMPLETION BUTTONS ===
            elif custom_id == "setup_test_rule":
                await self.handle_test_rule(interaction, session)

            elif custom_id == "setup_manage_rules":
                await self.handle_manage_rules(interaction, session)

            else:
                await interaction.response.send_message(
                    f"This button (`{custom_id}`) isn't implemented yet. Please use the navigation buttons.",
                    ephemeral=True
                )

        except Exception as e:
            self.logger.error(f"Error handling button interaction: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred. Please run `/setup` again.",
                ephemeral=True
            )

    async def handle_select_menu(self, interaction: discord.Interaction):
        """Handle select menu interactions."""
        try:
            session = await state_manager.get_session(interaction.guild_id)
            if not session:
                await interaction.response.send_message(
                    "Setup session expired. Please run `/setup` again.",
                    ephemeral=True
                )
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
                    await interaction.response.send_message(
                        f"✅ Log channel set to {interaction.guild.get_channel(channel_id).mention}",
                        ephemeral=True
                    )
                    await self.show_first_rule_step(interaction, session)
                else:
                    await interaction.response.send_message(
                        f"❌ {message}",
                        ephemeral=True
                    )

            elif custom_id == "rule_source_select":
                await self.handle_rule_channel_selection(interaction, session, "source")

            elif custom_id == "rule_dest_select":
                await self.handle_rule_channel_selection(interaction, session, "destination")

        except Exception as e:
            self.logger.error(f"Error handling select menu: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred. Please try again.",
                ephemeral=True
            )

    async def handle_rule_channel_selection(self, interaction: discord.Interaction, session, channel_type: str):
        """Handle channel selection during rule creation."""
        from .setup_helpers.rule_creation_flow import rule_creation_flow

        channel_id = int(interaction.data['values'][0])
        await rule_creation_flow.handle_channel_selection(interaction, session, channel_type, channel_id)

    async def handle_rule_continue(self, interaction: discord.Interaction, session, step: str):
        """Handle continue button in rule creation."""
        from .setup_helpers.rule_creation_flow import rule_creation_flow

        # Update step and show next
        session.current_rule["step"] = step
        await state_manager.update_session(interaction.guild_id, {
            "current_rule": session.current_rule
        })

        if step == "destination_channel":
            await rule_creation_flow.show_destination_channel_step(interaction, session)
        elif step == "rule_name":
            await rule_creation_flow.show_rule_name_step(interaction, session)

    async def handle_rule_back(self, interaction: discord.Interaction, session, current_step: str):
        """Handle back button in rule creation."""
        from .setup_helpers.rule_creation_flow import rule_creation_flow

        if current_step == "destination_channel":
            session.current_rule["step"] = "source_channel"
            await rule_creation_flow.show_source_channel_step(interaction, session)
        elif current_step == "rule_name":
            session.current_rule["step"] = "destination_channel"
            await rule_creation_flow.show_destination_channel_step(interaction, session)
        elif current_step == "rule_preview":
            session.current_rule["step"] = "rule_name"
            await rule_creation_flow.show_rule_name_step(interaction, session)

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

    async def handle_cancel_button(self, interaction: discord.Interaction, session: SetupState):
        """Handle cancel button."""
        # Clean up session
        await state_manager.cleanup_session(interaction.guild_id)

        embed = discord.Embed(
            title="❌ Setup Cancelled",
            description="Your setup progress has been cancelled. You can run `/setup` again anytime.",
            color=discord.Color.red()
        )

        await interaction.response.edit_message(embed=embed, view=None)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Listen for interactions and handle setup components."""
        if interaction.type == discord.InteractionType.component:
            custom_id = interaction.data.get('custom_id', '')

            if custom_id.startswith(('setup_', 'perms_', 'channel_', 'rule_', 'nav_', 'option_')):
                await self.handle_button_interaction(interaction)

            elif custom_id.endswith('_select'):
                await self.handle_select_menu(interaction)