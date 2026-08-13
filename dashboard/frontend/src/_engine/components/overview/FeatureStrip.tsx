/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { Link } from "react-router-dom";
import type { FeatureState, FeatureStatus } from "../../api/types";

/** The state word always ships with the colour - the bar alone says nothing. */
function stateWord(state: FeatureState): string {
  if (state === "on") return "On";
  if (state === "needs_setup") return "Needs setup";
  return "Off";
}

function stateModifier(state: FeatureState): string {
  if (state === "on") return " fstat__c--on";
  if (state === "needs_setup") return " fstat__c--warn";
  return "";
}

/**
 * "Is it working" - one card per feature.
 *
 * The complaint this answers is not that a dashboard is ugly, it is that an
 * admin changes a setting and cannot tell whether anything happened. A bot can
 * join with a permission unticked, look online and silently do nothing.
 */
export default function FeatureStrip({
  guildId,
  features,
  settingsHref,
}: {
  guildId: string;
  features: FeatureStatus[];
  /**
   * Where a feature card links to. Omit it for the fleet default,
   * `/settings/<guildId>?s=<settings_key>`; a bot whose settings live at a
   * different route passes its own builder.
   */
  settingsHref?: (settingsKey: string) => string;
}) {
  if (features.length === 0) {
    return <p className="ov-muted">No features are reporting a status for this server yet.</p>;
  }

  const hrefFor =
    settingsHref ??
    ((settingsKey: string) => `/settings/${guildId}?s=${encodeURIComponent(settingsKey)}`);

  return (
    <div className="fstat">
      {features.map((feature) => {
        const body = (
          <>
            <div className="fstat__n">{feature.label}</div>
            <div className="fstat__s">
              <b>{stateWord(feature.state)}</b>
              {feature.detail ? ` · ${feature.detail}` : ""}
            </div>
          </>
        );
        const className = `fstat__c${stateModifier(feature.state)}`;

        return feature.settings_key ? (
          <Link key={feature.key} className={className} to={hrefFor(feature.settings_key)}>
            {body}
          </Link>
        ) : (
          <div key={feature.key} className={className}>
            {body}
          </div>
        );
      })}
    </div>
  );
}

/** Counts for the chips in the tile head. */
export function featureCounts(features: FeatureStatus[]) {
  return {
    on: features.filter((f) => f.state === "on").length,
    needsSetup: features.filter((f) => f.state === "needs_setup").length,
    off: features.filter((f) => f.state === "off").length,
  };
}
