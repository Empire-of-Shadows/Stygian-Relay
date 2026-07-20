import type {
  AuditLogResponse,
  Channel,
  Guild,
  GuildConfig,
  Me,
  PremiumStatus,
  Role,
  Rule,
  RulesResponse,
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

  rules: (gid: string) => apiFetch<RulesResponse>(`/api/guilds/${gid}/rules`),
  createRule: (gid: string, body: Omit<Rule, "rule_id" | "schema_version" | "created_at" | "updated_at">) =>
    apiFetch<Rule>(`/api/guilds/${gid}/rules`, { method: "POST", body: JSON.stringify(body) }),
  getRule: (gid: string, rid: string) => apiFetch<Rule>(`/api/guilds/${gid}/rules/${rid}`),
  updateRule: (gid: string, rid: string, body: Partial<Omit<Rule, "rule_id" | "schema_version" | "created_at" | "updated_at">>) =>
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
};
