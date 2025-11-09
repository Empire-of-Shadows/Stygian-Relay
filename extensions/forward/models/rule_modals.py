"""
Modals for rule configuration input.
"""
import discord


class RuleNameModal(discord.ui.Modal, title="Rule Name"):
    """Modal for entering rule name."""

    name_input = discord.ui.TextInput(
        label="Rule Name",
        placeholder="Enter a descriptive name for this rule...",
        max_length=100,
        required=True
    )

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    async def on_submit(self, interaction: discord.Interaction):
        await self.callback(interaction, self.name_input.value)