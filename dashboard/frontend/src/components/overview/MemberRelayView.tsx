import { Link } from "react-router-dom";
import type { MemberGuildView, MemberRoute, RelayViewResponse } from "../../api/types";
import { Rule, Tile } from "../../_engine/components/overview/Tile";

/**
 * The member pane: where your messages go.
 *
 * Owner ruling 2026-08-13 - an ordinary member sees this, not just an admin. Relay
 * republishes what a member writes into a channel they may not be in, sometimes in a
 * server they are not in, so "which routes carry my messages" is a question they are
 * owed an answer to.
 *
 * The honesty rules this pane is built on:
 *
 *   - A route that does NOT carry you is still listed, marked as not carrying you.
 *     Hiding it would leave a member unable to tell "no rule watches that channel" from
 *     "a rule watches it but a filter excludes me".
 *   - A cross-server destination names the server. "Copied somewhere else" without
 *     saying where is worse than saying nothing.
 *   - A destination channel in another server is NOT named, because relay only resolves
 *     names in the server being listed. It says "a channel in <server>" rather than
 *     printing a raw id and calling it a name.
 *   - Forwarding switched off at the server level is stated, because every route below
 *     is then inert and a list of live-looking routes would be a lie.
 */
export default function MemberRelayView({ view }: { view: RelayViewResponse }) {
  const guilds = view.guilds;
  const withRoutes = guilds.filter((g) => g.routes.length > 0);
  const carryingYou = guilds.reduce((sum, g) => sum + g.carrying_you, 0);
  const paused = view.privacy.relaying_paused;

  return (
    <div className="ov-grid">
      <Tile
        span={12}
        title="Where your messages go"
        live={!paused}
        chips={
          paused ? (
            <span className="ov-chip ov-chip--good">Relaying paused for you</span>
          ) : carryingYou > 0 ? (
            // "1 route carries", not "1 route carry" - the verb agrees too, and a member
            // in exactly one relayed channel is the commonest case, not an edge one.
            <span className="ov-chip ov-chip--live">
              {carryingYou === 1
                ? "1 route carries your messages"
                : `${carryingYou} routes carry your messages`}
            </span>
          ) : (
            <span className="ov-chip">No route carries your messages</span>
          )
        }
        action={
          <Link className="ov-link" to="/me/privacy">
            Privacy choices
          </Link>
        }
        quiet={withRoutes.length === 0}
      >
        {paused && (
          <p className="ov-body">
            You have asked relay to leave your messages alone, so nothing you post is
            copied anywhere - whatever the routes below say. Copies posted before you made
            that choice are still in their channels.
          </p>
        )}

        {!paused && view.privacy.name_hidden && (
          <p className="ov-body">
            Your messages are copied, but no copy carries your name.
          </p>
        )}

        {withRoutes.length === 0 ? (
          <p className="ov-body">
            None of your servers has an active forwarding route right now, so nothing you
            post is being copied anywhere.
          </p>
        ) : (
          withRoutes.map((guild) => <GuildRoutes key={guild.guild_id} guild={guild} />)
        )}

        {withRoutes.length > 0 && (
          <>
            <Rule />
            <p className="ov-muted">
              A route copies every message in its source channel that passes the rule's
              filters. It does not follow you around - only the channels listed here are
              watched.
            </p>
          </>
        )}
      </Tile>
    </div>
  );
}

function GuildRoutes({ guild }: { guild: MemberGuildView }) {
  return (
    <div>
      <div className="ov-card__head" style={{ marginBottom: 4 }}>
        <span className="ov-card__title">{guild.guild_name ?? `Server ${guild.guild_id}`}</span>
        {!guild.forwarding_enabled && (
          <span className="ov-chip ov-chip--warn">Forwarding is off here</span>
        )}
      </div>
      {!guild.forwarding_enabled && (
        <p className="ov-muted">
          This server has forwarding switched off, so none of these routes is copying
          anything at the moment.
        </p>
      )}
      {guild.routes.map((route) => (
        <RouteRow key={route.rule_id} route={route} />
      ))}
    </div>
  );
}

function RouteRow({ route }: { route: MemberRoute }) {
  const source = route.source_channel_name
    ? `#${route.source_channel_name}`
    : `channel ${route.source_channel_id}`;

  const destination = route.cross_server
    ? `a channel in ${route.destination_guild_name ?? "another server"}`
    : route.destination_channel_name
      ? `#${route.destination_channel_name}`
      : `channel ${route.destination_channel_id}`;

  return (
    <div className="mroute">
      <div className="mroute__path">
        <span className="chan-chip" title={source}>{source}</span>
        <span className="route-arrow" aria-hidden="true">-&gt;</span>
        <span className="chan-chip" title={destination}>{destination}</span>
        {route.cross_server && (
          <span className="route-xguild" title="This route leaves the server">
            another server
          </span>
        )}
        <span
          className={
            route.carries_you ? "mroute__mark mroute__mark--yes" : "mroute__mark mroute__mark--no"
          }
          style={{ marginLeft: "auto" }}
        >
          <span className="mroute__dot" aria-hidden="true" />
          {route.carries_you ? "carries your messages" : "not your messages"}
        </span>
      </div>
      {!route.carries_you && (
        <span className="mroute__note">
          This rule only copies certain people, and you are not one of them.
        </span>
      )}
    </div>
  );
}
