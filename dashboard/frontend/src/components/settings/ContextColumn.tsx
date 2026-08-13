import { Component, type ReactNode } from "react";
import type { Channel, GuildOverview, Role } from "../../api/types";
import { formatCount, formatRelative } from "../../_engine/format";
import { reasonLabel } from "../overview/format";

/*
 * The right-hand column on the settings page: what the selected area is
 * actually doing right now.
 *
 * Two sources feed it. The draft is always there, so the "what is configured"
 * rows always render. The guild overview is optional - it can fail or come back
 * with null sections, and when it does those rows are simply left out. Nothing
 * here may throw when `overview` is null.
 */

export interface ContextDraft {
  is_enabled: boolean;
  notify_on_error: boolean;
  master_log_channel_id: string | null;
  manager_role_id: string | null;
  inbound_text: string;
}

function KvCard({
  title,
  rows,
  footer,
}: {
  title: string;
  rows: [string, string][];
  footer?: string;
}) {
  if (rows.length === 0 && !footer) return null;
  return (
    <div className="ov-card">
      <div className="ov-card__head">
        <span className="ov-card__title">{title}</span>
      </div>
      <div>
        {rows.map(([k, v]) => (
          <div className="ov-kv" key={k}>
            <span className="ov-kv__k">{k}</span>
            <span className="ov-kv__v">{v}</span>
          </div>
        ))}
      </div>
      {footer && <p className="ov-muted" style={{ margin: 0 }}>{footer}</p>}
    </div>
  );
}

function onOff(value: boolean): string {
  return value ? "On" : "Off";
}

function parseIds(raw: string): string[] {
  return raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
}

interface ContextProps {
  slug: string;
  draft: ContextDraft;
  channels: Channel[];
  roles: Role[];
  overview: GuildOverview | null;
}

/**
 * The settings form must survive anything the overview endpoint does.
 *
 * The types say every field is there once a section is non-null, but the
 * endpoint is new. If a section comes back a shape short, this column goes
 * quiet rather than taking the form down with it.
 */
export default class ContextColumn extends Component<ContextProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render(): ReactNode {
    if (this.state.failed) return null;
    return <ContextBody {...this.props} />;
  }
}

function ContextBody({ slug, draft, channels, roles, overview }: ContextProps) {
  const traffic = overview?.traffic ?? null;
  const rules = overview?.rules ?? null;
  const delivery = overview?.delivery ?? null;
  const config = overview?.config ?? null;

  const channelName = (id: string | null): string => {
    if (!id) return "Not set";
    const hit = channels.find((c) => c.id === id);
    return hit ? `#${hit.name}` : `#${id}`;
  };

  const roleName = (id: string | null): string => {
    if (!id) return "Not set";
    const hit = roles.find((r) => r.id === id);
    return hit ? hit.name : `Role ${id}`;
  };

  if (slug === "forwarding") {
    const rows: [string, string][] = [
      ["Forwarding", onOff(draft.is_enabled)],
      ["Error notices", onOff(draft.notify_on_error)],
    ];
    if (rules) {
      rows.push(["Active rules", `${rules.active} of ${rules.max_rules}`]);
    }
    if (traffic) {
      rows.push(["Forwarded today", `${formatCount(traffic.today_forwarded)} of ${formatCount(traffic.daily_limit)}`]);
      rows.push(["Forwarded in 30 days", formatCount(traffic.forwarded_30d)]);
    }
    return (
      <>
        <KvCard
          title="Right now"
          rows={rows}
          footer={
            traffic && traffic.last_forward_at
              ? `Last message forwarded ${formatRelative(traffic.last_forward_at)}.`
              : traffic
                ? "Nothing has been forwarded from this server yet."
                : undefined
          }
        />
        {delivery && delivery.reasons.length > 0 && (
          <KvCard
            title="Blocked, 30 days"
            rows={delivery.reasons.map(
              (reason) => [reasonLabel(reason.reason), formatCount(reason.count)] as [string, string],
            )}
            footer={
              delivery.undeliverable_30d > 0
                ? "Some messages could not be delivered. Check that every rule's destination channel still exists and the bot can post there."
                : undefined
            }
          />
        )}
      </>
    );
  }

  if (slug === "cross_server") {
    const listed = parseIds(draft.inbound_text);
    const rows: [string, string][] = [
      ["Servers allowed in", listed.length === 0 ? "None" : String(listed.length)],
    ];
    if (rules) {
      rows.push(["Rules pointing elsewhere", String(rules.cross_guild)]);
    }
    return (
      <KvCard
        title="Right now"
        rows={rows}
        footer={
          listed.length === 0
            ? "Nothing may forward into this server from anywhere else. Rules that stay inside this server still work."
            : "Each of these servers may forward into this one, if it has a rule pointing here."
        }
      />
    );
  }

  if (slug === "logging") {
    const rows: [string, string][] = [
      ["Log channel", channelName(draft.master_log_channel_id)],
    ];
    if (config && config.last_change && config.last_change.at) {
      rows.push(["Last settings change", formatRelative(config.last_change.at)]);
    }
    return (
      <KvCard
        title="Right now"
        rows={rows}
        footer={
          draft.master_log_channel_id
            ? "The bot posts premium changes, forwarding errors, and any rule it had to switch off here."
            : "With no channel set the bot keeps quiet. Everything is still recorded in the audit log."
        }
      />
    );
  }

  if (slug === "access") {
    const rows: [string, string][] = [
      ["Manager role", roleName(draft.manager_role_id)],
    ];
    if (config && config.last_change) {
      rows.push([
        "Last change",
        config.last_change.at ? formatRelative(config.last_change.at) : "unknown",
      ]);
    }
    return (
      <KvCard
        title="Right now"
        rows={rows}
        footer="Anyone with Manage Server always has access. This role is an addition to that, not a replacement."
      />
    );
  }

  // Unknown slug: say nothing rather than guess.
  return null;
}
