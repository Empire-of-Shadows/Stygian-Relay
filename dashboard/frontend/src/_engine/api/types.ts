/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
/**
 * Shared dashboard types. Only genuinely cross-bot shapes live here; bot-specific
 * data types (and per-bot permission flags) stay in each bot's own `api/types.ts`,
 * which imports from here.
 */

/**
 * The logged-in Discord user's identity, as returned by every dashboard's /api/me.
 *
 * Each bot extends this with its own permission flags (see the bot's `User` / `Me`).
 * Identity fields are typed as nullable because Discord and the session store do not
 * guarantee them in every case; a bot whose backend always populates one (e.g. codex's
 * non-null `username`) may narrow it in its own interface.
 */
export interface SessionUser {
  id: string;
  username: string | null;
  global_name: string | null;
  avatar: string | null;
  discriminator: string | null;
}
