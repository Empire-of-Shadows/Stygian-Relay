import type { GuildOverview, RelayViewResponse } from "../../api/types";
import type { Signal } from "../../_engine/components/overview/SignalStrip";
import { formatCount } from "../../_engine/format";

/*
 * The command-row numbers, shared by the two pages that draw a strip.
 *
 * These used to live inside DashboardPage, back when one page rendered both the
 * across-servers view and a picked server's view. Splitting those into `/me` and
 * `/me/guilds/:id/overview` left each page needing one of the two builders, and
 * the per-guild builder falls back to the member one, so both have to sit
 * somewhere both pages can reach.
 */

/**
 * A manager gets the server's figures; a member gets their own.
 *
 * A member has no access to forwarded totals or the daily cap, so the strip must not sit
 * empty for them - it reports the two things they can be told, from the member view.
 */
export function guildSignals(
  overview: GuildOverview | null,
  memberView: RelayViewResponse | null,
): Signal[] {
  if (!overview) return memberSignals(memberView, "here");
  const traffic = overview.traffic;
  const rules = overview.rules;

  return [
    {
      key: "forwarded",
      value: traffic ? formatCount(traffic.forwarded_30d) : "-",
      label: "Forwarded - 30 days",
    },
    {
      key: "today",
      value: traffic ? formatCount(traffic.today_forwarded) : "-",
      label: traffic ? `Today - of ${formatCount(traffic.daily_limit)}` : "Today",
    },
    {
      key: "rules",
      value: rules ? formatCount(rules.active) : "-",
      label: rules ? `Active rules - of ${rules.max_rules}` : "Active rules",
    },
    {
      key: "blocked",
      value: traffic ? formatCount(traffic.blocked_30d) : "-",
      label: "Blocked - 30 days",
    },
  ];
}

/**
 * The member's own two figures, summed over whatever servers the view covers.
 *
 * On `/me` the view spans every shared server, so this is the across-servers total; on
 * one server's overview the view covers that server alone and the same sums describe it.
 * Both readings are correct because the sum is over exactly what was asked for, which is
 * why `where` only changes the wording of the route-count label and never the arithmetic.
 */
export function memberSignals(
  view: RelayViewResponse | null,
  where: "here" | "everywhere" = "everywhere",
): Signal[] {
  if (!view) return [];
  const routes = view.guilds.reduce((sum, g) => sum + g.routes.length, 0);
  const carrying = view.guilds.reduce((sum, g) => sum + g.carrying_you, 0);
  const unknown = view.guilds.reduce((sum, g) => sum + g.unknown_you, 0);
  return [
    {
      key: "carrying",
      value: view.privacy.relaying_paused ? "0" : formatCount(carrying),
      label: view.privacy.relaying_paused
        ? "Carry your messages - you paused relaying"
        : unknown > 0
          // The figure counts only the routes we could answer for, so it would read as
          // the whole story while some were unanswered. Say how many are missing.
          ? `Routes carrying your messages (${unknown} could not be checked)`
          : "Routes carrying your messages",
    },
    {
      key: "routes",
      value: formatCount(routes),
      label: where === "here" ? "Active routes here" : "Active routes across your servers",
    },
  ];
}
