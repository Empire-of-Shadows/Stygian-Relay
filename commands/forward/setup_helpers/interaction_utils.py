import logging
from typing import Optional

import discord

logger = logging.getLogger(__name__)

# Discord error codes the response ladder needs to recover from.
_INTERACTION_ACK = 40060   # Interaction has already been acknowledged.
_INTERACTION_GONE = 10062  # Unknown interaction (token expired / never sent).


async def safe_respond(
    interaction: discord.Interaction,
    *,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    ephemeral: bool = True,
    edit: bool = False,
) -> Optional[discord.Message]:
    """
    Render a response to ``interaction`` while tolerating the two states the
    raw API forces us to handle: the interaction has already been
    acknowledged, or its token is no longer usable.

    ``edit=True`` performs an in-place edit of the originating component
    message — use this for button/select callbacks that should refresh the
    panel they live on. ``edit=False`` (the default) sends a fresh ephemeral
    response — use this for slash-command invocations.

    Returns the resulting ``Message`` when one can be fetched, otherwise
    ``None``. When ``view`` is supplied, ``view.message`` is wired up so the
    library's built-in timeout handling can disable components later.
    """
    kwargs: dict = {}
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs)
        elif edit:
            await interaction.response.edit_message(**kwargs)
        else:
            await interaction.response.send_message(ephemeral=ephemeral, **kwargs)
    except discord.HTTPException as e:
        if e.code not in (_INTERACTION_ACK, _INTERACTION_GONE):
            raise
        # Acknowledged or gone — try the alternates in order of preference.
        try:
            await interaction.edit_original_response(**kwargs)
        except discord.HTTPException:
            try:
                await interaction.followup.send(ephemeral=ephemeral, **kwargs)
            except discord.HTTPException as followup_error:
                logger.error(
                    f"Failed all interaction response methods: {followup_error}"
                )
                return None

    try:
        message = await interaction.original_response()
    except discord.HTTPException:
        return None
    if view is not None:
        view.message = message
    return message
