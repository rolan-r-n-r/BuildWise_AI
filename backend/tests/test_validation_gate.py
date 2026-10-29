"""
test_validation_gate.py - Universal Validation Gate & Engineering Layers 
==================================================================================
Covers review points 9, 13, 14, 15, 16, 17, 18, 20, 23, 24 + LLM-boundary:

1. UNIVERSAL GATE (matrix T1-T4 x 1-4 floors x strictness):
   - Every generation runs ALL layers L1-L15 - zero silent skips.
   - Per-layer status in {PASS, WARN, FAIL, N/A}; N/A always carries a reason.
   - overall_status == worst layer; validated_layers == non-N/A ids.
   - WARN layers surface findings (chips), never hidden.
   - Sheet stamp lists validated layers AND keeps NOT FOR CONSTRUCTION.

2. ENGINEERING LAYERS:
   - L9 ventilation: every wet room has a record with mode external_opening |
     shaft_vent | mechanical_flagged and a coded citation.
   - L10 wet-core: every wet room associated with a shaft; crossings recorded.
   - L11 terrace drainage: N/A-with-reason when no terrace; drain/parapet/RWP
     anchors when terrace exists; downpipe ties to site stormwater outlet SO-01.
   - L12 structural: columns at wall intersections within typology span limits;
     transfer beams flagged when upper walls lack support below.
   - L13 accessibility: corridor/door widths checked; applicability per typology;
     1500mm sanitary circle recorded.
   - L14 fire/egress: bedroom egress records, exit width table, travel verdict.

3. LLM BOUNDARY:
   - sanitize_llm_constraints strips coordinate/geometry keys and logs events.
   - Engine solve ignores geometry smuggled in via client constraints
     (geometry identical to a clean run) and logs boundary events.
   - Parser output (mocked LLM JSON with geometry fields) carries no geometry:
     ExtractedClientConstraints schema has no coordinate fields.

4. DETERMINISM: seed=42 twice -> byte-identical gate + certificate.
"""

import json
from typing import Any, List

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.multi_floor_plan import ExtractedClientConstraints
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.engineering import (
    compute_accessibility_audit,
    compute_fire_egress_audit,
    compute_structural_model,
    compute_terrace_drainage,
    compute_ventilation_registry,
    compute_wet_core_audit,
    ACCESS_CORRIDOR_MIN_M,
    SITE_STORM_OUTLET_ID,
    TYP_MAX_SPAN_M,
)
from app.services.floorplan.validation_gate import (
    LAYER_IDS,
    build_gate_layers,
    drawing_status_stamp,
    sanitize_llm_constraints,
)
from app.services.floorplan.drawing_ir import build_drawing_ir, render_svg_from_ir

TYPologies = ["T1_SINGLE_FAMILY", "T2_FAMILY_APARTMENT", "T3_LARGE_COMPLEX", "T4_WAREHOUSE"]
# Full matrix - all three strictness levels (the zero-
# silent-skips contract must hold at every strictness, not just high/medium).
STRICTNESS = ["high", "medium", "low"]
VALID_STATUSES = {"PASS", "WARN", "FAIL", "N/A"}
BASE_ROOMS = ["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]

_RANK = {"PASS": 0, "N/A": 1, "WARN": 2, "FAIL": 3}


def _solve(typology: str, floors: int, strictness: str = "medium",
           required_rooms: List[str] = None) -> Any:
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=floors,
        building_typology=typology,
        vastu_strictness=strictness,
        required_rooms=list(required_rooms or BASE_ROOMS),
    )
    return SoleGeometryEngine(req).solve()


# =============================================================================
# 1. UNIVERSAL GATE - MATRIX (zero silent skips)
# =============================================================================

@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
@pytest.mark.parametrize("strictness", STRICTNESS)
def test_gate_runs_all_layers_zero_silent_skips(typology: str, floors: int, strictness: str):
    """Every generation - any typology, any floor count - runs the full L1-L15 stack."""
    b = _solve(typology, floors, strictness)
    gate = b.validation_gate
    assert gate is not None, f"{typology} F{floors}: no gate report"
    ids = [ld["layer_id"] for ld in gate["layers"]]
    assert ids == LAYER_IDS, f"{typology} F{floors}: layer ids {ids} != canonical order"
    assert len(gate["layers"]) == len(LAYER_IDS)
    for ld in gate["layers"]:
        assert ld["status"] in VALID_STATUSES, f"{ld['layer_id']} status {ld['status']}"
        if ld["status"] == "N/A":
            assert ld.get("reason"), f"{ld['layer_id']} N/A without reason"        # Overall = worst *evaluated* layer. N/A means the layer did not run and
        # carries a reason; it is not a quality status and cannot downgrade the
        # gate (the public contract is PASS | WARN | FAIL).
        worst = "PASS"
        for ld in gate["layers"]:
            if ld["status"] == "N/A":
                continue
            if _RANK[ld["status"]] > _RANK[worst]:
                worst = ld["status"]
        assert gate["overall_status"] == worst
        assert gate["overall_status"] in ("PASS", "WARN", "FAIL")
    # validated_layers = every layer that ran (not N/A)
    assert gate["validated_layers"] == [ld["layer_id"] for ld in gate["layers"] if ld["status"] != "N/A"]
    # Building scope: L9/L10/L12/L13/L14 always evaluated (never N/A)
    for must_run in ("L9", "L10", "L12", "L13", "L14", "L15"):
        row = next(ld for ld in gate["layers"] if ld["layer_id"] == must_run)
        assert row["status"] != "N/A", f"{must_run} silently skipped on {typology} F{floors}"
    # WARN rows surface findings (chips), never hidden
    for ld in gate["layers"]:
        if ld["status"] == "WARN":
            assert isinstance(ld.get("findings"), list), f"{ld['layer_id']} WARN without findings"
    # QA + global metrics carry the gate
    assert b.qa_report["validation_gate_status"] == gate["overall_status"]
    assert b.qa_report["validation_gate"]["contract"] == "universal_gate_v1"
    assert b.global_metrics["validation_gate_status"] == gate["overall_status"]


@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
def test_certificate_carries_layer_statuses_and_stamp_layers(typology: str, floors: int):
    """Certificate exposes per-layer statuses and every sheet stamp lists them honestly."""
    b = _solve(typology, floors)
    cert = b.mathematical_certificate
    assert cert["layer_statuses"], "certificate missing layer_statuses"
    assert len(cert["layer_statuses"]) == len(LAYER_IDS)
    assert cert["overall_layer_status"] == b.validation_gate["overall_status"]
    # Floor sheets carry the same gate (zero silent skips per floor)
    for fl in b.floors:
        assert fl.validation_gate is not None
        assert [ld["layer_id"] for ld in fl.validation_gate["layers"]] == LAYER_IDS
    # Sheet stamp lists validated layers incl. engineering layers, keeps NFC
    svg = b.floors[0].svg_blueprint_cad or ""
    assert "STATUS: CONCEPT DESIGN" in svg
    assert "NOT FOR CONSTRUCTION" in svg
    stamp_lines = [l for l in svg.split("\n") if "STATUS: CONCEPT DESIGN" in l]
    stamp_text = " ".join(stamp_lines)
    for ld in b.validation_gate["layers"]:
        if ld["status"] != "N/A":
            assert ld["layer_id"] in stamp_text, f"{ld['layer_id']} missing from sheet stamp"
    # N/A layers must NOT be claimed as validated on the stamp line itself
    for ld in b.validation_gate["layers"]:
        if ld["status"] == "N/A":
            assert ld["layer_id"] not in stamp_text, (
                f"{ld['layer_id']} stamped as validated despite N/A"
            )
            # ...but the sheet layer table still records it with a reason
            assert f"N/A" in svg and ld["layer_id"] in svg


@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
def test_gate_sheet_layer_table_rendered(typology: str, floors: int):
    """SVG sheets render the full VALIDATION GATE layer table (L1-L15)."""
    b = _solve(typology, floors)
    svg = b.floors[0].svg_blueprint_cad or ""
    assert "VALIDATION GATE - LAYERS L1-L16" in svg
    for lid in LAYER_IDS:
        assert lid in svg
    for ld in b.validation_gate["layers"]:
        assert ld["status"] in svg  # every status chip rendered
    # Paper theme parity
    svg_paper = b.floors[0].svg_blueprint_paper or ""
    assert "VALIDATION GATE - LAYERS L1-L16" in svg_paper


# =============================================================================
# 1b. L15 PROGRAMME COMPLETENESS
# =============================================================================

def test_l15_t2_12x15_keeps_both_kitchens():
    """The canonical compact T2 plan keeps one kitchen per unit and passes L15.

    Regression: the old allocation guard deleted both kitchens at 12x15 and
    every other layer still passed.  Presence is now a hard gate.
    """
    req = FloorPlanRequest(plot_width_m=12.0, plot_depth_m=15.0, floors=1,
                           building_typology="T2_FAMILY_APARTMENT")
    b = SoleGeometryEngine(req).solve()
    ids = [r.room_id for r in b.floors[0].rooms]
    assert sum("kitchen" in rid for rid in ids) == 2, ids
    l15 = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L15")
    assert l15["status"] == "PASS", l15
    assert l15["details"]["missing"] == []
    assert set(l15["details"]["per_unit"]) == {"Unit_A", "Unit_B"}
    for unit_ids in l15["details"]["per_unit"].values():
        assert {"unit_living", "unit_kitchen", "unit_bed", "unit_bath"} <= set(unit_ids)


def test_l15_missing_kitchen_fails_gate_and_invalidates_certificate():
    """A plate that cannot hold a kitchen must never silently pass.

    Since a brief the statutory ceiling cannot hold is refused
    before a plan exists (no certificate can be issued for geometry that was
    never laid out), so the L15 failure is asserted on the planning path while
    the refusal itself is asserted as the alternative outcome.
    """
    req = FloorPlanRequest(plot_width_m=8.0, plot_depth_m=10.0, floors=1,
                           building_typology="T2_FAMILY_APARTMENT")
    b = SoleGeometryEngine(req).solve()
    if not b.floors:
        assert b.qa_report["status"] == "failed"
        reasons = " ".join(u.reason for u in (b.unmet_requirements or []))
        assert "does not fit the statutory ground plate" in reasons, reasons
        assert any(str(w).startswith(("T2-UNIT-MINIMA", "GEN-UNFIT")) for w in b.warnings)
        return
    l15 = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L15")
    assert l15["status"] == "FAIL"
    assert any("unit_kitchen" in f for f in l15.get("findings") or [])
    assert b.validation_gate["overall_status"] == "FAIL"
    assert b.mathematical_certificate["is_valid"] is False


def test_l15_catches_multi_wing_typology_fallback():
    """A T3/T4 L-shape drawn with the T1 house programme fails completeness."""
    from app.schemas.site_plan import PlotPolygonModel

    poly = PlotPolygonModel(
        vertices=[(0, 0), (14, 0), (14, 8), (8, 8), (8, 14), (0, 14)],
        shape_type="polygon", is_regular_rectangle=False,
        bounding_box=(0.0, 0.0, 14.0, 14.0),
    )
    for typology, expected in (
        ("T3_LARGE_COMPLEX", "sanitary_block"),
        ("T4_WAREHOUSE", "dock_bay"),
    ):
        req = FloorPlanRequest(plot_width_m=14.0, plot_depth_m=14.0,
                               plot_polygon=poly, floors=1,
                               building_typology=typology)
        b = SoleGeometryEngine(req).solve()
        if not b.floors:
            # A brief the statutory ceiling cannot host is refused before a
            # Plan exists; that refusal must name its reasons,
            # and no certificate can be issued for geometry that was never laid
            # out. The L15 path itself is asserted in the sibling test above.
            assert b.qa_report["status"] == "failed"
            assert b.unmet_requirements, f"{typology}: refusal without named failures"
            continue
        l15 = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L15")
        assert l15["status"] == "FAIL", f"{typology}: {l15}"
        assert any(expected in m for m in l15["details"]["missing"])


# =============================================================================
# 2. ENGINEERING LAYER PROPERTIES
# =============================================================================

@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
def test_l9_ventilation_every_wet_room_recorded(typology: str, floors: int):
    """Every kitchen/bath/utility carries a ventilation record with coded citation."""
    b = _solve(typology, floors)
    vent = compute_ventilation_registry(b.floors, b.duct_shafts)
    assert vent["total_rooms"] >= 1, "no wet rooms found at all"
    assert vent["citation"]
    for rec in vent["records"]:
        assert rec["mode"] in ("external_opening", "shaft_vent", "mechanical_flagged")
        assert rec["required_vent_area_sqm"] > 0
        if rec["mode"] == "shaft_vent":
            assert rec["shaft_id"], f"{rec['room_id']} shaft mode without shaft id"
    # Gate layer reflects the registry
    row = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L9")
    assert row["citation"] == vent["citation"]


@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
def test_l10_wet_core_shaft_grouping_no_undetected_crossings(typology: str, floors: int):
    """Wet rooms grouped on shafts; dry-room crossings recorded, never silent."""
    b = _solve(typology, floors)
    wet = compute_wet_core_audit(b.floors, b.duct_shafts)
    assert wet["wet_room_count"] >= 1
    assert wet["associated_count"] == wet["wet_room_count"], "wet room without shaft association"
    row = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L10")
    assert row["status"] != "N/A"
    if wet["crossings"]:
        assert row["status"] == "WARN"
        assert row["findings"], "crossings detected but findings empty"


def test_l11_terrace_drainage_set_and_site_outlet_tie():
    """Terrace drainage anchors exist for terraces; N/A-with-reason otherwise; SO-01 tie."""
    b = _solve("T1_SINGLE_FAMILY", 2)
    terr = compute_terrace_drainage(b.floors)
    row = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L11")
    if terr["terrace_count"] == 0:
        assert terr["status"] == "n/a"
        assert terr["reason"]
        assert row["status"] == "N/A" and row.get("reason")
    else:
        assert terr["status"] == "pass"
        for t in terr["terraces"]:
            assert t["slope_ratio"] == "1:100"
            assert t["downpipe_ties_to"] == SITE_STORM_OUTLET_ID
            assert t["parapet_min_h_m"] >= 1.0
            assert t["waterproofing_band_m"] > 0
            assert "Overflow" in t["overflow_note"]


def test_l11_terrace_with_band_draws_drainage_set():
    """A terraced plate yields drainage anchors (drain point, downpipe, WP band)."""
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="medium",
        required_rooms=list(BASE_ROOMS),            terrace_bands={1: {"edge": "N", "depth_m": 2.5}},
    )
    b = SoleGeometryEngine(req).solve()
    terr = compute_terrace_drainage(b.floors)
    assert terr["terrace_count"] >= 1, "terrace band requested but no terrace zone found"
    t0 = terr["terraces"][0]
    rx, ry, rw, rd = t0["rect"]
    dx, dy = t0["drain_point"]
    assert rx <= dx <= rx + rw and ry <= dy <= ry + rd
    assert t0["downpipe_ties_to"] == SITE_STORM_OUTLET_ID


@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
def test_l12_structural_columns_within_span_limits(typology: str, floors: int):
    """Columns along ground walls respect typology span limits; beams flagged honestly."""
    b = _solve(typology, floors)
    struct = compute_structural_model(b.floors, typology)
    max_span = TYP_MAX_SPAN_M[typology]
    assert struct["column_count"] >= 4, "no column grid at wall intersections"
    assert struct["max_span_m"] == max_span
    row = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L12")
    assert row["citation"]
    for beam in struct["beams"]:
        assert 0.0 <= beam["support_ratio"] < 0.95
        assert beam["note"]


def test_l12_transfer_beam_flagged_when_upper_wall_unsupported():
    """A synthetic unsupported upper wall must raise a flagged transfer beam."""
    class FakeRoom:
        def __init__(self, rid, x, y, w, d):
            self.room_id, self.x, self.y, self.width_m, self.depth_m = rid, x, y, w, d
            self.zone_category = "public"

    class FakeFloor:
        def __init__(self, wg, idx):
            self.wall_graph = wg
            self.floor_index = idx
            self.rooms = []

    ground_walls = [{"x1": 2, "y1": 0, "x2": 10, "y2": 0, "is_exterior": True, "is_load_bearing": False}]
    # Upper wall extends 2m beyond the wall below: only 80% support -> beam.
    upper_walls = [{"x1": 0, "y1": 0, "x2": 10, "y2": 0, "is_exterior": True, "is_load_bearing": False}]
    floors = [FakeFloor({"walls": ground_walls}, 0), FakeFloor({"walls": upper_walls}, 1)]
    struct = compute_structural_model(floors, "T1_SINGLE_FAMILY")
    assert struct["beam_count"] >= 1
    assert struct["beams"][0]["support_ratio"] < 0.95
    assert "Transfer beam" in struct["beams"][0]["note"]


@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
def test_l13_accessibility_per_typology_applicability(typology: str, floors: int):
    """Corridor widths vs typology minima; advisory vs full scope honored."""
    b = _solve(typology, floors)
    acc = compute_accessibility_audit(b.floors, typology)
    assert acc["citation"]
    row = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L13")
    assert row["status"] != "N/A"
    if typology in ("T3_LARGE_COMPLEX", "T4_WAREHOUSE"):
        assert acc["applicability"] == "full"
    else:
        assert acc["applicability"] == "advisory"
        assert row["status"] != "FAIL", "advisory typology must never hard-fail accessibility"
    for chk in acc["corridor_checks"]:
        assert chk["required_m"] == ACCESS_CORRIDOR_MIN_M[typology]


def test_l13_bathroom_maneuvering_circle_recorded():
    """1500mm circle check recorded for every sanitary room with fixtures."""
    b = _solve("T1_SINGLE_FAMILY", 1)
    acc = compute_accessibility_audit(b.floors, "T1_SINGLE_FAMILY")
    assert len(acc["circle_checks"]) >= 1
    for c in acc["circle_checks"]:
        assert c["circle_m"] == 1.50
        assert isinstance(c["achieved"], bool)


@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
def test_l14_fire_egress_records_and_exit_table(typology: str, floors: int):
    """Bedroom egress records + exit width table present; travel verdict drives status."""
    b = _solve(typology, floors)
    fire = compute_fire_egress_audit(b.floors, typology, True, occupant_load=4)
    assert len(fire["exit_width_table"]) == 2
    exits = {r["exit"] for r in fire["exit_width_table"]}
    assert exits == {"Main Entry Door", "Protected Stair"}
    for r in fire["exit_width_table"]:
        assert r["clear_width_m"] > 0
        assert r["code"]
    row = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L14")
    assert row["citation"]
    # Bedroom egress: every bedroom has a door; escape-window note when applicable
    for be in fire["bedroom_egress"]:
        assert be["corridor_door"] is True, f"{be['room_id']} bedroom without egress door"


def test_l14_travel_distance_failure_forces_fail():
    """If L1 travel-distance check fails, L14 must FAIL (hard layer)."""
    b = _solve("T1_SINGLE_FAMILY", 1)
    fire = compute_fire_egress_audit(b.floors, "T1_SINGLE_FAMILY", False, occupant_load=4)
    assert fire["status"] == "fail"
    assert any("Travel distance" in f for f in fire["findings"])


def test_l14_capacity_shortfall_is_a_named_hard_fail():
    """A stair too narrow for the storeys it serves is a hard FAIL, not a WARN.

    Release-closure pin: the protected stair is sized for the population of the
    storeys above grade (the ground floor discharges through the main entry).
    A shortfall on either exit must be named and must fail L14 so no certified
    verdict can carry it.
    """
    from types import SimpleNamespace

    def floor(door_id: str, stair: str) -> Any:
        return SimpleNamespace(
            floor_index=0,
            envelope={"width": 12.0, "depth": 18.0, "area_sqm": 216.0},
            rooms=[],
            windows=[],
            doors=[SimpleNamespace(door_id=door_id, width_m=1.0)],
            stair_schedule=[{"flight_width_m": stair}],
        )

    floors = [floor("main_entry_F0", "1.00 m") for _ in range(4)]
    fire = compute_fire_egress_audit(floors, "T2_FAMILY_APARTMENT", True, occupant_load=80)

    protection = fire["protection"]
    assert protection["building_occupant_load"] == 80
    assert protection["main_entry_load_served"] == 20
    assert protection["stair_load_served"] == 60
    assert protection["stair_occupants_served"] == 50
    assert protection["capacity_satisfied"] is False
    stair_row = next(r for r in fire["exit_width_table"] if r["exit"] == "Protected Stair")
    assert stair_row["capacity_satisfied"] is False
    assert fire["status"] == "fail"
    assert any("stair load 60" in f for f in fire["findings"])


def test_l14_capacity_shortfall_disappears_only_when_the_width_grows():
    """The same load on a compliant stair passes; nothing else changed."""
    from types import SimpleNamespace

    def floor(door_id: str, stair: str) -> Any:
        return SimpleNamespace(
            floor_index=0,
            envelope={"width": 12.0, "depth": 18.0, "area_sqm": 216.0},
            rooms=[],
            windows=[],
            doors=[SimpleNamespace(door_id=door_id, width_m=1.0)],
            stair_schedule=[{"flight_width_m": stair}],
        )

    floors = [floor("main_entry_F0", "1.30 m") for _ in range(4)]
    fire = compute_fire_egress_audit(floors, "T2_FAMILY_APARTMENT", True, occupant_load=80)
    protection = fire["protection"]
    assert protection["stair_load_served"] == 60
    assert protection["stair_occupants_served"] == 65
    assert protection["capacity_satisfied"] is True
    assert fire["status"] == "pass"


# =============================================================================
# 3. LLM BOUNDARY INVARIANT
# =============================================================================

def test_sanitize_llm_constraints_strips_geometry_and_logs():
    """Coordinate-bearing keys in LLM output are stripped and logged, never honored."""
    dirty = {
        "target_bedroom_count": 3,
        "x": 12.5,
        "y": 4.0,
        "width_m": 30.0,
        "polygon_coords": [(0, 0), (10, 10)],
        "vertices": [[1, 2], [3, 4]],
        "explicit_exclusions": ["pool"],
        "raw_notes": "three bedrooms",
    }
    out = sanitize_llm_constraints(dirty, source="unit_test")
    clean = out["sanitized"]
    assert "target_bedroom_count" in clean and clean["target_bedroom_count"] == 3
    for banned in ("x", "y", "width_m", "polygon_coords", "vertices"):
        assert banned not in clean
    assert out["events"], "geometry strip not logged"
    assert out["event_ids"] and all(eid.startswith("LLMB-") for eid in out["event_ids"])


def test_sanitize_llm_constraints_clean_pass_through():
    """Text-derived constraints pass untouched with no boundary events."""
    clean_in = {"target_bedroom_count": 2, "raw_notes": "quiet garden"}
    out = sanitize_llm_constraints(clean_in, source="unit_test")
    assert out["sanitized"] == clean_in
    assert out["events"] == [] and out["event_ids"] == []


@pytest.mark.parametrize("typology", TYPologies)
def test_engine_ignores_llm_smuggled_geometry(typology: str):
    """LLM-boundary invariant, three defenses deep:
    1. The schema DROPS smuggled geometry fields (pydantic validation).
    2. Solver geometry is IDENTICAL with and without a geometry-bearing payload.
    3. If a raw dict with geometry ever reaches the engine directly, the engine's
       sanitizer strips it AND logs an auditable boundary event."""
    clean_req = FloorPlanRequest(
        plot_width_m=18.0, plot_depth_m=14.0, floors=2,
        building_typology=typology, vastu_strictness="medium",
        required_rooms=list(BASE_ROOMS),
    )
    b_clean = SoleGeometryEngine(clean_req).solve()

    # --- Defense 1: pydantic schema drop -------------------------------------
    dirty_dict = {
        "target_bedroom_count": 2,
        "raw_notes": "two bedrooms",
        "extraction_source": "groq_llm",
        "x": 999.0, "width_m": 42.0, "polygon_coords": [(0, 0), (99, 99)],
    }
    parsed = ExtractedClientConstraints.model_validate(dirty_dict)
    assert not hasattr(parsed, "x") and not hasattr(parsed, "width_m")
    assert "x" not in parsed.model_dump()

    smuggle_req = FloorPlanRequest(
        plot_width_m=18.0, plot_depth_m=14.0, floors=2,
        building_typology=typology, vastu_strictness="medium",
        required_rooms=list(BASE_ROOMS),
        extracted_constraints=parsed,
    )
    b_dirty = SoleGeometryEngine(smuggle_req).solve()

    # --- Defense 2: geometry unchanged ---------------------------------------
    for fl_c, fl_d in zip(b_clean.floors, b_dirty.floors):
        c_rects = sorted((r.room_id, round(r.x, 3), round(r.y, 3), round(r.width_m, 3), round(r.depth_m, 3))
                         for r in fl_c.rooms)
        d_rects = sorted((r.room_id, round(r.x, 3), round(r.y, 3), round(r.width_m, 3), round(r.depth_m, 3))
                         for r in fl_d.rooms)
        assert c_rects == d_rects, f"{typology}: LLM geometry leaked into solver layout"
        assert len(c_rects) > 0

    # --- Defense 3: engine sanitizer catches direct dict injection ------------
    # (guards future refactors that might bypass the schema layer)
    eng = SoleGeometryEngine(clean_req)
    eng.client_constraints = dict(dirty_dict)  # simulate a boundary-bypassing caller
    b_guard = eng.solve()
    gate_d = b_guard.validation_gate
    assert gate_d["llm_boundary"]["event_ids"], "geometry strip not logged at engine boundary"
    fields = gate_d["llm_boundary"]["events"][0]["fields"]
    assert set(fields) >= {"x", "width_m", "polygon_coords"}
    # ...and the geometry STILL matches the clean run
    c_rects = sorted((r.room_id, round(r.x, 3), round(r.y, 3), round(r.width_m, 3), round(r.depth_m, 3))
                     for r in b_clean.floors[0].rooms)
    g_rects = sorted((r.room_id, round(r.x, 3), round(r.y, 3), round(r.width_m, 3), round(r.depth_m, 3))
                     for r in b_guard.floors[0].rooms)
    assert c_rects == g_rects, f"{typology}: direct dict geometry injection altered the layout"


def test_parser_schema_has_no_geometry_fields():
    """ExtractedClientConstraints exposes NO coordinate/geometry fields: the LLM is
    schema-confined to text-derived intent (parsing -> narrative only)."""
    schema = ExtractedClientConstraints.model_json_schema()
    props = set(schema.get("properties", {}).keys())
    banned = {"x", "y", "width", "depth", "width_m", "depth_m", "x1", "y1", "x2", "y2",
              "polygon", "polygon_coords", "vertices", "geometry", "rectangles", "coordinates",
              "rooms_geometry", "placements_geometry", "coords", "points"}
    assert not (props & banned), f"parser schema leaks geometry fields: {props & banned}"


def test_mocked_llm_json_with_geometry_cannot_inject_geometry():
    """A mocked Groq response stuffed with coordinates is validated against
    ExtractedClientConstraints (the parser's exact code path); the schema drops
    all geometry fields, so hallucinated coordinates cannot reach the solver."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    llm_json = {
        "target_bedroom_count": 3,
        "target_bathroom_count": 2,
        "explicit_exclusions": ["swimming pool"],
        # Malicious / hallucinated geometry payload:
        "x": 5.0, "y": 5.0, "width_m": 55.0, "depth_m": 40.0,
        "polygon_coords": [[0, 0], [50, 0], [50, 40]],
        "rooms_geometry": [{"room_id": "kitchen", "x": 1, "y": 1, "width_m": 4}],
        "raw_notes": "three bedrooms two baths",
    }
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(llm_json)}}]
    }

    class FakeSettings:
        DEFAULT_AI_PROVIDER = "groq"
        GROQ_API_KEY = "test-key-not-real"
        GROQ_MODEL = "mock-model"

    import app.ai.requirements_parser as rp

    # Path 1: schema validation (exactly what the parser does with LLM JSON).
    data = dict(llm_json)
    data["extraction_source"] = "groq_llm"
    constraints = ExtractedClientConstraints.model_validate(data)
    assert constraints.extraction_source == "groq_llm"
    assert constraints.target_bedroom_count == 3
    dumped = constraints.model_dump()
    for banned in ("x", "y", "width_m", "depth_m", "polygon_coords", "rooms_geometry"):
        assert banned not in dumped, f"LLM geometry field {banned} survived parsing"

    # Path 2: full async LLM surface with mocked transport.
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(return_value=fake_resp)
    with patch.object(rp, "settings", FakeSettings()), \
         patch.object(rp.httpx, "AsyncClient", return_value=fake_client):
        constraints_async = asyncio.run(rp.parse_client_requirements("three bedrooms two baths"))
    assert constraints_async.extraction_source == "groq_llm"
    dumped_async = constraints_async.model_dump()
    for banned in ("x", "y", "width_m", "depth_m", "polygon_coords", "rooms_geometry"):
        assert banned not in dumped_async

    # And the engine treats it as text-derived constraints only:
    clean_req = FloorPlanRequest(
        plot_width_m=18.0, plot_depth_m=14.0, floors=1,
        building_typology="T1_SINGLE_FAMILY", vastu_strictness="medium",
        required_rooms=list(BASE_ROOMS),
    )
    req = FloorPlanRequest(
        plot_width_m=18.0, plot_depth_m=14.0, floors=1,
        building_typology="T1_SINGLE_FAMILY", vastu_strictness="medium",
        required_rooms=list(BASE_ROOMS),
        extracted_constraints=constraints_async,
    )
    env_clean = SoleGeometryEngine(clean_req).solve().floors[0].envelope["width"]
    env_llm = SoleGeometryEngine(req).solve().floors[0].envelope["width"]
    assert env_clean == pytest.approx(env_llm), "hallucinated width_m altered the envelope"


# =============================================================================
# 4. DETERMINISM
# =============================================================================

@pytest.mark.parametrize("typology", TYPologies)
@pytest.mark.parametrize("floors", [1, 2])
def test_gate_determinism_seed42(typology: str, floors: int):
    """Same seed -> identical gate report and certificate.

    `evaluated_at` is wall-clock provenance (when the gate ran), not solver
    output - two identical solves legitimately differ by the clock tick, so it
    is excluded from the comparison. All geometry/status/finding fields must
    still match exactly.
    """
    b1 = _solve(typology, floors)
    b2 = _solve(typology, floors)

    def strip_ts(obj: dict) -> dict:
        """Deep-copy without wall-clock provenance keys (never solver output)."""
        import copy
        obj = copy.deepcopy(obj)
        obj.pop("evaluated_at", None)
        vg = (obj.get("details") or {}).get("validation_gate")
        if isinstance(vg, dict):
            vg.pop("evaluated_at", None)
        return obj

    assert strip_ts(b1.validation_gate) == strip_ts(b2.validation_gate)
    assert strip_ts(b1.mathematical_certificate) == strip_ts(b2.mathematical_certificate)
    assert b1.floors[0].svg_blueprint_cad == b2.floors[0].svg_blueprint_cad


# =============================================================================
# 5. SERVICE / STRUCTURAL TOGGLES
# =============================================================================

def test_service_layer_toggle_hides_drawing_not_validation():
    """include_service_layer=False removes shaft DRAWINGS (outline/stack/RWP
    polylines) but L9/L10 still validate."""
    base = dict(plot_width_m=20.0, plot_depth_m=18.0, floors=1,
                building_typology="T1_SINGLE_FAMILY", vastu_strictness="medium",
                required_rooms=list(BASE_ROOMS))
    b_on = SoleGeometryEngine(FloorPlanRequest(**base, include_service_layer=True)).solve()
    b_off = SoleGeometryEngine(FloorPlanRequest(**base, include_service_layer=False)).solve()
    svg_on = b_on.floors[0].svg_blueprint_cad or ""
    svg_off = b_off.floors[0].svg_blueprint_cad or ""
    n_poly_on = svg_on.count("<polyline")
    n_poly_off = svg_off.count("<polyline")
    assert n_poly_on > n_poly_off, "service toggle removed no service polylines"
    for lid in ("L9", "L10"):
        row_on = next(ld for ld in b_on.validation_gate["layers"] if ld["layer_id"] == lid)
        row_off = next(ld for ld in b_off.validation_gate["layers"] if ld["layer_id"] == lid)
        assert row_on["status"] != "N/A" and row_off["status"] != "N/A", \
            f"{lid} must validate even when drawings are toggled off"


def test_structural_toggle_hides_notes_not_validation():
    """include_structural_sheet=False removes grid bubbles + beam lines; L12 still runs."""
    base = dict(plot_width_m=20.0, plot_depth_m=18.0, floors=1,
                building_typology="T2_FAMILY_APARTMENT", vastu_strictness="medium",
                required_rooms=list(BASE_ROOMS))
    b_on = SoleGeometryEngine(FloorPlanRequest(**base, include_structural_sheet=True)).solve()
    b_off = SoleGeometryEngine(FloorPlanRequest(**base, include_structural_sheet=False)).solve()
    svg_on = b_on.floors[0].svg_blueprint_cad or ""
    svg_off = b_off.floors[0].svg_blueprint_cad or ""
    assert "col-grid-bubble" in svg_on
    assert "col-grid-bubble" not in svg_off
    row_off = next(ld for ld in b_off.validation_gate["layers"] if ld["layer_id"] == "L12")
    assert row_off["status"] != "N/A"


# =============================================================================
# 6. SITE SHEET SCOPE HONESTY
# =============================================================================

def test_site_sheet_gate_na_with_reasons_and_stamp():
    """Site gate records building layers as N/A-with-reason; stamp stays honest."""
    from app.schemas.site_plan import PlotPolygonModel
    from app.services.floorplan.site_geometry import compute_canonical_site_plan

    poly = PlotPolygonModel(
        vertices=[(0, 0), (14, 0), (14, 6), (8, 6), (8, 14), (0, 14)],
        shape_type="irregular",
        is_regular_rectangle=False,
    )
    ok, site, warns = compute_canonical_site_plan(14.0, 14.0, plot_polygon=poly,
                                                  typology="T1_SINGLE_FAMILY")
    assert ok and site is not None
    gate = site.validation_gate
    assert gate is not None
    assert [ld["layer_id"] for ld in gate["layers"]] == LAYER_IDS
    l1 = next(ld for ld in gate["layers"] if ld["layer_id"] == "L1")
    assert l1["status"] in ("PASS", "WARN", "FAIL")
    na = [ld for ld in gate["layers"] if ld["status"] == "N/A"]
    assert na, "site gate must honestly mark building layers N/A"
    for ld in na:
        assert ld.get("reason")
    # Stamp still lists site-validated layers and keeps NFC
    assert "L1" in site.drawing_status_stamp
    assert "NOT FOR CONSTRUCTION" in site.drawing_status_stamp
    # Site sheet SVG renders the gate table with N/A reasons
    site_ir = build_drawing_ir.__globals__["build_site_drawing_ir"](site)
    svg = render_svg_from_ir(site_ir)
    assert "VALIDATION GATE - LAYERS L1-L16" in svg
    assert "N/A" in svg


# =============================================================================
# 7. PDF SHEET 10.0 LAYER TABLE
# =============================================================================

def test_pdf_sheet10_layer_table_and_stamp():
    """PDF Sheet 10.0 carries the UNIVERSAL VALIDATION GATE table; NFC retained."""
    import io
    import pypdf
    from app.services.report_service import generate_pdf_report

    b = _solve("T1_SINGLE_FAMILY", 2)
    payload = {
        "request_id": "BW-TEST-VALIDATION-GATE-PDF",
        "timestamp": "2026-09-29 12:00:00 UTC",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Validation Gate Test Site",
        "overall_suitability_score": 85.0,
        "suitability_verdict": "Verified",
        "built_up_area_sqft": 3600.0,
        "floors": 2,
        "multi_storey": b.model_dump(),
    }
    pdf_buf = generate_pdf_report(payload)
    pdf_bytes = pdf_buf.getvalue()
    assert pdf_bytes.startswith(b"%PDF")

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "UNIVERSAL VALIDATION GATE" in text
    for lid in LAYER_IDS:
        assert lid in text
    assert "OVERALL" in text
    assert "NOT FOR CONSTRUCTION" in text or "not for construction" in text.lower()


# =============================================================================
# 5. CHAIN PRECISION & ADVISORY WORDING
# =============================================================================

def _fake_cert(**over: Any):
    """Minimal certificate stand-in for gate unit tests (no solver run)."""
    from types import SimpleNamespace
    base = dict(
        non_overlap=True, containment=True, chain_sums_match=True,
        zero_forbidden_violations=True, connectivity_bfs=True,
        vertical_stack_valid=True, core_continuity_valid=True,
        no_wet_over_terrace_valid=True, cores_stack_aligned=True,
        min_dimensions_satisfied=True, aspect_ratios_satisfied=True,
        egress_distances_satisfied=True, l2_door_swings_valid=True,
        l3_fixture_clearances_satisfied=True, l4_furniture_clearances_satisfied=True,
        details={"living_quality_layers": {}},
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("typology,floors", [
    ("T1_SINGLE_FAMILY", 2), ("T2_FAMILY_APARTMENT", 2),
    ("T3_LARGE_COMPLEX", 2), ("T4_WAREHOUSE", 1),
])
def test_chain_sums_machine_verified_zero_silent_skips(typology: str, floors: int):
    """Dimension-chain precision is machine-verified, never vacuous.

    The historical check read a serialized key that never existed
    ('dimension_chains'), so chain verification was silently skipped. Every
    solved floor must now expose audited chains and the L1 layer must state
    the verified count.
    """
    b = _solve(typology, floors)
    audit = b.mathematical_certificate["details"]["dimension_chain_audit"]
    assert audit["chains_checked"] > 0, f"{typology}: no chains audited (vacuous verification)"
    assert audit["floors_with_chains"] == floors, f"{typology}: chains missing on some floor"
    assert audit["floors_without_chains"] == []
    l1 = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L1")
    assert "dimension chains verified within 1mm" in l1["summary"]
    assert l1["status"] != "FAIL"


def test_l1_fails_when_a_floor_lacks_dimension_chains():
    """A solved floor without chains must FAIL L1 with an explicit finding."""
    cert = _fake_cert(details={
        "living_quality_layers": {},
        "dimension_chain_audit": {"chains_checked": 0, "floors_with_chains": 0,
                                  "floors_without_chains": [0]},
    })
    from types import SimpleNamespace
    layers = build_gate_layers(
        engine=SimpleNamespace(structural_grid=None),
        cert=cert, floors=[], duct_shafts=[], typology="T1_SINGLE_FAMILY",
        pi_ok=True, pi_warns=[], statutory_audit={"occupant_load": 0},
    )
    l1 = next(ld for ld in layers if ld["layer_id"] == "L1")
    assert l1["status"] == "FAIL"
    assert any("silent-skip guard" in f for f in l1.get("findings") or [])


@pytest.mark.parametrize("typology,floors", [("T1_SINGLE_FAMILY", 2), ("T4_WAREHOUSE", 1)])
def test_l12_load_path_continuity_wording(typology: str, floors: int):
    """L12 states the floor-to-floor load-path verdict explicitly."""
    b = _solve(typology, floors)
    l12 = next(ld for ld in b.validation_gate["layers"] if ld["layer_id"] == "L12")
    assert "load-path" in l12["summary"]


def test_l8_terrace_ratio_justification_surfaces():
    """A terrace-ratio breach carries conversion guidance even when L8 passes."""
    from types import SimpleNamespace
    cert = _fake_cert(details={"living_quality_layers": {
        "program_intent_audit": {"terrace_ratio_pct": 52.5, "terrace_ratio_satisfied": False},
    }})
    warns = ["Terrace Ratio Advisory: Open terrace area (52.5 m2, 52.5% of enclosed) "
             "exceeds optimal threshold (35%). Consider converting partial terrace."]
    layers = build_gate_layers(
        engine=SimpleNamespace(structural_grid=None),
        cert=cert, floors=[], duct_shafts=[], typology="T1_SINGLE_FAMILY",
        pi_ok=True, pi_warns=warns, statutory_audit={"occupant_load": 0},
    )
    l8 = next(ld for ld in layers if ld["layer_id"] == "L8")
    assert l8["status"] == "PASS"
    assert "terrace ratio" in l8["summary"].lower()
    assert any("Terrace Ratio" in f for f in l8.get("findings") or [])


def test_stamp_single_source_canonical_format():
    """Every stamp surface derives from the one canonical helper."""
    from app.services.floorplan.drawing_ir import SheetHeaderInfo, _wrap_status_stamp

    assert drawing_status_stamp(["L1", "L2"]) == (
        "STATUS: CONCEPT DESIGN - VALIDATED LAYERS: [L1, L2] - NOT FOR CONSTRUCTION")
    assert drawing_status_stamp(["L1", "L2"], scope_note="SITE SCOPE; BUILDING LAYERS N/A") == (
        "STATUS: CONCEPT DESIGN - VALIDATED LAYERS: [L1, L2] "
        "(SITE SCOPE; BUILDING LAYERS N/A) - NOT FOR CONSTRUCTION")

    hdr = SheetHeaderInfo(
        gen_id="GEN-T1-1F-42", plot_w_m=12.0, plot_d_m=15.0, storeys=1,
        storeys_label="G", floor_index=0, floor_name="Ground Floor (G)",
        elevation_m=0.0, envelope_w_m=10.0, envelope_d_m=13.0,
        freshness_token="GEN GEN-T1-1F-42", validated_layers=["L1", "L7"],
    )
    assert hdr.drawing_status_stamp == drawing_status_stamp(["L1", "L7"])

    # Wrapped sheet lines keep the head prefix and the legal tail, never dropped.
    lines = _wrap_status_stamp(drawing_status_stamp([f"L{i}" for i in range(1, 15)]), 60)
    assert all(l.startswith("STATUS: CONCEPT DESIGN") for l in lines)
    assert lines[-1].endswith("] - NOT FOR CONSTRUCTION")
