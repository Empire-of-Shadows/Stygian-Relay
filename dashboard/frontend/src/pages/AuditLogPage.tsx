import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AuditLogEntry } from "../api/types";

const CATEGORIES = ["", "rules", "settings", "premium", "guild"];

export function AuditLogPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState("");

  async function load(before?: string) {
    if (!guildId) return;
    setLoading(true);
    try {
      const res = await api.auditLog(guildId, before ?? null, category || null, 50);
      setEntries((prev) => before ? [...prev, ...res.entries] : res.entries);
      setCursor(res.next_cursor);
      setHasMore(res.next_cursor !== null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setEntries([]);
    setCursor(null);
    load();
  }, [guildId, category]);

  if (!guildId) return null;

  return (
    <div className="dash-page">
      <div className="page-header">
        <div>
          <Link to={`/guilds/${guildId}`} className="muted" style={{ fontSize: 13 }}>← Back</Link>
          <h1 style={{ marginTop: 4 }}>Audit Log</h1>
        </div>
        <select value={category} onChange={(e) => setCategory(e.target.value)} style={{ width: "auto" }}>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c || "All categories"}</option>
          ))}
        </select>
      </div>

      {error && <div className="alert danger">{error}</div>}

      {entries.length === 0 && !loading && (
        <div className="empty-state" style={{ padding: "3rem", textAlign: "center" }}>
          <p>No audit log entries found.</p>
        </div>
      )}

      {entries.length > 0 && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Category</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                    {e.created_at ? new Date(e.created_at).toLocaleString() : "—"}
                  </td>
                  <td>
                    <span className="badge">{e.category}</span>
                  </td>
                  <td className="muted" style={{ fontFamily: "monospace", fontSize: 12 }}>{e.actor_id}</td>
                  <td style={{ fontWeight: 600 }}>{e.action}</td>
                  <td className="muted" style={{ fontSize: 12, maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {Object.keys(e.payload).length > 0 ? JSON.stringify(e.payload).slice(0, 120) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loading && <div className="loading">Loading…</div>}

      {hasMore && !loading && (
        <div style={{ textAlign: "center", marginTop: 16 }}>
          <button className="btn btn-secondary" onClick={() => load(cursor ?? undefined)}>
            Load more
          </button>
        </div>
      )}
    </div>
  );
}
