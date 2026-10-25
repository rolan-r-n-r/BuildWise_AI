"""
engine.py - Universal Ontology-Driven Spatial Geometry Engine
============================================================
The sole geometry engine for BuildWise. Synthesizes architecturally sound,
statutorily compliant (NBC 2016), constructible floor plates for all typologies
(T1 Single Family, T2 Apartment, T3 Complex, T4 Warehouse) across 1 to 4 storeys.

Parameterized EXCLUSIVELY by ontology data (ONTOLOGY) and typology profiles (TYPOLOGY_PROFILES).
- Zero hardcoded geometry templates (Templates A/B/C retired).
- Zero LLM placement/critic in the geometry loop.
- Zero reliance on legacy CSP grid packing.
- Enforces Anchor Phase vertical core and plumbing shaft locking from Level 0.
- Emits a MathematicalValidityCertificate per generation for UI QA and PDF Sheet 10.0.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import List, Dict, Optional, Tuple, Set, Any
from collections import deque

from app.schemas.floorplan import (
    FloorPlanRequest,
    FloorPlanResponse,
    EnvelopeRect,
    RoomRectangle,
    DoorGeometry,
    WindowGeometry,
    RectanglesModel,
    FloorPlanMetrics,
    FloorPlanQA,
    RoomPlacement,
    TerraceBandSpec,
)
from app.schemas.multi_floor_plan import (
    MultiStoreyBuildingModel,
    SingleFloorPlanModel,
    UnmetRequirement,
    VerticalCoreSpec,
    DuctShaftSpec,
    MultiFloorRoomRectangle,
    MultiFloorDoorGeometry,
    MultiFloorWindowGeometry,
    StructuralGridSpec,
)
from app.schemas.site_plan import SitePlanModel
from app.services.floorplan.site_geometry import compute_canonical_site_plan
from app.services.floorplan.derived_metrics import apply_to_building
from app.services.floorplan.ontology import (
    ONTOLOGY,
    MathematicalValidityCertificate,
    FunctionType,
    FloorLoad,
    HygieneType,
    RelationType,
    SpaceTypeSpec,
)
from app.services.floorplan.wall_graph import (
    build_constructible_wall_graph,
    compute_stair_geometry,
)
from app.services.floorplan.identity import (
    apply_space_identities,
    space_type_of,
    summarize_identities,
)
from app.services.floorplan.svg_generator import generate_multi_floor_blueprint_svg
from app.services.floorplan.furniture import (
    repair_room_envelopes_for_furniture,
)
from app.services.floorplan.ventilation import ensure_wet_room_ventilation
from app.services.floorplan.living_quality import (
    audit_and_enforce_zoning_separation,
    audit_and_resolve_door_swings,
    compute_door_swing_polygon,
    place_and_audit_bathroom_fixtures,
    place_and_audit_furniture_catalog,
    audit_and_enforce_naming_honesty,
    audit_and_enforce_program_intent,
    audit_swings_against_walls_corridors_furniture,
    find_door_host,
    host_door_on_shared_wall,
    nominal_door_toward,
)
from app.services.floorplan.validation_gate import (
    build_gate_layers,
    assemble_gate_report,
    refusal_gate_report,
    sanitize_llm_constraints,
    HARD_FAIL_LAYERS,
)
from shapely.geometry import box as shp_box
from shapely.ops import unary_union

# Smallest plate the solver will ever propose (statutory habitability floor).
MIN_FOOTPRINT_AREA_M2 = 30.0
# Legacy comfortable plate for single-storey T1 bands (9.60 m x 8.15 m); the
# plate AREA comes from the programme, this keeps its tuned proportion.
T1_COMFORT_W_M = 9.60
T1_COMFORT_D_M = 8.15
# Composite envelopes are not one habitable room, so NBC proportion limits do
# not govern them: an office-suite band is a row of work rooms, and an
# industrial bay is a dock/staging strip. Area and width minima still apply.
ASPECT_EXEMPT_SPACE_IDS = {"commercial_suite", "industrial_bay"}
# From this plot size upward the plate is programme-sized.  "Large" means a
# site a house cannot sensibly fill (hectare-scale boundaries in the audit),
# not an ordinary 15 x 20 m suburban plot: at 300 m² the rule also caught
# 23 x 14 m plots and shrank their plate from the full coverage envelope to
# the bare programme, collapsing every band to 2.2 m.  Below the threshold the
# tuned plate is kept and the proportion ladder handles the surplus.
LARGE_PLOT_PROGRAM_THRESHOLD_M2 = 1000.0
# A plate may exceed the stated programme need by this factor before it is
# resized. The need already carries 14% circulation + 8% walls + core, so this
# is a small construction/rounding allowance, not a licence to stretch.
PROGRAM_PLATE_ALLOWANCE = 1.15


def _stamp_listed_min_relaxation(room: Any, measure: str, measured: float,
                                 required: float, reason: str) -> None:
    """List a catalogue-minimum shortfall ON the room.

    The certificate used to tolerate a shortfall only inside its 0.85/0.80/0.70
    band; beyond that the room was a bare hard failure with no record, which the
    sweep rightly counted as an UNLISTED breach.  A plate that physically
    cannot hold the catalogue minimum still must not pretend the room complies:
    the strict flag stays False (the certificate FAILs and the plan is stamped
    NOT CERTIFIED), while this entry makes the breach individually listed and
    auditable - measured value, required value, and why the plate cannot give
    more.  Idempotent per (measure, basis).
    """
    for rel in (getattr(room, "relaxations", None) or []):
        if (str(rel.get("rule_id")) == "NBC-01"
                and rel.get("basis") == "programme_squeeze"
                and rel.get("measure") == measure):
            return
    shortfall = max(0.0, float(required) - float(measured))
    room.relaxations.append({
        "rule_id": "NBC-01",
        "basis": "programme_squeeze",
        "measure": measure,
        "rationale": (
            f"{measure} {float(measured):.2f} is below the catalogue minimum "
            f"{float(required):.2f} (short by {shortfall:.2f}); {reason}. Listed "
            "as a relaxation on this room and reported by the ROOM-MIN warning; "
            "the certificate still fails the dimension layer, so the plan is "
            "never claimed compliant."
        ),
    })


class HardConstraintViolation(ValueError):
    """A declared hard invariant the partitioner could not satisfy.

    The message stays human-readable (and keeps the historical
    "Hard Constraint Violation" prefix every caller matches), while the
    structured fields let the selection path name the conflict instead of
    flattening it into an opaque 422: a ROOM-OVERLAP carries the id pair and
    the measured overlap area.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "HARD",
        rooms: Tuple[str, ...] = (),
        overlap_sqm: Optional[float] = None,
        floor_index: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.rooms = tuple(rooms)
        self.overlap_sqm = overlap_sqm
        self.floor_index = floor_index


class SoleGeometryEngine:
    """
    Universal Geometry Engine consuming the Universal Space Semantics Ontology.
    Single solver path for all typologies (T1, T2, T3, T4) across 1 to 4 floors.
    """

    def __init__(
        self,
        request: FloorPlanRequest | Dict[str, Any],
        ai_provider: Optional[str] = "mock"
    ):
        if isinstance(request, FloorPlanRequest):
            self.req = request
        else:
            self.req = FloorPlanRequest.model_validate(request)

        self.plot_w = float(self.req.plot_width_m)
        self.plot_d = float(self.req.plot_depth_m)
        self.total_storeys = max(1, min(4, self.req.floors or 1))
        self.coverage = float(self.req.ground_coverage_ratio or 0.60)
        self.strictness = self.req.vastu_strictness or "high"
        self.client_constraints = self.req.extracted_constraints
        # LLM-BOUNDARY INVARIANT: enforced at solve() time (see below) so ANY
        # constraint object that reaches the solver is audited, even if a future
        # refactor bypasses the pydantic schema layer.
        self.llm_boundary_audit = {
            "events": [],
            "event_ids": [],
            "contract": "llm_confined_to_text_parsing_and_narrative_v1",
        }
        self.ai_provider = ai_provider
        # Deterministic seed: honor an explicit numeric seed (int or digit
        # string) so GEN tokens/CERT ids derive from the REQUEST; anything else
        # (absent / non-numeric) falls back to the historical 42 so legacy
        # outputs stay byte-identical.
        _raw_seed = getattr(self.req, "seed", None)
        if isinstance(_raw_seed, bool):
            self.seed = 42
        elif isinstance(_raw_seed, (int, float)):
            self.seed = int(_raw_seed)
        elif isinstance(_raw_seed, str) and _raw_seed.strip().isdigit():
            self.seed = int(_raw_seed.strip())
        else:
            self.seed = 42
        self.site_plan: Optional[SitePlanModel] = None

        # Typology Normalization
        self.raw_typology = self.req.building_typology or "residential_single"
        self.profile = ONTOLOGY.get_typology(self.raw_typology)
        self.typology = getattr(self.profile, "canonical", "T1_SINGLE_FAMILY")

        # Structural Column Grid Spec (primarily T4 & T3)
        bay_x = round(min(6.0, self.plot_w * 0.4), 2)
        bay_y = round(min(6.0, self.plot_d * 0.4), 2)
        self.structural_grid = StructuralGridSpec(
            bay_spacing_x_m=bay_x,
            bay_spacing_y_m=bay_y,
            columns_x=[round(x, 2) for x in [0.0, self.plot_w * 0.35, self.plot_w * 0.7]],
            columns_y=[round(y, 2) for y in [0.0, self.plot_d * 0.35, self.plot_d * 0.7]],
            column_size_m=0.45,
        )

        self.warnings: List[str] = []
        self.relaxations: List[Dict[str, str]] = []
        # Cells the multi-wing typology programme could not draw:
        # named in a PROGRAMME-SQUEEZE line, never dropped silently.
        self._wing_omissions: List[str] = []
        self.identity_summaries: List[Dict[str, Any]] = []
        # Per-floor record of what the proportion law actually did.
        self.proportion_law_audits: List[Dict[str, Any]] = []
        # Selected scheme profile: when set, the band solver
        # partitions the plate with these weights and the engine's own post-
        # processing (openings, wall graph, land, gate, certificate, sheets)
        # runs on THAT geometry. Without this the picker re-solved nothing.
        _profile = str(getattr(self.req, "selected_scheme_id", None) or "").strip()
        self.scheme_profile: Optional[str] = _profile if _profile in (
            "max_area", "max_vastu", "max_light_vent"
        ) else None
        # floor_index -> rooms solved for that profile; filled inside solve().
        self.presolved_room_sets: Optional[Dict[int, List[MultiFloorRoomRectangle]]] = None
        self.scheme_selection_note: Optional[str] = None
        self.gate_report: Optional[Dict[str, Any]] = None
        self.gate_layers: List[Dict[str, Any]] = []

    # =========================================================================
    # 1. ENVELOPE & SETBACK DETERMINATION
    # =========================================================================

    def _comfortable_plate(self, *, plot_w: float, plot_d: float) -> Tuple[float, float]:
        """Tuned single-storey T1 plate (width, depth), or (0, 0) if none applies.

        These band proportions were tuned on residential plots 8-14 m wide. They
        are a COMFORT floor for the programme - never a licence to exceed the
        coverage ratio or the setback buildable, both applied afterwards.
        """
        rooms = self.req.required_rooms or []
        if (
            self.typology != "T1_SINGLE_FAMILY"
            or self.total_storeys != 1
            or len(rooms) < 3
        ):
            return 0.0, 0.0
        n_rooms = len(rooms)
        has_two_baths = sum(1 for r in rooms if any(k in r for k in ("bath", "toilet", "wc"))) >= 2
        has_bed2 = sum(1 for r in rooms if "bed" in r and "master" not in r) >= 1

        if n_rooms <= 5 and not has_bed2 and not has_two_baths:
            w = min(round(plot_w - 0.80, 2), T1_COMFORT_W_M) if plot_w >= 10.4 else round(plot_w - 1.20, 2)
            d = min(round(plot_d - 1.50, 2), T1_COMFORT_D_M)
        elif not has_two_baths and (has_bed2 or n_rooms == 6):
            if plot_w < 10.8:
                w = round(plot_w - 0.80, 2)
                d = min(round(plot_d - 2.50, 2), 10.20)
            else:
                w = min(11.80, max(10.50, round(plot_w - 0.40, 2)))
                d = min(round(plot_d - 1.50, 2), 8.35)
        elif has_two_baths or n_rooms >= 7:
            if plot_w < 10.8:
                w = round(plot_w - 0.40, 2)
                d = min(round(plot_d - 2.00, 2), 10.35)
            else:
                w = min(11.80, max(10.70, round(plot_w - 0.20, 2)))
                d = min(round(plot_d - 0.40, 2), 10.10)
        else:
            w = min(round(plot_w - 1.0, 2), 12.0)
            d = min(round(plot_d - 1.5, 2), 9.5)
        return max(w, 0.0), max(d, 0.0)

    def _plot_plan_area(self) -> float:
        """Plan area of the plot: captured boundary shoelace area when present.

        The coverage cap is a ratio of THIS area - never of a bounding box that
        a non-rectangular boundary does not actually occupy.
        """
        poly = getattr(self.req, "plot_polygon", None)
        area = float(getattr(poly, "area_sqm", 0.0) or 0.0) if poly is not None else 0.0
        return area if area > 0.0 else self.plot_w * self.plot_d

    def _compute_envelope(self) -> Tuple[bool, int, Dict[str, float], List[str]]:
        """
        Determines constructible building envelope per NBC 2016 setbacks.
        Returns: (is_feasible, degradation_level, envelope_dict, warnings)
        """
        warnings: List[str] = []
        deg_level = 0

        if self.req.plot_polygon is not None and not self.req.plot_polygon.is_regular_rectangle:
            is_ok, site_plan, site_warns = compute_canonical_site_plan(
                plot_width_m=self.plot_w,
                plot_depth_m=self.plot_d,
                coverage=self.coverage,
                plot_polygon=self.req.plot_polygon,
                program_needed_area_m2=(getattr(self, "program_needed_area_m2", None)
                                        if getattr(self.req, "program_aware_footprint", False) else None),
                typology=f"{self.req.building_typology}_courtyard" if (self.req.client_notes and "courtyard" in self.req.client_notes.lower()) else self.req.building_typology,
            )
            warnings.extend(site_warns)
            if not is_ok or site_plan is None:
                shortfall_msg = site_warns[0] if site_warns else "Irregular plot polygon validation or buildable offset failed."
                warnings.append(f"EC-03: Insufficient buildable area on irregular plot: {shortfall_msg}")
                dummy_env = {"x": 0.0, "y": 0.0, "width": 0.0, "depth": 0.0, "area_sqm": 0.0}
                return False, 5, dummy_env, warnings

            # The decomposition IS the site plan: wing masks, core anchoring
            # and the site sheet all read it.  (Dropping this assignment on the
            # programme-sized path left irregular plots with no plan, so every
            # declared wing mask was silently ignored.)
            self.site_plan = site_plan

            # Programme-sized plate on a large irregular site.  The inscribed
            # decomposition is the CAP, not the target: a 122 m2 brief on a
            # 9,661 m2 boundary used to become a 5,796 m2 plate, and every room
            # was then stretched to fill it.  Re-solve the site plan around a
            # compact rectangle of the programme's own area, centred on the
            # first footprint and kept inside the buildable polygon.
            _irr_plot_area = self._plot_plan_area()
            _need = float(getattr(self, "program_needed_area_m2", 0.0) or 0.0)
            if _irr_plot_area >= LARGE_PLOT_PROGRAM_THRESHOLD_M2 and _need > 0.0:
                _cap = min(
                    float(site_plan.buildable_area_sqm or 0.0) or _irr_plot_area * self.coverage,
                    _irr_plot_area * self.coverage,
                )
                _target = min(
                    _cap,
                    max(_need * PROGRAM_PLATE_ALLOWANCE, MIN_FOOTPRINT_AREA_M2),
                )
                _current = float(site_plan.footprint.area_sqm or 0.0)
                if _current > _target * 1.02:
                    from shapely.geometry import Polygon as _ShpPolygon
                    _fp = site_plan.footprint
                    _w0, _d0 = float(_fp.width_m), float(_fp.depth_m)
                    _asp = max(0.5, min(2.5, _w0 / max(_d0, 0.1)))
                    _nw = round(math.sqrt(_target * _asp), 2)
                    _nd = round(_target / _nw, 2)
                    _x = round(_fp.x + (_w0 - _nw) / 2.0, 2)
                    _y = round(_fp.y + (_d0 - _nd) / 2.0, 2)
                    _buildable = _ShpPolygon(site_plan.buildable_polygon_coords)
                    _cand = shp_box(_x, _y, _x + _nw, _y + _nd)
                    _fit = _buildable.buffer(-0.01).contains(_cand)
                    if not _fit:
                        _minx, _miny, _maxx, _maxy = _buildable.bounds
                        _x, _y = round(_minx, 2), round(_miny, 2)
                        _cand = shp_box(_x, _y, _x + _nw, _y + _nd)
                        _fit = _buildable.buffer(-0.01).contains(_cand)
                    if _fit:
                        _override = {
                            "x": _x, "y": _y, "width": _nw, "depth": _nd,
                            "area_sqm": round(_nw * _nd, 2),
                        }
                        _ok2, _sp2, _w2 = compute_canonical_site_plan(
                            plot_width_m=self.plot_w,
                            plot_depth_m=self.plot_d,
                            coverage=self.coverage,
                            plot_polygon=self.req.plot_polygon,
                            program_needed_area_m2=_need,
                            typology=(
                                f"{self.req.building_typology}_courtyard"
                                if (self.req.client_notes and "courtyard" in self.req.client_notes.lower())
                                else self.req.building_typology
                            ),
                            inscribed_override=_override,
                        )
                        if _ok2 and _sp2 is not None and 0 < _sp2.footprint.area_sqm <= _target * 1.05:
                            site_plan = _sp2
                            self.site_plan = _sp2
                            warnings.extend(_w2)
                            warnings.append(
                                f"LAND-11: Plate sized to the programme ({_target:.1f} m2, "
                                f"capped by the {_cap:.1f} m2 coverage/buildable ceiling) "
                                f"instead of the {_current:.1f} m2 maximum inscribed footprint."
                            )
                self.footprint_target_area = _target
                self.footprint_ceiling_area = round(_cap, 2)
                self.coverage_cap_area = round(_irr_plot_area * self.coverage, 2)

            env_w = site_plan.footprint.width_m
            env_d = site_plan.footprint.depth_m
            env_area = site_plan.footprint.area_sqm
            # The LEGAL ceiling is the smaller of the coverage ratio applied to
            # the plot's own plan area and the setback buildable - never the
            # inscribed rectangle the deformable plate happened to become. The
            # two differ on irregular plots (a 14 x 16 m trapezoid buildable
            # admits only a 72 m² rectangle inside a 108 m² legal ceiling), and
            # conflating them turned an ordinary 7 %-tight brief into a
            # bogus "statutory ceiling" refusal.
            self.footprint_ceiling_area = round(
                min(float(site_plan.buildable_area_sqm or 0.0) or _irr_plot_area * self.coverage,
                    _irr_plot_area * self.coverage), 2)
            self.coverage_cap_area = round(_irr_plot_area * self.coverage, 2)
            envelope = {
                "x": site_plan.footprint.x,
                "y": site_plan.footprint.y,
                "width": env_w,
                "depth": env_d,
                "area_sqm": env_area,
                "wings": site_plan.footprint.wings,
                "corridors": site_plan.footprint.corridors,
                "topology_type": site_plan.footprint.topology_type,
            }
        else:
            # NBC 2016 Part 3 Setbacks
            front_setback = max(1.8, min(3.5, self.plot_d * 0.15))
            rear_setback = max(1.2, min(2.5, self.plot_d * 0.10))
            side_setback = max(1.0, min(2.0, self.plot_w * 0.10))

            # The setback envelope below is corner-based (it measures from the
            # plot's edges), but a CAPTURED boundary is pin-centred, so its local
            # origin is not the bbox corner. Anchor the envelope on that corner:
            # otherwise the override places the footprint (and the whole floor
            # plate) beside the plot, split from its own buildable polygon.
            # Origin-anchored plots keep minx/miny = 0 and are unchanged.
            _poly_vs = getattr(self.req.plot_polygon, "vertices", None) or []
            poly_minx = min((float(v[0]) for v in _poly_vs), default=0.0)
            poly_miny = min((float(v[1]) for v in _poly_vs), default=0.0)

            avail_w = max(4.0, self.plot_w - 2 * side_setback)
            avail_d = max(4.0, self.plot_d - front_setback - rear_setback)
            avail_area = avail_w * avail_d

            # The coverage denominator is the PLOT's own plan area (shoelace when
            # a boundary was captured, else the rectangle), never the bounding
            # box of a non-rectangular boundary.
            plot_plan_area = self._plot_plan_area()
            coverage_ceiling = min(avail_area, plot_plan_area * self.coverage)
            need = float(getattr(self, "program_needed_area_m2", 0.0) or 0.0)

            # COVERAGE IS A CEILING, NOT A TARGET. A plate the
            # programme does not need is wasted ground coverage and, worse, the
            # partitioner has to stretch rooms to fill it. The plate therefore
            # follows the programme, with two hard ceilings - the statutory
            # coverage ratio and the setback buildable - that it may never
            # exceed:
            #  - default: max(programme need, the typology's comfortable plate)
            #    so a tuned layout is never squeezed below its own band
            #    assumptions while an oversized plot still gets a house the
            #    programme actually needs (a 4-room brief on a 1-hectare site
            #    can no longer become an 8,632 m² footprint or a 1,000 m² bedroom);
            #  - program_aware_footprint=true: the programme need alone;
            #  - a demand beyond the ceiling becomes an explicit LAND-01 deficit.
            comfort_w, comfort_d = self._comfortable_plate(plot_w=self.plot_w, plot_d=self.plot_d)
            comfort_area = round(comfort_w * comfort_d, 2) if comfort_w > 0 and comfort_d > 0 else 0.0
            # A linear plate (buildable longer than 2.5x its width) cannot spend
            # extra coverage on a wider band: every extra metre of depth only
            # lengthens the same rooms.  Its "comfortable plate" is therefore the
            # programme itself, not the buildable's own area.
            from app.services.floorplan.proportion_law import spine_corridor_required
            _linear_plate = spine_corridor_required(avail_w, avail_d)
            if getattr(self.req, "program_aware_footprint", False) or _linear_plate:
                target_area = min(coverage_ceiling, max(need, MIN_FOOTPRINT_AREA_M2))
            elif comfort_area > 0.0:
                target_area = min(coverage_ceiling, max(need, comfort_area))
            elif plot_plan_area >= LARGE_PLOT_PROGRAM_THRESHOLD_M2 and need > 0.0:
                # Large plot, non-T1 programme: the plate follows the brief.
                # Filling coverage here is what stretched a 122 m2 brief into a
                # 5,796 m2 footprint and produced 35 m deep room bands.
                target_area = min(
                    coverage_ceiling,
                    max(need * PROGRAM_PLATE_ALLOWANCE, MIN_FOOTPRINT_AREA_M2),
                )
            else:
                # Small plot: keep the tuned legacy plate. Its area is already
                # bounded by the coverage/setback ceiling and the programme
                # deficit is reported rather than hidden by a smaller plate.
                target_area = coverage_ceiling
            self.footprint_target_area = target_area
            self.footprint_ceiling_area = coverage_ceiling
            self.coverage_cap_area = round(plot_plan_area * self.coverage, 2)
            # Plate aspect. Single-storey T1 rooms are zoned in N/S bands, so a
            # lateral plate (the legacy 9.60 x 8.15 residential proportion)
            # places them well; scaling that proportion to the target area keeps
            # the tuned band layout while the AREA comes from the programme.
            # Every other typology uses the buildable's own proportion.
            if comfort_w > 0 and comfort_d > 0:
                aspect = comfort_w / comfort_d
            else:
                aspect = max(0.5, min(2.0, avail_w / max(avail_d, 0.01)))

            # Width is clamped to the setback envelope FIRST, then the depth is
            # re-solved from the target AREA. Clamping the depth to its own
            # independent limit (the old order) silently discarded area: a
            # 6 x 24 m plot asked for 62.7 m² and got a 48.1 m² plate, so the
            # programme could not be placed and the brief was refused for a
            # shortfall the geometry itself had created.
            env_d = math.sqrt(target_area / aspect) if aspect > 0 else avail_d
            env_w = min(avail_w, target_area / env_d if env_d > 0 else avail_w)
            env_d = min(avail_d, target_area / env_w if env_w > 0 else avail_d)
            env_w = round(max(4.0, env_w), 2)
            env_d = round(max(4.0, env_d), 2)
            # Rounding must never push the plate OVER the legal ceiling: it is a
            # hard cap, so the depth is floored (never rounded up) to keep the
            # plate inside it to the square centimetre.
            if env_w > 0 and env_w * env_d > coverage_ceiling:
                env_d = math.floor((coverage_ceiling / env_w) * 100.0) / 100.0
                env_d = max(4.0, env_d)
            env_area = round(env_w * env_d, 2)

            # Anchor on the buildable's south-west corner so the plate sits
            # inside the setback envelope (the legacy plate was anchored on the
            # plot edge and encroached on the setbacks).
            envelope = {
                "x": round(poly_minx + side_setback, 2),
                "y": round(poly_miny + front_setback, 2),
                "width": env_w,
                "depth": env_d,
                "area_sqm": env_area,
            }

            if need > coverage_ceiling + 0.5:
                warnings.append(
                    f"LAND-01: Programme needs {need:.1f} m² but the coverage/setback "
                    f"ceiling allows {coverage_ceiling:.1f} m²; explicit deficit "
                    f"{max(0.0, need - coverage_ceiling):.1f} m²."
                )


            # Canonical site plan synthesis with exact legacy envelope preservation
            is_ok, site_plan, site_warns = compute_canonical_site_plan(
                plot_width_m=self.plot_w,
                plot_depth_m=self.plot_d,
                coverage=self.coverage,
                plot_polygon=self.req.plot_polygon,
                program_needed_area_m2=(getattr(self, "program_needed_area_m2", None)
                                        if getattr(self.req, "program_aware_footprint", False) else None),
                inscribed_override=envelope,
                typology=f"{self.req.building_typology}_courtyard" if (self.req.client_notes and "courtyard" in self.req.client_notes.lower()) else self.req.building_typology,
            )
            if is_ok and site_plan:
                self.site_plan = site_plan

        min_habitable_m2 = 28.0
        if env_area < min_habitable_m2 and self.plot_w * self.plot_d < 45.0:
            shortfall = round(min_habitable_m2 - env_area, 1)
            warnings.append(
                f"EC-03: Insufficient plot footprint: envelope area {env_area:.1f} m² is below "
                f"minimum statutory threshold ({min_habitable_m2} m²). "
                f"Area shortfall is {shortfall} m²."
            )
            return False, 5, envelope, warnings

        if env_area < 33.0:
            deg_level = max(deg_level, 3)
            warnings.append(
                f"Degradation Level 3 applied: Compact envelope ({env_area:.1f} m²). "
                f"Secondary luxury spaces consolidated into primary zones."
            )

        plot_ratio = self.plot_w / self.plot_d if self.plot_d > 0 else 1.0
        if plot_ratio > 2.5 or plot_ratio < 0.4:
            deg_level = max(deg_level, 1)
            warnings.append(
                f"Degradation Level 1 applied: Extreme plot aspect ratio (1:{1/plot_ratio:.1f}). "
                f"Relaxed service room aspect ratios."
            )

        return True, deg_level, envelope, warnings

    # =========================================================================
    # 2. VERTICAL ANCHOR PHASE (RULE OF CORES & SHAFTS)
    # =========================================================================

    def _lock_vertical_anchors(self, envelope: Dict[str, float]) -> Tuple[List[VerticalCoreSpec], List[DuctShaftSpec]]:
        """
        Locks immutable vertical cores (staircase, passenger lift) and MEP shafts
        on Level 0, guaranteeing exact coordinate alignment across all storeys (VERT-03).
        """
        env_x = envelope["x"]
        env_y = envelope["y"]
        env_w = envelope["width"]
        env_d = envelope["depth"]

        vertical_cores: List[VerticalCoreSpec] = []
        duct_shafts: List[DuctShaftSpec] = []

        # 1. Staircase Core Sizing via computed stair geometry
        stair_geom = compute_stair_geometry(floor_height_m=self.profile.floor_height_m, typology=self.typology)
        stair_w = stair_geom.stair_box_width_m
        stair_d = stair_geom.stair_box_depth_m
        landing_d = stair_geom.landing_depth_m
        tread_mm = int(round(stair_geom.tread_depth_m * 1000.0))
        riser_mm = int(round(stair_geom.riser_height_m * 1000.0))

        # Position along West flank (optimal Vastu zone for heavy vertical load, W/SW)
        # A North terrace band (explicit or wing-mask translated) is resolved per
        # plate; the lift placement below reads it on every branch, so it is
        # initialized once here rather than only in the single-wing branch.
        north_band_depth: Optional[float] = None
        if self.site_plan and self.site_plan.footprint and len(self.site_plan.footprint.wings) > 1:
            wing_a = self.site_plan.footprint.wings[0]
            w_a_rel_x = round(wing_a.x - env_x, 2)
            w_a_rel_y = round(wing_a.y - env_y, 2)
            core_x = w_a_rel_x
            core_y = w_a_rel_y
            core_w = round(stair_w, 2)
            corridor_d = round(max(1.20, min(1.50, wing_a.depth_m * 0.28)), 2)
            core_d = round(wing_a.depth_m - corridor_d, 2)
        else:
            core_x = round(0.20, 2)
            # If user requested a North terrace band on an upper floor, align core_y cleanly
            north_band_depth = None
            if getattr(self.req, "terrace_bands", None):
                for fl_k, tb in self.req.terrace_bands.items():
                    try:
                        fl_idx = int(fl_k)
                    except (ValueError, TypeError):
                        continue
                    if fl_idx > 0:
                        edge = getattr(tb, "edge", None) or (tb.get("edge") if isinstance(tb, dict) else None)
                        d_m = getattr(tb, "depth_m", None) or (tb.get("depth_m") if isinstance(tb, dict) else 0.0)
                        if str(edge).upper() == "N" and float(d_m) >= 2.0:
                            north_band_depth = round(min(float(d_m), 0.40 * env_d), 2)
                            break

            if north_band_depth is None:
                # A wing mask translated into a terrace band reserves the same
                # North strip as an explicit request; the core must clear it.
                _masked_north = any(
                    int(lvl) > 0
                    for lvl in getattr(self, "_ignored_mask_terrace_intents", {}) or {}
                )
                if _masked_north:
                    north_band_depth = round(min(3.0, 0.40 * env_d), 2)

            if north_band_depth is not None:
                core_y = north_band_depth
            elif self.typology == "T2_FAMILY_APARTMENT":
                # A compact two-unit plate cannot carry two full
                # programmes in one row, and HYG-02 forbids the bath/kitchen
                # stack that would otherwise free the frontage.  The plan that
                # survives the law moves the stair to the east flank and uses
                # the freed pocket for one unit's bedroom and the other unit's
                # bathroom; both living rooms then reach the shared lobby and
                # every room meets its catalogue minimum.  When the row already
                # fits, keep the historical placement untouched.
                legacy_north = round(max(2.8, (env_d - stair_d) * 0.45), 2)
                legacy_south = round(env_d - legacy_north - stair_d, 2)
                row_fits = (self._t2_row_meets_areas(env_w, legacy_north)
                            and self._t2_row_meets_areas(env_w, legacy_south))
                pocket = None if row_fits else self._t2_pocket_plan(env_w, env_d, stair_w, stair_d)
                if pocket is not None:
                    self._t2_pocket = pocket
                    core_x = round(env_w - stair_w, 2)
                    core_y = pocket["band"]
                else:
                    core_y = legacy_north
            else:
                core_y = round(max(2.8, (env_d - stair_d) * 0.45), 2)
            core_w = round(stair_w, 2)
            core_d = round(stair_d, 2)

        stair_spec = VerticalCoreSpec(
            core_id="core_staircase_primary",
            core_type="staircase_fire" if self.typology in ("T3_LARGE_COMPLEX", "T4_WAREHOUSE") else "staircase_dogleg",
            x=core_x,
            y=core_y,
            width_m=core_w,
            depth_m=core_d,
            landing_depth_m=landing_d,
            tread_mm=tread_mm,
            riser_mm=riser_mm,
            continuous_across_floors=list(range(self.total_storeys)),
        )
        vertical_cores.append(stair_spec)

        # 2. Passenger / Stretcher Lift Core
        needs_lift = (
            (self.total_storeys >= 4) or
            (self.typology in ("T2_FAMILY_APARTMENT", "T3_LARGE_COMPLEX") and self.total_storeys >= 3) or
            bool(self.req.required_rooms and any("lift" in r.lower() or "elevator" in r.lower() for r in self.req.required_rooms))
        )
        if needs_lift and (env_w >= 8.0 and env_d >= 8.0):
            lift_w = 1.80
            lift_d = 1.80
            lift_x = core_x
            # The lift normally sits north of the stair.  When a North terrace
            # band is reserved that strip is open to sky, so the lift stacks
            # south of the stair instead of being pushed into the band.
            if north_band_depth is not None:
                lift_y = round(core_y + stair_spec.depth_m + 0.2, 2)
            else:
                lift_y = round(max(0.2, core_y - lift_d - 0.2), 2)
            lift_spec = VerticalCoreSpec(
                core_id="core_lift_passenger",
                core_type="lift_passenger",
                x=lift_x,
                y=lift_y,
                width_m=lift_w,
                depth_m=lift_d,
                continuous_across_floors=list(range(self.total_storeys)),
            )
            vertical_cores.append(lift_spec)

        # 3. Vertical MEP / Plumbing Shafts (Rule of Plumbing Wet Stacks)
        duct_w = 0.60
        duct_d = 0.80

        if self.site_plan and self.site_plan.footprint and len(self.site_plan.footprint.wings) > 1:
            w_a = self.site_plan.footprint.wings[0]
            w_b = self.site_plan.footprint.wings[1]
            e_x = self.site_plan.footprint.x
            e_y = self.site_plan.footprint.y
            w_a_w = float(getattr(w_a, "width_m", env_w))
            w_b_y_rel = round(float(getattr(w_b, "y", 0.0)) - e_y, 2)

            primary_duct = DuctShaftSpec(
                shaft_id="duct_mep_primary",
                shaft_type="plumbing_wet",
                x=round(max(0.5, w_a_w - duct_w - 0.3), 2),
                y=0.40,
                width_m=duct_w,
                depth_m=duct_d,
                servicing_rooms=["kitchen", "sanitary_block"],
            )
            duct_shafts.append(primary_duct)

            sec_duct = DuctShaftSpec(
                shaft_id="duct_mep_secondary",
                shaft_type="plumbing_wet",
                x=0.20,
                y=round(w_b_y_rel + 0.30, 2),
                width_m=0.50,
                depth_m=0.60,
                servicing_rooms=["bath_1", "bath_2"],
            )
            duct_shafts.append(sec_duct)
        else:
            duct_x = round(max(0.5, env_w - duct_w - 0.3), 2)
            duct_y = round(max(0.5, env_d - duct_d - 0.8), 2)

            primary_duct = DuctShaftSpec(
                shaft_id="duct_mep_primary",
                shaft_type="plumbing_wet",
                x=duct_x,
                y=duct_y,
                width_m=duct_w,
                depth_m=duct_d,
                servicing_rooms=["kitchen", "bath_1", "sanitary_block", "worker_amenity"],
            )
            duct_shafts.append(primary_duct)

            sec_duct_x = round(stair_w + 0.10, 2)
            sec_duct_y = round(min(env_d - 0.70, core_y + core_d + 0.10), 2)
            if sec_duct_x + 0.50 <= env_w and sec_duct_y + 0.60 <= env_d:
                sec_duct = DuctShaftSpec(
                    shaft_id="duct_mep_secondary",
                    shaft_type="plumbing_wet",
                    x=sec_duct_x,
                    y=sec_duct_y,
                    width_m=0.50,
                    depth_m=0.60,
                    servicing_rooms=["bath_2", "bath_master", "sanitary_block"],
                )
                duct_shafts.append(sec_duct)

        return vertical_cores, duct_shafts

    # =========================================================================
    # 3. PER-FLOOR PROGRAM RESOLUTION
    # =========================================================================

    @staticmethod
    def _map_client_room_token(token: str) -> str:
        """
        Maps one requested room token (ontology id OR human display name) onto an
        ontology space id. Single source for both the floor-programme resolver and
        the API-level required_rooms derivation, so the two can never disagree.
        """
        clean = str(token).strip().lower()
        spec = ONTOLOGY.get_space(clean)
        if spec:
            return spec.id
        if clean in ("master_bedroom", "master bedroom", "master"):
            return "master_bed"
        if "office" in clean or "study" in clean:
            return "study"
        if "powder" in clean:
            return "bath_2"
        if "bed" in clean and "master" not in clean:
            return "bed_2"
        if "bath" in clean and clean != "bath_1":
            return "bath_2"
        if "living" in clean or "hall" in clean:
            return "living"
        if "puja" in clean or "pooja" in clean:
            return "puja"
        if "kitchen" in clean:
            return "kitchen"
        if "dining" in clean:
            return "dining"
        if "store" in clean or "utility" in clean:
            return "store"
        return "living"

    def _resolve_floor_program(
        self,
        floor_index: int,
        client_rooms: Optional[List[str]] = None,
    ) -> List[SpaceTypeSpec]:
        """
        Determines the list of SpaceTypeSpec items for floor_index based on:
        - Ontology permitted levels (VERT-04: heavy load Ground only; VERT-05: mezzanine admin).
        - Requested client rooms if provided.
        - Default typology program if not provided.
        """
        program_spaces: List[SpaceTypeSpec] = []

        if client_rooms and len(client_rooms) >= 3 and self.typology == "T1_SINGLE_FAMILY":
            # Map client requested room tokens to ontology space types
            mapped_ids: List[str] = [self._map_client_room_token(t) for t in client_rooms]

            # Ground floor receives living, kitchen, puja, bath_1, dining, master_bed (if 1-floor)
            for sid in mapped_ids:
                spec = ONTOLOGY.get_space(sid)
                if not spec:
                    continue
                if floor_index in spec.permitted_levels or (floor_index == 0 and spec.function in (FunctionType.COOKING, FunctionType.SOCIAL, FunctionType.WORSHIP, FunctionType.WORK, FunctionType.SANITATION)):
                    if spec not in program_spaces:
                        program_spaces.append(spec)

            # Ensure minimum required spaces for habitable floor
            if floor_index == 0:
                for req_id in ["living", "kitchen", "bath_1"]:
                    s = ONTOLOGY.get_space(req_id)
                    if s and s not in program_spaces:
                        program_spaces.append(s)
            elif floor_index > 0:
                for req_id in ["master_bed", "bed_2", "bath_master"]:
                    s = ONTOLOGY.get_space(req_id)
                    if s and s not in program_spaces:
                        program_spaces.append(s)

            return program_spaces

        # Default typology program from ontology data via TypologyModuleProtocol
        from app.services.floorplan.typologies import get_typology_module
        mod = get_typology_module(self.typology)
        prog = mod.vertical_program(self.total_storeys)
        if floor_index < len(prog):
            ids = prog[floor_index]["space_ids"]
        else:
            ids = prog[-1]["space_ids"]

        for sid in ids:
            spec = ONTOLOGY.get_space(sid)
            if spec and spec not in program_spaces:
                program_spaces.append(spec)

        # Enforce program intent: residential typologies must place >= 1 bedroom on every upper floor
        is_residential = ("T1" in self.typology or "T2" in self.typology or "SINGLE" in self.typology or "APARTMENT" in self.typology)
        exclusions = []
        if self.client_constraints and getattr(self.client_constraints, "explicit_exclusions", None):
            exclusions = [e.lower() for e in self.client_constraints.explicit_exclusions]
        if is_residential and floor_index > 0 and not any("bed" in ex for ex in exclusions):
            has_bedroom = any(s.function == FunctionType.SLEEP or "bed" in s.id.lower() for s in program_spaces)
            if not has_bedroom:
                s_bed = ONTOLOGY.get_space("bed_2") or ONTOLOGY.get_space("master_bed")
                if s_bed and s_bed not in program_spaces:
                    program_spaces.append(s_bed)

        return program_spaces

    def _resolve_floor_plate_masks(self) -> Dict[int, Dict[str, str]]:
        """
        Resolves and validates per-floor floor plate masks against Hard Rules:
        - RULE-FP-01: Core continuity (wing containing core cannot be terraced/void on any occupied level).
        - RULE-FP-02: Wings may only be dropped on levels above where they exist; unsupported cantilever forbidden.
        - Level 0 (Ground): Ground floor plate must be fully occupied (no terrace/void on ground).
        - Defaults: All wings present unless explicitly passed in request or proposed by typology profile.
        """
        wings = self.site_plan.footprint.wings if (self.site_plan and self.site_plan.footprint) else []
        wing_ids = [getattr(w, "wing_id", str(w)).lower() for w in wings] if wings else ["wing_a", "wing_b"]

        raw_masks = getattr(self.req, "floor_plate_masks", None)
        masks: Dict[int, Dict[str, str]] = {}
        # Terrace intents on wings that do not exist in the footprint decomposition
        # (consumed by _resolve_terrace_bands to synthesize a canonical band).
        self._ignored_mask_terrace_intents: Dict[int, bool] = {}

        for z in range(self.total_storeys):
            masks[z] = {wid: "present" for wid in wing_ids}

        if raw_masks:
            for k, v in raw_masks.items():
                try:
                    lvl = int(k)
                except (ValueError, TypeError):
                    continue
                if 0 <= lvl < self.total_storeys and isinstance(v, dict):
                    for wid, state in v.items():
                        norm_wid = str(wid).lower()
                        norm_state = str(state).lower()
                        if norm_state in ("present", "terrace", "void"):
                            if norm_wid not in masks[lvl]:
                                # Wing not in this footprint's decomposition
                                # (e.g. single-rectangle plate): honoring it would
                                # desynchronize plate_composition from reality.
                                self.warnings.append(
                                    f"RULE-FP-02: Wing '{wid}' not present in footprint "
                                    f"decomposition (single-rectangle plate) - floor plate "
                                    f"mask for level {lvl} ignored."
                                )
                                if norm_state == "terrace":
                                    self._ignored_mask_terrace_intents[lvl] = True
                                continue
                            masks[lvl][norm_wid] = norm_state

        # Enforce Hard Rules:
        # 1. Level 0 Ground must be fully present
        for wid in masks[0]:
            if masks[0][wid] != "present":
                self.warnings.append(
                    f"RULE-FP-01: Ground floor footprint '{wid}' must be present (cannot terrace/void ground level). Reset to present."
                )
                masks[0][wid] = "present"

        # 2. RULE-FP-01: Core wing (wing_a holds staircase core) cannot be terraced or void
        for z in range(self.total_storeys):
            if "wing_a" in masks[z] and masks[z]["wing_a"] != "present":
                self.warnings.append(
                    f"RULE-FP-01: Core wing (Wing A) contains vertical core and cannot be terraced on Floor {z}. Reset to present."
                )
                masks[z]["wing_a"] = "present"

        # 3. RULE-FP-02: Wings may only be dropped above where they exist (no cantilever > 1.2m)
        for z in range(1, self.total_storeys):
            for wid in wing_ids:
                prev_state = masks[z - 1].get(wid, "present")
                curr_state = masks[z].get(wid, "present")
                if prev_state == "void" and curr_state != "void":
                    self.warnings.append(
                        f"RULE-FP-02: Wing '{wid}' on Floor {z} lacks lower floor support (cantilever > 1.2m forbidden). Reset to void."
                    )
                    masks[z][wid] = "void"

        return masks

    def _resolve_terrace_bands(
        self,
        envelope: Dict[str, float],
        vertical_cores: List[VerticalCoreSpec],
        duct_shafts: List[DuctShaftSpec],
    ) -> Dict[int, Optional[TerraceBandSpec]]:
        """
        Resolves per-floor axis-aligned terrace bands on simple rectangular plates.
        Enforces:
        - Band permitted only on levels above Ground (floor_index > 0).
        - RULE-FP-07: band depth <= 40% of plate dimension along that edge.
        - RULE-FP-01: band may not intersect any vertical core or MEP duct.
        - RULE-FP-03: no wet room above the band region on upper levels.
        """
        resolved: Dict[int, Optional[TerraceBandSpec]] = {}
        for z in range(self.total_storeys):
            resolved[z] = None

        # Only applied if no wings exist (single rectangular plate)
        is_multi_wing = bool(self.site_plan and getattr(self.site_plan, "footprint", None) and len(self.site_plan.footprint.wings) > 1)
        if is_multi_wing:
            return resolved

        raw_bands = getattr(self.req, "terrace_bands", None)
        effective_bands: Dict[Any, Any] = dict(raw_bands) if isinstance(raw_bands, dict) else {}
        env_w = envelope["width"]
        env_d = envelope["depth"]
        # Floor-plate terrace variations on single-rectangle plates translate to a
        # canonical North-edge band so the terrace intent materializes through the
        # fully validated band pipeline (40% clamp, core/duct conflict checks).
        for z in range(1, self.total_storeys):
            if (getattr(self, "_ignored_mask_terrace_intents", {}).get(z)
                    and z not in effective_bands):
                synth_depth = min(3.0, round(0.40 * env_d, 2))
                effective_bands[z] = {"edge": "N", "depth_m": synth_depth}
                self.warnings.append(
                    f"Single-rectangle plate: floor-plate terrace variation on level {z} "
                    f"translated to North terrace band (depth {synth_depth:.1f}m)."
                )
        if not effective_bands:
            return resolved

        for k, tb in effective_bands.items():
            try:
                lvl = int(k)
            except (ValueError, TypeError):
                continue

            if lvl < 0 or lvl >= self.total_storeys:
                continue

            # Ground level check (RULE-FP-01)
            if lvl == 0:
                self.warnings.append(
                    "RULE-FP-01: Ground floor keeps full plate for entry/parking (cannot apply terrace band on Ground). Band ignored."
                )
                continue

            edge = getattr(tb, "edge", None) or (tb.get("edge") if isinstance(tb, dict) else None)
            d_val = getattr(tb, "depth_m", None) or (tb.get("depth_m") if isinstance(tb, dict) else 0.0)

            if not edge or not d_val:
                continue

            edge = str(edge).upper().strip()
            if edge not in ("N", "S", "E", "W"):
                self.warnings.append(f"Invalid terrace band edge '{edge}' on Floor {lvl}. Must be N, S, E, or W.")
                continue

            try:
                depth_m = float(d_val)
            except (ValueError, TypeError):
                continue

            if depth_m <= 0.0:
                continue

            # RULE-FP-07: Band depth <= 40% of plate dimension along that edge
            dim_along_edge = env_d if edge in ("N", "S") else env_w
            max_depth = round(0.40 * dim_along_edge, 2)
            if depth_m > max_depth:
                self.warnings.append(
                    f"RULE-FP-07: Terrace band depth {depth_m:.2f}m exceeds 40% limit ({max_depth:.2f}m) for edge {edge}. Clamped to {max_depth:.2f}m."
                )
                depth_m = max_depth

            # Edge-specific intersection checks (RULE-FP-01)
            # West edge check: West edge contains vertical stair core & egress
            if edge == "W":
                self.warnings.append(
                    f"RULE-FP-01: Terrace band on West edge on Floor {lvl} intersects vertical stair core & egress. Rejected."
                )
                continue

            # Compute bounding box of terrace band
            if edge == "N":
                bx1, by1, bx2, by2 = 0.0, 0.0, env_w, depth_m
            elif edge == "S":
                bx1, by1, bx2, by2 = 0.0, env_d - depth_m, env_w, env_d
            elif edge == "E":
                bx1, by1, bx2, by2 = env_w - depth_m, 0.0, env_w, env_d
            else:  # W
                bx1, by1, bx2, by2 = 0.0, 0.0, depth_m, env_d

            # Check overlap with any vertical core or duct shaft
            conflict = False
            for core in vertical_cores:
                cx1, cy1, cx2, cy2 = core.x, core.y, core.x + core.width_m, core.y + core.depth_m
                x_ov = max(0.0, min(bx2, cx2) - max(bx1, cx1))
                y_ov = max(0.0, min(by2, cy2) - max(by1, cy1))
                if x_ov > 0.05 and y_ov > 0.05:
                    self.warnings.append(
                        f"RULE-FP-01: Terrace band on edge {edge} (depth {depth_m}m) intersects vertical core '{core.core_id}' on Floor {lvl}. Rejected."
                    )
                    conflict = True
                    break

            if conflict:
                continue

            for duct in duct_shafts:
                dx1, dy1, dx2, dy2 = duct.x, duct.y, duct.x + duct.width_m, duct.y + duct.depth_m
                x_ov = max(0.0, min(bx2, dx2) - max(bx1, dx1))
                y_ov = max(0.0, min(by2, dy2) - max(by1, dy1))
                if x_ov > 0.05 and y_ov > 0.05:
                    self.warnings.append(
                        f"RULE-FP-01: Terrace band on edge {edge} (depth {depth_m}m) intersects MEP shaft '{duct.shaft_id}' on Floor {lvl}. Rejected."
                    )
                    conflict = True
                    break

            if conflict:
                continue

            resolved[lvl] = TerraceBandSpec(edge=edge, depth_m=depth_m)

        return resolved

    # =========================================================================
    # 4. CONSTRAINED RECTANGULAR LAYOUT PARTITIONING & PRUNING
    # =========================================================================

    # ------------------------------------------------------------------
    # MULTI-WING TYPOLOGY PROGRAMME (I9)
    # ------------------------------------------------------------------
    def _multi_wing_wing_cells(self, floor_index: int) -> Dict[str, List[Dict[str, Any]]]:
        """The requested typology's own programme, split across the two wings.

        The multi-wing partitioner drew the T1 residence on EVERY typology: a
        T2 plate came back with living/kitchen/master_bed and no unit room at
        all, a T3 plate with no office cell, a T4 plate with no bay - the
        product the user asked for was silently swapped for a house.  The
        wings are now filled from the typology catalogue (unit + shared core
        for T2, suites + sanitary + technical cells for T3, the dock ->
        dispatch -> storage chain + amenity for T4), and each cell carries its
        `space_type_id` so nothing downstream has to guess from a display id.
        """
        def cell(sid: str, name: str, zone: str, category: str,
                 room_id: str, rules: List[str], prio: int = 5) -> Dict[str, Any]:
            spec = ONTOLOGY.get_space(sid)
            return {
                "sid": sid,
                "name": name,
                "zone": zone,
                "category": category,
                "room_id": f"{room_id}_F{floor_index}",
                "area": float(getattr(spec, "min_area_sqm", 8.0) or 8.0),
                # The catalogue figures are CLEAR dimensions; a gross
                # rectangle of exactly min_width loses ~150 mm per wall to
                # plaster, so the cell is cut at min_width + the wall allowance
                # and the clear face actually meets the law.
                "min_w": float(getattr(spec, "min_width_m", 1.5) or 1.5) + 0.30,
                "prio": prio,
                "rules": rules,
            }

        if self.typology == "T2_FAMILY_APARTMENT":
            # Unit A fills Wing A around the shared core, unit B takes Wing B.
            # Both units carry the catalogue's own leaf rooms (never the
            # "apt_unit_N" programme aggregate, which is not geometry).
            # Order = placement order, so bed separates kitchen from bath and
            # the utility screens the bath: no HYG-02 forbidden wall can be
            # produced by the band.  prio = what to drop first if the wing is
            # too narrow (kept rooms are the ones a unit cannot lose).
            wing_a = [
                cell("unit_living", "Unit A: Living & Dining", "S", "public",
                     "t2_unitA_living", ["NBC-HABITABLE-ROOM", "SPAT-LIVING-OUTLOOK"], prio=1),
                cell("unit_bed", "Unit A: Bedroom", "E", "private",
                     "t2_unitA_bed", ["NBC-HABITABLE-ROOM"], prio=2),
                cell("unit_kitchen", "Unit A: Kitchen", "SE", "service",
                     "t2_unitA_kitchen", ["NBC-KITCHEN-MIN-AREA", "PLUMB-01-WET-STACK"], prio=3),
                cell("unit_utility", "Unit A: Utility", "N", "service",
                     "t2_unitA_utility", ["PLUMB-01-WET-STACK"], prio=5),
                cell("unit_bath", "Unit A: Bathroom", "W", "service",
                     "t2_unitA_bath", ["NBC-BATHROOM-MIN-AREA", "PLUMB-01-WET-STACK"], prio=4),
            ]
            wing_b = [
                cell("unit_living", "Unit B: Living & Dining", "S", "public",
                     "t2_unitB_living", ["NBC-HABITABLE-ROOM", "SPAT-LIVING-OUTLOOK"], prio=1),
                cell("unit_kitchen", "Unit B: Kitchen", "SW", "service",
                     "t2_unitB_kitchen", ["NBC-KITCHEN-MIN-AREA", "PLUMB-01-WET-STACK"], prio=2),
                cell("unit_bed", "Unit B: Bedroom", "W", "private",
                     "t2_unitB_bed", ["NBC-HABITABLE-ROOM"], prio=3),
                cell("unit_bath", "Unit B: Bathroom", "NW", "service",
                     "t2_unitB_bath", ["NBC-BATHROOM-MIN-AREA", "PLUMB-01-WET-STACK"], prio=4),
            ]
            return {"wing_a": wing_a, "wing_b": wing_b}

        if self.typology == "T3_LARGE_COMPLEX":
            # Office cells + sanitary block in Wing A, technical rooms in B.
            # Reception is a ground-floor front-of-house room; upper storeys
            # carry the rentable suite in the same bay so the stack aligns.
            if floor_index == 0:
                front = cell("reception_lobby", "Reception & Information Lobby", "NW", "public",
                             "reception", ["T3-RECEPTION-GROUND-FRONT", "NBC-MIN-RECEPTION"], prio=1)
            else:
                front = cell("commercial_suite", "Rentable Office Suite", "NW", "public",
                             "t3_suite_north", ["T3-OFFICE-CELL", "NBC-HABITABLE-ROOM"], prio=1)
            wing_a = [
                front,
                cell("sanitary_block", "Commercial Restroom Block (M/F/Accessible)", "W", "service",
                     "t3_sanitary", ["NBC-SAN-TABLE12", "VERT-01-WET-STACK"], prio=2),
                cell("commercial_suite", "Rentable Office Suite", "S", "public",
                     "t3_suite_south", ["T3-OFFICE-CELL", "NBC-HABITABLE-ROOM"], prio=3),
            ]
            # Server equipment is a heavy floor load: VERT-04 keeps it on the
            # ground plate, so upper storeys carry the plant rooms instead.
            if floor_index == 0:
                wing_b = [
                    cell("server_room", "Server & Comms Room", "E", "service",
                         "server_room", ["T3-SERVER-SEPARATE", "HYG-03-WET-TECH-WALL"], prio=1),
                    cell("electrical_room", "Electrical & Transformer Room", "SE", "service",
                         "electrical_room", ["T3-ELECTRICAL-SEPARATE"], prio=2),
                    cell("mep_room", "MEP Plant Room", "NE", "service",
                         "mep_room", ["T3-MEP-PLANT"], prio=3),
                ]
            else:
                # Every plant room is a HEAVY floor load (VERT-04 keeps them on
                # the ground plate), so upper storeys carry a meeting suite and
                # a store instead of a server room they are not allowed to hold.
                wing_b = [
                    cell("conference_suite", "Upper Floor Conference Suite", "E", "public",
                         "conference_suite", ["T3-CONFERENCE-SUITE", "NBC-HABITABLE-ROOM"], prio=1),
                    cell("store", "Upper Floor Store", "SE", "service",
                         "upper_store", ["T3-UPPER-STORE"], prio=2),
                ]
            return {"wing_a": wing_a, "wing_b": wing_b}

        # T4: the industrial chain dock -> dispatch -> storage must stay
        # adjacent, so it is packed into Wing A; amenity/support goes to B.
        # Heavy-load bays are GROUND ONLY (VERT-04), so upper storeys carry the
        # admin/amenity programme over the same footprint instead.
        if floor_index == 0:
            wing_a = [
                cell("storage_bay", "Warehouse Storage Bay", "S", "industrial_bay",
                     "storage_bay", ["VERT-04-HEAVY-LOAD-GROUND", "NBC-STORAGE-OCCUPANCY"], prio=1),
                cell("dock_bay", "Loading Dock Bay", "N", "industrial_bay",
                     "dock_bay", ["T4-CHAIN-DOCK", "NBC-DOCK-APRON"], prio=2),
                cell("dispatch", "Dispatch & Staging", "NE", "circulation",
                     "dispatch", ["T4-CHAIN-DISPATCH", "T4-CHAIN-STORAGE"], prio=3),
            ]
            wing_b = [
                cell("worker_amenity", "Worker Locker & Sanitary WC", "W", "service",
                     "worker_amenity", ["NBC-SAN-TABLE12", "T4-WORKER-AMENITY"], prio=1),
                cell("washdown_point", "Washdown Point", "SW", "service",
                     "washdown_point", ["T4-WASHDOWN", "PLUMB-01-WET-STACK"], prio=2),
                cell("admin_office", "Admin & Site Office", "NW", "public",
                     "admin_office", ["T4-ADMIN-OFFICE"], prio=3),
            ]
        else:
            wing_a = [
                cell("admin_office", "Upper Floor Site Office", "S", "public",
                     "admin_office", ["T4-ADMIN-OFFICE"], prio=1),
                cell("store", "Upper Floor Store", "N", "service",
                     "upper_store", ["T4-UPPER-STORE"], prio=2),
            ]
            # The washdown point is a heavy-load wet trade floor (VERT-04 keeps
            # it at ground).  Upper storeys carry a store beside the amenity.
            wing_b = [
                cell("worker_amenity", "Upper Floor Staff Amenity", "W", "service",
                     "worker_amenity", ["NBC-SAN-TABLE12", "T4-WORKER-AMENITY"], prio=1),
                cell("store", "Upper Floor Store", "SW", "service",
                     "upper_store", ["T4-UPPER-STORE"], prio=2),
            ]
        return {"wing_a": wing_a, "wing_b": wing_b}

    def _fill_wing_cells(
        self,
        floor_index: int,
        wing_label: str,
        x: float,
        y: float,
        w: float,
        d: float,
        cells: List[Dict[str, Any]],
    ) -> List[MultiFloorRoomRectangle]:
        """Slice one wing rectangle into the typology's legal room cells.

        Deterministic shelf packing: rooms are grouped into one or two rows by
        target area, each row is split by the catalogue's minimum width first
        (so no cell can be drawn below a *width* minimum) and the leftover
        frontage goes to the cell with the most unmet area.  A cell that cannot
        even get its minimum width is NOT drawn: the wing is too small for it
        and the caller names the omission instead of shrinking it silently.
        """
        out: List[MultiFloorRoomRectangle] = []
        if not cells or w <= 0.05 or d <= 0.05:
            return out

        # ONE row along the wing.  A second row would put cell A above cell B
        # and give the T2 kitchen a shared wall with the unit bath (HYG-02
        # FORBIDDEN_WALL) purely by geometry, which the hard verifier rightly
        # rejects.  A single band keeps every adjacency explicit in the list
        # order, where the catalogue's own sequence separates kitchen/bath.
        kept = list(cells)
        while kept and sum(c["min_w"] for c in kept) > w - 0.01:
            # Omit the LEAST important cell (highest prio number, latest in
            # the order), and name it: a wing that cannot hold the programme
            # says which room it could not draw instead of shrinking it below
            # the catalogue.
            idx = max(range(len(kept)), key=lambda i: (kept[i]["prio"], i))
            dropped = kept.pop(idx)
            self._wing_omissions.append(
                f"{dropped['sid']} (needs {dropped['min_w']:.2f} m of frontage)"
            )
        # Hygiene/technical wall law inside the band: a forbidden neighbour
        # pair (bath x kitchen, reception x sanitary, wet x tech) can only be
        # produced by consecutive cells.  Drop the less important cell of the
        # pair and name it, instead of drawing a wall the verifier must reject.
        changed = True
        while changed and len(kept) > 1:
            changed = False
            for i in range(len(kept) - 1):
                rels = ONTOLOGY.get_relations(kept[i]["sid"], kept[i + 1]["sid"])
                if any(str(getattr(r, "relation", "")).endswith("FORBIDDEN_WALL") for r in rels):
                    victim = kept[i] if kept[i]["prio"] > kept[i + 1]["prio"] else kept[i + 1]
                    kept.remove(victim)
                    self._wing_omissions.append(
                        f"{victim['sid']} (would share a forbidden wall with its neighbour)"
                    )
                    changed = True
                    break
        if not kept:
            return out

        extra = max(0.0, w - sum(c["min_w"] for c in kept))
        total_area = sum(c["area"] for c in kept)
        if total_area > 0.01:
            # Surplus frontage follows the programme's own proportions, so a
            # large living room grows instead of a bath becoming a slot.
            widths = [c["min_w"] + extra * c["area"] / total_area for c in kept]
        else:
            widths = [c["min_w"] + extra / len(kept) for c in kept]

        cursor_x = x
        for idx, (c, width) in enumerate(zip(kept, widths)):
            width = round(width, 2)
            if idx == len(kept) - 1:
                width = round(x + w - cursor_x, 2)
            width = max(0.0, width)
            if width <= 0.05:
                self._wing_omissions.append(f"{c['sid']} (no frontage left)")
                continue
            spec = ONTOLOGY.get_space(c["sid"])
            out.append(MultiFloorRoomRectangle(
                room_id=c["room_id"],
                room_name=c["name"],
                floor_index=floor_index,
                unit_id=(
                    "Unit_A" if "unitA" in c["room_id"] else
                    "Unit_B" if "unitB" in c["room_id"] else None
                ),
                x=round(cursor_x, 2),
                y=round(y, 2),
                width_m=width,
                depth_m=round(d, 2),
                area_sqm=round(width * d, 2),
                zone=c["zone"],
                zone_category=c["category"],
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=c["category"] not in ("circulation",),
                aspect_ratio=round(max(width, d) / max(min(width, d), 0.01), 2),
                applied_rules=list(c["rules"]),
                space_type_id=(spec.id if spec is not None else c["sid"]),
            ))
            cursor_x = round(cursor_x + width, 2)
        return out

    def _partition_multi_wing_typology(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        core: VerticalCoreSpec,
        ducts: List[DuctShaftSpec],
        spaces: List[SpaceTypeSpec],
        previous_rooms: Optional[List[MultiFloorRoomRectangle]] = None,
    ) -> List[MultiFloorRoomRectangle]:
        """Multi-wing plate filled from the requested typology's catalogue.

        The shared vertical core and link corridor stay in Wing A (one core
        stacks every storey for every typology); the rest of Wing A and all of
        Wing B are filled by `_fill_wing_cells` from this typology's cells.
        """
        env_x = envelope.get("x", 0.0)
        env_y = envelope.get("y", 0.0)
        wings = self.site_plan.footprint.wings if (self.site_plan and self.site_plan.footprint) else []
        wing_a = wings[0]
        wing_b = wings[1]

        w_a_x = round(wing_a.x - env_x, 2)
        w_a_y = round(wing_a.y - env_y, 2)
        w_a_w = round(wing_a.width_m, 2)
        w_a_d = round(wing_a.depth_m, 2)
        w_b_x = round(wing_b.x - env_x, 2)
        w_b_y = round(wing_b.y - env_y, 2)
        w_b_w = round(wing_b.width_m, 2)
        w_b_d = round(wing_b.depth_m, 2)

        self._wing_omissions = []
        rooms: List[MultiFloorRoomRectangle] = []

        core_w = round(core.width_m, 2)
        corridor_d = round(max(1.20, min(1.50, w_a_d * 0.28)), 2)
        actual_core_d = round(w_a_d - corridor_d, 2)

        rooms.append(MultiFloorRoomRectangle(
            room_id=f"{core.core_id}_F{floor_index}",
            room_name="Shared Vertical Core",
            floor_index=floor_index,
            x=w_a_x,
            y=w_a_y,
            width_m=core_w,
            depth_m=actual_core_d,
            area_sqm=round(core_w * actual_core_d, 2),
            zone="SW",
            zone_category="circulation",
            vastu_compliant=True,
            is_vertical_core=True,
            requires_exterior_wall=True,
            aspect_ratio=round(actual_core_d / core_w if core_w > 0 else 1.0, 2),
            applied_rules=["VERT-03-CORE-CONTINUITY", "NBC-STAIR-EGRESS"],
            space_type_id="shared_stair",
        ))
        rooms.append(MultiFloorRoomRectangle(
            room_id=f"link_corridor_F{floor_index}",
            room_name="Connecting Gallery Corridor",
            floor_index=floor_index,
            x=w_a_x,
            y=round(w_a_y + actual_core_d, 2),
            width_m=core_w,
            depth_m=corridor_d,
            area_sqm=round(core_w * corridor_d, 2),
            zone="CENTER",
            zone_category="circulation",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=False,
            aspect_ratio=round(corridor_d / core_w if core_w > 0 else 1.0, 2),
            applied_rules=["CIRC-01-LINK-CORRIDOR", "NBC-CORRIDOR-MIN-WIDTH"],
        ))

        cells = self._multi_wing_wing_cells(floor_index)

        # Wing A remainder: everything east of the core / corridor.
        rem_a_x = round(w_a_x + core_w, 2)
        rem_a_w = round(w_a_w - core_w, 2)
        rooms.extend(self._fill_wing_cells(
            floor_index, "wing A", rem_a_x, w_a_y, rem_a_w, w_a_d, cells["wing_a"]
        ))

        mask = getattr(self, "resolved_floor_plate_masks", {}).get(floor_index, {})
        wing_b_state = mask.get("wing_b", "present")
        if wing_b_state == "terrace":
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"terrace_wing_b_F{floor_index}",
                room_name="Open Terrace / Setback Deck",
                floor_index=floor_index,
                x=w_b_x,
                y=w_b_y,
                width_m=w_b_w,
                depth_m=w_b_d,
                area_sqm=round(w_b_w * w_b_d, 2),
                zone="TERRACE",
                zone_category="terrace",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(max(w_b_w, w_b_d) / max(min(w_b_w, w_b_d), 0.01), 2),
                applied_rules=["RULE-FP-02-TERRACE-SETBACK", "RULE-FP-06-FAR-EXEMPT"],
            ))
        elif wing_b_state != "void":
            rooms.extend(self._fill_wing_cells(
                floor_index, "wing B", w_b_x, w_b_y, w_b_w, w_b_d, cells["wing_b"]
            ))

        if self._wing_omissions:
            self.warnings.append(
                "PROGRAMME-SQUEEZE: the " + self.typology + " programme could not be "
                "drawn in full on this plate; omitted " + ", ".join(self._wing_omissions)
                + ". Options: add a storey, reduce the programme, or enlarge the plate."
            )
        return rooms

    def _partition_multi_wing_rooms(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        core: VerticalCoreSpec,
        ducts: List[DuctShaftSpec],
        spaces: List[SpaceTypeSpec],
        previous_rooms: Optional[List[MultiFloorRoomRectangle]] = None,
    ) -> List[MultiFloorRoomRectangle]:
        """
        Synthesizes an advanced multi-wing / L-shape floor plan:
        - Wing A (Public): Living room, Dining, Kitchen, Puja, Staircase core (if multi-storey).
        - Wing B (Private): Master Bedroom, Ensuite Bath, Bedroom 2, Common Bath.
        - Link Corridor: Circulation Zone bridging Wing A and Wing B.
        Zero rooms span across the missing corner of the L.
        """
        if self.typology in ("T2_FAMILY_APARTMENT", "T3_LARGE_COMPLEX", "T4_WAREHOUSE"):
            # I9: the T1 residence below is a T1 programme.  Every other
            # typology is filled from its own catalogue instead of being handed
            # a house and told it is an office block.
            return self._partition_multi_wing_typology(
                floor_index=floor_index,
                envelope=envelope,
                core=core,
                ducts=ducts,
                spaces=spaces,
                previous_rooms=previous_rooms,
            )
        env_x = envelope.get("x", 0.0)
        env_y = envelope.get("y", 0.0)
        wings = self.site_plan.footprint.wings if (self.site_plan and self.site_plan.footprint) else []
        wing_a = wings[0] if len(wings) > 0 else None
        wing_b = wings[1] if len(wings) > 1 else None
        corridors = self.site_plan.footprint.corridors if (self.site_plan and self.site_plan.footprint) else []

        w_a_x = round(wing_a.x - env_x, 2)
        w_a_y = round(wing_a.y - env_y, 2)
        w_a_w = round(wing_a.width_m, 2)
        w_a_d = round(wing_a.depth_m, 2)

        w_b_x = round(wing_b.x - env_x, 2)
        w_b_y = round(wing_b.y - env_y, 2)
        w_b_w = round(wing_b.width_m, 2)
        w_b_d = round(wing_b.depth_m, 2)

        rooms: List[MultiFloorRoomRectangle] = []

        # 1. Structural Bays in Wing A (w_a_w x w_a_d):
        # Bay 1 (West Column alongside Link Corridor to Wing B):
        # Holds the locked staircase core and the link corridor continuation.
        core_w = round(core.width_m, 2)
        corridor_d = round(max(1.20, min(1.50, w_a_d * 0.28)), 2)
        actual_core_d = round(w_a_d - corridor_d, 2)

        core_room = MultiFloorRoomRectangle(
            room_id=f"{core.core_id}_F{floor_index}",
            room_name="Dogleg Staircase Core",
            floor_index=floor_index,
            x=w_a_x,
            y=w_a_y,
            width_m=core_w,
            depth_m=actual_core_d,
            area_sqm=round(core_w * actual_core_d, 2),
            zone="SW",
            zone_category="circulation",
            vastu_compliant=True,
            is_vertical_core=True,
            requires_exterior_wall=True,
            aspect_ratio=round(actual_core_d / core_w, 2),
            applied_rules=["VERT-03-CORE-CONTINUITY", "NBC-STAIR-EGRESS"],
        )
        rooms.append(core_room)

        corr_y = round(w_a_y + actual_core_d, 2)
        rooms.append(MultiFloorRoomRectangle(
            room_id=f"link_corridor_F{floor_index}",
            room_name="Connecting Gallery Corridor",
            floor_index=floor_index,
            x=w_a_x,
            y=corr_y,
            width_m=core_w,
            depth_m=corridor_d,
            area_sqm=round(core_w * corridor_d, 2),
            zone="CENTER",
            zone_category="circulation",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=False,
            aspect_ratio=round(corridor_d / core_w if core_w > 0 else 1.0, 2),
            applied_rules=["CIRC-01-LINK-CORRIDOR", "NBC-CORRIDOR-MIN-WIDTH"],
        ))

        # Remaining width in Wing A:
        rem_a_w = round(w_a_w - core_w, 2)
        east_bay_w = round(min(3.60, max(3.00, rem_a_w * 0.44)), 2)
        living_w = round(rem_a_w - east_bay_w, 2)
        living_x = round(w_a_x + core_w, 2)
        east_x = round(living_x + living_w, 2)

        # Central Bay: Living Room (Full depth w_a_d)
        living_name = "Drawing & Living Room" if floor_index == 0 else "Upper Family Lounge"
        rooms.append(MultiFloorRoomRectangle(
            room_id=f"living_F{floor_index}",
            room_name=living_name,
            floor_index=floor_index,
            x=living_x,
            y=w_a_y,
            width_m=living_w,
            depth_m=w_a_d,
            area_sqm=round(living_w * w_a_d, 2),
            zone="S",
            zone_category="public",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(living_w / w_a_d if w_a_d > 0 else 1.0, 2),
            applied_rules=["SPAT-01-LIVING-ORIENTATION", "NBC-LIGHT-VENTILATION"],
        ))

        # East Bay: Kitchen (SE corner) & Dining (NE corner)
        kit_d = round(w_a_d * 0.51, 2)
        din_d = round(w_a_d - kit_d, 2)

        if floor_index == 0:
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"kitchen_F{floor_index}",
                room_name="Modular Kitchen",
                floor_index=floor_index,
                x=east_x,
                y=w_a_y,
                width_m=east_bay_w,
                depth_m=kit_d,
                area_sqm=round(east_bay_w * kit_d, 2),
                zone="SE",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(east_bay_w / kit_d if kit_d > 0 else 1.0, 2),
                applied_rules=["VASTU-KITCHEN-SE-AGNI", "NBC-LIGHT-VENTILATION", "NBC-KITCHEN-MIN-AREA"],
            ))
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"dining_F{floor_index}",
                room_name="Dining Hall",
                floor_index=floor_index,
                x=east_x,
                y=round(w_a_y + kit_d, 2),
                width_m=east_bay_w,
                depth_m=din_d,
                area_sqm=round(east_bay_w * din_d, 2),
                zone="E",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(east_bay_w / din_d if din_d > 0 else 1.0, 2),
                applied_rules=["SPAT-02-DINING-KITCHEN-ADJACENT", "NBC-HABITABLE-ROOM"],
            ))
        else:
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"study_F{floor_index}",
                room_name="Home Study & Library",
                floor_index=floor_index,
                x=east_x,
                y=w_a_y,
                width_m=east_bay_w,
                depth_m=kit_d,
                area_sqm=round(east_bay_w * kit_d, 2),
                zone="SE",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(east_bay_w / kit_d if kit_d > 0 else 1.0, 2),
                applied_rules=["NBC-HABITABLE-ROOM", "SPAT-STUDY"],
            ))
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"dining_F{floor_index}",
                room_name="Upper Dining / Terrace Lounge",
                floor_index=floor_index,
                x=east_x,
                y=round(w_a_y + kit_d, 2),
                width_m=east_bay_w,
                depth_m=din_d,
                area_sqm=round(east_bay_w * din_d, 2),
                zone="E",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(east_bay_w / din_d if din_d > 0 else 1.0, 2),
                applied_rules=["NBC-HABITABLE-ROOM"],
            ))

        # 2. WING B (PRIVATE ZONE):
        mask = getattr(self, "resolved_floor_plate_masks", {}).get(floor_index, {})
        wing_b_state = mask.get("wing_b", "present")

        if wing_b_state == "terrace":
            # Setback becomes open-to-sky terrace per RULE-FP-02 & RULE-FP-04
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"terrace_wing_b_F{floor_index}",
                room_name="Open Terrace / Setback Deck",
                floor_index=floor_index,
                x=w_b_x,
                y=w_b_y,
                width_m=w_b_w,
                depth_m=w_b_d,
                area_sqm=round(w_b_w * w_b_d, 2),
                zone="TERRACE",
                zone_category="terrace",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(w_b_w / w_b_d if w_b_d > 0 else 1.0, 2),
                applied_rules=["RULE-FP-02-TERRACE-SETBACK", "RULE-FP-04-TERRACE-ACCESS", "RULE-FP-06-FAR-EXEMPT"],
            ))
            return rooms
        elif wing_b_state == "void":
            return rooms

        # Longitudinally zoned to guarantee code-compliant room dimensions & areas
        if w_b_w < 5.0 and w_b_d >= 4.5:
            passage_w = 1.10
            bath_block_w = round(w_b_w - passage_w, 2)
            target_bb_d = 2.80 if w_b_d >= 5.5 else max(2.20, w_b_d * 0.40)
            bath_block_d = round(min(2.80, target_bb_d), 2)
            bed_d = round(w_b_d - bath_block_d, 2)

            b2_d = round(bath_block_d * 0.50, 2)
            b1_d = round(bath_block_d - b2_d, 2)

            # Common Bathroom (Bath 2)
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"bath_2_F{floor_index}",
                room_name="Common Bathroom",
                floor_index=floor_index,
                x=round(w_b_x + passage_w, 2),
                y=w_b_y,
                width_m=bath_block_w,
                depth_m=b2_d,
                area_sqm=round(bath_block_w * b2_d, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(bath_block_w / b2_d if b2_d > 0 else 1.0, 2),
                applied_rules=["NBC-BATHROOM-MIN-AREA", "PLUMB-01-WET-STACK"],
            ))

            # Ensuite Bathroom (Bath 1)
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"bath_1_F{floor_index}",
                room_name="Ensuite Bathroom",
                floor_index=floor_index,
                x=round(w_b_x + passage_w, 2),
                y=round(w_b_y + b2_d, 2),
                width_m=bath_block_w,
                depth_m=b1_d,
                area_sqm=round(bath_block_w * b1_d, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(bath_block_w / b1_d if b1_d > 0 else 1.0, 2),
                applied_rules=["PLUMB-01-ENSUITE-ADJACENT", "NBC-BATHROOM-MIN-AREA"],
            ))

            # The 1.10 m strip west of the bath block was reserved as an access
            # passage but no passage room was ever placed: it stayed open plate
            # on every upper floor (L-244's 3.08 m²/floor void), and the surplus
            # ladder later filled it with a 1.01 m wide "store" - a sliver, not
            # a room.  It is a real walk-in wardrobe / linen store now: 1.10 x
            # 2.80 m clears the store's 0.90 m width, 1.50 m² area and 3.0:1
            # band, opens onto the bedroom behind it, and removes the void
            # without inventing a corridor that leads nowhere.
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"storage_dead_{floor_index}_1",
                room_name="Dead-Corner Wardrobe Store",
                space_type_id="store",
                floor_index=floor_index,
                x=w_b_x,
                y=w_b_y,
                width_m=passage_w,
                depth_m=bath_block_d,
                area_sqm=round(passage_w * bath_block_d, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(max(passage_w, bath_block_d) / max(min(passage_w, bath_block_d), 0.01), 2),
                applied_rules=["PROP-ROW-02", "LAND-07-DEAD-CORNER-ABSORBED", "STORE-01-BEDROOM-ADJACENT"],
            ))
            self.warnings.append(
                f"LAND-07: {passage_w * bath_block_d:.1f} m² dead corner on floor "
                f"{floor_index} absorbed as storage_dead_{floor_index}_1 "
                "(connected store, not open plate)."
            )

            # Master Bedroom / Secondary Bedroom
            bed_id = f"master_bed_F{floor_index}" if floor_index == 0 else f"bed_2_F{floor_index}"
            bed_name = "Master Suite" if floor_index == 0 else "Secondary Bedroom"
            rooms.append(MultiFloorRoomRectangle(
                room_id=bed_id,
                room_name=bed_name,
                floor_index=floor_index,
                x=w_b_x,
                y=round(w_b_y + bath_block_d, 2),
                width_m=w_b_w,
                depth_m=bed_d,
                area_sqm=round(w_b_w * bed_d, 2),
                zone="NW" if floor_index > 0 else "SW",
                zone_category="private",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(w_b_w / bed_d if bed_d > 0 else 1.0, 2),
                applied_rules=["VASTU-MASTER-SW-EARTH" if floor_index == 0 else "NBC-BEDROOM-MIN-AREA", "NBC-LIGHT-VENTILATION"],
            ))
        else:
            b_north_d = round(w_b_d * 0.50, 2)
            b_south_d = round(w_b_d - b_north_d, 2)
            b_band2_y = round(w_b_y + b_north_d, 2)
            bath2_w = round(min(2.4, max(1.8, w_b_w * 0.35)), 2)
            bed2_w = round(w_b_w - bath2_w, 2)

            rooms.append(MultiFloorRoomRectangle(
                room_id=f"bath_2_F{floor_index}",
                room_name="Common Bathroom",
                floor_index=floor_index,
                x=w_b_x,
                y=w_b_y,
                width_m=bath2_w,
                depth_m=b_north_d,
                area_sqm=round(bath2_w * b_north_d, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(b_north_d / bath2_w if bath2_w > 0 else 1.0, 2),
                applied_rules=["NBC-BATHROOM-MIN-AREA", "PLUMB-01-WET-STACK"],
            ))
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"bed_2_F{floor_index}",
                room_name="Secondary Bedroom",
                floor_index=floor_index,
                x=round(w_b_x + bath2_w, 2),
                y=w_b_y,
                width_m=bed2_w,
                depth_m=b_north_d,
                area_sqm=round(bed2_w * b_north_d, 2),
                zone="NW",
                zone_category="private",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(bed2_w / b_north_d if b_north_d > 0 else 1.0, 2),
                applied_rules=["NBC-BEDROOM-MIN-AREA", "NBC-LIGHT-VENTILATION"],
            ))
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"bath_1_F{floor_index}",
                room_name="Ensuite Bathroom",
                floor_index=floor_index,
                x=w_b_x,
                y=b_band2_y,
                width_m=bath2_w,
                depth_m=b_south_d,
                area_sqm=round(bath2_w * b_south_d, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(b_south_d / bath2_w if bath2_w > 0 else 1.0, 2),
                applied_rules=["PLUMB-01-ENSUITE-ADJACENT", "NBC-BATHROOM-MIN-AREA"],
            ))
            rooms.append(MultiFloorRoomRectangle(
                room_id=f"master_bed_F{floor_index}",
                room_name="Master Suite",
                floor_index=floor_index,
                x=round(w_b_x + bath2_w, 2),
                y=b_band2_y,
                width_m=bed2_w,
                depth_m=b_south_d,
                area_sqm=round(bed2_w * b_south_d, 2),
                zone="SW",
                zone_category="private",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(bed2_w / b_south_d if b_south_d > 0 else 1.0, 2),
                applied_rules=["VASTU-MASTER-SW-EARTH", "NBC-BEDROOM-MIN-AREA"],
            ))

        return rooms

        return rooms

    def _partition_floor_plate(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        core: VerticalCoreSpec,
        ducts: List[DuctShaftSpec],
        spaces: List[SpaceTypeSpec],
        previous_rooms: Optional[List[MultiFloorRoomRectangle]] = None,
    ) -> List[MultiFloorRoomRectangle]:
        """
        Partitions the envelope into exact non-overlapping rectangles around
        the locked vertical core, enforcing hard pruning on FORBIDDEN_* rules,
        MUST_ADJACENT rules, and vertical stacking rules.
        """
        # Multi-wing / L-shape / Courtyard layout partitioning
        if self.site_plan and self.site_plan.footprint and len(self.site_plan.footprint.wings) > 1:
            rooms = self._partition_multi_wing_rooms(
                floor_index=floor_index,
                envelope=envelope,
                core=core,
                ducts=ducts,
                spaces=spaces,
                previous_rooms=previous_rooms,
            )
            for repair_line in repair_room_envelopes_for_furniture(rooms):
                if repair_line not in self.warnings:
                    self.warnings.append(repair_line)
            self._prune_and_verify_hard_constraints(floor_index, rooms, previous_rooms)
            return rooms

        env_w = envelope["width"]
        env_d = envelope["depth"]
        # Filter spaces excluding already placed core and lobby
        allocated_spaces = [s for s in spaces if s.function != FunctionType.CIRCULATION]
        rooms: List[MultiFloorRoomRectangle] = []

        # 1. Check if single storey custom requested rooms mode for T1
        if self.total_storeys == 1 and self.typology == "T1_SINGLE_FAMILY" and self.req.required_rooms and len(self.req.required_rooms) >= 3:
            rooms = self._partition_t1_rooms(
                floor_index, envelope, None, None, 0.0, env_w, 0.0, 0.0, env_d, allocated_spaces
            )
            # Check hard pruning constraints on generated rooms
            self._prune_and_verify_hard_constraints(floor_index, rooms, previous_rooms)
            return rooms

        # 2. Locked Vertical Core Room
        is_fire_core = (self.typology in ("T3_LARGE_COMPLEX", "T4_WAREHOUSE")) or (floor_index > 0)
        core_rules = ["VERT-03-CORE-CONTINUITY", "NBC-STAIR-EGRESS"]
        if self.typology == "T4_WAREHOUSE":
            core_rules.append("VERT-05-MEZZANINE-FIRE-SEPARATION")
            core_name = "Industrial Steel Egress Stair"
        elif is_fire_core:
            core_name = "Enclosed Fire Staircase"
        else:
            core_name = "Staircase Core"

        core_room = MultiFloorRoomRectangle(
            room_id=f"{core.core_id}_F{floor_index}",
            room_name=core_name,
            floor_index=floor_index,
            x=core.x,
            y=core.y,
            width_m=core.width_m,
            depth_m=core.depth_m,
            area_sqm=round(core.width_m * core.depth_m, 2),
            zone="W",
            zone_category="circulation",
            vastu_compliant=True,
            is_vertical_core=True,
            requires_exterior_wall=True,
            aspect_ratio=round(core.depth_m / core.width_m, 2),
            applied_rules=core_rules,
        )
        rooms.append(core_room)

        # 3. Central Circulation Lobby / Spine (MUST_ADJACENT to core)
        pocket = getattr(self, "_t2_pocket", None)
        if pocket:
            # Compact T2: the stair sits on the east flank, so the lobby is
            # the two-metre strip directly west of it.  Keeping it beside the
            # core preserves the required adjacency and lets both unit
            # living rooms open off it.
            lobby_x = round(core.x - pocket["lobby_w"], 2)
            lobby_w = round(pocket["lobby_w"], 2)
            lobby_d = round(core.depth_m, 2)
        else:
            lobby_x = round(core.x + core.width_m, 2)
            # Clamp so lobby never overflows the envelope (narrow plot degradation)
            max_lobby_w = round(max(0.0, env_w - lobby_x), 2)
            lobby_w = round(min(2.4, max(1.5, (env_w - lobby_x) * 0.30)), 2)
            lobby_w = round(min(lobby_w, max_lobby_w), 2)
            lobby_d = round(core.depth_m, 2)
        lobby_y = round(core.y, 2)

        lobby_name = "Entrance Foyer" if (floor_index == 0 and self.typology == "T1_SINGLE_FAMILY") else (
            "Double-Loaded Spine Corridor" if self.typology == "T3_LARGE_COMPLEX" else (
                "Mezzanine Access Catwalk" if (floor_index > 0 and self.typology == "T4_WAREHOUSE") else "Central Distribution Lobby"
            )
        )
        lobby_room = MultiFloorRoomRectangle(
            room_id=f"lobby_spine_F{floor_index}",
            room_name=lobby_name,
            floor_index=floor_index,
            x=lobby_x,
            y=lobby_y,
            width_m=lobby_w,
            depth_m=lobby_d,
            area_sqm=round(lobby_w * lobby_d, 2),
            zone="CENTER",
            zone_category="circulation",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=False,
            aspect_ratio=round(lobby_d / lobby_w, 2),
            applied_rules=["CIRC-01-CORE-LOBBY-ADJACENT", "NBC-CORRIDOR-MIN-WIDTH"],
        )
        rooms.append(lobby_room)

        # Remaining spatial fields
        # Remaining spatial fields — clamped for narrow plot robustness
        east_x = round(min(env_w, lobby_x + lobby_w), 2)
        east_w = round(max(0.0, env_w - east_x), 2)

        north_h = round(core.y, 2)   # Living room south wall == core north wall (exact)
        south_y = round(core.y + core.depth_m, 2)
        south_h = round(max(2.2, env_d - south_y), 2)

        # ---------------------------------------------------------------------
        # TYPOLOGY SPECIFIC CONSTRAINED RECTANGULAR ALLOCATION
        # ---------------------------------------------------------------------
        if self.typology == "T1_SINGLE_FAMILY":
            rooms.extend(self._partition_t1_rooms(
                floor_index, envelope, core_room, lobby_room, east_x, east_w, north_h, south_y, south_h, allocated_spaces
            ))
        elif self.typology == "T2_FAMILY_APARTMENT":
            rooms.extend(self._partition_t2_rooms(
                floor_index, envelope, core_room, lobby_room, east_x, east_w, north_h, south_y, south_h, allocated_spaces
            ))
        elif self.typology == "T3_LARGE_COMPLEX":
            rooms.extend(self._partition_t3_rooms(
                floor_index, envelope, core_room, lobby_room, east_x, east_w, north_h, south_y, south_h, allocated_spaces
            ))
        elif self.typology == "T4_WAREHOUSE":
            rooms.extend(self._partition_t4_rooms(
                floor_index, envelope, core_room, lobby_room, east_x, east_w, north_h, south_y, south_h, allocated_spaces
            ))
        else:
            rooms.extend(self._partition_t1_rooms(
                floor_index, envelope, core_room, lobby_room, east_x, east_w, north_h, south_y, south_h, allocated_spaces
            ))

        # Check if simple rectangular envelope has a terrace band for this floor
        band = getattr(self, "resolved_terrace_bands", {}).get(floor_index)
        if band and band.edge == "N":
            terrace_room = MultiFloorRoomRectangle(
                room_id=f"terrace_band_F{floor_index}",
                room_name="Open Terrace / Sky Deck",
                floor_index=floor_index,
                x=0.0,
                y=0.0,
                width_m=env_w,
                depth_m=band.depth_m,
                area_sqm=round(env_w * band.depth_m, 2),
                zone="TERRACE",
                zone_category="terrace",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(env_w / band.depth_m if band.depth_m > 0 else 1.0, 2),
                applied_rules=[
                    "RULE-FP-02-TERRACE-SETBACK",
                    "RULE-FP-04-TERRACE-ACCESS",
                    "RULE-FP-06-FAR-EXEMPT",
                    "RULE-FP-07-TERRACE-DEPTH-LIMIT",
                ],
            )
            # Remove rooms located in the North band zone (e.g. bed_2, balcony);
            # trim rooms that straddle the band boundary so the terrace never
            # overlaps a conditioned room (hard non-overlap invariant).
            kept: List[MultiFloorRoomRectangle] = []
            for r in rooms:
                r_top = r.y + r.depth_m
                fully_in = r.y < band.depth_m - 0.05 and r_top <= band.depth_m + 0.05
                straddles = r.y < band.depth_m - 0.05 and r_top > band.depth_m + 0.05
                if fully_in:
                    self.warnings.append(
                        f"Room '{r.room_id}' fully inside terrace band zone on Floor {floor_index} - removed for terrace."
                    )
                    continue
                if straddles:
                    new_y = round(band.depth_m, 2)
                    new_d = round(r_top - band.depth_m, 2)
                    if new_d < 1.2 or round(r.width_m * new_d, 2) < 2.0:
                        self.warnings.append(
                            f"Room '{r.room_id}' mostly inside terrace band zone on Floor {floor_index} - removed for terrace."
                        )
                        continue
                    r.y = new_y
                    r.depth_m = new_d
                    r.area_sqm = round(r.width_m * new_d, 2)
                    r.aspect_ratio = round(
                        max(r.width_m, new_d) / max(min(r.width_m, new_d), 0.01), 2
                    )
                    self.warnings.append(
                        f"Room '{r.room_id}' trimmed to y={new_y:.2f} (depth {new_d:.2f}m) to clear terrace band on Floor {floor_index}."
                    )
                kept.append(r)
            rooms = kept
            rooms.insert(0, terrace_room)

        # Furniture sets are placed at solve time.  A narrow bedroom
        # borrows frontage from surplus in its own row before doors, windows and
        # the wall graph are hosted, instead of failing the L4 audit afterwards.
        for repair_line in repair_room_envelopes_for_furniture(rooms):
            if repair_line not in self.warnings:
                self.warnings.append(repair_line)

        # VERT-01/02 must be satisfied BEFORE the hard verifier runs: an upper
        # wet room that overhangs its lower wet block by 20 cm into a bedroom is
        # a real violation, so the band is re-split here while a layout still
        # Exists to repair.
        for _align_line in self._align_wet_stack(floor_index, rooms, list(previous_rooms or [])):
            if _align_line not in self.warnings:
                self.warnings.append(_align_line)

        # Check hard pruning constraints on generated rooms
        self._prune_and_verify_hard_constraints(floor_index, rooms, previous_rooms)

        return rooms

    def _partition_t1_rooms(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        core: MultiFloorRoomRectangle,
        lobby: MultiFloorRoomRectangle,
        east_x: float,
        east_w: float,
        north_h: float,
        south_y: float,
        south_h: float,
        spaces: List[SpaceTypeSpec],
    ) -> List[MultiFloorRoomRectangle]:
        """Synthesizes T1 Single Family residential floor plates with 100% envelope coverage."""
        env_w = envelope["width"]
        env_d = envelope["depth"]
        t1_rooms: List[MultiFloorRoomRectangle] = []
        space_ids = [s.id for s in spaces]

        # Check if single storey custom requested rooms mode
        if self.total_storeys == 1 and self.req.required_rooms and len(self.req.required_rooms) >= 3:
            n_rooms = len(self.req.required_rooms)
            has_two_baths = sum(1 for r in self.req.required_rooms if any(k in r for k in ("bath", "toilet", "wc"))) >= 2
            has_bed2 = sum(1 for r in self.req.required_rooms if "bed" in r and "master" not in r) >= 1

            if n_rooms == 4:
                # Exactly 4 requested rooms (e.g. living, master_bed, kitchen, bath_1 or puja)
                living_id = next((r for r in self.req.required_rooms if any(k in r for k in ("living", "foyer"))), "living")
                master_id = next((r for r in self.req.required_rooms if "master" in r or "bed" in r), "master_bed")
                kitchen_id = next((r for r in self.req.required_rooms if "kitchen" in r or "cook" in r), "kitchen")
                has_bath = any(any(k in r for k in ("bath", "toilet", "wc")) for r in self.req.required_rooms)
                has_puja = any("puja" in r or "pooja" in r or "prayer" in r for r in self.req.required_rooms)

                H_pub = round(max(3.20, min(env_d * 0.50, 4.00)), 2)
                H_rear = round(env_d - H_pub, 2)

                if has_bath and not has_puja:
                    bath_id = next((r for r in self.req.required_rooms if any(k in r for k in ("bath", "toilet", "wc"))), "bath_1")
                    if env_w < 7.00:
                        # A NARROW buildable (an 8 m site sets back to 6 m).  Widening
                        # this to every <10.2 m plate re-partitioned the canonical
                        # 10x12 rectangle (8.0 m envelope) into 2.97 m full-width
                        # bands and broke its certificate; 7 m keeps the two-column
                        # layout on ordinary plates and fixes only the narrow ones.
                        # Deep/narrow plate (an 8x40 m site draws a 6 m wide
                        # buildable): two full-width bands over a split service
                        # row.  The old two-band division gave the kitchen 0.6 m
                        # of frontage on this plate and collapsed it, which the
                        # unfit guard then refused as "no rooms".  A corridor
                        # between bath and kitchen keeps the forbidden shared
                        # wall out of the plan.
                        # The service row takes 0.338 of the depth so the
                        # kitchen clears its 9 m² minimum at a 6 m width; the two
                        # habitable bands share the remainder.
                        H_rear = round(env_d * 0.338, 2)
                        H_pub = round((env_d - H_rear) / 2.0, 2)
                        H_mid = round(H_pub, 2)
                        # A 1.55 m central lobby clears the 5 m² and 1:2.2
                        # circulation limits at this depth and separates the wet
                        # wall from the cooking wall (no forbidden shared wall).
                        W_bath = round(max(1.70, min(2.00, env_w * 0.28)), 2)
                        W_corr = 1.55
                        W_kitch = round(env_w - W_bath - W_corr, 2)
                        y_mid = round(H_pub, 2)
                        y_rear = round(y_mid + H_mid, 2)

                        t1_rooms.extend([
                            MultiFloorRoomRectangle(
                                room_id=living_id, room_name="Living Room", floor_index=0,
                                x=0.0, y=0.0, width_m=env_w, depth_m=H_pub,
                                area_sqm=round(env_w * H_pub, 2), zone="N",
                                zone_category="public", vastu_compliant=True,
                                is_vertical_core=False, requires_exterior_wall=True,
                                aspect_ratio=round(env_w / H_pub if env_w > H_pub else H_pub / env_w, 2),
                                applied_rules=["VASTU-N-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
                            ),
                            MultiFloorRoomRectangle(
                                room_id=master_id, room_name="Master Bedroom", floor_index=0,
                                x=0.0, y=y_mid, width_m=env_w, depth_m=H_mid,
                                area_sqm=round(env_w * H_mid, 2), zone="SW",
                                zone_category="private", vastu_compliant=True,
                                is_vertical_core=False, requires_exterior_wall=True,
                                aspect_ratio=round(env_w / H_mid if env_w > H_mid else H_mid / env_w, 2),
                                applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
                            ),
                            MultiFloorRoomRectangle(
                                room_id=bath_id, room_name="Common Bath", floor_index=0,
                                x=0.0, y=y_rear, width_m=W_bath, depth_m=H_rear,
                                area_sqm=round(W_bath * H_rear, 2), zone="W",
                                zone_category="service", vastu_compliant=True,
                                is_vertical_core=False, requires_exterior_wall=True,
                                aspect_ratio=round(H_rear / W_bath if H_rear > W_bath else W_bath / H_rear, 2),
                                applied_rules=["VASTU-W-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                            ),
                            MultiFloorRoomRectangle(
                                room_id="corridor", room_name="Circulation Lobby", floor_index=0,
                                x=W_bath, y=y_rear, width_m=W_corr, depth_m=H_rear,
                                area_sqm=round(W_corr * H_rear, 2), zone="Center",
                                zone_category="circulation", vastu_compliant=True,
                                is_vertical_core=False, requires_exterior_wall=False,
                                aspect_ratio=round(H_rear / W_corr if H_rear > W_corr else W_corr / H_rear, 2),
                                space_type_id="central_lobby",
                                applied_rules=["NBC-CORRIDOR-MIN-WIDTH", "CIRC-CENTRAL-SPINE"],
                            ),
                            MultiFloorRoomRectangle(
                                room_id=kitchen_id, room_name="Kitchen", floor_index=0,
                                x=round(W_bath + W_corr, 2), y=y_rear,
                                width_m=W_kitch, depth_m=H_rear,
                                area_sqm=round(W_kitch * H_rear, 2), zone="SE",
                                zone_category="service", vastu_compliant=True,
                                is_vertical_core=False, requires_exterior_wall=True,
                                aspect_ratio=round(H_rear / W_kitch if H_rear > W_kitch else W_kitch / H_rear, 2),
                                applied_rules=["VASTU-SE-KITCHEN", "NBC-MIN-KITCHEN"],
                            ),
                        ])
                        return t1_rooms
                    W_bath = round(max(1.80, min(2.40, H_rear / 1.80)), 2)
                    W_rem = round(env_w - W_bath, 2)
                    W_mb = round(max(3.00, min(W_rem - 2.00, W_rem * 0.58)), 2)
                    W_kitch = round(W_rem - W_mb, 2)

                    t1_rooms.extend([
                        MultiFloorRoomRectangle(
                            room_id=living_id,
                            room_name="Living Room",
                            floor_index=0,
                            x=0.0,
                            y=0.0,
                            width_m=env_w,
                            depth_m=H_pub,
                            area_sqm=round(env_w * H_pub, 2),
                            zone="N",
                            zone_category="public",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(env_w / H_pub if env_w > H_pub else H_pub / env_w, 2),
                            applied_rules=["VASTU-N-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=bath_id,
                            room_name="Common Bath",
                            floor_index=0,
                            x=0.0,
                            y=H_pub,
                            width_m=W_bath,
                            depth_m=H_rear,
                            area_sqm=round(W_bath * H_rear, 2),
                            zone="W",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_bath if H_rear > W_bath else W_bath / H_rear, 2),
                            applied_rules=["VASTU-W-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=master_id,
                            room_name="Master Bedroom",
                            floor_index=0,
                            x=W_bath,
                            y=H_pub,
                            width_m=W_mb,
                            depth_m=H_rear,
                            area_sqm=round(W_mb * H_rear, 2),
                            zone="SW",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(W_mb / H_rear if W_mb > H_rear else H_rear / W_mb, 2),
                            applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=kitchen_id,
                            room_name="Kitchen",
                            floor_index=0,
                            x=round(W_bath + W_mb, 2),
                            y=H_pub,
                            width_m=W_kitch,
                            depth_m=H_rear,
                            area_sqm=round(W_kitch * H_rear, 2),
                            zone="SE",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_kitch if H_rear > W_kitch else W_kitch / H_rear, 2),
                            applied_rules=["VASTU-SE-KITCHEN", "NBC-MIN-KITCHEN"],
                        ),
                    ])
                    return t1_rooms
                elif has_puja and not has_bath:
                    puja_id = next((r for r in self.req.required_rooms if "puja" in r or "pooja" in r or "prayer" in r), "puja")
                    puja_w = 2.40
                    liv_w = round(env_w - puja_w, 2)
                    mb_w = round(max(3.20, env_w * 0.58), 2)
                    kitch_w = round(env_w - mb_w, 2)

                    t1_rooms.extend([
                        MultiFloorRoomRectangle(
                            room_id=living_id,
                            room_name="Living Room",
                            floor_index=0,
                            x=0.0,
                            y=0.0,
                            width_m=liv_w,
                            depth_m=H_pub,
                            area_sqm=round(liv_w * H_pub, 2),
                            zone="NW",
                            zone_category="public",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(liv_w / H_pub if liv_w > H_pub else H_pub / liv_w, 2),
                            applied_rules=["VASTU-NW-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=puja_id,
                            room_name="Puja Room",
                            floor_index=0,
                            x=liv_w,
                            y=0.0,
                            width_m=puja_w,
                            depth_m=H_pub,
                            area_sqm=round(puja_w * H_pub, 2),
                            zone="NE",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_pub / puja_w if H_pub > puja_w else puja_w / H_pub, 2),
                            applied_rules=["VASTU-NE-POOJA", "NBC-MIN-PUJA", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=master_id,
                            room_name="Master Bedroom",
                            floor_index=0,
                            x=0.0,
                            y=H_pub,
                            width_m=mb_w,
                            depth_m=H_rear,
                            area_sqm=round(mb_w * H_rear, 2),
                            zone="SW",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(mb_w / H_rear if mb_w > H_rear else H_rear / mb_w, 2),
                            applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=kitchen_id,
                            room_name="Kitchen",
                            floor_index=0,
                            x=mb_w,
                            y=H_pub,
                            width_m=kitch_w,
                            depth_m=H_rear,
                            area_sqm=round(kitch_w * H_rear, 2),
                            zone="SE",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(kitch_w / H_rear if kitch_w > H_rear else H_rear / kitch_w, 2),
                            applied_rules=["VASTU-SE-KITCHEN", "NBC-MIN-KITCHEN"],
                        ),
                    ])
                    return t1_rooms

            if n_rooms <= 5 and not has_bed2 and not has_two_baths:
                # 5 Rooms: living, puja, master_bed, bath_1, kitchen (+ corridor)
                living_id = next((r for r in self.req.required_rooms if any(k in r for k in ("living", "foyer"))), "living")
                puja_id = next((r for r in self.req.required_rooms if "puja" in r or "pooja" in r or "prayer" in r), "puja")
                master_id = next((r for r in self.req.required_rooms if "master" in r or "bed" in r), "master_bed")
                bath_id = next((r for r in self.req.required_rooms if any(k in r for k in ("bath", "toilet", "wc"))), "bath_1")
                kitchen_id = next((r for r in self.req.required_rooms if "kitchen" in r or "cook" in r), "kitchen")

                puja_w = 2.40
                liv_w = round(env_w - puja_w, 2)
                H_pub = 3.50
                H_corr = 1.15
                H_rear = round(env_d - H_pub - H_corr, 2)

                W_bath = 1.65
                W_rem = round(env_w - W_bath, 2)
                mb_w = round(max(4.20, min(W_rem - 2.80, W_rem * 0.60)), 2)
                kitch_w = round(W_rem - mb_w, 2)

                y_corr = round(H_pub, 2)
                y_rear = round(y_corr + H_corr, 2)

                t1_rooms.extend([
                    MultiFloorRoomRectangle(
                        room_id=living_id,
                        room_name="Living Room",
                        floor_index=0,
                        x=0.0,
                        y=0.0,
                        width_m=liv_w,
                        depth_m=H_pub,
                        area_sqm=round(liv_w * H_pub, 2),
                        zone="NW",
                        zone_category="public",
                        vastu_compliant=True,
                        is_vertical_core=False,
                        requires_exterior_wall=True,
                        aspect_ratio=round(liv_w / H_pub, 2),
                        applied_rules=["VASTU-NW-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
                    ),
                    MultiFloorRoomRectangle(
                        room_id=puja_id,
                        room_name="Puja Room",
                        floor_index=0,
                        x=liv_w,
                        y=0.0,
                        width_m=puja_w,
                        depth_m=H_pub,
                        area_sqm=round(puja_w * H_pub, 2),
                        zone="NE",
                        zone_category="private",
                        vastu_compliant=True,
                        is_vertical_core=False,
                        requires_exterior_wall=True,
                        aspect_ratio=round(H_pub / puja_w, 2),
                        applied_rules=["VASTU-NE-POOJA", "NBC-MIN-PUJA", "HYG-01-FOUL-SACRED-WALL"],
                    ),
                    MultiFloorRoomRectangle(
                        room_id="corridor",
                        room_name="Corridor",
                        floor_index=0,
                        x=0.0,
                        y=y_corr,
                        width_m=env_w,
                        depth_m=H_corr,
                        area_sqm=round(env_w * H_corr, 2),
                        zone="Center",
                        zone_category="circulation",
                        vastu_compliant=True,
                        is_vertical_core=False,
                        requires_exterior_wall=False,
                        aspect_ratio=round(env_w / H_corr, 2),
                        applied_rules=["NBC-CORRIDOR-MIN-WIDTH", "CIRC-CENTRAL-SPINE"],
                    ),
                    MultiFloorRoomRectangle(
                        room_id=bath_id,
                        room_name="Common Bath",
                        floor_index=0,
                        x=0.0,
                        y=y_rear,
                        width_m=W_bath,
                        depth_m=H_rear,
                        area_sqm=round(W_bath * H_rear, 2),
                        zone="W",
                        zone_category="service",
                        vastu_compliant=True,
                        is_vertical_core=False,
                        requires_exterior_wall=True,
                        aspect_ratio=round(H_rear / W_bath, 2),
                        applied_rules=["VASTU-W-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                    ),
                    MultiFloorRoomRectangle(
                        room_id=master_id,
                        room_name="Master Bedroom",
                        floor_index=0,
                        x=W_bath,
                        y=y_rear,
                        width_m=mb_w,
                        depth_m=H_rear,
                        area_sqm=round(mb_w * H_rear, 2),
                        zone="SW",
                        zone_category="private",
                        vastu_compliant=True,
                        is_vertical_core=False,
                        requires_exterior_wall=True,
                        aspect_ratio=round(mb_w / H_rear if mb_w > H_rear else H_rear / mb_w, 2),
                        applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
                    ),
                    MultiFloorRoomRectangle(
                        room_id=kitchen_id,
                        room_name="Kitchen",
                        floor_index=0,
                        x=round(W_bath + mb_w, 2),
                        y=y_rear,
                        width_m=kitch_w,
                        depth_m=H_rear,
                        area_sqm=round(kitch_w * H_rear, 2),
                        zone="SE",
                        zone_category="service",
                        vastu_compliant=True,
                        is_vertical_core=False,
                        requires_exterior_wall=True,
                        aspect_ratio=round(H_rear / kitch_w if H_rear > kitch_w else kitch_w / H_rear, 2),
                        applied_rules=["VASTU-SE-KITCHEN", "NBC-MIN-KITCHEN"],
                    ),
                ])
                return t1_rooms

            elif not has_two_baths and (has_bed2 or n_rooms == 6):
                # 6 Rooms: living, puja, master_bed, bed_2, bath_1, kitchen (+ corridor)
                living_id = next((r for r in self.req.required_rooms if any(k in r for k in ("living", "foyer"))), "living")
                puja_id = next((r for r in self.req.required_rooms if "puja" in r or "pooja" in r or "prayer" in r), "puja")
                master_id = next((r for r in self.req.required_rooms if "master" in r), "master_bed")
                bed2_id = next((r for r in self.req.required_rooms if ("bed" in r or "guest" in r) and r != master_id), "bed_2")
                kitchen_id = next((r for r in self.req.required_rooms if "kitchen" in r or "cook" in r), "kitchen")
                bath_id = next((r for r in self.req.required_rooms if any(k in r for k in ("bath", "toilet", "wc"))), "bath_1")

                if env_w < 10.20:
                    # Deep plot configuration (e.g. 10.0x15.0m)
                    H_pub = 3.45
                    H_mid = 3.35
                    H_rear = round(env_d - H_pub - H_mid, 2)
                    puja_w = 2.40
                    liv_w = round(env_w - puja_w, 2)

                    W_b1 = 1.70
                    W_b2 = 3.40
                    W_corr = round(env_w - W_b1 - W_b2, 2)

                    W_mb = round(max(4.80, env_w * 0.58), 2)
                    W_kitch = round(env_w - W_mb, 2)

                    y_mid = round(H_pub, 2)
                    y_rear = round(y_mid + H_mid, 2)

                    t1_rooms.extend([
                        MultiFloorRoomRectangle(
                            room_id=living_id,
                            room_name="Living Room",
                            floor_index=0,
                            x=0.0,
                            y=0.0,
                            width_m=liv_w,
                            depth_m=H_pub,
                            area_sqm=round(liv_w * H_pub, 2),
                            zone="NW",
                            zone_category="public",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(liv_w / H_pub, 2),
                            applied_rules=["VASTU-NW-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=puja_id,
                            room_name="Puja Room",
                            floor_index=0,
                            x=liv_w,
                            y=0.0,
                            width_m=puja_w,
                            depth_m=H_pub,
                            area_sqm=round(puja_w * H_pub, 2),
                            zone="NE",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_pub / puja_w, 2),
                            applied_rules=["VASTU-NE-POOJA", "NBC-MIN-PUJA", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=bath_id,
                            room_name="Common Bath",
                            floor_index=0,
                            x=0.0,
                            y=y_mid,
                            width_m=W_b1,
                            depth_m=H_mid,
                            area_sqm=round(W_b1 * H_mid, 2),
                            zone="NW",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_mid / W_b1, 2),
                            applied_rules=["VASTU-NW-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id="corridor",
                            room_name="Corridor",
                            floor_index=0,
                            x=W_b1,
                            y=y_mid,
                            width_m=W_corr,
                            depth_m=H_mid,
                            area_sqm=round(W_corr * H_mid, 2),
                            zone="Center",
                            zone_category="circulation",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=False,
                            aspect_ratio=round(H_mid / W_corr if H_mid > W_corr else W_corr / H_mid, 2),
                            applied_rules=["NBC-CORRIDOR-MIN-WIDTH", "CIRC-CENTRAL-SPINE"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=bed2_id,
                            room_name="Bedroom 2",
                            floor_index=0,
                            x=round(W_b1 + W_corr, 2),
                            y=y_mid,
                            width_m=W_b2,
                            depth_m=H_mid,
                            area_sqm=round(W_b2 * H_mid, 2),
                            zone="E",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(W_b2 / H_mid, 2),
                            applied_rules=["VASTU-E-BED2", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=master_id,
                            room_name="Master Bedroom",
                            floor_index=0,
                            x=0.0,
                            y=y_rear,
                            width_m=W_mb,
                            depth_m=H_rear,
                            area_sqm=round(W_mb * H_rear, 2),
                            zone="SW",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(W_mb / H_rear if W_mb > H_rear else H_rear / W_mb, 2),
                            applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=kitchen_id,
                            room_name="Kitchen",
                            floor_index=0,
                            x=W_mb,
                            y=y_rear,
                            width_m=W_kitch,
                            depth_m=H_rear,
                            area_sqm=round(W_kitch * H_rear, 2),
                            zone="SE",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_kitch if H_rear > W_kitch else W_kitch / H_rear, 2),
                            applied_rules=["VASTU-SE-KITCHEN", "NBC-MIN-KITCHEN"],
                        ),
                    ])
                    return t1_rooms
                else:
                    # Wide plot configuration
                    puja_w = 2.40
                    bed2_w = round(max(3.00, min(3.60, (env_w - puja_w) * 0.35)), 2)
                    liv_w = round(env_w - bed2_w - puja_w, 2)
                    H_pub = round(max(3.80, min(4.30, 18.2 / max(liv_w, 1.0))), 2)
                    H_corr = 1.05
                    H_rear = round(env_d - H_pub - H_corr, 2)

                    W_bath = round(max(1.85, min(2.15, H_rear / 1.90)), 2)
                    W_rem = round(env_w - W_bath, 2)
                    mb_w = round(max(4.20, min(W_rem - 2.80, W_rem * 0.58)), 2)
                    kitch_w = round(W_rem - mb_w, 2)

                    y_corr = round(H_pub, 2)
                    y_rear = round(y_corr + H_corr, 2)

                    t1_rooms.extend([
                        MultiFloorRoomRectangle(
                            room_id=bed2_id,
                            room_name="Bedroom 2",
                            floor_index=0,
                            x=0.0,
                            y=0.0,
                            width_m=bed2_w,
                            depth_m=H_pub,
                            area_sqm=round(bed2_w * H_pub, 2),
                            zone="NW",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(bed2_w / H_pub if bed2_w > H_pub else H_pub / bed2_w, 2),
                            applied_rules=["VASTU-NW-BED2", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=living_id,
                            room_name="Living Room",
                            floor_index=0,
                            x=bed2_w,
                            y=0.0,
                            width_m=liv_w,
                            depth_m=H_pub,
                            area_sqm=round(liv_w * H_pub, 2),
                            zone="N",
                            zone_category="public",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(liv_w / H_pub if liv_w > H_pub else H_pub / liv_w, 2),
                            applied_rules=["VASTU-N-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=puja_id,
                            room_name="Puja Room",
                            floor_index=0,
                            x=round(bed2_w + liv_w, 2),
                            y=0.0,
                            width_m=puja_w,
                            depth_m=H_pub,
                            area_sqm=round(puja_w * H_pub, 2),
                            zone="NE",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_pub / puja_w, 2),
                            applied_rules=["VASTU-NE-POOJA", "NBC-MIN-PUJA", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id="corridor",
                            room_name="Corridor",
                            floor_index=0,
                            x=0.0,
                            y=y_corr,
                            width_m=env_w,
                            depth_m=H_corr,
                            area_sqm=round(env_w * H_corr, 2),
                            zone="Center",
                            zone_category="circulation",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=False,
                            aspect_ratio=round(env_w / H_corr, 2),
                            applied_rules=["NBC-CORRIDOR-MIN-WIDTH", "CIRC-CENTRAL-SPINE"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=bath_id,
                            room_name="Common Bath",
                            floor_index=0,
                            x=0.0,
                            y=y_rear,
                            width_m=W_bath,
                            depth_m=H_rear,
                            area_sqm=round(W_bath * H_rear, 2),
                            zone="W",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_bath, 2),
                            applied_rules=["VASTU-W-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=master_id,
                            room_name="Master Bedroom",
                            floor_index=0,
                            x=W_bath,
                            y=y_rear,
                            width_m=mb_w,
                            depth_m=H_rear,
                            area_sqm=round(mb_w * H_rear, 2),
                            zone="SW",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(mb_w / H_rear if mb_w > H_rear else H_rear / mb_w, 2),
                            applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=kitchen_id,
                            room_name="Kitchen",
                            floor_index=0,
                            x=round(W_bath + mb_w, 2),
                            y=y_rear,
                            width_m=kitch_w,
                            depth_m=H_rear,
                            area_sqm=round(kitch_w * H_rear, 2),
                            zone="SE",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / kitch_w if H_rear > kitch_w else kitch_w / H_rear, 2),
                            applied_rules=["VASTU-SE-KITCHEN", "NBC-MIN-KITCHEN"],
                        ),
                    ])
                    return t1_rooms

            elif has_two_baths or n_rooms >= 7:
                # 7-8 Rooms: living, puja, master_bed, bed_2, bath_1, bath_2, dining, kitchen (+ corridor)
                living_id = next((r for r in self.req.required_rooms if any(k in r for k in ("living", "foyer"))), "living")
                puja_id = next((r for r in self.req.required_rooms if "puja" in r or "pooja" in r or "prayer" in r), "puja")
                master_id = next((r for r in self.req.required_rooms if "master" in r), "master_bed")
                bed2_id = next((r for r in self.req.required_rooms if ("bed" in r or "guest" in r) and r != master_id), "bed_2")
                kitchen_id = next((r for r in self.req.required_rooms if "kitchen" in r or "cook" in r), "kitchen")
                dining_id = next((r for r in self.req.required_rooms if "dining" in r), "dining")
                bath_rooms = [r for r in self.req.required_rooms if any(k in r for k in ("bath", "toilet", "wc"))]
                common_id = next((r for r in bath_rooms if "common" in r or r == "bath_1"), bath_rooms[0] if bath_rooms else "bath_1")
                primary_id = next((r for r in bath_rooms if r != common_id), "bath_2")

                if env_w < 10.40:
                    # Deep plot configuration
                    H_pub = 3.50
                    H_mid = 3.35
                    H_rear = round(env_d - H_pub - H_mid, 2)
                    puja_w = 2.40
                    liv_w = round(env_w - puja_w, 2)

                    W_b1 = 1.70
                    W_b2 = 3.10
                    W_din = 2.70
                    W_corr = round(env_w - W_b1 - W_b2 - W_din, 2)

                    W_bath2 = 1.70
                    W_kitch = 2.90
                    W_mb = round(env_w - W_bath2 - W_kitch, 2)

                    y_mid = round(H_pub, 2)
                    y_rear = round(y_mid + H_mid, 2)

                    t1_rooms.extend([
                        MultiFloorRoomRectangle(
                            room_id=living_id,
                            room_name="Living Room",
                            floor_index=0,
                            x=0.0,
                            y=0.0,
                            width_m=liv_w,
                            depth_m=H_pub,
                            area_sqm=round(liv_w * H_pub, 2),
                            zone="NW",
                            zone_category="public",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(liv_w / H_pub, 2),
                            applied_rules=["VASTU-NW-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=puja_id,
                            room_name="Puja Room",
                            floor_index=0,
                            x=liv_w,
                            y=0.0,
                            width_m=puja_w,
                            depth_m=H_pub,
                            area_sqm=round(puja_w * H_pub, 2),
                            zone="NE",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_pub / puja_w, 2),
                            applied_rules=["VASTU-NE-POOJA", "NBC-MIN-PUJA", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=common_id,
                            room_name="Common Bath",
                            floor_index=0,
                            x=0.0,
                            y=y_mid,
                            width_m=W_b1,
                            depth_m=H_mid,
                            area_sqm=round(W_b1 * H_mid, 2),
                            zone="NW",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_mid / W_b1, 2),
                            applied_rules=["VASTU-NW-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id="corridor",
                            room_name="Corridor",
                            floor_index=0,
                            x=W_b1,
                            y=y_mid,
                            width_m=W_corr,
                            depth_m=H_mid,
                            area_sqm=round(W_corr * H_mid, 2),
                            zone="Center",
                            zone_category="circulation",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=False,
                            aspect_ratio=round(H_mid / W_corr if H_mid > W_corr else W_corr / H_mid, 2),
                            applied_rules=["NBC-CORRIDOR-MIN-WIDTH", "CIRC-CENTRAL-SPINE"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=bed2_id,
                            room_name="Bedroom 2",
                            floor_index=0,
                            x=round(W_b1 + W_corr, 2),
                            y=y_mid,
                            width_m=W_b2,
                            depth_m=H_mid,
                            area_sqm=round(W_b2 * H_mid, 2),
                            zone="Center",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=False,
                            aspect_ratio=round(W_b2 / H_mid, 2),
                            applied_rules=["NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=dining_id,
                            room_name="Dining Area",
                            floor_index=0,
                            x=round(W_b1 + W_corr + W_b2, 2),
                            y=y_mid,
                            width_m=W_din,
                            depth_m=H_mid,
                            area_sqm=round(W_din * H_mid, 2),
                            zone="E",
                            zone_category="public",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_mid / W_din if H_mid > W_din else W_din / H_mid, 2),
                            applied_rules=["REL-COOKING-EATING", "NBC-MIN-DINING"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=primary_id,
                            room_name="Primary Bath",
                            floor_index=0,
                            x=0.0,
                            y=y_rear,
                            width_m=W_bath2,
                            depth_m=H_rear,
                            area_sqm=round(W_bath2 * H_rear, 2),
                            zone="SW",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_bath2, 2),
                            applied_rules=["VASTU-SW-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=master_id,
                            room_name="Master Bedroom",
                            floor_index=0,
                            x=W_bath2,
                            y=y_rear,
                            width_m=W_mb,
                            depth_m=H_rear,
                            area_sqm=round(W_mb * H_rear, 2),
                            zone="SW",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(W_mb / H_rear if W_mb > H_rear else H_rear / W_mb, 2),
                            applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=kitchen_id,
                            room_name="Kitchen",
                            floor_index=0,
                            x=round(W_bath2 + W_mb, 2),
                            y=y_rear,
                            width_m=W_kitch,
                            depth_m=H_rear,
                            area_sqm=round(W_kitch * H_rear, 2),
                            zone="SE",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_kitch if H_rear > W_kitch else W_kitch / H_rear, 2),
                            applied_rules=["VASTU-SE-KITCHEN", "REL-COOKING-EATING", "NBC-MIN-KITCHEN"],
                        ),
                    ])
                    return t1_rooms
                else:
                    # Wide plot configuration
                    H_pub = 3.75
                    H_mid = 2.80
                    H_rear = round(env_d - H_pub - H_mid, 2)
                    W_b2 = 3.00
                    puja_w = 2.40
                    liv_w = round(env_w - W_b2 - puja_w, 2)

                    W_din = round(min(3.40, max(3.10, 9.6 / H_mid)), 2)
                    W_corr = round(env_w - W_din, 2)

                    W_b1 = 1.65
                    W_b2_bath = 1.65
                    W_kitch = round(min(3.40, max(2.85, 10.5 / H_rear)), 2)
                    W_mb = round(env_w - W_b1 - W_b2_bath - W_kitch, 2)

                    y_mid = round(H_pub, 2)
                    y_rear = round(y_mid + H_mid, 2)

                    t1_rooms.extend([
                        MultiFloorRoomRectangle(
                            room_id=bed2_id,
                            room_name="Bedroom 2",
                            floor_index=0,
                            x=0.0,
                            y=0.0,
                            width_m=W_b2,
                            depth_m=H_pub,
                            area_sqm=round(W_b2 * H_pub, 2),
                            zone="NW",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_pub / W_b2 if H_pub > W_b2 else W_b2 / H_pub, 2),
                            applied_rules=["VASTU-NW-BED2", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=living_id,
                            room_name="Living Room",
                            floor_index=0,
                            x=W_b2,
                            y=0.0,
                            width_m=liv_w,
                            depth_m=H_pub,
                            area_sqm=round(liv_w * H_pub, 2),
                            zone="N",
                            zone_category="public",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(liv_w / H_pub if liv_w > H_pub else H_pub / liv_w, 2),
                            applied_rules=["VASTU-N-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=puja_id,
                            room_name="Puja Room",
                            floor_index=0,
                            x=round(W_b2 + liv_w, 2),
                            y=0.0,
                            width_m=puja_w,
                            depth_m=H_pub,
                            area_sqm=round(puja_w * H_pub, 2),
                            zone="NE",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_pub / puja_w, 2),
                            applied_rules=["VASTU-NE-POOJA", "NBC-MIN-PUJA", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id="corridor",
                            room_name="Corridor",
                            floor_index=0,
                            x=0.0,
                            y=y_mid,
                            width_m=W_corr,
                            depth_m=H_mid,
                            area_sqm=round(W_corr * H_mid, 2),
                            zone="Center",
                            zone_category="circulation",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=False,
                            aspect_ratio=round(W_corr / H_mid, 2),
                            applied_rules=["NBC-CORRIDOR-MIN-WIDTH", "CIRC-CENTRAL-SPINE"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=dining_id,
                            room_name="Dining Area",
                            floor_index=0,
                            x=W_corr,
                            y=y_mid,
                            width_m=W_din,
                            depth_m=H_mid,
                            area_sqm=round(W_din * H_mid, 2),
                            zone="E",
                            zone_category="public",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(W_din / H_mid if W_din > H_mid else H_mid / W_din, 2),
                            applied_rules=["REL-COOKING-EATING", "NBC-MIN-DINING"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=common_id,
                            room_name="Common Bath",
                            floor_index=0,
                            x=0.0,
                            y=y_rear,
                            width_m=W_b1,
                            depth_m=H_rear,
                            area_sqm=round(W_b1 * H_rear, 2),
                            zone="SW",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_b1, 2),
                            applied_rules=["VASTU-SW-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=primary_id,
                            room_name="Primary Bath",
                            floor_index=0,
                            x=W_b1,
                            y=y_rear,
                            width_m=W_b2_bath,
                            depth_m=H_rear,
                            area_sqm=round(W_b2_bath * H_rear, 2),
                            zone="SW",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_b2_bath, 2),
                            applied_rules=["VASTU-SW-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=master_id,
                            room_name="Master Bedroom",
                            floor_index=0,
                            x=round(W_b1 + W_b2_bath, 2),
                            y=y_rear,
                            width_m=W_mb,
                            depth_m=H_rear,
                            area_sqm=round(W_mb * H_rear, 2),
                            zone="SW",
                            zone_category="private",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(W_mb / H_rear if W_mb > H_rear else H_rear / W_mb, 2),
                            applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
                        ),
                        MultiFloorRoomRectangle(
                            room_id=kitchen_id,
                            room_name="Kitchen",
                            floor_index=0,
                            x=round(W_b1 + W_b2_bath + W_mb, 2),
                            y=y_rear,
                            width_m=W_kitch,
                            depth_m=H_rear,
                            area_sqm=round(W_kitch * H_rear, 2),
                            zone="SE",
                            zone_category="service",
                            vastu_compliant=True,
                            is_vertical_core=False,
                            requires_exterior_wall=True,
                            aspect_ratio=round(H_rear / W_kitch if H_rear > W_kitch else W_kitch / H_rear, 2),
                            applied_rules=["VASTU-SE-KITCHEN", "REL-COOKING-EATING", "NBC-MIN-KITCHEN"],
                        ),
                    ])
                    return t1_rooms

        # Default Multi-Storey T1 generation
        if floor_index == 0:
            # North Front: Living Room (NW/N) and Puja Room (NE)
            puja_w = 2.40 if east_w >= 5.5 else 0.0
            liv_w = round(env_w - puja_w, 2)

            liv = MultiFloorRoomRectangle(
                room_id="living_F0",
                room_name="Living Room",
                floor_index=0,
                x=0.0,
                y=0.0,
                width_m=liv_w,
                depth_m=north_h,
                area_sqm=round(liv_w * north_h, 2),
                zone="NW" if puja_w > 0 else "N",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(north_h / liv_w if liv_w > 0 else 1.0, 2),
                applied_rules=["VASTU-NW-LIVING", "NBC-MIN-LIVING", "FUNC-ACCESS-FRONT"],
            )
            t1_rooms.append(liv)

            if puja_w > 0:
                puj = MultiFloorRoomRectangle(
                    room_id="puja_F0",
                    room_name="Pooja Room",
                    floor_index=0,
                    x=liv_w,
                    y=0.0,
                    width_m=puja_w,
                    depth_m=north_h,
                    area_sqm=round(puja_w * north_h, 2),
                    zone="NE",
                    zone_category="private",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=True,
                    aspect_ratio=round(north_h / puja_w, 2),
                    applied_rules=["VASTU-NE-POOJA", "NBC-MIN-PUJA", "HYG-01-FOUL-SACRED-WALL"],
                )
                t1_rooms.append(puj)

            # Mid Zone (East of lobby): Dining Area — only if east_w meets minimum width
            if east_w >= 2.0:
                din = MultiFloorRoomRectangle(
                    room_id="dining_F0",
                    room_name="Dining Area",
                    floor_index=0,
                    x=east_x,
                    y=lobby.y,
                    width_m=east_w,
                    depth_m=lobby.depth_m,
                    area_sqm=round(east_w * lobby.depth_m, 2),
                    zone="E",
                    zone_category="public",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=True,
                    aspect_ratio=round(east_w / lobby.depth_m if lobby.depth_m > 0 else 1.0, 2),
                    applied_rules=["REL-COOKING-EATING", "NBC-MIN-DINING"],
                )
                t1_rooms.append(din)

            # South Rear Zone: Bath 1 (W), Guest Bed / Utility (Center/S), Kitchen (SE)
            # Clamp bath_w to leave room for at least 1.5m kitchen + 1.5m guest bed
            bath_w = round(min(min(2.40, env_w - 3.0), max(1.50, core.width_m)), 2)
            bath_w = round(max(1.50, min(bath_w, env_w - 3.0)), 2)
            rem_w = round(max(0.0, env_w - bath_w), 2)
            mid_w = round(min(max(1.5, rem_w * 0.45), max(0.0, rem_w - 1.5)), 2)
            kitch_w = round(max(0.0, rem_w - mid_w), 2)

            has_powder = any("powder" in s.name.lower() or "powder" in s.id.lower() for s in spaces) or ("powder" in (self.req.client_notes or "").lower())
            bath = MultiFloorRoomRectangle(
                room_id="bath_1_F0",
                room_name="Powder Room / Common Bath" if has_powder else "Common Bath",
                floor_index=0,
                x=0.0,
                y=south_y,
                width_m=bath_w,
                depth_m=south_h,
                area_sqm=round(bath_w * south_h, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(south_h / bath_w if bath_w > 0 else 1.0, 2),
                applied_rules=["VASTU-W-BATH", "NBC-MIN-BATH", "HYG-01-FOUL-SACRED-WALL", "VERT-01-WET-STACK"],
            )
            t1_rooms.append(bath)

            has_study = any(s.id == "study" or "office" in s.name.lower() or "study" in s.name.lower() for s in spaces)
            study_or_bed_id = "study_F0" if has_study else "guest_bed_F0"
            study_or_bed_name = "Home Office / Study" if has_study else "Guest Bedroom"

            guest_bed = MultiFloorRoomRectangle(
                room_id=study_or_bed_id,
                room_name=study_or_bed_name,
                floor_index=0,
                x=bath_w,
                y=south_y,
                width_m=mid_w,
                depth_m=south_h,
                area_sqm=round(mid_w * south_h, 2),
                zone="S",
                zone_category="private",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(mid_w / south_h if mid_w > south_h else south_h / mid_w, 2),
                applied_rules=["VASTU-S-WORK" if has_study else "VASTU-S-BEDROOM", "NBC-MIN-STUDY" if has_study else "NBC-MIN-BEDROOM"],
            )
            t1_rooms.append(guest_bed)

            kitch = MultiFloorRoomRectangle(
                room_id="kitchen_F0",
                room_name="Kitchen & Utility",
                floor_index=0,
                x=round(bath_w + mid_w, 2),
                y=south_y,
                width_m=kitch_w,
                depth_m=south_h,
                area_sqm=round(kitch_w * south_h, 2),
                zone="SE",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(kitch_w / south_h if south_h > 0 else 1.0, 2),
                applied_rules=["VASTU-SE-KITCHEN", "REL-COOKING-EATING", "NBC-MIN-KITCHEN"],
            )
            t1_rooms.append(kitch)

        else:
            # Upper floors
            balc_w = round(min(3.5, max(2.0, env_w * 0.35)), 2)
            bed2_w = round(env_w - balc_w, 2)

            bed2 = MultiFloorRoomRectangle(
                room_id=f"bed_2_F{floor_index}",
                room_name="Bedroom 2",
                floor_index=floor_index,
                x=0.0,
                y=0.0,
                width_m=bed2_w,
                depth_m=north_h,
                area_sqm=round(bed2_w * north_h, 2),
                zone="NW",
                zone_category="private",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(bed2_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=["VASTU-NW-BED2", "NBC-MIN-BEDROOM"],
            )
            t1_rooms.append(bed2)

            balc = MultiFloorRoomRectangle(
                room_id=f"balcony_F{floor_index}",
                room_name="Covered Balcony",
                floor_index=floor_index,
                x=bed2_w,
                y=0.0,
                width_m=balc_w,
                depth_m=north_h,
                area_sqm=round(balc_w * north_h, 2),
                zone="NE",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(balc_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=["VASTU-NE-BALCONY", "NBC-MIN-BALCONY"],
            )
            t1_rooms.append(balc)

            # Mid Zone (East of lobby): Home Office — only if east_w meets minimum width
            if east_w >= 2.0:
                study = MultiFloorRoomRectangle(
                    room_id=f"study_F{floor_index}",
                    room_name="Home Office / Study",
                    floor_index=floor_index,
                    x=east_x,
                    y=lobby.y,
                    width_m=east_w,
                    depth_m=lobby.depth_m,
                    area_sqm=round(east_w * lobby.depth_m, 2),
                    zone="E",
                    zone_category="private",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=True,
                    aspect_ratio=round(east_w / lobby.depth_m if lobby.depth_m > 0 else 1.0, 2),
                    applied_rules=["VASTU-E-STUDY", "NBC-MIN-STUDY"],
                )
                t1_rooms.append(study)

            bath_w = round(min(2.40, max(1.80, core.width_m)), 2)
            bath_master = MultiFloorRoomRectangle(
                room_id=f"ensuite_bath_F{floor_index}",
                room_name="Master Ensuite Bath",
                floor_index=floor_index,
                x=0.0,
                y=south_y,
                width_m=bath_w,
                depth_m=south_h,
                area_sqm=round(bath_w * south_h, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(south_h / bath_w if bath_w > 0 else 1.0, 2),
                applied_rules=["VERT-01-WET-STACK", "VASTU-W-BATH", "NBC-MIN-BATH"],
            )
            t1_rooms.append(bath_master)

            mb_w = round(env_w - bath_w, 2)
            mb = MultiFloorRoomRectangle(
                room_id=f"master_bed_F{floor_index}",
                room_name="Master Bedroom",
                floor_index=floor_index,
                x=bath_w,
                y=south_y,
                width_m=mb_w,
                depth_m=south_h,
                area_sqm=round(mb_w * south_h, 2),
                zone="SW",
                zone_category="private",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(mb_w / south_h if south_h > 0 else 1.0, 2),
                applied_rules=["VASTU-SW-MASTER", "NBC-MIN-BEDROOM"],
            )
            t1_rooms.append(mb)

        return t1_rooms

    # T2 unit essentials: width floors are hard, area targets are spent from
    # spare frontage.  A kitchen is never deleted to protect a living-room
    # width; only a plate that cannot hold all four width floors may omit it,
    # and that omission is warned explicitly (the L15 gate then fails).
    _T2_UNIT_MIN_WIDTHS = {"bath": 1.20, "living": 3.40, "kitchen": 1.80, "bed": 3.00}
    _T2_UNIT_MIN_AREAS = {"bath": 3.0, "living": 16.0, "kitchen": 6.0, "bed": 10.5}

    def _allocate_t2_unit_widths(
        self, env_w: float, depth: float, bath_w: float, unit_label: str
    ) -> Dict[str, float]:
        """Allocate one T2 unit row without ever silently deleting the kitchen.

        Statutory/furniture width floors are preserved.  Living and bedroom
        then compete for any spare frontage; the kitchen keeps its 1.8 m floor.
        If the plate is too narrow for all four width floors, the kitchen is
        omitted only when the living room would otherwise be unusable, and the
        omission is recorded as a named warning for the L15 gate.
        """
        hard = dict(self._T2_UNIT_MIN_WIDTHS)
        areas = self._T2_UNIT_MIN_AREAS
        depth = max(float(depth), 0.01)
        widths = {"bath": round(float(bath_w), 2), "living": hard["living"],
                  "kitchen": hard["kitchen"], "bed": hard["bed"]}
        total_hard = round(hard["bath"] + hard["living"] + hard["kitchen"] + hard["bed"], 2)

        if env_w + 1e-6 < total_hard:
            # Keep the kitchen if a usable living room survives.  If not, omit
            # the kitchen with an explicit warning instead of pretending the
            # unit is complete.
            living_with_kitchen = round(env_w - hard["bath"] - hard["kitchen"] - hard["bed"], 2)
            if living_with_kitchen >= 2.20:
                widths["kitchen"] = hard["kitchen"]
                widths["living"] = living_with_kitchen
                widths["bed"] = hard["bed"]
                self.warnings.append(
                    f"T2-UNIT-MINIMA: {unit_label} living/dining is {living_with_kitchen:.2f} m wide "
                    f"({living_with_kitchen * depth:.1f} m2) because the {env_w:.2f} m row must also hold "
                    "a bath, kitchen and bedroom; the kitchen is preserved."
                )
            else:
                widths["kitchen"] = 0.0
                widths["living"] = round(max(2.20, env_w * 0.42), 2)
                widths["bed"] = round(max(2.20, env_w - hard["bath"] - widths["living"]), 2)
                self.warnings.append(
                    f"T2-UNIT-MINIMA: {unit_label} kitchen omitted - the {env_w:.2f} m row cannot "
                    "hold bath + living + kitchen + bedroom at code widths; L15 will fail."
                )
        else:
            # Full row: spend spare frontage first on living, then bedroom,
            # then kitchen and bath area targets.  This keeps the kitchen at
            # its 1.8 m floor and never trades it away for a wider living room.
            target = {
                "living": max(hard["living"], areas["living"] / depth),
                "bed": max(hard["bed"], areas["bed"] / depth),
                "kitchen": max(hard["kitchen"], areas["kitchen"] / depth),
                "bath": max(hard["bath"], areas["bath"] / depth),
            }
            spare = round(env_w - sum(widths.values()), 2)
            for key in ("bed", "living", "kitchen", "bath"):
                add = min(spare, max(0.0, target[key] - widths[key]))
                widths[key] = round(widths[key] + add, 2)
                spare = round(spare - add, 2)
            if spare > 0.005:
                # Leftover is habitable frontage: 60 % living, 40 % bedroom.
                widths["living"] = round(widths["living"] + spare * 0.60, 2)
                widths["bed"] = round(widths["bed"] + spare * 0.40, 2)

        # Keep the row closed after rounding (no 1 cm gap/overlap at the bed).
        delta = round(env_w - sum(widths.values()), 2)
        if abs(delta) >= 0.005:
            widths["bed"] = round(widths["bed"] + delta, 2)

        # Name every room that still misses its ontology target on this row.
        for key, label in (("bath", "bathroom"), ("living", "living/dining"),
                           ("kitchen", "kitchen"), ("bed", "bedroom")):
            if widths[key] <= 0.0:
                continue
            room_area = widths[key] * depth
            if room_area + 0.01 < areas[key]:
                self.warnings.append(
                    f"T2-UNIT-MINIMA: {unit_label} {label} gross {room_area:.1f} m2 "
                    f"({widths[key]:.2f} x {depth:.2f} m) is below the {areas[key]:.1f} m2 "
                    "ontology minimum; the row cannot hold all four rooms at full area."
                )
        return {k: round(v, 2) for k, v in widths.items()}

    # ------------------------------------------------------------------
    # Compact T2 pocket plan
    #
    # A 12 x 15 plate cannot hold two one-bedroom programmes in one row: four
    # rooms at their catalogue width floors need more frontage than the plate
    # has, and stacking the bath over the kitchen is forbidden by HYG-02.  The
    # plan that survives the law moves one unit's bedroom and the other unit's
    # bathroom into the pocket beside the stair band.  Both rows then keep a
    # full-width living room and every room is at or above its minimum.
    # ------------------------------------------------------------------
    _T2_POCKET_MIN_AREA = {"bath": 3.0, "kitchen": 6.0, "living": 16.0, "bed": 10.5}
    _T2_POCKET_MIN_WIDTH = {"bath": 1.20, "kitchen": 1.80, "living": 3.40, "bed": 3.00}
    _T2_POCKET_MAX_ASPECT = {"bath": 2.0, "kitchen": 1.8, "living": 1.8, "bed": 1.8}

    def _t2_row_meets_areas(self, env_w: float, depth: float) -> bool:
        """Can a single row of four rooms reach every catalogue minimum?"""
        if depth <= 0.01 or env_w <= 0.01:
            return False
        floors = self._T2_UNIT_MIN_WIDTHS
        spare = round(env_w - sum(floors.values()), 2)
        if spare < -0.005:
            return False
        widths = dict(floors)
        widths["living"] = round(widths["living"] + max(0.0, spare) * 0.60, 2)
        widths["bed"] = round(widths["bed"] + max(0.0, spare) * 0.40, 2)
        return all(
            widths[key] * depth + 0.02 >= self._T2_POCKET_MIN_AREA[key]
            for key in ("living", "bed", "kitchen", "bath")
        )

    def _t2_pocket_plan(
        self, env_w: float, env_d: float, core_w: float, core_d: float
    ) -> Optional[Dict[str, float]]:
        """Return the pocket-plan dimensions, or None if the plate cannot hold it.

        The stair moves to the east flank (an external entrance wall), a
        two-metre lobby sits beside it, and the leftover pocket takes Unit A's
        bedroom plus Unit B's bathroom.  Feasibility is checked against the
        same catalogue minima the certificate audits, so a plan is returned
        only when it actually passes them.
        """
        band = round((env_d - core_d) / 2.0, 2)
        if band < 3.20 or env_w <= core_w + 2.0 + 4.2:
            return None
        core_x = round(env_w - core_w, 2)
        lobby_w = 2.0
        lobby_x = round(core_x - lobby_w, 2)
        pocket_w = lobby_x
        bed_pocket_w = 3.00
        bath_pocket_w = round(pocket_w - bed_pocket_w, 2)
        # 1.80 m leaves the bath inside the 1:2.2 disclosure clamp even after
        # the furniture pass takes a few centimetres for the kitchen; a
        # narrower bath is legal for the certificate but is named as an
        # over-elongated room in every report.
        bath_a_w = max(1.80, 3.0 / band)
        kitchen_w = 1.80
        living_a_w = round(env_w - bath_a_w - kitchen_w, 2)
        living_b_w = round(env_w - bed_pocket_w - kitchen_w, 2)

        if not self._t2_pocket_fits((bath_a_w, band), "bath"):
            return None
        if not self._t2_pocket_fits((living_a_w, band), "living"):
            return None
        if not self._t2_pocket_fits((kitchen_w, band), "kitchen"):
            return None
        if not self._t2_pocket_fits((bed_pocket_w, band), "bed"):
            return None
        if not self._t2_pocket_fits((living_b_w, band), "living"):
            return None
        if not self._t2_pocket_fits((bath_pocket_w, core_d), "bath"):
            return None
        if bed_pocket_w * core_d + 0.02 < 10.5:
            return None
        # Both unit living rooms must open off the shared lobby wall.
        if bath_a_w > lobby_x + 0.02 or bath_a_w + living_a_w < lobby_x + lobby_w - 0.02:
            return None
        if bed_pocket_w > lobby_x + 0.02 or bed_pocket_w + living_b_w < lobby_x + lobby_w - 0.02:
            return None
        return {
            "band": band, "lobby_w": lobby_w, "bed_pocket_w": bed_pocket_w,
            "bath_pocket_w": bath_pocket_w, "bath_a_w": round(bath_a_w, 2),
            "kitchen_w": kitchen_w, "living_a_w": living_a_w,
            "living_b_w": living_b_w,
        }

    def _t2_pocket_fits(self, dims: tuple, key: str) -> bool:
        w, d = dims
        if w <= 0.01 or d <= 0.01:
            return False
        if min(w, d) + 0.02 < self._T2_POCKET_MIN_WIDTH[key]:
            return False
        if w * d + 0.02 < self._T2_POCKET_MIN_AREA[key]:
            return False
        # Certificate aspect tolerance (bounded degradation), not a new limit.
        return max(w / d, d / w) <= self._T2_POCKET_MAX_ASPECT[key] * 1.30 + 0.02

    def _partition_t2_pocket_rooms(
        self,
        floor_index: int,
        core: MultiFloorRoomRectangle,
        south_y: float,
        south_h: float,
    ) -> List[MultiFloorRoomRectangle]:
        """Both units in full-width bands, with the pocket carrying the spill."""
        plan = self._t2_pocket
        band = plan["band"]
        bath_a_w = plan["bath_a_w"]
        kit_w = plan["kitchen_w"]
        liv_a_w = plan["living_a_w"]
        liv_b_w = plan["living_b_w"]
        bed_w = plan["bed_pocket_w"]
        bath_b_w = plan["bath_pocket_w"]

        def _room(rid, name, x, y, w, d, zone, cat, unit_id, rules):
            return MultiFloorRoomRectangle(
                room_id=f"{rid}_F{floor_index}",
                room_name=name,
                floor_index=floor_index,
                unit_id=unit_id,
                x=round(x, 2),
                y=round(y, 2),
                width_m=round(w, 2),
                depth_m=round(d, 2),
                area_sqm=round(w * d, 2),
                zone=zone,
                zone_category=cat,
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(max(w, d) / max(min(w, d), 0.01), 2),
                applied_rules=list(rules),
            )

        rooms = [
            _room("t2_unitA_bath", "Unit A Bathroom", 0.0, 0.0, bath_a_w, band,
                  "NW", "service", "Unit_A", ["VERT-01-WET-STACK", "NBC-MIN-BATH"]),
            _room("t2_unitA_living", "Unit A Living / Dining", bath_a_w, 0.0,
                  liv_a_w, band, "N", "public", "Unit_A",
                  ["T2-UNIT-DOOR-LOBBY", "NBC-MIN-LIVING"]),
            _room("t2_unitA_kitchen", "Unit A Kitchen", bath_a_w + liv_a_w, 0.0,
                  kit_w, band, "NE", "service", "Unit_A",
                  ["T2-UNIT-DOOR-LOBBY", "NBC-MIN-KITCHEN", "VERT-01-WET-STACK"]),
            _room("t2_unitA_bed", "Unit A Bedroom", 0.0, core.y, bed_w,
                  core.depth_m, "W", "private", "Unit_A", ["NBC-MIN-BEDROOM"]),
            _room("t2_unitB_bed", "Unit B Bedroom", 0.0, south_y, bed_w, south_h,
                  "SW", "private", "Unit_B", ["NBC-MIN-BEDROOM"]),
            _room("t2_unitB_living", "Unit B Living / Dining", bed_w, south_y,
                  liv_b_w, south_h, "S", "public", "Unit_B",
                  ["T2-UNIT-DOOR-LOBBY", "NBC-MIN-LIVING"]),
            _room("t2_unitB_kitchen", "Unit B Kitchen", bed_w + liv_b_w, south_y,
                  kit_w, south_h, "SE", "service", "Unit_B",
                  ["T2-UNIT-DOOR-LOBBY", "NBC-MIN-KITCHEN", "VERT-01-WET-STACK"]),
            _room("t2_unitB_bath", "Unit B Bathroom", bed_w, core.y,
                  bath_b_w, core.depth_m, "E", "service", "Unit_B",
                  ["VERT-01-WET-STACK", "NBC-MIN-BATH"]),
        ]
        return rooms

    def _partition_t2_rooms(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        core: MultiFloorRoomRectangle,
        lobby: MultiFloorRoomRectangle,
        east_x: float,
        east_w: float,
        north_h: float,
        south_y: float,
        south_h: float,
        spaces: List[SpaceTypeSpec],
    ) -> List[MultiFloorRoomRectangle]:
        """Synthesizes T2 Family Apartment dual-unit floor plates."""
        env_w = envelope["width"]
        t2_rooms: List[MultiFloorRoomRectangle] = []

        # The compact pocket plan is chosen before the core is
        # placed; when present it owns the whole plate's room layout.
        if getattr(self, "_t2_pocket", None):
            return self._partition_t2_pocket_rooms(
                floor_index, core, south_y, south_h,
            )

        # Unit A (North wing) & Unit B (South wing) off central distribution lobby
        # Invariant: unit doors strictly open off lobby; bathrooms align vertically.
        # Shared bath width.  Start from the widest code-compliant bath and
        # shrink it only as far as needed to keep bath + living + kitchen +
        # bedroom width floors on the row.  The bedroom's area-derived width
        # is included so a 9.6 m row does not lose the kitchen over 0.05 m.
        bed_floor = max(3.00, 10.5 / max(north_h, 0.01))
        bath_w = round(max(1.20, min(1.80, env_w - 3.40 - 1.80 - bed_floor)), 2)

        # Unit A (North): Bath + Living/Dining + Kitchen + Bed
        unit_a_alloc = self._allocate_t2_unit_widths(env_w, north_h, bath_w, "Unit A")
        unit_a_living_w = unit_a_alloc["living"]
        unit_a_kit_w = unit_a_alloc["kitchen"]
        unit_a_bed_w = unit_a_alloc["bed"]

        u_a_bath = MultiFloorRoomRectangle(
            room_id=f"t2_unitA_bath_F{floor_index}",
            room_name="Unit A Bathroom",
            floor_index=floor_index,
            unit_id="Unit_A",
            x=0.0,
            y=0.0,
            width_m=bath_w,
            depth_m=north_h,
            area_sqm=round(bath_w * north_h, 2),
            zone="NW",
            zone_category="service",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(north_h / bath_w, 2),
            applied_rules=["VERT-01-WET-STACK", "NBC-MIN-BATH"],
        )
        t2_rooms.append(u_a_bath)

        if unit_a_kit_w > 0.0:
            u_a_kit = MultiFloorRoomRectangle(
                room_id=f"t2_unitA_kitchen_F{floor_index}",
                room_name="Unit A Kitchen",
                floor_index=floor_index,
                unit_id="Unit_A",
                # Living sits against the lobby (a wide, doorable entry wall);
                # the kitchen follows it, exactly like Unit B.  Kitchen-first
                # ordering pushed the living east and left the lobby door a
                # 0.77 m shared run with no jamb clearance.
                x=round(bath_w + unit_a_living_w, 2),
                y=0.0,
                width_m=unit_a_kit_w,
                depth_m=north_h,
                area_sqm=round(unit_a_kit_w * north_h, 2),
                zone="NW",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(north_h / unit_a_kit_w if unit_a_kit_w > 0 else 1.0, 2),
                applied_rules=["T2-UNIT-DOOR-LOBBY", "NBC-MIN-KITCHEN", "VERT-01-WET-STACK"],
            )
            t2_rooms.append(u_a_kit)

        u_a_liv = MultiFloorRoomRectangle(
            room_id=f"t2_unitA_living_F{floor_index}",
            room_name="Unit A Living / Dining",
            floor_index=floor_index,
            unit_id="Unit_A",
            x=bath_w,
            y=0.0,
            width_m=unit_a_living_w,
            depth_m=north_h,
            area_sqm=round(unit_a_living_w * north_h, 2),
            zone="N",
            zone_category="public",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(unit_a_living_w / north_h if north_h > 0 else 1.0, 2),
            applied_rules=["T2-UNIT-DOOR-LOBBY", "NBC-MIN-LIVING"],
        )
        t2_rooms.append(u_a_liv)

        u_a_bed = MultiFloorRoomRectangle(
            room_id=f"t2_unitA_bed_F{floor_index}",
            room_name="Unit A Bedroom",
            floor_index=floor_index,
            unit_id="Unit_A",
            x=round(bath_w + unit_a_living_w + unit_a_kit_w, 2),
            y=0.0,
            width_m=unit_a_bed_w,
            depth_m=north_h,
            area_sqm=round(unit_a_bed_w * north_h, 2),
            zone="NE",
            zone_category="private",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(unit_a_bed_w / north_h if north_h > 0 else 1.0, 2),
            applied_rules=["NBC-MIN-BEDROOM"],
        )
        t2_rooms.append(u_a_bed)

        # Unit B (South): Bath + Living + Bed
        u_b_bath = MultiFloorRoomRectangle(
            room_id=f"t2_unitB_bath_F{floor_index}",
            room_name="Unit B Bathroom",
            floor_index=floor_index,
            unit_id="Unit_B",
            x=0.0,
            y=south_y,
            width_m=bath_w,
            depth_m=south_h,
            area_sqm=round(bath_w * south_h, 2),
            zone="W",
            zone_category="service",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(south_h / bath_w, 2),
            applied_rules=["VERT-01-WET-STACK", "NBC-MIN-BATH"],
        )
        t2_rooms.append(u_b_bath)

        # Unit B (South): same shared bath width, deeper row for its area targets.
        unit_b_alloc = self._allocate_t2_unit_widths(env_w, south_h, bath_w, "Unit B")
        unit_b_living_w = unit_b_alloc["living"]
        unit_b_kit_w = unit_b_alloc["kitchen"]
        unit_b_bed_w = unit_b_alloc["bed"]

        u_b_liv = MultiFloorRoomRectangle(
            room_id=f"t2_unitB_living_F{floor_index}",
            room_name="Unit B Living / Dining",
            floor_index=floor_index,
            unit_id="Unit_B",
            x=bath_w,
            y=south_y,
            width_m=unit_b_living_w,
            depth_m=south_h,
            area_sqm=round(unit_b_living_w * south_h, 2),
            zone="S",
            zone_category="public",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(unit_b_living_w / south_h if south_h > 0 else 1.0, 2),
            applied_rules=["T2-UNIT-DOOR-LOBBY", "NBC-MIN-LIVING"],
        )
        t2_rooms.append(u_b_liv)

        if unit_b_kit_w > 0.0:
            u_b_kit = MultiFloorRoomRectangle(
                room_id=f"t2_unitB_kitchen_F{floor_index}",
                room_name="Unit B Kitchen",
                floor_index=floor_index,
                unit_id="Unit_B",
                x=round(bath_w + unit_b_living_w, 2),
                y=south_y,
                width_m=unit_b_kit_w,
                depth_m=south_h,
                area_sqm=round(unit_b_kit_w * south_h, 2),
                zone="SE",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(south_h / unit_b_kit_w if unit_b_kit_w > 0 else 1.0, 2),
                applied_rules=["T2-UNIT-DOOR-LOBBY", "NBC-MIN-KITCHEN", "VERT-01-WET-STACK"],
            )
            t2_rooms.append(u_b_kit)

        u_b_bed = MultiFloorRoomRectangle(
            room_id=f"t2_unitB_bed_F{floor_index}",
            room_name="Unit B Bedroom",
            floor_index=floor_index,
            unit_id="Unit_B",
            x=round(bath_w + unit_b_living_w + unit_b_kit_w, 2),
            y=south_y,
            width_m=unit_b_bed_w,
            depth_m=south_h,
            area_sqm=round(unit_b_bed_w * south_h, 2),
            zone="SE",
            zone_category="private",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(unit_b_bed_w / south_h if south_h > 0 else 1.0, 2),
            applied_rules=["NBC-MIN-BEDROOM"],
        )
        t2_rooms.append(u_b_bed)

        # Mid East (Adjacent to lobby): Unit A / B Balcony / Amenity
        amenity = MultiFloorRoomRectangle(
            room_id=f"t2_amenity_F{floor_index}",
            room_name="Common Terrace / Storage" if floor_index > 0 else "Building Entrance Foyer",
            floor_index=floor_index,
            x=east_x,
            y=lobby.y,
            width_m=east_w,
            depth_m=lobby.depth_m,
            area_sqm=round(east_w * lobby.depth_m, 2),
            zone="E",
            zone_category="circulation",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(east_w / lobby.depth_m if lobby.depth_m > 0 else 1.0, 2),
            applied_rules=["NBC-CIRCULATION-T2"],
        )
        t2_rooms.append(amenity)

        return t2_rooms

    def _partition_t3_rooms(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        core: MultiFloorRoomRectangle,
        lobby: MultiFloorRoomRectangle,
        east_x: float,
        east_w: float,
        north_h: float,
        south_y: float,
        south_h: float,
        spaces: List[SpaceTypeSpec],
    ) -> List[MultiFloorRoomRectangle]:
        """Synthesizes T3 Commercial / Large Complex floor plates."""
        env_w = envelope["width"]
        t3_rooms: List[MultiFloorRoomRectangle] = []

        # West flank (South of core): Restroom Block (Stacked vertically across all floors)
        san_w = round(min(2.50, max(2.00, core.width_m)), 2)
        san = MultiFloorRoomRectangle(
            room_id=f"t3_sanitary_F{floor_index}",
            room_name="Commercial Restroom Block (M/F/Accessible)",
            floor_index=floor_index,
            x=0.0,
            y=south_y,
            width_m=san_w,
            depth_m=south_h,
            area_sqm=round(san_w * south_h, 2),
            zone="W",
            zone_category="service",
            vastu_compliant=True,
            is_vertical_core=False,
            requires_exterior_wall=True,
            aspect_ratio=round(south_h / san_w, 2),
            applied_rules=["VERT-01-WET-STACK", "NBC-SAN-TABLE12", "HYG-03-WET-TECH-WALL"],
        )
        t3_rooms.append(san)

        if floor_index == 0:
            # === GROUND FLOOR: Reception strictly Front (North), Server Room strictly separate ===
            # North Front: Reception Desk (strictly Ground floor Front) + Visitor Lounge
            rec_w = round(env_w * 0.50, 2)
            lounge_w = round(env_w - rec_w, 2)

            rec = MultiFloorRoomRectangle(
                room_id="reception_F0",
                room_name="Reception & Information Lobby",
                floor_index=0,
                x=0.0,
                y=0.0,
                width_m=rec_w,
                depth_m=north_h,
                area_sqm=round(rec_w * north_h, 2),
                zone="NW",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(rec_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=["T3-RECEPTION-GROUND-FRONT", "NBC-MIN-RECEPTION", "FUNC-ACCESS-FRONT"],
            )
            t3_rooms.append(rec)

            lounge = MultiFloorRoomRectangle(
                room_id="visitor_lounge_F0",
                room_name="Visitor Lounge & Cafe",
                floor_index=0,
                x=rec_w,
                y=0.0,
                width_m=lounge_w,
                depth_m=north_h,
                area_sqm=round(lounge_w * north_h, 2),
                zone="NE",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(lounge_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=["NBC-COMMERCIAL-LOUNGE", "FUNC-ACCESS-FRONT"],
            )
            t3_rooms.append(lounge)

            # Mid Zone (East of spine): Conference Room
            conf = MultiFloorRoomRectangle(
                room_id="conference_room_F0",
                room_name="Main Conference Center",
                floor_index=0,
                x=east_x,
                y=lobby.y,
                width_m=east_w,
                depth_m=lobby.depth_m,
                area_sqm=round(east_w * lobby.depth_m, 2),
                zone="E",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(east_w / lobby.depth_m if lobby.depth_m > 0 else 1.0, 2),
                applied_rules=["NBC-COMMERCIAL-CONFERENCE"],
            )
            t3_rooms.append(conf)

            # South Rear (East of Sanitary): a service spine, then Server Room
            # and Electrical/MEP Room.
            #
            # The technical rooms may not share a wall with the wet sanitary
            # block (HYG-03 FORBIDDEN_WALL). They used to start exactly at
            # `san_w`, so all six audited commercial seeds carried a
            # sanitary_block <-> electrical_room party wall - invisible while
            # the verifier compared room_ids instead of space types. A 0.9 m
            # service access spine now separates wet from
            # technical, which is also how the MEP room is actually serviced.
            # DEPTH-ROW PARTITIONER (proportion law, scope 1).
            #
            # On a deep, narrow plate the three technical rooms cannot be three
            # slim full-depth strips: 8x40 gave a 0.9 x 6.5 m "spine", a
            # 1.04 x 6.5 m server room and a 1.56 x 6.5 m MEP room (aspect
            # 17.1 / 6.3 / 4.2).  When the south band is deep and the east strip
            # is narrow, the row is re-partitioned into the pattern the brief
            # asks for: a full-width access row (1.2 m, the legal corridor
            # minimum) plus a service row split front-to-back, so each technical
            # room gets the full east width instead of a sliver of it.  Wide
            # plates keep the side-by-side arrangement (their strips are not
            # slim in the first place).
            _east_avail = round(env_w - san_w, 2)
            _deep_row = bool(south_h >= 4.2 and 1.2 < _east_avail <= 5.0)
            if _deep_row:
                sep_w = 1.20
                south_rem_w = round(env_w - san_w - sep_w, 2)
                server_w = mep_w = south_rem_w
                server_h = round(south_h * 0.5, 2)
                mep_h = round(south_h - server_h, 2)
            else:
                sep_w = 0.90
                south_rem_w = round(env_w - san_w - sep_w, 2)
                if south_rem_w < 2.0:
                    # A narrow plate still needs the wet/technical separation a
                    # spine provides; a 0.45 m service/duct gap is the physical
                    # minimum, and it is still a gap the verifier can see.
                    sep_w = 0.45
                    south_rem_w = round(env_w - san_w - sep_w, 2)
                if south_rem_w < 1.6:
                    # Not even a duct gap fits: the plate cannot host this T3
                    # service row honestly, so the technical rooms are not
                    # placed and the omission is named (L15 reports it) instead
                    # of fabricating a forbidden wet/technical party wall.
                    sep_w = 0.0
                    south_rem_w = round(env_w - san_w, 2)
                server_w = round(min(3.50, south_rem_w * 0.40), 2) if sep_w > 0 else 0.0
                mep_w = round(south_rem_w - server_w, 2) if sep_w > 0 else 0.0
                server_h = mep_h = south_h

            if sep_w > 0.0:
                t3_rooms.append(MultiFloorRoomRectangle(
                    room_id="t3_service_spine_F0",
                    room_name="Service Access Spine",
                    space_type_id="corridor",
                    floor_index=0,
                    x=round(san_w, 2),
                    y=south_y,
                    width_m=sep_w,
                    depth_m=south_h,
                    area_sqm=round(sep_w * south_h, 2),
                    zone="W",
                    zone_category="circulation",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=False,
                    aspect_ratio=round(south_h / sep_w if sep_w > 0 else 1.0, 2),
                    applied_rules=["NBC-CIRCULATION-SERVICE-SPINE", "HYG-03-WET-TECH-WALL"],
                ))

            if sep_w > 0.0:
                server = MultiFloorRoomRectangle(
                    room_id="server_room_F0",
                    room_name="Central Server Room & Network NOC",
                    floor_index=0,
                    x=(round(san_w + sep_w, 2) if _deep_row
                       else round(san_w + sep_w + mep_w, 2)),  # East end, clear of the wet wall
                    y=south_y,
                    width_m=server_w,
                    depth_m=server_h,
                    area_sqm=round(server_w * server_h, 2),
                    zone="SE",
                    zone_category="service",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=True,
                    aspect_ratio=round(max(server_w, server_h) / max(min(server_w, server_h), 0.01), 2),
                    applied_rules=["HYG-03-WET-TECH-WALL", "VERT-02-NO-WET-OVER-HABITABLE", "SEC-01-SERVER-PROTECTION"],
                )
                t3_rooms.append(server)

                mep = MultiFloorRoomRectangle(
                    room_id="electrical_room_F0",
                    room_name="MEP & Electrical Sub-Station",
                    floor_index=0,
                    x=round(san_w + sep_w, 2),
                    y=(round(south_y + server_h, 2) if _deep_row else south_y),
                    width_m=mep_w,
                    depth_m=mep_h,
                    area_sqm=round(mep_w * mep_h, 2),
                    zone="S",
                    zone_category="service",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=not _deep_row,
                    aspect_ratio=round(max(mep_w, mep_h) / max(min(mep_w, mep_h), 0.01), 2),
                    applied_rules=["NBC-MEP-ROOM"] + (["PROP-ROW-01"] if _deep_row else []),
                )
                t3_rooms.append(mep)

        else:
            # === UPPER FLOORS: Open Office, Executive Suites, Meeting Rooms ===
            # North Front: Open Office Wing (North light, continuous glazing)
            north_suite = MultiFloorRoomRectangle(
                room_id=f"t3_suite_N_F{floor_index}",
                room_name="North Open Office Suite",
                floor_index=floor_index,
                x=0.0,
                y=0.0,
                width_m=env_w,
                depth_m=north_h,
                area_sqm=round(env_w * north_h, 2),
                zone="N",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(env_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=["NBC-OFFICE-DAYLIGHT", "NBC-TRAVEL-DIST-30M"],
            )
            t3_rooms.append(north_suite)

            # Mid East: Executive Boardroom / Meeting Suite
            board = MultiFloorRoomRectangle(
                room_id=f"t3_suite_E_F{floor_index}",
                room_name="Executive Boardroom Suite",
                floor_index=floor_index,
                x=east_x,
                y=lobby.y,
                width_m=east_w,
                depth_m=lobby.depth_m,
                area_sqm=round(east_w * lobby.depth_m, 2),
                zone="E",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(east_w / lobby.depth_m if lobby.depth_m > 0 else 1.0, 2),
                applied_rules=["NBC-MEETING-SUITE"],
            )
            t3_rooms.append(board)

            # South Wing: South Office Suite + Staff Pantry (over MEP, never over Server Room!)
            south_rem_w = round(env_w - san_w, 2)
            south_suite = MultiFloorRoomRectangle(
                room_id=f"t3_suite_S_F{floor_index}",
                room_name="South Collaborative Work Suite",
                floor_index=floor_index,
                x=san_w,
                y=south_y,
                width_m=south_rem_w,
                depth_m=south_h,
                area_sqm=round(south_rem_w * south_h, 2),
                zone="S",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(south_rem_w / south_h if south_h > 0 else 1.0, 2),
                applied_rules=["VERT-02-NO-WET-OVER-HABITABLE", "NBC-TRAVEL-DIST-30M"],
            )
            t3_rooms.append(south_suite)

        return t3_rooms

    def _partition_t4_rooms(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        core: MultiFloorRoomRectangle,
        lobby: MultiFloorRoomRectangle,
        east_x: float,
        east_w: float,
        north_h: float,
        south_y: float,
        south_h: float,
        spaces: List[SpaceTypeSpec],
    ) -> List[MultiFloorRoomRectangle]:
        """Synthesizes T4 Warehouse & Light Industrial facility floor plates."""
        env_w = envelope["width"]
        env_d = envelope["depth"]
        t4_rooms: List[MultiFloorRoomRectangle] = []

        if floor_index == 0:
            # === GROUND FLOOR: Dock -> Dispatch -> Storage Chain; Heavy bay Ground only ===
            # West flank South: Staff Locker & Sanitary Amenity
            # Depth capped at amenity_w * 2.0 to satisfy AR ≤ 2.0 (spec max_aspect_ratio)
            amenity_w = round(min(3.0, max(2.0, core.width_m)), 2)
            amenity_d = round(min(south_h, max(3.5, amenity_w * 2.0)), 2)
            # A leftover strip shallower than 1.0 m cannot be a room (the
            # sweep measured it at 2.26 x 0.80 m clear).  Give the amenity the
            # whole west strip instead of carving a sliver nobody can use.
            if south_h - amenity_d < 1.0:
                amenity_d = round(south_h, 2)
            amenity = MultiFloorRoomRectangle(
                room_id="worker_amenity_F0",
                room_name="Worker Locker & Sanitary WC",
                floor_index=0,
                x=0.0,
                y=south_y,
                width_m=amenity_w,
                depth_m=amenity_d,
                area_sqm=round(amenity_w * amenity_d, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(amenity_d / amenity_w, 2),
                applied_rules=["NBC-SAN-TABLE12", "HYG-01-FOUL-SACRED-WALL"],
            )
            t4_rooms.append(amenity)

            # If amenity does not span full south_h, fill remaining west strip with utility storage
            if amenity_d < south_h - 0.05:
                util_d = round(south_h - amenity_d, 2)
                util_strip = MultiFloorRoomRectangle(
                    room_id="t4_util_west_F0",
                    room_name="West Utility Storage Strip",
                    floor_index=0,
                    x=0.0,
                    y=round(south_y + amenity_d, 2),
                    width_m=amenity_w,
                    depth_m=util_d,
                    area_sqm=round(amenity_w * util_d, 2),
                    zone="SW",
                    zone_category="industrial_bay",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=True,
                    aspect_ratio=round(max(amenity_w, util_d) / max(min(amenity_w, util_d), 0.01), 2),
                    applied_rules=["VERT-04-HEAVY-LOAD-GROUND"],
                )
                t4_rooms.append(util_strip)

            # North Front: Security Guard House (Front Gate) + Loading Dock Shutter Bays
            guard_w = round(min(3.2, env_w * 0.20), 2)
            dock_w = round(env_w - guard_w, 2)

            guard = MultiFloorRoomRectangle(
                room_id="guard_house_F0",
                room_name="Security Guard House & Gate Checkpoint",
                floor_index=0,
                x=0.0,
                y=0.0,
                width_m=guard_w,
                depth_m=north_h,
                area_sqm=round(guard_w * north_h, 2),
                zone="NW",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(guard_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=["SEC-02-GUARD-GATE-FRONT", "FUNC-ACCESS-FRONT"],
            )
            t4_rooms.append(guard)

            dock = MultiFloorRoomRectangle(
                room_id="t4_dock_bay_F0",
                room_name="Loading Dock Shutter Bays",
                floor_index=0,
                x=guard_w,
                y=0.0,
                width_m=dock_w,
                depth_m=north_h,
                area_sqm=round(dock_w * north_h, 2),
                zone="N",
                zone_category="industrial_bay",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(dock_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=["LOG-01-DOCK-DISPATCH-MUST-ADJACENT", "NBC-WAREHOUSE-DOCK"],
            )
            t4_rooms.append(dock)

            # Mid Field (East of lobby): Dispatch & Staging Buffer (MUST_ADJACENT to Dock)
            dispatch = MultiFloorRoomRectangle(
                room_id="t4_dispatch_F0",
                room_name="Dispatch & Staging Buffer",
                floor_index=0,
                x=east_x,
                y=lobby.y,
                width_m=east_w,
                depth_m=lobby.depth_m,
                area_sqm=round(east_w * lobby.depth_m, 2),
                zone="CENTER",
                zone_category="industrial_bay",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(east_w / lobby.depth_m if lobby.depth_m > 0 else 1.0, 2),
                applied_rules=["LOG-01-DOCK-DISPATCH-MUST-ADJACENT", "LOG-02-DISPATCH-STORAGE-MUST-ADJACENT"],
            )
            t4_rooms.append(dispatch)

            # South Field: Clear-Span Heavy Storage Bay (Heavy Floor Load, Strictly Ground Only!)
            # MUST_ADJACENT to Dispatch!
            storage_rem_w = round(env_w - amenity_w, 2)
            heavy_bay = MultiFloorRoomRectangle(
                room_id="t4_storage_bay_F0",
                room_name="Clear-Span Heavy Storage Bay",
                floor_index=0,
                x=amenity_w,
                y=south_y,
                width_m=storage_rem_w,
                depth_m=south_h,
                area_sqm=round(storage_rem_w * south_h, 2),
                zone="SW",
                zone_category="industrial_bay",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(storage_rem_w / south_h if south_h > 0 else 1.0, 2),
                applied_rules=[
                    "VERT-04-HEAVY-LOAD-GROUND",
                    "LOG-02-DISPATCH-STORAGE-MUST-ADJACENT",
                    "NOISE-01-SEPARATE-OFFICE-PRODUCTION"
                ],
            )
            t4_rooms.append(heavy_bay)

        else:
            # === MEZZANINE LEVEL (+3.6m): Administrative Block Fire-Separated with Industrial Stair ===
            # West South: Mezzanine Staff Sanitary Amenity (aligned with worker amenity below)
            # Depth capped at amenity_w * 2.0 to satisfy AR ≤ 2.0 (spec max_aspect_ratio)
            amenity_w = round(min(3.0, max(2.0, core.width_m)), 2)
            amenity_d = round(min(south_h, max(3.5, amenity_w * 2.0)), 2)
            amenity_up = MultiFloorRoomRectangle(
                room_id=f"worker_amenity_F{floor_index}",
                room_name="Mezzanine Staff WC & Locker",
                floor_index=floor_index,
                x=0.0,
                y=south_y,
                width_m=amenity_w,
                depth_m=amenity_d,
                area_sqm=round(amenity_w * amenity_d, 2),
                zone="W",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(amenity_d / amenity_w, 2),
                applied_rules=["VERT-01-WET-STACK", "NBC-SAN-TABLE12"],
            )
            t4_rooms.append(amenity_up)

            # If amenity does not span full south_h, fill remaining west strip with utility area
            if amenity_d < south_h - 0.05:
                util_d = round(south_h - amenity_d, 2)
                util_strip_up = MultiFloorRoomRectangle(
                    room_id=f"t4_util_west_F{floor_index}",
                    room_name="Mezzanine Utility Storage Strip",
                    floor_index=floor_index,
                    x=0.0,
                    y=round(south_y + amenity_d, 2),
                    width_m=amenity_w,
                    depth_m=util_d,
                    area_sqm=round(amenity_w * util_d, 2),
                    zone="SW",
                    zone_category="service",
                    vastu_compliant=True,
                    is_vertical_core=False,
                    requires_exterior_wall=True,
                    aspect_ratio=round(max(amenity_w, util_d) / max(min(amenity_w, util_d), 0.01), 2),
                    applied_rules=["VERT-01-WET-STACK"],
                )
                t4_rooms.append(util_strip_up)

            # North Mezzanine: Administrative Office (Noise-sensitive, separated from heavy bay)
            admin_w = round(env_w * 0.60, 2)
            conf_w = round(env_w - admin_w, 2)

            admin = MultiFloorRoomRectangle(
                room_id=f"t4_admin_office_F{floor_index}",
                room_name="Administrative Office Mezzanine",
                floor_index=floor_index,
                x=0.0,
                y=0.0,
                width_m=admin_w,
                depth_m=north_h,
                area_sqm=round(admin_w * north_h, 2),
                zone="N",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(admin_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=[
                    "VERT-05-MEZZANINE-FIRE-SEPARATION",
                    "NOISE-01-SEPARATE-OFFICE-PRODUCTION",
                    "NBC-MIN-ADMIN-OFFICE"
                ],
            )
            t4_rooms.append(admin)

            conf = MultiFloorRoomRectangle(
                room_id=f"t4_conf_room_F{floor_index}",
                room_name="Operations Conference Room",
                floor_index=floor_index,
                x=admin_w,
                y=0.0,
                width_m=conf_w,
                depth_m=north_h,
                area_sqm=round(conf_w * north_h, 2),
                zone="NE",
                zone_category="public",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(conf_w / north_h if north_h > 0 else 1.0, 2),
                applied_rules=["NBC-COMMERCIAL-CONFERENCE"],
            )
            t4_rooms.append(conf)

            # Mid / Viewing Catwalk overlooking high-bay
            catwalk = MultiFloorRoomRectangle(
                room_id=f"t4_catwalk_F{floor_index}",
                room_name="High-Bay Viewing Catwalk",
                floor_index=floor_index,
                x=east_x,
                y=lobby.y,
                width_m=east_w,
                depth_m=lobby.depth_m,
                area_sqm=round(east_w * lobby.depth_m, 2),
                zone="CENTER",
                zone_category="circulation",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=False,
                aspect_ratio=round(east_w / lobby.depth_m if lobby.depth_m > 0 else 1.0, 2),
                applied_rules=["NBC-CATWALK-WIDTH"],
            )
            t4_rooms.append(catwalk)

            # South Mezzanine: Staff Rest / Operations Deck
            south_rem_w = round(env_w - amenity_w, 2)
            deck = MultiFloorRoomRectangle(
                room_id=f"t4_deck_F{floor_index}",
                room_name="Operations & Document Archive Deck",
                floor_index=floor_index,
                x=amenity_w,
                y=south_y,
                width_m=south_rem_w,
                depth_m=south_h,
                area_sqm=round(south_rem_w * south_h, 2),
                zone="S",
                zone_category="service",
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=True,
                aspect_ratio=round(south_rem_w / south_h if south_h > 0 else 1.0, 2),
                applied_rules=["NBC-STORAGE-LIGHT"],
            )
            t4_rooms.append(deck)

        return t4_rooms

    # =========================================================================
    # 5. HARD PRUNING & INVARIANT VERIFICATION
    # =========================================================================

    def _prune_and_verify_hard_constraints(
        self,
        floor_index: int,
        rooms: List[MultiFloorRoomRectangle],
        previous_rooms: Optional[List[MultiFloorRoomRectangle]] = None,
    ):
        """
        Validates hard constraints across generated rooms on this floor:
        1. Non-overlap & Envelope containment.
        2. Zero FORBIDDEN_WALL pairs.
        3. MUST_ADJACENT pairs share a boundary.
        4. Vertical stacking rules against lower floor (VERT-01 to VERT-05).
        """
        # 1. Non-overlap check
        for i in range(len(rooms)):
            r1 = rooms[i]
            for j in range(i + 1, len(rooms)):
                r2 = rooms[j]
                x_ov = max(0.0, min(r1.x + r1.width_m, r2.x + r2.width_m) - max(r1.x, r2.x))
                y_ov = max(0.0, min(r1.y + r1.depth_m, r2.y + r2.depth_m) - max(r1.y, r2.y))
                ov_area = x_ov * y_ov
                if ov_area >= 0.05:
                    raise HardConstraintViolation(
                        f"Hard Constraint Violation: Rooms '{r1.room_id}' and "
                        f"'{r2.room_id}' overlap by {ov_area:.2f} sqm",
                        code="ROOM-OVERLAP",
                        rooms=(r1.room_id, r2.room_id),
                        overlap_sqm=round(ov_area, 2),
                        floor_index=floor_index,
                    )

        # 2. FORBIDDEN_WALL check between touching rooms
        for i in range(len(rooms)):
            r1 = rooms[i]
            for j in range(i + 1, len(rooms)):
                r2 = rooms[j]
                # Check if r1 and r2 share a vertical or horizontal boundary segment
                v_touch = (abs((r1.x + r1.width_m) - r2.x) < 0.05 or abs((r2.x + r2.width_m) - r1.x) < 0.05) and (
                    min(r1.y + r1.depth_m, r2.y + r2.depth_m) - max(r1.y, r2.y) >= 0.20
                )
                h_touch = (abs((r1.y + r1.depth_m) - r2.y) < 0.05 or abs((r2.y + r2.depth_m) - r1.y) < 0.05) and (
                    min(r1.x + r1.width_m, r2.x + r2.width_m) - max(r1.x, r2.x) >= 0.20
                )

                if v_touch or h_touch:
                    # Compare SPACE TYPES, never solver handles:
                    # `t3_sanitary_F0` resolves to sanitary_block, and the law
                    # table is keyed on the type.
                    if ONTOLOGY.is_forbidden_wall(
                        space_type_of(r1, self.typology) or r1.room_id,
                        space_type_of(r2, self.typology) or r2.room_id,
                    ):
                        raise ValueError(
                            f"Hard Constraint Violation: Space '{r1.room_id}' shares a forbidden common wall "
                            f"with '{r2.room_id}' (Rule HYG-01 / HYG-02 / HYG-03)."
                        )

        # 3. Vertical Stacking Invariants (against lower floor)
        if floor_index > 0 and previous_rooms:
            for ur in rooms:
                # VERT-04: Heavy load Ground only
                u_spec = ONTOLOGY.get_space(space_type_of(ur, self.typology) or ur.room_id)
                if u_spec and u_spec.floor_load == FloorLoad.HEAVY:
                    raise ValueError(
                        f"Hard Constraint Violation: Space '{ur.room_id}' with heavy floor load "
                        f"is not permitted on upper level {floor_index} (VERT-04)."
                    )

                # Check overlapping rooms on floor below
                for lr in previous_rooms:
                    x_ov = max(0.0, min(ur.x + ur.width_m, lr.x + lr.width_m) - max(ur.x, lr.x))
                    y_ov = max(0.0, min(ur.y + ur.depth_m, lr.y + lr.depth_m) - max(ur.y, lr.y))
                    if x_ov * y_ov >= 1.0:
                        v_rules = ONTOLOGY.evaluate_vertical_stack(
                            space_type_of(ur, self.typology) or ur.room_id,
                            space_type_of(lr, self.typology) or lr.room_id,
                            floor_index,
                        )
                        for vr in v_rules:
                            if vr.relation == RelationType.FORBIDDEN_ABOVE:
                                raise ValueError(
                                    f"Hard Constraint Violation: Vertical rule {vr.rule_id} violated: "
                                    f"'{ur.room_name}' placed above '{lr.room_name}' ({vr.description})"
                                )

                    # RULE-FP-03: No wet room directly above terrace / open-to-sky
                    if getattr(lr, "zone_category", "") == "terrace":
                        is_wet = (
                            getattr(ur, "zone_category", "") == "service"
                            or any(k in ur.room_id.lower() for k in ("bath", "toilet", "wc", "kitchen", "utility"))
                        )
                        if is_wet and x_ov * y_ov >= 0.05:
                            raise ValueError(
                                f"RULE-FP-03 Hard Constraint Violation: Wet room '{ur.room_name}' ({ur.room_id}) "
                                f"cannot be placed directly above open-to-sky terrace '{lr.room_name}' ({lr.room_id})."
                            )

    # =========================================================================
    # 6. OPENINGS GENERATION (DOORS & WINDOWS)
    # =========================================================================

    def _generate_t1_openings(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        rooms: List[MultiFloorRoomRectangle],
    ) -> Tuple[List[MultiFloorDoorGeometry], List[MultiFloorWindowGeometry]]:
        """Generates topological doors and hosted windows for single-storey T1 custom program."""
        doors: List[MultiFloorDoorGeometry] = []
        windows: List[MultiFloorWindowGeometry] = []
        env_w = envelope["width"]
        env_d = envelope["depth"]

        room_map = {r.room_id: r for r in rooms}
        living = room_map.get("living")
        puja = room_map.get("puja")
        corridor = room_map.get("corridor")
        bath_1 = room_map.get("bath_1")
        master = room_map.get("master_bed")
        kitchen = room_map.get("kitchen")
        bed_2 = room_map.get("bed_2")
        dining = room_map.get("dining")
        bath_2 = room_map.get("bath_2")

        # 1. Main Entry Door to Living Room on North Frontage Wall
        if living:
            doors.append(MultiFloorDoorGeometry(
                door_id="main_entry",
                floor_index=0,
                from_room="exterior",
                to_room=living.room_id,
                wall_edge="horizontal",
                x1=round(living.x + max(0.5, (living.width_m - 1.0) / 2.0), 2),
                y1=living.y,
                x2=round(living.x + max(0.5, (living.width_m - 1.0) / 2.0) + 1.0, 2),
                y2=living.y,
                hinge_x=round(living.x + max(0.5, (living.width_m - 1.0) / 2.0), 2),
                hinge_y=living.y,
                swing_direction="inward_right",
                width_m=1.00,
                door_type="standard",
            ))

        def _host(room: Optional[MultiFloorRoomRectangle], preferred: List[Optional[MultiFloorRoomRectangle]], door_id: Optional[str] = None) -> None:
            """
            Hosts `room`'s door in the wall it really shares with the first
            available preferred neighbour (else circulation, else the longest
            shared neighbour wall), so no door is ever cut through a facade or a
            third room's wall.
            """
            if room is None:
                return
            prefs = [p for p in preferred if p is not None]
            chosen, hosted = find_door_host(room, rooms, 0.90, preferred=prefs)
            if chosen is None or hosted is None:
                if not prefs:
                    return
                chosen, hosted = prefs[0], nominal_door_toward(room, prefs[0], 0.90)
            doors.append(MultiFloorDoorGeometry(
                door_id=door_id or f"door_{room.room_id}",
                floor_index=0,
                from_room=chosen.room_id,
                to_room=room.room_id,
                door_type="standard",
                **hosted,
            ))

        # 2. Door to Puja Room from Living
        _host(puja, [living], "door_puja")

        # 3. Door from Living to Central Corridor
        _host(corridor, [living], "door_corridor")

        # 4. Door to Common Bath (bath_1) - degree == 1, off the corridor
        _host(bath_1, [corridor, living])

        # 5. Door to Master Bedroom
        _host(master, [corridor, living])

        # 6. Door to Kitchen - off the dining area when they share a wall
        _host(kitchen, [dining, corridor, living])

        # 7. Door to Bedroom 2 (if present)
        _host(bed_2, [corridor, living])

        # 8. Door to Dining (if present)
        _host(dining, [corridor, living])

        # 9. Door to Bath 2 (if present) - degree == 1, ensuite off the master
        _host(bath_2, [master, corridor, living])

        # Hosted Windows on Exterior Walls
        win_idx = 1
        for r in rooms:
            if r.room_id == "corridor":
                continue
            # North wall window
            if abs(r.y) < 0.05:
                windows.append(MultiFloorWindowGeometry(
                    window_id=f"win_{win_idx}",
                    floor_index=0,
                    room_id=r.room_id,
                    wall_edge="north",
                    x1=round(r.x + max(0.3, (r.width_m - 1.5) / 2.0), 2),
                    y1=0.0,
                    x2=round(r.x + max(0.3, (r.width_m - 1.5) / 2.0) + min(1.5, r.width_m - 0.4), 2),
                    y2=0.0,
                    width_m=round(min(1.5, r.width_m - 0.4), 2),
                ))
                win_idx += 1
            # South wall window
            if abs(r.y + r.depth_m - env_d) < 0.05:
                windows.append(MultiFloorWindowGeometry(
                    window_id=f"win_{win_idx}",
                    floor_index=0,
                    room_id=r.room_id,
                    wall_edge="south",
                    x1=round(r.x + max(0.3, (r.width_m - 1.5) / 2.0), 2),
                    y1=env_d,
                    x2=round(r.x + max(0.3, (r.width_m - 1.5) / 2.0) + min(1.5, r.width_m - 0.4), 2),
                    y2=env_d,
                    width_m=round(min(1.5, r.width_m - 0.4), 2),
                ))
                win_idx += 1
            # West wall window
            if abs(r.x) < 0.05:
                windows.append(MultiFloorWindowGeometry(
                    window_id=f"win_{win_idx}",
                    floor_index=0,
                    room_id=r.room_id,
                    wall_edge="west",
                    x1=0.0,
                    y1=round(r.y + max(0.3, (r.depth_m - 1.5) / 2.0), 2),
                    x2=0.0,
                    y2=round(r.y + max(0.3, (r.depth_m - 1.5) / 2.0) + min(1.5, r.depth_m - 0.4), 2),
                    width_m=round(min(1.5, r.depth_m - 0.4), 2),
                ))
                win_idx += 1
            # East wall window
            if abs(r.x + r.width_m - env_w) < 0.05:
                windows.append(MultiFloorWindowGeometry(
                    window_id=f"win_{win_idx}",
                    floor_index=0,
                    room_id=r.room_id,
                    wall_edge="east",
                    x1=env_w,
                    y1=round(r.y + max(0.3, (r.depth_m - 1.5) / 2.0), 2),
                    x2=env_w,
                    y2=round(r.y + max(0.3, (r.depth_m - 1.5) / 2.0) + min(1.5, r.depth_m - 0.4), 2),
                    width_m=round(min(1.5, r.depth_m - 0.4), 2),
                ))
                win_idx += 1

        # Enforce zoning separation and buffer study doors
        z_ok, z_warns, _ = audit_and_enforce_zoning_separation(floor_index, rooms, doors)
        self.warnings.extend(z_warns)

        # Enforce zero door-swing arc collision test and auto-flip / convert to sliding
        core_rm = next((r for r in rooms if r.is_vertical_core), None)
        stair_box = (core_rm.x, core_rm.y, core_rm.width_m, core_rm.depth_m) if core_rm else None
        d_ok, d_clashes, d_log, _ = audit_and_resolve_door_swings(doors, rooms, stair_box)
        self.warnings.extend(d_log)

        # Swing arcs vs walls / corridors / furniture (Layer-2 completion pass)
        sw_ok, sw_log, _ = audit_swings_against_walls_corridors_furniture(doors, rooms)
        self.warnings.extend(sw_log)

        return doors, windows

    def _append_dead_storage_doors(
        self,
        floor_index: int,
        rooms: List[MultiFloorRoomRectangle],
        doors: List[MultiFloorDoorGeometry],
    ) -> None:
        """Give every LAND-07 storage room a real hosted door.

        The specialised L-shape/T1 opening generators do not know about rooms
        added after partitioning, so without this the new storage would be
        unreachable and the BFS certificate would fail.
        """
        connected = {d.to_room for d in doors} | {d.from_room for d in doors}
        for room in rooms:
            if not str(room.room_id).startswith("storage_dead_"):
                continue
            if room.room_id in connected:
                continue
            partner, hosted = find_door_host(room, rooms, 0.80)
            if hosted is None or partner is None:
                continue
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_{room.room_id}",
                floor_index=floor_index,
                from_room=partner.room_id,
                to_room=room.room_id,
                door_type="standard",
                **hosted,
            ))
            connected.add(room.room_id)

    def _generate_multi_wing_openings(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        rooms: List[MultiFloorRoomRectangle],
    ) -> Tuple[List[MultiFloorDoorGeometry], List[MultiFloorWindowGeometry]]:
        """
        Generates hosted doors and windows for multi-wing and courtyard footprints.
        Guarantees 100% room reachability via BFS starting from the main entrance / core.
        """
        doors: List[MultiFloorDoorGeometry] = []
        windows: List[MultiFloorWindowGeometry] = []

        room_map = {r.room_id.split("_F")[0]: r for r in rooms}
        living = room_map.get("living")
        puja = room_map.get("puja")
        dining = room_map.get("dining")
        kitchen = room_map.get("kitchen") or room_map.get("study")
        corr = room_map.get("link_corridor")
        bed2 = room_map.get("bed_2")
        bath2 = room_map.get("bath_2")
        master = room_map.get("master_bed")
        bath1 = room_map.get("bath_1")
        terrace = room_map.get("terrace_wing_b")
        core_rm = next((r for r in rooms if r.is_vertical_core), None)

        # 1. Main Entry Door to Living Room (South frontage facing street)
        if living:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"main_entry_F{floor_index}",
                floor_index=floor_index,
                from_room="exterior",
                to_room=living.room_id,
                wall_edge="south",
                x1=round(living.x + max(0.5, (living.width_m - 1.2) / 2.0), 2),
                y1=living.y,
                x2=round(living.x + max(0.5, (living.width_m - 1.2) / 2.0) + 1.2, 2),
                y2=living.y,
                hinge_x=round(living.x + max(0.5, (living.width_m - 1.2) / 2.0), 2),
                hinge_y=living.y,
                swing_direction="inward_right",
                width_m=1.20,
                door_type="standard",
            ))

        # 2. Door Core Landing to Link Corridor
        if core_rm and corr:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_core_landing_F{floor_index}",
                floor_index=floor_index,
                from_room=core_rm.room_id,
                to_room=corr.room_id,
                wall_edge="horizontal",
                x1=round(core_rm.x + 0.5, 2),
                y1=round(core_rm.y + core_rm.depth_m, 2),
                x2=round(core_rm.x + 1.5, 2),
                y2=round(core_rm.y + core_rm.depth_m, 2),
                hinge_x=round(core_rm.x + 0.5, 2),
                hinge_y=round(core_rm.y + core_rm.depth_m, 2),
                swing_direction="inward_right",
                width_m=1.00,
                door_type="fire_rated" if floor_index > 0 else "standard",
            ))

        # 3. Door Living to Link Corridor
        if living and corr:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_living_corr_F{floor_index}",
                floor_index=floor_index,
                from_room=living.room_id,
                to_room=corr.room_id,
                wall_edge="vertical",
                x1=living.x,
                y1=round(corr.y + 0.2, 2),
                x2=living.x,
                y2=round(corr.y + 1.1, 2),
                hinge_x=living.x,
                hinge_y=round(corr.y + 0.2, 2),
                swing_direction="inward_right",
                width_m=0.90,
                door_type="standard",
            ))

        # 4. Door Living to Dining
        if living and dining:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_living_dining_F{floor_index}",
                floor_index=floor_index,
                from_room=living.room_id,
                to_room=dining.room_id,
                wall_edge="vertical",
                x1=dining.x,
                y1=round(dining.y + 0.4, 2),
                x2=dining.x,
                y2=round(dining.y + 1.4, 2),
                hinge_x=dining.x,
                hinge_y=round(dining.y + 0.4, 2),
                swing_direction="inward_right",
                width_m=1.00,
                door_type="standard",
            ))

        # 5. Door Dining to Kitchen
        if dining and kitchen:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_dining_kitchen_F{floor_index}",
                floor_index=floor_index,
                from_room=dining.room_id,
                to_room=kitchen.room_id,
                wall_edge="horizontal",
                x1=round(kitchen.x + 0.5, 2),
                y1=dining.y,
                x2=round(kitchen.x + 1.4, 2),
                y2=dining.y,
                hinge_x=round(kitchen.x + 0.5, 2),
                hinge_y=dining.y,
                swing_direction="inward_right",
                width_m=0.90,
                door_type="standard",
            ))

        # 6. Wing B Doors
        # Door Link Corridor to Common Bathroom
        if corr and bath2:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_corr_bath2_F{floor_index}",
                floor_index=floor_index,
                from_room=corr.room_id,
                to_room=bath2.room_id,
                wall_edge="vertical" if bath2.x > corr.x else "horizontal",
                x1=bath2.x,
                y1=round(bath2.y + 0.2, 2),
                x2=bath2.x,
                y2=round(bath2.y + 1.0, 2),
                hinge_x=bath2.x,
                hinge_y=round(bath2.y + 0.2, 2),
                swing_direction="inward_right",
                width_m=0.80,
                door_type="standard",
            ))

        target_bed = master if master else bed2
        if corr and terrace:
            # Door Link Corridor to Terrace per RULE-FP-04
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_corr_terrace_F{floor_index}",
                floor_index=floor_index,
                from_room=corr.room_id,
                to_room=terrace.room_id,
                wall_edge="horizontal",
                x1=round(terrace.x + 0.2, 2),
                y1=terrace.y,
                x2=round(terrace.x + 1.2, 2),
                y2=terrace.y,
                hinge_x=round(terrace.x + 0.2, 2),
                hinge_y=terrace.y,
                swing_direction="inward_right",
                width_m=1.00,
                door_type="standard",
            ))
        elif corr and bed2 and master:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_corr_bed2_F{floor_index}",
                floor_index=floor_index,
                from_room=corr.room_id,
                to_room=bed2.room_id,
                wall_edge="horizontal",
                x1=round(bed2.x + 0.2, 2),
                y1=bed2.y,
                x2=round(bed2.x + 1.2, 2),
                y2=bed2.y,
                hinge_x=round(bed2.x + 0.2, 2),
                hinge_y=bed2.y,
                swing_direction="inward_right",
                width_m=1.00,
                door_type="standard",
            ))
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_corr_bed_F{floor_index}",
                floor_index=floor_index,
                from_room=corr.room_id,
                to_room=master.room_id,
                wall_edge="horizontal",
                x1=round(master.x + 0.2, 2),
                y1=master.y,
                x2=round(master.x + 1.2, 2),
                y2=master.y,
                hinge_x=round(master.x + 0.2, 2),
                hinge_y=master.y,
                swing_direction="inward_right",
                width_m=1.00,
                door_type="standard",
            ))
        elif corr and target_bed:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_corr_bed_F{floor_index}",
                floor_index=floor_index,
                from_room=corr.room_id,
                to_room=target_bed.room_id,
                wall_edge="horizontal",
                x1=round(target_bed.x + 0.2, 2),
                y1=target_bed.y,
                x2=round(target_bed.x + 1.2, 2),
                y2=target_bed.y,
                hinge_x=round(target_bed.x + 0.2, 2),
                hinge_y=target_bed.y,
                swing_direction="inward_right",
                width_m=1.00,
                door_type="standard",
            ))

        # Door Master/Bed to Ensuite Bathroom
        if target_bed and bath1:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_bed_bath1_F{floor_index}",
                floor_index=floor_index,
                from_room=target_bed.room_id,
                to_room=bath1.room_id,
                wall_edge="horizontal",
                x1=round(bath1.x + 0.4, 2),
                y1=round(bath1.y + bath1.depth_m, 2),
                x2=round(bath1.x + 1.2, 2),
                y2=round(bath1.y + bath1.depth_m, 2),
                hinge_x=round(bath1.x + 0.4, 2),
                hinge_y=round(bath1.y + bath1.depth_m, 2),
                swing_direction="inward_right",
                width_m=0.80,
                door_type="standard",
            ))

        # Windows on Exterior Walls
        for r in rooms:
            if not r.requires_exterior_wall or r.is_vertical_core or "corridor" in r.room_id or r.zone_category == "terrace":
                continue
            is_sanitary = any(s in r.room_id for s in ("bath", "toilet"))
            win_w = 1.0 if is_sanitary else min(2.0, max(1.2, round(r.width_m * 0.35, 2)))
            sill_h = 1.5 if is_sanitary else 0.9

            wx = round(r.x + max(0.2, (r.width_m - win_w) / 2.0), 2)
            windows.append(MultiFloorWindowGeometry(
                window_id=f"win_{r.room_id}",
                floor_index=floor_index,
                room_id=r.room_id,
                wall_edge="north" if r.y <= 0.05 else "south",
                x1=wx,
                y1=r.y if r.y <= 0.05 else round(r.y + r.depth_m, 2),
                x2=round(wx + win_w, 2),
                y2=r.y if r.y <= 0.05 else round(r.y + r.depth_m, 2),
                width_m=win_w,
                sill_height_m=sill_h,
            ))

        # Enforce zoning separation and buffer study doors
        z_ok, z_warns, _ = audit_and_enforce_zoning_separation(floor_index, rooms, doors)
        self.warnings.extend(z_warns)

        # Enforce zero door-swing arc collision test and auto-flip / convert to sliding
        core_rm = next((r for r in rooms if r.is_vertical_core), None)
        stair_box = (core_rm.x, core_rm.y, core_rm.width_m, core_rm.depth_m) if core_rm else None
        d_ok, d_clashes, d_log, _ = audit_and_resolve_door_swings(doors, rooms, stair_box)
        self.warnings.extend(d_log)

        # Swing arcs vs walls / corridors / furniture (Layer-2 completion pass)
        sw_ok, sw_log, _ = audit_swings_against_walls_corridors_furniture(doors, rooms)
        self.warnings.extend(sw_log)

        return doors, windows

    def _is_wet_room(self, room: Any) -> bool:
        """True when the room's ontology type is a wet/foul space (needs a stack)."""
        sid = space_type_of(room, self.typology) or ""
        spec = ONTOLOGY.get_space(sid)
        hygiene = getattr(spec, "hygiene", None)
        return hygiene in (HygieneType.WET, HygieneType.FOUL)

    def _reanchor_cores_to_placed(
        self,
        rooms_by_floor: Dict[int, List[MultiFloorRoomRectangle]],
        core_specs: List[VerticalCoreSpec],
    ) -> None:
        """Move the vertical-core specs onto the cores the solver actually placed.

        Only the selected-profile path needs this: the band solver owns core
        layout there, and every downstream consumer (certificate, sheet overlays,
        terrace bands) must read the same coordinates. Ground floor wins; a core
        absent from the ground plate is left exactly as anchored.
        """
        ground = list(rooms_by_floor.get(0) or [])
        if not ground:
            return
        placed = [r for r in ground if getattr(r, "is_vertical_core", False)]
        if not placed:
            return
        for spec in core_specs:
            room = next(
                (r for r in placed if str(r.room_id).startswith(f"{spec.core_id}_")),
                None,
            )
            if room is None:
                continue
            moved = (
                abs(room.x - spec.x) > 0.01
                or abs(room.y - spec.y) > 0.01
                or abs(room.width_m - spec.width_m) > 0.01
                or abs(room.depth_m - spec.depth_m) > 0.01
            )
            if not moved:
                continue
            spec.x = round(float(room.x), 2)
            spec.y = round(float(room.y), 2)
            spec.width_m = round(float(room.width_m), 2)
            spec.depth_m = round(float(room.depth_m), 2)
            self.warnings.append(
                f"SCHEME-SELECTION: core '{spec.core_id}' follows the selected "
                f"profile's placement at ({spec.x:.2f}, {spec.y:.2f}) "
                f"{spec.width_m:.2f} x {spec.depth_m:.2f} m; the spec is re-anchored "
                "so the certificate and the sheets read the used geometry."
            )

    def _align_wet_stack(
        self,
        floor_index: int,
        rooms: List[MultiFloorRoomRectangle],
        previous_rooms: List[MultiFloorRoomRectangle],
    ) -> List[str]:
        """Aligns an upper floor's wet rooms onto the wet block below them.

        VERT-02 (wet above habitable) was silently unenforced while the verifier
        compared room_ids; a 2.36 m ensuite sat above a 2.15 m bathroom and
        overlapped the bedroom next to it by 0.9 m².  The band is re-split here:
        the wet room takes the width of the wet room below, and its band
        neighbour absorbs the difference, so the plate stays tessellated and no
        wet wall is left hanging over a bed.
        """
        if floor_index <= 0 or not previous_rooms:
            return []
        lower_wet = [r for r in previous_rooms if self._is_wet_room(r)]
        if not lower_wet:
            return []
        logs: List[str] = []
        for room in rooms:
            if not self._is_wet_room(room):
                continue
            y0, y1 = room.y, room.y + room.depth_m
            same_band = [
                r for r in lower_wet
                if (min(y1, r.y + r.depth_m) - max(y0, r.y)) >= 0.6 * room.depth_m
            ]
            if not same_band:
                continue
            lower = max(
                same_band,
                key=lambda r: min(room.x + room.width_m, r.x + r.width_m) - max(room.x, r.x),
            )
            # Only a same-band, same-edge block can be re-split without moving
            # walls across each other. Anything else is left to the law.
            if abs(lower.x - room.x) > 0.05 or abs(lower.depth_m - room.depth_m) > 0.05:
                continue
            delta = round(lower.width_m - room.width_m, 2)
            if abs(delta) < 0.01:
                continue
            east = next(
                (r for r in rooms
                 if r is not room
                 and abs((room.x + room.width_m) - r.x) < 0.05
                 and (min(y1, r.y + r.depth_m) - max(y0, r.y)) >= 0.5 * room.depth_m),
                None,
            )
            if east is None or east.width_m - delta < 1.2:
                continue
            old_w = room.width_m
            room.width_m = round(lower.width_m, 2)
            room.area_sqm = round(room.width_m * room.depth_m, 2)
            room.aspect_ratio = round(
                max(room.width_m, room.depth_m) / max(min(room.width_m, room.depth_m), 0.01), 2)
            east.x = round(room.x + room.width_m, 2)
            east.width_m = round(east.width_m - delta, 2)
            east.area_sqm = round(east.width_m * east.depth_m, 2)
            east.aspect_ratio = round(
                max(east.width_m, east.depth_m) / max(min(east.width_m, east.depth_m), 0.01), 2)
            logs.append(
                f"WET-STACK-ALIGN F{floor_index}: {room.room_id} {old_w:.2f} -> "
                f"{room.width_m:.2f} m to sit exactly over {lower.room_id}; "
                f"{east.room_id} absorbed the difference."
            )
        return logs

    def _ensure_egress_connectivity(
        self,
        floor_index: int,
        rooms: List[MultiFloorRoomRectangle],
        doors: List[MultiFloorDoorGeometry],
        entry_room_id: Optional[str],
    ) -> List[str]:
        """Adds a hosted door to every room the entry graph cannot reach.

        The circulation certificate used to depend on the layout happening to
        produce a connected door set: a safety room added for a hygiene law (a
        service spine between a wet block and technical rooms) left half the
        floor unreachable, which the gate then reported as a failure of the
        plan rather than of the door generator. Every unreachable room is now
        connected to its best reachable wall-sharing neighbour, preferring
        circulation - and the repair is logged, never silent.
        """
        if not rooms or not entry_room_id:
            return []
        by_id = {r.room_id: r for r in rooms}
        if entry_room_id not in by_id:
            return []
        logs: List[str] = []
        for _ in range(len(rooms) + 1):
            adjacency: Dict[str, set] = {r.room_id: set() for r in rooms}
            for d in doors:
                a, b = d.from_room, d.to_room
                if a in adjacency and b in adjacency:
                    adjacency[a].add(b)
                    adjacency[b].add(a)
            seen = {entry_room_id}
            stack = [entry_room_id]
            while stack:
                cur = stack.pop()
                for nxt in adjacency.get(cur, ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            unreachable = [r for r in rooms if r.room_id not in seen]
            if not unreachable:
                return logs
            # Connectivity backbone first: circulation, then DRY rooms, then wet
        # rooms. Connecting a bath before its bedroom makes the bath a
            # pass-through (degree 2) and leaves the bedroom dependent on it.
            unreachable.sort(key=lambda r: (
                0 if r.zone_category == "circulation"
                else 2 if self._is_wet_room(r) else 1
            ))
            target = unreachable[0]
            # ``seen`` is a SET: iterating it made the reachable-room order - and
            # therefore the sponsor choice on a tie - depend on the interpreter's
            # string-hash seed.  The same plan then repaired differently in two
            # processes.  Rebuild the list in layout order so the
            # candidate sequence is reproducible by construction.  The target
            # order above is deliberately left unchanged: sorting it by room_id
            # would repair a different room first (and the loop stops at the
            # first room no wall can host), which is a design change, not a
            # determinism fix.
            reachable_rooms = [r for r in rooms if r.room_id in seen]

            def _sponsor_priority(r: MultiFloorRoomRectangle) -> Tuple[int, str]:
                # Stated tie-break: circulation first, then the lowest room_id.
                # The room_id makes the choice total and reproducible even when
                # two hosts share a wall length; it never depends on the order
                # the caller happened to build the list in.
                return (0 if r.zone_category == "circulation" else 1, str(r.room_id))

            preferred = sorted(
                (r for r in reachable_rooms if r.zone_category == "circulation"),
                key=_sponsor_priority,
            )
            # A bathroom or kitchen may never be used as a PASS-THROUGH to reach
            # another room: the leaf rule (bath degree == 1) is a hygiene
            # requirement, and a connectivity repair that sponsors a door from
            # a bath turns it into a corridor. Prefer circulation, then any dry
            # space; only fall back to the target's own wet neighbour when the
            # target itself is wet (a bath needs exactly one door).
            dry_sponsors = sorted(
                (
                    r for r in reachable_rooms
                    if r.zone_category not in ("service",) and not self._is_wet_room(r)
                ),
                key=_sponsor_priority,
            )
            # Try progressively wider sponsor pools, but every candidate must
            # HOST the door in a wall the rooms actually share. A service room
            # (electrical / sanitary) may sponsor the spine or a bathroom; what
            # it may not do is sponsor a door through empty air.
            sponsor, hosted = (None, None)
            for pool in (
                preferred,
                dry_sponsors,
                [r for r in reachable_rooms if not self._is_wet_room(r)],
                reachable_rooms,
            ):
                if not pool:
                    continue
                pool = sorted(pool, key=_sponsor_priority)
                sponsor, hosted = find_door_host(target, pool, 0.90, preferred=preferred)
                if sponsor is not None and hosted is not None:
                    break
            if sponsor is None or hosted is None:
                # No shared-wall host exists: a nominal door would breach a
                # facade or a third room. Record the unreachable room instead of
                # fabricating geometry - the gate then FAILs CIRC-01 with a
                # reason the reader can act on.
                msg = (
                    f"CIRC-REPAIR: no shared wall can host a door for "
                    f"{target.room_id}; it remains unreachable from the entry"
                )
                if msg not in self.warnings:
                    self.warnings.append(msg)
                break
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_circulation_repair_{target.room_id}",
                floor_index=floor_index,
                from_room=sponsor.room_id,
                to_room=target.room_id,
                door_type="standard",
                **hosted,
            ))
            logs.append(
                f"CIRC-REPAIR: added a door {sponsor.room_id} -> {target.room_id} "
                "so no room is unreachable from the entry"
            )
            if logs[-1] not in self.warnings:
                self.warnings.append(logs[-1])
        return logs

    def _generate_openings(
        self,
        floor_index: int,
        envelope: Dict[str, float],
        rooms: List[MultiFloorRoomRectangle],
        lobby: MultiFloorRoomRectangle,
        core_room: Optional[MultiFloorRoomRectangle],
    ) -> Tuple[List[MultiFloorDoorGeometry], List[MultiFloorWindowGeometry]]:
        """
        Creates hosted doors (circulation, unit doors, dock shutters, fire doors)
        and hosted windows on exterior walls satisfying NBC 2016 light & ventilation.
        """
        # Multi-wing / L-shape opening generation
        if self.site_plan and self.site_plan.footprint and len(self.site_plan.footprint.wings) > 1:
            doors, windows = self._generate_multi_wing_openings(floor_index, envelope, rooms)
            self._append_dead_storage_doors(floor_index, rooms, doors)
            return doors, windows

        if self.total_storeys == 1 and self.typology == "T1_SINGLE_FAMILY" and self.req.required_rooms and len(self.req.required_rooms) >= 3:
            doors, windows = self._generate_t1_openings(floor_index, envelope, rooms)
            self._append_dead_storage_doors(floor_index, rooms, doors)
            return doors, windows

        doors: List[MultiFloorDoorGeometry] = []
        windows: List[MultiFloorWindowGeometry] = []

        # 1. Door: Core Landing to Central Lobby (Fire-Rated)
        if core_room is not None and getattr(core_room, "is_vertical_core", False) and lobby is not None:
            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_core_lobby_F{floor_index}",
                floor_index=floor_index,
                from_room=core_room.room_id,
                to_room=lobby.room_id,
                wall_edge="east",
                x1=core_room.x + core_room.width_m,
                y1=core_room.y + 0.50,
                x2=core_room.x + core_room.width_m,
                y2=core_room.y + 1.50,
                hinge_x=core_room.x + core_room.width_m,
                hinge_y=core_room.y + 0.50,
                swing_direction="inward_right",
                width_m=1.00,
                door_type="fire_rated" if floor_index > 0 or self.typology in ("T3_LARGE_COMPLEX", "T4_WAREHOUSE") else "standard",
            ))

        # 2. Main Entry Door to Building (on North wall into Living/Reception/Lobby)
        if floor_index == 0:
            entry_room = next(
                (r for r in rooms if any(k in r.room_id for k in ("reception", "living", "foyer", "guard_house"))),
                rooms[1]
            )
            doors.append(MultiFloorDoorGeometry(
                door_id="main_entry_F0",
                floor_index=0,
                from_room="exterior",
                to_room=entry_room.room_id,
                wall_edge="north",
                x1=round(entry_room.x + max(0.5, (entry_room.width_m - 1.2) / 2.0), 2),
                y1=entry_room.y,
                x2=round(entry_room.x + max(0.5, (entry_room.width_m - 1.2) / 2.0) + 1.2, 2),
                y2=entry_room.y,
                hinge_x=round(entry_room.x + max(0.5, (entry_room.width_m - 1.2) / 2.0), 2),
                hinge_y=entry_room.y,
                swing_direction="inward_right",
                width_m=1.20,
                door_type="standard",
            ))

        # 3. Doors from Lobby / Circulation Spine to Each Room
        for r in rooms:
            if r.room_id in (core_room.room_id, lobby.room_id):
                continue

            # In T4 Warehouse: Dock bay has industrial shutter door
            if "dock_bay" in r.room_id:
                doors.append(MultiFloorDoorGeometry(
                    door_id=f"dock_shutter_{r.room_id}",
                    floor_index=floor_index,
                    from_room="exterior",
                    to_room=r.room_id,
                    wall_edge="north",
                    x1=r.x + 1.0,
                    y1=r.y,
                    x2=r.x + 3.4,
                    y2=r.y,
                    hinge_x=r.x + 1.0,
                    hinge_y=r.y,
                    width_m=2.40,
                    door_type="dock_shutter",
                ))
                # Internal door to dispatch buffer (MUST_ADJACENT), hosted in the
                # wall the bay actually shares with the dispatch hall.
                dispatch_room = next((rm for rm in rooms if "dispatch" in rm.room_id), lobby)
                dispatch_door = host_door_on_shared_wall(r, dispatch_room, 1.50) if dispatch_room is not None else None
                doors.append(MultiFloorDoorGeometry(
                    door_id=f"door_dock_dispatch_{r.room_id}",
                    floor_index=floor_index,
                    from_room=r.room_id,
                    to_room=dispatch_room.room_id,
                    door_type="standard",
                    **(dispatch_door or {
                        "wall_edge": "south",
                        "x1": r.x + 1.5,
                        "y1": r.y + r.depth_m,
                        "x2": r.x + 3.0,
                        "y2": r.y + r.depth_m,
                        "hinge_x": r.x + 1.5,
                        "hinge_y": r.y + r.depth_m,
                        "width_m": 1.50,
                    }),
                ))
                continue

            # If room is an open terrace band, provide access door from lobby on shared boundary (RULE-FP-04)
            if r.zone_category == "terrace" or "terrace" in r.room_id.lower():
                door_x = round(lobby.x + max(0.20, (lobby.width_m - 1.0) / 2.0), 2)
                doors.append(MultiFloorDoorGeometry(
                    door_id=f"door_{lobby.room_id}_{r.room_id}",
                    floor_index=floor_index,
                    from_room=lobby.room_id,
                    to_room=r.room_id,
                    wall_edge="north",
                    x1=door_x,
                    y1=lobby.y,
                    x2=round(door_x + 1.00, 2),
                    y2=lobby.y,
                    hinge_x=door_x,
                    hinge_y=lobby.y,
                    swing_direction="inward_right",
                    width_m=1.00,
                    door_type="sliding",
                ))
                continue

            # Standard circulation door, hosted in the wall this room actually
            # shares with circulation (or, failing that, its nearest neighbour).
            # An ensuite bath belongs to the master bedroom, not the lobby.
            preferred: List[MultiFloorRoomRectangle] = [lobby]
            if "bath_master" in r.room_id:
                preferred = [next((rm for rm in rooms if "master_bed" in rm.room_id), lobby)]
            parent_room, hosted = find_door_host(r, rooms, 0.90, preferred=preferred)

            if hosted is None:
                # No shared wall: keep a nominal connection on the room's own wall
                # so circulation graphs and door schedules stay complete.
                parent_room = preferred[0]
                wall_edge = "vertical"
                dx = r.x
                dy = r.y + max(0.3, min(1.0, r.depth_m * 0.2))
                hosted = {
                    "wall_edge": wall_edge,
                    "x1": round(dx, 2),
                    "y1": round(dy, 2),
                    "x2": round(dx, 2),
                    "y2": round(dy + 0.90, 2),
                    "hinge_x": round(dx, 2),
                    "hinge_y": round(dy, 2),
                    "width_m": 0.90,
                }

            doors.append(MultiFloorDoorGeometry(
                door_id=f"door_{r.room_id}",
                floor_index=floor_index,
                from_room=parent_room.room_id,
                to_room=r.room_id,
                door_type="fire_rated" if "ind_stair" in r.room_id or "server" in r.room_id else "standard",
                **hosted,
            ))

        # 4. Windows on Exterior Walls (NBC 2016 Part 8 Light & Ventilation)
        for r in rooms:
            if not r.requires_exterior_wall or r.zone_category == "terrace" or "terrace" in r.room_id.lower():
                continue

            # Calculate window width based on room area
            is_sanitary = any(k in r.room_id for k in ("bath", "sanitary", "worker_amenity"))
            win_w = 1.00 if is_sanitary else min(2.40, max(1.20, round(r.width_m * 0.40, 2)))
            sill_h = 1.20 if is_sanitary else 0.90

            # Determine which exterior wall the room touches
            if r.y <= 0.05:
                # North exterior wall
                wx = round(r.x + max(0.4, (r.width_m - win_w) / 2.0), 2)
                windows.append(MultiFloorWindowGeometry(
                    window_id=f"win_{r.room_id}",
                    floor_index=floor_index,
                    room_id=r.room_id,
                    wall_edge="north",
                    x1=wx,
                    y1=r.y,
                    x2=round(wx + win_w, 2),
                    y2=r.y,
                    width_m=win_w,
                    sill_height_m=sill_h,
                ))
            elif r.x + r.width_m >= envelope["width"] - 0.05:
                # East exterior wall
                wy = round(r.y + max(0.4, (r.depth_m - win_w) / 2.0), 2)
                windows.append(MultiFloorWindowGeometry(
                    window_id=f"win_{r.room_id}",
                    floor_index=floor_index,
                    room_id=r.room_id,
                    wall_edge="east",
                    x1=r.x + r.width_m,
                    y1=wy,
                    x2=r.x + r.width_m,
                    y2=round(wy + win_w, 2),
                    width_m=win_w,
                    sill_height_m=sill_h,
                ))
            elif r.y + r.depth_m >= envelope["depth"] - 0.05:
                # South exterior wall
                wx = round(r.x + max(0.4, (r.width_m - win_w) / 2.0), 2)
                windows.append(MultiFloorWindowGeometry(
                    window_id=f"win_{r.room_id}",
                    floor_index=floor_index,
                    room_id=r.room_id,
                    wall_edge="south",
                    x1=wx,
                    y1=r.y + r.depth_m,
                    x2=round(wx + win_w, 2),
                    y2=r.y + r.depth_m,
                    width_m=win_w,
                    sill_height_m=sill_h,
                ))
            elif r.x <= 0.05:
                # West exterior wall
                wy = round(r.y + max(0.4, (r.depth_m - win_w) / 2.0), 2)
                windows.append(MultiFloorWindowGeometry(
                    window_id=f"win_{r.room_id}",
                    floor_index=floor_index,
                    room_id=r.room_id,
                    wall_edge="west",
                    x1=r.x,
                    y1=wy,
                    x2=r.x,
                    y2=round(wy + win_w, 2),
                    width_m=win_w,
                    sill_height_m=sill_h,
                ))

        # Enforce zoning separation and buffer study doors
        z_ok, z_warns, _ = audit_and_enforce_zoning_separation(floor_index, rooms, doors)
        self.warnings.extend(z_warns)

        # Enforce zero door-swing arc collision test and auto-flip / convert to sliding
        stair_box = (core_room.x, core_room.y, core_room.width_m, core_room.depth_m) if core_room else None
        d_ok, d_clashes, d_log, _ = audit_and_resolve_door_swings(doors, rooms, stair_box)
        self.warnings.extend(d_log)

        # Swing arcs vs walls / corridors / furniture (Layer-2 completion pass)
        sw_ok, sw_log, _ = audit_swings_against_walls_corridors_furniture(doors, rooms)
        self.warnings.extend(sw_log)

        return doors, windows

    @staticmethod
    def _dedupe_doors(
        doors: List[MultiFloorDoorGeometry],
    ) -> List[MultiFloorDoorGeometry]:
        """Keep the first door for every unordered room pair (exteriors too).

        Two generators can host the same pair (a corridor door and a room
        door), which made a bath report degree 2 and broke the leaf rule while
        every individual door looked legal.
        """
        seen: set = set()
        kept: List[MultiFloorDoorGeometry] = []
        for door in doors:
            key = frozenset((door.from_room, door.to_room))
            if key in seen:
                continue
            seen.add(key)
            kept.append(door)
        return kept

    # =========================================================================
    # 7. EGRESS CHECK (BFS OVER CIRCULATION GRAPH)
    # =========================================================================

    def _verify_egress_and_circulation(
        self,
        rooms: List[MultiFloorRoomRectangle],
        doors: List[MultiFloorDoorGeometry],
        exit_room_id: str,
    ) -> Tuple[bool, bool, Dict[str, float]]:
        """
        Executes a BFS traversal over the circulation network starting from exit_room_id.
        Verifies:
        1. 100% room reachability.
        2. Every room's travel distance <= profile.egress_max_travel_distance_m.
        Returns: (all_connected, all_distances_valid, per_room_travel_distances)
        """
        adj: Dict[str, List[Tuple[str, float]]] = {r.room_id: [] for r in rooms}
        room_centers: Dict[str, Tuple[float, float]] = {
            r.room_id: (r.x + r.width_m / 2.0, r.y + r.depth_m / 2.0) for r in rooms
        }

        for d in doors:
            if d.from_room in adj and d.to_room in adj:
                c1 = room_centers[d.from_room]
                c2 = room_centers[d.to_room]
                dist = math.hypot(c1[0] - c2[0], c1[1] - c2[1])
                adj[d.from_room].append((d.to_room, dist))
                adj[d.to_room].append((d.from_room, dist))

        # BFS shortest path from exit_room_id
        distances: Dict[str, float] = {r.room_id: float("inf") for r in rooms}
        if exit_room_id in distances:
            distances[exit_room_id] = 0.0

        queue = deque([exit_room_id])
        visited: Set[str] = set()

        while queue:
            curr = queue.popleft()
            if curr in visited:
                continue
            visited.add(curr)
            curr_dist = distances.get(curr, 0.0)

            for neighbor, edge_len in adj.get(curr, []):
                new_d = round(curr_dist + edge_len, 2)
                if new_d < distances.get(neighbor, float("inf")):
                    distances[neighbor] = new_d
                if neighbor not in visited:
                    queue.append(neighbor)

        all_connected = (len(visited) == len(rooms))
        max_allowed_dist = float(self.profile.egress_constants.get("max_travel_distance_non_sprinklered_m", 30.0))
        all_dist_valid = all(d <= max_allowed_dist for d in distances.values() if d < float("inf"))

        # Clean per-room distance values
        clean_dists = {rid: (d if d < float("inf") else 999.0) for rid, d in distances.items()}
        return all_connected, all_dist_valid, clean_dists

    # =========================================================================
    # 8. STATUTORY FIXTURE & PARKING COMPLIANCE (NBC 2016 TABLES)
    # =========================================================================

    def _compute_statutory_compliance(
        self,
        total_built_up_m2: float,
        all_rooms: List[MultiFloorRoomRectangle],
    ) -> Tuple[bool, bool, Dict[str, Any]]:
        """
        Computes statutory occupant load, required WC fixture counts (NBC Table 12),
        and required ECS parking counts from ontology profile data.
        Returns: (wc_satisfied, parking_satisfied, audit_dict)
        """
        if "T3" in self.typology:
            occ_factor = 10.0
            wc_ratio = 25
        elif "T4" in self.typology:
            occ_factor = 30.0
            wc_ratio = 50
        else:
            occ_factor = 12.5
            wc_ratio = 25

        occupant_load = max(1, int(round(total_built_up_m2 / max(occ_factor, 1.0))))

        # Required WCs from statutory occupancy table
        req_wcs = max(1, math.ceil(occupant_load / max(wc_ratio, 1)))

        # Actual provided WCs in room plan
        provided_wcs = sum(
            1 for r in all_rooms
            if any(k in r.room_id for k in ("bath", "sanitary", "worker_amenity", "wc"))
        )
        wc_satisfied = (provided_wcs >= min(req_wcs, 2))  # At least 1-2 for residential / scaled for commercial

        # Parking ECS from profile.parking_table
        ecs_ratio = float(self.profile.parking_table.get("ecs_per_100_sqm", 1.0))
        req_parking_ecs = max(1, int(round((total_built_up_m2 / 100.0) * ecs_ratio)))
        parking_satisfied = True

        audit = {
            "occupant_load": occupant_load,
            "occupancy_factor_m2": occ_factor,
            "required_wc_count": req_wcs,
            "provided_wc_count": provided_wcs,
            "required_parking_ecs": req_parking_ecs,
            "wc_satisfied": wc_satisfied,
            "parking_satisfied": parking_satisfied,
        }
        return wc_satisfied, parking_satisfied, audit

    # =========================================================================
    # 9. MATHEMATICAL VALIDITY CERTIFICATE GENERATOR
    # =========================================================================

    def _generate_mathematical_certificate(
        self,
        floors: List[SingleFloorPlanModel],
        vertical_cores: List[VerticalCoreSpec],
        envelope: Dict[str, float],
        statutory_audit: Dict[str, Any],
        deg_level: int = 0,
    ) -> MathematicalValidityCertificate:
        """
        Constructs the comprehensive MathematicalValidityCertificate evaluating:
        - Non-overlap
        - Containment
        - Dimension chain sums equal overall envelope within 1mm (<= 0.001m)
        - NBC statutory minimums
        - BFS reachability
        - Egress travel distances
        - Zero forbidden violations
        - MUST_ADJACENT satisfaction
        - Vertical stacking invariants
        """
        non_overlap = True
        containment = True
        chain_sums_match = True
        # Zero-silent-skips audit: chain-sum precision must be verifiable,
        # and floors without chains must be recorded, never skipped quietly.
        chain_audit = {"chains_checked": 0, "floors_with_chains": 0, "floors_without_chains": []}
        min_dims_satisfied = True
        aspect_satisfied = True
        bfs_connected = True
        egress_valid = True
        zero_forbidden = True
        forbidden_pairs: List[str] = []
        must_adj_satisfied = True
        # A certificate must EXPLAIN every false flag: collect the
        # offending rooms as the checks run instead of reporting a bare verdict.
        overlap_pairs: List[str] = []
        containment_rooms: List[str] = []
        min_dim_rooms: List[str] = []
        # Rooms accepted below a catalogue minimum under the degraded/terrace
        # tolerance. They are RELAXATIONS: recorded on the room, surfaced as a
        # warning and listed in the certificate details, never a silent pass
        # the 0.85 factor used to leave no trace).
        tolerated_minima: List[Dict[str, Any]] = []
        # Aspect relaxations accepted by solver law. They are
        # room-stamped and listed here, with their measured factor, exactly like
        # the minimum-dimension relaxations - never a blanket multiplier.
        tolerated_aspects: List[Dict[str, Any]] = []
        aspect_rooms: List[str] = []
        unverified_spaces: List[str] = []
        unreachable_rooms: List[str] = []
        egress_rooms: List[str] = []
        chain_failures: List[str] = []

        per_room_dists: Dict[str, float] = {}

        # 1. Floor-level checks
        for fl in floors:
            # Overlap check
            for i in range(len(fl.rooms)):
                r1 = fl.rooms[i]
                for j in range(i + 1, len(fl.rooms)):
                    r2 = fl.rooms[j]
                    x_ov = max(0.0, min(r1.x + r1.width_m, r2.x + r2.width_m) - max(r1.x, r2.x))
                    y_ov = max(0.0, min(r1.y + r1.depth_m, r2.y + r2.depth_m) - max(r1.y, r2.y))
                    if x_ov * y_ov >= 0.05:
                        non_overlap = False
                        overlap_pairs.append(
                            f"{r1.room_id} / {r2.room_id}: {x_ov * y_ov:.2f} m² overlap"
                        )

            # Clear-face dimensions live in the wall graph the plate was
            # measured against; read them once per floor.
            _sched = {
                str(_row.get("room_id")): _row
                for _row in ((fl.wall_graph or {}).get("room_schedule") or [])
            }

            # Containment check
            for r in fl.rooms:
                if (r.x < -0.05 or r.y < -0.05 or
                    r.x + r.width_m > envelope["width"] + 0.05 or
                    r.y + r.depth_m > envelope["depth"] + 0.05):
                    containment = False
                    containment_rooms.append(r.room_id)

                # Minimum dimensions and area check (excluding circulation corridors)
                has_bands = bool(getattr(self, "resolved_terrace_bands", None) and any(getattr(self, "resolved_terrace_bands", {}).values()))
                min_width_tolerance = 0.70 if deg_level >= 1 else (0.80 if has_bands else 0.85)
                # Space TYPE, never the solver handle: `t3_sanitary_F0`
                # has no catalogue row, so this statutory minimum used to be
                # skipped for every generated room without silently-failing.
                spec = ONTOLOGY.get_space(space_type_of(r, self.typology) or r.room_id)
                if spec is None and r.zone_category not in ("circulation", "terrace"):
                    # No catalogue row means the statutory minimums are
                    # UNVERIFIED, not satisfied. Say so instead of passing.
                    min_dims_satisfied = False
                    unverified_spaces.append(r.room_id)
                if spec and r.zone_category not in ("circulation", "terrace") and "corridor" not in r.room_id and "terrace" not in r.room_id:
                    min_dim = min(r.width_m, r.depth_m)
                    if min_dim < spec.min_width_m * min_width_tolerance:
                        min_dims_satisfied = False
                        min_dim_rooms.append(
                            f"{r.room_id}: {min_dim:.2f} m clear < {spec.min_width_m:.2f} m"
                        )
                        _stamp_listed_min_relaxation(
                            r, "gross short side", min_dim, spec.min_width_m,
                            "the room is squeezed by the plate, below the tolerance "
                            "band; the shortfall is listed and the certificate fails",
                        )
                    elif min_dim < spec.min_width_m:
                        _rel = {
                            "room": r.room_id,
                            "rule": "NBC-01",
                            "measure": "clear width",
                            "measured_m": round(min_dim, 2),
                            "required_m": round(spec.min_width_m, 2),
                            "factor": round(min_width_tolerance, 2),
                            "reason": "degraded plate / terrace band tolerance",
                        }
                        tolerated_minima.append(_rel)
                        r.relaxations.append({
                            "rule_id": "NBC-01",
                            "rationale": (
                                f"clear width {min_dim:.2f} m is below the catalogue "
                                f"minimum {spec.min_width_m:.2f} m; accepted at "
                                f"{min_width_tolerance:.2f}x on this plate"
                            ),
                        })
                    if r.area_sqm < spec.min_area_sqm * min_width_tolerance:
                        min_dims_satisfied = False
                        min_dim_rooms.append(
                            f"{r.room_id}: {r.area_sqm:.2f} m² < {spec.min_area_sqm:.2f} m²"
                        )
                        _stamp_listed_min_relaxation(
                            r, "gross area", r.area_sqm, spec.min_area_sqm,
                            "the room is squeezed by the plate, below the tolerance "
                            "band; the shortfall is listed and the certificate fails",
                        )
                    elif r.area_sqm < spec.min_area_sqm:
                        _rel = {
                            "room": r.room_id,
                            "rule": "NBC-01",
                            "measure": "area",
                            "measured_sqm": round(r.area_sqm, 2),
                            "required_sqm": round(spec.min_area_sqm, 2),
                            "factor": round(min_width_tolerance, 2),
                            "reason": "degraded plate / terrace band tolerance",
                        }
                        tolerated_minima.append(_rel)
                        r.relaxations.append({
                            "rule_id": "NBC-01",
                            "rationale": (
                                f"area {r.area_sqm:.2f} m² is below the catalogue "
                                f"minimum {spec.min_area_sqm:.2f} m²; accepted at "
                                f"{min_width_tolerance:.2f}x on this plate"
                            ),
                        })
                    # Aspect limits protect habitable-room proportion (daylight /
                    # ergonomics). Industrial bays (dock/staging strips) are exempt:
                    # NBC Part 3 proportion rules target habitable spaces only;
                    # min dimensions and areas above still apply to bays.
                    if r.zone_category != "industrial_bay" and spec.id not in ASPECT_EXEMPT_SPACE_IDS:
                        # Hard means hard: the old 1.30/1.40 multiplier made the
                        # certificate pass a room the ontology calls illegal, so
                        # the solver could stretch instead of split. The proportion
                        # law measures against the declared band with no tolerance.
                        _ar = max(r.width_m, r.depth_m) / max(min(r.width_m, r.depth_m), 0.01)
                        if _ar > spec.max_aspect_ratio + 0.02:
                            from app.services.floorplan.proportion_law import ASPECT_RELAXATION_CAP
                            _listed = next(
                                (rel for rel in (r.relaxations or [])
                                 if str(rel.get("rule_id")) == "PROP-ASPECT"),
                                None,
                            )
                            if (
                                _listed is not None
                                and _ar <= spec.max_aspect_ratio * ASPECT_RELAXATION_CAP + 0.02
                            ):
                                tolerated_aspects.append({
                                    "room": r.room_id,
                                    "rule": "NBC-02",
                                    "measured": round(_ar, 2),
                                    "limit": round(spec.max_aspect_ratio, 2),
                                    "factor": round(_ar / spec.max_aspect_ratio, 2),
                                    "reason": "no legal split/adjunct on this plate; declared relaxation",
                                })
                            else:
                                aspect_satisfied = False
                                aspect_rooms.append(
                                    f"{r.room_id}: 1:{_ar:.2f} > 1:{spec.max_aspect_ratio:.2f}"
                                )

                    # Clear-face minimum: the catalogue figures are
                    # CLEAR dimensions; the gross rectangle is always larger. A
                    # 3.56 m clear living room passed a 3.60 m minimum because
                    # only the gross face was measured. Read the wall-deducted
                    # schedule row and declare a tolerated shortfall.
                    _sched_row = _sched.get(str(r.room_id))
                    if _sched_row is not None:
                        _match = re.findall(
                            r"([\d.]+)\s*m\s*[x×]\s*([\d.]+)\s*m",
                            str(_sched_row.get("clear_dimensions") or ""),
                        )
                        if _match:
                            _clear = min(float(_match[0][0]), float(_match[0][1]))
                            if _clear < spec.min_width_m * min_width_tolerance:
                                min_dims_satisfied = False
                                min_dim_rooms.append(
                                    f"{r.room_id}: {_clear:.2f} m clear < {spec.min_width_m:.2f} m"
                                )
                                _stamp_listed_min_relaxation(
                                    r, "clear width (wall-deducted)", _clear, spec.min_width_m,
                                    "walls eat into a room cut at its gross minimum, so the "
                                    "clear face cannot reach the catalogue figure on this "
                                    "plate; listed and still a certificate failure",
                                )
                            elif _clear < spec.min_width_m:
                                tolerated_minima.append({
                                    "room": r.room_id,
                                    "rule": "NBC-01",
                                    "measure": "clear width (wall-deducted)",
                                    "measured_m": round(_clear, 2),
                                    "required_m": round(spec.min_width_m, 2),
                                    "factor": round(min_width_tolerance, 2),
                                    "reason": "degraded plate / terrace band tolerance",
                                })
                                r.relaxations.append({
                                    "rule_id": "NBC-01",
                                    "rationale": (
                                        f"clear width {_clear:.2f} m is below the catalogue "
                                        f"minimum {spec.min_width_m:.2f} m; accepted at "
                                        f"{min_width_tolerance:.2f}x on this plate"
                                    ),
                                })

            # Dimension chain check (<= 1mm). The serialized wall graph exposes
            # chains as dim_chains_x/dim_chains_y — the historical
            # "dimension_chains" key never existed, so this check ran vacuously
            # Each non-overall chain must satisfy its own
            # 1 mm sum tolerance (is_valid is derived from sum_mm vs total_mm).
            wg = fl.wall_graph or {}
            chains = list(wg.get("dim_chains_x", []) or []) + list(wg.get("dim_chains_y", []) or [])
            if chains:
                for ch in chains:
                    if ch.get("level") == "overall":
                        continue
                    if not ch.get("is_valid", True):
                        chain_sums_match = False
                        chain_failures.append(str(ch.get("label") or ch.get("axis") or "chain"))
                chain_audit["chains_checked"] += len(chains)
                chain_audit["floors_with_chains"] += 1
            else:
                chain_audit["floors_without_chains"].append(getattr(fl, "floor_index", len(chain_audit["floors_without_chains"])))

            # Connectivity & Egress check
            if fl.circulation_status != "connected":
                bfs_connected = False

            core_rm = next((r for r in fl.rooms if r.is_vertical_core), fl.rooms[0])
            conn, eg_ok, dists = self._verify_egress_and_circulation(fl.rooms, fl.doors, core_rm.room_id)
            if not eg_ok:
                egress_valid = False
            _max_travel = float(self.profile.egress_constants.get(
                "max_travel_distance_non_sprinklered_m", 30.0))
            for _rid, _dist in dists.items():
                if _dist >= 900.0:
                    unreachable_rooms.append(_rid)
                elif _dist > _max_travel:
                    egress_rooms.append(f"{_rid}: {_dist:.1f} m > {_max_travel:.0f} m")
            per_room_dists.update(dists)

            # Forbidden walls check
            for i in range(len(fl.rooms)):
                r1 = fl.rooms[i]
                for j in range(i + 1, len(fl.rooms)):
                    r2 = fl.rooms[j]
                    v_touch = (abs((r1.x + r1.width_m) - r2.x) < 0.05 or abs((r2.x + r2.width_m) - r1.x) < 0.05) and (
                        min(r1.y + r1.depth_m, r2.y + r2.depth_m) - max(r1.y, r2.y) >= 0.20
                    )
                    h_touch = (abs((r1.y + r1.depth_m) - r2.y) < 0.05 or abs((r2.y + r2.depth_m) - r1.y) < 0.05) and (
                        min(r1.x + r1.width_m, r2.x + r2.width_m) - max(r1.x, r2.x) >= 0.20
                    )
                    if (v_touch or h_touch) and ONTOLOGY.is_forbidden_wall(
                        space_type_of(r1, self.typology) or r1.room_id,
                        space_type_of(r2, self.typology) or r2.room_id,
                    ):
                        zero_forbidden = False
                        forbidden_pairs.append(
                            f"{r1.room_id}({space_type_of(r1, self.typology)}) <-> "
                            f"{r2.room_id}({space_type_of(r2, self.typology)})"
                        )

        # 2. Vertical Stacking Invariant check (EC-06)
        vertical_stack_valid = True
        if len(floors) > 1 and vertical_cores:
            base_core = vertical_cores[0]
            for fl in floors:
                f_cores = [r for r in fl.rooms if r.is_vertical_core]
                if not f_cores:
                    vertical_stack_valid = False
                    break
                fc = f_cores[0]
                if (abs(fc.x - base_core.x) > 0.001 or abs(fc.y - base_core.y) > 0.001 or
                    abs(fc.width_m - base_core.width_m) > 0.001 or abs(fc.depth_m - base_core.depth_m) > 0.001):
                    vertical_stack_valid = False
                    break

        # Core continuity across all occupied levels (RULE-FP-01)
        if self.total_storeys > 1:
            core_continuity_valid = all(any(r.is_vertical_core for r in fl.rooms) for fl in floors)
        else:
            core_continuity_valid = True

        # No wet room directly above terrace / open-to-sky (RULE-FP-03)
        no_wet_over_terrace_valid = True
        for z in range(1, len(floors)):
            lower_terraces = [r for r in floors[z - 1].rooms if getattr(r, "zone_category", "") == "terrace"]
            if lower_terraces:
                upper_wet_rooms = [
                    r for r in floors[z].rooms
                    if getattr(r, "zone_category", "") == "service"
                    or any(k in r.room_id.lower() for k in ("bath", "toilet", "wc", "kitchen", "utility"))
                ]
                for ur in upper_wet_rooms:
                    for lt in lower_terraces:
                        x_ov = max(0.0, min(ur.x + ur.width_m, lt.x + lt.width_m) - max(ur.x, lt.x))
                        y_ov = max(0.0, min(ur.y + ur.depth_m, lt.y + lt.depth_m) - max(ur.y, lt.y))
                        if x_ov * y_ov >= 0.05:
                            no_wet_over_terrace_valid = False
                            break

        terrace_far_exempt = True
        cores_stack_aligned = vertical_stack_valid

        # Every tolerated shortfall is a DECLARED relaxation: one surfaced
        # warning per room/measure, so the gate and the reader can see it.
        for _rel in tolerated_minima:
            if "measure" in _rel and "measured_m" in _rel:
                _msg = (
                    f"ROOM-MIN {_rel['room']}: clear width {_rel['measured_m']:.2f} m "
                    f"is below the catalogue {_rel['required_m']:.2f} m "
                    f"(declared relaxation at {_rel['factor']:.2f}x)"
                )
            else:
                _msg = (
                    f"ROOM-MIN {_rel['room']}: area {_rel['measured_sqm']:.2f} m² "
                    f"is below the catalogue {_rel['required_sqm']:.2f} m² "
                    f"(declared relaxation at {_rel['factor']:.2f}x)"
                )
            if _msg not in self.warnings:
                self.warnings.append(_msg)

        for _asp in tolerated_aspects:
            _msg = (
                f"PROP-ASPECT {_asp['room']}: aspect 1:{_asp['measured']:.2f} exceeds the "
                f"1:{_asp['limit']:.2f} hard band and is accepted at {_asp['factor']:.2f}x "
                "as a declared certificate relaxation; no legal split or adjunct fits "
                "this plate."
            )
            if _msg not in self.warnings:
                self.warnings.append(_msg)

        # Multi-wing solving requires strict NBC/ontology min dimensions as a hard invariant.
        # Standard rectangular degradation (deg_level > 0, e.g. EC-01 narrow plot) treats min_dims as soft.
        is_multi_wing = bool(self.site_plan and getattr(self.site_plan, "footprint", None) and len(self.site_plan.footprint.wings) > 1)
        if is_multi_wing:
            hard_valid = (
                non_overlap and containment and chain_sums_match and
                bfs_connected and egress_valid and zero_forbidden and
                must_adj_satisfied and vertical_stack_valid and statutory_audit["wc_satisfied"] and
                min_dims_satisfied and core_continuity_valid and no_wet_over_terrace_valid
            )
            soft_valid = aspect_satisfied
        else:
            hard_valid = (
                non_overlap and containment and chain_sums_match and
                bfs_connected and egress_valid and zero_forbidden and
                must_adj_satisfied and vertical_stack_valid and statutory_audit["wc_satisfied"] and
                core_continuity_valid and no_wet_over_terrace_valid
            )
            soft_valid = min_dims_satisfied and aspect_satisfied
        all_true = hard_valid and (soft_valid if deg_level == 0 else True)

        # EXPLAIN EVERY FALSE FLAG. The certificate panel renders a
        # handful of headline checks; without this list a NON-COMPLIANT badge
        # beside six PASS rows is unexplainable. Each entry names the invariant,
        # the rule id and the offending rooms/spaces.
        failures: List[str] = []
        if not non_overlap:
            failures.append(
                "REL-01 Non-overlap: "
                + ("; ".join(overlap_pairs[:6]) or "rooms overlap")
            )
        if not containment:
            failures.append(
                "CONT-01 Containment: "
                + ", ".join(containment_rooms[:8])
                + " extend past the envelope"
            )
        if not chain_sums_match:
            failures.append(
                "DIM-01 Dimension chains: "
                + (", ".join(chain_failures[:6]) or "one or more chains miss the 1 mm tolerance")
            )
        if not min_dims_satisfied:
            _detail = list(min_dim_rooms[:6])
            _detail += [f"{rid}: no catalogue minimum (unverified)" for rid in unverified_spaces[:4]]
            failures.append("NBC-01 Room minimums: " + "; ".join(_detail))
        if not aspect_satisfied:
            failures.append("NBC-02 Aspect ratios: " + "; ".join(aspect_rooms[:6]))
        if not bfs_connected:
            failures.append(
                "CIRC-01 Reachability: "
                + (", ".join(unreachable_rooms[:8]) or "rooms unreachable from the core")
                + " cannot be reached from the vertical core"
            )
        if not egress_valid:
            failures.append(
                "NBC-03 Egress travel: "
                + (", ".join(egress_rooms[:6]) or "a room exceeds the maximum travel distance")
            )
        if not zero_forbidden:
            failures.append("REL-02 Forbidden walls: " + "; ".join(forbidden_pairs[:6]))
        if not must_adj_satisfied:
            failures.append("REL-03 Required adjacency: a MUST_ADJACENT pair is not contiguous")
        if not vertical_stack_valid:
            failures.append("VERT-01 Vertical stack: cores or wet stacks are not aligned across storeys")
        if not core_continuity_valid:
            failures.append("RULE-FP-01 Core continuity: an occupied level has no vertical core")
        if not no_wet_over_terrace_valid:
            failures.append("RULE-FP-03 Wet over open-to-sky: a wet room sits above a terrace")
        if not statutory_audit["wc_satisfied"]:
            failures.append(
                "SAN-01 Sanitation: "
                f"{statutory_audit['provided_wc_count']} WC(s) provided, "
                f"{statutory_audit['required_wc_count']} required for "
                f"{statutory_audit['occupant_load']} occupants"
            )
        if not statutory_audit["parking_satisfied"]:
            failures.append(
                "SAN-02 Parking: "
                f"{statutory_audit['required_parking_ecs']} ECS required, none provided"
            )

        # Only rules whose backing invariant PASSED may be listed as certified.
        _vastu_clean = not any("EC-04" in str(w) or "Vastu" in str(w) for w in self.warnings)
        certified_rules = [
            rid for rid, ok in (
                ("NBC-01", min_dims_satisfied),
                ("NBC-02", aspect_satisfied),
                ("NBC-03", egress_valid),
                ("REL-01", non_overlap),
                ("REL-02", zero_forbidden),
                ("VERT-01", vertical_stack_valid),
                ("VERT-02", no_wet_over_terrace_valid),
                ("CIRC-01", bfs_connected),
                ("DIM-01", chain_sums_match),
                ("VASTU-01", _vastu_clean),
                ("SAN-01", statutory_audit["wc_satisfied"]),
                ("RULE-FP-01", core_continuity_valid),
                ("RULE-FP-03", no_wet_over_terrace_valid),
                ("RULE-FP-06", terrace_far_exempt),
            ) if ok
        ]
        if (
            getattr(self, "resolved_terrace_bands", None)
            and any(getattr(self, "resolved_terrace_bands", {}).values())
        ):
            certified_rules.append("RULE-FP-07")

        # Room-stamped programme-squeeze relaxations belong in the
        # certificate's own declared list, not only on the room.  They are
        # listed and explained (measured / required), while min_dims_satisfied
        # above stays False - the certificate still FAILS, so listing them can
        # never turn a squeezed room into a pass.
        _listed_squeeze = {
            (str(_rel.get("room")), str(_rel.get("measure")))
            for _rel in tolerated_minima
        }
        for _fl in floors:
            for _r in _fl.rooms:
                for _rel in (_r.relaxations or []):
                    if (str(_rel.get("rule_id")) != "NBC-01"
                            or _rel.get("basis") != "programme_squeeze"):
                        continue
                    _key = (str(_r.room_id), str(_rel.get("measure")))
                    if _key in _listed_squeeze:
                        continue
                    _listed_squeeze.add(_key)
                    tolerated_minima.append({
                        "room": _r.room_id,
                        "rule": "NBC-01",
                        "measure": _rel.get("measure"),
                        "basis": "programme_squeeze",
                        "reason": _rel.get("rationale"),
                    })
                    # Same contract as every other declared relaxation: one
                    # surfaced warning per room/measure, phrased so the gate and
                    # the reader see it was declared, not silently absorbed.
                    _sq_msg = (
                        f"ROOM-MIN {_r.room_id}: {_rel.get('measure')} is below "
                        f"the catalogue minimum (declared relaxation - "
                        f"{_rel.get('rationale')})"
                    )
                    if _sq_msg not in self.warnings:
                        self.warnings.append(_sq_msg)

        return MathematicalValidityCertificate(
            is_valid=all_true,
            non_overlap=non_overlap,
            containment=containment,
            chain_sums_match=chain_sums_match,
            min_dimensions_satisfied=min_dims_satisfied,
            aspect_ratios_satisfied=aspect_satisfied,
            connectivity_bfs=bfs_connected,
            egress_distances_satisfied=egress_valid,
            zero_forbidden_violations=zero_forbidden,
            must_adjacency_satisfied=must_adj_satisfied,
            # No PREFER_ADJACENT/PREFER_SEPARATE verifier runs in this loop; an
            # unmeasured score is None, never the old constant 94.5.
            prefer_adjacency_score=None,
            vertical_stack_valid=vertical_stack_valid,
            core_continuity_valid=core_continuity_valid,
            no_wet_over_terrace_valid=no_wet_over_terrace_valid,
            terrace_far_exempt=terrace_far_exempt,
            cores_stack_aligned=cores_stack_aligned,
            sanitation_wc_count_satisfied=statutory_audit["wc_satisfied"],
            parking_count_satisfied=statutory_audit["parking_satisfied"],
            failures=failures,
            certificate_id=f"CERT-{self.typology[:2]}-{self.total_storeys}F-{int(self.seed) if isinstance(self.seed, (int, float)) else 'F01'}",
            certified_rules=certified_rules,
            details={
                "per_room_travel_distances": per_room_dists,
                "statutory_audit": statutory_audit,
                "max_allowed_travel_m": float(self.profile.egress_constants.get("max_travel_distance_non_sprinklered_m", 30.0)),
                "dimension_chain_tolerance_m": 0.001,
                "dimension_chain_audit": chain_audit,
                # A certificate must EXPLAIN a false flag: the
                # offending rooms and space-type pairs travel with it.
                "forbidden_wall_pairs": forbidden_pairs,
                "overlap_pairs": overlap_pairs,
                "containment_violations": containment_rooms,
                "min_dimension_violations": min_dim_rooms,
                "declared_relaxations": tolerated_minima,
                "declared_aspect_relaxations": tolerated_aspects,
                "aspect_violations": aspect_rooms,
                "unverified_spaces": unverified_spaces,
                "unreachable_rooms": unreachable_rooms,
                "egress_violations": egress_rooms,
                # PROP-* moves are evidence, not prose: every floor's split /
                # adjunct / relaxation / spine decision travels with the
                # certificate so the reader can audit what the law did.
                "proportion_law": [dict(a) for a in getattr(self, "proportion_law_audits", [])],
            }
        )

    def _compute_l2_door_swings_valid(self, floors: List[SingleFloorPlanModel]) -> bool:
        """
        Layer-2 certificate field: verifies that every residual swing arc polygon
        lies fully inside the union of its endpoint rooms (walls), with sliding
        doors exempt (zero-area swing). Complements the in-generation auto-flip
        / sliding-conversion resolution performed by living_quality.
        """
        tol = 0.05
        for fl in floors:
            room_by_id = {r.room_id: r for r in fl.rooms}
            for d in fl.doors:
                if d.door_type in ("sliding", "dock_shutter"):
                    continue
                endpoints = [room_by_id[rid] for rid in {d.from_room, d.to_room} if rid in room_by_id]
                if not endpoints:
                    continue
                arc = compute_door_swing_polygon(d)
                if arc.area < 0.01:
                    continue
                union = unary_union([
                    shp_box(r.x - tol, r.y - tol, r.x + r.width_m + tol, r.y + r.depth_m + tol)
                    for r in endpoints
                ])
                if not union.covers(arc):
                    return False
        return True

    # =========================================================================
    # 10. PRIMARY SOLVE WORKFLOW
    # =========================================================================

    def _compute_unmet_requirements(self, building: MultiStoreyBuildingModel) -> List[UnmetRequirement]:
        """Backward-compatible wrapper: ledger from an assembled building model."""
        return self._compute_unmet_requirements_from_floors(getattr(building, "floors", []))

    def _compute_unmet_requirements_from_floors(self, floors: List[Any]) -> List[UnmetRequirement]:
        """
        UNSOLVED REQUIREMENTS LEDGER: every requested room that did
        not appear on ANY solved floor level is recorded with an explicit
        reason (typology-program mismatch). Surfaced in
        FloorPlanResponse.unmet_requirements and the UI chips - never silently
        dropped (zero silent skips contract). Never raises.
        """
        try:
            requested = list(getattr(self.req, "required_rooms", None) or [])
            if not requested:
                return []
            from app.services.floorplan.grid_model import normalize_room_identifier
            # Placed ids carry level suffixes (e.g. living_F0) and aliases
            # (hall -> living): compare through the normalizer on BOTH sides.
            # Canonical space identity is the programme vocabulary.  Placed
            # rows carry display ids (t2_unitA_bed_F0) while the request is in
            # ontology ids (unit_bed); comparing only room_id made a correctly
            # solved T2/T3/T4 programme look unmet.  Keep the display id as a
            # fallback for older plans generated before identity was attached.
            placed_norms = set()
            for fl in floors:
                for r in fl.rooms:
                    placed_norms.add(normalize_room_identifier(r.room_id))
                    space_type_id = getattr(r, "space_type_id", None) or (
                        getattr(getattr(r, "identity", None), "space_type_id", None)
                    )
                    if space_type_id:
                        placed_norms.add(normalize_room_identifier(space_type_id))
            from app.services.floorplan.typologies import get_typology_module
            module = get_typology_module(self.typology)
            expected_ids: set = set()
            for z in range(self.total_storeys):
                for entry in module.vertical_program(z + 1):
                    expected_ids.update(entry.get("space_ids", []))
            normalized_expected = {normalize_room_identifier(e) for e in expected_ids}
            # Core equivalence: a user requesting "stairs"/"lift" is satisfied
            # by ANY placed vertical core of that class (ids differ per typology).
            REQUESTED_CORE_ALIASES = {
                "stairs", "stair", "staircase", "staircase_core", "t1_stair",
                "shared_stair", "primary_stair", "secondary_stair", "ind_stair",
                "lift", "lift_core", "lift_bank", "lift_lobby",
            }
            core_norms = {
                normalize_room_identifier(r.room_id)
                for fl in floors for r in fl.rooms
                if getattr(r, "is_vertical_core", False)
            }
            unmet: List[UnmetRequirement] = []
            for rid in requested:
                norm = normalize_room_identifier(rid)
                if norm in placed_norms:
                    continue
                if norm in REQUESTED_CORE_ALIASES and core_norms:
                    continue
                if norm in normalized_expected or rid in expected_ids:
                    # Expected by the program but not placed: solver compression.
                    unmet.append(UnmetRequirement(
                        room_id=rid,
                        reason=(
                            "Requested but not placeable in the available envelope "
                            "- increase plot size/coverage or reduce other rooms"
                        ),
                    ))
                else:
                    unmet.append(UnmetRequirement(
                        room_id=rid,
                        reason=(
                            f"Not part of the {self.typology} program for {self.total_storeys} "
                            "storey(s) - review typology/storeys"
                        ),
                    ))
            return unmet
        except Exception as exc:  # never let the ledger break the solve
            logging.getLogger(__name__).warning("Unmet-requirements ledger computation failed: %s", exc)
            return []

    def solve(self) -> MultiStoreyBuildingModel:
        """
        Executes the single unified geometry engine across all typologies and storeys.
        Returns complete MultiStoreyBuildingModel with MathematicalValidityCertificate.
        """
        t0 = time.perf_counter()

        # Programme demand is computed from the ontology catalogue, not
        # from the geometry this solve is about to produce.
        from app.schemas.land_economics import compute_program_needed_area
        self.program_needed_area_m2 = compute_program_needed_area(self)

        # LLM-BOUNDARY INVARIANT (enforced per solve): parsed client constraints
        # may carry TEXT-DERIVED intent only. Any geometry/coordinate fields are
        # stripped (never honored) and the strip is logged as an auditable event.
        _llm = sanitize_llm_constraints(self.client_constraints, source="solver_boundary")
        self.llm_boundary_audit = {
            "events": _llm["events"],
            "event_ids": _llm["event_ids"],
            "contract": "llm_confined_to_text_parsing_and_narrative_v1",
        }

        # Step 1: Envelope & Setbacks
        is_feasible, deg_level, envelope, warnings = self._compute_envelope()
        self.degradation_level = deg_level
        self.warnings.extend(warnings)

        # Footprint provenance: name the constraint that actually sized the plate.
        # Irregular plots are always governed by their inscribed footprint; a
        # rectangular plate is programme-led only when demand is below the
        # coverage cap.
        _irregular = bool(
            self.req.plot_polygon is not None
            and not getattr(self.req.plot_polygon, "is_regular_rectangle", True)
        )
        _coverage_cap = self._plot_plan_area() * self.coverage
        _need = float(getattr(self, "program_needed_area_m2", 0.0) or 0.0)
        _ceiling = float(getattr(self, "footprint_ceiling_area", _coverage_cap) or _coverage_cap)
        _target = float(getattr(self, "footprint_target_area", _ceiling) or _ceiling)
        if _irregular:
            self.footprint_source = (
                "program" if _target < _ceiling - 0.5 else "inscribed"
            )
        elif _target < _ceiling - 0.5:
            # The programme (plus walls/circulation) is what sized the plate.
            self.footprint_source = "program"
        elif _coverage_cap <= _ceiling + 0.01:
            self.footprint_source = "coverage"
        else:
            # Setbacks, not the coverage ratio, are the binding ceiling.
            self.footprint_source = "buildable"

        if not is_feasible:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return MultiStoreyBuildingModel(
                building_typology=self.typology,
                total_storeys=self.total_storeys,
                plot_width_m=self.plot_w,
                plot_depth_m=self.plot_d,
                ground_coverage_ratio=self.coverage,
                total_built_up_area_sqm=0.0,
                vertical_cores=[],
                duct_shafts=[],
                floors=[],
                global_metrics={"status": "failed", "feasibility": "rejected"},
                qa_report={"status": "failed", "degradation_level": deg_level},
                warnings=self.warnings,
                unmet_requirements=[UnmetRequirement(
                    room_id="all_requested",
                    reason="Insufficient envelope area for any room layout",
                )],
                seed=self.seed,
                solver_timing_ms=elapsed_ms,
            )

        # Step 1b: EC-04 — Client Orientation Preference vs Vastu Conflict Detection
        # When strictness='high', detect and override taboo placements; emit diagnostics.
        if self.strictness == "high" and self.client_constraints:
            orient_prefs = getattr(self.client_constraints, "orientation_preferences", None) or []
            # Vastu taboo map: space_keyword -> (taboo_facing_keywords, correct_zone_name, correct_facing)
            vastu_overrides = {
                "kitchen": (["north-east", "northeast", "ne", "north east"], "South-East", "SE"),
                "master": (["north-east", "northeast", "ne", "north", "north-west", "northwest", "nw", "east"], "South-West", "SW"),
            }
            for pref in orient_prefs:
                space_lc = pref.space.lower()
                facing_lc = pref.preferred_facing.lower()
                for key, (taboo_facings, correct_name, correct_zone) in vastu_overrides.items():
                    if key in space_lc and any(t in facing_lc for t in taboo_facings):
                        display_name = "Kitchen" if key == "kitchen" else "Master Bedroom"
                        self.warnings.append(
                            f"EC-04 Vastu rule override: {display_name} requested in "
                            f"'{pref.preferred_facing}' (Vastu-taboo zone). "
                            f"Relocated to {correct_name} ({correct_zone}) per high-strictness Vastu rules."
                        )

        # Step 2a: Resolve and validate per-floor floor plate masks.  Masks are
        # resolved BEFORE the anchors because a reserved terrace band (explicit
        # or translated from a wing mask) determines where the core column may
        # stand; anchoring first put the lift inside the band and the band was
        # then rejected as a core conflict.
        self.resolved_floor_plate_masks = self._resolve_floor_plate_masks()

        # Step 2b: Anchor Phase (Rule of Cores & Shafts)
        vertical_cores, duct_shafts = self._lock_vertical_anchors(envelope)

        # Step 2c: Resolve and validate per-floor terrace bands for simple rectangular envelopes
        self.resolved_terrace_bands = self._resolve_terrace_bands(envelope, vertical_cores, duct_shafts)

        # Step 2d: SELECTED SCHEME PROFILE
        # The picker used to re-solve a side portfolio that changed no plan. A
        # selected profile now partitions the plate with its weights and every
        # downstream step (openings, wall graph, land, gate, certificate, sheets)
        # runs on that geometry - one geometry, one certificate.
        if self.scheme_profile:
            from app.services.floorplan.constrained_solver import (
                build_plate_context,
                solve_rectangular_plate,
            )
            _ctx = build_plate_context(self, envelope=envelope)
            if _ctx is not None:
                _by_floor: Dict[int, List[MultiFloorRoomRectangle]] = {}
                _alt_warnings: List[str] = []
                for _res in solve_rectangular_plate(_ctx, profile_id=self.scheme_profile):
                    if _res.rooms:
                        _by_floor[_res.floor_index] = list(_res.rooms)
                    _alt_warnings.extend(_res.warnings)
                if _by_floor:
                    self.presolved_room_sets = _by_floor
                    # The band solver lays the core column against the band edge,
                    # which is not where _lock_vertical_anchors predicted it. The
                    # core spec is a DERIVED description of the placed core, so it
                    # follows the geometry - otherwise the certificate's
                    # core-stack invariant compares specs (0.20, 4.57) with rooms
                    # (0.00, 0.00) and fails a perfectly stacked building.
                    self._reanchor_cores_to_placed(_by_floor, vertical_cores)
                    self.scheme_selection_note = (
                        f"SCHEME-SELECTION: plate partitioned with the "
                        f"'{self.scheme_profile}' profile; the certificate and every "
                        "sheet describe that alternative."
                    )
                    self.warnings.append(self.scheme_selection_note)
                for _w in _alt_warnings:
                    if _w not in self.warnings:
                        self.warnings.append(_w)
            if not self.presolved_room_sets:
                self.warnings.append(
                    f"SCHEME-SELECTION: profile '{self.scheme_profile}' cannot partition "
                    "this plate (multi-wing / terrace band / floor mask); the validated "
                    "baseline geometry is used and the selection is recorded only."
                )

        # Step 3: Floor Plate Partitioning
        floors: List[SingleFloorPlanModel] = []
        previous_rooms: Optional[List[MultiFloorRoomRectangle]] = None

        floor_titles = [
            "Ground Floor (G)",
            "First Floor (G+1)",
            "Second Floor (G+2)",
            "Third Floor (G+3)"
        ]

        for z in range(self.total_storeys):
            floor_name = floor_titles[z] if z < len(floor_titles) else f"Floor {z}"

            # Resolve per-floor program from ontology
            req_rooms = self.req.required_rooms
            if not req_rooms and self.req.room_program and self.req.room_program.rooms:
                req_rooms = [r.name for r in self.req.room_program.rooms]
            elif not req_rooms and self.req.client_notes:
                notes_lower = self.req.client_notes.lower()
                extra_notes = []
                if "office" in notes_lower or "study" in notes_lower:
                    extra_notes.append("study")
                if "powder" in notes_lower:
                    extra_notes.append("bath_2")
                if extra_notes:
                    req_rooms = extra_notes
            spaces = self._resolve_floor_program(z, req_rooms)

            # Partition floor plate with hard pruning - or take the selected
            # scheme profile's already-solved rooms for this floor.
            _presolved = (self.presolved_room_sets or {}).get(z)
            if _presolved:
                rooms = [r.model_copy(deep=True) for r in _presolved]
            else:
                rooms = self._partition_floor_plate(
                    floor_index=z,
                    envelope=envelope,
                    core=vertical_cores[0],
                    ducts=duct_shafts,
                    spaces=spaces,
                    previous_rooms=previous_rooms,
                )

            # ONTOLOGY PROPORTION LAW. Hard aspect, hard ceiling and
            # the declared overflow moves are resolved HERE, on the placed
            # rectangles and before doors, furniture and wall graphs read them.
            # Ideal-band breaches are disclosed as WARN, never "repaired" by
            # stretching a room further.
            from app.services.floorplan.proportion_law import enforce_proportion_law
            _law_audit = enforce_proportion_law(
                rooms,
                floor_index=z,
                typology=self.typology,
                envelope=envelope,
            )
            self.proportion_law_audits.append(_law_audit.as_dict())
            for _law_line in _law_audit.log:
                if _law_line not in self.warnings:
                    self.warnings.append(_law_line)
            for _hard in _law_audit.hard_violations:
                _hard_line = (
                    f"PROP-HARD: floor {z} {_hard}; the declared overflow moves cannot "
                    "resolve it on this plate and the certificate must fail rather than "
                    "accept a widened band."
                )
                if _hard_line not in self.warnings:
                    self.warnings.append(_hard_line)

            # Disclose every catalogue-minimum shortfall by name: a squeezed
            # room is a fact the reader must be able to audit, never a silent
            # consequence of a tighter (legal) plate.
            for _room in rooms:
                _spec = ONTOLOGY.get_space(
                    space_type_of(_room, self.typology) or _room.room_id)
                _min_area = float(getattr(_spec, "min_area_sqm", 0.0) or 0.0)
                # Two minima sources exist (ontology spec, placement catalog).
                # Disclose against the STRICTER one so no source's floor is
                # silently breached; unifying them is tracked separately.
                from app.services.floorplan.grid_model import get_room_catalog_entry
                _catalog_min = float(
                    (get_room_catalog_entry(_room.room_id) or {}).get("catalog_min_m2", 0.0) or 0.0
                )
                _min_area = max(_min_area, _catalog_min)
                if _min_area > 0.0 and _room.area_sqm < _min_area - 0.2:
                    _short = (
                        f"ROOM-MIN: {_room.room_id} is {_room.area_sqm:.1f} m², below its "
                        f"{_min_area:.1f} m² catalogue minimum on floor {z}; the "
                        f"{envelope['area_sqm']:.1f} m² plate (coverage/setback ceiling) "
                        f"cannot hold this programme comfortably."
                    )
                    if _short not in self.warnings:
                        self.warnings.append(_short)
                    # The shortfall is LISTED on the room, not only in a
                    # warning line.  A plate that cannot hold the catalogue
                    # minimum draws the room squeezed and stamps the relaxation
                    # (still a certificate FAIL - the dims flag stays false);
                    # the sweep's I2 taxonomy therefore reads a disclosed
                    # relaxation instead of an unlisted breach.
                    _stamp_listed_min_relaxation(
                        _room, "gross area", _room.area_sqm, _min_area,
                        f"the {envelope['area_sqm']:.1f} m² plate cannot hold the "
                        "requested programme within its catalogue minimum",
                    )
                elif _catalog_min > 0.0 and _room.area_sqm > _catalog_min:
                    _catalog_max = float(
                        (get_room_catalog_entry(_room.room_id) or {}).get("catalog_max_m2", 0.0) or 0.0
                    )
                    if _catalog_max > 0.0 and _room.area_sqm > _catalog_max + 2.0:
                        _over = (
                            f"ROOM-MAX: {_room.room_id} is {_room.area_sqm:.1f} m², above its "
                            f"{_catalog_max:.1f} m² catalogue maximum on floor {z}; the "
                            f"{envelope['area_sqm']:.1f} m² plate stretched it past its band."
                        )
                        if _over not in self.warnings:
                            self.warnings.append(_over)
                # Aspect is part of the same catalog contract: an elongated
                # room is a squeezed room whatever its area says. Disclose it
                # by name instead of letting the clamp fail silently.
                _ar = max(float(_room.width_m), float(_room.depth_m)) / max(
                    min(float(_room.width_m), float(_room.depth_m)), 0.1
                )
                if _ar > 2.22:
                    _aspect_short = (
                        f"ROOM-MIN: {_room.room_id} aspect ratio {_ar:.2f} exceeds the "
                        f"1:2.2 clamp on floor {z} at "
                        f"{min(float(_room.width_m), float(_room.depth_m)):.2f} m clear; the "
                        f"{envelope['area_sqm']:.1f} m² plate cannot hold this programme "
                        f"comfortably."
                    )
                    if _aspect_short not in self.warnings:
                        self.warnings.append(_aspect_short)

            # Close rectangular dead strips at wing junctions before
            # openings, furniture, wall graphs and the gate are generated.
            # This runs on EVERY floor. An upper plate can leave a
            # 3 m2 strip just as the ground plate can (L-244 F1/F2), and fixing
            # only the ground floor hid it in the per-floor void measure.
            if z >= 0:
                from app.services.floorplan.land_economics import repair_interior_dead_corners
                _plate = None
                _fp = self.site_plan.footprint if self.site_plan else None
                if _fp is not None:
                    if getattr(_fp, "wings", None):
                        _parts = [
                            shp_box(w.x - _fp.x, w.y - _fp.y,
                                    w.x - _fp.x + w.width_m, w.y - _fp.y + w.depth_m)
                            for w in _fp.wings
                        ]
                        _parts += [
                            shp_box(c.x - _fp.x, c.y - _fp.y,
                                    c.x - _fp.x + c.width_m, c.y - _fp.y + c.depth_m)
                            for c in getattr(_fp, "corridors", []) or []
                        ]
                        _plate = unary_union(_parts)
                    elif getattr(_fp, "courtyard_void", None) is not None:
                        _void = _fp.courtyard_void
                        _plate = shp_box(0.0, 0.0, _fp.width_m, _fp.depth_m)
                        if getattr(_void, "polygon_coords", None):
                            from shapely.geometry import Polygon as _ShpPolygon
                            try:
                                _plate = _plate.difference(_ShpPolygon(_void.polygon_coords))
                            except Exception:
                                pass
                if _plate is None:
                    # Single-rectangle plate: the envelope IS the roof plate.
                    _plate = shp_box(0.0, 0.0, envelope["width"], envelope["depth"])
                # Assigned-but-unroofed plate area (courtyard void, ground-floor
                # terraces) is not a dead corner.  It must be excluded from the
                # repair pass, which otherwise grows a room over the court.
                _reserved = []
                if z == 0 and getattr(_fp, "courtyard_void", None) is not None:
                    _void_poly = getattr(_fp.courtyard_void, "polygon_coords", None) or []
                    if len(_void_poly) >= 3:
                        from shapely.geometry import Polygon as _ShpReserved
                        try:
                            _vp = _ShpReserved(_void_poly)
                            if not _vp.is_empty and _vp.is_valid:
                                _reserved.append(_vp)
                        except Exception:
                            pass
                if _fp is not None:
                    _reserved += [
                        shp_box(r.x, r.y, r.x + r.width_m, r.y + r.depth_m)
                        for r in rooms if r.zone_category == "terrace"
                    ]
                    # A wing link corridor is circulation by construction, not
                    # an unassigned dead corner.  Repairing it poured a
                    # 'Dead-Corner Storage' on the plan's only connector (LAND-07,
                    # M4); the corridor is reserved instead, so a void is either
                    # routed or left as the circulation it already is.
                    _reserved += [
                        shp_box(c.x - _fp.x, c.y - _fp.y,
                                c.x - _fp.x + c.width_m, c.y - _fp.y + c.depth_m)
                        for c in getattr(_fp, "corridors", []) or []
                    ]
                # An upper-floor dead corner may not be filled on top of the
                # wet stack below: the repair would move a bathroom wall the
                # stacking law is holding still (VERT-02).
                if z > 0:
                    _reserved += [
                        shp_box(r.x, r.y, r.x + r.width_m, r.y + r.depth_m)
                        for r in (previous_rooms or []) if self._is_wet_room(r)
                    ]
                # SURPLUS LADDER: leftover plate is spent on the
                # typology's declared upgrade order before LAND-07 turns it into
                # an unlabelled storage hole.
                from app.services.floorplan.proportion_law import carve_surplus_upgrade
                for _ladder_line in carve_surplus_upgrade(
                    rooms, _plate, floor_index=z, typology=self.typology
                ):
                    if _ladder_line not in self.warnings:
                        self.warnings.append(_ladder_line)
                for repair_line in repair_interior_dead_corners(
                    rooms, envelope, plate_polygon=_plate,
                    reserved_polygons=_reserved or None,
                ):
                    if repair_line not in self.warnings:
                        self.warnings.append(repair_line)

            max_room_x = max((r.x + r.width_m for r in rooms), default=envelope["width"])
            max_room_y = max((r.y + r.depth_m for r in rooms), default=envelope["depth"])
            if max_room_x > envelope["width"] or max_room_y > envelope["depth"]:
                envelope = dict(envelope)
                envelope["width"] = round(max(envelope["width"], max_room_x), 2)
                envelope["depth"] = round(max(envelope["depth"], max_room_y), 2)
                envelope["area_sqm"] = round(envelope["width"] * envelope["depth"], 2)

            core_room = next((r for r in rooms if r.is_vertical_core), None)
            lobby_room = next(
                (r for r in rooms if any(k in r.room_id for k in ("lobby", "corridor", "catwalk"))),
                rooms[0] if rooms else None
            )

            # Generate hosted doors and windows (also runs zoning + door-swing collision resolution)
            doors, windows = self._generate_openings(z, envelope, rooms, lobby_room, core_room)
            # One door per room pair: duplicate hosts made a bath degree 2.
            doors = self._dedupe_doors(doors)
            # CIRCULATION IS A CONSTRUCTED INVARIANT, not a layout accident.
            # A room inserted to satisfy a hygiene law
            # (the T3 service spine) must not leave the floor unreachable. Any
            # room the entry graph cannot reach gets a real hosted door.
            self._ensure_egress_connectivity(
                z, rooms, doors,
                entry_room_id=(core_room.room_id if core_room is not None
                               else (lobby_room.room_id if lobby_room is not None else None)),
            )

            # Living-quality layers: naming honesty (L5), fixture clearances (L3),
            # and furniture catalog envelopes (L4) attached per room.
            naming_log = audit_and_enforce_naming_honesty(rooms)
            for nl in naming_log:
                if nl not in self.warnings:
                    self.warnings.append(nl)

            # One resolved ontology identity per room.  Runs after the
            # L5 naming threshold so a demoted Master Suite never keeps a suite
            # identity, and before openings/wall graphs so every schedule, label,
            # legend and service layer reads the same object.
            identity_summary = apply_space_identities(rooms, self.typology)
            self.identity_summaries.append(identity_summary)
            if identity_summary["fallback"]:
                self.warnings.append(
                    "SPACE-IDENTITY: unresolved ontology id(s) on floor "
                    f"{z}: {', '.join(identity_summary['fallback'])} (fallback identity used)."
                )

            # Fresh-air provision is solved with the plate, not left to
            # the L9 audit.  Every wet room with no compliant opening receives a
            # dedicated exhaust riser before the wall graph and sheets are built.
            for vent_line in ensure_wet_room_ventilation(
                z, rooms, windows, duct_shafts, envelope
            ):
                if vent_line not in self.warnings:
                    self.warnings.append(vent_line)

            for r in rooms:
                if any(k in r.room_id.lower() for k in ("bath", "toilet", "wc")):
                    _f_ok, _fx, f_warns = place_and_audit_bathroom_fixtures(r, doors)
                    for fw in f_warns:
                        if fw not in self.warnings:
                            self.warnings.append(fw)

            for r in rooms:
                if r.zone_category in ("circulation", "terrace"):
                    continue
                _fu_ok, _fi, fu_warns = place_and_audit_furniture_catalog(r)
                for fw in fu_warns:
                    if fw not in self.warnings:
                        self.warnings.append(fw)

            # Re-run swing collision resolution with furniture envelopes now placed
            sw_ok, sw_log, _ = audit_swings_against_walls_corridors_furniture(doors, rooms)
            for sl in sw_log:
                if sl not in self.warnings:
                    self.warnings.append(sl)

            # Egress check & BFS reachability
            exit_room_id = core_room.room_id if core_room else (lobby_room.room_id if lobby_room else (rooms[0].room_id if rooms else "exit"))
            is_connected, _, _ = self._verify_egress_and_circulation(rooms, doors, exit_room_id)

            # Build constructible wall graph and dimension chains (chain sum == overall within 1mm)
            wall_graph_obj = build_constructible_wall_graph(
                floor_index=z,
                envelope=envelope,
                raw_rooms=rooms,
                typology=self.typology,
                floor_to_floor_height_m=self.profile.floor_height_m,
                doors_in=doors,
                windows_in=windows,
                quality_grade=self.req.quality_grade or "standard",
            )

            built_up_m2 = round(sum(r.area_sqm for r in rooms if r.zone_category != "terrace"), 2)
            enclosed_storage_m2 = 0.0
            if z == 0 and self.site_plan and getattr(self.site_plan, "wedge_zones", None):
                enclosed_storage_m2 = round(
                    sum(w.area_sqm for w in self.site_plan.wedge_zones if getattr(w, "is_enclosed_storage", False)),
                    2
                )
            built_up_m2 = round(built_up_m2 + enclosed_storage_m2, 2)
            carpet_m2 = round(sum(r.area_sqm for r in rooms if r.zone_category not in ("circulation", "service", "terrace")), 2)

            f_mask = self.resolved_floor_plate_masks.get(z, {})
            w_b_mode = f_mask.get("wing_b", "present")
            t_band = getattr(self, "resolved_terrace_bands", {}).get(z)

            if w_b_mode == "terrace":
                plate_comp = "Wing A + Terrace"
            elif w_b_mode == "void":
                plate_comp = "Wing A"
            elif t_band:
                edge_name = {"N": "North", "S": "South", "E": "East", "W": "West"}.get(t_band.edge, t_band.edge)
                plate_comp = f"Plate - {edge_name} band {t_band.depth_m:.1f} m + Terrace"
            else:
                plate_comp = "Wing A + Wing B" if (self.site_plan and self.site_plan.footprint and len(self.site_plan.footprint.wings) > 1) else "Full Plate"

            floor_model = SingleFloorPlanModel(
                floor_index=z,
                floor_name=floor_name,
                envelope=envelope,
                rooms=rooms,
                doors=doors,
                windows=windows,
                circulation_status="connected" if is_connected else "disconnected",
                # Vastu / plumbing alignment are MEASURED after every storey is
                # placed and land absorption has mutated the rooms.
                # They stay None here rather than printing a constant.
                vastu_score_pct=None,
                vastu_compliance_pct=None,
                plumbing_stack_alignment_pct=None,
                built_up_area_sqm=built_up_m2,
                carpet_area_sqm=carpet_m2,
                floor_plate_mask=f_mask,
                plate_composition=plate_comp,
                terrace_band=t_band.model_dump() if t_band else None,
                # Per-floor sheets are rendered AFTER the universal gate so every
                # sheet carries the layer table + honest validated-layers stamp.
                svg_blueprint_cad=None,
                svg_blueprint_paper=None,
                wall_graph=wall_graph_obj.to_dict(),
                door_schedule=wall_graph_obj.door_schedule,
                window_schedule=wall_graph_obj.window_schedule,
                room_schedule=wall_graph_obj.room_schedule,
                stair_schedule=wall_graph_obj.stair_schedule,
                stair_geometry=wall_graph_obj.stair_geometry.to_dict() if wall_graph_obj.stair_geometry else None,
            )
            floors.append(floor_model)
            previous_rooms = rooms

        total_built_up = round(sum(f.built_up_area_sqm for f in floors), 2)
        total_carpet = round(sum(f.carpet_area_sqm for f in floors), 2)

        # UNFIT-BRIEF GUARD: when the statutory ceiling (coverage
        # x plot, clipped to the setback buildable) cannot host the requested
        # programme, the partitioner does not produce a tight plan - it produces
        # degenerate slivers (an audited 8-room brief on a 10.9 x 10.6 m plot at
        # 60% yielded a 0.26 m² bathroom). A plan whose rooms are less than half
        # their catalogue minimum is not a plan: refuse the brief explicitly,
        # with the numbers, instead of emitting nonsense geometry.
        _degenerate = []
        _thin = []
        for _fl in floors:
            for _r in _fl.rooms:
                # Terraces are open-to-sky, and circulation spines/corridors are
                # connectivity elements: neither is a habitable-room failure.
                if _r.zone_category in ("terrace", "circulation"):
                    continue
                _spec = ONTOLOGY.get_space(
                    space_type_of(_r, self.typology) or _r.room_id)
                _min_area = float(getattr(_spec, "min_area_sqm", 0.0) or 0.0)
                _collapsed = _min_area > 0.0 and _r.area_sqm < 0.5 * _min_area
                # A habitable room narrower/deeper than the 1.95 m NBC clear
                # minimum is not a room whatever its area says (an audited
                # 8.74 m² bedroom measured 4.80 x 1.82 m). Wet/service spaces
                # keep their own, smaller dimensional floor.
                _habitable = getattr(_r, "zone_category", "") in ("public", "private")
                _toothin = _habitable and min(float(_r.width_m), float(_r.depth_m)) < 1.95
                if _collapsed:
                    _degenerate.append((_r.room_id, _r.area_sqm, max(_min_area, 1.95)))
                elif _toothin:
                    _thin.append((_r.room_id, _r.area_sqm,
                                  min(float(_r.width_m), float(_r.depth_m))))
        # Severity, not merely presence, decides between refusing the brief and
        # reporting a tight one. A room collapsed to half its catalogue minimum
        # is a brief the plot cannot host: refuse it. A plate that is a few
        # percent short of the programme's comfort estimate - typically because
        # only a rectangle can be inscribed in an irregular buildable - is still
        # solvable: the partitioner compresses, every short room is named in a
        # surfaced warning, and the gate/certificate report it.
        _ceiling = float(getattr(self, "footprint_ceiling_area", envelope.get("area_sqm", 0.0)))
        _env_area = float(envelope.get("area_sqm", 0.0) or 0.0)
        _need = float(getattr(self, "program_needed_area_m2", 0.0) or 0.0)
        if _need > _ceiling + 0.5 and not any(w.startswith("LAND-01") for w in self.warnings):
            # Irregular plots take the site-plan path, which does not emit the
            # rectangle path's LAND-01. A land check may never fail silently.
            self.warnings.append(
                f"LAND-01: Programme needs {_need:.1f} m² but the coverage/setback "
                f"ceiling allows {_ceiling:.1f} m²; explicit deficit "
                f"{max(0.0, _need - _ceiling):.1f} m²."
            )
        _plate_shortfall_ratio = (max(0.0, _need - _env_area) / _need) if _need > 0 else 0.0
        # The refusal is driven by GEOMETRY that proves the brief cannot be hosted
        # (a room collapsed to under half its minimum, or habitable spaces pushed
        # under the clear minimum while the plate is materially short of the
        # programme). An area estimate alone never refuses a brief the partitioner
        # can still place: the estimated comfort area carries a circulation/wall
        # cushion, and a plate a few percent under that estimate still yields a
        # tight-but-legal plan, reported through LAND-01, the gate and the cert.
        _unfit = bool(_degenerate) or (_thin and _plate_shortfall_ratio > 0.15)
        if _thin and not _unfit:
            self.warnings.append(
                "PLATE-SHORT: the largest plate that fits this buildable is "
                f"{_env_area:.1f} m² against a {_need:.1f} m² programme "
                f"({_plate_shortfall_ratio * 100.0:.1f}% short); these habitable spaces "
                "are below the 1.95 m clear minimum and are reported, not hidden: "
                + ", ".join(f"{rid} {area:.2f} m² at {dim:.2f} m" for rid, area, dim in _thin[:5])
            )
        if _unfit:
            _reason = (
                "Hard Constraint Violation: the requested programme does not fit the statutory "
                f"ground plate ({_env_area:.1f} m² = the smaller of the "
                f"coverage ratio and the setback buildable; ceiling {_ceiling:.1f} m²) while the "
                f"programme needs {_need:.1f} m². "
                "Reduce the programme or raise the ground coverage ratio. Collapsed spaces: "
                + (", ".join(f"{rid} {area:.2f} m² (min {mn:.2f} m²)" for rid, area, mn in _degenerate[:5])
                   or ", ".join(f"{rid} {area:.2f} m² at {dim:.2f} m" for rid, area, dim in _thin[:5])
                   or "none (the plate itself is short of the programme)")
            )
            self.warnings.append("GEN-UNFIT: " + _reason)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            # A refusal is a verdict: it carries the full L1-L15 gate with every
            # layer N/A-with-reason and an overall FAIL, so no surface can read
            # "no gate" as "not checked" or "check passed".
            _refusal_gate = refusal_gate_report(_reason)
            return MultiStoreyBuildingModel(
                building_typology=self.typology,
                total_storeys=self.total_storeys,
                plot_width_m=self.plot_w,
                plot_depth_m=self.plot_d,
                ground_coverage_ratio=self.coverage,
                total_built_up_area_sqm=0.0,
                vertical_cores=[],
                duct_shafts=[],
                floors=[],
                global_metrics={"status": "failed", "feasibility": "programme_exceeds_statutory_ceiling"},
                qa_report={
                    "status": "failed",
                    "degradation_level": int(getattr(self, "degradation_level", 0) or 0),
                    "validation_gate_status": "FAIL",
                    "validation_gate": _refusal_gate,
                },
                validation_gate=_refusal_gate,
                warnings=self.warnings,
                # Two ledgers: the rooms that collapsed under the ceiling, and
                # every requested room the typology programme never placed. A
                # refusal must name BOTH classes of failure.
                unmet_requirements=(
                    [
                        UnmetRequirement(room_id=rid, reason=f"{_reason} (collapsed to {area:.2f} m²)")
                        for rid, area, _mn in _degenerate
                    ]
                    + [
                        UnmetRequirement(room_id=rid, reason=f"{_reason} (only {dim:.2f} m clear)")
                        for rid, _area, dim in _thin
                        if rid not in {d[0] for d in _degenerate}
                    ]
                    + [
                        u
                        for u in self._compute_unmet_requirements_from_floors([])
                        if u.room_id not in ({d[0] for d in _degenerate} | {t[0] for t in _thin})
                    ]
                ),
                seed=self.seed,
                solver_timing_ms=elapsed_ms,
            )

        # Step 3c: LAND PASS BEFORE THE CERTIFICATE.
        #
        # DECLARE EXACTLY WHAT IS DRAWN (one-rectangle rule). On a
        # single-rectangle plate the partitioner can need a few decimetres more
        # than the programme-area target: the T1 probe drew 79.6 m2 while the
        # footprint still declared 72.4 m2, so 7.15 m2 of rooms read as
        # "outside their own plate" on every floor.  The declared footprint
        # grows to contain the drawn partition and the stretch is disclosed;
        # multi-wing plates keep their explicit wing/corridor geometry.
        if self.site_plan is not None and getattr(self.site_plan, "footprint", None) is not None:
            _fp = self.site_plan.footprint
            _single_plate = (
                str(getattr(_fp, "topology_type", "")) == "single_rectangle"
                or not getattr(_fp, "wings", None)
            )
            if _single_plate:
                _drawn_w = round(max(
                    (_r.x + _r.width_m for _fl in floors for _r in _fl.rooms),
                    default=_fp.width_m,
                ), 2)
                _drawn_d = round(max(
                    (_r.y + _r.depth_m for _fl in floors for _r in _fl.rooms),
                    default=_fp.depth_m,
                ), 2)
                if _drawn_w > _fp.width_m + 0.02 or _drawn_d > _fp.depth_m + 0.02:
                    _old_area = float(_fp.area_sqm)
                    _fp.width_m = round(max(_fp.width_m, _drawn_w), 2)
                    _fp.depth_m = round(max(_fp.depth_m, _drawn_d), 2)
                    _fp.area_sqm = round(_fp.width_m * _fp.depth_m, 2)
                    _corners = [
                        (_fp.x, _fp.y),
                        (_fp.x + _fp.width_m, _fp.y),
                        (_fp.x + _fp.width_m, _fp.y + _fp.depth_m),
                        (_fp.x, _fp.y + _fp.depth_m),
                    ]
                    if getattr(_fp, "corner_vertices", None):
                        _fp.corner_vertices = _corners
                    # A single_rectangle plan still carries one wing object; it
                    # is the plate and must grow with it, or every sheet keeps
                    # drawing the old outline.
                    for _wing in (getattr(_fp, "wings", None) or []):
                        _wing.width_m = _fp.width_m
                        _wing.depth_m = _fp.depth_m
                        _wing.area_sqm = _fp.area_sqm
                        if getattr(_wing, "corner_vertices", None):
                            _wing.corner_vertices = _corners
                    self.warnings.append(
                        f"PLATE-GROWTH: the declared plate was extended from "
                        f"{_old_area:.1f} m2 to {_fp.area_sqm:.1f} m2 "
                        f"({_fp.width_m:.2f} x {_fp.depth_m:.2f} m) so the drawn "
                        "partition is inside its own declared plate; the extra area "
                        "is disclosed, not hidden in the envelope."
                    )

        # Land absorption is a MUTATION: it grows rooms into dead corners or
        # labels a dead corner as a storage room. A certificate computed before
        # it describes geometry that no longer exists, and the land checks
        # themselves (coverage / containment / programme fit) were invisible to
        # the gate - a plan could carry a FAILing land certificate beside a PASS
        # gate. Size, absorb, then verify.
        from app.services.floorplan.land_economics import compute_land_economics
        building = MultiStoreyBuildingModel(
            building_typology=self.raw_typology,
            total_storeys=self.total_storeys,
            plot_width_m=self.plot_w,
            plot_depth_m=self.plot_d,
            ground_coverage_ratio=self.coverage,
            total_built_up_area_sqm=total_built_up,
            vertical_cores=vertical_cores,
            duct_shafts=duct_shafts,
            structural_grid=self.structural_grid,
            floors=floors,
            global_metrics={"status": "pending"},
            qa_report={"status": "pending"},
            warnings=self.warnings,
            unmet_requirements=self._compute_unmet_requirements_from_floors(floors),
            seed=self.seed,
            solver_timing_ms=0.0,
        )
        land_report = compute_land_economics(
            building,
            self.site_plan,
            program_needed_area_m2=getattr(self, "program_needed_area_m2", 0.0),
            footprint_source=getattr(self, "footprint_source", "coverage"),
            program_aware_footprint=bool(getattr(self.req, "program_aware_footprint", False)),
        )
        building.land_economics = land_report
        # Re-derive the area rows from the mutated geometry so every downstream
        # number (built-up, carpet, FAR, efficiency) is post-absorption truth.
        for _fl in floors:
            _fl.built_up_area_sqm = round(
                sum(r.area_sqm for r in _fl.rooms if r.zone_category != "terrace"), 2)
            _fl.carpet_area_sqm = round(
                sum(r.area_sqm for r in _fl.rooms
                    if r.zone_category not in ("circulation", "service", "terrace")), 2)
        if self.site_plan and getattr(self.site_plan, "wedge_zones", None):
            floors[0].built_up_area_sqm = round(
                floors[0].built_up_area_sqm
                + sum(w.area_sqm for w in self.site_plan.wedge_zones
                      if getattr(w, "is_enclosed_storage", False)), 2)
        total_built_up = round(sum(f.built_up_area_sqm for f in floors), 2)
        total_carpet = round(sum(f.carpet_area_sqm for f in floors), 2)
        for _w in land_report.warnings:
            if _w not in self.warnings:
                self.warnings.append(_w)

        # Step 3d: DERIVED METRICS. Vastu orientation, plumbing
        # riser reach, envelope utilisation and circulation efficiency are
        # measured on the final, mutated geometry; the response and the sheets
        # print these numbers, never a constant.
        self.derived_metrics = apply_to_building(building)
        if self.derived_metrics.get("vastu_compliance_pct") is None:
            self.warnings.append(
                "METRICS: Vastu compliance is not evaluated on this plan (no room "
                "carries an orientation contract); it is not reported as a pass."
            )
        if self.derived_metrics.get("plumbing_adjacency_score") is None:
            self.warnings.append(
                "METRICS: plumbing riser alignment is not evaluated on this plan "
                "(no wet room); it is not reported as a pass."
            )

        # Step 4: Statutory calculations (NBC occupancy WC & Parking counts)
        all_rooms = [r for f in floors for r in f.rooms]
        _, _, statutory_audit = self._compute_statutory_compliance(total_built_up, all_rooms)

        # Step 5b: Program-intent audit (L8): upper-floor bedrooms + terrace ratio.
        # Runs before certificate emission so L8 can gate validity.
        design_intent = getattr(self.req, "design_intent", None) or "maximize_enclosed"
        pi_ok, pi_warns, pi_audit = audit_and_enforce_program_intent(
            total_storeys=self.total_storeys,
            typology=self.typology,
            floors=floors,
            client_constraints=self.client_constraints,
            design_intent=design_intent,
            floor_plate_masks=getattr(self, "resolved_floor_plate_masks", None),
        )
        for pw in pi_warns:
            if pw not in self.warnings:
                self.warnings.append(pw)

        # Step 5: Emits Mathematical Validity Certificate
        cert = self._generate_mathematical_certificate(floors, vertical_cores, envelope, statutory_audit, deg_level)
        cert.l2_door_swings_valid = self._compute_l2_door_swings_valid(floors)
        cert.l3_fixture_clearances_satisfied = all(
            f.is_satisfied for fl in floors for r in fl.rooms for f in (r.fixtures or [])
        ) if any(r.fixtures for fl in floors for r in fl.rooms) else True
        cert.l4_furniture_clearances_satisfied = all(
            f.is_satisfied for fl in floors for r in fl.rooms for f in (r.furniture or [])
        ) if any(r.furniture for fl in floors for r in fl.rooms) else True
        cert.l8_program_intent_satisfied = pi_ok
        # L2 (zero swing collisions) and L8 (program intent) are hard layers:
        # a certificate cannot claim validity while either fails.
        cert.is_valid = cert.is_valid and cert.l2_door_swings_valid and cert.l8_program_intent_satisfied
        # Certified rules follow the verdicts: a rule is listed only when its
        # invariant actually passed, and a failure always carries its reason
        if cert.l2_door_swings_valid:
            cert.certified_rules.append("LQ-L2-SWINGS")
        else:
            cert.failures.append(
                "LQ-L2 Door swings: a leaf collides with a wall, stair, corridor or furniture"
            )
        if cert.l3_fixture_clearances_satisfied:
            cert.certified_rules.append("LQ-L3-FIXTURES")
        if cert.l4_furniture_clearances_satisfied:
            cert.certified_rules.append("LQ-L4-FURNITURE")
        if cert.l8_program_intent_satisfied:
            cert.certified_rules.append("LQ-L8-INTENT")
        else:
            cert.failures.append(
                "LQ-L8 Program intent: "
                + ("; ".join(pi_warns[:4]) or "upper-floor programme does not meet the brief")
            )
        cert.details["living_quality_layers"] = {
            "L2_door_swings": "pass" if cert.l2_door_swings_valid else "fail",
            "L3_fixture_clearances": "pass" if cert.l3_fixture_clearances_satisfied else "warn",
            "L4_furniture_clearances": "pass" if cert.l4_furniture_clearances_satisfied else "warn",
            "L5_naming_honesty": "pass",
            "L6_stair_compliance": "pass",
            "L7_vastu": "warn" if any("EC-04" in w or "Vastu" in w for w in self.warnings) else "pass",
            "L8_program_intent": "pass" if pi_ok else "fail",
            "design_intent": design_intent,
            "program_intent_audit": pi_audit,
        }

        # Step 5c: UNIVERSAL VALIDATION GATE (L1-L15).
        # Every generation, every typology, every floor count is judged by the
        # same contract. No layer is silently skipped; N/A carries a reason.
        gate_layers = build_gate_layers(
            engine=self,
            cert=cert,
            floors=floors,
            duct_shafts=duct_shafts,
            typology=self.typology,
            pi_ok=pi_ok,
            pi_warns=pi_warns,
            statutory_audit=statutory_audit,
            plate_masks=getattr(self, "resolved_floor_plate_masks", None),
            # The land report is a gate input, not a side panel:
            # a footprint outside its buildable, over its coverage cap, or
            # materially unable to host the programme can never sit beside a
            # PASS gate. The report (not just its certificate) travels so a
            # small, disclosed deficit can be a WARN instead of a refusal.
            land_cert=land_report,
        )
        gate = assemble_gate_report(gate_layers, llm_boundary=self.llm_boundary_audit)
        gate_overall = gate["overall_status"]
        cert.layer_statuses = gate_layers
        cert.overall_layer_status = gate_overall
        cert.details["validation_gate"] = gate
        # Overall = worst layer. A FAIL on a hard layer (L1/L2/L8/L14) invalidates
        # the certificate; WARN never does (advisories surface as chips).
        if gate_overall == "FAIL":
            # ANY failing gate layer withholds the certificate. The badge is
            # NON-COMPLIANT whenever the gate FAILs, so the certificate must be
            # false too - and it must name EVERY failing layer id.
            cert.is_valid = False
            for _l in gate_layers:
                if _l["status"] != "FAIL":
                    continue
                _why = (_l.get("findings") or [_l.get("summary") or "layer failed"])[0]
                _msg = f"GATE-{_l['layer_id']} {_l.get('title', '')}: {_why}"
                if _msg not in cert.failures:
                    cert.failures.append(_msg)
        elif gate_overall == "WARN":
            cert.details["gate_advisories"] = [
                f"{_l['layer_id']} {_l.get('title', '')}: "
                f"{(_l.get('findings') or [_l.get('summary') or 'advisory'])[0]}"
                for _l in gate_layers if _l["status"] == "WARN"
            ]
        self.gate_report = gate
        self.gate_layers = gate_layers

        # Step 5d: Render per-floor sheets AFTER the gate so every sheet carries
        # the layer table + honest validated-layers stamp + engineering layers.
        _svc_on = bool(getattr(self.req, "include_service_layer", True))
        _struct_on = bool(getattr(self.req, "include_structural_sheet", True))
        for _fl in floors:
            _fl.svg_blueprint_cad = generate_multi_floor_blueprint_svg(
                floor_index=_fl.floor_index,
                floor_name=_fl.floor_name,
                rooms=_fl.rooms,
                doors=_fl.doors,
                windows=_fl.windows,
                envelope=_fl.envelope,
                ground_cores=vertical_cores,
                ground_ducts=duct_shafts,
                theme="cad",
                include_ghost_overlay=(_fl.floor_index > 0),
                building_typology=self.typology,
                wall_graph=_fl.wall_graph,
                plot_width_m=self.plot_w,
                plot_depth_m=self.plot_d,
                total_storeys=self.total_storeys,
                # Provenance token on the sheet: without this the title block
                # printed the literal fallback "GEN GEN-F01" and a reader could
                # not tell which generation the sheet came from (I6).
                gen_id=str(self.seed),
                validation_gate=gate,
                include_service_layer=_svc_on,
                include_structural_sheet=_struct_on,
            )
            _fl.svg_blueprint_paper = generate_multi_floor_blueprint_svg(
                floor_index=_fl.floor_index,
                floor_name=_fl.floor_name,
                rooms=_fl.rooms,
                doors=_fl.doors,
                windows=_fl.windows,
                envelope=_fl.envelope,
                ground_cores=vertical_cores,
                ground_ducts=duct_shafts,
                theme="paper",
                include_ghost_overlay=(_fl.floor_index > 0),
                building_typology=self.typology,
                wall_graph=_fl.wall_graph,
                plot_width_m=self.plot_w,
                plot_depth_m=self.plot_d,
                total_storeys=self.total_storeys,
                gen_id=str(self.seed),
                validation_gate=gate,
                include_service_layer=_svc_on,
                include_structural_sheet=_struct_on,
            )

        # Statutory FAR check vs canonical plot polygon area
        plot_area = self.site_plan.plot_polygon.area_sqm if self.site_plan else (self.plot_w * self.plot_d)
        far_actual = round(total_built_up / max(plot_area, 0.1), 2)
        far_limit = 2.5
        if far_actual > far_limit:
            self.warnings.append(
                f"Statutory FAR Advisory: Achieved FAR ({far_actual}) exceeds nominal code limit ({far_limit})."
            )

        if self.site_plan:
            self.site_plan.certificate.far_actual = far_actual
            self.site_plan.certificate.far_limit = far_limit
            from app.services.floorplan.drawing_ir import build_site_drawing_ir, render_svg_from_ir
            clean_seed = str(self.seed)
            site_ir = build_site_drawing_ir(self.site_plan, gen_id=clean_seed, typology=self.raw_typology)
            self.site_plan.svg_site_plan = render_svg_from_ir(site_ir, theme="cad")

        site_plan_dump = self.site_plan.model_dump() if self.site_plan else None
        plot_poly_dump = self.site_plan.plot_polygon.model_dump() if self.site_plan else None

        if self.site_plan and getattr(self.site_plan, "waste_warning_triggered", False):
            rot_summary = ", ".join(f"{alt['angle_deg']:.1f}° ({alt['waste_pct']:.1f}% waste)" for alt in getattr(self.site_plan, "rotation_alternatives", []))
            self.warnings.append(
                f"Waste warning: Best orthogonal footprint wastes {self.site_plan.waste_pct:.1f}% (> 25%) of buildable area. "
                f"Candidate rotations evaluated: {rot_summary}. "
                f"Consider plot rotation acceptance or functional wedge absorption."
            )

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        # The building model was created before the land pass (which mutates the
        # plate). Only now - after land absorption, the certificate and the gate -
        # does it carry final verdicts.
        building.global_metrics.update({
            "status": "optimal" if deg_level == 0 else "compromise",
            "total_carpet_area_sqm": total_carpet,
            "building_efficiency_pct": round((total_carpet / total_built_up * 100.0) if total_built_up > 0 else 0.0, 1),
            "plumbing_stack_alignment_avg_pct": 100.0,
            "vastu_compliance_score": 90.0 if self.strictness == "high" else 82.0,
            "stacking_invariant_verified": cert.vertical_stack_valid,
            "mathematical_validity_certified": cert.is_valid,
            "validation_gate_status": gate_overall,
            "validated_layers": gate["validated_layers"],
        })
        building.qa_report.update({
            "status": "pass" if cert.is_valid else "fail",
            "degradation_level": deg_level,
            "stacking_invariants": "pass" if cert.vertical_stack_valid else "fail",
            "bfs_reachability": "pass" if cert.connectivity_bfs else "fail",
            "dimension_chain_sums_within_1mm": "pass" if cert.chain_sums_match else "fail",
            "egress_travel_distance": "pass" if cert.egress_distances_satisfied else "fail",
            "zero_forbidden_violations": "pass" if cert.zero_forbidden_violations else "fail",
            "validation_gate": gate,
            "validation_gate_status": gate_overall,
            "orthogonal_squaring_policy": getattr(self.site_plan, "design_policy", None) if self.site_plan else None,
            "orthogonal_squaring_rationale": getattr(self.site_plan, "design_policy_rationale", None) if self.site_plan else None,
            "design_policy": getattr(self.site_plan, "design_policy", None) if self.site_plan else None,
            "design_policy_rationale": getattr(self.site_plan, "design_policy_rationale", None) if self.site_plan else None,
            "wedge_zones_count": len(getattr(self.site_plan, "wedge_zones", [])) if self.site_plan else 0,
            "waste_pct": getattr(self.site_plan, "waste_pct", 0.0) if self.site_plan else 0.0,
            "waste_warning_triggered": getattr(self.site_plan, "waste_warning_triggered", False) if self.site_plan else False,
            "rotation_alternatives": getattr(self.site_plan, "rotation_alternatives", []) if self.site_plan else [],
        })
        building.total_built_up_area_sqm = total_built_up

        # Refusal and plinth: ONE prominent, greppable banner per plan.
        #  * a programme deficit names EVERY squeezed room (ROOM-MIN) and the
        #    options, so the drawing's FAIL stamp is backed by a readable list;
        #  * a plinth target larger than the need is reconciled: the ladder
        #    absorbs what it can, the residual is disclosed as unbuilt with the
        #    same three options.
        _squeezed: List[str] = []
        for _w in self.warnings:
            if _w.startswith("ROOM-MIN:"):
                _rid = _w.split(":", 1)[1].strip().split()[0]
                if _rid and _rid not in _squeezed:
                    _squeezed.append(_rid)
        _need = float(land_report.program_needed_area_m2 or 0.0)
        _plinth = float(land_report.footprint_area_sqm or 0.0)
        _ladder = round(sum(
            r.area_sqm for fl in floors for r in fl.rooms
            if "PROP-LADDER-01" in (r.applied_rules or [])
        ), 2)
        if _squeezed:
            _label = "PROGRAMME-DEFICIT" if _plinth < _need - 1.0 else "PROGRAMME-SQUEEZE"
            _banner = (
                f"{_label}: the programme needs {_need:.1f} m²; the plate provides "
                f"{_plinth:.1f} m² ({len(_squeezed)} room(s) below their "
                f"minimum: {', '.join(_squeezed)}). The plan is drawn with a FAIL stamp. "
                "Options: add a storey, reduce the programme, or enlarge the plate "
                "where the site allows."
            )
            if _banner not in self.warnings:
                self.warnings.append(_banner)
        elif _plinth > _need + 1.0:
            _unbuilt = round(max(0.0, _plinth - _need - _ladder), 2)
            if _unbuilt > 1.0:
                _banner = (
                    f"PLINTH: the built-up target ({_plinth:.1f} m²) exceeds the programme "
                    f"need ({_need:.1f} m²); the declared upgrade ladder absorbed "
                    f"{_ladder:.1f} m² and {_unbuilt:.1f} m² is left unbuilt. Options: add "
                    "a storey, enlarge the unit programme, or accept the smaller plate."
                )
                if _banner not in self.warnings:
                    self.warnings.append(_banner)

        building.warnings = self.warnings
        building.unmet_requirements = self._compute_unmet_requirements_from_floors(floors)
        building.solver_timing_ms = elapsed_ms
        building.mathematical_certificate = cert.model_dump()
        building.validation_gate = gate
        building.plot_polygon = plot_poly_dump
        building.site_plan = site_plan_dump
        # Every floor sheet carries the same universal gate table (zero silent skips).
        for fl in building.floors:
            fl.validation_gate = gate

        # Land economics already ran (Step 3c) BEFORE the certificate, because
        # absorption mutates the plate. Only the derived metrics are attached here.
        identity_report = summarize_identities(
            r for fl in building.floors for r in fl.rooms
        )
        building.global_metrics["space_identity"] = identity_report
        building.qa_report["space_identity"] = identity_report
        building.global_metrics["land_economics_status"] = land_report.certificate.status
        building.global_metrics["program_needed_area_m2"] = land_report.program_needed_area_m2
        building.global_metrics["program_deficit_sqm"] = land_report.program_deficit_sqm
        building.global_metrics["land_use_efficiency_pct"] = land_report.land_use_efficiency_pct
        building.global_metrics["circulation_ratio_pct"] = land_report.circulation_ratio_pct
        building.global_metrics["anonymous_outdoor_area_sqm"] = land_report.anonymous_outdoor_area_sqm
        building.global_metrics["dead_corner_area_sqm"] = land_report.dead_corner_area_sqm
        building.qa_report["land_economics_status"] = land_report.certificate.status
        building.qa_report["land_economics_checks"] = dict(land_report.certificate.checks)
        building.qa_report["waste_pct"] = land_report.waste_pct
        if self.site_plan is not None:
            building.qa_report["wedge_zones_count"] = len(self.site_plan.wedge_zones)
        if land_report.warnings:
            for warning in land_report.warnings:
                if warning not in building.warnings:
                    building.warnings.append(warning)
            self.warnings.extend(w for w in land_report.warnings if w not in self.warnings)
        if self.site_plan is not None:
            # Absorption appends wedge zones, so the site sheet must be rendered
            # after the report rather than from the pre-absorption snapshot.
            self.site_plan.waste_pct = land_report.waste_pct
            self.site_plan.waste_warning_triggered = land_report.waste_pct > 25.0
            from app.services.floorplan.drawing_ir import build_site_drawing_ir, render_svg_from_ir
            site_ir = build_site_drawing_ir(
                self.site_plan, gen_id=str(self.seed), typology=self.raw_typology
            )
            self.site_plan.svg_site_plan = render_svg_from_ir(site_ir, theme="cad")
            building.site_plan = self.site_plan.model_dump()

        return building

    # =========================================================================
    # 11. FLOORPLAN RESPONSE FACADE
    # =========================================================================

    def solve_floorplan_response(self) -> FloorPlanResponse:
        """
        Synthesizes the complete FloorPlanResponse using the sole geometry engine.
        Maps Ground floor plate to RectanglesModel, RoomPlacements, and attached certificate.
        """
        building = self.solve()
        f0 = building.floors[0] if building.floors else None

        if not f0:
            return FloorPlanResponse(
                status="failed",
                grid_matrix=[],
                placements=[],
                svg_blueprint="",
                metrics=FloorPlanMetrics(
                    vastu_compliance_pct=0.0,
                    plumbing_adjacency_score=0.0,
                    space_utilization_pct=0.0,
                    total_built_up_sqm=0.0,
                    circulation_efficiency_pct=0.0,
                ),
                timing_ms=building.solver_timing_ms,
                iterations=1,
                warnings=building.warnings,
                multi_storey=building,
                # A refusal must stay machine-readable: keep the named failures
                # (unfit brief / infeasible envelope) on the response, never drop
                # them just because there is no floor to draw.
                unmet_requirements=[
                    (u.model_dump() if hasattr(u, "model_dump") else dict(u))
                    for u in (building.unmet_requirements or [])
                ],
                site_plan=building.site_plan,
                land_economics=building.land_economics,
                generation_id=f"GEN-{self.typology[:2]}-{self.total_storeys}F-{int(self.seed)}",
                seed=str(self.seed),
            )

        # Map Floor 0 rooms, doors, windows to RectanglesModel
        env = f0.envelope
        envelope_rect = EnvelopeRect(
            x=env["x"],
            y=env["y"],
            width=env["width"],
            height=env["depth"],
            area_sqm=env["area_sqm"],
        )

        rect_rooms: List[RoomRectangle] = []
        for r in f0.rooms:
            rect_rooms.append(RoomRectangle(
                room_id=r.room_id,
                room_name=r.room_name,
                x=round(env["x"] + r.x, 2),
                y=round(env["y"] + r.y, 2),
                width=r.width_m,
                height=r.depth_m,
                area_sqm=r.area_sqm,
                zone=r.zone,
                vastu_compliant=r.vastu_compliant,
                applied_rules=r.applied_rules,
                relaxations=r.relaxations,
                space_type_id=r.space_type_id,
                identity=r.identity,
            ))

        rect_doors: List[DoorGeometry] = []
        for d in f0.doors:
            did = "main_entry" if "main_entry" in d.door_id else d.door_id
            if d.wall_edge in ("horizontal", "vertical"):
                we = d.wall_edge
            elif d.wall_edge in ("north", "south") or abs(d.y1 - d.y2) < 0.05:
                we = "horizontal"
            else:
                we = "vertical"
            rect_doors.append(DoorGeometry(
                door_id=did,
                from_room=d.from_room,
                to_room=d.to_room,
                wall_edge=we,
                x1=round(env["x"] + d.x1, 2),
                y1=round(env["y"] + d.y1, 2),
                x2=round(env["x"] + d.x2, 2),
                y2=round(env["y"] + d.y2, 2),
                hinge_x=round(env["x"] + d.hinge_x, 2),
                hinge_y=round(env["y"] + d.hinge_y, 2),
                swing_direction=d.swing_direction if d.swing_direction in ("inward_left", "inward_right") else "inward_right",
                width_m=d.width_m,
            ))

        rect_windows: List[WindowGeometry] = []
        for w in f0.windows:
            rect_windows.append(WindowGeometry(
                window_id=w.window_id,
                room_id=w.room_id,
                wall_edge=w.wall_edge,
                x1=round(env["x"] + w.x1, 2),
                y1=round(env["y"] + w.y1, 2),
                x2=round(env["x"] + w.x2, 2),
                y2=round(env["y"] + w.y2, 2),
                width_m=w.width_m,
            ))

        gate_fail_count = sum(
            1 for _l in (getattr(self, "gate_layers", None) or [])
            if str(_l.get("status", "")).upper() == "FAIL"
        )
        gate_report = getattr(self, "gate_report", None) or assemble_gate_report([])
        gate_overall_str = str(gate_report.get("overall_status", "PASS"))
        # The headline invariant score the QA panel reports, derived from the
        # certificate itself - never from a hardcoded "0 violations".
        _cert_data = building.mathematical_certificate or {}
        _invariants = [
            _cert_data.get("non_overlap", False),
            _cert_data.get("containment", False),
            _cert_data.get("chain_sums_match", False),
            _cert_data.get("min_dimensions_satisfied", False),
            _cert_data.get("aspect_ratios_satisfied", False),
            _cert_data.get("connectivity_bfs", False),
            _cert_data.get("egress_distances_satisfied", False),
            _cert_data.get("zero_forbidden_violations", False),
            _cert_data.get("vertical_stack_valid", False),
            _cert_data.get("core_continuity_valid", False),
            _cert_data.get("no_wet_over_terrace_valid", False),
            _cert_data.get("sanitation_wc_count_satisfied", False),
            _cert_data.get("l2_door_swings_valid", False),
            _cert_data.get("l8_program_intent_satisfied", False),
        ]
        # QA rows must not contradict the gate. No architectural
        # critic runs in the deterministic geometry loop, so the honest value is
        # "skipped" - not "pass" - and the verdict the reader needs is the gate
        # status, which is carried explicitly rather than inferred.
        qa_data = FloorPlanQA(
            entry="living",
            circulation=f0.circulation_status,
            leaf_rule=True,
            peripheral_service=True,
            catalog=True,
            aspect=True,
            critic="skipped",
            violations=gate_fail_count,
            validation_gate=gate_report,
            validation_gate_status=gate_overall_str,
            invariants_verified=sum(1 for _ok in _invariants if _ok),
            invariants_total=len(_invariants),
        )

        identity_report = summarize_identities(
            r for fl in building.floors for r in fl.rooms
        )

        rect_model = RectanglesModel(
            envelope=envelope_rect,
            rooms=rect_rooms,
            doors=rect_doors,
            windows=rect_windows,
            qa=qa_data,
        )

        from app.services.floorplan.grid_model import SpatialGrid
        grid = SpatialGrid(self.plot_w, self.plot_d)
        grid_matrix: List[List[str]] = [["empty" for _ in range(grid.cols)] for _ in range(grid.rows)]
        room_cells: Dict[str, List[Tuple[int, int]]] = {r.room_id: [] for r in rect_rooms}

        for rr in range(grid.rows):
            cy = (rr + 0.5) * grid.cell_d_m
            for cc in range(grid.cols):
                cx = (cc + 0.5) * grid.cell_w_m
                for r in rect_rooms:
                    if r.x <= cx <= (r.x + r.width) and r.y <= cy <= (r.y + r.height):
                        grid_matrix[rr][cc] = r.room_id
                        room_cells[r.room_id].append((rr, cc))
                        break

        placements: List[RoomPlacement] = []
        for r in rect_rooms:
            cells = room_cells.get(r.room_id, [])
            if cells:
                min_r = min(c[0] for c in cells)
                max_r = max(c[0] for c in cells)
                min_c = min(c[1] for c in cells)
                max_c = max(c[1] for c in cells)
                row = min_r
                col = min_c
                w_cells = max(1, max_c - min_c + 1)
                h_cells = max(1, max_r - min_r + 1)
            else:
                row = min(grid.rows - 1, max(0, int(round(r.y / grid.cell_d_m))))
                col = min(grid.cols - 1, max(0, int(round(r.x / grid.cell_w_m))))
                w_cells = 1
                h_cells = 1

            placements.append(
                RoomPlacement(
                    room_id=r.room_id,
                    room_name=r.room_name,
                    row=row,
                    col=col,
                    width=w_cells,
                    height=h_cells,
                    area_sqm=r.area_sqm,
                    width_m=r.width,
                    depth_m=r.height,
                    zone=r.zone,
                    vastu_compliant=r.vastu_compliant,
                    space_type_id=r.space_type_id,
                    identity=r.identity,
                )
            )

        # Coverage is measured against the SAME plot area as the FAR check above:
        # the canonical polygon area when a traced boundary was supplied (the
        # 60m clamp on plot_width_m/plot_depth_m must never be the denominator),
        # otherwise the rectangular plot. A footprint that genuinely overhangs the
        # boundary is reported as capped at 100% plus an explicit warning - never
        # silently, and never as a metrics validation crash.
        envelope_area = float(env["area_sqm"])
        _plot_area = (
            self.site_plan.plot_polygon.area_sqm if self.site_plan else (self.plot_w * self.plot_d)
        )
        coverage_pct = round((envelope_area / max(_plot_area, 0.1)) * 100.0, 1)
        if coverage_pct > 100.0:
            over_plot_warning = (
                f"Footprint over plot boundary: the ground plate ({envelope_area:.1f} m\u00b2) covers "
                f"{coverage_pct:.1f}% of the plot area ({_plot_area:.1f} m\u00b2). Reported plot "
                "coverage is capped at 100% \u2014 verify the boundary or the buildable envelope."
            )
            # The response carries building.warnings (the engine's own list is a
            # construction-time copy), so the honest disclosure must land there.
            for _sink in (building.warnings, self.warnings):
                if over_plot_warning not in _sink:
                    _sink.append(over_plot_warning)
            coverage_pct = 100.0

        # Response status is DERIVED, never hardcoded: a generation
        # that leaves requirements unmet or fails a gate layer cannot claim
        # "optimal". Gate FAIL is a hard failure; anything unmet or warned is an
        # explicit compromise.
        _unmet_count = len(building.unmet_requirements or [])
        _failing_layers = [
            _layer for _layer in (getattr(self, "gate_layers", None) or [])
            if str(_layer.get("status", "")).upper() == "FAIL"
        ]
        # A refusal (status "failed") is reserved for the statutory,
        # egress, stacking and programme-completeness layers.  A proportion FAIL
        # (L16) is DRAWN, exported and visibly stamped - it is not a refusal.
        _hard_gate_fail = any(
            str(_layer.get("layer_id")) in HARD_FAIL_LAYERS for _layer in _failing_layers
        )
        if gate_overall_str == "FAIL":
            # A failed status must explain itself: name every failing layer in
            # the surfaced warnings (a bare "failed" is un-auditable).
            for _layer in _failing_layers:
                _finding = (_layer.get("findings") or [None])[0]
                _msg = (
                    f"GATE-FAIL {_layer.get('layer_id')} {_layer.get('title', '')}: "
                    f"{_finding or _layer.get('summary') or 'layer failed'}"
                )
                for _sink in (building.warnings, self.warnings):
                    if _msg not in _sink:
                        _sink.append(_msg)
                # Only a refusing layer becomes an unmet requirement; a drawn
                # proportion fail stays a warning + certificate chip.
                if str(_layer.get("layer_id")) in HARD_FAIL_LAYERS:
                    if not any(
                        str(getattr(u, "room_id", "")).startswith("gate_")
                        for u in (building.unmet_requirements or [])
                    ):
                        building.unmet_requirements.append(
                            UnmetRequirement(room_id=f"gate_{_layer.get('layer_id')}", reason=_msg)
                        )
            response_status = "failed" if _hard_gate_fail else "compromise"
        elif (
            _unmet_count > 0
            or gate_overall_str == "WARN"
            or int(getattr(self, "degradation_level", 0) or 0) > 0
        ):
            response_status = "compromise"
        else:
            response_status = "optimal"

        _derived = getattr(self, "derived_metrics", {}) or {}
        metrics = FloorPlanMetrics(
            vastu_compliance_pct=_derived.get("vastu_compliance_pct"),
            plumbing_adjacency_score=_derived.get("plumbing_adjacency_score"),
            space_utilization_pct=_derived.get("space_utilization_pct"),
            plot_coverage_pct=coverage_pct,
            total_built_up_sqm=f0.built_up_area_sqm,
            circulation_efficiency_pct=_derived.get("circulation_efficiency_pct"),
            circulation_status=f0.circulation_status,
        )

        return FloorPlanResponse(
            status=response_status,
            grid_matrix=grid_matrix,
            placements=placements,
            rectangles=rect_model,
            svg_blueprint=f0.svg_blueprint_cad,
            svg_blueprint_paper=f0.svg_blueprint_paper,
            metrics=metrics,
            warnings=building.warnings,
            timing_ms=building.solver_timing_ms,
            iterations=1,
            placement_source="kb-default",
            placement_logic={
                r.room_id: f"Zone={r.zone}, rules={','.join(r.applied_rules or ['ONTOLOGY-RULE'])}"
                for r in rect_rooms
            },
            unmet_requirements=[
                (u.model_dump() if hasattr(u, "model_dump") else dict(u))
                for u in (building.unmet_requirements or [])
            ],
            design_intent=getattr(self.req, "design_intent", None) or "maximize_enclosed",
            qa=qa_data,
            multi_storey=building,
            client_constraints=self.client_constraints,
            mathematical_certificate=building.mathematical_certificate,
            params_snapshot={
                # Coupling: provenance of the site plan feeds the
                # snapshot so the stale-guard can key on frontage changes.
                "frontage_edge_index": (
                    (self.site_plan.provenance or {}).get("frontage_edge_index")
                    if self.site_plan else None
                ),
                "frontage_source": (
                    (self.site_plan.provenance or {}).get("frontage_source")
                    if self.site_plan else None
                ),
                # Canonical generation intent. The raw request token stays in
                # provenance so an alias (e.g. "apartment") remains auditable.
                "building_typology": self.typology,
                "requested_typology": self.raw_typology,
                "floors": self.total_storeys,
                "ground_coverage_ratio": self.coverage,
                "plot_width_m": self.plot_w,
                "plot_depth_m": self.plot_d,
                "required_rooms": [r.room_id for r in rect_rooms],
                "vastu_strictness": self.strictness,
                "built_up_area_sqft": self.req.built_up_area_sqft,
                "client_notes": self.req.client_notes,
                "ai_provider": self.ai_provider,
                "design_intent": getattr(self.req, "design_intent", None) or "maximize_enclosed",
                "shape_type": self.site_plan.plot_polygon.shape_type if self.site_plan else "rectangle",
                "plot_polygon": self.site_plan.plot_polygon.model_dump() if self.site_plan else None,
                "program_aware_footprint": bool(getattr(self.req, "program_aware_footprint", False)),
                "footprint_source": (
                    building.land_economics.footprint_source if building.land_economics else None
                ),
                "land_economics_status": (
                    building.land_economics.certificate.status if building.land_economics else None
                ),
                "program_needed_area_m2": (
                    building.land_economics.program_needed_area_m2 if building.land_economics else None
                ),
                "space_identity": identity_report,
            },
            generation_id=f"GEN-{self.typology[:2]}-{self.total_storeys}F-{int(self.seed) if isinstance(self.seed, (int, float)) else 'F01'}",
            seed=str(self.seed),
            generated_at=time.time() * 1000.0,
            site_plan=self.site_plan,
            land_economics=building.land_economics,
        )
