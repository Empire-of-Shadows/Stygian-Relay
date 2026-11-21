/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { createContext, useContext, useId, useRef, useState, type ReactNode } from "react";
import type { Channel, Role } from "../../api/types";
import {
  MAX_NAME_LENGTH,
  validateChannelName,
  validateRoleName,
  type CreatableKind,
} from "./names";

/*
 * Create a role or a channel right where it is picked (added 2026-11-20).
 *
 * The dashboard half of the admin panel's inline Create button. A bot opts in by
 * wrapping its settings form in <EntityCreatorProvider>; without one, every
 * picker renders exactly as before. Inside one, every ChannelField, RoleField and
 * MultiRoleField grows a Create button unless it passes allowCreate={false}.
 *
 * The button is greyed out, with the reason on hover and on keyboard focus,
 * when the bot does not hold the permission Discord requires. That uses
 * aria-disabled rather than disabled, because a disabled button cannot take
 * focus and in some browsers does not report hover, so the reason would be
 * unreachable for exactly the people who need it.
 *
 * Creating does not save anything. The new role or channel is selected in the
 * form and the section shows as unsaved, the same as picking one by hand.
 */

export interface CreateAbility {
  allowed: boolean;
  /** Why not, as a phrase that follows the bot's name. Null when allowed. */
  reason: string | null;
}

export interface CreateCategory extends CreateAbility {
  id: string;
  name: string;
}

/** The shape of backend/discord_objects.py create_abilities(). */
export interface CreateAbilities {
  roles: CreateAbility;
  channels: CreateAbility;
  categories: CreateCategory[];
}

export interface EntityCreator {
  /** The bot's name as members know it, for the hover text. */
  botName: string;
  /** Null while loading, and when the request failed. */
  abilities: CreateAbilities | null;
  abilitiesFailed: boolean;
  /** Create the role and add it to the page's role list. Rejects with a readable error. */
  createRole: (name: string) => Promise<Role>;
  /** Create the channel and add it to the page's channel list. */
  createChannel: (name: string, kind: CreatableKind, parentId: string | null) => Promise<Channel>;
}

const EntityCreatorContext = createContext<EntityCreator | null>(null);

export function EntityCreatorProvider({
  value,
  children,
}: {
  value: EntityCreator | null;
  children: ReactNode;
}) {
  return (
    <EntityCreatorContext.Provider value={value}>{children}</EntityCreatorContext.Provider>
  );
}

export function useEntityCreator(): EntityCreator | null {
  return useContext(EntityCreatorContext);
}

const KIND_NOUN: Record<CreatableKind, string> = {
  text: "text channel",
  voice: "voice channel",
  category: "category",
};

function blockedReason(creator: EntityCreator, what: "roles" | "channels"): string | null {
  if (creator.abilitiesFailed) {
    return `Could not check what ${creator.botName} is allowed to do in this server. Reload the page to try again.`;
  }
  if (!creator.abilities) return `Checking what ${creator.botName} is allowed to do...`;
  const a = creator.abilities[what];
  if (a.allowed) return null;
  // Discord answers are cached for up to a minute, so a permission just granted
  // can take that long to show here.
  return `${creator.botName} ${a.reason}. Check the bot's permissions in your Discord server settings, then reload this page in a minute.`;
}

function errorText(e: unknown, fallback: string): string {
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

function CreateButton({
  label,
  blocked,
  onClick,
}: {
  label: string;
  blocked: string | null;
  onClick: () => void;
}) {
  const tipId = useId();
  return (
    <span className={"eos-create__tipwrap" + (blocked ? " has-tip" : "")} data-tip={blocked ?? undefined}>
      <button
        type="button"
        className="btn btn-secondary eos-create__btn"
        aria-disabled={blocked ? "true" : undefined}
        aria-describedby={blocked ? tipId : undefined}
        onClick={blocked ? undefined : onClick}
      >
        + {label}
      </button>
      {blocked && (
        <span id={tipId} className="visually-hidden">
          {blocked}
        </span>
      )}
    </span>
  );
}

type Target = { target: "role" } | { target: "channel"; kinds: CreatableKind[] };

/**
 * The Create control under one picker. Renders nothing outside a provider, or
 * for a channel picker whose accepted types include nothing a bot can create.
 */
export function CreateEntityControl(
  props: Target & { onCreated: (id: string) => void },
) {
  const creator = useEntityCreator();
  const inputId = useId();
  const [open, setOpen] = useState<CreatableKind | "role" | null>(null);
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  // The create request can take seconds (a rate-limit retry waits up to 10 s).
  // Call the LATEST onCreated when it returns, not the one from the render the
  // click happened in, or every edit made meanwhile would be put back. The page's
  // own draft update must be functional too (setDraft(prev => ...)), so a create
  // that lands after the person moved to another section cannot undo it.
  const onCreatedRef = useRef(props.onCreated);
  onCreatedRef.current = props.onCreated;

  if (!creator) return null;
  const kinds = props.target === "channel" ? props.kinds : [];
  if (props.target === "channel" && kinds.length === 0) return null;

  const blocked = blockedReason(creator, props.target === "role" ? "roles" : "channels");

  const start = (kind: CreatableKind | "role") => {
    setOpen(kind);
    setName("");
    setParentId("");
    setError(null);
    setCreated(null);
  };
  const cancel = () => {
    setOpen(null);
    setError(null);
  };

  if (!open) {
    return (
      <div className="eos-create">
        <div className="eos-create__row">
          {props.target === "role" ? (
            <CreateButton label="Create role" blocked={blocked} onClick={() => start("role")} />
          ) : (
            kinds.map((k) => (
              <CreateButton
                key={k}
                label={
                  kinds.length === 1 && k === "text" ? "Create channel" : `Create ${KIND_NOUN[k]}`
                }
                blocked={blocked}
                onClick={() => start(k)}
              />
            ))
          )}
        </div>
        {created && (
          <p className="eos-muted eos-create__note" role="status">
            Created {created}. Save this section to use it here.
          </p>
        )}
      </div>
    );
  }

  const noun = open === "role" ? "role" : KIND_NOUN[open];
  const check = open === "role" ? validateRoleName(name) : validateChannelName(open, name);
  const showsCategory = open === "text" || open === "voice";
  const categories = creator.abilities?.categories ?? [];
  const typed = name.trim().length > 0;

  const submit = async () => {
    if (busy || !check.ok || check.name === null) return;
    setBusy(true);
    setError(null);
    try {
      if (open === "role") {
        const role = await creator.createRole(check.name);
        setCreated(`the role ${role.name}`);
        onCreatedRef.current(role.id);
      } else {
        const channel = await creator.createChannel(
          check.name,
          open,
          showsCategory && parentId ? parentId : null,
        );
        setCreated(open === "category" ? `the category ${channel.name}` : `#${channel.name}`);
        onCreatedRef.current(channel.id);
      }
      setOpen(null);
    } catch (e) {
      setError(errorText(e, `Could not create the ${noun}.`));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="eos-create">
      <div className="eos-create__form" role="group" aria-label={`Create a ${noun}`}>
        <label htmlFor={inputId}>New {noun} name</label>
        <input
          id={inputId}
          type="text"
          value={name}
          maxLength={MAX_NAME_LENGTH}
          autoFocus
          disabled={busy}
          aria-invalid={typed && !check.ok ? true : undefined}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void submit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              cancel();
            }
          }}
        />
        {typed && !check.ok && <p className="eos-field__error">{check.error}</p>}
        {typed && check.ok && open === "text" && check.name !== name.trim() && (
          <p className="eos-muted eos-create__note">Discord will name it #{check.name}</p>
        )}
        {showsCategory && categories.length > 0 && (
          <>
            <label htmlFor={`${inputId}-cat`}>Category (optional)</label>
            <select
              id={`${inputId}-cat`}
              value={parentId}
              disabled={busy}
              onChange={(e) => setParentId(e.target.value)}
            >
              <option value="">-- no category --</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id} disabled={!c.allowed}>
                  {c.name}
                  {c.allowed ? "" : ` (${creator.botName} ${c.reason})`}
                </option>
              ))}
            </select>
          </>
        )}
        {error && (
          <p className="eos-field__error" role="alert">
            {error}
          </p>
        )}
        <div className="eos-create__actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || !check.ok}
            onClick={() => void submit()}
          >
            {busy ? "Creating..." : `Create ${noun}`}
          </button>
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={cancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
