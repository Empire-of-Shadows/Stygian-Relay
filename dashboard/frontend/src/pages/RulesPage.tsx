import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Channel, GuildOverview, Rule } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import ConfirmDialog from "../components/ConfirmDialog";
import SignalStrip, { type Signal } from "../_engine/components/overview/SignalStrip";
import { KeyValue, Rule as Divider, Tile } from "../_engine/components/overview/Tile";
import { formatCount, formatDate, formatRelative } from "../_engine/format";

/*
 * Forwarding rules.
 *
 * This replaced a five-column table of raw snowflakes with Edit / Pause / Delete
 * buttons and a browser confirm() on the delete. The table said nothing about whether a
 * rule was doing anything: two identical-looking rows could be one carrying a thousand
 * messages a month and one whose destination channel was deleted in March.
 *
 * A rule is a ROUTE, so it is drawn as one - the two channels it connects, whether it
 * leaves the server, how much it carried, and a live dot. The figures come from the
 * overview endpoint, which already computes per-rule 30-day counts for the home page;
 * the rules list itself carries no counts.
 *
 * Every count here is real or absent. A rule the overview has no figure for renders
 * "not counted" rather than a zero that would read as "carried nothing".
 */

export function RulesPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [overview, setOverview] = useState<GuildOverview | null>(null);
  const [channels, setChannels] = useState<Map<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Rule | null>(null);

  useEffect(() => {
    if (!guildId) return;
    let cancelled = false;
    api.rules(guildId)
      .then((r) => {
        if (cancelled) return;
        setRules(r.rules);
      })
      .catch((e) => { if (!cancelled) setError(formatError(e)); });

    // Both are enrichment. A failure leaves the rules list rendering with no figures and
    // raw ids rather than taking the page down.
    api.overview(guildId).then((o) => { if (!cancelled) setOverview(o); }).catch(() => {});
    api.channels(guildId)
      .then((list: Channel[]) => {
        if (!cancelled) setChannels(new Map(list.map((c) => [c.id, c.name])));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [guildId]);

  /** rule_id -> messages carried in 30 days. Absent means "no figure", not zero. */
  const carried = useMemo(() => {
    const map = new Map<string, number>();
    for (const route of overview?.rules?.routes ?? []) {
      map.set(route.rule_id, route.forwarded_30d);
    }
    return map;
  }, [overview]);

  const channelName = (id: string | number): string => {
    const key = String(id ?? "");
    if (!key) return "unknown channel";
    const name = channels.get(key);
    return name ? `#${name}` : `#${key}`;
  };

  async function handleToggle(rule: Rule) {
    if (!guildId || toggling) return;
    setToggling(rule.rule_id);
    setError(null);
    try {
      const res = await api.toggleRule(guildId, rule.rule_id);
      setRules((prev) =>
        prev?.map((r) => r.rule_id === rule.rule_id ? { ...r, is_active: res.is_active } : r) ?? null
      );
    } catch (e) {
      setError(formatError(e));
    } finally {
      setToggling(null);
    }
  }

  async function handleDelete(rule: Rule) {
    if (!guildId) return;
    setPendingDelete(null);
    setDeleting(rule.rule_id);
    setError(null);
    try {
      await api.deleteRule(guildId, rule.rule_id);
      setRules((prev) => prev?.filter((r) => r.rule_id !== rule.rule_id) ?? null);
    } catch (e) {
      setError(formatError(e));
    } finally {
      setDeleting(null);
    }
  }

  if (!guildId) return null;

  const total = rules?.length ?? 0;
  const active = rules?.filter((r) => r.is_active).length ?? 0;
  const paused = total - active;
  const crossServer =
    rules?.filter((r) => String(r.destination_guild_id ?? "") !== "" &&
      String(r.destination_guild_id) !== guildId).length ?? 0;
  // Only an ACTIVE rule can be idle in a way that matters - a paused rule carrying
  // nothing is doing exactly what it was told to.
  const idle = rules
    ? rules.filter((r) => r.is_active && carried.get(r.rule_id) === 0).length
    : 0;
  const maxRules = overview?.rules?.max_rules ?? null;
  const plan = overview?.plan ?? null;
  const atCap = maxRules !== null && active >= maxRules;

  const signals: Signal[] = rules === null ? [] : [
    {
      key: "active",
      value: formatCount(active),
      label: maxRules !== null ? `Active - of ${maxRules}` : "Active rules",
    },
    { key: "paused", value: formatCount(paused), label: "Paused" },
    { key: "cross", value: formatCount(crossServer), label: "To another server" },
    {
      key: "idle",
      value: overview?.rules ? formatCount(idle) : "-",
      label: overview?.rules ? "Active but carried nothing" : "Idle - not counted",
    },
  ];

  return (
    <div className="page">
      <div className="page-header" style={{ paddingTop: 16 }}>
        <div>
          <Link to={`/me?guild=${guildId}`} className="muted" style={{ fontSize: 13 }}>
            &larr; Server overview
          </Link>
          <h1 style={{ marginTop: 4 }}>Forwarding rules</h1>
        </div>
        <Link to={`/guilds/${guildId}/rules/new`} className="btn btn-primary">
          New rule
        </Link>
      </div>

      <div className="ov-command">
        <span className="ov-muted" style={{ maxWidth: "46ch" }}>
          Each rule is one route: a channel to watch, and a channel to copy into.
        </span>
        <SignalStrip signals={signals} />
      </div>

      {error && <Alert kind="danger">{error}</Alert>}

      {rules === null && !error && (
        <div className="ov-grid" role="status" aria-busy="true">
          <div className="skeleton-card s12" />
          <span className="visually-hidden">Loading rules</span>
        </div>
      )}

      {rules !== null && rules.length === 0 && (
        <div className="ov-grid">
          <Tile span={12} title="No rules yet" quiet>
            <p className="ov-body">
              Nothing is being forwarded in this server, because no rule tells the bot what
              to copy where. A rule takes two channels and copies every message from the
              first into the second.
            </p>
            <div className="admin-actions">
              <Link to={`/guilds/${guildId}/rules/new`} className="btn btn-primary">
                Create your first rule
              </Link>
            </div>
          </Tile>
        </div>
      )}

      {rules !== null && rules.length > 0 && (
        <div className="ov-grid">
          <Tile
            span={8}
            title={`Your routes, ${total} rule${total === 1 ? "" : "s"}`}
            chips={
              atCap ? (
                <span className="ov-chip ov-chip--warn">Rule limit reached</span>
              ) : active > 0 ? (
                <span className="ov-chip ov-chip--good">{active} running</span>
              ) : (
                <span className="ov-chip ov-chip--warn">None active</span>
              )
            }
          >
            <div className="route-grid">
              {rules.map((rule) => (
                <RuleCard
                  key={rule.rule_id}
                  rule={rule}
                  guildId={guildId}
                  carried={carried.has(rule.rule_id) ? carried.get(rule.rule_id)! : null}
                  hasCounts={overview?.rules != null}
                  channelName={channelName}
                  busyToggle={toggling === rule.rule_id}
                  busyDelete={deleting === rule.rule_id}
                  onToggle={() => handleToggle(rule)}
                  onDelete={() => setPendingDelete(rule)}
                />
              ))}
            </div>
          </Tile>

          <Tile span={4} title="What your plan allows">
            {plan ? (
              <>
                <KeyValue
                  k="Rules in use"
                  v={maxRules !== null ? `${active} of ${maxRules}` : String(active)}
                />
                <KeyValue k="Messages per day" v={formatCount(plan.daily_limit)} />
                <KeyValue k="Plan" v={plan.is_premium ? "Premium" : "Free"} />
                <Divider />
                <p className="ov-muted">
                  {atCap
                    ? "You are at the limit. Pause a rule you are not using, or upgrade, before adding another."
                    : "Only active rules count towards the limit. A paused rule keeps its settings and costs nothing."}
                </p>
                <div className="admin-actions">
                  <Link className="btn btn-secondary" to={`/guilds/${guildId}/premium`}>
                    Plan details
                  </Link>
                </div>
              </>
            ) : (
              <p className="ov-muted">
                Your plan's limits could not be loaded right now. Refresh to try again.
              </p>
            )}
          </Tile>
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete "${pendingDelete?.rule_name ?? ""}"?`}
        message={
          "This removes the rule for good. Messages it has already forwarded stay where " +
          "they are - deleting the rule only stops it copying anything from now on. If you " +
          "only want to stop it for a while, pause it instead."
        }
        confirmLabel="Delete rule"
        destructive
        onConfirm={() => pendingDelete && handleDelete(pendingDelete)}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

/**
 * One rule as a route card.
 *
 * Adapted from the analytics page's RouteCards, which had no way to act on a rule and no
 * idea when one was created. The share bar at the foot of the analytics version is
 * dropped here: a rule's share of total traffic is an analytics question, and this page
 * is about the setup.
 */
function RuleCard({
  rule,
  guildId,
  carried,
  hasCounts,
  channelName,
  busyToggle,
  busyDelete,
  onToggle,
  onDelete,
}: {
  rule: Rule;
  guildId: string;
  /** Null when the overview could not be loaded - NOT the same as zero. */
  carried: number | null;
  hasCounts: boolean;
  channelName: (id: string | number) => string;
  busyToggle: boolean;
  busyDelete: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const crossServer =
    String(rule.destination_guild_id ?? "") !== "" &&
    String(rule.destination_guild_id) !== guildId;

  return (
    <div
      className={`route-card${rule.is_active ? "" : " route-card--muted"}`}
      style={{ "--share": "0%" } as CSSProperties}
    >
      <div className="route-card__top">
        <span className="route-name" title={rule.rule_name}>
          {rule.rule_name}
        </span>
        <span
          className={`route-status route-status--${rule.is_active ? "active" : "paused"}`}
          title={rule.is_active ? "Active" : "Paused"}
          aria-label={rule.is_active ? "Active" : "Paused"}
        />
      </div>

      <div className="route-path">
        <span className="chan-chip" title={channelName(rule.source_channel_id)}>
          {channelName(rule.source_channel_id)}
        </span>
        <span className="route-arrow" aria-hidden="true">-&gt;</span>
        <span className="chan-chip" title={channelName(rule.destination_channel_id)}>
          {crossServer ? "a channel elsewhere" : channelName(rule.destination_channel_id)}
        </span>
        {crossServer && (
          <span className="route-xguild" title="Copies into another server">
            another server
          </span>
        )}
      </div>

      <div>
        <KeyValue
          k="Carried, 30 days"
          v={
            hasCounts
              ? carried === null
                ? "not counted"
                : `${formatCount(carried)} message${carried === 1 ? "" : "s"}`
              : "not counted"
          }
        />
        <KeyValue
          k="Created"
          v={rule.created_at ? formatDate(rule.created_at) : "unknown"}
        />
        <KeyValue
          k="Last edited"
          v={rule.updated_at ? formatRelative(rule.updated_at) : "never"}
        />
      </div>

      <div className="admin-actions" style={{ marginTop: "auto" }}>
        <Link to={`/guilds/${guildId}/rules/${rule.rule_id}`} className="btn btn-secondary small">
          Edit
        </Link>
        <button
          type="button"
          className={`btn small ${rule.is_active ? "ghost" : "btn-success"}`}
          onClick={onToggle}
          disabled={busyToggle}
        >
          {busyToggle ? "Working..." : rule.is_active ? "Pause" : "Resume"}
        </button>
        <button
          type="button"
          className="btn btn-danger small"
          onClick={onDelete}
          disabled={busyDelete}
        >
          {busyDelete ? "Deleting..." : "Delete"}
        </button>
      </div>
    </div>
  );
}
