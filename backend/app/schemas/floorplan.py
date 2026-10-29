from typing import List, Dict, Optional, Literal, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from app.schemas.room_program import RoomProgram
from app.schemas.multi_floor_plan import MultiStoreyBuildingModel, ExtractedClientConstraints
from app.schemas.site_plan import PlotPolygonModel, SitePlanModel
from app.schemas.scheme import SchemeAlternative, SchemePortfolio
from app.schemas.land_economics import LandEconomicsReport
from app.schemas.space_identity import SpaceIdentity
from app.schemas.typology import BuildingTypology

class TerraceBandSpec(BaseModel):
    """
    Axis-aligned terrace band applied to a single rectangular plate.
    Occupied region = plate minus band.
    """
    edge: Literal["N", "S", "E", "W"] = Field(..., description="Edge along which terrace band is cut (N, S, E, W)")
    depth_m: float = Field(..., ge=0.0, description="Depth of terrace band in meters")


class FloorPlanRequest(BaseModel):
    # A captured boundary is authoritative: its bounding box can legitimately be
    # far wider than a single residential plot (an audited 108.5 x 89.1 m site
    # was silently clamped to 60 x 60 m). The upper bound therefore only guards
    # against absurd/typo input; coverage - not a dimension clamp - limits the
    # building footprint.
    plot_width_m: Optional[float] = Field(default=None, ge=6.0, le=2000.0, description="Plot frontage width in meters (bounding box of a captured boundary)")
    plot_depth_m: Optional[float] = Field(default=None, ge=6.0, le=2000.0, description="Plot depth in meters (bounding box of a captured boundary)")
    plot_polygon: Optional[PlotPolygonModel] = Field(
        default=None,
        description="Optional canonical plot polygon [(x_m, y_m)] in local tangent plane"
    )
    required_rooms: Optional[List[str]] = Field(
        default=None,
        description="Optional list of required room IDs to be placed"
    )
    vastu_strictness: Literal["high", "medium", "low"] = Field(
        default="high",
        description="Weight of Vastu Shastra rules vs. plumbing & circulation efficiency"
    )
    building_typology: Optional[BuildingTypology] = Field(default="residential_single", description="Typology identifier")
    seed: Optional[str] = Field(
        default=None,
        max_length=32,
        description="Optional deterministic generation seed; numeric values drive the GEN/CERT token, others fall back to the historical default",
    )
    quality_grade: Optional[Literal["basic", "standard", "premium"]] = Field(default="standard", description="Specification grade: basic, standard, premium")
    floors: Optional[int] = Field(default=1, ge=1, le=10, description="Number of storeys/levels")
    built_up_area_sqft: Optional[float] = Field(default=None, allow_inf_nan=False, description="Total plinth/built-up area in sq ft")
    ground_coverage_ratio: Optional[float] = Field(default=0.60, allow_inf_nan=False, description="Ground coverage ratio applied")
    client_notes: Optional[str] = Field(default=None, max_length=240, description="Optional client notes / design requirements")
    ai_provider: Optional[Literal["mock", "groq", "gemini", "ollama"]] = Field(default="mock", description="AI provider for LLM room program synthesis")
    room_program: Optional[RoomProgram] = Field(default=None, description="Explicit LLM or caller-provided room program")
    solar_axis_degrees: Optional[float] = Field(default=None, allow_inf_nan=False, description="Optimal solar axis in degrees")
    prevailing_wind_direction_degrees: Optional[float] = Field(default=None, allow_inf_nan=False, description="Prevailing wind azimuth in degrees")
    top_vastu_entrances: Optional[List[str]] = Field(default=None, description="Top ranked auspicious entrance orientations")
    program_source: Optional[str] = Field(default=None, description="Pre-computed program source: llm, cache, or fallback")
    bypass_cache: Optional[bool] = Field(default=False, description="Whether to bypass room program cache for fresh generation")
    extracted_constraints: Optional[ExtractedClientConstraints] = Field(
        default=None,
        description="Optional pre-parsed structured client constraints"
    )
    multi_storey: Optional[MultiStoreyBuildingModel] = Field(
        default=None,
        description="Optional pre-generated multi-storey building model for direct PDF export or re-rendering"
    )
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0, description="Site latitude for the dossier header (avoids a hardcoded placeholder city)")
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0, description="Site longitude for the dossier header")
    floor_plate_masks: Optional[Dict[str, Dict[str, Literal["present", "terrace", "void"]]] | Dict[int, Dict[str, Literal["present", "terrace", "void"]]]] = Field(
        default=None,
        description="Per-floor wing presence mask: floor_index -> wing_id -> present|terrace|void"
    )
    terrace_bands: Optional[Dict[str, TerraceBandSpec] | Dict[int, TerraceBandSpec]] = Field(
        default=None,
        description="Per-floor terrace band on simple rectangular plate: floor_index -> {edge: N|S|E|W, depth_m}"
    )
    design_intent: Optional[Literal["maximize_enclosed", "passive_ventilation"]] = Field(
        default=None,
        description="L8 program intent: maximize_enclosed (default) or passive_ventilation (terrace ratio advisory enforced)"
    )
    include_service_layer: Optional[bool] = Field(
        default=True,
        description="Draw service layer (shafts, soil/waste/vent stacks, inspection, RWP, terrace drainage) on sheets; validation always runs L9-L10 regardless"
    )
    include_structural_sheet: Optional[bool] = Field(
        default=True,
        description="Draw structural layer (column grid bubbles, beams, feasibility notes) on sheets; validation always runs L12 regardless"
    )
    include_scheme_alternatives: Optional[bool] = Field(
        default=False,
        description="Generate the constrained solver's ranked scheme portfolio (Max Area / Max Vastu / Max Light+Vent) alongside the legacy plan"
    )
    program_aware_footprint: Optional[bool] = Field(
        default=False,
        description="Deprecated provenance flag. The footprint is ALWAYS sized from the ontology programme (plus walls/circulation/core) and only CAPPED by the coverage ratio and the setback buildable, so programme-aware sizing is no longer optional. Retained so persisted requests stay valid; report.footprint_source names the binding constraint."
    )
    selected_scheme_id: Optional[str] = Field(
        default=None,
        description="Optional user-chosen scheme id; recorded in provenance when scheme alternatives are generated"
    )
    partition_variant: Optional[Literal["service_row", "single_unit", "duplex"]] = Field(
        default=None,
        description=(
            "Optional deterministic T2 plate variant. 'service_row' is the S1 "
            "depth-row alternative; 'single_unit' is V2 (one dwelling per floor, "
            "core/lobby in a north strip); 'duplex' is V3, four floor-level "
            "units per plate arranged as two-storey dwellings with an internal "
            "unit stair. Omitting it keeps the baseline side-by-side two-unit "
            "partition."
        ),
    )
    units_per_floor: Optional[int] = Field(
        default=None,
        ge=1,
        le=4,
        description=(
            "Declared floor-level units. T2 implements 1 (one-unit V2 plate), 2 "
            "(side-by-side) and 4 when partition_variant='duplex' (four "
            "floor-level units, grouped into dwellings that span two storeys). "
            "3 is not implemented and is rejected rather than drawn as a "
            "different plan. Omitted keeps the typology default."
        ),
    )
    confirm_dwelling_deficit: bool = Field(
        default=False,
        description=(
            "Explicit confirmation of a strategy's dwelling-count change. The "
            "ladder measures S2 but will not make it the active generation "
            "until this is true; the unconfirmed result stays a remediation card."
        ),
    )

    @model_validator(mode="after")
    def validate_duplex_unit_count(self) -> "FloorPlanRequest":
        """Duplex is a drawn variant with four floor-level units per plate.

        The doorway into V3 is explicit: the caller must ask for the duplex
        variant (and, if it declares a count, the four floor-level units that
        variant actually draws).  Asking for four units without the variant is
        refused rather than silently drawn as a two-unit plate.
        """
        if self.partition_variant == "duplex":
            if self.units_per_floor not in (None, 4):
                raise ValueError(
                    "partition_variant='duplex' draws four floor-level units "
                    "per plate (two two-storey dwellings in the target "
                    "programme); units_per_floor must be omitted or 4."
                )
            if self.floors is not None and int(self.floors) % 2:
                raise ValueError(
                    "partition_variant='duplex' needs an even number of storeys "
                    "so every dwelling has its paired upper level."
                )
            return self
        if self.units_per_floor == 4:
            raise ValueError(
                "units_per_floor=4 is implemented only with "
                "partition_variant='duplex'. Implemented T2 variants are 1 "
                "(single_unit), 2 (side-by-side / service_row) and duplex=4."
            )
        return self

    @model_validator(mode="after")
    def reject_unimplemented_t2_units(self) -> "FloorPlanRequest":
        """Do not accept a T2 unit count the partitioner cannot draw.

        T2 now draws 1, 2 or (with the explicit duplex variant) 4 floor-level
        units.  Three remains unimplemented; requiring it used to return a "
        successful two-unit plan whose ``units_per_floor`` said three.  The "
        request is refused at the API boundary with a named range instead of "
        being silently clamped.
        """
        # Mirror normalize_typology(): every identifier that resolves to T2
        # must be refused here, or the engine's strict guard becomes a 500
        # instead of a named 422.
        t2_aliases = (
            "residential_multi",
            "T2_FAMILY_APARTMENT",
            "t2_family_apartment",
            "apartment",
            "duplex",
            "builder_floor",
            "t2",
        )
        if (
            self.building_typology in t2_aliases
            and self.units_per_floor is not None
            and self.units_per_floor > 2
            and not (self.partition_variant == "duplex" and self.units_per_floor == 4)
        ):
            raise ValueError(
                f"units_per_floor={self.units_per_floor} is not implemented for "
                "T2_FAMILY_APARTMENT. Implemented values are 1 (one-unit V2 "
                "plate), 2 (side-by-side two-unit plate) and 4 with "
                "partition_variant='duplex' (two-storey dwellings); a "
                "three-unit T2 partition is not available."
            )
        return self

    @model_validator(mode="after")
    def enforce_typology_unit_range(self) -> "FloorPlanRequest":
        """Refuse a unit count the typology does not draw.

        T1/T3/T4 used to clamp an out-of-range ``units_per_floor`` and then
        certify the smaller plan under a generation token that still named the
        requested count: a T1 request for three units returned a ONE-unit plan
        labelled CERTIFIED.  The typology's own ProgrammeVariables is the
        single source of truth, so the API boundary refuses the same range the
        engine declares - it never substitutes a different count for a
        certified answer.  T2 keeps its named 422 above (three units and the
        duplex doorway are T2-specific), so it is skipped here.
        """
        if self.units_per_floor is None:
            return self
        # Lazy imports keep the schema module free of a services import cycle.
        from app.services.floorplan.programme_variables import get_programme_variables
        from app.services.floorplan.typologies import TYPOLOGY_T2, normalize_typology

        canonical = normalize_typology(self.building_typology)
        if canonical == TYPOLOGY_T2:
            return self
        variables = get_programme_variables(canonical)
        low, high = variables.units_per_floor_range
        value = int(self.units_per_floor)
        if low <= value <= high:
            return self
        expected = (
            f"{low}" if low == high else f"{low}-{high}"
        )
        raise ValueError(
            f"units_per_floor={value} is outside the implemented range for "
            f"{canonical} ({expected}); the engine will not draw a different "
            "unit count while reporting the requested one."
        )

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "multiStorey" in data and "multi_storey" not in data:
                data["multi_storey"] = data["multiStorey"]
            if "floorPlateMasks" in data and "floor_plate_masks" not in data:
                data["floor_plate_masks"] = data["floorPlateMasks"]
            if "terraceBands" in data and "terrace_bands" not in data:
                data["terrace_bands"] = data["terraceBands"]
            if "groundCoverageRatio" in data and "ground_coverage_ratio" not in data:
                data["ground_coverage_ratio"] = data["groundCoverageRatio"]
            if "builtUpAreaSqft" in data and "built_up_area_sqft" not in data:
                data["built_up_area_sqft"] = data["builtUpAreaSqft"]
            if "requiredRooms" in data and "required_rooms" not in data:
                data["required_rooms"] = data["requiredRooms"]
            if "plotWidthM" in data and "plot_width_m" not in data:
                data["plot_width_m"] = data["plotWidthM"]
            if "plotDepthM" in data and "plot_depth_m" not in data:
                data["plot_depth_m"] = data["plotDepthM"]
            if "plotPolygon" in data and "plot_polygon" not in data:
                data["plot_polygon"] = data["plotPolygon"]
            if "bypassCache" in data and "bypass_cache" not in data:
                data["bypass_cache"] = data["bypassCache"]
            if "includeSchemeAlternatives" in data and "include_scheme_alternatives" not in data:
                data["include_scheme_alternatives"] = data["includeSchemeAlternatives"]
            if "programAwareFootprint" in data and "program_aware_footprint" not in data:
                data["program_aware_footprint"] = data["programAwareFootprint"]
            if "selectedSchemeId" in data and "selected_scheme_id" not in data:
                data["selected_scheme_id"] = data["selectedSchemeId"]
            # If plot_polygon is provided without plot dimensions, derive bounding box dimensions
            poly_data = data.get("plot_polygon")
            if poly_data:
                verts = poly_data.get("vertices") if isinstance(poly_data, dict) else getattr(poly_data, "vertices", None)
                if verts and len(verts) >= 3:
                    xs = [pt[0] for pt in verts]
                    ys = [pt[1] for pt in verts]
                    bbox_w = round(max(xs) - min(xs), 2)
                    bbox_d = round(max(ys) - min(ys), 2)
                    if data.get("plot_width_m") is None:
                        data["plot_width_m"] = bbox_w
                    if data.get("plot_depth_m") is None:
                        data["plot_depth_m"] = bbox_d
            # Extract plot dimensions from multi_storey if not explicitly at top level
            if data.get("multi_storey") and isinstance(data["multi_storey"], dict):
                ms = data["multi_storey"]
                if "plot_width_m" not in data and "plot_width_m" in ms:
                    data["plot_width_m"] = ms["plot_width_m"]
                if "plot_depth_m" not in data and "plot_depth_m" in ms:
                    data["plot_depth_m"] = ms["plot_depth_m"]
                if "plot_polygon" not in data and "plot_polygon" in ms:
                    data["plot_polygon"] = ms["plot_polygon"]
                if "floors" not in data and "total_storeys" in ms:
                    data["floors"] = ms["total_storeys"]
                if "building_typology" not in data and "building_typology" in ms:
                    data["building_typology"] = ms["building_typology"]
            # Fallback default if neither polygon nor dimensions given
            if data.get("plot_width_m") is None:
                data["plot_width_m"] = 12.0
            if data.get("plot_depth_m") is None:
                data["plot_depth_m"] = 14.0
        return data

    @field_validator("seed", mode="before")
    @classmethod
    def coerce_numeric_seed(cls, v: Any) -> Any:
        """Accept numeric seeds (int/float, not bool) as canonical digit strings.

        The engine derives GEN/CERT tokens from the seed; callers may
        legitimately pass JSON numbers, so coerce them to strings up front
        instead of failing pydantic string validation.
        """
        if v is None or isinstance(v, str):
            return v
        if isinstance(v, bool):
            raise ValueError("seed must be a string or a number")
        if isinstance(v, (int, float)):
            return str(v)
        return v

    @field_validator("required_rooms")
    @classmethod
    def validate_rooms(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        seen = set()
        deduped = []
        for r in v:
            clean = r.strip().lower()
            if clean and clean not in seen:
                seen.add(clean)
                deduped.append(clean)
        if len(deduped) < 3:
            raise ValueError("At least 3 distinct rooms are required to synthesize a floor plan.")
        return deduped

    @model_validator(mode="after")
    def normalize_programme_ids(self) -> "FloorPlanRequest":
        """Resolve legacy/display room IDs to canonical ontology IDs.

        Old clients (and saved snapshots) send IDs such as ``apt_a_living`` or
        ``loading_dock``.  The typology was still solved correctly, but the
        programme audit reported every such room as unmet because the solver
        only knows the ontology IDs.  Normalizing here keeps the request and
        the audit on the same vocabulary without hiding genuinely unsupported
        rooms.
        """
        if self.required_rooms:
            from app.services.floorplan.room_aliases import normalize_room_ids

            self.required_rooms = normalize_room_ids(
                self.building_typology or "residential_single",
                self.required_rooms,
            )
        return self

class EnvelopeRect(BaseModel):
    x: float
    y: float
    width: float
    height: float
    area_sqm: float

class RoomRectangle(BaseModel):
    room_id: str
    room_name: str
    x: float
    y: float
    width: float
    height: float
    area_sqm: float
    zone: str
    vastu_compliant: bool
    applied_rules: List[str] = Field(default_factory=list, description="Ontology rule IDs shaping this room")
    relaxations: List[Dict[str, str]] = Field(default_factory=list, description="Rule relaxations with rationale tags")
    space_type_id: Optional[str] = Field(default=None, description="Canonical ontology space type")
    identity: Optional[SpaceIdentity] = Field(default=None, description="Resolved identity: single source for name, zone and service class")

class DoorGeometry(BaseModel):
    door_id: str
    from_room: str
    to_room: str
    wall_edge: str
    x1: float
    y1: float
    x2: float
    y2: float
    hinge_x: float
    hinge_y: float
    swing_direction: str
    width_m: float = 0.9

class WindowGeometry(BaseModel):
    window_id: str
    room_id: str
    wall_edge: str
    x1: float
    y1: float
    x2: float
    y2: float
    width_m: float

class FloorPlanQA(BaseModel):
    entry: str = Field(default="living", description="Entry room name")
    circulation: str = Field(default="connected", description="Circulation status: connected or disconnected")
    leaf_rule: bool = Field(default=True, description="Whether all bath/WC/utility/store nodes have degree == 1")
    peripheral_service: bool = Field(default=True, description="Whether service rooms touch exterior walls and avoid central 40% box")
    catalog: bool = Field(default=True, description="Whether room areas satisfy catalog bounds (e.g. bath 3.5-6 m2, puja min width 2.4m)")
    aspect: bool = Field(default=True, description="Whether aspect ratios are <= 1:2.2")
    critic: str = Field(default="skipped", description="Architect-critic verdict: pass, fail, or skipped (skipped when no critic ran - never a fabricated pass)")
    violations: int = Field(default=0, description="Count of FAILing validation-gate layers")
    critic_notes: Optional[List[str]] = Field(default_factory=list, description="Critic identified architectural concerns if any")
    # The universal gate is part of the QA contract (audit F23): it used to be
    # attached to the response but silently dropped by this model's schema.
    validation_gate: Optional[Dict[str, Any]] = Field(default=None, description="Universal validation gate L1-L15 report")
    validation_gate_status: Optional[str] = Field(default=None, description="Gate overall status: PASS | WARN | FAIL")
    invariants_verified: Optional[int] = Field(default=None, description="Certificate invariants that passed")
    invariants_total: Optional[int] = Field(default=None, description="Certificate invariants evaluated")

class RectanglesModel(BaseModel):
    envelope: EnvelopeRect
    rooms: List[RoomRectangle]
    doors: List[DoorGeometry] = Field(default_factory=list)
    windows: List[WindowGeometry] = Field(default_factory=list)
    qa: Optional[FloorPlanQA] = None

class RoomPlacement(BaseModel):
    room_id: str
    room_name: str
    row: int
    col: int
    width: int
    height: int
    area_sqm: float
    width_m: float
    depth_m: float
    zone: str
    vastu_compliant: bool
    space_type_id: Optional[str] = None
    identity: Optional[SpaceIdentity] = None

class FloorPlanMetrics(BaseModel):
    # Every percentage here is measured from the placed geometry (audit F04).
    # ``None`` means "not evaluable on this plan" and renders as “—”; it never
    # stands in for a pass.
    vastu_compliance_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    plumbing_adjacency_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    space_utilization_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    plot_coverage_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    total_built_up_sqm: float
    circulation_efficiency_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    circulation_status: Optional[str] = Field(default="connected", description="Circulation connectivity status")

class FloorPlanResponse(BaseModel):
    status: Literal["optimal", "compromise", "failed"]
    grid_matrix: List[List[str]] = Field(..., description="2D matrix of room IDs (R x C)")
    placements: List[RoomPlacement] = Field(..., description="Structured room placement coordinates")
    rectangles: Optional[RectanglesModel] = Field(default=None, description="Continuous geometric rectangles model")
    svg_blueprint: str = Field(..., description="Raw standalone W3C SVG XML string ready for frontend injection")
    svg_blueprint_paper: Optional[str] = Field(default=None, description="Paper blueprint theme SVG string ready for print or paper mode")
    metrics: FloorPlanMetrics
    warnings: List[str] = Field(default_factory=list)
    timing_ms: float = Field(..., description="Solver execution duration in milliseconds")
    iterations: int = Field(..., description="Total backtracking iterations evaluated")
    design_intent: Optional[str] = Field(default=None, description="2-3 sentence architectural design brief from room program")
    program_source: Optional[str] = Field(default="fallback", description="Source of room program: llm, cache, or fallback")
    placement_source: Optional[str] = Field(default="kb-default", description="Source of room placement: 'llm+kb' or 'kb-default'")
    placement_logic: Optional[Dict[str, str]] = Field(default_factory=dict, description="Room-by-room architectural rationale sentences")
    ai_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Room program generation metadata")
    room_program: Optional[RoomProgram] = Field(default=None, description="Room program specification evaluated by solver")
    qa: Optional[FloorPlanQA] = Field(
        default_factory=lambda: FloorPlanQA(entry="hall", circulation="connected", violations=0),
        description="Architectural spatial logic QA gate verification stats"
    )
    multi_storey: Optional[MultiStoreyBuildingModel] = Field(
        default=None,
        description="Full multi-storey building model synthesizing all floor plates and vertical cores"
    )
    client_constraints: Optional[ExtractedClientConstraints] = Field(
        default=None,
        description="Structured design constraints parsed from client requirements"
    )
    mathematical_certificate: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Mathematical validity certificate certifying non-overlap, containment, egress, adjacency, and stacking"
    )
    params_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Snapshot of generation input parameters"
    )
    unmet_requirements: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Requested rooms the solver could not satisfy, each with an explicit reason (zero silent skips)"
    )
    generation_id: Optional[str] = Field(
        default=None,
        description="Unique generation ID token"
    )
    seed: Optional[str] = Field(
        default=None,
        description="Deterministic generation seed"
    )
    generated_at: Optional[float] = Field(
        default=None,
        description="Timestamp of generation in epoch milliseconds"
    )
    site_plan: Optional[SitePlanModel] = Field(
        default=None,
        description="Canonical site plan with buildable polygon, setbacks, and outdoor fragments"
    )
    scheme_alternatives: Optional[List[SchemeAlternative]] = Field(
        default=None,
        description="Ranked scheme alternatives (only present when include_scheme_alternatives=true)"
    )
    scheme_portfolio: Optional[SchemePortfolio] = Field(
        default=None,
        description="Scheme portfolio provenance, reference metrics and selected scheme (only present when requested)"
    )
    selected_scheme_id: Optional[str] = Field(
        default=None,
        description="Selected scheme id, recorded in the response and provenance"
    )
    land_economics: Optional[LandEconomicsReport] = Field(
        default=None,
        description="Land-economics report and SPACE-EFFICIENCY certificate"
    )
    plan_verdict: Optional[Literal["CERTIFIED", "ADVISORY", "NOT-CERTIFIED-FAIL-STAMP"]] = Field(
        default=None,
        description=(
            "The ONE plan verdict, computed server-side from the certificate, the "
            "validation gate and the page-1 plan warnings. Card, certificate panel "
            "and PDF render this string verbatim; none re-derives a severity."
        ),
    )
    plan_verdict_reasons: Optional[List[str]] = Field(
        default=None,
        description="Named facts behind plan_verdict, in the order they were checked",
    )


class FloorPlanParamsSnapshot(BaseModel):
    building_typology: str
    floors: int
    ground_coverage_ratio: float
    plot_width_m: float
    plot_depth_m: float
    required_rooms: List[str] = Field(default_factory=list)
    vastu_strictness: str = "high"
    built_up_area_sqft: Optional[float] = None
    client_notes: Optional[str] = None
    ai_provider: Optional[str] = None
    shape_type: Optional[str] = "rectangle"
    plot_polygon: Optional[PlotPolygonModel] = None

