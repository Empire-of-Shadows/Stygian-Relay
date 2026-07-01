import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { PremiumStatus } from "../api/types";

export function PremiumPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [premium, setPremium] = useState<PremiumStatus | null>(null);
  const [code, setCode] = useState("");
  const [redeeming, setRedeeming] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!guildId) return;
    api.premium(guildId).then(setPremium).catch((e) => setError(String(e)));
  }, [guildId]);

  async function handleRedeem(e: React.FormEvent) {
    e.preventDefault();
    if (!guildId || !code.trim()) return;
    setRedeeming(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await api.redeemCode(guildId, code.trim());
      setSuccess(`Code redeemed! Tier: ${res.tier}${res.expires_at ? ` — expires ${new Date(res.expires_at).toLocaleDateString()}` : " (lifetime)"}`);
      setCode("");
      const updated = await api.premium(guildId);
      setPremium(updated);
    } catch (e) {
      setError(String(e).replace(/^Error: \d+: /, ""));
    } finally {
      setRedeeming(false);
    }
  }

  if (!guildId) return null;

  return (
    <div className="dash-page" style={{ maxWidth: 640, margin: "0 auto" }}>
      <div className="page-header">
        <div>
          <Link to={`/guilds/${guildId}`} className="muted" style={{ fontSize: 13 }}>← Back</Link>
          <h1 style={{ marginTop: 4 }}>Premium</h1>
        </div>
      </div>

      {error && <div className="alert danger">{error}</div>}
      {success && <div className="alert success">{success}</div>}

      {premium && (
        <div className="card" style={{ marginBottom: 24 }}>
          <h3 style={{ marginBottom: 12 }}>Current Plan</h3>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div className="stat">
              <span className="value" style={{ fontSize: "1.4rem", textTransform: "capitalize" }}>
                {premium.tier}
              </span>
              <span className="label">Tier</span>
            </div>
            <div className="stat">
              <span className="value" style={{ fontSize: "1.4rem" }}>{premium.max_rules}</span>
              <span className="label">Max Rules</span>
            </div>
            <div className="stat">
              <span className="value" style={{ fontSize: "1.4rem" }}>{premium.daily_limit.toLocaleString()}</span>
              <span className="label">Daily Limit</span>
            </div>
          </div>
          {premium.is_premium && !premium.is_lifetime && premium.expires_at && (
            <p className="muted" style={{ marginTop: 12, fontSize: 13 }}>
              Expires: {new Date(premium.expires_at).toLocaleDateString()}
            </p>
          )}
          {premium.is_lifetime && (
            <p style={{ marginTop: 12, fontSize: 13, color: "var(--success)" }}>Lifetime subscription active</p>
          )}
        </div>
      )}

      <div className="card">
        <h3 style={{ marginBottom: 12 }}>Redeem a Code</h3>
        <form onSubmit={handleRedeem}>
          <div className="field">
            <label>Activation Code</label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="XXXX-XXXX-XXXX"
              required
              style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={redeeming || !code.trim()}>
            {redeeming ? "Redeeming…" : "Redeem Code"}
          </button>
        </form>
      </div>
    </div>
  );
}
