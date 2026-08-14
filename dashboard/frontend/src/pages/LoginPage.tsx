import { Link, Navigate, useLocation } from "react-router-dom";
import { discordLoginUrl } from "../api/client";
import type { Me } from "../api/types";

export function LoginPage({ me }: { me: Me | null }) {
  const location = useLocation();
  const next = new URLSearchParams(location.search).get("next") || "/me";

  if (me) return <Navigate to={next} replace />;

  return (
    <div className="login-main">
      <div className="login-hero">
        <h1>Stygian Relay</h1>
        <p className="tagline">
          Sign in with Discord to manage your message forwarding rules, view stats, and configure
          your relay settings. Your Empire of Shadows session is shared - one login covers every
          bot dashboard.
        </p>
        <a href={discordLoginUrl(next)} className="cta">
          Login with Discord
        </a>
        <p className="muted" style={{ marginTop: "0.75rem", fontSize: "0.85rem" }}>
          One login covers every Empire of Shadows dashboard, so by signing in you agree to the{" "}
          <a
            href="https://eosofficial.club/privacy"
            target="_blank"
            rel="noopener noreferrer"
          >
            Empire of Shadows Privacy Policy
          </a>
          , which covers every bot, dashboard, and tool in the ecosystem. Stygian Relay has its own{" "}
          <Link to="/privacy">privacy page</Link> for the detail specific to this bot.
        </p>
        <p className="muted" style={{ fontSize: "0.85rem" }}>
          New here?{" "}
          <a
            href="https://eosofficial.club/about"
            target="_blank"
            rel="noopener noreferrer"
          >
            Read what this project is about
          </a>{" "}
          - six bots, one ecosystem, and why it is built that way.
        </p>

        <div className="login-divider">Explore the ecosystem</div>

        <div className="login-tiles">
          <a className="tile-button" href="https://eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">Main Site</span>
            <span className="tile-desc">Empire of Shadows hub - news, links, community.</span>
          </a>
          <a className="tile-button" href="https://host.eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">TheHost</span>
            <span className="tile-desc">Events, games, and interactive activities.</span>
          </a>
          <a className="tile-button" href="https://codex.eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">TheCodex</span>
            <span className="tile-desc">Guides, polls, and stats for TheCodex bot.</span>
          </a>
          <a className="tile-button" href="https://ecom.eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">Ecom</span>
            <span className="tile-desc">Leveling, embers, and economy for the Ecom bot.</span>
          </a>
          <a className="tile-button" href="https://reminder.eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">Imperial Reminder</span>
            <span className="tile-desc">Bump reminders that keep a server listed.</span>
          </a>
          <a className="tile-button" href="https://decree.eosofficial.club" target="_blank" rel="noopener noreferrer">
            <span className="tile-title">The Decree</span>
            <span className="tile-desc">Scheduled quotes and announcements on a timer.</span>
          </a>
        </div>
      </div>

      {/*
        What the bot actually does, below the fold.
        This strip was an empty reserved div. Every figure in it is the real free-tier
        limit the backend enforces (dashboard/services/premium.py::get_guild_limits), not
        a marketing number, so it cannot promise something a new server does not get. It
        is static on purpose: nobody is signed in here, so there is nothing live to read.
      */}
      <div className="login-below">
        <div className="login-divider">What Stygian Relay does</div>
        <div className="login-tiles">
          <div className="tile-button" style={{ cursor: "default" }}>
            <span className="tile-title">Copies a channel into another channel</span>
            <span className="tile-desc">
              Pick a channel to watch and a channel to copy into. Every message posted in
              the first is reposted in the second, as a quote with a link back to the
              original.
            </span>
          </div>
          <div className="tile-button" style={{ cursor: "default" }}>
            <span className="tile-title">Three routes free, 100 messages a day</span>
            <span className="tile-desc">
              A free server can run three rules at once and forward up to 100 messages a
              day. Premium raises that to twenty rules and 5,000 messages, and is bought
              through Discord.
            </span>
          </div>
          <div className="tile-button" style={{ cursor: "default" }}>
            <span className="tile-title">Filters, and a say for members</span>
            <span className="tile-desc">
              Each rule can require or block words, set a length range, and pick which
              roles it copies. Any member can ask relay to leave their messages out
              entirely, or to keep their name off the copies.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
