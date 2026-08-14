/** Relay-specific wording for the overview and the analytics page. Plain language.
 *
 * ONE map for both pages. The analytics page used to carry a second, differently-worded
 * copy of the same three reasons ("Rate limited" / "Misconfigured rule" where the
 * overview said "Slowed down" / "Could not deliver"), so the same blocked message was
 * named two different things depending on which page you opened. The overview's plainer
 * wording won; the analytics page's longer explanations were kept as the help text.
 */

/**
 * How a blocked-message reason is written for an admin.
 *
 * The keys are the bot's own `METRIC_*` constants, which are the only values
 * `record_denial` is ever called with (`commands/forward/forward.py`). An
 * unknown reason falls back to the raw key rather than being hidden, so a new
 * bot-side counter shows up here instead of silently disappearing.
 *
 * `color` is for the breakdown bars only. It is a severity cue that always ships
 * alongside the written label, never the only thing distinguishing two rows.
 */
const REASON_META: Record<string, { label: string; help: string; color: string }> = {
  perm_failure: {
    label: "Could not deliver",
    help: "The destination channel is missing, or the bot cannot post there.",
    color: "var(--danger)",
  },
  daily_limit_hit: {
    label: "Daily limit reached",
    help: "Skipped after this server hit its daily forward cap.",
    color: "var(--warning)",
  },
  rate_limited: {
    label: "Slowed down",
    help: "Bursts throttled so forwarding stays smooth.",
    color: "var(--warning)",
  },
};

export function reasonLabel(reason: string): string {
  return REASON_META[reason]?.label ?? reason;
}

export function reasonHelp(reason: string): string {
  return REASON_META[reason]?.help ?? "";
}

export function reasonColor(reason: string): string {
  return REASON_META[reason]?.color ?? "var(--muted)";
}

/** "premium, extra" -> "Premium, Extra". Falls back to "Free". */
export function planLabel(tier: string, tiers: string[]): string {
  const parts = tiers.length > 0 ? tiers : [tier || "free"];
  return parts
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(", ");
}
