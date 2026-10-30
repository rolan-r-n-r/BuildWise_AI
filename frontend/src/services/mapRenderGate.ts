/**
 * mapRenderGate.ts — one switch for "the map must not be rendering right now".
 * ===========================================================================
 * Measured problem: while the report sheet covers the map (96 % of the
 * viewport is behind glass), MapLibre keeps rendering. Those frames show up as
 * 24–62 ms entries inside the long animation frames of *unrelated* interactions —
 * every tab switch, floor switch and ghost toggle had the map's render callback
 * interleaved into its task, which is why those surfaces could not reach zero
 * long tasks even after their own React work was cut to three commits.
 *
 * `map.repaint` is a documented public switch ("whether the map will continuously
 * repaint"), so this needs no private API. A ref-counted hold means several
 * owners can ask at once — the open report sheet, a modal on top of it, and a
 * discrete commit in flight — and the map resumes only when the last one lets go.
 *
 * On resume the map is resized (its container may have changed shape while it was
 * covered) and repainted once, so a modal closing shows a current map on the very
 * next frame instead of a stale one.
 */
import type { Map as MlMap, StyleSpecification } from 'maplibre-gl';

let map: MlMap | null = null;
const holders = new Set<string>();
/**
 * Holds that also strip the layer stack, not merely stop repainting.
 *
 * Stripping is for a map nobody can see (a report sheet over 96% of it). A
 * two-frame hold across a visible interaction must NEVER strip: replacing a
 * visible basemap's layers with an empty stack paints the background alone, and
 * a measured style switch showed exactly that — one blank frame at 80 ms
 * (luminance spread 5.9 against 42–60 for the surrounding frames) before the
 * restore landed. The frame budget is kept; the rebuild is not.
 */
const stripHolders = new Set<string>();
let paused = false;
let stripped = false;

/**
 * The style captured at freeze time, restored on thaw.
 *
 * WHY A STYLE SWAP IS NECESSARY — measured, not assumed. `map.repaint = false`
 * (the documented "continuously repaint" switch) stops frames the APP requests;
 * it does not touch frames a SOURCE requests. Instrumenting the covered windows
 * showed 4–5 rendered frames per second inside them against **76 `sourcedata`
 * events**, with zero `move`/`resize` events: the map was not animating, it was
 * reacting to tile traffic — and the app itself causes much of that traffic (the
 * prewarmed raster modes are deliberately kept visible at opacity 0 as a standing
 * tile cache).
 *
 * MapLibre 6.11.1 has no public `Map.pause()`/`resume()` (the `pause()/resume()`
 * in its type surface belong to `SourceCache` and `VideoSource`). What it does
 * have is a public, reversible way to stop a source from being needed at all:
 * `setStyle(style, { diff: true })`. Removing every LAYER while KEEPING every
 * SOURCE means no layer references a source, so MapLibre stops fetching and
 * rendering tiles — while the sources, their workers and their tile caches stay
 * exactly where they are, so thawing re-attaches layers over warm tiles instead
 * of refetching the world.
 */
let frozenStyle: StyleSpecification | null = null;

/**
 * Re-assert hook owned by MapCanvas.
 *
 * A diff style swap does not fire `style.load`, so whatever the app installs on
 * that event has to be re-asserted explicitly after a thaw. Everything the app
 * installs is idempotent (each helper guards on `getSource`/`getLayer`), so this
 * is a repair pass, not a rebuild.
 *
 * It must also run AFTER THE RESTORE HAS LANDED, not in the same tick.
 * `getStyle()` immediately after `setStyle(restore, { diff: true })` still reports
 * the STYLE WE JUST REPLACED — MapLibre applies a diff on its own turn — so an
 * installer called there sees the stripped, layer-less style and rebuilds the
 * app's layers into it. Measured consequence of that window: MapCanvas re-learns
 * every authored paint opacity from a style that is mid-switch (its raster
 * overlays sit at opacity 0 as a standing cache), so the next mode switch faded
 * the imagery to 0 — a blank map over a correct attribution line. One frame is
 * enough for the restore to become visible.
 */
let reassert: (() => void) | null = null;

/** MapCanvas registers its layer installer here. */
export function setMapRenderGateReassert(fn: (() => void) | null): void {
  reassert = fn;
}

/** Run the app's repair pass once the restored style is the one in effect. */
function reassertAfterRestore(): void {
  requestAnimationFrame(() => {
    try {
      reassert?.();
    } catch {
      /* an idempotent repair must never take the app down with it */
    }
  });
}

/** Remove every layer (keeping every source) so no tile work can be requested. */
function freezeTilePipeline(instance: MlMap): void {
  try {
    const full = instance.getStyle() as StyleSpecification | undefined;
    if (!full || !Array.isArray(full.layers) || full.layers.length === 0) return;
    // Never replace a live snapshot. A second freeze can arrive while the first
    // is still stripping (a report sheet opening inside a modal), and by then the
    // live style IS the stripped one — plus whatever a repair pass put back into
    // it — so snapshotting it would make the thaw restore a style with no
    // basemap in it. The first snapshot is the truth.
    if (frozenStyle) return;
    frozenStyle = full;
    instance.setStyle({ ...(full as StyleSpecification), layers: [] }, { diff: true });
  } catch {
    /* a style we cannot read or re-apply is not worth breaking the app over */
  }
}

/** Re-attach the captured layers over the still-warm sources. */
function thawTilePipeline(instance: MlMap): void {
  const restore = frozenStyle;
  frozenStyle = null;
  try {
    if (restore) {
      // Guard: restore only while OUR freeze is still the live style — if the app
      // applied a whole new style meanwhile (theme swap, OSM fallback), that
      // newer style is the truth and the snapshot must not resurrect the old one.
      //
      // The test is the snapshot's TOP layer id, and that detail matters. The app
      // inserts its own layers at the BOTTOM of the stack, so the top layer is
      // always a basemap layer — one only the app's own style swap can remove.
      // Testing the FIRST id (as this did) asked about the app's bottom-most
      // overlay instead, and an app-owned layer says nothing about the basemap:
      // whenever those layers exist, the guard read "a newer style is live" and
      // silently DROPPED the restore. Measured on the dev build: one basemap
      // switch and the whole vector style was gone for good — 122 layers down to
      // the app's own 12, buildings on a blank canvas with no streets, labels or
      // water, and no way back through further switching.
      const topId = restore.layers?.[restore.layers.length - 1]?.id;
      const styleIsStillStripped = !topId || !instance.getLayer(topId);
      if (styleIsStillStripped) {
        instance.setStyle(restore, { diff: true });
        // The diff is applied on the style's own turn and can take longer than a
        // frame on a full basemap. Verify rather than trust: if the basemap is
        // still missing a frame later, apply the snapshot outright (no diff,
        // which re-creates the sources and is why it is not the first choice).
        requestAnimationFrame(() => {
          try {
            if (topId && !instance.getLayer(topId)) instance.setStyle(restore);
          } catch {
            /* the app's current style stays in place */
          }
        });
      }
    }
    // Whatever happened, the app's own layers must exist afterwards: overlay
    // layers installed while frozen are dropped by a diff restore, and a full
    // app style swap re-installs them through `style.load` anyway. Deferred a
    // frame so the repair pass sees the restored style (see reassertAfterRestore).
    reassertAfterRestore();
  } catch {
    /* leave the app's current style in place */
    reassertAfterRestore();
  }
}

/**
 * True while the live style is the gate's stripped one.
 *
 * MapCanvas needs this because the strip fires `style.load`, and the app must not
 * treat that as a style change: rebuilding its layers here puts back exactly the
 * layers the gate removed — the covered map would keep fetching and painting,
 * which is the traffic the freeze exists to stop.
 */
export function mapRenderGateFrozen(): boolean {
  return frozenStyle !== null;
}

/**
 * The app applied a whole new style of its own (theme swap, OSM fallback).
 *
 * Two things become stale at once, and this drops both: the frozen snapshot
 * (restoring it would resurrect the style the app just replaced) and the paint
 * opacities the app learned from the previous style (MapCanvas re-reads those on
 * the `style.load` that follows — see `appStyleIntentRef`).
 */
export function markStyleReplaced(): void {
  frozenStyle = null;
}

function apply(): void {
  if (!map) return;
  const shouldPause = holders.size > 0;
  const shouldStrip = stripHolders.size > 0;
  if (shouldPause === paused && shouldStrip === stripped) return;
  paused = shouldPause;
  try {
    if (shouldPause) {
      // Cancel any camera ease or rotation in flight: a paused map must not
      // resume by jumping to where an animation would have finished.
      map.stop();
      map.repaint = false;
      if (shouldStrip && !stripped) {
        freezeTilePipeline(map);
        stripped = frozenStyle !== null;
      } else if (!shouldStrip && stripped) {
        // A stripped hold ended while another frame hold remains: put the
        // basemap back now rather than leaving a blank map under a pause.
        thawTilePipeline(map);
        stripped = false;
      }
    } else {
      const wasStripped = stripped;
      if (stripped) {
        thawTilePipeline(map);
        stripped = false;
      }
      map.repaint = true;
      // Only a long, layer-stripping hold can have left the container a
      // different shape. A two-frame hold around a visible style switch does
      // not need a framebuffer reallocation — and that resize is itself a
      // blank frame on some drivers, which is exactly what the hold exists to
      // avoid.
      if (wasStripped) map.resize();
      map.triggerRepaint();
    }
  } catch {
    /* the map was torn down mid-hold — nothing to gate */
  }
}

/** MapCanvas registers its instance here (and passes null on unmount). */
export function attachMapRenderGate(instance: MlMap | null): void {
  map = instance;
  paused = false;
  stripped = false;
  frozenStyle = null;
  if (instance) apply();
}

/**
 * Ask the map to stop rendering. Hold until the matching `releaseMapRender`.
 * Idempotent per reason, so a double-invoked effect cannot leak a hold.
 */
export function holdMapRender(reason: string): void {
  holders.add(reason);
  stripHolders.add(reason);
  apply();
}

/** Let go of a hold. Rendering resumes when no reason is left. */
export function releaseMapRender(reason: string): void {
  holders.delete(reason);
  stripHolders.delete(reason);
  apply();
}

let unitSeq = 0;

/**
 * Ceiling on a cross-commit hold, in ms.
 *
 * The rAF pair below is the intended release (two frames); this is the floor
 * under it, not a second policy. Timers keep running where animation callbacks
 * do not — a hidden tab, an occluded window, a renderer Chromium has parked —
 * and it is far longer than the commit-and-paint window the hold exists for.
 */
const HOLD_FAILSAFE_MS = 1000;

/**
 * Hold the gate across the NEXT COMMIT AND PAINT, then let go.
 *
 * For discrete interactions (a tab switch, a floor switch) the map's render loop
 * must not fire inside the click task — its frame lands in the same long task as
 * the commit, which is exactly what turned a 3-commit switch into a 100 ms LoAF.
 * Each call takes its own hold key, so two overlapping interactions cannot
 * release each other's.
 */
export function holdMapRenderAcrossCommit(reason: string): void {
  const key = `${reason}#${++unitSeq}`;
  // Frame hold only: stop repainting for the commit, but never strip a visible
  // basemap (see stripHolders).
  holders.add(key);
  apply();
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    holders.delete(key);
    stripHolders.delete(key); // harmless; frame holds never add one
    apply();
  };
  // Two frames: the first lands in the same frame as the commit, the second
  // after the browser has painted it. Releasing on the first would let a map
  // frame slip into the very frame we are protecting.
  requestAnimationFrame(() => {
    requestAnimationFrame(release);
  });
  // If those callbacks never run, the hold must still end. Measured: in a page
  // whose rendering is parked, `requestAnimationFrame` fires NOTHING at all —
  // and a leaked hold means the map's layers stay stripped, so the basemap is a
  // blank canvas until something else releases it. A timer still runs there.
  setTimeout(release, HOLD_FAILSAFE_MS);
}

