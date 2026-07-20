/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import type { ReactNode } from "react";
import { EcosystemNav } from "./EcosystemNav";
import { logoutUrl } from "../api/http";
import type { SessionUser } from "../api/types";

/**
 * Shared dashboard header shell. Each bot wraps this with its own brand + nav (see
 * the bot's `components/AppHeader` / `Header`). The shell owns the uniform parts: the
 * `.app-header` layout, the EcosystemNav switcher, and the user-info + Log out block
 * (or a logged-out CTA). Bot-specific bits arrive as props/slots:
 *
 *   brand     - logo + title (a bot renders its own)
 *   nav       - the bot's nav links (shown only when logged in and no `left` slot)
 *   left/right - slots (e.g. a builder's back button / mode switch)
 *   loggedOut - shown in the user slot when there is no user (e.g. a login CTA)
 */
export function AppShell({ user, brand, nav, left, right, hideUser, loggedOut }: {
  user?: SessionUser | null;
  brand: ReactNode;
  nav?: ReactNode;
  left?: ReactNode;
  right?: ReactNode;
  hideUser?: boolean;
  loggedOut?: ReactNode;
}) {
  const avatarUrl =
    user?.avatar && user?.id
      ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=64`
      : null;
  const displayName = user?.global_name || user?.username;

  return (
    <header className="app-header">
      <div style={{ display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>
        {brand}
        {left ?? (user && nav ? (
          <nav className="nav-links" style={{ marginLeft: 8 }}>{nav}</nav>
        ) : null)}
      </div>
      <div style={{ marginLeft: "auto", marginRight: 12 }}>
        <EcosystemNav />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {right}
        {!hideUser && (user ? (
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
        ) : loggedOut)}
      </div>
    </header>
  );
}
