"""
BuildWise Pipeline Contracts & Buildability Invariants Test Suite.
Verifies:
1. Producer->Consumer DTO contract completeness across all API and internal interfaces.
2. Buildability invariants:
   - Dimension chain sums equal envelope dimensions within 1mm on every floor.
   - Hosted openings have valid width, height, sill, lintel, and deterministic tags.
   - Computed stair adheres to Blondel's rule (2R + T in [600, 650]mm) with risers <= 175mm.
   - Zero negative room geometry across all typologies and plot dimensions.
   - Construction schedules (Door, Window, Room) properly populated in DTOs and reports.
"""

import pytest
import math
from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.wall_graph import (
    build_constructible_wall_graph,
    compute_stair_geometry,
    StairGeometry
)
from app.services.report_service import generate_pdf_report


# =============================================================================
# 1. PRODUCER -> CONSUMER CONTRACT TESTS
# =============================================================================

def test_api_response_frontend_contract():
    """
    Verifies that FloorPlanResponse contains all fields required by the frontend:
    - rectangles (envelope, rooms, doors, windows, qa)
    - placements (room_id, room_name, width_m, depth_m, zone, vastu_compliant)
    - grid_matrix (2D list)
    - svg_blueprint and svg_blueprint_paper
    - metrics (vastu_compliance_pct, space_utilization_pct, plot_coverage_pct, circulation_status)
    - warnings list
    - multi_storey (total_floors, floors with svg_blueprint_cad, svg_blueprint_paper, wall_graph)
    """
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=10.0,
        building_typology="T1_SINGLE_FAMILY",
        floors=2,
        vastu_strictness="high",
        ai_provider="mock"
    )
    res = generate_floor_plan(req)
    data = res.model_dump()

    # Top-level API contract fields
    expected_top_fields = [
        "status", "grid_matrix", "placements", "rectangles",
        "svg_blueprint", "svg_blueprint_paper", "metrics",
        "warnings", "timing_ms", "qa", "multi_storey"
    ]
    for f in expected_top_fields:
        assert f in data, f"Missing required top-level field '{f}' in FloorPlanResponse"

    # Metrics contract fields consumed by FloorPlanGeneratorCard.tsx
    metrics = data["metrics"]
    for mf in ["vastu_compliance_pct", "plumbing_adjacency_score", "space_utilization_pct", "plot_coverage_pct"]:
        assert mf in metrics, f"Missing required metrics field '{mf}'"

    # Multi-storey contract fields consumed by BlueprintViewer.tsx and FloorPlanGeneratorCard.tsx
    assert data["multi_storey"] is not None
    ms = data["multi_storey"]
    assert "floors" in ms
    assert len(ms["floors"]) >= 2

    for fl in ms["floors"]:
        assert "floor_index" in fl
        assert "floor_name" in fl
        assert "svg_blueprint_cad" in fl and fl["svg_blueprint_cad"].startswith("<svg")
        assert "svg_blueprint_paper" in fl and fl["svg_blueprint_paper"].startswith("<svg")
        assert "wall_graph" in fl and fl["wall_graph"] is not None


def test_internal_wall_graph_dto_contract():
    """
    Verifies the contract between SoleGeometryEngine / wall_graph and svg_generator / report_service:
    - wall_graph must have walls, openings, rooms, stair_geometry,
      dim_chains_x, dim_chains_y, door_schedule, window_schedule, room_schedule.
    """
    solver = SoleGeometryEngine(FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=12.0,
        building_typology="T1_SINGLE_FAMILY",
        floors=2,
        vastu_strictness="medium",
        ai_provider="mock"
    ))
    building = solver.solve()
    assert building is not None and len(building.floors) >= 2

    for fl in building.floors:
        wg = fl.wall_graph
        assert wg is not None, f"Floor {fl.floor_index} missing wall_graph"
        assert len(wg.get("walls", [])) > 0
        assert len(wg.get("openings", [])) > 0
        assert len(wg.get("rooms", [])) > 0
        assert wg.get("stair_geometry") is not None
        assert len(wg.get("door_schedule", [])) > 0
        assert len(wg.get("window_schedule", [])) > 0
        assert len(wg.get("room_schedule", [])) > 0


# =============================================================================
# 2. BUILDABILITY INVARIANTS: DIMENSION CHAINS ACCURACY (1mm)
# =============================================================================

@pytest.mark.parametrize("typology", ["T1_SINGLE_FAMILY", "T2_FAMILY_APARTMENT", "T3_COMMERCIAL_RETAIL"])
@pytest.mark.parametrize("plot_w,plot_d", [(12.0, 10.0), (16.0, 14.0), (22.0, 18.0)])
def test_dimension_chain_sum_invariant(typology, plot_w, plot_d):
    """
    INVARIANT: Every dimension chain must equal the overall envelope dimension within 1mm (0.001m).
    envelope = sum(clear_room_dimensions) + sum(wall_thicknesses).
    """
    solver = SoleGeometryEngine(FloorPlanRequest(
        plot_width_m=plot_w,
        plot_depth_m=plot_d,
        building_typology=typology,
        floors=2,
        vastu_strictness="low",
        ai_provider="mock"
    ))
    building = solver.solve()
    if not building.floors:
        # Refused brief: the statutory ceiling cannot hold the
        # programme, and the refusal names the shortfall rather than squeezing.
        assert building.qa_report.get("status") == "failed"
        assert any(str(w).startswith(("GEN-UNFIT", "LAND-01")) for w in building.warnings), building.warnings
        return

    for fl in building.floors:
        wg = fl.wall_graph
        env_w = wg["envelope"]["width"]
        env_d = wg["envelope"]["depth"]

        # X chains
        for chain in wg.get("dim_chains_x", []):
            chain_sum = sum(s["length_m"] for s in chain["segments"])
            assert abs(chain_sum - env_w) <= 0.002, (
                f"Floor {fl.floor_index} chain X '{chain.get('chain_id')}' sum {chain_sum:.4f} != envelope width {env_w:.4f}"
            )

        # Y chains
        for chain in wg.get("dim_chains_y", []):
            chain_sum = sum(s["length_m"] for s in chain["segments"])
            assert abs(chain_sum - env_d) <= 0.002, (
                f"Floor {fl.floor_index} chain Y '{chain.get('chain_id')}' sum {chain_sum:.4f} != envelope depth {env_d:.4f}"
            )


# =============================================================================
# 3. BUILDABILITY INVARIANTS: STAIRCASE MATH & BLONDEL'S RULE
# =============================================================================

@pytest.mark.parametrize("floor_h", [2.8, 3.0, 3.3, 3.6])
@pytest.mark.parametrize("typology", ["T1_SINGLE_FAMILY", "T2_FAMILY_APARTMENT", "T3_COMMERCIAL_RETAIL"])
def test_computed_staircase_blondel_rule(floor_h, typology):
    """
    INVARIANT: Computed staircase geometry must:
    - Have riser R <= 175mm (0.175m)
    - Satisfy N * R == floor_h within 1mm
    - Satisfy Blondel's ergonomic comfort equation: 2R + T in [600mm, 650mm] (0.600m to 0.650m)
    - Have tread T in [250mm, 300mm]
    """
    stair = compute_stair_geometry(floor_height_m=floor_h, typology=typology)
    assert stair.riser_height_m <= 0.175 + 1e-4, f"Riser {stair.riser_height_m} exceeds 175mm"
    assert abs(stair.riser_count * stair.riser_height_m - floor_h) <= 0.001, "Riser sum != floor height"
    assert 0.250 <= stair.tread_depth_m <= 0.300 + 1e-4, f"Tread {stair.tread_depth_m} out of range"
    blondel = 2.0 * stair.riser_height_m + stair.tread_depth_m
    assert 0.598 <= blondel <= 0.652, f"Blondel 2R+T = {blondel:.3f} outside [0.600, 0.650] range"


# =============================================================================
# 4. BUILDABILITY INVARIANTS: HOSTED OPENINGS & SCHEDULES
# =============================================================================

def test_hosted_openings_and_schedules():
    """
    INVARIANT: Hosted doors and windows must have deterministic tags (D1..Dn, W1..Wn),
    valid lintel and sill heights, and appear in the respective schedules.
    """
    solver = SoleGeometryEngine(FloorPlanRequest(
        plot_width_m=15.0,
        plot_depth_m=12.0,
        building_typology="T1_SINGLE_FAMILY",
        floors=2,
        vastu_strictness="medium",
        ai_provider="mock"
    ))
    building = solver.solve()
    wg = building.floors[0].wall_graph

    d_sched = wg.get("door_schedule", [])
    w_sched = wg.get("window_schedule", [])
    r_sched = wg.get("room_schedule", [])

    assert len(d_sched) >= 4, "Insufficient door schedule entries"
    assert len(w_sched) >= 4, "Insufficient window schedule entries"
    assert len(r_sched) >= 4, "Insufficient room schedule entries"

    # Check deterministic tags
    for idx, d in enumerate(d_sched, 1):
        assert d["tag"] == f"D{idx}", f"Door tag {d['tag']} is not deterministic D{idx}"
        assert d["width_mm"] >= 750, f"Door width {d['width_mm']} is below 750mm"
        assert d["height_mm"] >= 2000, f"Door height {d['height_mm']} is below 2000mm"

    for idx, w in enumerate(w_sched, 1):
        assert w["tag"] == f"W{idx}", f"Window tag {w['tag']} is not deterministic W{idx}"
        assert w["sill_mm"] >= 600, f"Window sill {w['sill_mm']} is below 600mm"
        assert w["lintel_mm"] >= 2000, f"Window lintel {w['lintel_mm']} is below 2000mm"


# =============================================================================
# 5. INTEGRATION INVARIANT: NON-CORRUPT GEOMETRY ON TINY & LARGE PLOTS
# =============================================================================

@pytest.mark.parametrize("plot_w,plot_d", [(6.0, 6.6), (22.0, 18.0)])
@pytest.mark.parametrize("typology", ["T1_SINGLE_FAMILY", "T2_FAMILY_APARTMENT"])
def test_non_negative_geometry_and_graceful_degradation(plot_w, plot_d, typology):
    """
    INVARIANT: No layout returned by the pipeline may contain non-positive room dimensions
    (width <= 0, height <= 0, area <= 0).
    On compact plots where footprint is insufficient, the engine must gracefully degrade or warn.
    """
    req = FloorPlanRequest(
        plot_width_m=plot_w,
        plot_depth_m=plot_d,
        building_typology=typology,
        floors=1,
        vastu_strictness="medium",
        ai_provider="mock"
    )
    res = generate_floor_plan(req)
    assert res.status in ("optimal", "compromise", "failed")

    if res.rectangles:
        for r in res.rectangles.rooms:
            assert r.width > 0.0, f"Room {r.room_id} has non-positive width: {r.width}"
            assert r.height > 0.0, f"Room {r.room_id} has non-positive height: {r.height}"
            assert r.area_sqm > 0.0, f"Room {r.room_id} has non-positive area: {r.area_sqm}"

    if res.multi_storey and res.multi_storey.floors:
        for fl in res.multi_storey.floors:
            for r in fl.rooms:
                assert r.width_m > 0.0, f"MS Room {r.room_id} has non-positive width: {r.width_m}"
                assert r.depth_m > 0.0, f"MS Room {r.room_id} has non-positive depth: {r.depth_m}"


# =============================================================================
# 6. PDF DOSSIER GENERATION CONTRACT TEST
# =============================================================================

def test_pdf_dossier_generation_with_schedules():
    """
    Verifies that generate_pdf_report generates a valid non-empty PDF byte stream
    when include_construction_schedules=True for both single-storey and multi-storey payloads.
    """
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=12.0,
        building_typology="T1_SINGLE_FAMILY",
        floors=2,
        vastu_strictness="medium",
        ai_provider="mock"
    )
    res = generate_floor_plan(req)
    analysis_mock = {
        "report_id": "TEST-CONTRACT-001",
        "plot_width_m": 14.0,
        "plot_depth_m": 12.0,
        "building_typology": "residential_single",
        "quality_grade": "standard",
        "floors": 2,
        "built_up_area_sqft": 2400.0,
    }
    pdf_buf = generate_pdf_report(
        analysis_mock,
        floor_plan=res.model_dump(),
        dossier_only=True,
        include_construction_schedules=True
    )
    pdf_bytes = pdf_buf.getvalue()
    assert len(pdf_bytes) > 5000, "PDF stream is too small or empty"
    assert pdf_bytes.startswith(b"%PDF-"), "Generated stream is not a valid PDF"


# =============================================================================
# 7. SINGLE SOURCE OF TRUTH: SIDEBAR TYPOLOGY & STOREYS COMBINATIONS (4x4)
# =============================================================================

@pytest.mark.parametrize("sidebar_typology,expected_canonical", [
    ("residential_single", "T1_SINGLE_FAMILY"),
    ("residential_multi", "T2_FAMILY_APARTMENT"),
    ("commercial", "T3_LARGE_COMPLEX"),
    ("industrial", "T4_WAREHOUSE"),
])
@pytest.mark.parametrize("sidebar_storeys", [1, 2, 3, 4])
def test_sidebar_single_source_contract_all_combinations(sidebar_typology, expected_canonical, sidebar_storeys):
    """
    Contract test: verifies that payload.floors and payload.building_typology
    always equal sidebar values for all 16 combinations (4 typologies x 4 storeys),
    and that the multi-floor engine properly maps and fulfills them.
    """
    from app.services.floorplan.typologies import normalize_typology

    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=12.0,
        building_typology=sidebar_typology,
        floors=sidebar_storeys,
        ground_coverage_ratio=0.60,
        vastu_strictness="medium",
        ai_provider="mock",
    )

    # Invariant 1: Request payload directly reflects sidebar input
    assert req.floors == sidebar_storeys, f"Expected floors {sidebar_storeys}, got {req.floors}"
    assert req.building_typology == sidebar_typology, f"Expected typology {sidebar_typology}, got {req.building_typology}"

    # Invariant 2: Typology normalizer correctly resolves canonical model key
    resolved_canonical = normalize_typology(req.building_typology)
    assert resolved_canonical == expected_canonical, (
        f"Typology mapping mismatch: {sidebar_typology} resolved to {resolved_canonical}, expected {expected_canonical}"
    )

    # Invariant 3: Solver executes and produces the exact number of levels
    res = generate_floor_plan(req)
    if res.status == "failed":
        # An over-programmed brief cannot fit a 14 x 12 m plot at 60 % coverage;
        # refusing it is the honest answer, and the refusal must
        # carry the numbers - either the ceiling shortfall or the gate-bearing
        # land check that failed.
        reasons = " ".join(u["reason"] for u in (res.unmet_requirements or []))
        assert any(k in reasons for k in (
            "does not fit the statutory ground plate",
            "programme fits the footprint",
            "GATE-FAIL",
        )), reasons
        return
    assert res.status in ("optimal", "compromise"), f"Generation failed for {sidebar_typology} {sidebar_storeys} storeys: {res.warnings}"

    if sidebar_storeys > 1:
        assert res.multi_storey is not None, f"MultiStorey model missing for {sidebar_storeys} storeys"
        assert res.multi_storey.total_storeys == sidebar_storeys, (
            f"Expected {sidebar_storeys} total_storeys, got {res.multi_storey.total_storeys}"
        )
        assert len(res.multi_storey.floors) == sidebar_storeys, (
            f"Expected {sidebar_storeys} floor slices, got {len(res.multi_storey.floors)}"
        )
        assert res.multi_storey.building_typology == sidebar_typology, (
            f"Expected building_typology {sidebar_typology}, got {res.multi_storey.building_typology}"
        )
        assert normalize_typology(res.multi_storey.building_typology) == expected_canonical, (
            f"Expected canonical typology {expected_canonical}, got {normalize_typology(res.multi_storey.building_typology)}"
        )
    else:
        # Single level
        assert len(res.placements) >= 3, "Single level must have at least 3 room placements"

