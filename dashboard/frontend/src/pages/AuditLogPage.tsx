import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { AuditLogEntry } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import { KeyValue, Rule as Divider, Tile } from "../_engine/components/overview/Tile";
import { formatDateTime, formatRelative } from "../_engine/format";
import { AdminNav } from "../components/AdminNav";

/*
 * The change history.
 *
 * It used to be a five-column table where the "Actor" column was a raw snowflake and the
 * "Details" column was the first 120 characters of JSON. Nobody can read that, and the
 * one question the page exists to answer - who changed what, and when - was the one thing
 * it did not say.
 *
 * Every known action is written as a sentence. An action with no sentence yet falls back
 * to its raw name rather than being hidden, so a new bot-side or dashboard-side action
 * appears here the day it ships instead of silently vanishing.
 *
 * The name comes from `payload.actor_name`, which the dashboard's own writer records
 * alongside the id. Older entries and the bot's own writer carry only the id, so the id
 * is what renders then - never a fabricated name.
 */

// Only categories a writer actually produces (verified 2026-08-24: the audit
// writers emit exactly rules/settings/premium - the old "guild" and "system"
// options always returned an empty page).
const CATEGORIES = ["", "rules", "settings", "premium"];

const CATEGORY_LABELS: Record<string, string> = {
  rules: "Forwarding rules",
  settings: "Server settings",
  premium: "Premium",
};

function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category ?? "Other";
}

/**
 * One entry as a sentence.
 *
 * `payload` is typed loosely because two writers fill it - the bot's AuditLog and the
 * dashboard's - so every read is defensive. A missing field degrades the sentence rather
 * than throwing.
 */
function describe(entry: AuditLogEntry): string {
  const p = entry.payload ?? {};
  const str = (key: string): string => {
    const value = p[key];
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
  };
  const ruleName = str("rule_name") || str("rule_id") || "a rule";
  const fields = Array.isArray(p.fields) ? (p.fields as unknown[]).map(String) : [];

  switch (entry.action) {
    case "create_rule":
      return `Created the forwarding rule "${ruleName}".`;
    case "update_rule":
      return fields.length > 0
        ? `Edited the forwarding rule "${ruleName}" (${fields.length} setting${fields.length === 1 ? "" : "s"} changed).`
        : `Edited the forwarding rule "${ruleName}".`;
    case "delete_rule":
      return `Deleted the forwarding rule "${ruleName}".`;
    case "pause_rule":
      return `Paused the forwarding rule "${ruleName}".`;
    case "resume_rule":
      return `Resumed the forwarding rule "${ruleName}".`;
    case "update_config":
      return fields.length > 0
        ? `Changed the server settings (${humanFields(fields)}).`
        : "Changed the server settings.";
    case "set_manager_role":
      return "Changed which role can manage the relay.";
    default:
      // Unknown action: say what the raw name was rather than inventing a sentence, so a
      // new action is visible here the day it ships.
      return entry.action ? entry.action.replace(/_/g, " ") : "Made a change.";
  }
}

/** Turn stored field paths into something readable in a sentence. */
function humanFields(fields: string[]): string {
  const NAMES: Record<string, string> = {
    is_enabled: "the master switch",
    "features.forwarding_enabled": "the master switch",
    "features.notify_on_error": "error notices",
    master_log_channel_id: "the log channel",
    manager_role_id: "who can manage",
    inbound_allowed_guilds: "the cross-server allowlist",
  };
  const named = Array.from(new Set(fields.map((f) => NAMES[f] ?? f)));
  if (named.length === 1) return named[0];
  if (named.length === 2) return `${named[0]} and ${named[1]}`;
  return `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}`;
}

function actorLabel(entry: AuditLogEntry): string {
  const name = entry.payload?.actor_name;
  if (typeof name === "string" && name.trim()) return name;
  return entry.actor_id || "unknown";
}

export function AuditLogPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const category = searchParams.get("category") ?? "";
  const actorFilter = searchParams.get("actor") ?? "";

  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const setParam = (key: string, value: string) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  };

  const load = useCallback(
    async (before?: string) => {
      if (!guildId) return;
      setLoading(true);
      setError(null);
      try {
        const res = await api.auditLog(guildId, before ?? null, category || null, 50);
        setEntries((prev) => (before ? [...prev, ...res.entries] : res.entries));
        setCursor(res.next_cursor);
        setHasMore(res.next_cursor !== null);
      } catch (e) {
        setError(formatError(e));
      } finally {
        setLoading(false);
      }
    },
    [guildId, category],
  );

  useEffect(() => {
    setEntries([]);
    setCursor(null);
    load();
  }, [load]);

  /**
   * The actor filter is applied CLIENT-SIDE, over the pages already loaded.
   *
   * The API has no actor parameter, and adding one would mean a new index on a
   * TTL collection for a filter over at most a few hundred rows. The rail says how many
   * pages it is filtering so the number is never mistaken for the whole history.
   */
  const visible = useMemo(
    () => (actorFilter ? entries.filter((e) => e.actor_id === actorFilter) : entries),
    [entries, actorFilter],
  );

  const actors = useMemo(() => {
    const map = new Map<string, { id: string; label: string; count: number }>();
    for (const entry of entries) {
      const id = entry.actor_id || "unknown";
      const existing = map.get(id);
      if (existing) existing.count += 1;
      else map.set(id, { id, label: actorLabel(entry), count: 1 });
    }
    return Array.from(map.values()).sort((a, b) => b.count - a.count);
  }, [entries]);

  const byCategory = useMemo(() => {
    const map = new Map<string, number>();
    for (const entry of visible) {
      const key = entry.category || "other";
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  }, [visible]);

  if (!guildId) return null;

  const newest = visible[0]?.created_at ?? null;

  return (
    <div className="page">
      <div style={{ paddingTop: 16 }}>
        <AdminNav guildId={guildId} />
      </div>

      <div className="page-header">
        <div>
          <h1 style={{ marginTop: 4 }}>Change history</h1>
        </div>
      </div>

      <div className="ov-command">
        <span className="ov-muted" style={{ maxWidth: "44ch" }}>
          Every change to this server's relay - from the dashboard and from the bot's
          Discord panel. Entries are kept for a year.
        </span>
        <div className="ov-signals" style={{ gap: 12 }}>
          <div className="eos-field" style={{ marginBottom: 0 }}>
            <label htmlFor="audit-category">Area</label>
            <select
              id="audit-category"
              value={category}
              onChange={(e) => setParam("category", e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c ? categoryLabel(c) : "Everything"}</option>
              ))}
            </select>
          </div>
          <div className="eos-field" style={{ marginBottom: 0 }}>
            <label htmlFor="audit-actor">Who</label>
            <select
              id="audit-actor"
              value={actorFilter}
              onChange={(e) => setParam("actor", e.target.value)}
            >
              <option value="">Anyone</option>
              {actors.map((a) => (
                <option key={a.id} value={a.id}>{a.label}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {error && <Alert kind="danger">{error}</Alert>}

      <div className="ov-grid">
        <Tile
          span={8}
          title={
            visible.length === 0
              ? "Nothing recorded"
              : `${visible.length} change${visible.length === 1 ? "" : "s"} loaded`
          }
          quiet={visible.length === 0 && !loading}
        >
          {visible.length === 0 && !loading && (
            <p className="ov-body">
              {entries.length === 0
                ? "No changes have been recorded for this server yet. Anything you change here or in the bot's Discord panel will show up on this page."
                : "Nobody matching that filter has changed anything in the entries loaded so far. Load more, or clear the filter."}
            </p>
          )}

          <div className="ov-queue">
            {visible.map((entry) => (
              <div className="ov-qrow" key={entry.id} style={{ alignItems: "flex-start" }}>
                <span
                  className="ov-qrow__dot"
                  style={{ marginTop: 6, background: "var(--eos-fg-accent)" }}
                />
                <span style={{ minWidth: 0, flex: 1 }}>
                  <span className="ov-body" style={{ display: "block" }}>
                    {describe(entry)}
                  </span>
                  <span className="ov-muted">
                    <span title={entry.actor_id || undefined}>{actorLabel(entry)}</span>
                    {" - "}
                    {categoryLabel(entry.category)}
                    {entry.created_at ? ` - ${formatDateTime(entry.created_at)}` : ""}
                  </span>
                </span>
                <span className="ov-qrow__meta">
                  {entry.created_at ? formatRelative(entry.created_at) : "unknown"}
                </span>
              </div>
            ))}
          </div>

          {loading && <p className="ov-muted">Loading...</p>}

          {hasMore && !loading && (
            <div className="admin-actions">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => load(cursor ?? undefined)}
              >
                Load more
              </button>
            </div>
          )}
        </Tile>

        <Tile span={4} title="What has been changing">
          {byCategory.length === 0 ? (
            <p className="ov-muted">Nothing loaded to summarise yet.</p>
          ) : (
            <>
              <div>
                {byCategory.map(([key, count]) => (
                  <KeyValue key={key} k={categoryLabel(key)} v={String(count)} />
                ))}
              </div>
              <Divider />
              <KeyValue
                k="Most recent"
                v={newest ? formatRelative(newest) : "unknown"}
              />
              <KeyValue k="People involved" v={String(actors.length)} />
            </>
          )}
          <Divider />
          <p className="ov-muted">
            These counts cover the entries loaded so far, not the whole year. Load more to
            widen them.
            {actorFilter ? " The area counts also respect the person filter above." : ""}
          </p>
        </Tile>
      </div>
    </div>
  );
}
