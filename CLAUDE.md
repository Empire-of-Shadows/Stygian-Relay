# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

**Stygian-Relay** (`relay`) is the Empire of Shadows **channel-to-channel message forwarder**.
It mirrors/forwards messages between channels (and across guilds) according to per-guild
**rules** with filtering (allow/deny patterns, transforms). It is part of the larger
Empire of Shadows ecosystem (see the monorepo root `../../CLAUDE.md` and the engine masters in
`../../EmpireSystems/`).

- **Entry point:** `Relay.py` — loads `docker/.env` (+ `.env.local` override) → `storage.logging`
  setup (+ email ErrorReporter on root) → signal handlers → `db_manager` init → health
  endpoint (**port 50013**) → `on_ready` (Database Attachment via `attach_databases` +
  `initialize_existing_guilds`, cog load, command sync, status).
- **Run locally:** `python Relay.py`  ·  **Docker:** `docker/stygian.sh` (joins `obsidian_grid`).

## Engine distribution: vendored, not installed

Both shared engines are **vendored copies** living in this repo. Relay does NOT pip-install
`EmpireSystems`; there is no engine entry in `requirements.txt` and no GitHub fetch at build.
This is deliberate — see the note at the bottom of this file.

| Master | Vendored into | Owner |
|---|---|---|
| `../../EmpireSystems/storage_engine/` | `storage/` (imported as `storage`) | master |
| `../../EmpireSystems/admin_engine/` | `admin/` (at the repo root) | master |
| `../../EmpireSystems/storage_engine/bot_specific/relay/` | `storage/bot_specific/relay/` | master, relay only |
| — | `admin/settings/`, `storage/settings/` | **relay** (the seam) |

Files carrying a `# VENDORED ... DO NOT EDIT HERE` banner are generated. **Never edit them.**
Edit the master in `../../EmpireSystems/` and re-run the sync tool; drift is caught by `--check`.

**Relay is the pilot for the ecosystem layout**: engines at the repo root, everything relay
writes by hand grouped in a `settings/` package inside each. The other five bots are still on
the old flat layout (`commands/admin/`), and `sync_admin_engine.py` refuses to vendor across
layouts, so they are frozen until each is migrated.

### Syncing

```bash
# from the monorepo root
python EmpireSystems/tools/sync_admin_engine.py   --check --bot relay
python EmpireSystems/tools/sync_storage_engine.py --check --bot relay --scope bot-specific
```

⚠️ **Never run `sync_storage_engine.py --bot relay --scope engine`.** Relay is still on the
pre-loguru `storage/logging/` package while the master ships loguru `log/`; syncing the storage
engine would rewrite `storage/__init__.py` to import `.log` against relay's on-disk `logging/`
and hard-fail every import. The tool's `LEGACY_LOGGING` guard refuses it. Relay's loguru
migration is a tracked follow-up.

## Layout

| Path | What it is |
|---|---|
| `Relay.py` | Main entrypoint (bot-named, PascalCase). |
| `startup/` | `bot.py` (instance/intents/token), `sync.py` (parallel+priority cog loader, command table), `phases.py` (startup metrics/summary). Canonical ecosystem startup package. |
| `commands/` | Relay's own slash-command cogs only: `common/`, `forward/`, `premium/`. Cog discovery is `COG_DIRECTORIES = ["commands", "admin"]`. |
| `admin/` | **Vendored `admin_engine`** (the shared `/admin panel`), at the repo root. `admin/settings/` is the bot-owned seam: `bindings.py`, `panel_configs.py`. Branding text + tier resolution are inlined in `bindings.py` (valid variant — the engine reads them through the bindings seam, so there is no separate `panel_branding.py` / `role_auth.py`). `admin/admin_cog.py` is the only `def setup(...)` under `admin/`, so discovery picks up exactly it. |
| `storage/` | **Vendored `storage_engine`**. `storage/settings/` is the bot-owned seam: `bindings.py`, `define_collections.py` (collection registry), `database_properties.py`, `manager.py` (the concrete `DatabaseManager` → the shared `db_manager`). The bespoke `database/` package it replaced is gone. |
| `storage/bot_specific/relay/` | Relay's domain layer — **master-owned**, authored in `../../EmpireSystems/storage_engine/bot_specific/relay/` and vendored here. Grouped by feature: `guild/` (`guild_manager.py`, `constants.py`, `permissions.py`), `forwarding/` (`rule_schema.py`), `audit/` (`writer.py`), plus flat `exceptions.py` / `utils.py` (plumbing, deliberately not directories). Reaches Mongo through the engine's pymongo connection. Import the singletons from the facade: `from storage.bot_specific.relay import db_manager, guild_manager, audit_log`. |
| `logger/` | Bot-owned email `ErrorReporter` add-on (`error_reporter.py`, `email_templates.py`, `reporting_types.py`) — the survivor of the old logging package; wired onto the root logger in `Relay.py` (ERROR+ → email). Structured logging itself comes from the vendored `storage.logging` (stdlib-based; the master's loguru `log/` is not adopted yet). (Email transport is moving to Proton.) |
| `status/` | Presence / idle rotation. |
| `dashboard/` | FastAPI backend (`routers/`, `services/`, `auth/`) + React/Vite SPA (`frontend/`). Standalone: it does **not** import the bot's `storage/` package. |
| `context/` | Reference docs (e.g. `componentsv2guide.md` — gitignored). |
| `docker/` | Dockerfile, docker-compose, `.env(.local)`, `stygian.sh`. |

## What is and isn't yours

Only `admin/settings/` and `storage/settings/` are relay's to edit. Everything else in those two
directories is generated — the engine (from `ENGINE_FILES`) and relay's own domain layer (from
`bot_specific/relay/`). That is the point of the split: hand-written and generated code no longer
interleave.

To change relay's domain logic (`guild_manager`, `rule_schema`, `audit`, …) edit the **master** at
`../../EmpireSystems/storage_engine/bot_specific/relay/` and re-vendor. Editing the copy here is
what `--check` reports as drift; a file here that the master lacks is reported as `[ORPHAN]`.

## Standardization status (ecosystem audit)

Relay is aligned to the ecosystem standard (`../../audit/STANDARD.md`), and is the **pilot** for
the root-`admin/` + `settings/`-seam layout. **Done:** `startup/` package, `Relay.py` entrypoint,
dead `cogs/` removed, lowercase `context/`, this `CLAUDE.md`, the **storage migration** (the
bespoke `database/` retired in favour of the shared engine), the **dashboard** (FastAPI +
React/Vite), and the **layout migration** (engines at the repo root, seams grouped in `settings/`,
domain layer moved into the master under `bot_specific/relay/<feature>/`).

**Pending:** the **loguru migration** — relay is still on the pre-loguru `storage/logging/` while
the master ships `log/`. Until then its storage engine cannot be re-vendored (see the warning
above); `--scope engine` is refused by the tool's `LEGACY_LOGGING` guard.

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
