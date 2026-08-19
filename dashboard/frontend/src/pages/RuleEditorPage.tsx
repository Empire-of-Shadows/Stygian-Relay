import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  AdvancedOptions,
  AuthorFilters,
  Channel,
  GuildOverview,
  MessageTypes,
  Role,
  Rule,
  RuleFilters,
  RuleFormatting,
  RuleWriteBody,
} from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";
import {
  ChannelField,
  Fieldset,
  FRow,
  MultiOptionField,
  MultiRoleField,
  OptionSelect,
  PickerStatusProvider,
  TextField,
  ToggleField,
} from "../_engine/components/settings/fields";
import { KeyValue, Rule as Divider } from "../_engine/components/overview/Tile";
import { formatCount } from "../_engine/format";

/*
 * The rule editor.
 *
 * It used to be five snowflake boxes and a collapsed panel of comma-separated ID lists,
 * which meant the whole of a rule's behaviour - what kinds of message it copies, which
 * keywords it requires or blocks, how long a message may be, whether the copy names its
 * author - could only be changed from the /admin panel in Discord. Everything a rule
 * carries is editable here now (owner ruling 2026-08-13).
 *
 * Channels and roles are pickers over the server's real channels and roles, so a mistyped
 * digit can no longer point a rule at nothing. The one exception is a destination in
 * ANOTHER server: the dashboard can only list channels for a server the signed-in user
 * manages, so a cross-server destination stays an ID box, with a live note saying what
 * that means.
 *
 * The right-hand column is a live sentence about what the rule does as currently drafted.
 */

const DEFAULT_FILTERS: AuthorFilters = {
  allow_user_ids: [],
  deny_user_ids: [],
  allow_role_ids: [],
  deny_role_ids: [],
};

const DEFAULT_MESSAGE_TYPES: MessageTypes = {
  text: true,
  media: true,
  links: true,
  embeds: true,
  files: true,
  stickers: false,
};

const DEFAULT_CONTENT_FILTERS: RuleFilters = {
  require_keywords: [],
  block_keywords: [],
  min_length: 0,
  max_length: 2000,
};

const DEFAULT_FORMATTING: RuleFormatting = {
  include_author: true,
  add_prefix: "",
  add_suffix: "",
  forward_attachments: true,
  forward_embeds: true,
  forward_style: "native",
};

const DEFAULT_ADVANCED: AdvancedOptions = {
  case_sensitive: false,
  whole_word_only: false,
};

type MessageTypeKey = keyof MessageTypes;

/** Human labels for the message-type switches. Order is the order they render in. */
const MESSAGE_TYPE_OPTIONS: [MessageTypeKey, string][] = [
  ["text", "Plain text messages"],
  ["links", "Messages containing a link"],
  ["media", "Images and videos"],
  ["files", "File attachments"],
  ["embeds", "Rich embeds"],
  ["stickers", "Stickers"],
];

function parseIds(raw: string): string[] {
  return raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
}

export function RuleEditorPage() {
  const { guildId, ruleId } = useParams<{ guildId: string; ruleId: string }>();
  const navigate = useNavigate();
  const isNew = ruleId === "new";

  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [ruleName, setRuleName] = useState("");
  const [sourceChannelId, setSourceChannelId] = useState<string | null>(null);
  const [destChannelId, setDestChannelId] = useState<string | null>(null);
  const [destGuildId, setDestGuildId] = useState("");
  const [crossServer, setCrossServer] = useState(false);
  const [isActive, setIsActive] = useState(true);

  const [filters, setFilters] = useState<AuthorFilters>(DEFAULT_FILTERS);
  const [messageTypes, setMessageTypes] = useState<MessageTypes>(DEFAULT_MESSAGE_TYPES);
  const [contentFilters, setContentFilters] = useState<RuleFilters>(DEFAULT_CONTENT_FILTERS);
  const [formatting, setFormatting] = useState<RuleFormatting>(DEFAULT_FORMATTING);
  const [advanced, setAdvanced] = useState<AdvancedOptions>(DEFAULT_ADVANCED);

  const [channels, setChannels] = useState<Channel[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [channelsFailed, setChannelsFailed] = useState(false);
  const [rolesFailed, setRolesFailed] = useState(false);
  const [overview, setOverview] = useState<GuildOverview | null>(null);

  useEffect(() => {
    if (!guildId) return;
    api.channels(guildId)
      .then((list) => { setChannels(list); setChannelsFailed(false); })
      .catch(() => { setChannels([]); setChannelsFailed(true); });
    api.roles(guildId)
      .then((list) => { setRoles(list); setRolesFailed(false); })
      .catch(() => { setRoles([]); setRolesFailed(true); });
    // Optional: the context column drops the rows it cannot fill.
    api.overview(guildId).then(setOverview).catch(() => setOverview(null));
  }, [guildId]);

  useEffect(() => {
    if (isNew || !guildId || !ruleId) return;
    api.getRule(guildId, ruleId)
      .then((rule: Rule) => {
        setRuleName(rule.rule_name);
        setSourceChannelId(String(rule.source_channel_id));
        setDestChannelId(String(rule.destination_channel_id));
        const destGuild = rule.destination_guild_id ? String(rule.destination_guild_id) : "";
        setDestGuildId(destGuild);
        setCrossServer(destGuild !== "" && destGuild !== guildId);
        setIsActive(rule.is_active);
        // Every section is defaulted rather than assumed present: a rule written before
        // the section existed simply has no key for it, and the API's own migration fills
        // the same defaults on read.
        setFilters(rule.settings?.author_filters ?? DEFAULT_FILTERS);
        setMessageTypes({ ...DEFAULT_MESSAGE_TYPES, ...(rule.settings?.message_types ?? {}) });
        setContentFilters({ ...DEFAULT_CONTENT_FILTERS, ...(rule.settings?.filters ?? {}) });
        setFormatting({ ...DEFAULT_FORMATTING, ...(rule.settings?.formatting ?? {}) });
        setAdvanced({ ...DEFAULT_ADVANCED, ...(rule.settings?.advanced_options ?? {}) });
      })
      .catch((e) => setError(formatError(e)))
      .finally(() => setLoading(false));
  }, [guildId, ruleId, isNew]);

  /** The channel options, guaranteeing a saved value is one of them. */
  const channelOptions = useMemo(() => {
    const extras: Channel[] = [];
    for (const id of [sourceChannelId, crossServer ? null : destChannelId]) {
      if (id && !channels.some((c) => c.id === id)) {
        extras.push({ id, name: `channel ${id}`, type: 0, parent_id: null, position: -1 });
      }
    }
    return extras.length > 0 ? [...channels, ...extras] : channels;
  }, [channels, sourceChannelId, destChannelId, crossServer]);

  const selectedTypes = useMemo(
    () => MESSAGE_TYPE_OPTIONS.map(([k]) => k).filter((k) => messageTypes[k]),
    [messageTypes],
  );

  const carried = useMemo(() => {
    if (isNew || !ruleId) return null;
    const route = overview?.rules?.routes.find((r) => r.rule_id === ruleId);
    return route ? route.forwarded_30d : null;
  }, [overview, ruleId, isNew]);

  const channelName = (id: string | null): string | null => {
    if (!id) return null;
    const hit = channels.find((c) => c.id === id);
    return hit ? `#${hit.name}` : `#${id}`;
  };

  const lengthInvalid = contentFilters.min_length > contentFilters.max_length;
  const noTypes = selectedTypes.length === 0;

  // A cross-server rule additionally needs exactly one destination server ID; the
  // destination channel field is required either way, picker or ID box.
  const canSave =
    ruleName.trim().length > 0 &&
    !!sourceChannelId &&
    !!destChannelId &&
    (!crossServer || parseIds(destGuildId).length === 1) &&
    !lengthInvalid &&
    !noTypes;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!guildId || !canSave) return;
    setSaving(true);
    setError(null);
    try {
      const body: RuleWriteBody = {
        rule_name: ruleName.trim(),
        source_channel_id: sourceChannelId ?? undefined,
        destination_channel_id: destChannelId ?? undefined,
        destination_guild_id: crossServer ? destGuildId.trim() : undefined,
        is_active: isActive,
        author_filters: filters,
        message_types: messageTypes,
        filters: contentFilters,
        formatting,
        advanced_options: advanced,
      };
      if (isNew) {
        await api.createRule(guildId, body);
      } else {
        await api.updateRule(guildId, ruleId!, body);
      }
      navigate(`/guilds/${guildId}/rules`);
    } catch (e) {
      setError(formatError(e));
    } finally {
      setSaving(false);
    }
  }

  if (!guildId) return null;
  if (loading) {
    return (
      <div className="page">
        <div className="ov-grid" role="status" aria-busy="true">
          <div className="skeleton-card s12" />
          <span className="visually-hidden">Loading this rule</span>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header" style={{ paddingTop: 16 }}>
        <div>
          <Link to={`/guilds/${guildId}/rules`} className="muted" style={{ fontSize: 13 }}>
            &larr; Forwarding rules
          </Link>
          <h1 style={{ marginTop: 4 }}>{isNew ? "New rule" : "Edit rule"}</h1>
        </div>
      </div>

      {error && <Alert kind="danger">{error}</Alert>}

      <PickerStatusProvider value={{ channelsFailed, rolesFailed }}>
        <form className="set-layout" onSubmit={handleSubmit} style={{ gridTemplateColumns: "minmax(0, 1fr) 300px" }}>
          <div className="set-main" style={{ maxWidth: "none" }}>
            <Fieldset title="The route">
              <FRow full>
                <TextField
                  label="Rule name"
                  value={ruleName}
                  onChange={setRuleName}
                  maxLength={100}
                  placeholder="Announcements to General"
                  description="Only for your own reference - it never appears on a forwarded message."
                />
              </FRow>
              <FRow>
                <ChannelField
                  label="Watch this channel"
                  value={sourceChannelId}
                  channels={channelOptions}
                  filterType={0}
                  onChange={setSourceChannelId}
                  description="Every message posted here is considered for copying."
                />
                {crossServer ? (
                  <TextField
                    label="Destination channel ID"
                    value={destChannelId ?? ""}
                    onChange={(v) => setDestChannelId(v.trim() || null)}
                    placeholder="Channel ID in the other server"
                    description="An ID rather than a picker: the dashboard can only list channels for servers you manage."
                  />
                ) : (
                  <ChannelField
                    label="Copy into this channel"
                    value={destChannelId}
                    channels={channelOptions}
                    filterType={0}
                    onChange={setDestChannelId}
                    description="Messages that pass the rule are posted here."
                  />
                )}
              </FRow>
              <FRow full>
                <ToggleField
                  label="The destination is in another server"
                  value={crossServer}
                  onChange={(v) => {
                    setCrossServer(v);
                    if (!v) setDestGuildId("");
                  }}
                  description="Cross-server copying only works if that server has allowed yours in its own cross-server settings. Without that, the rule saves but nothing arrives."
                />
              </FRow>
              {crossServer && (
                <FRow full>
                  <TextField
                    label="Destination server ID"
                    value={destGuildId}
                    onChange={setDestGuildId}
                    placeholder="123456789012345678"
                    description="The ID of the server the messages are copied into."
                  />
                </FRow>
              )}
              <FRow full>
                <ToggleField
                  label="Rule is active"
                  value={isActive}
                  onChange={setIsActive}
                  description="A paused rule keeps everything you set here and copies nothing. Only active rules count towards your plan's rule limit."
                />
              </FRow>
            </Fieldset>

            <Fieldset title="What gets copied">
              <FRow full>
                <MultiOptionField
                  label="Kinds of message"
                  value={selectedTypes}
                  options={MESSAGE_TYPE_OPTIONS}
                  requireOne
                  onChange={(picked) => {
                    const next = { ...DEFAULT_MESSAGE_TYPES };
                    for (const key of MESSAGE_TYPE_OPTIONS.map(([k]) => k)) {
                      next[key] = picked.includes(key);
                    }
                    setMessageTypes(next);
                  }}
                  description="A message has to be at least one of these to be copied. At least one must stay ticked - a rule with none copies nothing at all."
                />
              </FRow>
            </Fieldset>

            <Fieldset title="Word filters">
              <FRow full>
                <KeywordField
                  label="Only copy messages containing"
                  values={contentFilters.require_keywords}
                  onChange={(v) => setContentFilters({ ...contentFilters, require_keywords: v })}
                  placeholder="giveaway"
                  description="Leave empty to copy everything. With words listed, a message needs at least one of them."
                />
              </FRow>
              <FRow full>
                <KeywordField
                  label="Never copy messages containing"
                  values={contentFilters.block_keywords}
                  onChange={(v) => setContentFilters({ ...contentFilters, block_keywords: v })}
                  placeholder="spoiler"
                  description="A message with any of these words is skipped, even if it matched the list above."
                />
              </FRow>
              <FRow>
                <ToggleField
                  label="Match capital letters exactly"
                  value={advanced.case_sensitive}
                  onChange={(v) => setAdvanced({ ...advanced, case_sensitive: v })}
                  description="Off means Giveaway and giveaway both match."
                />
                <ToggleField
                  label="Match whole words only"
                  value={advanced.whole_word_only}
                  onChange={(v) => setAdvanced({ ...advanced, whole_word_only: v })}
                  description="On means 'art' no longer matches inside 'start'."
                />
              </FRow>
            </Fieldset>

            <Fieldset title="Message length">
              <FRow>
                <NumberField
                  label="Shortest message to copy"
                  value={contentFilters.min_length}
                  min={0}
                  max={2000}
                  onChange={(v) => setContentFilters({ ...contentFilters, min_length: v })}
                  description="In characters. 0 copies even an empty message with only an attachment on it."
                />
                <NumberField
                  label="Longest message to copy"
                  value={contentFilters.max_length}
                  min={0}
                  max={2000}
                  onChange={(v) => setContentFilters({ ...contentFilters, max_length: v })}
                  description="In characters. 2000 is Discord's own limit, so it copies anything."
                />
              </FRow>
              {lengthInvalid && (
                <p className="alert danger" role="alert" style={{ margin: 0 }}>
                  The shortest length is above the longest, so this rule would copy nothing.
                </p>
              )}
            </Fieldset>

            <Fieldset title="How the copy looks">
              <FRow full>
                <ToggleField
                  label="Show who wrote the message"
                  value={formatting.include_author}
                  onChange={(v) => setFormatting({ ...formatting, include_author: v })}
                  description="Puts the author's display name at the top of the copy. A member who has asked relay to hide their name always has it left off, whatever this is set to."
                />
              </FRow>
              <FRow>
                <ToggleField
                  label="Copy attachments"
                  value={formatting.forward_attachments}
                  onChange={(v) => setFormatting({ ...formatting, forward_attachments: v })}
                  description="Re-uploads images and files with the copy. Off posts the text only."
                />
                <ToggleField
                  label="Copy embeds"
                  value={formatting.forward_embeds}
                  onChange={(v) => setFormatting({ ...formatting, forward_embeds: v })}
                  description="Keeps link previews and rich embeds on the copy."
                />
              </FRow>
              <FRow full>
                <OptionSelect
                  label="Style"
                  value={formatting.forward_style}
                  options={[["native", "Quoted - the original shown as a quote with a link back"]]}
                  onChange={(v) => setFormatting({ ...formatting, forward_style: v })}
                  description="One style today. Every forwarded message is posted as a quote with a link back to the original."
                />
              </FRow>
              <FRow>
                <TextField
                  label="Prefix"
                  value={formatting.add_prefix}
                  onChange={(v) => setFormatting({ ...formatting, add_prefix: v })}
                  maxLength={200}
                  placeholder="From the announcements channel"
                />
                <TextField
                  label="Suffix"
                  value={formatting.add_suffix}
                  onChange={(v) => setFormatting({ ...formatting, add_suffix: v })}
                  maxLength={200}
                  placeholder="Reply in the original channel"
                />
              </FRow>
              <p className="eos-muted" style={{ margin: 0 }}>
                The prefix goes on its own line above the quoted copy and the suffix on its
                own line below it, so they read as your words rather than the original
                author's. Leave either one empty to skip it.
              </p>
            </Fieldset>

            <Fieldset title="Whose messages">
              <FRow full>
                <MultiRoleField
                  label="Only copy messages from these roles"
                  value={filters.allow_role_ids}
                  roles={roles}
                  onChange={(v) => setFilters({ ...filters, allow_role_ids: v })}
                  description="Leave every box unticked to copy everyone. With roles ticked, only members holding one of them are copied."
                />
              </FRow>
              <FRow full>
                <MultiRoleField
                  label="Never copy messages from these roles"
                  value={filters.deny_role_ids}
                  roles={roles}
                  onChange={(v) => setFilters({ ...filters, deny_role_ids: v })}
                  description="A member holding one of these is skipped, even if another role would have allowed them."
                />
              </FRow>
              <FRow>
                <IdListField
                  label="Only copy these members"
                  values={filters.allow_user_ids}
                  onChange={(v) => setFilters({ ...filters, allow_user_ids: v })}
                  description="Member IDs, separated by commas or spaces."
                />
                <IdListField
                  label="Never copy these members"
                  values={filters.deny_user_ids}
                  onChange={(v) => setFilters({ ...filters, deny_user_ids: v })}
                  description="Member IDs, separated by commas or spaces. A blocked member is skipped even if a role allows them."
                />
              </FRow>
            </Fieldset>

            <div className="savebar">
              <button type="submit" className="btn btn-primary" disabled={saving || !canSave}>
                {saving ? "Saving..." : isNew ? "Create rule" : "Save changes"}
              </button>
              <Link to={`/guilds/${guildId}/rules`} className="btn ghost">
                Cancel
              </Link>
              <span className="muted" style={{ fontSize: 13 }}>
                {noTypes
                  ? "Pick at least one kind of message"
                  : !canSave
                    ? "Fill in the name and both channels"
                    : "Ready to save"}
              </span>
            </div>
          </div>

          <aside className="set-ctx" aria-label="What this rule does">
            <div className="ov-card">
              <div className="ov-card__head">
                <span className="ov-card__title">What this rule does</span>
              </div>
              <p className="ov-body">{summarySentence({
                source: channelName(sourceChannelId),
                destination: crossServer ? null : channelName(destChannelId),
                crossServer,
                destGuildId: destGuildId.trim(),
                isActive,
              })}</p>
              <Divider />
              <KeyValue
                k="Kinds copied"
                v={
                  selectedTypes.length === MESSAGE_TYPE_OPTIONS.length
                    ? "everything"
                    : `${selectedTypes.length} of ${MESSAGE_TYPE_OPTIONS.length}`
                }
              />
              <KeyValue
                k="Required words"
                v={contentFilters.require_keywords.length === 0
                  ? "none"
                  : String(contentFilters.require_keywords.length)}
              />
              <KeyValue
                k="Blocked words"
                v={contentFilters.block_keywords.length === 0
                  ? "none"
                  : String(contentFilters.block_keywords.length)}
              />
              <KeyValue
                k="Length window"
                v={`${contentFilters.min_length} to ${contentFilters.max_length} characters`}
              />
              <KeyValue
                k="Author line"
                v={formatting.include_author ? "shown" : "left off"}
              />
              <KeyValue
                k="Who is copied"
                v={
                  filters.allow_role_ids.length + filters.allow_user_ids.length > 0
                    ? "a named few"
                    : filters.deny_role_ids.length + filters.deny_user_ids.length > 0
                      ? "everyone except a named few"
                      : "everyone"
                }
              />
              {!isNew && (
                <>
                  <Divider />
                  <p className="ov-muted">
                    {overview?.rules == null
                      ? "How much this rule has carried could not be loaded."
                      : carried === null
                        ? "This rule has no traffic figure yet."
                        : `${formatCount(carried)} message${carried === 1 ? "" : "s"} carried in the last 30 days.`}
                  </p>
                </>
              )}
            </div>
          </aside>
        </form>
      </PickerStatusProvider>
    </div>
  );
}

/** The plain sentence at the top of the context column. */
function summarySentence({
  source,
  destination,
  crossServer,
  destGuildId,
  isActive,
}: {
  source: string | null;
  destination: string | null;
  crossServer: boolean;
  destGuildId: string;
  isActive: boolean;
}): string {
  if (!source) return "Pick a channel to watch and this will say what the rule does.";
  const where = crossServer
    ? destGuildId
      ? `a channel in server ${destGuildId}`
      : "a channel in another server"
    : (destination ?? "a channel you have not picked yet");
  const lead = isActive
    ? `Messages in ${source} are copied to ${where}`
    : `Messages in ${source} would be copied to ${where}, but the rule is paused`;
  return `${lead}.`;
}

/**
 * A keyword list, entered as chips.
 *
 * Not a comma-separated text box: a keyword may legitimately contain a space ("free
 * nitro"), and a box that splits on commas AND spaces would quietly turn one phrase into
 * two words that each match on their own. One entry per press of Enter, removable
 * individually.
 */
function KeywordField({
  label,
  values,
  onChange,
  placeholder,
  description,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  description?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const word = draft.trim().slice(0, 100);
    if (!word || values.includes(word)) {
      setDraft("");
      return;
    }
    if (values.length >= 50) return;
    onChange([...values, word]);
    setDraft("");
  };

  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>{description}</p>
      )}
      {values.length > 0 && (
        <div className="kwlist">
          {values.map((word) => (
            <span key={word} className="kwchip">
              <span title={word}>{word}</span>
              <button
                type="button"
                aria-label={`Remove ${word}`}
                onClick={() => onChange(values.filter((w) => w !== word))}
              >
                x
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="kwadd">
        <input
          type="text"
          value={draft}
          maxLength={100}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              // Enter inside a form submits it; a keyword entry must not save the rule.
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="btn btn-secondary small" onClick={add} disabled={!draft.trim()}>
          Add
        </button>
      </div>
      <p className="eos-muted" style={{ marginTop: 6, marginBottom: 0 }}>
        {values.length === 0 ? "None set" : `${values.length} of 50`}
      </p>
    </div>
  );
}

/** A whole number with a bounded range. The engine's fields have no numeric input. */
function NumberField({
  label,
  value,
  min,
  max,
  onChange,
  description,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
  description?: string;
}) {
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>{description}</p>
      )}
      <input
        type="number"
        value={String(value)}
        min={min}
        max={max}
        onChange={(e) => {
          const parsed = Number(e.target.value);
          // An empty or non-numeric box reads as the floor rather than NaN, which would
          // otherwise be sent to the API and rejected as a 422 the user cannot explain.
          if (!Number.isFinite(parsed)) return onChange(min);
          onChange(Math.min(max, Math.max(min, Math.trunc(parsed))));
        }}
      />
    </div>
  );
}

/** Member IDs as a comma or space separated list. IDs never contain either. */
function IdListField({
  label,
  values,
  onChange,
  description,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
  description?: string;
}) {
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>{description}</p>
      )}
      <input
        type="text"
        value={values.join(", ")}
        placeholder="123456789012345678"
        onChange={(e) => onChange(parseIds(e.target.value))}
      />
      <p className="eos-muted" style={{ marginTop: 6, marginBottom: 0 }}>
        {values.length === 0 ? "None set" : `${values.length} listed`}
      </p>
    </div>
  );
}
