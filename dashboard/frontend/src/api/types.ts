export type PanelRole = "admin" | "none";

export interface Me {
  id: string;
  username: string | null;
  global_name: string | null;
  avatar: string | null;
  discriminator: string | null;
  can_manage_any: boolean;
  can_access_admin_any: boolean;
  can_access_mod_any: false;
  can_access_settings_any: boolean;
}

export interface Guild {
  id: string;
  name: string;
  icon: string | null;
  bot_in_guild: boolean;
  has_config: boolean;
  setup_required: boolean;
  panel_role: PanelRole;
}

export interface Channel {
  id: string;
  name: string;
  type: number;
  parent_id: string | null;
  position: number;
}

export interface Role {
  id: string;
  name: string;
  color: number;
  position: number;
}

export interface AuthorFilters {
  allow_user_ids: string[];
  deny_user_ids: string[];
  allow_role_ids: string[];
  deny_role_ids: string[];
}

export interface RuleSettings {
  author_filters: AuthorFilters;
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
  forwarded: number;
}

export interface StatsResponse {
  guild_id: string;
  period_days: number;
  total_forwarded: number;
  total_blocked: number;
  today_forwarded: number;
  daily_limit: number;
  is_premium: boolean;
  daily: DailyCount[];
  per_rule: PerRuleStat[];
}

export interface PremiumStatus {
  guild_id: string;
  tier: "free" | "premium" | "lifetime";
  is_premium: boolean;
  is_lifetime: boolean;
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
