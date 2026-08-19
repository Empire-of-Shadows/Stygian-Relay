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

  const lastGroup = groups.length - 1;
  // Text width is estimated at ~0.62em per character plus a little breathing
  // room, rather than measured, so this stays a single render with no second
  // layout pass. The 8px is the minimum gap between two neighbouring labels.
  const labelWidth = groups.reduce((n, g) => Math.max(n, g.length), 0) * 6.2 + 8;

  /**
   * Where a label under group `i` is actually painted. An end label that would
   * run past the plot is pulled inward instead of clipped, so its span is not
   * always centred on its bar - which is why the thinning below has to test
   * these spans rather than assume the drawn indexes are evenly spaced.
   */
  function labelPlacement(i: number) {
    const centre = PL + i * groupWidth + groupWidth / 2;
    const half = labelWidth / 2;
    if (centre - half < PL) {
      return { x: PL, anchor: "start" as const, from: PL, to: PL + labelWidth };
    }
    if (centre + half > W - PR) {
      return { x: W - PR, anchor: "end" as const, from: W - PR - labelWidth, to: W - PR };
    }
    return { x: centre, anchor: "middle" as const, from: centre - half, to: centre + half };
  }

  // Thin the axis labels so they never collide in a narrow tile. Group count
  // alone cannot decide this: the old rule allowed six labels whatever the
  // width and then forced the last one on top of that, which put two labels a
  // single group apart whenever the count was not a multiple of the step -
  // eight groups drew 0, 2, 4, 6 and then 7 as its neighbour. Instead, take
  // the most labels that genuinely fit: try six spread evenly across the axis,
  // drop to five, and so on until no two painted spans touch. Spreading from
  // both ends keeps the first and last groups labelled, which a fixed step
  // stepping from zero does not.
  const evenlySpread = (slots: number) => [
    ...new Set(
      Array.from({ length: slots }, (_, k) => Math.round((k * lastGroup) / (slots - 1))),
    ),
  ];
  const spansClear = (indexes: number[]) =>
    indexes.every((i, k) => k === 0 || labelPlacement(indexes[k - 1]).to <= labelPlacement(i).from);

  // Falls back to the most recent group alone, for when even the two ends
  // would overlap each other.
  let labelIndexes = [lastGroup];
  for (let slots = Math.min(6, groups.length); slots >= 2; slots--) {
    const candidate = evenlySpread(slots);
    if (candidate.length === slots && spansClear(candidate)) {
      labelIndexes = candidate;
      break;
    }
  }
  const labelled = new Set(labelIndexes);

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

        {groups.map((group, i) => {
          if (!labelled.has(i)) return null;
          const { x, anchor } = labelPlacement(i);
          return (
            <text
              key={`label-${group}-${i}`}
              x={x}
              y={H - 4}
              textAnchor={anchor}
              fontSize={10}
              style={{ fill: "var(--eos-fg-muted)" }}
            >
              {group}
            </text>
          );
        })}

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
