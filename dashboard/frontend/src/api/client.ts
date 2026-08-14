import type {
  AuditLogResponse,
  Channel,
  DeleteUserDataResponse,
  Guild,
  GuildConfig,
  GuildOverview,
  Me,
  PremiumStatus,
  PrivacyFeatures,
  RelayViewResponse,
  Role,
  Rule,
  RulesResponse,
  RuleWriteBody,
  ScopeGuild,
  StatsResponse,
} from "./types";
import { apiFetch } from "../_engine/api/http";

// Re-export the shared transport surface so pages keep importing from "./api/client".
export {
  UnauthorizedError,
  ApiError,
  TimeoutError,
  discordLoginUrl,
  logoutUrl,
} from "../_engine/api/http";

export const api = {
  me: () => apiFetch<Me>("/api/me", { suppressAuthHandler: true }),
  guilds: () => apiFetch<Guild[]>("/api/guilds"),
  botInviteUrl: () => apiFetch<{ url: string | null }>("/api/bot-invite-url"),
  channels: (gid: string) => apiFetch<Channel[]>(`/api/guilds/${gid}/channels`),
  roles: (gid: string) => apiFetch<Role[]>(`/api/guilds/${gid}/roles`),

  overview: (gid: string) => apiFetch<GuildOverview>(`/api/guilds/${gid}/overview`),

  rules: (gid: string) => apiFetch<RulesResponse>(`/api/guilds/${gid}/rules`),
  // The write body is its own type rather than a mangled `Omit<Rule, ...>`: a Rule holds
  // channel ids as numbers and its settings sections nested under `settings`, while the
  // API takes ids as strings and each settings section as a top-level field.
  createRule: (gid: string, body: RuleWriteBody) =>
    apiFetch<Rule>(`/api/guilds/${gid}/rules`, { method: "POST", body: JSON.stringify(body) }),
  getRule: (gid: string, rid: string) => apiFetch<Rule>(`/api/guilds/${gid}/rules/${rid}`),
  updateRule: (gid: string, rid: string, body: RuleWriteBody) =>
    apiFetch<{ ok: boolean }>(`/api/guilds/${gid}/rules/${rid}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRule: (gid: string, rid: string) =>
    apiFetch<void>(`/api/guilds/${gid}/rules/${rid}`, { method: "DELETE" }),
  toggleRule: (gid: string, rid: string) =>
    apiFetch<{ is_active: boolean }>(`/api/guilds/${gid}/rules/${rid}/toggle`, { method: "PATCH", body: "{}" }),

  stats: (gid: string, days = 30) =>
    apiFetch<StatsResponse>(`/api/guilds/${gid}/stats?days=${days}`),

  premium: (gid: string) => apiFetch<PremiumStatus>(`/api/guilds/${gid}/premium`),

  config: (gid: string) => apiFetch<GuildConfig>(`/api/guilds/${gid}/config`),
  saveConfig: (gid: string, patch: Partial<GuildConfig>) =>
    apiFetch<{ ok: boolean }>(`/api/guilds/${gid}/config`, { method: "PUT", body: JSON.stringify(patch) }),

  auditLog: (gid: string, before?: string | null, category?: string | null, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (before) params.set("before", before);
    if (category) params.set("category", category);
    return apiFetch<AuditLogResponse>(`/api/guilds/${gid}/audit-log?${params.toString()}`);
  },

  // ── The member's own data. Signed-in only; no panel access needed. ──────

  getUserPrivacy: () => apiFetch<{ features: PrivacyFeatures }>("/api/user/privacy"),
  saveUserPrivacy: (features: PrivacyFeatures) =>
    apiFetch<{ features: PrivacyFeatures }>("/api/user/privacy", {
      method: "PUT",
      body: JSON.stringify({ features }),
    }),

  userDataGuilds: () => apiFetch<ScopeGuild[]>("/api/user/data/guilds"),

  /**
   * A plain URL rather than a fetch: the response is a file attachment, and letting the
   * browser follow the link is what gets it a Save dialog. The session cookie rides along
   * because it is a same-origin navigation.
   */
  exportUserDataUrl: (gid: string | null) =>
    gid ? `/api/user/data/export?guild_id=${encodeURIComponent(gid)}` : "/api/user/data/export",

  deleteUserData: (gid: string | null) =>
    apiFetch<DeleteUserDataResponse>("/api/user/data", {
      method: "DELETE",
      body: JSON.stringify({ confirm: true, guild_id: gid }),
    }),

  relayView: (gid?: string | null) =>
    apiFetch<RelayViewResponse>(
      gid ? `/api/user/relay-view?guild=${encodeURIComponent(gid)}` : "/api/user/relay-view",
    ),
};
