/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useElementWidth, usePrefersReducedMotion } from "./hooks";

export interface BarChartSeries {
  /** Stable identity. Order decides the colour slot, so it must not be sorted. */
  key: string;
  label: string;
  /** One value per group, same length and order as `groups`. */
  values: number[];
}

interface BarChartProps {
  /** X axis labels, already formatted ("Aug"). */
  groups: string[];
  series: BarChartSeries[];
  ariaLabel: string;
  /** Unit word used in the tooltip ("drops"). */
  unit: string;
  height?: number;
  emptyLabel?: string;
}

/**
 * Three categorical slots, taken from the stylesheet by class so the hexes
 * stay in one place. The semantic --success / --warning / --danger colours are
 * deliberately not in this list: they mean state, not identity.
 */
const SERIES_CLASSES = ["series-1", "series-2", "series-3"];
const MAX_COLOURED_SERIES = SERIES_CLASSES.length;

/**
 * Grouped bars. One series draws a plain bar chart; two or more draw grouped
 * bars with a legend, because colour must never be the only thing telling two
 * series apart.
 *
 * Series beyond the three colour slots are folded into a neutral "Other" bar
 * rather than given an invented hue.
 */
export default function BarChart({
  groups,
  series,
  ariaLabel,
  unit,
  height = 96,
  emptyLabel = "Nothing recorded yet.",
}: BarChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const measured = useElementWidth(hostRef, 320);
  const reducedMotion = usePrefersReducedMotion();
  const [hover, setHover] = useState<number | null>(null);

  const drawn: BarChartSeries[] = series.slice(0, MAX_COLOURED_SERIES);
  if (series.length > MAX_COLOURED_SERIES) {
    const rest = series.slice(MAX_COLOURED_SERIES);
    drawn.push({
      key: "__other",
      label: "Other",
      values: groups.map((_, i) => rest.reduce((sum, s) => sum + (s.values[i] ?? 0), 0)),
    });
  }

  const hasData = groups.length > 0 && drawn.some((s) => s.values.some((v) => v > 0));
  if (!hasData) {
    return <p className="ov-muted">{emptyLabel}</p>;
  }

  const W = Math.max(measured, 200);
  const H = height;
  const PT = 6;
  const PB = 18;
  const PL = 2;
  const PR = 2;
  const iw = W - PL - PR;
  const ih = H - PT - PB;

  let peak = 0;
  for (const s of drawn) for (const v of s.values) if (v > peak) peak = v;
  const top = peak > 0 ? peak * 1.15 : 1;

  const groupWidth = iw / groups.length;
  const inset = Math.min(6, groupWidth * 0.14);
  const gap = drawn.length > 1 ? 2 : 0;
  const bandWidth = Math.max(groupWidth - inset * 2, 4);
  // Capped so a three-month chart does not draw slabs; the band is then
  // centred in its group rather than stretched across it.
  const barWidth = Math.min(
    Math.max((bandWidth - gap * (drawn.length - 1)) / drawn.length, 2),
    30,
  );
  const bandUsed = barWidth * drawn.length + gap * (drawn.length - 1);
  const bandOffset = Math.max((groupWidth - bandUsed) / 2, 0);
  const baseline = PT + ih;

  // Thin the axis labels so they never collide in a narrow tile.
  const labelStep = Math.max(1, Math.ceil(groups.length / 6));

  const colourOf = (index: number): string | undefined =>
    index < MAX_COLOURED_SERIES ? SERIES_CLASSES[index] : undefined;

  function handleMove(event: ReactPointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) return;
    const local = ((event.clientX - rect.left) / rect.width) * W;
    const index = Math.floor((local - PL) / groupWidth);
    setHover(Math.min(groups.length - 1, Math.max(0, index)));
  }

  const tipLeft =
    hover === null
      ? 0
      : Math.min(Math.max(PL + hover * groupWidth + groupWidth / 2 - 50, 0), Math.max(W - 120, 0));

  const summary = groups
    .map((g, i) => `${g}: ${drawn.map((s) => `${s.label} ${s.values[i] ?? 0}`).join(", ")}`)
    .join(". ");

  return (
    <div className="chartbox" ref={hostRef}>
      <svg
        role="img"
        aria-label={ariaLabel}
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        onPointerMove={handleMove}
        onPointerDown={handleMove}
        onPointerLeave={() => setHover(null)}
      >
        <line
          x1={PL}
          x2={W - PR}
          y1={baseline}
          y2={baseline}
          strokeWidth={1}
          style={{ stroke: "rgba(255, 255, 255, 0.06)" }}
        />

        {groups.map((group, i) => (
          <g key={`${group}-${i}`}>
            {drawn.map((s, j) => {
              const value = s.values[i] ?? 0;
              if (value <= 0) return null;
              const barHeight = Math.max((ih * value) / top, 2);
              const cls = colourOf(j);
              return (
                <rect
                  key={s.key}
                  x={PL + i * groupWidth + bandOffset + j * (barWidth + gap)}
                  y={baseline - barHeight}
                  width={barWidth}
                  height={barHeight}
                  rx={Math.min(3, barWidth / 2)}
                  className={cls}
                  fill={cls ? "currentColor" : undefined}
                  style={cls ? undefined : { fill: "var(--eos-fg-muted)" }}
                />
              );
            })}
          </g>
        ))}

        {groups.map((group, i) =>
          i % labelStep === 0 || i === groups.length - 1 ? (
            <text
              key={`label-${group}-${i}`}
              x={PL + i * groupWidth + groupWidth / 2}
              y={H - 4}
              textAnchor="middle"
              fontSize={10}
              style={{ fill: "var(--eos-fg-muted)" }}
            >
              {group}
            </text>
          ) : null,
        )}

        {hover !== null && (
          <rect
            x={PL + hover * groupWidth}
            y={PT}
            width={groupWidth}
            height={ih}
            rx={4}
            style={{ fill: "rgba(255, 255, 255, 0.05)" }}
          />
        )}

        {groups.map((group, i) => (
          <rect
            key={`hit-${group}-${i}`}
            x={PL + i * groupWidth}
            y={0}
            width={groupWidth}
            height={H}
            fill="transparent"
          />
        ))}
      </svg>

      <div
        className="chart-tip"
        aria-hidden="true"
        style={{
          opacity: hover === null ? 0 : 1,
          left: tipLeft,
          top: 0,
          transition: reducedMotion ? "none" : undefined,
        }}
      >
        {hover === null ? null : (
          <>
            {groups[hover]}
            {drawn.map((s) => (
              <span key={s.key}>
                <br />
                <b>{s.values[hover] ?? 0}</b> {drawn.length > 1 ? s.label : unit}
              </span>
            ))}
          </>
        )}
      </div>

      {drawn.length > 1 && (
        <div className="chart-legend">
          {drawn.map((s, j) => {
            const cls = colourOf(j);
            return (
              <span key={s.key}>
                <i
                  className={cls}
                  style={{ background: cls ? "currentColor" : "var(--eos-fg-muted)" }}
                />
                {s.label}
              </span>
            );
          })}
        </div>
      )}

      <span className="visually-hidden">{summary}</span>
    </div>
  );
}
