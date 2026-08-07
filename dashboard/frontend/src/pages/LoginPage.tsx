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
        </div>
      </div>
      <div className="login-below" />
    </div>
  );
}
