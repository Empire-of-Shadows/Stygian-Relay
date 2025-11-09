from typing import List, Optional, Dict, Any
import discord


class ButtonManager:
    """Manages interactive buttons for setup flows."""

    # Button style mappings
    PRIMARY = discord.ButtonStyle.primary
    SECONDARY = discord.ButtonStyle.secondary
    SUCCESS = discord.ButtonStyle.success
    DANGER = discord.ButtonStyle.danger

    def __init__(self):
        self.button_callbacks = {}

    def create_button_row(self, buttons: List[Dict[str, Any]]) -> discord.ui.View:
        """
        Create a row of buttons with callbacks.
        This method is the primary way to create a view with buttons.
        """
        view = discord.ui.View(timeout=1800)  # 30 minute timeout

        for button_config in buttons:
            button = discord.ui.Button(
                label=button_config.get("label", ""),
                style=button_config.get("style", self.SECONDARY),
                custom_id=button_config.get("custom_id"),
                emoji=button_config.get("emoji"),
                disabled=button_config.get("disabled", False),
                row=button_config.get("row", 0)
            )

            # Store callback for this button
            if "callback" in button_config:
                self.button_callbacks[button_config["custom_id"]] = button_config["callback"]
                button.callback = self._create_button_callback(button_config["custom_id"])

            view.add_item(button)

        return view

    def _create_button_callback(self, custom_id: str):
        """
        Create a callback function for a button.
        This method is used to create a callback that can be assigned to a
        button.
        """

        async def button_callback(interaction: discord.Interaction):
            callback = self.button_callbacks.get(custom_id)
            if callback:
                await callback(interaction)
            # No-op if no callback is defined, allowing the global listener to handle it.

        return button_callback

    def get_welcome_buttons(self) -> discord.ui.View:
        """
        Get buttons for the welcome step.
        This view is shown to the user when they start the setup wizard.
        """
        buttons = [
            {
                "label": "Start Setup",
                "style": self.SUCCESS,
                "custom_id": "setup_start",
                "emoji": "🚀"
            },
            {
                "label": "Learn More",
                "style": self.SECONDARY,
                "custom_id": "setup_learn_more",
                "emoji": "❓"
            },
            {
                "label": "Cancel",
                "style": self.DANGER,
                "custom_id": "setup_cancel",
                "emoji": "✖️"
            }
        ]
        return self.create_button_row(buttons)

    def get_yes_no_buttons(self) -> discord.ui.View:
        """
        Get standard Yes/No buttons.
        This view is used for simple yes/no questions.
        """
        buttons = [
            {
                "label": "Yes",
                "style": self.SUCCESS,
                "custom_id": "option_yes",
                "emoji": "✅"
            },
            {
                "label": "No",
                "style": self.DANGER,
                "custom_id": "option_no",
                "emoji": "❌"
            },
            {
                "label": "Back",
                "style": self.SECONDARY,
                "custom_id": "option_back",
                "emoji": "⬅️"
            }
        ]
        return self.create_button_row(buttons)

    def get_navigation_buttons(self, include_back: bool = True, include_skip: bool = False) -> discord.ui.View:
        """
        Get navigation buttons for setup steps.
        This view is used for navigating between steps in the setup wizard.
        """
        buttons = []

        if include_back:
            buttons.append({
                "label": "Back",
                "style": self.SECONDARY,
                "custom_id": "nav_back",
                "emoji": "⬅️"
            })

        if include_skip:
            buttons.append({
                "label": "Skip",
                "style": self.SECONDARY,
                "custom_id": "nav_skip",
                "emoji": "⏭️"
            })

        buttons.append({
            "label": "Continue",
            "style": self.SUCCESS,
            "custom_id": "nav_continue",
            "emoji": "➡️"
        })

        buttons.append({
            "label": "Cancel",
            "style": self.DANGER,
            "custom_id": "nav_cancel",
            "emoji": "✖️"
        })

        return self.create_button_row(buttons)

    def get_channel_select_buttons(self) -> discord.ui.View:
        """
        Get buttons for channel selection steps.
        This view is used when the user needs to select a channel.
        """
        buttons = [
            {
                "label": "Select Channel",
                "style": self.PRIMARY,
                "custom_id": "channel_select",
                "emoji": "🔍"
            },
            {
                "label": "Back",
                "style": self.SECONDARY,
                "custom_id": "channel_back",
                "emoji": "⬅️"
            },
            {
                "label": "Skip for Now",
                "style": self.SECONDARY,
                "custom_id": "channel_skip",
                "emoji": "⏭️"
            }
        ]
        return self.create_button_row(buttons)


# Global button manager instance
button_manager = ButtonManager()