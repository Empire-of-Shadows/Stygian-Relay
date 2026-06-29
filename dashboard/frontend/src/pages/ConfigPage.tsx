import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { GuildConfig } from "../api/types";

export function ConfigPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [config, setConfig] = useState<GuildConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const [logChannelId, setLogChannelId] = useState("");
  const [managerRoleId, setManagerRoleId] = useState("");
  const [isEnabled, setIsEnabled] = useState(true);
  const [inboundGuilds, setInboundGuilds] = useState("");

  useEffect(() => {
    if (!guildId) return;
    api.config(guildId)
      .then((c) => {
        setConfig(c);
        setLogChannelId(c.master_log_channel_id ?? "");
        setManagerRoleId(c.manager_role_id ?? "");
        setIsEnabled(c.is_enabled ?? true);
        setInboundGuilds(c.inbound_allowed_guilds.join(", "));
      })
      .catch((e) => setError(String(e)));
  }, [guildId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!guildId) return;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const patch: Partial<GuildConfig> = {};
      if (logChannelId !== (config?.master_log_channel_id ?? "")) {
        patch.master_log_channel_id = logChannelId || null;
      }
      if (managerRoleId !== (config?.manager_role_id ?? "")) {
        patch.manager_role_id = managerRoleId || null;
      }
      if (isEnabled !== config?.is_enabled) {
        patch.is_enabled = isEnabled;
      }
      const parsedGuilds = inboundGuilds.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
      const currentGuilds = config?.inbound_allowed_guilds ?? [];
      if (JSON.stringify(parsedGuilds) !== JSON.stringify(currentGuilds)) {
        patch.inbound_allowed_guilds = parsedGuilds;
      }
      if (Object.keys(patch).length > 0) {
        await api.saveConfig(guildId, patch);
        const updated = await api.config(guildId);
        setConfig(updated);
      }
      setSuccess(true);
    } catch (e) {
      setError(String(e).replace(/^Error: \d+: /, ""));
    } finally {
      setSaving(false);
    }
  }

  if (!guildId) return null;

  return (
    <div className="dash-page" style={{ maxWidth: 640, margin: "0 auto" }}>
      <div className="page-header">
        <div>
          <Link to={`/guilds/${guildId}`} className="muted" style={{ fontSize: 13 }}>← Back</Link>
          <h1 style={{ marginTop: 4 }}>Guild Settings</h1>
        </div>
      </div>

      {error && <div className="alert danger">{error}</div>}
      {success && <div className="alert success">Settings saved.</div>}

      {config === null && !error && <div className="loading">Loading…</div>}

      {config !== null && (
        <form className="card" onSubmit={handleSubmit}>
          <div className="field">
            <label>Log Channel ID <span className="muted">(optional)</span></label>
            <input
              type="text"
              value={logChannelId}
              onChange={(e) => setLogChannelId(e.target.value)}
              placeholder="Channel snowflake for relay logs"
            />
          </div>

          <div className="field">
            <label>Manager Role ID <span className="muted">(grants dashboard admin access)</span></label>
            <input
              type="text"
              value={managerRoleId}
              onChange={(e) => setManagerRoleId(e.target.value)}
              placeholder="Role snowflake"
            />
          </div>

          <div className="field">
            <label className="toggle">
              <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} />
              <span>Bot enabled for this server</span>
            </label>
          </div>

          <div className="field">
            <label>Allowed Inbound Guilds <span className="muted">(comma-separated guild IDs)</span></label>
            <input
              type="text"
              value={inboundGuilds}
              onChange={(e) => setInboundGuilds(e.target.value)}
              placeholder="Guild snowflakes allowed to forward messages here"
            />
          </div>

          <div style={{ marginTop: 16 }}>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? "Saving…" : "Save Settings"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
