/**
 * sitePreviewOverlay.ts — site preview map layers.
 * ==========================================================
 * Renders the deterministic /api/site/preview geometry over the map:
 *   - setback band: translucent amber plot tint + dashed plot ring
 *   - buildable polygon: green tint + dashed outline
 *   - footprint: solid accent fill (wings unioned server-side)
 *   - wedge zones: purple tints
 *   - frontage: thick cyan edge + inward-pointing arrow (canvas image)
 * Mirrors mapDrawAdapter's idempotent install + GeoJSON source batching.
 * All colors come from design tokens (MAP_OVERLAY) — no ad-hoc hex here.
 */
import type { Map as MlMap, GeoJSONSource } from 'maplibre-gl';
import { MAP_OVERLAY } from '../../design/tokens';
import { unprojectToLngLat, type LocalOrigin } from '../../services/projection';
import type { SitePreviewResponse } from '../../services/siteIntelligence';

const SPOTLIGHT_SRC = 'bw-preview-spotlight';
const SETBACK_SRC = 'bw-preview-setback';
const BUILDABLE_SRC = 'bw-preview-buildable';
const FOOTPRINT_SRC = 'bw-preview-footprint';
const WEDGES_SRC = 'bw-preview-wedges';
const FRONTAGE_SRC = 'bw-preview-frontage';
const ARROW_SRC = 'bw-preview-arrow';

const ARROW_IMAGE_ID = 'bw-frontage-arrow';

type Origin = { lat: number; lon: number };

function project(v: [number, number], origin: Origin): [number, number] {
  const ll = unprojectToLngLat({ x: v[0], y: v[1] }, origin as LocalOrigin);
  return [ll.lon, ll.lat];
}

function ringFeature(ring: [number, number][], origin: Origin, props: Record<string, unknown> = {}): GeoJSON.Feature<GeoJSON.Polygon> {
  const closed = ring.length > 0 ? [...ring, ring[0]] : [];
  return {
    type: 'Feature',
    properties: props,
    geometry: { type: 'Polygon', coordinates: [closed.map((v) => project(v, origin))] },
  };
}

function emptyPoly(): GeoJSON.Feature<GeoJSON.Polygon> {
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[]] } };
}

/**
 * A world-sized veil with the selected plot punched out. It is the map's
 * equivalent of lowering the room lights: unrelated parcels and labels recede,
 * the surveyed ring keeps its full contrast, and no filter is composited over
 * the canvas. The hole is the opposite winding of the outer ring so the fill
 * rule is unambiguous.
 */
function spotlightFeature(
  ring: [number, number][],
  origin: Origin,
): GeoJSON.Feature<GeoJSON.Polygon> {
  const hole = ring.length >= 3 ? [...ring, ring[0]].map((v) => project(v, origin)).reverse() : [];
  return {
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'Polygon',
      coordinates: [
        [
          [-180, -85],
          [180, -85],
          [180, 85],
          [-180, 85],
          [-180, -85],
        ],
        hole,
      ],
    },
  };
}

function emptyLine(): GeoJSON.Feature<GeoJSON.LineString> {
  return { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [] } };
}

function emptyFc(): GeoJSON.FeatureCollection {
  return { type: 'FeatureCollection', features: [] };
}

/** 24x28 cyan triangle pointing north at rotation 0 (rotated per-feature). */
function makeArrowImage(): { width: number; height: number; data: Uint8Array } {
  const width = 24;
  const height = 28;
  const data = new Uint8Array(width * height * 4);
  const cx = width / 2;
  const apex = 1;
  const base = height - 4;
  const halfBase = 8;
  const inside = (x: number, y: number): boolean => {
    if (y < apex || y > base) return false;
    const t = (y - apex) / (base - apex);
    const half = halfBase * t;
    return x >= cx - half && x <= cx + half;
  };
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (!inside(x, y)) continue;
      const idx = (y * width + x) * 4;
      data[idx] = 0x64;
      data[idx + 1] = 0xd2;
      data[idx + 2] = 0xff;
      data[idx + 3] = 255;
    }
  }
  return { width, height, data };
}

function ensureArrowImage(map: MlMap): void {
  if (map.hasImage(ARROW_IMAGE_ID)) return;
  map.addImage(ARROW_IMAGE_ID, makeArrowImage());
}

/** Install sources + layers once; idempotent per map style. */
export function installPreviewLayers(map: MlMap): void {
  if (map.getSource(SETBACK_SRC)) return;

  map.addSource(SPOTLIGHT_SRC, { type: 'geojson', data: emptyPoly() });
  map.addSource(SETBACK_SRC, { type: 'geojson', data: emptyPoly() });
  map.addSource(BUILDABLE_SRC, { type: 'geojson', data: emptyPoly() });
  map.addSource(FOOTPRINT_SRC, { type: 'geojson', data: emptyPoly() });
  map.addSource(WEDGES_SRC, { type: 'geojson', data: emptyFc() });
  map.addSource(FRONTAGE_SRC, { type: 'geojson', data: emptyLine() });
  map.addSource(ARROW_SRC, { type: 'geojson', data: emptyFc() });
  ensureArrowImage(map);

  // Paint order: spotlight (bottom) -> setback band -> buildable -> wedges ->
  // footprint -> frontage (top). The spotlight is below every app overlay so
  // only the basemap is dimmed, never the evidence the reader is inspecting.
  map.addLayer({
    id: 'bw-preview-spotlight-fill',
    type: 'fill',
    source: SPOTLIGHT_SRC,
    paint: {
      'fill-color': MAP_OVERLAY.spotlight,
      'fill-opacity': MAP_OVERLAY.spotlightOpacity,
      'fill-opacity-transition': { duration: 240, delay: 0 },
    },
  });
  map.addLayer({
    id: 'bw-preview-setback-fill',
    type: 'fill',
    source: SETBACK_SRC,
    paint: { 'fill-color': MAP_OVERLAY.setback, 'fill-opacity': 0.10 },
  });
  map.addLayer({
    id: 'bw-preview-setback-line',
    type: 'line',
    source: SETBACK_SRC,
    paint: { 'line-color': MAP_OVERLAY.setback, 'line-width': 1.5, 'line-dasharray': [2, 2] },
  });
  map.addLayer({
    id: 'bw-preview-buildable-fill',
    type: 'fill',
    source: BUILDABLE_SRC,
    paint: { 'fill-color': MAP_OVERLAY.buildable, 'fill-opacity': 0.10 },
  });
  map.addLayer({
    id: 'bw-preview-buildable-line',
    type: 'line',
    source: BUILDABLE_SRC,
    paint: { 'line-color': MAP_OVERLAY.buildable, 'line-width': 2, 'line-dasharray': [2, 2] },
  });
  map.addLayer({
    id: 'bw-preview-wedges-fill',
    type: 'fill',
    source: WEDGES_SRC,
    paint: { 'fill-color': MAP_OVERLAY.wedge, 'fill-opacity': 0.20 },
  });
  map.addLayer({
    id: 'bw-preview-footprint-fill',
    type: 'fill',
    source: FOOTPRINT_SRC,
    paint: { 'fill-color': MAP_OVERLAY.footprint, 'fill-opacity': 0.30 },
  });
  map.addLayer({
    id: 'bw-preview-footprint-line',
    type: 'line',
    source: FOOTPRINT_SRC,
    paint: { 'line-color': MAP_OVERLAY.footprint, 'line-width': 2 },
  });
  map.addLayer({
    id: 'bw-preview-frontage-line',
    type: 'line',
    source: FRONTAGE_SRC,
    paint: {
      'line-color': MAP_OVERLAY.frontage,
      'line-width': 5,
      'line-opacity': 0.95,
    },
    layout: { 'line-cap': 'round' },
  });
  map.addLayer({
    id: 'bw-preview-frontage-arrow',
    type: 'symbol',
    source: ARROW_SRC,
    layout: {
      'icon-image': ARROW_IMAGE_ID,
      'icon-size': 0.9,
      'icon-rotate': ['get', 'angle'],
      'icon-rotation-alignment': 'map',
      'icon-allow-overlap': true,
      'icon-ignore-placement': true,
    },
  });
}

export interface PreviewRenderInput {
  preview: SitePreviewResponse;
  origin: Origin;
}

function edgeBearingDeg(a: [number, number], b: [number, number]): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  return ((Math.atan2(dx, dy) * 180) / Math.PI % 360 + 360) % 360;
}

/** Push preview geometry into the map sources. */
export function updatePreviewSources(map: MlMap, input: PreviewRenderInput): void {
  const { preview, origin } = input;
  const apply = (id: string, data: GeoJSON.Feature | GeoJSON.FeatureCollection): void => {
    const src = map.getSource(id) as GeoJSONSource | undefined;
    if (src) src.setData(data as never);
  };
  if (!preview.ok) {
    clearPreviewSources(map);
    return;
  }

  apply(SPOTLIGHT_SRC, spotlightFeature(preview.plot.vertices, origin));
  apply(SETBACK_SRC, ringFeature(preview.plot.vertices, origin));
  apply(
    BUILDABLE_SRC,
    preview.buildable.vertices.length >= 3 ? ringFeature(preview.buildable.vertices, origin) : emptyPoly(),
  );
  apply(
    FOOTPRINT_SRC,
    preview.footprint.vertices.length >= 3 ? ringFeature(preview.footprint.vertices, origin) : emptyPoly(),
  );
  apply(
    WEDGES_SRC,
    preview.wedges.length > 0
      ? {
          type: 'FeatureCollection',
          features: preview.wedges
            .filter((w) => w.polygon_coords.length >= 3)
            .map((w) => ringFeature(w.polygon_coords, origin, { wedge_id: w.wedge_id, name: w.name })),
        }
      : emptyFc(),
  );

  const fi = preview.frontage?.edge_index;
  const ring = preview.plot.vertices;
  if (fi !== undefined && ring.length >= 3) {
    const a = ring[fi];
    const b = ring[(fi + 1) % ring.length];
    apply(FRONTAGE_SRC, {
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: [project(a, origin), project(b, origin)] },
    });
    // Inward-pointing arrow at the frontage midpoint (plot ring is CCW).
    const inward = ((edgeBearingDeg(a, b) + 90) % 360 + 360) % 360;
    const mid: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    apply(ARROW_SRC, {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { angle: inward },
          geometry: { type: 'Point', coordinates: project(mid, origin) },
        },
      ],
    });
  } else {
    apply(FRONTAGE_SRC, emptyLine());
    apply(ARROW_SRC, emptyFc());
  }
}

export function clearPreviewSources(map: MlMap): void {
  const apply = (id: string, data: GeoJSON.Feature | GeoJSON.FeatureCollection): void => {
    const src = map.getSource(id) as GeoJSONSource | undefined;
    if (src) src.setData(data as never);
  };
  apply(SPOTLIGHT_SRC, emptyPoly());
  apply(SETBACK_SRC, emptyPoly());
  apply(BUILDABLE_SRC, emptyPoly());
  apply(FOOTPRINT_SRC, emptyPoly());
  apply(WEDGES_SRC, emptyFc());
  apply(FRONTAGE_SRC, emptyLine());
  apply(ARROW_SRC, emptyFc());
}
