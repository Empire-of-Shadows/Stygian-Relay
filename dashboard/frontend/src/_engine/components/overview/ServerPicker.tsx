/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { useEffect, useRef, useState } from "react";
import type { Guild } from "../../api/types";
import GuildIcon from "./GuildIcon";

interface ServerPickerProps {
  guilds: Guild[];
  selectedGuildId: string | null;
  onSelect: (guildId: string | null) => void;
  /** Second line under the server name. */
  meta: string;
}

const ALL_SERVERS_LABEL = "All servers";

/**
 * Which server the page is about.
 *
 * Replaces the pill strip, which grew a horizontal scrollbar as soon as
 * somebody was in more than a handful of servers.
 *
 * The wrapper carries no class on purpose. The popover is absolutely
 * positioned with `top`/`left` unset, so it lands at its static position -
 * directly under the button - without needing a positioned ancestor.
 */
export default function ServerPicker({
  guilds,
  selectedGuildId,
  onSelect,
  meta,
}: ServerPickerProps) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const selected = guilds.find((g) => g.id === selectedGuildId) ?? null;
  const name = selected ? selected.name : ALL_SERVERS_LABEL;

  const choose = (guildId: string | null) => {
    setOpen(false);
    onSelect(guildId);
  };

  return (
    <div ref={wrapRef}>
      <button
        type="button"
        ref={buttonRef}
        className="serverpick"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {selected ? (
          <GuildIcon id={selected.id} icon={selected.icon} name={selected.name} />
        ) : (
          <span className="serverpick__icon" aria-hidden="true">
            All
          </span>
        )}
        <span>
          <span className="serverpick__name">{name}</span>
          <span className="serverpick__meta">{meta}</span>
        </span>
        <span className="serverpick__chev" aria-hidden="true">
          &#9660;
        </span>
      </button>

      {open && (
        <div className="serverlist" role="group" aria-label="Choose a server">
          <button
            type="button"
            className={`serverlist__item${selectedGuildId === null ? " is-active" : ""}`}
            aria-current={selectedGuildId === null}
            onClick={() => choose(null)}
          >
            <span className="serverpick__icon" aria-hidden="true">
              All
            </span>
            {ALL_SERVERS_LABEL}
          </button>

          {guilds.map((guild) => (
            <button
              key={guild.id}
              type="button"
              className={`serverlist__item${guild.id === selectedGuildId ? " is-active" : ""}`}
              aria-current={guild.id === selectedGuildId}
              onClick={() => choose(guild.id)}
            >
              <GuildIcon id={guild.id} icon={guild.icon} name={guild.name} size={32} />
              {guild.name}
              <span className="serverlist__tag">{tagFor(guild)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function tagFor(guild: Guild): string {
  if (guild.setup_required) return "not added";
  if (guild.panel_role === "admin") return "manage";
  return "member";
}

/**
 * The line under the server name in the button.
 *
 * `botName` names the bot in the "not added yet" line. It defaults to the
 * neutral "The bot" so a caller that passes nothing still reads correctly.
 */
export function pickerMeta(
  guild: Guild | null,
  guildCount: number,
  botName: string = "The bot",
): string {
  if (!guild) {
    return guildCount === 1
      ? "Everything from your one server"
      : `Everything across your ${guildCount} servers`;
  }
  if (guild.setup_required) return `${botName} is not in this server yet`;
  if (guild.panel_role === "admin") return "You manage this server";
  return "You are a member here";
}
