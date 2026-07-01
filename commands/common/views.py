"""
Generic paginated embed view. Used by /forward list_rules and /premium-codes
to browse arbitrarily large lists of items without truncating to 10.
"""
from typing import Callable, List, Any, Awaitable, Union
import discord
from discord import ui


# A render callback can be sync or async; it gets the page slice + page metadata
# and returns a fully built Embed.
RenderFn = Callable[[List[Any], int, int], Union[discord.Embed, Awaitable[discord.Embed]]]


class PaginatedEmbedView(ui.View):
    """Buttons: ⏮ ◀ Page X/Y ▶ ⏭"""

    def __init__(
        self,
        items: List[Any],
        render: RenderFn,
        page_size: int = 10,
        author_id: int = None,
        timeout: float = 180,
    ):
        super().__init__(timeout=timeout)
        self.items = items
        self.render = render
        self.page_size = max(1, page_size)
        self.author_id = author_id
        self.page = 0
        self.total_pages = max(1, (len(items) + self.page_size - 1) // self.page_size)
        self._refresh_buttons()

    def _slice(self) -> List[Any]:
        start = self.page * self.page_size
        return self.items[start:start + self.page_size]

    async def _build_embed(self) -> discord.Embed:
        result = self.render(self._slice(), self.page, self.total_pages)
        if hasattr(result, "__await__"):
            result = await result
        return result

    def _refresh_buttons(self):
        self.first.disabled = self.page == 0
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page >= self.total_pages - 1
        self.last.disabled = self.page >= self.total_pages - 1
        self.indicator.label = f"{self.page + 1}/{self.total_pages}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id is not None and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the user who ran this command can page through results.",
                ephemeral=True
            )
            return False
        return True

    async def _update(self, interaction: discord.Interaction):
        self._refresh_buttons()
        embed = await self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="⏮", style=discord.ButtonStyle.secondary)
    async def first(self, interaction: discord.Interaction, button: ui.Button):
        self.page = 0
        await self._update(interaction)

    @ui.button(label="◀", style=discord.ButtonStyle.primary)
    async def prev(self, interaction: discord.Interaction, button: ui.Button):
        if self.page > 0:
            self.page -= 1
        await self._update(interaction)

    @ui.button(label="1/1", style=discord.ButtonStyle.secondary, disabled=True)
    async def indicator(self, interaction: discord.Interaction, button: ui.Button):
        # Display-only.
        await interaction.response.defer()

    @ui.button(label="▶", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        await self._update(interaction)

    @ui.button(label="⏭", style=discord.ButtonStyle.secondary)
    async def last(self, interaction: discord.Interaction, button: ui.Button):
        self.page = self.total_pages - 1
        await self._update(interaction)

    async def initial_embed(self) -> discord.Embed:
        return await self._build_embed()
