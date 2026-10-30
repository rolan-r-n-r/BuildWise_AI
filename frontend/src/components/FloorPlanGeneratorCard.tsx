import React, { useState, useEffect, useRef } from 'react';
import type { FloorPlanRequest, FloorPlanResponse, AnalysisParams, FloorPlanParamsSnapshot, PlotPolygon } from '../services/types';
import { planVerdictBadge } from '../services/planWarnings';
import { WarningReportView } from './report/WarningReportView';
import { PlanAdvisorPanel } from './report/PlanAdvisorPanel';
import {
  buildWarningReport,
  collectRelaxations,
  truthInputForPlan,
} from '../services/warningReport';
import type { RemediationOption } from '../services/types';
import { generateFloorPlan } from '../services/api';
import { BlueprintViewer } from './BlueprintViewer';
import { Icon } from './Icon';
import {
  buildPlotPolygonPayload,
  metricsFor,
  type SharedBoundaryState,
} from '../services/siteBoundary';
import { ConstraintChips } from './ConstraintChips';
import { SegmentedControl } from '../design';
import { Skeleton } from './report/Skeleton';

/**
 * A generation request that never answers must not leave the card spinning
 * forever. 120 s is well above the
 * engine's observed worst case (the whole funnel waits 60 s for a solve) and
 * still bounded. Abort is an explicit, disclosed failure: nothing is drawn and
 * the previous plan stays on screen.
 */
const GENERATION_TIMEOUT_MS = 120_000;

/** Dev-only test seam so the timeout branch can be exercised without waiting 2 min. */
function generationTimeoutMs(): number {
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const override = Number((window as unknown as { __bwGenerationTimeoutMs?: number }).__bwGenerationTimeoutMs);
    if (Number.isFinite(override) && override > 0) return override;
  }
  return GENERATION_TIMEOUT_MS;
}
import { CertificatePanel } from './report/CertificatePanel';
import { SchemePicker, type SchemeSelectionStatus } from './SchemePicker';
import {
  type CanonicalTypology,
  type RoomOption,
  normalizeTypology,
  getTypologyConfig,
  formatStoreysChip,
  formatCoverageChip,
  isFloorPlanStale,
  TYPOLOGY_LABELS,
  TYPOLOGY_ROOM_CATALOGS,
} from '../services/typology';

// Re-export for compatibility
export type { CanonicalTypology, RoomOption };
export { normalizeTypology, TYPOLOGY_LABELS, TYPOLOGY_ROOM_CATALOGS };

interface FloorPlanGeneratorCardProps {
  defaultWidthM?: number;
  defaultDepthM?: number;
  onFloorPlanGenerated?: (plan: FloorPlanResponse) => void;
  activeFloorPlan?: FloorPlanResponse | null;
  // Shared analysis parameters from App.tsx (single source of truth). Parameters
  // only — the site's coordinates live with the captured plot.
  analysisRequest?: AnalysisParams;
  buildingTypology?: string;
  qualityGrade?: string;
  floors?: number;
  builtUpAreaSqft?: number;
  groundCoverageRatio?: number;
  clientNotes?: string;
  aiProvider?: string;
  solarAxisDegrees?: number;
  prevailingWindDirectionDegrees?: number;
  topVastuEntrances?: string[];
  /** Shared single-source boundary (map capture). Overrides the legacy local vertex editor. */
  sharedBoundary?: SharedBoundaryState | null;
  /** Applies an applied remediation's validated parameters to the shared request. */
  onRequestPatch?: (patch: Partial<AnalysisParams>) => void;
}

export const FloorPlanGeneratorCard: React.FC<FloorPlanGeneratorCardProps> = ({
  defaultWidthM = 10.0,
  defaultDepthM = 12.0,
  onFloorPlanGenerated,
  activeFloorPlan = null,
  analysisRequest,
  buildingTypology,
  qualityGrade,
  floors = 1,
  builtUpAreaSqft,
  groundCoverageRatio,
  clientNotes,
  aiProvider,
  solarAxisDegrees,
  prevailingWindDirectionDegrees,
  topVastuEntrances,
  sharedBoundary,
  onRequestPatch,
}) => {
  // Inherit parameters directly from shared request (single source of truth)
  // Delete card's local copies of storeys/typology/coverage so disagreement is impossible.
  const activeFloors = analysisRequest?.floors ?? floors ?? 1;
  const activeTypology = analysisRequest?.building_typology ?? buildingTypology ?? 'residential_single';
  const activeCoverage = analysisRequest?.ground_coverage_ratio ?? groundCoverageRatio ?? 0.60;
  const activeNotes = analysisRequest?.client_requirements ?? clientNotes;
  const activeGrade = analysisRequest?.quality_grade ?? qualityGrade ?? 'standard';
  const activeAreaSqft = analysisRequest?.built_up_area_sqft ?? builtUpAreaSqft;
  const activeProvider = analysisRequest?.ai_provider ?? aiProvider;
  const activeConstraints = analysisRequest?.extracted_constraints;

  const [userWidth, setUserWidth] = useState<number | null>(null);
  const [userDepth, setUserDepth] = useState<number | null>(null);

  // Single-source boundary: derived from the shared map-capture model.
  // The legacy local vertex editor is retired; boundary is captured on the map.
  const sharedActive = Boolean(sharedBoundary && sharedBoundary.vertices.length >= 3);
  const siteMode: 'rectangle' | 'irregular' = sharedActive ? 'irregular' : 'rectangle';
  const irregularVertices: [number, number][] = sharedBoundary
    ? sharedBoundary.vertices.map((v: { x: number; y: number }) => [v.x, v.y] as [number, number])
    : [];

  // Live Polygon Metrics & Geometry Validation (shared model)
  const polyMetrics = React.useMemo(() => {
    const m = sharedBoundary ? metricsFor(sharedBoundary.vertices) : null;
    if (!m) {
      return {
        area: 0,
        perimeter: 0,
        isValid: false,
        reason: 'Capture the plot boundary on the map first.',
        bbox: [0, 0, 10, 10] as [number, number, number, number],
        shapeType: 'rectangle',
      };
    }
    return {
      area: Math.round(m.areaSqm * 10) / 10,
      perimeter: Math.round(m.perimeterM * 10) / 10,
      isValid: m.valid,
      reason: m.reason ?? 'Valid Statutory Boundary',
      bbox: m.bbox,
      shapeType: m.shapeType,
    };
  }, [sharedBoundary]);

  /* bbox edges are geodesic floats: subtracting them surfaces the binary
     residue (89.05499999999999) in the read-only width/depth inputs. Round to
     the centimetre the solver actually consumes. */
  const bboxWidth = Math.max(4.0, Math.round((polyMetrics.bbox[2] - polyMetrics.bbox[0]) * 100) / 100);
  const bboxDepth = Math.max(4.0, Math.round((polyMetrics.bbox[3] - polyMetrics.bbox[1]) * 100) / 100);

  const plotWidth = siteMode === 'irregular' ? bboxWidth : (userWidth ?? defaultWidthM);
  const plotDepth = siteMode === 'irregular' ? bboxDepth : (userDepth ?? defaultDepthM);



  // Sync user dimensions when default props change
  useEffect(() => {
    setUserWidth(null);
    setUserDepth(null);
  }, [defaultWidthM, defaultDepthM]);

  const typologyConfig = getTypologyConfig(activeTypology);
  const canonicalTypology = typologyConfig.canonical;
  const availableRooms = typologyConfig.rooms;

  // Initialize selected rooms based on inherited typology and storeys
  const [selectedRooms, setSelectedRooms] = useState<string[]>(() => {
    return availableRooms
      .filter((r) => r.required || (activeFloors >= 2 && r.isCore))
      .map((r) => r.id);
  });
  // Strategy selection applied by a remediation card. These are validated
  // request inputs, not geometry: the engine still draws and certifies.
  const [partitionVariant, setPartitionVariant] = useState<
    'service_row' | 'single_unit' | 'duplex' | null
  >(null);
  const [unitsPerFloor, setUnitsPerFloor] = useState<number | null>(null);

  const prevTypologyRef = useRef<string>(canonicalTypology);
  const prevFloorsRef = useRef<number>(activeFloors);

  // Live propagation: dynamically adapt selected rooms when inherited Typology or Floors changes
  useEffect(() => {
    const isTypologyChanged = prevTypologyRef.current !== canonicalTypology;
    const isFloorsChanged = prevFloorsRef.current !== activeFloors;

    if (isTypologyChanged || isFloorsChanged) {
      prevTypologyRef.current = canonicalTypology;
      prevFloorsRef.current = activeFloors;

      const currentRoomIds = new Set(availableRooms.map((r) => r.id));
      const hasValidRooms = selectedRooms.some((r) => currentRoomIds.has(r));

      if (isTypologyChanged || !hasValidRooms) {
        // Switch to sensible default selection for the newly selected typology
        const defaultSelection = availableRooms
          .filter((r) => r.required || (activeFloors >= 2 && r.isCore))
          .map((r) => r.id);

        setSelectedRooms(defaultSelection.length >= 3 ? defaultSelection : availableRooms.slice(0, 4).map((r) => r.id));
      } else if (isFloorsChanged) {
        if (activeFloors >= 2) {
          // Auto-include vertical core rooms if multiple storeys requested
          const coreRooms = availableRooms.filter((r) => r.isCore).map((r) => r.id);
          setSelectedRooms((prev) => Array.from(new Set([...prev, ...coreRooms])));
        } else {
          // Exclude vertical core rooms when switching back to single storey to kill cross-run bleed
          const coreRoomIds = new Set(availableRooms.filter((r) => r.isCore).map((r) => r.id));
          setSelectedRooms((prev) => {
            const filtered = prev.filter((r) => !coreRoomIds.has(r));
            return filtered.length >= 3 ? filtered : availableRooms.filter((r) => r.required).map((r) => r.id);
          });
        }
      }
    }
  }, [canonicalTypology, activeFloors, availableRooms, selectedRooms]);

  const [strictness, setStrictness] = useState<'high' | 'medium' | 'low'>('high');
  const [floorPlateMasks, setFloorPlateMasks] = useState<Record<number, Record<string, 'present' | 'terrace' | 'void'>>>({});
  const [terraceBands, setTerraceBands] = useState<Record<number, { edge: 'none' | 'N' | 'S' | 'E' | 'W'; depth_m: number }>>({});
  const [designIntent, setDesignIntent] = useState<'maximize_enclosed' | 'passive_ventilation'>('maximize_enclosed');
  // Engineering drawing toggles (service layer + structural sheet).
  const [includeServiceLayer, setIncludeServiceLayer] = useState(true);
  const [includeStructuralSheet, setIncludeStructuralSheet] = useState(true);

  // Initialize floorPlateMasks when activeFloors or activeTypology changes
  useEffect(() => {
    setFloorPlateMasks((prev) => {
      const next: Record<number, Record<string, 'present' | 'terrace' | 'void'>> = {};
      for (let z = 0; z < activeFloors; z++) {
        next[z] = {
          wing_a: 'present',
          wing_b: prev[z]?.wing_b || 'present',
        };
      }
      // Typology default proposal (e.g. T1 G+2 top level terraces Wing B)
      const typUpper = activeTypology.toUpperCase();
      if ((typUpper.includes('T1') || typUpper.includes('SINGLE')) && activeFloors >= 3) {
        if (!prev[activeFloors - 1]?.wing_b) {
          next[activeFloors - 1].wing_b = 'terrace';
        }
      }
      return next;
    });
  }, [activeFloors, activeTypology]);

  // Initialize terraceBands when activeFloors changes
  useEffect(() => {
    setTerraceBands((prev) => {
      const next: Record<number, { edge: 'none' | 'N' | 'S' | 'E' | 'W'; depth_m: number }> = {};
      for (let z = 0; z < activeFloors; z++) {
        next[z] = prev[z] || {
          edge: 'none',
          depth_m: 3.0,
        };
      }
      return next;
    });
  }, [activeFloors]);

  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  // Scheme profile the user picked. Sent with every generation so
  // the plate is re-solved with that profile's weights; the picker records what
  // the backend actually did with it.
  const [schemeProfile, setSchemeProfile] = useState<string | null>(null);
  const [pendingSchemeProfile, setPendingSchemeProfile] = useState<string | null>(null);
  const [localFloorPlan, setLocalFloorPlan] = useState<FloorPlanResponse | null>(null);
  // Last request actually sent. The advisor's dry-runs reuse it verbatim.
  const [lastRequest, setLastRequest] = useState<FloorPlanRequest | null>(null);
  // An accepted rotation is a validated plot geometry for this session; it is
  // cleared with the card (reset remounts it) and keeps the stale guard honest.
  const [rotationPolygon, setRotationPolygon] = useState<PlotPolygon | null>(null);
  // Canonical single source of truth: parent-managed activeFloorPlan if provided, falling back to local state
  const floorPlan = activeFloorPlan !== undefined ? activeFloorPlan : localFloorPlan;
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // Field-level 422 detail, kept separate so the message stays readable and
  // each rejected input can be named (e.g. "floors: needs an even number").
  const [validationIssues, setValidationIssues] = useState<string[]>([]);

  /**
   * Chunked arrival: the plan commits, the SVG body follows in its own slice.
   * -------------------------------------------------------------------------
   * A finished generation used to arrive in ONE task: the solver's response
   * state, the whole Cost & Plan subtree and the blueprint viewer's first render
   * (sanitize + ghost/inject pass over a multi-hundred-node SVG, then 
   * `dangerouslySetInnerHTML`) all landed together — three long tasks from one
   * click. Splitting them is not a spinner: the plan's own content (status,
   * notices, sheet metrics) commits immediately, and only the SVG body waits for
   * an idle slice.
   *
   * The placeholder is 360px — the viewer's own `h-[360px] min-h-[320px]` box —
   * so the body it stands in for cannot move when it swaps in. A shorter
   * placeholder would trade the long task for a layout shift, which is the one
   * thing this program measures harder than task length.
   */
  // The gate is a KEY, not a boolean: a plan is "ready" only when the slice that
  // mounted its body has run FOR THAT generation, so a fresh plan is not ready by
  // default and no effect has to reset the flag (which would be a state write in
  // an effect, and a second render on arrival).
  const [readyPlanKey, setReadyPlanKey] = useState<string | null>(null);
  const planKey = floorPlan ? floorPlan.generation_id || String(floorPlan.generated_at) : null;
  const viewerReady = planKey !== null && readyPlanKey === planKey;
  useEffect(() => {
    if (!planKey) return;
    let cancelled = false;
    const mount = () => {
      if (cancelled) return;
      // A transition, so a real interaction (a floor switch, a tab click) that
      // arrives in this slice still wins over mounting the SVG.
      React.startTransition(() => setReadyPlanKey(planKey));
    };
    const hasIdle = typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function';
    const handle = hasIdle
      ? window.requestIdleCallback(mount, { timeout: 400 })
      : window.setTimeout(mount, 40);
    return () => {
      cancelled = true;
      if (hasIdle) window.cancelIdleCallback(handle);
      else clearTimeout(handle);
    };
  }, [planKey]);

  // Synchronize when parent activeFloorPlan changes
  useEffect(() => {
    if (activeFloorPlan !== undefined) {
      setLocalFloorPlan(activeFloorPlan);
    }
  }, [activeFloorPlan]);

  const activeBandsPayload = (() => {
    if (siteMode !== 'rectangle') return undefined;
    const activeBands: Record<number, { edge: 'N' | 'S' | 'E' | 'W'; depth_m: number }> = {};
    Object.entries(terraceBands).forEach(([k, v]) => {
      const lvl = parseInt(k, 10);
      if (lvl > 0 && v.edge !== 'none') {
        activeBands[lvl] = {
          edge: v.edge,
          depth_m: v.depth_m,
        };
      }
    });
    return Object.keys(activeBands).length > 0 ? activeBands : undefined;
  })();

  // STALE-PLAN GUARD: Check if active parameters differ from snapshot in current plan
  const isPlanStale = Boolean(
    floorPlan &&
    (floorPlan.params_snapshot
      ? isFloorPlanStale(floorPlan.params_snapshot, {
          building_typology: activeTypology,
          floors: activeFloors,
          ground_coverage_ratio: activeCoverage,
          plot_width_m: Number(plotWidth),
          plot_depth_m: Number(plotDepth),
          required_rooms: selectedRooms,
          vastu_strictness: strictness,
          built_up_area_sqft: activeAreaSqft,
          client_notes: activeNotes,
          quality_grade: activeGrade,
          ai_provider: activeProvider,
          solar_axis_degrees: solarAxisDegrees,
          prevailing_wind_direction_degrees: prevailingWindDirectionDegrees,
          shape_type: siteMode === 'irregular' ? polyMetrics.shapeType : 'rectangle',
          plot_polygon:
            rotationPolygon ??
            (siteMode === 'irregular'
              ? {
                  vertices: irregularVertices,
                  shape_type: polyMetrics.shapeType as any,
                  area_sqm: polyMetrics.area,
                  perimeter_m: polyMetrics.perimeter,
                  bounding_box: polyMetrics.bbox,
                  is_regular_rectangle: false,
                }
              : undefined),
          terrace_bands: activeBandsPayload,
          floor_plate_masks: siteMode === 'irregular' ? floorPlateMasks : undefined,
          design_intent: designIntent,
          include_service_layer: includeServiceLayer,
          include_structural_sheet: includeStructuralSheet,
        })
      : (
        (floorPlan.multi_storey && floorPlan.multi_storey.total_storeys !== activeFloors) ||
        (floorPlan.multi_storey && normalizeTypology(floorPlan.multi_storey.building_typology) !== canonicalTypology)
      ))
  );

  // Gate verdicts are read from the response, never re-derived in the UI: the
  // QA rows and the certificate badge must agree with the gate.
  const gateReport = floorPlan?.qa?.validation_gate
    || floorPlan?.mathematical_certificate?.details?.validation_gate
    || floorPlan?.multi_storey?.validation_gate;
  const gateStatus = floorPlan?.qa?.validation_gate_status || gateReport?.overall_status;
  const gateWarnCount = Array.isArray(gateReport?.layers)
    ? gateReport.layers.filter((l: any) => l.status === 'WARN').length
    : 0;
  const gateFailCount = Array.isArray(gateReport?.layers)
    ? gateReport.layers.filter((l: any) => l.status === 'FAIL').length
    : 0;
  // The verdict is the SERVER's, rendered verbatim by the card, the
  // certificate panel and the PDF.  A legacy payload without the field may
  // only be read from its certificate/gate; the browser never re-classifies a
  // warning as a FAIL of its own (that is how the card and the export drifted).
  const planVerdict: 'CERTIFIED' | 'ADVISORY' | 'NOT-CERTIFIED-FAIL-STAMP' =
    floorPlan?.plan_verdict ??
    ((floorPlan?.mathematical_certificate as any)?.is_valid === false ||
    String(gateStatus || '').toUpperCase() === 'FAIL'
      ? 'NOT-CERTIFIED-FAIL-STAMP'
      : 'CERTIFIED');
  // One relaxation inventory (structured room data), used by the tiered
  // warning report and the certificate's count. The old list printed every
  // rationale twice and let a 200-char chip overflow the card.
  const relaxations = React.useMemo(() => collectRelaxations(floorPlan), [floorPlan]);

  // Scheme portfolio + what the backend did with the selection.
  // Read from the response, never inferred from the presence of a profile.
  const schemeAlternatives = floorPlan?.scheme_alternatives ?? [];
  // A single alternative is honest only when the picker says why (I7/W2).
  const schemeDisclosure =
    (floorPlan?.scheme_portfolio?.provenance?.no_material_alternative as string | undefined) ?? null;
  const schemeSnapshot = (floorPlan?.params_snapshot ?? {}) as Record<string, any>;
  const schemeSelectionStatus: SchemeSelectionStatus =
    schemeSnapshot.scheme_selection_status === 'applied'
      ? 'applied'
      : schemeSnapshot.scheme_selection_status === 'rejected_non_compliant'
      ? 'rejected_non_compliant'
      : schemeSnapshot.scheme_selection_status === 'recorded_only'
      ? 'recorded_only'
      : 'unselected';
  const schemeFailingLayers: string[] = Array.isArray(schemeSnapshot.scheme_selection_failing_layers)
    ? schemeSnapshot.scheme_selection_failing_layers
    : [];

  // SELECTION-PATH: `params_snapshot` is the only channel that survives a
  // fallback.  `unmet_requirements` is shared with the natural deficit path and
  // the warning list is prose, so neither can prove which layout was drawn.
  // The backend writes these three keys ONLY when it replaced the requested
  // partition, which means their absence is evidence the selection WAS drawn;
  // the card must never infer a fallback from a warning line.
  const selectionFallback =
    schemeSnapshot.selection_path === 'fallback_legal_programme'
      ? {
          reason: String(schemeSnapshot.selection_fallback_reason || '').trim(),
          unplaced: Array.isArray(schemeSnapshot.selection_unplaced_rooms)
            ? schemeSnapshot.selection_unplaced_rooms.map((r: unknown) => String(r))
            : [],
        }
      : null;

  // Boundary edits (presets / import / vertex edits) live in the map capture
  // capture wizard. The card deep-links instead of owning geometry state.
  const requestBoundaryEdit = () => {
    window.dispatchEvent(new CustomEvent('bw:edit-boundary'));
  };

  const toggleRoom = (roomId: string) => {
    setSelectedRooms((prev) =>
      prev.includes(roomId)
        ? prev.filter((r) => r !== roomId)
        : [...prev, roomId]
    );
  };

  const handleGenerate = async (
    profileOverride?: string | null,
    requestPatch?: Partial<FloorPlanRequest>,
  ) => {
    if (selectedRooms.length < 3) {
      setErrorMessage('Please select at least 3 rooms to generate an architectural floor plan.');
      setValidationIssues([]);
      return;
    }

    if (siteMode === 'irregular' && !polyMetrics.isValid) {
      setErrorMessage(`Invalid plot polygon: ${polyMetrics.reason}`);
      setValidationIssues([]);
      return;
    }

    const activeSchemeProfile = profileOverride !== undefined ? profileOverride : schemeProfile;
    setIsGenerating(true);
    setErrorMessage(null);
    setValidationIssues([]);
    setPendingSchemeProfile(activeSchemeProfile || null);

    // A captured boundary is authoritative: send its real bounding box. The
    // previous 60 m clamp turned a 108.5 x 89.1 m site into 60 x 60 m while the
    // polygon still described the full plot, so the plate and the site plan
    // Disagreed. Coverage, not a dimension clamp, caps the plate.
    const currentWidth = Math.max(4.0, Number(plotWidth) || 10.0);
    const currentDepth = Math.max(4.0, Number(plotDepth) || 12.0);

    // THE single-source funnel: identical model as map trace / presets / import.
    let plotPoly: PlotPolygon | undefined = rotationPolygon ?? undefined;
    if (!plotPoly && sharedBoundary && sharedBoundary.vertices.length >= 3) {
      const payload = buildPlotPolygonPayload({
        vertices: sharedBoundary.vertices,
        origin: sharedBoundary.origin,
        source: sharedBoundary.source,
        frontageEdgeIndex: sharedBoundary.frontageEdgeIndex,
      });
      plotPoly = {
        vertices: payload.vertices,
        shape_type: payload.shape_type as any,
        area_sqm: payload.area_sqm,
        perimeter_m: payload.perimeter_m,
        bounding_box: payload.bounding_box,
        is_regular_rectangle: payload.is_regular_rectangle,
      };
    }

    const req: FloorPlanRequest = {
      plot_width_m: currentWidth,
      plot_depth_m: currentDepth,
      required_rooms: selectedRooms,
      vastu_strictness: strictness,
      building_typology: activeTypology,
      quality_grade: activeGrade,
      floors: activeFloors,
      built_up_area_sqft: activeAreaSqft,
      ground_coverage_ratio: activeCoverage,
      client_notes: activeNotes,
      ai_provider: activeProvider,
      solar_axis_degrees: solarAxisDegrees,
      prevailing_wind_direction_degrees: prevailingWindDirectionDegrees,
      top_vastu_entrances: topVastuEntrances,
      extracted_constraints: activeConstraints,
      bypass_cache: true,
      plot_polygon: plotPoly,
      floor_plate_masks: siteMode === 'irregular' ? floorPlateMasks : undefined,
      terrace_bands: activeBandsPayload,
      design_intent: designIntent,
      include_service_layer: includeServiceLayer,
      include_structural_sheet: includeStructuralSheet,
      // The flag is now part of the client contract. It stays OFF
      // until the band solver can re-partition a programme-sized plate: with it
      // on, `selected_scheme_id` fell back to `recorded_only` and the scheme
      // Picker stopped re-solving, which is the worse regression.
      program_aware_footprint: false,
      // Always ask for the portfolio so the picker can show what the other two
      // profiles would have produced; the geometry itself follows the selection.
      include_scheme_alternatives: true,
      selected_scheme_id: activeSchemeProfile || undefined,
      partition_variant: requestPatch?.partition_variant ?? partitionVariant ?? undefined,
      units_per_floor: requestPatch?.units_per_floor ?? unitsPerFloor ?? undefined,
    };
    // A remediation applies ONLY validated inputs, on top of the request the
    // controls produced. No coordinate, area or verdict is written here.
    const finalReq: FloorPlanRequest = requestPatch ? { ...req, ...requestPatch } : req;

    // Mirror the request schema's one structural rule that a UI action can
    // violate: V3 pairs every dwelling with an upper level, so an odd storey
    // count cannot be drawn.  Refuse locally with the same explanation instead
    // of sending a request the API will reject.
    if (
      finalReq.partition_variant === 'duplex' &&
      typeof finalReq.floors === 'number' &&
      finalReq.floors % 2 === 1
    ) {
      setErrorMessage(
        `The two-storey duplex variant needs an even number of storeys; this request has ${finalReq.floors}. Add or remove a storey, or choose another strategy.`,
      );
      setValidationIssues([
        `floors: duplex needs an even number of storeys (received ${finalReq.floors}).`,
      ]);
      setIsGenerating(false);
      setPendingSchemeProfile(null);
      return;
    }

    const controller = new AbortController();
    const timeoutMs = generationTimeoutMs();
    let timedOut = false;
    const timeoutTimer = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);

    try {
      const resp = await generateFloorPlan(finalReq, controller.signal);
      // Plumbing: the card owns the freshness snapshot and therefore REPLACES
      // the server's `params_snapshot`. The backend's selection provenance has
      // to ride across that replacement - dropping it here is exactly what made
      // a fallback plan read like the requested layout.
      const backendSnapshot = (resp.params_snapshot ?? {}) as Record<string, any>;
      const snapshot: FloorPlanParamsSnapshot = {
        building_typology: finalReq.building_typology ?? activeTypology,
        floors: finalReq.floors ?? activeFloors,
        ground_coverage_ratio: finalReq.ground_coverage_ratio ?? activeCoverage,
        plot_width_m: currentWidth,
        plot_depth_m: currentDepth,
        required_rooms: [...(finalReq.required_rooms ?? selectedRooms)].sort(),
        vastu_strictness: finalReq.vastu_strictness ?? strictness,
        built_up_area_sqft: finalReq.built_up_area_sqft ?? activeAreaSqft,
        client_notes: (activeNotes || '').trim(),
        ai_provider: activeProvider,
        shape_type: siteMode === 'irregular' || finalReq.plot_polygon ? polyMetrics.shapeType : 'rectangle',
        plot_polygon: finalReq.plot_polygon ?? plotPoly,
        quality_grade: activeGrade,
        solar_axis_degrees: solarAxisDegrees,
        prevailing_wind_direction_degrees: prevailingWindDirectionDegrees,
        terrace_bands: finalReq.terrace_bands,
        floor_plate_masks: finalReq.floor_plate_masks,
        design_intent: finalReq.design_intent,
        partition_variant: finalReq.partition_variant,
        units_per_floor: finalReq.units_per_floor,
        include_service_layer: finalReq.include_service_layer,
        include_structural_sheet: finalReq.include_structural_sheet,
        selected_scheme_id: finalReq.selected_scheme_id,
        scheme_selection_status: backendSnapshot.scheme_selection_status,
        scheme_profile: backendSnapshot.scheme_profile,
        ...(backendSnapshot.selection_path
          ? {
              selection_path: String(backendSnapshot.selection_path),
              selection_fallback_reason: String(backendSnapshot.selection_fallback_reason ?? ''),
              selection_unplaced_rooms: Array.isArray(backendSnapshot.selection_unplaced_rooms)
                ? backendSnapshot.selection_unplaced_rooms.map((r: unknown) => String(r))
                : [],
            }
          : {}),
      };
      const freshPlan: FloorPlanResponse = {
        ...resp,
        // The generation token is owned by the backend - derived
        // from typology/storeys/seed (GEN-{TYP}-{N}F-{seed}) so identical
        // requests are byte-identical and traceable. The previous client-side
        // Math.random() token broke that determinism contract. generated_at
        // stays client-side purely for freshness ordering.
        generation_id: resp.generation_id,
        generated_at: Date.now(),
        params_snapshot: snapshot,
      };
      // Only a SUCCESSFUL generation may become the request snapshot the
      // advisor/remediation panel reads.  Writing it before the response made
      // a rejected request trigger a second 422 from the remediation endpoint
      // against the same invalid payload.
      setLastRequest(finalReq);
      setLocalFloorPlan(freshPlan);
      if (onFloorPlanGenerated) {
        onFloorPlanGenerated(freshPlan);
      }
    } catch (err: any) {
      const issues = Array.isArray(err?.issues) ? err.issues.map(String) : [];
      setValidationIssues(issues);
      setErrorMessage(
        timedOut
          ? `Generation timed out after ${Math.round(timeoutMs / 1000)} s — the engine did not answer. Nothing was drawn; the previous plan is unchanged. Retry when the engine is responsive.`
          : err?.status === 422
            ? `The engine rejected this design: ${err.message}. Correct the named inputs and generate again. The previous plan is unchanged.`
            : err?.message || 'Failed to generate floor plan.'
      );
    } finally {
      window.clearTimeout(timeoutTimer);
      setIsGenerating(false);
      setPendingSchemeProfile(null);
    }
  };

  /**
   * Picking a profile re-solves the plate - it is not a cosmetic toggle. The
   * same funnel as Generate runs, so the new geometry owns the certificate,
   * land economics and every sheet that follows.
   */
  const handleSelectScheme = (schemeId: string) => {
    if (isGenerating || schemeId === schemeProfile) return;
    setSchemeProfile(schemeId);
    void handleGenerate(schemeId);
  };

  // ONE warning report for the surface AND the advisor: their counts cannot
  // drift because they read the same object.
  const warningReport = React.useMemo(
    () => buildWarningReport(floorPlan?.warnings ?? [], relaxations, truthInputForPlan(floorPlan)),
    [floorPlan, relaxations],
  );

  // The advisor's dry-runs need the request that produced the plan. A live
  // Generate carries it directly; a restored plan carries only the params
  // snapshot, which is the same inputs in a looser shape. Normalise it here so
  // the panel always receives validated request fields, never a raw snapshot.
  const remediationRequest = React.useMemo<Partial<FloorPlanRequest> | null>(() => {
    if (lastRequest) return lastRequest;
    const snapshot = floorPlan?.params_snapshot;
    if (!snapshot) return null;
    return {
      plot_width_m: snapshot.plot_width_m,
      plot_depth_m: snapshot.plot_depth_m,
      required_rooms: snapshot.required_rooms,
      floors: snapshot.floors,
      ground_coverage_ratio: snapshot.ground_coverage_ratio,
      building_typology: snapshot.building_typology as FloorPlanRequest['building_typology'],
      vastu_strictness: snapshot.vastu_strictness as FloorPlanRequest['vastu_strictness'],
      built_up_area_sqft: snapshot.built_up_area_sqft,
      client_notes: snapshot.client_notes,
      ai_provider: snapshot.ai_provider,
      plot_polygon: snapshot.plot_polygon,
      solar_axis_degrees: snapshot.solar_axis_degrees,
      prevailing_wind_direction_degrees: snapshot.prevailing_wind_direction_degrees,
      terrace_bands: snapshot.terrace_bands,
      floor_plate_masks: snapshot.floor_plate_masks,
      design_intent: snapshot.design_intent,
      include_service_layer: snapshot.include_service_layer,
      include_structural_sheet: snapshot.include_structural_sheet,
      include_scheme_alternatives: true,
      selected_scheme_id: snapshot.selected_scheme_id,
      partition_variant: snapshot.partition_variant,
      units_per_floor: snapshot.units_per_floor,
    };
  }, [lastRequest, floorPlan?.params_snapshot]);

  /**
   * Apply a remediation through the existing validated inputs and re-solve.
   * Nothing is written from an AI response: the patch comes from the engine's
   * own option, and the regenerated plan re-certifies.
   */
  const handleApplyRemediation = (option: RemediationOption) => {
    const patch = (option.patch ?? {}) as Partial<FloorPlanRequest>;
    if (patch.partition_variant) {
      setPartitionVariant(patch.partition_variant as 'service_row' | 'single_unit' | 'duplex');
    }
    if (typeof patch.units_per_floor === 'number') {
      setUnitsPerFloor(patch.units_per_floor);
    }
    let nextProfile = schemeProfile;
    if (typeof patch.floors === 'number') {
      onRequestPatch?.({ floors: patch.floors });
    }
    if (typeof patch.ground_coverage_ratio === 'number') {
      onRequestPatch?.({ ground_coverage_ratio: patch.ground_coverage_ratio });
    }
    if (Array.isArray(patch.required_rooms)) {
      setSelectedRooms(patch.required_rooms);
    }
    if (patch.plot_polygon) {
      setRotationPolygon(patch.plot_polygon as PlotPolygon);
    }
    if (patch.selected_scheme_id) {
      nextProfile = String(patch.selected_scheme_id);
      setSchemeProfile(nextProfile);
    }
    void handleGenerate(nextProfile, patch);
  };

  return (
    <div
      data-testid="floorplan-generator-card"
      className="rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 space-y-3.5 w-full min-w-0"
    >
      {/* Header with Title and READ-ONLY Inherited Parameter Summary Chips */}
      <div className="border-b border-[var(--hairline)] pb-2.5 space-y-2 min-w-0">
        <div className="flex items-center justify-between gap-2 min-w-0 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <Icon name="blueprint" size={15} className="text-[var(--text-2)] shrink-0" />
            <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
              Generative Floor Plan Engine
            </h3>
          </div>
          {floorPlan && (
            <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-[var(--fill)] text-[var(--text-1)] capitalize shrink-0">
              {floorPlan.status}
            </span>
          )}
        </div>

        {/* READ-ONLY Parameter Inheritance Summary Chips */}
        <div className="flex items-center justify-between gap-2 flex-wrap text-[11px]">
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Typology Chip */}
            <span
              data-testid="inherited-typology-chip"
              title={`Inherited from Project Parameters: ${typologyConfig.label}`}
              className="px-2.5 py-1 rounded-[6px] font-mono font-semibold bg-[var(--fill)] text-[var(--text-1)] border border-[var(--hairline)] tracking-tight select-none"
            >
              {typologyConfig.shortCode}
            </span>

            {/* Storeys Chip */}
            <span
              data-testid="inherited-storeys-chip"
              title={`Inherited from Project Parameters: ${activeFloors} level(s)`}
              className={`px-2.5 py-1 rounded-[6px] font-mono font-semibold select-none border ${
                activeFloors > 1
                  ? 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                  : 'bg-[var(--fill)] text-[var(--text-1)] border-[var(--hairline)]'
              }`}
            >
              {formatStoreysChip(activeFloors)}
            </span>

            {/* Coverage Chip */}
            <span
              data-testid="inherited-coverage-chip"
              title={`Inherited from Project Parameters: ${Math.round(activeCoverage * 100)}% Ground Coverage Ratio`}
              className="px-2.5 py-1 rounded-[6px] font-mono font-semibold bg-[var(--fill)] text-[var(--text-1)] border border-[var(--hairline)] tracking-tight select-none"
            >
              {formatCoverageChip(activeCoverage)}
            </span>

            {/* Shape Typology & Area Chip */}
            <span
              data-testid="plot-shape-chip"
              title={
                siteMode === 'rectangle'
                  ? `Rectangle plot: ${plotWidth}m x ${plotDepth}m (4 vertices)`
                  : `${polyMetrics.shapeType.toUpperCase()} plot: ${polyMetrics.area} m² (${irregularVertices.length} vertices)`
              }
              className={`px-2.5 py-1 rounded-[6px] font-mono font-semibold select-none border ${
                siteMode === 'irregular'
                  ? 'bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/30'
                  : 'bg-[var(--fill)] text-[var(--text-1)] border-[var(--hairline)]'
              }`}
            >
              {siteMode === 'rectangle'
                ? `RECT · ${(plotWidth * plotDepth).toFixed(0)} m² · 4V`
                : `${polyMetrics.shapeType.replace('_', '-').toUpperCase()} · ${polyMetrics.area.toFixed(0)} m² · ${irregularVertices.length}V`}
            </span>
          </div>

          {/* Subtle Edit Hint */}
          <span className="text-[11px] text-[var(--text-3)] italic flex items-center gap-1 select-none">
            <Icon name="info" size={11} className="shrink-0 opacity-70" />
            <span>Edit in Project Parameters</span>
          </span>
        </div>
      </div>

      {/* Error Notice */}
      {errorMessage && (
        <div
          data-testid="floorplan-generate-error"
          role="alert"
          className="p-2.5 rounded-[10px] bg-[var(--fill)] text-[12px] text-[var(--semantic-red-ink)] space-y-1"
        >
          <div className="flex items-start gap-2">
            <Icon name="alert-triangle" size={14} className="shrink-0 mt-0.5" />
            <span className="min-w-0 break-words">{errorMessage}</span>
          </div>
          {validationIssues.length > 0 && (
            <ul
              data-testid="floorplan-validation-issues"
              className="list-disc space-y-0.5 pl-8 text-[11px] leading-snug"
            >
              {validationIssues.map((issue) => (
                <li key={issue} className="break-words">
                  {issue}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Single-Source Boundary Status (map capture is the only editor) */}
      <div className="flex items-center justify-between p-2.5 rounded-[10px] bg-[var(--fill)] border border-[var(--hairline)]">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="maximize" size={14} className="text-[var(--text-2)] shrink-0" />
          <span className="text-[12px] font-medium text-[var(--text-1)] truncate">
            {siteMode === 'rectangle'
              ? 'Rectangle plot (default dimensions)'
              : `Boundary: ${String(polyMetrics.shapeType).replace('_', '-').toUpperCase()} · ${polyMetrics.area.toFixed(0)} m² · ${polyMetrics.bbox ? '' : ''}${irregularVertices.length} vertices`}
          </span>
          {!polyMetrics.isValid && siteMode === 'irregular' && (
            <span className="text-[11px] text-[var(--semantic-red-ink)] truncate">{polyMetrics.reason}</span>
          )}
        </div>
        <button
          type="button"
          onClick={requestBoundaryEdit}
          className="px-2.5 py-1 rounded-[8px] text-[11px] font-medium bg-[var(--accent-tint)] text-[var(--accent-ink)] hover:brightness-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] shrink-0"
        >
          Edit on map
        </button>
      </div>

      {/* Drafting-Specific Controls: Plot Dimensions (m) & Vastu Strictness */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-[12px]">
        {/* Plot Dimensions */}
        <div className="space-y-1 min-w-0">
          <div className="flex items-center justify-between">
            <label className="text-[12px] font-normal text-[var(--text-3)] block">
              Plot dimensions (meters)
            </label>
            {siteMode === 'irregular' && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-500/15 text-purple-700 dark:text-purple-300 font-medium">
                BBox (Read-only)
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <span className="text-[11px] text-[var(--text-3)] block mb-0.5">Width (m)</span>
              <input
                type="number"
                min="6"
                max="60"
                step="0.5"
                value={plotWidth}
                readOnly={siteMode === 'irregular'}
                disabled={siteMode === 'irregular'}
                onChange={(e) => setUserWidth(parseFloat(e.target.value) || 10)}
                className={`w-full h-8 border-0 rounded-[8px] px-2.5 text-[12px] font-mono outline-none ${
                  siteMode === 'irregular'
                    ? 'bg-neutral-200/50 dark:bg-neutral-800/50 text-[var(--text-2)] cursor-not-allowed'
                    : 'bg-[var(--fill)] text-[var(--text-1)] focus:ring-[2px] focus:ring-[var(--accent)]/30'
                }`}
              />
            </div>
            <div>
              <span className="text-[11px] text-[var(--text-3)] block mb-0.5">Depth (m)</span>
              <input
                type="number"
                min="6"
                max="60"
                step="0.5"
                value={plotDepth}
                readOnly={siteMode === 'irregular'}
                disabled={siteMode === 'irregular'}
                onChange={(e) => setUserDepth(parseFloat(e.target.value) || 12)}
                className={`w-full h-8 border-0 rounded-[8px] px-2.5 text-[12px] font-mono outline-none ${
                  siteMode === 'irregular'
                    ? 'bg-neutral-200/50 dark:bg-neutral-800/50 text-[var(--text-2)] cursor-not-allowed'
                    : 'bg-[var(--fill)] text-[var(--text-1)] focus:ring-[2px] focus:ring-[var(--accent)]/30'
                }`}
              />
            </div>
          </div>
        </div>

        {/* Vastu Strictness: iOS Segmented Control */}
        <div className="space-y-1 min-w-0">
          <label className="text-[12px] font-normal text-[var(--text-3)] block">
            Vastu strictness
          </label>
          <SegmentedControl
            ariaLabel="Vastu strictness"
            size="sm"
            stretch
            value={strictness}
            onChange={setStrictness}
            options={[
              { id: 'high', label: 'High' },
              { id: 'medium', label: 'Medium' },
              { id: 'low', label: 'Low' },
            ]}
          />
          <span className="text-[11px] text-[var(--text-3)] block leading-tight">
            {strictness === 'high'
              ? 'Canonical zones (Kitchen SE, Puja NE, Bed SW).'
              : strictness === 'medium'
              ? 'Balanced plumbing and secondary zones.'
              : 'Soft Vastu scoring for compact footprints.'}
          </span>
        </div>
      </div>

      {/* Irregular Cadastral Boundary Polygon Editor */}
      {siteMode === 'irregular' && (
        <div className="space-y-3 p-3 rounded-[12px] bg-[var(--fill)] border border-purple-500/20">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="text-[12px] font-semibold text-[var(--text-1)]">
                Cadastral Boundary Polygon ({irregularVertices.length} Vertices)
              </span>
              <span
                className={`text-[10px] font-mono px-2 py-0.5 rounded-full font-medium ${
                  polyMetrics.isValid
                    ? 'bg-emerald-500/15 text-[var(--semantic-green-ink)]'
                    : 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
                }`}
              >
                {polyMetrics.isValid
                  ? `Valid (${polyMetrics.shapeType.replace('_', '-').toUpperCase()})`
                  : `Invalid: ${polyMetrics.reason}`}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-[11px] font-mono text-[var(--text-2)]">
              <span>Area: <strong>{polyMetrics.area} m²</strong></span>
              <span>·</span>
              <span>Perim: <strong>{polyMetrics.perimeter} m</strong></span>
            </div>
          </div>

          {/* Read-only boundary summary (edit on the map) */}
          <div className="flex items-center justify-between rounded-[8px] bg-[var(--bg-card)] border border-[var(--hairline)] px-3 py-2">
            <span className="text-[11px] text-[var(--text-2)]">
              Geometry preview and vertex editing moved to the map capture wizard.
            </span>
            <button
              type="button"
              onClick={requestBoundaryEdit}
              className="text-[11px] font-medium text-[var(--accent-ink)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] rounded"
            >
              Open capture
            </button>
          </div>
        </div>
      )}
      {activeConstraints && (
        <div className="space-y-1 min-w-0 pt-0.5">
          <div className="flex items-center justify-between text-[11px] text-[var(--text-3)]">
            <span className="font-semibold uppercase tracking-wider">Active Client Constraints</span>
            <span>Inherited from Project Parameters</span>
          </div>
          <ConstraintChips constraints={activeConstraints} readOnly />
        </div>
      )}

      {/* Dynamic Typology Room Selection */}
      <div className="space-y-1.5 min-w-0">
        <div className="flex items-center justify-between text-[12px] text-[var(--text-3)] flex-wrap gap-1">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="font-semibold text-[var(--text-1)] truncate">
              {typologyConfig.label}
            </span>
            <span className="text-[11px] font-mono">
              ({selectedRooms.length} selected)
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-[11px]">
            {activeFloors > 1 ? (
              <span className="text-[var(--semantic-amber-ink)] font-medium">
                Vertical cores anchor-locked
              </span>
            ) : (
              <span>Min 3 required</span>
            )}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-1.5">
          {availableRooms.map((room) => {
            const isChecked = selectedRooms.includes(room.id);
            const isVerticalCore = Boolean(room.isCore);
            return (
              <button
                key={room.id}
                type="button"
                onClick={() => toggleRoom(room.id)}
                className={`p-2 rounded-[8px] text-left text-[12px] flex items-center justify-between gap-1.5 transition-ui cursor-pointer ${
                  isChecked
                    ? isVerticalCore
                      ? 'bg-purple-500/15 text-purple-700 dark:text-purple-300 font-semibold ring-1 ring-purple-500/30'
                      : 'bg-[var(--accent-tint)] text-[var(--accent-ink)] font-semibold'
                    : 'bg-[var(--fill)] text-[var(--text-2)] hover:text-[var(--text-1)]'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <div
                    className={`w-3.5 h-3.5 rounded-[4px] border flex items-center justify-center shrink-0 ${
                      isChecked
                        ? isVerticalCore
                          ? 'border-purple-600 bg-purple-600 text-white'
                          : 'border-[var(--accent)] bg-[var(--accent)] text-white'
                        : 'border-[var(--hairline)] bg-transparent'
                    }`}
                  >
                    {isChecked && <Icon name="check" size={10} />}
                  </div>
                  <div className="flex flex-col min-w-0">
                    <span className="leading-tight break-words truncate">{room.label}</span>
                    <div className="flex items-center gap-1.5 text-[10px] text-[var(--text-3)] font-mono">
                      {room.minAreaSqm ? <span>min {room.minAreaSqm} m²</span> : null}
                      {room.zone ? (
                        <span className="uppercase px-1 py-0.2 rounded bg-black/5 dark:bg-white/5 font-semibold">
                          [{room.zone}]
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>
                {isVerticalCore && (
                  <span
                    className={`text-[9px] px-1 py-0.2 rounded font-bold uppercase shrink-0 ${
                      isChecked
                        ? 'bg-purple-600 text-white'
                        : 'bg-purple-500/15 text-purple-600 dark:text-purple-400'
                    }`}
                  >
                    Core
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Per-Level Floorplate Variations & Wings (RULE-FP-01..06) */}
      {/* Winged Plot Variations (Irregular / Winged Plots) */}
      {activeFloors > 1 && siteMode === 'irregular' && (
        <div className="space-y-2 p-3 rounded-[12px] bg-[var(--fill)] border border-[var(--hairline)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Icon name="layers" size={14} className="text-[var(--accent-ink)]" />
              <span className="text-[12px] font-semibold text-[var(--text-1)]">
                Per-Floor Floorplate Variations
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-3)] font-mono">
              RULE-FP-01..06
            </span>
          </div>
          <div className="space-y-2">
            {Array.from({ length: activeFloors }).map((_, z) => {
              const lvlTitle = z === 0 ? 'G (Ground)' : `G+${z} (Level ${z})`;
              const mask = floorPlateMasks[z] || { wing_a: 'present', wing_b: 'present' };
              const prevMask = z > 0 ? (floorPlateMasks[z - 1] || { wing_a: 'present', wing_b: 'present' }) : null;
              const isPrevVoid = prevMask?.wing_b === 'void';

              return (
                <div key={z} className="flex items-center justify-between text-[11px] p-2 rounded-[8px] bg-[var(--card-bg-subtle)] border border-[var(--hairline)]">
                  <span className="font-semibold text-[var(--text-1)] min-w-[80px]">{lvlTitle}</span>
                  <div className="flex items-center gap-3">
                    {/* Wing A: Core Wing (Always Present per RULE-FP-01) */}
                    <label
                      className="flex items-center gap-1 text-[var(--text-2)] cursor-not-allowed opacity-75"
                      title="Contains vertical core & egress stairs (RULE-FP-01)"
                    >
                      <input type="checkbox" checked={true} disabled={true} className="rounded text-[var(--accent-ink)]" />
                      <span>Wing A (Core)</span>
                    </label>

                    {/* Wing B: Setback / Terrace Toggle */}
                    {z === 0 ? (
                      <label
                        className="flex items-center gap-1 text-[var(--text-2)] cursor-not-allowed opacity-75"
                        title="Ground floor footprint must be occupied (RULE-FP-01)"
                      >
                        <input type="checkbox" checked={true} disabled={true} className="rounded text-[var(--accent-ink)]" />
                        <span>Wing B (Ground)</span>
                      </label>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <span className="text-[var(--text-3)]">Wing B:</span>
                        <select
                          value={mask.wing_b}
                          disabled={isPrevVoid}
                          title={isPrevVoid ? "Cannot add wing above absent level without support (RULE-FP-02)" : "Select floorplate status for Wing B"}
                          onChange={(e) => {
                            const val = e.target.value as 'present' | 'terrace' | 'void';
                            setFloorPlateMasks((prev) => ({
                              ...prev,
                              [z]: { ...prev[z], wing_b: val },
                            }));
                          }}
                          className="px-2 py-0.5 rounded-[6px] text-[11px] bg-[var(--fill)] text-[var(--text-1)] border border-[var(--hairline)] cursor-pointer"
                        >
                          <option value="present">Enclosed</option>
                          <option value="terrace">Terrace (Open-to-Sky)</option>
                          <option value="void">Void (Dropped)</option>
                        </select>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Design Intent Toggle (feeds solver scoring weights) */}
      <div className="space-y-2 p-3 rounded-[12px] bg-[var(--fill)] border border-[var(--hairline)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Icon name="layers" size={14} className="text-[var(--accent-ink)]" />
            <span className="text-[12px] font-semibold text-[var(--text-1)]">Design Intent</span>
          </div>
          <span className="text-[10px] text-[var(--text-3)] font-mono">L8 PROGRAM INTENT</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button
            data-testid="design-intent-maximize"
            type="button"
            onClick={() => setDesignIntent('maximize_enclosed')}
            className={`px-3 py-2 rounded-[8px] text-[11px] font-semibold border transition-colors ${
              designIntent === 'maximize_enclosed'
                ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                : 'bg-[var(--card-bg-subtle)] text-[var(--text-2)] border-[var(--hairline)] hover:border-[var(--accent)]'
            }`}
            title="Solver prioritizes enclosed conditioned area; terrace ratio advisory capped at 35%"
          >
            Maximize Enclosed Area
          </button>
          <button
            data-testid="design-intent-passive"
            type="button"
            onClick={() => setDesignIntent('passive_ventilation')}
            className={`px-3 py-2 rounded-[8px] text-[11px] font-semibold border transition-colors ${
              designIntent === 'passive_ventilation'
                ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                : 'bg-[var(--card-bg-subtle)] text-[var(--text-2)] border-[var(--hairline)] hover:border-[var(--accent)]'
            }`}
            title="Solver prioritizes passive ventilation / terrace / garden; terrace ratio advisory relaxed to 45%"
          >
            Passive Ventilation / Terrace / Garden
          </button>
        </div>
        <p className="text-[10px] text-[var(--text-3)]">
          {designIntent === 'passive_ventilation'
            ? 'Terraces and open-to-sky zones score higher; terrace ratio advisory relaxed to 45%.'
            : 'Enclosed conditioned area scores higher; terrace ratio advisory enforced at 35% with conversion suggestion.'}
        </p>
      </div>

      {/* Engineering Drawing Toggles (Service / Structural) */}
      <div className="space-y-2 p-3 rounded-[12px] bg-[var(--fill)] border border-[var(--hairline)]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Icon name="layers" size={14} className="text-[var(--accent-ink)]" />
            <span className="text-[12px] font-semibold text-[var(--text-1)]">Engineering Drawing Layers</span>
          </div>
          <span className="text-[10px] text-[var(--text-3)] font-mono">L9-L14</span>
        </div>
        <div className="space-y-1.5">
          <label className="flex items-center justify-between gap-2 cursor-pointer" data-testid="toggle-service-layer">
            <span className="text-[11px] text-[var(--text-2)]">Service layer (shafts, soil/waste/vent pipes, inspection, rainwater, terrace drainage)</span>
            <input
              type="checkbox"
              checked={includeServiceLayer}
              onChange={(e) => setIncludeServiceLayer(e.target.checked)}
              className="accent-[var(--accent)] shrink-0"
            />
          </label>
          <label className="flex items-center justify-between gap-2 cursor-pointer" data-testid="toggle-structural-sheet">
            <span className="text-[11px] text-[var(--text-2)]">Structural layer (column grid bubbles, beams, STRUCTURAL FEASIBILITY notes)</span>
            <input
              type="checkbox"
              checked={includeStructuralSheet}
              onChange={(e) => setIncludeStructuralSheet(e.target.checked)}
              className="accent-[var(--accent)] shrink-0"
            />
          </label>
        </div>
        <p className="text-[10px] text-[var(--text-3)]">
          Validation always runs all layers L1-L15 regardless of drawing toggles - toggles affect what is drawn, never what is checked.
        </p>
      </div>

      {/* Axis-Aligned Terrace Bands (Simple Rectangular Plots) */}
      {activeFloors > 1 && siteMode === 'rectangle' && (
        <div className="space-y-2 p-3 rounded-[12px] bg-[var(--fill)] border border-[var(--hairline)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <Icon name="layers" size={14} className="text-[var(--accent-ink)]" />
              <span className="text-[12px] font-semibold text-[var(--text-1)]">
                Per-Floor Terrace Bands (Rectangular)
              </span>
            </div>
            <span className="text-[10px] text-[var(--text-3)] font-mono">
              RULE-FP-01..07
            </span>
          </div>
          <div className="space-y-2">
            {Array.from({ length: activeFloors }).map((_, z) => {
              const lvlTitle = z === 0 ? 'G (Ground)' : `G+${z} (Level ${z})`;
              const band = terraceBands[z] || { edge: 'none', depth_m: 3.0 };
              const envW = Math.max(4.0, (Number(plotWidth) || 12.0) - 2.4);
              const envD = Math.max(4.0, (Number(plotDepth) || 15.0) - 3.75);
              const dimAlongEdge = (band.edge === 'E' || band.edge === 'W') ? envW : envD;
              const maxDepth = Math.round(0.40 * dimAlongEdge * 10) / 10;

              return (
                <div key={z} className="p-2 rounded-[8px] bg-[var(--card-bg-subtle)] border border-[var(--hairline)] space-y-1.5 text-[11px]">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-[var(--text-1)] min-w-[80px]">{lvlTitle}</span>
                    {z === 0 ? (
                      <span
                        className="text-[var(--text-3)] italic cursor-not-allowed"
                        title="Ground floor keeps full plate for entry/parking (RULE-FP-01)"
                      >
                        Full Plate Only (Entry/Parking - RULE-FP-01)
                      </span>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className="text-[var(--text-3)]">Terrace Edge:</span>
                        <select
                          data-testid={`terrace-edge-f${z}`}
                          value={band.edge}
                          onChange={(e) => {
                            const edge = e.target.value as 'none' | 'N' | 'S' | 'E' | 'W';
                            const newDim = (edge === 'E' || edge === 'W') ? envW : envD;
                            const newMax = Math.round(0.40 * newDim * 10) / 10;
                            const clampedDepth = Math.min(band.depth_m || 3.0, newMax);
                            setTerraceBands((prev) => ({
                              ...prev,
                              [z]: { edge, depth_m: clampedDepth },
                            }));
                          }}
                          className="px-2 py-0.5 rounded-[6px] text-[11px] bg-[var(--fill)] text-[var(--text-1)] border border-[var(--hairline)] cursor-pointer"
                        >
                          <option value="none">None (Full Plate)</option>
                          <option value="N">North Edge (Front Terrace)</option>
                          <option value="S">South Edge (Rear Terrace)</option>
                          <option value="E">East Edge (Side Terrace)</option>
                          <option
                            value="W"
                            disabled={true}
                            title="Disabled: West edge contains vertical stair core & egress (RULE-FP-01)"
                            className="text-[var(--text-3)] bg-[var(--fill)] opacity-50"
                          >
                            West Edge (Disabled: Stair Core)
                          </option>
                        </select>
                      </div>
                    )}
                  </div>

                  {z > 0 && band.edge !== 'none' && (
                    <div className="flex items-center justify-between pt-1 border-t border-[var(--hairline)]/50 gap-3">
                      <div className="flex items-center gap-1.5 text-[var(--text-2)]">
                        <span>Depth:</span>
                        <span className="font-mono font-semibold text-[var(--accent-ink)]">
                          {band.depth_m.toFixed(1)}m
                        </span>
                        <span className="text-[10px] text-[var(--text-3)]">
                          (max {maxDepth.toFixed(1)}m / 40%)
                        </span>
                      </div>
                      <input
                        type="range"
                        data-testid={`terrace-depth-f${z}`}
                        min="1.5"
                        max={maxDepth}
                        step="0.1"
                        value={Math.min(band.depth_m, maxDepth)}
                        title="Band depth <= 40% of plate dimension per RULE-FP-07"
                        onChange={(e) => {
                          const depth_m = parseFloat(e.target.value);
                          setTerraceBands((prev) => ({
                            ...prev,
                            [z]: { ...prev[z], depth_m },
                          }));
                        }}
                        className="w-36 h-1.5 accent-[var(--accent)] cursor-pointer"
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Action Button: Primary Accent Button */}
      <button
        type="button"
        onClick={() => handleGenerate()}
        disabled={isGenerating}
        className="w-full h-9 px-4 rounded-full bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] disabled:bg-[var(--fill)] disabled:text-[var(--text-3)] text-white text-[13px] font-semibold flex items-center justify-center gap-2 transition-ui select-none shadow-sm cursor-pointer disabled:cursor-not-allowed"
      >
        {isGenerating ? (
          <>
            <Icon name="loader" size={14} className="animate-spin" />
            <span>Solving Spatial Layout...</span>
          </>
        ) : (
          <>
            <Icon name="blueprint" size={14} />
            <span>
              {activeFloors > 1
                ? `Generate ${activeFloors}-Storey Architectural Blueprint`
                : 'Generate Architectural Blueprint'}
            </span>
          </>
        )}
      </button>

      {/* Blueprint render placeholder while the solver runs (no plan yet) */}
      {isGenerating && !floorPlan && (
        <div className="space-y-3 pt-1" aria-label="Solving architectural layout">
          <Skeleton className="h-[320px] w-full rounded-[16px]" label="Generating architectural blueprint" />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        </div>
      )}

      {/* Blueprint & Metrics Display */}
      {floorPlan && (
        <div className="space-y-3 pt-1">
          {/* Multi-Storey Stacking Verification Callout */}
          {floorPlan.multi_storey && (
            <div className="rounded-[10px] bg-purple-500/10 border border-purple-500/25 p-3 space-y-2">
              <div className="flex items-center justify-between flex-wrap gap-1.5">
                <div className="flex items-center gap-1.5">
                  <Icon name="layers" size={14} className="text-purple-600 dark:text-purple-400" />
                  <span className="text-[11px] font-bold uppercase tracking-wider text-purple-700 dark:text-purple-300">
                    CF-HSA Multi-Storey Core Alignment
                  </span>
                </div>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-600 text-white select-none">
                  {floorPlan.multi_storey.total_storeys} STOREYS VERIFIED
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                <div className="bg-[var(--fill)]/50 rounded-[6px] p-1.5 text-center">
                  <span className="text-[var(--text-3)] block text-[10px]">Anchor Cores</span>
                  <span className="font-semibold font-mono text-[var(--text-1)]">
                    {floorPlan.multi_storey.vertical_cores.length} locked (X,Y)
                  </span>
                </div>
                <div className="bg-[var(--fill)]/50 rounded-[6px] p-1.5 text-center">
                  <span className="text-[var(--text-3)] block text-[10px]">Wet Stacks</span>
                  <span className="font-semibold font-mono text-[var(--text-1)]">
                    {floorPlan.multi_storey.duct_shafts.length} MEP shafts
                  </span>
                </div>
                <div className="bg-[var(--fill)]/50 rounded-[6px] p-1.5 text-center">
                  <span className="text-[var(--text-3)] block text-[10px]">Total Built-Up</span>
                  <span className="font-semibold font-mono text-[var(--text-1)]">
                    {floorPlan.multi_storey.total_built_up_area_sqm.toFixed(1)} m²
                  </span>
                </div>
                <div className="bg-[var(--fill)]/50 rounded-[6px] p-1.5 text-center">
                  <span className="text-[var(--text-3)] block text-[10px]">Ghost Overlay</span>
                  <span className="font-semibold text-[var(--semantic-green-ink)]">
                    Active on F1+
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Design Brief Accent-tinted Callout */}
          <div className="rounded-[10px] bg-[var(--accent-tint)] border border-[var(--accent)]/20 p-3 space-y-1.5">
            <div className="flex items-center justify-between flex-wrap gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--accent-ink)]">
                Design Brief
              </span>
              <div className="flex items-center gap-1.5">
                {floorPlan.qa?.critic && (
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-semibold select-none ${
                      floorPlan.qa.critic === 'pass'
                        ? 'bg-emerald-600 text-white'
                        : floorPlan.qa.critic === 'skipped'
                        ? 'bg-[var(--fill)] text-[var(--text-2)] border border-[var(--hairline)]'
                        : 'bg-rose-600 text-white'
                    }`}
                  >
                    {floorPlan.qa.critic === 'pass'
                      ? 'Architect review: passed'
                      : floorPlan.qa.critic === 'skipped'
                      ? 'Architect review: not run'
                      : 'Architect review: flagged'}
                  </span>
                )}
                {floorPlan.placement_source && (
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-semibold select-none ${
                      floorPlan.placement_source.includes('ai') || floorPlan.placement_source.includes('llm')
                        ? 'bg-[var(--accent)] text-white'
                        : 'bg-[var(--fill)] text-[var(--text-2)] border border-[var(--hairline)]'
                    }`}
                  >
                    {floorPlan.placement_source.includes('ai') || floorPlan.placement_source.includes('llm')
                      ? 'Placement: AI-reasoned + KB-validated'
                      : 'Placement: KB-standard'}
                  </span>
                )}
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-semibold select-none ${
                    floorPlan.program_source === 'llm' || floorPlan.program_source === 'cache'
                      ? 'bg-[var(--accent)] text-white'
                      : 'bg-[var(--fill)] text-[var(--text-2)] border border-[var(--hairline)]'
                  }`}
                >
                  {floorPlan.program_source === 'llm' || floorPlan.program_source === 'cache'
                    ? 'Program: AI-generated'
                    : 'Program: Standard'}
                </span>
              </div>
            </div>
            <p className="text-[12px] italic text-[var(--text-1)] leading-relaxed">
              {floorPlan.design_intent ||
                'Space plan optimized for functional circulation, Vastu compliance, and plumbing consolidation.'}
            </p>
            {(() => {
              const logicList: { room?: string; text: string }[] = [];
              if (Array.isArray(floorPlan.placement_logic)) {
                floorPlan.placement_logic.forEach((item: any) => {
                  logicList.push({ text: String(item) });
                });
              } else if (floorPlan.placement_logic && typeof floorPlan.placement_logic === 'object') {
                Object.entries(floorPlan.placement_logic).forEach(([room, text]) => {
                  logicList.push({ room, text: String(text) });
                });
              }
              if (logicList.length === 0) return null;
              return (
                <details className="mt-2 text-[12px] group">
                  <summary className="cursor-pointer text-[11px] font-medium text-[var(--accent-ink)] hover:underline select-none flex items-center gap-1">
                    <span>Placement Logic ({logicList.length} rules applied)</span>
                  </summary>
                  <ul className="mt-1.5 space-y-1 pl-4 list-disc text-[11px] text-[var(--text-1)]">
                    {logicList.map((item, idx) => (
                      <li key={idx} className="leading-snug">
                        {item.room && <span className="font-semibold capitalize mr-1">{item.room.replace('_', ' ')}:</span>}
                        {item.text}
                      </li>
                    ))}
                  </ul>
                </details>
              );
            })()}

            {/* SELECTION-FALLBACK: a 200 must never read as "your rooms were
                placed". The drawn plate is the plate's legal programme, and it is
                named as such here, before the per-room ledger. */}
            {selectionFallback && (
              <div
                data-testid="selection-fallback-notice"
                className="mt-2.5 p-3 rounded-[10px] bg-rose-500/10 border border-rose-500/30 text-rose-800 dark:text-rose-100 space-y-1.5"
              >
                <div className="flex items-center gap-1.5 font-semibold text-[12px]">
                  <Icon name="shield-alert" size={13} className="shrink-0" />
                  <span>Requested selection not drawn</span>
                </div>
                <p className="text-[11px] leading-snug">
                  {selectionFallback.reason
                    ? `The selected programme could not be drawn (${selectionFallback.reason}). `
                    : 'The selected programme could not be drawn. '}
                  The plan on this page is the plate&apos;s legal programme — not the layout
                  you selected.
                </p>
                {selectionFallback.unplaced.length > 0 && (
                  <div data-testid="selection-unplaced-ledger" className="space-y-1">
                    <span className="text-[11px] font-semibold">
                      Selected rooms not drawn ({selectionFallback.unplaced.length}):
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {selectionFallback.unplaced.map((rid) => (
                        <span
                          key={rid}
                          className="inline-flex items-center px-2 py-0.5 rounded-full bg-rose-500/15 border border-rose-500/30 text-[11px] font-medium capitalize"
                        >
                          {rid.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Unmet Requirements Ledger: requested rooms the solver could not place */}
            {floorPlan.unmet_requirements && floorPlan.unmet_requirements.length > 0 && (
              <div
                data-testid="unmet-ledger"
                className="mt-2.5 p-3 rounded-[10px] bg-rose-500/10 border border-rose-500/25 text-rose-800 dark:text-rose-200 space-y-1.5"
              >
                <div className="flex items-center gap-1.5 font-semibold text-[12px]">
                  <Icon name="shield-alert" size={13} className="shrink-0" />
                  <span>Unmet Requirements ({floorPlan.unmet_requirements.length})</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {floorPlan.unmet_requirements.map((u, idx) => (
                    <span
                      key={idx}
                      title={u.reason}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-500/15 border border-rose-500/30 text-[11px] font-medium text-rose-900 dark:text-rose-100"
                    >
                      <span className="capitalize">{u.room_id.replace(/_/g, ' ')}</span>
                    </span>
                  ))}
                </div>
                <ul className="text-[11px] space-y-0.5 pl-4 list-disc text-rose-900/80 dark:text-rose-100/80">
                  {floorPlan.unmet_requirements.map((u, idx) => (
                    <li
                      key={idx}
                      data-testid={`unmet-room-${u.room_id}`}
                      data-reason={u.reason}
                      className="leading-snug"
                    >
                      <span className="capitalize font-semibold mr-1">{u.room_id.replace(/_/g, ' ')}:</span>{u.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* ONE warning surface: verdict → failures → relaxations →
                advisories → engine log. T4 operations never inflate the warning
                counts; the full verbatim list stays one click away. */}
            <WarningReportView
              warnings={floorPlan.warnings ?? []}
              relaxations={relaxations}
              planVerdict={planVerdict}
              certificateFailures={floorPlan.mathematical_certificate?.failures ?? []}
              prebuiltReport={warningReport}
            />

            {/* Advisor + remediation: the deterministic summary is instant; the
                advisory paragraph is optional and never authoritative. */}
            <PlanAdvisorPanel
              plan={floorPlan}
              report={warningReport}
              request={remediationRequest}
              planVerdict={planVerdict}
              isGenerating={isGenerating}
              onApply={handleApplyRemediation}
            />

            {/* Critic Notes */}
            {floorPlan.qa?.critic_notes && floorPlan.qa.critic_notes.length > 0 && (
              <div className="mt-2 p-2.5 rounded-[10px] bg-blue-500/10 border border-blue-500/25 text-[11px] text-blue-800 dark:text-blue-200">
                <span className="font-semibold mr-1">Architect Critic Notes:</span>
                <span>{floorPlan.qa.critic_notes.join('; ')}</span>
              </div>
            )}
          </div>

          {/* Key-Value Metrics Rows */}
          <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
            <div className="h-10 flex items-center justify-between px-0.5">
              <span className="text-[13px] font-normal text-[var(--text-2)]">Vastu compliance</span>
              <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                {floorPlan.metrics.vastu_compliance_pct != null ? `${floorPlan.metrics.vastu_compliance_pct.toFixed(0)}%` : '—'}
              </span>
            </div>
            <div className="h-10 flex items-center justify-between px-0.5">
              <span className="text-[13px] font-normal text-[var(--text-2)]">Plumbing adjacency efficiency</span>
              <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                {floorPlan.metrics.plumbing_adjacency_score != null ? `${floorPlan.metrics.plumbing_adjacency_score.toFixed(0)}%` : '—'}
              </span>
            </div>
            <div className="h-10 flex items-center justify-between px-0.5">
              <span className="text-[13px] font-normal text-[var(--text-2)]">Space utilization</span>
              <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                {floorPlan.metrics.space_utilization_pct != null ? `${floorPlan.metrics.space_utilization_pct.toFixed(0)}%` : '—'}
              </span>
            </div>
            <div className="h-10 flex items-center justify-between px-0.5">
              <span className="text-[13px] font-normal text-[var(--text-2)]">Plot coverage ratio</span>
              <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                {floorPlan.metrics.plot_coverage_pct ? `${floorPlan.metrics.plot_coverage_pct.toFixed(0)}%` : '—'}
              </span>
            </div>
            <div className="h-10 flex items-center justify-between px-0.5">
              <span className="text-[13px] font-normal text-[var(--text-2)]">Circulation</span>
              <span className="text-[13px] font-semibold text-[var(--semantic-green-ink)] capitalize tabular-nums whitespace-nowrap">
                {floorPlan.metrics.circulation_status || floorPlan.qa?.circulation || 'Connected'}
              </span>
            </div>
            {floorPlan.qa && (
              <>
                {/* The gate verdict and the invariant score are separate rows:
                    "0 violations" beside a WARN gate was a contradiction (audit
                    F15). Each row now reports the thing it actually measures. */}
                <div className="h-10 flex items-center justify-between px-0.5" data-testid="qa-gate-row">
                  <span className="text-[13px] font-normal text-[var(--text-2)]">Validation gate</span>
                  <span className={`text-[13px] font-semibold tabular-nums whitespace-nowrap ${
                    gateStatus === 'PASS'
                      ? 'text-[var(--semantic-green-ink)]'
                      : gateStatus === 'FAIL'
                      ? 'text-rose-600'
                      : gateStatus === 'WARN'
                      ? 'text-amber-700 dark:text-amber-300'
                      : 'text-[var(--text-2)]'
                  }`}>
                    {gateStatus || 'NOT RUN'}
                    {gateStatus === 'WARN' && gateWarnCount > 0 ? ` (${gateWarnCount} advisory)` : ''}
                    {gateStatus === 'FAIL' && gateFailCount > 0 ? ` (${gateFailCount} failed)` : ''}
                  </span>
                </div>
                {typeof floorPlan.qa.invariants_total === 'number' && floorPlan.qa.invariants_total > 0 && (
                  <div className="h-10 flex items-center justify-between px-0.5" data-testid="qa-invariants-row">
                    <span className="text-[13px] font-normal text-[var(--text-2)]">Solver invariants</span>
                    <span className={`text-[13px] font-semibold tabular-nums whitespace-nowrap ${
                      (floorPlan.qa.invariants_verified ?? 0) === floorPlan.qa.invariants_total
                        ? 'text-[var(--semantic-green-ink)]'
                        : 'text-amber-700 dark:text-amber-300'
                    }`}>
                      {floorPlan.qa.invariants_verified ?? 0}/{floorPlan.qa.invariants_total} verified
                    </span>
                  </div>
                )}
                {floorPlan.qa.critic && (
                  <div className="h-10 flex items-center justify-between px-0.5">
                    <span className="text-[13px] font-normal text-[var(--text-2)]">Architect critic (advisory)</span>
                    <span className={`text-[13px] font-semibold tabular-nums whitespace-nowrap ${
                      floorPlan.qa.critic === 'pass'
                        ? 'text-[var(--semantic-green-ink)]'
                        : floorPlan.qa.critic === 'skipped'
                        ? 'text-[var(--text-2)]'
                        : 'text-rose-600'
                    }`}>
                      {floorPlan.qa.critic === 'pass'
                        ? 'Passed'
                        : floorPlan.qa.critic === 'skipped'
                        ? 'Not run'
                        : 'Flagged'}
                    </span>
                  </div>
                )}
              </>
            )}
            <div className="h-10 flex items-center justify-between px-0.5">
              <span className="text-[13px] font-normal text-[var(--text-2)]">Engine latency</span>
              <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                {floorPlan.timing_ms.toFixed(0)}ms
              </span>
            </div>
          </div>

          {/* Mathematical Validity Certificate & Relaxations Panel */}
          {(() => {
            const cert = floorPlan.mathematical_certificate || floorPlan.multi_storey?.mathematical_certificate;
            if (!cert) return null;
            const certId = cert.certificate_id || 'CERT-MATH-VALID-2026';
            const isValid = Boolean(cert.is_valid);

            // A missing flag is NOT a pass: 'undefined' renders as NOT RUN
            // Instead of silently becoming a green check.
            const certChecks = [
              { name: 'Non-Overlap & Containment', pass: cert.non_overlap && cert.containment, ref: 'REL-01 / CONT-01' },
              { name: 'Zero Forbidden Wall Pairs', pass: cert.zero_forbidden_violations, ref: 'REL-02 / FORBIDDEN' },
              { name: 'BFS Circulation Reachability', pass: cert.connectivity_bfs, ref: 'CIRC-01 / BFS-GRAPH' },
              { name: 'Dimension Chains Sum (≤1mm)', pass: cert.chain_sums_match, ref: 'DIM-01 / NBC-TOLERANCE' },
              { name: 'NBC Egress Travel Distance', pass: cert.egress_distances_satisfied, ref: 'NBC-03 / EGRESS-30M' },
              { name: 'Vertical Stack Alignment', pass: cert.vertical_stack_valid, ref: 'VERT-01..05 / CORE-STACK' },
              { name: 'NBC Room Minimums', pass: cert.min_dimensions_satisfied, ref: 'NBC-01 / ROOM-MIN' },
              { name: 'Aspect Ratio Limits', pass: cert.aspect_ratios_satisfied, ref: 'NBC-02 / ASPECT' },
              { name: 'NBC Sanitation Count', pass: cert.sanitation_wc_count_satisfied, ref: 'SAN-01 / NBC-TABLE-12' },
            ];

            // Only rules the certificate actually verified are listed; there is
            // No optimistic fallback list.
            const certifiedRules: string[] = cert.certified_rules || [];
            const certFailures: string[] = Array.isArray(cert.failures) ? cert.failures : [];
            // The badge follows the PLAN verdict. A certified geometry
            // with named programme deficits must not read "CERTIFIED" here.
            const verdictBadge = planVerdictBadge(planVerdict);
            const badge = {
              text: verdictBadge.text,
              cls:
                verdictBadge.tone === 'red'
                  ? 'bg-rose-600 text-white'
                  : verdictBadge.tone === 'amber'
                  ? 'bg-amber-500 text-white'
                  : 'bg-emerald-600 text-white',
            };

            return (
              <div className="p-3 rounded-[12px] bg-emerald-500/5 border border-emerald-500/20 text-[12px] space-y-2.5">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-1.5 font-semibold text-[13px] text-emerald-800 dark:text-emerald-300">
                    <Icon name="check-circle" size={15} className="text-[var(--semantic-green-ink)] shrink-0" />
                    <span>Mathematical Validity Certificate</span>
                    <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-[var(--semantic-green-ink)]">
                      {certId}
                    </span>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${badge.cls}`}
                    data-testid="certificate-verdict"
                  >
                    {badge.text}
                  </span>
                </div>

                {/* 6 Invariant Verification Badges */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                  {certChecks.map((chk, idx) => (
                    <div
                      key={idx}
                      className="p-1.5 px-2 rounded-[8px] bg-white/60 dark:bg-black/20 border border-[var(--hairline)] flex items-center justify-between text-[11px]"
                    >
                      <span className="font-medium text-[var(--text-1)] truncate mr-1.5">{chk.name}</span>
                      <div className="flex items-center gap-1 shrink-0 font-mono text-[10px]">
                        <span className="text-[var(--text-3)]">{chk.ref}</span>
                        <span className={`font-bold px-1.5 py-0.2 rounded ${
                          chk.pass === true
                            ? 'bg-emerald-500/15 text-[var(--semantic-green-ink)]'
                            : chk.pass === false
                            ? 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
                            : 'bg-[var(--fill)] text-[var(--text-3)]'
                        }`}>
                          {chk.pass === true ? 'PASS' : chk.pass === false ? 'FAIL' : 'NOT RUN'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* WHY THE CERTIFICATE WAS WITHHELD: the headline
                    rows above can all pass while a non-headline invariant fails;
                    the badge is never left unexplained. */}
                {(!isValid || certFailures.length > 0) && (
                  <div
                    className="p-2 rounded-[8px] bg-rose-500/10 border border-rose-500/25 text-[11px] text-rose-900 dark:text-rose-100 space-y-1"
                    data-testid="certificate-failures"
                  >
                    <div className="font-semibold">
                      Non-compliance reasons ({certFailures.length})
                    </div>
                    {certFailures.length > 0 ? (
                      <ul className="space-y-0.5 pl-4 list-disc">
                        {certFailures.map((f, idx) => (
                          <li key={idx} className="leading-snug">{f}</li>
                        ))}
                      </ul>
                    ) : (
                      <div className="leading-snug">
                        The certificate was withheld without a stated invariant — treat this plan as unverified.
                      </div>
                    )}
                  </div>
                )}

                {/* UNIVERSAL VALIDATION GATE - single renderer.
                    Rows, N/A reasons, WARN chips and the incomplete-gate flag
                    all come from CertificatePanel so this card and the report
                    sheet cannot drift. */}
                {(() => {
                  const gate = (cert.details && cert.details.validation_gate) || floorPlan.qa?.validation_gate;
                  if (!gate || !Array.isArray(gate.layers) || gate.layers.length === 0) return null;
                  return (
                    <div className="pt-2 border-t border-emerald-500/20">
                      <CertificatePanel
                        qa={{ ...(floorPlan.qa || {}), validation_gate: gate } as any}
                        relaxationsCount={relaxations.length}
                        planVerdict={planVerdict}
                      />
                    </div>
                  );
                })()}

                {/* Certified Rule IDs list */}
                <div className="text-[11px] text-[var(--text-2)] flex items-baseline gap-1.5 flex-wrap">
                  <span className="font-semibold text-[var(--text-1)]">Certified Rule IDs:</span>
                  <span className="font-mono text-[10px] text-[var(--text-3)]">
                    {certifiedRules.join(', ')}
                  </span>
                </div>

              </div>
            );
          })()}

          {/* Scheme alternatives: selecting one re-solves the plate. */}
          {schemeAlternatives.length > 0 && (
            <div className="space-y-1.5">
              <SchemePicker
                alternatives={schemeAlternatives}
                selectedSchemeId={schemeProfile}
                selectionStatus={schemeSelectionStatus}
                pendingProfile={pendingSchemeProfile}
                disclosure={schemeDisclosure}
                onSelect={handleSelectScheme}
                disabled={isGenerating}
              />
              {schemeSelectionStatus === 'rejected_non_compliant' && schemeFailingLayers.length > 0 && (
                <div
                  className="text-[10px] text-[var(--semantic-red-ink)] leading-snug"
                  data-testid="scheme-rejected-layers"
                >
                  Failing layers: {schemeFailingLayers.join(', ')}
                </div>
              )}
            </div>
          )}

          {/* Blueprint SVG Viewer with Stale Plan Guard & Site Plan Tab.
              Mounted one idle slice after the plan lands (see `viewerReady`),
              behind a same-height placeholder so the arrival is chunked without
              moving anything. */}
          {viewerReady ? (
            <BlueprintViewer
              svgString={floorPlan.svg_blueprint}
              svgPaperString={floorPlan.svg_blueprint_paper}
              placements={floorPlan.placements}
              plotWidthM={plotWidth}
              plotDepthM={plotDepth}
              multiStorey={floorPlan.multi_storey}
              sitePlan={floorPlan.site_plan || floorPlan.multi_storey?.site_plan}
              generationTimestamp={floorPlan.generated_at}
              generationId={floorPlan.generation_id}
              storeys={activeFloors}
              isStale={isPlanStale}
              requestedTypology={activeTypology}
              planVerdict={planVerdict}
            />
          ) : (
            <Skeleton
              className="h-[360px] w-full rounded-[16px]"
              label="Rendering architectural blueprint"
            />
          )}
        </div>
      )}
    </div>
  );
};
