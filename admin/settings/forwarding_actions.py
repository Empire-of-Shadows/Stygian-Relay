"""Forwarding-rule management for the Stygian-Relay admin panel (bot-owned seam).

This lives in ``admin/settings/`` (relay's hand-written admin seam, NOT the vendored
engine). It turns the previously read-only **Forwarding Rules** section into a working
create/manage surface built entirely from the engine's generic node kinds:

* ``make_add_rule_node()``    -> an ``action`` node driving a step wizard (source channel
  -> destination server -> destination channel -> name) that calls
  ``guild_manager.add_rule``. Same-server picks use Discord's native, searchable
  ``ChannelSelect`` (no 25-channel cap); a cross-server destination is chosen by picking
  the server, then a paginated channel list (native selects can't reach another guild).
* ``make_manage_rules_node()`` -> a ``paginated_list`` node listing every rule with a
  per-item **Delete**.

Rules are persisted in exactly the shape the runtime (``commands/forward/forward.py``)
reads: a nested ``settings`` dict (``message_types``/``filters``/``formatting``/
``advanced_options``). We reuse ``RuleSetupHelper.create_initial_rule`` so a
panel-created rule is byte-identical to a ``/forward``-wizard-created one - an empty
``settings`` would silently forward nothing.
"""

from __future__ import annotations

import logging

import discord

from storage.bot_specific.relay import audit_log, guild_manager

from ..views.base import (
    AdminLayoutBuilder,
    build_notice_layout,
    cid,
    editable_container,
    readonly_container,
)
from ..views.panel_engine import PanelInputModal, PanelNode

logger = logging.getLogger("RelayForwardingActions")

# Channel kinds a rule can forward between. Announcement (news) channels are
# TextChannel instances, so they forward the same way; include both so the
# native picker and the cross-guild list surface them.
_TEXTLIKE_TYPES = [discord.ChannelType.text, discord.ChannelType.news]

# Cross-guild channel list page size. StringSelect is hard-capped at 25 options
# and, unlike the native ChannelSelect, can't be populated by Discord, so we
# paginate a foreign guild's channels ourselves.
_CROSS_CHANNEL_PAGE = 25

# Cooldown key for the create action (shared per user via cog._check_cooldown).
_ADD_RULE_KEY = "relay_add_rule"


# ─── Add Rule: step wizard ───────────────────────────────────────────────────

class AddRuleFlow:
    """A short-lived state machine driving the Add-Rule wizard on message 2.

    One instance per ``on_run`` invocation. State (chosen source/destination) lives
    on the instance; each step rebuilds and re-renders the message-2 LayoutView.
    """

    def __init__(self, cog, guild: discord.Guild, ctx, bot):
        self.cog = cog
        self.guild = guild
        self.ctx = ctx
        self.bot = bot

        self.source_id: int | None = None
        self.dest_guild_id: int | None = None
        self.dest_channel_id: int | None = None
        self.dest_page: int = 0
        # Whether the destination-server step was actually shown (it's skipped
        # when the only candidate is this server) - controls where Back goes.
        self.showed_server_step: bool = False

    # -- rendering plumbing ---------------------------------------------------

    async def _render(self, interaction: discord.Interaction, view: discord.ui.LayoutView) -> None:
        """Edit message 2 in place, keeping the view bound to the panel session."""
        if self.ctx.session is not None:
            try:
                self.ctx.session.register_view(view)
            except Exception:
                logger.debug("register_view failed for add-rule step", exc_info=True)
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(view=view)
            else:
                await interaction.response.edit_message(view=view)
        except discord.HTTPException as e:
            # 40060: interaction already acknowledged - fall back to editing the
            # original response instead of a second acknowledgement.
            if getattr(e, "code", None) == 40060:
                try:
                    await interaction.edit_original_response(view=view)
                except discord.HTTPException as e2:
                    logger.warning("add-rule render fallback failed: %s", e2)
            else:
                logger.warning("add-rule render failed: %s", e)

    @staticmethod
    def _button(label: str, style: discord.ButtonStyle, cb, key: str) -> discord.ui.Button:
        btn = discord.ui.Button(label=label, style=style, custom_id=cid("relayrule", key))
        btn.callback = cb
        return btn

    @staticmethod
    def _row(*items: discord.ui.Item) -> discord.ui.ActionRow:
        row = discord.ui.ActionRow()
        for it in items:
            row.add_item(it)
        return row

    # -- navigation -----------------------------------------------------------

    async def _back_to_panel(self, interaction: discord.Interaction) -> None:
        if self.ctx.parent_node is not None:
            await self.cog._navigate_to(
                interaction, self.ctx.parent_node, self.guild,
                parent_node=self.ctx.grandparent_node, edit=True,
                refresh_parent=self.ctx.refresh_parent, session=self.ctx.session,
            )
        else:
            await self._render(interaction, AdminLayoutBuilder().add_text("Closed.").build())

    async def _cancel(self, interaction: discord.Interaction) -> None:
        await self._back_to_panel(interaction)

    async def _back_from_channel(self, interaction: discord.Interaction) -> None:
        if self.showed_server_step:
            await self.render_destination_server(interaction)
        else:
            await self.render_source(interaction)

    # -- Step 1: source channel ----------------------------------------------

    async def render_source(self, interaction: discord.Interaction) -> None:
        b = AdminLayoutBuilder()
        b.add_header("## Add Forwarding Rule")
        b.add_item(readonly_container(discord.ui.TextDisplay(
            "**Step 1 of 3 - Source channel**\n"
            "Choose the channel to forward messages **from**. Start typing to "
            "search this server's channels."
        )))

        select = discord.ui.ChannelSelect(
            channel_types=_TEXTLIKE_TYPES,
            placeholder="Select source channel...",
            min_values=1, max_values=1,
            custom_id=cid("relayrule", "src"),
        )

        async def _picked(inter: discord.Interaction):
            self.source_id = select.values[0].id
            await self.render_destination_server(inter)

        select.callback = _picked
        b.add_item(editable_container(self._row(select)))
        b.add_item(self._row(self._button(
            self.ctx.back_label or "Back", discord.ButtonStyle.secondary, self._cancel, "src_back",
        )))
        await self._render(interaction, b.build())

    # -- Step 2: destination server ------------------------------------------

    async def _candidate_guilds(self, user_id: int) -> list[discord.Guild]:
        """This server first, then every other guild the bot AND the acting admin
        share whose inbound allowlist opts this server in (so cross-server forwards
        can actually deliver, and the admin can see the target's channels)."""
        out: list[discord.Guild] = [self.guild]
        for g in self.bot.guilds:
            if g.id == self.guild.id:
                continue
            if g.get_member(user_id) is None:
                continue
            try:
                if not await guild_manager.is_inbound_allowed(str(g.id), self.guild.id):
                    continue
            except Exception:
                logger.debug("is_inbound_allowed check failed for %s", g.id, exc_info=True)
                continue
            out.append(g)
        return out

    async def render_destination_server(self, interaction: discord.Interaction) -> None:
        candidates = await self._candidate_guilds(interaction.user.id)
        if len(candidates) <= 1:
            # No real choice - destination is this server. Skip straight to the
            # channel picker (a single pre-selected option wouldn't fire a callback).
            self.showed_server_step = False
            self.dest_guild_id = self.guild.id
            self.dest_page = 0
            await self.render_destination_channel(interaction)
            return

        self.showed_server_step = True
        b = AdminLayoutBuilder()
        b.add_header("## Add Forwarding Rule")
        b.add_item(readonly_container(discord.ui.TextDisplay(
            "**Step 2 of 3 - Destination server**\n"
            "Same server is the common case. You can also forward into another "
            "server that the bot and you both share and that allows inbound "
            "forwards from here."
        )))

        options = []
        for g in candidates[:25]:
            desc = "This server" if g.id == self.guild.id else f"Server ID: {g.id}"
            options.append(discord.SelectOption(
                label=g.name[:100], value=str(g.id), description=desc[:100],
            ))
        select = discord.ui.Select(
            placeholder="Select destination server...",
            options=options, min_values=1, max_values=1,
            custom_id=cid("relayrule", "dguild"),
        )

        async def _picked(inter: discord.Interaction):
            self.dest_guild_id = int(select.values[0])
            self.dest_channel_id = None
            self.dest_page = 0
            await self.render_destination_channel(inter)

        select.callback = _picked
        b.add_item(editable_container(self._row(select)))
        b.add_item(self._row(
            self._button("Back", discord.ButtonStyle.secondary, self._back_to_source, "dguild_back"),
            self._button("Cancel", discord.ButtonStyle.secondary, self._cancel, "dguild_cancel"),
        ))
        await self._render(interaction, b.build())

    async def _back_to_source(self, interaction: discord.Interaction) -> None:
        await self.render_source(interaction)

    # -- Step 3: destination channel -----------------------------------------

    async def render_destination_channel(self, interaction: discord.Interaction) -> None:
        same_server = self.dest_guild_id is None or self.dest_guild_id == self.guild.id
        if same_server:
            await self._render_dest_channel_same(interaction)
        else:
            await self._render_dest_channel_cross(interaction)

    async def _render_dest_channel_same(self, interaction: discord.Interaction) -> None:
        b = AdminLayoutBuilder()
        b.add_header("## Add Forwarding Rule")
        b.add_item(readonly_container(discord.ui.TextDisplay(
            "**Step 3 of 3 - Destination channel**\n"
            "Choose the channel to forward messages **to** in this server. Start "
            "typing to search."
        )))

        select = discord.ui.ChannelSelect(
            channel_types=_TEXTLIKE_TYPES,
            placeholder="Select destination channel...",
            min_values=1, max_values=1,
            custom_id=cid("relayrule", "dst"),
        )

        async def _picked(inter: discord.Interaction):
            channel_id = select.values[0].id
            err = await self._validate_destination(channel_id)
            if err:
                await inter.response.send_message(
                    view=build_notice_layout("Cannot use that channel", err), ephemeral=True,
                )
                return
            self.dest_channel_id = channel_id
            await self.render_name(inter)

        select.callback = _picked
        b.add_item(editable_container(self._row(select)))
        b.add_item(self._row(
            self._button("Back", discord.ButtonStyle.secondary, self._back_from_channel, "dst_back"),
            self._button("Cancel", discord.ButtonStyle.secondary, self._cancel, "dst_cancel"),
        ))
        await self._render(interaction, b.build())

    async def _render_dest_channel_cross(self, interaction: discord.Interaction) -> None:
        target = self.bot.get_guild(self.dest_guild_id)
        if target is None or target.me is None:
            await interaction.response.send_message(
                view=build_notice_layout(
                    "Server unavailable",
                    "I'm no longer in that server. Pick a different destination server.",
                ),
                ephemeral=True,
            )
            return

        channels = [
            c for c in target.text_channels
            if c.permissions_for(target.me).send_messages
        ]
        if not channels:
            await interaction.response.send_message(
                view=build_notice_layout(
                    "No writable channels",
                    f"I can't post in any channel in **{target.name}**. Grant me "
                    "Send Messages there, or pick another server.",
                ),
                ephemeral=True,
            )
            return

        total_pages = max(1, (len(channels) + _CROSS_CHANNEL_PAGE - 1) // _CROSS_CHANNEL_PAGE)
        self.dest_page = max(0, min(self.dest_page, total_pages - 1))
        start = self.dest_page * _CROSS_CHANNEL_PAGE
        page_channels = channels[start:start + _CROSS_CHANNEL_PAGE]

        b = AdminLayoutBuilder()
        b.add_header("## Add Forwarding Rule")
        b.add_item(readonly_container(discord.ui.TextDisplay(
            f"**Step 3 of 3 - Destination channel**\n"
            f"Channel in **{target.name}** to forward messages **to**.\n"
            f"Page {self.dest_page + 1} of {total_pages} "
            f"({len(channels)} channels I can post in)."
        )))

        options = [
            discord.SelectOption(
                label=f"#{c.name}"[:100], value=str(c.id), description=f"ID: {c.id}"[:100],
            )
            for c in page_channels
        ]
        select = discord.ui.Select(
            placeholder="Select destination channel...",
            options=options, min_values=1, max_values=1,
            custom_id=cid("relayrule", "dstx"),
        )

        async def _picked(inter: discord.Interaction):
            channel_id = int(select.values[0])
            err = await self._validate_destination(channel_id)
            if err:
                await inter.response.send_message(
                    view=build_notice_layout("Cannot use that channel", err), ephemeral=True,
                )
                return
            self.dest_channel_id = channel_id
            await self.render_name(inter)

        select.callback = _picked
        b.add_item(editable_container(self._row(select)))

        if total_pages > 1:
            async def _prev(inter: discord.Interaction):
                self.dest_page -= 1
                await self._render_dest_channel_cross(inter)

            async def _next(inter: discord.Interaction):
                self.dest_page += 1
                await self._render_dest_channel_cross(inter)

            b.add_item(self._row(
                self._button("Prev", discord.ButtonStyle.secondary, _prev, "dstx_prev"),
                self._button("Next", discord.ButtonStyle.secondary, _next, "dstx_next"),
            ))

        b.add_item(self._row(
            self._button("Back", discord.ButtonStyle.secondary, self._back_to_server, "dstx_back"),
            self._button("Cancel", discord.ButtonStyle.secondary, self._cancel, "dstx_cancel"),
        ))
        await self._render(interaction, b.build())

    async def _back_to_server(self, interaction: discord.Interaction) -> None:
        await self.render_destination_server(interaction)

    # -- Step 4: name + create -----------------------------------------------

    async def render_name(self, interaction: discord.Interaction) -> None:
        src = self.guild.get_channel(self.source_id)
        target = self.bot.get_guild(self.dest_guild_id) if self.dest_guild_id else self.guild
        target = target or self.guild
        dst = target.get_channel(self.dest_channel_id)
        cross = target.id != self.guild.id

        lines = [
            f"**Source:** {src.mention if src else f'<#{self.source_id}>'}",
            f"**Destination:** {dst.mention if dst else f'<#{self.dest_channel_id}>'}"
            + (f" in **{target.name}**" if cross else ""),
        ]
        if cross:
            lines.append(
                "-# Cross-server rule - it keeps working only while "
                f"**{target.name}** allows inbound forwards from this server and "
                "I can post there."
            )

        b = AdminLayoutBuilder()
        b.add_header("## Add Forwarding Rule")
        b.add_item(readonly_container(discord.ui.TextDisplay(
            "**Review and create**\n" + "\n".join(lines)
        )))

        async def _open_modal(inter: discord.Interaction):
            default_name = self._auto_name(src, dst, cross, target)
            modal = PanelInputModal(
                title="Name this rule",
                label="Rule name (optional)",
                placeholder=default_name[:100],
                min_length=0, max_length=100, default="",
                on_submit_callback=self._create, required=False,
            )
            await inter.response.send_modal(modal)

        b.add_item(editable_container(self._row(
            self._button("Create Rule", discord.ButtonStyle.success, _open_modal, "create"),
        )))
        b.add_item(self._row(
            self._button("Back", discord.ButtonStyle.secondary, self._back_to_channel, "name_back"),
            self._button("Cancel", discord.ButtonStyle.secondary, self._cancel, "name_cancel"),
        ))
        await self._render(interaction, b.build())

    async def _back_to_channel(self, interaction: discord.Interaction) -> None:
        await self.render_destination_channel(interaction)

    def _auto_name(self, src, dst, cross: bool, target) -> str:
        s = f"#{src.name}" if src else f"channel {self.source_id}"
        d = f"#{dst.name}" if dst else f"channel {self.dest_channel_id}"
        if cross and target is not None:
            return f"Forward from {s} to {d} in {target.name}"
        return f"Forward from {s} to {d}"

    async def _validate_destination(self, channel_id: int) -> str | None:
        """Return an error string if ``channel_id`` can't be a destination, else None."""
        dest_guild_id = self.dest_guild_id or self.guild.id
        target = self.bot.get_guild(dest_guild_id)
        if target is None or target.me is None:
            return "I'm no longer in that server. Pick a different destination server."
        channel = target.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            return "That channel no longer exists or isn't a text channel."
        if not channel.permissions_for(target.me).send_messages:
            return f"I don't have permission to send messages in {channel.mention}."
        cross = target.id != self.guild.id
        if not cross and channel_id == self.source_id:
            return "Source and destination channels must be different."
        if cross and not await guild_manager.is_inbound_allowed(str(target.id), self.guild.id):
            return (
                f"**{target.name}** doesn't allow inbound forwards from this "
                "server. Ask its admins to add this server to their inbound "
                "allowlist first."
            )
        return None

    async def _build_rule_data(self, name: str | None, dest_guild_id: int) -> dict:
        # Reuse the wizard's default-settings factory so panel-created rules are
        # identical to /forward-created ones (the runtime needs the nested
        # settings; an empty settings dict forwards nothing).
        from commands.forward.setup_helpers.rule_setup import rule_setup_helper

        base = await rule_setup_helper.create_initial_rule(
            source_channel_id=self.source_id,
            destination_channel_id=self.dest_channel_id,
            rule_name=name,
        )
        return {
            "rule_name": base.get("name"),
            "source_channel_id": base.get("source_channel_id"),
            "destination_channel_id": base.get("destination_channel_id"),
            "destination_guild_id": dest_guild_id,
            "enabled": base.get("is_active", True),
            "settings": {
                "message_types": base.get("message_types", {}),
                "filters": base.get("filters", {}),
                "formatting": base.get("formatting", {}),
                "advanced_options": base.get("advanced_options", {}),
            },
        }

    async def _create(self, interaction: discord.Interaction, raw_name: str) -> None:
        if not self.cog._check_cooldown(interaction.user.id, _ADD_RULE_KEY):
            await interaction.response.send_message(
                view=build_notice_layout("Slow down", "Please wait a moment and try again."),
                ephemeral=True,
            )
            return
        if not self.source_id or not self.dest_channel_id:
            await interaction.response.send_message(
                view=build_notice_layout("Incomplete", "Pick a source and destination channel first."),
                ephemeral=True,
            )
            return
        # Re-validate at the last moment - channels/permissions may have changed
        # while the wizard was open.
        err = await self._validate_destination(self.dest_channel_id)
        if err:
            await interaction.response.send_message(
                view=build_notice_layout("Cannot use that channel", err), ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        name = (raw_name or "").strip()
        if not name:
            # Blank submission -> use the friendly auto-name (channel names, same as the
            # modal placeholder), not the raw-ID fallback baked into create_initial_rule.
            src = self.guild.get_channel(self.source_id)
            target = self.bot.get_guild(self.dest_guild_id) if self.dest_guild_id else self.guild
            dst = target.get_channel(self.dest_channel_id) if target else None
            cross = bool(self.dest_guild_id and self.dest_guild_id != self.guild.id)
            name = self._auto_name(src, dst, cross, target)
        dest_guild_id = self.dest_guild_id or self.guild.id
        rule_data = await self._build_rule_data(name, dest_guild_id)

        try:
            ok, reason = await guild_manager.add_rule(guild_id=str(self.guild.id), **rule_data)
        except Exception:
            logger.exception("add_rule failed for guild %s", self.guild.id)
            ok, reason = False, "error"

        if ok:
            self.cog._invalidate_guild_caches(self.guild.id)
            await self._audit(interaction, rule_data)
            logger.info(
                "Admin %s created forwarding rule %s (%s -> %s) in guild %s",
                interaction.user, rule_data["rule_name"], rule_data["source_channel_id"],
                rule_data["destination_channel_id"], self.guild.id,
            )
            await self._back_to_panel(interaction)
            if self.ctx.refresh_parent:
                await self.ctx.refresh_parent()
            await interaction.followup.send(
                view=build_notice_layout(
                    "Rule created",
                    f"Now forwarding <#{rule_data['source_channel_id']}> to "
                    f"<#{rule_data['destination_channel_id']}>.",
                ),
                ephemeral=True,
            )
            return

        if reason == "limit_reached":
            limits = await guild_manager.get_guild_limits(str(self.guild.id))
            cap = limits.get("max_rules", 3)
            await interaction.followup.send(
                view=build_notice_layout(
                    "Rule limit reached",
                    f"You've hit the active-rule limit ({cap}). Delete a rule from "
                    "**Manage Rules**, or upgrade to premium for a higher limit.",
                ),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                view=build_notice_layout(
                    "Could not save",
                    "Something went wrong saving the rule. Please try again.",
                ),
                ephemeral=True,
            )

    async def _audit(self, interaction: discord.Interaction, rule_data: dict) -> None:
        try:
            await audit_log.log(
                "settings", str(self.guild.id), str(interaction.user.id), "create_rule",
                {
                    "rule_name": rule_data["rule_name"],
                    "source_channel_id": rule_data["source_channel_id"],
                    "destination_channel_id": rule_data["destination_channel_id"],
                    "destination_guild_id": rule_data["destination_guild_id"],
                },
            )
        except Exception:
            logger.debug("audit create_rule failed", exc_info=True)


def make_add_rule_node() -> PanelNode:
    """The ``Add Rule`` action node - launches the create wizard."""
    async def _on_run(cog, interaction, guild, ctx):
        flow = AddRuleFlow(cog, guild, ctx, interaction.client)
        await flow.render_source(interaction)

    return PanelNode(
        key="add_rule",
        label="Add Rule",
        kind="action",
        description="Create a new forwarding rule (pick a source and destination channel).",
        on_run=_on_run,
    )


# ─── Manage Rules: list + delete ─────────────────────────────────────────────

def make_manage_rules_node() -> PanelNode:
    """The ``Manage Rules`` paginated list - browse every rule, delete any one."""

    async def _items(guild_id) -> list:
        return await guild_manager.get_guild_rules(str(guild_id))

    async def _count(guild_id) -> int:
        return len(await guild_manager.get_guild_rules(str(guild_id)))

    def _format_line(item: dict, _abs_index: int) -> str:
        name = item.get("rule_name") or "(unnamed)"
        src = item.get("source_channel_id")
        dst = item.get("destination_channel_id")
        status = "on" if item.get("is_active") else "off"
        return f"**{name}** ({status}) - <#{src}> -> <#{dst}>"

    def _option_label(item: dict, _abs_index: int) -> str:
        name = item.get("rule_name") or "(unnamed)"
        marker = "" if item.get("is_active") else "[off] "
        return f"{marker}{name}"[:100]

    def _item_value(item: dict) -> str:
        return str(item.get("rule_id"))

    def _confirm_line(item: dict) -> str:
        name = item.get("rule_name") or "(unnamed)"
        return f"Permanently delete rule **{name}**? This can't be undone."

    async def _delete(guild_id, rule_id: str) -> bool:
        return await guild_manager.permanently_delete_rule(str(guild_id), rule_id)

    return PanelNode(
        key="manage_rules",
        label="Manage Rules",
        kind="paginated_list",
        description="Your forwarding rules. Use the menu below to delete one.",
        list_get_items=_items,
        list_count=_count,
        list_format_line=_format_line,
        list_item_option_label=_option_label,
        list_item_value=_item_value,
        list_page_size=10,
        list_action_label="Delete",
        list_action=_delete,
        list_action_confirm_line=_confirm_line,
    )
