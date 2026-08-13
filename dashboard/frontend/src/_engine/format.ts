/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
/** Shared formatting for the dashboard home. Plain wording, no flavour text. */

/** Compact big numbers: 1200 -> "1.2k". */
export function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}

/** "12 Jul 2026", or "-" when there is nothing to show. */
export function formatDate(iso: string | null): string {
  const d = parseIso(iso);
  if (!d) return "-";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** "12 Jul" - used where the year is noise. */
export function formatShortDate(iso: string | null): string {
  const d = parseIso(iso);
  if (!d) return "-";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** "09:00" in the reader's own locale and zone. */
export function formatClock(iso: string | null): string {
  const d = parseIso(iso);
  if (!d) return "-";
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** "12 Jul, 09:00". */
export function formatDateTime(iso: string | null): string {
  const d = parseIso(iso);
  if (!d) return "-";
  return `${formatShortDate(iso)}, ${formatClock(iso)}`;
}

/** "3 days ago" / "just now". Falls back to a date past a month. */
export function formatRelative(iso: string | null): string {
  const d = parseIso(iso);
  if (!d) return "never";
  const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
  if (seconds < 0) return formatDate(iso);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  if (days < 31) return `${days} day${days === 1 ? "" : "s"} ago`;
  return formatDate(iso);
}

/** Tight age for a list row: "6d", "3h", "now". */
export function formatAge(iso: string | null): string {
  const d = parseIso(iso);
  if (!d) return "-";
  const seconds = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (seconds < 3600) return "now";
  const hours = Math.floor(seconds / 3600);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

/** Trend x-axis label from a "YYYY-MM-DD" day key. */
export function formatDayLabel(day: string): string {
  const parsed = parseDayKey(day);
  if (!parsed) return day;
  return parsed.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Monthly bucket label. Accepts "YYYY-MM" and passes anything else through. */
export function formatMonthLabel(month: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return month;
  const d = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  return d.toLocaleDateString(undefined, { month: "short" });
}

/** Whole days as friendly length: "26 days", "2 months, 4 days". */
export function formatDayCount(days: number): string {
  if (days < 0) return "-";
  if (days < 31) return `${days} day${days === 1 ? "" : "s"}`;
  const months = Math.floor(days / 30);
  const rest = days % 30;
  const monthPart = `${months} month${months === 1 ? "" : "s"}`;
  if (rest === 0) return monthPart;
  return `${monthPart}, ${rest} day${rest === 1 ? "" : "s"}`;
}

/** A remaining day count as time left: "none left", "3 months left". */
export function formatRunway(daysLeft: number): string {
  if (daysLeft <= 0) return "none left";
  if (daysLeft >= 730) return `${Math.round(daysLeft / 365)} years left`;
  if (daysLeft >= 60) return `${Math.round(daysLeft / 30)} months left`;
  return `${daysLeft} day${daysLeft === 1 ? "" : "s"} left`;
}

/** Link to a Discord channel, thread or server. */
export function discordLink(guildId: string, channelId?: string | null): string {
  return channelId
    ? `https://discord.com/channels/${guildId}/${channelId}`
    : `https://discord.com/channels/${guildId}`;
}

function parseIso(iso: string | null): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * "YYYY-MM-DD" is a calendar day, not an instant. `new Date()` reads it as UTC
 * midnight, which renders as the previous day west of Greenwich, so build the
 * date from its parts instead.
 */
function parseDayKey(day: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}
