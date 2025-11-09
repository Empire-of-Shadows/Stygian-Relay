
"""
Manages the interactive flow for creating a new forwarding rule.
"""
import discord
from typing import Optional, Tuple

from ..models.setup_state import SetupState
from .channel_select import channel_selector
from .state_manager import state_manager

# Import logger
from logger.logger_setup import get_logger


class RuleCreationFlow:
    """Handles the step-by-step process of creating a forwarding rule."""

    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("RuleCreationFlow", level=20, json_format=False, colored_console=True)

    async def start_rule_creation(self, interaction: discord.Interaction, session: SetupState):
        """Start the rule creation flow."""
        self.logger.info(f"Starting rule creation for guild {interaction.guild_id}")
        # Initialize a new rule in the session
        session.current_rule = {
            "step": "source_channel"
        }
        await state_manager.update_session(interaction.guild_id, {
            "current_rule": session.current_rule
        })
        self.logger.debug(f"Rule session initialized for guild {interaction.guild_id}")
        await self.show_source_channel_step(interaction, session)

    async def show_source_channel_step(self, interaction: discord.Interaction, session: SetupState):
        """Show the source channel selection step."""
        self.logger.debug(f"Showing source channel selection for guild {interaction.guild_id}")
        embed = await channel_selector.create_channel_embed(interaction.guild, "source_channel")
        view = await channel_selector.create_channel_select_menu(
            interaction.guild, "text", "rule_source_select"
        )

        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view)
            self.logger.info(f"Source channel selection displayed for guild {interaction.guild_id}")
        except discord.HTTPException as e:
            self.logger.error(f"Error displaying source channel selection: {e}", exc_info=True)
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

    async def show_destination_channel_step(self, interaction: discord.Interaction, session: SetupState):
        """Show the destination channel selection step."""
        self.logger.debug(f"Showing destination channel selection for guild {interaction.guild_id}")
        embed = await channel_selector.create_channel_embed(interaction.guild, "destination_channel")
        view = await channel_selector.create_channel_select_menu(
            interaction.guild, "text", "rule_dest_select"
        )

        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view)
            self.logger.info(f"Destination channel selection displayed for guild {interaction.guild_id}")
        except discord.HTTPException as e:
            self.logger.error(f"Error displaying destination channel selection: {e}", exc_info=True)
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

    async def handle_channel_selection(self, interaction: discord.Interaction, session: SetupState, channel_type: str,
                                       channel_id: int):
        """Handle channel selection for source or destination."""
        self.logger.info(f"Channel selected: {channel_type} = {channel_id} for guild {interaction.guild_id}")
        is_valid, message = await channel_selector.validate_channel_access(interaction.guild, channel_id)

        if not is_valid:
            self.logger.warning(f"Invalid channel selection: {message} for guild {interaction.guild_id}")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(f"❌ {message}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ {message}", ephemeral=True)
            except discord.HTTPException as e:
                if "already been acknowledged" in str(e).lower():
                    await interaction.followup.send(f"❌ {message}", ephemeral=True)
                else:
                    raise e
            return

        if channel_type == "source":
            session.current_rule["source_channel_id"] = channel_id
            self.logger.info(f"Source channel set to {channel_id} for guild {interaction.guild_id}")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        f"✅ Source channel set to {interaction.guild.get_channel(channel_id).mention}", ephemeral=True)
                else:
                    await interaction.response.send_message(
                        f"✅ Source channel set to {interaction.guild.get_channel(channel_id).mention}", ephemeral=True)
            except discord.HTTPException as e:
                if "already been acknowledged" in str(e).lower():
                    await interaction.followup.send(
                        f"✅ Source channel set to {interaction.guild.get_channel(channel_id).mention}", ephemeral=True)
                else:
                    raise e
            await self.show_destination_channel_step(interaction, session)
        elif channel_type == "destination":
            session.current_rule["destination_channel_id"] = channel_id
            self.logger.info(f"Destination channel set to {channel_id} for guild {interaction.guild_id}")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        f"✅ Destination channel set to {interaction.guild.get_channel(channel_id).mention}",
                        ephemeral=True)
                else:
                    await interaction.response.send_message(
                        f"✅ Destination channel set to {interaction.guild.get_channel(channel_id).mention}",
                        ephemeral=True)
            except discord.HTTPException as e:
                if "already been acknowledged" in str(e).lower():
                    await interaction.followup.send(
                        f"✅ Destination channel set to {interaction.guild.get_channel(channel_id).mention}",
                        ephemeral=True)
                else:
                    raise e
            await self.show_rule_name_step(interaction, session)



    async def show_rule_name_step(self, interaction: discord.Interaction, session: SetupState):
        """Show the rule name input step."""
        self.logger.debug(f"Showing rule name step for guild {interaction.guild_id}")
        embed = discord.Embed(
            title="📝 Rule Name",
            description="Please provide a name for this rule.",
            color=discord.Color.blue()
        )
        from ..setup_helpers.button_manager import button_manager
        view = button_manager.create_button_row([
            {
                "label": "Enter Name",
                "style": discord.ButtonStyle.primary,
                "custom_id": "rule_name_input"
            },
            {
                "label": "Use Auto-generated Name",
                "style": discord.ButtonStyle.secondary,
                "custom_id": "rule_auto_name"
            }
        ])

        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view)
            self.logger.info(f"Rule name step displayed for guild {interaction.guild_id}")
        except discord.HTTPException as e:
            self.logger.error(f"Error displaying rule name step: {e}", exc_info=True)
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

    async def handle_auto_name(self, interaction: discord.Interaction, session: SetupState):
        """Handle auto-naming the rule."""
        source_channel = interaction.guild.get_channel(session.current_rule["source_channel_id"])
        dest_channel = interaction.guild.get_channel(session.current_rule["destination_channel_id"])
        rule_name = f"Forward from #{source_channel.name} to #{dest_channel.name}"
        session.current_rule["rule_name"] = rule_name
        self.logger.info(f"Auto-generated rule name: '{rule_name}' for guild {interaction.guild_id}")
        await self.show_rule_preview_step(interaction, session)

    async def show_rule_preview_step(self, interaction: discord.Interaction, session: SetupState):
        """Show a preview of the rule before creation."""
        self.logger.debug(f"Showing rule preview for guild {interaction.guild_id}")
        from .rule_setup import rule_setup_helper
        rule = await rule_setup_helper.create_initial_rule(
            source_channel_id=session.current_rule["source_channel_id"],
            destination_channel_id=session.current_rule["destination_channel_id"],
            rule_name=session.current_rule["rule_name"]
        )
        embed = await rule_setup_helper.create_rule_preview_embed(rule, interaction.guild)
        from ..setup_helpers.button_manager import button_manager
        view = button_manager.create_button_row([
            {
                "label": "Create Rule",
                "style": discord.ButtonStyle.success,
                "custom_id": "rule_final_create"
            },
            {
                "label": "Edit Settings",
                "style": discord.ButtonStyle.secondary,
                "custom_id": "rule_edit_settings"
            },
            {
                "label": "Start Over",
                "style": discord.ButtonStyle.danger,
                "custom_id": "rule_start_over"
            }
        ])

        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=view)
            else:
                await interaction.response.send_message(embed=embed, view=view)
            self.logger.info(f"Rule preview displayed for guild {interaction.guild_id}")
        except discord.HTTPException as e:
            self.logger.error(f"Error displaying rule preview: {e}", exc_info=True)
            if "already been acknowledged" in str(e).lower():
                try:
                    await interaction.edit_original_response(embed=embed, view=view)
                except discord.HTTPException:
                    await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            else:
                raise e

    async def create_final_rule(self, interaction: discord.Interaction, session: SetupState) -> Tuple[bool, str]:
        """Create the final rule and save it to the database."""
        self.logger.info(f"Creating final rule for guild {interaction.guild_id}")
        try:
            from .rule_setup import rule_setup_helper
            rule = await rule_setup_helper.create_initial_rule(
                source_channel_id=session.current_rule["source_channel_id"],
                destination_channel_id=session.current_rule["destination_channel_id"],
                rule_name=session.current_rule["rule_name"]
            )

            # Validate the rule
            is_valid, errors = await rule_setup_helper.validate_rule_configuration(rule, interaction.guild)
            if not is_valid:
                error_msg = " ".join(errors)
                self.logger.error(f"Rule validation failed: {error_msg}")
                return False, error_msg

            # Add rule to session (for display purposes)
            session.forwarding_rules.append(rule)
            await state_manager.update_session(interaction.guild_id, {
                "forwarding_rules": session.forwarding_rules
            })

            # SAVE TO DATABASE
            self.logger.info(f"Saving rule to database for guild {interaction.guild_id}")
            from database import guild_manager

            # Prepare rule data for database
            rule_data = {
                "rule_name": rule.get("name"),
                "source_channel_id": rule.get("source_channel_id"),
                "destination_channel_id": rule.get("destination_channel_id"),
                "enabled": rule.get("enabled", True),
                "settings": rule.get("settings", {})
            }

            # Save to database
            save_result = await guild_manager.add_forwarding_rule(
                guild_id=interaction.guild_id,
                **rule_data
            )

            if save_result:
                self.logger.info(f"✅ Rule '{rule_data['rule_name']}' saved successfully to database for guild {interaction.guild_id}")
                return True, "Rule created and saved successfully."
            else:
                self.logger.error(f"Failed to save rule to database for guild {interaction.guild_id}")
                return False, "Rule created but failed to save to database. Please try again."

        except Exception as e:
            self.logger.error(f"Error creating final rule: {e}", exc_info=True)
            return False, f"An error occurred while creating the rule: {str(e)}"

    async def handle_rule_back(self, interaction: discord.Interaction, session: SetupState, step: str):
        """Handle back navigation within rule creation."""
        self.logger.info(f"Handling back navigation for step: {step} in guild {interaction.guild_id}")
        if step == "source":
            # Go back to the first rule step
            from ..setup import SetupCog
            setup_cog = SetupCog(self.bot)
            await setup_cog.show_first_rule_step(interaction, session)
        elif step == "destination":
            await self.show_source_channel_step(interaction, session)
        elif step == "name":
            await self.show_destination_channel_step(interaction, session)
        elif step == "preview":
            await self.show_rule_name_step(interaction, session)
        else:
            # Default back to source channel
            self.logger.warning(f"Unknown step '{step}', defaulting to source channel")
            await self.show_source_channel_step(interaction, session)

rule_creation_flow = RuleCreationFlow(None)