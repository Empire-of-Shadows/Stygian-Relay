import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { GuildOverview, PremiumStatus } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import { KeyValue, Rule as Divider, Stat, Tile } from "../_engine/components/overview/Tile";
import { formatCount, formatDate } from "../_engine/format";
import { planLabel, reasonLabel } from "../components/overview/format";

/*
 * The plan page.
 *
 * It used to be three numbers in a card and a paragraph, which told an admin what they
 * had and nothing about whether they needed more. The question this page exists to answer
 * is "should I upgrade", and that is only answerable next to real usage: how many rules
 * are actually in use against the cap, how close today's traffic is to the daily cap, and
 * how many messages the cap has actually cost this server.
 *
 * The free and premium figures are the REAL limits the backend enforces
 * (dashboard/services/premium.py's fallbacks, which mirror the bot's own
 * GuildManager.get_guild_limits), not marketing copy - so the table cannot drift away
 * from what a purchase actually buys.
 */

/** The fallbacks in dashboard/services/premium.py::get_guild_limits. */
const FREE_MAX_RULES = 3;
const FREE_DAILY_LIMIT = 100;
const PREMIUM_MAX_RULES = 20;
const PREMIUM_DAILY_LIMIT = 5000;

export function PremiumPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [premium, setPremium] = useState<PremiumStatus | null>(null);
  const [overview, setOverview] = useState<GuildOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!guildId) return;
    let cancelled = false;
    api.premium(guildId)
      .then((p) => { if (!cancelled) setPremium(p); })
      .catch((e) => { if (!cancelled) setError(formatError(e)); });
    // Usage is enrichment: without it the plan tile still renders, and the usage tile
    // says the figures could not be loaded rather than showing zeros.
    api.overview(guildId).then((o) => { if (!cancelled) setOverview(o); }).catch(() => {});
    return () => { cancelled = true; };
  }, [guildId]);

  if (!guildId) return null;

  const traffic = overview?.traffic ?? null;
  const rules = overview?.rules ?? null;
  const delivery = overview?.delivery ?? null;

  const capHits =
    delivery?.reasons.find((r) => r.reason === "daily_limit_hit")?.count ?? null;

  const rulePct =
    rules && premium && premium.max_rules > 0
      ? Math.min(100, (rules.active / premium.max_rules) * 100)
      : 0;
  const dailyPct =
    traffic && premium && premium.daily_limit > 0
      ? Math.min(100, (traffic.today_forwarded / premium.daily_limit) * 100)
      : 0;

  return (
    <div className="page">
      <div className="page-header" style={{ paddingTop: 16 }}>
        <div>
          <Link to={`/me?guild=${guildId}`} className="muted" style={{ fontSize: 13 }}>
            &larr; Server overview
          </Link>
          <h1 style={{ marginTop: 4 }}>Plan</h1>
        </div>
      </div>

      {error && <Alert kind="danger">{error}</Alert>}

      {premium === null && !error && (
        <div className="ov-grid" role="status" aria-busy="true">
          <div className="skeleton-card s6" />
          <div className="skeleton-card s6" />
          <span className="visually-hidden">Loading your plan</span>
        </div>
      )}

      {premium && (
        <div className="ov-grid">
          <Tile
            span={6}
            title="Your plan"
            live
            chips={
              premium.is_premium ? (
                <span className="ov-chip ov-chip--good">
                  {planLabel(premium.tier, premium.tiers)}
                </span>
              ) : (
                <span className="ov-chip">Free</span>
              )
            }
          >
            <Stat
              value={premium.is_premium ? planLabel(premium.tier, premium.tiers) : "Free"}
              label="Current plan for this server"
            />
            <Divider />
            <KeyValue k="Rules allowed" v={String(premium.max_rules)} />
            <KeyValue k="Messages per day" v={formatCount(premium.daily_limit)} />
            <KeyValue
              k="Renews"
              v={
                !premium.is_premium
                  ? "not applicable"
                  : premium.expires_at
                    ? formatDate(premium.expires_at)
                    : "no end date"
              }
            />
            <Divider />
            <p className="ov-muted">
              {premium.is_premium
                ? "Premium is managed through Discord. Changes there appear here on their own, usually within a minute or two."
                : "Premium is bought through Discord, from the bot's profile. Once it is active it shows up here on its own - there is nothing to enter."}
            </p>
          </Tile>

          <Tile span={6} title="How much you are using">
            {rules || traffic ? (
              <>
                {rules && (
                  <div>
                    <div className="ov-statrow">
                      <Stat
                        small
                        value={rules.active}
                        sub={`/${premium.max_rules}`}
                        label="Active rules"
                      />
                    </div>
                    <div className="ov-meter" style={{ marginTop: 8 }}>
                      <div className="ov-meter__fill" style={{ width: `${rulePct}%` }} />
                    </div>
                  </div>
                )}
                {traffic && (
                  <div>
                    <div className="ov-statrow">
                      <Stat
                        small
                        value={formatCount(traffic.today_forwarded)}
                        sub={`/${formatCount(premium.daily_limit)}`}
                        label="Forwarded today"
                      />
                    </div>
                    <div className="ov-meter" style={{ marginTop: 8 }}>
                      <div className="ov-meter__fill" style={{ width: `${dailyPct}%` }} />
                    </div>
                  </div>
                )}
                <Divider />
                {!rules && (
                  <p className="ov-muted">Your rule usage could not be loaded right now.</p>
                )}
                {!traffic && (
                  <p className="ov-muted">Today's usage could not be loaded right now.</p>
                )}
                {rules && traffic && (
                  <p className="ov-muted">
                    {rules.active >= premium.max_rules
                      ? "You are at your rule limit. Pause one you are not using, or upgrade, before adding another."
                      : `${premium.max_rules - rules.active} more rule${premium.max_rules - rules.active === 1 ? "" : "s"} available on this plan.`}
                  </p>
                )}
              </>
            ) : (
              <p className="ov-muted">
                Your usage figures could not be loaded right now. Refresh to try again.
              </p>
            )}
          </Tile>

          <Tile
            span={7}
            title="Free and Premium side by side"
            chips={
              premium.is_premium ? (
                <span className="ov-chip ov-chip--good">You have Premium</span>
              ) : null
            }
          >
            <p className="ov-body">
              These are the limits the bot actually enforces, not a sales sheet.
            </p>
            <div className="ov-cols ov-cols--2">
              <div>
                <span className="ov-card__title">Free</span>
                <KeyValue k="Rules" v={String(FREE_MAX_RULES)} />
                <KeyValue k="Messages per day" v={formatCount(FREE_DAILY_LIMIT)} />
                <KeyValue k="Forwarded messages" v="carry a small footer" />
              </div>
              <div>
                <span className="ov-card__title">Premium</span>
                <KeyValue k="Rules" v={String(PREMIUM_MAX_RULES)} />
                <KeyValue k="Messages per day" v={formatCount(PREMIUM_DAILY_LIMIT)} />
                <KeyValue k="Forwarded messages" v="no footer" />
              </div>
            </div>
            <Divider />
            <p className="ov-muted">
              The footer is occasional rather than on every message, and it is the source
              server's plan that decides it - a premium server forwarding into a free one
              still forwards without a footer.
            </p>
          </Tile>

          <Tile
            span={5}
            title="What the daily cap has cost"
            chips={
              capHits !== null && capHits > 0 ? (
                <span className="ov-chip ov-chip--warn">Cap reached recently</span>
              ) : null
            }
          >
            {delivery === null ? (
              <p className="ov-muted">
                Blocked-message figures could not be loaded right now. Refresh to try again.
              </p>
            ) : capHits === null || capHits === 0 ? (
              <p className="ov-body">
                This server has not hit its daily forwarding cap in the last 30 days, so the
                cap is not costing you anything at the moment.
              </p>
            ) : (
              <>
                <Stat
                  value={formatCount(capHits)}
                  label={`Messages skipped in 30 days because the daily cap was reached`}
                />
                <Divider />
                <p className="ov-muted">
                  Once a server passes {formatCount(premium.daily_limit)} forwarded messages
                  in a day, nothing more is copied until midnight UTC.
                  {premium.is_premium
                    ? " That is the premium allowance, so a higher one is not available."
                    : ` Premium raises the allowance to ${formatCount(PREMIUM_DAILY_LIMIT)} a day.`}
                </p>
                <Link className="ov-link" to={`/guilds/${guildId}/stats`}>
                  See the full breakdown
                </Link>
              </>
            )}

            {delivery && delivery.reasons.length > 0 && (
              <>
                <Divider />
                <span className="ov-card__title">Everything blocked, 30 days</span>
                <div>
                  {delivery.reasons.map((reason) => (
                    <KeyValue
                      key={reason.reason}
                      k={reasonLabel(reason.reason)}
                      v={formatCount(reason.count)}
                    />
                  ))}
                </div>
              </>
            )}
          </Tile>
        </div>
      )}
    </div>
  );
}
