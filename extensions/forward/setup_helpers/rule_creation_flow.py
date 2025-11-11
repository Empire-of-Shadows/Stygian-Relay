import discord
from typing import Tuple

from ..models.setup_state import SetupState
from .channel_select import channel_selector
from .state_manager import state_manager
from logger.logger_setup import get_logger


class RuleCreationFlow:
    """Handles the step-by-step process of creating a forwarding rule."""

    def __init__(self, bot, cog):
        self.bot = bot
        self.cog = cog
        self.logger = get_logger("RuleCreationFlow", level=20, json_format=False, colored_console=True)

    async def start_rule_creation(self, interaction: discord.Interaction):
        """
        Starts the rule creation flow by initializing a new rule in the user's
        session and showing the first step (source channel selection).
        """
        session = await state_manager.get_session(interaction.guild_id)
        if not session:
            # If no session is found, create one. This might happen if the session expired right at this moment.
            session = await state_manager.create_session(interaction.guild_id, interaction.user.id)

        self.logger.info(f"Starting rule creation for guild {interaction.guild_id}")
        session.current_rule = {
            "step": "source_channel"
        }
        await state_manager.update_session(interaction.guild_id, {
            "current_rule": session.current_rule
        })
        self.logger.debug(f"Rule session initialized for guild {interaction.guild_id}")
        await self.show_source_channel_step(interaction, session)

    # In your RuleCreationFlow class or in the ForwardCog, update the channel selection methods:

    async def show_source_channel_step(self, interaction: discord.Interaction, session: SetupState):
        """Show source channel selection step with direct callbacks"""
        embed = discord.Embed(
            title="📥 Select Source Channel",
            description="Choose the channel where messages will be forwarded **FROM**.\n\n"
                        "This is the channel that will be monitored for new messages.",
            color=discord.Color.blue()
        )

        # Create select menu with direct callback
        view = discord.ui.View(timeout=300)

        select_options = []
        for channel in interaction.guild.text_channels:
            if channel.permissions_for(interaction.guild.me).view_channel:
                select_options.append(
                    discord.SelectOption(
                        label=f"#{channel.name}"[:25],
                        value=str(channel.id),
                        description=f"ID: {channel.id}"[:50]
                    )
                )

        if select_options:
            select_menu = discord.ui.Select(
                placeholder="Select source channel...",
                options=select_options[:25],
                custom_id="rule_source_select"
            )
            view.add_item(select_menu)
        else:
            view.add_item(discord.ui.Button(
                label="No accessible channels found",
                disabled=True,
                style=discord.ButtonStyle.secondary # Type: Ignore
            ))

        # Add navigation buttons
        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary, # Type: Ignore
            custom_id="rule_source_back",
            emoji="⬅️",
            row=1
        )
        view.add_item(back_button)

        cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger, # Type: Ignore
            custom_id="rule_source_cancel",
            emoji="✖️",
            row=1
        )
        view.add_item(cancel_button)

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

    async def show_destination_channel_step(self, interaction: discord.Interaction, session: SetupState):
        """Show destination channel selection step with direct callbacks"""
        embed = discord.Embed(
            title="📤 Select Destination Channel",
            description="Choose the channel where messages will be forwarded **TO**.\n\n"
                        "This is where the forwarded messages will appear.",
            color=discord.Color.blue()
        )

        # Create select menu with direct callback
        view = discord.ui.View(timeout=300)

        select_options = []
        for channel in interaction.guild.text_channels:
            if channel.permissions_for(interaction.guild.me).send_messages:
                select_options.append(
                    discord.SelectOption(
                        label=f"#{channel.name}"[:25],
                        value=str(channel.id),
                        description=f"ID: {channel.id}"[:50]
                    )
                )

        if select_options:
            select_menu = discord.ui.Select(
                placeholder="Select destination channel...",
                options=select_options[:25],
                custom_id="rule_dest_select"
            )
            view.add_item(select_menu)
        else:
            view.add_item(discord.ui.Button(
                label="No writable channels found",
                disabled=True,
                style=discord.ButtonStyle.secondary # Type: Ignore
            ))

        # Add navigation buttons
        back_button = discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary, # Type: Ignore
            custom_id="rule_dest_back",
            emoji="⬅️",
            row=1
        )
        view.add_item(back_button)

        cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger, # Type: Ignore
            custom_id="rule_dest_cancel",
            emoji="✖️",
            row=1
        )
        view.add_item(cancel_button)

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

    async def handle_channel_selection(self, interaction: discord.Interaction, session: SetupState, channel_type: str,
                                       channel_id: int):
        """
        Handles the selection of a source or destination channel.
        This method is called when the user selects a channel from the dropdown.
        """
        self.logger.info(f"Channel selected: {channel_type} = {channel_id} for guild {interaction.guild_id}")
        
        if session.current_rule is None:
            self.logger.warning(f"session.current_rule is None, initialising to prevent errors")
            session.current_rule = {}
            
        is_valid, message = await channel_selector.validate_channel_access(interaction.guild, channel_id)

        if not is_valid:
            self.logger.warning(f"Invalid channel selection: {message} for guild {interaction.guild_id}")
            await interaction.followup.send(f"❌ {message}", ephemeral=True)
            return

        if channel_type == "source":
            session.current_rule["source_channel_id"] = channel_id
            self.logger.info(f"Source channel set to {channel_id} for guild {interaction.guild_id}")
            await interaction.followup.send(
                f"✅ Source channel set to {interaction.guild.get_channel(channel_id).mention}", ephemeral=True)
            await self.show_destination_channel_step(interaction, session)
        elif channel_type == "destination":
            session.current_rule["destination_channel_id"] = channel_id
            self.logger.info(f"Destination channel set to {channel_id} for guild {interaction.guild_id}")
            await interaction.followup.send(
                f"✅ Destination channel set to {interaction.guild.get_channel(channel_id).mention}", ephemeral=True)
            await self.show_rule_name_step(interaction, session)

    async def show_rule_name_step(self, interaction: discord.Interaction, session: SetupState):
        """
        Show the rule name input step.
        This is the third step in creating a new rule.
        """
        self.logger.debug(f"Showing rule name step for guild {interaction.guild_id}")
        embed = discord.Embed(
            title="📝 Rule Name",
            description="Please provide a name for this rule.",
            color=discord.Color.blue()
        )
        from ..setup_helpers.button_manager import button_manager
        view = button_manager.create_button_row([
            {"label": "Enter Name", "style": discord.ButtonStyle.primary, "custom_id": "rule_name_input"},
            {"label": "Use Auto-generated Name", "style": discord.ButtonStyle.secondary, "custom_id": "rule_auto_name"}
        ])

        try:
            if interaction.response.is_done(): # Type: Ignore
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view) # Type: Ignore
            self.logger.info(f"Rule name step displayed for guild {interaction.guild_id}")
        except discord.HTTPException as e:
            self.logger.error(f"Error displaying rule name step: {e}", exc_info=True)
            if "already been acknowledged" in str(e).lower():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                raise e

    async def handle_auto_name(self, interaction: discord.Interaction, session: SetupState):
        """
        Generate a default rule name based on the selected channels.
        This method is called when the user clicks the "Use Auto-generated Name"
        button.
        """
        source_channel = interaction.guild.get_channel(session.current_rule["source_channel_id"])
        dest_channel = interaction.guild.get_channel(session.current_rule["destination_channel_id"])
        rule_name = f"Forward from #{source_channel.name} to #{dest_channel.name}"
        session.current_rule["rule_name"] = rule_name
        self.logger.info(f"Auto-generated rule name: '{rule_name}' for guild {interaction.guild_id}")
        await self.show_rule_preview_step(interaction, session)

    async def show_rule_preview_step(self, interaction: discord.Interaction, session: SetupState):
        """
        Show a preview of the rule before creation.
        This is the final step before creating the rule.
        """
        self.logger.debug(f"Showing rule preview for guild {interaction.guild_id}")
        from .rule_setup import rule_setup_helper
        rule = await rule_setup_helper.create_initial_rule(
            source_channel_id=session.current_rule["source_channel_id"],
            destination_channel_id=session.current_rule["destination_channel_id"],
            rule_name=session.current_rule["rule_name"]
        )
        embed = await rule_setup_helper.create_rule_preview_embed(rule, interaction.guild)
        from ..setup_helpers.button_manager import button_manager
        edit_settings_button = {
            "label": "Edit Settings",
            "style": discord.ButtonStyle.secondary,
            "custom_id": "rule_edit_settings",
            "disabled": not session.is_editing  # Disable if not editing an existing rule
        }
        view = button_manager.create_button_row([
            {"label": "Create Rule", "style": discord.ButtonStyle.success, "custom_id": "rule_final_create"},
            edit_settings_button,
            {"label": "Start Over", "style": discord.ButtonStyle.danger, "custom_id": "rule_start_over"}
        ])

        try:
            if interaction.response.is_done():  # Type: Ignore
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view)  # Type: Ignore
            self.logger.info(f"Rule preview displayed for guild {interaction.guild_id}")
        except discord.HTTPException as e:
            if e.code == 40060:  # Interaction has already been acknowledged
                self.logger.info("Interaction already acknowledged when showing rule preview, editing instead.")
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                self.logger.error(f"Error displaying rule preview: {e}", exc_info=True)
                raise e

    async def create_final_rule(self, interaction: discord.Interaction, session: SetupState) -> Tuple[bool, str]:
        """
        Validates the rule stored in the session, saves it to the database,
        and returns the result.
        """
        self.logger.info(f"Creating final rule for guild {interaction.guild_id}")
        try:
            from .rule_setup import rule_setup_helper
            rule = await rule_setup_helper.create_initial_rule(
                source_channel_id=session.current_rule["source_channel_id"],
                destination_channel_id=session.current_rule["destination_channel_id"],
                rule_name=session.current_rule["rule_name"]
            )

            is_valid, errors = await rule_setup_helper.validate_rule_configuration(rule, interaction.guild)
            if not is_valid:
                error_msg = " ".join(errors)
                self.logger.error(f"Rule validation failed: {error_msg}")
                return False, error_msg

            session.forwarding_rules.append(rule)
            await state_manager.update_session(interaction.guild_id, {"rules": session.forwarding_rules})

            from database import guild_manager
            rule_data = {
                "rule_name": rule.get("name"),
                "source_channel_id": rule.get("source_channel_id"),
                "destination_channel_id": rule.get("destination_channel_id"),
                "enabled": rule.get("is_active", True),
                "settings": {
                    "message_types": rule.get("message_types", {}),
                    "filters": rule.get("filters", {}),
                    "formatting": rule.get("formatting", {}),
                    "advanced_options": rule.get("advanced_options", {})
                }
            }

            save_result = await guild_manager.add_rule(guild_id=interaction.guild_id, **rule_data)

            if save_result:
                self.logger.info(f"✅ Rule '{rule_data['rule_name']}' saved successfully for guild {interaction.guild_id}")
                await state_manager.cleanup_session(interaction.guild_id)
                return True, "Rule created and saved successfully."
            else:
                self.logger.error(f"Failed to save rule to database for guild {interaction.guild_id}")
                return False, "Rule created but failed to save to database. Please try again."

        except Exception as e:
            self.logger.error(f"Error creating final rule: {e}", exc_info=True)
            return False, f"An error occurred while creating the rule: {str(e)}"

    async def handle_rule_back(self, interaction: discord.Interaction, session: SetupState, cog_instance, step: str):
        """
        Handles 'back' navigation within the rule creation flow.
        This method is called when the user clicks a back button in the rule
        creation flow.
        """
        self.logger.info(f"Handling back navigation for step: {step} in guild {interaction.guild_id}")
        if step == "source":
            await cog_instance.show_first_rule_step(interaction, session)
        elif step == "destination":
            await self.show_source_channel_step(interaction, session)
        elif step == "name":
            await self.show_destination_channel_step(interaction, session)
        elif step == "preview":
            await self.show_rule_name_step(interaction, session)
        else:
            self.logger.warning(f"Unknown step '{step}', defaulting to source channel")
            await self.show_source_channel_step(interaction, session)