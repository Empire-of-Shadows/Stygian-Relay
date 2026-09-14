"""
Category content for the /help command.

Plain data module (no setup(), so the cog loader leaves it alone). The view
and cog live in help_commands.py.

TextDisplay formatting rules (verified against live rendering):
  - Bold (**text**) does NOT auto-newline. Append \\n explicitly after every
    bold header.
  - Use unicode bullets instead of dash list markers.
  - Keep each body well under the 4000-char TextDisplay limit.
"""

from dataclasses import dataclass
from typing import Optional

import discord

DASHBOARD_URL = "https://relay.eosofficial.club"
PRIVACY_URL = "https://relay.eosofficial.club/privacy"


@dataclass(frozen=True)
class HelpCategory:
    key: str
    label: str
    description: str  # select-option description, max 100 chars
    emoji: str
    accent: int
    thumbnail: Optional[str]  # asset filename; None = bot avatar
    admin_only: bool
    blurb: str  # short line beside the thumbnail
    body: str


OVERVIEW = HelpCategory(
    key="overview",
    label="Overview",
    description="What this bot does and how to use this help",
    emoji="\N{BOOKS}",
    accent=discord.Color.blue().value,
    thumbnail=None,
    admin_only=False,
    blurb="Messages posted in one channel, mirrored into another.",
    body=(
        "**What this bot does**\n"
        "Stygian Relay copies messages from one channel into another - inside "
        "this server, or into a different server that has agreed to receive "
        "them. Admins decide which channels are linked by creating forwarding "
        "rules.\n"
        "\n"
        "**How members experience it**\n"
        "\N{BULLET} There is nothing to run. Post normally in a linked channel "
        "and the bot handles the rest\n"
        "\N{BULLET} A copy appears in the destination channel as a quote that "
        "names you and links back to your original post. Copies never ping anyone\n"
        "\N{BULLET} Attachments come along when they fit the destination's "
        "upload limit; anything skipped is listed in a short note under the copy\n"
        "\N{BULLET} Only channels an admin has linked are watched, and messages "
        "from bots are never copied\n"
        "\N{BULLET} Nothing is forwarded until an admin adds at least one rule\n"
        "\N{BULLET} You decide about your own messages: on the dashboard's Privacy page "
        "you can stop them being relayed anywhere, or keep your name off the copies\n"
        "\n"
        "**Using this help**\n"
        "Pick a category from the dropdown below.\n"
        "\n"
        f"The web dashboard at {DASHBOARD_URL} covers the same setup in the "
        "browser.\n"
        "\n"
        "Responses to /help are only visible to you."
    ),
)

FORWARDING = HelpCategory(
    key="forwarding",
    label="Forwarding",
    description="How forwarding rules decide what gets copied",
    emoji="\N{TWISTED RIGHTWARDS ARROWS}",
    accent=discord.Color.purple().value,
    thumbnail=None,
    admin_only=False,
    blurb="One rule links one source channel to one destination channel.",
    body=(
        "**What a rule does**\n"
        "A rule watches one source channel and copies matching messages into "
        "one destination channel. A server can have several rules, and one "
        "source channel can feed more than one destination.\n"
        "\n"
        "**What gets copied**\n"
        "Each rule chooses which kinds of message it carries: plain text, "
        "media, links, embeds, file attachments, and stickers. Stickers are off "
        "by default, the rest are on.\n"
        "\n"
        "**Filters**\n"
        "\N{BULLET} Required and blocked keywords, optionally case-sensitive or "
        "whole-word only\n"
        "\N{BULLET} Minimum and maximum message length\n"
        "\N{BULLET} Allow or deny specific members and roles, so one rule can "
        "carry only certain people's posts\n"
        "\n"
        "**Limits**\n"
        "Every server has a cap on how many rules can be active at once and how "
        "many messages can be forwarded per day. When the daily cap is reached, "
        "forwarding pauses until midnight UTC and the bot says so in the source "
        "channel if the Daily Limit Notice is on. A flood of more than about ten "
        "messages a second is cut back: the extra messages are not copied.\n"
        "\n"
        "**Across servers**\n"
        "A rule can point into another server only if that server has added "
        "this one to its inbound allowlist. Without that opt-in the copy is "
        "refused, even if the bot is in both servers.\n"
        "\n"
        "**When a rule breaks**\n"
        "If the destination channel is deleted or the bot loses permission to "
        "post there, the rule stops delivering. After repeated failures it is "
        "switched off automatically and a notice is posted in the server's log "
        "channel. Once it is fixed, an admin resumes the rule from the dashboard's "
        "Forwarding rules page.\n"
        "\n"
        "Forwarded copies from servers on the free tier occasionally carry a "
        "small Empire of Shadows credit line at the bottom. Premium servers "
        "forward without it."
    ),
)

ADMIN = HelpCategory(
    key="admin",
    label="Admin",
    description="Server configuration, setup, and the dashboard",
    emoji="\N{WRENCH}",
    accent=discord.Color.red().value,
    thumbnail=None,
    admin_only=True,
    blurb="Configuration and management, for Manage Server and the Manager Role.",
    body=(
        "**`/admin panel`**\n"
        "The configuration panel for this server. Open to anyone with Manage "
        "Server or Administrator, plus anyone holding the Manager Role you "
        "configure. Sections:\n"
        "\N{BULLET} **Core** - the Manager Role (only Manage Server can change it), "
        "and the log channel where the bot posts rules it switched off and premium "
        "changes\n"
        "\N{BULLET} **Feature Toggles** - the master Message Forwarding switch, "
        "the Daily Limit Notice, and the inbound allowlist of servers permitted to "
        "forward into this one\n"
        "\N{BULLET} **Forwarding Rules** - the list of every rule with a delete "
        "option, headed by active rules against your limit and how many messages "
        "went out today. Add Rule walks through source channel, destination "
        "server, destination channel, and a name\n"
        "\N{BULLET} **Premium** - your current status and limits, read-only\n"
        "\n"
        "**`/premium status`**\n"
        "Whether this server has premium, which tier, when it expires, and the "
        "rule and daily-forward limits that apply. Premium raises both limits "
        "and removes the credit line from forwarded copies.\n"
        "\n"
        "**First-time setup**\n"
        "\N{BULLET} Add at least one rule under Forwarding Rules (Message "
        "Forwarding is already on; turning it off pauses every rule)\n"
        "\N{BULLET} Set a log channel so you see errors and auto-disabled rules\n"
        "\N{BULLET} To receive forwards from another server, add its server ID "
        "to the inbound allowlist first\n"
        "\n"
        "**Web dashboard**\n"
        f"The same setup is available in the browser at {DASHBOARD_URL} - sign "
        "in with Discord. It adds a rule editor with filters and pause/resume, "
        "forwarding stats, and a history of who changed what.\n"
        "\n"
        f"The privacy policy is at {PRIVACY_URL}"
    ),
)


CATEGORIES: dict[str, HelpCategory] = {
    c.key: c for c in (OVERVIEW, FORWARDING, ADMIN)
}
CATEGORY_ORDER: list[str] = list(CATEGORIES)
DEFAULT_CATEGORY = OVERVIEW.key
