import { Link } from "react-router-dom";

// Adapted from TheCodex's Privacy Policy for Stygian Relay's actual data practices.
//
// Verified against the storage layer on 2026-08-01 and corrected on 2026-08-13. The
// corrections were about things the earlier wording was quietly wrong or vague about:
//
//   - "does not store the content" was true but incomplete. `message_logs` keeps a
//     REFERENCE to the original message - its ID and its channel - for 90 days, which is
//     a pointer to the member's message even though the text is not copied. Section 2 now
//     says so.
//   - The policy never said that forwarding REPUBLISHES a display name and message
//     content into another channel, which may be in a different server with a different
//     audience. That is the single most consequential thing this bot does. Section 3 says
//     it now.
//   - "related configuration may be cleaned up" on bot removal said nothing checkable.
//     Section 7 now names what survives and for how long, from the TTL indexes in
//     guild_manager._ensure_indexes (message_logs 90 days, denial_counters 90 days,
//     audit_logs 365 days) and the premium state, which is not on a TTL at all.
//   - Section 8 now points at the member's own controls, which did not exist before.
//
// Renumbering: the new section 3 pushed every later heading down by one.
const EFFECTIVE_DATE = "August 13, 2026";

export function PrivacyPolicyPage() {
  return (
    <div className="dash-page">
      <section className="dash-hero">
        <div className="dash-hero__orb" />
        <div className="dash-hero__copy">
          <span className="dash-hero__eyebrow">Legal</span>
          <h1 className="dash-hero__title">Privacy Policy</h1>
          <p className="dash-hero__sub">Effective {EFFECTIVE_DATE}</p>
        </div>
      </section>

      <div className="legal-doc">
        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>1. Overview</h2>
          <p>
            This policy explains what data Stygian Relay ("the bot", "we", "us") collects when you
            use the bot or the web dashboard, how we use it, and the choices you have. Stygian Relay
            is part of the Empire of Shadows ecosystem and is designed to work in any Discord server.
            Because the bot forwards messages between channels, it reads message content in order to
            repost it. Section 2 lists what is kept; section 3 explains what forwarding actually
            does with what you post, which is the part most worth reading.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>2. Information we collect</h2>
          <ul>
            <li>
              <strong>Discord account data</strong> provided through Discord login (OAuth): your user
              ID, username, global display name, and avatar, plus the servers you are in and your
              permissions in them, which we use for dashboard access control.
            </li>
            <li>
              <strong>Server configuration:</strong> the manager role, log channel, feature toggles,
              and the list of servers allowed to forward into yours.
            </li>
            <li>
              <strong>Forwarding rules</strong> you create: the source and destination channel IDs,
              an optional destination server, a rule name, and any author filters you set.
            </li>
            <li>
              <strong>A delivery record for each message forwarded:</strong> which rule ran, the
              source and destination channel, the ID of the original message, whether it succeeded,
              and when. These power the usage figures on the dashboard. They contain no message text
              and do not name the author.
            </li>
            <li>
              <strong>A reference to your original message, for 90 days.</strong> The delivery
              record above holds the ID of the message that was forwarded and the channel it was
              posted in. That is a pointer back to your message, not a copy of it - we do not
              store what you wrote - but it is still a record that you posted something in that
              channel at that moment. It is deleted automatically after 90 days.
            </li>
            <li>
              <strong>Your own privacy choices,</strong> if you set any: whether you have asked us
              not to relay your messages, and whether you have asked us to keep your name off
              forwarded copies. These are stored against your Discord user ID and apply in every
              server the bot runs in.
            </li>
            <li>
              <strong>An audit log</strong> of configuration and rule changes (who changed what, and
              when) so administrators can review activity.
            </li>
            <li><strong>Premium subscription status</strong> for servers with a premium plan.</li>
            <li><strong>A session cookie</strong> that keeps you signed in to the dashboard.</li>
          </ul>
          <p className="muted">
            Message content is read in transit to forward it to the destination channel; the bot
            does not store or archive the content of forwarded messages. It keeps the rules that
            route them and a record that a delivery happened, not the messages themselves.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>3. What forwarding actually does</h2>
          <p>
            This is the part worth reading twice, because it is the whole purpose of the bot.
            When a server administrator sets up a forwarding rule, every message posted in the
            channel they chose is <strong>republished into another channel</strong> - your
            display name and the content of your message, reposted as a quote with a link back to
            your original.
          </p>
          <p>
            <strong>That other channel can be in a different server.</strong> A rule may copy from
            a channel in one server into a channel in another, so people who are not in your
            server, and who you have never met, can end up reading what you wrote with your name
            on it. Cross-server forwarding only works when the receiving server has explicitly
            allowed yours, but that is a decision between the two servers' administrators, not
            one you are asked about.
          </p>
          <p>
            You have two ways to stop it, and they apply everywhere the bot runs, not just in one
            server. You can ask us not to relay your messages at all, or you can ask us to keep
            your name off forwarded copies. Both are on the{" "}
            <Link to="/me/privacy">Privacy &amp; data</Link> page once you are signed in, and both take
            effect within about a minute. Neither one removes copies that were already posted -
            those are ordinary Discord messages in someone else's channel now, and we cannot
            delete them.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>4. How we use your data</h2>
          <p>
            We use this data to run message forwarding, power your dashboard, show usage statistics,
            and gate settings to the right people. We do not sell your data and we do not show
            advertising.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>5. Cookies</h2>
          <p>
            We use a single session cookie to identify your signed-in session on the dashboard. It
            is required for login to work. Sessions expire automatically after about 30 days, after
            which you will need to sign in again.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>6. Third parties</h2>
          <p>
            We rely on Discord for login and as the platform the bot runs on, and on our database and
            hosting infrastructure (MongoDB) to store your configuration and statistics. Your
            dashboard session is shared across the Empire of Shadows ecosystem, so one login covers
            every bot dashboard. We do not share your data with advertisers or data brokers.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>7. Data retention</h2>
          <p>
            We keep your server configuration and forwarding rules for as long as the bot is set up
            in your server. Login sessions expire automatically after about 30 days.
          </p>
          <p>
            <strong>If the bot is removed from a server, this is exactly what survives and for how
            long.</strong> Removal does not trigger a deletion; the records already written simply
            run out their normal lifetime:
          </p>
          <ul>
            <li>
              <strong>Delivery records</strong> - which rule ran, the channels, and the ID of the
              original message: deleted automatically <strong>90 days</strong> after each one was
              written.
            </li>
            <li>
              <strong>Blocked-message counters</strong> - the daily tallies of messages we could
              not forward and why, with no message or member attached: deleted automatically
              <strong> 90 days</strong> after each day's tally.
            </li>
            <li>
              <strong>Audit-log entries</strong> - who changed a setting or a rule, and when:
              deleted automatically <strong>365 days</strong> after each entry.
            </li>
            <li>
              <strong>Premium status</strong> for the server, and the entitlement records behind
              it: kept indefinitely, because they are a record of a purchase.
            </li>
            <li>
              <strong>Your own privacy choices:</strong> kept until you change them. They are
              deliberately not deleted, because deleting them would silently switch relaying back
              on for you.
            </li>
          </ul>
          <p>
            Everything else - the server's configuration and its forwarding rules - stays until it
            is deleted from the dashboard or the bot's admin panel, or until an administrator asks
            us to remove it.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>8. Your choices and rights</h2>
          <p>
            <strong>As a member,</strong> the <Link to="/me/privacy">Privacy &amp; data</Link> page is
            where you control this. You can stop your messages being relayed anywhere, keep your
            name off forwarded copies, download everything we hold for you, or have your name taken
            out of every forwarding rule. No permission in any server is needed - signing in is
            enough. Copies already posted into a channel cannot be removed by us; ask that server's
            staff.
          </p>
          <p>
            <strong>As a server administrator,</strong> you can edit or delete forwarding rules and
            configuration from the dashboard at any time, and remove the bot from a server to stop
            it processing that server's messages.
          </p>
          <p>
            For anything the pages above do not cover, contact us at
            <a href="mailto:support@eosofficial.club"> support@eosofficial.club</a>.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>9. Children</h2>
          <p>
            You must meet Discord's minimum age requirement for your region to use the bot or the
            dashboard. We do not knowingly collect data from anyone below that age.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>10. Changes to this policy</h2>
          <p>
            We may update this policy from time to time. The effective date at the top of this page
            reflects the latest version, and we will note material changes where practical.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>11. Contact</h2>
          <p>
            Questions about this policy or your data can be sent to
            <a href="mailto:support@eosofficial.club"> support@eosofficial.club</a>.
          </p>
        </section>
      </div>
    </div>
  );
}
