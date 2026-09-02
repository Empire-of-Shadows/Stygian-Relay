import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, UnauthorizedError } from "../api/client";
import type { Guild, Me, RelayViewResponse } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import MemberRelayView from "../components/overview/MemberRelayView";
import ServerPicker, { pickerMeta } from "../_engine/components/overview/ServerPicker";
import SignalStrip from "../_engine/components/overview/SignalStrip";
import { memberSignals } from "../components/overview/signals";

/**
 * The relay dashboard home.
 *
 * Two things, and only these two: the server picker, and where your messages go across
 * EVERY server you share with Stygian Relay. Everyone gets that combined view, including
 * an admin - an admin is a member of their own server before they are its administrator,
 * and relay copies their messages too (owner ruling 2026-08-13).
 *
 * One server's own view is NOT here any more. It lives at `/me/guilds/:id/overview`, and
 * picking a server in the picker navigates there. This page used to render a picked
 * server inline and keep the choice in the URL as `?guild=`, which left one per-guild
 * view addressed by a query parameter while every other per-guild page used a path, and
 * made `/me` two different pages depending on how you arrived at it.
 *
 * The old `/me?guild=` form is still a link somebody may have saved, so the route
 * redirects it to that server's overview (see `MeOrRedirect` in App).
 */
export function DashboardPage({ me }: { me: Me | null }) {
  const navigate = useNavigate();

  const [guilds, setGuilds] = useState<Guild[] | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [memberView, setMemberView] = useState<RelayViewResponse | null>(null);
  const [memberViewLoading, setMemberViewLoading] = useState(true);

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
    // No guild argument: the endpoint then answers for every server the session shares
    // with the bot, which is exactly the across-servers view this page is. Never allowed
    // to take the page down - a failure leaves the picker and the server list working.
    api.relayView()
      .then((data) => { if (alive) setMemberView(data); })
      .catch(() => { if (alive) setMemberView(null); })
      .finally(() => { if (alive) setMemberViewLoading(false); });
    return () => { alive = false; };
  }, []);

  // Picking a server is navigation now, not selection: this page has no per-server state
  // left to set. "All servers" is what this page already is, so choosing it stays put
  // rather than routing anywhere.
  const selectGuild = (guildId: string | null) => {
    if (guildId) navigate(`/me/guilds/${guildId}/overview`);
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
          // Nothing is ever selected here: this page IS the across-servers view, and
          // choosing a server leaves it for that server's own page.
          selectedGuildId={null}
          onSelect={selectGuild}
          meta={pickerMeta(null, guilds.length, "Stygian Relay")}
        />
        <SignalStrip signals={memberSignals(memberView)} />
      </div>

      <p className="ov-muted" style={{ margin: "0 0 4px" }}>
        {guilds.length === 1
          ? "Everything below covers your one server."
          : `Everything below covers all ${guilds.length} of your servers.`}{" "}
        Choose one above for its own page - its routes, and, if you manage it, its
        settings and figures.
      </p>

      {memberViewLoading && !memberView && (
        <div className="ov-grid" role="status" aria-busy="true">
          <div className="skeleton-card s12" />
          <span className="visually-hidden">Loading where your messages go</span>
        </div>
      )}

      {!memberViewLoading && !memberView && (
        <div className="ov-grid">
          <section className="ov-card ov-card--quiet s12">
            <div className="ov-card__head">
              <span className="ov-card__title">Not loaded</span>
            </div>
            <p className="ov-body">
              Where your messages go could not be loaded right now. Refresh to try again,
              or open one of your servers above.
            </p>
          </section>
        </div>
      )}

      {memberView && <MemberRelayView view={memberView} />}
    </div>
  );
}
