/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import "./styles/AppFooter.css";

/**
 * Shared dashboard footer: a brand line plus optional legal links. Bots pass their
 * own `brand` string; `legal` (default on) renders the About / Terms / Privacy links so
 * the footer is consistent across dashboards. Pass `legal={false}` for a bot that does
 * not yet have /terms and /privacy pages. The About link points at the ecosystem hub's
 * project page, which exists for every bot, so it renders regardless of `legal`.
 *
 * `extraLinks` is a slot for a bot's own footer links (a public board, ecosystem links)
 * rendered in the same row, after the legal links. Pass bare `<a>`/`<Link>` elements - a
 * fragment is fine - and they pick up the shared footer link styling from their position
 * inside the nav. Omitting it renders exactly the footer that existed before the slot.
 */
export function AppFooter({
  brand,
  legal = true,
  extraLinks,
}: {
  brand: string;
  legal?: boolean;
  extraLinks?: ReactNode;
}) {
  return (
    <footer className="site-footer">
      <span className="site-footer__brand">{brand}</span>
      <nav className="site-footer__links" aria-label="About and legal">
        <a href="https://eosofficial.club/about" target="_blank" rel="noopener noreferrer">
          About the Project
        </a>
        {legal && (
          <>
            <Link to="/terms">Terms of Service</Link>
            <Link to="/privacy">Privacy Policy</Link>
          </>
        )}
        {extraLinks}
      </nav>
    </footer>
  );
}
