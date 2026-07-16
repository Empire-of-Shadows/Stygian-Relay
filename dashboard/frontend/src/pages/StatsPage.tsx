import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Channel, StatsResponse, PerRuleStat, PerSourceStat } from "../api/types";

const RANGES = [7, 30, 90] as const;

const REASON_META: Record<string, { label: string; desc: string; color: string }> = {
  daily_limit_hit: {
    label: "Daily limit reached",
    desc: "Messages skipped after the server hit its daily forward cap.",
    color: "var(--warning)",
  },
  rate_limited: {
    label: "Rate limited",
    desc: "Bursts throttled to keep forwarding smooth.",
    color: "var(--warning)",
  },
  perm_failure: {
    label: "Misconfigured rule",
    desc: "Destination channel missing, or the bot lacks permission there.",
    color: "var(--danger)",
  },
};

function reasonMeta(reason: string) {
  return REASON_META[reason] ?? { label: reason, desc: "", color: "var(--muted)" };
}

function fmt(n: number): string {
  return n.toLocaleString();
}

/** Short UTC month/day for a YYYY-MM-DD key. */
function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

// ── Summary tile ──────────────────────────────────────────────────────────
function Tile({ value, label, sub, accent }: { value: string; label: string; sub?: string; accent?: boolean }) {
  return (
    <div className={`empire-stat${accent ? " empire-stat--accent" : ""}`}>
      <div className="empire-stat__value">{value}</div>
      <div className="empire-stat__label">{label}</div>
      {sub && <div className="empire-stat__sub">{sub}</div>}
    </div>
  );
}

// ── Daily forwarded trend (single-series area + hover crosshair) ───────────
function TrendChart({ daily }: { daily: StatsResponse["daily"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = daily.length;
  const W = 720;
  const H = 160;
  const padTop = 10;
  const padBottom = 22;
  const innerH = H - padTop - padBottom;
  const max = Math.max(1, ...daily.map((d) => d.forwarded));

  const x = (i: number) => (n <= 1 ? W / 2 : (i * W) / (n - 1));
  const y = (v: number) => padTop + innerH * (1 - v / max);

  const linePts = daily.map((d, i) => `${x(i)},${y(d.forwarded)}`).join(" ");
  const areaPath = `M0,${padTop + innerH} L${daily.map((d, i) => `${x(i)},${y(d.forwarded)}`).join(" L")} L${W},${padTop + innerH} Z`;

  const active = hover ?? (n > 0 ? n - 1 : 0);
  const cur = daily[active];

  // A few evenly-spaced date ticks along the axis.
  const tickIdx = n <= 1 ? [0] : [0, Math.floor((n - 1) / 2), n - 1];

  return (
    <div className="card">
      <div className="chart-head">
        <h3>Forwarded over time</h3>
        {cur && (
          <div className="chart-caption">
            <b>{shortDate(cur.date)}</b> &middot; <b>{fmt(cur.forwarded)}</b> forwarded
            {cur.blocked > 0 && <> &middot; {fmt(cur.blocked)} blocked</>}
          </div>
        )}
      </div>
      <div className="chart-wrap">
        <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Forwarded messages per day">
          <defs>
            <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--brand-2)" stopOpacity="0.45" />
              <stop offset="100%" stopColor="var(--brand)" stopOpacity="0.04" />
            </linearGradient>
          </defs>
          {/* baseline + mid gridlines */}
          <line className="grid-line" x1="0" y1={padTop + innerH} x2={W} y2={padTop + innerH} />
          <line className="grid-line" x1="0" y1={padTop + innerH / 2} x2={W} y2={padTop + innerH / 2} />
          <path d={areaPath} fill="url(#trendFill)" />
          <polyline points={linePts} fill="none" stroke="var(--brand-2)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          {hover !== null && cur && (
            <>
              <line className="grid-line" x1={x(active)} y1={padTop} x2={x(active)} y2={padTop + innerH} stroke="var(--brand-2)" strokeOpacity="0.5" />
              <circle cx={x(active)} cy={y(cur.forwarded)} r="4" fill="#fff" stroke="var(--brand-2)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            </>
          )}
          {tickIdx.map((i) => (
            <text key={i} className="axis-label" x={Math.min(Math.max(x(i), 18), W - 18)} y={H - 6} textAnchor="middle">
              {daily[i] ? shortDate(daily[i].date) : ""}
            </text>
          ))}
          <text className="axis-label" x="2" y={padTop + 8}>{fmt(max)}</text>
        </svg>
        <div className="hit-row" onMouseLeave={() => setHover(null)}>
          {daily.map((d, i) => (
            <div key={d.date} className="hit" onMouseEnter={() => setHover(i)} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Busiest hours (sequential magnitude bars, UTC) ─────────────────────────
function HoursChart({ hourly }: { hourly: number[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...hourly);
  const total = hourly.reduce((a, b) => a + b, 0);
  const peakHour = hourly.indexOf(Math.max(...hourly));
  const cur = hover ?? (total > 0 ? peakHour : null);

  return (
    <div className="card">
      <div className="chart-head">
        <h3>Busiest hours <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>(UTC)</span></h3>
        {cur !== null && (
          <div className="chart-caption">
            <b>{String(cur).padStart(2, "0")}:00</b> &middot; <b>{fmt(hourly[cur])}</b> forwarded
          </div>
        )}
      </div>
      <div className="hours-grid" onMouseLeave={() => setHover(null)}>
        {hourly.map((v, h) => (
          <div
            key={h}
            className="hour-bar"
            onMouseEnter={() => setHover(h)}
            style={{ height: `${(v / max) * 100}%`, opacity: 0.35 + 0.65 * (v / max) }}
            title={`${String(h).padStart(2, "0")}:00 · ${fmt(v)}`}
          />
        ))}
      </div>
      <div className="hours-axis">
        {Array.from({ length: 24 }, (_, h) => (
          <span key={h} style={{ textAlign: "center" }}>{h % 6 === 0 ? h : ""}</span>
        ))}
      </div>
    </div>
  );
}

// ── Generic horizontal share bars ──────────────────────────────────────────
type ShareItem = { key: string; name: string; meta?: string; value: number; muted?: boolean };
function ShareBars({ items }: { items: ShareItem[] }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="share-list">
      {items.map((it) => (
        <div key={it.key} className="share-row">
          <div className="share-row__head">
            <span className="share-row__name" title={it.name}>{it.name}</span>
            <span style={{ display: "flex", gap: 10, alignItems: "baseline", flexShrink: 0 }}>
              {it.meta && <span className="share-row__meta">{it.meta}</span>}
              <span className="share-row__val">{fmt(it.value)}</span>
            </span>
          </div>
          <div className="share-track">
            <div className={`share-fill${it.muted ? " share-fill--muted" : ""}`} style={{ width: `${(it.value / max) * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function StatsPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [days, setDays] = useState<number>(30);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [channels, setChannels] = useState<Map<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!guildId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.stats(guildId, days)
      .then((s) => { if (!cancelled) setStats(s); })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [guildId, days]);

  // Channel names are best-effort; stats still render if this fails.
  useEffect(() => {
    if (!guildId) return;
    let cancelled = false;
    api.channels(guildId)
      .then((chs: Channel[]) => {
        if (cancelled) return;
        setChannels(new Map(chs.map((c) => [c.id, c.name])));
      })
      .catch(() => { /* fall back to raw IDs */ });
    return () => { cancelled = true; };
  }, [guildId]);

  const channelName = (id: string): string => {
    if (!id) return "unknown";
    const name = channels.get(id);
    return name ? `#${name}` : `#${id}`;
  };

  const ruleItems: ShareItem[] = useMemo(
    () => (stats?.per_rule ?? []).map((r: PerRuleStat) => ({
      key: r.rule_id,
      name: r.deleted ? "Deleted rule" : r.rule_name,
      meta: r.deleted
        ? undefined
        : `${channelName(r.source_channel_id)} → ${channelName(r.destination_channel_id)}`,
      value: r.forwarded,
      muted: r.deleted || !r.is_active,
    })),
    [stats, channels],
  );

  const sourceItems: ShareItem[] = useMemo(
    () => (stats?.per_source ?? []).map((s: PerSourceStat) => ({
      key: s.channel_id,
      name: channelName(s.channel_id),
      value: s.forwarded,
    })),
    [stats, channels],
  );

  if (!guildId) return null;

  const t = stats?.totals;
  const hasActivity = !!t && (t.forwarded > 0 || t.blocked > 0);

  return (
    <div className="dash-page">
      <div className="page-header">
        <div>
          <Link to={`/guilds/${guildId}`} className="muted" style={{ fontSize: 13 }}>← Back</Link>
          <h1 style={{ marginTop: 4 }}>Forwarding Analytics</h1>
          <p className="muted" style={{ marginTop: 4 }}>
            Last {days} days
            {stats && <> &middot; updated {new Date(stats.generated_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</>}
          </p>
        </div>
        <div className="seg" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r} className={r === days ? "active" : ""} onClick={() => setDays(r)}>
              {r}d
            </button>
          ))}
        </div>
      </div>

      {error && <div className="alert danger">{error}</div>}
      {loading && !stats && <div className="loading">Loading analytics…</div>}

      {stats && t && (
        <>
          <div className="stats-tiles">
            <Tile accent value={fmt(t.forwarded)} label="Forwarded" sub={`in the last ${days} days`} />
            <Tile
              value={`${fmt(t.today_forwarded)} / ${fmt(stats.daily_limit)}`}
              label="Today"
              sub={t.today_forwarded >= stats.daily_limit ? "daily cap reached" : `${Math.round((t.today_forwarded / Math.max(1, stats.daily_limit)) * 100)}% of cap`}
            />
            <Tile value={fmt(t.daily_average)} label="Avg / day" />
            <Tile value={t.peak ? fmt(t.peak.forwarded) : "0"} label="Peak day" sub={t.peak ? shortDate(t.peak.date) : undefined} />
            <Tile value={t.fanout_ratio ? `${t.fanout_ratio}×` : "-"} label="Fan-out" sub={`${fmt(t.unique_sources)} source msgs`} />
            <Tile value={fmt(t.blocked)} label="Blocked" sub={stats.blocked_by_reason.length ? `${stats.blocked_by_reason.length} reasons` : "none"} />
          </div>

          {/* Today's quota gauge */}
          <div className="card" style={{ marginBottom: 24 }}>
            <div className="chart-head">
              <h3>Today's usage</h3>
              <div className="chart-caption">
                <b>{fmt(t.today_forwarded)}</b> / {fmt(stats.daily_limit)}
                {stats.is_premium && <span className="badge success" style={{ marginLeft: 8 }}>Premium</span>}
              </div>
            </div>
            <div style={{ height: 12, background: "rgba(255,255,255,0.08)", borderRadius: 999, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                width: `${Math.min(100, (t.today_forwarded / Math.max(1, stats.daily_limit)) * 100).toFixed(1)}%`,
                background: t.today_forwarded >= stats.daily_limit
                  ? "linear-gradient(135deg, var(--warning), #e8913a)"
                  : "linear-gradient(135deg, var(--brand), var(--brand-2))",
                borderRadius: 999,
                transition: "width 0.5s ease",
              }} />
            </div>
          </div>

          {!hasActivity && (
            <div className="empty-state" style={{ padding: "40px 24px" }}>
              No forwarding activity in this period yet. Once your rules start relaying messages, analytics will appear here.
            </div>
          )}

          {hasActivity && (
            <>
              <div className="section">
                <TrendChart daily={stats.daily} />
              </div>

              <div className="section">
                <HoursChart hourly={stats.hourly} />
              </div>

              {ruleItems.length > 0 && (
                <div className="section">
                  <h2>Top rules</h2>
                  <div className="card"><ShareBars items={ruleItems.slice(0, 10)} /></div>
                </div>
              )}

              {sourceItems.length > 0 && (
                <div className="section">
                  <h2>Busiest source channels</h2>
                  <div className="card"><ShareBars items={sourceItems} /></div>
                </div>
              )}

              {stats.blocked_by_reason.length > 0 && (
                <div className="section">
                  <h2>Why messages were blocked</h2>
                  <div className="card share-list">
                    {stats.blocked_by_reason.map((b) => {
                      const meta = reasonMeta(b.reason);
                      const pct = t.blocked > 0 ? (b.count / t.blocked) * 100 : 0;
                      return (
                        <div key={b.reason} className="reason-row">
                          <div className="reason-row__head">
                            <span className="reason-row__dot" style={{ background: meta.color }} />
                            <span className="reason-row__name">{meta.label}</span>
                            <span className="reason-row__val">{fmt(b.count)}</span>
                          </div>
                          {meta.desc && <div className="reason-row__desc">{meta.desc}</div>}
                          <div className="share-track">
                            <div className="share-fill" style={{ width: `${pct}%`, background: meta.color }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="section">
                <h2>Recent days</h2>
                <div className="card" style={{ padding: 0, overflow: "hidden" }}>
                  <div style={{ overflowX: "auto" }}>
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
                            <td className="muted">{shortDate(d.date)}</td>
                            <td>{fmt(d.forwarded)}</td>
                            <td className="muted">{fmt(d.blocked)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
