/** Relay-specific wording for the overview. Plain language, no jargon. */

/**
 * How a blocked-message reason is written for an admin.
 *
 * The keys are the bot's own `METRIC_*` constants, which are the only values
 * `record_denial` is ever called with (`commands/forward/forward.py`). An
 * unknown reason falls back to the raw key rather than being hidden, so a new
 * bot-side counter shows up here instead of silently disappearing.
 */
const REASON_LABELS: Record<string, { label: string; help: string }> = {
  perm_failure: {
    label: "Could not deliver",
    help: "The destination channel is missing, or the bot cannot post there.",
  },
  daily_limit_hit: {
    label: "Daily limit reached",
    help: "Skipped after this server hit its daily forward cap.",
  },
  rate_limited: {
    label: "Slowed down",
    help: "Bursts throttled so forwarding stays smooth.",
  },
};

export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason]?.label ?? reason;
}

export function reasonHelp(reason: string): string {
  return REASON_LABELS[reason]?.help ?? "";
}

/** "premium, extra" -> "Premium, Extra". Falls back to "Free". */
export function planLabel(tier: string, tiers: string[]): string {
  const parts = tiers.length > 0 ? tiers : [tier || "free"];
  return parts
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(", ");
}
