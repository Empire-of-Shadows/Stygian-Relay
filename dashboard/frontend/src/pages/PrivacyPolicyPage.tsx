// DRAFT legal copy - adapted from TheCodex's Privacy Policy for Stygian Relay's
// actual data practices (see relay's storage layer). Two claims especially worth
// confirming before publishing: (1) that forwarded message content is processed in
// transit and NOT stored/archived, and (2) the retention specifics. Effective date
// is a placeholder.
const EFFECTIVE_DATE = "July 19, 2026";

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
            repost it - see "Information we collect" below for what is kept and what is not.
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
              <strong>Forwarding statistics:</strong> aggregate counts such as how many messages were
              forwarded per rule and per day, used to show usage on the dashboard. These are counts,
              not copies of the messages.
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
            does not store or archive the content of forwarded messages. It keeps forwarding counts
            and the rules that route them, not the messages themselves.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>3. How we use your data</h2>
          <p>
            We use this data to run message forwarding, power your dashboard, show usage statistics,
            and gate settings to the right people. We do not sell your data and we do not show
            advertising.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>4. Cookies</h2>
          <p>
            We use a single session cookie to identify your signed-in session on the dashboard. It
            is required for login to work. Sessions expire automatically after about 30 days, after
            which you will need to sign in again.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>5. Third parties</h2>
          <p>
            We rely on Discord for login and as the platform the bot runs on, and on our database and
            hosting infrastructure (MongoDB) to store your configuration and statistics. Your
            dashboard session is shared across the Empire of Shadows ecosystem, so one login covers
            every bot dashboard. We do not share your data with advertisers or data brokers.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>6. Data retention</h2>
          <p>
            We keep your server configuration and forwarding rules for as long as the bot is set up
            in your server. Forwarding statistics and audit-log entries are kept to provide history
            on the dashboard. Login sessions expire automatically. If the bot is removed from a
            server, related configuration may be cleaned up.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>7. Your choices and rights</h2>
          <p>
            Server administrators can edit or delete forwarding rules and configuration from the
            dashboard at any time, and can remove the bot from a server to stop it processing that
            server's messages. To request a copy of, or the deletion of, the data we hold for you or
            your server, contact us at
            <a href="mailto:support@eosofficial.club"> support@eosofficial.club</a>.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>8. Children</h2>
          <p>
            You must meet Discord's minimum age requirement for your region to use the bot or the
            dashboard. We do not knowingly collect data from anyone below that age.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>9. Changes to this policy</h2>
          <p>
            We may update this policy from time to time. The effective date at the top of this page
            reflects the latest version, and we will note material changes where practical.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>10. Contact</h2>
          <p>
            Questions about this policy or your data can be sent to
            <a href="mailto:support@eosofficial.club"> support@eosofficial.club</a>.
          </p>
        </section>
      </div>
    </div>
  );
}
