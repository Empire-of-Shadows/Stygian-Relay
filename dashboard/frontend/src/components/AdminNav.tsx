import { NavLink } from "react-router-dom";

function navClass({ isActive }: { isActive: boolean }) {
  return "nav-button" + (isActive ? " active" : "");
}

/** The admin tab bar for one server's management pages, so the admin tree navigates
 *  within itself instead of sending an admin back out to the member side to change page.
 *
 *  Every tab is always shown. Hiding a link was never the gate - the dashboard re-checks
 *  the panel tier on every read and every write, so a link somebody should not have leads
 *  to a refusal rather than to data.
 *
 *  The Rules tab stays highlighted while a single rule is open, because the rule editor
 *  lives under the rules path and NavLink matches on the path prefix. That is deliberate:
 *  the editor is a page within Forwarding rules, not a seventh area. */
export function AdminNav({ guildId }: { guildId: string }) {
  return (
    <nav className="nav-links" style={{ marginBottom: 20 }}>
      <NavLink to="/settings" end className="nav-button">&larr; Your servers</NavLink>
      <NavLink to={`/settings/guilds/${guildId}/settings`} className={navClass}>Settings</NavLink>
      <NavLink to={`/settings/guilds/${guildId}/rules`} className={navClass}>
        Forwarding rules
      </NavLink>
      <NavLink to={`/settings/guilds/${guildId}/stats`} className={navClass}>Analytics</NavLink>
      <NavLink to={`/settings/guilds/${guildId}/premium`} className={navClass}>Plan</NavLink>
      <NavLink to={`/settings/guilds/${guildId}/audit-log`} className={navClass}>
        Change history
      </NavLink>
    </nav>
  );
}
