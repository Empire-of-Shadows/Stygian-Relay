import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { StatsResponse } from "../api/types";

export function StatsPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!guildId) return;
    api.stats(guildId, 30)
      .then(setStats)
      .catch((e) => setError(String(e)));
  }, [guildId]);

  if (!guildId) return null;

  return (
    <div className="dash-page">
      <div className="page-header">
        <div>
          <Link to={`/guilds/${guildId}`} className="muted" style={{ fontSize: 13 }}>← Back</Link>
          <h1 style={{ marginTop: 4 }}>Forwarding Stats</h1>
          <p className="muted" style={{ marginTop: 4 }}>Last 30 days</p>
        </div>
      </div>

      {error && <div className="alert danger">{error}</div>}

      {stats === null && !error && <div className="loading">Loading stats…</div>}

      {stats !== null && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 16, marginBottom: 24 }}>
            <div className="empire-stat">
              <div className="empire-stat__value">{stats.total_forwarded.toLocaleString()}</div>
              <div className="empire-stat__label">Total Forwarded</div>
            </div>
            <div className="empire-stat">
              <div className="empire-stat__value">{stats.today_forwarded.toLocaleString()}</div>
              <div className="empire-stat__label">Today</div>
            </div>
            <div className="empire-stat">
              <div className="empire-stat__value">{stats.total_blocked.toLocaleString()}</div>
              <div className="empire-stat__label">Blocked</div>
            </div>
            <div className="empire-stat">
              <div className="empire-stat__value">{stats.daily_limit.toLocaleString()}</div>
              <div className="empire-stat__label">Daily Limit</div>
            </div>
          </div>

          {stats.today_forwarded > 0 && (
            <div className="card" style={{ marginBottom: 24 }}>
              <h3 style={{ marginBottom: 8 }}>Today's Usage</h3>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{
                  flex: 1, height: 12, background: "rgba(255,255,255,0.08)", borderRadius: 999, overflow: "hidden"
                }}>
                  <div style={{
                    height: "100%",
                    width: `${Math.min(100, (stats.today_forwarded / stats.daily_limit) * 100).toFixed(1)}%`,
                    background: "linear-gradient(135deg, var(--brand), var(--brand-2))",
                    borderRadius: 999,
                    transition: "width 0.5s ease",
                  }} />
                </div>
                <span className="muted" style={{ fontSize: 13, whiteSpace: "nowrap" }}>
                  {stats.today_forwarded} / {stats.daily_limit}
                </span>
              </div>
            </div>
          )}

          {stats.daily.length > 0 && (
            <div className="section">
              <h2>Daily Activity</h2>
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Forwarded</th>
                      <th>Blocked</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...stats.daily].reverse().slice(0, 14).map((d) => (
                      <tr key={d.date}>
                        <td className="muted">{d.date}</td>
                        <td>{d.forwarded.toLocaleString()}</td>
                        <td className="muted">{d.blocked.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {stats.per_rule.length > 0 && (
            <div className="section">
              <h2>By Rule (30d)</h2>
              <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Rule ID</th>
                      <th>Forwarded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.per_rule.map((r) => (
                      <tr key={r.rule_id}>
                        <td className="muted" style={{ fontFamily: "monospace", fontSize: 13 }}>{r.rule_id}</td>
                        <td>{r.forwarded.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
