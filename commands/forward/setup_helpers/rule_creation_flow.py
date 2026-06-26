"""
Rule creation flow — Components v2 LayoutViews.

All wizard steps render as LayoutViews so they can be edited in-place on the
admin panel's message 2, which is itself a Components v2 message. Mixing v1
embeds with a v2 message is rejected by Discord (error 50035), so embeds are
not used here.
"""

import discord
import logging
from typing import Tuple

from ..models.setup_state import SetupState
from .state_manager import state_manager
from .permission_check import permission_checker


def _build_layout(items: list[discord.ui.Item], timeout: float = 300.0) -> discord.ui.LayoutView:
    layout = discord.ui.LayoutView(timeout=timeout)
    for item in items:
        layout.add_item(item)
    return layout


async def _render(interaction: discord.Interaction, layout: discord.ui.LayoutView) -> None:
    """Edit msg2 in place if the interaction is responded/deferred, else send a new ephemeral."""
    try:
        if interaction.response.is_done():
            await interaction.edit_original_response(view=layout)
        else:
            await interaction.response.edit_message(view=layout)
    except discord.HTTPException as e:
        # Component interactions support edit_message; if not (e.g. modal
        # submit before defer), fall back to editing the original response.
        if e.code == 40060:
            await interaction.edit_original_response(view=layout)
        else:
            raise


class RuleCreationFlow:
    """Step-by-step rule creation rendered as Components v2 LayoutViews."""

    def __init__(self, bot, cog):
        self.bot = bot
        self.cog = cog
        self.logger = logging.getLogger(__name__)

    async def start_rule_creation(self, interaction: discord.Interaction):
        session = await state_manager.get_session(interaction.guild_id)
        if not session:
            session = await state_manager.create_session(interaction.guild_id, interaction.user.id)

        self.logger.info(f"Starting rule creation for guild {interaction.guild_id}")
        session.current_rule = {"step": "source_channel"}
        await state_manager.update_session(interaction.guild_id, {"current_rule": session.current_rule})
        await self.show_source_channel_step(interaction, session)

    # ── Step 1: Source channel ────────────────────────────────────────────
    async def show_source_channel_step(self, interaction: discord.Interaction, session: SetupState):
        items: list[discord.ui.Item] = [
            discord.ui.TextDisplay("## 📥 Select Source Channel"),
            discord.ui.TextDisplay(
                "Choose the channel messages will be forwarded **from**.\n"
                "This is the channel that will be monitored for new messages."
            ),
            discord.ui.Separator(),
        ]

        select_options = []
        for channel in interaction.guild.text_channels:
            if channel.permissions_for(interaction.guild.me).view_channel:
                select_options.append(
                    discord.SelectOption(
                        label=f"#{channel.name}"[:25],
                        value=str(channel.id),
                        description=f"ID: {channel.id}"[:50],
                    )
                )

        if select_options:
            select_menu = discord.ui.Select(
                placeholder="Select source channel...",
                options=select_options[:25],
                custom_id="rule_source_select",
            )
            row = discord.ui.ActionRow()
            row.add_item(select_menu)
            items.append(row)
        else:
            items.append(discord.ui.TextDisplay("*No accessible text channels found.*"))

        nav_row = discord.ui.ActionRow()
        nav_row.add_item(discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            custom_id="rule_source_cancel",
            emoji="✖️",
        ))
        items.append(nav_row)

        await _render(interaction, _build_layout(items))

    async def handle_channel_selection(self, interaction: discord.Interaction, session: SetupState,
                                       channel_type: str, channel_id: int):
        """Validate and store the selected channel; advance to the next step."""
        self.logger.info(f"Channel selected: {channel_type} = {channel_id} for guild {interaction.guild_id}")

        if session.current_rule is None:
            session.current_rule = {}

        from .channel_select import channel_selector

        if channel_type == "source":
            # Source is always in the rule-owner's guild.
            is_valid, message = await channel_selector.validate_channel_access(interaction.guild, channel_id)
            if not is_valid:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)
                return
            session.current_rule["source_channel_id"] = channel_id
            await self.show_destination_guild_step(interaction, session)
            return

        if channel_type == "destination":
            target_guild = self._resolve_target_guild(session, interaction.guild)
            if target_guild is None:
                await interaction.followup.send(
                    "❌ I'm no longer in the destination guild — pick a different one.",
                    ephemeral=True,
                )
                await self.show_destination_guild_step(interaction, session)
                return

            is_valid, message = await channel_selector.validate_channel_access(target_guild, channel_id)
            if not is_valid:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)
                return

            destination_channel = target_guild.get_channel(channel_id)
            required = ["view_channel", "send_messages", "embed_links", "attach_files"]
            ok, missing = await permission_checker.check_channel_permissions(
                destination_channel, required_perms=required
            )
            if not ok:
                await interaction.followup.send(
                    f"❌ I can't post in {destination_channel.mention}.\n"
                    f"{permission_checker.format_missing_permissions(missing)}\n\n"
                    "Grant those permissions and pick the destination again.",
                    ephemeral=True,
                )
                return

            if (
                channel_id == session.current_rule.get("source_channel_id")
                and target_guild.id == interaction.guild.id
            ):
                await interaction.followup.send(
                    "❌ Source and destination channels cannot be the same.", ephemeral=True
                )
                return

            session.current_rule["destination_channel_id"] = channel_id
            session.current_rule["destination_guild_id"] = target_guild.id
            await self.show_rule_name_step(interaction, session)

    def _resolve_target_guild(
        self, session: SetupState, fallback: discord.Guild
    ) -> discord.Guild | None:
        """Look up the chosen destination guild; fall back to the source guild."""
        target_id = session.destination_guild_id
        if target_id is None:
            return fallback
        return self.bot.get_guild(int(target_id)) or fallback

    async def _candidate_destination_guilds(
        self, interaction: discord.Interaction
    ) -> list[discord.Guild]:
        """Source guild first, then any other guild the bot AND user share
        whose inbound allowlist opts the source guild in."""
        from database import guild_manager

        invoking_user = interaction.user
        source_id = interaction.guild_id
        candidates: list[discord.Guild] = []
        if interaction.guild is not None:
            candidates.append(interaction.guild)
        for g in self.bot.guilds:
            if g.id == source_id:
                continue
            if g.get_member(invoking_user.id) is None:
                continue
            if not await guild_manager.is_inbound_allowed(str(g.id), source_id):
                continue
            candidates.append(g)
        return candidates

    # ── Step 1.5: Destination guild ───────────────────────────────────────
    async def show_destination_guild_step(self, interaction: discord.Interaction, session: SetupState):
        """
        Pick a destination guild — same-guild by default, or any other guild
        the bot AND the invoking user are members of. Cross-guild rules let
        an admin in source guild route messages into a guild they're also in.

        When the bot+user share only the source guild, this step is a no-op:
        we stamp same-guild and skip straight to the channel picker. A select
        menu with a single pre-selected option doesn't fire a callback when
        the user re-picks the default, so the wizard would deadlock.
        """
        candidate_guilds = await self._candidate_destination_guilds(interaction)

        if len(candidate_guilds) <= 1:
            # No real choice — same-guild only. Stamp and advance silently.
            target_id = candidate_guilds[0].id if candidate_guilds else interaction.guild_id
            session.destination_guild_id = target_id
            await state_manager.update_session(
                interaction.guild_id, {"destination_guild_id": target_id}
            )
            await self.show_destination_channel_step(interaction, session)
            return

        items: list[discord.ui.Item] = [
            discord.ui.TextDisplay("## 🌐 Destination Guild"),
            discord.ui.TextDisplay(
                "Pick where the destination channel lives. Same-guild is the "
                "common case; cross-guild rules require the bot to be a "
                "member of the target guild *and* you to be a member too "
                "(so you can see its channels)."
            ),
            discord.ui.Separator(),
        ]

        if len(candidate_guilds) > 25:
            self.logger.info(
                f"User {interaction.user.id} shares >25 guilds with the bot; "
                f"truncating destination guild list to 25"
            )
        # Important: do NOT pre-mark any option with default=True. Discord
        # treats re-clicking an already-selected option as a no-op, which
        # would deadlock the wizard if the user wanted same-guild.
        select_options: list[discord.SelectOption] = []
        for g in candidate_guilds[:25]:
            label = f"{g.name}"
            description = (
                "This server (same-guild)" if g.id == interaction.guild_id
                else f"ID: {g.id}"
            )
            select_options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=str(g.id),
                    description=description[:100],
                )
            )

        select_menu = discord.ui.Select(
            placeholder="Select destination guild...",
            options=select_options,
            custom_id="rule_dest_guild_select",
        )
        row = discord.ui.ActionRow()
        row.add_item(select_menu)
        items.append(row)

        nav_row = discord.ui.ActionRow()
        nav_row.add_item(discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="rule_dest_guild_back",
            emoji="⬅️",
        ))
        nav_row.add_item(discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            custom_id="rule_dest_guild_cancel",
            emoji="✖️",
        ))
        items.append(nav_row)

        await _render(interaction, _build_layout(items))

    async def handle_destination_guild_selection(
        self, interaction: discord.Interaction, session: SetupState, guild_id: int
    ):
        """Store the chosen destination guild and advance to channel picker."""
        target_guild = self.bot.get_guild(guild_id)
        if target_guild is None:
            await interaction.followup.send(
                "❌ I'm not in that guild anymore. Pick another.", ephemeral=True
            )
            return
        if target_guild.get_member(interaction.user.id) is None:
            await interaction.followup.send(
                "❌ You don't appear to be a member of that guild. Pick a guild "
                "you share with the bot.",
                ephemeral=True,
            )
            return

        if target_guild.id != interaction.guild_id:
            from database import guild_manager
            if not await guild_manager.is_inbound_allowed(
                str(target_guild.id), interaction.guild_id
            ):
                await interaction.followup.send(
                    "❌ That guild no longer allows forwarding from this server. "
                    "Ask its admins to add this server to their inbound allowlist.",
                    ephemeral=True,
                )
                return

        session.destination_guild_id = target_guild.id
        await state_manager.update_session(
            interaction.guild_id, {"destination_guild_id": target_guild.id}
        )
        await self.show_destination_channel_step(interaction, session)

    # ── Step 2: Destination channel ───────────────────────────────────────
    async def show_destination_channel_step(self, interaction: discord.Interaction, session: SetupState):
        target_guild = self._resolve_target_guild(session, interaction.guild)
        if target_guild is None:
            await interaction.followup.send(
                "❌ The selected destination guild is unavailable. Pick another.",
                ephemeral=True,
            )
            await self.show_destination_guild_step(interaction, session)
            return

        cross_guild = target_guild.id != interaction.guild.id
        header = "## 📤 Select Destination Channel"
        body = (
            f"Choose the channel messages will be forwarded **to** in "
            f"**{target_guild.name}**.\n"
            "Only channels where I have `send_messages` are listed."
            if cross_guild else
            "Choose the channel messages will be forwarded **to**.\n"
            "This is where the forwarded messages will appear."
        )

        items: list[discord.ui.Item] = [
            discord.ui.TextDisplay(header),
            discord.ui.TextDisplay(body),
            discord.ui.Separator(),
        ]

        bot_member = target_guild.me
        if bot_member is None:
            items.append(discord.ui.TextDisplay(
                "*I'm no longer a member of the destination guild — go back "
                "and choose another.*"
            ))
            select_options: list[discord.SelectOption] = []
        else:
            select_options = []
            for channel in target_guild.text_channels:
                if channel.permissions_for(bot_member).send_messages:
                    select_options.append(
                        discord.SelectOption(
                            label=f"#{channel.name}"[:25],
                            value=str(channel.id),
                            description=f"ID: {channel.id}"[:50],
                        )
                    )

        if select_options:
            select_menu = discord.ui.Select(
                placeholder="Select destination channel...",
                options=select_options[:25],
                custom_id="rule_dest_select",
            )
            row = discord.ui.ActionRow()
            row.add_item(select_menu)
            items.append(row)
        elif bot_member is not None:
            items.append(discord.ui.TextDisplay("*No writable text channels found.*"))

        nav_row = discord.ui.ActionRow()
        nav_row.add_item(discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="rule_destination_back",
            emoji="⬅️",
        ))
        nav_row.add_item(discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            custom_id="rule_dest_cancel",
            emoji="✖️",
        ))
        items.append(nav_row)

        await _render(interaction, _build_layout(items))

    # ── Step 3: Rule name ─────────────────────────────────────────────────
    async def show_rule_name_step(self, interaction: discord.Interaction, session: SetupState):
        items: list[discord.ui.Item] = [
            discord.ui.TextDisplay("## 📝 Rule Name"),
            discord.ui.TextDisplay("Provide a name for this rule, or use an auto-generated one."),
            discord.ui.Separator(),
        ]
        action_row = discord.ui.ActionRow()
        action_row.add_item(discord.ui.Button(
            label="Enter Name",
            style=discord.ButtonStyle.primary,
            custom_id="rule_name_input",
        ))
        action_row.add_item(discord.ui.Button(
            label="Use Auto-generated Name",
            style=discord.ButtonStyle.secondary,
            custom_id="rule_auto_name",
        ))
        items.append(action_row)

        nav_row = discord.ui.ActionRow()
        nav_row.add_item(discord.ui.Button(
            label="Back",
            style=discord.ButtonStyle.secondary,
            custom_id="rule_name_back",
            emoji="⬅️",
        ))
        nav_row.add_item(discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            custom_id="rule_name_cancel",
            emoji="✖️",
        ))
        items.append(nav_row)

        await _render(interaction, _build_layout(items))

    async def handle_auto_name(self, interaction: discord.Interaction, session: SetupState):
        source_channel = interaction.guild.get_channel(session.current_rule["source_channel_id"])
        target_guild = self._resolve_target_guild(session, interaction.guild)
        dest_channel = (
            target_guild.get_channel(session.current_rule["destination_channel_id"])
            if target_guild else None
        )

        if not source_channel or not dest_channel:
            await interaction.followup.send(
                "❌ One or more selected channels no longer exist. Please restart the setup.",
                ephemeral=True,
            )
            return

        cross_guild = target_guild is not None and target_guild.id != interaction.guild.id
        if cross_guild:
            rule_name = (
                f"Forward from #{source_channel.name} to #{dest_channel.name} "
                f"in {target_guild.name}"
            )
        else:
            rule_name = f"Forward from #{source_channel.name} to #{dest_channel.name}"
        session.current_rule["rule_name"] = rule_name
        await self.show_rule_preview_step(interaction, session)

    # ── Step 4: Rule preview ──────────────────────────────────────────────
    async def show_rule_preview_step(self, interaction: discord.Interaction, session: SetupState):
        from .rule_setup import rule_setup_helper
        from ..setup import normalize_channel_id

        rule = await rule_setup_helper.create_initial_rule(
            source_channel_id=session.current_rule["source_channel_id"],
            destination_channel_id=session.current_rule["destination_channel_id"],
            rule_name=session.current_rule["rule_name"],
        )
        # Preserve fields when editing an existing rule.
        if session.is_editing:
            rule.update({k: v for k, v in session.current_rule.items() if k not in rule})

        guild = interaction.guild
        target_guild = self._resolve_target_guild(session, guild)
        src_id = normalize_channel_id(rule.get("source_channel_id"))
        dst_id = normalize_channel_id(rule.get("destination_channel_id"))
        src = guild.get_channel(src_id) if src_id else None
        dst = target_guild.get_channel(dst_id) if (target_guild and dst_id) else None

        cross_guild = target_guild is not None and target_guild.id != guild.id
        dest_line = (
            f"**Destination:** {dst.mention if dst else f'<#{dst_id}>'}"
            + (f" *(in **{target_guild.name}**)*" if cross_guild else "")
        )
        body_lines = [
            f"**Name:** {rule.get('name') or rule.get('rule_name', '(unnamed)')}",
            f"**Source:** {src.mention if src else f'<#{src_id}>'}",
            dest_line,
            f"**Status:** {'🟢 Active' if rule.get('is_active', True) else '🔴 Inactive'}",
        ]
        if cross_guild:
            body_lines.append(
                "-# Cross-guild rule — anyone with rule-management rights here "
                "can re-route messages there. Destination admins can revoke "
                "by kicking me or removing send-permissions."
            )

        items: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                "## 📋 Rule Preview" + (" — Editing" if session.is_editing else "")
            ),
            discord.ui.TextDisplay("\n".join(body_lines)),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                "Review the rule above. Click **Save** to apply, **Edit Settings** to "
                "modify channels/name/status, or **Start Over** to discard and restart."
            ),
        ]

        action_row = discord.ui.ActionRow()
        action_row.add_item(discord.ui.Button(
            label="Save" if session.is_editing else "Create Rule",
            style=discord.ButtonStyle.success,
            custom_id="rule_final_create",
        ))
        action_row.add_item(discord.ui.Button(
            label="Edit Settings",
            style=discord.ButtonStyle.secondary,
            custom_id="rule_edit_settings",
        ))
        action_row.add_item(discord.ui.Button(
            label="Start Over",
            style=discord.ButtonStyle.danger,
            custom_id="rule_start_over",
            disabled=session.is_editing,
        ))
        items.append(action_row)

        nav_row = discord.ui.ActionRow()
        nav_row.add_item(discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.danger,
            custom_id="rule_preview_cancel",
            emoji="✖️",
        ))
        items.append(nav_row)

        await _render(interaction, _build_layout(items))

    async def create_final_rule(self, interaction: discord.Interaction, session: SetupState) -> Tuple[bool, str]:
        """Validate, save, and return (success, message)."""
        self.logger.info(f"Creating final rule for guild {interaction.guild_id}")
        try:
            from .rule_setup import rule_setup_helper
            rule = await rule_setup_helper.create_initial_rule(
                source_channel_id=session.current_rule["source_channel_id"],
                destination_channel_id=session.current_rule["destination_channel_id"],
                rule_name=session.current_rule["rule_name"],
            )
            if "is_active" in session.current_rule:
                rule["is_active"] = bool(session.current_rule["is_active"])

            dest_guild = interaction.guild
            if session.destination_guild_id and session.destination_guild_id != interaction.guild_id:
                dest_guild = interaction.client.get_guild(session.destination_guild_id) or interaction.guild
            is_valid, errors = await rule_setup_helper.validate_rule_configuration(rule, interaction.guild, dest_guild)
            if not is_valid:
                return False, " ".join(errors)

            session.forwarding_rules.append(rule)
            await state_manager.update_session(interaction.guild_id, {"rules": session.forwarding_rules})

            from database import guild_manager
            destination_guild_id = (
                session.destination_guild_id or interaction.guild_id
            )
            rule_data = {
                "rule_name": rule.get("name"),
                "source_channel_id": rule.get("source_channel_id"),
                "destination_channel_id": rule.get("destination_channel_id"),
                "destination_guild_id": destination_guild_id,
                "enabled": rule.get("is_active", True),
                "settings": {
                    "message_types": rule.get("message_types", {}),
                    "filters": rule.get("filters", {}),
                    "formatting": rule.get("formatting", {}),
                    "advanced_options": rule.get("advanced_options", {}),
                },
            }

            save_ok, reason = await guild_manager.add_rule(guild_id=str(interaction.guild_id), **rule_data)

            if save_ok:
                self.logger.info(f"Rule '{rule_data['rule_name']}' saved for guild {interaction.guild_id}")
                return True, "Rule created and saved successfully."
            if reason == "limit_reached":
                limits = await guild_manager.get_guild_limits(str(interaction.guild_id))
                cap = limits.get("max_rules", 3)
                return False, (
                    f"You have reached the active-rule limit ({cap}). "
                    "Disable or delete an existing rule, or upgrade to premium for more."
                )
            return False, "Rule created but failed to save to database. Please try again."

        except Exception as e:
            self.logger.error(f"Error creating final rule: {e}", exc_info=True)
            return False, f"An error occurred while creating the rule: {str(e)}"

    async def handle_rule_back(self, interaction: discord.Interaction, session: SetupState, cog_instance, step: str):
        """Step-back navigation."""
        self.logger.info(f"Back nav: step={step} guild={interaction.guild_id}")
        if step in ("dest_guild", "destination_guild"):
            await self.show_source_channel_step(interaction, session)
        elif step == "destination":
            # Channel picker → back to destination guild picker.
            await self.show_destination_guild_step(interaction, session)
        elif step == "name":
            await self.show_destination_channel_step(interaction, session)
        elif step == "preview":
            await self.show_rule_name_step(interaction, session)
        else:
            await self.show_source_channel_step(interaction, session)
