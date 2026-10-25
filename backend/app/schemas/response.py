from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class FactorScore(BaseModel):
    factor_id: str
    name: str
    weight: float
    # None when the factor could not be measured
    # (e.g. road distance unavailable) - never a fabricated raw value.
    raw_value: Optional[float] = None
    unit: str
    score: float  # 0 to 100
    status: str   # optimal, acceptable, critical
    details: str

class OrientationData(BaseModel):
    optimal_axis_degrees: float
    axis_label: str
    prevailing_wind_direction_degrees: float
    solar_exposure_summary: str
    cross_ventilation_rating: str
    passive_design_rationale: str

class CostItem(BaseModel):
    category: str
    amount_inr: float
    percentage: float
    description: str

class CostEstimate(BaseModel):
    base_rate_per_sqft: float
    terrain_multiplier: float
    base_cost_inr: float
    terrain_surcharge_inr: float
    total_estimated_cost_inr: float
    cost_range_min_inr: float
    cost_range_max_inr: float
    breakdown: List[CostItem]
    currency: str = "INR"
    disclaimer: str

class RiskItem(BaseModel):
    severity: str  # low, medium, high
    category: str  # slope, flood, access, climate
    title: str
    description: str
    mitigation_strategy: str

# --- Module 1: Hazard History & Climate Stress Profile ---
class SeismicEvent(BaseModel):
    magnitude: float
    date_iso: str
    distance_km: float
    place: str

class SeismicProfile(BaseModel):
    # zone/zone_factor are None when the site is
    # outside the IS 1893:2016 (India) mapping extent - "Not Assessed", never a
    # fabricated default zone.
    zone: Optional[str]  # "Zone II".."Zone V", or None when not assessed
    zone_factor: Optional[float]  # 0.10, 0.16, 0.24, 0.36, or None
    standard: str  # "BIS IS 1893:2016"
    district: str
    event_count_50yr_250km: int
    is_capped: bool = False
    event_count_display: str
    max_magnitude: Optional[float] = None
    years_since_last_event: Optional[float] = None
    recent_major_events: List[SeismicEvent] = []
    confidence: str  # "high", "moderate", "low"
    confidence_warning: Optional[str] = None

class FloodProfile(BaseModel):
    discharge_peak_to_mean_ratio: Optional[float] = None
    pressure_level: str  # "low", "moderate", "high"
    ndma_flood_prone: bool
    elevation_amsl_m: float
    confidence: str  # "high", "moderate", "low"
    confidence_warning: Optional[str] = None

class StormCycloneProfile(BaseModel):
    max_annual_gust_kmh: float
    extreme_rainfall_days: float
    exposure_level: str  # "low", "moderate", "high"
    ndma_cyclone_prone: bool
    confidence: str  # "high", "moderate", "low"
    confidence_warning: Optional[str] = None

class HazardProfile(BaseModel):
    seismic: SeismicProfile
    flood: FloodProfile
    storm_cyclone: StormCycloneProfile
    overall_hazard_level: str  # "low", "moderate", "high", "critical"
    warnings: List[str] = []
    # Per-upstream fetch timestamps (ISO8601 UTC) for the hazard telemetry
    # sources; a None value means the upstream was NOT fetched this session
    # (fallback model applied) and is disclosed as such downstream.
    source_fetches: Dict[str, Optional[str]] = {}

# --- Module 2: Indicative Land Value Engine ---
class MultiplierBreakdown(BaseModel):
    road_accessibility_score: float
    road_contribution: float
    facility_proximity_score: float
    facility_contribution: float
    net_multiplier: float
    is_clamped: bool

class LandValueEstimate(BaseModel):
    indicative_rate_per_sqft: Optional[float] = None
    base_table_rate_per_sqft: Optional[float] = None
    is_user_override: bool = False
    locality_multiplier: float = 1.0
    multiplier_breakdown: MultiplierBreakdown
    plot_area_sqft: float
    # Provenance of plot_area_sqft (audit F07): the report may only call the
    # number a "captured boundary" when it actually came from one.
    plot_area_source: str = Field(
        "derived_from_coverage",
        description="captured_boundary | client_plot_area | derived_from_coverage",
    )
    boundary_area_sqft: Optional[float] = Field(
        None, description="Shoelace area of the captured boundary, in sq ft"
    )
    plot_area_warnings: List[str] = Field(default_factory=list)
    ground_coverage_ratio_applied: float = 0.60
    land_cost_inr: Optional[float] = None
    construction_cost_inr: float
    combined_project_total_inr: Optional[float] = None
    as_of_year: Optional[int] = None
    jurisdiction_zone: Optional[str] = None
    source_publication: Optional[str] = None
    disclaimer: str
    confidence_warning: Optional[str] = None

# --- Module 3: Vastu & Functional Planning Advisory ---
class RankedEntrance(BaseModel):
    direction: str  # "N", "NE", "E", "SE", "S", "SW", "W", "NW"
    score: float
    vastu_rationale: str
    practical_rationale: str
    is_approach_side: bool

class RoomGridZone(BaseModel):
    zone: str  # "N", "NE", "E", "SE", "S", "SW", "W", "NW", "Center"
    zone_name: str
    primary_room: str
    alternative_room: str
    prohibited: List[str]
    vastu_rationale: str
    civil_engineering_rationale: str

class SlopeReading(BaseModel):
    drainage_direction: str
    azimuth_degrees: float
    auspiciousness: str  # "favourable", "neutral", "requires_remedy"
    rationale: str
    remedy_notes: Optional[str] = None

class ReconciliationItem(BaseModel):
    topic: str
    status: str  # "concordant" | "divergent"
    vastu_position: str
    scientific_passive_position: str
    recommended_synthesis: str

class RoadApproach(BaseModel):
    bearing_degrees: Optional[float] = None
    approach_side: str  # "N", "S", "E", "W", etc. or "unknown"
    distance_meters: Optional[float] = None
    is_fallback: bool

class VastuAdvisory(BaseModel):
    ranked_entrances: List[RankedEntrance]
    room_grid: List[RoomGridZone]
    slope_reading: SlopeReading
    reconciliation_notes: List[ReconciliationItem]
    road_approach: RoadApproach

# --- Module 4: Ranked Traceable Recommendations ---
class RecommendationItem(BaseModel):
    category: str  # "site_works", "structure", "water_drainage", "climate_passive", "access_circulation", "vastu_compliance", "cost_phasing"
    category_label: str
    severity: str  # "critical", "advisory", "optimal"
    rule_id: str
    trigger_condition: str
    source_data_ref: str
    recommendation_text: str

class DataSourceProvenance(BaseModel):
    """Fetch provenance for one external data source.

    fetched_at is an ISO8601 UTC timestamp when the upstream was successfully
    consulted during this analysis, and None when the value on the response is
    a deterministic fallback model (never presented as a live reading).
    """
    source: str
    fetched_at: Optional[str] = None
    is_fallback: bool = False


# --- Map-first capture: server-validated boundary echo (audit F22) ---
class BoundaryOrigin(BaseModel):
    lat: float
    lon: float


class BoundaryProvenance(BaseModel):
    boundary_source: str
    projection: str
    origin: BoundaryOrigin
    area_method: str


class BoundarySummaryResponse(BaseModel):
    """Server-validated echo of the captured plot boundary.

    `area_sqm`/`area_sqft` are the server's shoelace result (authoritative);
    `client_area_sqm` and `area_delta_pct` record what the client claimed, so
    the report can disclose a disagreement instead of silently picking one.
    """
    vertex_count: int
    area_sqm: float
    area_sqft: float
    perimeter_m: float
    shape_type: str
    source: str
    frontage_edge_index: Optional[int] = None
    frontage_annotation: Optional[str] = None
    origin: BoundaryOrigin
    winding: str
    captured: bool = True
    authoritative: bool = True
    client_area_sqm: Optional[float] = None
    area_delta_pct: Optional[float] = None
    provenance: BoundaryProvenance


# --- Master Analysis Response ---
class AnalysisResponse(BaseModel):
    request_id: str
    timestamp: str
    coordinates: Dict[str, float]
    formatted_address: str
    overall_suitability_score: float
    suitability_verdict: str  # Suitable, Conditionally Suitable, Challenging
    factors: List[FactorScore]
    orientation: OrientationData
    cost_estimate: CostEstimate
    risks: List[RiskItem]
    hazard_profile: HazardProfile
    land_value: LandValueEstimate
    vastu_advisory: VastuAdvisory
    recommendation_items: List[RecommendationItem]
    detailed_recommendations: List[str]
    engineering_summary: str
    ai_metadata: Dict[str, str]
    degraded_mode: bool
    warnings: List[str]
    # Per-source fetch provenance keyed by source id
    # (geocode, elevation, climate, road, seismic, flood, storm). Consumed by
    # the report UI methodology disclosures so every timestamp shown is the
    # real server fetch time, never a client-side placeholder.
    data_sources: Dict[str, DataSourceProvenance] = {}
    parameter_reflection: Optional[str] = None
    # Generated methodology disclosures keyed by factor id ("slope" today).
    # Served with the analysis so the report's popover renders the SAME band
    # table the engine evaluated, not a hand-copied string.
    methodology: Dict[str, str] = Field(default_factory=dict)
    feasibility_score: Optional[int] = None
    structural_recommendations: Optional[List[str]] = None
    cost_breakdown: Optional[Dict[str, Any]] = None
    vastu_compliance: Optional[Dict[str, Any]] = None
    # Map-first capture: read-only echo of the captured boundary,
    # validated server-side (shoelace area, perimeter, winding, statutory minima).
    boundary_summary: Optional[BoundarySummaryResponse] = None
    # The analysed building's storey count, echoed from the request. The report
    # must print the project the user actually configured: it used to default
    # to 2 because this field did not exist.
    storeys: Optional[int] = Field(default=None, ge=1, le=10, description="Above-ground storeys analysed")
    building_typology: Optional[str] = Field(default=None, description="Typology analysed (echoed from the request)")

class HealthResponse(BaseModel):
    status: str
    version: str
    ai_adapters_available: List[str]
    active_default_ai: str
