<div align="center">

# Stygian Relay

**Forward messages from one channel to another, within a server or across servers, by rules you set.**

[![Add to Discord](https://img.shields.io/badge/Add_to-Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/oauth2/authorize?client_id=1436174302385930330)
[![Dashboard](https://img.shields.io/badge/Dashboard-relay.eosofficial.club-7603FF?style=for-the-badge)](https://relay.eosofficial.club)
[![Docs](https://img.shields.io/badge/Docs-Wiki-7603FF?style=for-the-badge)](https://wiki.eosofficial.club/bots/stygian-relay)
[![Support](https://img.shields.io/badge/Support-Server-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/jxDQrYqcVv)

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.7-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)
[![MongoDB](https://img.shields.io/badge/MongoDB-pymongo_async-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

</div>

Stygian Relay copies messages from a source channel into a destination channel, following rules
you define. Mirror announcements into a second channel or a partner server, feed several channels
into one digest, or let two communities share a channel without merging.

> [!CAUTION]
> This bot reads message content, because the content it forwards *is* the product. There is no
> relay that does not read what it relays. If that is not something you want in a server, decline
> this bot; nothing else in the fleet depends on it.

## Contents

- [Rules](#rules)
- [Cross-server forwarding](#cross-server-forwarding)
- [Commands](#commands)
- [Getting started](#getting-started)
- [Dashboard](#dashboard)
- [Limits and premium](#limits-and-premium)
- [Privacy](#privacy)
- [Permissions and intents](#permissions-and-intents)
- [Development](#development)
- [Links](#links)

## Rules

Each rule is a source channel, a destination channel, and what happens in between.

| Option | What it does |
|---|---|
| **Message types** | Forward any mix of text, media, links, embeds, files and stickers. |
| **Keywords** | Require a keyword, or block one. Optionally case-sensitive or whole-word only. |
| **Length** | Minimum and maximum message length. |
| **Authors** | Allow or deny specific members or roles. |
| **Formatting** | Show or hide the author line, add a prefix or suffix, include or drop attachments and embeds. |

- **Attachments are re-uploaded**, not hotlinked, so they survive the original being deleted.
- **Link previews carry across**: the bot waits briefly for the source message's own preview so a
  video or article card is not lost.
- **Rules can be paused** without being deleted, and one master switch pauses all forwarding.
- **Broken rules speak up.** A rule that keeps failing, for example because the bot lost access to
  the destination, is switched off automatically and a notice goes to your log channel instead of
  messages silently disappearing.
- **A delivery log** shows what ran and where, without storing the message text.

## Cross-server forwarding

Forwarding into another server needs the bot in **both** servers, and the **destination** server
has to allow it:

1. The destination server's admin opens `/admin panel`, **Feature Toggles**, **Inbound Forward
   Allowlist**, and adds the source server's ID. An empty list blocks every inbound forward.
2. When you build the rule, the wizard only offers destination servers you are actually in, so a
   rule cannot be pointed at a stranger's server.

Rules within one server need neither step.

## Commands

| Command | Who can use it | What it does |
|---|---|---|
| `/admin panel` | Manage Server or the manager role | Server settings and the Forwarding Rules list, with the Add Rule wizard. |
| `/premium status` | Everyone | Whether this server has premium, and its limits. |
| `/help` | Everyone | How the bot works. |

## Getting started

1. [Add Stygian Relay to your server](https://discord.com/oauth2/authorize?client_id=1436174302385930330),
   and to the destination server too if it is a different one.
2. Run `/admin panel`. Under **Core**, set a **log channel** and, if you like, a **manager role**
   (a role that gets full admin access to this bot).
3. Open **Forwarding Rules** and choose **Add Rule**: pick the source, the destination and any
   filters.
4. For a cross-server rule, add the source server to the destination's inbound allowlist.
5. Send a test message and check it arrives.

## Dashboard

[relay.eosofficial.club](https://relay.eosofficial.club) signs you in with Discord, using the same
login as every Empire of Shadows site.

| Page | Who sees it |
|---|---|
| **Home** and **Privacy** - your servers, your relay privacy choices, export and erase | You |
| **Settings, Rules, Stats, Premium, Audit log** - build and edit rules, see what was forwarded, and who changed what | Admins (Manage Server or the manager role) |
| **Terms**, **Privacy policy** | Anyone, no login |

## Limits and premium

Forwarding itself is never behind premium. Premium raises the limits:

| | Free | Premium |
|---|---|---|
| Active rules per server | 15 | 40 |
| Forwarded messages per day | 500 | 5,000 |
| "Powered by Empire of Shadows" line | Now and then on a forwarded copy | Never |

The limits are defaults the operator can change. Turn on **Daily Limit Notice** to have the bot
say so in the channel when the day's limit is reached.

> [!NOTE]
> Premium is not on sale yet. `/premium status` shows your server's current limits.

## Privacy

Relay is the one bot in the fleet that republishes members' words elsewhere, so every member gets
two switches on the dashboard's Privacy page:

- **Do not relay my messages** - nothing you post is copied anywhere, by any rule, in any server.
- **Do not show my name** - your messages are still relayed, without the author line.

Your choice beats the mirror being complete. The full policy covering every Empire of Shadows bot
is at [eosofficial.club/privacy](https://eosofficial.club/privacy).

## Permissions and intents

| Permission | Where | Why |
|---|---|---|
| View Channel | Source and destination | Receive and post. |
| Send Messages | Destination and log channel | Every forward, plus notices. |
| Read Message History | Source | Re-reading a message whose preview arrives late. |
| Embed Links | Destination | Not cosmetic: link and video previews die without it. |
| Attach Files | Destination | Attachments are downloaded and re-uploaded. |

**Intents:** Guilds, Guild Messages and Message Content. No Server Members and no presence. The
bot cannot ping @everyone or roles.

## Development

<details>
<summary><b>Running it locally</b></summary>

<br>

Requires Python 3.13 and MongoDB. Configuration is read from `docker/.env`, with an optional
`docker/.env.local` override. Both are gitignored.

```bash
pip install -r requirements.txt
python Relay.py                 # the bot, health endpoint on :50013

pip install -r dashboard/requirements.txt
python -m dashboard.app         # the dashboard API, :54013

cd dashboard/frontend
npm install && npm run build    # the React front end
```

</details>

<details>
<summary><b>How the code is organised</b></summary>

<br>

| Path | What it is |
|---|---|
| `Relay.py` | Entry point: logging, database, health endpoint, then the bot. |
| `startup/` | Bot construction and cog discovery. |
| `commands/forward/` | The forwarder itself and the rule wizard. |
| `commands/premium/` | Premium: Discord entitlements, reconciliation, owner tools. |
| `storage/` | Database layer. Shared storage engine plus Relay's domain code in `storage/bot_specific/relay/` and member privacy in `storage/settings/user_preferences.py`. |
| `admin/` | The `/admin panel`. Shared admin engine plus Relay's panel tree in `admin/settings/`. |
| `dashboard/` | FastAPI backend and React front end. |

Files that start with a `# VENDORED ... DO NOT EDIT HERE` banner, including Relay's own domain
layer under `storage/bot_specific/relay/`, are copied in from the `EmpireSystems` repository.
Change them there and re-sync; never edit the copy.

Tests and migrations live outside this repository, in the ecosystem's
`TestsAndMigrations/Stygian-Relay/` folder.

</details>

## Links

- [Changelog](CHANGELOG.md) - what changed, in plain language
- [Stygian Relay on the wiki](https://wiki.eosofficial.club/bots/stygian-relay)
- [All six bots](https://wiki.eosofficial.club/bots) and [the main site](https://eosofficial.club)
- [Support server](https://discord.gg/jxDQrYqcVv) for help and bug reports
- [Community server](https://discord.gg/xx86YEhaYF), where the bots were built and are played

## Contributing, security and license

Contributions are welcome under the terms in [CONTRIBUTING.md](CONTRIBUTING.md). Please report
security problems privately as described in [SECURITY.md](SECURITY.md), not in a public issue.

Copyright (c) 2025-2026 Empire of Shadows. All rights reserved; see [LICENSE](LICENSE).

<div align="center">
<sub>Part of the <a href="https://eosofficial.club">Empire of Shadows</a> ecosystem</sub>
</div>
