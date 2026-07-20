/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { useCallback, useRef, useState } from "react";
import "./styles/ToastStack.css";

export type ToastKind = "success" | "error" | "info";

interface Toast {
  id: number;
  msg: string;
  kind: ToastKind;
}

/**
 * Transient, non-blocking notifications for action feedback ("Saved", "Save failed").
 * Use it for the result of a user action; use <Alert> for load / persistent errors.
 *
 * `useToast()` owns the queue and auto-dismiss; render `<ToastStack {...}/>` once near
 * the page root. Errors linger (10s) so they are not missed; success/info clear at 3s.
 *
 *   const { toasts, push, dismiss } = useToast();
 *   push("Saved", "success");
 *   <ToastStack toasts={toasts} onDismiss={dismiss} />
 */
export function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback((msg: string, kind: ToastKind = "info", duration?: number) => {
    const id = nextId.current++;
    setToasts((prev) => [...prev, { id, msg, kind }]);
    const effective = duration ?? (kind === "error" ? 10000 : 3000);
    if (effective > 0) {
      setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), effective);
    }
    return id;
  }, []);

  return { toasts, push, dismiss };
}

export function ToastStack({ toasts, onDismiss }: {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} role={t.kind === "error" ? "alert" : "status"}>
          <span className="toast-msg">{t.msg}</span>
          <button
            type="button"
            className="toast-close"
            aria-label="Dismiss notification"
            onClick={() => onDismiss(t.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
