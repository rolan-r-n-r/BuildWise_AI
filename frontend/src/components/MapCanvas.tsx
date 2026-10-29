import React, { useCallback, useEffect, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { FeatureCollection, Polygon, LineString } from 'geojson';
import { Icon } from './Icon';
import { MapStyleSelector, type MapStyleMode } from './MapStyleSelector';
import {
  attachMapRenderGate,
  holdMapRenderAcrossCommit,
  mapRenderGateFrozen,
  markStyleReplaced,
  setMapRenderGateReassert,
} from '../services/mapRenderGate';
import type { GeoJsonFeatureCollection } from '../services/types';
import { DEFAULT_SITE_ZOOM } from '../services/sessionReset';

interface MapCanvasProps {
  latitude: number | null;
  longitude: number | null;
  orientationDegrees?: number;
  plinthAreaSqFt?: number;
  onLocationSelect: (lat: number, lon: number) => void;
  invalidateTrigger?: any;
  className?: string;
  entranceDirection?: string;
  treeClusters?: GeoJsonFeatureCollection | null;
  waterBodies?: GeoJsonFeatureCollection | null;
  theme?: 'light' | 'dark';
  /**
   * Site focus: while the capture wizard is open or a boundary is committed the
   * basemap's 3D building massing is suppressed. Extruded city blocks over the
   * plot read as a dark square sitting on the pin and hide the very geometry
   * (boundary, setback band, footprint) the user is working on.
   */
  hideMassing?: boolean;
  /**
   * Zoom ceiling. Browsing stays at 18 (beyond that the pitched camera dips
   * below extruded rooftops); an active site session raises it so small urban
   * plots are large enough on screen for precise edge picking.
   */
  maxZoom?: number;
  /**
   * Suppress the analysis-derived site estimate (footprint rectangle + entrance
   * arrow) once a real plot has been captured. That estimate is anchored on the
   * pin and ignores the plot, so left on it reads as a second boundary riding
   * along with the marker while the authoritative preview footprint sits
   * somewhere else. One building outline at a time.
   */
  hideSiteEstimate?: boolean;
  /** Invoked once the MapLibre instance is created (and with null on teardown). */
  onMapReady?: (map: maplibregl.Map | null) => void;
  /**
   * Reset-contract token: every new value returns the camera to its first-run
   * view (the current site, zoom 16, flat). The first token is the mount state
   * and is skipped — the map was created at that view.
   */
  viewResetToken?: number;
}

const CUSTOM_LAYER_IDS = new Set([
  'satellite-layer',
  'terrain-layer',
  'hillshade-layer',
  '3d-buildings',
  'footprint-fill',
  'footprint-line',
  'entrance-shaft',
  'entrance-head',
  'tree-clusters-fill',
  'tree-clusters-line',
  'water-bodies-fill',
  'water-bodies-line',
  'osm-fallback-layer',
]);

const isCustomOverlayLayer = (layerId: string): boolean =>
  CUSTOM_LAYER_IDS.has(layerId) ||
  layerId.startsWith('bw-capture-') ||
  layerId.startsWith('bw-preview-');

// Animated map-mode switching (Apple Maps feel): a quick base cross-fade with labels
// staggered on top — outgoing labels duck out first, incoming ones arrive last.
const STYLE_FADE_MS = 420; // base layers (fills, lines, rasters, extrusions)
const LABEL_FADE_IN_DELAY_MS = 140; // labels wait for the base to settle
const LABEL_FADE_MS = 280; // incoming labels fade in quickly
const LABEL_FADE_OUT_MS = 200; // outgoing labels leave early
const RASTER_TILE_HEAD_START_MS = 80; // let fresh raster tiles decode before revealing
const TILE_READY_TIMEOUT_MS = 1200; // max wait for incoming raster tiles before fading anyway
const TILE_CHECK_INTERVAL_MS = 60; // poll frequency for tile-readiness checks
// Zoom-pulse "dive": the camera pushes in ~1/3 zoom level as the new layer fades in,
// then settles back — one synchronized beat instead of a flat opacity swap.
const PULSE_ZOOM_DELTA = 0.32; // zoom levels pushed in at the pulse apex
const PULSE_IN_MS = 280; // standalone dive-in duration (no pitch change)
const PULSE_OUT_MS = 420; // settle-back duration

/** Camera ease issued by syncCameraForMode — folded into the zoom pulse when present. */
interface CameraEaseTarget {
  pitch: number;
  bearing?: number;
  duration: number;
}

// Paint property that controls opacity for each MapLibre layer type. Animating these
// (instead of flipping `visibility`) is what makes mode switches cross-fade smoothly.
const PAINT_OPACITY_PROPS: Record<string, string[]> = {
  background: ['background-opacity'],
  circle: ['circle-opacity'],
  fill: ['fill-opacity'],
  'fill-extrusion': ['fill-extrusion-opacity'],
  heatmap: ['heatmap-opacity'],
  line: ['line-opacity'],
  raster: ['raster-opacity'],
  symbol: ['icon-opacity', 'text-opacity'],
  hillshade: ['hillshade-exaggeration'],
};

/**
 * The app's own raster mode overlays.
 *
 * They are authored fully visible — added with no `raster-opacity` at all — so
 * every other value they can hold is transient STATE: 0 while prewarmed as a
 * standing tile cache, 0 (or mid-fade) while another mode is showing. Learning
 * one of those as the "authored" opacity is how a mode switch faded the imagery
 * to nothing while leaving the correct attribution line on screen.
 */
const RASTER_OVERLAY_MODE_LAYERS = new Set(['satellite-layer', 'terrain-layer']);

const isStreetLineLayer = (layer: { type: string; id: string }) =>
  layer.type === 'line' &&
  (layer.id.startsWith('road_') ||
    layer.id.startsWith('bridge_') ||
    layer.id.startsWith('highway_'));

const EMPTY_GEOJSON_COLLECTION: FeatureCollection = {
  type: 'FeatureCollection',
  features: [],
};

export const MapCanvas: React.FC<MapCanvasProps> = ({
  latitude,
  longitude,
  orientationDegrees,
  plinthAreaSqFt,
  onLocationSelect,
  invalidateTrigger,
  className = 'h-full w-full',
  entranceDirection,
  treeClusters,
  waterBodies,
  theme = 'light',
  hideMassing = false,
  maxZoom = 18,
  hideSiteEstimate = false,
  onMapReady,
  viewResetToken = 0,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);

  const [showTreeLayer, setShowTreeLayer] = useState<boolean>(true);
  const [showWaterLayer, setShowWaterLayer] = useState<boolean>(true);
  const [mapStyle, setMapStyle] = useState<MapStyleMode>('standard');
  const [isFallbackActive, setIsFallbackActive] = useState<boolean>(false);
  const fallbackAppliedRef = useRef<boolean>(false);
  const prevCoordsRef = useRef<{ lat: number; lng: number } | null>(null);
  const prevThemeRef = useRef<'light' | 'dark' | null>(null);

  const onMapReadyRef = useRef(onMapReady);
  onMapReadyRef.current = onMapReady;
  const onLocationSelectRef = useRef(onLocationSelect);
  useEffect(() => {
    onLocationSelectRef.current = onLocationSelect;
  }, [onLocationSelect]);

  const mapStyleRef = useRef<MapStyleMode>(mapStyle);
  useEffect(() => {
    mapStyleRef.current = mapStyle;
  }, [mapStyle]);

  const themeRef = useRef<'light' | 'dark'>(theme);
  useEffect(() => {
    themeRef.current = theme;
  }, [theme]);
  /**
   * Set by the two places the app applies a WHOLE new style of its own (the theme
   * swap and the OSM raster fallback), consumed by the `style.load` handler.
   *
   * Only then are the learned authored paint opacities stale and worth re-reading.
   * Every other `style.load` is a repair — the render gate's own strip and restore
   * fire one too (measured), and re-learning there samples the style mid-switch:
   * the raster overlays sit at opacity 0 as a standing tile cache, so the next
   * mode switch faded the imagery to nothing over a correct attribution line.
   */
  const appStyleIntentRef = useRef(false);

  const showTreeLayerRef = useRef(showTreeLayer);
  useEffect(() => {
    showTreeLayerRef.current = showTreeLayer;
  }, [showTreeLayer]);

  const showWaterLayerRef = useRef(showWaterLayer);
  useEffect(() => {
    showWaterLayerRef.current = showWaterLayer;
  }, [showWaterLayer]);

  const hideMassingRef = useRef(hideMassing);
  hideMassingRef.current = hideMassing;
  const maxZoomRef = useRef(maxZoom);
  maxZoomRef.current = maxZoom;

  const treeClustersRef = useRef(treeClusters);
  useEffect(() => {
    treeClustersRef.current = treeClusters;
  }, [treeClusters]);

  const waterBodiesRef = useRef(waterBodies);
  useEffect(() => {
    waterBodiesRef.current = waterBodies;
  }, [waterBodies]);

  const footprintGeoJsonRef = useRef<FeatureCollection>(EMPTY_GEOJSON_COLLECTION);
  // Tracks whether the current camera pitch was applied automatically by us (Standard-mode
  // building tilt) so we only auto-flatten pitches we own — never user-set ones.
  const autoTiltedRef = useRef<boolean>(false);
  const entranceShaftGeoJsonRef = useRef<FeatureCollection>(EMPTY_GEOJSON_COLLECTION);
  const entranceHeadGeoJsonRef = useRef<FeatureCollection>(EMPTY_GEOJSON_COLLECTION);
  const footprintCornersLatLngRef = useRef<{ lat: number; lng: number }[]>([]);
  // Animated mode switching: per-style-load cache of each base layer's authored paint
  // opacity so fades restore the exact original value (some are expressions), plus a
  // deferred pass that flips visibility off only after a fade-out completes.
  const originalPaintOpacitiesRef = useRef<Map<string, any>>(new Map());
  const styleFadeCleanupRef = useRef<{
    timer: ReturnType<typeof setTimeout>;
    mode: MapStyleMode;
  } | null>(null);
  // setTimeout handle for the zoom-pulse settle phase (mode-switch "dive" beat).
  const zoomPulseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // The zoom the camera must settle back to. Captured only when no pulse is already
  // active, so rapid re-switches mid-dive keep returning to the ORIGINAL zoom instead
  // of compounding upward (re-basing on mid-flight zoom would drift +Δ per volley).
  const pulseBaseZoomRef = useRef<number | null>(null);
  // Previous mode seen by the style effect — distinguishes real mode switches from
  // initial mount / StrictMode remount so the pulse never fires on page load.
  const prevMapStyleRef = useRef<MapStyleMode | null>(null);
  // Increments per applyMapStyleVisibility run so awaited tile-readiness gates can
  // detect when a newer switch superseded them mid-await.
  const styleFadeRunIdRef = useRef<number>(0);
  // Raster layers deliberately kept visible at opacity 0 as a standing tile cache.
  // The deferred hide pass must never hide these — their residency is what makes
  // subsequent mode switches instant.
  const prewarmedRasterLayersRef = useRef<Set<string>>(new Set());

  // Default coordinate: Center of India (Nagpur / Central Plateau)
  const defaultLat = 20.5937;
  const defaultLon = 78.9629;
  const defaultZoom = 5;

  const getVectorStyleUrl = (t: 'light' | 'dark') =>
    t === 'dark'
      ? 'https://tiles.openfreemap.org/styles/dark'
      : 'https://tiles.openfreemap.org/styles/liberty';

  const getOsmRasterFallbackStyle = (t: 'light' | 'dark'): maplibregl.StyleSpecification => ({
    version: 8,
    name: 'OSM Raster Fallback',
    sources: {
      'osm-fallback-source': {
        type: 'raster',
        tiles:
          t === 'dark'
            ? [
                'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
                'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
                'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
              ]
            : [
                'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
                'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
              ],
        tileSize: 256,
        maxzoom: 19,
        attribution: t === 'dark' ? '© CARTO © OpenStreetMap' : '© OpenStreetMap contributors',
      },
    },
    layers: [
      {
        id: 'osm-fallback-layer',
        type: 'raster',
        source: 'osm-fallback-source',
        minzoom: 0,
        maxzoom: 19,
      },
    ],
  });

  const createPinElement = (t: 'light' | 'dark') => {
    const accentColor = t === 'dark' ? '#0A84FF' : '#0071E3';
    const el = document.createElement('div');
    el.className = 'apple-map-pin-root';
    el.innerHTML = `
      <div class="apple-pin-container">
        <div class="apple-pin-ring" style="border-color: ${accentColor};"></div>
        <svg class="apple-pin-svg" width="34" height="42" viewBox="0 0 34 42" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M17 0C7.61 0 0 7.61 0 17C0 28.5 15.3 40.8 16.2 41.5C16.7 41.9 17.3 41.9 17.8 41.5C18.7 40.8 34 28.5 34 17C34 7.61 26.39 0 17 0Z" fill="${accentColor}"/>
          <circle cx="17" cy="16" r="4.5" fill="#FFFFFF"/>
        </svg>
      </div>
    `;
    return el;
  };

  // ---------- Raster tile readiness (polished mode switching) ----------

  /**
   * True when the layer's source has finished loading everything it needs for the
   * current viewport (map.isSourceLoaded). A hidden layer is never "ready" — the
   * caller must reveal it first so MapLibre actually starts fetching tiles.
   */
  const isLayerReady = (map: maplibregl.Map, layerId: string) => {
    try {
      const layer = (map as any).getLayer(layerId);
      if (!layer) return true;
      if ((map as any).getLayoutProperty(layerId, 'visibility') === 'none') return false;
      return map.isSourceLoaded(layer.source);
    } catch {
      return true;
    }
  };

  /**
   * Resolves once the given raster layer has all of its viewport tiles loaded — or
   * after TILE_READY_TIMEOUT_MS, so a slow tile server can never stall the UI.
   */
  const waitForRasterTiles = (map: maplibregl.Map, layerId: string) =>
    new Promise<boolean>((resolve) => {
      if (isLayerReady(map, layerId)) {
        resolve(true);
        return;
      }
      let settled = false;
      const done = (ready: boolean) => {
        if (settled) return;
        settled = true;
        clearInterval(poll);
        clearTimeout(timeout);
        resolve(ready);
      };
      const poll = setInterval(() => {
        if (isLayerReady(map, layerId)) done(true);
      }, TILE_CHECK_INTERVAL_MS);
      const timeout = setTimeout(() => done(false), TILE_READY_TIMEOUT_MS);
    });

  /**
   * Kick off tile downloads for a raster mode without showing it: the layer is made
   * visible at opacity 0 (MapLibre only fetches tiles for visible layers), rendered
   * once, and left resident in the source cache. Runs when the camera is idle so it
   * never races user interaction — a later switch then fades in pre-loaded imagery.
   */
  const prewarmRasterTiles = (map: maplibregl.Map, mode: MapStyleMode) => {
    if (mode !== 'satellite' && mode !== 'terrain') return;
    const layerId = mode === 'satellite' ? 'satellite-layer' : 'terrain-layer';
    if (!map.getLayer(layerId)) return;
    if (
      isLayerReady(map, layerId) &&
      prewarmedRasterLayersRef.current.has(layerId)
    ) {
      return; // already resident and cached
    }

    const start = () => {
      /**
       * Remember what "shown" means for this layer BEFORE hiding it.
       *
       * A mode switch fades a raster layer back to the authored opacity captured
       * in `originalPaintOpacitiesRef`, and the picker prewarms both raster layers
       * the moment it opens — so if that capture happens after this call, it
       * captures the 0 written below and the reveal fades the imagery to nothing:
       * a blank map under the CORRECT attribution line ("Imagery: Esri, Maxar…"),
       * which is exactly how this bug reached a user. Seeding the map here keeps
       * the capture order-independent. The layers are authored visible (implicit
       * opacity 1), so a 0/undefined read means another prewarm, not a value.
       */
      if (!originalPaintOpacitiesRef.current.has(layerId)) {
        let authored = 1;
        try {
          const current = (map as any).getPaintProperty(layerId, 'raster-opacity');
          if (typeof current === 'number' && current > 0) authored = current;
        } catch {
          authored = 1;
        }
        originalPaintOpacitiesRef.current.set(layerId, authored);
      }
      try {
        (map as any).setPaintProperty(layerId, 'raster-opacity-transition', {
          duration: 0,
          delay: 0,
        });
        (map as any).setPaintProperty(layerId, 'raster-opacity', 0);
      } catch {
        // ignore
      }
      try {
        if ((map as any).getLayoutProperty(layerId, 'visibility') === 'none') {
          map.setLayoutProperty(layerId, 'visibility', 'visible');
        }
      } catch {
        // ignore
      }
      // Standing cache: stays visible at opacity 0 so MapLibre keeps its tiles
      // loaded and up to date as the user pans/zooms.
      prewarmedRasterLayersRef.current.add(layerId);
    };

    if (map.isMoving() || zoomPulseTimerRef.current !== null) {
      // Retry once the camera rests — tiles for a moving viewport are wasted work.
      map.once('idle', () => prewarmRasterTiles(map, mode));
      return;
    }
    start();
  };

  /**
   * Animated mode switching (Apple Maps behaviour): base layers cross-fade over
   * STYLE_FADE_MS while the camera pitches/levels, instead of snapping.
   *
   * How it works:
   * 1. Compute the target opacity (0 or authored) for every base layer in the new mode.
   * 2. Layers keep `visibility: 'visible'` for the whole animation so MapLibre
   *    interpolates paint values on-GPU with zero flicker; a deferred pass flips
   *    visibility off only once a fade-out has completed.
   * 3. Custom overlays (footprint, entrance, canopy, water) are never touched.
   * 4. When switching INTO a raster mode (waitForTiles), the fade is gated on the
   *    incoming tiles being loaded — reveals imagery, never grey blanks — with a
   *    timeout fallback and staleness detection for rapid re-switches.
   */
  const applyMapStyleVisibility = async (
    map: maplibregl.Map,
    mode: MapStyleMode,
    waitForTiles = false
  ) => {
    const style = map.getStyle();
    if (!style || !style.layers) return;

    // Bump on EVERY invocation (not only gated ones) so a Standard switch also
    // invalidates a stale raster-mode gate that is still awaiting tiles.
    const runId = ++styleFadeRunIdRef.current;

    const orig = originalPaintOpacitiesRef.current;
    const fadeTargets: { layerId: string; type: string; target: number }[] = [];
    const hasVectorStreets = Boolean(map.getLayer('vector-street-lines'));

    for (const layer of style.layers) {
      // Liberty ships its own building-3d extrusion that would ghost over imagery — kill it.
      if (layer.id === 'building-3d') {
        try {
          map.setLayoutProperty('building-3d', 'visibility', 'none');
        } catch {
          // ignore
        }
        continue;
      }

      // Dedicated raster/3D layers we injected: fade by mode. (Must be handled BEFORE
      // the CUSTOM_LAYER_IDS guard below, which only exists to protect user overlays.)
      if (layer.id === 'satellite-layer') {
        fadeTargets.push({ layerId: layer.id, type: layer.type, target: mode === 'satellite' ? 1 : 0 });
        continue;
      }
      if (layer.id === 'terrain-layer' || layer.id === 'hillshade-layer') {
        fadeTargets.push({ layerId: layer.id, type: layer.type, target: mode === 'terrain' ? 1 : 0 });
        continue;
      }
      if (layer.id === 'osm-fallback-layer') {
        fadeTargets.push({ layerId: layer.id, type: layer.type, target: mode === 'standard' ? 1 : 0 });
        continue;
      }
      if (layer.id === '3d-buildings') {
        // Extrusions live in Standard (vector) and Terrain (relief) views — never over
        // imagery, and never while the site is the subject (see hideMassing).
        const massingOff = mode === 'satellite' || hideMassingRef.current;
        fadeTargets.push({ layerId: layer.id, type: layer.type, target: massingOff ? 0 : 1 });
        continue;
      }

      // Custom overlay layers (footprint, entrance, canopy, water, capture tracing, site preview) are never touched.
      if (isCustomOverlayLayer(layer.id)) continue;

      let target: number;
      if (mode === 'standard') {
        target = 1;
      } else if (mode === 'satellite') {
        // Keep only street/road lines above imagery for Apple-style dark cartography
        // (suppressed when the dedicated vector-street-lines overlay already covers it).
        target = isStreetLineLayer(layer) && !hasVectorStreets ? 1 : 0;
      } else {
        target = 0; // terrain
      }
      fadeTargets.push({ layerId: layer.id, type: layer.type, target });
    }

    // Capture each layer's authored paint opacity once (per style load) so fades always
    // restore the exact original value — some are data expressions, not plain numbers.
    for (const ft of fadeTargets) {
      if (orig.has(ft.layerId)) continue;
      const props = PAINT_OPACITY_PROPS[ft.type];
      let value: any = 1;
      if (props) {
        try {
          value = (map as any).getPaintProperty(ft.layerId, props[0]);
        } catch {
          value = 1;
        }
      }
      // The app's own raster overlays are pinned rather than read: whatever they
      // are at this instant (0 as a standing cache, mid-fade, hidden behind the
      // other mode) is state, never design. `prewarmRasterTiles` seeds the same
      // value — this is the half that holds when the capture happens after a
      // prewarm, or on a re-learn the seed never saw.
      if (RASTER_OVERLAY_MODE_LAYERS.has(ft.layerId)) value = 1;
      orig.set(ft.layerId, value ?? 1);
    }

    // Cancel any in-flight deferred pass from a rapid style switch.
    if (styleFadeCleanupRef.current) {
      clearTimeout(styleFadeCleanupRef.current.timer);
      styleFadeCleanupRef.current = null;
    }

    // GATE (raster modes): hold the cross-fade until the incoming imagery/topo tiles
    // are resident, so the fade reveals loaded pixels instead of grey blanks. A hard
    // timeout caps the wait, and a run-id check drops stale gates when the user
    // re-switches while we were waiting.
    if (waitForTiles && mode !== 'standard') {
      const rasterLayerId = mode === 'satellite' ? 'satellite-layer' : 'terrain-layer';
      if (map.getLayer(rasterLayerId)) {
        // Reveal at opacity 0 BEFORE waiting, so MapLibre starts fetching the
        // viewport tiles now and readiness reflects real progress.
        try {
          if ((map as any).getLayoutProperty(rasterLayerId, 'visibility') === 'none') {
            map.setLayoutProperty(rasterLayerId, 'visibility', 'visible');
          }
          (map as any).setPaintProperty(rasterLayerId, 'raster-opacity-transition', {
            duration: 0,
            delay: 0,
          });
          (map as any).setPaintProperty(rasterLayerId, 'raster-opacity', 0);
        } catch {
          // ignore
        }
        await waitForRasterTiles(map, rasterLayerId);
        if (runId !== styleFadeRunIdRef.current) return; // superseded by a newer switch
      }
    }

    let anyFadeOut = false;
    let maxFadeMs = 0;
    for (const { layerId, type, target } of fadeTargets) {
      const props = PAINT_OPACITY_PROPS[type];
      if (!props) continue;

      const authored = orig.get(layerId) ?? 1;
      const toValue = target === 1 ? authored : 0;

      // Apple Maps choreography: the base cross-fades quickly while labels hold back
      // and arrive after the imagery settles; outgoing labels duck out early so they
      // never linger over the incoming layer.
      const isLabel = type === 'symbol';
      const duration = isLabel ? (target === 1 ? LABEL_FADE_MS : LABEL_FADE_OUT_MS) : STYLE_FADE_MS;
      let delay = isLabel && target === 1 ? LABEL_FADE_IN_DELAY_MS : 0;
      // Give freshly-shown raster tiles a head start so the fade-in reveals loaded imagery.
      if (target === 1 && type === 'raster') {
        delay = Math.max(delay, RASTER_TILE_HEAD_START_MS);
      }
      maxFadeMs = Math.max(maxFadeMs, delay + duration);

      try {
        if (
          target === 1 &&
          !(layerId === '3d-buildings' && hideMassingRef.current) &&
          (map as any).getLayoutProperty(layerId, 'visibility') === 'none'
        ) {
          map.setLayoutProperty(layerId, 'visibility', 'visible');
        }
      } catch {
        // ignore
      }

      for (const prop of props) {
        let current: any;
        try {
          current = (map as any).getPaintProperty(layerId, prop);
        } catch {
          continue;
        }
        // Styles often omit opacity (implicit 1) — getPaintProperty then returns
        // undefined, so normalize before comparing or the fade would be skipped.
        const currentNum = typeof current === 'number' ? current : 1;
        if (currentNum === toValue) continue;

        if (target === 0) anyFadeOut = true;
        try {
          (map as any).setPaintProperty(layerId, `${prop}-transition`, {
            duration,
            delay,
          });
          (map as any).setPaintProperty(layerId, prop, toValue);
        } catch {
          // Ignore unmodifiable internal layer styles
        }
      }
    }

    // Deferred pass: hide layers that ended fully transparent once the fade completes.
    if (anyFadeOut) {
      const timer = setTimeout(() => {
        styleFadeCleanupRef.current = null;
        for (const { layerId, type, target } of fadeTargets) {
          if (target !== 0) continue;
          // Prewarmed raster layers are a standing tile cache — never hide them.
          if (prewarmedRasterLayersRef.current.has(layerId)) continue;
          const props = PAINT_OPACITY_PROPS[type];
          if (!props) continue;
          try {
            if ((map as any).getPaintProperty(layerId, props[0]) === 0) {
              map.setLayoutProperty(layerId, 'visibility', 'none');
            }
          } catch {
            // ignore
          }
        }
      }, maxFadeMs + 50);
      styleFadeCleanupRef.current = { timer, mode };
    }

    // Keep the other raster mode pre-warmed (visible at opacity 0, tiles resident)
    // so the next switch is instant.
    if (waitForTiles) {
      for (const m of ['satellite', 'terrain'] as const) {
        if (m !== mode) prewarmRasterTiles(map, m);
      }
    }
  };

  /**
   * Mode camera choreography (Apple Maps behaviour):
   * - Terrain: true DEM displacement (setTerrain) + 55° tilt so relief reads well.
   * - Standard: gentle 45° tilt when zoomed into the building-extrusion range (top-down
   *   views make extruded blocks invisible); flattens out at street-map zooms.
   * - Satellite: level orthographic-style view over the imagery.
   */
  /**
   * Zoom-pulse "dive" (Apple Maps behaviour): as the new layer cross-fades in, the
   * camera pushes in slightly and then settles back — one synchronized beat.
   *
   * Contract: the camera must always return to exactly the zoom it started at
   * (baseZoom), so repeated switches never drift. MapLibre easeTo replaces any
   * in-flight camera animation, so when a pitch ease is running (or about to run)
   * the dive is FOLDED into it — zoom + pitch glide to the apex together, then the
   * settle phase eases zoom back. If the camera is still easing at settle time,
   * settle defers to the next idle and aborts if the user has grabbed the camera.
   */
  const startZoomPulse = (
    map: maplibregl.Map,
    pitchTarget: CameraEaseTarget | null
  ) => {
    if (zoomPulseTimerRef.current !== null) {
      clearTimeout(zoomPulseTimerRef.current);
      zoomPulseTimerRef.current = null;
    }
    if (pulseBaseZoomRef.current === null) {
      // Fresh pulse (none was active): anchor the settle target at the resting zoom.
      pulseBaseZoomRef.current = map.getZoom();
    }
    const baseZoom = pulseBaseZoomRef.current ?? map.getZoom();
    const apexZoom = baseZoom + PULSE_ZOOM_DELTA;

    const doSettle = () => {
      // User grabbed the camera or zoomed themselves mid-pulse — never fight them.
      // (Our own dive ends exactly at apexZoom, so any deviation means user intent.)
      if (Math.abs(map.getZoom() - apexZoom) > 0.05 || map.isMoving()) {
        pulseBaseZoomRef.current = null; // no settle ease follows; re-arm immediately
        return;
      }
      map.easeTo({ zoom: baseZoom, duration: PULSE_OUT_MS });
      // Keep the base anchor until the settle ease finishes: a switch issued mid-settle
      // must still target the ORIGINAL zoom, not re-base on the flying camera.
      setTimeout(() => {
        pulseBaseZoomRef.current = null;
      }, PULSE_OUT_MS + 80);
    };
    const settle = () => {
      zoomPulseTimerRef.current = null;
      if (map.isMoving()) {
        // A camera ease is still in flight; settle once it rests.
        map.once('idle', doSettle);
        return;
      }
      doSettle();
    };

    if (pitchTarget) {
      // Fold: easeTo replaces the in-flight pitch ease, so re-issue its full target
      // (pitch + bearing + own duration) with the dive zoom added — one synchronized
      // glide in which zoom and pitch arrive at the apex together.
      map.easeTo({
        zoom: apexZoom,
        pitch: pitchTarget.pitch,
        ...(pitchTarget.bearing !== undefined ? { bearing: pitchTarget.bearing } : {}),
        duration: pitchTarget.duration,
      });
      zoomPulseTimerRef.current = setTimeout(settle, pitchTarget.duration + 60);
    } else {
      map.easeTo({ zoom: apexZoom, duration: PULSE_IN_MS });
      zoomPulseTimerRef.current = setTimeout(settle, PULSE_IN_MS + 60);
    }
  };

  const syncCameraForMode = (
    map: maplibregl.Map,
    mode: MapStyleMode
  ): CameraEaseTarget | null => {
    // Returns the camera ease this call issued (so the zoom pulse can fold into the
    // same glide), or null when no camera ease was issued.
    const currentPitch = map.getPitch();
    if (mode === 'terrain') {
      autoTiltedRef.current = false;
      // Lazily ensure the DEM source exists (e.g. mode toggled before style.load setup ran).
      if (!map.getSource('terrain-dem-source')) {
        map.addSource('terrain-dem-source', {
          type: 'raster-dem',
          tiles: [
            'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png',
          ],
          tileSize: 256,
          maxzoom: 13,
          encoding: 'terrarium',
        });
      }
      map.setTerrain({ source: 'terrain-dem-source' });
      if (currentPitch < 1) {
        const bearing = map.getBearing() === 0 ? -17.5 : map.getBearing();
        map.easeTo({ pitch: 55, bearing, duration: 900 });
        return { pitch: 55, bearing, duration: 900 };
      }
      return null;
    } else {
      if (map.getTerrain()) {
        map.setTerrain(null);
      }
      if (mode === 'standard') {
        // Auto-tilt only when the camera is still flat or already auto-tilted by us —
        // never stomp a pitch the user set themselves.
        const buildingZoom = map.getZoom() >= 14.6;
        if (currentPitch < 1 && buildingZoom) {
          autoTiltedRef.current = true;
          map.easeTo({ pitch: 45, duration: 800 });
          return { pitch: 45, duration: 800 };
        } else if (autoTiltedRef.current && !buildingZoom) {
          autoTiltedRef.current = false;
          map.easeTo({ pitch: 0, duration: 700 });
          return { pitch: 0, duration: 700 };
        }
        return null;
      } else if (currentPitch >= 1) {
        map.easeTo({ pitch: 0, duration: 700 });
        return { pitch: 0, duration: 700 };
      }
      return null;
    }
  };

  /**
   * Registers all raster sources, 3D buildings, and custom GeoJSON overlays.
   *
   * Two kinds of caller, and they must not be confused:
   *   • a real style load (initial load, theme toggle, WebGL context restore) brings
   *     a NEW style whose authored paint values have to be learned from it, and
   *     whose raster layers are recreated cold — so `relearnPaintOpacity` is true;
   *   • the render gate's repair pass re-applies the style that is ALREADY loaded
   *     and is called for missing layers only. Re-learning there is wrong twice
   *     over: the style it sees is mid-swap, and the layers it reads are being
   *     faded right then. It passes `relearnPaintOpacity: false`.
   *
   * Everything installed here is idempotent (each helper guards on getSource /
   * getLayer), so an extra call is always safe — only the bookkeeping is not.
   */
  const setupCustomLayersAndSources = (
    map: maplibregl.Map,
    { relearnPaintOpacity = true }: { relearnPaintOpacity?: boolean } = {}
  ) => {
    const style = map.getStyle();
    if (!style) return;

    // Fresh style (initial load or theme switch): re-capture authored paint opacities
    // and re-arm the standing raster cache (layers are recreated hidden).
    if (relearnPaintOpacity) {
      originalPaintOpacitiesRef.current.clear();
      prewarmedRasterLayersRef.current.clear();
    }

    const currentTheme = themeRef.current;
    const currentMode = mapStyleRef.current;
    const accentColor = currentTheme === 'dark' ? '#0A84FF' : '#0071E3';
    const firstLayerId = style.layers?.[0]?.id;

    // 1. Satellite Raster Source & Layer (ESRI World Imagery)
    // maxzoom 18, NOT 19: outside metro coverage Esri has no z19 tiles and serves
    // grey "Map data not yet available" placeholders instead (verified via their
    // tilemap API for rural parcels). Capping at 18 makes MapLibre overzoom the
    // deepest REAL imagery — slightly soft when fully zoomed, never placeholder-grey.
    if (!map.getSource('satellite-source')) {
      map.addSource('satellite-source', {
        type: 'raster',
        tiles: [
          'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        ],
        tileSize: 256,
        maxzoom: 18,
        attribution: 'Esri, Maxar, Earthstar Geographics',
      });
    }
    if (!map.getLayer('satellite-layer')) {
      map.addLayer(
        {
          id: 'satellite-layer',
          type: 'raster',
          source: 'satellite-source',
          layout: {
            visibility: currentMode === 'satellite' ? 'visible' : 'none',
          },
          // Kept: these two layers are hidden in the default mode (visibility
          // 'none'), so this cannot affect the standard-basemap numbers above,
          // and it removes a 300 ms per-tile cross-fade in the satellite and
          // terrain modes — where the imagery IS the layer being painted.
          paint: { 'raster-fade-duration': 0 },
        },
        firstLayerId
      );
    }

    // 2. Terrain Raster Source & Layer (OpenTopoMap, maxzoom 17)
    if (!map.getSource('terrain-source')) {
      map.addSource('terrain-source', {
        type: 'raster',
        tiles: [
          'https://a.tile.opentopomap.org/{z}/{x}/{y}.png',
          'https://b.tile.opentopomap.org/{z}/{x}/{y}.png',
          'https://c.tile.opentopomap.org/{z}/{x}/{y}.png',
        ],
        tileSize: 256,
        maxzoom: 17,
        attribution: '© OpenTopoMap (CC-BY-SA)',
      });
    }
    if (!map.getLayer('terrain-layer')) {
      map.addLayer(
        {
          id: 'terrain-layer',
          type: 'raster',
          source: 'terrain-source',
          layout: {
            visibility: currentMode === 'terrain' ? 'visible' : 'none',
          },
          paint: { 'raster-fade-duration': 0 },
        },
        firstLayerId
      );
    }

    // 2b. Hillshade Source & Layer (AWS Terrain Tiles / Terrarium PNG, global)
    if (!map.getSource('hillshade-source')) {
      map.addSource('hillshade-source', {
        type: 'raster-dem',
        tiles: [
          'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png',
        ],
        tileSize: 256,
        maxzoom: 13,
        encoding: 'terrarium',
        attribution: 'Terrain: AWS Open Data / Mapzen',
      });
    }
    if (!map.getLayer('hillshade-layer')) {
      map.addLayer(
        {
          id: 'hillshade-layer',
          type: 'hillshade',
          source: 'hillshade-source',
          layout: {
            visibility: currentMode === 'terrain' ? 'visible' : 'none',
          },
          paint: {
            'hillshade-exaggeration': 0.45,
            'hillshade-shadow-color': '#473B24',
            'hillshade-highlight-color': '#FFFFFF',
            'hillshade-accent-color': '#3A3126',
          },
        },
        firstLayerId
      );
    }

    // 2c. Dedicated 3D Terrain DEM Source (separate from hillshade-source per MapLibre
    // guidance — sharing one source between hillshade + setTerrain degrades render quality).
    if (!map.getSource('terrain-dem-source')) {
      map.addSource('terrain-dem-source', {
        type: 'raster-dem',
        tiles: [
          'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png',
        ],
        tileSize: 256,
        maxzoom: 13,
        encoding: 'terrarium',
      });
    }

    // 3. Find first symbol layer to place 3D buildings below street/POI labels
    let firstSymbolId: string | undefined;
    for (const l of style.layers || []) {
      if (l.type === 'symbol') {
        firstSymbolId = l.id;
        break;
      }
    }

    // Remove default building-3d if already present in style (e.g., liberty) to ensure standardized styling
    if (map.getLayer('building-3d')) {
      try {
        map.removeLayer('building-3d');
      } catch {}
    }

    // Add standardized 3D Buildings Fill-Extrusion Layer (if vector source available)
    if (!map.getLayer('3d-buildings')) {
      const vectorSourceId =
        Object.keys(style.sources || {}).find(
          (id) => (map.getSource(id) as any)?.type === 'vector'
        );

      if (vectorSourceId && map.getSource(vectorSourceId)) {
        map.addLayer(
          {
            id: '3d-buildings',
            source: vectorSourceId,
            'source-layer': 'building',
            type: 'fill-extrusion',
            // Low enough that Terrain mode shows extruded blocks over the relief;
            // below ~14.5 tile detail is too coarse for meaningful building shapes.
            minzoom: 14.5,
            paint: {
              'fill-extrusion-color': currentTheme === 'dark' ? '#1F2430' : '#E8E6E1',
              'fill-extrusion-height': [
                'coalesce',
                ['get', 'render_height'],
                ['get', 'height'],
                0,
              ],
              'fill-extrusion-base': [
                'coalesce',
                ['get', 'render_min_height'],
                ['get', 'min_height'],
                0,
              ],
              'fill-extrusion-opacity': 0.9,
            },
          },
          firstSymbolId
        );
      }
    }
    // Re-assert massing visibility after every style (re)load: satellite never shows
    // extrusions, and neither does an active capture/site session (hideMassing).
    if (map.getLayer('3d-buildings')) {
      map.setLayoutProperty(
        '3d-buildings',
        'visibility',
        mapStyleRef.current !== 'satellite' && !hideMassingRef.current ? 'visible' : 'none'
      );
    }

    // 4. Proposed Building Footprint Overlay
    if (!map.getSource('footprint-source')) {
      map.addSource('footprint-source', {
        type: 'geojson',
        data: footprintGeoJsonRef.current,
      });
    } else {
      (map.getSource('footprint-source') as maplibregl.GeoJSONSource).setData(
        footprintGeoJsonRef.current
      );
    }
    if (!map.getLayer('footprint-fill')) {
      map.addLayer({
        id: 'footprint-fill',
        type: 'fill',
        source: 'footprint-source',
        paint: {
          'fill-color': accentColor,
          'fill-opacity': 0.25,
        },
      });
    }
    if (!map.getLayer('footprint-line')) {
      map.addLayer({
        id: 'footprint-line',
        type: 'line',
        source: 'footprint-source',
        paint: {
          'line-color': accentColor,
          'line-width': 2,
          'line-dasharray': [2, 2],
        },
      });
    }

    // 5. Entrance Arrow (Shaft & Head) Overlay
    if (!map.getSource('entrance-shaft-source')) {
      map.addSource('entrance-shaft-source', {
        type: 'geojson',
        data: entranceShaftGeoJsonRef.current,
      });
    } else {
      (map.getSource('entrance-shaft-source') as maplibregl.GeoJSONSource).setData(
        entranceShaftGeoJsonRef.current
      );
    }
    if (!map.getLayer('entrance-shaft')) {
      map.addLayer({
        id: 'entrance-shaft',
        type: 'line',
        source: 'entrance-shaft-source',
        layout: {
          'line-cap': 'round',
        },
        paint: {
          'line-color': accentColor,
          'line-width': 3,
        },
      });
    }

    if (!map.getSource('entrance-head-source')) {
      map.addSource('entrance-head-source', {
        type: 'geojson',
        data: entranceHeadGeoJsonRef.current,
      });
    } else {
      (map.getSource('entrance-head-source') as maplibregl.GeoJSONSource).setData(
        entranceHeadGeoJsonRef.current
      );
    }
    if (!map.getLayer('entrance-head')) {
      map.addLayer({
        id: 'entrance-head',
        type: 'fill',
        source: 'entrance-head-source',
        paint: {
          'fill-color': accentColor,
          'fill-opacity': 1.0,
        },
      });
    }

    // 6. Tree Canopy Clusters Overlay
    const treeData =
      treeClustersRef.current && treeClustersRef.current.features?.length
        ? (treeClustersRef.current as any)
        : EMPTY_GEOJSON_COLLECTION;

    if (!map.getSource('tree-clusters-source')) {
      map.addSource('tree-clusters-source', {
        type: 'geojson',
        data: treeData,
      });
    } else {
      (map.getSource('tree-clusters-source') as maplibregl.GeoJSONSource).setData(
        treeData
      );
    }
    if (!map.getLayer('tree-clusters-fill')) {
      map.addLayer({
        id: 'tree-clusters-fill',
        type: 'fill',
        source: 'tree-clusters-source',
        layout: {
          visibility: showTreeLayerRef.current ? 'visible' : 'none',
        },
        paint: {
          'fill-color': [
            'match',
            ['coalesce', ['get', 'rank'], ['get', 'preservation_rank'], ''],
            'preserve',
            '#34C759',
            'compensate',
            '#FF9F0A',
            'removable',
            '#FF3B30',
            '#34C759',
          ],
          'fill-opacity': 0.3,
        },
      });
    }
    if (!map.getLayer('tree-clusters-line')) {
      map.addLayer({
        id: 'tree-clusters-line',
        type: 'line',
        source: 'tree-clusters-source',
        layout: {
          visibility: showTreeLayerRef.current ? 'visible' : 'none',
        },
        paint: {
          'line-color': [
            'match',
            ['coalesce', ['get', 'rank'], ['get', 'preservation_rank'], ''],
            'preserve',
            '#248A3D',
            'compensate',
            '#FF9F0A',
            'removable',
            '#FF3B30',
            '#34C759',
          ],
          'line-width': 1.5,
          'line-dasharray': [2, 2],
        },
      });
    }

    // 7. Water Bodies Overlay
    const waterData =
      waterBodiesRef.current && waterBodiesRef.current.features?.length
        ? (waterBodiesRef.current as any)
        : EMPTY_GEOJSON_COLLECTION;

    if (!map.getSource('water-bodies-source')) {
      map.addSource('water-bodies-source', {
        type: 'geojson',
        data: waterData,
      });
    } else {
      (map.getSource('water-bodies-source') as maplibregl.GeoJSONSource).setData(
        waterData
      );
    }
    if (!map.getLayer('water-bodies-fill')) {
      map.addLayer({
        id: 'water-bodies-fill',
        type: 'fill',
        source: 'water-bodies-source',
        layout: {
          visibility: showWaterLayerRef.current ? 'visible' : 'none',
        },
        paint: {
          'fill-color': '#0A84FF',
          'fill-opacity': 0.3,
        },
      });
    }
    if (!map.getLayer('water-bodies-line')) {
      map.addLayer({
        id: 'water-bodies-line',
        type: 'line',
        source: 'water-bodies-source',
        layout: {
          visibility: showWaterLayerRef.current ? 'visible' : 'none',
        },
        paint: {
          'line-color': '#0A84FF',
          'line-width': 1.5,
        },
      });
    }

    // Apply the active Hybrid logic filter
    applyMapStyleVisibility(map, currentMode);
    syncCameraForMode(map, currentMode);
    // Warm the idle raster mode's tiles so the first switch to it is instant.
    if (currentMode !== 'standard') {
      for (const m of ['satellite', 'terrain'] as const) {
        if (m !== currentMode) prewarmRasterTiles(map, m);
      }
    }
  };

  // Mount MapLibre Map instance
  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    const initialCenter: [number, number] = [
      longitude ?? defaultLon,
      latitude ?? defaultLat,
    ];
    const initialZoom = latitude && longitude ? 16 : defaultZoom;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: getVectorStyleUrl(theme),
      center: initialCenter,
      zoom: initialZoom,
      minZoom: 3,
      // Cap at z18: beyond that the pitched camera dips below extruded rooftops and the
      // scene collapses into floating grey blocks with the base map invisible.
      maxZoom: maxZoomRef.current,
      pitch: 0,
      bearing: 0,
      attributionControl: false,
      /* ---------------------------------------------------------------------
         B8: MAP RENDER TUNING WAS TRIED AND REVERTED — the defaults are better.

         Measured at 4× CPU throttle on the real basemap, over the same tiles and
         in the same minute (two builds, same probe):

           `fadeDuration: 0, crossSourceCollisions: false, renderWorldCopies:
           false`  → streaming pan p50 16 fps (62.4 ms), 71 frames over 50 ms
           library defaults              → streaming pan p50 36 fps (27.8 ms), 3
                                            frames over 50 ms

         Settled panning was identical either way (47.8 vs 48.1 fps, 20.9 ms per
         frame): those options change how tiles are batch-committed during
         streaming, not the steady-state cost, and removing the cross-fade makes
         the engine commit each arriving tile instead of coalescing them.
         `maxTileCacheSize: 80` was tried separately and was no better (36 → 16).

         Three further items from the brief do not exist in this library version,
         verified against maplibre-gl's own type definitions: `keepBuffer` and
         `preferCanvas` are Leaflet/Mapbox options, and `detectRetina` is gone
         (pixel ratio is simply what the device reports). */
    });

    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 10,
      className: 'apple-map-popup',
    });
    popupRef.current = popup;

    // Failsafe: if vector style fails to load (e.g. OpenFreeMap network block, rate limit, timeout),
    // gracefully fall back to OSM raster tiles so the user never sees a blank canvas.
    let styleFallbackTimer: ReturnType<typeof setTimeout> | null = null;

    const triggerFallbackStyle = () => {
      if (fallbackAppliedRef.current) return;
      fallbackAppliedRef.current = true;
      setIsFallbackActive(true);
      try {
        appStyleIntentRef.current = true;
        markStyleReplaced();
        map.setStyle(getOsmRasterFallbackStyle(themeRef.current));
      } catch (err) {
        console.warn('Failed to apply fallback map style:', err);
      }
    };

    styleFallbackTimer = setTimeout(() => {
      if (!map.isStyleLoaded() && !fallbackAppliedRef.current) {
        console.warn('Vector map style timed out. Falling back to OSM raster tiles.');
        triggerFallbackStyle();
      }
    }, 4500);

    const handleMapError = (e: any) => {
      // If error occurs while initial vector style is loading or tiles fail, activate fallback
      if (!map.isStyleLoaded() && !fallbackAppliedRef.current) {
        console.warn('Map style loading error detected, activating fallback:', e);
        triggerFallbackStyle();
      }
    };
    map.on('error', handleMapError);

    map.on('style.load', () => {
      if (styleFallbackTimer) {
        clearTimeout(styleFallbackTimer);
        styleFallbackTimer = null;
      }
      // The render gate swaps the style too — once to strip its layers (freeze),
      // once to put them back (thaw) — and a diff swap fires `style.load` as well
      // (measured, ~165 ms after the strip of a 122-layer style). Neither is a
      // style change for the app:
      //   • while frozen the style must stay EMPTY. Installing here puts back the
      //     very layers the gate removed, and the covered map keeps fetching and
      //     painting underneath — the traffic the freeze exists to stop. The
      //     intent flag is left untouched: a real style swap queued behind this
      //     load still gets its re-learn.
      //   • a thaw restore re-applies the style the app already had, so its load
      //     is a repair pass, not a new style: the snapshot holds every layer, and
      //     re-reading the learned opacities here would sample a mid-switch style.
      if (mapRenderGateFrozen()) {
        map.resize();
        return;
      }
      const appAppliedStyle = appStyleIntentRef.current;
      appStyleIntentRef.current = false;
      setupCustomLayersAndSources(map, { relearnPaintOpacity: appAppliedStyle });
      map.resize();
    });

    map.on('load', () => {
      map.resize();
    });

    // Click handler for location selection
    map.on('click', (e: maplibregl.MapMouseEvent) => {
      onLocationSelectRef.current(e.lngLat.lat, e.lngLat.lng);
    });

    // Standard-mode auto-tilt: pitch into 3D when zooming into the extrusion range and
    // flatten again when zooming back out. Skipped when the user has pitched manually.
    map.on('zoomend', () => {
      if (mapStyleRef.current === 'standard') {
        syncCameraForMode(map, 'standard');
      }
    });

    // Any manual pitch adjustment (right-drag / compass) hands camera control to the user.
    map.on('pitchend', () => {
      if (Math.abs(map.getPitch() - 45) > 0.5) {
        autoTiltedRef.current = false;
      }
    });

    // Tooltips on Hover for Custom GeoJSON Layers
    map.on('mouseenter', 'tree-clusters-fill', (e: maplibregl.MapLayerMouseEvent) => {
      map.getCanvas().style.cursor = 'pointer';
      const feature = e.features?.[0];
      if (feature) {
        const props = (feature.properties as any) || {};
        const id = props.cluster_id || 'Cluster';
        const area = props.area_sqm ? `${props.area_sqm} m²` : '';
        const ndvi =
          props.mean_ndvi !== undefined
            ? ` (NDVI: ${Number(props.mean_ndvi).toFixed(2)})`
            : '';
        const r = props.rank || props.preservation_rank;
        const rank = r ? ` [${String(r).toUpperCase()}]` : '';
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="vibrancy-pill px-2 py-1 text-xs">Tree ${id}: ${area}${ndvi}${rank}</div>`
          )
          .addTo(map);
      }
    });
    map.on('mouseleave', 'tree-clusters-fill', () => {
      map.getCanvas().style.cursor = '';
      popup.remove();
    });

    map.on('mouseenter', 'water-bodies-fill', (e: maplibregl.MapLayerMouseEvent) => {
      map.getCanvas().style.cursor = 'pointer';
      const feature = e.features?.[0];
      if (feature) {
        const props = (feature.properties as any) || {};
        const id = props.cluster_id || 'Water Body';
        const area = props.area_sqm ? `${props.area_sqm} m²` : '';
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="vibrancy-pill px-2 py-1 text-xs">${id}: ${area}</div>`
          )
          .addTo(map);
      }
    });
    map.on('mouseleave', 'water-bodies-fill', () => {
      map.getCanvas().style.cursor = '';
      popup.remove();
    });

    map.on('mouseenter', 'footprint-fill', (e: maplibregl.MapLayerMouseEvent) => {
      map.getCanvas().style.cursor = 'pointer';
      const feature = e.features?.[0];
      if (feature) {
        const title =
          (feature.properties as any)?.title || 'Proposed Layout Footprint';
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="vibrancy-pill px-2 py-1 text-xs">${title}</div>`
          )
          .addTo(map);
      }
    });
    map.on('mouseleave', 'footprint-fill', () => {
      map.getCanvas().style.cursor = '';
      popup.remove();
    });

    map.on('mouseenter', 'entrance-head', (e: maplibregl.MapLayerMouseEvent) => {
      map.getCanvas().style.cursor = 'pointer';
      const feature = e.features?.[0];
      if (feature) {
        const title = (feature.properties as any)?.title || 'Main Entrance';
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="vibrancy-pill px-2 py-1 text-xs">${title}</div>`
          )
          .addTo(map);
      }
    });
    map.on('mouseleave', 'entrance-head', () => {
      map.getCanvas().style.cursor = '';
      popup.remove();
    });

    mapInstanceRef.current = map;
    // Hand the instance to the render gate: while something covers the map (the
    // report sheet, a modal) or a discrete commit is in flight, its tile pipeline
    // is frozen so its frames cannot land inside those interactions. The gate
    // thaws by re-applying the captured style in a diff — which does NOT fire
    // `style.load`, so the layer installer is registered with it as the repair
    // pass for anything the app owns (all of it idempotent). It runs a frame
    // after the restore and without re-learning paint opacities: the style it
    // would otherwise read is the stripped one, mid-switch.
    setMapRenderGateReassert(() =>
      setupCustomLayersAndSources(map, { relearnPaintOpacity: false })
    );
    attachMapRenderGate(map);
    onMapReadyRef.current?.(map);
    // Window and container resize observers
    const resizeObserver = new ResizeObserver(() => {
      map.resize();
    });
    if (mapContainerRef.current) {
      resizeObserver.observe(mapContainerRef.current);
    }

    const handleWindowResize = () => {
      map.resize();
    };
    window.addEventListener('resize', handleWindowResize);

    // Double-frame + timer layout calibration to ensure mobile viewports calculate accurately
    const rafId = requestAnimationFrame(() => {
      map.resize();
    });
    const layoutTimer = setTimeout(() => {
      map.resize();
    }, 250);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        map.resize();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    const handleContextLost = (e: Event) => {
      // MapLibre hands its own event object to this listener, not the DOM
      // WebGLContextEvent: it has no preventDefault. Calling it unconditionally
      // threw `TypeError: e.preventDefault is not a function` on every context
      // loss; cancel only when the event really supports it.
      if (typeof e.preventDefault === 'function') e.preventDefault();
      console.warn('Map WebGL context lost.');
    };
    const handleContextRestored = () => {
      console.info('Map WebGL context restored.');
      map.resize();
      setupCustomLayersAndSources(map);
    };

    map.on('webglcontextlost', handleContextLost as any);
    map.on('webglcontextrestored', handleContextRestored as any);

    return () => {
      if (styleFallbackTimer) clearTimeout(styleFallbackTimer);
      cancelAnimationFrame(rafId);
      clearTimeout(layoutTimer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('resize', handleWindowResize);
      resizeObserver.disconnect();
      map.off('error', handleMapError);
      map.off('webglcontextlost', handleContextLost as any);
      map.off('webglcontextrestored', handleContextRestored as any);
      if (popupRef.current) {
        popupRef.current.remove();
        popupRef.current = null;
      }
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
      if (styleFadeCleanupRef.current) {
        clearTimeout(styleFadeCleanupRef.current.timer);
        styleFadeCleanupRef.current = null;
      }
      if (zoomPulseTimerRef.current) {
        clearTimeout(zoomPulseTimerRef.current);
        zoomPulseTimerRef.current = null;
      }
      onMapReadyRef.current?.(null);
      setMapRenderGateReassert(null);
      attachMapRenderGate(null);
      map.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  // Theme switch: update vector style URL & marker element
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    if (prevThemeRef.current !== null && prevThemeRef.current !== theme) {
      appStyleIntentRef.current = true;
      markStyleReplaced();
      if (fallbackAppliedRef.current) {
        map.setStyle(getOsmRasterFallbackStyle(theme));
      } else {
        map.setStyle(getVectorStyleUrl(theme));
      }

      if (markerRef.current) {
        const pinEl = createPinElement(theme);
        // Replace DOM contents inside marker
        const markerEl = markerRef.current.getElement();
        markerEl.innerHTML = pinEl.innerHTML;
      }
    }
    prevThemeRef.current = theme;
  }, [theme]);

  // Map Details style change: Standard / Satellite / Terrain
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Real switch = a previous mode was seen AND differs. The null check alone would
    // misfire on StrictMode remounts (the ref outlives the unmounted map instance).
    const isUserSwitch =
      prevMapStyleRef.current !== null && prevMapStyleRef.current !== mapStyle;
    prevMapStyleRef.current = mapStyle;

    applyMapStyleVisibility(map, mapStyle, true);
    // Camera first (its pitch ease may be running), then fold the dive beat into it —
    // on real switches only, never on initial mount or StrictMode remount. The fade
    // itself is gated on raster tile readiness and starts the moment tiles land.
    const pitchTarget = syncCameraForMode(map, mapStyle);
    if (isUserSwitch) {
      startZoomPulse(map, pitchTarget);
    }
  }, [mapStyle]);

  // Site session: raise/lower the zoom ceiling (see maxZoom).
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    try {
      map.setMaxZoom(maxZoom);
    } catch {
      // Non-fatal: the map keeps its previous ceiling.
    }
  }, [maxZoom]);

  // Site focus: suppress basemap building massing over the plot (see hideMassing).
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    if (!map.getLayer('3d-buildings')) return;
    map.setLayoutProperty(
      '3d-buildings',
      'visibility',
      mapStyleRef.current !== 'satellite' && !hideMassing ? 'visible' : 'none'
    );
  }, [hideMassing, mapStyle]);

  // Invalidate / Resize helper
  useEffect(() => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.resize();
      const timer = setTimeout(() => {
        if (mapInstanceRef.current) {
          mapInstanceRef.current.resize();
        }
      }, 350);
      return () => clearTimeout(timer);
    }
  }, [invalidateTrigger]);

  // Update site pin marker position and building footprint overlays
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    const accentColor = theme === 'dark' ? '#0A84FF' : '#0071E3';

    if (latitude !== null && longitude !== null) {
      const lngLat: [number, number] = [longitude, latitude];

      if (!markerRef.current) {
        const pinEl = createPinElement(theme);
        const marker = new maplibregl.Marker({
          element: pinEl,
          draggable: true,
          anchor: 'bottom',
        })
          .setLngLat(lngLat)
          .addTo(map);

        marker.on('dragend', () => {
          const pos = marker.getLngLat();
          onLocationSelectRef.current(pos.lat, pos.lng);
        });

        markerRef.current = marker;
      } else {
        markerRef.current.setLngLat(lngLat);
      }

      // Draw oriented building footprint polygon if orientation angle is provided
      // (unless a captured plot owns the site: see hideSiteEstimate).
      if (orientationDegrees !== undefined && !hideSiteEstimate) {
        const plinthSqFt = plinthAreaSqFt ?? 2000;
        const areaM2 = plinthSqFt * 0.092903;
        const aspectRatio = 1.75;
        const widthM = Math.sqrt(areaM2 / aspectRatio);
        const lengthM = widthM * aspectRatio;
        const halfLength = lengthM / 2.0;
        const halfWidth = widthM / 2.0;

        const aRad = (orientationDegrees * Math.PI) / 180.0;
        const longUnitE = Math.sin(aRad);
        const longUnitN = Math.cos(aRad);

        const shortAngleRad = aRad + Math.PI / 2.0;
        const shortUnitE = Math.sin(shortAngleRad);
        const shortUnitN = Math.cos(shortAngleRad);

        const corners = [
          { x: -halfLength, y: -halfWidth },
          { x: halfLength, y: -halfWidth },
          { x: halfLength, y: halfWidth },
          { x: -halfLength, y: halfWidth },
        ];

        const latRad = (latitude * Math.PI) / 180.0;
        const polygonPoints: [number, number][] = corners.map((c) => {
          const metersEast = c.x * longUnitE + c.y * shortUnitE;
          const metersNorth = c.x * longUnitN + c.y * shortUnitN;
          const dLat = metersNorth / 110540.0;
          const dLng = metersEast / (111320.0 * Math.cos(latRad));
          return [longitude + dLng, latitude + dLat]; // [lng, lat]
        });

        // Store the 4 unique polygon corners for centroid calculation
        footprintCornersLatLngRef.current = polygonPoints.slice(0, 4).map(([lng, lat]) => ({
          lat,
          lng,
        }));

        // Close polygon ring for GeoJSON polygon geometry
        const closedPolygonPoints = [...polygonPoints, polygonPoints[0]];

        const footprintFeatureCollection: FeatureCollection<Polygon> = {
          type: 'FeatureCollection',
          features: [
            {
              type: 'Feature',
              geometry: {
                type: 'Polygon',
                coordinates: [closedPolygonPoints],
              },
              properties: {
                title: `Proposed Layout Footprint (${orientationDegrees.toFixed(0)}° Long Axis)`,
              },
            },
          ],
        };

        footprintGeoJsonRef.current = footprintFeatureCollection;

        const footprintSource = map.getSource('footprint-source') as
          | maplibregl.GeoJSONSource
          | undefined;
        if (footprintSource) {
          footprintSource.setData(footprintFeatureCollection);
        }

        // Footprint entrance arrow anchored at midpoint of corresponding edge
        if (entranceDirection) {
          const DIR_TO_DEG: Record<string, number> = {
            N: 0,
            NE: 45,
            E: 90,
            SE: 135,
            S: 180,
            SW: 225,
            W: 270,
            NW: 315,
          };
          const entDeg = DIR_TO_DEG[entranceDirection.toUpperCase()] ?? 45;
          const entRad = (entDeg * Math.PI) / 180.0;
          const uE = Math.sin(entRad);
          const uN = Math.cos(entRad);

          const edgeMidpoints = [
            {
              metersEast: -halfWidth * shortUnitE,
              metersNorth: -halfWidth * shortUnitN,
              normalE: -shortUnitE,
              normalN: -shortUnitN,
            },
            {
              metersEast: halfLength * longUnitE,
              metersNorth: halfLength * longUnitN,
              normalE: longUnitE,
              normalN: longUnitN,
            },
            {
              metersEast: halfWidth * shortUnitE,
              metersNorth: halfWidth * shortUnitN,
              normalE: shortUnitE,
              normalN: shortUnitN,
            },
            {
              metersEast: -halfLength * longUnitE,
              metersNorth: -halfLength * longUnitN,
              normalE: -longUnitE,
              normalN: -longUnitN,
            },
          ];

          let bestEdge = edgeMidpoints[0];
          let bestDot = -Infinity;
          for (const edge of edgeMidpoints) {
            const dot = edge.normalE * uE + edge.normalN * uN;
            if (dot > bestDot) {
              bestDot = dot;
              bestEdge = edge;
            }
          }

          const anchorDLat = bestEdge.metersNorth / 110540.0;
          const anchorDLng = bestEdge.metersEast / (111320.0 * Math.cos(latRad));
          const anchorLat = latitude + anchorDLat;
          const anchorLng = longitude + anchorDLng;

          const arrowLen = 7.0;
          const headLen = 2.5;
          const tipLat = anchorLat + (arrowLen * uN) / 110540.0;
          const tipLng = anchorLng + (arrowLen * uE) / (111320.0 * Math.cos(latRad));

          const headAngle1 = entRad + (145 * Math.PI) / 180.0;
          const headAngle2 = entRad - (145 * Math.PI) / 180.0;
          const wing1Lat = tipLat + (headLen * Math.cos(headAngle1)) / 110540.0;
          const wing1Lng = tipLng + (headLen * Math.sin(headAngle1)) / (111320.0 * Math.cos(latRad));
          const wing2Lat = tipLat + (headLen * Math.cos(headAngle2)) / 110540.0;
          const wing2Lng = tipLng + (headLen * Math.sin(headAngle2)) / (111320.0 * Math.cos(latRad));

          const shaftCollection: FeatureCollection<LineString> = {
            type: 'FeatureCollection',
            features: [
              {
                type: 'Feature',
                geometry: {
                  type: 'LineString',
                  coordinates: [
                    [anchorLng, anchorLat],
                    [tipLng, tipLat],
                  ],
                },
                properties: {
                  title: `Main Entrance: ${entranceDirection.toUpperCase()}`,
                },
              },
            ],
          };

          const headCollection: FeatureCollection<Polygon> = {
            type: 'FeatureCollection',
            features: [
              {
                type: 'Feature',
                geometry: {
                  type: 'Polygon',
                  coordinates: [
                    [
                      [tipLng, tipLat],
                      [wing1Lng, wing1Lat],
                      [wing2Lng, wing2Lat],
                      [tipLng, tipLat],
                    ],
                  ],
                },
                properties: {
                  title: `Main Entrance: ${entranceDirection.toUpperCase()}`,
                },
              },
            ],
          };

          entranceShaftGeoJsonRef.current = shaftCollection;
          entranceHeadGeoJsonRef.current = headCollection;

          const shaftSource = map.getSource('entrance-shaft-source') as
            | maplibregl.GeoJSONSource
            | undefined;
          if (shaftSource) shaftSource.setData(shaftCollection);

          const headSource = map.getSource('entrance-head-source') as
            | maplibregl.GeoJSONSource
            | undefined;
          if (headSource) headSource.setData(headCollection);
        } else {
          entranceShaftGeoJsonRef.current = EMPTY_GEOJSON_COLLECTION;
          entranceHeadGeoJsonRef.current = EMPTY_GEOJSON_COLLECTION;
          const shaftSource = map.getSource('entrance-shaft-source') as
            | maplibregl.GeoJSONSource
            | undefined;
          if (shaftSource) shaftSource.setData(EMPTY_GEOJSON_COLLECTION);
          const headSource = map.getSource('entrance-head-source') as
            | maplibregl.GeoJSONSource
            | undefined;
          if (headSource) headSource.setData(EMPTY_GEOJSON_COLLECTION);
        }
      } else {
        footprintGeoJsonRef.current = EMPTY_GEOJSON_COLLECTION;
        entranceShaftGeoJsonRef.current = EMPTY_GEOJSON_COLLECTION;
        entranceHeadGeoJsonRef.current = EMPTY_GEOJSON_COLLECTION;
        footprintCornersLatLngRef.current = [];

        const footprintSource = map.getSource('footprint-source') as
          | maplibregl.GeoJSONSource
          | undefined;
        if (footprintSource) footprintSource.setData(EMPTY_GEOJSON_COLLECTION);

        const shaftSource = map.getSource('entrance-shaft-source') as
          | maplibregl.GeoJSONSource
          | undefined;
        if (shaftSource) shaftSource.setData(EMPTY_GEOJSON_COLLECTION);

        const headSource = map.getSource('entrance-head-source') as
          | maplibregl.GeoJSONSource
          | undefined;
        if (headSource) headSource.setData(EMPTY_GEOJSON_COLLECTION);
      }

      // Keep paint colors synced with theme
      if (map.getLayer('footprint-fill')) {
        map.setPaintProperty('footprint-fill', 'fill-color', accentColor);
      }
      if (map.getLayer('footprint-line')) {
        map.setPaintProperty('footprint-line', 'line-color', accentColor);
      }
      if (map.getLayer('entrance-shaft')) {
        map.setPaintProperty('entrance-shaft', 'line-color', accentColor);
      }
      if (map.getLayer('entrance-head')) {
        map.setPaintProperty('entrance-head', 'fill-color', accentColor);
      }
      // Buildings visible in Standard + Terrain; hidden in Satellite so extrusions never
      // ghost over the photography.
      const show3dBuildings =
        mapStyleRef.current !== 'satellite' && !hideMassingRef.current;
      if (map.getLayer('3d-buildings')) {
        map.setLayoutProperty(
          '3d-buildings',
          'visibility',
          show3dBuildings ? 'visible' : 'none'
        );
        map.setPaintProperty(
          '3d-buildings',
          'fill-extrusion-color',
          theme === 'dark' ? '#1F2430' : '#E8E6E1'
        );
      }

      const currentZoom = map.getZoom();
      const prevCoords = prevCoordsRef.current;
      const isFirstCoordPass = prevCoords === null;
      const coordsChanged =
        !isFirstCoordPass &&
        (Math.abs(prevCoords.lat - latitude) > 0.00005 ||
          Math.abs(prevCoords.lng - longitude) > 0.00005);

      prevCoordsRef.current = { lat: latitude, lng: longitude };

      if (coordsChanged) {
        if (currentZoom < 15) {
          map.flyTo({ center: lngLat, zoom: 16, duration: 1000, essential: true });
        } else {
          map.panTo(lngLat);
        }
      }
    } else {
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
      footprintGeoJsonRef.current = EMPTY_GEOJSON_COLLECTION;
      entranceShaftGeoJsonRef.current = EMPTY_GEOJSON_COLLECTION;
      entranceHeadGeoJsonRef.current = EMPTY_GEOJSON_COLLECTION;
      footprintCornersLatLngRef.current = [];

      const footprintSource = map.getSource('footprint-source') as
        | maplibregl.GeoJSONSource
        | undefined;
      if (footprintSource) footprintSource.setData(EMPTY_GEOJSON_COLLECTION);

      const shaftSource = map.getSource('entrance-shaft-source') as
        | maplibregl.GeoJSONSource
        | undefined;
      if (shaftSource) shaftSource.setData(EMPTY_GEOJSON_COLLECTION);

      const headSource = map.getSource('entrance-head-source') as
        | maplibregl.GeoJSONSource
        | undefined;
      if (headSource) headSource.setData(EMPTY_GEOJSON_COLLECTION);
    }

    // Expose map, marker, and footprint test shim on window for automated audit/screenshot scripts
    if (typeof window !== 'undefined') {
      const isVisible =
        mapContainerRef.current && mapContainerRef.current.offsetParent !== null;

      (window as any).__maplibreMap = map;
      (window as any).__maplibreMarker = markerRef.current;

      // Provide backwards-compatible proxy shim for __leafletMap / __leafletMarker / __leafletFootprint
      if (isVisible || !(window as any).__leafletMap) {
        const markerObj = markerRef.current;
        (window as any).__leafletMarker = markerObj
          ? {
              getLatLng: () => {
                const ll = markerObj.getLngLat();
                return { lat: ll.lat, lng: ll.lng };
              },
            }
          : null;

        (window as any).__leafletFootprint =
          footprintCornersLatLngRef.current.length > 0
            ? {
                getLatLngs: () => [footprintCornersLatLngRef.current],
              }
            : null;

        (window as any).__leafletMap = {
          raw: map,
          latLngToContainerPoint: (latlng: any) => {
            const lat = latlng.lat !== undefined ? latlng.lat : latlng[0];
            const lng = latlng.lng !== undefined ? latlng.lng : latlng[1];
            return map.project([lng, lat]);
          },
          project: (latlng: any, _zoom?: number) => {
            const lat = latlng.lat !== undefined ? latlng.lat : latlng[0];
            const lng = latlng.lng !== undefined ? latlng.lng : latlng[1];
            return map.project([lng, lat]);
          },
          setZoom: (z: number, _opts?: any) => {
            map.setZoom(z);
          },
          setView: (latlng: any, z: number, _opts?: any) => {
            const lat = latlng.lat !== undefined ? latlng.lat : latlng[0];
            const lng = latlng.lng !== undefined ? latlng.lng : latlng[1];
            map.jumpTo({ center: [lng, lat], zoom: z });
          },
          panTo: (latlng: any) => {
            const lat = latlng.lat !== undefined ? latlng.lat : latlng[0];
            const lng = latlng.lng !== undefined ? latlng.lng : latlng[1];
            map.panTo([lng, lat]);
          },
        };
      }
    }
  }, [latitude, longitude, orientationDegrees, plinthAreaSqFt, entranceDirection, theme, hideSiteEstimate]);

  /**
   * RESET CONTRACT: a reset is a view reset too. The token changes only when
   * the app resets, so ordinary site moves (which have their own flyTo) are
   * untouched. `jumpTo` rather than `flyTo`: the reset is a state, not an
   * animation the reader should wait through.
   */
  const viewResetTokenRef = useRef<number>(viewResetToken);
  useEffect(() => {
    if (viewResetToken === viewResetTokenRef.current) return;
    viewResetTokenRef.current = viewResetToken;
    const map = mapInstanceRef.current;
    if (!map || map._removed) return;
    const hasSite = latitude !== null && longitude !== null;
    map.stop();
    map.jumpTo({
      center: hasSite ? [longitude as number, latitude as number] : [defaultLon, defaultLat],
      zoom: hasSite ? DEFAULT_SITE_ZOOM : defaultZoom,
      pitch: 0,
      bearing: 0,
    });
    popupRef.current?.remove();
  }, [viewResetToken, latitude, longitude]);

  // Synchronize Ecological GeoJSON Layers
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    const treeSource = map.getSource('tree-clusters-source') as
      | maplibregl.GeoJSONSource
      | undefined;
    if (treeSource) {
      const data =
        treeClusters && treeClusters.features?.length
          ? treeClusters
          : EMPTY_GEOJSON_COLLECTION;
      treeSource.setData(data as any);
    }

    if (map.getLayer('tree-clusters-fill')) {
      map.setLayoutProperty(
        'tree-clusters-fill',
        'visibility',
        showTreeLayer ? 'visible' : 'none'
      );
    }
    if (map.getLayer('tree-clusters-line')) {
      map.setLayoutProperty(
        'tree-clusters-line',
        'visibility',
        showTreeLayer ? 'visible' : 'none'
      );
    }

    const waterSource = map.getSource('water-bodies-source') as
      | maplibregl.GeoJSONSource
      | undefined;
    if (waterSource) {
      const data =
        waterBodies && waterBodies.features?.length
          ? waterBodies
          : EMPTY_GEOJSON_COLLECTION;
      waterSource.setData(data as any);
    }

    if (map.getLayer('water-bodies-fill')) {
      map.setLayoutProperty(
        'water-bodies-fill',
        'visibility',
        showWaterLayer ? 'visible' : 'none'
      );
    }
    if (map.getLayer('water-bodies-line')) {
      map.setLayoutProperty(
        'water-bodies-line',
        'visibility',
        showWaterLayer ? 'visible' : 'none'
      );
    }
  }, [treeClusters, waterBodies, showTreeLayer, showWaterLayer]);

  // Opening the Map Details picker signals imminent style switching: pre-warm both
  // raster modes' tiles so whichever the user picks fades in already loaded.
  const handleStylePickerOpen = useCallback(() => {
    const map = mapInstanceRef.current;
    if (!map || map._removed) return;
    prewarmRasterTiles(map, 'satellite');
    prewarmRasterTiles(map, 'terrain');
  }, []);

  const handleResetView = () => {
    if (mapInstanceRef.current) {
      if (latitude !== null && longitude !== null) {
        mapInstanceRef.current.flyTo({
          center: [longitude, latitude],
          zoom: 16,
          essential: true,
        });
      } else {
        mapInstanceRef.current.flyTo({
          center: [defaultLon, defaultLat],
          zoom: defaultZoom,
          essential: true,
        });
      }
    }
  };

  const handleZoomIn = () => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.zoomIn();
    }
  };

  const handleZoomOut = () => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.zoomOut();
    }
  };

  return (
    <div className={`relative z-0 overflow-hidden ${className}`}>
      <div ref={mapContainerRef} className="w-full h-full" />

      {/* Floating Instructions Banner (when no coordinate selected) */}
      {!latitude && !longitude && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-[1000] pointer-events-none">
          <div className="vibrancy-pill px-4 py-2 rounded-full shadow-lg flex items-center gap-2 text-[12px] font-medium text-[var(--text-1)] border border-[var(--panel-border-color)]">
            <Icon name="crosshair" size={14} className="text-[var(--accent-ink)] shrink-0" />
            <span>Click anywhere on the map to place site pin</span>
          </div>
        </div>
      )}

      {/* Floating Bottom-Left Group: Map Details Selector + Coordinate Chip */}
      <div className="absolute bottom-2 sm:bottom-3 left-2 sm:left-3 lg:left-[364px] z-[1000] pointer-events-auto flex items-center gap-1.5 sm:gap-2 max-w-[calc(100vw-110px)] sm:max-w-none">
        <MapStyleSelector
          currentStyle={mapStyle}
          onStyleChange={(s) => {
            // A mode switch commits a lot (style fade bookkeeping, camera ease, a
            // whole layer-visibility pass). Holding the render loop across the
            // commit and its paint keeps the map's own frame OUT of that task —
            // the map repaints on the frame after, which is where it belongs.
            holdMapRenderAcrossCommit('style-switch');
            setMapStyle(s);
          }}
          onOpen={handleStylePickerOpen}
        />

        {latitude !== null && longitude !== null && (
          <div className="vibrancy-pill px-2.5 sm:px-3 py-1 sm:py-1.5 rounded-full flex items-center gap-1.5 sm:gap-2 text-[11px] sm:text-[12px] font-medium text-[var(--text-1)] border border-[var(--panel-border-color)] shadow-md min-w-0">
            <Icon name="crosshair" size={13} className="text-[var(--text-2)] shrink-0" />
            <span className="font-mono tabular-nums truncate">
              {latitude.toFixed(4)}, {longitude.toFixed(4)}
            </span>
            {orientationDegrees !== undefined && (
              <>
                <span className="text-[var(--hairline)] hidden xs:inline">|</span>
                <span className="text-[11px] text-[var(--text-2)] hidden xs:flex items-center gap-1 shrink-0">
                  <Icon name="compass" size={12} className="text-[var(--accent-ink)]" />
                  {orientationDegrees.toFixed(0)}°
                </span>
              </>
            )}
          </div>
        )}
      </div>

      {/* Floating Zoom Controls: Vertical group, two 32px vibrancy squares radius 10 with hairline divider */}
      <div className="absolute top-[62px] sm:top-[76px] lg:top-[118px] map-controls-anchor z-[1000] pointer-events-auto flex flex-col rounded-[10px] vibrancy-panel overflow-hidden border border-[var(--panel-border-color)] shadow-md">
        <button
          type="button"
          onClick={handleZoomIn}
          className="bw-touch-target w-8 h-8 flex items-center justify-center text-[var(--text-1)] hover:bg-[var(--fill)] transition-colors active:brightness-95"
          title="Zoom In"
          aria-label="Zoom In"
        >
          <Icon name="plus" size={15} />
        </button>
        <div className="h-[1px] w-full bg-[var(--hairline)]" />
        <button
          type="button"
          onClick={handleZoomOut}
          className="bw-touch-target w-8 h-8 flex items-center justify-center text-[var(--text-1)] hover:bg-[var(--fill)] transition-colors active:brightness-95"
          title="Zoom Out"
          aria-label="Zoom Out"
        >
          <Icon name="minus" size={15} />
        </button>
      </div>

      {/* Floating Recenter & Layer Chips */}
      <div className="absolute top-[138px] sm:top-[152px] lg:top-[194px] map-controls-anchor z-[1000] pointer-events-auto flex flex-col items-end gap-1.5">
        <button
          type="button"
          onClick={handleResetView}
          className="bw-touch-target w-8 h-8 rounded-[10px] vibrancy-panel flex items-center justify-center text-[var(--text-1)] hover:bg-[var(--fill)] transition-colors border border-[var(--panel-border-color)] shadow-md"
          title="Recenter Map View"
          aria-label="Recenter Map View"
        >
          <Icon name="crosshair" size={15} />
        </button>

        {/* Ecological Layer Toggles */}
        {((treeClusters?.features?.length ?? 0) > 0 ||
          (waterBodies?.features?.length ?? 0) > 0) && (
          <div className="vibrancy-panel rounded-[12px] p-1 flex flex-col gap-1 border border-[var(--panel-border-color)] shadow-md">
            {(treeClusters?.features?.length ?? 0) > 0 && (
              <button
                type="button"
                onClick={() => {
                  holdMapRenderAcrossCommit('layer-toggle');
                  setShowTreeLayer((prev) => !prev);
                }}
                className={`bw-touch-target flex items-center gap-1 px-2 py-1 rounded-[8px] transition-colors text-[11px] font-medium cursor-pointer ${
                  showTreeLayer
                    ? 'bg-[var(--accent-tint)] text-[var(--accent-ink)]'
                    : 'text-[var(--text-2)] hover:bg-[var(--fill)]'
                }`}
                title="Toggle Tree Canopy Layer"
                aria-label="Toggle Tree Canopy Layer"
              >
                <Icon
                  name="tree"
                  size={12}
                  className={showTreeLayer ? 'text-[var(--accent-ink)]' : 'text-[var(--text-2)]'}
                />
                <span>Canopy ({treeClusters?.features.length})</span>
              </button>
            )}
            {(waterBodies?.features?.length ?? 0) > 0 && (
              <button
                type="button"
                onClick={() => {
                  holdMapRenderAcrossCommit('layer-toggle');
                  setShowWaterLayer((prev) => !prev);
                }}
                className={`bw-touch-target flex items-center gap-1 px-2 py-1 rounded-[8px] transition-colors text-[11px] font-medium cursor-pointer ${
                  showWaterLayer
                    ? 'bg-[var(--accent-tint)] text-[var(--accent-ink)]'
                    : 'text-[var(--text-2)] hover:bg-[var(--fill)]'
                }`}
                title="Toggle Water Bodies Layer"
                aria-label="Toggle Water Bodies Layer"
              >
                <Icon
                  name="droplet"
                  size={12}
                  className={showWaterLayer ? 'text-[var(--accent-ink)]' : 'text-[var(--text-2)]'}
                />
                <span>Water ({waterBodies?.features.length})</span>
              </button>
            )}
          </div>
        )}
      </div>

      {/* Dynamic Attribution Compliance Pill (bottom-right) */}
      <div className="absolute bottom-2 sm:bottom-3 right-2 sm:right-4 z-[1000] pointer-events-auto">
        <div className="vibrancy-pill px-2 sm:px-2.5 py-0.5 sm:py-1 rounded-full text-[10px] text-[var(--text-2)] flex items-center gap-1 border border-[var(--panel-border-color)] shadow-sm max-w-[calc(100vw-16px)]">
          <span>&copy;</span>
          <a
            href={isFallbackActive ? 'https://www.openstreetmap.org/copyright' : 'https://openfreemap.org'}
            target="_blank"
            rel="noreferrer"
            className="hover:underline text-[var(--text-1)] font-medium"
          >
            <span className="xs:hidden">{isFallbackActive ? 'OSM' : 'OFM'}</span>
            <span className="hidden xs:inline">{isFallbackActive ? 'OpenStreetMap' : 'OpenFreeMap'}</span>
          </a>
          {!isFallbackActive && (
            <>
              <span>&copy;</span>
              <a
                href="https://www.openstreetmap.org/copyright"
                target="_blank"
                rel="noreferrer"
                className="hover:underline text-[var(--text-1)] font-medium"
              >
                <span className="xs:hidden">OSM</span>
                <span className="hidden xs:inline">OpenStreetMap contributors</span>
              </a>
            </>
          )}

          {mapStyle === 'satellite' && (
            <>
              <span className="text-[var(--hairline)]">|</span>
              <span className="hidden xs:inline">Imagery:</span>
              <a
                href="https://www.esri.com"
                target="_blank"
                rel="noreferrer"
                className="hover:underline text-[var(--text-1)] font-medium"
              >
                <span className="xs:hidden">Esri</span>
                <span className="hidden xs:inline">Esri, Maxar, Earthstar Geographics</span>
              </a>
            </>
          )}

          {mapStyle === 'terrain' && (
            <>
              <span className="text-[var(--hairline)]">|</span>
              <a
                href="https://opentopomap.org"
                target="_blank"
                rel="noreferrer"
                className="hover:underline text-[var(--text-1)] font-medium"
              >
                <span className="xs:hidden">Topo</span>
                <span className="hidden xs:inline">OpenTopoMap (CC-BY-SA)</span>
              </a>
              <span className="text-[var(--hairline)] hidden xs:inline">|</span>
              <a
                href="https://registry.opendata.aws/terrain-tiles/"
                target="_blank"
                rel="noreferrer"
                className="hover:underline text-[var(--text-1)] font-medium hidden xs:inline"
              >
                Terrain: AWS Open Data
              </a>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
