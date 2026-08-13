/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { useState } from "react";

interface GuildIconProps {
  id: string;
  icon: string | null | undefined;
  name: string;
  /** Requested CDN size. The stylesheet decides the rendered box. */
  size?: 32 | 64 | 96;
}

/**
 * Server avatar with a letter fallback.
 *
 * The fallback covers both cases: no icon hash at all, and a hash whose image
 * 404s (Discord keeps returning stale hashes after an icon is removed).
 */
export default function GuildIcon({ id, icon, name, size = 64 }: GuildIconProps) {
  const [broken, setBroken] = useState(false);
  const letter = name.trim().charAt(0).toUpperCase() || "?";

  return (
    <span className="serverpick__icon" aria-hidden="true">
      {!icon || broken ? (
        letter
      ) : (
        <img
          src={`https://cdn.discordapp.com/icons/${id}/${icon}.png?size=${size}`}
          alt=""
          loading="lazy"
          onError={() => setBroken(true)}
        />
      )}
    </span>
  );
}
