/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { useEffect, useRef, useState, type ReactNode } from "react";
import "./styles/ConfirmDialog.css";

/**
 * A destructive question, asked properly - the one confirmation surface for
 * every bot dashboard.
 *
 * This replaces the browser `confirm()` calls the data pages used to make. A
 * native confirm cannot say what it is about to delete, cannot be styled, and
 * on some browsers can be suppressed entirely - at which point the page reads
 * the suppression as "yes".
 *
 * Behaviour, in one place so no dashboard has to re-derive it:
 *   - focus moves into the dialog on open and returns to whatever opened it
 *     on close;
 *   - Escape cancels, and so does a backdrop click (unless the action is
 *     already in flight, where there is nothing left to cancel);
 *   - Tab is kept inside the dialog, which matters most when a control in it
 *     is disabled and must not be a stop in the cycle;
 *   - `busy` disables both buttons while the action is running;
 *   - `typeToConfirm` adds the typed-confirmation step the privacy pages need:
 *     an input inside the dialog, and a confirm button that stays disabled
 *     until what was typed matches exactly.
 *
 * Rendered as null while closed, and the typed box is cleared on every
 * opening, so each opening starts clean whether or not the parent unmounts it.
 */

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** Prose, or richer content - it is rendered inside the message paragraph. */
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  /** Disables both buttons while the action is in flight. */
  busy?: boolean;
  /** When set, the confirm button is armed only once this exact word is typed. */
  typeToConfirm?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  busy = false,
  typeToConfirm,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const [text, setText] = useState("");
  const dialogRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const previousActive = useRef<HTMLElement | null>(null);
  // Held in a ref so the key handler is installed once per opening. The parent
  // passes a fresh closure every render; depending on it would re-run the
  // effect and steal focus back mid-interaction.
  const cancelRef = useRef(onCancel);
  cancelRef.current = onCancel;
  // `busy` is read through a ref for the same reason: the key handler is installed
  // once per opening, so a plain closure would capture whatever busy was when the
  // dialog opened - which is always false - and the guard below would never fire.
  const busyRef = useRef(busy);
  busyRef.current = busy;

  useEffect(() => {
    if (!open) return;
    // Cleared here rather than on close so a parent that keeps this mounted
    // still gets an empty box on every opening.
    setText("");
    previousActive.current = document.activeElement as HTMLElement | null;
    // The typed step starts in the box; a plain confirm starts on the button.
    if (inputRef.current) inputRef.current.focus();
    else confirmRef.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        // Escape is one of three ways out, and it has to agree with the other
        // two: the backdrop is inert while busy and the Cancel button is
        // disabled while busy. Without this guard Escape was the one route that
        // still fired mid-flight, closing the dialog over a request that keeps
        // running - so the member watched a destructive action they believe they
        // cancelled go through anyway. Worst on the privacy pages, which are the
        // ones using typeToConfirm. preventDefault still runs so Escape does not
        // fall through to anything behind the dialog either way.
        e.preventDefault();
        if (busyRef.current) return;
        cancelRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      // Rebuilt on every Tab because the confirm button can be disabled until
      // the word is typed, and a disabled control must not be a stop in the
      // cycle.
      const stops = Array.from(
        dialog.querySelectorAll<HTMLElement>("input, button"),
      ).filter((node) => !node.hasAttribute("disabled"));
      if (stops.length === 0) return;
      const first = stops[0];
      const last = stops[stops.length - 1];
      const active = document.activeElement;
      if (!dialog.contains(active)) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previousActive.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  const typed = typeToConfirm !== undefined;
  const armed = !busy && (!typed || text === typeToConfirm);

  return (
    <div
      className="confirm-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-title"
      aria-describedby="confirm-message"
      onClick={busy ? undefined : onCancel}
    >
      <div className="confirm-dialog" ref={dialogRef} onClick={(e) => e.stopPropagation()}>
        <h2 id="confirm-title" className="confirm-title">{title}</h2>
        <p id="confirm-message" className="confirm-message">{message}</p>

        {typed ? (
          <div className="eos-field">
            <label htmlFor="confirm-type-input">Type {typeToConfirm} to confirm</label>
            <input
              id="confirm-type-input"
              ref={inputRef}
              type="text"
              value={text}
              disabled={busy}
              autoComplete="off"
              placeholder={typeToConfirm}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && armed) onConfirm();
              }}
            />
          </div>
        ) : null}

        <div className="confirm-actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={busy}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={destructive ? "btn btn-danger" : "btn btn-primary"}
            disabled={!armed}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
