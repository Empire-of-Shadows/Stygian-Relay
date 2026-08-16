/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import "./styles/PageSkeleton.css";

/**
 * The shape of a page, shown while its data is on the way.
 *
 * A spinner says "something is happening"; this says "a heading and a row of
 * cards are about to appear here", so the layout does not jump when they do.
 * `role="status"` plus `aria-busy` is what a screen reader needs to announce
 * the wait, and the visually-hidden line is what it reads out.
 */
export default function PageSkeleton() {
  return (
    <div className="page-skeleton" role="status" aria-live="polite" aria-busy="true">
      <div className="skeleton-bar skeleton-bar--lg" />
      <div className="skeleton-grid">
        <div className="skeleton-card" />
        <div className="skeleton-card" />
        <div className="skeleton-card" />
      </div>
      <span className="visually-hidden">Loading...</span>
    </div>
  );
}
