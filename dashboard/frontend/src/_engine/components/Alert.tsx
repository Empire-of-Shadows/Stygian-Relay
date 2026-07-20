/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import type { ReactNode } from "react";

export type AlertKind = "danger" | "success" | "warning";

/**
 * Inline status banner - the standard surface for load / persistent errors and
 * confirmations (pair it with formatError for the message). Renders nothing when
 * there is no content, so it drops straight in as `<Alert kind="danger">{error}</Alert>`
 * and shows only when `error` is truthy.
 */
export function Alert({ kind = "danger", children }: {
  kind?: AlertKind;
  children: ReactNode;
}) {
  if (!children) return null;
  return (
    <div className={`alert ${kind}`} role="alert">
      {children}
    </div>
  );
}
