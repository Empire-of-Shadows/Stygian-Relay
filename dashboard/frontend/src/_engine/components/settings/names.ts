/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
/*
 * Discord name rules for the dashboard's Create role / Create channel controls.
 *
 * A line-for-line port of backend/discord_objects.py, which itself matches the
 * admin panel (admin_engine/actions/discord_objects/create.py). The server is the
 * one that decides; this copy exists so the form can show the name a text channel
 * will actually get while it is typed, and refuse a bad one before a round trip.
 * Change all three together.
 */

export type CreatableKind = "text" | "voice" | "category";

/** Discord channel type numbers for the kinds a dashboard may create. */
export const CHANNEL_KIND_TYPES: Record<CreatableKind, number> = {
  text: 0,
  voice: 2,
  category: 4,
};

export const MAX_NAME_LENGTH = 100;

export interface NameCheck {
  ok: boolean;
  /** The name that will be sent (normalised for text channels). */
  name: string | null;
  error: string;
}

const RESERVED_ROLE_NAMES = new Set(["everyone", "@everyone", "here", "@here"]);
const TEXT_CHANNEL_CHAR = /^[a-z0-9-]$/;

function basicName(raw: string, what: string): NameCheck {
  const name = (raw ?? "").trim();
  if (!name) return { ok: false, name: null, error: `${what} name cannot be empty.` };
  if (name.length > MAX_NAME_LENGTH) {
    return {
      ok: false,
      name: null,
      error: `${what} name must be ${MAX_NAME_LENGTH} characters or fewer.`,
    };
  }
  return { ok: true, name, error: "" };
}

export function validateRoleName(raw: string): NameCheck {
  const base = basicName(raw, "Role");
  if (!base.ok || base.name === null) return base;
  if (RESERVED_ROLE_NAMES.has(base.name.toLowerCase())) {
    return { ok: false, name: null, error: "That name is reserved by Discord. Pick another name." };
  }
  return base;
}

export function validateTextChannelName(raw: string): NameCheck {
  const base = basicName(raw, "Channel");
  if (!base.ok || base.name === null) return base;
  const name = base.name
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  if (!name) {
    return {
      ok: false,
      name: null,
      error: "Channel name must include at least one letter or number.",
    };
  }
  const bad = [...new Set([...name].filter((c) => !TEXT_CHANNEL_CHAR.test(c)))].sort();
  if (bad.length > 0) {
    return {
      ok: false,
      name: null,
      error:
        'Channel names can only use lowercase letters, numbers, and "-" ' +
        "(spaces and capitals are converted automatically). " +
        `Remove: ${bad.map((c) => `"${c}"`).join(", ")}.`,
    };
  }
  return { ok: true, name, error: "" };
}

export function validateChannelName(kind: CreatableKind, raw: string): NameCheck {
  if (kind === "text") return validateTextChannelName(raw);
  return basicName(raw, kind === "category" ? "Category" : "Channel");
}

/**
 * The kinds a channel picker can offer to create, from the channel types it
 * accepts. Text when it takes text channels, voice when it takes voice
 * channels, both when it takes both, a category when it takes categories. A
 * picker with no type filter offers text, like the panel. Announcement, stage
 * and forum channels need server features a bot cannot assume, so they are
 * never offered.
 */
export function creatableKinds(types: number[] | undefined): CreatableKind[] {
  if (!types || types.length === 0) return ["text"];
  const out: CreatableKind[] = [];
  if (types.includes(CHANNEL_KIND_TYPES.text)) out.push("text");
  if (types.includes(CHANNEL_KIND_TYPES.voice)) out.push("voice");
  if (types.includes(CHANNEL_KIND_TYPES.category)) out.push("category");
  return out;
}
