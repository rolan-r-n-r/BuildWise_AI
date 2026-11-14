/**
 * CaptureSheet.tsx — STEP ZERO: map-first site capture wizard.
 * =====================================================================
 * Four steps: LOCATE -> TRACE -> FRONTAGE -> REVIEW.
 * - TRACE: point-by-point vertices with FREE/ORTHOGONAL/PARALLEL snap,
 *   magnetic guides, live length+bearing badges, live area/perimeter,
 *   close via first-vertex/double-click, ESC cancels, invalid rings blocked
 *   with the statutory reason (EC-01/02/03 mirror).
 * - FRONTAGE: click the road-facing edge (a smart suggestion is offered).
 * - REVIEW: summary chips; commit enables "Run Site Feasibility" upstream.
 * Single source of truth: every path exits through the SAME commit payload.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Map as MlMap } from 'maplibre-gl';
import { projectToLocal, unprojectToLngLat, type LocalOrigin } from '../../services/projection';
import { parseBoundaryText } from '../../services/boundaryIO';
import {
  buildPlotPolygonPayload,
  BoundaryError,
  metricsFor,
  presetVertices,
  rectangleVertices,
  ensureCCW,
  validateLiveRing,
  edgeBearingLength,
  type SharedBoundaryState,
} from '../../services/siteBoundary';
import type { Vertex } from '../../services/boundaryIO';
import { azimuthDeg, quadrantBearing, formatBearing } from '../../services/projection';
import {
  snapPoint,
  distanceToFirstVertex,
  nearestEdgeWithin,
  edgeCallouts,
  type SnapMode,
} from '../../services/captureGeometry';
import {
  installCaptureLayers,
  updateCaptureSources,
  clearCaptureSources,
  clearCaptureWhenReady,
  clearDraftOverlays,
  setCaptureCursor,
  setEditCursor,
  setVertexFeatureState,
  pulseBoundaryLock,
  setVertexToLngLat,
  updateFrontageSuggestion,
  updateHoveredEdge,
} from './mapDrawAdapter';
import { TraceHistory } from './traceHistory';
import { hitVertex, hitEdgeMidpoint, edgeMidpoint, dragDelta } from './traceGestures';
import {
  setPulseBridge,
  playVertexPop,
  playVertexShrink,
  playSnapLock,
} from './capturePulse';
import { TraceToolbar, type TraceMode } from './TraceToolbar';
import { PresetMenu, type PresetMenuId } from './PresetMenu';
import { CaptureHUD } from './CaptureHUD';
import { fetchNearestRoad } from '../../services/siteIntelligenceApi';
import {
  suggestFrontageEdge,
  type FrontageSuggestion,
  type NearestRoadResponse,
} from '../../services/siteIntelligence';
import { Icon } from '../Icon';
import { Kbd } from '../../design';

export type CaptureStep = 'locate' | 'trace' | 'frontage' | 'review';

export interface CaptureSheetProps {
  open: boolean;
  step: CaptureStep;
  onStepChange: (step: CaptureStep) => void;
  /** Existing boundary loaded for editing (may be null on first capture). */
  boundary: SharedBoundaryState | null;
  pin: { lat: number; lon: number } | null;
  /** Move the app pin (LOCATE step). */
  onPinChange: (lat: number, lon: number) => void;
  /** Commit the boundary (single funnel — same payload for every path). */
  onCommit: (boundary: SharedBoundaryState) => void;
  onCancel: () => void;
  /** Access the live MapLibre instance (owned by MapCanvas). */
  getMap: () => MlMap | null;
}

const CLOSE_TOLERANCE_M = 6.0;
/** Pointer-to-edge pick band in SCREEN space (converted to meters at the current
 *  zoom), so the highlight follows the cursor, not the zoom level. */
const HOVER_TOLERANCE_PX = 18;
/** Geographic floor for the pick band — never finer than a fingertip click. */
const HOVER_TOLERANCE_MIN_M = 4.0;
/** Zoom ceiling while capturing (matches the map's active-site session cap). */
const SITE_PICK_MAX_ZOOM = 20;

export const CaptureSheet: React.FC<CaptureSheetProps> = ({
  open,
  step,
  onStepChange,
  boundary,
  pin,
  onPinChange: _onPinChange,
  onCommit,
  onCancel,
  getMap,
}) => {
  const [origin, setOrigin] = useState<LocalOrigin>(() => ({
    lat: boundary?.origin.lat ?? pin?.lat ?? 12.9716,
    lon: boundary?.origin.lon ?? pin?.lon ?? 77.5946,
  }));
  const [vertices, setVertices] = useState<Vertex[]>(() => boundary?.vertices ?? []);
  const [cursor, setCursor] = useState<Vertex | null>(null);
  const [snapMode, setSnapMode] = useState<SnapMode>('ORTHOGONAL');
  const [lastBearing, setLastBearing] = useState<number | null>(null);
  const [frontageEdge, setFrontageEdge] = useState<number | null>(boundary?.frontageEdgeIndex ?? null);
  // Overpass-backed frontage suggestion (ASSUMED until the user confirms).
  const [road, setRoad] = useState<NearestRoadResponse | null>(null);
  const [roadLoading, setRoadLoading] = useState<boolean>(false);
  const [roadError, setRoadError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<FrontageSuggestion | null>(null);
  const [frontageConfirmed, setFrontageConfirmed] = useState<boolean>(false);
  /** The frontage that will commit: explicit pick, else the accepted suggestion. */
  const activeFrontage = frontageConfirmed ? frontageEdge : (suggestion?.edgeIndex ?? frontageEdge);
  const [guides, setGuides] = useState<{ a: Vertex; b: Vertex }[]>([]);
  /** FRONTAGE picker: edge under the pointer (null when the pointer is off-ring). */
  const [hoveredEdge, setHoveredEdge] = useState<number | null>(null);
  /** Shown when a frontage click lands away from every edge (no silent pick). */
  const [missHint, setMissHint] = useState<boolean>(false);
  /** Pointer position (map pixels) driving the hover callout badge. */
  const [hoverPx, setHoverPx] = useState<{ x: number; y: number } | null>(null);
  /** Live pointer screen position for CAD dimension HUD during tracing. */
  const [cursorPx, setCursorPx] = useState<{ x: number; y: number } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importText, setImportText] = useState('');
  const [rectW, setRectW] = useState(12);
  const [rectD, setRectD] = useState(18);
  const [rectRot, setRectRot] = useState(0);
  /** Presets dropdown (replaces the single-letter wizard chips). */
  const [presetOpen, setPresetOpen] = useState<boolean>(false);
  // Escape must close the menu before it reaches the wizard's cancel handler.
  const presetOpenRef = useRef(presetOpen);
  presetOpenRef.current = presetOpen;
  const rafRef = useRef<number | null>(null);
  const pendingCursorRef = useRef<Vertex | null>(null);
  /** Cleanup for the context-menu suppressor installed in the map effect. */
  const contextMenuCleanupRef = useRef<(() => void) | null>(null);
  /** True between mousedown/mouseup while dragPan is hijacked for a vertex drag. */
  const dragPanDisabledRef = useRef<boolean>(false);
  const finishTraceRef = useRef<() => void>(() => {});
  const undoVertexRef = useRef<() => void>(() => {});
  const stepRef = useRef(step);
  stepRef.current = step;
  const verticesRef = useRef(vertices);
  verticesRef.current = vertices;
  const lastBearingRef = useRef(lastBearing);
  lastBearingRef.current = lastBearing;
  const snapModeRef = useRef(snapMode);
  snapModeRef.current = snapMode;
  const originRef = useRef(origin);
  originRef.current = origin;
  const cursorRef = useRef(cursor);
  cursorRef.current = cursor;
  const guidesRef = useRef(guides);
  guidesRef.current = guides;
  const wasOpenRef = useRef(open);

  /* ---------- interaction layer ---------- */
  /** Draw = click-to-place with magnetic snapping; Edit = drag/insert/delete. */
  const [traceMode, setTraceMode] = useState<TraceMode>('draw');
  /** Drag gesture EDIT state: index being dragged + its origin for Δ badges. */
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const dragOriginRef = useRef<Vertex | null>(null);
  const [dragDeltaNow, setDragDeltaNow] = useState<{ dx: number; dy: number } | null>(null);
  /**
   * The ring as it exists mid-drag (dragged vertex at the pointer). This drives
   * the live HUD area/perimeter/validity while the handle is moving — the map
   * canvas draws the same ring via editLiveRing, so HUD and geometry agree to
   * the frame, without mutating the authoritative ring until mouseup.
   */
  const [dragPreview, setDragPreview] = useState<Vertex[] | null>(null);
  /** Revealed mid-edge '+' handle: edge index + position. */
  const [insertEdge, setInsertEdge] = useState<number | null>(null);
  const [insertPos, setInsertPos] = useState<Vertex | null>(null);
  /** Undo/redo stack (pure TraceHistory). */
  const historyRef = useRef<TraceHistory>(new TraceHistory());
  const [historyTick, setHistoryTick] = useState(0);
  /** Screen-reader announcements (Vertex placed at 12.4 meters North…). */
  const [announce, setAnnounce] = useState<string>('');
  /** Coach-mark progress + shift-snap state (drives HUD). */
  const [coachProgress, setCoachProgress] = useState<Set<'step1' | 'step2' | 'step3'>>(new Set(['step1']));
  const shiftHeldRef = useRef(false);
  /** The snapped cursor flipped true/false between frames (snap lock effect triggers). */
  const snapLockedRef = useRef<boolean>(false);
  // Listener-closure mirrors (the map event effect never re-subscribes on
  // mode changes — refs keep the handlers authoritative).
  const traceModeRef = useRef<TraceMode>('draw');
  traceModeRef.current = traceMode;
  const dragIdxRef = useRef<number | null>(null);
  dragIdxRef.current = dragIdx;
  const insertEdgeRef = useRef<number | null>(null);
  insertEdgeRef.current = insertEdge;
  const insertPosRef = useRef<Vertex | null>(null);
  insertPosRef.current = insertPos;
  const coachProgressRef = useRef<Set<'step1' | 'step2' | 'step3'>>(coachProgress);
  coachProgressRef.current = coachProgress;
  // Shift-forced ORTHOGONAL snap bookkeeping (release restores prior mode).
  const shiftForcedSnapRef = useRef<boolean>(false);
  const snapPreShiftRef = useRef<SnapMode>('ORTHOGONAL');
  // Undo/redo reachable from the map-event closure (ref mirrors).
  const applyUndoRef = useRef<() => void>(() => {});
  const applyRedoRef = useRef<() => void>(() => {});

  /** Dismiss a coach step — the design primitive writes localStorage; locally
   * we only drop the step from the progress set so the next can appear. */
  const dismissCoach = (step: 'step1' | 'step2' | 'step3'): void => {
    setCoachProgress((prev) => {
      const next = new Set(prev);
      next.delete(step);
      return next;
    });
  };

  /* ---------- pulse bridge: local meters -> WGS84 for one-shot pulses ---------- */
  useEffect(() => {
    setPulseBridge({
      toLngLat: (v: Vertex): [number, number] => {
        const ll = unprojectToLngLat(v, originRef.current);
        return [ll.lon, ll.lat];
      },
    });
  }, []);

  /* ---------- origin + projection transform ---------- */
  useEffect(() => {
    if (!open) return;
    setVertexToLngLat((v: Vertex): [number, number] => {
      const ll = unprojectToLngLat(v, origin);
      return [ll.lon, ll.lat];
    });
  }, [open, origin]);

  // Sync origin and state when capture opens (fresh pin or boundary)
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      const nextOrigin: LocalOrigin = {
        lat: boundary?.origin.lat ?? pin?.lat ?? 12.9716,
        lon: boundary?.origin.lon ?? pin?.lon ?? 77.5946,
      };
      setOrigin(nextOrigin);
      originRef.current = nextOrigin;
      setVertexToLngLat((v: Vertex): [number, number] => {
        const ll = unprojectToLngLat(v, nextOrigin);
        return [ll.lon, ll.lat];
      });
      const initialVs = boundary?.vertices ?? [];
      setVertices(initialVs);
      verticesRef.current = initialVs;
      setCursor(null);
      cursorRef.current = null;
      setGuides([]);
      guidesRef.current = [];
      setLastBearing(null);
      lastBearingRef.current = null;
      setFrontageEdge(boundary?.frontageEdgeIndex ?? null);
      setFrontageConfirmed(false);
      setSuggestion(null);
      setMissHint(false);
      setHoveredEdge(null);
      setHoverPx(null);
    }
    wasOpenRef.current = open;
  }, [open, boundary, pin]);

  // A fresh ring follows the pin. While nothing is drawn yet, placing the pin
  // re-anchors the tangent plane, so the boundary that gets committed carries
  // the pin the user actually placed as its origin - never this wizard's
  // fallback point (which the app would then show as the site coordinates).
  // Once a vertex exists the ring is a real drawn shape and stays put.
  useEffect(() => {
    if (!open || !pin) return;
    if (vertices.length > 0) return;
    if (origin.lat === pin.lat && origin.lon === pin.lon) return;
    const next: LocalOrigin = { lat: pin.lat, lon: pin.lon };
    setOrigin(next);
    originRef.current = next;
  }, [open, pin, vertices.length, origin.lat, origin.lon]);

  /* ---------- map lifecycle: layers, cursor, listeners ---------- */
  useEffect(() => {
    if (!open) return;
    const map = getMap();
    if (!map) return;
    setCaptureCursor(map, step === 'trace' || step === 'frontage');
    if (step === 'trace' || step === 'frontage') {
      try {
        map.doubleClickZoom.disable();
      } catch {}
    }

    // Install now (the adapter gates on a MOUNTED style, not on
    // isStyleLoaded — which is false while any basemap tile is in flight and
    // would delay the first trace paint until the basemap settled). A style
    // swap wipes the sources and is re-installed by the style.load handler
    // registered below.
    const setupLayersAndSources = (): void => {
      installCaptureLayers(map);
      updateCaptureSources(map, {
        ring: verticesRef.current,
        cursor: stepRef.current === 'trace' ? cursorRef.current : null,
        guides: stepRef.current === 'trace' ? guidesRef.current : [],
        isClosed: stepRef.current !== 'trace',
      });
    };
    setupLayersAndSources();

    const toLocal = (lngLat: { lng: number; lat: number }): Vertex =>
      projectToLocal(lngLat.lat, lngLat.lng, originRef.current);

    // The dashed live edge + magnetic guides are a TRACE-step affordance only.
    // Once the ring is closed (or the wizard moved to FRONTAGE/REVIEW) a line
    // tracking the pointer is meaningless geometry and reads as a stray dashed
    // outline left over the traced boundary - never schedule it then.
    const scheduleCursor = (v: Vertex): void => {
      if (stepRef.current !== 'trace') return;
      pendingCursorRef.current = v;
      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        const next = pendingCursorRef.current;
        if (!next || stepRef.current !== 'trace') return;
        const currentVertices = verticesRef.current;
        const anchor = currentVertices[currentVertices.length - 1] ?? null;
        const canClose = currentVertices.length >= 3;
        const distToFirst = canClose ? distanceToFirstVertex(next, currentVertices[0]) : Infinity;
        const isMagneticClose = canClose && distToFirst <= CLOSE_TOLERANCE_M;

        let snappedPoint: Vertex;
        let guides: { a: Vertex; b: Vertex }[];
        let snapEngaged = false;

        if (isMagneticClose) {
          snappedPoint = currentVertices[0];
          guides = [];
          snapEngaged = true;
        } else {
          const snap = snapPoint(next, anchor, lastBearingRef.current, snapModeRef.current);
          snappedPoint = snap.point;
          guides = snap.guides;
          snapEngaged = snap.snapped && guides.length > 0;
        }

        cursorRef.current = snappedPoint;
        guidesRef.current = guides;
        setCursor(snappedPoint);
        setGuides(guides);
        // Snap "lock" animation: engage on the ACTIVE→locked transition (50ms).
        if (snapEngaged && !snapLockedRef.current) {
          playSnapLock(map, snappedPoint);
        }
        snapLockedRef.current = snapEngaged;
        // Coach step 2 also earns on a real snap engagement (Shift OR guide).
        if (snapEngaged && !coachProgressRef.current.has('step2')) {
          setCoachProgress((prev) => new Set(prev).add('step2'));
        }
        updateCaptureSources(map, {
          ring: currentVertices,
          cursor: snappedPoint,
          guides,
          isClosed: isMagneticClose,
        });
      });
    };

    /** Pick band in meters for the current zoom: HOVER_TOLERANCE_PX pixels. */
    const hoverToleranceM = (point: { x: number; y: number } | undefined, local: Vertex): number => {
      if (!point) return HOVER_TOLERANCE_MIN_M;
      try {
        const probe = map.unproject([point.x + HOVER_TOLERANCE_PX, point.y]);
        const probeLocal = projectToLocal(probe.lat, probe.lng, originRef.current);
        return Math.max(
          HOVER_TOLERANCE_MIN_M,
          Math.hypot(probeLocal.x - local.x, probeLocal.y - local.y)
        );
      } catch {
        return HOVER_TOLERANCE_MIN_M;
      }
    };

    const onMouseMove = (e: any): void => {
      if (e.point) {
        setCursorPx({ x: e.point.x, y: e.point.y });
      }
      const currentVertices = verticesRef.current;
      const local = toLocal(e.lngLat);

      // ===== EDIT mode: contextual cursor + drag + '+' handle reveal =====
      if (stepRef.current === 'trace' && traceModeRef.current === 'edit' && currentVertices.length >= 3) {
        // Active drag: move the vertex under the pointer (rAF-throttled for 60fps).
        const di = dragIdxRef.current;
        if (di !== null) {
          pendingCursorRef.current = local;
          if (rafRef.current !== null) return;
          rafRef.current = requestAnimationFrame(() => {
            rafRef.current = null;
            const v = pendingCursorRef.current;
            if (!v || stepRef.current !== 'trace' || dragIdxRef.current === null) return;
            const ring = verticesRef.current;
            const next = ring.map((p, i) => (i === dragIdxRef.current ? v : p));
            const includeClose = stepRef.current !== 'trace';
            // Live HUD + map preview share one ring: the canvas draws editLiveRing
            // and the HUD reads dragPreview, so both move together each frame.
            setDragDeltaNow(dragDelta(dragOriginRef.current, v));
            setDragPreview(next);
            updateCaptureSources(map, {
              ring: next,
              cursor: null,
              guides: [],
              isClosed: includeClose,
              editLiveRing: next,
              invalid: next.length >= 3 ? !metricsFor(next).valid : false,
            });
          });
          return;
        }

        // Hover probes: vertex handle first, then mid-edge insertion point.
        const vHit = hitVertex(currentVertices, local, hoverToleranceM(e.point, local));
        if (vHit !== null) {
          setEditCursor(map, 'move');
          setInsertEdge(null);
          setInsertPos(null);
          setVertexFeatureState(map, 'hover', vHit);
          updateCaptureSources(map, { ring: currentVertices, cursor: null, guides: [], isClosed: true, insertHandle: null });
          return;
        }
        const eHit = hitEdgeMidpoint(currentVertices, local, hoverToleranceM(e.point, local), 2);
        if (eHit !== null) {
          setEditCursor(map, 'copy');
          const mid = edgeMidpoint(currentVertices, eHit);
          setInsertEdge(eHit);
          setInsertPos(mid);
          setVertexFeatureState(map, 'hover', null);
          updateCaptureSources(map, { ring: currentVertices, cursor: null, guides: [], isClosed: true, insertHandle: mid });
          return;
        }
        setEditCursor(map, 'crosshair');
        setInsertEdge(null);
        setInsertPos(null);
        setVertexFeatureState(map, 'hover', null);
        updateCaptureSources(map, { ring: currentVertices, cursor: null, guides: [], isClosed: true, insertHandle: null });
        return;
      }

      if (stepRef.current === 'trace') {
        scheduleCursor(local);
        return;
      }
      // FRONTAGE: highlight the edge under the pointer so the pick is aimed.
      if (stepRef.current !== 'frontage' || currentVertices.length < 3) return;
      const idx = nearestEdgeWithin(currentVertices, local, hoverToleranceM(e.point, local));
      setHoveredEdge((prev) => (prev === idx ? prev : idx));
      updateHoveredEdge(map, currentVertices, idx);
      setHoverPx(idx !== null && e.point ? { x: e.point.x, y: e.point.y } : null);
      // Aiming at an edge again retires the "click an edge" hint.
      if (idx !== null) setMissHint(false);
    };

    const clearHover = (): void => {
      setHoveredEdge(null);
      setHoverPx(null);
      updateHoveredEdge(map, verticesRef.current, null);
    };

    const onMouseOut = (): void => {
      clearHover();
      setCursorPx(null);
      if (stepRef.current === 'trace') {
        cursorRef.current = null;
        setCursor(null);
        setGuides([]);
        updateCaptureSources(map, {
          ring: verticesRef.current,
          cursor: null,
          guides: [],
          isClosed: false,
        });
      }
    };

    const onClick = (e: any): void => {
      const currentVertices = verticesRef.current;
      const local = toLocal(e.lngLat);
      if (stepRef.current === 'trace') {
        // ===== EDIT mode clicks: drag-commit, insert, delete =====
        if (traceModeRef.current === 'edit' && currentVertices.length >= 3) {
          const originalEvent: any = e.originalEvent ?? {};
          const ctrlCmd = Boolean(originalEvent.ctrlKey || originalEvent.metaKey || originalEvent.button === 2);
          const vHit = hitVertex(currentVertices, local, hoverToleranceM(e.point, local));
          if (vHit !== null) {
            if (ctrlCmd || originalEvent.button === 2) {
              // DELETE (Cmd/Ctrl+Click or right-click): shrink + remove.
              if (currentVertices.length <= 3) return; // ring floor
              pushHistory();
              playVertexShrink(map, currentVertices[vHit]);
              const next = currentVertices.filter((_, i) => i !== vHit);
              verticesRef.current = next;
              setVertices(next);
              setAnnounce(`Vertex deleted, ${next.length} vertices remain`);
              updateCaptureSources(map, { ring: next, cursor: null, guides: [], isClosed: true, invalid: !metricsFor(next).valid });
              return;
            }
            // End a pending drag (no-op commit) — nothing else to do on click.
            return;
          }
          const eHit = hitEdgeMidpoint(currentVertices, local, hoverToleranceM(e.point, local), 2);
          if (eHit !== null) {
            // INSERT mid-edge vertex with the same "pop" as placement.
            pushHistory();
            const mid = edgeMidpoint(currentVertices, eHit);
            playVertexPop(map, mid);
            const next = currentVertices.slice();
            next.splice(eHit + 1, 0, mid);
            verticesRef.current = next;
            setVertices(next);
            setInsertEdge(null);
            setInsertPos(null);
            setAnnounce(`Vertex inserted, ${next.length} vertices`);
            updateCaptureSources(map, { ring: next, cursor: null, guides: [], isClosed: true, invalid: !metricsFor(next).valid });
            return;
          }
          return;
        }

        // ===== DRAW mode: place / close =====
        // Close if near first vertex or magnetically snapped to first vertex
        const isNearFirst =
          currentVertices.length >= 3 &&
          (distanceToFirstVertex(local, currentVertices[0]) <= CLOSE_TOLERANCE_M ||
            (cursorRef.current !== null && distanceToFirstVertex(cursorRef.current, currentVertices[0]) < 0.1));
        if (isNearFirst) {
          // Completion "lock": pulse the whole polygon boundary.
          pulseBoundaryLock(map);
          for (let i = 0; i < currentVertices.length; i++) {
            setTimeout(() => playVertexPop(map, currentVertices[i]), i * 24);
          }
          finishTraceRef.current();
          return;
        }
        const anchor = currentVertices[currentVertices.length - 1] ?? null;
        const snap = snapPoint(local, anchor, lastBearingRef.current, snapModeRef.current);
        // Suppress degenerate duplicate clicks within 0.5m of the anchor
        if (anchor && Math.hypot(snap.point.x - anchor.x, snap.point.y - anchor.y) < 0.5) {
          return;
        }
        pushHistory();
        playVertexPop(map, snap.point);
        const nextRing = [...currentVertices, snap.point];
        verticesRef.current = nextRing;
        lastBearingRef.current = anchor ? snap.azimuth : null;
        cursorRef.current = snap.point;
        setVertices(nextRing);
        setLastBearing(anchor ? snap.azimuth : null);
        // Coach progress: 2nd click earns step2, 4th click earns step3.
        setCoachProgress((prev) => {
          const next = new Set(prev);
          if (nextRing.length >= 2) next.add('step2');
          if (nextRing.length >= 4) next.add('step3');
          return next;
        });
        // Accessibility: "Vertex placed at 12.4 meters North".
        const bearingLabel = formatBearing(snap.azimuth);
        setAnnounce(`Vertex placed at ${snap.lengthM.toFixed(1)} meters ${bearingLabel}`);
        updateCaptureSources(map, { ring: nextRing, cursor: snap.point, guides: [], isClosed: false });
      } else if (stepRef.current === 'frontage') {
        if (currentVertices.length >= 3) {
          // Precision pick: only the edge under the pointer (within the band).
          const idx = nearestEdgeWithin(currentVertices, local, hoverToleranceM(e.point, local));
          if (idx === null) {
            setMissHint(true);
            return;
          }
          setMissHint(false);
          setFrontageEdge(idx);
          setFrontageConfirmed(true);
        }
      }
    };

    const onDblClick = (e: any): void => {
      if (e && e.preventDefault) e.preventDefault();
      if (stepRef.current === 'trace' && verticesRef.current.length >= 3) {
        // Completion "lock" pulse, same as the first-vertex close.
        pulseBoundaryLock(map);              finishTraceRef.current();
            }};

    /** Contextual drag START (EDIT mode): mousedown near a vertex handle. */
    const onMouseDown = (e: any): void => {
      if (stepRef.current !== 'trace' || traceModeRef.current !== 'edit') return;
      const currentVertices = verticesRef.current;
      if (currentVertices.length < 3) return;
      const local = toLocal(e.lngLat);
      const vHit = hitVertex(currentVertices, local, hoverToleranceM(e.point, local));
      if (vHit === null) return;
      // Right button starts a DELETE, not a drag.
      if (e.originalEvent?.button === 2) return;
      // MapLibre's dragPan treats this mousedown as the
      // start of a camera pan, so the vertex never follows the pointer and
      // mouseup lands wherever the camera rolled. From here until mouseup the
      // gesture belongs to the vertex, not the camera.
      try { map.dragPan.disable(); } catch {}
      dragPanDisabledRef.current = true;
      dragIdxRef.current = vHit;
      setDragIdx(vHit);
      dragOriginRef.current = currentVertices[vHit];
      setDragDeltaNow({ dx: 0, dy: 0 });
      setVertexFeatureState(map, 'drag', vHit);
      setEditCursor(map, 'grabbing');
    };

    /** Drag END: commit the dragged position into the authoritative ring. */
    const onMouseUp = (e: any): void => {
      const di = dragIdxRef.current;
      // Restore camera panning unconditionally — even on a spurious mouseup.
      if (dragPanDisabledRef.current) {
        dragPanDisabledRef.current = false;
        try { map.dragPan.enable(); } catch {}
      }
      if (di === null) return;
      dragIdxRef.current = null;
      setDragIdx(null);
      setVertexFeatureState(map, 'drag', null);
      setEditCursor(map, 'move');
      const local = toLocal(e.lngLat);
      const ring = verticesRef.current;
      const next = ring.map((p, i) => (i === di ? local : p));
      pushHistory();
      verticesRef.current = next;
      setVertices(next);

      setDragPreview(null);
      setDragDeltaNow(null);
      const delta = dragDelta(dragOriginRef.current, local);
      if (delta) {
        setAnnounce(
          `Vertex moved ${Math.abs(delta.dx).toFixed(1)} meters ${delta.dx >= 0 ? 'East' : 'West'}, ${Math.abs(delta.dy).toFixed(1)} meters ${delta.dy >= 0 ? 'North' : 'South'}`
        );
      }
      updateCaptureSources(map, {
        ring: next,
        cursor: null,
        guides: [],
        isClosed: true,
        editLiveRing: null,
        invalid: !metricsFor(next).valid,
      });
    };

    const onKey = (e: KeyboardEvent): void => {
      const target = e.target as HTMLElement | null;
      const isInput =
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          (target as any).isContentEditable);

      if (e.key === 'Escape') {
        e.stopPropagation();
        // The wizard's keydown listener is on `window` (capture) and therefore
        // runs BEFORE the preset menu's document-level handler — so without
        // this guard, dismissing the dropdown would cancel the whole capture.
        // The menu owns Escape while it is open.
        if (presetOpenRef.current) {
          setPresetOpen(false);
          return;
        }
        // Wipe every draft overlay the instant Esc is pressed, not
        // just when the effect re-subscribes (which can be style-gated).
        const m0 = getMap();
        if (m0) clearDraftOverlays(m0);
        onCancel();
        return;
      }

      if (isInput) return;

      if (stepRef.current === 'trace') {
        // Shift momentarily forces ORTHOGONAL snapping (coach step 2 hint).
        if (e.key === 'Shift') {
          shiftHeldRef.current = true;
          if (traceModeRef.current === 'draw') {
            if (!shiftForcedSnapRef.current) {
              snapPreShiftRef.current = snapModeRef.current;
              shiftForcedSnapRef.current = true;
            }
            if (snapModeRef.current !== 'ORTHOGONAL') {
              setSnapMode('ORTHOGONAL');
              snapModeRef.current = 'ORTHOGONAL';
              if (pendingCursorRef.current) scheduleCursor(pendingCursorRef.current);
            }
          }
        }

        // D / E tool switching (keyboard a11y gate).
        if (
          (e.key === 'd' || e.key === 'D') &&
          !e.ctrlKey &&
          !e.metaKey &&
          !e.altKey
        ) {
          e.preventDefault();
          e.stopPropagation();
          setTraceMode('draw');
          return;
        }
        if (
          (e.key === 'e' || e.key === 'E') &&
          !e.ctrlKey &&
          !e.metaKey &&
          !e.altKey &&
          verticesRef.current.length >= 3
        ) {
          e.preventDefault();
          e.stopPropagation();
          setTraceMode('edit');
          return;
        }

        // Backspace, Delete, or Ctrl+Z / Cmd+Z to undo vertex
        if (e.key === 'Backspace' || e.key === 'Delete') {
          e.preventDefault();
          e.stopPropagation();
          undoVertexRef.current();
          return;
        }
        if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
          e.preventDefault();
          e.stopPropagation();
          if (e.shiftKey) {
            applyRedoRef.current();
          } else {
            applyUndoRef.current();
          }
          return;
        }

        // Enter or Space to finish/close tracing
        if (e.key === 'Enter' || e.key === ' ') {
          if (verticesRef.current.length >= 3) {
            e.preventDefault();
            e.stopPropagation();
            pulseBoundaryLock(map);
            finishTraceRef.current();
            return;
          }
        }

        // Tab to cycle snap mode
        if (e.key === 'Tab') {
          e.preventDefault();
          e.stopPropagation();
          const modes: SnapMode[] = ['ORTHOGONAL', 'PARALLEL', 'FREE'];
          const currentIndex = modes.indexOf(snapModeRef.current);
          const nextMode = modes[(currentIndex + 1) % modes.length];
          setSnapMode(nextMode);
          snapModeRef.current = nextMode;
          if (pendingCursorRef.current) {
            scheduleCursor(pendingCursorRef.current);
          }
        }
      }
    };

    const onKeyUp = (e: KeyboardEvent): void => {
      if (e.key === 'Shift') {
        shiftHeldRef.current = false;
        // Restore the pre-shift snap mode (only when Shift forced it).
        if (stepRef.current === 'trace' && traceModeRef.current === 'draw') {
          // Tab is the explicit mode owner; after Shift is released we return
          // to PARALLEL (the pre-shift workflow default) only if it was forced.
          if (snapModeRef.current === 'ORTHOGONAL' && shiftForcedSnapRef.current) {
            setSnapMode(snapPreShiftRef.current);
            snapModeRef.current = snapPreShiftRef.current;
            shiftForcedSnapRef.current = false;
          }
        }
      }
    };

    const onStyleLoad = (): void => {
      installCaptureLayers(map);
      updateCaptureSources(map, {
        ring: verticesRef.current,
        cursor: stepRef.current === 'trace' ? cursorRef.current : null,
        guides: stepRef.current === 'trace' ? guidesRef.current : [],
        isClosed: stepRef.current !== 'trace',
      });
    };

    map.on('mousemove', onMouseMove);
    map.on('click', onClick);
    map.on('dblclick', onDblClick);
    map.on('mouseout', onMouseOut);
    map.on('mousedown', onMouseDown);
    map.on('mouseup', onMouseUp);
    // Native context menu handler: right-click DELETE on a vertex handle:
    // MapLibre never surfaces button=2 as 'contextmenu' on its
    // own; without this the browser menu opens and nothing is deleted.
    const onContextMenu = (e: any): void => {
      if (stepRef.current !== 'trace' || traceModeRef.current !== 'edit') return;
      e?.preventDefault?.();
      const currentVertices = verticesRef.current;
      if (currentVertices.length < 3) return;
      const local = toLocal(e.lngLat);
      const vHit = hitVertex(currentVertices, local, hoverToleranceM(e.point, local));
      if (vHit === null || currentVertices.length <= 3) return; // ring floor
      pushHistory();
      playVertexShrink(map, currentVertices[vHit]);
      const next = currentVertices.filter((_, i) => i !== vHit);
      verticesRef.current = next;
      setVertices(next);
      setAnnounce(`Vertex deleted, ${next.length} vertices remain`);
      updateCaptureSources(map, { ring: next, cursor: null, guides: [], isClosed: true, invalid: !metricsFor(next).valid });
    };
    if (typeof map.on !== 'function') return;
    try {
      const canvas = map.getCanvas();
      // Suppress the browser menu so right-click reaches the map events.
      canvas.addEventListener('contextmenu', (ev: Event) => ev.preventDefault());
      contextMenuCleanupRef.current = () => {
        canvas.removeEventListener('contextmenu', (ev: Event) => ev.preventDefault());
      };
    } catch {}
    map.on('contextmenu', onContextMenu);
    // Camera moves invalidate a pointer-relative hover (and its badge).
    map.on('movestart', clearHover);
    map.on('zoomstart', clearHover);
    map.on('style.load', onStyleLoad);
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('keyup', onKeyUp, true);

    // Leaving the picker step must never leave a highlighted edge behind.
    if (stepRef.current !== 'frontage') clearHover();

    return () => {
      map.off('mousemove', onMouseMove);
      map.off('click', onClick);
      map.off('dblclick', onDblClick);
      map.off('mouseout', onMouseOut);
      map.off('mousedown', onMouseDown);
      map.off('mouseup', onMouseUp);
      map.off('contextmenu', onContextMenu);
      if (contextMenuCleanupRef.current) {
        contextMenuCleanupRef.current();
        contextMenuCleanupRef.current = null;
      }
      // Destroy every draft overlay when the wizard
      // closes. Unless the style is mid-reload, this runs synchronously.
      clearCaptureWhenReady(map);
      map.off('movestart', clearHover);
      map.off('zoomstart', clearHover);
      map.off('style.load', onStyleLoad);
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('keyup', onKeyUp, true);
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      setCaptureCursor(map, false);
      try {
        map.doubleClickZoom.enable();
      } catch {}
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, step, getMap, onCancel]);

  // Clean sources when capture sheet closes. clearCaptureWhenReady retries
  // until the style has the capture sources installed, so a close that lands
  // during a tile/style refresh still wipes every draft overlay.
  useEffect(() => {
    if (!open) clearCaptureWhenReady(getMap());
  }, [open, getMap]);

  // Recovery re-apply on a genuine style swap only (sources recreated empty).
  // Deliberately NOT hooked to 'idle': an idle re-apply would clobber the
  // imperative hover affordances (mid-edge insert handle, drag ring) that are
  // set outside React state. A style swap always fires style.load, which is the
  // only event that actually needs the ring re-pushed.
  useEffect(() => {
    const map = getMap();
    if (!map || !open) return;
    const reapply = (): void => {
      const tracing = stepRef.current === 'trace';
      updateCaptureSources(map, {
        ring: verticesRef.current,
        cursor: tracing ? cursorRef.current : null,
        guides: tracing ? guidesRef.current : [],
        isClosed: stepRef.current !== 'trace',
        insertHandle: tracing && traceModeRef.current === 'edit' ? insertPosRef.current : null,
      });
    };
    map.on('style.load', reapply);
    return () => {
      map.off('style.load', reapply);
    };
  }, [open, getMap]);

  /* ---------- render loop side effects ---------- */
  useEffect(() => {
    const map = getMap();
    if (!map || !open) return;
    // Guard the single render path: outside the TRACE step the live edge and
    // guides are always empty, whatever stale cursor/guides state remains.
    const tracing = step === 'trace';
    const isClosed = !tracing || (boundary !== null && vertices === boundary.vertices);
    updateCaptureSources(map, {
      ring: vertices,
      cursor: tracing ? cursor : null,
      guides: tracing ? guides : [],
      isClosed,
    });
  }, [open, step, vertices, cursor, guides, getMap, boundary]);

  /* ---------- Road telemetry + frontage suggestion ---------- */
  // Debounced (400 ms) /api/nearest-road fetch while the frontage step is
  // open. Honors AbortController; a failure degrades to manual selection and
  // never fabricates a bearing (Amendment 1).
  useEffect(() => {
    if (!open || step !== 'frontage' || !pin) return;
    const controller = new AbortController();
    setRoadLoading(true);
    setRoadError(null);
    const timer = setTimeout(() => {
      fetchNearestRoad(pin.lat, pin.lon, controller.signal)
        .then((resp) => {
          setRoad(resp);
          if (resp.warning) setRoadError(resp.warning);
        })
        .catch((e: unknown) => {
          if (controller.signal.aborted) return;
          setRoadError(e instanceof Error ? e.message : 'Road lookup unavailable.');
          setRoad(null);
        })
        .finally(() => {
          if (!controller.signal.aborted) setRoadLoading(false);
        });
    }, 400);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [open, step, pin]);

  // Map the road bearing onto the current ring; clear the suggestion when
  // the user picks a different edge (their choice wins over the heuristic).
  useEffect(() => {
    if (!open || step !== 'frontage') {
      const map = getMap();
      if (map) updateFrontageSuggestion(map, vertices, null);
      return;
    }
    if (frontageConfirmed) return;
    const bearing = road?.found ? (road.road?.bearing_degrees ?? null) : null;
    setSuggestion(bearing === null ? null : suggestFrontageEdge(vertices, bearing));
  }, [open, step, road, vertices, frontageConfirmed, getMap]);

  // Reflect the (confirmed or suggested) frontage on the map.
  useEffect(() => {
    if (!open || step !== 'frontage') return;
    const map = getMap();
    if (!map) return;
    const active = frontageConfirmed ? frontageEdge : (suggestion?.edgeIndex ?? frontageEdge);
    updateFrontageSuggestion(map, vertices, active);
  }, [open, step, vertices, suggestion, frontageEdge, frontageConfirmed, getMap]);

  /**
   * Frame the finished ring: the frontage picker needs the plot on screen at a
   * workable scale (the map itself caps at z18). Padding keeps the plot clear of
   * the sidebar, the results panel and this sheet.
   */
  const frameRing = useCallback(
    (ring: Vertex[]): void => {
      if (ring.length < 3) return;
      const map = getMap();
      if (!map) return;
      const pts = ring.map((v) => unprojectToLngLat(v, originRef.current));
      const lngs = pts.map((p) => p.lon);
      const lats = pts.map((p) => p.lat);
      const box = map.getContainer();
      const w = box.clientWidth || 1;
      const h = box.clientHeight || 1;
      try {
        map.fitBounds(
          [
            [Math.min(...lngs), Math.min(...lats)],
            [Math.max(...lngs), Math.max(...lats)],
          ],
          {
            padding: {
              left: Math.min(380, w * 0.3),
              right: Math.min(400, w * 0.32),
              top: Math.min(120, h * 0.14),
              bottom: Math.min(320, h * 0.36),
            },
            maxZoom: SITE_PICK_MAX_ZOOM,
            duration: 450,
          }
        );
      } catch {
        // Non-fatal: a failed fit only means the user keeps their current view.
      }
    },
    [getMap]
  );

  /* ---------- trace helpers ---------- */
  const finishTrace = useCallback((): void => {
    const currentVertices = verticesRef.current;
    if (currentVertices.length < 3) return;
    setHoveredEdge(null);
    setCursorPx(null);
    const _m = getMap();
    if (_m) updateHoveredEdge(_m, currentVertices, null);
    // The rubber-band edge, guides, ghost and close halo are trace
    // affordances — destroy them the moment the ring closes, before the
    // (style-gated) render-effect can ever repaint them.
    if (_m) clearDraftOverlays(_m);
    // Drop the in-flight live edge immediately (a queued rAF frame would
    // otherwise repaint the dashed line after the ring closes).
    pendingCursorRef.current = null;
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    setCursor(null);
    cursorRef.current = null;
    setGuides([]);
    guidesRef.current = [];
    resetFrontageChoice();
    const map = getMap();
    if (map) updateCaptureSources(map, { ring: currentVertices, cursor: null, guides: [], isClosed: true });
    frameRing(currentVertices);
    onStepChange('frontage');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onStepChange, getMap, frameRing]);

  const resetFrontageChoice = (): void => {
    setFrontageEdge(boundary?.frontageEdgeIndex ?? null);
    setFrontageConfirmed(false);
    setSuggestion(null);
    setMissHint(false);
  };

  const undoVertex = useCallback((): void => {
    setVertices((prev) => {
      if (prev.length === 0) return prev;
      const next = prev.slice(0, -1);
      verticesRef.current = next;
      const prevAzimuth =
        next.length >= 2 ? azimuthDeg(next[next.length - 2], next[next.length - 1]) : null;
      setLastBearing(prevAzimuth);
      lastBearingRef.current = prevAzimuth;
      const map = getMap();
      if (map) {
        updateCaptureSources(map, {
          ring: next,
          cursor: cursorRef.current,
          guides: [],
          isClosed: false,
        });
      }
      return next;
    });
  }, [getMap]);

  finishTraceRef.current = finishTrace;
  undoVertexRef.current = undoVertex;

  /* ---------- premium: history-aware undo/redo (Ctrl+Z / Ctrl+Shift+Z) ---------- */
  const applyUndo = useCallback((): void => {
    const current = verticesRef.current;
    const prev = historyRef.current.undo(current);
    if (!prev) return;
    verticesRef.current = prev;
    setVertices(prev);
    if (prev.length >= 2) {
      const az = azimuthDeg(prev[prev.length - 2], prev[prev.length - 1]);
      lastBearingRef.current = az;
      setLastBearing(az);
    } else {
      setLastBearing(null);
      lastBearingRef.current = null;
    }
    // Leaving edit-mode drag state on undo (authoritative ring changed).
    setDragIdx(null);
    dragOriginRef.current = null;
    setDragDeltaNow(null);
    setDragPreview(null);
    
    setHistoryTick((t) => t + 1);
    const map = getMap();
    if (map) {
      updateCaptureSources(map, {
        ring: prev,
        cursor: stepRef.current === 'trace' ? cursorRef.current : null,
        guides: stepRef.current === 'trace' ? guidesRef.current : [],
        isClosed: stepRef.current !== 'trace',
        invalid: !metricsFor(prev).valid,
      });
    }
  }, [getMap]);

  const applyRedo = useCallback((): void => {
    const current = verticesRef.current;
    const next = historyRef.current.redo(current);
    if (!next) return;
    verticesRef.current = next;
    setVertices(next);
    if (next.length >= 2) {
      const az = azimuthDeg(next[next.length - 2], next[next.length - 1]);
      lastBearingRef.current = az;
      setLastBearing(az);
    } else {
      setLastBearing(null);
      lastBearingRef.current = null;
    }
    setHistoryTick((t) => t + 1);
    const map = getMap();
    if (map) {
      updateCaptureSources(map, {
        ring: next,
        cursor: stepRef.current === 'trace' ? cursorRef.current : null,
        guides: stepRef.current === 'trace' ? guidesRef.current : [],
        isClosed: stepRef.current !== 'trace',
        invalid: !metricsFor(next).valid,
      });
    }
  }, [getMap]);

  /** Record a history snapshot before ANY accepted ring mutation. */
  const pushHistory = useCallback((): void => {
    historyRef.current.push(verticesRef.current);
    setHistoryTick((t) => t + 1);
  }, []);

  applyUndoRef.current = applyUndo;
  applyRedoRef.current = applyRedo;

  const resetTrace = (): void => {
    setTraceMode('draw');
    historyRef.current.clear();
    setHistoryTick((t) => t + 1);
    verticesRef.current = [];
    setLastBearing(null);
    lastBearingRef.current = null;
    setCursor(null);
    cursorRef.current = null;
    setCursorPx(null);
    setGuides([]);
    guidesRef.current = [];
    setDragIdx(null);
    dragIdxRef.current = null;
    setDragPreview(null);
    setDragDeltaNow(null);
    resetFrontageChoice();
    setAnnounce('Trace cleared');
    const map = getMap();
    if (map) clearCaptureSources(map);
  };

  /* ---------- quick paths (same funnel on commit) ---------- */
  /** Quick paths jump straight to FRONTAGE: clear the trace-only state first. */
  const dropTraceCursor = (): void => {
    setHoveredEdge(null);
    setCursorPx(null);
    const _hoverMap = getMap();
    if (_hoverMap) updateHoveredEdge(_hoverMap, [], null);
    pendingCursorRef.current = null;
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    setCursor(null);
    cursorRef.current = null;
    setGuides([]);
    guidesRef.current = [];
  };

  /**
   * Presets from the toolbar dropdown — seeds a parametric polygon
   * CENTERED ON THE PIN using the wizard's dims (width × depth × rotation),
   * then switches to EDIT mode (stays on the trace step so the seed is
   * immediately draggable/undoable). rect + l_shape honor the inputs; the
   * other presets scale from the longer dimension for a sane footprint.
   */
  const applyToolbarPreset = (id: PresetMenuId): void => {
    const center: Vertex = { x: 0, y: 0 };
    const footprint = Math.max(rectW, rectD, 12);
    const vs =
      id === 'rect'
        ? rectangleVertices({ widthM: rectW, depthM: rectD, rotationDeg: rectRot }, center)
        : presetVertices(id, footprint, center);
    pushHistory();
    setVertices(vs);
    verticesRef.current = vs;
    dropTraceCursor();
    resetFrontageChoice();
    setTraceMode('edit');
    setAnnounce(`${id.replace('_', '-')} preset seeded, ${vs.length} vertices — edit mode active`);
    const map = getMap();
    if (map) {
      clearDraftOverlays(map);
      updateCaptureSources(map, { ring: vs, cursor: null, guides: [], isClosed: true });
    }
    frameRing(vs);
  };

  const handleImport = (): void => {
    setImportError(null);
    try {
      const parsed = parseBoundaryText(importText, originRef.current);
      if (parsed.vertices.length < 3) throw new Error('Fewer than 3 vertices after parsing.');
      const vs = ensureCCW(parsed.vertices);
      setVertices(vs);
      verticesRef.current = vs;
      setImportText('');
      resetFrontageChoice();
      historyRef.current.clear();
      setHistoryTick((t) => t + 1);
      setTraceMode('edit');
      setAnnounce(`Boundary imported, ${vs.length} vertices`);
      const map = getMap();
      if (map) updateCaptureSources(map, { ring: vs, cursor: null, guides: [], isClosed: true });
      onStepChange('frontage');
    } catch (e: any) {
      setImportError(e?.message ?? 'Import failed.');
    }
  };

  /* ---------- commit (single funnel) ---------- */
  const live = useMemo(() => metricsFor(vertices), [vertices]);
  const liveRingCheck = useMemo(() => validateLiveRing(vertices, cursor), [vertices, cursor]);

  const commit = (): void => {
    try {
      // Validation happens inside the funnel; throws BoundaryError on invalid.
      buildPlotPolygonPayload({
        vertices,
        origin,
        source: inferSource(),
        frontageEdgeIndex: activeFrontage,
      });
      const committed: SharedBoundaryState = {
        vertices: ensureCCW(vertices),
        origin,
        source: inferSource(),
        frontageEdgeIndex: activeFrontage,
      };
      onCommit(committed);
    } catch (e) {
      if (e instanceof BoundaryError) setImportError(e.message);
    }
  };

  function inferSource(): SharedBoundaryState['source'] {
    if (boundary?.source === 'legacy') return 'legacy';
    if (vertices.length === 4 && rectW && rectD) return 'rectangle';
    return 'trace';
  }

  /* ---------- derived UI state ---------- */
  const stepIndex = ['locate', 'trace', 'frontage', 'review'].indexOf(step);
  const canClose = vertices.length >= 3;
  const liveValid = live.valid;
  const canCommit = liveValid;
  const liveEdgeInfo = useMemo(() => {
    if (step !== 'trace' || !cursor || vertices.length === 0) return null;
    const anchor = vertices[vertices.length - 1];
    const az = azimuthDeg(anchor, cursor);
    const len = Math.hypot(cursor.x - anchor.x, cursor.y - anchor.y);
    return { az, len, bearing: quadrantBearing(az) };
  }, [step, cursor, vertices]);

  const isNearCloseTarget = useMemo(() => {
    if (step !== 'trace' || vertices.length < 3 || !cursor) return false;
    return (
      distanceToFirstVertex(cursor, vertices[0]) <= 0.001 ||
      distanceToFirstVertex(cursor, vertices[0]) <= CLOSE_TOLERANCE_M
    );
  }, [step, vertices, cursor]);

  /* ---------- per-edge callouts (frontage precision) ---------- */
  // Every edge carries its own length + quadrant bearing. The map caps at z18,
  // where a 12 m urban plot is only ~20 px wide - per-edge badges on the map
  // would overlap into noise, so the callouts live as a readable edge table in
  // the sheet, while the map shows a single badge that follows the pointer.
  const edgeRows = useMemo(() => edgeCallouts(vertices), [vertices]);

  /** Role tag for an edge: is it the suggestion, the pick, or plain geometry. */
  const edgeRole = (index: number): 'PICKED' | 'SUGGESTED' | null => {
    if (frontageConfirmed && frontageEdge === index) return 'PICKED';
    if (!frontageConfirmed && suggestion !== null && suggestion.edgeIndex === index) return 'SUGGESTED';
    return null;
  };


  /** Pick an edge from the table (same single-source choice as a map click). */
  const pickEdge = (index: number): void => {
    setMissHint(false);
    setFrontageEdge(index);
    setFrontageConfirmed(true);
    const map = getMap();
    if (map) updateFrontageSuggestion(map, vertices, index);
  };

  if (!open) return null;

  /* ---------- render ---------- */
  // History availability for the toolbar (recomputed on demand + historyTick).
  void historyTick; // recompute signal — stack flags live below
  const canUndoNow = historyRef.current.canUndo;
  const canRedoNow = historyRef.current.canRedo;
  // HUD metrics: the live ring INCLUDING the cursor while drawing, or the
  // mid-drag preview ring while an EDIT handle is being moved (area,
  // perimeter and validity track the drag frame by frame, not on release).
  const inTrace = step === 'trace';
  const hudRing = dragPreview ?? (inTrace && cursor ? [...vertices, cursor] : vertices);
  const hudMetrics = metricsFor(hudRing.length >= 3 ? hudRing : vertices);

  return (
    <>
      {/* Screen-reader announcements (Vertex placed at 12.4 meters North…). */}
      <div aria-live="polite" role="status" className="sr-only" data-testid="capture-announce">
        {announce}
      </div>

      {/* Contextual stats HUD + coach marks.
          vertexCount is the COMMITTED count: the live area/perimeter
          deliberately include the floating cursor preview, but a "Vertices"
          counter that disagrees with the wizard's own "N vertices" line
          reads as a bug. One number, two places, same value. */}
      {inTrace && (
        <CaptureHUD
          visible={inTrace}
          areaSqm={Math.abs(hudMetrics.areaSqm) || 0}
          perimeterM={hudMetrics.perimeterM}
          vertexCount={vertices.length}
          invalid={hudRing.length >= 3 && !hudMetrics.valid}
          invalidReason={hudMetrics.reason}
          drawPlacedCount={vertices.length}
          coachProgress={coachProgress}
          onDismissCoach={dismissCoach}
        />
      )}

      {/* Drag delta badge (Δx, Δy) while EDIT-dragging */}
      {inTrace && dragDeltaNow && cursorPx && (
        <div
          style={cursorPx ? { left: cursorPx.x + 18, top: cursorPx.y + 12 } : undefined}
          className="absolute z-[960] pointer-events-none select-none"
          data-testid="drag-delta-badge"
        >
          <div className="vibrancy-pill px-2 py-0.5 rounded-[6px] shadow-md text-[10px] ui-font-tabular font-semibold text-[var(--text-1)] flex items-center gap-1.5">
            <span>
              Δx {dragDeltaNow.dx >= 0 ? '+' : ''}{dragDeltaNow.dx.toFixed(1)}
            </span>
            <span className="text-[var(--hairline)]">|</span>
            <span>
              Δy {dragDeltaNow.dy >= 0 ? '+' : ''}{dragDeltaNow.dy.toFixed(1)} m
            </span>
          </div>
        </div>
      )}
      {/* Floating glass toolbar.
          Top-right keeps it clear of the step sheet, the HUD and the zoom
          stack at every viewport; --map-controls-right tracks the results
          panel so it never slides under the right drawer. */}
      {step === 'trace' && (
        <div
          className="absolute right-2 sm:right-4 lg:right-[calc(var(--map-controls-right,16px)+16px)] top-[62px] sm:top-[76px] lg:top-[330px] z-[1002] pointer-events-auto"
          data-testid="trace-toolbar-anchor"
        >
          <TraceToolbar
            visible={step === 'trace'}
            mode={traceMode}
            presetsMenu={
              <PresetMenu
                open={presetOpen}
                onClose={() => setPresetOpen(false)}
                widthM={rectW}
                depthM={rectD}
                rotationDeg={rectRot}
                onPick={applyToolbarPreset}
              />
            }
            onModeChange={(m) => {
              if (m === 'edit' && vertices.length < 3) return;
              setTraceMode(m);
              const map = getMap();
              if (map) {
                setEditCursor(map, m === 'edit' ? 'crosshair' : 'crosshair');
                // Leaving edit mode clears any drag/hover affordances.
                if (m === 'draw') {
                  setInsertEdge(null);
                  setInsertPos(null);
                  setDragIdx(null);
                  dragIdxRef.current = null;
                  setDragDeltaNow(null);
                  setDragPreview(null);
                  setVertexFeatureState(map, 'hover', null);
                  setVertexFeatureState(map, 'drag', null);
                  updateCaptureSources(map, { ring: verticesRef.current, cursor: cursorRef.current, guides: guidesRef.current, isClosed: false, editLiveRing: null, insertHandle: null });
                } else {
                  // Entering edit: the rubber-band edge is a draw affordance.
                  clearDraftOverlays(map);
                  updateCaptureSources(map, { ring: verticesRef.current, cursor: null, guides: [], isClosed: true, editLiveRing: null, insertHandle: null });
                }
              }
            }}
            canUndo={canUndoNow}
            canRedo={canRedoNow}
            onUndo={applyUndo}
            onRedo={applyRedo}
            onFinish={() => {
              const m = getMap();
              if (m) pulseBoundaryLock(m);
              finishTraceRef.current();
            }}
            finishDisabled={!canClose}
            finishDisabledReason={
              vertices.length < 3
                ? 'Add at least 3 vertices to finish'
                : undefined
            }
            vertexCount={vertices.length}
            onImport={() => {
              const el = document.querySelector<HTMLDetailsElement>('[data-testid="import-disclosure"]');
              if (el) el.open = true;
            }}
            onPresets={() => setPresetOpen((v) => !v)}
            presetsOpen={presetOpen}
          />
        </div>
      )}

      {/* EDIT-mode '+' insertion handle hint (pure DOM twin of the map layer,
          exposes the hovered midpoint to assistive tech) */}
      {inTrace && traceMode === 'edit' && insertPos !== null && (
        <span data-testid="capture-insert-affordance" className="sr-only">
          Insert vertex at edge midpoint, press click to add
        </span>
      )}

      {/* Dynamic guidance pill while tracing */}
      {step === 'trace' && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-[1000] pointer-events-none select-none">
          <div className="vibrancy-pill px-3.5 py-1.5 rounded-full shadow-lg flex items-center gap-2.5 text-[11px] font-medium text-[var(--text-1)] border border-[var(--panel-border-color)] bg-[var(--surface-overlay)] backdrop-blur-md">
            <Icon name="crosshair" size={13} className="text-[var(--accent-ink)] shrink-0" />
            <div className="flex items-center gap-1.5 flex-wrap">
              {vertices.length === 0 ? (
                <>
                  <span>Click map to place 1st boundary vertex</span>
                  <span className="text-[var(--text-3)]">·</span>
                  <span className="text-[var(--text-2)] flex items-center gap-1"><Kbd>Esc</Kbd> Cancel</span>
                </>
              ) : vertices.length < 3 ? (
                <>
                  <span>Click to place point {vertices.length + 1}</span>
                  <span className="text-[var(--text-3)]">·</span>
                  <span className="text-[var(--text-2)] flex items-center gap-1"><Kbd>Tab</Kbd> Snap</span>
                  <span className="text-[var(--text-3)]">·</span>
                  <span className="text-[var(--text-2)] flex items-center gap-1"><Kbd>Ctrl+Z</Kbd> Undo</span>
                  <span className="text-[var(--text-3)]">·</span>
                  <span className="text-[var(--text-2)] flex items-center gap-1"><Kbd>Esc</Kbd> Cancel</span>
                </>
              ) : (
                <>
                  {/* Emphasis comes from weight + the accent keycap, not from
                      accent-coloured 11px copy: token ink keeps the worst-case
                      contrast over dark basemap tiles above AA. */}
                  <span className="text-[var(--text-1)] font-semibold flex items-center gap-1">
                    Click P1 or <Kbd>Enter</Kbd> to close
                  </span>
                  <span className="text-[var(--text-3)]">·</span>
                  <span className="text-[var(--text-2)] flex items-center gap-1"><Kbd>Tab</Kbd> Snap</span>
                  <span className="text-[var(--text-3)]">·</span>
                  <span className="text-[var(--text-2)] flex items-center gap-1"><Kbd>Ctrl+Z</Kbd> Undo</span>
                  <span className="text-[var(--text-3)]">·</span>
                  <span className="text-[var(--text-2)] flex items-center gap-1"><Kbd>Esc</Kbd> Cancel</span>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Floating CAD Cursor Dimension HUD while tracing */}
      {step === 'trace' && cursorPx && (
        <div
          style={{ left: cursorPx.x + 16, top: cursorPx.y - 14 }}
          className="absolute z-[950] pointer-events-none transition-[left,top] duration-100 ease-out select-none"
          data-testid="cursor-dimension-hud"
        >
          {isNearCloseTarget ? (
            <div className="vibrancy-pill px-2.5 py-1 rounded-full shadow-lg border border-[var(--accent)] bg-[var(--accent)] text-white text-[11px] font-semibold flex items-center gap-1.5 whitespace-nowrap">
              <Icon name="crosshair" size={12} className="shrink-0" />
              <span>Click or Enter to close</span>
              <span className="opacity-90 text-[10px]">({vertices.length} vertices)</span>
            </div>
          ) : liveEdgeInfo ? (
            <div className="vibrancy-pill px-2.5 py-1 rounded-[8px] shadow-lg border border-[var(--panel-border-color)] bg-[var(--surface-overlay)] text-[var(--text-1)] text-[11px] font-medium flex items-center gap-2 backdrop-blur-md">
              <span className="font-semibold ui-font-tabular text-[var(--accent-ink)]">
                {liveEdgeInfo.len.toFixed(2)} m
              </span>
              <span className="text-[var(--hairline)]">|</span>
              <span className="ui-font-tabular text-[var(--text-2)] text-[10px]">
                {liveEdgeInfo.bearing}
              </span>
              {snapMode !== 'FREE' && (
                <span className="text-[9px] uppercase px-1 py-0.5 rounded bg-[var(--accent-tint)] text-[var(--accent-ink)] font-bold">
                  {snapMode === 'ORTHOGONAL' ? '90°' : 'PAR'}
                </span>
              )}
              {!liveRingCheck.valid && (
                <span className="text-[10px] text-[var(--semantic-red-ink)] font-medium flex items-center gap-0.5">
                  <Icon name="alert-triangle" size={11} className="shrink-0" />
                  Invalid
                </span>
              )}
            </div>
          ) : vertices.length === 0 ? (
            <div className="vibrancy-pill px-2 py-0.5 rounded-[6px] shadow-sm border border-[var(--panel-border-color)] bg-[var(--surface-overlay)] text-[var(--text-2)] text-[10px] font-medium backdrop-blur-md">
              Click to place 1st vertex
            </div>
          ) : null}
        </div>
      )}

      {/* Hovered-edge callout: one badge pinned to the pointer, readable at any zoom */}
      {step === 'frontage' && hoveredEdge !== null && hoverPx && edgeRows[hoveredEdge] && (
        <div
          style={{ left: hoverPx.x + 14, top: hoverPx.y - 12 }}
          className="absolute z-[900] pointer-events-none"
        >
          <span
            data-testid="frontage-hover-badge"
            className="inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold ui-font-tabular border border-[var(--accent)] bg-[var(--accent)] text-white shadow-sm"
          >
            {edgeRows[hoveredEdge].label}
          </span>
        </div>
      )}

      {/* Stepped capture panel */}
      <div
        className="absolute bottom-12 sm:bottom-14 left-2 sm:left-3 lg:left-[364px] z-[1000] pointer-events-auto w-[320px] max-w-[calc(100vw-16px)] vibrancy-panel rounded-[16px] shadow-2xl border border-[var(--panel-border-color)] pb-[var(--safe-area-bottom)]"
        data-testid="capture-sheet"
      >
        {/* Step rail */}
        <div className="flex items-center gap-1 px-3.5 pt-3">
          {(['locate', 'trace', 'frontage', 'review'] as CaptureStep[]).map((s, i) => (
            <React.Fragment key={s}>
              <button
                type="button"
                onClick={() => i <= stepIndex && onStepChange(s)}
                className={`bw-touch-target w-6 h-6 rounded-full text-[11px] font-semibold flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
                  i === stepIndex
                    ? 'bg-[var(--accent)] text-white'
                    : i < stepIndex
                      ? 'bg-[var(--accent-tint)] text-[var(--accent-ink)]'
                      : 'bg-[var(--fill)] text-[var(--text-3)]'
                }`}
                aria-current={i === stepIndex ? 'step' : undefined}
                aria-label={`Step ${i + 1}: ${s}`}
              >
                {i + 1}
              </button>
              {i < 3 && <div className="flex-1 h-[1px] bg-[var(--hairline)]" />}
            </React.Fragment>
          ))}
        </div>

        <div className="px-3.5 py-3 space-y-3">
          {/* STEP 1 — LOCATE */}
          {step === 'locate' && (
            <>
              <div className="text-[13px] font-semibold text-[var(--text-1)]">Locate the site</div>
              <p className="text-[12px] text-[var(--text-2)] leading-snug">
                Click the map to move the pin, or use search. The boundary origin is the pin.
              </p>
              {pin ? (
                <div
                  data-testid="capture-pin-coords"
                  className="text-[11px] ui-font-tabular text-[var(--text-2)]"
                >
                  {pin.lat.toFixed(5)}, {pin.lon.toFixed(5)}
                </div>
              ) : (
                /* No located pin yet: tracing here would anchor the boundary at
                   the wizard's fallback point and hand the app a captured plot
                   its own CTA still refuses to analyze. Say what is missing and
                   keep the trace button closed. */
                <div
                  data-testid="capture-needs-pin"
                  className="flex items-start gap-1.5 text-[11px] leading-snug text-[var(--text-2)]"
                >
                  <Icon name="crosshair" size={12} className="text-[var(--accent-ink)] shrink-0 mt-[1px]" />
                  <span>Click the map to place the pin - it sets the boundary origin.</span>
                </div>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={onCancel}
                  className="text-[12px] font-medium px-3 py-1.5 min-h-[34px] rounded-[8px] text-[var(--text-2)] hover:text-[var(--text-1)] hover:bg-[var(--fill)] transition-colors active:scale-95 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => onStepChange('trace')}
                  disabled={!pin}
                  title={pin ? undefined : 'Place the pin on the map first'}
                  className="text-[12px] font-semibold px-3.5 py-1.5 min-h-[34px] rounded-[8px] bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:hover:bg-[var(--accent)] active:scale-95 transition-colors shadow-sm cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:brightness-100 disabled:active:scale-100"
                >
                  Trace boundary
                </button>
              </div>
            </>
          )}

          {/* STEP 2 — TRACE */}
          {step === 'trace' && (
            <>
              <div className="flex items-center justify-between">
                <div className="text-[13px] font-semibold text-[var(--text-1)]">Trace the boundary</div>
                <div className="flex items-center rounded-[8px] bg-[var(--fill)] p-[2px]" title="Press Tab to cycle snap mode (Free / Ortho / Parallel)">
                  {(['FREE', 'ORTHOGONAL', 'PARALLEL'] as SnapMode[]).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setSnapMode(m)}
                      title={m === 'ORTHOGONAL' ? 'Orthogonal snapping' : `${m.charAt(0)}${m.slice(1).toLowerCase()} snapping`}
                      data-testid={`snap-${m.toLowerCase()}`}
                      className={`px-1.5 py-0.5 rounded-[6px] text-[10px] font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
                        snapMode === m ? 'bg-[var(--segmented-active-bg)] text-[var(--segmented-active-label)] shadow-sm' : 'text-[var(--text-2)]'
                      }`}
                    >
                      {m === 'ORTHOGONAL' ? 'Ortho' : m === 'PARALLEL' ? 'Parallel' : 'Free'}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center gap-2 text-[12px] ui-font-tabular text-[var(--text-2)]">
                <span>{vertices.length} vertices</span>
                <span>·</span>
                <span>{live.areaSqm.toFixed(1)} m²</span>
                <span>·</span>
                <span>{live.perimeterM.toFixed(1)} m</span>
              </div>
              {liveEdgeInfo && (
                <div className="text-[11px] ui-font-tabular text-[var(--accent-ink)]">
                  Live edge: {liveEdgeInfo.len.toFixed(2)} m · {liveEdgeInfo.bearing}
                </div>
              )}
              {!liveRingCheck.valid && cursor && vertices.length >= 2 && (
                <div className="text-[11px] text-[var(--semantic-red-ink)]">{liveRingCheck.reason}</div>
              )}

              {/* EDIT-mode affordance legend: every gesture is named in plain
                  language with its icon (no single-letter controls). */}
              {traceMode === 'edit' && vertices.length >= 3 && (
                <div
                  data-testid="edit-mode-hint"
                  className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10px] text-[var(--text-3)]"
                >
                  <span className="flex items-center gap-1">
                    <Icon name="edit" size={11} className="text-[var(--accent-ink)]" />
                    Drag a handle to move
                  </span>
                  <span className="flex items-center gap-1">
                    <Icon name="plus" size={11} className="text-[var(--accent-ink)]" />
                    Click an edge to insert
                  </span>
                  <span className="flex items-center gap-1">
                    <Icon name="x" size={11} className="text-[var(--semantic-red-ink)]" />
                    Right-click or <Kbd>Ctrl</Kbd>+click to delete
                  </span>
                </div>
              )}

              {/* Parametric seed inputs (labelled, no single-letter chips).
                  Selecting a preset from the toolbar dropdown consumes these dims. */}
              <div data-testid="preset-dims" className="space-y-1">
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]">
                  Preset dimensions
                </div>
                <div className="flex items-end gap-2 flex-wrap">
                  <label className="flex flex-col gap-0.5">
                    <span className="text-[10px] text-[var(--text-3)]">Frontage width (m)</span>
                    <input type="number" min={6} max={60} step={0.5} value={rectW} onChange={(e) => setRectW(Number(e.target.value) || 12)} className="w-16 h-7 rounded-[6px] bg-[var(--fill)] px-1.5 text-[11px] ui-font-tabular text-[var(--text-1)]" />
                  </label>
                  <label className="flex flex-col gap-0.5">
                    <span className="text-[10px] text-[var(--text-3)]">Plot depth (m)</span>
                    <input type="number" min={6} max={60} step={0.5} value={rectD} onChange={(e) => setRectD(Number(e.target.value) || 18)} className="w-16 h-7 rounded-[6px] bg-[var(--fill)] px-1.5 text-[11px] ui-font-tabular text-[var(--text-1)]" />
                  </label>
                  <label className="flex flex-col gap-0.5">
                    <span className="text-[10px] text-[var(--text-3)]">Rotation (°)</span>
                    <input type="number" min={0} max={359} step={1} value={rectRot} onChange={(e) => setRectRot(Number(e.target.value) || 0)} className="w-16 h-7 rounded-[6px] bg-[var(--fill)] px-1.5 text-[11px] ui-font-tabular text-[var(--text-1)]" />
                  </label>
                </div>
              </div>

              {/* Import */}
              <details className="text-[12px]" data-testid="import-disclosure">
                <summary className="cursor-pointer text-[var(--text-2)] select-none flex items-center gap-1.5">
                  <Icon name="file-code" size={12} className="text-[var(--text-3)] shrink-0" />
                  Import GeoJSON / KML
                </summary>
                <textarea
                  rows={3}
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder='{"type":"Polygon",...} or <kml>...'
                  className="mt-1.5 w-full text-[11px] font-mono p-2 rounded-[6px] bg-[var(--fill)] border border-[var(--hairline)] text-[var(--text-1)] outline-none focus:ring-1 focus:ring-[var(--accent)]"
                />
                {importError && <div className="text-[11px] text-[var(--semantic-red-ink)] mt-1">{importError}</div>}
                <button type="button" onClick={handleImport} title="Import the pasted GeoJSON or KML boundary" className="mt-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-[6px] bg-[var(--accent-tint)] text-[var(--accent-ink)] inline-flex items-center gap-1.5">
                  <Icon name="upload" size={12} />
                  Import
                </button>
              </details>

              <div className="flex justify-between items-center gap-2 pt-1">
                <div className="flex gap-1.5 min-w-0">
                  <button
                    type="button"
                    onClick={undoVertex}
                    disabled={vertices.length === 0}
                    title="Undo last placed vertex (Backspace / Delete / Ctrl+Z)"
                    className="text-[11px] font-medium px-2.5 py-1 min-h-[32px] rounded-[6px] bg-[var(--fill)] text-[var(--text-1)] hover:bg-[var(--fill-hover)] disabled:opacity-40 active:scale-95 transition-colors cursor-pointer disabled:cursor-not-allowed flex items-center gap-1.5"
                  >
                    <Icon name="undo2" size={12} className="shrink-0" />
                    <span>Undo</span>
                  </button>
                  <button
                    type="button"
                    onClick={resetTrace}
                    title="Clear the boundary and start over"
                    className="text-[11px] font-medium px-2.5 py-1 min-h-[32px] rounded-[6px] bg-[var(--fill)] text-[var(--text-1)] hover:bg-[var(--fill-hover)] active:scale-95 transition-colors cursor-pointer whitespace-nowrap"
                  >
                    Clear
                  </button>
                </div>
                <button
                  type="button"
                  onClick={finishTrace}
                  disabled={!canClose}
                  title={canClose ? "Close the boundary (Enter)" : "Add at least 3 vertices to close the boundary"}
                  className="shrink-0 h-8 min-h-[32px] px-3.5 rounded-[8px] bg-[var(--accent)] text-white text-[12px] font-semibold whitespace-nowrap hover:bg-[var(--accent-hover)] disabled:hover:bg-[var(--accent)] active:scale-95 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-sm cursor-pointer flex items-center gap-1.5"
                >
                  <Icon name="check" size={13} className="shrink-0" />
                  <span>Close shape</span>
                </button>
              </div>
            </>
          )}

          {/* STEP 3 - FRONTAGE */}
          {step === 'frontage' && (
            <>
              <div className="text-[13px] font-semibold text-[var(--text-1)]">Confirm the frontage</div>
              <p className="text-[12px] text-[var(--text-2)] leading-snug">
                Hover an edge to read its length and bearing, then click it. The amber
                edge is the Overpass suggestion.
              </p>
              {hoveredEdge !== null && edgeRows[hoveredEdge] && (
                <div
                  data-testid="frontage-hover-readout"
                  className="text-[11px] ui-font-tabular text-[var(--accent-ink)] font-semibold"
                >
                  {edgeRows[hoveredEdge].label} · click to pick
                </div>
              )}

              {/* Every edge with its length + bearing: pick by measurement, not guesswork. */}
              {edgeRows.length >= 3 && (
                <div className="space-y-1" data-testid="frontage-edge-table">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]">
                    Edges (length · bearing)
                  </div>
                  {edgeRows.map((row) => {
                    const role = edgeRole(row.index);
                    const isHovered = hoveredEdge === row.index;
                    return (
                      <button
                        key={`edge-row-${row.index}`}
                        type="button"
                        data-testid={`edge-row-${row.index}`}
                        aria-label={`Edge ${row.index + 1}: ${row.label.split(' · ').slice(1).join(', ')}`}
                        aria-pressed={role === 'PICKED'}
                        onClick={() => pickEdge(row.index)}
                        className={`w-full flex items-center justify-between gap-2 rounded-[8px] px-2 py-1 text-[11px] ui-font-tabular text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
                          isHovered
                            ? 'bg-[var(--accent-tint)] text-[var(--accent-ink)]'
                            : 'bg-[var(--fill)] text-[var(--text-2)] hover:bg-[var(--fill-hover)]'
                        }`}
                      >
                        <span className="font-semibold text-[var(--text-1)]">
                          P{row.index + 1}
                        </span>
                        <span className="flex-1 text-right">
                          {row.lengthM.toFixed(2)} m · {row.label.split(' · ')[2]}
                        </span>
                        {role && (
                          <span
                            className={`px-1.5 py-0.5 rounded-full text-[9px] font-semibold tracking-[0.06em] ${
                              role === 'PICKED'
                                ? 'bg-[var(--semantic-green)]/15 text-[var(--semantic-green-ink)]'
                                : 'bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)]'
                            }`}
                          >
                            {role}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
              {missHint && (
                <div
                  data-testid="frontage-miss-hint"
                  className="text-[11px] text-[var(--semantic-amber-ink)]"
                >
                  Click directly on an edge - each label shows its length and bearing.
                </div>
              )}

              {/* Road telemetry status (ASSUMED until confirmed — never fabricated) */}
              {roadLoading && (
                <div className="flex items-center gap-2 text-[11px] text-[var(--text-3)]">
                  <span className="h-3 w-24 rounded-full bg-[var(--fill)] animate-pulse" />
                  <span>Looking for nearby roads…</span>
                </div>
              )}
              {!roadLoading && roadError && (
                <div className="text-[11px] text-[var(--semantic-amber-ink)]">{roadError}</div>
              )}
              {!roadLoading && !roadError && road?.found && road.road && (
                <div className="text-[11px] ui-font-tabular text-[var(--text-2)]">
                  Nearest road: {road.road.road_name ?? road.road.highway_class ?? 'unnamed'}
                  {road.road.distance_meters !== null ? ` · ${road.road.distance_meters.toFixed(0)} m` : ''}
                  {road.road.bearing_degrees !== null ? ` · from ${road.road.approach_side}` : ''}
                  {road.cached ? ' · cached' : ''}
                </div>
              )}

              {(() => {
                if (frontageEdge === null && suggestion === null) return null;
                const idx = frontageEdge ?? suggestion!.edgeIndex;
                const info = edgeBearingLength(vertices, idx);
                const fromSuggestion = !frontageConfirmed && suggestion !== null && suggestion.edgeIndex === idx;
                return (
                  <div className="space-y-1">
                    <div className="text-[11px] ui-font-tabular text-[var(--text-2)]">
                      {`${info.lengthM.toFixed(2)} m · ${info.bearing}`}
                    </div>
                    {fromSuggestion ? (
                      <div className="flex items-center gap-1.5">
                        <span className="px-1.5 py-0.5 rounded-full text-[9px] font-semibold tracking-[0.06em] bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)]">ASSUMED</span>
                        <span className="text-[11px] text-[var(--text-2)]">Suggested from OSM road bearing</span>
                        <button
                          type="button"
                          onClick={() => {
                            setFrontageEdge(suggestion!.edgeIndex);
                            setFrontageConfirmed(true);
                          }}
                          className="text-[11px] font-semibold px-2 py-0.5 rounded-[6px] bg-[var(--accent-tint)] text-[var(--accent-ink)]"
                        >
                          Accept
                        </button>
                      </div>
                    ) : frontageConfirmed && frontageEdge !== null ? (
                      <div className="flex items-center gap-1.5">
                        <span className="px-1.5 py-0.5 rounded-full text-[9px] font-semibold tracking-[0.06em] bg-[var(--semantic-green)]/15 text-[var(--semantic-green-ink)]">VERIFIED</span>
                        <span className="text-[11px] text-[var(--text-2)]">Confirmed by you on the map</span>
                      </div>
                    ) : null}
                  </div>
                );
              })()}
              {frontageEdge === null && suggestion === null && (
                <div
                  data-testid="frontage-unselected-hint"
                  className="flex items-center gap-1.5 p-2 rounded-[8px] bg-[var(--accent-tint)]/40 border border-[var(--hairline)] text-[11px] text-[var(--accent-ink)]"
                >
                  <Icon name="info" size={13} className="shrink-0" />
                  <span>Select a road frontage edge from the table or click an edge on the map to proceed.</span>
                </div>
              )}
              <div className="flex justify-between items-center pt-1">
                <button
                  type="button"
                  onClick={() => onStepChange('trace')}
                  className="text-[11px] font-medium px-2.5 py-1 min-h-[32px] rounded-[6px] bg-[var(--fill)] text-[var(--text-1)] hover:bg-[var(--fill-hover)] active:scale-95 transition-colors cursor-pointer"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={() => onStepChange('review')}
                  disabled={frontageEdge === null && suggestion === null}
                  title={
                    frontageEdge === null && suggestion === null
                      ? 'Select a road frontage edge above to proceed to Review'
                      : undefined
                  }
                  className="text-[12px] font-semibold px-3.5 py-1.5 min-h-[32px] rounded-[8px] bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:hover:bg-[var(--accent)] active:scale-95 transition-colors disabled:opacity-40 shadow-sm cursor-pointer disabled:cursor-not-allowed"
                >
                  Review
                </button>
              </div>
            </>
          )}

          {/* STEP 4 - REVIEW */}
          {step === 'review' && (
            <>
              <div className="text-[13px] font-semibold text-[var(--text-1)]">Review boundary</div>
              <div className="flex flex-wrap gap-1.5">
                <span className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[11px] ui-font-tabular text-[var(--text-1)]">{live.areaSqm.toFixed(1)} m²</span>
                <span className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[11px] ui-font-tabular text-[var(--text-1)]">{live.perimeterM.toFixed(1)} m</span>
                <span className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[11px] ui-font-tabular text-[var(--text-1)]">{live.vertexCount} vertices</span>
                <span className="px-2 py-0.5 rounded-full bg-[var(--accent-tint)] text-[11px] text-[var(--accent-ink)]">{String(live.shapeType).replace('_', '-')}</span>
              </div>
              {activeFrontage !== null && (
                <div className="text-[11px] text-[var(--text-2)] ui-font-tabular">
                  Frontage: edge P{(activeFrontage % vertices.length) + 1}–P{((activeFrontage + 1) % vertices.length) + 1}
                  {!frontageConfirmed && suggestion !== null && suggestion.edgeIndex === activeFrontage ? ' (suggested)' : ''}
                </div>
              )}
              <div className="flex justify-between items-center pt-1">
                <button
                  type="button"
                  onClick={() => onStepChange('frontage')}
                  className="text-[11px] font-medium px-2.5 py-1 min-h-[32px] rounded-[6px] bg-[var(--fill)] text-[var(--text-1)] hover:bg-[var(--fill-hover)] active:scale-95 transition-colors cursor-pointer"
                >
                  Back
                </button>
                <button
                  type="button"
                  onClick={commit}
                  disabled={!canCommit}
                  className="text-[12px] font-semibold px-3.5 py-1.5 min-h-[34px] rounded-[8px] bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] disabled:hover:bg-[var(--accent)] active:scale-95 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-sm cursor-pointer"
                >
                  Use this boundary
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
};
