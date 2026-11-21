import { NavLink, useSearchParams } from "react-router-dom";

function navClass({ isActive }: { isActive: boolean }) {
  return "nav-button" + (isActive ? " active" : "");
}

/** Marks an admin link as opened from a server's overview, so the admin tree's
 *  back link returns there instead of to the settings hub.
 *
 *  A query parameter rather than router state on purpose: the settings and audit
 *  log pages rewrite their own query string (`?s=`, `?section=`), which would
 *  drop router state but merges into existing parameters, and the vendored
 *  FeatureStrip only takes a plain href string. */
export function fromOverview(path: string): string {
  return path + (path.includes("?") ? "&" : "?") + "from=overview";
}

/** For a link from one admin page to another: keeps the from-overview marker
 *  when the current page carries it, so the way back survives the move. */
export function useAdminHref(): (path: string) => string {
  const [searchParams] = useSearchParams();
  const cameFromOverview = searchParams.get("from") === "overview";
  return (path) => (cameFromOverview ? fromOverview(path) : path);
}

/** The admin tab bar for one server's management pages, so the admin tree navigates
 *  within itself instead of sending an admin back out to the member side to change page.
 *
 *  The back link follows where the admin came in. Opened from the server's overview
 *  (the member side), it returns to that overview and every tab keeps the marker so the
 *  way back survives moving between tabs. Opened from the settings hub, or from a bare
 *  link, it returns to the hub.
 *
 *  Every tab is always shown. Hiding a link was never the gate - the dashboard re-checks
 *  the panel tier on every read and every write, so a link somebody should not have leads
 *  to a refusal rather than to data.
 *
 *  The Rules tab stays highlighted while a single rule is open, because the rule editor
 *  lives under the rules path and NavLink matches on the path prefix. That is deliberate:
 *  the editor is a page within Forwarding rules, not a seventh area. */
export function AdminNav({ guildId }: { guildId: string }) {
  const [searchParams] = useSearchParams();
  const cameFromOverview = searchParams.get("from") === "overview";
  const tab = useAdminHref();
  return (
    <nav className="nav-links" style={{ marginBottom: 20 }}>
      {cameFromOverview ? (
        <NavLink to={`/me/guilds/${guildId}/overview`} end className="nav-button">
          &larr; Overview
        </NavLink>
      ) : (
        <NavLink to="/settings" end className="nav-button">&larr; Your servers</NavLink>
      )}
      <NavLink to={tab(`/settings/guilds/${guildId}/settings`)} className={navClass}>
        Settings
      </NavLink>
      <NavLink to={tab(`/settings/guilds/${guildId}/rules`)} className={navClass}>
        Forwarding rules
      </NavLink>
      <NavLink to={tab(`/settings/guilds/${guildId}/stats`)} className={navClass}>Analytics</NavLink>
      <NavLink to={tab(`/settings/guilds/${guildId}/premium`)} className={navClass}>Plan</NavLink>
      <NavLink to={tab(`/settings/guilds/${guildId}/audit-log`)} className={navClass}>
        Change history
      </NavLink>
    </nav>
  );
}
