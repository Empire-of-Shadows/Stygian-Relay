/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { Link } from "react-router-dom";
import "./styles/AppFooter.css";

/**
 * Shared dashboard footer: a brand line plus optional legal links. Bots pass their
 * own `brand` string; `legal` (default on) renders the Terms / Privacy links so the
 * footer is consistent across dashboards. Pass `legal={false}` for a bot that does
 * not yet have /terms and /privacy pages.
 */
export function AppFooter({ brand, legal = true }: { brand: string; legal?: boolean }) {
  return (
    <footer className="site-footer">
      <span className="site-footer__brand">{brand}</span>
      {legal && (
        <nav className="site-footer__links" aria-label="Legal">
          <Link to="/terms">Terms of Service</Link>
          <Link to="/privacy">Privacy Policy</Link>
        </nav>
      )}
    </footer>
  );
}
