import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, UnauthorizedError } from "../api/client";
import type { Channel, Guild, GuildOverview, Me } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import RelayOverview from "../components/overview/RelayOverview";
import ServerPicker, { pickerMeta } from "../_engine/components/overview/ServerPicker";
import SignalStrip, { type Signal } from "../_engine/components/overview/SignalStrip";
import { formatCount } from "../_engine/format";

/**
 * The relay dashboard home.
 *
 * One server at a time, chosen with the shared server picker and kept in the
 * URL as `?guild=`, so the page is shareable and survives a reload. The command
 * row carries the figures that are only figures; everything with something to
 * say lives in a tile below.
 *
 * This replaced a grid of server cards that led to a hub of five link cards.
 * The cards said nothing about whether the relay was actually forwarding, which
 * is the only question an admin opens this page with.
 */
export function DashboardPage({ me }: { me: Me | null }) {
  const [guilds, setGuilds] = useState<Guild[] | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [searchParams, setSearchParams] = useSearchParams();
  const selectedGuildId = searchParams.get("guild");

  const [overview, setOverview] = useState<GuildOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [channels, setChannels] = useState<Map<string, string>>(new Map());

  // The ?guild= the page was opened with. A shared link always beats the
  // default-to-your-first-server behaviour below.
  const openedWith = useRef<string | null>(searchParams.get("guild"));

  const selectGuild = (guildId: string | null, replace: boolean) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (guildId) next.set("guild", guildId);
        else next.delete("guild");
        return next;
      },
      { replace },
    );
  };

  useEffect(() => {
    let alive = true;
    api.guilds()
      .then((list) => {
        if (!alive) return;
        setGuilds(list);
        if (!openedWith.current) {
          const first = list.find((g) => g.bot_in_guild && !g.setup_required) ?? list[0];
          if (first) selectGuild(first.id, true);
        }
      })
      .catch((e) => {
        if (!alive) return;
        setError(
          e instanceof UnauthorizedError
            ? "Your session has expired."
            : formatError(e, "Failed to load servers."),
        );
      });
    api.botInviteUrl()
      .then((r) => { if (alive) setInviteUrl(r.url); })
      .catch(() => {});
    return () => { alive = false; };
    // Runs once: the initial guild comes from the URL, captured above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedGuild = useMemo(
    () => (guilds ?? []).find((g) => g.id === selectedGuildId) ?? null,
    [guilds, selectedGuildId],
  );

  const canShowOverview =
    selectedGuild !== null && selectedGuild.bot_in_guild && !selectedGuild.setup_required;

  useEffect(() => {
    if (!canShowOverview || !selectedGuild) {
      setOverview(null);
      setOverviewError(null);
      return;
    }
    let cancelled = false;
    setOverviewLoading(true);
    setOverviewError(null);
    api.overview(selectedGuild.id)
      .then((data) => { if (!cancelled) setOverview(data); })
      .catch((e) => {
        if (cancelled) return;
        setOverview(null);
        if (e instanceof UnauthorizedError) return;
        setOverviewError(formatError(e, "Could not load this server."));
      })
      .finally(() => { if (!cancelled) setOverviewLoading(false); });
    return () => { cancelled = true; };
  }, [canShowOverview, selectedGuild]);

  // Channel names are best-effort: the overview still renders with raw ids if
  // the picker list cannot be fetched.
  useEffect(() => {
    if (!canShowOverview || !selectedGuild) {
      setChannels(new Map());
      return;
    }
    let cancelled = false;
    api.channels(selectedGuild.id)
      .then((list: Channel[]) => {
        if (cancelled) return;
        setChannels(new Map(list.map((c) => [c.id, c.name])));
      })
      .catch(() => { /* fall back to raw ids */ });
    return () => { cancelled = true; };
  }, [canShowOverview, selectedGuild]);

  const channelName = (id: string): string => {
    if (!id) return "unknown channel";
    const name = channels.get(id);
    return name ? `#${name}` : `#${id}`;
  };

  const displayName = me?.global_name || me?.username || "there";

  if (error) {
    return (
      <div className="page">
        <div style={{ paddingTop: 24 }}>
          <Alert kind="danger">{error}</Alert>
        </div>
      </div>
    );
  }

  if (guilds === null) {
    return (
      <div className="page">
        <div className="page-skeleton" role="status" aria-busy="true">
          <div className="skeleton-bar skeleton-bar--lg" />
          <div className="skeleton-grid">
            <div className="skeleton-card" />
            <div className="skeleton-card" />
            <div className="skeleton-card" />
            <div className="skeleton-card" />
          </div>
          <span className="visually-hidden">Loading your servers</span>
        </div>
      </div>
    );
  }

  if (guilds.length === 0) {
    return (
      <div className="page">
        <div className="ov-grid">
          <section className="ov-card ov-card--quiet s12">
            <div className="ov-card__head">
              <span className="ov-card__title">No servers</span>
            </div>
            <p className="ov-body">
              Hey, {displayName}. No servers to show yet - the relay appears here once you have
              Manage Server permission in a server it has been added to.
            </p>
            {inviteUrl && (
              <div className="admin-actions">
                <a
                  className="btn btn-primary"
                  href={inviteUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Add Stygian Relay to a server
                </a>
              </div>
            )}
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="ov-command">
        <ServerPicker
          guilds={guilds}
          selectedGuildId={selectedGuildId}
          onSelect={(id) => selectGuild(id, true)}
          meta={pickerMeta(selectedGuild, guilds.length, "Stygian Relay")}
        />
        <SignalStrip signals={signalsFor(overview)} />
      </div>

      {selectedGuild === null && (
        <div className="ov-grid">
          <section className="ov-card ov-card--quiet s12">
            <div className="ov-card__head">
              <span className="ov-card__title">Pick a server</span>
            </div>
            <p className="ov-body">
              Choose a server above to see what its relay is forwarding.
            </p>
          </section>
        </div>
      )}

      {selectedGuild?.setup_required && (
        <div className="ov-grid">
          <section className="ov-card ov-card--quiet s12">
            <div className="ov-card__head">
              <span className="ov-card__title">Not added yet</span>
              <span className="ov-chip ov-chip--warn">Bot missing</span>
            </div>
            <p className="ov-body">
              Stygian Relay is not in this server yet. Add it with the link below, then come back
              here.
            </p>
            <div className="admin-actions">
              {inviteUrl ? (
                <a
                  className="btn btn-primary"
                  href={`${inviteUrl}&guild_id=${selectedGuild.id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Add Stygian Relay
                </a>
              ) : (
                <span className="guild-invite-hint">Bot not in this server yet.</span>
              )}
            </div>
          </section>
        </div>
      )}

      {canShowOverview && overviewLoading && !overview && (
        <div className="ov-grid" role="status" aria-busy="true">
          <div className="skeleton-card s12" />
          <div className="skeleton-card s7" />
          <div className="skeleton-card s5" />
          <div className="skeleton-card s6" />
          <div className="skeleton-card s6" />
          <span className="visually-hidden">Loading this server</span>
        </div>
      )}

      {canShowOverview && overviewError && (
        <div className="ov-grid">
          <section className="ov-card ov-card--quiet s12">
            <div className="ov-card__head">
              <span className="ov-card__title">Not loaded</span>
            </div>
            <p className="ov-body" role="alert">{overviewError}</p>
          </section>
        </div>
      )}

      {canShowOverview && overview && (
        <RelayOverview overview={overview} channelName={channelName} />
      )}

      {canShowOverview && overview && (
        <p className="ov-muted" style={{ paddingBottom: 32 }}>
          Looking for something else?{" "}
          <Link className="ov-link" to={`/guilds/${overview.guild_id}/stats`}>Analytics</Link>
          {" - "}
          <Link className="ov-link" to={`/guilds/${overview.guild_id}/rules`}>Rules</Link>
          {" - "}
          <Link className="ov-link" to={`/guilds/${overview.guild_id}/config`}>Settings</Link>
          {" - "}
          <Link className="ov-link" to={`/guilds/${overview.guild_id}/premium`}>Premium</Link>
          {" - "}
          <Link className="ov-link" to={`/guilds/${overview.guild_id}/audit-log`}>Audit log</Link>
        </p>
      )}
    </div>
  );
}

/* ── The command-row numbers ───────────────────────────────────────── */

function signalsFor(overview: GuildOverview | null): Signal[] {
  if (!overview) return [];
  const traffic = overview.traffic;
  const rules = overview.rules;

  return [
    {
      key: "forwarded",
      value: traffic ? formatCount(traffic.forwarded_30d) : "-",
      label: "Forwarded - 30 days",
    },
    {
      key: "today",
      value: traffic ? formatCount(traffic.today_forwarded) : "-",
      label: traffic ? `Today - of ${formatCount(traffic.daily_limit)}` : "Today",
    },
    {
      key: "rules",
      value: rules ? formatCount(rules.active) : "-",
      label: rules ? `Active rules - of ${rules.max_rules}` : "Active rules",
    },
    {
      key: "blocked",
      value: traffic ? formatCount(traffic.blocked_30d) : "-",
      label: "Blocked - 30 days",
    },
  ];
}
