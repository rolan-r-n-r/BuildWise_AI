/**
 * tokens.ts — BuildWise AI Design System: single source of truth.
 * ================================================================
 * Every new/changed UI must consume these tokens (or the primitives in
 * primitives.tsx). Ad-hoc hex colors, radii, shadows and transition timings
 * in component code are flagged by `npm run lint:tokens`.
 *
 * Layering:
 *   tokens.ts (this file)  → index.css :root variables (live values)
 *   primitives.tsx         → components (the ONLY sanctioned building blocks)
 *
 * New primitive or token ⇒ document the justification in the PR and update
 * docs/upgrades/ux-qa-checklist.md.
 */

/** App theme mode (`data-theme` on <html>). Sheet themes are separate (THEMES). */
export type ThemeMode = 'light' | 'dark';

/** Drawing sheet theme (CAD = dark blueprint, Paper = light print). */
export type SheetTheme = 'cad' | 'paper';

/* ------------------------------------------------------------------ */
/* MOTION — macOS-grade: 150–200 ms ease-out. `prefers-reduced-motion` */
/* is honored globally in index.css; `ui()` classes remain safe there. */
/* ------------------------------------------------------------------ */
export const MOTION = {
  duration: {
    /** Micro feedback (press, chip toggle) */
    fast: 100,
    /** Standard control transitions (default) */
    base: 150,
    /** Larger surfaces (popovers, panels) */
    slow: 200,
    /** Map camera / drawer sheet (drag-adjacent, outside the 150-200 band by design) */
    sheet: 250,
    /** Popovers and inline menus — one step above a control, below a panel. */
    popover: 180,
    /** Drawers and modals: long enough to read as a surface, not a flash. */
    panel: 280,
    /** Spatial camera moves (gated by usePresence / readSpatialDuration). */
    spatial: 720,
  },
  ease: {
    /** Standard deceleration — iOS ease-out */
    out: 'cubic-bezier(0.25, 0.1, 0.25, 1)',
    /** Emphasis entrances (popovers) */
    outBack: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
    /** Symmetric (theme cross-fades) */
    inOut: 'cubic-bezier(0.65, 0, 0.35, 1)',
    /**
     * Spatial ease — starts decisively, lands softly. Used for map camera
     * flights and drawers: a long distance should not share the 150 ms control
     * curve, or the last third of the movement is a crawl.
     */
    spatial: 'cubic-bezier(0.22, 0.61, 0.36, 1)',
  },
} as const;

/**
 * Transition class composer. Usage: `ui('base')`, `ui('fast')`, `ui('slow')`,
 * `ui('none')` (returns '' for hover-free decorative layers).
 * Properties are constrained to paint-safe ones (color/opacity/transform/
 * shadow) so transitions never trigger layout.
 */
export type MotionToken = keyof typeof MOTION.duration | 'none';
export function ui(token: MotionToken): string {
  switch (token) {
    case 'none':
      return '';
    case 'fast':
      return 'transition-[color,background-color,border-color,opacity,box-shadow,transform] duration-100 ease-apple';
    case 'slow':
      return 'transition-[color,background-color,border-color,opacity,box-shadow,transform] duration-200 ease-apple';
    case 'sheet':
      return 'transition-[color,background-color,border-color,opacity,box-shadow,transform] duration-250 ease-apple';
    case 'popover':
      return 'transition-[color,background-color,border-color,opacity,box-shadow,transform] duration-[180ms] ease-apple';
    case 'panel':
      return 'transition-[color,background-color,border-color,opacity,box-shadow,transform] duration-[280ms] ease-spatial';
    case 'base':
    default:
      return 'transition-[color,background-color,border-color,opacity,box-shadow,transform] duration-150 ease-apple';
  }
}

/* ------------------------------------------------------------------ */
/* RADII — 6/8/10/12/16 + full. Rounded-2xl (16) is the outermost      */
/* surface radius; nothing nests a larger radius inside a smaller one. */
/* ------------------------------------------------------------------ */
export const RADII = { xs: 6, sm: 8, md: 10, lg: 12, xl: 16, full: 9999 } as const;

/* ------------------------------------------------------------------ */
/* TYPOGRAPHY — SF-adjacent stack; tabular figures for every number    */
/* that changes or compares (apply class `ui-font-tabular`).           */
/* ------------------------------------------------------------------ */
export const TYPOGRAPHY = {
  fontStack:
    "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  monoStack: "'JetBrains Mono', 'Fira Code', monospace",
  sizes: { caption2: 10, caption: 11, footnote: 12, body: 13, headline: 15, title: 17 },
} as const;

/** Class applying tabular (fixed-width) numerals — use on ALL measurements. */
export const TABULAR_NUMS_CLASS = 'ui-font-tabular';

/* ------------------------------------------------------------------ */
/* Z-INDEX — app chrome stacking, single source                        */
/* ------------------------------------------------------------------ */
export const Z_INDEX = {
  mapChrome: 900,
  header: 1001,
  popover: 1050,
  sheet: 1100,
  toast: 1200,
} as const;

/* ------------------------------------------------------------------ */
/* HIT TARGETS — 32 px chrome buttons with >=44 px effective           */
/* target via ::before hit-slop (see IconButton primitive).            */
/* ------------------------------------------------------------------ */
export const HIT_TARGETS = { iconButton: 32, minTarget: 44 } as const;

/* ------------------------------------------------------------------ */
/* SHORTCUTS — single source of truth for the ? shortcuts help sheet   */
/* and the keyboard-shortcuts section of the methodology reference.    */
/* ------------------------------------------------------------------ */
export interface ShortcutHintDef {
  /** Primary key, matched case-insensitively against KeyboardEvent.key */
  key: string;
  /** Human-readable action shown in the help sheet + methodology reference */
  label: string;
  /** Which surface the key belongs to (app chrome or the map view) */
  scope: 'App' | 'Map';
}

export const SHORTCUTS: readonly ShortcutHintDef[] = [
  { key: 't', label: 'Toggle Light / Dark', scope: 'App' },
  { key: 'm', label: 'Map Details (Standard / Satellite / Terrain)', scope: 'Map' },
  { key: 'r', label: 'Reset Site Analysis', scope: 'App' },
  { key: '?', label: 'Show Keyboard Shortcuts', scope: 'App' },
] as const;

/* ------------------------------------------------------------------ */
/* AA INK PAIRS — audited by scripts/check_contrast.cjs. Values mirror */
/* index.css (app themes) and drawing_ir.py sheet palettes (CAD/Paper) */
/* exactly; the checker fails the build if they drift below 4.5:1.     */
/* ------------------------------------------------------------------ */
export interface InkPair {
  /** Display name for reports */
  name: string;
  /** Surface color the ink renders on */
  bg: string;
  /** Primary text color */
  ink: string;
  /** Secondary text color (must also clear AA for body copy) */
  inkSecondary: string;
}

export const APP_INK: Record<ThemeMode, InkPair> = {
  light: { name: 'App Light', bg: '#F5F5F7', ink: '#1D1D1F', inkSecondary: '#6A6A6F' },
  dark: { name: 'App Dark', bg: '#000000', ink: '#F5F5F7', inkSecondary: '#A1A1A6' },
};

/** Mirrors backend/app/services/floorplan/drawing_ir.py:2359–2370. */
export const SHEET_INK: Record<SheetTheme, InkPair> = {
  cad: { name: 'Sheet CAD', bg: '#0B132B', ink: '#F8FAFC', inkSecondary: '#94A3B8' },
  paper: { name: 'Sheet Paper', bg: '#F8FAFC', ink: '#0F172A', inkSecondary: '#64748B' },
};

/* ------------------------------------------------------------------ */
/* MAP CAPTURE — drawing-annotation colors                            */
/* Justification: MapLibre layer `paint` props need concrete strings,  */
/* not CSS vars; values defined ONCE here and re-exported for the map  */
/* adapter, keeping the token single-source intact.                    */
/* ------------------------------------------------------------------ */
export const MAP_CAPTURE = {
  /** Boundary fill + live edge: accent blue (matches --accent dark value) */
  accent: '#0A84FF',
  /** Magnetic guide lines: amber (matches --semantic-amber) */
  guide: '#FF9F0A',
  /** Vertex marker core / halo */
  vertexStroke: '#FFFFFF',
} as const;

/* ------------------------------------------------------------------ */
/* MAP CARTOGRAPHY — mode-specific raster treatment                   */
/* Justification: MapLibre paint properties need concrete numbers, not */
/* CSS variables. Keeping them here means the satellites/terrain look  */
/* is tuned in one place and reviewed like every other visual token.   */
/* ------------------------------------------------------------------ */
export const MAP_CARTOGRAPHY = {
  /** Satellite: street lines are context, not the subject. */
  satellite: {
    roadOpacity: 0.34,
    saturation: -0.05,
    contrast: 0.04,
  },
  /** Terrain: keep relief legible without the topo sheet shouting. */
  terrain: {
    saturation: -0.18,
    contrast: 0,
    brightnessMax: 1,
    brightnessMaxDark: 0.66,
    hillshadeExaggeration: 0.32,
    pitch: 48,
  },
  /** Standard-mode massing. One step lighter on dark so roofs read as volume. */
  buildingLight: '#E8E6E1',
  buildingDark: '#344054',
  /**
   * Dark-mode map ground. The provider's near-black ground swallowed the
   * building massing and left the roads as the only legible thing on screen;
   * one step of navy restores ground-to-roof separation without turning the
   * dark theme into a light map.
   */
  backgroundDark: '#141A24',
} as const;

/* ------------------------------------------------------------------ */
/* CAMERA — spatial transition timing                                 */
/* `readSpatialDuration` is the JS-side honour of the same reduced-    */
/* motion contract the stylesheet applies to CSS transitions.          */
/* ------------------------------------------------------------------ */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Camera duration in ms, collapsed to 0 when the reader asks for less motion. */
export function spatialDuration(ms: number = MOTION.duration.spatial): number {
  return prefersReducedMotion() ? 0 : ms;
}

/* ------------------------------------------------------------------ */
/* MAP OVERLAY — site preview rendering                               */
/* Justification: MapLibre layer `paint` props need concrete strings,  */
/* not CSS vars; defined ONCE here and consumed by the preview overlay */
/* adapter so the token single-source rule holds for map layers too.   */
/* Semantics: amber = non-buildable (setback band), green = buildable, */
/* accent = footprint, purple = wedge zones, cyan = frontage.          */
/* ------------------------------------------------------------------ */
export const MAP_OVERLAY = {
  /** Setback band (plot ring + hatch tint): amber (matches --semantic-amber) */
  setback: '#FF9F0A',
  /** Buildable polygon: green, tuned for satellite basemaps (map-only value) */
  buildable: '#30D158',
  /** Building footprint: accent blue (matches MAP_CAPTURE.accent) */
  footprint: '#0A84FF',
  /** Wedge zones: purple (map-only value; no app-surface equivalent needed) */
  wedge: '#BF5AF2',
  /** Frontage highlight + arrow: cyan, distinct from accent and buildable */
  frontage: '#64D2FF',
  /** Arrow/marker halo */
  markerStroke: '#FFFFFF',
  /** Dimming veil outside the selected plot (never above the overlays). */
  spotlight: '#000000',
  spotlightOpacity: 0.1,
} as const;
