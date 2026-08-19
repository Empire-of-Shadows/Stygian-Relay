import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, UnauthorizedError } from "../api/client";
import type { Channel, Guild, GuildOverview, Me, RelayViewResponse } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import MemberRelayView from "../components/overview/MemberRelayView";
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
 *
 * MEMBER FIRST (owner ruling 2026-08-13). Everyone who signs in gets the "where do my
 * messages go" pane, including an admin - an admin is a member of their own server before
 * they are its administrator, and relay copies their messages too. The server overview
 * sits below it under its own heading, and only for someone who can actually manage the
 * server. Before this, a member with no permissions got a completely empty page, because
 * the guild listing dropped them outright.
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

  const [memberView, setMemberView] = useState<RelayViewResponse | null>(null);
  const [memberViewLoading, setMemberViewLoading] = useState(false);

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
          // Land on a server the user actually manages, since that is the page with the
          // most on it. A member-only list falls through to the first ready server, and
          // then to the first server of any kind, so there is always a selection.
          const first =
            list.find((g) => g.panel_role === "admin" && g.bot_in_guild && !g.setup_required) ??
            list.find((g) => g.bot_in_guild && !g.setup_required) ??
            list[0];
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

  /** Relay is present and set up here - the precondition for anything below. */
  const relayPresent =
    selectedGuild !== null && selectedGuild.bot_in_guild && !selectedGuild.setup_required;

  /** ...and the user can manage it, which is what the server overview needs. Asking for
   *  the overview without this earns a 403, since every guild route is admin-only. */
  const canShowOverview = relayPresent && selectedGuild?.panel_role === "admin";

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

  // The member pane. Fetched for anyone relay is present for, admin or not, and never
  // allowed to take the page down with it: it is additive, so a failure leaves the server
  // overview rendering alone rather than showing an error for a section nobody asked for.
  useEffect(() => {
    if (!relayPresent || !selectedGuild) {
      setMemberView(null);
      return;
    }
    let cancelled = false;
    setMemberViewLoading(true);
    api.relayView(selectedGuild.id)
      .then((data) => { if (!cancelled) setMemberView(data); })
      .catch(() => { if (!cancelled) setMemberView(null); })
      .finally(() => { if (!cancelled) setMemberViewLoading(false); });
    return () => { cancelled = true; };
  }, [relayPresent, selectedGuild]);

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
              Hey, {displayName}. No servers to show yet - a server appears here once you are
              in one that Stygian Relay has been added to.
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
        <SignalStrip signals={signalsFor(overview, memberView)} />
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

      {/* Member first: this is everyone's pane, admins included. An admin sees it above
          the server sections under codex's headings; a member sees it as the whole page,
          with no heading over it because there is nothing to distinguish it from. */}
      {relayPresent && memberViewLoading && !memberView && (
        <div className="ov-grid" role="status" aria-busy="true">
          <div className="skeleton-card s12" />
          <span className="visually-hidden">Loading where your messages go</span>
        </div>
      )}

      {relayPresent && memberView && (
        <>
          {canShowOverview && (
            <h2 className="section-title" style={{ margin: "4px 0 12px" }}>
              Your messages
            </h2>
          )}
          <MemberRelayView view={memberView} />
        </>
      )}

      {canShowOverview && (overview || overviewLoading || overviewError) && (
        <h2 className="section-title" style={{ margin: "28px 0 12px" }}>
          Server overview
        </h2>
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

      {relayPresent && !canShowOverview && (
        <p className="ov-muted" style={{ paddingBottom: 32 }}>
          You are a member of this server rather than one of its managers, so the server's
          own settings and figures are not shown here.{" "}
          <Link className="ov-link" to="/me/privacy">Your privacy choices</Link> control
          whether your messages are relayed at all.
        </p>
      )}
    </div>
  );
}

/* ── The command-row numbers ───────────────────────────────────────── */

/**
 * A manager gets the server's figures; a member gets their own.
 *
 * A member has no access to forwarded totals or the daily cap, so the strip must not sit
 * empty for them - it reports the two things they can be told, from the member view.
 */
function signalsFor(
  overview: GuildOverview | null,
  memberView: RelayViewResponse | null,
): Signal[] {
  if (!overview) return memberSignals(memberView);
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

function memberSignals(view: RelayViewResponse | null): Signal[] {
  if (!view) return [];
  const routes = view.guilds.reduce((sum, g) => sum + g.routes.length, 0);
  const carrying = view.guilds.reduce((sum, g) => sum + g.carrying_you, 0);
  const unknown = view.guilds.reduce((sum, g) => sum + g.unknown_you, 0);
  return [
    {
      key: "carrying",
      value: view.privacy.relaying_paused ? "0" : formatCount(carrying),
      label: view.privacy.relaying_paused
        ? "Carry your messages - you paused relaying"
        : unknown > 0
          // The figure counts only the routes we could answer for, so it would read as
          // the whole story while some were unanswered. Say how many are missing.
          ? `Routes carrying your messages (${unknown} could not be checked)`
          : "Routes carrying your messages",
    },
    {
      key: "routes",
      value: formatCount(routes),
      label: "Active routes here",
    },
  ];
}
