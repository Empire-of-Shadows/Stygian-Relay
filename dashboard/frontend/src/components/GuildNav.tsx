import { NavLink } from "react-router-dom";
import type { PanelRole } from "../api/types";

function navClass({ isActive }: { isActive: boolean }) {
  return "nav-button" + (isActive ? " active" : "");
}

/** Per-guild tab bar for the member side of the relay dashboard.
 *
 *  Relay's member surface in one server is a single page - the overview - because
 *  everything else it can say about a server (its rules, its analytics, its plan, its
 *  change history) is admin-only and lives in the `/settings` tree. So the bar is short
 *  on purpose: back to the server list, this server's overview, and a way into the admin
 *  tree for someone who can manage it. The bar is still worth having on one page, because
 *  it is what tells a member the server list is one click away rather than a browser
 *  back-button away, and it is where a second member page would go the day there is one.
 *
 *  The Settings link is HIDDEN here, not enforced here - every guild route re-checks the
 *  tier server-side, and a member who forges the URL gets a 403 from the API rather than
 *  a page.
 *
 *  A server the bot is not in yet (`setupRequired`) keeps only the back link and Overview:
 *  a Settings tab would lead to a config page for a server with no config, and a dead tab
 *  next to an invite card reads as broken rather than as empty. */
export function GuildNav({
  guildId,
  panelRole,
  setupRequired = false,
}: {
  guildId: string;
  panelRole?: PanelRole;
  setupRequired?: boolean;
}) {
  const canSeeSettings = panelRole === "admin" && !setupRequired;
  return (
    <nav className="nav-links" style={{ marginBottom: 20 }}>
      <NavLink to="/me" end className="nav-button">&larr; Servers</NavLink>
      <NavLink to={`/me/guilds/${guildId}/overview`} className={navClass}>Overview</NavLink>
      {canSeeSettings && (
        <NavLink to={`/settings/guilds/${guildId}/settings`} className={navClass}>
          Settings
        </NavLink>
      )}
    </nav>
  );
}
