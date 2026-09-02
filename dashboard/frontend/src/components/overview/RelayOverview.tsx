import { Link } from "react-router-dom";
import type {
  ConfigOverview,
  DeliveryOverview,
  GuildOverview,
  PlanOverview,
  RulesOverview,
  TrafficOverview,
} from "../../api/types";
import AreaChart from "../../_engine/components/charts/AreaChart";
import BarChart from "../../_engine/components/charts/BarChart";
import FeatureStrip, { featureCounts } from "../../_engine/components/overview/FeatureStrip";
import {
  KeyValue,
  Rule,
  SectionUnavailable,
  Stat,
  Tile,
} from "../../_engine/components/overview/Tile";
import {
  formatCount,
  formatDate,
  formatDayLabel,
  formatRelative,
} from "../../_engine/format";
import { planLabel, reasonHelp, reasonLabel } from "./format";

/**
 * The relay admin home.
 *
 * The question this page answers, in order: is anything being forwarded, how
 * close is the server to its daily cap, which routes are carrying the traffic,
 * what got blocked, how is the server configured, and what does the plan allow.
 *
 * Every section of the payload can be null on its own, so every reader here has
 * a null branch that says so in words rather than rendering a zero.
 */
export default function RelayOverview({
  overview,
  channelName,
}: {
  overview: GuildOverview;
  /** Resolves a channel id to "#name", falling back to the raw id. */
  channelName: (id: string) => string;
}) {
  const guildId = overview.guild_id;
  return (
    <div className="ov-grid">
      <IsItWorking overview={overview} />
      <ForwardingTrend guildId={guildId} traffic={overview.traffic} />
      <Today traffic={overview.traffic} plan={overview.plan} />
      <Routes guildId={guildId} rules={overview.rules} channelName={channelName} />
      <Blocked guildId={guildId} delivery={overview.delivery} />
      <ServerSetup guildId={guildId} config={overview.config} channelName={channelName} />
      <Plan guildId={guildId} plan={overview.plan} rules={overview.rules} />
    </div>
  );
}

/** A deep link into one area of a server's settings page, which is where the engine's
 *  FeatureStrip sends "this feature is not set up yet". The rail reads the area out of
 *  `?s=`, so the link opens on the right one rather than on the default. */
function settingsHrefFor(guildId: string) {
  return (settingsKey: string) =>
    `/settings/guilds/${guildId}/settings?s=${encodeURIComponent(settingsKey)}`;
}

/* ── Is it working ─────────────────────────────────────────────────── */

function IsItWorking({ overview }: { overview: GuildOverview }) {
  const guildId = overview.guild_id;
  const counts = featureCounts(overview.features);
  return (
    <Tile
      span={12}
      title="Is it working"
      chips={
        <>
          {counts.on > 0 && <span className="ov-chip ov-chip--good">{counts.on} running</span>}
          {counts.needsSetup > 0 && (
            <span className="ov-chip ov-chip--warn">{counts.needsSetup} need setting up</span>
          )}
          {counts.off > 0 && <span className="ov-chip">{counts.off} off</span>}
        </>
      }
      action={
        <>
          <Link className="ov-link" to={`/settings/guilds/${guildId}/settings`}>
            Change settings
          </Link>
          <Link className="ov-link" to={`/settings/guilds/${guildId}/audit-log`}>
            Change history
          </Link>
        </>
      }
    >
      <FeatureStrip
        guildId={guildId}
        features={overview.features}
        settingsHref={settingsHrefFor(guildId)}
      />
    </Tile>
  );
}

/* ── Forwarded over time ───────────────────────────────────────────── */

function ForwardingTrend({
  guildId,
  traffic,
}: {
  guildId: string;
  traffic: TrafficOverview | null;
}) {
  if (!traffic) {
    return (
      <Tile span={7} title="Forwarded over time">
        <SectionUnavailable what="Forwarding history" />
      </Tile>
    );
  }

  const points = traffic.daily.map((day) => ({
    label: formatDayLabel(day.date),
    value: day.forwarded,
  }));

  return (
    <Tile
      span={7}
      title={`Forwarded over time, ${traffic.days} days`}
      chips={
        traffic.blocked_30d > 0 ? (
          <span className="ov-chip ov-chip--warn">
            {formatCount(traffic.blocked_30d)} blocked
          </span>
        ) : null
      }
      action={
        <Link className="ov-link" to={`/settings/guilds/${guildId}/stats`}>
          Full analytics
        </Link>
      }
    >
      <div className="ov-statrow">
        <Stat small value={formatCount(traffic.forwarded_30d)} label="Forwarded" />
        <Stat small value={traffic.avg_per_active_day.toFixed(1)} label="Per busy day" />
        {/* No "/30" here on purpose. The window is bounded by a timestamp, so
            it spans 31 calendar days - today plus a partial day thirty days
            back - exactly as the analytics page does. A "24/30" would be a
            precision the number does not have. */}
        <Stat small value={traffic.days_active} label="Days with traffic" />
        <Stat
          small
          value={traffic.peak ? formatCount(traffic.peak.forwarded) : "0"}
          label={traffic.peak ? `Best day, ${formatDayLabel(traffic.peak.date)}` : "Best day"}
        />
      </div>
      <AreaChart
        points={points}
        ariaLabel={`Messages forwarded on each of the last ${traffic.days} days`}
        unit="messages"
        emptyLabel="Nothing has been forwarded yet, so there is no trend to draw."
      />
      {/* Blocked as a COMPANION rather than a second line on the same axes. A day with
          three blocked messages next to three thousand forwarded ones would be an
          invisible line on a shared scale, and giving it its own axis would make the
          same three look like a crisis. Its own small chart, on its own scale, with the
          count written above it, is the honest way to show both. Drawn only when there
          is something to draw. */}
      {traffic.blocked_30d > 0 && (
        <>
          <Rule />
          <span className="ov-card__title">Blocked over the same days</span>
          <BarChart
            groups={traffic.daily.map((day) => formatDayLabel(day.date))}
            series={[{
              key: "blocked",
              label: "Blocked",
              values: traffic.daily.map((day) => day.blocked),
            }]}
            ariaLabel={`Messages blocked on each of the last ${traffic.days} days`}
            unit="messages"
            height={70}
            emptyLabel="Nothing was blocked in this period."
          />
        </>
      )}
      <Rule />
      <p className="ov-muted">
        {formatCount(traffic.lifetime)} forwarded since this server started using the relay.
      </p>
    </Tile>
  );
}

/* ── Today ─────────────────────────────────────────────────────────── */

function Today({
  traffic,
  plan,
}: {
  traffic: TrafficOverview | null;
  plan: PlanOverview | null;
}) {
  if (!traffic) {
    return (
      <Tile span={5} title="Today">
        <SectionUnavailable what="Today's usage" />
      </Tile>
    );
  }

  const limit = Math.max(1, traffic.daily_limit);
  const used = Math.min(100, (traffic.today_forwarded / limit) * 100);
  const atCap = traffic.today_forwarded >= traffic.daily_limit;

  return (
    <Tile
      span={5}
      title="Today"
      live
      chips={
        atCap ? (
          <span className="ov-chip ov-chip--warn">Daily cap reached</span>
        ) : plan?.is_premium ? (
          <span className="ov-chip ov-chip--good">Premium</span>
        ) : null
      }
    >
      <Stat
        value={formatCount(traffic.today_forwarded)}
        sub={`/${formatCount(traffic.daily_limit)}`}
        label="Messages forwarded today"
      />
      <div className="ov-meter">
        <div className="ov-meter__fill" style={{ width: `${used}%` }} />
      </div>
      <p className="ov-muted">
        {atCap
          ? "Nothing more will be forwarded until the cap resets at midnight UTC."
          : `${Math.round(used)}% of today's allowance used.`}
      </p>
      <Rule />
      <KeyValue
        k="Last message forwarded"
        v={traffic.last_forward_at ? formatRelative(traffic.last_forward_at) : "never"}
      />
    </Tile>
  );
}

/* ── Routes ────────────────────────────────────────────────────────── */

function Routes({
  guildId,
  rules,
  channelName,
}: {
  guildId: string;
  rules: RulesOverview | null;
  channelName: (id: string) => string;
}) {
  if (!rules) {
    return (
      <Tile span={7} title="Your routes">
        <SectionUnavailable what="Your forwarding rules" />
      </Tile>
    );
  }

  return (
    <Tile
      span={7}
      title="Your routes"
      chips={
        <span className={rules.active > 0 ? "ov-chip ov-chip--good" : "ov-chip ov-chip--warn"}>
          {rules.active} of {rules.max_rules} active
        </span>
      }
      action={
        <Link className="ov-link" to={`/settings/guilds/${guildId}/rules`}>
          Manage rules
        </Link>
      }
      quiet={rules.total === 0}
    >
      {rules.total === 0 ? (
        <>
          <p className="ov-body">
            No forwarding rules yet. A rule is one route: pick the channel to watch and the
            channel to copy into.
          </p>
          <div className="admin-actions">
            <Link className="btn btn-primary" to={`/settings/guilds/${guildId}/rules/new`}>
              Create your first rule
            </Link>
          </div>
        </>
      ) : (
        <>
          <div className="ov-queue">
            {rules.routes.map((route) => (
              <Link
                key={route.rule_id}
                className="ov-qrow"
                to={`/settings/guilds/${guildId}/rules/${route.rule_id}`}
              >
                <span
                  className="ov-qrow__dot"
                  style={{
                    background: route.is_active ? "var(--eos-success)" : "var(--eos-fg-muted)",
                  }}
                />
                <span className="ov-qrow__txt">
                  {route.rule_name}
                  {" - "}
                  {channelName(route.source_channel_id)}
                  {" to "}
                  {channelName(route.destination_channel_id)}
                  {route.cross_guild ? " (another server)" : ""}
                </span>
                <span className="ov-qrow__meta">
                  {route.is_active ? `${formatCount(route.forwarded_30d)} sent` : "paused"}
                </span>
              </Link>
            ))}
          </div>
          {rules.total > rules.routes.length && (
            <p className="ov-muted">
              and {rules.total - rules.routes.length} more on the rules page
            </p>
          )}
          <Rule />
          <div className="ov-statrow">
            <Stat small value={rules.active} label="Active" />
            <Stat small value={rules.paused} label="Paused" />
            <Stat small value={rules.cross_guild} label="To another server" />
          </div>
          {/* newest_at was computed by the overview service and never rendered. It is
              the answer to "has anybody touched this recently", which is the first thing
              worth knowing about a set of routes that is not behaving. */}
          <KeyValue
            k="Newest rule added"
            v={rules.newest_at ? formatRelative(rules.newest_at) : "unknown"}
          />
          {rules.idle_active > 0 && (
            <p className="ov-muted">
              {rules.idle_active} active {rules.idle_active === 1 ? "rule has" : "rules have"}{" "}
              carried nothing in the last 30 days. That is normal for a quiet channel, and worth a
              look if you expected traffic.
            </p>
          )}
        </>
      )}
    </Tile>
  );
}

/* ── Blocked ───────────────────────────────────────────────────────── */

function Blocked({
  guildId,
  delivery,
}: {
  guildId: string;
  delivery: DeliveryOverview | null;
}) {
  if (!delivery) {
    return (
      <Tile span={5} title="Blocked messages">
        <SectionUnavailable what="Blocked messages" />
      </Tile>
    );
  }

  if (delivery.blocked_30d === 0) {
    return (
      <Tile
        span={5}
        title="Blocked messages"
        chips={<span className="ov-chip ov-chip--good">Nothing blocked</span>}
      >
        <p className="ov-body">
          Every message a rule matched in the last 30 days went through.
        </p>
      </Tile>
    );
  }

  return (
    <Tile
      span={5}
      title="Blocked messages"
      chips={
        delivery.undeliverable_30d > 0 ? (
          <span className="ov-chip ov-chip--bad">Needs a look</span>
        ) : (
          <span className="ov-chip ov-chip--warn">Within limits</span>
        )
      }
      action={
        <Link className="ov-link" to={`/settings/guilds/${guildId}/stats`}>
          Breakdown
        </Link>
      }
    >
      <Stat value={formatCount(delivery.blocked_30d)} label="Not forwarded, 30 days" />
      <div>
        {delivery.reasons.map((reason) => (
          <KeyValue
            key={reason.reason}
            k={reasonLabel(reason.reason)}
            v={formatCount(reason.count)}
          />
        ))}
      </div>
      {delivery.reasons.length > 0 && (
        <p className="ov-muted">
          {reasonHelp(delivery.reasons[0].reason)}
          {/* A "YYYY-MM-DD" key is a calendar day, not an instant - formatDayLabel
              builds it from its parts, where formatDate would read it as UTC
              midnight and render the day before west of Greenwich. */}
          {delivery.reasons[0].last_date
            ? ` Last seen ${formatDayLabel(delivery.reasons[0].last_date)}.`
            : ""}
        </p>
      )}
    </Tile>
  );
}

/* ── How this server is set up ─────────────────────────────────────── */

function ServerSetup({
  guildId,
  config,
  channelName,
}: {
  guildId: string;
  config: ConfigOverview | null;
  channelName: (id: string) => string;
}) {
  if (!config) {
    return (
      <Tile span={6} title="How this server is set up">
        <SectionUnavailable what="This server's settings" />
      </Tile>
    );
  }

  if (!config.has_config) {
    return (
      <Tile
        span={6}
        title="How this server is set up"
        chips={<span className="ov-chip ov-chip--warn">Not set up</span>}
        quiet
      >
        <p className="ov-body">
          The relay has not written any settings for this server yet. Open the settings page to
          get started, or run the setup from the bot's admin panel in Discord.
        </p>
        <div className="admin-actions">
          <Link className="btn btn-primary" to={`/settings/guilds/${guildId}/settings`}>
            Open settings
          </Link>
        </div>
      </Tile>
    );
  }

  const inbound = config.inbound_allowed_guilds.length;

  return (
    <Tile
      span={6}
      title="How this server is set up"
      action={
        <Link className="ov-link" to={`/settings/guilds/${guildId}/settings`}>
          Change settings
        </Link>
      }
    >
      <div>
        <KeyValue k="Forwarding" v={config.forwarding_enabled ? "On" : "Off"} />
        <KeyValue k="Error notices" v={config.notify_on_error ? "On" : "Off"} />
        <KeyValue
          k="Log channel"
          v={config.log_channel_id ? channelName(config.log_channel_id) : "Not set"}
        />
        <KeyValue
          k="Manager role"
          v={config.manager_role_id ? "One role has full access" : "Not set"}
        />
        <KeyValue
          k="Servers allowed to forward in"
          v={inbound === 0 ? "None" : String(inbound)}
        />
      </div>
      <Rule />
      <p className="ov-muted">
        {config.last_change && config.last_change.at
          ? `Last change ${formatRelative(config.last_change.at)} - ${config.last_change.action.replace(/_/g, " ")}.`
          : "No changes recorded yet."}
      </p>
    </Tile>
  );
}

/* ── Plan ──────────────────────────────────────────────────────────── */

function Plan({
  guildId,
  plan,
  rules,
}: {
  guildId: string;
  plan: PlanOverview | null;
  rules: RulesOverview | null;
}) {
  if (!plan) {
    return (
      <Tile span={6} title="Plan">
        <SectionUnavailable what="Your plan" />
      </Tile>
    );
  }

  return (
    <Tile
      span={6}
      title="Plan"
      chips={
        plan.is_premium ? (
          <span className="ov-chip ov-chip--good">{planLabel(plan.tier, plan.tiers)}</span>
        ) : (
          <span className="ov-chip">Free</span>
        )
      }
      action={
        <Link className="ov-link" to={`/settings/guilds/${guildId}/premium`}>
          Plan details
        </Link>
      }
    >
      <div className="ov-statrow">
        <Stat
          small
          value={rules ? rules.active : "-"}
          sub={`/${plan.max_rules}`}
          label="Rules in use"
        />
        <Stat small value={formatCount(plan.daily_limit)} label="Messages per day" />
      </div>
      <Rule />
      <p className="ov-muted">
        {plan.is_premium
          ? plan.expires_at
            ? `Premium runs until ${formatDate(plan.expires_at)}.`
            : "Premium is active with no end date."
          : "Premium raises the rule limit and the daily message allowance. It is managed through Discord and appears here automatically."}
      </p>
    </Tile>
  );
}
