import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Channel, GuildConfig, GuildOverview, Role } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import {
  ChannelField,
  Fieldset,
  FRow,
  PickerStatusProvider,
  RoleField,
  TextareaField,
  ToggleField,
} from "../_engine/components/settings/fields";
import ContextColumn from "../components/settings/ContextColumn";

/*
 * Server settings.
 *
 * This replaced a single card holding four raw snowflake boxes. The layout is
 * now the shared rail + reading-width form column + context column: the rail
 * says what state each area is in, the form asks for one area at a time, and
 * the context column shows what that area is actually doing right now.
 *
 * Every setting that was here before is still here and still writes the same
 * field through the same PUT. Two of them became pickers instead of snowflake
 * boxes, matching what the Discord admin panel already offered for the same two
 * settings. Nothing autosaves; each area has its own Save button, and editing
 * one area never discards unsaved edits in another.
 */

// ---------------------------------------------------------------------------
// Rail definition
// ---------------------------------------------------------------------------

type Slug = "forwarding" | "cross_server" | "logging" | "access";

/** The draft fields each rail entry owns. Save and dirty-checking both use it. */
type DraftField =
  | "is_enabled"
  | "notify_on_error"
  | "inbound_text"
  | "master_log_channel_id"
  | "manager_role_id";

interface Draft {
  is_enabled: boolean;
  notify_on_error: boolean;
  master_log_channel_id: string | null;
  manager_role_id: string | null;
  /** Kept as raw text so a half-typed list is not thrown away on every stroke. */
  inbound_text: string;
}

interface RailItem {
  slug: Slug;
  label: string;
  title: string;
  blurb: string;
  fields: DraftField[];
  /** Terms the rail search box matches on. */
  search: string[];
}

const RAIL_GROUPS: { name: string; items: RailItem[] }[] = [
  {
    name: "Relay",
    items: [
      {
        slug: "forwarding",
        label: "Forwarding",
        title: "Forwarding",
        blurb:
          "The master switch for this server. With it off, no rule fires and nothing is copied anywhere, however many rules you have. Error notices are the short in-channel message the bot posts when it has to stop forwarding.",
        fields: ["is_enabled", "notify_on_error"],
        search: [
          "Forwarding enabled",
          "Master switch",
          "Turn the bot on or off",
          "Error notices",
          "Notify on error",
          "Rate limit warning",
        ],
      },
      {
        slug: "cross_server",
        label: "Cross-server",
        title: "Cross-server forwarding",
        blurb:
          "Which other servers are allowed to forward messages into this one. This is your side of the handshake: a rule in another server only reaches you if that server's ID is listed here. Leave it empty to block every inbound forward. Rules that stay inside this server are unaffected.",
        fields: ["inbound_text"],
        search: [
          "Inbound allowlist",
          "Allowed inbound guilds",
          "Cross-guild forwarding",
          "Servers allowed to forward in",
        ],
      },
      {
        slug: "logging",
        label: "Activity log",
        title: "Activity log",
        blurb:
          "A channel where the bot writes what it is doing - premium changes, errors, and rules it had to switch off. Leave it unset and the bot simply keeps quiet.",
        fields: ["master_log_channel_id"],
        search: ["Log channel", "Master log channel", "Activity log", "Where errors are posted"],
      },
    ],
  },
  {
    name: "Access",
    items: [
      {
        slug: "access",
        label: "Who can manage",
        title: "Who can manage",
        blurb:
          "Members with this role get the same access to the admin panel and this dashboard as someone with Manage Server. It is full access, not a limited tier. Everyone else sees nothing here.",
        fields: ["manager_role_id"],
        search: [
          "Manager role",
          "Who can manage",
          "Panel access",
          "Admin role",
          "Delegate access",
        ],
      },
    ],
  },
];

const RAIL_ITEMS: RailItem[] = RAIL_GROUPS.flatMap((group) => group.items);

const DEFAULT_SLUG: Slug = "forwarding";

function parseSlug(raw: string | null): Slug {
  const hit = RAIL_ITEMS.find((item) => item.slug === raw);
  return hit ? hit.slug : DEFAULT_SLUG;
}

/** Terms that reach the two rail links out of this page. */
const RULES_SEARCH = ["Forwarding rules", "Routes", "Source channel", "Destination channel"];
const AUDIT_SEARCH = ["Audit log", "History of changes", "Who changed a setting and when"];

// ---------------------------------------------------------------------------
// Draft helpers
// ---------------------------------------------------------------------------

/** The list, parsed the same way the old single form parsed it. */
export function parseGuildIds(raw: string): string[] {
  return raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
}

function toDraft(config: GuildConfig): Draft {
  const features = config.features ?? {};
  const notify = features["notify_on_error"];
  return {
    is_enabled: config.is_enabled ?? true,
    // Matches the bot's own default (DEFAULT_GUILD_SETTINGS_TEMPLATE), so a
    // config written before this switch existed reads as on, not off.
    notify_on_error: notify === undefined ? true : Boolean(notify),
    master_log_channel_id: config.master_log_channel_id ?? null,
    manager_role_id: config.manager_role_id ?? null,
    inbound_text: (config.inbound_allowed_guilds ?? []).join(", "),
  };
}

function fieldDirty(field: DraftField, draft: Draft, saved: Draft): boolean {
  if (field === "inbound_text") {
    // Compared as parsed lists, so re-typing the same ids with different
    // spacing is not a change - exactly what the old form did.
    return (
      JSON.stringify(parseGuildIds(draft.inbound_text)) !==
      JSON.stringify(parseGuildIds(saved.inbound_text))
    );
  }
  return draft[field] !== saved[field];
}

/**
 * Options for a picker, guaranteeing the value already saved is one of them.
 *
 * The channel and role listings are filtered (text channels only; no managed or
 * @everyone roles), so a value saved from Discord's own admin panel can be
 * absent from the list. Without this the select would fall back to "not set"
 * and the next save would silently clear a setting nobody touched.
 */
function withSavedOption<T extends { id: string; name: string }>(
  options: T[],
  savedId: string | null,
  make: (id: string) => T,
): T[] {
  if (!savedId || options.some((option) => option.id === savedId)) return options;
  return [...options, make(savedId)];
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function ConfigPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const [config, setConfig] = useState<GuildConfig | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState<Draft | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [channelsFailed, setChannelsFailed] = useState(false);
  const [rolesFailed, setRolesFailed] = useState(false);
  const [overview, setOverview] = useState<GuildOverview | null>(null);
  const [savingSlug, setSavingSlug] = useState<Slug | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "danger"; text: string } | null>(null);
  const [query, setQuery] = useState("");

  const slug = parseSlug(searchParams.get("s"));

  useEffect(() => {
    if (!guildId) return;
    setMessage(null);
    setLoadError(null);

    api.config(guildId)
      .then((c) => {
        setConfig(c);
        const next = toDraft(c);
        setDraft(next);
        setSaved(next);
      })
      .catch((e) => setLoadError(formatError(e)));

    // Loaded separately from the config so a permission problem on one of them
    // cannot blank the page. When one fails the picker says so rather than
    // showing an empty dropdown that reads as "this server has none".
    api.channels(guildId)
      .then((list) => { setChannels(list); setChannelsFailed(false); })
      .catch(() => { setChannels([]); setChannelsFailed(true); });

    api.roles(guildId)
      .then((list) => { setRoles(list); setRolesFailed(false); })
      .catch(() => { setRoles([]); setRolesFailed(true); });

    // Optional. The context column drops the rows it cannot fill.
    api.overview(guildId)
      .then(setOverview)
      .catch(() => setOverview(null));
  }, [guildId]);

  const channelOptions = useMemo(
    () => withSavedOption(
      channels,
      saved?.master_log_channel_id ?? null,
      (id) => ({ id, name: `channel ${id}`, type: 0, parent_id: null, position: -1 }),
    ),
    [channels, saved],
  );

  const roleOptions = useMemo(
    () => withSavedOption(
      roles,
      saved?.manager_role_id ?? null,
      (id) => ({ id, name: `Role ${id}`, color: 0, position: -1 }),
    ),
    [roles, saved],
  );

  if (!guildId) return null;

  if (loadError) {
    return (
      <div className="page">
        <div className="alert danger" role="alert" style={{ marginTop: 16 }}>{loadError}</div>
      </div>
    );
  }

  if (!config || !draft || !saved) {
    return (
      <div className="page">
        <p className="muted" style={{ padding: 24 }}>Loading settings...</p>
      </div>
    );
  }

  const isDirty = (item: RailItem): boolean =>
    item.fields.some((field) => fieldDirty(field, draft, saved));

  const active = RAIL_ITEMS.find((item) => item.slug === slug) ?? RAIL_ITEMS[0];
  const activeDirty = isDirty(active);

  const update = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  const goTo = (next: Slug) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        params.set("s", next);
        return params;
      },
      { replace: true },
    );
  };

  /** Build the wire patch for one rail entry - only the fields that changed. */
  const patchFor = (item: RailItem): Partial<GuildConfig> => {
    const patch: Partial<GuildConfig> = {};
    for (const field of item.fields) {
      if (!fieldDirty(field, draft, saved)) continue;
      if (field === "is_enabled") {
        patch.is_enabled = draft.is_enabled;
      } else if (field === "notify_on_error") {
        // Sent as a features patch, which the API expands to a dotted
        // `features.notify_on_error` write. It deliberately does not carry
        // `forwarding_enabled`, so the API's is_enabled mirroring still runs.
        patch.features = { ...(patch.features ?? {}), notify_on_error: draft.notify_on_error };
      } else if (field === "master_log_channel_id") {
        patch.master_log_channel_id = draft.master_log_channel_id || null;
      } else if (field === "manager_role_id") {
        patch.manager_role_id = draft.manager_role_id || null;
      } else if (field === "inbound_text") {
        patch.inbound_allowed_guilds = parseGuildIds(draft.inbound_text);
      }
    }
    return patch;
  };

  const save = async (item: RailItem) => {
    const patch = patchFor(item);
    if (Object.keys(patch).length === 0) return;
    setSavingSlug(item.slug);
    setMessage(null);
    try {
      await api.saveConfig(guildId, patch);
      const updated = await api.config(guildId);
      const fresh = toDraft(updated);
      setConfig(updated);
      setSaved(fresh);
      // Only the fields just saved take the server's version; unsaved edits in
      // the other rail entries are left exactly as the admin typed them.
      const picked = Object.fromEntries(
        item.fields.map((field) => [field, fresh[field]]),
      ) as Partial<Draft>;
      setDraft((prev) => (prev ? { ...prev, ...picked } : fresh));
      setMessage({ kind: "success", text: `Saved ${item.title.toLowerCase()}.` });
      // The context column reads live state, so refresh it after a write.
      api.overview(guildId).then(setOverview).catch(() => {});
    } catch (e) {
      setMessage({ kind: "danger", text: formatError(e, "Save failed.") });
    } finally {
      setSavingSlug(null);
    }
  };

  const q = query.trim().toLowerCase();
  const itemMatches = (item: RailItem): boolean => {
    if (!q) return true;
    if (item.label.toLowerCase().includes(q)) return true;
    if (item.title.toLowerCase().includes(q)) return true;
    return item.search.some((term) => term.toLowerCase().includes(q));
  };
  const rulesMatches = !q || RULES_SEARCH.some((term) => term.toLowerCase().includes(q));
  const auditMatches = !q || AUDIT_SEARCH.some((term) => term.toLowerCase().includes(q));
  const anyMatch = RAIL_ITEMS.some(itemMatches) || rulesMatches || auditMatches;

  return (
    <div className="page">
      <div className="page-header" style={{ paddingTop: 16 }}>
        <div>
          <Link to={`/me?guild=${guildId}`} className="muted" style={{ fontSize: 13 }}>
            &larr; Server overview
          </Link>
          <h1 style={{ marginTop: 4 }}>Server settings</h1>
        </div>
      </div>

      {message && (
        <div className={`alert ${message.kind}`} role="status">{message.text}</div>
      )}

      <div className="set-layout">
        <div>
          <div className="set-search">
            <span className="set-search__i" aria-hidden="true">&#8981;</span>
            <input
              type="search"
              value={query}
              placeholder="Search settings"
              aria-label="Search settings"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <nav className="set-rail" aria-label="Settings sections">
            {RAIL_GROUPS.map((group) => {
              const items = group.items.filter(itemMatches);
              const showRules = group.name === "Relay" && rulesMatches;
              const showAudit = group.name === "Access" && auditMatches;
              if (items.length === 0 && !showRules && !showAudit) return null;
              return (
                <Fragment key={group.name}>
                  <div className="set-rail__grp">{group.name}</div>
                  {items.map((item) => {
                    const badge = isDirty(item)
                      ? { text: "Unsaved", tone: "warn" }
                      : railBadge(item.slug, draft);
                    return (
                      <button
                        key={item.slug}
                        type="button"
                        className={"set-rail__item" + (item.slug === slug ? " is-active" : "")}
                        aria-current={item.slug === slug ? "page" : undefined}
                        onClick={() => goTo(item.slug)}
                      >
                        <span>{item.label}</span>
                        <span
                          className={
                            "set-rail__badge" + (badge.tone ? ` set-rail__badge--${badge.tone}` : "")
                          }
                        >
                          {badge.text}
                        </span>
                      </button>
                    );
                  })}
                  {showRules && (
                    <Link className="set-rail__item" to={`/guilds/${guildId}/rules`}>
                      <span>Forwarding rules</span>
                    </Link>
                  )}
                  {showAudit && (
                    <Link className="set-rail__item" to={`/guilds/${guildId}/audit-log`}>
                      <span>Audit log</span>
                    </Link>
                  )}
                </Fragment>
              );
            })}
            {!anyMatch && (
              <p className="set-rail__empty">Nothing here matches "{query.trim()}".</p>
            )}
          </nav>
        </div>

        <PickerStatusProvider value={{ channelsFailed, rolesFailed }}>
          <div className="set-main">
            <div className="set-head">
              <h1>{active.title}</h1>
              <p>{active.blurb}</p>
            </div>

            {slug === "forwarding" && (
              <Fieldset title="Switches">
                <FRow full>
                  <ToggleField
                    label="Forward messages in this server"
                    value={draft.is_enabled}
                    onChange={(v) => update({ is_enabled: v })}
                    description="Off means no rule fires, whatever it is set to."
                  />
                  <ToggleField
                    label="Post a notice when forwarding is blocked"
                    value={draft.notify_on_error}
                    onChange={(v) => update({ notify_on_error: v })}
                    description="A short message in the source channel when the daily cap is hit, so nobody wonders where their message went. It deletes itself after a minute."
                  />
                </FRow>
              </Fieldset>
            )}

            {slug === "cross_server" && (
              <Fieldset title="Inbound allowlist">
                <FRow full>
                  <TextareaField
                    label="Server IDs allowed to forward into this server"
                    value={draft.inbound_text}
                    onChange={(v) => update({ inbound_text: v })}
                    placeholder="123456789012345678, 234567890123456789"
                    description="Separate IDs with commas or spaces. Empty blocks every inbound forward from another server."
                    rows={3}
                  />
                </FRow>
                <p className="eos-muted" style={{ margin: 0 }}>
                  {parseGuildIds(draft.inbound_text).length === 0
                    ? "No other server may forward into this one."
                    : `${parseGuildIds(draft.inbound_text).length} server ID(s) listed.`}
                </p>
              </Fieldset>
            )}

            {slug === "logging" && (
              <Fieldset title="Where the bot writes">
                <FRow full>
                  <ChannelField
                    label="Log channel"
                    value={draft.master_log_channel_id}
                    channels={channelOptions}
                    filterType={0}
                    onChange={(v) => update({ master_log_channel_id: v })}
                    description="Text channels only, matching what the Discord admin panel offers."
                  />
                </FRow>
              </Fieldset>
            )}

            {slug === "access" && (
              <Fieldset title="Delegated access">
                <FRow full>
                  <RoleField
                    label="Manager role"
                    value={draft.manager_role_id}
                    roles={roleOptions}
                    onChange={(v) => update({ manager_role_id: v })}
                    description="One role only. Holding it is the same as having Manage Server as far as this bot is concerned."
                  />
                </FRow>
              </Fieldset>
            )}

            <div className="savebar">
              <button
                type="button"
                className="btn btn-primary"
                disabled={!activeDirty || savingSlug === active.slug}
                onClick={() => save(active)}
              >
                {savingSlug === active.slug ? "Saving..." : "Save"}
              </button>
              <span className="muted" style={{ fontSize: 13 }}>
                {activeDirty ? "Unsaved changes" : "Everything here is saved"}
              </span>
            </div>
          </div>
        </PickerStatusProvider>

        <aside className="set-ctx" aria-label="Current state">
          <ContextColumn
            slug={slug}
            draft={draft}
            channels={channelOptions}
            roles={roleOptions}
            overview={overview}
          />
        </aside>
      </div>
    </div>
  );
}

/**
 * What the rail badge says about an area.
 *
 * "Set up" is the load-bearing one: switched on but missing the thing it cannot
 * run without, which is the state that looks fine and silently does nothing.
 */
function railBadge(slug: Slug, draft: Draft): { text: string; tone: string } {
  switch (slug) {
    case "forwarding":
      return draft.is_enabled ? { text: "On", tone: "ok" } : { text: "Off", tone: "" };
    case "cross_server": {
      const count = parseGuildIds(draft.inbound_text).length;
      return count > 0 ? { text: String(count), tone: "ok" } : { text: "None", tone: "" };
    }
    case "logging":
      return draft.master_log_channel_id
        ? { text: "On", tone: "ok" }
        : { text: "Off", tone: "" };
    case "access":
      return draft.manager_role_id ? { text: "1 role", tone: "ok" } : { text: "None", tone: "" };
  }
}
