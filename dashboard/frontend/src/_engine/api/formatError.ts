/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { TimeoutError, UnauthorizedError } from "./http";

/**
 * Map any thrown value to a short, friendly, user-facing message.
 *
 * The single normalizer every dashboard routes errors through, so the wording a
 * user sees is identical across bots. Prefers the transport's typed errors
 * (UnauthorizedError / TimeoutError); ApiError and plain Errors fall through to
 * their message, and network failures are caught by name.
 */
export function formatError(e: unknown, fallback = "Something went wrong - try again."): string {
  if (e instanceof UnauthorizedError) return "Your session has expired.";
  if (e instanceof TimeoutError) return "Request timed out - try again.";
  if (e instanceof Error) {
    if (!e.message) return fallback;
    if (/^TypeError|^NetworkError/i.test(e.message)) return "Network error - check your connection.";
    return e.message;
  }
  if (typeof e === "string" && e.trim()) return e;
  return fallback;
}
