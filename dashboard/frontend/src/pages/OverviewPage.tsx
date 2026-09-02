import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, UnauthorizedError } from "../api/client";
import type { Channel, Guild, GuildOverview, RelayViewResponse } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import SignalStrip from "../_engine/components/overview/SignalStrip";
import { GuildNav } from "../components/GuildNav";
import MemberRelayView from "../components/overview/MemberRelayView";
import RelayOverview from "../components/overview/RelayOverview";
import { guildSignals } from "../components/overview/signals";

/**
 * One server, in full.
 *
 * This is the landing page for a server: picking one anywhere in the app arrives here.
 * It answers the member's question first - where do my messages go in this server - and
 * then, for somebody who can manage it, the admin's: is the relay working, what is it
 * carrying, and what does the plan allow.
 *
 * It used to be the `?guild=` branch of the dashboard home. That left one per-guild view
 * addressed by a query parameter while every other per-guild page used a path, and it
 * meant `/me` was two different pages depending on the URL - a server list when you
 * arrived and one server's report the moment you chose. Now `/me` is the list plus your
 * activity across every server, and everything about ONE server lives under
 * `/me/guilds/:id/`, starting here. The old `/me?guild=` links still work: the route
 * redirects them here (see `MeOrRedirect` in App).
 *
 * MEMBER FIRST (owner ruling 2026-08-13). Everyone who signs in gets the "where do my
 * messages go" pane, including an admin - an admin is a member of their own server before
 * they are its administrator, and relay copies their messages too. The server overview
 * sits below it under its own heading, and only for someone who can actually manage the
 * server.
 *
 * The loads below are deliberately independent, exactly as they were on the home page:
 * they read different endpoints and are each allowed to fail alone, so losing the server
 * overview never blanks the member's own pane and vice versa.
 */
export function OverviewPage() {
  const { guildId = "" } = useParams<{ guildId: string }>();

  const [guilds, setGuilds] = useState<Guild[] | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [overview, setOverview] = useState<GuildOverview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [channels, setChannels] = useState<Map<string, string>>(new Map());

  const [memberView, setMemberView] = useState<RelayViewResponse | null>(null);
  const [memberViewLoading, setMemberViewLoading] = useState(false);

  // The server list is fetched here rather than handed down, so this page stands on its
  // own when it is the first URL of the session - which it now often is, because it is
  // what a shared link points at. It is the same request the home page makes, and the
  // only thing this page needs out of it is which tier the member holds in THIS server.
  useEffect(() => {
    let alive = true;
    api.guilds()
      .then((list) => { if (alive) setGuilds(list); })
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
  }, []);

  const guild = useMemo(
    () => (guilds ?? []).find((g) => g.id === guildId) ?? null,
    [guilds, guildId],
  );

  /** Relay is present and set up here - the precondition for anything below. */
  const relayPresent = guild !== null && guild.bot_in_guild && !guild.setup_required;

  /** ...and the user can manage it, which is what the server overview needs. Asking for
   *  the overview without this earns a 403, since every guild route is admin-only. */
  const canShowOverview = relayPresent && guild?.panel_role === "admin";

  useEffect(() => {
    if (!canShowOverview) {
      setOverview(null);
      setOverviewError(null);
      return;
    }
    let cancelled = false;
    setOverviewLoading(true);
    setOverviewError(null);
    api.overview(guildId)
      .then((data) => { if (!cancelled) setOverview(data); })
      .catch((e) => {
        if (cancelled) return;
        setOverview(null);
        if (e instanceof UnauthorizedError) return;
        setOverviewError(formatError(e, "Could not load this server."));
      })
      .finally(() => { if (!cancelled) setOverviewLoading(false); });
    return () => { cancelled = true; };
  }, [canShowOverview, guildId]);

  // Channel names are best-effort: the overview still renders with raw ids if
  // the picker list cannot be fetched.
  useEffect(() => {
    if (!canShowOverview) {
      setChannels(new Map());
      return;
    }
    let cancelled = false;
    api.channels(guildId)
      .then((list: Channel[]) => {
        if (cancelled) return;
        setChannels(new Map(list.map((c) => [c.id, c.name])));
      })
      .catch(() => { /* fall back to raw ids */ });
    return () => { cancelled = true; };
  }, [canShowOverview, guildId]);

  // The member pane. Fetched for anyone relay is present for, admin or not, and never
  // allowed to take the page down with it: it is additive, so a failure leaves the server
  // overview rendering alone rather than showing an error for a section nobody asked for.
  useEffect(() => {
    if (!relayPresent) {
      setMemberView(null);
      return;
    }
    let cancelled = false;
    setMemberViewLoading(true);
    api.relayView(guildId)
      .then((data) => { if (!cancelled) setMemberView(data); })
      .catch(() => { if (!cancelled) setMemberView(null); })
      .finally(() => { if (!cancelled) setMemberViewLoading(false); });
    return () => { cancelled = true; };
  }, [relayPresent, guildId]);

  const channelName = (id: string): string => {
    if (!id) return "unknown channel";
    const name = channels.get(id);
    return name ? `#${name}` : `#${id}`;
  };

  if (error) {
    return (
      <div className="page">
        <div style={{ paddingTop: 16 }}><GuildNav guildId={guildId} /></div>
        <Alert kind="danger">{error}</Alert>
      </div>
    );
  }

  return (
    <div className="page">
      {/* Rendered before the server list arrives so the way back out is never missing.
          The Settings tab appears with the list, because until then there is nothing to
          say what the member is allowed to do here. */}
      <div style={{ paddingTop: 16 }}>
        <GuildNav
          guildId={guildId}
          panelRole={guild?.panel_role}
          setupRequired={guild?.setup_required ?? false}
        />
      </div>

      <div className="page-header">
        <div>
          <span className="eyebrow">{guild?.name ?? "Server"}</span>
          <h1 style={{ marginTop: 4 }}>Overview</h1>
        </div>
      </div>

      <div className="ov-command">
        <span className="ov-muted" style={{ maxWidth: "46ch" }}>
          {guild === null
            ? "Loading this server..."
            : guild.setup_required
              ? "Stygian Relay has not been added to this server yet."
              : canShowOverview
                ? "You manage this server, so its own figures are below your own."
                : "You are a member here, so this page is about your messages."}
        </span>
        <SignalStrip signals={guildSignals(overview, memberView)} />
      </div>

      {guilds !== null && guild === null && (
        <div className="ov-grid">
          <section className="ov-card ov-card--quiet s12">
            <div className="ov-card__head">
              <span className="ov-card__title">Server not found</span>
            </div>
            <p className="ov-body">
              This server is not one of yours, or you are no longer in it.{" "}
              <Link className="ov-link" to="/me">Back to your servers</Link>.
            </p>
          </section>
        </div>
      )}

      {guild?.setup_required && (
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
                  href={`${inviteUrl}&guild_id=${guild.id}`}
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
          <Link className="ov-link" to={`/settings/guilds/${overview.guild_id}/stats`}>
            Analytics
          </Link>
          {" - "}
          <Link className="ov-link" to={`/settings/guilds/${overview.guild_id}/rules`}>Rules</Link>
          {" - "}
          <Link className="ov-link" to={`/settings/guilds/${overview.guild_id}/settings`}>
            Settings
          </Link>
          {" - "}
          <Link className="ov-link" to={`/settings/guilds/${overview.guild_id}/premium`}>
            Premium
          </Link>
          {" - "}
          <Link className="ov-link" to={`/settings/guilds/${overview.guild_id}/audit-log`}>
            Audit log
          </Link>
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
