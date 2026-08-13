import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Guild } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { GuildWebScene } from "../_engine/components/GuildWebScene";

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
  onNavigate,
}: {
  guild: Guild;
  inviteUrl: string | null;
  onNavigate: (path: string) => void;
}) {
  const iconUrl = guildIconUrl(guild);

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
          </>
        )}
      </div>

      {!guild.bot_in_guild && (
        <p className="guild-invite-hint" style={{ marginTop: 0 }}>
          The bot is not in this server yet. Use the link above to add it, then come back here.
        </p>
      )}
    </>
  );
}
