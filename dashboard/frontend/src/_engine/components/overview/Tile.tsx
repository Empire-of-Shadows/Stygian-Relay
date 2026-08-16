/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import type { CSSProperties, ReactNode } from "react";

type Span = 3 | 4 | 5 | 6 | 7 | 8 | 12;

interface TileProps {
  /** Columns out of twelve. The class has to sit on the direct grid child. */
  span: Span;
  title: string;
  /** A glyph rendered in the head, ahead of the title. */
  icon?: ReactNode;
  /** Any CSS colour. Draws a rail down the left edge in that colour - use it to
   *  tie a tile to something the page already colours (a series, a state), never
   *  as decoration. */
  accent?: string;
  /** Chips rendered inline after the title. */
  chips?: ReactNode;
  /** Links or buttons pushed to the right of the head. */
  action?: ReactNode;
  /** The one live tile in this composition; use it once per composition or it stops
   *  meaning anything. A page that renders two compositions (member and server, say)
   *  carries one live tile in each. */
  live?: boolean;
  /** Dashed, transparent treatment for a section with nothing in it. */
  quiet?: boolean;
  children: ReactNode;
}

export function Tile({ span, title, icon, accent, chips, action, live, quiet, children }: TileProps) {
  const classes = ["ov-card"];
  if (live) classes.push("ov-card--live");
  if (quiet) classes.push("ov-card--quiet");
  if (accent) classes.push("ov-card--accent");
  classes.push(`s${span}`);
  // The colour travels as a custom property so the rail itself stays one rule in
  // eos-layout.css. Nothing is emitted at all when no accent was asked for.
  const style = accent ? ({ "--tile-accent": accent } as CSSProperties) : undefined;
  return (
    <section className={classes.join(" ")} style={style}>
      <div className="ov-card__head">
        {icon ? <span className="ov-card__icon">{icon}</span> : null}
        <span className="ov-card__title">{title}</span>
        {chips}
        {action ? <div className="ov-card__act">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

interface StatProps {
  value: ReactNode;
  label: string;
  /** Smaller trailing part of the figure, such as "/30". */
  sub?: ReactNode;
  /** Smaller figure - used wherever several stats share a row. */
  small?: boolean;
}

export function Stat({ value, label, sub, small }: StatProps) {
  return (
    <div>
      <div className={small ? "ov-stat ov-stat--sm" : "ov-stat"}>
        {value}
        {sub ? <span className="ov-stat__sub">{sub}</span> : null}
      </div>
      <div className="ov-stat-l">{label}</div>
    </div>
  );
}

export function KeyValue({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="ov-kv">
      <span className="ov-kv__k">{k}</span>
      <span className="ov-kv__v">{v}</span>
    </div>
  );
}

export function Rule() {
  return <div className="ov-rule" />;
}

/** A section the API could not return, said plainly rather than shown as zero. */
export function SectionUnavailable({ what }: { what: string }) {
  return <p className="ov-muted">{what} could not be loaded right now. Refresh to try again.</p>;
}
