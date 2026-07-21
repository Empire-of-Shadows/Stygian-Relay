<div align="center">

# Stygian Relay

**Rule-based message forwarding bot for Empire of Shadows**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.7+-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)
[![MongoDB](https://img.shields.io/badge/MongoDB-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

Automatically mirrors messages between channels - within a server or across servers - based on configurable per-guild rules with filtering, transforms, and comprehensive audit logging.

</div>

---

## ✨ Features

<table>
<tr>
<td width="50%" valign="top">

### 📨 Forwarding Engine
- Channel-to-channel message mirroring
- Cross-server forwarding support
- Rule-based dispatch - multiple rules per guild, each with its own source and destination
- Setup wizard via `/forward setup` guides the initial configuration

</td>
<td width="50%" valign="top">

### 🔍 Advanced Filtering
- Filter by message content
- Filter by message type (text, media, links, embeds, files, stickers)
- Filter by message length
- Allow and deny lists per rule

</td>
</tr>
<tr>
<td width="50%" valign="top">

### 🗄️ Database-Backed Rules
- All per-guild settings and forwarding rules stored in MongoDB
- Rules survive restarts, redeploys, and bot outages
- Rule state (active/inactive) togglable without deletion

</td>
<td width="50%" valign="top">

### 🔒 Permissions & Audit
- Requires **Manage Server** permission to configure
- Comprehensive audit logging of all forwarding activity
- Dedicated log channel per guild for bot activity and errors

</td>
</tr>
</table>

### ⚙️ Admin Panel
> `/admin panel` - unified configuration panel (Discord Components v2) for per-guild forwarding settings, rule management, and bot configuration.

---

## 🔧 Required Permissions

For Stygian Relay to forward messages correctly, the bot needs:

| Permission | Why |
|---|---|
| **View Channels** | List and access source and destination channels |
| **Send Messages** | Post forwarded messages to destination channels |
| **Read Message History** | Retrieve messages from source channels |
| **Attach Files** | Forward messages containing file attachments |
| **Embed Links** | Display rich embeds in forwarded messages |
| **Manage Webhooks** | *(Recommended)* Enables seamless forwarding with custom name and avatar |

---

## 🔧 Tech Stack

| Layer | Technology |
|---|---|
| **Runtime** | Python 3.11+ |
| **Discord** | discord.py 2.7+ |
| **Database** | MongoDB · Motor (async) · asyncpg |
| **Admin Panel** | Discord Components v2 (vendored `admin_engine`) |
| **Storage** | Vendored `storage_engine` |
| **Deployment** | Docker Compose · `obsidian_grid` network |

---

<div align="center">
<sub>Part of the **Empire of Shadows** ecosystem · `Informatinal/Stygian-Relay`</sub>
</div>
