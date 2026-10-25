import React, { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import ReactDOM from 'react-dom';
import type { RoomPlacement, MultiStoreyBuildingModel, SingleFloorPlanModel, SitePlanModel } from '../services/types';
import { downloadFloorplanDossier } from '../services/api';
import { Icon } from './Icon';
import { useDesign } from '../design';
import { frontageChipText, polygonChipText } from '../services/sheetTruth';
import { isGhostOverlayVisible, patchGhostOverlayDom, sanitizeBlueprintSvg } from './report/svgSanitize';
import { ECS_DISCLOSURE } from './report/termDisclosures';
import { PlanVerdictChip } from './report/PlanVerdictChip';
import {
  formatProgrammeCounts,
  generatedTypologyMatches,
  getTypologyProfile,
  summariseFloorProgramme,
  resolveProgrammeFloor,
  unitCountForFloor,
} from '../services/typologyProgramme';

interface BlueprintViewerProps {
  svgString: string;
  svgPaperString?: string;
  placements?: RoomPlacement[];
  plotWidthM?: number;
  plotDepthM?: number;
  multiStorey?: MultiStoreyBuildingModel | null;
  sitePlan?: SitePlanModel | null;
  generationTimestamp?: number;
  generationId?: string;
  storeys?: number;
  isStale?: boolean;
  requestedTypology?: string;
  /** Server-computed plan verdict, rendered verbatim. */
  planVerdict?: string | null;
}

type SheetGestureState = {
  mode: 'none' | 'pan' | 'pinch';
  dist: number;
  zoom: number;
  x: number;
  y: number;
};

interface SheetGestureOpts {
  gestureRef: { current: SheetGestureState };
  panStartRef: { current: { x: number; y: number } };
  movedRef: { current: boolean };
  lastTapRef: { current: { t: number; x: number; y: number } };
  getPan: () => { x: number; y: number };
  setPan: (p: { x: number; y: number }) => void;
  getZoom: () => number;
  setZoom: (z: number) => void;
  minZoom: number;
  maxZoom: number;
  onDoubleTap?: () => void;
}

/**
 * Direct-manipulation gestures for a fixed-fidelity drawing sheet: one-finger
 * drag pans, two-finger pinch zooms, and a double-tap steps the zoom. The
 * sheet itself is never reflowed — touch only moves the viewport over it.
 */
function makeSheetGestures(opts: SheetGestureOpts) {
  const { gestureRef, panStartRef, movedRef, lastTapRef, getPan, setPan, getZoom, setZoom, minZoom, maxZoom, onDoubleTap } = opts;
  return {
    onTouchStart(e: React.TouchEvent<HTMLDivElement>) {
      const g = gestureRef.current;
      if (e.touches.length === 2) {
        const a = e.touches[0];
        const b = e.touches[1];
        g.mode = 'pinch';
        g.dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
        g.zoom = getZoom();
      } else if (e.touches.length === 1) {
        g.mode = 'pan';
        g.x = e.touches[0].clientX;
        g.y = e.touches[0].clientY;
        panStartRef.current = { ...getPan() };
        movedRef.current = false;
      }
    },
    onTouchMove(e: React.TouchEvent<HTMLDivElement>) {
      const g = gestureRef.current;
      if (g.mode === 'pinch' && e.touches.length === 2) {
        const a = e.touches[0];
        const b = e.touches[1];
        const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
        if (g.dist > 0) {
          const next = Math.min(maxZoom, Math.max(minZoom, g.zoom * (dist / g.dist)));
          setZoom(Number(next.toFixed(2)));
        }
      } else if (g.mode === 'pan' && e.touches.length === 1) {
        const dx = e.touches[0].clientX - g.x;
        const dy = e.touches[0].clientY - g.y;
        if (Math.abs(dx) + Math.abs(dy) > 6) movedRef.current = true;
        setPan({ x: panStartRef.current.x + dx, y: panStartRef.current.y + dy });
      }
    },
    onTouchEnd(e: React.TouchEvent<HTMLDivElement>) {
      const g = gestureRef.current;
      if (g.mode === 'pan' && e.changedTouches.length > 0 && !movedRef.current) {
        const t = e.changedTouches[0];
        const now = Date.now();
        const last = lastTapRef.current;
        if (now - last.t < 300 && Math.hypot(t.clientX - last.x, t.clientY - last.y) < 24) {
          onDoubleTap?.();
          lastTapRef.current = { t: 0, x: 0, y: 0 };
        } else {
          lastTapRef.current = { t: now, x: t.clientX, y: t.clientY };
        }
      }
      g.mode = 'none';
    },
  };
}

const ROOM_METADATA: Record<string, { dotColor: string; label: string; zone: string; isCore?: boolean }> = {
  // T1 Residence
  master_bed: { dotColor: '#0284C7', label: 'Master Bedroom', zone: 'SW' },
  living: { dotColor: '#10B981', label: 'Living Room', zone: 'N/NE' },
  kitchen: { dotColor: '#F59E0B', label: 'Kitchen', zone: 'SE' },
  puja: { dotColor: '#EAB308', label: 'Puja Room', zone: 'NE' },
  bath_1: { dotColor: '#06B6D4', label: 'Primary Bath', zone: 'W' },
  bath_2: { dotColor: '#14B8A6', label: 'Common Bath', zone: 'NW' },
  bed_2: { dotColor: '#3B82F6', label: 'Bedroom 2', zone: 'NW' },
  dining: { dotColor: '#F97316', label: 'Dining Area', zone: 'W' },
  stairs: { dotColor: '#8B5CF6', label: 'Staircase Core', zone: 'SW/W', isCore: true },
  balcony: { dotColor: '#10B981', label: 'Covered Balcony', zone: 'NE' },
  study: { dotColor: '#6366F1', label: 'Study / Office', zone: 'NE' },
  utility: { dotColor: '#EC4899', label: 'Utility / Store', zone: 'SE' },
  terrace_wing_b: { dotColor: '#0EA5E9', label: 'Open Terrace / Setback Deck', zone: 'TERRACE' },
  terrace_band: { dotColor: '#0EA5E9', label: 'Open Terrace / Sky Deck', zone: 'TERRACE' },
  terrace: { dotColor: '#0EA5E9', label: 'Open Terrace / Setback Deck', zone: 'TERRACE' },

  // T2 Apartment
  staircase_core: { dotColor: '#8B5CF6', label: 'Common Stair Core', zone: 'CORE', isCore: true },
  lift_core: { dotColor: '#A855F7', label: 'Passenger Lift Core', zone: 'CORE', isCore: true },
  lobby: { dotColor: '#64748B', label: 'Central Lobby', zone: 'CIRC' },
  apt_a_living: { dotColor: '#059669', label: 'Unit A Living', zone: 'NE' },
  apt_a_kitchen: { dotColor: '#D97706', label: 'Unit A Kitchen', zone: 'SE' },
  apt_a_bed: { dotColor: '#0284C7', label: 'Unit A Master Bed', zone: 'SW' },
  apt_a_bath: { dotColor: '#0891B2', label: 'Unit A Bath', zone: 'W' },
  apt_b_living: { dotColor: '#10B981', label: 'Unit B Living', zone: 'NW' },
  apt_b_kitchen: { dotColor: '#F59E0B', label: 'Unit B Kitchen', zone: 'SE' },
  apt_b_bed: { dotColor: '#2563EB', label: 'Unit B Bedroom', zone: 'NW' },
  apt_b_bath: { dotColor: '#06B6D4', label: 'Unit B Bath', zone: 'W' },
  apt_balcony: { dotColor: '#34D399', label: 'Apartment Balcony', zone: 'E' },

  // T3 Complex
  fire_stair_1: { dotColor: '#EF4444', label: 'Fire Stair Core 1', zone: 'CORE', isCore: true },
  fire_stair_2: { dotColor: '#DC2626', label: 'Fire Exit Stair 2', zone: 'CORE', isCore: true },
  lift_bank: { dotColor: '#9333EA', label: 'Dual Lift Bank & Lobby', zone: 'CORE', isCore: true },
  corridor: { dotColor: '#64748B', label: 'Spine Corridor', zone: 'CIRC' },
  commercial_suite_a: { dotColor: '#2563EB', label: 'Commercial Suite A', zone: 'N' },
  commercial_suite_b: { dotColor: '#3B82F6', label: 'Commercial Suite B', zone: 'E' },
  commercial_suite_c: { dotColor: '#60A5FA', label: 'Commercial Suite C', zone: 'S' },
  restroom_block: { dotColor: '#06B6D4', label: 'Public Restrooms', zone: 'W' },
  mep_room: { dotColor: '#F59E0B', label: 'MEP & Service Room', zone: 'NW' },

  // T4 Warehouse
  storage_bay: { dotColor: '#3B82F6', label: 'Clear-Span Storage Bay', zone: 'BAY' },
  loading_dock: { dotColor: '#F97316', label: 'Loading Dock Shutter', zone: 'DOCK' },
  dispatch_buffer: { dotColor: '#EAB308', label: 'Dispatch Buffer', zone: 'BUFFER' },
  staff_amenities: { dotColor: '#14B8A6', label: 'Staff Locker & WC', zone: 'AMENITY' },
  steel_stair: { dotColor: '#8B5CF6', label: 'Industrial Steel Stair', zone: 'CORE', isCore: true },
  mezzanine_office: { dotColor: '#6366F1', label: 'Mezzanine Office', zone: 'OFFICE' },
  conference_room: { dotColor: '#8B5CF6', label: 'Conference Room', zone: 'ADMIN' },
  catwalk: { dotColor: '#94A3B8', label: 'Inspection Catwalk', zone: 'ACCESS' },

  // Canonical ontology IDs emitted by current generations. The legacy keys
  // above stay for plans generated before the typology vocabulary alignment.
  // New dot fills consume the semantic tokens (never raw hex) so the design
  // system gate keeps passing as typologies are added; the chip label, not the
  // hue, is what identifies the space.
  t1_stair: { dotColor: 'var(--accent)', label: 'Private Staircase', zone: 'CORE', isCore: true },
  foyer: { dotColor: 'var(--text-2)', label: 'Entry Foyer', zone: 'N' },
  shared_stair: { dotColor: 'var(--accent)', label: 'Shared Staircase Core', zone: 'CORE', isCore: true },
  floor_lobby: { dotColor: 'var(--text-2)', label: 'Floor Distribution Lobby', zone: 'CIRC' },
  unit_living: { dotColor: 'var(--semantic-green)', label: 'Unit Living / Dining', zone: 'N' },
  unit_kitchen: { dotColor: 'var(--semantic-amber)', label: 'Unit Kitchen', zone: 'SE' },
  unit_bed: { dotColor: 'var(--semantic-green)', label: 'Unit Bedroom', zone: 'SW' },
  unit_bath: { dotColor: 'var(--accent)', label: 'Unit Bathroom', zone: 'W' },
  unit_balcony: { dotColor: 'var(--semantic-green)', label: 'Unit Private Balcony', zone: 'N' },
  unit_utility: { dotColor: 'var(--semantic-amber)', label: 'Unit Utility / Dry Balcony', zone: 'SE' },
  primary_stair: { dotColor: 'var(--semantic-red)', label: 'Fire Staircase 1', zone: 'CORE', isCore: true },
  secondary_stair: { dotColor: 'var(--semantic-red)', label: 'Fire Exit Staircase 2', zone: 'CORE', isCore: true },
  lift_lobby: { dotColor: 'var(--accent)', label: 'Elevator Core & Lobby', zone: 'CORE', isCore: true },
  spine_corridor: { dotColor: 'var(--text-2)', label: 'Double-Loaded Spine Corridor', zone: 'CIRC' },
  commercial_suite: { dotColor: 'var(--semantic-green)', label: 'Commercial / Office Suite', zone: 'N' },
  sanitary_block: { dotColor: 'var(--accent)', label: 'Commercial Restroom Block', zone: 'W' },
  dock_bay: { dotColor: 'var(--semantic-amber)', label: 'Loading Dock Shutter Bay', zone: 'DOCK' },
  dispatch: { dotColor: 'var(--text-2)', label: 'Dispatch & Staging Buffer', zone: 'BUFFER' },
  worker_amenity: { dotColor: 'var(--semantic-amber)', label: 'Staff Locker & Sanitary WC', zone: 'AMENITY' },
  admin_office: { dotColor: 'var(--accent)', label: 'Administrative Office Mezzanine', zone: 'OFFICE' },
  conf_room: { dotColor: 'var(--accent)', label: 'Conference / Operations Room', zone: 'ADMIN' },
  ind_stair: { dotColor: 'var(--semantic-red)', label: 'Industrial Fire Egress Stair', zone: 'CORE', isCore: true },
  admin_catwalk: { dotColor: 'var(--text-2)', label: 'Mezzanine Access Catwalk', zone: 'ACCESS' },
};

export const BlueprintViewer: React.FC<BlueprintViewerProps> = ({
  svgString,
  svgPaperString,
  placements = [],
  plotWidthM,
  plotDepthM,
  multiStorey = null,
  sitePlan = null,
  generationTimestamp,
  generationId,
  storeys,
  isStale = false,
  requestedTypology,
  planVerdict,
}) => {
  const { pushToast } = useDesign();
  const [mode, setMode] = useState<'cad' | 'paper'>('cad');
  const [zoom, setZoom] = useState<number>(1.0);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState<boolean>(false);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);

  // Site plan and multi-floor view state
  const [viewTab, setViewTab] = useState<'site' | 'floor'>('floor');
  const effectiveSitePlan = sitePlan || multiStorey?.site_plan;

  // Multi-floor state
  const [activeFloorIndex, setActiveFloorIndex] = useState<number>(0);
  const [showGhostOverlay, setShowGhostOverlay] = useState<boolean>(true);
  const [isExportingPdf, setIsExportingPdf] = useState<boolean>(false);

  // Modal zoom and pan state
  const [modalZoom, setModalZoom] = useState<number>(1.0);
  const [modalPan, setModalPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isModalPanning, setIsModalPanning] = useState<boolean>(false);

  const dragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const panStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const modalDragStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const modalPanStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // A plan is multi-storey ONLY if multiStorey model has > 1 floor, exactly matching report_service.py:2050 (len(ms_floors) > 1)
  const isMultiStorey = Boolean(
    multiStorey &&
    multiStorey.floors &&
    multiStorey.floors.length > 1 &&
    (storeys === undefined || storeys > 1)
  );
  const safeFloorIndex =
    isMultiStorey && multiStorey?.floors && activeFloorIndex < multiStorey.floors.length
      ? activeFloorIndex
      : 0;
  const currentFloor: SingleFloorPlanModel | null = isMultiStorey && multiStorey?.floors
    ? multiStorey.floors[safeFloorIndex] || multiStorey.floors[0]
    : null;

  // Whenever generationId, generationTimestamp, or primary svgString changes: reset active floor, viewTab, pan, and zoom
  useEffect(() => {
    setViewTab('floor');
    setActiveFloorIndex(0);
    setSelectedRoomId(null);
    setZoom(1.0);
    setPan({ x: 0, y: 0 });
    setModalZoom(1.0);
    setModalPan({ x: 0, y: 0 });
  }, [generationId, generationTimestamp, svgString]);

  const activeSvg = useMemo(() => {
    if (viewTab === 'site' && effectiveSitePlan?.svg_site_plan) {
      return effectiveSitePlan.svg_site_plan;
    }
    if (isMultiStorey && currentFloor) {
      return mode === 'paper' && currentFloor.svg_blueprint_paper
        ? currentFloor.svg_blueprint_paper
        : currentFloor.svg_blueprint_cad;
    }
    return mode === 'paper' && svgPaperString ? svgPaperString : svgString;
  }, [viewTab, effectiveSitePlan, isMultiStorey, currentFloor, mode, svgPaperString, svgString]);

  // Derive robust generation key and visible freshness token (Requirement 6)
  const effectiveGenId = generationId ?? (generationTimestamp ? `T${generationTimestamp}` : (svgString ? `${svgString.length}_${svgString.slice(0, 16).replace(/\W/g, '')}` : 'init'));
  const storeysLabel = isMultiStorey ? `G+${(multiStorey?.total_storeys || storeys || 2) - 1}` : 'G';
  const dimsLabel = `${(plotWidthM || 10).toFixed(1)}x${(plotDepthM || 12).toFixed(1)}m`;
  // Sheet truth: the viewer header carries the same frontage + polygon-hash
  // provenance markers as the drawn sheets (sheetTruth parity with drawing_ir).
  const _prov = (multiStorey?.site_plan?.provenance || sitePlan?.provenance || {}) as Record<string, any>;
  const sheetTruthTail = [
    frontageChipText(_prov.frontage_edge_index, _prov.frontage_source),
    polygonChipText(multiStorey?.plot_polygon || sitePlan?.plot_polygon),
  ].join(' | ');
  const freshnessToken = `${effectiveGenId} | ${dimsLabel} | ${storeysLabel} | ${sheetTruthTail}`;

  // (The per-container keys that used to force a REMOUNT on every ghost toggle
  // are gone with the re-inject: a ghost flip is now an in-place DOM patch, and a
  // sheet switch is chunked, so neither wants React to tear the subtree down.)

  // Sanitize raw SVG and inject paint-order halo style + dynamic ghost overlay styling.
  // The ghost gate itself lives in report/svgSanitize.ts (isGhostOverlayVisible)
  // so the invariant is unit-testable: the F0 anchor core is on every sheet, so
  // the overlay is injected ONLY when the toggle is on AND an upper floor is
  // active. `data-ghost-overlay` mirrors the same boolean in both directions.
  const ghostVisible = isGhostOverlayVisible(showGhostOverlay, safeFloorIndex);
  // `sanitizeBlueprintSvg` carries its own two-entry memo (keyed by the source
  // SVG identity), so toggling the ghost overlay between two states it has
  // already rendered costs a map lookup rather than a full re-parse — that
  // re-parse was the largest long task on this surface. This memo still exists
  // for the within-render-reasons: it keeps React from calling into it on every
  // unrelated re-render.
  const sanitizedSvg = useMemo(
    () => sanitizeBlueprintSvg(activeSvg, ghostVisible),
    [activeSvg, ghostVisible]
  );

  /**
   * GHOST FLIP IS NOT A RE-INJECT (the ghost-flip rule).
   *
   * The overlay's visibility is already decided by a rule inside the injected
   * `<style>` and mirrored by the `data-ghost-overlay` attribute, so a toggle is
   * two DOM writes — see `patchGhostOverlayDom`, which owns the rule text. What
   * made this surface the largest Long Task on the sheet was re-parsing and
   * re-inserting a 1 224-node SVG to change one display rule.
   *
   * The card and the modal hold separate copies, so both are patched. Note what
   * is deliberately NOT here: writing the flip back into React state. The state
   * change that ran this effect already re-rendered, and that render passed the
   * SAME html string for `injectState.ghost` — which React skips — so the patch
   * stands; a fallback write would only cost a second render for nothing.
   */
  const injectedGhostRef = useRef<boolean>(ghostVisible);
  useEffect(() => {
    if (injectedGhostRef.current === ghostVisible) return;
    patchGhostOverlayDom(cardSheetRef.current, ghostVisible);
    patchGhostOverlayDom(modalSheetRef.current, ghostVisible);
    injectedGhostRef.current = ghostVisible;
  }, [ghostVisible]);

  /**
   * Sheet-gated inject (the generation chunker's pattern, reused here).
   *
   * A floor switch or a mode switch replaces the SHEET: the inject re-parses and
   * re-inserts a multi-hundred-node SVG (1 224 nodes on a G+1 dossier), which at
   * 4× CPU throttle was a 130 ms task on a surface that shows nothing else. The
   * chrome that says which floor you are on still switches in the click frame;
   * only the sheet's body waits for an idle slice, behind a placeholder inside the
   * SAME 360 px box the sheet occupies, so nothing below it can move.
   *
   * The gate deliberately EXCLUDES the ghost flag: toggling the ghost overlay is a
   * cosmetic change to the sheet already on screen, and making it flash a
   * placeholder would be a worse trade than the cost it saves. Ghost flips keep
   * their instant, keyed re-inject.
   */
  const cardSheetRef = useRef<HTMLDivElement | null>(null);
  const modalSheetRef = useRef<HTMLDivElement | null>(null);
  const sheetKey = `blueprint-sheet-${effectiveGenId}-${safeFloorIndex}-${mode}`;
  /**
   * The ghost state the CURRENTLY INJECTED html was built with. Part of the same
   * state cell as the sheet, so a sheet switch rebuilds both together.
   */
  const [injectState, setInjectState] = useState<{ sheetKey: string; ghost: boolean }>(() => ({
    sheetKey,
    ghost: ghostVisible,
  }));
  const injectReady = injectState.sheetKey === sheetKey;
  /** The html React is told to hold: the injected sheet with its own ghost state. */
  const renderSvg = useMemo(
    () => sanitizeBlueprintSvg(activeSvg, injectState.ghost),
    [activeSvg, injectState.ghost]
  );
  useEffect(() => {
    if (injectReady) return;
    let cancelled = false;
    const mount = () => {
      if (cancelled) return;
      React.startTransition(() => setInjectState({ sheetKey, ghost: ghostVisible }));
    };
    const hasIdle = typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function';
    const handle = hasIdle
      ? window.requestIdleCallback(mount, { timeout: 300 })
      : window.setTimeout(mount, 32);
    return () => {
      cancelled = true;
      if (hasIdle) window.cancelIdleCallback(handle);
      else clearTimeout(handle);
    };    // `ghostVisible` is read when a sheet is (re)mounted — including it keeps the
    // mount honest without re-running anything while the sheet is unchanged
    // (the early return above covers that).
  }, [sheetKey, injectReady, ghostVisible]);

  // Derive per-floor room placements for current floor legend.
  // SINGLE SOURCE: the on-sheet room label and the ROOM SCHEDULE both print the
  // CLEAR area (`clear_area_sqm`). The room model's `area_sqm` is the GROSS
  // allocated area, so a chip reading it disagreed with the drawing by ~8%.
  // The legend chip resolves the clear area from the same schedule rows the
  // sheet prints, and formats it to the same one decimal place.
  const generatedProfile = useMemo(
    () => getTypologyProfile(multiStorey?.building_typology),
    [multiStorey?.building_typology]
  );
  const programmeFloor = useMemo(
    () => resolveProgrammeFloor(currentFloor, multiStorey?.floors),
    [currentFloor, multiStorey?.floors]
  );
  const programmeCounts = useMemo(
    () => summariseFloorProgramme(programmeFloor),
    [programmeFloor]
  );
  const programmeText = useMemo(
    () => formatProgrammeCounts(programmeCounts),
    [programmeCounts]
  );
  const storeyCount = multiStorey?.total_storeys || storeys || 1;
  const generatedGfa = multiStorey?.total_built_up_area_sqm || 0;
  const generatedUnitCount = unitCountForFloor(programmeFloor);
  const typologyMismatch = Boolean(
    multiStorey && requestedTypology && !generatedTypologyMatches(multiStorey, requestedTypology)
  );
  const selectedRoom = useMemo(
    () => currentFloor?.rooms.find((room) => room.room_id === selectedRoomId) || null,
    [currentFloor, selectedRoomId]
  );
  // A new floor is a new room set: an id that only existed on the previous
  // plate must not highlight or open the inspector.  Derived during render so
  // the viewer never needs an effect just to clear state.
  const activeRoomId = selectedRoom ? selectedRoomId : null;
  const selectedRoomWindows = useMemo(
    () => (currentFloor?.windows || []).filter((window) => window.room_id === selectedRoom?.room_id),
    [currentFloor, selectedRoom?.room_id]
  );
  const selectedRoomDoors = useMemo(
    () => (currentFloor?.doors || []).filter(
      (door) => door.from_room === selectedRoom?.room_id || door.to_room === selectedRoom?.room_id
    ),
    [currentFloor, selectedRoom?.room_id]
  );
  const selectedRoomShafts = useMemo(
    () => (multiStorey?.duct_shafts || []).filter((shaft) =>
      shaft.servicing_rooms.includes(selectedRoom?.room_id || '')
    ),
    [multiStorey?.duct_shafts, selectedRoom?.room_id]
  );
  const selectedRoomFurniture = selectedRoom?.furniture || [];
  const selectedRoomFurnitureOk = selectedRoomFurniture.length > 0 &&
    selectedRoomFurniture.every((item) => item.is_satisfied);
  const selectedRoomVentilation = selectedRoomWindows.length > 0
    ? `${selectedRoomWindows.length} opening${selectedRoomWindows.length === 1 ? '' : 's'}`
    : selectedRoomShafts.length > 0
      ? `${selectedRoomShafts.length} mechanical shaft${selectedRoomShafts.length === 1 ? '' : 's'}`
      : 'No opening / shaft';

  const currentPlacements = useMemo(() => {
    const schedule = (currentFloor?.room_schedule ?? []) as Array<Record<string, unknown>>;
    const clearByRoom = new Map<string, number>();
    for (const row of schedule) {
      const id = typeof row.room_id === 'string' ? row.room_id : null;
      const clear = Number(row.clear_area_sqm ?? row.area_sqm);
      if (id && Number.isFinite(clear) && clear > 0) clearByRoom.set(id, clear);
    }
    const clearAreaFor = (roomId: string, fallback: number | undefined): number | undefined => {
      const direct = clearByRoom.get(roomId);
      if (direct !== undefined) return direct;
      // Floor-suffixed rows (living_F0) vs base ids (living): match on the base
      // id so a placement without its own schedule row still resolves.
      const base = roomId.replace(/_F\d+$/, '');
      for (const [id, area] of clearByRoom) {
        if (id.replace(/_F\d+$/, '') === base) return area;
      }
      return fallback;
    };
    if (isMultiStorey && currentFloor && currentFloor.rooms && currentFloor.rooms.length > 0) {
      return currentFloor.rooms.map((r) => ({
        room_id: r.room_id,
        room_name: r.room_name,
        zone: r.zone,
        is_core: Boolean(r.is_vertical_core),
        area_sqm: clearAreaFor(r.room_id, r.area_sqm),
      }));
    }
    return placements.map((p) => ({
      room_id: p.room_id,
      room_name: p.room_name,
      zone: p.zone,
      is_core: p.room_id === 'stairs' || p.room_id.includes('stair') || p.room_id.includes('lift'),
      area_sqm: clearAreaFor(p.room_id, p.area_sqm),
    }));
  }, [isMultiStorey, currentFloor, placements]);

  const selectedRoomClearArea = useMemo(
    () => currentPlacements.find((placement) => placement.room_id === selectedRoom?.room_id)?.area_sqm,
    [currentPlacements, selectedRoom?.room_id]
  );

  const handleZoomIn = () => setZoom((z) => Math.min(2.5, +(z + 0.25).toFixed(2)));
  const handleZoomOut = () => setZoom((z) => Math.max(0.75, +(z - 0.25).toFixed(2)));
  const handleReset = () => {
    setZoom(1.0);
    setPan({ x: 0, y: 0 });
  };

  const handleModalZoomIn = () => setModalZoom((z) => Math.min(3.5, +(z + 0.25).toFixed(2)));
  const handleModalZoomOut = () => setModalZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)));
  const handleModalReset = () => {
    setModalZoom(1.0);
    setModalPan({ x: 0, y: 0 });
  };

  const handleDownloadSvg = () => {
    if (isStale) return;
    if (!sanitizedSvg) return;
    const blob = new Blob([sanitizedSvg], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const floorTag = isMultiStorey && currentFloor ? `_${currentFloor.floor_name.replace(/\s+/g, '_')}` : '';
    const cleanGen = effectiveGenId.replace(/[^a-zA-Z0-9_-]/g, '');
    const wStr = (plotWidthM || 10).toFixed(1);
    const dStr = (plotDepthM || 12).toFixed(1);
    link.download = `BuildWise_Blueprint_${cleanGen}${floorTag}_${wStr}x${dStr}m.svg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const handleExportPdf = async () => {
    if (isStale) return;
    try {
      setIsExportingPdf(true);
      const payload: Record<string, any> = {
        plot_width_m: plotWidthM || (multiStorey?.plot_width_m ?? 12.0),
        plot_depth_m: plotDepthM || (multiStorey?.plot_depth_m ?? 15.0),
        floors: multiStorey ? multiStorey.total_storeys : 1,
        building_typology: multiStorey ? multiStorey.building_typology : 'residential_single',
      };
      if (multiStorey) {
        payload.multi_storey = multiStorey;
      }
      await downloadFloorplanDossier(payload);
    } catch (error) {
      console.error('Error exporting PDF dossier:', error);
      pushToast({ message: 'Failed to export PDF dossier. Please try again.', tone: 'critical' });
    } finally {
      setIsExportingPdf(false);
    }
  };

  // Close modal on Escape
  useEffect(() => {
    if (!isModalOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsModalOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isModalOpen]);

  // Card pan listeners
  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    setIsPanning(true);
    dragMovedRef.current = false;
    dragStartRef.current = { x: e.clientX, y: e.clientY };
    panStartRef.current = { ...pan };
  };

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!isPanning) return;
      dragMovedRef.current = true;
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      setPan({
        x: panStartRef.current.x + dx,
        y: panStartRef.current.y + dy,
      });
    },
    [isPanning]
  );

  const handleMouseUp = () => setIsPanning(false);

  /* ---------- sheet gestures (touch pan/pinch; fixed-fidelity artifact) ---------- */
  const cardGestureRef = useRef<SheetGestureState>({ mode: 'none', dist: 0, zoom: 1, x: 0, y: 0 });
  const modalGestureRef = useRef<SheetGestureState>({ mode: 'none', dist: 0, zoom: 1, x: 0, y: 0 });
  const lastTapRef = useRef<{ t: number; x: number; y: number }>({ t: 0, x: 0, y: 0 });
  const dragMovedRef = useRef<boolean>(false);
  const cardCanvasRef = useRef<HTMLDivElement>(null);
  const modalCanvasRef = useRef<HTMLDivElement>(null);

  const cardGestures = makeSheetGestures({
    gestureRef: cardGestureRef,
    panStartRef: panStartRef,
    movedRef: dragMovedRef,
    lastTapRef,
    getPan: () => pan,
    setPan: setPan,
    getZoom: () => zoom,
    setZoom: setZoom,
    minZoom: 0.75,
    maxZoom: 2.5,
    onDoubleTap: () => setZoom((z) => (z > 1.5 ? 1.0 : Math.min(2.5, z + 0.5))),
  });
  const modalGestures = makeSheetGestures({
    gestureRef: modalGestureRef,
    panStartRef: modalPanStartRef,
    movedRef: dragMovedRef,
    lastTapRef,
    getPan: () => modalPan,
    setPan: setModalPan,
    getZoom: () => modalZoom,
    setZoom: setModalZoom,
    minZoom: 0.5,
    maxZoom: 3.5,
    onDoubleTap: () => setModalZoom((z) => (z > 1.5 ? 1.0 : Math.min(3.5, z + 0.5))),
  });

  // ctrl/cmd + wheel (trackpad pinch) zooms the sheet without hijacking page
  // scroll: plain wheel keeps scrolling the surrounding report.
  useEffect(() => {
    const el = cardCanvasRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      setZoom((z) => Number(Math.min(2.5, Math.max(0.75, z * (e.deltaY < 0 ? 1.12 : 1 / 1.12))).toFixed(2)));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);
  useEffect(() => {
    const el = modalCanvasRef.current;
    if (!el || !isModalOpen) return;
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      setModalZoom((z) => Number(Math.min(3.5, Math.max(0.5, z * (e.deltaY < 0 ? 1.12 : 1 / 1.12))).toFixed(2)));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [isModalOpen]);

  // Modal pan listeners
  const handleModalMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    setIsModalPanning(true);
    dragMovedRef.current = false;
    modalDragStartRef.current = { x: e.clientX, y: e.clientY };
    modalPanStartRef.current = { ...modalPan };
  };

  const handleModalMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!isModalPanning) return;
      dragMovedRef.current = true;
      const dx = e.clientX - modalDragStartRef.current.x;
      const dy = e.clientY - modalDragStartRef.current.y;
      setModalPan({
        x: modalPanStartRef.current.x + dx,
        y: modalPanStartRef.current.y + dy,
      });
    },
    [isModalPanning]
  );

  const handleModalMouseUp = () => setIsModalPanning(false);

  // Render floor switcher tab bar (including Site Plan tab when available)
  const renderFloorSwitcher = (isModal: boolean = false) => {
    const hasSitePlan = Boolean(effectiveSitePlan?.svg_site_plan);
    const hasMultipleFloors = Boolean(isMultiStorey && multiStorey?.floors && multiStorey.floors.length > 1);

    if (!hasSitePlan && !hasMultipleFloors) {
      return null;
    }

    const floorsList = multiStorey?.floors || [
      {
        floor_index: 0,
        floor_name: 'Ground Floor (G)',
        built_up_area_sqm: 0,
        carpet_area_sqm: 0,
        rooms: [],
        doors: [],
        windows: [],
        circulation_status: 'connected' as const,
        vastu_score_pct: null,
        vastu_compliance_pct: null,
        plumbing_stack_alignment_pct: null,
        svg_blueprint_cad: svgString,
        svg_blueprint_paper: svgPaperString || svgString,
        envelope: { x: 0, y: 0, width: plotWidthM || 10, depth: plotDepthM || 12, area_sqm: 120 }
      }
    ];

    return (
      <div
        className={`flex items-center gap-1.5 overflow-x-auto py-1.5 px-2.5 sm:px-3.5 border-b border-[var(--hairline)] ${
          isModal ? 'bg-[var(--fill)]/40' : 'bg-[var(--fill)]/20'
        } overscroll-x-contain touch-pan-x [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden`}
      >
        <div className="flex items-center gap-1 mr-1 text-[10px] sm:text-[11px] font-semibold uppercase tracking-wider text-[var(--text-3)] shrink-0 select-none">
          <Icon name="layers" size={13} className="text-[var(--accent-ink)]" />
          <span>Views:</span>
        </div>

        {/* Dedicated Sheet 10.SP (Site Plan & Cadastral Survey) */}
        {hasSitePlan && (
          <button
            type="button"
            data-testid="tab-site-plan"
            onClick={() => setViewTab('site')}
            className={`px-2.5 sm:px-3 py-1 sm:py-1.5 rounded-[8px] sm:rounded-[9px] text-[11px] sm:text-[12px] transition-colors flex items-center gap-1.5 shrink-0 cursor-pointer ${
              viewTab === 'site'
                ? 'bg-emerald-600 text-white shadow-xs font-semibold ring-1 ring-white/20'
                : 'bg-[var(--fill)] text-[var(--text-2)] hover:text-[var(--text-1)] hover:bg-[var(--fill-hover)] font-medium'
            }`}
          >
            <Icon name="compass" size={13} />
            <span>Site Plan</span>
            <span
              className={`text-[9px] px-1.5 py-0.2 rounded font-bold uppercase tracking-wider ${
                viewTab === 'site' ? 'bg-white/20 text-white' : 'bg-emerald-500/15 text-[var(--semantic-green-ink)]'
              }`}
            >
              10.SP
            </span>
          </button>
        )}

        {/* Storey Floor Plates */}
        {floorsList.map((fl, idx) => {
          if (!hasMultipleFloors && !hasSitePlan) return null;
          const isActive = viewTab === 'floor' && safeFloorIndex === idx;
          const elevation = (fl.floor_index * 3.0).toFixed(1);
          const isGround = fl.floor_index === 0;
          const plateComp = (fl as any).plate_composition || '';
          const tabLabel = plateComp
            ? `${fl.floor_name || `Floor ${fl.floor_index}`}: ${plateComp}`
            : (fl.floor_name || `Floor ${fl.floor_index}`);
          return (
            <button
              key={fl.floor_index}
              type="button"
              data-testid={`tab-floor-${fl.floor_index}`}
              onClick={() => {
                setViewTab('floor');
                setActiveFloorIndex(idx);
              }}
              className={`px-2.5 sm:px-3 py-1 sm:py-1.5 rounded-[8px] sm:rounded-[9px] text-[11px] sm:text-[12px] transition-colors flex items-center gap-1.5 shrink-0 cursor-pointer ${
                isActive
                  ? 'bg-[var(--accent)] text-white shadow-xs font-semibold ring-1 ring-white/20'
                  : 'bg-[var(--fill)] text-[var(--text-2)] hover:text-[var(--text-1)] hover:bg-[var(--fill-hover)] font-medium'
              }`}
            >
              <span>{tabLabel}</span>
              <span
                className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
                  isActive ? 'bg-white/20 text-white' : 'bg-black/5 dark:bg-white/10 text-[var(--text-3)]'
                }`}
              >
                +{elevation}m
              </span>
              {isGround && (
                <span
                  className={`text-[9px] px-1.5 py-0.2 rounded font-bold uppercase tracking-wider ${
                    isActive ? 'bg-amber-400 text-amber-950' : 'bg-amber-500/15 text-[var(--semantic-amber-ink)]'
                  }`}
                >
                  Anchor
                </span>
              )}
            </button>
          );
        })}
      </div>
    );
  };

  return (
    <div
      id="blueprint-viewer-container"
      className="flex flex-col w-full min-w-0 rounded-[16px] vibrancy-panel border border-[var(--panel-border-color)] shadow-md overflow-hidden @container"
    >
      {/* 1. Header: title + visible freshness token + CAD/Storey chip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 sm:gap-2 px-3 sm:px-3.5 py-2 sm:py-2.5 border-b border-[var(--hairline)]">
        <div className="flex items-center justify-between sm:justify-start gap-2 min-w-0 w-full sm:w-auto">
          <div className="flex items-center gap-2 min-w-0">
            <Icon name="blueprint" size={15} className="text-[var(--accent-ink)] shrink-0" />
            <h3 className="text-[13px] sm:text-[15px] font-semibold text-[var(--text-1)] tracking-tight truncate">
              {isMultiStorey && currentFloor ? `${currentFloor.floor_name}` : 'Architectural Blueprint'}
            </h3>
          </div>
          <div className="flex items-center gap-1 shrink-0 sm:hidden">
            {isMultiStorey && currentFloor && (
              <span className="font-mono text-[10px] font-semibold text-[var(--accent-ink)] bg-[var(--accent-tint)] px-1.5 py-0.5 rounded-[5px] whitespace-nowrap">
                +{(currentFloor.floor_index * 3.0).toFixed(1)}m
              </span>
            )}
            <span className="text-[10px] font-semibold text-[var(--accent-ink)] bg-[var(--accent-tint)] px-1.5 py-0.5 rounded-[5px] uppercase tracking-wider whitespace-nowrap">
              {isMultiStorey ? `${multiStorey?.total_storeys}F CAD` : 'CAD 2D'}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap w-full sm:w-auto min-w-0">
          {/* Refusal: a withheld certificate is a header fact, not a detail
              buried in the QA panel.  The plan is still drawn and exported;
              the chip makes sure it is never mistaken for certified. */}
          <PlanVerdictChip
            verdict={planVerdict}
            isValid={multiStorey?.mathematical_certificate?.is_valid}
            gateStatus={multiStorey?.validation_gate?.overall_status}
          />
          {isStale && (
            <span
              data-testid="stale-plan-chip"
              title="Parameters have changed since this blueprint was generated. Please regenerate."
              className="font-mono text-[10px] sm:text-[11px] font-semibold text-amber-800 dark:text-amber-200 bg-amber-500/20 border border-amber-500/40 px-2 py-0.5 rounded-[6px] whitespace-nowrap flex items-center gap-1.5 select-none animate-pulse shadow-xs"
            >
              <Icon name="alert-triangle" size={12} className="text-[var(--semantic-amber-ink)] shrink-0" />
              <span>Parameters changed - regenerate</span>
            </span>
          )}
          <span
            data-testid="blueprint-freshness-token"
            title={`Blueprint Generation Freshness Token (${freshnessToken})`}
            className="font-mono text-[10px] sm:text-[11px] font-semibold text-[var(--accent-ink)] bg-[var(--accent-tint)] px-2 py-0.5 rounded-[6px] border border-[var(--accent)]/20 max-w-full truncate"
          >
            {freshnessToken}
          </span>
          {isMultiStorey && currentFloor && (
            <span className="hidden sm:inline-block font-mono text-[11px] font-semibold text-[var(--accent-ink)] bg-[var(--accent-tint)] px-2 py-0.5 rounded-[6px] whitespace-nowrap">
              +{(currentFloor.floor_index * 3.0).toFixed(1)}m LVL
            </span>
          )}
          <span className="hidden sm:inline-block text-[10px] font-semibold text-[var(--accent-ink)] bg-[var(--accent-tint)] px-1.5 py-0.5 rounded-[6px] uppercase tracking-wider whitespace-nowrap">
            {isMultiStorey ? `${multiStorey?.total_storeys}F CAD` : 'CAD 2D'}
          </span>
        </div>
      </div>

      {/* 2. Generated programme provenance: the blueprint states what it is a
          blueprint OF, not just which parameters were on screen. */}
      {multiStorey && (
        <div
          data-testid="generated-typology-strip"
          className="flex flex-col gap-1 px-3 sm:px-3.5 py-2 border-b border-[var(--hairline)] bg-emerald-500/[0.06]"
        >
          <div className="flex items-center gap-1.5 flex-wrap min-w-0 text-[11px]">
            <span className="font-semibold uppercase tracking-wider text-[var(--text-3)] shrink-0">
              Generated as
            </span>
            <span
              data-testid="generated-typology-badge"
              className="px-2 py-0.5 rounded-[5px] font-mono font-bold text-[10px] bg-emerald-600 text-white tracking-tight select-none"
            >
              {generatedProfile.shortCode}
            </span>
            <span
              data-testid="generated-typology-label"
              className="font-semibold text-[var(--text-1)] truncate"
            >
              {generatedProfile.label}
            </span>
            <span className="text-[10px] text-[var(--text-2)] font-medium">
              {generatedProfile.useClass} · {generatedProfile.occupancy}
            </span>
            {typologyMismatch && (
              <span
                data-testid="generated-typology-mismatch"
                className="px-1.5 py-0.5 rounded-[4px] text-[9px] font-bold uppercase tracking-wider bg-amber-500/20 text-[var(--semantic-amber-ink)] border border-amber-500/40"
              >
                Request now says {getTypologyProfile(requestedTypology).shortCode}
              </span>
            )}
          </div>
          <div className="flex items-center gap-x-2 gap-y-0.5 flex-wrap text-[10px] text-[var(--text-2)] min-w-0">
            <span className="font-mono font-semibold text-[var(--text-1)]">
              {storeyCount <= 1 ? 'G (1 level)' : `G+${storeyCount - 1} (${storeyCount} levels)`}
            </span>
            {generatedGfa > 0 && (
              <span className="font-mono">{generatedGfa.toFixed(1)} m² GFA</span>
            )}
            {generatedUnitCount > 0 && (
              <span>
                {generatedUnitCount} unit{generatedUnitCount === 1 ? '' : 's'} on this floor
              </span>
            )}
            <span data-testid="generated-programme" className="truncate">
              {programmeText ? `Programme: ${programmeText}` : 'Programme: no rooms on this floor'}
            </span>
          </div>
          <p className="text-[10px] leading-snug text-[var(--text-3)] truncate" title={generatedProfile.intent}>
            {generatedProfile.intent}
          </p>
        </div>
      )}

      {/* 3. Storey Switcher Tabs (Rendered when multi-floor) */}
      {renderFloorSwitcher(false)}

      {/* 3. Toolbar row below header */}
      <div className="flex items-center justify-between gap-1.5 sm:gap-2 px-2.5 sm:px-3.5 py-1.5 sm:py-2 border-b border-[var(--hairline)] bg-[var(--fill)]/30 flex-wrap sm:flex-nowrap">
        <div className="flex items-center gap-1.5 sm:gap-2">
          {/* Mode Selector: CAD vs Paper */}
          <div className="flex items-center bg-[var(--fill)] rounded-[8px] sm:rounded-[9px] p-[2px] sm:p-[3px] shadow-[inset_0_1px_2px_rgba(0,0,0,0.06)]">
            <button
              type="button"
              onClick={() => setMode('cad')}
              className={`h-6 px-2 sm:px-2.5 rounded-[6px] sm:rounded-[7px] text-[10px] sm:text-[11px] font-semibold flex items-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50 ${
                mode === 'cad'
                  ? 'bg-[var(--segmented-active-bg)] text-[var(--segmented-active-label)] bw-segmented-active-shadow'
                  : 'text-[var(--text-2)] hover:text-[var(--text-1)]'
              }`}
            >
              CAD
            </button>
            <button
              type="button"
              onClick={() => setMode('paper')}
              className={`h-6 px-2 sm:px-2.5 rounded-[6px] sm:rounded-[7px] text-[10px] sm:text-[11px] font-semibold flex items-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50 ${
                mode === 'paper'
                  ? 'bg-[var(--segmented-active-bg)] text-[var(--segmented-active-label)] bw-segmented-active-shadow'
                  : 'text-[var(--text-2)] hover:text-[var(--text-1)]'
              }`}
            >
              Paper
            </button>
          </div>

          {/* Ghost Core Overlay Toggle (Multi-floor upper storeys) */}
          {isMultiStorey && multiStorey!.floors.length > 1 && (
            <button
              type="button"
              data-testid="ghost-overlay-toggle"
              aria-pressed={showGhostOverlay}
              onClick={() => setShowGhostOverlay((v) => !v)}
              disabled={activeFloorIndex === 0}
              title={
                activeFloorIndex === 0
                  ? 'Ground Floor is the primary Anchor Core (Ghost overlay appears on upper floors)'
                  : showGhostOverlay
                  ? 'Hide F0 Core Ghost Overlay'
                  : 'Show F0 Core Ghost Overlay (Verifying vertical stacking alignment)'
              }
              className={`h-6 sm:h-7 px-2 sm:px-2.5 rounded-[7px] sm:rounded-[9px] text-[10px] sm:text-[11px] font-semibold flex items-center gap-1 sm:gap-1.5 transition-colors duration-150 ease-out cursor-pointer select-none active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50 disabled:active:scale-100 ${
                activeFloorIndex === 0
                  ? 'opacity-50 cursor-not-allowed bg-[var(--fill)] text-[var(--text-3)]'
                  : showGhostOverlay
                  ? 'bg-amber-500/15 text-[var(--semantic-amber-ink)] border border-amber-500/30 shadow-[inset_0_0_0_1px_rgba(245,158,11,0.12),0_1px_3px_rgba(245,158,11,0.15)]'
                  : 'bg-[var(--fill)] text-[var(--text-2)] hover:text-[var(--text-1)] hover:bg-[var(--fill-hover)]'
              }`}
            >
              <Icon
                name="layers"
                size={12}
                className={showGhostOverlay && safeFloorIndex > 0 ? 'text-[var(--semantic-amber-ink)] animate-pulse' : ''}
              />
              <span className="hidden sm:inline">{safeFloorIndex === 0 ? 'F0 Anchor' : showGhostOverlay ? 'Ghost Core: ON' : 'Ghost Core: OFF'}</span>
              <span className="inline sm:hidden">{safeFloorIndex === 0 ? 'Anchor' : showGhostOverlay ? 'Ghost: ON' : 'Ghost: OFF'}</span>
            </button>
          )}
        </div>

        {/* Zoom Controls & Expand Action (segmented cluster) */}
        <div className="flex items-center gap-1.5 sm:gap-2">
          <div className="flex items-center gap-0.5 bg-[var(--fill)] rounded-[8px] sm:rounded-[9px] p-[2px] sm:p-[3px] shadow-[inset_0_1px_2px_rgba(0,0,0,0.06)]">
            <button
              type="button"
              onClick={handleZoomOut}
              disabled={zoom <= 0.75}
              title="Zoom Out"
              aria-label="Zoom Out"
              className="bw-touch-target w-6 h-6 sm:w-7 sm:h-7 rounded-[5px] sm:rounded-[6px] hover:bg-[var(--fill-hover)] disabled:opacity-40 disabled:hover:bg-transparent text-[var(--text-1)] flex items-center justify-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.92] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50"
            >
              <Icon name="minus" size={13} />
            </button>
            <span className="font-mono text-[11px] sm:text-[12px] text-[var(--text-2)] tabular-nums min-w-[32px] sm:min-w-[38px] text-center font-semibold select-none">
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              onClick={handleZoomIn}
              disabled={zoom >= 2.5}
              title="Zoom In"
              aria-label="Zoom In"
              className="bw-touch-target w-6 h-6 sm:w-7 sm:h-7 rounded-[5px] sm:rounded-[6px] hover:bg-[var(--fill-hover)] disabled:opacity-40 disabled:hover:bg-transparent text-[var(--text-1)] flex items-center justify-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.92] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50"
            >
              <Icon name="plus" size={13} />
            </button>
            <button
              type="button"
              onClick={handleReset}
              title="Reset Zoom & Pan"
              aria-label="Reset View"
              className="bw-touch-target w-6 h-6 sm:w-7 sm:h-7 rounded-[5px] sm:rounded-[6px] hover:bg-[var(--fill-hover)] text-[var(--text-1)] flex items-center justify-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.92] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50"
            >
              <Icon name="refresh" size={13} />
            </button>
          </div>

          {/* Quick-Download PDF Dossier Button */}
          <button
            type="button"
            id="blueprint-export-dossier-btn"
            onClick={handleExportPdf}
            disabled={isExportingPdf || isStale}
            title={
              isStale
                ? 'Parameters changed — regenerate blueprint before exporting.'
                : 'Export Multi-Page Architectural PDF Dossier (Cover Sheet 10.0 + Floor Sheets 10.1-10.N)'
            }
            aria-label="Export Dossier (PDF)"
            className={`h-6 sm:h-7 px-2 sm:px-2.5 rounded-[7px] sm:rounded-[9px] text-[10px] sm:text-[11px] font-semibold flex items-center gap-1 sm:gap-1.5 transition-colors duration-150 ease-out select-none ${
              isStale
                ? 'opacity-40 cursor-not-allowed bg-[var(--fill)] text-[var(--text-3)] border border-[var(--hairline)]'
                : 'bg-red-500/10 hover:bg-red-500/20 active:bg-red-500/25 text-red-600 dark:text-red-400 border border-red-500/25 shadow-[inset_0_1px_0_rgba(255,255,255,0.15),0_1px_2px_rgba(220,38,38,0.12)] cursor-pointer active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100'
            }`}
          >
            {isExportingPdf ? (
              <>
                <Icon name="loader" size={12} className="animate-spin text-red-500" />
                <span className="whitespace-nowrap hidden sm:inline">Exporting...</span>
                <span className="whitespace-nowrap inline sm:hidden">...</span>
              </>
            ) : (
              <>
                <Icon name="file-text" size={12} />
                <span className="whitespace-nowrap hidden sm:inline">Export Dossier (PDF)</span>
                <span className="whitespace-nowrap inline sm:hidden">PDF</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={() => setIsModalOpen(true)}
            title="Open Fullscreen Blueprint Modal"
            aria-label="Open Fullscreen Blueprint"
            className="bw-touch-target w-6 h-6 sm:w-8 sm:h-8 rounded-[7px] sm:rounded-[9px] bg-[var(--accent-tint)] text-[var(--accent-ink)] hover:brightness-105 active:scale-[0.92] flex items-center justify-center transition-colors duration-150 ease-out cursor-pointer shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50"
          >
            <Icon name="maximize" size={13} />
          </button>
        </div>
      </div>

      {/* 4. Canvas Preview */}
      <div
        className="relative w-full min-h-[320px] h-[360px] overflow-hidden select-none cursor-pointer group"
        style={{ backgroundColor: 'var(--blueprint-bg)' }}
        onClick={() => {
          // The whole canvas opens the modal — but a drag that ended here is a
          // pan gesture, not a click (mouse and touch alike).
          if (dragMovedRef.current) return;
          setIsModalOpen(true);
        }}
        title="Click to open full-size blueprint modal"
      >
        {/* Subtle grid pattern */}
        <svg
          className="absolute inset-0 w-full h-full pointer-events-none opacity-20"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <pattern id="viewer-ambient-grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="currentColor" strokeWidth="0.5" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#viewer-ambient-grid)" className="text-[var(--hairline)]" />
        </svg>

        {/* Pan & Zoom Transform Wrapper (mouse + touch: the sheet is a
            fixed-fidelity artifact — gestures move the viewport over it) */}
        <div
          ref={cardCanvasRef}
          className="w-full h-full flex items-center justify-center p-3 transition-transform will-change-transform"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: 'center center',
            transition: isPanning ? 'none' : 'transform 0.15s ease-out',
            touchAction: 'none',
          }}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onTouchStart={cardGestures.onTouchStart}
          onTouchMove={cardGestures.onTouchMove}
          onTouchEnd={cardGestures.onTouchEnd}
        >
          {injectReady ? (
            <div
              ref={cardSheetRef}
              className="relative flex items-center justify-center w-full h-full drop-shadow-md"
              dangerouslySetInnerHTML={{ __html: renderSvg }}
            />
          ) : (
            /* Same box, same footprint: the sheet swaps in without moving it. */
            <div
              className="relative flex items-center justify-center w-full h-full"
              aria-busy="true"
              aria-label="Loading floor sheet"
            >
              <div className="report-skeleton w-[240px] h-[300px] rounded-[10px]" />
            </div>
          )}
        </div>

        {/* Expand Sheet cue: always visible — a hover-only affordance would
            never be discovered on touch, and a persistent cue helps everywhere. */}
        <div className="absolute bottom-2.5 right-2.5 px-2.5 py-1 rounded-full vibrancy-pill text-[11px] font-medium text-[var(--text-1)] border border-[var(--panel-border-color)] flex items-center gap-1 shadow-sm pointer-events-none">
          <Icon name="maximize" size={12} className="text-[var(--accent-ink)]" />
          <span>Expand Sheet</span>
        </div>
      </div>

      {/* 5. Per-Floor Room Legend & Site Policy / Wedge Legend */}
      {viewTab === 'site' && effectiveSitePlan ? (
        <div className="flex flex-col gap-2.5 p-3 border-t border-[var(--hairline)] bg-[var(--card-bg-subtle)]/30">
          {/* Drawing Status Stamp */}
          {effectiveSitePlan.drawing_status_stamp && (
            <div className="p-2.5 rounded-[8px] bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 font-mono text-[11px] font-semibold tracking-wide flex items-center gap-2">
              <span className="px-1.5 py-0.5 rounded bg-red-600 text-white text-[9px] font-bold tracking-wider uppercase shrink-0">
                STATUS STAMP
              </span>
              <span className="truncate">{effectiveSitePlan.drawing_status_stamp}</span>
            </div>
          )}

          {/* Derivation Chain Banner */}
          {effectiveSitePlan.derivation_text && (
            <div className="p-2.5 rounded-[8px] bg-[var(--card-bg)] border border-[var(--hairline)] flex flex-col gap-1 text-[11px]">
              <div className="flex items-center gap-2">
                <span className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider bg-sky-500/20 text-sky-700 dark:text-sky-300">
                  Derivation Chain
                </span>
                <span className="font-mono text-[11px] text-[var(--text-1)] font-medium">
                  {effectiveSitePlan.derivation_text}
                </span>
              </div>
              {effectiveSitePlan.derivation_chain && effectiveSitePlan.derivation_chain.length > 0 && (
                <div className="flex items-center gap-1.5 text-[10px] font-mono text-[var(--text-3)] overflow-x-auto py-0.5">
                  {effectiveSitePlan.derivation_chain.map((step, idx) => (
                    <React.Fragment key={idx}>
                      <span className="px-1.5 py-0.5 rounded bg-[var(--fill)] border border-[var(--hairline)] text-[var(--text-2)] whitespace-nowrap">
                        {step}
                      </span>
                      {idx < (effectiveSitePlan.derivation_chain?.length ?? 0) - 1 && (
                        <Icon name="chevron-right" size={10} className="text-[var(--text-3)] inline-block align-middle" />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Parking Envelope & ECS Coexistence */}
          {effectiveSitePlan.parking && (
            <div className={`p-2.5 rounded-[8px] border text-[11px] flex flex-col gap-1.5 ${
              effectiveSitePlan.parking.coexistence_status === 'COEXISTENT'
                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-800 dark:text-emerald-200'
                : 'bg-amber-500/10 border-amber-500/30 text-amber-800 dark:text-amber-200'
            }`}>
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <span className={`inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider ${
                    effectiveSitePlan.parking.coexistence_status === 'COEXISTENT'
                      ? 'bg-emerald-500/25 text-emerald-800 dark:text-emerald-200'
                      : 'bg-amber-500/25 text-amber-800 dark:text-amber-200'
                  }`}>
                    Parking ({effectiveSitePlan.parking.provided_ecs}/{effectiveSitePlan.parking.required_ecs} ECS)
                    {ECS_DISCLOSURE}
                  </span>
                  <span className="font-medium text-[var(--text-1)]">
                    {effectiveSitePlan.parking.bays.length} Bays (2.5m x 5.0m) + Drive Aisle ({effectiveSitePlan.parking.drive_aisle_width_m}m)
                  </span>
                </div>
                <span className="text-[10px] font-mono font-medium">
                  {effectiveSitePlan.parking.total_parking_area_sqm.toFixed(1)} m²
                </span>
              </div>
              {effectiveSitePlan.parking.deficit_warning && (
                <div className="text-[11px] font-medium text-[var(--semantic-amber-ink)] flex items-start gap-1.5 bg-amber-500/10 p-2 rounded border border-amber-500/20">
                  <Icon name="alert-triangle" size={13} className="shrink-0 text-[var(--semantic-amber-ink)] mt-0.5" />
                  <div>
                    <p className="font-semibold">{effectiveSitePlan.parking.deficit_warning}</p>
                    {effectiveSitePlan.parking.coexistence_options && effectiveSitePlan.parking.coexistence_options.length > 0 && (
                      <ul className="list-disc list-inside mt-1 space-y-0.5 text-[10px]">
                        {effectiveSitePlan.parking.coexistence_options.map((opt, oIdx) => (
                          <li key={oIdx}>{opt}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Declared Policy */}
          {effectiveSitePlan.design_policy && (
            <div className="flex flex-col gap-1 p-2.5 rounded-[10px] bg-amber-500/10 border border-amber-500/20 text-[12px]">
              <div className="flex items-center gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider bg-amber-500/25 text-amber-800 dark:text-amber-200">
                  Declared Policy
                </span>
                <span className="font-semibold text-[var(--text-1)]">
                  {effectiveSitePlan.design_policy}
                </span>
              </div>
              {effectiveSitePlan.design_policy_rationale && (
                <span className="text-[11px] text-[var(--text-2)] pl-1">
                  Rationale: {effectiveSitePlan.design_policy_rationale}
                </span>
              )}
              {effectiveSitePlan.waste_warning_triggered && (
                <span className="text-[11px] font-medium text-[var(--semantic-amber-ink)] pl-1 flex items-center gap-1 mt-0.5">
                  <Icon name="alert-triangle" size={12} className="shrink-0 text-[var(--semantic-amber-ink)]" />
                  Best orthogonal footprint wastes {effectiveSitePlan.waste_pct?.toFixed(1)}% of buildable area (&gt;25%). Plot rotation alternatives evaluated; functional wedge absorption active.
                </span>
              )}
            </div>
          )}

          {/* Functional Wedges */}
          {effectiveSitePlan.wedge_zones && effectiveSitePlan.wedge_zones.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-semibold text-[var(--text-3)] uppercase tracking-wider">
                Functional Wedges ({effectiveSitePlan.wedge_zones.length}):
              </span>
              {effectiveSitePlan.wedge_zones.map((wz) => (
                <div
                  key={wz.wedge_id}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium whitespace-nowrap select-none border border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-200"
                >
                  <span className="w-2.5 h-2.5 rounded-full shrink-0 bg-amber-500" />
                  <span className="text-[11px] font-mono font-semibold opacity-75">{wz.wedge_id}</span>
                  <span className="text-[12px] font-medium">{wz.name}</span>
                  <span className="text-[11px] font-mono opacity-80">{wz.area_sqm.toFixed(1)}m²</span>
                  <span className="text-[9px] px-1 py-0.2 rounded font-bold uppercase tracking-wider bg-amber-500/20 text-[var(--semantic-amber-ink)]">
                    {wz.is_enclosed_storage ? 'Enclosed Storage' : 'Non-Carpet'}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* 8-Point Site Sheet Completeness Checklist */}
          {effectiveSitePlan.checklist && (
            <div className="flex items-center gap-2 overflow-x-auto py-1 text-[10px] font-mono border-t border-[var(--hairline)]/40 pt-2">
              <span className="font-semibold text-[var(--text-3)] uppercase tracking-wider shrink-0">8-Pt Checklist:</span>
              {Object.entries(effectiveSitePlan.checklist).map(([key, val]) => (
                <span
                  key={key}
                  className={`px-1.5 py-0.5 rounded whitespace-nowrap border ${
                    val
                      ? 'bg-emerald-500/10 text-[var(--semantic-green-ink)] border-emerald-500/30'
                      : 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/30'
                  }`}
                >
                  {val ? (
                    <Icon name="check" size={11} className="inline-block align-[-2px] text-[var(--semantic-green-ink)]" />
                  ) : (
                    <Icon name="x" size={11} className="inline-block align-[-2px] text-[var(--semantic-red-ink)]" />
                  )}{' '}
                  {key.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          )}

          {/* Annotation Status Taxonomy Legend */}
          <div className="flex flex-wrap items-center gap-2 pt-1.5 border-t border-[var(--hairline)]/50 text-[10px]">
            <span className="font-semibold text-[var(--text-3)] uppercase tracking-wider">Status Taxonomy:</span>
            <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-[var(--semantic-green-ink)] font-mono font-semibold border border-emerald-500/30">
              VERIFIED: Closed Polygon
            </span>
            <span className="px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-700 dark:text-blue-300 font-mono font-semibold border border-blue-500/30">
              CALCULATED: Formula / Setback
            </span>
            <span className="px-1.5 py-0.5 rounded bg-amber-500/15 text-[var(--semantic-amber-ink)] font-mono font-semibold border border-amber-500/30">
              ASSUMED: Inferred Boundary
            </span>
            <span className="px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-700 dark:text-purple-300 font-mono font-semibold border border-purple-500/30">
              RECOMMENDED: Best-Practice Access
            </span>
          </div>
        </div>
      ) : currentPlacements.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 p-3 border-t border-[var(--hairline)] bg-[var(--card-bg-subtle)]/30">
          <div className="flex items-center gap-1.5 mr-1 shrink-0">
            <span className="text-[11px] font-semibold text-[var(--text-3)] uppercase tracking-wider">
              {currentFloor ? `${currentFloor.floor_name}:` : 'Legend:'}
            </span>
            {currentFloor && (
              <span className="text-[10px] text-[var(--text-3)] font-mono">
                ({currentFloor.rooms.length} zones)
              </span>
            )}
          </div>
          {currentPlacements.map((p, pIdx) => {
            const baseRoomId = p.room_id.replace(/_F\d+$/, '');
            const isTerraceBand = baseRoomId === 'terrace_band' || baseRoomId.includes('terrace') || (p as any).zone_category === 'terrace';
            const isBalcony = baseRoomId === 'balcony' || baseRoomId === 'apt_balcony';

            const meta = ROOM_METADATA[p.room_id] || ROOM_METADATA[baseRoomId] || {
              dotColor: p.is_core ? '#8B5CF6' : (isTerraceBand ? '#0EA5E9' : (isBalcony ? '#10B981' : '#64748B')),
              label: p.room_name,
              zone: p.zone,
            };
            const chipDotColor = isTerraceBand ? '#0EA5E9' : (isBalcony ? '#10B981' : meta.dotColor);
            const chipLabel = isTerraceBand ? 'Open Terrace / Sky Deck' : (isBalcony ? 'Covered Balcony' : (meta.label || p.room_name));
            const chipZone = isTerraceBand ? 'TERRACE' : (isBalcony ? (p.zone || 'NE') : (meta.zone || p.zone));

            return (
              <button
                type="button"
                key={`${p.room_id}-${pIdx}`}
                data-testid={`room-chip-${p.room_id}`}
                aria-pressed={activeRoomId === p.room_id}
                onClick={() => setSelectedRoomId((current) => (current === p.room_id ? null : p.room_id))}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium whitespace-nowrap select-none border transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50 ${
                  activeRoomId === p.room_id
                    ? 'ring-2 ring-[var(--accent)]/60 border-[var(--accent)]/60'
                    : ''
                } ${
                  p.is_core
                    ? 'bg-purple-500/10 border-purple-500/30 text-purple-700 dark:text-purple-300'
                    : isTerraceBand
                    ? 'bg-sky-500/10 border-sky-500/30 text-sky-800 dark:text-sky-200'
                    : 'bg-[var(--fill)] border-transparent text-[var(--text-1)]'
                }`}
              >
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0 shadow-2xs"
                  style={{ backgroundColor: chipDotColor }}
                />
                <span className="text-[11px] font-mono font-semibold opacity-75">[{pIdx + 1}]</span>
                <span className="text-[12px] font-medium">{chipLabel}</span>
                {p.area_sqm !== undefined && (
                  <span className="text-[11px] font-mono opacity-75">{p.area_sqm.toFixed(2)}m²</span>
                )}
                <span className="text-[10px] text-[var(--text-3)] font-normal">({chipZone})</span>
                {p.is_core && (
                  <span className="text-[9px] px-1 py-0.2 rounded font-bold uppercase bg-purple-500/20 text-purple-600 dark:text-purple-300 tracking-wider">
                    Core
                  </span>
                )}
                {isTerraceBand && (
                  <span className="text-[9px] px-1.5 py-0.2 rounded font-bold uppercase bg-sky-500/20 text-sky-700 dark:text-sky-300 tracking-wider">
                    TERRACE / Non-Carpet
                  </span>
                )}
              </button>
            );
          })}
          {selectedRoom && (
            <div
              data-testid="room-inspector"
              className="w-full mt-1 rounded-[10px] border border-[var(--hairline)] bg-[var(--card-bg)] p-2.5 space-y-2"
            >
              <div className="flex items-start justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-1.5 flex-wrap min-w-0">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0 bg-emerald-500" />
                  <span className="text-[12px] font-semibold text-[var(--text-1)]">
                    {selectedRoom.identity?.name || selectedRoom.room_name}
                  </span>
                  <span className="text-[10px] font-mono text-[var(--text-3)]">
                    {selectedRoom.space_type_id || selectedRoom.identity?.space_type_id || selectedRoom.room_id}
                  </span>
                  {selectedRoom.unit_id && (
                    <span className="text-[9px] px-1 py-0.2 rounded bg-sky-500/15 text-sky-700 dark:text-sky-300 font-semibold uppercase tracking-wider">
                      {selectedRoom.unit_id}
                    </span>
                  )}
                  {selectedRoom.identity?.is_wet && (
                    <span className="text-[9px] px-1 py-0.2 rounded bg-cyan-500/15 text-cyan-700 dark:text-cyan-300 font-semibold uppercase tracking-wider">
                      Wet room
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  data-testid="room-inspector-close"
                  onClick={() => setSelectedRoomId(null)}
                  className="w-5 h-5 rounded-[5px] hover:bg-[var(--fill-hover)] text-[var(--text-2)] flex items-center justify-center cursor-pointer shrink-0"
                  aria-label="Close room inspector"
                >
                  <Icon name="x" size={11} />
                </button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 text-[10px]">
                <div className="rounded-[6px] bg-[var(--fill)]/70 px-2 py-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-[var(--text-3)]">Clear area</div>
                  <div className="font-mono font-semibold text-[var(--text-1)]">
                    {(selectedRoomClearArea ?? selectedRoom.area_sqm).toFixed(2)} m²
                  </div>
                </div>
                <div className="rounded-[6px] bg-[var(--fill)]/70 px-2 py-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-[var(--text-3)]">Gross allocation</div>
                  <div className="font-mono font-semibold text-[var(--text-1)]">{selectedRoom.area_sqm.toFixed(2)} m²</div>
                </div>
                <div className="rounded-[6px] bg-[var(--fill)]/70 px-2 py-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-[var(--text-3)]">Code minimum</div>
                  <div className="font-mono font-semibold text-[var(--text-1)]">
                    {selectedRoom.identity ? `${selectedRoom.identity.min_area_sqm.toFixed(1)} m² / ${selectedRoom.identity.min_width_m.toFixed(1)} m` : 'Not resolved'}
                  </div>
                </div>
                <div className="rounded-[6px] bg-[var(--fill)]/70 px-2 py-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-[var(--text-3)]">Envelope</div>
                  <div className="font-mono font-semibold text-[var(--text-1)]">
                    {selectedRoom.width_m.toFixed(2)} × {selectedRoom.depth_m.toFixed(2)} m
                  </div>
                </div>
                <div className="rounded-[6px] bg-[var(--fill)]/70 px-2 py-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-[var(--text-3)]">Hygiene</div>
                  <div className="font-semibold text-[var(--text-1)] capitalize">
                    {selectedRoom.identity?.hygiene_class || 'unclassified'}
                  </div>
                </div>
                <div className="rounded-[6px] bg-[var(--fill)]/70 px-2 py-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-[var(--text-3)]">Ventilation</div>
                  <div className="font-semibold text-[var(--text-1)]">{selectedRoomVentilation}</div>
                </div>
                <div className="rounded-[6px] bg-[var(--fill)]/70 px-2 py-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-[var(--text-3)]">Furniture</div>
                  <div className={`font-semibold ${selectedRoomFurniture.length === 0 ? 'text-[var(--text-3)]' : selectedRoomFurnitureOk ? 'text-[var(--semantic-green-ink)]' : 'text-[var(--semantic-amber-ink)]'}`}>
                    {selectedRoomFurniture.length === 0 ? 'None required' : `${selectedRoomFurniture.length} placed${selectedRoomFurnitureOk ? '' : ' · short'}`}
                  </div>
                </div>
                <div className="rounded-[6px] bg-[var(--fill)]/70 px-2 py-1.5">
                  <div className="text-[9px] uppercase tracking-wider text-[var(--text-3)]">Openings / shafts</div>
                  <div className="font-semibold text-[var(--text-1)]">
                    {selectedRoomWindows.length} win · {selectedRoomDoors.length} door · {selectedRoomShafts.length} shaft
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-wrap text-[10px] text-[var(--text-2)]">
                <span className="font-mono">{selectedRoom.fixtures?.length || 0} fixtures</span>
                <span className="text-[var(--text-3)]">•</span>
                <span>{selectedRoom.identity?.daylight_req ? 'Daylight required' : 'Daylight not required'}</span>
                <span className="text-[var(--text-3)]">•</span>
                <span>{selectedRoom.identity?.clear_area_basis ? `${selectedRoom.identity.clear_area_basis} basis` : 'area basis unresolved'}</span>
                {selectedRoom.orientation_rationale && (
                  <>
                    <span className="text-[var(--text-3)]">•</span>
                    <span className="truncate" title={selectedRoom.orientation_rationale}>{selectedRoom.orientation_rationale}</span>
                  </>
                )}
              </div>
            </div>
          )}
          {safeFloorIndex === 0 && effectiveSitePlan?.wedge_zones?.filter(w => w.is_interior_side).map((wz) => (
            <div
              key={`interior-wedge-${wz.wedge_id}`}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium whitespace-nowrap select-none border border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-200"
            >
              <span className="w-2.5 h-2.5 rounded-full shrink-0 bg-amber-500" />
              <span className="text-[11px] font-mono font-semibold opacity-75">[{wz.wedge_id}]</span>
              <span className="text-[12px] font-medium">{wz.name}</span>
              <span className="text-[11px] font-mono opacity-80">{wz.area_sqm.toFixed(1)}m²</span>
              <span className="text-[9px] px-1 py-0.2 rounded font-bold uppercase tracking-wider bg-amber-500/20 text-[var(--semantic-amber-ink)]">
                {wz.is_enclosed_storage ? 'Enclosed BUA' : 'Non-Carpet Wedge'}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 6. macOS-Style Fullscreen Sheet Modal */}
      {isModalOpen &&
        ReactDOM.createPortal(
          <div
            className="fixed inset-0 z-[2000] bg-black/50 backdrop-blur-[20px] flex items-center justify-center p-3 sm:p-6 animate-fade-in"
            onClick={() => setIsModalOpen(false)}
          >
            <div
              className="vibrancy-panel rounded-[20px] max-w-[92vw] max-h-[88vh] w-full h-full flex flex-col shadow-2xl border border-[var(--panel-border-color)] overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Modal Header */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 px-3 sm:px-5 py-2.5 sm:py-3 border-b border-[var(--hairline)]">
                <div className="flex items-center justify-between sm:justify-start gap-3 min-w-0 w-full sm:w-auto">
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="w-8 h-8 rounded-[10px] bg-[var(--accent-tint)] text-[var(--accent-ink)] flex items-center justify-center shrink-0">
                      <Icon name="blueprint" size={16} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <h3 className="text-[14px] sm:text-[16px] font-semibold text-[var(--text-1)] tracking-tight whitespace-nowrap">
                          {isMultiStorey && currentFloor ? `${currentFloor.floor_name}` : 'Architectural Floor Plan'}
                        </h3>
                        {isStale && (
                          <span
                            data-testid="modal-stale-plan-chip"
                            title="Parameters changed — regenerate blueprint before exporting."
                            className="font-mono text-[10px] sm:text-[11px] font-semibold text-amber-800 dark:text-amber-200 bg-amber-500/20 border border-amber-500/40 px-1.5 py-0.5 rounded-[6px] whitespace-nowrap flex items-center gap-1 select-none animate-pulse"
                          >
                            <Icon name="alert-triangle" size={11} className="text-[var(--semantic-amber-ink)] shrink-0" />
                            <span>Parameters changed</span>
                          </span>
                        )}
                        <span
                          data-testid="modal-blueprint-freshness-token"
                          className="font-mono text-[10px] sm:text-[11px] font-semibold text-[var(--accent-ink)] bg-[var(--accent-tint)] px-1.5 py-0.5 rounded-[6px] whitespace-nowrap border border-[var(--accent)]/20 max-w-[180px] sm:max-w-xs truncate"
                        >
                          {freshnessToken}
                        </span>
                        {multiStorey && (
                          <span
                            data-testid="modal-generated-typology-chip"
                            title={generatedProfile.intent}
                            className="font-mono text-[10px] font-semibold text-emerald-800 dark:text-emerald-200 bg-emerald-500/15 border border-emerald-500/30 px-1.5 py-0.5 rounded-[6px] whitespace-nowrap"
                          >
                            {generatedProfile.shortCode}
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] sm:text-[12px] text-[var(--text-2)] truncate">
                        {isMultiStorey ? `Multi-Storey CAD Drafting (${multiStorey?.total_storeys} Levels)` : 'CAD 2D Drafting (Single Level Ground)'} &bull; {(plotWidthM || 10).toFixed(1)}m x {(plotDepthM || 12).toFixed(1)}m Grid
                        {isMultiStorey && currentFloor && ` • Elevation +${(currentFloor.floor_index * 3.0).toFixed(1)}m`}
                      </p>
                    </div>
                  </div>
                  {/* Mobile-only close button */}
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="sm:hidden w-8 h-8 rounded-[9px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-2)] hover:text-[var(--text-1)] flex items-center justify-center transition-colors duration-150 cursor-pointer active:scale-[0.92] shrink-0"
                    aria-label="Close modal"
                  >
                    <Icon name="x" size={16} />
                  </button>
                </div>

                <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap sm:flex-nowrap justify-between sm:justify-end w-full sm:w-auto">
                  {/* Mode switcher in modal */}
                  <div className="flex items-center bg-[var(--fill)] rounded-[8px] sm:rounded-[9px] p-[2px] sm:p-[3px] mr-1 shadow-[inset_0_1px_2px_rgba(0,0,0,0.06)]">
                    <button
                      type="button"
                      onClick={() => setMode('cad')}
                      className={`h-6 px-2.5 sm:px-3 rounded-[6px] sm:rounded-[7px] text-[11px] sm:text-[12px] font-semibold flex items-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50 ${
                        mode === 'cad'
                          ? 'bg-[var(--segmented-active-bg)] text-[var(--segmented-active-label)] bw-segmented-active-shadow'
                          : 'text-[var(--text-2)] hover:text-[var(--text-1)]'
                      }`}
                    >
                      CAD
                    </button>
                    <button
                      type="button"
                      onClick={() => setMode('paper')}
                      className={`h-6 px-2.5 sm:px-3 rounded-[6px] sm:rounded-[7px] text-[11px] sm:text-[12px] font-semibold flex items-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50 ${
                        mode === 'paper'
                          ? 'bg-[var(--segmented-active-bg)] text-[var(--segmented-active-label)] bw-segmented-active-shadow'
                          : 'text-[var(--text-2)] hover:text-[var(--text-1)]'
                      }`}
                    >
                      Paper
                    </button>
                  </div>

                  {/* Ghost Core Toggle in Modal */}
                  {isMultiStorey && multiStorey!.floors.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setShowGhostOverlay((v) => !v)}
                      disabled={safeFloorIndex === 0}
                      title={
                        safeFloorIndex === 0
                          ? 'Ground Floor is the primary Anchor Core'
                          : showGhostOverlay
                          ? 'Hide F0 Core Ghost Overlay'
                          : 'Show F0 Core Ghost Overlay'
                      }
                      className={`h-7 sm:h-8 px-2 sm:px-2.5 rounded-[8px] sm:rounded-[9px] text-[10px] sm:text-[11px] font-semibold flex items-center gap-1 sm:gap-1.5 transition-colors duration-150 ease-out cursor-pointer mr-1 select-none active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50 disabled:active:scale-100 ${
                        safeFloorIndex === 0
                          ? 'opacity-50 cursor-not-allowed bg-[var(--fill)] text-[var(--text-3)]'
                          : showGhostOverlay
                          ? 'bg-amber-500/15 text-[var(--semantic-amber-ink)] border border-amber-500/30 shadow-[inset_0_0_0_1px_rgba(245,158,11,0.12),0_1px_3px_rgba(245,158,11,0.15)]'
                          : 'bg-[var(--fill)] text-[var(--text-2)] hover:text-[var(--text-1)] hover:bg-[var(--fill-hover)]'
                      }`}
                    >
                      <Icon
                        name="layers"
                        size={12}
                        className={showGhostOverlay && safeFloorIndex > 0 ? 'text-[var(--semantic-amber-ink)] animate-pulse' : ''}
                      />
                      <span className="hidden sm:inline">{safeFloorIndex === 0 ? 'F0 Anchor' : showGhostOverlay ? 'Ghost: ON' : 'Ghost: OFF'}</span>
                      <span className="inline sm:hidden">{safeFloorIndex === 0 ? 'Anchor' : showGhostOverlay ? 'Ghost: ON' : 'Ghost: OFF'}</span>
                    </button>
                  )}

                  {/* Modal Zoom Controls (segmented cluster) */}
                  <div className="flex items-center gap-0.5 bg-[var(--fill)] rounded-[8px] sm:rounded-[9px] p-[2px] sm:p-[3px] mr-1 sm:mr-2 shadow-[inset_0_1px_2px_rgba(0,0,0,0.06)]">
                    <button
                      type="button"
                      onClick={handleModalZoomOut}
                      disabled={modalZoom <= 0.5}
                      title="Zoom Out"
                      aria-label="Zoom Out"
                      className="bw-touch-target w-6 h-6 sm:w-7 sm:h-8 rounded-[5px] sm:rounded-[6px] hover:bg-[var(--fill-hover)] disabled:opacity-40 disabled:hover:bg-transparent text-[var(--text-1)] flex items-center justify-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.92] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50"
                    >
                      <Icon name="minus" size={13} />
                    </button>
                    <span className="font-mono text-[11px] sm:text-[12px] text-[var(--text-2)] tabular-nums min-w-[34px] sm:min-w-[40px] text-center font-semibold select-none">
                      {Math.round(modalZoom * 100)}%
                    </span>
                    <button
                      type="button"
                      onClick={handleModalZoomIn}
                      disabled={modalZoom >= 3.5}
                      title="Zoom In"
                      aria-label="Zoom In"
                      className="bw-touch-target w-6 h-6 sm:w-7 sm:h-8 rounded-[5px] sm:rounded-[6px] hover:bg-[var(--fill-hover)] disabled:opacity-40 disabled:hover:bg-transparent text-[var(--text-1)] flex items-center justify-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.92] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50"
                    >
                      <Icon name="plus" size={13} />
                    </button>
                    <button
                      type="button"
                      onClick={handleModalReset}
                      title="Reset View"
                      aria-label="Reset View"
                      className="bw-touch-target w-6 h-6 sm:w-7 sm:h-8 rounded-[5px] sm:rounded-[6px] hover:bg-[var(--fill-hover)] text-[var(--text-1)] flex items-center justify-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.92] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50"
                    >
                      <Icon name="refresh" size={13} />
                    </button>
                  </div>

                  {/* Export Dossier (PDF) Button in Modal */}
                  <button
                    type="button"
                    onClick={handleExportPdf}
                    disabled={isExportingPdf || isStale}
                    title={
                      isStale
                        ? 'Parameters changed — regenerate blueprint before exporting.'
                        : 'Export Multi-Page Architectural PDF Dossier'
                    }
                    className={`h-7 sm:h-8 px-2 sm:px-3 rounded-[8px] sm:rounded-[9px] text-[11px] sm:text-[12px] font-semibold flex items-center gap-1 sm:gap-1.5 transition-colors duration-150 ease-out mr-1 sm:mr-2 select-none ${
                      isStale
                        ? 'opacity-40 cursor-not-allowed bg-[var(--fill)] text-[var(--text-3)] border border-[var(--hairline)]'
                        : 'bg-red-500/10 hover:bg-red-500/20 active:bg-red-500/25 text-red-600 dark:text-red-400 border border-red-500/25 shadow-[inset_0_1px_0_rgba(255,255,255,0.15),0_1px_2px_rgba(220,38,38,0.15)] cursor-pointer active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100'
                    }`}
                  >
                    {isExportingPdf ? (
                      <>
                        <Icon name="loader" size={13} className="animate-spin text-red-500" />
                        <span className="whitespace-nowrap hidden sm:inline">Exporting PDF...</span>
                        <span className="whitespace-nowrap inline sm:hidden">...</span>
                      </>
                    ) : (
                      <>
                        <Icon name="file-text" size={13} />
                        <span className="whitespace-nowrap hidden sm:inline">Export Dossier (PDF)</span>
                        <span className="whitespace-nowrap inline sm:hidden">PDF</span>
                      </>
                    )}
                  </button>

                  {/* Export SVG Button */}
                  <button
                    type="button"
                    onClick={handleDownloadSvg}
                    disabled={isStale}
                    title={
                      isStale
                        ? 'Parameters changed — regenerate blueprint before exporting.'
                        : 'Export SVG'
                    }
                    className={`h-7 sm:h-8 px-2.5 sm:px-3.5 rounded-[8px] sm:rounded-[9px] text-[11px] sm:text-[12px] font-semibold flex items-center gap-1 sm:gap-1.5 transition-colors duration-150 ease-out select-none mr-1 sm:mr-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/60 ${
                      isStale
                        ? 'opacity-40 cursor-not-allowed bg-[var(--fill)] text-[var(--text-3)] border border-[var(--hairline)]'
                        : 'bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] active:scale-[0.97] cursor-pointer shadow-[0_1px_3px_rgba(0,113,227,0.35)]'
                    }`}
                  >
                    <Icon name="download" size={13} />
                    <span className="whitespace-nowrap hidden sm:inline">Export SVG</span>
                    <span className="whitespace-nowrap inline sm:hidden">SVG</span>
                  </button>

                  {/* Close Button on Desktop */}
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="hidden sm:flex w-8 h-8 rounded-[9px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-2)] hover:text-[var(--text-1)] items-center justify-center transition-colors duration-150 ease-out cursor-pointer active:scale-[0.92] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/50"
                    aria-label="Close modal"
                  >
                    <Icon name="x" size={16} />
                  </button>
                </div>
              </div>

              {/* Modal Storey Switcher Tabs */}
              {renderFloorSwitcher(true)}

              {/* Modal Body Canvas */}
              <div
                ref={modalCanvasRef}
                className="relative flex-1 w-full overflow-hidden select-none"
                style={{ backgroundColor: 'var(--blueprint-bg)', touchAction: 'none' }}
                onMouseDown={handleModalMouseDown}
                onMouseMove={handleModalMouseMove}
                onMouseUp={handleModalMouseUp}
                onTouchStart={modalGestures.onTouchStart}
                onTouchMove={modalGestures.onTouchMove}
                onTouchEnd={modalGestures.onTouchEnd}
              >
                <div
                  className="w-full h-full flex items-center justify-center p-8 transition-transform will-change-transform"
                  style={{
                    transform: `translate(${modalPan.x}px, ${modalPan.y}px) scale(${modalZoom})`,
                    transformOrigin: 'center center',
                    transition: isModalPanning ? 'none' : 'transform 0.15s ease-out',
                    cursor: isModalPanning ? 'grabbing' : 'grab',
                  }}
                >
                  <div
                    ref={modalSheetRef}
                    className="relative flex items-center justify-center w-full h-full drop-shadow-xl"
                    dangerouslySetInnerHTML={{ __html: sanitizedSvg }}
                  />
                </div>
              </div>

              {/* Modal Footer Legend */}
              {viewTab === 'site' && effectiveSitePlan ? (
                <div className="flex flex-col gap-1.5 p-3 border-t border-[var(--hairline)] bg-[var(--fill)]/20 text-[11px]">
                  {effectiveSitePlan.drawing_status_stamp && (
                    <div className="font-mono text-red-600 dark:text-red-400 font-semibold truncate flex items-center gap-1.5">
                      <span className="px-1.5 py-0.5 rounded bg-red-600 text-white text-[9px] font-bold tracking-wider uppercase">
                        STAMP
                      </span>
                      <span>{effectiveSitePlan.drawing_status_stamp}</span>
                    </div>
                  )}
                  {effectiveSitePlan.derivation_text && (
                    <div className="font-mono text-[var(--text-2)] truncate">
                      {effectiveSitePlan.derivation_text}
                    </div>
                  )}
                </div>
              ) : currentPlacements.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 p-3 border-t border-[var(--hairline)] bg-[var(--fill)]/20">
                  <div className="flex items-center gap-1 mr-1">
                    <span className="text-[11px] font-semibold text-[var(--text-3)] uppercase tracking-wider">
                      {currentFloor ? `${currentFloor.floor_name} Zones:` : 'Spatial Allocations:'}
                    </span>
                    {currentFloor && (
                      <span className="text-[10px] text-[var(--text-3)] font-mono">
                        ({currentFloor.rooms.length} spaces)
                      </span>
                    )}
                  </div>
                  {currentPlacements.map((p, pIdx) => {
                    const baseRoomId = p.room_id.replace(/_F\d+$/, '');
                    const isTerraceBand = baseRoomId === 'terrace_band' || baseRoomId.includes('terrace') || (p as any).zone_category === 'terrace';
                    const isBalcony = baseRoomId === 'balcony' || baseRoomId === 'apt_balcony';

                    const meta = ROOM_METADATA[p.room_id] || ROOM_METADATA[baseRoomId] || {
                      dotColor: p.is_core ? '#8B5CF6' : (isTerraceBand ? '#0EA5E9' : (isBalcony ? '#10B981' : '#64748B')),
                      label: p.room_name,
                      zone: p.zone,
                    };
                    const chipDotColor = isTerraceBand ? '#0EA5E9' : (isBalcony ? '#10B981' : meta.dotColor);
                    const chipLabel = isTerraceBand ? 'Open Terrace / Sky Deck' : (isBalcony ? 'Covered Balcony' : (meta.label || p.room_name));
                    const chipZone = isTerraceBand ? 'TERRACE' : (isBalcony ? (p.zone || 'NE') : (meta.zone || p.zone));

                    return (
                      <div
                        key={`modal-legend-${p.room_id}-${pIdx}`}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[12px] font-medium whitespace-nowrap select-none border ${
                          p.is_core
                            ? 'bg-purple-500/10 border-purple-500/30 text-purple-700 dark:text-purple-300'
                            : isTerraceBand
                            ? 'bg-sky-500/10 border-sky-500/30 text-sky-800 dark:text-sky-200'
                            : 'bg-[var(--fill)] border-transparent text-[var(--text-1)]'
                        }`}
                      >
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0 shadow-2xs"
                          style={{ backgroundColor: chipDotColor }}
                        />
                        <span className="text-[11px] font-mono font-semibold opacity-75">[{pIdx + 1}]</span>
                        <span className="text-[12px] font-medium">{chipLabel}</span>
                        {p.area_sqm !== undefined && (
                          <span className="text-[11px] font-mono opacity-80">{p.area_sqm.toFixed(1)}m²</span>
                        )}
                        <span className="text-[11px] text-[var(--text-3)] font-normal">({chipZone})</span>
                        {p.is_core && (
                          <span className="text-[9px] px-1 py-0.2 rounded font-bold uppercase bg-purple-500/20 text-purple-600 dark:text-purple-300 tracking-wider">
                            Core
                          </span>
                        )}
                        {isTerraceBand && (
                          <span className="text-[9px] px-1.5 py-0.2 rounded font-bold uppercase bg-sky-500/20 text-sky-700 dark:text-sky-300 tracking-wider">
                            TERRACE / Non-Carpet
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>,
          document.body
        )}
    </div>
  );
};

