import { Link, NavLink } from "react-router-dom";
import type { Me } from "../api/types";
import { AppShell } from "../_engine/components/AppShell";

function navClass({ isActive }: { isActive: boolean }) {
  return "nav-button" + (isActive ? " active" : "");
}

/** Stygian Relay header: the shared AppShell wired with relay's brand + nav. */
export function Header({ me }: { me: Me | null }) {
  return (
    <AppShell
      user={me}
      brand={
        <Link to={me ? "/me" : "/"} style={{ textDecoration: "none", color: "inherit" }}>
          <h1>
            <span className="app-header__title-text">Stygian Relay</span>
          </h1>
        </Link>
      }
      nav={me ? (
        <>
          <NavLink to="/me" end className={navClass}>Servers</NavLink>
          {me.can_access_settings_any && (
            <NavLink to="/settings" className={navClass}>Settings</NavLink>
          )}
        </>
      ) : null}
      loggedOut={<a href="/auth/discord" className="cta">Log in with Discord</a>}
    />
  );
}
