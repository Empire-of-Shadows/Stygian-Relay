# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project Overview

**Stygian-Relay** (`relay`) is the Empire of Shadows **channel-to-channel message forwarder**.
It mirrors/forwards messages between channels (and across guilds) according to per-guild
**rules** with filtering (allow/deny patterns, transforms). It is part of the larger
Empire of Shadows ecosystem (see the monorepo root `../../CLAUDE.md` and the engine masters in
`../../EmpireSystems/`).

- **Entry point:** `Relay.py` — loads `docker/.env` (+ `.env.local` override) → `storage_engine.log`
  (loguru) setup (+ email ErrorReporter on root) → signal handlers → `db_manager` init → health endpoint
  (**port 50013**) → `on_ready` (Database Attachment via `attach_databases` +
  `initialize_existing_guilds`, cog load, command sync, status).
- **Run locally:** `python Relay.py`  ·  **Docker:** `docker/stygian.sh` (joins `obsidian_grid`).

## Layout

| Path | What it is |
|---|---|
| `Relay.py` | Main entrypoint (bot-named, PascalCase). |
| `startup/` | `bot.py` (instance/intents/token), `sync.py` (parallel+priority cog loader, command table), `phases.py` (startup metrics/summary). Canonical ecosystem startup package. |
| `commands/` | The bot's own slash-command cogs: `common/`, `forward/`, `premium/`. |
| `admin/` | Bot-owned admin **seam** (top-level, a sibling of `storage/`): `bindings.py` (backend seam; also inlines branding + tier resolution), `panel_configs.py` (`MAIN_PANEL` tree), `admin_setup.py` (the cog loader shim). `admin_engine` is an **installed package** — the shim injects the seam into its `AdminCog` (`AdminCog(bot, bindings=…, panel=MAIN_PANEL)`). Discovered via `COG_DIRECTORIES = ["commands", "admin"]`. |
| `storage/` | Bot-owned storage **seam** only: `bindings.py`, `define_collections.py` (collection registry), `manager.py` (→ the shared `db_manager`). `storage_engine` is an **installed package** (typed `db_manager.<key>` accessors are auto-derived from the registry — there is no `database_properties.py`). Relay's domain layer lives under `storage/bot_specific/relay/` (`guild_manager.py`, `audit.py`, `rule_schema.py`, `permissions.py`, `utils.py`, `exceptions.py`, `constants.py`) and reaches Mongo through the engine's pymongo connection (`db_manager.get_raw_collection` / `get_client`; two back-compat accessors on the concrete `DatabaseManager` keep the ported query logic unchanged). |
| `logger/` | Bot-owned email `ErrorReporter` add-on (`error_reporter.py`, `email_templates.py`, `reporting_types.py`) — the survivor of the old logging package; wired onto the root logger in `Relay.py` (ERROR+ → email). Structured logging itself now comes from `storage_engine.log` (loguru). (Email transport is moving to Proton.) |
| `status/` | Presence / idle rotation. |
| `context/` | Reference docs (e.g. `componentsv2guide.md` — gitignored). |
| `docker/` | Dockerfile, docker-compose, `.env(.local)`, `stygian.sh`. |
| `dashboard/` | ⚠️ **Does not exist yet** — relay has no web dashboard. See Standardization. |

## The admin panel (installed engine)

The `/admin panel` is the shared **`admin_engine`**, an **installed package** (from
`../../EmpireSystems/` — `pip install EmpireSystems[admin]`, see `requirements.txt`), never edited
in place. Relay supplies only the small seam in the top-level **`admin/`** directory: `bindings.py`
(the backend seam — also inlines branding + tier resolution), `panel_configs.py` (`MAIN_PANEL`
tree), and `admin_setup.py` (the cog loader shim). The engine no longer relative-imports the seam;
the shim injects it via `AdminCog(bot, bindings=bindings, panel=panel_configs.MAIN_PANEL)`. Seam
templates live at `../../EmpireSystems/Settings/admin/`.

## Standardization status (ecosystem audit)

Relay is aligned to the ecosystem standard (`../../audit/STANDARD.md`). **Done:** `startup/`
package, `commands/` cog dir, `Relay.py` entrypoint, dead `cogs/` removed, lowercase `context/`,
this `CLAUDE.md`, and the **storage + logging + engine-distribution migration** — the bespoke
`database/` was retired in favour of the shared `storage_engine`; its domain layer moved under
`storage/bot_specific/relay/` and runs on the shared `db_manager`, logging is now based on
`storage_engine.log` (loguru; the email `ErrorReporter` kept as a bot-owned add-on, Proton-bound),
and both engines are now **installed packages** (`EmpireSystems`, fetched from GitHub at build)
with admin moved out of `commands/` into a top-level `admin/` seam — no vendored copies or sync tools.
**Pending (large, tracked follow-up):**
1. **Build a dashboard** (`dashboard/`) from the standard FastAPI + React/Vite skeleton.

## Conventions

- Async/await throughout; structured logging (`storage_engine.log`); graceful shutdown (signal handlers).
- MongoDB via the shared `storage_engine` (`db_manager`); relay's domain logic lives in `storage/bot_specific/relay/`.
- Health endpoint on `:50013`. All services share the external `obsidian_grid` Docker network.
