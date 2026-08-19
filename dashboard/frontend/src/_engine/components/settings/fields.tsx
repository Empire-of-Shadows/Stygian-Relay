/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { createContext, useContext, type ReactNode } from "react";
import type { Channel, Role } from "../../api/types";

/*
 * Field renderers for the admin settings form.
 *
 * These are the same renderers the page has always used - they were lifted out
 * of AdminSettingsPage so the page file can be about layout and navigation.
 * Behaviour is unchanged apart from one addition: when the Discord channel or
 * role list could not be fetched, the picker says so instead of quietly showing
 * an empty dropdown that reads as "this server has no channels".
 */

// ---------------------------------------------------------------------------
// Picker availability
// ---------------------------------------------------------------------------

export interface PickerStatus {
  /** True when the channel list request failed, so `channels` is empty by accident. */
  channelsFailed: boolean;
  /** True when the role list request failed, so `roles` is empty by accident. */
  rolesFailed: boolean;
}

const PickerStatusContext = createContext<PickerStatus>({
  channelsFailed: false,
  rolesFailed: false,
});

export function PickerStatusProvider({
  value,
  children,
}: {
  value: PickerStatus;
  children: ReactNode;
}) {
  return (
    <PickerStatusContext.Provider value={value}>{children}</PickerStatusContext.Provider>
  );
}

/**
 * Read the picker availability flags from inside the provider.
 *
 * The engine's own fields read the context directly; this exists so a BOT-owned
 * field component can too, instead of having the two booleans prop-drilled down
 * to it from the page that already put them in the context. Purely additive - the
 * context keeps its defaults, so a component used outside a provider still sees
 * "nothing failed" rather than throwing, which is the right answer for a page
 * that never had pickers to fail.
 *
 * Bots unwind their prop-drilling onto this at their own turn; nothing is
 * required to adopt it.
 */
export function usePickerStatus(): PickerStatus {
  return useContext(PickerStatusContext);
}

const CHANNELS_UNAVAILABLE =
  "The channel list could not be loaded, so there is nothing to choose from here. Whatever is already saved stays as it is. Reload the page to try again.";

const ROLES_UNAVAILABLE =
  "The role list could not be loaded, so there is nothing to choose from here. Whatever is already saved stays as it is. Reload the page to try again.";

function FieldNote({ text }: { text: string }) {
  return (
    <p className="eos-muted" style={{ marginTop: 6, marginBottom: 0 }}>
      {text}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

/** One bordered block inside the settings column, with an optional sub-head. */
export function Fieldset({
  title,
  children,
}: {
  title?: string;
  children: ReactNode;
}) {
  return (
    <section className="fieldset">
      {title && <h2 className="fieldset__h">{title}</h2>}
      {children}
    </section>
  );
}

/** A row of fields. Two up by default; `full` gives one full-width column. */
export function FRow({ full, children }: { full?: boolean; children: ReactNode }) {
  return <div className={full ? "frow frow--1" : "frow"}>{children}</div>;
}

// ---------------------------------------------------------------------------
// Field renderers
// ---------------------------------------------------------------------------

export function ChannelField({
  label,
  value,
  channels,
  onChange,
  disabled,
  filterType,
  description,
}: {
  label: string;
  value: string | null;
  channels: Channel[];
  onChange: (v: string | null) => void;
  disabled?: boolean;
  filterType?: number;
  description?: string;
}) {
  const { channelsFailed } = useContext(PickerStatusContext);
  const options = filterType !== undefined
    ? channels.filter((c) => c.type === filterType)
    : channels;
  const note = channelsFailed
    ? CHANNELS_UNAVAILABLE
    : options.length === 0
      ? "No channels this setting can use were found in this server."
      : null;
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>
          {description}
        </p>
      )}
      <select
        value={value ?? ""}
        disabled={disabled || channelsFailed}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">-- not set --</option>
        {channelsFailed && value && <option value={value}>Already set</option>}
        {options.map((c) => (
          <option key={c.id} value={c.id}>
            #{c.name}
          </option>
        ))}
      </select>
      {note && <FieldNote text={note} />}
    </div>
  );
}

export function RoleField({
  label,
  value,
  roles,
  onChange,
  disabled,
  description,
}: {
  label: string;
  value: string | null;
  roles: Role[];
  onChange: (v: string | null) => void;
  disabled?: boolean;
  description?: string;
}) {
  const { rolesFailed } = useContext(PickerStatusContext);
  const sorted = [...roles].sort((a, b) => b.position - a.position);
  const note = rolesFailed
    ? ROLES_UNAVAILABLE
    : sorted.length === 0
      ? "No roles were found in this server."
      : null;
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>
          {description}
        </p>
      )}
      <select
        value={value ?? ""}
        disabled={disabled || rolesFailed}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">-- not set --</option>
        {rolesFailed && value && <option value={value}>Already set</option>}
        {sorted.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
      </select>
      {note && <FieldNote text={note} />}
    </div>
  );
}

export function MultiRoleField({
  label,
  description,
  value,
  roles,
  max,
  onChange,
  disabled,
}: {
  label: string;
  description?: string;
  value: string[];
  roles: Role[];
  max?: number;
  onChange: (v: string[]) => void;
  disabled?: boolean;
}) {
  const { rolesFailed } = useContext(PickerStatusContext);
  const selected = new Set(value);
  const sorted = [...roles].sort((a, b) => b.position - a.position);
  const limitReached = max !== undefined && selected.size >= max;
  const toggle = (id: string) => {
    if (disabled) return;
    const next = new Set(selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      if (max !== undefined && next.size >= max) return;
      next.add(id);
    }
    onChange(sorted.filter((r) => next.has(r.id)).map((r) => r.id));
  };
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>
          {description}
        </p>
      )}
      <div
        style={{
          maxHeight: 220,
          overflowY: "auto",
          border: "1px solid var(--border, #2a2a2a)",
          borderRadius: 6,
          padding: 8,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {sorted.length === 0 && (
          <p className="eos-muted" style={{ margin: 0 }}>
            {rolesFailed ? ROLES_UNAVAILABLE : "No roles available."}
          </p>
        )}
        {sorted.map((r) => {
          const checked = selected.has(r.id);
          const lockedByCap = !checked && limitReached;
          const rowDisabled = disabled || lockedByCap;
          return (
            <label
              key={r.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                cursor: rowDisabled ? "not-allowed" : "pointer",
                opacity: rowDisabled ? 0.5 : 1,
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                disabled={rowDisabled}
                onChange={() => toggle(r.id)}
              />
              <span>{r.name}</span>
            </label>
          );
        })}
      </div>
      <p className="eos-muted" style={{ marginTop: 6, marginBottom: 0 }}>
        {selected.size} selected{max !== undefined ? ` / ${max} max` : ""}
      </p>
    </div>
  );
}

/**
 * Checkbox list over a fixed option list, producing an array setting.
 *
 * The array-valued sibling of OptionSelect. MultiRoleField is the same shape
 * over Discord roles; this one takes the static [value, label] pairs the rest
 * of the settings form already uses, and keeps the declared option order rather
 * than the order the boxes were ticked, so the saved list is stable.
 */
export function MultiOptionField<V extends string>({
  label,
  description,
  value,
  options,
  onChange,
  disabled,
  requireOne,
}: {
  label: string;
  description?: string;
  value: V[];
  options: [V, string][];
  onChange: (v: V[]) => void;
  disabled?: boolean;
  requireOne?: boolean;
}) {
  const selected = new Set(value);
  const toggle = (v: V) => {
    if (disabled) return;
    // With requireOne, the last remaining choice cannot be unticked. An empty
    // list is not a meaningful setting here - the bot falls back to its default
    // rather than posting everything - so the picker never offers that state.
    if (requireOne && selected.has(v) && selected.size <= 1) return;
    const next = new Set(selected);
    if (next.has(v)) {
      next.delete(v);
    } else {
      next.add(v);
    }
    onChange(options.map(([optValue]) => optValue).filter((o) => next.has(o)));
  };
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>
          {description}
        </p>
      )}
      <div
        style={{
          border: "1px solid var(--border, #2a2a2a)",
          borderRadius: 6,
          padding: 8,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {options.map(([optValue, optLabel]) => (
          <label
            key={String(optValue)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              cursor: disabled ? "not-allowed" : "pointer",
              opacity: disabled ? 0.5 : 1,
            }}
          >
            <input
              type="checkbox"
              checked={selected.has(optValue)}
              disabled={disabled}
              onChange={() => toggle(optValue)}
            />
            <span>{optLabel}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

export function OptionSelect<V extends string | number>({
  label,
  value,
  options,
  onChange,
  disabled,
  description,
}: {
  label: string;
  value: V;
  options: [V, string][];
  onChange: (v: V) => void;
  disabled?: boolean;
  description?: string;
}) {
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>
          {description}
        </p>
      )}
      <select
        value={String(value)}
        disabled={disabled}
        onChange={(e) => {
          const raw = e.target.value;
          const sample = options[0]?.[0];
          if (typeof sample === "number") {
            onChange(Number(raw) as V);
          } else {
            onChange(raw as V);
          }
        }}
      >
        {options.map(([v, optLabel]) => (
          <option key={String(v)} value={String(v)}>
            {optLabel}
          </option>
        ))}
      </select>
    </div>
  );
}

export function ToggleField({
  label,
  value,
  onChange,
  disabled,
  description,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  description?: string;
}) {
  return (
    <div className="eos-field">
      <label className="eos-toggle">
        <input
          type="checkbox"
          checked={!!value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span>{label}</span>
      </label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 4, marginBottom: 0 }}>
          {description}
        </p>
      )}
    </div>
  );
}

export function TextField({
  label,
  value,
  onChange,
  disabled,
  description,
  placeholder,
  maxLength,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  description?: string;
  placeholder?: string;
  maxLength?: number;
}) {
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>
          {description}
        </p>
      )}
      <input
        type="text"
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function TextareaField({
  label,
  value,
  onChange,
  disabled,
  description,
  placeholder,
  maxLength,
  rows = 4,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  description?: string;
  placeholder?: string;
  maxLength?: number;
  rows?: number;
}) {
  return (
    <div className="eos-field">
      <label>{label}</label>
      {description && (
        <p className="eos-muted" style={{ marginTop: 0, marginBottom: 6 }}>
          {description}
        </p>
      )}
      <textarea
        value={value}
        rows={rows}
        disabled={disabled}
        placeholder={placeholder}
        maxLength={maxLength}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
