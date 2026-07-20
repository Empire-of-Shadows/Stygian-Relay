import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AuthorFilters, Rule } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";

const DEFAULT_FILTERS: AuthorFilters = {
  allow_user_ids: [],
  deny_user_ids: [],
  allow_role_ids: [],
  deny_role_ids: [],
};

function parseIds(raw: string): string[] {
  return raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
}

function joinIds(ids: string[]): string {
  return ids.join(", ");
}

export function RuleEditorPage() {
  const { guildId, ruleId } = useParams<{ guildId: string; ruleId: string }>();
  const navigate = useNavigate();
  const isNew = ruleId === "new";

  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [ruleName, setRuleName] = useState("");
  const [sourceChannelId, setSourceChannelId] = useState("");
  const [destChannelId, setDestChannelId] = useState("");
  const [destGuildId, setDestGuildId] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [filters, setFilters] = useState<AuthorFilters>(DEFAULT_FILTERS);
  const [showFilters, setShowFilters] = useState(false);

  useEffect(() => {
    if (isNew || !guildId || !ruleId) return;
    api.getRule(guildId, ruleId)
      .then((rule: Rule) => {
        setRuleName(rule.rule_name);
        setSourceChannelId(String(rule.source_channel_id));
        setDestChannelId(String(rule.destination_channel_id));
        setDestGuildId(rule.destination_guild_id ? String(rule.destination_guild_id) : "");
        setIsActive(rule.is_active);
        setFilters(rule.settings?.author_filters ?? DEFAULT_FILTERS);
      })
      .catch((e) => setError(formatError(e)))
      .finally(() => setLoading(false));
  }, [guildId, ruleId, isNew]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!guildId) return;
    setSaving(true);
    setError(null);
    try {
      const body = {
        rule_name: ruleName,
        source_channel_id: sourceChannelId,
        destination_channel_id: destChannelId,
        destination_guild_id: destGuildId || undefined,
        is_active: isActive,
        author_filters: filters,
      };
      if (isNew) {
        await api.createRule(guildId, body as never);
      } else {
        await api.updateRule(guildId, ruleId!, body as never);
      }
      navigate(`/guilds/${guildId}/rules`);
    } catch (e) {
      setError(formatError(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="loading">Loading rule…</div>;
  if (!guildId) return null;

  return (
    <div className="dash-page" style={{ maxWidth: 640, margin: "0 auto" }}>
      <div className="page-header">
        <div>
          <Link to={`/guilds/${guildId}/rules`} className="muted" style={{ fontSize: 13 }}>← Rules</Link>
          <h1 style={{ marginTop: 4 }}>{isNew ? "New Rule" : "Edit Rule"}</h1>
        </div>
      </div>

      <Alert kind="danger">{error}</Alert>

      <form className="card" onSubmit={handleSubmit}>
        <div className="field">
          <label>Rule Name</label>
          <input type="text" value={ruleName} onChange={(e) => setRuleName(e.target.value)} required maxLength={100} placeholder="e.g. Announcements → General" />
        </div>

        <div className="field-row">
          <div className="field">
            <label>Source Channel ID</label>
            <input type="text" value={sourceChannelId} onChange={(e) => setSourceChannelId(e.target.value)} required placeholder="Channel snowflake" />
          </div>
          <div className="field">
            <label>Destination Channel ID</label>
            <input type="text" value={destChannelId} onChange={(e) => setDestChannelId(e.target.value)} required placeholder="Channel snowflake" />
          </div>
        </div>

        <div className="field">
          <label>Destination Guild ID <span className="muted">(optional — leave blank for same server)</span></label>
          <input type="text" value={destGuildId} onChange={(e) => setDestGuildId(e.target.value)} placeholder="Guild snowflake" />
        </div>

        <div className="field">
          <label className="toggle">
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
            <span>Active</span>
          </label>
        </div>

        <div className="admin-section">
          <button
            type="button"
            className="btn ghost small"
            onClick={() => setShowFilters((v) => !v)}
          >
            {showFilters ? "Hide" : "Show"} Author Filters
          </button>

          {showFilters && (
            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 12 }}>
              {(["allow_user_ids", "deny_user_ids", "allow_role_ids", "deny_role_ids"] as (keyof AuthorFilters)[]).map((key) => (
                <div key={key} className="field">
                  <label>{key.replace(/_/g, " ")}</label>
                  <input
                    type="text"
                    value={joinIds(filters[key])}
                    onChange={(e) =>
                      setFilters((f) => ({ ...f, [key]: parseIds(e.target.value) }))
                    }
                    placeholder="Comma-separated IDs"
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: "flex", gap: 12, marginTop: 16 }}>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? "Saving…" : isNew ? "Create Rule" : "Save Changes"}
          </button>
          <Link to={`/guilds/${guildId}/rules`} className="btn ghost">Cancel</Link>
        </div>
      </form>
    </div>
  );
}
