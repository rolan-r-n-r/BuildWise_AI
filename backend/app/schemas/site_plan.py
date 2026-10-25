import math
from typing import List, Tuple, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator


class PlotVertex(BaseModel):
    """Survey vertex in local tangent plane (Easting, Northing)."""
    id: str = Field(..., description="Vertex identifier, e.g. P1, P2...")
    x_m: float = Field(..., allow_inf_nan=False, description="Local Easting in meters (+X is East)")
    y_m: float = Field(..., allow_inf_nan=False, description="Local Northing in meters (+Y is North)")


class SurveyEdge(BaseModel):
    """Survey boundary edge between two vertices with length and bearing."""
    edge_index: int
    from_vertex: str
    to_vertex: str
    length_m: float
    bearing_deg: float  # Azimuth from North (0° = North, 90° = East)
    bearing_dms: str    # e.g. "N 45° 30' E"


class PlotPolygonModel(BaseModel):
    """
    Canonical ordered polygon model in a local tangent plane (E/N,
    equirectangular with cos(lat) scaling) + origin lat/lon.
    """
    vertices: List[Tuple[float, float]] = Field(
        ...,
        description="Ordered list of (x_m, y_m) vertices in local metric tangent plane"
    )
    origin_lat: Optional[float] = Field(default=None, allow_inf_nan=False, description="WGS84 origin latitude")
    origin_lon: Optional[float] = Field(default=None, allow_inf_nan=False, description="WGS84 origin longitude")

    @field_validator("vertices")
    @classmethod
    def reject_non_finite_vertices(cls, vertices: List[Tuple[float, float]]):
        """NaN/Infinity are not JSON and must not reach the geometry engine."""
        for idx, (x, y) in enumerate(vertices):
            if not math.isfinite(x):
                raise ValueError(f"vertices[{idx}].x must be a finite number, got {x!r}")
            if not math.isfinite(y):
                raise ValueError(f"vertices[{idx}].y must be a finite number, got {y!r}")
        return vertices
    projection_note: str = Field(
        default="Local tangent plane (E/N, equirectangular with cos(lat) scaling)",
        description="Projection methodology description"
    )
    shape_type: Literal["rectangle", "irregular", "trapezoid", "l_shape", "pentagon", "polygon"] = Field(
        default="irregular",
        description="Recognized geometric typology"
    )
    is_regular_rectangle: bool = Field(
        default=False,
        description="True if shape is a regular 4-vertex rectangle"
    )
    has_curved_edges: bool = Field(
        default=False,
        description="True if polygon was approximated from curvilinear boundary"
    )
    area_sqm: float = Field(default=0.0, description="Shoelace area in square meters")
    perimeter_m: float = Field(default=0.0, description="Perimeter in meters")
    bounding_box: Tuple[float, float, float, float] = Field(
        default=(0.0, 0.0, 0.0, 0.0),
        description="(min_x, min_y, max_x, max_y) in meters"
    )


class OutdoorFragment(BaseModel):
    """Outdoor zone fragment resulting from buildable polygon minus footprint."""
    fragment_id: str
    name: str  # e.g. "Garden 1", "Visitor parking (1 ECS) 2"
    area_sqm: float
    centroid: Tuple[float, float]
    polygon_coords: List[Tuple[float, float]] = Field(default_factory=list)
    # Outdoor routing (ONTOLOGY.outdoor_routes): every patch carries the
    # declared use it was routed to, not a single generic yard label.
    route_kind: Optional[str] = Field(
        default=None, description="parking | garden | terrace | planter | yard | plaza"
    )
    route_label: Optional[str] = Field(default=None, description="Declared route label")
    ecs: float = Field(default=0.0, description="Equivalent car spaces delivered by this patch")
    rationale: str = Field(default="", description="Route citation / why this patch got this use")


class WedgeZone(BaseModel):
    """
    Functional non-habitable wedge zone absorbing residual slivers between
    the orthogonal footprint and angled/curvilinear boundary.
    """
    wedge_id: str = Field(..., description="Wedge identifier, e.g. WDG-01")
    classification: Literal[
        "storage_closet",
        "duct_shaft",
        "planter",
        "stair_wedge",
        "parking_apron"
    ] = Field(..., description="Functional non-habitable classification")
    name: str = Field(..., description="Display name, e.g. Boundary Planter Wedge, Outdoor Storage Closet")
    area_sqm: float = Field(..., description="Area in square meters")
    centroid: Tuple[float, float] = Field(..., description="(x, y) centroid coordinates")
    polygon_coords: List[Tuple[float, float]] = Field(default_factory=list, description="Boundary polygon coordinates")
    is_enclosed_storage: bool = Field(default=False, description="True if enclosed storage (counted in built-up)")
    is_interior_side: bool = Field(default=False, description="True if adjacent to building footprint wall")
    adjacent_wing_id: Optional[str] = Field(default=None, description="Adjacent wing ID if applicable")
    width_m: float = Field(default=0.0, description="Approximate minimum width")
    length_m: float = Field(default=0.0, description="Approximate length")


class FootprintWing(BaseModel):
    """Individual rectangular wing within an articulated footprint."""
    wing_id: str
    label: str
    zone_type: Literal["public", "private", "service", "circulation"] = "public"
    x: float
    y: float
    width_m: float
    depth_m: float
    area_sqm: float
    corner_vertices: List[Tuple[float, float]] = Field(default_factory=list)


class CorridorLink(BaseModel):
    """Circulation corridor bridging two wings."""
    link_id: str
    from_wing_id: str
    to_wing_id: str
    x: float
    y: float
    width_m: float
    depth_m: float
    area_sqm: float
    polygon_coords: List[Tuple[float, float]] = Field(default_factory=list)


class InscribedFootprint(BaseModel):
    """Footprint geometry fitted inside buildable polygon."""
    x: float          # SW origin X (meters)
    y: float          # SW origin Y (meters)
    width_m: float    # Footprint width in meters
    depth_m: float    # Footprint depth in meters
    area_sqm: float   # Footprint area in m²
    rotation_angle_deg: float = 0.0  # Rotation angle relative to North (0° = aligned)
    center_x: float = 0.0
    center_y: float = 0.0
    corner_vertices: List[Tuple[float, float]] = Field(default_factory=list)
    topology_type: Literal["single_rectangle", "l_shape", "courtyard", "multi_wing"] = "single_rectangle"
    wings: List[FootprintWing] = Field(default_factory=list)
    corridors: List[CorridorLink] = Field(default_factory=list)
    courtyard_void: Optional[OutdoorFragment] = None


class ParkingBay(BaseModel):
    """Standard Equivalent Car Space (ECS) parking bay geometry (2.5m x 5.0m)."""
    bay_id: str = Field(..., description="Unique bay identifier, e.g. ECS-1")
    width_m: float = Field(default=2.5, description="Bay clear width in meters")
    length_m: float = Field(default=5.0, description="Bay clear length in meters")
    x: float = Field(..., description="SW corner Easting in meters")
    y: float = Field(..., description="SW corner Northing in meters")
    orientation_deg: float = Field(default=0.0, description="Orientation angle in degrees")
    polygon_coords: List[Tuple[float, float]] = Field(default_factory=list, description="4 corner coordinates")


class ParkingEnvelope(BaseModel):
    """
    Parking envelope derived in the parking-first pipeline prior to footprint.
    Contains required/provided ECS counts, individual bays, drive aisle, and coexistence options.
    """
    required_ecs: int = Field(default=1, description="Statutory ECS count required by typology/units")
    provided_ecs: int = Field(default=1, description="Actual surface ECS bays accommodated on site")
    deficit_ecs: int = Field(default=0, description="Deficit count if surface parking cannot fit")
    bays: List[ParkingBay] = Field(default_factory=list, description="Accommodated 2.5x5.0m parking bays")
    drive_aisle_polygon: List[Tuple[float, float]] = Field(default_factory=list, description="Drive aisle access geometry")
    drive_aisle_width_m: float = Field(default=3.5, description="Drive aisle clear width in meters")
    total_parking_area_sqm: float = Field(
        default=0.0,
        description="Total parking envelope area: ECS bays + drive aisle (single source for UI/PDF)"
    )
    coexistence_status: str = Field(
        default="COEXISTENT",
        description="COEXISTENT if statutory parking fits with footprint, else DEFICIT_WARNED"
    )
    deficit_warning: Optional[str] = Field(default=None, description="Explicit warning if parking + footprint cannot coexist")
    coexistence_options: List[str] = Field(
        default_factory=list,
        description="Explicit options to resolve deficit: reduce footprint, stack parking, accept deficit"
    )


class SiteSheetChecklist(BaseModel):
    """Programmatic completeness checklist for Sheet 10.0 / Site Survey."""
    has_road_annotation: bool = Field(default=False, description="Road side + width annotated")
    has_gates: bool = Field(default=False, description="Vehicular gate + pedestrian entry marked")
    has_parking_bays: bool = Field(default=False, description="Parking bays with 2.5x5.0m dims and aisle")
    has_sewer_connection: bool = Field(default=False, description="Sewer connection point with invert level")
    has_stormwater_drainage: bool = Field(default=False, description="Stormwater outlet + drainage direction arrows")
    has_levels_and_slope: bool = Field(default=False, description="Finished ground level + road level + slope note")
    has_setbacks_all_sides: bool = Field(default=False, description="Setback dimensions indicated on every side")
    has_neighbour_ticks: bool = Field(default=False, description="Neighbour / boundary ticks on adjoining edges")
    is_complete: bool = Field(default=False, description="True if all 8 required items are present")
    missing_items: List[str] = Field(default_factory=list, description="List of missing required items if incomplete")


class SiteCertificate(BaseModel):
    """Mathematical site compliance certificate."""
    footprint_contained_in_buildable: bool = True
    setback_distance_satisfied: bool = True
    min_setback_achieved_m: float = 0.0
    required_setback_m: float = 0.0
    ground_coverage_actual_pct: float = 0.0
    ground_coverage_limit_pct: float = 60.0
    far_actual: float = 0.0
    far_limit: float = 2.5
    is_valid: bool = True
    diagnostics: List[str] = Field(default_factory=list)


class SitePlanModel(BaseModel):
    """
    Complete site layer synthesis encapsulating all irregularity at the site level.
    """
    plot_polygon: PlotPolygonModel
    buildable_polygon_coords: List[Tuple[float, float]]
    buildable_area_sqm: float
    nominal_setback_m: float
    reduced_setback_applied: bool = False
    footprint: InscribedFootprint
    outdoor_zones: List[OutdoorFragment] = Field(default_factory=list)
    wedge_zones: List[WedgeZone] = Field(default_factory=list, description="Absorbed functional non-habitable wedge zones")
    design_policy: Optional[str] = Field(
        default=None,
        description="Declared design policy for non-orthogonal plots"
    )
    design_policy_rationale: Optional[str] = Field(
        default=None,
        description="Rationale for orthogonal squaring-off"
    )
    waste_pct: float = Field(default=0.0, description="Percentage of buildable area not inscribed by footprint")
    rotation_alternatives: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Evaluated rotation angles and waste metrics for QA"
    )
    waste_warning_triggered: bool = Field(default=False, description="True if waste_pct > 25.0%")
    setback_band_area_sqm: float = 0.0
    edges: List[SurveyEdge] = Field(default_factory=list)
    vertex_table: List[PlotVertex] = Field(default_factory=list)
    site_vastu_zones: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    certificate: SiteCertificate = Field(default_factory=SiteCertificate)
    building_line_coords: List[Tuple[float, float]] = Field(
        default_factory=list,
        description="Explicit building line coordinates derived from inward setback envelope"
    )
    setback_dimensions: Dict[str, float] = Field(
        default_factory=dict,
        description="Setback distance dimensions on all sides (front_m, rear_m, left_m, right_m)"
    )
    derivation_chain: List[str] = Field(
        default_factory=list,
        description="Explicit derivation chain: plot -> setbacks -> buildable -> building line -> footprint"
    )
    derivation_text: str = Field(
        default="",
        description="Printed derivation banner text: FOOTPRINT DERIVED FROM BUILDABLE POLYGON P1..Pn"
    )
    parking: Optional[ParkingEnvelope] = Field(
        default=None,
        description="Parking-first envelope with 2.5x5.0m bays and drive aisle"
    )
    checklist: Optional[SiteSheetChecklist] = Field(
        default=None,
        description="Site sheet completeness checklist evaluation"
    )
    validated_layers: List[str] = Field(
        default_factory=lambda: ["L1", "L2"],
        description="List of validated layer tokens for drawing status stamp"
    )
    validation_gate: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Universal validation gate for the SITE scope: site layers evaluated, building layers N/A with explicit reasons"
    )
    drawing_status_stamp: str = Field(
        default="STATUS: CONCEPT DESIGN - VALIDATED LAYERS: [L1, L2] - NOT FOR CONSTRUCTION",
        description="Drawing status stamp line"
    )
    provenance: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Boundary source, frontage source, projection origin - flows end-to-end"
    )
    svg_site_plan: Optional[str] = None
