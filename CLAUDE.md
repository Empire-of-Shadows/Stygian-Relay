# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

**Stygian-Relay** (`relay`) is the Empire of Shadows **channel-to-channel message forwarder**.
It mirrors/forwards messages between channels (and across guilds) according to per-guild
**rules** with filtering (allow/deny patterns, transforms). It is part of the larger
Empire of Shadows ecosystem (see the monorepo root `../../CLAUDE.md` and the engine masters in
`../../EmpireSystems/`).

- **Entry point:** `Relay.py` — loads `docker/.env` (+ `.env.local` override) → `storage.logging`
  (loguru) setup (+ email ErrorReporter on root) → signal handlers → `db_manager` init → health
  endpoint (**port 50013**) → `on_ready` (Database Attachment via `attach_databases` +
  `initialize_existing_guilds`, cog load, command sync, status).
- **Run locally:** `python Relay.py`  ·  **Docker:** `docker/stygian.sh` (joins `obsidian_grid`).

## Engine distribution: vendored, not installed

Both shared engines are **vendored copies** living in this repo. Relay does NOT pip-install
`EmpireSystems`; there is no engine entry in `requirements.txt` and no GitHub fetch at build.
This is deliberate — see the note at the bottom of this file.

| Engine | Master | Vendored into |
|---|---|---|
| `storage_engine` | `../../EmpireSystems/storage_engine/` | `storage/` (imported as `storage`) |
| `admin_engine` | `../../EmpireSystems/admin_engine/` | `commands/admin/` |

Files carrying a `# VENDORED ... DO NOT EDIT HERE` banner are generated. **Never edit them.**
Edit the master in `../../EmpireSystems/` and re-run the sync tool; drift is caught by `--check`.

## Layout

| Path | What it is |
|---|---|
| `Relay.py` | Main entrypoint (bot-named, PascalCase). |
| `startup/` | `bot.py` (instance/intents/token), `sync.py` (parallel+priority cog loader, command table), `phases.py` (startup metrics/summary). Canonical ecosystem startup package. |
| `commands/` | Slash-command cogs: `admin/`, `common/`, `forward/`, `premium/`. `COG_DIRECTORIES = ["commands"]`. |
| `commands/admin/` | **Vendored `admin_engine`** (the shared `/admin panel`) + the bot-owned seam: `bindings.py`, `panel_configs.py`, `actions/`. Branding text + tier resolution are inlined in `bindings.py` (valid variant — the engine reads them through the bindings seam, so there is no separate `panel_branding.py` / `role_auth.py`). |
| `storage/` | **Vendored `storage_engine`** + the bot-owned seam: `bindings.py`, `define_collections.py` (collection registry), `manager.py` (the concrete `DatabaseManager` → the shared `db_manager`). Relay's domain layer lives under `storage/bot_specific/relay/` (`guild_manager.py`, `audit.py`, `rule_schema.py`, `permissions.py`, `utils.py`, `exceptions.py`, `constants.py`) and reaches Mongo through the engine's pymongo connection. The bespoke `database/` package it replaced is gone. |
| `logger/` | Bot-owned email `ErrorReporter` add-on (`error_reporter.py`, `email_templates.py`, `reporting_types.py`) — the survivor of the old logging package; wired onto the root logger in `Relay.py` (ERROR+ → email). Structured logging itself comes from the vendored `storage.logging` (loguru). (Email transport is moving to Proton.) |
| `status/` | Presence / idle rotation. |
| `dashboard/` | FastAPI backend (`routers/`, `services/`, `auth/`) + React/Vite SPA (`frontend/`). Standalone: it does **not** import the bot's `storage/` package. |
| `context/` | Reference docs (e.g. `componentsv2guide.md` — gitignored). |
| `docker/` | Dockerfile, docker-compose, `.env(.local)`, `stygian.sh`. |

## Syncing the engines

Run from the **monorepo root** (`../../`):

```bash
python tools/sync_storage_engine.py --bot relay      # vendor master -> relay
python tools/sync_storage_engine.py --check --bot relay   # drift gate (non-zero on drift)
python tools/sync_admin_engine.py  --check --bot relay
```

Only the engine files listed in each tool's `ENGINE_FILES` are copied. Everything else in
`storage/` and `commands/admin/` is bot-owned and never touched — including everything under
`storage/bot_specific/relay/`.

## Standardization status (ecosystem audit)

Relay is aligned to the ecosystem standard (`../../audit/STANDARD.md`). **Done:** `startup/`
package, `commands/` cog dir, `Relay.py` entrypoint, dead `cogs/` removed, lowercase `context/`,
this `CLAUDE.md`, the **storage + logging migration** (the bespoke `database/` retired in favour of
the shared engine; its domain layer moved under `storage/bot_specific/relay/`; logging rebased on
`storage.logging` with the email `ErrorReporter` kept as a bot-owned add-on), and the
**dashboard** (FastAPI + React/Vite).

## Why vendored and not pip-installed

Relay briefly ran on `EmpireSystems` as an installed package (`pip install
EmpireSystems[admin,discord] @ git+https://github.com/...@dev`). That was **reverted deliberately**
— it added complexity without paying for itself at this stage:

- `docker/Dockerfile` clones Stygian-Relay standalone, so the engine had to be fetched from a
  second GitHub repo at build time.
- Builds tracked an unpinned `@dev` branch, so they were not reproducible.
- Any engine change required a push to EmpireSystems before relay could build.

Do **not** reintroduce the installed-package model here without a deliberate decision. The rest of
the fleet is vendored; relay matches it.

## Conventions

- Async/await throughout; structured logging (`storage.logging`); graceful shutdown (signal handlers).
- MongoDB via the vendored `storage_engine` (`db_manager`); relay's domain logic lives in `storage/bot_specific/relay/`.
- Health endpoint on `:50013`. All services share the external `obsidian_grid` Docker network.
