/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
/**
 * Shared dashboard types. Only genuinely cross-bot shapes live here; bot-specific
 * data types (and per-bot permission flags) stay in each bot's own `api/types.ts`,
 * which imports from here.
 *
 * The pattern throughout is SUPERSET-HERE, NARROW-IN-THE-BOT: where bots disagree
 * on whether a field is present, the engine declares it optional and a bot that
 * always populates it re-declares it required in its own interface (see how
 * codex's `User` narrows `SessionUser`). That way adding a type here can never
 * invalidate a bot that was already correct.
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

/**
 * Access tier for one guild. ADMIN-ONLY fleet-wide - there is no Mod tier.
 *
 * Verified identical across all six bot frontends when this moved into the engine
 * (2026-08-12); no frontend anywhere still references a mod tier.
 */
export type PanelRole = "admin" | "none";

/**
 * One guild in the server picker.
 *
 * `panel_role` is optional because TheDecree and ImperialReminder omit it from
 * their payloads; bots that always send it should narrow it to required.
 *
 * `member_count` is the superset pattern in action: only some dashboards enrich
 * the listing from their guild snapshot, so it is optional AND nullable (a bot
 * that sends the field still sends null when it holds no snapshot). Consumers
 * must have a sensible answer for "absent" - GuildWebScene, for instance, draws
 * every orb the same size when nobody reports a count.
 */
export interface Guild {
  id: string;
  name: string;
  icon: string | null;
  bot_in_guild: boolean;
  has_config: boolean;
  setup_required: boolean;
  panel_role?: PanelRole;
  member_count?: number | null;
}

/**
 * A Discord channel, as returned by every dashboard's /api/guilds/{id}/channels.
 *
 * `parent_id` is optional: TheHost, Stygian-Relay and EcomRebuild return it,
 * the other three do not. Engine components must not depend on it.
 */
export interface Channel {
  id: string;
  name: string;
  type: number;
  position: number;
  parent_id?: string | null;
}

/** A Discord role, as returned by every dashboard's /api/guilds/{id}/roles. */
export interface Role {
  id: string;
  name: string;
  color: number;
  position: number;
}

/**
 * Whether a feature is doing anything right now.
 *
 * "needs_setup" is the load-bearing one: enabled but missing something it
 * cannot run without (a channel, a role). A bot that looks online and silently
 * does nothing is the single most common complaint against bot dashboards.
 */
export type FeatureState = "on" | "needs_setup" | "off";

export interface FeatureStatus {
  key: string;
  label: string;
  state: FeatureState;
  /** Short human line: "Posted today - 7 votes", "No channel set". */
  detail: string;
  /** Settings key this feature deep-links to. Null if not settable. */
  settings_key: string | null;
}
