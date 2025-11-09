import discord
from typing import Callable, Awaitable


class RuleNameModal(discord.ui.Modal, title="Rule Name"):
    """A modal that prompts the user to enter or edit a name for a forwarding rule."""

    name_input = discord.ui.TextInput(
        label="Rule Name",
        placeholder="Enter a descriptive name for this rule...",
        max_length=100,
        required=True
    )

    def __init__(self, callback: Callable[[discord.Interaction, str], Awaitable[None]], current_name: str = None):
        """
        Initializes the modal.

        Args:
            callback: An awaitable function to call when the modal is submitted.
                      It receives the interaction and the new name as arguments.
            current_name: The existing name of the rule, if editing.
        """
        super().__init__()
        self.callback = callback
        if current_name:
            self.name_input.default = current_name

    async def on_submit(self, interaction: discord.Interaction):
        """
        Called when the user submits the modal. It invokes the callback
        with the interaction and the entered name.
        This method is called by the discord.py library when the user
        clicks the "Submit" button in the modal.
        """
        await self.callback(interaction, self.name_input.value)