/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Catches render / lifecycle errors in its subtree and shows a friendly fallback
 * instead of a blank white screen. Wrap the app once near the root.
 *
 * Note: React error boundaries do NOT catch errors thrown in async event handlers
 * (a failed fetch in an onClick) - those still surface through formatError / <Alert>.
 * This is the safety net for a component that throws while rendering.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode; fallback?: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface to the console; a shared reporter can hook in here later.
    console.error("Dashboard crashed:", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback;
    return (
      <div
        className="empty-state"
        style={{ maxWidth: 520, margin: "4rem auto", padding: "2.5rem", textAlign: "center" }}
      >
        <h2 style={{ marginBottom: "0.75rem" }}>Something went wrong</h2>
        <p className="muted" style={{ marginBottom: "1.25rem" }}>
          This page hit an unexpected error. Reloading usually fixes it.
        </p>
        <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
