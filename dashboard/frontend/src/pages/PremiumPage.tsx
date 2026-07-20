import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { PremiumStatus } from "../api/types";
import { formatError } from "../_engine/api/formatError";
import { Alert } from "../_engine/components/Alert";

export function PremiumPage() {
  const { guildId } = useParams<{ guildId: string }>();
  const [premium, setPremium] = useState<PremiumStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!guildId) return;
    api.premium(guildId).then(setPremium).catch((e) => setError(formatError(e)));
  }, [guildId]);

  if (!guildId) return null;

  const tierLabel = premium?.tiers?.length ? premium.tiers.join(", ") : premium?.tier ?? "free";

  return (
    <div className="dash-page" style={{ maxWidth: 640, margin: "0 auto" }}>
      <div className="page-header">
        <div>
          <Link to={`/guilds/${guildId}`} className="muted" style={{ fontSize: 13 }}>← Back</Link>
          <h1 style={{ marginTop: 4 }}>Premium</h1>
        </div>
      </div>

      <Alert kind="danger">{error}</Alert>

      {premium && (
        <div className="card" style={{ marginBottom: 24 }}>
          <h3 style={{ marginBottom: 12 }}>Current Plan</h3>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <div className="stat">
              <span className="value" style={{ fontSize: "1.4rem", textTransform: "capitalize" }}>
                {tierLabel}
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
          {premium.is_premium && premium.expires_at && (
            <p className="muted" style={{ marginTop: 12, fontSize: 13 }}>
              Expires: {new Date(premium.expires_at).toLocaleDateString()}
            </p>
          )}
          {premium.is_premium && !premium.expires_at && (
            <p style={{ marginTop: 12, fontSize: 13, color: "var(--success)" }}>
              Active - no expiry
            </p>
          )}
        </div>
      )}

      {premium && !premium.is_premium && (
        <div className="card">
          <h3 style={{ marginBottom: 12 }}>Upgrade to Premium</h3>
          <p className="muted" style={{ fontSize: 14 }}>
            Premium unlocks more forwarding rules, higher daily limits, and ad-free forwards.
            Premium is managed through Discord - once active it appears here automatically.
          </p>
        </div>
      )}
    </div>
  );
}
