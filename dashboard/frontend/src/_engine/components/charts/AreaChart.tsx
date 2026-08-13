/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { useId, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useElementWidth, usePrefersReducedMotion } from "./hooks";

export interface AreaChartPoint {
  /** Short axis label, already formatted for display ("4 Aug"). */
  label: string;
  value: number;
}

interface AreaChartProps {
  points: AreaChartPoint[];
  /** Sentence describing the whole chart, for screen readers. */
  ariaLabel: string;
  /** Unit word used in the tooltip ("votes"). */
  unit: string;
  height?: number;
  /**
   * Categorical colour slot from the stylesheet. The class sets `color`, and
   * every painted part of the chart uses `currentColor`, so the hex values live
   * in the stylesheet and never in here.
   */
  seriesClass?: string;
  /** Shown in place of the plot when there is not enough history to draw. */
  emptyLabel?: string;
}

/**
 * One series over time: 2px line, gradient area fill, three-line grid, an
 * emphasised endpoint, and a crosshair plus tooltip on hover.
 *
 * A single series carries no legend on purpose - the tile title names it.
 */
export default function AreaChart({
  points,
  ariaLabel,
  unit,
  height = 132,
  seriesClass = "series-1",
  emptyLabel = "Not enough history to draw a trend yet.",
}: AreaChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const measured = useElementWidth(hostRef);
  const reducedMotion = usePrefersReducedMotion();
  const rawId = useId();
  const [hover, setHover] = useState<number | null>(null);

  if (points.length < 2) {
    return <p className="ov-muted">{emptyLabel}</p>;
  }

  const gradientId = `area-fill-${rawId.replace(/[^a-zA-Z0-9]/g, "")}`;
  const W = Math.max(measured, 200);
  const H = height;
  const PT = 12;
  const PB = 20;
  const PL = 6;
  const PR = 6;
  const iw = W - PL - PR;
  const ih = H - PT - PB;

  const last = points.length - 1;
  const values = points.map((p) => p.value);
  const peak = Math.max(...values);
  const top = peak > 0 ? peak * 1.25 : 1;

  const x = (i: number) => PL + (iw * i) / last;
  const y = (v: number) => PT + ih - (ih * v) / top;

  const line = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${x(last).toFixed(1)} ${(PT + ih).toFixed(1)} L${PL} ${(PT + ih).toFixed(1)} Z`;

  // First, middle and last only - a label under every point is unreadable.
  const labelIndexes = Array.from(new Set([0, Math.floor(last / 2), last]));

  const peakIndex = values.indexOf(peak);
  const summary =
    `${points.length} points from ${points[0].label} to ${points[last].label}. ` +
    `Highest ${peak} ${unit} on ${points[peakIndex].label}. ` +
    `Most recent ${values[last]} ${unit} on ${points[last].label}.`;

  const active = hover === null ? null : points[hover];
  const tipLeft = hover === null ? 0 : Math.min(Math.max(x(hover) - 46, 0), Math.max(W - 116, 0));

  function handleMove(event: ReactPointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const local = ((event.clientX - rect.left) / rect.width) * W;
    const index = Math.round(((local - PL) / iw) * last);
    setHover(Math.min(last, Math.max(0, index)));
  }

  return (
    <div className="chartbox" ref={hostRef}>
      <svg
        className={seriesClass}
        role="img"
        aria-label={ariaLabel}
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        onPointerMove={handleMove}
        onPointerDown={handleMove}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity={0.42} />
            <stop offset="100%" stopColor="currentColor" stopOpacity={0.02} />
          </linearGradient>
        </defs>

        {[0, 0.5, 1].map((fraction) => (
          <line
            key={fraction}
            x1={PL}
            x2={W - PR}
            y1={PT + ih * fraction}
            y2={PT + ih * fraction}
            style={{ stroke: "rgba(255, 255, 255, 0.06)" }}
            strokeWidth={1}
          />
        ))}

        <path d={area} fill={`url(#${gradientId})`} />
        <path
          d={line}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        <circle
          cx={x(last)}
          cy={y(values[last])}
          r={4.5}
          fill="currentColor"
          strokeWidth={2}
          style={{ stroke: "var(--eos-bg-2)" }}
        />

        <line
          x1={hover === null ? 0 : x(hover)}
          x2={hover === null ? 0 : x(hover)}
          y1={PT}
          y2={PT + ih}
          strokeWidth={1}
          style={{
            stroke: "rgba(255, 255, 255, 0.28)",
            opacity: hover === null ? 0 : 1,
            transition: reducedMotion ? "none" : "opacity 100ms ease",
          }}
        />
        <circle
          cx={hover === null ? 0 : x(hover)}
          cy={hover === null ? 0 : y(values[hover])}
          r={4}
          fill="currentColor"
          strokeWidth={2}
          style={{
            stroke: "var(--eos-bg-2)",
            opacity: hover === null ? 0 : 1,
            transition: reducedMotion ? "none" : "opacity 100ms ease",
          }}
        />

        {labelIndexes.map((i) => (
          <text
            key={i}
            x={x(i)}
            y={H - 5}
            textAnchor={i === 0 ? "start" : i === last ? "end" : "middle"}
            fontSize={10}
            style={{ fill: "var(--eos-fg-muted)" }}
          >
            {points[i].label}
          </text>
        ))}
      </svg>

      <div
        className="chart-tip"
        aria-hidden="true"
        style={{
          opacity: active === null ? 0 : 1,
          left: tipLeft,
          top: 0,
          transition: reducedMotion ? "none" : undefined,
        }}
      >
        {active === null ? null : (
          <>
            <b>{active.value}</b> {unit}
            <br />
            {active.label}
          </>
        )}
      </div>

      <span className="visually-hidden">{summary}</span>
    </div>
  );
}
