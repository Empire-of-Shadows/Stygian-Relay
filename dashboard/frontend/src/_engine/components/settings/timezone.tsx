/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { useId, useState } from "react";
import { TIMEZONE_REGIONS, TIMEZONE_ZONES } from "./timezones";

/*
 * Timezone picker: region first, then zone (added 2026-11-20).
 *
 * The same two steps as the Discord admin panel, over the same list (timezones.ts
 * is generated from the panel's own module), with the same labels: a zone reads
 * "New York - UTC-05:00", the offset worked out now so daylight saving is right.
 *
 * Picking a region does not change the setting on its own. The zone list switches
 * and asks for a zone, and until one is picked the saved timezone stays as it was
 * and the field says so. A saved value the list does not carry (an older name
 * like US/Central) is shown as it is, never silently swapped for another zone.
 */

const REGION_PREFIXES = new Set(TIMEZONE_REGIONS.map(([p]) => p));

/** The region a zone belongs to, by the panel's rule. */
export function timezoneRegion(tz: string): string {
  const prefix = tz.split("/", 1)[0];
  return REGION_PREFIXES.has(prefix) ? prefix : "Etc";
}

/** "America/New_York" -> "New York"; "America/Argentina/Salta" -> "Argentina / Salta". */
export function prettyZone(tz: string): string {
  const tail = tz.includes("/") ? tz.slice(tz.indexOf("/") + 1) : tz;
  return tail.replace(/_/g, " ").replace(/\//g, " / ");
}

/** Current offset as "UTC+02:00" / "UTC-05:00", like the panel. Empty when the
 *  browser does not know the zone. */
export function offsetLabel(tz: string, at: Date = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "longOffset" })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName")?.value;
    if (!part) return "";
    const m = /^GMT(?:([+-])(\d{1,2})(?::?(\d{2}))?)?$/.exec(part.replace("−", "-"));
    if (!m) return "";
    if (!m[1]) return "UTC+00:00";
    return `UTC${m[1]}${m[2].padStart(2, "0")}:${m[3] ?? "00"}`;
  } catch {
    return "";
  }
}

/** "New York - UTC-05:00", or just the name when the offset is unknown. */
export function timezoneLabel(tz: string): string {
  const off = offsetLabel(tz);
  return off ? `${prettyZone(tz)} - ${off}` : prettyZone(tz);
}

export function TimezoneField({
  label = "Timezone",
  value,
  onChange,
  disabled,
  description,
}: {
  label?: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  description?: string;
}) {
  const id = useId();
  const savedRegion = timezoneRegion(value);
  // Only differs from the saved value's region while a new region is being
  // browsed and no zone in it has been picked yet.
  const [browsing, setBrowsing] = useState<string | null>(null);
  const region = browsing ?? savedRegion;
  const zones = TIMEZONE_ZONES[region] ?? [];
  const listed = zones.includes(value);
  // A saved name the panel's list does not carry is shown raw, not prettified.
  const savedListed = (TIMEZONE_ZONES[savedRegion] ?? []).includes(value);
  const regionLabel = (p: string) => TIMEZONE_REGIONS.find(([k]) => k === p)?.[1] ?? p;

  return (
    <div className="eos-field">
      <label htmlFor={`${id}-region`}>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>
          {description}
        </p>
      )}
      <div className="eos-tz">
        <select
          id={`${id}-region`}
          aria-label={`${label}: region`}
          value={region}
          disabled={disabled}
          onChange={(e) => {
            const next = e.target.value;
            setBrowsing(next === savedRegion ? null : next);
          }}
        >
          {TIMEZONE_REGIONS.map(([prefix, name]) => (
            <option key={prefix} value={prefix}>
              {name}
            </option>
          ))}
        </select>
        <select
          aria-label={`${label}: zone`}
          value={listed ? value : ""}
          disabled={disabled}
          onChange={(e) => {
            if (!e.target.value) return;
            setBrowsing(null);
            onChange(e.target.value);
          }}
        >
          {!listed && (
            <option value="" disabled>
              -- pick a zone --
            </option>
          )}
          {zones.map((tz) => (
            <option key={tz} value={tz}>
              {timezoneLabel(tz)}
            </option>
          ))}
        </select>
      </div>
      {!listed && value && (
        <p className="eos-muted eos-tz__note">
          Still saved:{" "}
          {savedListed
            ? `${timezoneLabel(value)} (${regionLabel(savedRegion)})`
            : `${value}${offsetLabel(value) ? ` (${offsetLabel(value)})` : ""}`}
          . Pick a zone to change it.
        </p>
      )}
    </div>
  );
}
