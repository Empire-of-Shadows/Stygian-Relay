"""Admin cog loader (bot-owned seam).

The admin panel ships as the installed ``admin_engine`` package; the engine no longer
relative-imports the bot's seam. This shim injects relay's ``bindings`` + ``MAIN_PANEL`` into the
engine's ``AdminCog`` at startup. It is the one file under ``admin/`` with a ``setup()``, so the
cog auto-loader (``startup/sync.py`` walks ``admin/``) picks it up; ``bindings`` /
``panel_configs`` define no ``setup()`` and are skipped.
"""

from admin_engine import AdminCog

from admin import bindings, panel_configs


async def setup(bot):
    await bot.add_cog(AdminCog(bot, bindings=bindings, panel=panel_configs.MAIN_PANEL))
