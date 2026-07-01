import { Link, NavLink } from "react-router-dom";
import { logoutUrl } from "../api/client";
import type { Me } from "../api/types";
import { EcosystemNav } from "./EcosystemNav";

export function Header({ me }: { me: Me | null }) {
  const avatarUrl =
    me?.avatar && me?.id
      ? `https://cdn.discordapp.com/avatars/${me.id}/${me.avatar}.png?size=64`
      : null;
  const displayName = me?.global_name || me?.username;

  return (
    <header className="app-header">
      <div style={{ display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>
        <Link to={me ? "/me" : "/"} style={{ textDecoration: "none", color: "inherit" }}>
          <h1>
            <span className="app-header__title-text">Stygian Relay</span>
          </h1>
        </Link>
        {me && (
          <nav className="nav-links" style={{ marginLeft: 8 }}>
            <NavLink to="/me" end className={navClass}>Servers</NavLink>
            {me.can_access_settings_any && (
              <NavLink to="/settings" className={navClass}>Settings</NavLink>
            )}
          </nav>
        )}
      </div>
      <div style={{ marginLeft: "auto", marginRight: 12 }}>
        <EcosystemNav />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {me ? (
          <div className="user-info">
            {avatarUrl && <img src={avatarUrl} alt="" />}
            <span>{displayName}</span>
            <a
              href={logoutUrl()}
              className="btn btn-secondary"
              style={{ fontSize: 12, padding: "4px 10px" }}
            >
              Log out
            </a>
          </div>
        ) : (
          <a href="/auth/discord" className="cta">Log in with Discord</a>
        )}
      </div>
    </header>
  );
}

function navClass({ isActive }: { isActive: boolean }) {
  return "nav-button" + (isActive ? " active" : "");
}
