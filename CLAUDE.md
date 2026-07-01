# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

**Stygian-Relay** (`relay`) is the Empire of Shadows **channel-to-channel message forwarder**.
It mirrors/forwards messages between channels (and across guilds) according to per-guild
**rules** with filtering (allow/deny patterns, transforms). It is part of the larger
Empire of Shadows ecosystem (see the monorepo root `../../CLAUDE.md` and the engine masters in
`../../EmpireSystems/`).

- **Entry point:** `Relay.py` — loads `docker/.env` (+ `.env.local` override) → sets up logging →
  signal handlers → DB init → health endpoint (**port 50005**) → `on_ready` (database attach via
  `initialize_existing_guilds`, cog load, command sync, status).
- **Run locally:** `python Relay.py`  ·  **Docker:** `docker/stygian.sh` (joins `obsidian_grid`).

## Layout

| Path | What it is |
|---|---|
| `Relay.py` | Main entrypoint (bot-named, PascalCase). |
| `startup/` | `bot.py` (instance/intents/token), `sync.py` (parallel+priority cog loader, command table), `phases.py` (startup metrics/summary). Canonical ecosystem startup package. |
| `commands/` | Slash-command cogs: `admin/`, `common/`, `forward/`, `premium/`. `COG_DIRECTORIES = ["commands"]`. |
| `commands/admin/` | **Vendored `admin_engine`** (the shared `/admin panel`) + bot-owned `bindings.py`, `panel_configs.py`, `actions/__init__.py`. Branding text + tier resolution are inlined in `bindings.py` (valid variant — engine reads them through the bindings seam, no separate `panel_branding.py`/`role_auth.py`). |
| `database/` | **Bespoke data layer** (`core.py` → `db_core`, `guild_manager.py`, `rule_schema.py`, `permissions.py`, `audit.py`, `utils.py`, `exceptions.py`, `constants.py`). ⚠️ **Not yet migrated to the shared `storage_engine`** — see Standardization below. |
| `logger/` | Rich logging (`log_config.py`, `log_factory.py`) with an email `ErrorReporter` (`error_reporter.py`, `email_templates.py`, `reporting_types.py`). (Email transport is moving to Proton.) |
| `status/` | Presence / idle rotation. |
| `context/` | Reference docs (e.g. `componentsv2guide.md` — gitignored). |
| `docker/` | Dockerfile, docker-compose, `.env(.local)`, `stygian.sh`. |
| `dashboard/` | ⚠️ **Does not exist yet** — relay has no web dashboard. See Standardization. |

## The admin panel (vendored)

`commands/admin/` is the shared `admin_engine`, **vendored byte-for-byte** from
`../../EmpireSystems/admin_engine/` by `../../tools/sync_admin_engine.py`. **Never edit the
vendored files** — edit the master and re-run the sync. Drift gate:
`python tools/sync_admin_engine.py --check --bot relay` (run from the monorepo root). Bot-owned
(non-vendored) files: `bindings.py` (the backend seam — also inlines branding + tier resolution),
`panel_configs.py` (`MAIN_PANEL` tree), `actions/__init__.py`.

## Standardization status (ecosystem audit)

Relay is being aligned to the ecosystem standard (`../../audit/STANDARD.md`). **Done:** `startup/`
package, `commands/` cog dir, `Relay.py` entrypoint, dead `cogs/` removed, lowercase `context/`,
this `CLAUDE.md`. **Pending (large, tracked follow-ups):**
1. **`database/` → shared `storage_engine`** — adopt the vendored `storage/` (bindings/manager +
   `DefineCollections`/`DatabaseProperties` mixins, `db_core` → `db_manager`, generic
   `CollectionManager` capabilities), add `relay` to `tools/sync_storage_engine.py`, and base the
   logger on `storage.logging` (keeping the `ErrorReporter` as a bot-owned add-on, Proton-bound).
2. **Build a dashboard** (`dashboard/`) from the standard FastAPI + React/Vite skeleton.

## Conventions

- Async/await throughout; structured logging; graceful shutdown (signal handlers).
- MongoDB via the bespoke `database/` layer today (→ `storage_engine` after migration).
- Health endpoint on `:50005`. All services share the external `obsidian_grid` Docker network.
