import pytest
from app.schemas.floorplan import FloorPlanRequest
from app.schemas.multi_floor_plan import (
    MultiStoreyBuildingModel,
    ExtractedClientConstraints,
)
from app.services.floorplan.engine import SoleGeometryEngine


# =====================================================================
# 1. EC-06 Stacking Invariant Tests
# =====================================================================

@pytest.mark.parametrize("floors_count", [2, 3, 4])
def test_stacking_invariant_vertical_core(floors_count):
    """
    EC-06: Verifies that staircase core and vertical duct shafts have identical
    X, Y coordinates and dimensions across all floors within 0.001m tolerance.
    """
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=16.0,
        floors=floors_count,
        building_typology="T1_SINGLE_FAMILY",
        ground_coverage_ratio=0.60,
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()

    assert building.total_storeys == floors_count
    assert len(building.floors) == floors_count
    assert building.global_metrics["stacking_invariant_verified"] is True
    assert building.qa_report["stacking_invariants"] == "pass"

    # Compare floor 0 vertical core coordinates with each upper floor
    f0 = building.floors[0]
    f0_cores = [r for r in f0.rooms if r.is_vertical_core]
    assert len(f0_cores) == 1
    core_0 = f0_cores[0]

    for z in range(1, floors_count):
        fz = building.floors[z]
        fz_cores = [r for r in fz.rooms if r.is_vertical_core]
        assert len(fz_cores) == 1
        core_z = fz_cores[0]

        # Invariant check: X, Y, width, depth must be identical down to 0.001m
        assert abs(core_z.x - core_0.x) < 0.001, f"Floor {z} core X drifted: {core_z.x} vs {core_0.x}"
        assert abs(core_z.y - core_0.y) < 0.001, f"Floor {z} core Y drifted: {core_z.y} vs {core_0.y}"
        assert abs(core_z.width_m - core_0.width_m) < 0.001
        assert abs(core_z.depth_m - core_0.depth_m) < 0.001


def test_stacking_invariant_shared_cores_and_ducts():
    """Verify shared vertical cores and duct shafts match between building and floors."""
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=18.0,
        floors=3,
    )
    building = SoleGeometryEngine(req).solve()
    assert len(building.vertical_cores) >= 1
    assert len(building.duct_shafts) >= 1

    stair_spec = building.vertical_cores[0]
    for floor in building.floors:
        stair_room = next(r for r in floor.rooms if r.is_vertical_core)
        assert abs(stair_room.x - stair_spec.x) < 0.001
        assert abs(stair_room.y - stair_spec.y) < 0.001


# =====================================================================
# 2. Graph Reachability Tests
# =====================================================================

@pytest.mark.parametrize("floors_count", [1, 2, 3, 4])
def test_graph_reachability_all_floors(floors_count):
    """
    Verifies that for every floor plate, 100% of rooms are reachable
    from the vertical core via doors and circulation lobby (BFS reachability).
    """
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        floors=floors_count,
    )
    building = SoleGeometryEngine(req).solve()

    for z, floor in enumerate(building.floors):
        assert floor.circulation_status == "connected", f"Floor {z} circulation is disconnected!"
        assert len(floor.doors) >= len(floor.rooms) - 1, f"Floor {z} has insufficient doors"

        # Verify door connectivity explicitly
        core_room = next(r for r in floor.rooms if r.is_vertical_core)
        door_from_core = any(d.from_room == core_room.room_id or d.to_room == core_room.room_id for d in floor.doors)
        assert door_from_core, f"Floor {z} staircase core has no door exit!"


# =====================================================================
# 3. Rule of Plumbing Wet Stacks
# =====================================================================

def test_plumbing_wet_stack_alignment():
    """
    Verifies that upper floor bathrooms are vertically aligned with
    continuous vertical MEP duct shafts or ground-level wet rooms.
    """
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        floors=2,
    )
    building = SoleGeometryEngine(req).solve()
    assert len(building.floors) == 2

    # Check plumbing alignment metric on upper floor
    f1 = building.floors[1]
    assert f1.plumbing_stack_alignment_pct >= 85.0
    assert building.global_metrics["plumbing_stack_alignment_avg_pct"] >= 85.0


# =====================================================================
# 4. Graceful Degradation Protocol Tests (Section 3.3)
# =====================================================================

def test_graceful_degradation_ec03_subminimum_plot():
    """
    EC-03: Sub-Minimum Plot (6.0m x 7.0m = 42m2).
    Requires solver to reject impossible program gracefully with clear NBC deficiency warning,
    without raising an unhandled exception or crashing.
    """
    req = FloorPlanRequest(
        plot_width_m=6.0,
        plot_depth_m=7.0,
        floors=2,
        ground_coverage_ratio=0.60,
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()

    assert building.qa_report["status"] == "failed"
    assert building.total_built_up_area_sqm == 0.0
    assert any("EC-03" in w for w in building.warnings)
    assert any("Insufficient plot footprint" in w for w in building.warnings)
    assert any("Area shortfall is" in w for w in building.warnings)


def test_graceful_degradation_ec01_narrow_deep_plot():
    """
    EC-01: Narrow Deep Plot (6.0m x 24.0m, aspect ratio 1:4).
    Verifies solver accommodates extreme aspect ratio and reports Level 1 degradation.
    """
    req = FloorPlanRequest(
        plot_width_m=6.0,
        plot_depth_m=24.0,
        floors=2,
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()

    # Proportion law: a 6 x 24 m plot cannot hold this programme inside
    # the ontology's hard bands, and the old suite called that a PASS because no
    # layer measured proportion.  The plan is still drawn and the degradation is
    # reported; the gate now says FAIL and names the squeezed rooms, which is
    # the honest result, not a fabrication. The previous PASS expectation would
    # have re-hidden the very defect this guard exists to surface.
    #
    # A 4.0 m buildable cannot carry bath 2.10 + spine 1.50 + a legal kitchen;
    # the partitioner used to draw a 0.40 m kitchen sliver.  That is now a NAMED
    # refusal (GEN-UNFIT with plate, programme and the collapsed room) - drawing
    # a 0.4 m kitchen was the dishonest answer.
    if not building.floors:
        reasons = " ".join(
            str(getattr(u, "reason", "") or "") for u in (building.unmet_requirements or [])
        )
        assert "does not fit the statutory ground plate" in reasons, reasons
        assert any(w.startswith("GEN-UNFIT") for w in building.warnings), building.warnings
        assert "m²" in reasons
        return
    assert building.qa_report["status"] == "fail"
    assert building.validation_gate["overall_status"] == "FAIL"
    l16 = next(
        l for l in building.validation_gate["layers"] if l["layer_id"] == "L16"
    )
    assert l16["status"] == "FAIL"
    assert l16["details"]["beyond_cap"], "a proportion FAIL must name the rooms"
    assert l16["details"]["justified_beyond_cap"], (
        "each beyond-cap room carries its own plate-capacity justification"
    )
    assert any("guest_bed_F0" in x or "kitchen_F0" in x or "bath_1_F0" in x
               for x in l16["details"]["beyond_cap"])
    assert len(building.floors) == 2
    assert any("Degradation Level 1" in w for w in building.warnings)
    assert any(w.startswith("ROOM-MIN") for w in building.warnings), (
        "the deficit banner needs the named squeezed-room lines"
    )


# =====================================================================
# 5. Performance and SVG Output
# =====================================================================

def test_solver_performance_and_svg_generation():
    """Verifies solver execution completes in < 1500ms and produces valid SVG blueprints."""
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=16.0,
        floors=3,
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()

    assert building.solver_timing_ms < 1500.0
    for floor in building.floors:
        assert floor.svg_blueprint_cad.startswith("<svg")
        assert floor.svg_blueprint_cad.endswith("</svg>")
        assert floor.svg_blueprint_paper.startswith("<svg")
        assert floor.svg_blueprint_paper.endswith("</svg>")
        assert floor.built_up_area_sqm > 0.0
        assert floor.carpet_area_sqm > 0.0


def test_floorplan_service_integration_multi_storey():
    """Verifies that generate_floor_plan automatically populates multi_storey when floors >= 1."""
    from app.services.floorplan.floorplan_service import generate_floor_plan

    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        floors=2,
        required_rooms=["living", "kitchen", "master_bed"],
    )
    resp = generate_floor_plan(req)
    assert resp.multi_storey is not None
    assert resp.multi_storey.total_storeys == 2
    assert len(resp.multi_storey.floors) == 2
    assert resp.multi_storey.global_metrics["stacking_invariant_verified"] is True


# =====================================================================
# 6. Typology Matrix Tests (4 Typologies x 1-4 Storeys x 3 Vastu Strictness)
# =====================================================================

TYPOLOGIES = [
    "T1_SINGLE_FAMILY",
    "T2_FAMILY_APARTMENT",
    "T3_LARGE_COMPLEX",
    "T4_WAREHOUSE",
]
STOREYS = [1, 2, 3, 4]
STRICTNESS_LEVELS = ["high", "medium", "low"]


@pytest.mark.parametrize("typology", TYPOLOGIES)
@pytest.mark.parametrize("floors_count", STOREYS)
@pytest.mark.parametrize("strictness", STRICTNESS_LEVELS)
def test_typology_matrix(typology, floors_count, strictness):
    """
    Validates complete matrix: 4 Typologies x 1-4 Storeys x 3 Strictness levels (48 combinations).
    Verifies:
    - total_storeys and floor count matches request
    - Stacking invariants hold (<0.001m drift)
    - Circulation connectivity (100% BFS reachability)
    - Valid non-zero built-up and carpet area on every floor
    - Valid CAD & Paper SVG output
    """
    plot_w = 24.0 if typology == "T4_WAREHOUSE" else 15.0
    plot_d = 30.0 if typology == "T4_WAREHOUSE" else 18.0

    req = FloorPlanRequest(
        plot_width_m=plot_w,
        plot_depth_m=plot_d,
        floors=floors_count,
        building_typology=typology,
        vastu_strictness=strictness,
        ground_coverage_ratio=0.60,
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()

    assert building.total_storeys == floors_count
    assert len(building.floors) == floors_count
    assert building.qa_report["status"] == "pass"
    assert building.qa_report["stacking_invariants"] == "pass"
    assert building.global_metrics["stacking_invariant_verified"] is True
    assert building.global_metrics["vastu_compliance_score"] > 0

    # Verify every floor plate
    f0 = building.floors[0]
    f0_core = next(r for r in f0.rooms if r.is_vertical_core)

    for z, floor in enumerate(building.floors):
        assert floor.floor_index == z
        assert floor.built_up_area_sqm > 0.0
        assert floor.carpet_area_sqm > 0.0
        assert floor.circulation_status == "connected"
        assert len(floor.rooms) >= 3
        assert floor.svg_blueprint_cad.startswith("<svg")
        assert floor.svg_blueprint_paper.startswith("<svg")

        # Stacking check against floor 0 core (< 0.001m drift)
        fz_core = next(r for r in floor.rooms if r.is_vertical_core)
        assert abs(fz_core.x - f0_core.x) < 0.001
        assert abs(fz_core.y - f0_core.y) < 0.001
        assert abs(fz_core.width_m - f0_core.width_m) < 0.001
        assert abs(fz_core.depth_m - f0_core.depth_m) < 0.001


# =====================================================================
# 7. Edge Case EC-04: Conflicting Constraints
# =====================================================================

def test_ec04_conflicting_constraints_kitchen_ne_override():
    """
    EC-04: Client requests Kitchen in North-East (taboo zone in Vastu).
    With strictness='high', solver must relocate Kitchen to South-East (Agni zone)
    and emit an explicit diagnostic warning detailing the override.
    """
    from app.schemas.multi_floor_plan import SpaceOrientationPreference
    constraints = ExtractedClientConstraints(
        orientation_preferences=[
            SpaceOrientationPreference(space="kitchen", preferred_facing="North-East")
        ]
    )
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="high",
        extracted_constraints=constraints,
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()

    assert any("EC-04 Vastu rule override" in w for w in building.warnings)
    assert any("Kitchen" in w and "South-East" in w for w in building.warnings)

    # Verify that Kitchen is placed in SE on ground floor
    f0 = building.floors[0]
    kitchen = next(r for r in f0.rooms if "kitchen" in r.room_id)
    assert kitchen.zone == "SE"
    assert kitchen.vastu_compliant is True


def test_ec04_conflicting_constraints_master_bed_ne_override():
    """
    EC-04: Client requests Master Bedroom in North-East.
    With strictness='high', solver overrides and relocates to South-West (Nairutya).
    """
    from app.schemas.multi_floor_plan import SpaceOrientationPreference
    constraints = ExtractedClientConstraints(
        orientation_preferences=[
            SpaceOrientationPreference(space="master bedroom", preferred_facing="North")
        ]
    )
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="high",
        extracted_constraints=constraints,
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()

    assert any("EC-04 Vastu rule override" in w for w in building.warnings)
    assert any("Master Bedroom" in w and "South-West" in w for w in building.warnings)

    # Verify Master Bedroom placement on first floor
    f1 = building.floors[1]
    m_bed = next(r for r in f1.rooms if "master" in r.room_id)
    assert m_bed.zone == "SW"


def test_ec04_low_strictness_lenient_handling():
    """With low Vastu strictness, user preferences are not sternly overridden."""
    from app.schemas.multi_floor_plan import SpaceOrientationPreference
    constraints = ExtractedClientConstraints(
        orientation_preferences=[
            SpaceOrientationPreference(space="kitchen", preferred_facing="North-East")
        ]
    )
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="low",
        extracted_constraints=constraints,
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()

    # In low strictness, EC-04 override warning is suppressed
    assert not any("EC-04 Vastu rule override" in w for w in building.warnings)


# =====================================================================
# 8. Typology Catalogs, Adjacency Graphs & Normalization
# =====================================================================

def test_typology_catalogs_and_normalization():
    """Verifies that all 4 typologies have valid catalogs, adjacency graphs, and solvers."""
    from app.services.floorplan.typologies import (
        normalize_typology,
        get_typology_solver,
        get_typology_catalog,
        get_typology_adjacency_graph,
        TYPOLOGY_T1,
        TYPOLOGY_T2,
        TYPOLOGY_T3,
        TYPOLOGY_T4,
    )

    # Test normalization of aliases
    assert normalize_typology("villa") == TYPOLOGY_T1
    assert normalize_typology("residential_single") == TYPOLOGY_T1
    assert normalize_typology("apartment") == TYPOLOGY_T2
    assert normalize_typology("commercial") == TYPOLOGY_T3
    assert normalize_typology("industrial") == TYPOLOGY_T4
    assert normalize_typology(None) == TYPOLOGY_T1

    # Verify each typology catalog has NBC minimum areas and valid adjacency graphs
    for typ in [TYPOLOGY_T1, TYPOLOGY_T2, TYPOLOGY_T3, TYPOLOGY_T4]:
        cat = get_typology_catalog(typ)
        assert len(cat) >= 5
        for space_id, meta in cat.items():
            assert "min_area_sqm" in meta
            assert meta["min_area_sqm"] > 0
            assert "min_width_m" in meta
            assert meta["min_width_m"] > 0

        graph = get_typology_adjacency_graph(typ)
        assert len(graph) >= 5

        solver_cls = get_typology_solver(typ)
        assert hasattr(solver_cls, "synthesize_floor_rooms")


def test_t4_warehouse_subminimum_plot_ec03():
    """EC-03: Verifies that warehouse typology on sub-minimum plot triggers graceful rejection."""
    req = FloorPlanRequest(
        plot_width_m=6.0,
        plot_depth_m=7.0,
        floors=1,
        building_typology="T4_WAREHOUSE",
    )
    solver = SoleGeometryEngine(req)
    building = solver.solve()
    assert building.qa_report["status"] == "failed"
    assert any("EC-03" in w for w in building.warnings)

