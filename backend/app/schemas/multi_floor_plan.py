from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field, model_validator

from app.schemas.land_economics import LandEconomicsReport
from app.schemas.space_identity import SpaceIdentity


class UnmetRequirement(BaseModel):
    """
    One requested room the solver could not satisfy, with an explicit reason
    (zero silent skips for user requirements).
    """
    room_id: str
    reason: str


class VerticalCoreSpec(BaseModel):
    """
    Specification for vertically continuous building circulation elements
    (staircases, lifts, and MEP structural chases) that must align across all storeys.
    """
    core_id: str
    core_type: Literal[
        "staircase_dogleg",
        "staircase_fire",
        "lift_passenger",
        "lift_service",
        "mep_chase"
    ]
    x: float
    y: float
    width_m: float
    depth_m: float
    landing_depth_m: Optional[float] = None
    tread_mm: int = 250
    riser_mm: int = 175
    continuous_across_floors: List[int] = Field(default_factory=list)


class DuctShaftSpec(BaseModel):
    """
    Vertical MEP and wet plumbing shaft connecting bathrooms and kitchens to foundation drainage.
    """
    shaft_id: str
    shaft_type: Literal["plumbing_wet", "electrical_mep", "hvac_vent"]
    x: float
    y: float
    width_m: float
    depth_m: float
    servicing_rooms: List[str] = Field(default_factory=list)


class BathroomFixtureSpec(BaseModel):
    """
    Statutory coded bathroom fixture with strict clearances per NBC 2016 Part 9 / Time-Saver Standards.
    """
    fixture_id: str
    fixture_type: Literal["wc", "wash_basin", "shower"]
    x: float
    y: float
    width_m: float
    depth_m: float
    clearance_front_m: float
    clearance_side_m: float
    is_satisfied: bool = True
    clearance_notes: str = ""


class FurnitureItemSpec(BaseModel):
    """
    Standard catalog furniture item with circulation envelope.
    """
    item_id: str
    item_type: str  # bed_king, bed_queen, wardrobe, sofa_set, dining_table_6p, kitchen_cooktop, kitchen_sink, kitchen_fridge
    x: float
    y: float
    width_m: float
    depth_m: float
    circulation_clearance_m: float
    is_satisfied: bool = True


class MultiFloorRoomRectangle(BaseModel):
    """
    Exact continuous geometric footprint of a room located on a specific floor level.
    """
    room_id: str
    room_name: str
    floor_index: int  # 0 = Ground, 1 = G+1, 2 = G+2, 3 = G+3
    unit_id: Optional[str] = None  # None for T1/T4; "U1", "U2" for multi-unit T2/T3
    # A dwelling may occupy more than one storey.  ``unit_id`` names the
    # level-unit a room belongs to on its own floor; ``dwelling_id`` names the
    # household that owns it.  For a repeated flat the two are equal (each
    # level is its own dwelling); for a duplex two levels share one
    # ``dwelling_id`` and carry complementary ``dwelling_level`` values.  Both
    # fields are optional so existing serialized plans remain valid.
    dwelling_id: Optional[str] = Field(
        default=None,
        description="Stable household id; equal to unit_id unless the dwelling spans storeys",
    )
    dwelling_level: Optional[Literal["lower", "upper"]] = Field(
        default=None,
        description="Level of a multi-storey dwelling; None for a single-level unit",
    )
    x: float
    y: float
    width_m: float
    depth_m: float
    area_sqm: float
    zone: str  # N, NE, E, SE, S, SW, W, NW, CENTER
    zone_category: Literal["public", "private", "service", "circulation", "industrial_bay", "terrace"] = "public"
    vastu_compliant: bool = True
    is_vertical_core: bool = False
    requires_exterior_wall: bool = True
    aspect_ratio: float = 1.0
    applied_rules: List[str] = Field(default_factory=list, description="Ontology rule IDs shaping this room")
    relaxations: List[Dict[str, str]] = Field(default_factory=list, description="Rule relaxations with rationale tags")
    fixtures: List[BathroomFixtureSpec] = Field(default_factory=list, description="Coded bathroom fixtures with statutory clearances")
    furniture: List[FurnitureItemSpec] = Field(default_factory=list, description="Minimum furniture layout satisfying circulation envelopes")
    naming_threshold_used: Optional[str] = Field(default=None, description="Ontological naming and area threshold applied")
    space_type_id: Optional[str] = Field(default=None, description="Canonical ontology space type (unit-independent identity)")
    identity: Optional[SpaceIdentity] = Field(
        default=None,
        description="Resolved ontology identity: the single source for name, zone, hygiene, clear-area basis and statutory minima",
    )
    scheme_profile: Optional[str] = Field(default=None, description="Scheme profile that placed this room")
    orientation_rationale: Optional[str] = Field(default=None, description="Why this room was assigned this orientation/band")
    score_contributions: Dict[str, float] = Field(default_factory=dict, description="Per-metric score contribution from this room")

    @model_validator(mode="after")
    def normalize_aspect_ratio(self):
        """Store aspect as max(w,d)/min(w,d), never a mixed-orientation ratio.

        The placement layer used to write ``w/d`` for some rooms and ``d/w`` for
        others, so a 1:13 bathroom could be stored as 0.08 and pass a check that
        read the field.  Normalizing at the schema boundary makes every writer
        (legacy partitioners, scheme solver, repairs) orientation-safe.
        """
        if self.width_m > 1e-9 and self.depth_m > 1e-9:
            self.aspect_ratio = round(
                max(self.width_m, self.depth_m) / min(self.width_m, self.depth_m), 2
            )
        return self


class MultiFloorDoorGeometry(BaseModel):
    """
    Architectural door representation with hinge, swing arc, and room connection.
    """
    door_id: str
    floor_index: int
    from_room: str
    to_room: str
    wall_edge: Literal["north", "south", "east", "west", "vertical", "horizontal"]
    x1: float
    y1: float
    x2: float
    y2: float
    hinge_x: float
    hinge_y: float
    swing_direction: Literal["inward_right", "inward_left", "outward_right", "outward_left"] = "inward_right"
    width_m: float = 0.90
    door_type: Literal["standard", "fire_rated", "sliding", "dock_shutter"] = "standard"


class MultiFloorWindowGeometry(BaseModel):
    """
    Architectural window representation on exterior walls.
    """
    window_id: str
    floor_index: int
    room_id: str
    wall_edge: Literal["north", "south", "east", "west"]
    x1: float
    y1: float
    x2: float
    y2: float
    width_m: float
    sill_height_m: float = 0.90


class StructuralGridSpec(BaseModel):
    """
    Structural column grid specification primarily for Typology T4 (Warehouse) and T3 (Complex).
    """
    bay_spacing_x_m: float = 6.0
    bay_spacing_y_m: float = 6.0
    columns_x: List[float] = Field(default_factory=list)
    columns_y: List[float] = Field(default_factory=list)
    column_size_m: float = 0.45


class SingleFloorPlanModel(BaseModel):
    """
    Complete geometric and metric blueprint representation for a single storey level.
    """
    floor_index: int
    floor_name: str  # "Ground Floor (G)", "First Floor (G+1)", etc.
    envelope: Dict[str, Any]  # x, y, width, depth, area_sqm, optional wings/corridors/topology_type
    rooms: List[MultiFloorRoomRectangle] = Field(default_factory=list)
    doors: List[MultiFloorDoorGeometry] = Field(default_factory=list)
    windows: List[MultiFloorWindowGeometry] = Field(default_factory=list)
    circulation_status: Literal["connected", "disconnected"] = "connected"
    # Measured by derived_metrics from the placed rectangles; ``None`` means the
    # floor carries nothing to measure (e.g. no wet room), never a silent pass.
    vastu_score_pct: Optional[float] = None
    vastu_compliance_pct: Optional[float] = None
    plumbing_stack_alignment_pct: Optional[float] = None
    built_up_area_sqm: float = 0.0
    carpet_area_sqm: float = 0.0
    svg_blueprint_cad: Optional[str] = Field(default="", description="CAD-theme blueprint SVG; rendered after the universal validation gate so sheets carry the layer table and stamp")
    svg_blueprint_paper: Optional[str] = Field(default="", description="Paper-theme blueprint SVG; rendered after the universal validation gate")
    wall_graph: Optional[Dict[str, Any]] = None
    door_schedule: List[Dict[str, Any]] = Field(default_factory=list)
    window_schedule: List[Dict[str, Any]] = Field(default_factory=list)
    room_schedule: List[Dict[str, Any]] = Field(default_factory=list)
    stair_geometry: Optional[Dict[str, Any]] = None
    stair_schedule: List[Dict[str, Any]] = Field(default_factory=list)
    validation_gate: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Universal validation gate layer table (L1-L15) for this floor"
    )
    mathematical_certificate: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Mathematical validity certificate for this floor plate"
    )
    floor_plate_mask: Dict[str, str] = Field(
        default_factory=dict,
        description="Per-wing presence mask for this floor: wing_id -> present|terrace|void"
    )
    plate_composition: str = Field(
        default="",
        description="Human-readable plate composition summary e.g. Wing A + Terrace"
    )
    terrace_band: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Active terrace band on this floor if applicable: {edge: N|S|E|W, depth_m}"
    )


class MultiStoreyBuildingModel(BaseModel):
    """
    Root multi-storey architectural blueprint representation synthesizing all storeys,
    shared vertical circulation cores, structural grid, and compliance verification.
    """
    building_typology: Literal[
        "T1_SINGLE_FAMILY",
        "T2_FAMILY_APARTMENT",
        "T3_LARGE_COMPLEX",
        "T4_WAREHOUSE"
    ] | str
    total_storeys: int = Field(..., ge=1, le=4)
    plot_width_m: float
    plot_depth_m: float
    ground_coverage_ratio: float = 0.60
    total_built_up_area_sqm: float = 0.0
    vertical_cores: List[VerticalCoreSpec] = Field(default_factory=list)
    duct_shafts: List[DuctShaftSpec] = Field(default_factory=list)
    structural_grid: Optional[StructuralGridSpec] = None
    floors: List[SingleFloorPlanModel] = Field(default_factory=list)
    # Design variables the solve actually used (units per floor range, stacking
    # model, amenity placement, governing floor).  Disclosed with the plan so a
    # reader can see which choices were fixed and which were searched.
    programme_variables: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-typology programme variables used by this solve",
    )
    units_per_floor: Optional[int] = Field(
        default=None,
        description="Resolved dwellings per floor for this solve",
    )
    # Strategy escalation is engine evidence, not UI state: every tried strategy
    # stays on the plan whether it passed, failed, was skipped or errored.
    strategy_chain: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Ordered S0-S5 strategies tried for this plan, with measured outcomes",
    )
    strategy_chain_line: Optional[str] = Field(
        default=None,
        description="One-line disclosure: S0 fail -> S1 fail -> ...; selected S1",
    )
    strategy_selected: Optional[str] = Field(
        default=None,
        description="Id of the strategy whose plan was returned",
    )
    global_metrics: Dict[str, Any] = Field(default_factory=dict)
    qa_report: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    unmet_requirements: List[UnmetRequirement] = Field(default_factory=list)
    seed: int = 42
    solver_timing_ms: float = 0.0
    mathematical_certificate: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Consolidated mathematical validity certificate for building"
    )
    validation_gate: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Universal validation gate report: per-layer L1-L15 statuses, overall=worst layer, N/A-with-reason, LLM-boundary audit"
    )
    plot_polygon: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Canonical site polygon model dictionary"
    )
    site_plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Canonical site plan model dictionary"
    )
    land_economics: Optional[LandEconomicsReport] = Field(
        default=None,
        description="Land-economics report and SPACE-EFFICIENCY certificate"
    )


# ---------------------------------------------------------------------------
# Structured Client Requirements Schemas
# ---------------------------------------------------------------------------

class SpatialAdjacencyConstraint(BaseModel):
    room_a: str
    room_b: str
    relationship: Literal["connected", "adjacent", "separated"] = "adjacent"


class OrientationPreferenceConstraint(BaseModel):
    space: str
    preferred_facing: Literal[
        "North", "East", "South", "West",
        "North-East", "South-East", "South-West", "North-West"
    ]


# Alias for backward and test compatibility
SpaceOrientationPreference = OrientationPreferenceConstraint


class ExtractedClientConstraints(BaseModel):
    """
    Structured design constraints extracted from free-text client notes.
    """
    target_bedroom_count: int = Field(default=2, ge=1, le=6)
    target_bathroom_count: int = Field(default=2, ge=1, le=6)
    specialized_spaces: List[str] = Field(default_factory=list)
    spatial_adjacencies: List[SpatialAdjacencyConstraint] = Field(default_factory=list)
    orientation_preferences: List[OrientationPreferenceConstraint] = Field(default_factory=list)
    explicit_exclusions: List[str] = Field(default_factory=list)
    raw_notes: Optional[str] = None
    extraction_source: Literal["groq_llm", "gemini_llm", "regex_fallback"] = "regex_fallback"
