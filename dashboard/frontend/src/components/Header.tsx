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
          {/* Fleet vocabulary: the member link is "Dashboard" and the admin hub is
              "Manage", the same two words on every bot's header. They used to be
              "Servers" and "Settings", and "Settings" in particular collided with the
              per-server Settings tab further down the page - two links with one name,
              leading to different places. The targets are unchanged. */}
          <NavLink to="/me" end className={navClass}>Dashboard</NavLink>
          {/* Not gated on any permission: relay copies an ordinary member's messages, so
              the switches that stop it have to be reachable by an ordinary member. */}
          <NavLink to="/me/privacy" className={navClass}>Privacy</NavLink>
          {me.can_access_settings_any && (
            <NavLink to="/settings" className={navClass}>Manage</NavLink>
          )}
        </>
      ) : null}
      loggedOut={<a href="/auth/discord" className="cta">Log in with Discord</a>}
    />
  );
}
