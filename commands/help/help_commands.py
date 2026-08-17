"""
Help Command System

/help - ephemeral Components v2 panel: one accent-colored container per page
(Section + Thumbnail header, Separator, body text) with a category select for
navigation, a dashboard link, and a close button. Each select interaction
builds a fresh view and edits the original message, matching the admin panel
pattern. Category content lives in help_content.py.
"""

import logging
from pathlib import Path

import discord
from discord import ui, app_commands
from discord.ext import commands

from commands.help.help_content import (
    CATEGORIES,
    CATEGORY_ORDER,
    DASHBOARD_URL,
    DEFAULT_CATEGORY,
)

logger = logging.getLogger("Help")

# Relay ships no help artwork yet, so every category sets thumbnail=None and
# falls back to the bot avatar. The path is here for when assets are added.
ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"


class RelayHelpView(ui.LayoutView):
    """Ephemeral help panel with a category-selector dropdown."""

    def __init__(
        self,
        bot: commands.Bot,
        is_admin: bool,
        current_key: str = DEFAULT_CATEGORY,
        timeout: float = 300.0,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.is_admin = is_admin
        category = CATEGORIES.get(current_key)
        if category is None or (category.admin_only and not is_admin):
            current_key = DEFAULT_CATEGORY
        self.current_key = current_key
        # Files the sender must attach alongside this view (page thumbnail).
        self.files: list[discord.File] = []
        self._populate()

    def _visible_keys(self) -> list[str]:
        return [
            key for key in CATEGORY_ORDER
            if self.is_admin or not CATEGORIES[key].admin_only
        ]

    def _populate(self) -> None:
        category = CATEGORIES[self.current_key]

        if category.thumbnail:
            media = f"attachment://{category.thumbnail}"
            self.files = [
                discord.File(ASSETS_DIR / category.thumbnail, filename=category.thumbnail)
            ]
        else:
            media = str(self.bot.user.display_avatar.url)
            self.files = []

        header = ui.Section(accessory=ui.Thumbnail(media=media))
        header.add_item(ui.TextDisplay(f"# {category.emoji} {category.label}"))
        header.add_item(ui.TextDisplay(category.blurb))

        container = ui.Container()
        container.accent_color = category.accent
        container.add_item(header)
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(category.body))
        self.add_item(container)

        select = ui.Select(
            placeholder="Pick a help category...",
            options=[
                discord.SelectOption(
                    label=CATEGORIES[key].label,
                    value=key,
                    description=CATEGORIES[key].description,
                    emoji=CATEGORIES[key].emoji,
                    default=(key == self.current_key),
                )
                for key in self._visible_keys()
            ],
        )
        select.callback = self._on_select
        self.add_item(ui.ActionRow(select))

        dashboard_btn = ui.Button(label="Dashboard", url=DASHBOARD_URL)
        close_btn = ui.Button(label="Close", style=discord.ButtonStyle.secondary)
        close_btn.callback = self._on_close
        self.add_item(ui.ActionRow(dashboard_btn, close_btn))

    async def _on_select(self, interaction: discord.Interaction) -> None:
        selected = (interaction.data or {}).get("values", [DEFAULT_CATEGORY])[0]
        refreshed = RelayHelpView(
            self.bot,
            self.is_admin,
            current_key=selected,
            timeout=self.timeout or 300.0,
        )
        await interaction.response.edit_message(
            view=refreshed, attachments=refreshed.files
        )
        self.stop()

    async def _on_close(self, interaction: discord.Interaction) -> None:
        closed = ui.LayoutView()
        closed.add_item(ui.TextDisplay("Help closed. Run /help any time."))
        await interaction.response.edit_message(view=closed, attachments=[])
        self.stop()


class HelpCommands(commands.Cog):
    """Public /help command. Ephemeral, browses categories via dropdown."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        logger.info("HelpCommands cog initialized")

    @staticmethod
    async def _is_admin(interaction: discord.Interaction) -> bool:
        """Does this member get the admin help page?

        Uses the same answer as the /admin panel, so a holder of the configured
        Manager Role - who can open and use the whole panel - is not told the
        admin commands do not exist. Manage Server alone still qualifies, and
        stays the fallback if the settings lookup cannot be reached.
        """
        try:
            from admin.settings.bindings import resolve_panel_role

            return await resolve_panel_role(interaction.user, interaction.guild_id) == "admin"
        except Exception as e:                       # noqa: BLE001 - help must still render
            logger.warning("Panel-role lookup failed, falling back to Manage Server: %s", e)
            perms = getattr(interaction.user, "guild_permissions", None)
            return bool(perms and perms.manage_guild)

    @app_commands.command(name="help", description="\N{BOOKS} View bot commands and documentation")
    @app_commands.guild_only()
    async def help(self, interaction: discord.Interaction):
        try:
            is_admin = await self._is_admin(interaction)
            view = RelayHelpView(self.bot, is_admin)
            await interaction.response.send_message(
                view=view, files=view.files, ephemeral=True
            )
            logger.info(
                "Help command invoked by %s (admin: %s)", interaction.user, is_admin
            )
        except Exception as e:
            logger.error(f"Error in help command: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "An error occurred while loading the help menu. Please try again later.",
                    ephemeral=True,
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCommands(bot))
    logger.info("HelpCommands cog loaded successfully")
