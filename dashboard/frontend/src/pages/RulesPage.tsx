import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Rule } from "../api/types";

export function RulesPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    if (!guildId) return;
    api.rules(guildId)
      .then((r) => setRules(r.rules))
      .catch((e) => setError(String(e)));
  }, [guildId]);

  async function handleToggle(rule: Rule) {
    if (!guildId || toggling) return;
    setToggling(rule.rule_id);
    try {
      const res = await api.toggleRule(guildId, rule.rule_id);
      setRules((prev) =>
        prev?.map((r) => r.rule_id === rule.rule_id ? { ...r, is_active: res.is_active } : r) ?? null
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setToggling(null);
    }
  }

  async function handleDelete(rule: Rule) {
    if (!guildId || deleting) return;
    if (!confirm(`Delete rule "${rule.rule_name}"? This cannot be undone.`)) return;
    setDeleting(rule.rule_id);
    try {
      await api.deleteRule(guildId, rule.rule_id);
      setRules((prev) => prev?.filter((r) => r.rule_id !== rule.rule_id) ?? null);
    } catch (e) {
      setError(String(e));
    } finally {
      setDeleting(null);
    }
  }

  if (!guildId) return null;

  return (
    <div className="dash-page">
      <div className="page-header">
        <div>
          <Link to={`/guilds/${guildId}`} className="muted" style={{ fontSize: 13 }}>← Back</Link>
          <h1 style={{ marginTop: 4 }}>Forwarding Rules</h1>
        </div>
        <Link to={`/guilds/${guildId}/rules/new`} className="btn btn-primary">
          + New Rule
        </Link>
      </div>

      {error && <div className="alert danger">{error}</div>}

      {rules === null && !error && (
        <div className="loading">Loading rules…</div>
      )}

      {rules !== null && rules.length === 0 && (
        <div className="empty-state" style={{ padding: "3rem", textAlign: "center" }}>
          <p style={{ marginBottom: "1rem" }}>No forwarding rules configured yet.</p>
          <Link to={`/guilds/${guildId}/rules/new`} className="btn btn-primary">Create your first rule</Link>
        </div>
      )}

      {rules !== null && rules.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Source Channel</th>
                <th>Destination Channel</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.rule_id}>
                  <td style={{ fontWeight: 600 }}>{rule.rule_name}</td>
                  <td className="muted" style={{ fontFamily: "monospace", fontSize: 13 }}>
                    {rule.source_channel_id}
                  </td>
                  <td className="muted" style={{ fontFamily: "monospace", fontSize: 13 }}>
                    {rule.destination_channel_id}
                  </td>
                  <td>
                    <span className={`badge ${rule.is_active ? "success" : ""}`}>
                      {rule.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 8 }}>
                      <Link
                        to={`/guilds/${guildId}/rules/${rule.rule_id}`}
                        className="btn btn-secondary small"
                      >
                        Edit
                      </Link>
                      <button
                        className={`btn small ${rule.is_active ? "ghost" : "btn-success"}`}
                        onClick={() => handleToggle(rule)}
                        disabled={toggling === rule.rule_id}
                      >
                        {rule.is_active ? "Pause" : "Enable"}
                      </button>
                      <button
                        className="btn btn-danger small"
                        onClick={() => handleDelete(rule)}
                        disabled={deleting === rule.rule_id}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
