import { useEffect, useRef, useState } from "react";
import "./styles/EcosystemNav.css";

/**
 * Empire of Shadows — cross-app "Warp" dropdown.
 *
 * One eye-catching switcher shared (copy-per-repo, byte-identical) across every
 * surface: the four React dashboards and the Jinja hub. The current app is
 * auto-detected from the hostname so this file needs zero per-repo config.
 *
 * Keep this list and the markup in sync with the hub's Jinja partial:
 *   Website/EmpiresWeb/partials/buttons/html/ecosystem-nav.html
 */
interface EcoApp {
  key: string;
  name: string;
  tagline: string;
  icon: string;
  href: string;
  /** hostname prefix used to detect the active app */
  host: string;
}

const APPS: EcoApp[] = [
  { key: "hub", name: "Empire", tagline: "Main site", icon: "🏰", href: "https://eosofficial.club", host: "eosofficial.club" },
  { key: "host", name: "TheHost", tagline: "Events & games", icon: "🎉", href: "https://host.eosofficial.club", host: "host.eosofficial.club" },
  { key: "codex", name: "TheCodex", tagline: "Guide, polls & profiles", icon: "📖", href: "https://codex.eosofficial.club", host: "codex.eosofficial.club" },
  { key: "ecom", name: "Ecom", tagline: "Leveling & economy", icon: "💰", href: "https://ecom.eosofficial.club", host: "ecom.eosofficial.club" },
  { key: "reminder", name: "Reminder", tagline: "Bump reminders", icon: "⏰", href: "https://reminder.eosofficial.club", host: "reminder.eosofficial.club" },
  { key: "decree", name: "Quotes", tagline: "Scheduled quotes", icon: "💬", href: "https://decree.eosofficial.club", host: "decree.eosofficial.club" },
  { key: "relay", name: "Stygian Relay", tagline: "Message forwarding", icon: "🔀", href: "https://relay.eosofficial.club", host: "relay.eosofficial.club" },
  { key: "health", name: "Health", tagline: "System status", icon: "🛡️", href: "https://health.eosofficial.club", host: "health.eosofficial.club" },
];

function detectActiveKey(): string | null {
  if (typeof window === "undefined") return null;
  const h = window.location.hostname;
  // Most specific first so "host.eosofficial.club" wins over the bare hub.
  const match = [...APPS]
    .sort((a, b) => b.host.length - a.host.length)
    .find((app) => h === app.host || h.endsWith("." + app.host) || h === app.host.split(".")[0]);
  return match ? match.key : null;
}

export function EcosystemNav() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const activeKey = detectActiveKey();

  useEffect(() => {
    if (!open) return;
    function onPointer(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="eco-nav" ref={rootRef}>
      <button
        type="button"
        className={"eco-nav__trigger" + (open ? " is-open" : "")}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Empire of Shadows apps"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="eco-nav__trigger-mark" aria-hidden="true">✦</span>
        <span className="eco-nav__trigger-text">Empire</span>
        <span className="eco-nav__chevron" aria-hidden="true">▾</span>
      </button>

      {open && (
        <div className="eco-nav__panel" role="menu" aria-label="Empire of Shadows ecosystem">
          <div className="eco-nav__panel-head">Empire of Shadows</div>
          <div className="eco-nav__list">
            {APPS.map((app, i) => {
              const isActive = app.key === activeKey;
              return (
                <a
                  key={app.key}
                  className={"eco-nav__item" + (isActive ? " is-active" : "")}
                  href={isActive ? undefined : app.href}
                  role="menuitem"
                  rel="noopener"
                  aria-current={isActive ? "page" : undefined}
                  style={{ "--eco-i": i } as React.CSSProperties}
                  tabIndex={isActive ? -1 : 0}
                  onClick={isActive ? (e) => e.preventDefault() : undefined}
                >
                  <span className="eco-nav__icon" aria-hidden="true">{app.icon}</span>
                  <span className="eco-nav__text">
                    <span className="eco-nav__name">{app.name}</span>
                    <span className="eco-nav__tagline">{app.tagline}</span>
                  </span>
                  {isActive ? (
                    <span className="eco-nav__badge">Here</span>
                  ) : (
                    <span className="eco-nav__dot" aria-hidden="true" />
                  )}
                </a>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
