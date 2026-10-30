/**
 * usePlotCameraFocus.ts — selection-driven camera choreography.
 * ==============================================================
 * When a boundary becomes the selected plot, remember where the reader was
 * looking, then frame the ring inside the space the floating panels leave.
 * When the property panel is dismissed, put the camera back exactly as it was.
 *
 * One memory per selection: a second boundary selected after a restore takes
 * a fresh snapshot, so the camera never drifts back to a stale place.
 */
import { useCallback, useEffect, useRef } from 'react';
import type { Map as MlMap } from 'maplibre-gl';
import type { SharedBoundaryState } from '../services/siteBoundary';
import {
  boundaryLngLatBox,
  focusCameraOnPlot,
  readCamera,
  restoreCamera,
  type CameraSnapshot,
} from '../services/plotCamera';

export interface UsePlotCameraFocusOptions {
  getMap: () => MlMap | null;
  boundary: SharedBoundaryState | null;
  /** False while the capture wizard owns the map, or the preview is dismissed. */
  enabled: boolean;
  /**
   * The capture wizard takes the camera over. Snapshot the reader's view when
   * it opens, so dismissing the finished plot returns to where they were —
   * not to the frontage-picking zoom the wizard left behind.
   */
  captureOpen: boolean;
  /** Re-run the first fit once the lazy map engine becomes ready. */
  mapReady: boolean;
  /** Desktop shell state: the insets that keep the ring clear of the panels. */
  leftPanelOpen: boolean;
  rightPanelOpen: boolean;
}

export interface UsePlotCameraFocusResult {
  /** Restore the pre-selection camera. Returns false when nothing was saved. */
  restore: () => boolean;
}

function boundaryKey(boundary: SharedBoundaryState | null): string | null {
  if (!boundary) return null;
  return [
    boundary.origin.lat.toFixed(7),
    boundary.origin.lon.toFixed(7),
    boundary.frontageEdgeIndex ?? '',
    boundary.vertices.map((v) => `${v.x},${v.y}`).join(';'),
  ].join('|');
}

export function usePlotCameraFocus({
  getMap,
  boundary,
  enabled,
  captureOpen,
  mapReady,
  leftPanelOpen,
  rightPanelOpen,
}: UsePlotCameraFocusOptions): UsePlotCameraFocusResult {
  const memoryRef = useRef<CameraSnapshot | null>(null);
  const lastKeyRef = useRef<string | null>(null);

  const key = boundaryKey(boundary);

  useEffect(() => {
    const map = getMap();
    if (!map) return;

    // The wizard owns the camera while it is open. Record the view on entry so
    // the eventual selection has a genuine "before" to return to.
    if (captureOpen) {
      if (memoryRef.current === null) memoryRef.current = readCamera(map);
      return;
    }

    if (!boundary) {
      memoryRef.current = null;
      lastKeyRef.current = null;
      return;
    }
    if (!enabled || !mapReady) return;
    if (!boundaryLngLatBox(boundary)) return;
    if (key === lastKeyRef.current) return;

    // Snapshot once per selection, then frame. The wizard already recorded the
    // reader's view when it opened, so do NOT overwrite it with the camera the
    // wizard left behind — that was the difference between "back to the map I
    // was reading" and "back to the frontage-picking zoom". Panel toggles and
    // window resizes deliberately do not re-fit either.
    if (memoryRef.current === null) memoryRef.current = readCamera(map);
    lastKeyRef.current = key;
    focusCameraOnPlot(map, boundary, {
      width: window.innerWidth,
      height: window.innerHeight,
      leftPanel: leftPanelOpen,
      rightPanel: rightPanelOpen,
    });
  }, [
    boundary,
    captureOpen,
    enabled,
    getMap,
    key,
    leftPanelOpen,
    mapReady,
    rightPanelOpen,
    // `boundary` is stable between reducer commits; `key` is what identifies a
    // genuinely new selection. The effect deliberately reads live panel state
    // at run time so a resize can re-fit without re-saving the camera.
  ]);

  const restore = useCallback((): boolean => {
    const map = getMap();
    const snapshot = memoryRef.current;
    if (!map || !snapshot) return false;
    restoreCamera(map, snapshot);
    memoryRef.current = null;
    lastKeyRef.current = null;
    return true;
  }, [getMap]);

  return { restore };
}
