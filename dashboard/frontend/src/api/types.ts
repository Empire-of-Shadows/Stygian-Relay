/**
 * Relay's dashboard contract.
 *
 * The genuinely cross-bot shapes come from the shared dashboard engine and are
 * composed here rather than duplicated. The pattern is superset-in-the-engine,
 * narrow-in-the-bot: relay's backend always sends `panel_role` and always sends
 * `parent_id` on a channel, so both are re-declared required below.
 *
 * Note the imports are separate from the re-exports on purpose - `export type
 * { X } from ...` forwards a name without binding it locally, so the interfaces
 * further down could not extend it.
 */
import type {
  Channel as EngineChannel,
  FeatureStatus,
  Guild as EngineGuild,
  PanelRole,
  Role,
  SessionUser,
} from "../_engine/api/types";

export type { FeatureStatus, PanelRole, Role };
export type { FeatureState } from "../_engine/api/types";

export interface Me extends SessionUser {
  can_manage_any: boolean;
  can_access_admin_any: boolean;
  can_access_settings_any: boolean;
}

/** Relay always resolves a tier for every guild it returns. */
export interface Guild extends EngineGuild {
  panel_role: PanelRole;
}

/** Relay's channel listing always carries the category id. */
export interface Channel extends EngineChannel {
  parent_id: string | null;
}

export interface AuthorFilters {
  allow_user_ids: string[];
  deny_user_ids: string[];
  allow_role_ids: string[];
  deny_role_ids: string[];
}

/** Which kinds of message a rule copies. All false forwards nothing at all. */
export interface MessageTypes {
  text: boolean;
  media: boolean;
  links: boolean;
  embeds: boolean;
  files: boolean;
  stickers: boolean;
}

/** Keyword and length gates, applied to message content before forwarding. */
export interface RuleFilters {
  require_keywords: string[];
  block_keywords: string[];
  min_length: number;
  max_length: number;
}

/**
 * How a forwarded copy is written.
 *
 * `add_prefix` and `add_suffix` are applied as of 2026-08-19 - the bot wraps them around
 * the quote block, outside it, so they read as the rule owner's lines and not as words the
 * original author wrote.
 *
 * `forward_style` is the one still stored but NOT read: the runtime always renders the
 * quoted style. The editor says so on the page rather than presenting it as if it changed
 * the forwarded message. See dashboard/routers/rules.py::FormattingModel.
 */
export interface RuleFormatting {
  include_author: boolean;
  add_prefix: string;
  add_suffix: string;
  forward_attachments: boolean;
  forward_embeds: boolean;
  forward_style: string;
}

/** How keyword matching is performed. */
export interface AdvancedOptions {
  case_sensitive: boolean;
  whole_word_only: boolean;
}

export interface RuleSettings {
  author_filters: AuthorFilters;
  message_types: MessageTypes;
  filters: RuleFilters;
  formatting: RuleFormatting;
  advanced_options: AdvancedOptions;
}

/** The body of a rule create or update. Every settings section is optional. */
export interface RuleWriteBody {
  rule_name?: string;
  source_channel_id?: string;
  destination_channel_id?: string;
  destination_guild_id?: string;
  is_active?: boolean;
  author_filters?: AuthorFilters;
  message_types?: MessageTypes;
  filters?: RuleFilters;
  formatting?: RuleFormatting;
  advanced_options?: AdvancedOptions;
}

export interface Rule {
  rule_id: string;
  rule_name: string;
  source_channel_id: number;
  destination_channel_id: number;
  destination_guild_id: number;
  is_active: boolean;
  settings: RuleSettings;
  schema_version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface RulesResponse {
  rules: Rule[];
  count: number;
}

export interface DailyCount {
  date: string;
  forwarded: number;
  blocked: number;
}

export interface PerRuleStat {
  rule_id: string;
  rule_name: string;
  source_channel_id: string;
  destination_channel_id: string;
  destination_guild_id: string;
  is_active: boolean;
  deleted: boolean;
  forwarded: number;
}

export interface PerSourceStat {
  channel_id: string;
  forwarded: number;
}

/** Where the traffic landed. Same shape as PerSourceStat, different question. */
export type PerDestinationStat = PerSourceStat;

export interface BlockedReason {
  reason: string;
  count: number;
}

export interface StatsTotals {
  forwarded: number;
  lifetime: number;
  blocked: number;
  today_forwarded: number;
  daily_average: number;
  unique_sources: number;
  fanout_ratio: number;
  active_rules: number;
  peak: { date: string; forwarded: number } | null;
}

export interface StatsResponse {
  guild_id: string;
  period_days: number;
  generated_at: string;
  daily_limit: number;
  is_premium: boolean;
  totals: StatsTotals;
  daily: DailyCount[];
  hourly: number[];
  per_rule: PerRuleStat[];
  per_source: PerSourceStat[];
  per_destination: PerDestinationStat[];
  blocked_by_reason: BlockedReason[];
}

export interface PremiumStatus {
  guild_id: string;
  tier: string;
  tiers: string[];
  is_premium: boolean;
  expires_at: string | null;
  max_rules: number;
  daily_limit: number;
}

export interface GuildConfig {
  guild_id: string;
  master_log_channel_id: string | null;
  manager_role_id: string | null;
  is_enabled: boolean;
  premium_tier: string | null;
  features: Record<string, unknown>;
  limits: Record<string, unknown>;
  inbound_allowed_guilds: string[];
}

export interface AuditLogEntry {
  id: string;
  category: string;
  guild_id: string;
  actor_id: string;
  action: string;
  payload: Record<string, unknown>;
  created_at: string | null;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
  next_cursor: string | null;
}

/* ── Guild overview (the dashboard home) ────────────────────────────────
   Every section is independently nullable: the endpoint builds them
   concurrently and returns null for any one that failed, so a single broken
   collection cannot blank the page. `features` is the one exception - it is
   derived from the config document and degrades to an empty list. */

export interface TrafficDay {
  date: string;
  forwarded: number;
  blocked: number;
}

export interface TrafficOverview {
  days: number;
  daily: TrafficDay[];
  forwarded_30d: number;
  blocked_30d: number;
  lifetime: number;
  today_forwarded: number;
  daily_limit: number;
  days_active: number;
  avg_per_active_day: number;
  peak: { date: string; forwarded: number } | null;
  last_forward_at: string | null;
}

export interface OverviewRoute {
  rule_id: string;
  rule_name: string;
  source_channel_id: string;
  destination_channel_id: string;
  destination_guild_id: string;
  cross_guild: boolean;
  is_active: boolean;
  forwarded_30d: number;
}

export interface RulesOverview {
  total: number;
  active: number;
  paused: number;
  cross_guild: number;
  max_rules: number;
  idle_active: number;
  newest_at: string | null;
  routes: OverviewRoute[];
}

export interface DeliveryReason {
  reason: string;
  count: number;
  last_date: string | null;
}

export interface DeliveryOverview {
  blocked_30d: number;
  undeliverable_30d: number;
  reasons: DeliveryReason[];
}

export interface PlanOverview {
  tier: string;
  tiers: string[];
  is_premium: boolean;
  expires_at: string | null;
  max_rules: number;
  daily_limit: number;
}

export interface ConfigOverview {
  has_config: boolean;
  is_enabled: boolean;
  forwarding_enabled: boolean;
  notify_on_error: boolean;
  log_channel_id: string | null;
  manager_role_id: string | null;
  inbound_allowed_guilds: string[];
  last_change: {
    category: string;
    action: string;
    actor_id: string;
    at: string | null;
  } | null;
}

export interface GuildOverview {
  guild_id: string;
  features: FeatureStatus[];
  traffic: TrafficOverview | null;
  rules: RulesOverview | null;
  delivery: DeliveryOverview | null;
  plan: PlanOverview | null;
  config: ConfigOverview | null;
}

/* ── The member's own data (privacy page + member pane) ─────────────────── */

/**
 * The member's privacy choices.
 *
 * A `true` value means OPTED OUT of that thing - `show_name: true` is "do not show my
 * name". `all` is the master switch and covers both. Same polarity as the bot's
 * UserPreferenceCache, which is what lets `all` gate both without a special case.
 */
export interface PrivacyFeatures {
  all: boolean;
  relay_messages: boolean;
  show_name: boolean;
}

/** A server the member can scope an export or an erasure to. */
export interface ScopeGuild {
  id: string;
  name: string | null;
  icon: string | null;
}

export interface DeleteUserDataResponse {
  user_id: string;
  guild_id: string | null;
  deleted: Record<string, number>;
}

/** One active route, as a member is allowed to see it. */
export interface MemberRoute {
  rule_id: string;
  source_channel_id: string;
  source_channel_name: string | null;
  destination_channel_id: string;
  /** Null for a cross-server destination - that guild's channels are not fetched. */
  destination_channel_name: string | null;
  cross_server: boolean;
  destination_guild_id: string | null;
  destination_guild_name: string | null;
  /**
   * Whether this route would carry THIS member's messages.
   *
   * Null means "could not work it out" - the rule filters by role and the member's
   * roles could not be read. It is deliberately NOT false: an unread role set matches
   * no deny rule, so treating unknown as "not carried" reported the opposite of the
   * truth to a member who is in fact blocked.
   */
  carries_you: boolean | null;
}

export interface MemberGuildView {
  guild_id: string;
  guild_name: string | null;
  forwarding_enabled: boolean;
  has_config: boolean;
  routes: MemberRoute[];
  /** Routes that definitely carry this member. Unknown routes are NOT counted here. */
  carrying_you: number;
  /** Routes whose answer depends on roles that could not be read. */
  unknown_you: number;
}

export interface RelayViewResponse {
  guilds: MemberGuildView[];
  privacy: {
    relaying_paused: boolean;
    name_hidden: boolean;
  };
}
