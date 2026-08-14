import { Link } from "react-router-dom";

// Published terms, adapted from TheCodex's for Stygian Relay's actual service
// (cross-channel message forwarding). Ruled published by the owner on 2026-08-13; the
// DRAFT marker and its placeholder date are gone and the effective date is real. Section
// 4 gained the member's own controls, which shipped the same day - a terms page that
// makes a member responsible for forwarded content has to say what a member can do
// about it.
const EFFECTIVE_DATE = "August 13, 2026";

export function TermsPage() {
  return (
    <div className="dash-page">
      <section className="dash-hero">
        <div className="dash-hero__orb" />
        <div className="dash-hero__copy">
          <span className="dash-hero__eyebrow">Legal</span>
          <h1 className="dash-hero__title">Terms of Service</h1>
          <p className="dash-hero__sub">Effective {EFFECTIVE_DATE}</p>
        </div>
      </section>

      <div className="legal-doc">
        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>1. Acceptance and eligibility</h2>
          <p>
            Stygian Relay ("the bot", "we", "us") is a Discord bot and companion web dashboard
            operated as part of the Empire of Shadows ecosystem. By adding the bot to a server,
            creating forwarding rules, or signing in to the dashboard, you agree to these Terms of
            Service.
          </p>
          <p>
            You must meet Discord's minimum age requirement for your region and comply with the
            <a href="https://discord.com/terms" target="_blank" rel="noopener"> Discord Terms of Service</a>
            at all times. If you do not agree to these terms, do not use the bot or the dashboard.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>2. The service</h2>
          <p>
            Stygian Relay forwards messages from one channel to another, within a single server or
            across servers, according to forwarding rules that server administrators configure. It
            includes a web dashboard for creating and managing those rules, viewing forwarding
            statistics, and configuring per-server settings. The bot is designed to work in any
            Discord server, not only Empire of Shadows.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>3. Acceptable use</h2>
          <p>When using the bot or dashboard, you agree not to:</p>
          <ul>
            <li>Use forwarding to spam, flood, harass, or evade moderation or bans in any server.</li>
            <li>Forward content that violates the Discord Terms of Service or the rules of either the source or destination server.</li>
            <li>Forward another server's messages without the right to do so, or in a way that misleads members about where a message originated.</li>
            <li>Attempt to disrupt, overload, reverse engineer, or gain unauthorized access to the service.</li>
          </ul>
          <p className="muted">
            Server administrators control which channels the bot forwards to and from, and may add
            or remove rules at their discretion. Cross-server forwarding into a server is only
            possible when that server has allowed the source server.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>4. Forwarded content and responsibility</h2>
          <p>
            You are responsible for the forwarding rules you create and for the content those rules
            move on your behalf. Forwarded content remains subject to these terms, the Discord Terms
            of Service, and the rules of the servers involved.
          </p>
          <p>
            The bot reposts message content as configured; it does not review or moderate what is
            forwarded. Server administrators are responsible for ensuring their forwarding setup is
            appropriate for the members of the destination channel.
          </p>
          <p>
            <strong>Members have their own say over this.</strong> Anyone signed in to the
            dashboard can ask the bot not to relay their messages at all, or to leave their name
            off forwarded copies, from the <Link to="/me/privacy">Privacy &amp; data</Link> page.
            Those choices apply in every server the bot runs in and override a rule's own settings.
            They do not affect copies that were already posted, which are ordinary Discord messages
            in the destination channel and are that server's to remove.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>5. Availability and "as is"</h2>
          <p>
            The service is provided "as is" and "as available", without warranties of any kind. We
            do not guarantee that forwarding will be uninterrupted, timely, error free, or available
            at any particular time, and features may change or be discontinued.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>6. Limitation of liability</h2>
          <p>
            To the maximum extent permitted by law, we are not liable for any indirect, incidental,
            or consequential damages, or for any loss of data or content, arising from your use of
            or inability to use the bot or dashboard, including messages that fail to forward or are
            forwarded in error.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>7. Termination</h2>
          <p>
            We may suspend or revoke access to the bot or dashboard at any time, including for
            violations of these terms. Server administrators may remove the bot from their server at
            any time. You may stop using the service and remove the bot whenever you choose.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>8. Changes to these terms</h2>
          <p>
            We may update these terms from time to time. The effective date at the top of this page
            reflects the latest version. Continued use of the bot or dashboard after an update means
            you accept the revised terms.
          </p>
        </section>

        <section className="section card">
          <h2 className="section-title" style={{ marginTop: 0 }}>9. Contact</h2>
          <p>
            Questions about these terms can be sent to
            <a href="mailto:support@eosofficial.club"> support@eosofficial.club</a>.
          </p>
        </section>
      </div>
    </div>
  );
}
