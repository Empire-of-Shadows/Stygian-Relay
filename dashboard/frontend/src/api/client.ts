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

const BASE = "";

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let csrfToken: string | null = null;

async function fetchCsrfToken(): Promise<string> {
  const resp = await fetch(`${BASE}/auth/csrf`, { credentials: "include" });
  if (resp.status === 401) throw new UnauthorizedError();
  if (!resp.ok) throw new Error(`${resp.status}: failed to fetch CSRF token`);
  const data = (await resp.json()) as { csrf_token: string };
  csrfToken = data.csrf_token;
  return csrfToken;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const needsCsrf = UNSAFE_METHODS.has(method);

  const doFetch = async (): Promise<Response> => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...((init?.headers as Record<string, string>) ?? {}),
    };
    if (needsCsrf) {
      headers["X-CSRF-Token"] = csrfToken ?? (await fetchCsrfToken());
    }
    return fetch(`${BASE}${path}`, { credentials: "include", ...init, headers });
  };

  let resp = await doFetch();

  if (resp.status === 403 && needsCsrf) {
    csrfToken = null;
    resp = await doFetch();
  }

  if (resp.status === 401) throw new UnauthorizedError();
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export class UnauthorizedError extends Error {
  constructor() {
    super("Unauthorized");
    this.name = "UnauthorizedError";
  }
}

export const api = {
  me: () => request<Me>("/api/me"),
  guilds: () => request<Guild[]>("/api/guilds"),
  botInviteUrl: () => request<{ url: string | null }>("/api/bot-invite-url"),
  channels: (gid: string) => request<Channel[]>(`/api/guilds/${gid}/channels`),
  roles: (gid: string) => request<Role[]>(`/api/guilds/${gid}/roles`),

  rules: (gid: string) => request<RulesResponse>(`/api/guilds/${gid}/rules`),
  createRule: (gid: string, body: Omit<Rule, "rule_id" | "schema_version" | "created_at" | "updated_at">) =>
    request<Rule>(`/api/guilds/${gid}/rules`, { method: "POST", body: JSON.stringify(body) }),
  getRule: (gid: string, rid: string) => request<Rule>(`/api/guilds/${gid}/rules/${rid}`),
  updateRule: (gid: string, rid: string, body: Partial<Omit<Rule, "rule_id" | "schema_version" | "created_at" | "updated_at">>) =>
    request<{ ok: boolean }>(`/api/guilds/${gid}/rules/${rid}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRule: (gid: string, rid: string) =>
    request<void>(`/api/guilds/${gid}/rules/${rid}`, { method: "DELETE" }),
  toggleRule: (gid: string, rid: string) =>
    request<{ is_active: boolean }>(`/api/guilds/${gid}/rules/${rid}/toggle`, { method: "PATCH", body: "{}" }),

  stats: (gid: string, days = 30) =>
    request<StatsResponse>(`/api/guilds/${gid}/stats?days=${days}`),

  premium: (gid: string) => request<PremiumStatus>(`/api/guilds/${gid}/premium`),

  config: (gid: string) => request<GuildConfig>(`/api/guilds/${gid}/config`),
  saveConfig: (gid: string, patch: Partial<GuildConfig>) =>
    request<{ ok: boolean }>(`/api/guilds/${gid}/config`, { method: "PUT", body: JSON.stringify(patch) }),

  auditLog: (gid: string, before?: string | null, category?: string | null, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (before) params.set("before", before);
    if (category) params.set("category", category);
    return request<AuditLogResponse>(`/api/guilds/${gid}/audit-log?${params.toString()}`);
  },
};

export function discordLoginUrl(redirectTo?: string): string {
  const qs = redirectTo ? `?redirect_to=${encodeURIComponent(redirectTo)}` : "";
  return `/auth/discord${qs}`;
}

export function logoutUrl(): string {
  return "/auth/logout";
}
