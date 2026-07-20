import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, UnauthorizedError } from "../api/client";
import type { Guild, Me } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";

function GuildIcon({ guild }: { guild: Guild }) {
  if (guild.icon) {
    const url = `https://cdn.discordapp.com/icons/${guild.id}/${guild.icon}.png?size=64`;
    return (
      <div className="guild-icon">
        <img src={url} alt="" onError={(e) => { (e.currentTarget.parentElement!.innerHTML = guild.name[0] ?? "?"); }} />
      </div>
    );
  }
  return (
    <div className="guild-icon">
      <div className="guild-icon-fallback">{guild.name[0] ?? "?"}</div>
    </div>
  );
}

export function DashboardPage({ me }: { me: Me | null }) {
  const [guilds, setGuilds] = useState<Guild[] | null>(null);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.guilds()
      .then((g) => { if (alive) setGuilds(g); })
      .catch((e) => { if (alive) setError(e instanceof UnauthorizedError ? "Your session has expired." : formatError(e, "Failed to load servers.")); });
    api.botInviteUrl()
      .then((r) => { if (alive) setInviteUrl(r.url); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const displayName = me?.global_name || me?.username || "there";

  return (
    <div className="dash-page">
      <div className="dash-hero">
        <div className="dash-hero__orb" />
        <div className="dash-hero__copy">
          <span className="dash-hero__eyebrow">Message Forwarding</span>
          <h1 className="dash-hero__title">Hey, {displayName}</h1>
          <p className="dash-hero__sub">
            Select a server to manage forwarding rules, view stats, and configure settings.
          </p>
        </div>
        {inviteUrl && (
          <div className="dash-hero__strip">
            <a href={inviteUrl} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
              Add to Server
            </a>
          </div>
        )}
      </div>

      <div className="dash-page__body">
        <Alert kind="danger">{error}</Alert>

        {guilds === null && !error && (
          <div className="page-skeleton">
            <div className="skeleton-bar" />
            <div className="skeleton-grid">
              {Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton-card" />)}
            </div>
          </div>
        )}

        {guilds !== null && guilds.length === 0 && (
          <div className="empty-state" style={{ padding: "3rem", marginTop: "2rem" }}>
            <p style={{ marginBottom: "1rem" }}>No servers found where you have Manage Server permission and the relay bot is installed.</p>
            {inviteUrl && (
              <a href={inviteUrl} target="_blank" rel="noopener noreferrer" className="btn btn-primary">
                Add Stygian Relay to a Server
              </a>
            )}
          </div>
        )}

        {guilds !== null && guilds.length > 0 && (
          <div className="guild-grid">
            {guilds.map((guild) => {
              if (guild.setup_required) {
                return (
                  <div key={guild.id} className="card guild-card guild-card--setup">
                    <GuildIcon guild={guild} />
                    <div style={{ minWidth: 0 }}>
                      <div className="guild-name">{guild.name}</div>
                      <div className="guild-invite-hint">Bot not in this server</div>
                      {inviteUrl && (
                        <a
                          href={`${inviteUrl}&guild_id=${guild.id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn-success small"
                          style={{ marginTop: 8 }}
                        >
                          Add Bot
                        </a>
                      )}
                    </div>
                  </div>
                );
              }
              return (
                <Link key={guild.id} to={`/guilds/${guild.id}`} className="card guild-card">
                  <GuildIcon guild={guild} />
                  <div style={{ minWidth: 0 }}>
                    <div className="guild-name">{guild.name}</div>
                    {!guild.has_config && (
                      <div className="guild-invite-hint">Setup required</div>
                    )}
                  </div>
                  <span className="guild-invite-badge" style={{ marginLeft: "auto" }}>
                    {guild.panel_role === "admin" ? "Admin" : "View"}
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
