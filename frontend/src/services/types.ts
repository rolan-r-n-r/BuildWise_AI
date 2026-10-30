/**
 * Storage-key namespaces used by this app (no migration required — every key
 * is live; documented here so future authors extend rather than fork):
 *   bw.*            localStorage/sessionStorage UI state (bw.report.sections.v1,
 *                   bw.coach.<id>, bw.assisted.continue)
 *   buildwise.*     localStorage feature prefs (buildwise.units)
 *   bw_geocode_v1:* localStorage geocode response cache (versioned prefix)
 */
export interface AnalysisRequest {
  latitude: number;
  longitude: number;
  built_up_area_sqft: number;
  quality_grade: 'basic' | 'standard' | 'premium';
  building_typology: string;
  floors: number;
  ai_provider: string;
  override_land_rate_per_sqft?: number;
  plot_area_sqft?: number;
  ground_coverage_ratio?: number;
  client_requirements?: string;
  extracted_constraints?: ExtractedClientConstraints;
  /** Optional map-captured boundary (the server re-validates authoritatively). */
  boundary?: BoundarySummaryPayload | null;
}

/**
 * Analysis parameters: everything the request carries EXCEPT where the site is.
 *
 * The site's coordinates are deliberately not part of the app's parameter state.
 * The captured plot owns them (see `siteLocation` in App.tsx), so there is only
 * one value pair for "where this is" and no second copy to keep in step; the
 * coordinates are attached when a request is built.
 */
export type AnalysisParams = Omit<AnalysisRequest, 'latitude' | 'longitude'>;

/** Mirrors the backend BoundarySummary wire shape ({x,y} vertices in local meters). */
export interface BoundarySummaryPayload {
  vertices: { x: number; y: number }[];
  origin_lat: number;
  origin_lon: number;
  shape_type: string;
  area_sqm: number;
  perimeter_m: number;
  source: string;
  frontage_edge_index: number | null;
}

export interface FactorScore {
  factor_id: string;
  name: string;
  weight: number;
  raw_value: number | null;
  unit: string;
  score: number;
  status: 'optimal' | 'acceptable' | 'critical' | 'unknown';
  details: string;
}

export interface OrientationData {
  optimal_axis_degrees: number;
  axis_label: string;
  prevailing_wind_direction_degrees: number;
  solar_exposure_summary: string;
  cross_ventilation_rating: string;
  passive_design_rationale: string;
}

export interface CostItem {
  category: string;
  amount_inr: number;
  percentage: number;
  description: string;
}

export interface CostEstimate {
  base_rate_per_sqft: number;
  terrain_multiplier: number;
  base_cost_inr: number;
  terrain_surcharge_inr: number;
  total_estimated_cost_inr: number;
  cost_range_min_inr: number;
  cost_range_max_inr: number;
  breakdown: CostItem[];
  currency: string;
  disclaimer: string;
}

export interface RiskItem {
  severity: 'low' | 'medium' | 'high';
  category: string;
  title: string;
  description: string;
  mitigation_strategy: string;
}

// ----------------------------------------------------
// New Modules Interfaces
// ----------------------------------------------------

export interface SeismicEvent {
  magnitude: number;
  date_iso: string;
  distance_km: number;
  place: string;
}

export interface SeismicProfile {
  // Null when the site lies outside the IS 1893:2016
  // mapping extent - render as a distinct "Not Assessed" state, never a default zone.
  zone: string | null;
  zone_factor: number | null;
  standard: string;
  district?: string | null;
  state?: string | null;
  event_count: number;
  is_capped: boolean;
  event_count_display: string;
  max_magnitude?: number | null;
  years_since_last_event?: number | null;
  recent_major_events: SeismicEvent[];
  confidence: 'high' | 'moderate' | 'low';
  confidence_warning?: string | null;
}

export interface FloodProfile {
  discharge_peak_to_mean_ratio?: number | null;
  pressure_level: 'low' | 'moderate' | 'high';
  ndma_flood_prone: boolean;
  elevation_amsl_m?: number | null;
  confidence: 'high' | 'moderate' | 'low';
  confidence_warning?: string | null;
}

export interface StormCycloneProfile {
  max_annual_gust_kmh?: number | null;
  extreme_rainfall_days?: number | null;
  exposure_level: 'low' | 'moderate' | 'high';
  ndma_cyclone_prone: boolean;
  confidence: 'high' | 'moderate' | 'low';
  confidence_warning?: string | null;
}

export interface HazardProfile {
  seismic: SeismicProfile;
  flood: FloodProfile;
  storm_cyclone: StormCycloneProfile;
  overall_hazard_level: 'low' | 'moderate' | 'high' | 'critical';
  warnings: string[];
}

export interface MultiplierBreakdown {
  road_accessibility_score: number;
  road_contribution: number;
  facility_proximity_score: number;
  facility_contribution: number;
  net_multiplier: number;
  is_clamped: boolean;
}

export interface LandValueEstimate {
  indicative_rate_per_sqft?: number | null;
  base_table_rate_per_sqft?: number | null;
  is_user_override: boolean;
  locality_multiplier: number;
  multiplier_breakdown: MultiplierBreakdown;
  plot_area_sqft: number;
  /** Where plot_area_sqft came from. The report may only label the number a
   * "captured boundary" when this is 'captured_boundary'. */
  plot_area_source?: 'captured_boundary' | 'client_plot_area' | 'derived_from_coverage';
  /** Shoelace area of the captured boundary, in sq ft (null when none). */
  boundary_area_sqft?: number | null;
  plot_area_warnings?: string[];
  ground_coverage_ratio_applied: number;
  land_cost_inr?: number | null;
  construction_cost_inr: number;
  combined_project_total_inr?: number | null;
  as_of_year?: number | null;
  jurisdiction_zone?: string | null;
  source_publication?: string | null;
  disclaimer: string;
  confidence_warning?: string | null;
}

export interface RankedEntrance {
  direction: string;
  score: number;
  vastu_rationale: string;
  is_approach_side: boolean;
}

export interface RoomGridZone {
  zone: string;
  zone_name: string;
  primary_room: string;
  alternative_room: string;
  prohibited: string[];
  vastu_rationale: string;
  civil_engineering_rationale: string;
}

export interface SlopeReading {
  drainage_direction: string;
  auspiciousness: 'favourable' | 'neutral' | 'requires_remedy';
  rationale: string;
  remedy_notes?: string | null;
}

export interface ReconciliationItem {
  topic: string;
  status: 'concordant' | 'divergent';
  vastu_position: string;
  scientific_passive_position: string;
  recommended_synthesis: string;
}

export interface RoadApproach {
  bearing_degrees?: number | null;
  approach_side: string;
  distance_meters?: number | null;
  is_fallback: boolean;
}

export interface VastuAdvisory {
  ranked_entrances: RankedEntrance[];
  room_grid: RoomGridZone[];
  slope_reading: SlopeReading;
  reconciliation_notes: ReconciliationItem[];
  road_approach: RoadApproach;
}

export interface RecommendationItem {
  rule_id: string;
  category: string;
  category_label: string;
  severity: 'critical' | 'advisory' | 'optimal';
  trigger_condition: string;
  source_data_ref: string;
  recommendation_text: string;
  id?: string;
  title?: string;
  description?: string;
}

export interface AnalysisResponse {
  request_id: string;
  timestamp: string;
  coordinates: {
    latitude: number;
    longitude: number;
  };
  formatted_address: string;
  overall_suitability_score: number;
  suitability_verdict: 'Suitable' | 'Conditionally Suitable' | 'Challenging';
  factors: FactorScore[];
  orientation: OrientationData;
  cost_estimate: CostEstimate;
  risks: RiskItem[];
  engineering_summary: string;
  detailed_recommendations: string[];
  hazard_profile?: HazardProfile;
  land_value?: LandValueEstimate;
  vastu_advisory?: VastuAdvisory;
  recommendation_items?: RecommendationItem[];
  site_vision?: SiteVisionResponse;
  floorplan?: FloorPlanResponse;
  parameter_reflection?: string;
  feasibility_score?: number;
  structural_recommendations?: string[];
  cost_breakdown?: Record<string, any>;
  vastu_compliance?: Record<string, any>;
  ai_metadata: {
    provider_requested?: string;
    provider_used?: string;
    generation_time_ms?: string;
    fallback_reason?: string;
    parameter_reflection?: string;
    /** Never rendered as a report value; stripped server-side. */
    feasibility_score?: string;
    narrative_class?: string;
    narrative_redactions?: string;
  };
  degraded_mode: boolean;
  warnings: string[];
  /** Per-source fetch provenance: real server ISO8601 fetch timestamps; null
   *  means the upstream degraded to its disclosed fallback model. */
  data_sources?: Record<string, DataSourceProvenance>;
  /** Generated methodology disclosures keyed by factor id. */
  methodology?: Record<string, string>;
  /** Server-validated echo of the captured boundary. */
  boundary_summary?: BoundarySummary | null;
}

/** Server-validated boundary echo: every value recomputed server-side. */
export interface BoundarySummary {
  vertex_count: number;
  area_sqm: number;
  area_sqft: number;
  perimeter_m: number;
  shape_type: string;
  source: string;
  frontage_edge_index?: number | null;
  frontage_annotation?: string | null;
  origin: { lat: number; lon: number };
  winding: 'cw' | 'ccw' | string;
  captured: boolean;
  authoritative: boolean;
  client_area_sqm?: number | null;
  area_delta_pct?: number | null;
  provenance: {
    boundary_source: string;
    projection: string;
    origin: { lat: number; lon: number };
    area_method?: string;
  };
}

export interface DataSourceProvenance {
  source: string;
  fetched_at: string | null;
  is_fallback: boolean;
}

// ----------------------------------------------------
// Satellite Vision & Tree Preservation Module
// ----------------------------------------------------

export type SiteVisionMode = 'segformer' | 'index-only' | 'unavailable';
export type PreservationRank = 'preserve' | 'compensate' | 'removable' | 'context';

export interface SiteVisionRequest {
  latitude: number;
  longitude: number;
  plot_area_sqft?: number;
  mode_override?: 'segformer' | 'index-only';
  orientation_deg?: number;
}

export interface SceneMetadata {
  id: string;
  datetime: string;
  cloud_cover_pct: number;
  source: string;
}

export interface PreservationItem {
  cluster_id: string;
  area_sqm: number;
  centroid: [number, number];
  mean_ndvi: number;
  overlap_footprint: boolean;
  rank: PreservationRank;
  action: string;
}

export interface GeoJsonFeature {
  type: 'Feature';
  geometry: {
    type: 'Polygon' | 'MultiPolygon';
    coordinates: number[][][] | number[][][][];
  };
  properties: {
    cluster_id: string;
    area_sqm: number;
    mean_ndvi?: number;
    rank?: PreservationRank;
    [key: string]: any;
  };
}

export interface GeoJsonFeatureCollection {
  type: 'FeatureCollection';
  features: GeoJsonFeature[];
}

export interface SiteVisionResponse {
  mode: SiteVisionMode;
  scene_metadata?: SceneMetadata | null;
  green_cover_pct: number;
  water_cover_pct: number;
  built_up_pct: number;
  tree_clusters: GeoJsonFeatureCollection;
  water_bodies: GeoJsonFeatureCollection;
  preservation_plan: PreservationItem[];
  warnings: string[];
  timing_ms: Record<string, number>;
}

// ----------------------------------------------------
// Generative Floor Plan Engine Interfaces (Sole Geometry Engine - Ontology-Driven)
// ----------------------------------------------------

export interface EnvelopeRect {
  x: number;
  y: number;
  width: number;
  height: number;
  area_sqm: number;
}

export interface RoomRectangle {
  room_id: string;
  room_name: string;
  x: number;
  y: number;
  width: number;
  height: number;
  area_sqm: number;
  zone: string;
  vastu_compliant: boolean;
}

export interface DoorGeometry {
  door_id: string;
  from_room: string;
  to_room: string;
  wall_edge: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  hinge_x: number;
  hinge_y: number;
  swing_direction: string;
  width_m: number;
}

export interface WindowGeometry {
  window_id: string;
  room_id: string;
  wall_edge: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  width_m: number;
}

export interface FloorPlanQA {
  entry: string;
  circulation: string;
  leaf_rule?: boolean;
  peripheral_service?: boolean;
  catalog?: boolean;
  aspect?: boolean;
  critic?: string;
  violations: number;
  critic_notes?: string[];
  validation_gate?: ValidationGateReport;
  validation_gate_status?: 'PASS' | 'WARN' | 'FAIL';
  invariants_verified?: number;
  invariants_total?: number;
}

export interface RectanglesModel {
  envelope: EnvelopeRect;
  rooms: RoomRectangle[];
  doors: DoorGeometry[];
  windows: WindowGeometry[];
  qa?: FloorPlanQA;
}

export interface RoomSpec {
  name: string;
  min_area_pct: number;
  max_area_pct: number;
  vastu_zone: 'N' | 'NE' | 'E' | 'SE' | 'S' | 'SW' | 'W' | 'NW' | 'CENTER';
  adjacency: string[];
  requires_plumbing: boolean;
  priority: number;
}

export interface SolverHints {
  target_utilization: number;
  allow_corridors: boolean;
}

export interface RoomProgram {
  rooms: RoomSpec[];
  design_intent: string;
  solver_hints: SolverHints;
}

export interface VerticalCoreSpec {
  core_id: string;
  core_type: 'staircase_dogleg' | 'staircase_fire' | 'lift_passenger' | 'lift_service' | 'mep_chase';
  x: number;
  y: number;
  width_m: number;
  depth_m: number;
  landing_depth_m?: number;
  tread_mm: number;
  riser_mm: number;
  continuous_across_floors: number[];
}

export interface DuctShaftSpec {
  shaft_id: string;
  shaft_type: 'plumbing_wet' | 'electrical_mep' | 'hvac_vent';
  x: number;
  y: number;
  width_m: number;
  depth_m: number;
  servicing_rooms: string[];
}

export interface SpaceIdentity {
  space_type_id: string;
  name: string;
  zone: string;
  function: string;
  hygiene_class: string;
  clear_area_basis: 'clear_face' | 'carpet' | 'gross';
  min_area_sqm: number;
  min_width_m: number;
  max_aspect_ratio: number;
  citation: string;
  ventilation_req: string;
  daylight_req: boolean;
  is_wet: boolean;
  orientation_preference: string[];
  orientation_avoid: string[];
  source: 'ontology' | 'fallback';
}

export interface MultiFloorRoomRectangle {
  room_id: string;
  room_name: string;
  floor_index: number;
  unit_id?: string;
  x: number;
  y: number;
  width_m: number;
  depth_m: number;
  area_sqm: number;
  zone: string;
  zone_category: 'public' | 'private' | 'service' | 'circulation' | 'industrial_bay' | 'terrace';
  vastu_compliant: boolean;
  is_vertical_core?: boolean;
  requires_exterior_wall?: boolean;
  naming_threshold_used?: string;
  aspect_ratio?: number;
  applied_rules?: string[];
  relaxations?: Array<Record<string, string>>;
  fixtures?: BathroomFixtureSpec[];
  furniture?: FurnitureItemSpec[];
  space_type_id?: string;
  identity?: SpaceIdentity;
  scheme_profile?: string;
  orientation_rationale?: string;
  score_contributions?: Record<string, number>;
}

export interface BathroomFixtureSpec {
  fixture_id: string;
  fixture_type: 'wc' | 'wash_basin' | 'shower';
  x: number;
  y: number;
  width_m: number;
  depth_m: number;
  clearance_front_m: number;
  clearance_side_m: number;
  is_satisfied: boolean;
  clearance_notes?: string;
}

export interface FurnitureItemSpec {
  item_id: string;
  item_type: string;
  x: number;
  y: number;
  width_m: number;
  depth_m: number;
  circulation_clearance_m: number;
  is_satisfied: boolean;
}

export interface MultiFloorDoorGeometry {
  door_id: string;
  floor_index: number;
  from_room: string;
  to_room: string;
  wall_edge: 'north' | 'south' | 'east' | 'west' | 'vertical' | 'horizontal';
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  hinge_x: number;
  hinge_y: number;
  swing_direction: 'inward_right' | 'inward_left' | 'outward_right' | 'outward_left';
  width_m: number;
  door_type?: 'standard' | 'fire_rated' | 'sliding' | 'dock_shutter';
}

export interface MultiFloorWindowGeometry {
  window_id: string;
  floor_index: number;
  room_id: string;
  wall_edge: 'north' | 'south' | 'east' | 'west';
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  width_m: number;
  sill_height_m?: number;
}

export interface StructuralGridSpec {
  bay_spacing_x_m: number;
  bay_spacing_y_m: number;
  columns_x: number[];
  columns_y: number[];
  column_size_m: number;
}

export interface SingleFloorPlanModel {
  floor_index: number;
  floor_name: string;
  envelope: {
    x: number;
    y: number;
    width: number;
    depth: number;
    area_sqm: number;
  };
  rooms: MultiFloorRoomRectangle[];
  doors: MultiFloorDoorGeometry[];
  windows: MultiFloorWindowGeometry[];
  circulation_status: 'connected' | 'disconnected';
  vastu_score_pct: number | null;
  plumbing_stack_alignment_pct: number | null;
  built_up_area_sqm: number;
  carpet_area_sqm: number;
  svg_blueprint_cad: string;
  svg_blueprint_paper: string;
  wall_graph?: Record<string, any>;
  door_schedule?: Array<Record<string, any>>;
  window_schedule?: Array<Record<string, any>>;
  room_schedule?: Array<Record<string, any>>;
  stair_schedule?: Array<Record<string, any>>;
  mathematical_certificate?: MathematicalValidityCertificate;
  floor_plate_mask?: Record<string, string>;
  plate_composition?: string;
  terrace_band?: TerraceBandSpec;
}

export interface TerraceBandSpec {
  edge: 'N' | 'S' | 'E' | 'W';
  depth_m: number;
}

export interface MathematicalValidityCertificate {
  is_valid: boolean;
  non_overlap: boolean;
  containment: boolean;
  chain_sums_match: boolean;
  min_dimensions_satisfied: boolean;
  aspect_ratios_satisfied: boolean;
  connectivity_bfs: boolean;
  egress_distances_satisfied: boolean;
  zero_forbidden_violations: boolean;
  must_adjacency_satisfied: boolean;
  prefer_adjacency_score?: number;
  vertical_stack_valid?: boolean;
  core_continuity_valid?: boolean;
  no_wet_over_terrace_valid?: boolean;
  terrace_far_exempt?: boolean;
  cores_stack_aligned?: boolean;
  sanitation_wc_count_satisfied?: boolean;
  parking_count_satisfied?: boolean;
  l2_door_swings_valid?: boolean;
  l3_fixture_clearances_satisfied?: boolean;
  l4_furniture_clearances_satisfied?: boolean;
  l8_program_intent_satisfied?: boolean;
  layer_statuses?: ValidationGateLayer[];
  overall_layer_status?: 'PASS' | 'WARN' | 'FAIL';
  certificate_id?: string;
  certified_rules?: string[];
  /** One human-readable reason per failing invariant, naming the offending rooms. */
  failures?: string[];
  details?: Record<string, any>;
}

// ----------------------------------------------------
// Land economics (backend app/schemas/land_economics.py)
// ----------------------------------------------------

export interface LandEconomicsCertificate {
  status: 'PASS' | 'WARN' | 'FAIL' | string;
  checks: Record<string, boolean>;
  warnings: string[];
}

export interface ResidualSliver {
  sliver_id: string;
  area_sqm: number;
  centroid: [number, number];
  polygon_coords?: Array<[number, number]>;
  absorbed_as?: string;
  rationale?: string;
}

export interface LandEconomicsReport {
  program_needed_area_m2: number;
  buildable_area_sqm: number;
  coverage_limit_area_sqm: number;
  footprint_area_sqm: number;
  footprint_source: string;
  program_aware_footprint: boolean;
  program_deficit_sqm: number;
  ground_program_area_sqm: number;
  ground_circulation_area_sqm: number;
  total_gfa_sqm: number;
  land_use_efficiency_pct: number;
  footprint_utilization_pct: number;
  floor_area_ratio: number;
  circulation_ratio_pct: number;
  wedge_area_sqm: number;
  outdoor_area_sqm: number;
  occupied_area_sqm: number;
  waste_area_sqm: number;
  waste_pct: number;
  anonymous_outdoor_area_sqm: number;
  dead_corner_area_sqm: number;
  sliver_count: number;
  slivers: ResidualSliver[];
  absorbed_residual_count: number;
  furniture_fit_pct?: number | null;
  warnings: string[];
  certificate: LandEconomicsCertificate;
}

// ----------------------------------------------------
// Scheme portfolio (backend app/schemas/scheme.py)
// ----------------------------------------------------

export interface SchemeMetrics {
  land_use_efficiency_pct: number;
  circulation_ratio_pct: number;
  vastu_score: number;
  daylight_score: number;
  relation_score: number;
  compactness_score: number;
  total_score: number;
  forbidden_violations: number;
  must_adjacency_score: number;
  prefer_score: number;
  egress_connected: boolean;
  min_area_violations: number;
  min_width_violations: number;
  aspect_violations: number;
  furniture_fit_pct: number;
  program_area_sqm: number;
  circulation_area_sqm: number;
  envelope_area_sqm: number;
  program_deficit_sqm: number;
  dropped_rooms: string[];
}

export interface SchemeAlternative {
  scheme_id: string;
  profile: 'max_area' | 'max_vastu' | 'max_light_vent' | string;
  label: string;
  rank: number;
  feasible: boolean;
  score: number;
  weights: Record<string, number>;
  metrics: SchemeMetrics;
  delta_vs_engine: Record<string, number | null>;
  delta_vs_best: Record<string, number | null>;
  floors: Array<{
    floor_index: number;
    floor_name: string;
    envelope: Record<string, any>;
    rooms: any[];
    doors?: any[];
    windows?: any[];
    svg_blueprint_cad?: string | null;
    svg_blueprint_paper?: string | null;
    metrics?: Record<string, any>;
  }>;
  warnings: string[];
  provenance: Record<string, any>;
}

export interface SchemePortfolio {
  seed: number;
  typology: string;
  reference_metrics: SchemeMetrics;
  alternatives: SchemeAlternative[];
  selected_scheme_id?: string | null;
  selection_source: string;
  provenance: Record<string, any>;
}

// ----------------------------------------------------
// Universal Validation Gate (L1-L15)
// ----------------------------------------------------

export interface ValidationGateLayer {
  layer_id: string;
  title: string;
  status: 'PASS' | 'WARN' | 'FAIL' | 'N/A';
  summary?: string;
  reason?: string; // mandatory when status === 'N/A'
  findings?: string[];
  citation?: string;
  details?: Record<string, any>;
}

export interface ValidationGateReport {
  layer_ids: string[];
  layers: ValidationGateLayer[];
  overall_status: 'PASS' | 'WARN' | 'FAIL';
  validated_layers: string[];
  n_a_layers?: Array<{ layer_id: string; reason: string }>;
  llm_boundary?: { events?: Array<Record<string, any>>; event_ids?: string[]; contract?: string };
  evaluated_at?: string;
  contract?: string;
}

// ----------------------------------------------------
// Canonical Site Layer & Irregular Plot Polygon Models
// ----------------------------------------------------

export interface PlotVertex {
  id: string;
  x_m: number;
  y_m: number;
}

export interface PlotPolygon {
  vertices: [number, number][]; // ordered (x_m, y_m) in local tangent plane (+X East, +Y North)
  origin_lat?: number | null;
  origin_lon?: number | null;
  projection_note?: string;
  shape_type?: 'rectangle' | 'trapezoid' | 'l_shape' | 'pentagon' | 'polygon';
  area_sqm?: number;
  perimeter_m?: number;
  bounding_box?: [number, number, number, number];
  is_regular_rectangle?: boolean;
}

export interface SurveyEdge {
  edge_id: string;
  start_vertex: string;
  end_vertex: string;
  length_m: number;
  bearing_deg: number;
  bearing_str: string;
}

export interface OutdoorFragment {
  id: string;
  label: string;
  area_sqm: number;
  centroid_x: number;
  centroid_y: number;
  polygon_coords: [number, number][];
}

export interface InscribedFootprint {
  x: number;
  y: number;
  width_m: number;
  depth_m: number;
  area_sqm: number;
  rotation_angle_deg: number;
  center_x: number;
  center_y: number;
  corner_vertices: [number, number][];
}

export interface SiteCertificate {
  footprint_contained_in_buildable: boolean;
  setback_distance_satisfied: boolean;
  min_setback_achieved_m: number;
  required_setback_m: number;
  ground_coverage_actual_pct: number;
  ground_coverage_limit_pct: number;
  far_actual: number;
  far_limit: number;
  is_valid: boolean;
  diagnostics: string[];
}

export interface WedgeZone {
  wedge_id: string;
  classification: 'storage_closet' | 'duct_shaft' | 'planter' | 'stair_wedge' | 'parking_apron' | string;
  name: string;
  area_sqm: number;
  centroid: [number, number];
  polygon_coords: [number, number][];
  is_enclosed_storage: boolean;
  is_interior_side: boolean;
  width_m: number;
  length_m: number;
}

export interface ParkingBay {
  bay_id: string;
  x: number;
  y: number;
  width_m: number;
  length_m: number;
  orientation_deg: number;
}

export interface ParkingEnvelope {
  required_ecs: number;
  provided_ecs: number;
  bays: ParkingBay[];
  drive_aisle_width_m: number;
  drive_aisle_polygon: [number, number][];
  total_parking_area_sqm: number;
  coexistence_status: 'COEXISTENT' | 'DEFICIT_WARNED';
  deficit_warning?: string;
  coexistence_options: string[];
}

export interface SiteSheetChecklist {
  road_side_and_width: boolean;
  vehicular_gate_and_pedestrian_entry: boolean;
  parking_bays_with_dims: boolean;
  sewer_connection_point: boolean;
  stormwater_outlet_and_drainage_arrows: boolean;
  finished_ground_level_and_slope_note: boolean;
  setback_dimensions_every_side: boolean;
  neighbour_ticks: boolean;
  is_complete: boolean;
  missing_items: string[];
}

export interface SitePlanModel {
  plot_polygon: PlotPolygon;
  buildable_polygon_coords: [number, number][];
  buildable_area_sqm: number;
  nominal_setback_m: number;
  reduced_setback_applied: boolean;
  building_line_coords?: [number, number][];
  setback_dimensions?: Record<string, number>;
  derivation_chain?: string[];
  derivation_text?: string;
  parking?: ParkingEnvelope;
  checklist?: SiteSheetChecklist;
  validated_layers?: string[];
  drawing_status_stamp?: string;
  footprint: InscribedFootprint;
  outdoor_zones: OutdoorFragment[];
  wedge_zones?: WedgeZone[];
  setback_band_area_sqm: number;
  edges: SurveyEdge[];
  vertex_table: PlotVertex[];
  site_vastu_zones?: Record<string, [number, number, number, number]>;
  certificate: SiteCertificate;
  svg_site_plan?: string;
  provenance?: Record<string, any>;
  design_policy?: string;
  design_policy_rationale?: string;
  waste_pct?: number;
  rotation_alternatives?: Array<{
    angle_deg: number;
    footprint_area_sqm: number;
    waste_pct: number;
    width_m: number;
    depth_m: number;
  }>;
  waste_warning_triggered?: boolean;
}

export interface MultiStoreyBuildingModel {
  building_typology: 'T1_SINGLE_FAMILY' | 'T2_FAMILY_APARTMENT' | 'T3_LARGE_COMPLEX' | 'T4_WAREHOUSE' | string;
  total_storeys: number;
  plot_width_m: number;
  plot_depth_m: number;
  ground_coverage_ratio: number;
  total_built_up_area_sqm: number;
  vertical_cores: VerticalCoreSpec[];
  duct_shafts: DuctShaftSpec[];
  structural_grid?: StructuralGridSpec;
  floors: SingleFloorPlanModel[];
  programme_variables?: Record<string, any>;
  units_per_floor?: number;
  strategy_chain?: StrategyChainEntry[];
  strategy_chain_line?: string;
  strategy_selected?: string;
  global_metrics: Record<string, any>;
  qa_report: Record<string, any>;
  warnings: string[];
  unmet_requirements: UnmetRequirement[];
  seed: number;
  solver_timing_ms: number;
  mathematical_certificate?: MathematicalValidityCertificate;
  validation_gate?: ValidationGateReport;
  land_economics?: LandEconomicsReport;
  plot_polygon?: PlotPolygon;
  site_plan?: SitePlanModel;
}

/** One strategy the escalation ladder actually tried, skipped or errored. */
export interface StrategyChainEntry {
  id: string;
  label: string;
  status: 'certified' | 'fail' | 'skipped' | 'error';
  disclosure: string;
  verdict?: string | null;
  certificate_valid?: boolean | null;
  gate_status?: string | null;
  warnings?: number | null;
  failures?: number | null;
  plate_area_m2?: number | null;
  floors?: number | null;
  skip_reason?: string;
  error?: string;
}

/** Requested room the solver could not place, with an explicit reason. */
export interface UnmetRequirement {
  room_id: string;
  reason: string;
}

export interface SpatialAdjacencyConstraint {
  room_a: string;
  room_b: string;
  relationship: 'connected' | 'adjacent' | 'separated';
}

export interface OrientationPreferenceConstraint {
  space: string;
  preferred_facing: 'North' | 'East' | 'South' | 'West' | 'North-East' | 'South-East' | 'South-West' | 'North-West';
}

export interface ExtractedClientConstraints {
  target_bedroom_count: number;
  target_bathroom_count: number;
  specialized_spaces: string[];
  spatial_adjacencies: SpatialAdjacencyConstraint[];
  orientation_preferences: OrientationPreferenceConstraint[];
  explicit_exclusions: string[];
  raw_notes?: string;
  extraction_source?: 'groq_llm' | 'gemini_llm' | 'regex_fallback';
}

export interface FloorPlanRequest {
  plot_width_m: number;
  plot_depth_m: number;
  required_rooms?: string[];
  vastu_strictness: 'high' | 'medium' | 'low';
  building_typology?: string;
  quality_grade?: string;
  floors?: number;
  built_up_area_sqft?: number;
  ground_coverage_ratio?: number;
  client_notes?: string;
  ai_provider?: string;
  room_program?: RoomProgram;
  solar_axis_degrees?: number;
  prevailing_wind_direction_degrees?: number;
  top_vastu_entrances?: string[];
  program_source?: string;
  bypass_cache?: boolean;
  extracted_constraints?: ExtractedClientConstraints;
  plot_polygon?: PlotPolygon;
  floor_plate_masks?: Record<number | string, Record<string, 'present' | 'terrace' | 'void'>>;
  terrace_bands?: Record<number | string, TerraceBandSpec>;
  design_intent?: 'maximize_enclosed' | 'passive_ventilation';
  include_service_layer?: boolean;
  include_structural_sheet?: boolean;
  include_scheme_alternatives?: boolean;
  selected_scheme_id?: string;
  /** Deterministic plate variant chosen by the strategy ladder (S1/S2). */
  partition_variant?: 'service_row' | 'single_unit' | 'duplex';
  /** Declared dwellings per floor; 1 selects the one-unit V2 plate. */
  units_per_floor?: number;
  // Size the plate from the programme need (capped by the statutory ceiling)
  // Instead of the typology's comfortable plate.
  program_aware_footprint?: boolean;
}

export interface RoomPlacement {
  room_id: string;
  room_name: string;
  row: number;
  col: number;
  width: number;
  height: number;
  area_sqm: number;
  width_m: number;
  depth_m: number;
  zone: string;
  vastu_compliant: boolean;
  applied_rules?: string[];
  relaxations?: Array<{ rule_id: string; rationale: string }>;
}

export interface FloorPlanMetrics {
  // Measured by the engine; null means the plan carried nothing to measure.
  vastu_compliance_pct: number | null;
  plumbing_adjacency_score: number | null;
  space_utilization_pct: number | null;
  plot_coverage_pct?: number;
  total_built_up_sqm: number;
  circulation_efficiency_pct: number | null;
  circulation_status?: string;
}

export interface FloorPlanParamsSnapshot {
  building_typology: string;
  floors: number;
  ground_coverage_ratio: number;
  plot_width_m: number;
  plot_depth_m: number;
  required_rooms: string[];
  vastu_strictness: string;
  built_up_area_sqft?: number;
  client_notes?: string;
  ai_provider?: string;
  shape_type?: string;
  plot_polygon?: PlotPolygon;
  quality_grade?: string;
  solar_axis_degrees?: number;
  prevailing_wind_direction_degrees?: number;
  terrace_bands?: Record<number | string, TerraceBandSpec>;
  floor_plate_masks?: Record<number | string, Record<string, 'present' | 'terrace' | 'void'>>;
  design_intent?: 'maximize_enclosed' | 'passive_ventilation';
  include_service_layer?: boolean;
  include_structural_sheet?: boolean;
  seed?: string;
  /** Ask the solver for the ranked Max Area / Max Vastu / Max Light+Vent portfolio. */
  include_scheme_alternatives?: boolean;
  /** Chosen profile; the plate is re-solved with that profile's weights. */
  selected_scheme_id?: string;
  /** Strategy inputs applied by a remediation card, kept for a restore. */
  partition_variant?: 'service_row' | 'single_unit' | 'duplex';
  units_per_floor?: number;
  /** Backend-recorded outcome of a scheme selection. */
  scheme_selection_status?: 'applied' | 'rejected_non_compliant' | 'recorded_only' | string;
  scheme_selection_failing_layers?: string[];
  scheme_profile?: string | null;
  /** selection path: set ONLY when the requested selection was replaced by the legal
   *  programme. Absent means the selection was drawn as asked. */
  selection_path?: 'fallback_legal_programme' | string;
  selection_fallback_reason?: string;
  selection_unplaced_rooms?: string[];
}

export interface FloorPlanResponse {
  status: 'optimal' | 'compromise' | 'failed';
  grid_matrix: string[][];
  placements: RoomPlacement[];
  rectangles?: RectanglesModel;
  svg_blueprint: string;
  svg_blueprint_paper?: string;
  metrics: FloorPlanMetrics;
  qa?: FloorPlanQA;
  warnings: string[];
  timing_ms: number;
  iterations: number;
  design_intent?: string;
  program_source?: 'llm' | 'cache' | 'fallback' | string;
  placement_source?: 'llm+kb' | 'kb-default' | string;
  placement_logic?: Record<string, string> | string[];
  ai_metadata?: Record<string, any>;
  room_program?: RoomProgram;
  multi_storey?: MultiStoreyBuildingModel;
  client_constraints?: ExtractedClientConstraints;
  generated_at?: number;
  generation_id?: string;
  unmet_requirements?: UnmetRequirement[];
  params_snapshot?: FloorPlanParamsSnapshot;
  mathematical_certificate?: MathematicalValidityCertificate;
  plot_polygon?: PlotPolygon;
  site_plan?: SitePlanModel;
  land_economics?: LandEconomicsReport;
  scheme_alternatives?: SchemeAlternative[];
  scheme_portfolio?: SchemePortfolio;
  selected_scheme_id?: string;
  /**
   * The ONE server-computed plan verdict. Card, certificate
   * panel and PDF render this string verbatim; the UI never re-derives a
   * severity of its own.
   */
  plan_verdict?: 'CERTIFIED' | 'ADVISORY' | 'NOT-CERTIFIED-FAIL-STAMP';
  plan_verdict_reasons?: string[];
}

/* ------------------------------------------------------------------ */
/* Remediation + advisory (engine-measured, AI-worded)                 */
/* ------------------------------------------------------------------ */

export interface MeasuredEffect {
  verdict: 'CERTIFIED' | 'ADVISORY' | 'NOT-CERTIFIED-FAIL-STAMP' | string;
  certificate_valid: boolean;
  gate_status?: string | null;
  warning_count: number;
  failure_count: number;
  relaxation_count: number;
  plate_area_m2?: number | null;
  rooms_placed: number;
  floors: number;
  status?: string | null;
  delta_warnings: number;
  delta_failures: number;
  engine_ms: number;
}

export interface RemediationOption {
  id: 'add_storey' | 'reduce_programme' | 'accept_rotation' | 'enlarge_plate' | 'switch_scheme' | string;
  title: string;
  description: string;
  /** Only validated generator inputs: floors, rooms, coverage, polygon, scheme id. */
  patch: Partial<FloorPlanRequest> & Record<string, any>;
  /** False for a named constraint with no valid patch for this request. */
  available?: boolean;
  /** Why the alternative cannot be applied; required when available is false. */
  constraint_reason?: string | null;
  /** Engine evidence behind the recommendation (finding codes, rooms). */
  basis?: {
    type?: string;
    codes?: string[];
    rooms?: string[];
    [key: string]: any;
  };
  effect: MeasuredEffect | null;
  error: string | null;
  details: Record<string, any>;
}

export interface RemediationResponse {
  plan_hash: string;
  options: RemediationOption[];
  engine_ms: number;
  note: string;
}

export interface AdvisoryMeta {
  provider_requested: string;
  provider_used: string;
  narrative_class: string;
  fallback_reason?: string | null;
  redactions: string[];
  cached: boolean;
  generation_time_ms?: number | null;
}

export interface AdvisoryResponse {
  narrative: string | null;
  /** One advisor-worded sentence per engine option id (wording only). */
  option_notes?: Record<string, string>;
  meta: AdvisoryMeta;
}

export interface ReportRequestPayload {
  analysis_data: AnalysisResponse;
  site_vision?: SiteVisionResponse | null;
  floor_plan?: FloorPlanResponse | null;
}

