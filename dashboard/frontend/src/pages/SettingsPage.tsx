import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Guild, GuildOverview } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { GuildWebScene } from "../_engine/components/GuildWebScene";
import { KeyValue } from "../_engine/components/overview/Tile";
import { formatCount, formatRelative } from "../_engine/format";

/**
 * The server picker, as the shared web-of-servers scene.
 *
 * `/settings` used to redirect straight back to the server list, so the
 * "Settings" link in the header went nowhere. It is now the fleet's guild
 * picker: one orb per server the user can manage, and a panel that grows out of
 * the web with that server's actions.
 */

/** Real Discord icon for a guild, or null so the scene draws its own orb.
 *  Typed on the two fields it reads rather than on relay's Guild, so it also
 *  satisfies the scene's callback, which hands over the wider engine Guild. */
function guildIconUrl(g: { id: string; icon: string | null }): string | null {
  return g.icon ? `https://cdn.discordapp.com/icons/${g.id}/${g.icon}.png?size=64` : null;
}

export function SettingsPage() {
  const [guilds, setGuilds] = useState<Guild[] | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // guild id -> its overview, fetched only when a node is actually picked and kept after
  // so re-picking the same node is instant. The panel is a shortcut menu; it must not
  // cost one request per server just to draw the web.
  const [overviews, setOverviews] = useState<Map<string, GuildOverview>>(new Map());
  const [overviewFailed, setOverviewFailed] = useState<Set<string>>(new Set());
  const navigate = useNavigate();
  // The scene draws its tether to this element, so the panel has to be a real
  // node in the layout even while it is closed.
  const blobRef = useRef<HTMLElement>(null);

  useEffect(() => {
    api.guilds().then(setGuilds).catch((e) => setError(formatError(e, "Failed to load servers.")));
    api.botInviteUrl().then((r) => setInviteUrl(r.url)).catch(() => {});
  }, []);

  const webGuilds = useMemo(
    () => (guilds ?? []).filter((g) => g.panel_role !== "none"),
    [guilds],
  );
  const counts = useMemo(() => ({
    total: webGuilds.length,
    ready: webGuilds.filter((g) => g.bot_in_guild && !g.setup_required).length,
  }), [webGuilds]);
  const selected = webGuilds.find((g) => g.id === selectedId) ?? null;

  // Lazy: one request the first time a server's node is picked, never on page load.
  useEffect(() => {
    if (!selected || !selected.bot_in_guild || selected.setup_required) return;
    if (overviews.has(selected.id) || overviewFailed.has(selected.id)) return;
    let cancelled = false;
    api.overview(selected.id)
      .then((o) => {
        if (!cancelled) setOverviews((prev) => new Map(prev).set(selected.id, o));
      })
      .catch(() => {
        if (!cancelled) setOverviewFailed((prev) => new Set(prev).add(selected.id));
      });
    return () => { cancelled = true; };
  }, [selected, overviews, overviewFailed]);

  const message = error ? (
    <div className="alert danger">{error}</div>
  ) : !guilds ? (
    <p className="muted">Loading servers...</p>
  ) : webGuilds.length === 0 ? (
    <div className="card">
      <h3>No servers to manage</h3>
      <p className="muted">
        You need Manage Server permission (or the manager role this bot has been given) in a
        Discord server to configure Stygian Relay.
        {inviteUrl && (
          <>
            {" "}
            <a href={inviteUrl} target="_blank" rel="noreferrer">Add Stygian Relay to a server</a>.
          </>
        )}
      </p>
    </div>
  ) : null;

  return (
    <div className="settings-scene">
      {message ? (
        <div className="settings-scene__message">{message}</div>
      ) : (
        <>
          <GuildWebScene
            guilds={webGuilds}
            selectedId={selectedId}
            onSelect={setSelectedId}
            tetherTo={blobRef}
            iconUrl={guildIconUrl}
            hubMark="S"
          >
            <span className="gw-eyebrow">Configuration</span>
            <h1 className="gw-title" data-gw-collide>The Relay Web</h1>
            <p className="gw-sub" data-gw-collide>
              Every server you relay for, strung together. Pluck a node to manage it.
            </p>
            <p className="gw-counts">
              {counts.total} servers - {counts.ready} ready
            </p>
          </GuildWebScene>

          <aside
            ref={blobRef}
            className={"gw-blob" + (selected ? " is-show" : "")}
            aria-live="polite"
          >
            {selected && (
              <>
                <button
                  type="button"
                  className="gw-blob-close"
                  aria-label="Close"
                  onClick={() => setSelectedId(null)}
                >
                  x
                </button>
                <ServerActionPanel
                  guild={selected}
                  inviteUrl={inviteUrl}
                  overview={overviews.get(selected.id) ?? null}
                  overviewFailed={overviewFailed.has(selected.id)}
                  onNavigate={(path) => navigate(path)}
                />
              </>
            )}
          </aside>
        </>
      )}
    </div>
  );
}

function ServerActionPanel({
  guild,
  inviteUrl,
  overview,
  overviewFailed,
  onNavigate,
}: {
  guild: Guild;
  inviteUrl: string | null;
  /** Fetched on selection. Null while in flight or when the fetch failed. */
  overview: GuildOverview | null;
  overviewFailed: boolean;
  onNavigate: (path: string) => void;
}) {
  const iconUrl = guildIconUrl(guild);
  const traffic = overview?.traffic ?? null;
  const rules = overview?.rules ?? null;

  return (
    <>
      <div className="settings-blob__head">
        <div className="guild-icon" style={{ width: 44, height: 44 }}>
          {iconUrl ? <img src={iconUrl} alt="" /> : (guild.name ?? "?")[0]}
        </div>
        <div style={{ minWidth: 0 }}>
          <div
            className="guild-name"
            style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            {guild.name}
          </div>
          <span className="status-badge status-badge--approved">Admin</span>
        </div>
      </div>

      <div className="settings-blob__actions">
        {!guild.bot_in_guild ? (
          inviteUrl && (
            <a
              className="btn btn-primary"
              href={`${inviteUrl}&guild_id=${guild.id}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Add Stygian Relay
            </a>
          )
        ) : (
          <>
            <button className="btn btn-primary" onClick={() => onNavigate(`/me?guild=${guild.id}`)}>
              Server overview
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => onNavigate(`/guilds/${guild.id}/rules`)}
            >
              Forwarding rules
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => onNavigate(`/guilds/${guild.id}/config`)}
            >
              Settings
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => onNavigate(`/guilds/${guild.id}/stats`)}
            >
              Analytics
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => onNavigate(`/guilds/${guild.id}/premium`)}
            >
              Plan
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => onNavigate(`/guilds/${guild.id}/audit-log`)}
            >
              Change history
            </button>
          </>
        )}
      </div>

      {/* A few live figures, so picking a node says something about the server rather
          than only offering places to go. Absent figures say so - a "0 forwarded" on a
          server whose overview simply has not arrived would be a lie. */}
      {guild.bot_in_guild && !guild.setup_required && (
        <div style={{ marginTop: 12 }}>
          {overviewFailed ? (
            <p className="muted" style={{ fontSize: 12, margin: 0 }}>
              This server's figures could not be loaded.
            </p>
          ) : !overview ? (
            <p className="muted" style={{ fontSize: 12, margin: 0 }}>
              Loading this server's figures...
            </p>
          ) : (
            <>
              <KeyValue
                k="Active rules"
                v={rules ? `${rules.active} of ${rules.max_rules}` : "not loaded"}
              />
              <KeyValue
                k="Forwarded, 30 days"
                v={traffic ? formatCount(traffic.forwarded_30d) : "not loaded"}
              />
              <KeyValue
                k="Today"
                v={
                  traffic
                    ? `${formatCount(traffic.today_forwarded)} of ${formatCount(traffic.daily_limit)}`
                    : "not loaded"
                }
              />
              <KeyValue
                k="Last forward"
                v={
                  traffic
                    ? traffic.last_forward_at
                      ? formatRelative(traffic.last_forward_at)
                      : "never"
                    : "not loaded"
                }
              />
            </>
          )}
        </div>
      )}

      {!guild.bot_in_guild && (
        <p className="guild-invite-hint" style={{ marginTop: 0 }}>
          The bot is not in this server yet. Use the link above to add it, then come back here.
        </p>
      )}
    </>
  );
}
