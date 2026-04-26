"""
Panel Engine — generic config-driven panel builder.

PanelNode dataclass + view builders (build_menu_view, build_select_view,
build_modal_trigger_view, build_dual_modal_trigger_view, build_overview_view).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import discord

from .base import PanelLayoutBuilder, create_empty_layout, create_unique_id


@dataclass
class PanelNode:
    """A node in the panel config tree.

    kind: "menu" | "role_select" | "channel_select" | "option_select"
          | "modal_input" | "dual_modal_input"
    """

    key: str
    label: str
    kind: str
    description: str = ""

    children: dict[str, "PanelNode"] = field(default_factory=dict)

    locked_children: Optional[Callable] = None
    lock_reason: str = ""
    toggle_get: Optional[Callable] = None
    toggle_set: Optional[Callable] = None
    on_toggle_callback: Optional[Callable] = None
    description_builder: Optional[Callable] = None
    async_description: Optional[Callable] = None  # async (guild) -> str — runtime-resolved description override

    get_values: Optional[Callable] = None
    set_values: Optional[Callable] = None
    clear_values: Optional[Callable] = None
    pre_check: Optional[Callable] = None
    post_save_hook: Optional[Callable] = None

    channel_types: Optional[list] = None

    options: Optional[list] = None
    min_values: int = 1
    max_values: int = 25

    premium_values: set[str] | None = None
    premium_max_values: int | None = None

    modal_title: str = ""
    modal_label: str = "Value"
    modal_placeholder: str = ""
    modal_min_length: int = 1
    modal_max_length: int = 100
    modal_validator: Optional[Callable] = None
    modal_paragraph: bool = False
    modal_required: bool = True

    modal_label_2: str = ""
    modal_placeholder_2: str = ""
    modal_min_length_2: int = 0
    modal_max_length_2: int = 500


def _get_default_option_value(node: PanelNode) -> str | None:
    if not node.options:
        return None
    for opt in node.options:
        if "(Default)" in opt[1]:
            return str(opt[0])
    return None


def _option_label(node: PanelNode, value: str) -> str:
    if not node.options:
        return value
    for opt in node.options:
        if str(opt[0]) == value:
            return opt[1].replace(" (Default)", "").replace(" (Premium)", "").replace("💎 ", "").strip()
    return value


def _child_summary(node: PanelNode, values: list, guild: discord.Guild | None = None) -> str:
    kind = node.kind
    n = len(values)
    if kind == "role_select":
        return f"{n} role(s) assigned" if n else "Not assigned"
    if kind == "channel_select":
        is_category_only = (
            node.channel_types is not None
            and len(node.channel_types) == 1
            and node.channel_types[0] == discord.ChannelType.category
        )
        noun = "category" if is_category_only else "channel"
        if not n:
            return "Not set"
        if guild is None:
            return f"{noun.capitalize()} configured"
        names = []
        for cid in values:
            ch = guild.get_channel(int(cid))
            if ch is None:
                names.append(f"Unknown ({cid})")
            elif is_category_only:
                names.append(ch.name)
            else:
                names.append(f"#{ch.name}")
        return ", ".join(names)
    if kind == "option_select":
        if not n:
            return "Not set"
        default_val = _get_default_option_value(node)
        if n == 1 and default_val is not None and str(values[0]) == default_val:
            return "Default"
        label = _option_label(node, str(values[0])) if n == 1 else f"{n} selected"
        return label
    if kind == "modal_input":
        return str(values[0]) if values else "Not set"
    if kind == "dual_modal_input":
        val1 = values[0] if len(values) > 0 else ""
        return str(val1) if val1 else "Not set"
    if kind == "menu":
        if n == 1 and len(node.children) == 1:
            return str(values[0])
        if n:
            if n == 1 and values[0] == "__defaults__":
                return "Default settings"
            return f"{n} setting(s) customized"
        return "Not configured"
    return f"{n} configured" if n else "Not set"


def build_menu_view(
    node: PanelNode,
    summary_map: dict[str, list],
    on_select: Callable[[discord.Interaction, str], Awaitable[None]],
    on_cancel: Callable[[discord.Interaction], Awaitable[None]],
    locked_keys: set[str] | None = None,
    toggle_state: bool | None = None,
    on_toggle: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    back_label: str = "Done",
    preamble_items: list[discord.ui.Item] | None = None,
    extra_buttons: list[discord.ui.Button] | None = None,
    description_override: str | None = None,
    guild_id: int | None = None,
    guild: discord.Guild | None = None,
) -> discord.ui.LayoutView:
    unique_id = create_unique_id()
    builder = PanelLayoutBuilder()
    _locked = locked_keys or set()

    if toggle_state is not None:
        status = "Enabled" if toggle_state else "Disabled"
        builder.add_header(f"## {node.label} — {status}")
    else:
        builder.add_header(f"## {node.label}")

    if preamble_items:
        for item in preamble_items:
            builder.add_item(item)

    if description_override is not None:
        desc_text = description_override
    elif node.description_builder is not None and guild_id is not None:
        try:
            desc_text = node.description_builder(guild_id)
        except Exception:
            desc_text = node.description
    else:
        desc_text = node.description
    if desc_text:
        builder.add_text(desc_text)
        builder.add_separator()

    lines = []
    for key, child in node.children.items():
        prefix = "\U0001f512 " if key in _locked else ""
        lines.append(
            f"- **{prefix}{child.label}:** {_child_summary(child, summary_map.get(key, []), guild)}"
        )
    if lines:
        builder.add_text("\n".join(lines))

    if node.children:
        builder.add_separator()
        builder.add_text("Select a category below to configure it.")

        options = [
            discord.SelectOption(
                label=f"\U0001f512 {child.label}" if key in _locked else child.label,
                value=key,
                description=(
                    "Locked — configure prerequisite first"
                    if key in _locked
                    else _child_summary(child, summary_map.get(key, []), guild)
                ),
            )
            for key, child in node.children.items()
        ]
        select = discord.ui.Select(
            placeholder="Select a category...",
            custom_id=f"menu_select_{unique_id}",
            options=options,
        )

        async def _select_cb(interaction: discord.Interaction):
            await on_select(interaction, interaction.data["values"][0])

        select.callback = _select_cb
        builder.add_select(select)

    row = discord.ui.ActionRow()

    if on_toggle is not None and toggle_state is not None:
        toggle_btn = discord.ui.Button(
            label="Disable" if toggle_state else "Enable",
            style=discord.ButtonStyle.danger if toggle_state else discord.ButtonStyle.success,
            custom_id=f"toggle_{unique_id}",
        )
        toggle_btn.callback = on_toggle
        row.add_item(toggle_btn)

    back_style = discord.ButtonStyle.danger if back_label == "Close Panel" else discord.ButtonStyle.secondary
    done_btn = discord.ui.Button(
        label=back_label,
        style=back_style,
        custom_id=f"done_{unique_id}",
    )
    done_btn.callback = on_cancel
    row.add_item(done_btn)

    if extra_buttons:
        for btn in extra_buttons:
            row.add_item(btn)

    builder.add_item(row)
    return builder.build()


def build_select_view(
    node: PanelNode,
    current_values: list,
    guild: discord.Guild,
    on_save: Callable[[discord.Interaction, list], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    on_clear: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    back_label: str = "Back",
    is_premium: bool = False,
) -> discord.ui.LayoutView:
    unique_id = create_unique_id()
    builder = PanelLayoutBuilder()

    builder.add_header(f"## {node.label}")

    if node.kind == "role_select":
        if current_values:
            names = []
            for rid in current_values:
                role = guild.get_role(int(rid))
                names.append(role.name if role else f"Unknown ({rid})")
            builder.add_text(f"**Currently assigned:** {', '.join(names)}")
        else:
            builder.add_text("*No roles currently assigned.*")

    elif node.kind == "channel_select":
        is_category_only = (
            node.channel_types is not None
            and len(node.channel_types) == 1
            and node.channel_types[0] == discord.ChannelType.category
        )
        noun = "category" if is_category_only else "channel"
        if current_values:
            parts = []
            for cid in current_values:
                ch = guild.get_channel(int(cid))
                if ch is None:
                    parts.append(f"Unknown ({cid})")
                elif is_category_only:
                    parts.append(ch.name)
                else:
                    parts.append(ch.mention)
            label = f"Current {noun}" if len(parts) == 1 else f"Current {noun}s"
            builder.add_text(f"**{label}:** {', '.join(parts)}")
        else:
            builder.add_text(f"*No {noun} currently set.*")

    elif node.kind == "option_select":
        if current_values:
            opt_label_map = {str(opt[0]): opt[1] for opt in (node.options or [])}
            names = [opt_label_map.get(str(v), str(v)) for v in current_values]
            builder.add_text(f"**Currently selected:** {', '.join(names)}")
        else:
            builder.add_text("*Nothing currently selected.*")

    builder.add_separator()
    builder.add_text(node.description or f"Select values for **{node.label}**.")

    if node.kind == "role_select":
        component = discord.ui.RoleSelect(
            placeholder=f"Select roles for {node.label}...",
            custom_id=f"select_{unique_id}",
            min_values=node.min_values,
            max_values=node.max_values,
            default_values=[discord.Object(id=int(rid)) for rid in current_values],
        )

        async def _role_cb(interaction: discord.Interaction):
            role_ids = [int(rid) for rid in interaction.data.get("resolved", {}).get("roles", {}).keys()]
            await on_save(interaction, role_ids)

        component.callback = _role_cb

    elif node.kind == "channel_select":
        effective_max = node.max_values
        if is_premium and node.premium_max_values is not None:
            effective_max = node.premium_max_values
        select_kwargs = dict(
            placeholder=f"Select channel for {node.label}...",
            custom_id=f"select_{unique_id}",
            min_values=node.min_values,
            max_values=effective_max,
            default_values=[discord.Object(id=int(v)) for v in current_values],
        )
        if node.channel_types:
            select_kwargs["channel_types"] = node.channel_types
        component = discord.ui.ChannelSelect(**select_kwargs)

        async def _channel_cb(interaction: discord.Interaction):
            channel_ids = [int(cid) for cid in interaction.data.get("values", [])]
            await on_save(interaction, channel_ids)

        component.callback = _channel_cb

    elif node.kind == "option_select":
        current_strs = [str(v) for v in current_values]
        _prem = node.premium_values or set()
        option_objects = []
        for opt in (node.options or []):
            val, lbl = str(opt[0]), opt[1]
            desc = opt[2] if len(opt) > 2 else None
            if val in _prem and not is_premium:
                lbl = f"💎 {lbl}"
                desc = "Requires Premium subscription"
            option_objects.append(
                discord.SelectOption(
                    label=lbl,
                    value=val,
                    description=desc,
                    default=(val in current_strs),
                )
            )
        component = discord.ui.Select(
            placeholder="Select one or more options...",
            custom_id=f"select_{unique_id}",
            min_values=node.min_values,
            max_values=min(node.max_values, len(option_objects)) if option_objects else 1,
            options=option_objects,
        )

        async def _option_cb(interaction: discord.Interaction):
            await on_save(interaction, interaction.data["values"])

        component.callback = _option_cb

    else:
        return create_empty_layout(f"Unknown node kind: {node.kind!r}")

    builder.add_select(component)

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(label=back_label, style=back_style, custom_id=f"back_{unique_id}")
    back_btn.callback = on_back
    btn_row = discord.ui.ActionRow()
    btn_row.add_item(back_btn)

    if on_clear is not None:
        clear_btn = discord.ui.Button(
            label="Clear",
            style=discord.ButtonStyle.danger,
            custom_id=f"clear_{unique_id}",
            disabled=(len(current_values) == 0),
        )
        clear_btn.callback = on_clear
        btn_row.add_item(clear_btn)

    builder.add_item(btn_row)
    return builder.build()


class PanelInputModal(discord.ui.Modal):
    """Single-field modal used by build_modal_trigger_view."""

    def __init__(
        self,
        *,
        title: str,
        label: str,
        placeholder: str,
        min_length: int,
        max_length: int,
        default: str,
        on_submit_callback: Callable[[discord.Interaction, str], Awaitable[None]],
        paragraph: bool = False,
        required: bool = True,
    ):
        super().__init__(title=title)
        self._callback = on_submit_callback
        self.value_input = discord.ui.TextInput(
            label=label,
            placeholder=placeholder or None,
            required=required,
            style=discord.TextStyle.paragraph if paragraph else discord.TextStyle.short,
            min_length=min_length,
            max_length=max_length,
            default=default or None,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(interaction, self.value_input.value.strip())


def build_modal_trigger_view(
    node: PanelNode,
    current_values: list,
    guild: discord.Guild,
    on_save: Callable[[discord.Interaction, discord.Interaction, str], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    on_clear: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    back_label: str = "Back",
) -> discord.ui.LayoutView:
    unique_id = create_unique_id()
    builder = PanelLayoutBuilder()

    builder.add_header(f"## {node.label}")

    if current_values:
        builder.add_text(f"**Current value:** {current_values[0]}")
    else:
        builder.add_text("*Not currently set.*")

    builder.add_separator()
    builder.add_text(node.description or f"Set a value for **{node.label}**.")

    set_btn = discord.ui.Button(
        label=f"Set {node.label}",
        style=discord.ButtonStyle.primary,
        custom_id=f"set_{unique_id}",
    )

    async def set_btn_callback(bi: discord.Interaction):
        async def _on_submit(mi: discord.Interaction, raw: str):
            await on_save(bi, mi, raw)

        modal = PanelInputModal(
            title=node.modal_title or f"Set {node.label}",
            label=node.modal_label or "Value",
            placeholder=node.modal_placeholder or "",
            min_length=node.modal_min_length,
            max_length=node.modal_max_length,
            default=current_values[0] if current_values else "",
            on_submit_callback=_on_submit,
            paragraph=node.modal_paragraph,
            required=node.modal_required,
        )
        await bi.response.send_modal(modal)

    set_btn.callback = set_btn_callback

    action_items = [set_btn]
    if on_clear is not None:
        clear_btn = discord.ui.Button(
            label="Clear",
            style=discord.ButtonStyle.danger,
            custom_id=f"clear_{unique_id}",
            disabled=(len(current_values) == 0),
        )
        clear_btn.callback = on_clear
        action_items.append(clear_btn)

    builder.add_action_row(*action_items)

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(label=back_label, style=back_style, custom_id=f"back_{unique_id}")
    back_btn.callback = on_back
    back_row = discord.ui.ActionRow()
    back_row.add_item(back_btn)
    builder.add_item(back_row)

    return builder.build()


class _PanelDualInputModal(discord.ui.Modal):
    def __init__(
        self,
        *,
        title: str,
        label: str,
        placeholder: str,
        min_length: int,
        max_length: int,
        default: str,
        label_2: str,
        placeholder_2: str,
        min_length_2: int,
        max_length_2: int,
        default_2: str,
        on_submit_callback: Callable[[discord.Interaction, str, str], Awaitable[None]],
    ):
        super().__init__(title=title)
        self._callback = on_submit_callback
        self.value_input = discord.ui.TextInput(
            label=label,
            placeholder=placeholder or None,
            required=True,
            style=discord.TextStyle.short,
            min_length=min_length,
            max_length=max_length,
            default=default or None,
        )
        self.value_input_2 = discord.ui.TextInput(
            label=label_2,
            placeholder=placeholder_2 or None,
            required=False,
            style=discord.TextStyle.paragraph,
            min_length=min_length_2,
            max_length=max_length_2,
            default=default_2 or None,
        )
        self.add_item(self.value_input)
        self.add_item(self.value_input_2)

    async def on_submit(self, interaction: discord.Interaction):
        await self._callback(
            interaction,
            self.value_input.value.strip(),
            self.value_input_2.value.strip(),
        )


def _compact_category_summary(
    cat_node: PanelNode,
    cat_summaries: dict[str, str | dict[str, str]],
    toggle: bool | None,
) -> str:
    configured = 0
    total = 0
    for child_key, child_node in cat_node.children.items():
        val = cat_summaries.get(child_key, "Not configured")
        if isinstance(val, dict):
            for sub_val in val.values():
                total += 1
                if sub_val not in ("Not configured", "Not set", "Not assigned"):
                    configured += 1
        else:
            total += 1
            if val not in ("Not configured", "Not set", "Not assigned"):
                configured += 1

    if total == 0:
        return "Informational"
    if configured == 0:
        return "Not configured"
    return f"{configured} of {total} configured"


def build_overview_view(
    root_node: PanelNode,
    deep_summary: dict[str, dict[str, str | dict[str, str]]],
    toggle_states: dict[str, bool | None],
    locked_keys: set[str],
    on_category_select: Callable[[discord.Interaction, str], Awaitable[None]],
    preamble_items: list[discord.ui.Item] | None = None,
    extra_buttons: list[discord.ui.Button] | None = None,
    compact: bool = True,
) -> discord.ui.LayoutView:
    unique_id = create_unique_id()
    builder = PanelLayoutBuilder()
    _locked = locked_keys or set()

    builder.add_header(f"## {root_node.label}")

    if preamble_items:
        for item in preamble_items:
            builder.add_item(item)

    builder.add_separator()

    if compact:
        lines = []
        for cat_key, cat_node in root_node.children.items():
            cat_summaries = deep_summary.get(cat_key, {})
            lock_prefix = "\U0001f512 " if cat_key in _locked else ""
            toggle = toggle_states.get(cat_key)

            summary = _compact_category_summary(cat_node, cat_summaries, toggle)
            if toggle is not None:
                status = "Enabled" if toggle else "Disabled"
                lines.append(f"**{lock_prefix}{cat_node.label}** — {status} ({summary})")
            else:
                lines.append(f"**{lock_prefix}{cat_node.label}** — {summary}")

        builder.add_text("\n".join(lines))
    else:
        for cat_key, cat_node in root_node.children.items():
            cat_summaries = deep_summary.get(cat_key, {})
            lock_prefix = "\U0001f512 " if cat_key in _locked else ""

            toggle = toggle_states.get(cat_key)
            if toggle is not None:
                status = "Enabled" if toggle else "Disabled"
                header = f"**{lock_prefix}{cat_node.label}** — {status}"
            else:
                header = f"**{lock_prefix}{cat_node.label}**"

            lines = [header]
            for child_key, child_node in cat_node.children.items():
                val = cat_summaries.get(child_key, "Not configured")
                if isinstance(val, dict):
                    lines.append(f"  {child_node.label}:")
                    for sub_key, sub_node in child_node.children.items():
                        sub_val = val.get(sub_key, "Not configured")
                        lines.append(f"    • {sub_node.label}: {sub_val}")
                else:
                    lines.append(f"  • {child_node.label}: {val}")

            builder.add_text("\n".join(lines))

    builder.add_separator()
    builder.add_text("Select a category below to configure it.")

    options = [
        discord.SelectOption(
            label=f"\U0001f512 {child.label}" if key in _locked else child.label,
            value=key,
            description=child.description[:100] if child.description else None,
        )
        for key, child in root_node.children.items()
    ]
    select = discord.ui.Select(
        placeholder="Select a category...",
        custom_id=f"overview_select_{unique_id}",
        options=options,
    )

    async def _select_cb(interaction: discord.Interaction):
        await on_category_select(interaction, interaction.data["values"][0])

    select.callback = _select_cb
    builder.add_select(select)

    if extra_buttons:
        row = discord.ui.ActionRow()
        for btn in extra_buttons:
            row.add_item(btn)
        builder.add_item(row)

    return builder.build()


def build_dual_modal_trigger_view(
    node: PanelNode,
    current_values: list,
    guild: discord.Guild,
    on_save: Callable[[discord.Interaction, discord.Interaction, str, str], Awaitable[None]],
    on_back: Callable[[discord.Interaction], Awaitable[None]],
    back_label: str = "Back",
) -> discord.ui.LayoutView:
    unique_id = create_unique_id()
    builder = PanelLayoutBuilder()

    builder.add_header(f"## {node.label}")

    val1 = current_values[0] if len(current_values) > 0 else ""
    val2 = current_values[1] if len(current_values) > 1 else ""

    if val1 or val2:
        lines = []
        if val1:
            lines.append(f"**{node.modal_label or 'Field 1'}:** {val1}")
        if val2:
            lines.append(f"**{node.modal_label_2 or 'Field 2'}:** {val2}")
        builder.add_text("\n".join(lines))
    else:
        builder.add_text("*Not currently set.*")

    builder.add_separator()
    builder.add_text(node.description or f"Set values for **{node.label}**.")

    edit_btn = discord.ui.Button(label="Edit", style=discord.ButtonStyle.primary, custom_id=f"edit_{unique_id}")

    async def edit_btn_callback(bi: discord.Interaction):
        async def _on_submit(mi: discord.Interaction, raw1: str, raw2: str):
            await on_save(bi, mi, raw1, raw2)

        modal = _PanelDualInputModal(
            title=node.modal_title or f"Set {node.label}",
            label=node.modal_label or "Field 1",
            placeholder=node.modal_placeholder or "",
            min_length=node.modal_min_length,
            max_length=node.modal_max_length,
            default=val1,
            label_2=node.modal_label_2 or "Field 2",
            placeholder_2=node.modal_placeholder_2 or "",
            min_length_2=node.modal_min_length_2,
            max_length_2=node.modal_max_length_2,
            default_2=val2,
            on_submit_callback=_on_submit,
        )
        await bi.response.send_modal(modal)

    edit_btn.callback = edit_btn_callback
    builder.add_action_row(edit_btn)

    back_style = discord.ButtonStyle.danger if back_label == "Close" else discord.ButtonStyle.secondary
    back_btn = discord.ui.Button(label=back_label, style=back_style, custom_id=f"back_{unique_id}")
    back_btn.callback = on_back
    back_row = discord.ui.ActionRow()
    back_row.add_item(back_btn)
    builder.add_item(back_row)

    return builder.build()
