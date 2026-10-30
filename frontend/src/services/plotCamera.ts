/**
 * plotCamera.ts — the camera contract for a selected plot.
 * ========================================================
 * A captured boundary is the app's selection subject. Selecting it should
 * read as a spatial move, not a jump: frame the ring with room for the floating
 * panels, keep the reader's bearing, and remember where they were so closing
 * the property panel can put the camera back.
 *
 * The geometry and padding rules live here (pure, browser-free) so the mobile /
 * desktop insets and the reduced-motion decision can be unit-tested without a
 * WebGL context. The React hook simply applies them to a live MapLibre map.
 */
import type { Map as MlMap } from 'maplibre-gl';
import { unprojectToLngLat } from './projection';
import type { SharedBoundaryState } from './siteBoundary';
import { MOTION, spatialDuration } from '../design/tokens';

export interface LngLatBox {
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface CameraSnapshot {
  center: { lng: number; lat: number };
  zoom: number;
  bearing: number;
  pitch: number;
}

export interface CameraPadding {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/**
 * Longitude/latitude envelope of a boundary's local tangent-plane vertices.
 * Returns null for a degenerate ring (fewer than 3 vertices or a zero box), so
 * a malformed plot can never command the camera.
 */
export function boundaryLngLatBox(boundary: SharedBoundaryState | null | undefined): LngLatBox | null {
  if (!boundary || boundary.vertices.length < 3) return null;
  const origin = boundary.origin;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const v of boundary.vertices) {
    const ll = unprojectToLngLat(v, origin);
    west = Math.min(west, ll.lon);
    east = Math.max(east, ll.lon);
    south = Math.min(south, ll.lat);
    north = Math.max(north, ll.lat);
  }
  if (![west, south, east, north].every(Number.isFinite)) return null;
  if (east - west < 1e-9 && north - south < 1e-9) return null;
  return { west, south, east, north };
}

/** MapLibre's [[west, south], [east, north]] bounds shape. */
export function boxToBounds(box: LngLatBox): [[number, number], [number, number]] {
  return [
    [box.west, box.south],
    [box.east, box.north],
  ];
}

/**
 * Padding for a plot-focus fit.
 *
 * The map is edge-to-edge and the desktop shell floats two 340/360px panels
 * over it, so fitting to the raw viewport would centre the plot underneath a
 * panel. The cap keeps the map's usable width sane on a 1024px laptop where
 * both panels are open; below `lg` the panels are drawers and the only losses
 * are the header and the bottom chip band.
 */
export function plotFocusPadding(
  width: number,
  height: number,
  options: { leftPanel?: boolean; rightPanel?: boolean } = {},
): CameraPadding {
  const safeWidth = Math.max(1, width);
  const safeHeight = Math.max(1, height);
  if (safeWidth < 1024) {
    return {
      top: Math.min(112, safeHeight * 0.16),
      bottom: Math.min(136, safeHeight * 0.2),
      left: 20,
      right: 20,
    };
  }
  const left = options.leftPanel === false ? 24 : Math.min(364, safeWidth * 0.28);
  const right = options.rightPanel === false ? 24 : Math.min(384, safeWidth * 0.29);
  return {
    top: Math.min(112, safeHeight * 0.14),
    bottom: Math.min(112, safeHeight * 0.14),
    left,
    right,
  };
}

/** Read the camera state we must be able to return to. */
export function readCamera(map: MlMap): CameraSnapshot {
  const center = map.getCenter();
  return {
    center: { lng: center.lng, lat: center.lat },
    zoom: map.getZoom(),
    bearing: map.getBearing(),
    pitch: map.getPitch(),
  };
}

/**
 * Frame a plot without changing bearing or pitch: orientation is the reader's,
 * and a style/selection move should never spin the world underneath them.
 * `maxZoom` keeps a tiny plot from filling the screen with one wall.
 */
export function focusCameraOnPlot(
  map: MlMap,
  boundary: SharedBoundaryState,
  options: { width: number; height: number; leftPanel?: boolean; rightPanel?: boolean },
): boolean {
  const box = boundaryLngLatBox(boundary);
  if (!box) return false;
  const padding = plotFocusPadding(options.width, options.height, options);
  map.fitBounds(boxToBounds(box), {
    padding,
    maxZoom: 18.4,
    duration: spatialDuration(MOTION.duration.spatial),
    essential: true,
  });
  return true;
}

/**
 * Return to the camera captured before the plot was selected. Bearing and
 * pitch are restored too: if the reader had rotated the map, that orientation
 * is part of where they were.
 */
export function restoreCamera(map: MlMap, snapshot: CameraSnapshot): void {
  map.easeTo({
    center: [snapshot.center.lng, snapshot.center.lat],
    zoom: snapshot.zoom,
    bearing: snapshot.bearing,
    pitch: snapshot.pitch,
    duration: spatialDuration(520),
    essential: true,
  });
}
