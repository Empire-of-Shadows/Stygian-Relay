/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
/**
 * Static option lists shared by every bot's admin settings form.
 *
 * Only lists with no bot-specific knowledge live here - timezones, clock hours
 * and minutes, and Discord's own fixed thread auto-archive values. Anything
 * that belongs to one bot's features stays in that bot's own `options.ts`.
 *
 * The Discord admin panel and this dashboard write the same config keys, so a
 * value that exists on one side but not the other is a real bug - change both
 * together, never one alone.
 */

export const TIMEZONE_OPTIONS: [string, string][] = [
  ["America/New_York", "US Eastern"],
  ["America/Chicago", "US Central"],
  ["America/Denver", "US Mountain"],
  ["America/Los_Angeles", "US Pacific"],
  ["Europe/London", "UK / GMT"],
  ["Europe/Paris", "Central Europe"],
  ["Europe/Berlin", "Germany"],
  ["Asia/Tokyo", "Japan"],
  ["Australia/Sydney", "Australia Eastern"],
];

export const HOUR_OPTIONS: [number, string][] = Array.from({ length: 24 }, (_, h) => [
  h,
  `${String(h).padStart(2, "0")}:00`,
]);

export const MINUTE_OPTIONS: [number, string][] = [
  [0, ":00"],
  [15, ":15"],
  [30, ":30"],
  [45, ":45"],
];

export const ARCHIVE_OPTIONS: [number, string][] = [
  [60, "1 Hour"],
  [1440, "1 Day"],
  [4320, "3 Days"],
  [10080, "1 Week"],
];

/** Look up a label from one of the lists above, falling back to the raw value. */
export function optionLabel<V extends string | number>(
  options: [V, string][],
  value: V,
): string {
  const hit = options.find(([v]) => v === value);
  return hit ? hit[1] : String(value);
}
