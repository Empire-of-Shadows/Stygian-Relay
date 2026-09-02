import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Channel, StatsResponse, PerRuleStat, PerSourceStat } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import SignalStrip, { type Signal } from "../_engine/components/overview/SignalStrip";
import { KeyValue, Rule as Divider, Stat, Tile } from "../_engine/components/overview/Tile";
import { formatCount } from "../_engine/format";
import { AdminNav } from "../components/AdminNav";
import { reasonColor, reasonHelp, reasonLabel } from "../components/overview/format";

/*
 * Forwarding analytics.
 *
 * SHELL MIGRATION, not a rewrite. The page's own drawings are the good part and are kept
 * exactly: the two-series trend chart with its hover crosshair, the 24-hour bars, the
 * horizontal share bars, and the route cards. What changed is the frame around them - the
 * bespoke `.bento` grid and `.stats-tiles` strip became the engine's `.page` column,
 * `.ov-grid` and SignalStrip, so this page sits in the same layout as the home page
 * instead of its own.
 *
 * Two side cards were replaced rather than restyled: UsageCard and BlockedCard were
 * card-shaped restatements of things the Tile idiom says better, and their blocked-reason
 * wording was a second, differently-worded copy of the overview's. That copy is gone -
 * both pages now read the one map in components/overview/format.ts.
 *
 * Four things were ADDED, all from data the endpoint already returned or now returns in
 * the same single pass: where traffic lands (per_destination), blocked over time drawn
 * from daily[].blocked, which day of the week is busiest, and the split between routes
 * that stay in this server and routes that leave it.
 *
 * Every figure here is real. Where a series has no history the chart says so in a
 * sentence rather than drawing a flat line at zero.
 */

const RANGES = [7, 30, 90] as const;

function fmt(n: number): string {
  return n.toLocaleString();
}

/** Short UTC month/day for a YYYY-MM-DD key. */
function shortDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Day-of-week index for a YYYY-MM-DD key, read as a UTC calendar day. */
function weekdayOf(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}

// ── Daily trend (two series: forwarded area + blocked companion) ───────────
/**
 * Kept from the previous page, with the blocked series added as a companion line.
 *
 * The blocked line is drawn on the SAME scale as forwarded on purpose. A second axis
 * would make three blocked messages look like a crisis next to three thousand forwarded
 * ones; on one scale the reader can see it is a rounding error, which is the truth.
 */
function TrendChart({ daily }: { daily: StatsResponse["daily"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const n = daily.length;
  const W = 720;
  const H = 170;
  const padTop = 10;
  const padBottom = 22;
  const innerH = H - padTop - padBottom;
  const max = Math.max(1, ...daily.map((d) => Math.max(d.forwarded, d.blocked)));
  const anyBlocked = daily.some((d) => d.blocked > 0);

  const x = (i: number) => (n <= 1 ? W / 2 : (i * W) / (n - 1));
  const y = (v: number) => padTop + innerH * (1 - v / max);

  const linePts = daily.map((d, i) => `${x(i)},${y(d.forwarded)}`).join(" ");
  const blockedPts = daily.map((d, i) => `${x(i)},${y(d.blocked)}`).join(" ");
  const areaPath = `M0,${padTop + innerH} L${daily.map((d, i) => `${x(i)},${y(d.forwarded)}`).join(" L")} L${W},${padTop + innerH} Z`;

  const active = hover ?? (n > 0 ? n - 1 : 0);
  const cur = daily[active];
  const tickIdx = n <= 1 ? [0] : [0, Math.floor((n - 1) / 2), n - 1];

  return (
    <>
      <div className="chart-head">
        {cur && (
          <div className="chart-caption">
            <b>{shortDate(cur.date)}</b> &middot; <b>{fmt(cur.forwarded)}</b> forwarded
            {cur.blocked > 0 && <> &middot; {fmt(cur.blocked)} blocked</>}
          </div>
        )}
        {anyBlocked && (
          <div className="chart-legend">
            <span><i style={{ background: "var(--brand-2)" }} />Forwarded</span>
            <span><i style={{ background: "var(--warning)" }} />Blocked</span>
          </div>
        )}
      </div>
      <div className="chart-wrap">
        <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Forwarded and blocked messages per day">
          <defs>
            <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--brand-2)" stopOpacity="0.45" />
              <stop offset="100%" stopColor="var(--brand)" stopOpacity="0.04" />
            </linearGradient>
          </defs>
          <line className="grid-line" x1="0" y1={padTop + innerH} x2={W} y2={padTop + innerH} />
          <line className="grid-line" x1="0" y1={padTop + innerH / 2} x2={W} y2={padTop + innerH / 2} />
          <path d={areaPath} fill="url(#trendFill)" />
          <polyline points={linePts} fill="none" stroke="var(--brand-2)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          {anyBlocked && (
            <polyline
              points={blockedPts}
              fill="none"
              stroke="var(--warning)"
              strokeWidth="1.5"
              strokeDasharray="4 3"
              strokeLinejoin="round"
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
            />
          )}
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
    </>
  );
}

// ── Busiest hours (sequential magnitude bars, UTC) ─────────────────────────
function HoursChart({ hourly }: { hourly: number[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...hourly);
  const total = hourly.reduce((a, b) => a + b, 0);
  const peakHour = hourly.indexOf(Math.max(...hourly));
  const cur = hover ?? (total > 0 ? peakHour : null);

  if (total === 0) {
    return <p className="ov-muted">Nothing has been forwarded in this period, so there is no busiest hour yet.</p>;
  }

  return (
    <>
      <div className="chart-head">
        <span className="ov-muted">Times are UTC</span>
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
            title={`${String(h).padStart(2, "0")}:00 - ${fmt(v)}`}
          />
        ))}
      </div>
      <div className="hours-axis">
        {Array.from({ length: 24 }, (_, h) => (
          <span key={h} style={{ textAlign: "center" }}>{h % 6 === 0 ? h : ""}</span>
        ))}
      </div>
    </>
  );
}

// ── Generic horizontal share bars ─────────────────────────────────────────
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

// ── Route cards - the "top rules" display ──────────────────────────────────
function RouteCards({
  rules,
  total,
  guildId,
  channelName,
}: {
  rules: PerRuleStat[];
  total: number;
  guildId: string;
  channelName: (id: string) => string;
}) {
  return (
    <div className="route-grid">
      {rules.slice(0, 9).map((r, i) => {
        const status = r.deleted ? "deleted" : r.is_active ? "active" : "paused";
        const statusLabel = r.deleted ? "No longer exists" : r.is_active ? "Active" : "Paused";
        const crossGuild = !r.deleted && r.destination_guild_id !== "" && r.destination_guild_id !== guildId;
        const share = total > 0 ? Math.round((r.forwarded / total) * 100) : 0;
        const card = (
          <>
            <div className="route-card__top">
              <span className="route-rank">#{i + 1}</span>
              <span className="route-name" title={r.deleted ? "Deleted rule" : r.rule_name}>
                {r.deleted ? "Deleted rule" : r.rule_name}
              </span>
              <span className={`route-status route-status--${status}`} title={statusLabel} aria-label={statusLabel} />
            </div>
            {r.deleted ? (
              <div className="route-path route-path--gone">Rule no longer exists</div>
            ) : (
              <div className="route-path">
                <span className="chan-chip" title={channelName(r.source_channel_id)}>{channelName(r.source_channel_id)}</span>
                <span className="route-arrow" aria-label="forwards to">-&gt;</span>
                <span className="chan-chip" title={channelName(r.destination_channel_id)}>{channelName(r.destination_channel_id)}</span>
                {crossGuild && <span className="route-xguild" title="Forwards to another server">another server</span>}
              </div>
            )}
            <div className="route-card__foot">
              <span className="route-count">{fmt(r.forwarded)}</span>
              <span className="route-count-label">forwarded</span>
              {share > 0 && <span className="route-share">{share}%</span>}
            </div>
          </>
        );

        // A deleted rule has no editor to open, so it stays a plain card. A live one
        // links to its editor - the question "why is this route quiet" is answered there.
        return r.deleted ? (
          <div
            key={r.rule_id}
            className="route-card route-card--muted"
            style={{ "--share": `${share}%` } as CSSProperties}
          >
            {card}
          </div>
        ) : (
          <Link
            key={r.rule_id}
            to={`/settings/guilds/${guildId}/rules/${r.rule_id}`}
            className={`route-card${r.is_active ? "" : " route-card--muted"}`}
            style={{ "--share": `${share}%`, textDecoration: "none", color: "inherit" } as CSSProperties}
          >
            {card}
          </Link>
        );
      })}
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
      .catch((e) => { if (!cancelled) setError(formatError(e)); })
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

  const sourceItems: ShareItem[] = useMemo(
    () => (stats?.per_source ?? []).map((s: PerSourceStat) => ({
      key: s.channel_id,
      name: channelName(s.channel_id),
      value: s.forwarded,
    })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stats, channels],
  );

  const destinationItems: ShareItem[] = useMemo(
    () => (stats?.per_destination ?? []).map((s) => ({
      key: s.channel_id,
      name: channelName(s.channel_id),
      value: s.forwarded,
    })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stats, channels],
  );

  /** Forwarded totals per day of the week, summed over the window. */
  const weekday = useMemo(() => {
    const totals = new Array(7).fill(0) as number[];
    for (const day of stats?.daily ?? []) totals[weekdayOf(day.date)] += day.forwarded;
    return totals;
  }, [stats]);

  /**
   * Routes that stay inside this server versus routes that leave it.
   *
   * Computed here rather than server-side: per_rule already carries the destination
   * server for every rule with traffic, so the split is arithmetic on data already
   * fetched. A deleted rule has no destination server recorded any more and is counted
   * as neither, which is why the two figures can sum to less than the total.
   */
  const split = useMemo(() => {
    let internal = 0;
    let external = 0;
    let unknown = 0;
    for (const r of stats?.per_rule ?? []) {
      if (r.deleted || !r.destination_guild_id) unknown += r.forwarded;
      else if (r.destination_guild_id === guildId) internal += r.forwarded;
      else external += r.forwarded;
    }
    return { internal, external, unknown };
  }, [stats, guildId]);

  if (!guildId) return null;

  const t = stats?.totals;
  const hasActivity = !!t && (t.forwarded > 0 || t.blocked > 0);
  const hasBlocked = !!stats && stats.blocked_by_reason.length > 0;
  const weekdayTotal = weekday.reduce((a, b) => a + b, 0);
  const busiestDay = weekdayTotal > 0 ? weekday.indexOf(Math.max(...weekday)) : null;

  const signals: Signal[] = !t ? [] : [
    { key: "lifetime", value: formatCount(t.lifetime), label: "Forwarded all time" },
    { key: "window", value: formatCount(t.forwarded), label: `Forwarded - ${days} days` },
    {
      key: "today",
      value: formatCount(t.today_forwarded),
      label: `Today - of ${formatCount(stats!.daily_limit)}`,
    },
    { key: "blocked", value: formatCount(t.blocked), label: `Blocked - ${days} days` },
  ];

  return (
    <div className="page">
      <div style={{ paddingTop: 16 }}>
        <AdminNav guildId={guildId} />
      </div>

      <div className="page-header">
        <div>
          <h1 style={{ marginTop: 4 }}>Forwarding analytics</h1>
        </div>
        <div className="seg" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r} className={r === days ? "active" : ""} onClick={() => setDays(r)}>
              {r}d
            </button>
          ))}
        </div>
      </div>

      <div className="ov-command">
        <span className="ov-muted">
          Last {days} days
          {stats && (
            <>
              {" - updated "}
              {new Date(stats.generated_at).toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </>
          )}
        </span>
        <SignalStrip signals={signals} />
      </div>

      {error && <Alert kind="danger">{error}</Alert>}

      {loading && !stats && (
        <div className="ov-grid" role="status" aria-busy="true">
          <div className="skeleton-card s8" />
          <div className="skeleton-card s4" />
          <div className="skeleton-card s6" />
          <div className="skeleton-card s6" />
          <span className="visually-hidden">Loading analytics</span>
        </div>
      )}

      {stats && t && !hasActivity && (
        <div className="ov-grid">
          <Tile span={12} title="Nothing to chart yet" quiet>
            <p className="ov-body">
              No messages have been forwarded or blocked in the last {days} days, so there
              is nothing to draw. Once your rules start copying messages, the charts appear
              here on their own.
            </p>
            <div className="admin-actions">
              <Link className="btn btn-secondary" to={`/settings/guilds/${guildId}/rules`}>
                Check your rules
              </Link>
            </div>
          </Tile>
        </div>
      )}

      {stats && t && hasActivity && (
        <div className="ov-grid">
          <Tile
            span={8}
            title={`Forwarded over time, ${days} days`}
            live
            chips={
              t.blocked > 0 ? (
                <span className="ov-chip ov-chip--warn">{formatCount(t.blocked)} blocked</span>
              ) : (
                <span className="ov-chip ov-chip--good">Nothing blocked</span>
              )
            }
          >
            <div className="ov-statrow">
              <Stat small value={fmt(t.daily_average)} label="Average per day" />
              <Stat
                small
                value={t.peak ? fmt(t.peak.forwarded) : "0"}
                label={t.peak ? `Best day, ${shortDate(t.peak.date)}` : "Best day"}
              />
              <Stat small value={formatCount(t.active_rules)} label="Active rules" />
            </div>
            <TrendChart daily={stats.daily} />
          </Tile>

          <Tile span={4} title="Today against the cap">
            <Stat
              value={formatCount(t.today_forwarded)}
              sub={`/${formatCount(stats.daily_limit)}`}
              label="Forwarded today"
            />
            <div className="ov-meter">
              <div
                className="ov-meter__fill"
                style={{
                  width: `${Math.min(100, (t.today_forwarded / Math.max(1, stats.daily_limit)) * 100)}%`,
                }}
              />
            </div>
            <p className="ov-muted">
              {t.today_forwarded >= stats.daily_limit
                ? "The cap has been reached. Nothing more is forwarded until midnight UTC."
                : `${Math.round((t.today_forwarded / Math.max(1, stats.daily_limit)) * 100)}% of today's allowance used.`}
            </p>
            <Divider />
            <KeyValue k="Plan" v={stats.is_premium ? "Premium" : "Free"} />
            <KeyValue k="All time" v={formatCount(t.lifetime)} />
            <Link className="ov-link" to={`/settings/guilds/${guildId}/premium`}>
              Plan details
            </Link>
          </Tile>

          <Tile span={7} title="Busiest hours">
            <HoursChart hourly={stats.hourly} />
          </Tile>

          <Tile span={5} title="Busiest days of the week">
            {weekdayTotal === 0 ? (
              <p className="ov-muted">
                Nothing forwarded in this period, so there is no busiest day yet.
              </p>
            ) : (
              <>
                <ShareBars
                  items={WEEKDAYS.map((label, i) => ({
                    key: label,
                    name: label,
                    value: weekday[i],
                    muted: i !== busiestDay,
                  }))}
                />
                <p className="ov-muted">
                  Summed over the whole {days}-day window, by UTC calendar day.
                </p>
              </>
            )}
          </Tile>

          {sourceItems.length > 0 && (
            <Tile span={6} title="Where messages come from">
              <ShareBars items={sourceItems} />
              <p className="ov-muted">
                The channels your rules are watching, by how much each one produced.
              </p>
            </Tile>
          )}

          {destinationItems.length > 0 && (
            <Tile span={6} title="Where messages land">
              <ShareBars items={destinationItems} />
              <p className="ov-muted">
                A busy source that fans out to several destinations looks like one bar on
                the left and several here - this is the side that shows which channels are
                actually filling up.
              </p>
            </Tile>
          )}

          <Tile span={6} title="Fan-out">
            <div className="ov-statrow">
              <Stat
                value={t.fanout_ratio ? `${t.fanout_ratio}x` : "-"}
                label="Copies per original message"
              />
              <Stat small value={formatCount(t.unique_sources)} label="Original messages" />
              <Stat small value={formatCount(t.forwarded)} label="Copies made" />
            </div>
            <Divider />
            <p className="ov-body">
              {t.unique_sources === 0
                ? "No original messages have been copied in this period."
                : t.fanout_ratio > 1.05
                  ? `${formatCount(t.unique_sources)} original message${t.unique_sources === 1 ? "" : "s"} produced ${formatCount(t.forwarded)} cop${t.forwarded === 1 ? "y" : "ies"}, because more than one rule watches the same channel. That is why the forwarded total can be larger than the number of messages people actually posted.`
                  : "Each original message produced about one copy, so no channel is being watched by more than one rule."}
            </p>
            <Divider />
            <span className="ov-card__title">Staying here, or leaving</span>
            <KeyValue k="Copied within this server" v={formatCount(split.internal)} />
            <KeyValue k="Copied into another server" v={formatCount(split.external)} />
            {split.unknown > 0 && (
              <KeyValue k="From rules since deleted" v={formatCount(split.unknown)} />
            )}
            <p className="ov-muted">
              {split.external === 0
                ? "Nothing leaves this server. Every copy stays in a channel here."
                : `${Math.round((split.external / Math.max(1, split.internal + split.external)) * 100)}% of copies are posted into a different server, where different people can read them.`}
            </p>
          </Tile>

          <Tile
            span={6}
            title="Why messages were blocked"
            chips={
              !hasBlocked ? <span className="ov-chip ov-chip--good">Nothing blocked</span> : null
            }
          >
            {!hasBlocked ? (
              <p className="ov-body">
                Every message a rule matched in the last {days} days went through.
              </p>
            ) : (
              <div className="share-list">
                {stats.blocked_by_reason.map((b) => {
                  const pct = t.blocked > 0 ? (b.count / t.blocked) * 100 : 0;
                  return (
                    <div key={b.reason} className="reason-row">
                      <div className="reason-row__head">
                        <span className="reason-row__dot" style={{ background: reasonColor(b.reason) }} />
                        <span className="reason-row__name">{reasonLabel(b.reason)}</span>
                        <span className="reason-row__val">{fmt(b.count)}</span>
                      </div>
                      {reasonHelp(b.reason) && (
                        <div className="reason-row__desc">{reasonHelp(b.reason)}</div>
                      )}
                      <div className="share-track">
                        <div className="share-fill" style={{ width: `${pct}%`, background: reasonColor(b.reason) }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Tile>

          {stats.per_rule.length > 0 && (
            <Tile
              span={12}
              title="Which rules carried the traffic"
              action={
                <Link className="ov-link" to={`/settings/guilds/${guildId}/rules`}>
                  Manage rules
                </Link>
              }
            >
              <RouteCards
                rules={stats.per_rule}
                total={t.forwarded}
                guildId={guildId}
                channelName={channelName}
              />
              <p className="ov-muted">
                Pick a rule to open its settings. A rule listed as no longer existing still
                has messages in the history it forwarded before it was deleted.
              </p>
            </Tile>
          )}
        </div>
      )}
    </div>
  );
}
