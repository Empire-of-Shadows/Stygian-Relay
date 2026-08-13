/* VENDORED from dashboard_engine/ - DO NOT EDIT HERE.
   Edit the master at EmpireSystems/dashboard_engine/ and run:
     python EmpireSystems/tools/sync_dashboard_engine.py
   Drift is enforced by:
     python EmpireSystems/tools/sync_dashboard_engine.py --check */
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import type { ReactNode, Ref, RefObject } from "react";
import "./styles/GuildWebScene.css";
import type { Guild } from "../api/types";

/**
 * GuildWebScene - the living "web of servers" scene.
 *
 * A full-bleed, physically simulated network of the guilds a user can manage: a
 * central hub, one orb per guild, silk strands between them, signal pulses along
 * the strands, and two layers of ambient dust the title copy sits between.
 *
 * WHY IT IS IMPERATIVE. Everything inside the `<svg>` and the two `<canvas>`
 * layers is built and moved with direct DOM writes rather than React state. A
 * force simulation runs every animation frame; re-rendering a React tree at 60fps
 * for that is not viable. React owns the shell (the scene box, the copy slot, the
 * canvases, the svg root) and the imperative layer owns everything painted inside
 * it. Selection stays a React prop, so the page remains the source of truth.
 *
 * OWNERSHIP. This component is generic: it knows nothing about any one bot. The
 * title copy arrives as `children` and is rendered top-left inside the scene; the
 * detail panel is the page's own markup, anchored by `tetherTo`. Guild icon URLs
 * arrive through `iconUrl` because the CDN path is the bot's call.
 *
 * SIZING. The scene fills its parent edge to edge. The page decides the viewport
 * maths - this component never reads the window box - so the parent must be
 * `position: relative` and must have a height of its own (see the contract note
 * in GuildWebScene.css; a percentage height would resolve to zero there).
 *
 * REDUCED MOTION. Under `prefers-reduced-motion: reduce` the layout is settled
 * synchronously and drawn once, the dust is painted as a single still field, and
 * the entry flight, pulses and parallax never run. Selecting, dragging and
 * keyboard operation all still work.
 */

const NS = "http://www.w3.org/2000/svg";

/** Hub radius, and the viewport margins each body bounces off. */
const HUB_R = 34;
const HUB_MARGIN = 58;
const NODE_MARGIN = 80;
/** Below this scene width the blob docks to the bottom (keep in step with the
 *  .gw-blob media query in GuildWebScene.css) and the web leans UP, not left. */
const NARROW = 640;
/** How much speed survives a wall bounce. */
const RESTITUTION = 0.72;
/** Ceiling on throw velocity, so a violent flick cannot slingshot a node. */
const THROW_CAP = 26;
const DUST_COUNT = 190;
/** Entry flight: seconds between launches, and seconds per node. */
const ENTRY_STAGGER = 0.09;
const ENTRY_DUR = 0.65;
/** Signal pulses along the hub spokes, and the faster ones along the tether. */
const PULSE_CADENCE = 1400;
const PULSE_DUR = 1500;
const TETHER_CADENCE = 460;
const TETHER_DUR = 800;
/**
 * The simulation never fully freezes. A small alpha floor keeps thrown bodies
 * flying, bounces bouncing, and the web faintly alive at rest.
 */
const ALPHA_FLOOR = 0.08;
/** Uniform orb radius used when a guild reports no member count. */
const BASE_R = 26;

/** Unique per mounted scene, so two scenes never share an SVG defs id. */
let sceneSeq = 0;

/** How a guild's orb reads: configured, needs setup, or the bot is not there. */
export type GuildWebState = "ok" | "setup" | "missing";

/**
 * Map production guild fields onto the three visual states.
 *
 * `setup_required` is treated as setup on its own because some dashboards set it
 * for reasons beyond a missing config document; "the bot is not in the guild"
 * always wins, since nothing else is actionable there.
 */
export function guildWebState(g: Guild): GuildWebState {
  if (!g.bot_in_guild) return "missing";
  if (!g.has_config || g.setup_required) return "setup";
  return "ok";
}

export interface GuildWebSceneHandle {
  /** Re-run the staggered entry flight. A no-op under reduced motion. */
  replay(): void;
}

interface SimNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  /** Mass. Bigger orbs are denser, so the same force moves them less. */
  m: number;
  /** Entry-flight destination. */
  tx: number;
  ty: number;
}

interface DustMote {
  x: number;
  y: number;
  r: number;
  s: number;
  a: number;
  o: number;
  /** < 0.5 renders behind the copy, >= 0.5 in front of it. */
  depth: number;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface LinkEl {
  link: [string, string];
  fils: SVGPathElement[];
  idx: number;
}

interface Pulse {
  path: SVGPathElement;
  born: number;
  dur: number;
}

interface DragState {
  id: string;
  dx: number;
  dy: number;
  tvx: number;
  tvy: number;
  lastX: number;
  lastY: number;
  lastT: number;
}

/** Stable per-guild hue in the violet band, derived from the snowflake. */
function hueFor(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return 240 + (h % 70);
}

/**
 * Orb radius by member count, on a square-root scale so a 5000-member server is
 * bigger than a 50-member one without dwarfing it. Uniform when the count is
 * absent - a bot that does not report member counts gets an even web.
 */
function nodeRadius(g: Guild): number {
  const mc = g.member_count;
  if (mc === null || mc === undefined) return BASE_R;
  return Math.max(18, Math.min(34, 10 + Math.sqrt(Math.max(0, mc)) * 1.15));
}

function ease(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/** Hub spokes, plus a ring and a few chords, so the layout reads as a web. */
function buildLinks(ids: string[]): [string, string][] {
  const out: [string, string][] = ids.map((id) => ["hub", id]);
  const n = ids.length;
  if (n >= 3) for (let i = 0; i < n; i++) out.push([ids[i], ids[(i + 1) % n]]);
  if (n >= 5) for (let j = 0; j < n; j++) out.push([ids[j], ids[(j + 2) % n]]);
  return out;
}

/** One filament of a strand: a quadratic bow, offset so the three do not overlap. */
function vinePath(a: { x: number; y: number }, b: { x: number; y: number }, idx: number, fil: number): string {
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const base = Math.min(40, len * 0.12) * (idx % 2 ? 1 : -1);
  const off = base + (fil - 1) * 7;
  const cx = mx + (-dy / len) * off;
  const cy = my + (dx / len) * off;
  return `M ${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}`;
}

function truncate(name: string, max = 15): string {
  return name.length > max ? name.slice(0, max - 1) + "..." : name;
}

function svgEl<K extends keyof SVGElementTagNameMap>(name: K, cls?: string): SVGElementTagNameMap[K] {
  const e = document.createElementNS(NS, name);
  if (cls) e.setAttribute("class", cls);
  return e;
}

export function GuildWebScene({
  guilds,
  selectedId,
  onSelect,
  children,
  tetherTo,
  iconUrl,
  hubIcon,
  hubMark,
  ref,
}: {
  guilds: Guild[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /**
   * Rendered inside the scene, top-left. Any element in here carrying
   * `data-gw-collide` is measured on mount and on resize: the dust bounces off
   * it and the orbs are pushed out of it, so the copy owns its corner.
   */
  children?: ReactNode;
  /**
   * The detail panel. While a node is selected, a glowing tether is drawn from
   * that node to this element's left-centre, with pulses running along it.
   */
  tetherTo?: RefObject<HTMLElement | null>;
  /** Real icon URL for a guild, or null to use the generated gradient orb. */
  iconUrl?: (g: Guild) => string | null;
  /** Optional image drawn in the hub core (a bot's logo mark). */
  hubIcon?: string | null;
  /** Optional glyph drawn in the hub core when there is no `hubIcon`. */
  hubMark?: string;
  ref?: Ref<GuildWebSceneHandle>;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const backRef = useRef<HTMLCanvasElement>(null);
  const frontRef = useRef<HTMLCanvasElement>(null);
  const copyRef = useRef<HTMLDivElement>(null);

  const [size, setSize] = useState({ w: 0, h: 0 });
  const [reduce, setReduce] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );

  // Live prop mirrors. The animation loop is imperative and outlives any single
  // render, so it reads the current values through refs rather than closing over
  // the values captured when the effect ran.
  const selectedRef = useRef<string | null>(selectedId);
  selectedRef.current = selectedId;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const tetherRef = useRef(tetherTo);
  tetherRef.current = tetherTo;

  /** Handle onto the running simulation, or null while nothing is mounted. */
  const simRef = useRef<{
    settle: (from: number) => void;
    draw: () => void;
    retarget: () => void;
    replay: () => void;
  } | null>(null);

  useImperativeHandle(ref, () => ({
    replay: () => simRef.current?.replay(),
  }), []);

  // ── Reduced-motion tracking ─────────────────────────────────────────────
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    if (!mq) return;
    const onChange = () => setReduce(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // ── Scene box ───────────────────────────────────────────────────────────
  // The first measurement lands immediately so the web paints without delay;
  // later ones are debounced, because a live window drag would otherwise rebuild
  // the whole scene on every frame of the resize.
  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    let timer: number | undefined;
    let first = true;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect;
      if (r.width <= 0 || r.height <= 0) return;
      const next = { w: Math.round(r.width), h: Math.round(r.height) };
      if (first) {
        first = false;
        setSize(next);
        return;
      }
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setSize(next), 150);
    });
    ro.observe(el);
    return () => {
      window.clearTimeout(timer);
      ro.disconnect();
    };
  }, []);

  // Everything that changes what is drawn. Selection is deliberately absent: it
  // is applied without rebuilding the scene.
  const dataKey = guilds
    .map((g) => [g.id, g.name, g.icon ?? "", g.member_count ?? "", g.bot_in_guild, g.has_config, g.setup_required].join(":"))
    .join("|");

  // ── The scene itself ────────────────────────────────────────────────────
  useEffect(() => {
    const root = rootRef.current;
    const svg = svgRef.current;
    const backCv = backRef.current;
    const frontCv = frontRef.current;
    const copy = copyRef.current;
    if (!root || !svg || !backCv || !frontCv || !copy) return;
    const W = size.w;
    const H = size.h;
    if (W <= 0 || H <= 0) return;

    const backCtx = backCv.getContext("2d");
    const frontCtx = frontCv.getContext("2d");
    if (!backCtx || !frontCtx) return;

    const uid = ++sceneSeq;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const cs = getComputedStyle(root);
    const dustColor = cs.getPropertyValue("--gw-silk").trim() || "#7a3df0";

    // ── State ──
    const nodes = new Map<string, SimNode>();
    const links = buildLinks(guilds.map((g) => g.id));
    const linkEls: LinkEl[] = [];
    const nodeEls = new Map<string, SVGGElement>();
    const states = new Map<string, GuildWebState>();
    let alpha = 0;
    let entryStart: number | null = null;
    let pulses: Pulse[] = [];
    let tetherPulses: { born: number; dur: number }[] = [];
    let lastSpawn = 0;
    let lastTetherSpawn = 0;
    let drag: DragState | null = null;
    let dust: DustMote[] = [];
    let collide: Box[] = [];
    let rootRect: DOMRect = root.getBoundingClientRect();
    const mouse = { x: 0.5, y: 0.5 };
    const hubTarget = { x: W * 0.56, y: H * 0.55 };
    let tetherEl: SVGPathElement | null = null;
    let pulseGroup: SVGGElement | null = null;
    let hubEl: SVGGElement | null = null;
    let raf = 0;

    // ── Measurement ──
    const measure = () => {
      rootRect = root.getBoundingClientRect();
      const pad = 10;
      const next: Box[] = [];
      copy.querySelectorAll<HTMLElement>("[data-gw-collide]").forEach((elm) => {
        const r = elm.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return;
        next.push({
          x: r.left - rootRect.left - pad,
          y: r.top - rootRect.top - pad,
          w: r.width + pad * 2,
          h: r.height + pad * 2,
        });
      });
      collide = next;
    };

    // ── Physics ──
    const applyForces = (a: number) => {
      const arr = [...nodes.values()];
      const linkLen = Math.min(W, H) * 0.28;
      const kRep = Math.pow(Math.min(W, H), 2) * 0.05;

      for (let i = 0; i < arr.length; i++) {
        for (let j = i + 1; j < arr.length; j++) {
          const p = arr[i];
          const q = arr[j];
          const dx = p.x - q.x;
          const dy = p.y - q.y;
          const d2 = dx * dx + dy * dy || 0.01;
          const d = Math.sqrt(d2);
          const f = (kRep / d2) * a;
          const ux = dx / d;
          const uy = dy / d;
          p.vx += (ux * f) / p.m;
          p.vy += (uy * f) / p.m;
          q.vx -= (ux * f) / q.m;
          q.vy -= (uy * f) / q.m;
        }
      }

      for (const [sId, tId] of links) {
        const s = nodes.get(sId);
        const t = nodes.get(tId);
        if (!s || !t) continue;
        const dx = t.x - s.x;
        const dy = t.y - s.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const f = 0.045 * (d - linkLen) * a;
        const ux = dx / d;
        const uy = dy / d;
        s.vx += (ux * f) / s.m;
        s.vy += (uy * f) / s.m;
        t.vx -= (ux * f) / t.m;
        t.vy -= (uy * f) / t.m;
      }

      for (const n of arr) {
        if (drag && drag.id === n.id) {
          n.vx = 0;
          n.vy = 0;
          continue;
        }
        if (n.id === "hub") {
          // A free body: weak homing and light damping, so a throw flies and the
          // whole web chases it instead of the centre snapping back.
          n.vx += (hubTarget.x - n.x) * 0.0009;
          n.vy += (hubTarget.y - n.y) * 0.0009;
          n.vx *= 0.965;
          n.vy *= 0.965;
        } else {
          n.vx += (hubTarget.x - n.x) * 0.0025 * a;
          n.vy += (hubTarget.y - n.y) * 0.0025 * a;
          // The copy owns its corner: orbs are pushed gently out of it.
          for (const r of collide) {
            const cx = Math.max(r.x, Math.min(r.x + r.w, n.x));
            const cy = Math.max(r.y, Math.min(r.y + r.h, n.y));
            let dx = n.x - cx;
            let dy = n.y - cy;
            const d2 = dx * dx + dy * dy;
            const reach = 90;
            if (d2 < reach * reach) {
              const d = Math.sqrt(d2) || 1;
              const f = ((reach - d) / reach) * 1.6 * a / n.m;
              if (d2 < 1) {
                dx = 0.6;
                dy = 1;
              }
              n.vx += (dx / d) * f;
              n.vy += (dy / d) * f;
            }
          }
          n.vx *= 0.9;
          n.vy *= 0.9;
        }
        n.x += n.vx;
        n.y += n.vy;
        // Bounce off the edges instead of sticking to them.
        const mg = n.id === "hub" ? HUB_MARGIN : NODE_MARGIN;
        if (n.x < mg) { n.x = mg; n.vx = Math.abs(n.vx) * RESTITUTION; }
        if (n.x > W - mg) { n.x = W - mg; n.vx = -Math.abs(n.vx) * RESTITUTION; }
        if (n.y < mg) { n.y = mg; n.vy = Math.abs(n.vy) * RESTITUTION; }
        if (n.y > H - mg) { n.y = H - mg; n.vy = -Math.abs(n.vy) * RESTITUTION; }
      }
    };

    const settle = (from: number) => {
      let a = from;
      for (let k = 0; k < 400 && a > 0.02; k++) {
        applyForces(a);
        a *= 0.985;
      }
    };

    // ── Seed ──
    const seed = () => {
      nodes.clear();
      nodes.set("hub", { id: "hub", x: hubTarget.x, y: hubTarget.y, vx: 0, vy: 0, m: 3, tx: hubTarget.x, ty: hubTarget.y });
      const ring = Math.min(W, H) * 0.3;
      guilds.forEach((g, i) => {
        const ang = (i / Math.max(1, guilds.length)) * Math.PI * 2 + 0.4;
        const r = ring * (0.8 + (i % 3) * 0.14);
        // Density: mass grows with the orb's area, so big servers throw heavy.
        const m = Math.pow(nodeRadius(g) / BASE_R, 2);
        nodes.set(g.id, {
          id: g.id,
          x: hubTarget.x,
          y: hubTarget.y,
          vx: 0,
          vy: 0,
          m,
          tx: hubTarget.x + Math.cos(ang) * r,
          ty: hubTarget.y + Math.sin(ang) * r,
        });
        states.set(g.id, guildWebState(g));
      });
    };

    // ── DOM ──
    const buildDOM = () => {
      svg.replaceChildren();
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

      const defs = svgEl("defs");
      guilds.forEach((g) => {
        const hue = hueFor(g.id);
        const grad = svgEl("radialGradient");
        grad.setAttribute("id", `gw-orb-${uid}-${g.id}`);
        const s0 = svgEl("stop");
        s0.setAttribute("offset", "0%");
        s0.setAttribute("stop-color", `hsl(${hue}, 62%, 58%)`);
        const s1 = svgEl("stop");
        s1.setAttribute("offset", "100%");
        s1.setAttribute("stop-color", `hsl(${hue}, 68%, 30%)`);
        grad.append(s0, s1);
        defs.appendChild(grad);

        const clip = svgEl("clipPath");
        clip.setAttribute("id", `gw-clip-${uid}-${g.id}`);
        const cc = svgEl("circle");
        cc.setAttribute("r", String(nodeRadius(g)));
        clip.appendChild(cc);
        defs.appendChild(clip);
      });
      const hubClip = svgEl("clipPath");
      hubClip.setAttribute("id", `gw-hubclip-${uid}`);
      const hc = svgEl("circle");
      hc.setAttribute("r", String(HUB_R));
      hubClip.appendChild(hc);
      defs.appendChild(hubClip);
      svg.appendChild(defs);

      // Strands: three filaments each, so a link reads as silk rather than wire.
      linkEls.length = 0;
      const strandGroup = svgEl("g");
      links.forEach((link, i) => {
        const fils: SVGPathElement[] = [];
        for (let f = 0; f < 3; f++) {
          const p = svgEl("path", `gw-vine gw-vine--f${f}`);
          strandGroup.appendChild(p);
          fils.push(p);
        }
        linkEls.push({ link, fils, idx: i });
      });
      svg.appendChild(strandGroup);

      tetherEl = svgEl("path", "gw-tether");
      tetherEl.style.display = "none";
      svg.appendChild(tetherEl);

      hubEl = svgEl("g", "gw-hub");
      const halo = svgEl("circle", "gw-hub-halo gw-hub-breathe");
      halo.setAttribute("r", String(HUB_R + 12));
      const runes = svgEl("circle", "gw-hub-runes gw-hub-spin");
      runes.setAttribute("r", String(HUB_R + 20));
      const core = svgEl("circle", "gw-hub-core");
      core.setAttribute("r", String(HUB_R));
      hubEl.append(halo, runes, core);
      if (hubIcon) {
        const img = svgEl("image");
        img.setAttribute("href", hubIcon);
        img.setAttribute("x", String(-HUB_R));
        img.setAttribute("y", String(-HUB_R));
        img.setAttribute("width", String(HUB_R * 2));
        img.setAttribute("height", String(HUB_R * 2));
        img.setAttribute("clip-path", `url(#gw-hubclip-${uid})`);
        img.setAttribute("preserveAspectRatio", "xMidYMid slice");
        img.addEventListener("error", () => img.remove());
        hubEl.appendChild(img);
      } else if (hubMark) {
        const mark = svgEl("text", "gw-hub-mark");
        mark.textContent = hubMark;
        hubEl.appendChild(mark);
      }
      const ring = svgEl("circle", "gw-hub-ring");
      ring.setAttribute("r", String(HUB_R));
      hubEl.appendChild(ring);
      hubEl.addEventListener("pointerdown", (e) => startDrag("hub", hubEl!, e));
      svg.appendChild(hubEl);

      pulseGroup = svgEl("g", "gw-pulses");
      svg.appendChild(pulseGroup);

      nodeEls.clear();
      guilds.forEach((g) => {
        const r = nodeRadius(g);
        const state = states.get(g.id) ?? "ok";
        const grp = svgEl("g", `gw-node gw-node--${state}`);
        grp.setAttribute("tabindex", "0");
        grp.setAttribute("role", "button");
        grp.setAttribute(
          "aria-label",
          g.name + (state === "setup" ? " (needs setup)" : state === "missing" ? " (bot not in server)" : ""),
        );

        const glow = svgEl("circle", "gw-aura-glow");
        glow.setAttribute("r", String(r + 6));
        const orb = svgEl("circle", "gw-node-orb");
        orb.setAttribute("r", String(r));
        orb.setAttribute("fill", `url(#gw-orb-${uid}-${g.id})`);
        grp.append(glow, orb);

        const initial = svgEl("text", "gw-node-initial");
        initial.setAttribute("style", `font-size:${Math.round(r * 0.72)}px`);
        initial.textContent = (g.name || "?").charAt(0);
        grp.appendChild(initial);

        // A real icon when the bot supplied one; the generated orb + initial is
        // what stays behind if it is absent or fails to load.
        const url = iconUrl?.(g) ?? null;
        if (url) {
          const img = svgEl("image");
          img.setAttribute("href", url);
          img.setAttribute("x", String(-r));
          img.setAttribute("y", String(-r));
          img.setAttribute("width", String(r * 2));
          img.setAttribute("height", String(r * 2));
          img.setAttribute("clip-path", `url(#gw-clip-${uid}-${g.id})`);
          img.setAttribute("preserveAspectRatio", "xMidYMid slice");
          img.addEventListener("error", () => img.remove());
          grp.appendChild(img);
        }

        const nring = svgEl("circle", "gw-node-ring");
        nring.setAttribute("r", String(r));
        grp.appendChild(nring);

        const label = svgEl("text", "gw-node-label");
        label.setAttribute("y", String(r + 17));
        label.textContent = truncate(g.name || "Unknown");
        grp.appendChild(label);

        const toggle = () => onSelectRef.current(g.id === selectedRef.current ? null : g.id);
        grp.addEventListener("click", toggle);
        grp.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            toggle();
          }
        });
        grp.addEventListener("pointerdown", (e) => startDrag(g.id, grp, e));

        svg.appendChild(grp);
        nodeEls.set(g.id, grp);
      });
    };

    const startDrag = (id: string, el: SVGGElement, e: PointerEvent) => {
      const n = nodes.get(id);
      if (!n) return;
      const lx = e.clientX - rootRect.left;
      const ly = e.clientY - rootRect.top;
      drag = { id, dx: n.x - lx, dy: n.y - ly, tvx: 0, tvy: 0, lastX: e.clientX, lastY: e.clientY, lastT: performance.now() };
      el.setPointerCapture(e.pointerId);
      alpha = Math.max(alpha, 0.5);
    };

    // ── Drawing ──
    const blobAnchor = (from?: { x: number; y: number } | null): { x: number; y: number } | null => {
      const el = tetherRef.current?.current;
      if (!el) return null;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return null;
      const left = r.left - rootRect.left;
      const top = r.top - rootRect.top;
      if (!from) return { x: left + 6, y: top + r.height / 2 };
      // Attach at the nearest point on the blob's edge, so the tether reads
      // right whether the blob floats at the side (desktop) or docks to the
      // bottom (phones) - no layout-mode detection needed.
      const ax = Math.max(left, Math.min(left + r.width, from.x));
      const ay = Math.max(top, Math.min(top + r.height, from.y));
      if (ax > left && ax < left + r.width && ay > top && ay < top + r.height) {
        // The node sits over the blob: fall back to its top-centre.
        return { x: left + r.width / 2, y: top + 4 };
      }
      return { x: ax, y: ay };
    };

    const draw = () => {
      const sel = selectedRef.current;
      for (const le of linkEls) {
        const a = nodes.get(le.link[0]);
        const b = nodes.get(le.link[1]);
        if (!a || !b) continue;
        const active = sel !== null && (le.link[0] === sel || le.link[1] === sel);
        const dim = sel !== null && !active;
        le.fils.forEach((p, f) => {
          p.setAttribute("d", vinePath(a, b, le.idx, f));
          p.classList.toggle("is-active", active);
          p.classList.toggle("is-dim", dim);
        });
      }
      const hub = nodes.get("hub");
      if (hubEl && hub) hubEl.setAttribute("transform", `translate(${hub.x} ${hub.y})`);
      for (const g of guilds) {
        const n = nodes.get(g.id);
        const el = nodeEls.get(g.id);
        if (!n || !el) continue;
        el.setAttribute("transform", `translate(${n.x} ${n.y})`);
        el.classList.toggle("is-selected", g.id === sel);
        el.classList.toggle("is-dim", sel !== null && g.id !== sel);
      }
      // The panel hangs off the selected node by its own strand.
      const selNode = sel ? nodes.get(sel) : null;
      const anchor = selNode ? blobAnchor(selNode) : null;
      if (tetherEl && anchor && selNode) {
        tetherEl.style.display = "";
        tetherEl.setAttribute("d", vinePath(selNode, anchor, 0, 1));
      } else if (tetherEl) {
        tetherEl.style.display = "none";
      }
    };

    // ── Pulses ──
    const spawnPulse = (now: number) => {
      const candidates = linkEls.filter(
        (le) => le.link[0] === "hub" && states.get(le.link[1]) !== "missing",
      );
      if (!candidates.length) return;
      const le = candidates[Math.floor(Math.random() * candidates.length)];
      pulses.push({ path: le.fils[0], born: now, dur: PULSE_DUR });
    };

    const stepPulses = (now: number) => {
      const group = pulseGroup;
      if (!group) return;
      const sel = selectedRef.current;
      if (!document.hidden) {
        if (now - lastSpawn > PULSE_CADENCE) {
          spawnPulse(now);
          lastSpawn = now;
        }
        if (sel && now - lastTetherSpawn > TETHER_CADENCE) {
          tetherPulses.push({ born: now, dur: TETHER_DUR });
          lastTetherSpawn = now;
        }
      }
      pulses = pulses.filter((p) => now - p.born < p.dur);
      tetherPulses = tetherPulses.filter((p) => now - p.born < p.dur && sel);
      const total = pulses.length + tetherPulses.length;
      while (group.childNodes.length < total) group.appendChild(svgEl("circle", "gw-pulse"));
      while (group.childNodes.length > total && group.lastChild) group.removeChild(group.lastChild);

      let i = 0;
      for (const p of pulses) {
        const len = p.path.getTotalLength();
        const t = ease((now - p.born) / p.dur);
        const pt = p.path.getPointAtLength(t * len);
        const c = group.childNodes[i++] as SVGCircleElement;
        c.setAttribute("cx", String(pt.x));
        c.setAttribute("cy", String(pt.y));
        c.setAttribute("r", String(2.6 * (1 - Math.abs(t - 0.5))));
      }
      if (sel && tetherEl && tetherEl.style.display !== "none") {
        const tlen = tetherEl.getTotalLength();
        for (const p of tetherPulses) {
          const t = ease((now - p.born) / p.dur);
          const pt = tetherEl.getPointAtLength(t * tlen);
          const c = group.childNodes[i++] as SVGCircleElement;
          c.setAttribute("cx", String(pt.x));
          c.setAttribute("cy", String(pt.y));
          c.setAttribute("r", String(3 * (1 - Math.abs(t - 0.5))));
        }
      }
    };

    // ── Dust ──
    const sizeCanvas = (cv: HTMLCanvasElement, ctx: CanvasRenderingContext2D) => {
      cv.width = Math.max(1, Math.round(W * dpr));
      cv.height = Math.max(1, Math.round(H * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const seedDust = () => {
      dust = [];
      for (let i = 0; i < DUST_COUNT; i++) {
        dust.push({
          x: Math.random() * W,
          y: Math.random() * H,
          r: Math.random() * 1.7 + 0.3,
          s: Math.random() * 0.18 + 0.03,
          a: Math.random() * Math.PI * 2,
          o: Math.random() * 0.35 + 0.08,
          depth: Math.random(),
        });
      }
    };

    const inBox = (x: number, y: number, r: Box) => x > r.x && x < r.x + r.w && y > r.y && y < r.y + r.h;

    const stepDust = (moving: boolean) => {
      backCtx.clearRect(0, 0, W, H);
      frontCtx.clearRect(0, 0, W, H);
      const px = (mouse.x - 0.5) * 16;
      const py = (mouse.y - 0.5) * 12;
      for (const d of dust) {
        if (moving) {
          let nx = d.x + Math.cos(d.a) * d.s;
          let ny = d.y + Math.sin(d.a) * d.s * 0.6;
          // Motes sharing the copy's plane bounce off the words.
          if (d.depth > 0.38 && d.depth < 0.62) {
            for (const r of collide) {
              if (inBox(nx, ny, r) && !inBox(d.x, d.y, r)) {
                const fromLeft = Math.abs(d.x - r.x);
                const fromRight = Math.abs(r.x + r.w - d.x);
                const fromTop = Math.abs(d.y - r.y);
                const fromBottom = Math.abs(r.y + r.h - d.y);
                const m = Math.min(fromLeft, fromRight, fromTop, fromBottom);
                if (m === fromLeft || m === fromRight) d.a = Math.PI - d.a;
                else d.a = -d.a;
                d.a += (Math.random() - 0.5) * 0.2;
                nx = d.x;
                ny = d.y;
                break;
              }
            }
          }
          d.x = nx;
          d.y = ny;
          if (d.x < -4) d.x = W + 4;
          if (d.x > W + 4) d.x = -4;
          if (d.y < -4) d.y = H + 4;
          if (d.y > H + 4) d.y = -4;
        }
        const ctx = d.depth < 0.5 ? backCtx : frontCtx;
        ctx.globalAlpha = d.o * (d.depth < 0.5 ? 0.75 : 1);
        ctx.fillStyle = dustColor;
        ctx.beginPath();
        ctx.arc(d.x + px * d.depth, d.y + py * d.depth, d.r * (0.7 + d.depth * 0.6), 0, Math.PI * 2);
        ctx.fill();
      }
      backCtx.globalAlpha = 1;
      frontCtx.globalAlpha = 1;
    };

    // ── Frame ──
    const frame = (now: number) => {
      if (entryStart !== null) {
        const t = (now - entryStart) / 1000;
        const hub = nodes.get("hub")!;
        let done = true;
        guilds.forEach((g, i) => {
          const n = nodes.get(g.id);
          if (!n) return;
          const lt = Math.max(0, Math.min(1, (t - i * ENTRY_STAGGER) / ENTRY_DUR));
          if (lt < 1) done = false;
          const e = ease(lt);
          n.x = hub.x + (n.tx - hub.x) * e;
          n.y = hub.y + (n.ty - hub.y) * e;
        });
        if (done) {
          entryStart = null;
          alpha = 0.8;
        }
      } else {
        applyForces(Math.max(alpha, ALPHA_FLOOR));
        if (alpha > 0.02) alpha *= 0.985;
      }
      if (drag) alpha = Math.max(alpha, 0.3);
      draw();
      stepPulses(now);
      stepDust(true);
      // The copy drifts against the dust for depth.
      copy.style.transform = `translate(${(mouse.x - 0.5) * -8}px, ${(mouse.y - 0.5) * -5}px)`;
      raf = requestAnimationFrame(frame);
    };

    // ── Events ──
    const onPointerMove = (e: PointerEvent) => {
      if (!drag) return;
      const n = nodes.get(drag.id);
      if (!n) return;
      const mg = drag.id === "hub" ? HUB_MARGIN : NODE_MARGIN;
      n.x = Math.max(mg, Math.min(W - mg, e.clientX - rootRect.left + drag.dx));
      n.y = Math.max(mg, Math.min(H - mg, e.clientY - rootRect.top + drag.dy));
      // Track pointer velocity so letting go becomes a throw.
      const now = performance.now();
      const dt = Math.max(1, now - drag.lastT);
      drag.tvx = 0.55 * drag.tvx + 0.45 * ((e.clientX - drag.lastX) / dt) * 16.7;
      drag.tvy = 0.55 * drag.tvy + 0.45 * ((e.clientY - drag.lastY) / dt) * 16.7;
      drag.lastX = e.clientX;
      drag.lastY = e.clientY;
      drag.lastT = now;
      alpha = Math.max(alpha, 0.5);
      if (reduce) draw();
    };

    const onPointerUp = () => {
      if (!drag) return;
      const n = nodes.get(drag.id);
      if (n) {
        n.vx = Math.max(-THROW_CAP, Math.min(THROW_CAP, drag.tvx || 0));
        n.vy = Math.max(-THROW_CAP, Math.min(THROW_CAP, drag.tvy || 0));
      }
      alpha = Math.max(alpha, 0.6);
      drag = null;
      if (reduce) {
        settle(0.6);
        draw();
      }
    };

    // Mouse parallax: the dust layers and the copy drift against the pointer.
    const onMouse = (e: PointerEvent) => {
      mouse.x = (e.clientX - rootRect.left) / W;
      mouse.y = (e.clientY - rootRect.top) / H;
    };

    const onSvgClick = (e: MouseEvent) => {
      if (e.target === svg) onSelectRef.current(null);
    };

    const onViewportChange = () => measure();

    svg.addEventListener("pointermove", onPointerMove);
    svg.addEventListener("click", onSvgClick);
    window.addEventListener("pointerup", onPointerUp);
    if (!reduce) window.addEventListener("pointermove", onMouse);
    window.addEventListener("scroll", onViewportChange, true);
    window.addEventListener("resize", onViewportChange);

    const copyRo = new ResizeObserver(() => measure());
    copyRo.observe(copy);

    // ── Boot ──
    sizeCanvas(backCv, backCtx);
    sizeCanvas(frontCv, frontCtx);
    measure();
    seed();
    buildDOM();
    seedDust();

    if (selectedRef.current) {
      if (W <= NARROW) hubTarget.y = H * 0.4;
      else hubTarget.x = W * 0.42;
    }

    if (reduce) {
      for (const n of nodes.values()) {
        if (n.id === "hub") continue;
        n.x = n.tx;
        n.y = n.ty;
      }
      settle(1);
      draw();
      stepDust(false);
    } else {
      entryStart = performance.now();
      raf = requestAnimationFrame(frame);
    }

    simRef.current = {
      settle,
      draw,
      retarget: () => {
        // Make room for the blob: lean left where it floats at the side,
        // lean up where it docks to the bottom (phones).
        const narrow = W <= NARROW;
        hubTarget.x = selectedRef.current && !narrow ? W * 0.42 : W * 0.56;
        hubTarget.y = selectedRef.current && narrow ? H * 0.4 : H * 0.55;
        alpha = Math.max(alpha, 0.35);
      },
      replay: () => {
        if (reduce) return;
        const hub = nodes.get("hub")!;
        for (const n of nodes.values()) {
          if (n.id === "hub") continue;
          n.x = hub.x;
          n.y = hub.y;
          n.vx = 0;
          n.vy = 0;
        }
        pulses = [];
        tetherPulses = [];
        entryStart = performance.now();
        alpha = 0;
      },
    };

    return () => {
      cancelAnimationFrame(raf);
      simRef.current = null;
      svg.removeEventListener("pointermove", onPointerMove);
      svg.removeEventListener("click", onSvgClick);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointermove", onMouse);
      window.removeEventListener("scroll", onViewportChange, true);
      window.removeEventListener("resize", onViewportChange);
      copyRo.disconnect();
      svg.replaceChildren();
      backCtx.clearRect(0, 0, W, H);
      frontCtx.clearRect(0, 0, W, H);
      copy.style.transform = "";
    };
    // `guilds` is covered by dataKey; the mirrors are refs and never stale.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataKey, size.w, size.h, reduce, hubIcon, hubMark]);

  // ── Selection ───────────────────────────────────────────────────────────
  // The web leans left to make room for the panel; under reduced motion it
  // re-settles and repaints at once instead of animating there.
  useEffect(() => {
    const sim = simRef.current;
    if (!sim) return;
    sim.retarget();
    if (reduce) {
      sim.settle(0.6);
    }
    sim.draw();
  }, [selectedId, reduce]);

  return (
    <div className="gw-scene" ref={rootRef}>
      <canvas className="gw-dust gw-dust--back" ref={backRef} aria-hidden="true" />
      <div className="gw-scene-copy" ref={copyRef}>{children}</div>
      <svg className="gw-web" ref={svgRef} role="group" aria-label="Network of your servers" />
      <canvas className="gw-dust gw-dust--front" ref={frontRef} aria-hidden="true" />
    </div>
  );
}
