import { Link, useParams } from "react-router-dom";

export function GuildPage() {
  const { guildId } = useParams<{ guildId: string }>();
  if (!guildId) return null;

  const items = [
    {
      to: `/guilds/${guildId}/rules`,
      icon: "🔀",
      title: "Forwarding Rules",
      desc: "Create, edit, and manage message forwarding rules for this server.",
    },
    {
      to: `/guilds/${guildId}/stats`,
      icon: "📊",
      title: "Stats",
      desc: "View forwarded message counts, daily limits, and per-rule breakdowns.",
    },
    {
      to: `/guilds/${guildId}/config`,
      icon: "⚙️",
      title: "Settings",
      desc: "Configure log channel, manager role, and inbound guild allowlist.",
    },
    {
      to: `/guilds/${guildId}/premium`,
      icon: "👑",
      title: "Premium",
      desc: "View your current plan, tier, and rule limits.",
    },
    {
      to: `/guilds/${guildId}/audit-log`,
      icon: "📋",
      title: "Audit Log",
      desc: "See a history of all admin actions taken on this server.",
    },
  ];

  return (
    <div className="dash-page">
      <div className="dash-hero">
        <div className="dash-hero__orb" />
        <div className="dash-hero__copy">
          <span className="dash-hero__eyebrow">Stygian Relay</span>
          <h1 className="dash-hero__title">Server Dashboard</h1>
          <p className="dash-hero__sub">
            Manage forwarding rules, view stats, and configure your relay settings.
          </p>
        </div>
        <div className="dash-hero__strip">
          <Link to="/me" className="btn btn-secondary">← All Servers</Link>
        </div>
      </div>

      <div className="dash-page__body">
        <div className="activity-grid">
          {items.map((item) => (
            <Link key={item.to} to={item.to} className="activity-card" style={{ textDecoration: "none" }}>
              <div className="activity-card__header">
                <span className="activity-card__sigil">{item.icon}</span>
                <span className="activity-card__title">{item.title}</span>
              </div>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.5 }}>{item.desc}</p>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
