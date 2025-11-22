# extensions/forward/views/custom_views.py

import discord
import logging

logger = logging.getLogger("Forward.View")

class CustomView(discord.ui.View):
    """
    A custom view that handles timeouts gracefully by disabling components
    and logging the timeout event without trying to edit the original message
    if the interaction is likely expired.
    """
    def __init__(self, *, timeout: float | None = 180):
        super().__init__(timeout=timeout)
        self.message: discord.Message | None = None
        self._interaction: discord.Interaction | None = None

    async def on_timeout(self) -> None:
        logger.info(f"View timed out after {self.timeout} seconds for message {self.message.id if self.message else 'unknown'}.")
        for item in self.children:
            item.disabled = True
        
        # If we have the message object, we can try to edit it.
        # This is safer than using the interaction object from `view.start()`,
        # which might have expired.
        if self.message:
            try:
                await self.message.edit(view=self)
                logger.debug(f"Disabled components on message {self.message.id} after timeout.")
            except discord.NotFound:
                # This is expected if the message was deleted.
                logger.warning(f"Message {self.message.id} not found when trying to disable view on timeout (it may have been deleted).")
            except discord.Forbidden:
                logger.warning(f"Missing permissions to edit message {self.message.id} on timeout.")
            except discord.HTTPException as e:
                # This can happen if the interaction webhook is unknown (10015)
                if e.code == 10015:
                    logger.warning(f"Failed to edit message {self.message.id} on timeout: Unknown Webhook. The interaction likely expired.")
                else:
                    logger.error(f"An HTTP error occurred while editing message {self.message.id} on timeout: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"An unexpected error occurred while editing message {self.message.id} on timeout: {e}", exc_info=True)
        elif self._interaction:
            # Fallback to the interaction if we don't have the message object for some reason
            try:
                await self._interaction.edit_original_response(view=self)
            except discord.HTTPException as e:
                if e.code == 10015: # Unknown Webhook
                    logger.warning("Failed to edit original response on timeout: Unknown Webhook.")
                else:
                    logger.error(f"Failed to edit original response on timeout: {e}")
        else:
            logger.debug("View timed out, but no message or interaction was available to edit.")

    def stop(self):
        """
        Disables all components when the view is stopped manually.
        """
        for item in self.children:
            item.disabled = True
        super().stop()
