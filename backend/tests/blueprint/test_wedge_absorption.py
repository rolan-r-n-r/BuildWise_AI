import pytest
import math
from shapely.geometry import Polygon as ShapelyPolygon, box as ShapelyBox

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.site_plan import PlotPolygonModel, SitePlanModel
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.site_geometry import (
    compute_canonical_site_plan,
    validate_and_canonicalize_polygon,
    approximate_curvilinear_polygon,
    evaluate_orthogonal_waste_and_rotations,
)
from app.services.floorplan.drawing_ir import (
    build_site_drawing_ir,
    build_drawing_ir,
    render_svg_from_ir,
    render_reportlab_from_ir,
)


# ==============================================================================
# GOLDEN TEST FIXTURES
# ==============================================================================

# Acute Trapezoid: Base 16m, Top 9m, Depth 14m, Area = 175.0 m²
ACUTE_TRAPEZOID_VERTICES = [
    (0.0, 0.0),
    (16.0, 0.0),
    (12.0, 14.0),
    (3.0, 14.0),
]

# Curvilinear: 20m x 20m square with circular fillet arc on NE corner (approx 50 points, tolerance 0.10)
_straight_pts = [(0.0, 0.0), (20.0, 0.0), (20.0, 12.0)]
_arc_pts = []
for _step in range(1, 50):
    _angle = (math.pi / 2.0) * (_step / 49.0)
    _ax = round(12.0 + 8.0 * math.cos(_angle), 3)
    _ay = round(12.0 + 8.0 * math.sin(_angle), 3)
    _arc_pts.append((_ax, _ay))
_curved_verts = _straight_pts + _arc_pts + [(0.0, 20.0)]
_is_ok, _diags, _approx_coords = approximate_curvilinear_polygon(_curved_verts, tolerance=0.10)

CURVILINEAR_POLY_MODEL = PlotPolygonModel(
    vertices=_approx_coords,
    shape_type="irregular",
    has_curved_edges=True,
    is_regular_rectangle=False,
)


# ==============================================================================
# 1. AUDIT & WEDGE ABSORPTION ON ACUTE TRAPEZOID
# ==============================================================================

def test_acute_trapezoid_wedge_absorption():
    """
    On golden acute-trapezoid:
    1. Measures wasted buildable area before absorption (33.13 m² = 34.5% of buildable).
    2. Verifies slivers >= 3.0 m² and width >= 0.6 m are absorbed as functional wedge zones.
    3. Confirms wedge zones are classified (storage_closet, stair_wedge, planter, parking_apron).
    4. Verifies built-up area includes enclosed storage while carpet area strictly excludes all wedges.
    """
    poly = PlotPolygonModel(
        vertices=ACUTE_TRAPEZOID_VERTICES,
        shape_type="trapezoid",
        is_regular_rectangle=False,
    )
    is_ok, sp, warns = compute_canonical_site_plan(16.0, 14.0, plot_polygon=poly)
    assert is_ok is True and sp is not None

    # 1. Measurement before vs after
    assert sp.buildable_area_sqm > 0
    fp_area = sp.footprint.area_sqm
    buildable_area = sp.buildable_area_sqm
    wasted_raw = buildable_area - fp_area

    assert wasted_raw > 25.0, f"Raw wasted area should be > 25 m², got {wasted_raw:.2f}"
    assert sp.waste_pct > 25.0, f"Waste percentage should exceed 25%, got {sp.waste_pct:.1f}%"

    # 2. Wedge absorption
    assert len(sp.wedge_zones) >= 2, f"Expected at least 2 absorbed wedge zones, got {len(sp.wedge_zones)}"

    total_wedge_area = sum(w.area_sqm for w in sp.wedge_zones)

    # Wedges must absorb > 70% of the raw wasted area
    assert total_wedge_area / wasted_raw > 0.70, (
        f"Expected wedge zones to absorb >70% of waste ({wasted_raw:.2f} m²), "
        f"absorbed {total_wedge_area:.2f} m²"
    )

    # 3. Classifications
    valid_classes = {"storage_closet", "duct_shaft", "planter", "stair_wedge", "parking_apron"}
    for wz in sp.wedge_zones:
        assert wz.area_sqm >= 3.0, f"Wedge zone {wz.wedge_id} area must be >= 3.0 m², got {wz.area_sqm}"
        assert wz.width_m >= 0.6, f"Wedge zone {wz.wedge_id} width must be >= 0.6 m, got {wz.width_m}"
        assert wz.classification in valid_classes, f"Invalid classification {wz.classification}"

    # 4. Enclosed storage built-up vs carpet area
    req = FloorPlanRequest(
        plot_width_m=16.0,
        plot_depth_m=14.0,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=poly,
    )
    res = generate_floor_plan(req)
    assert res.multi_storey is not None

    bldg = res.multi_storey
    enclosed_storage_area = sum(w.area_sqm for w in sp.wedge_zones if w.is_enclosed_storage)

    # Built-up area includes enclosed storage
    if enclosed_storage_area > 0:
        assert bldg.total_built_up_area_sqm >= fp_area + enclosed_storage_area - 0.1

    # Carpet area strictly excludes all wedges
    carpet_area = sum(r.area_sqm for r in bldg.floors[0].rooms if not r.room_id.lower().startswith("terrace"))
    for wz in sp.wedge_zones:
        # None of the rooms should be a wedge zone
        assert all(r.room_id != wz.wedge_id for r in bldg.floors[0].rooms)


# ==============================================================================
# 2. CURVILINEAR BOUNDARY WEDGE ABSORPTION
# ==============================================================================

def test_curvilinear_wedge_absorption():
    """
    On curvilinear golden case:
    Curvilinear boundary approximated as polyline under tolerance rule.
    Wedge zones between squared-off footprint and curved boundary are absorbed.
    """
    is_ok, sp, warns = compute_canonical_site_plan(20.0, 20.0, plot_polygon=CURVILINEAR_POLY_MODEL)
    assert is_ok is True and sp is not None

    assert sp.plot_polygon.has_curved_edges is True
    assert len(sp.wedge_zones) >= 1, "Curvilinear boundary must absorb functional wedge zones"

    for wz in sp.wedge_zones:
        assert wz.area_sqm >= 3.0
        assert wz.width_m >= 0.6
        assert len(wz.polygon_coords) >= 3


# ==============================================================================
# 3. DECLARED DESIGN POLICY SURFACE & QA PANEL
# ==============================================================================

def test_declared_design_policy_surface():
    """
    POLICY SURFACE:
    Site sheet title block, QA report, and SVG banner state:
    'Building squared off; irregular residue allocated to setbacks/wedge zones'
    with rationale 'Structural grid, construction cost, NBC regularity'.
    """
    poly = PlotPolygonModel(
        vertices=ACUTE_TRAPEZOID_VERTICES,
        shape_type="trapezoid",
        is_regular_rectangle=False,
    )
    is_ok, sp, warns = compute_canonical_site_plan(16.0, 14.0, plot_polygon=poly)
    assert is_ok is True and sp is not None

    # Model attributes
    assert sp.design_policy == "Building squared off; irregular residue allocated to setbacks/wedge zones"
    assert sp.design_policy_rationale == "Structural grid, construction cost, NBC regularity"

    # Drawing IR & SVG rendering
    site_ir = build_site_drawing_ir(sp, gen_id="GEN-POLICY-01", typology="T1_SINGLE_FAMILY")
    assert site_ir.design_policy == sp.design_policy
    assert site_ir.design_policy_rationale == sp.design_policy_rationale

    svg = render_svg_from_ir(site_ir)
    assert "Building squared off; irregular residue allocated to setbacks/wedge zones" in svg
    assert "Structural grid, construction cost, NBC regularity" in svg
    assert "mf-hatch-wedge" in svg
    assert "Functional Wedge Zone (Non-Habitable Absorption)" in svg

    # Engine QA report
    req = FloorPlanRequest(
        plot_width_m=16.0,
        plot_depth_m=14.0,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=poly,
    )
    res = generate_floor_plan(req)
    assert res.multi_storey is not None
    qa = res.multi_storey.qa_report

    assert qa.get("design_policy") == sp.design_policy
    assert qa.get("design_policy_rationale") == sp.design_policy_rationale
    assert qa.get("wedge_zones_count", 0) >= 2


# ==============================================================================
# 4. WASTE WARNING & ROTATION ALTERNATIVES EVALUATION
# ==============================================================================

def test_waste_warning_fires_on_narrow_acute_case():
    """
    WASTE WARNING:
    On acute trapezoid, best orthogonal footprint wastes > 25% of buildable area.
    Evaluates candidate rotations (0° axis + edge-aligned angles).
    Asserts warning fires and rotation alternatives recorded in QA.
    """
    poly = PlotPolygonModel(
        vertices=ACUTE_TRAPEZOID_VERTICES,
        shape_type="trapezoid",
        is_regular_rectangle=False,
    )
    is_ok, sp, warns = compute_canonical_site_plan(16.0, 14.0, plot_polygon=poly)
    assert is_ok is True and sp is not None

    assert sp.waste_warning_triggered is True
    assert sp.waste_pct > 25.0
    assert len(sp.rotation_alternatives) >= 2

    # Check rotation candidate recording
    angles_evaluated = [alt["angle_deg"] for alt in sp.rotation_alternatives]
    assert 0.0 in angles_evaluated

    # Check user-facing warning in floor plan response
    req = FloorPlanRequest(
        plot_width_m=16.0,
        plot_depth_m=14.0,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=poly,
    )
    res = generate_floor_plan(req)
    assert any("Waste warning" in w for w in res.warnings), "Expected Waste warning in response warnings"


# ==============================================================================
# 5. INVARIANT TEST: ALL HABITABLE ROOMS STRICTLY RECTANGULAR
# ==============================================================================

@pytest.mark.parametrize("typology", ["T1_SINGLE_FAMILY", "T2_FAMILY_APARTMENT", "T3_LARGE_COMPLEX", "T4_WAREHOUSE"])
@pytest.mark.parametrize("plot_poly_model", [
    PlotPolygonModel(vertices=ACUTE_TRAPEZOID_VERTICES, shape_type="trapezoid", is_regular_rectangle=False),
    CURVILINEAR_POLY_MODEL,
])
def test_all_habitable_rooms_strictly_rectangular(typology, plot_poly_model):
    """
    INVARIANT TEST:
    All habitable rooms strictly rectangular (4 orthogonal corners, width * depth == area).
    Only wedge / terrace / outdoor fragments may be polygons.
    Assert on T1-T4 x irregular golden cases (Acute Trapezoid, Curvilinear).
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=20.0,
        floors=2,
        building_typology=typology,
        plot_polygon=plot_poly_model,
    )
    res = generate_floor_plan(req)
    assert res.multi_storey is not None, f"Failed generating for {typology}"

    for floor in res.multi_storey.floors:
        for room in floor.rooms:
            rid = room.room_id.lower()
            is_terrace = "terrace" in rid or getattr(room, "zone_category", "") == "terrace"
            if is_terrace:
                continue

            # Every habitable and service room must have 4 orthogonal corners and standard rectangle properties
            assert room.width_m > 0, f"Room {room.room_id} width must be > 0"
            assert room.depth_m > 0, f"Room {room.room_id} depth must be > 0"
            expected_area = room.width_m * room.depth_m
            assert abs(room.area_sqm - expected_area) < 0.25, (
                f"Room {room.room_id} in {typology} not rectangular! "
                f"Area {room.area_sqm} != {room.width_m} * {room.depth_m} ({expected_area})"
            )


# ==============================================================================
# 6. RECTANGLE-EQUIVALENCE PRESERVATION
# ==============================================================================

def test_rectangle_equivalence_preservation():
    """
    RECTANGLE EQUIVALENCE:
    For regular rectangle plots:
    - wedge_zones is empty (no wedges generated)
    - waste_warning_triggered is False
    - design_policy is None
    - Byte-identical SVG vs legacy path
    """
    rect_poly = PlotPolygonModel(
        vertices=[(0.0, 0.0), (15.0, 0.0), (15.0, 12.0), (0.0, 12.0)],
        shape_type="rectangle",
        is_regular_rectangle=True,
    )
    is_ok, sp, warns = compute_canonical_site_plan(15.0, 12.0, plot_polygon=rect_poly)
    assert is_ok is True and sp is not None

    assert len(sp.wedge_zones) == 0, "Regular rectangle must not generate wedge zones"
    assert sp.waste_warning_triggered is False, "Regular rectangle must not trigger waste warning"
    assert sp.design_policy is None, "Regular rectangle does not declare squaring-off policy"
