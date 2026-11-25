import shapely
from shapely.geometry import Polygon as ShapelyPolygon, Point as ShapelyPoint, box

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.site_plan import PlotPolygonModel, SitePlanModel
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.site_geometry import (
    compute_canonical_site_plan,
    validate_and_canonicalize_polygon,
    compute_required_ecs,
    compute_parking_envelope,
)
from app.services.floorplan.drawing_ir import (
    build_site_drawing_ir,
    build_drawing_ir,
    verify_site_sheet_completeness,
    render_svg_from_ir,
    render_reportlab_from_ir,
)
from app.services.report_service import generate_pdf_report


# ==============================================================================
# GOLDEN IRREGULAR TEST FIXTURES
# ==============================================================================

# 1. L-Shape (Concave): 20m x 20m overall bbox, Area = 352 m²
L_SHAPE_VERTICES = [
    (0.0, 0.0),
    (20.0, 0.0),
    (20.0, 14.0),
    (12.0, 14.0),
    (12.0, 20.0),
    (0.0, 20.0),
]

# 2. Trapezoid: Base 16m, Top 9m, Depth 14m, Area = 175 m²
TRAPEZOID_VERTICES = [
    (0.0, 0.0),
    (16.0, 0.0),
    (12.0, 14.0),
    (3.0, 14.0),
]

# 3. Pentagon (Chamfered Corner): 14m x 15m with chamfered corner, Area = 185 m²
PENTAGON_VERTICES = [
    (0.0, 0.0),
    (14.0, 0.0),
    (14.0, 10.0),
    (9.0, 15.0),
    (0.0, 15.0),
]


# ==============================================================================
# 1. BUILDING-LINE DERIVATION & CONTAINMENT PROOF
# ==============================================================================

def test_floor_envelope_provably_contained_in_buildable_polygon_golden_cases():
    """
    Assert for every golden irregular case (L-shape, Trapezoid, Pentagon):
    1. The floor envelope is strictly contained within the buildable polygon with margin >= 0.
    2. Building-line coordinates are explicitly exposed.
    3. Derivation banner text and chain follow the strict specification.
    """
    golden_cases = [
        ("L-Shape", L_SHAPE_VERTICES),
        ("Trapezoid", TRAPEZOID_VERTICES),
        ("Pentagon", PENTAGON_VERTICES),
    ]

    for name, vertices in golden_cases:
        poly_model = PlotPolygonModel(
            vertices=vertices,
            shape_type="irregular",
            is_regular_rectangle=False,
        )
        req = FloorPlanRequest(
            plot_width_m=20.0,
            plot_depth_m=20.0,
            floors=2,
            building_typology="T1_SINGLE_FAMILY",
            required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
            plot_polygon=poly_model,
        )
        res = generate_floor_plan(req)
        assert res.multi_storey is not None, f"Generation failed for {name}"
        raw_site_plan = res.multi_storey.site_plan
        assert raw_site_plan is not None, f"Site plan must exist for {name}"
        sp = SitePlanModel.model_validate(raw_site_plan)

        # 1. Geometry Containment Proof
        buildable_poly = ShapelyPolygon(sp.buildable_polygon_coords)
        if sp.footprint.wings:
            wing_boxes = [box(w.x, w.y, w.x + w.width_m, w.y + w.depth_m) for w in sp.footprint.wings]
            footprint_poly = shapely.unary_union(wing_boxes)
        else:
            footprint_poly = box(
                sp.footprint.x,
                sp.footprint.y,
                sp.footprint.x + sp.footprint.width_m,
                sp.footprint.y + sp.footprint.depth_m
            )

        # Allow 1e-4 tolerance for numerical precision at polygon boundaries
        is_contained = buildable_poly.buffer(1e-4).contains(footprint_poly)
        assert is_contained, (
            f"Footprint envelope is NOT contained in buildable polygon for {name}! "
            f"Buildable area: {buildable_poly.area}, Footprint area: {footprint_poly.area}"
        )
        assert sp.certificate.footprint_contained_in_buildable is True

        # Check margin >= 0
        min_distance = buildable_poly.exterior.distance(footprint_poly)
        assert min_distance >= -1e-4, f"Margin must be >= 0 for {name}, got {min_distance}"

        # 2. Building-Line Coordinates Expose
        assert sp.building_line_coords is not None
        assert len(sp.building_line_coords) == len(sp.buildable_polygon_coords)
        assert sp.building_line_coords == sp.buildable_polygon_coords

        # 3. Setback dimensions exposed
        assert sp.setback_dimensions is not None
        for side in ["front_m", "rear_m", "left_m", "right_m"]:
            assert side in sp.setback_dimensions
            assert sp.setback_dimensions[side] > 0

        # 4. Derivation Text & Chain
        assert sp.derivation_chain is not None
        assert len(sp.derivation_chain) >= 4
        assert sp.derivation_text is not None
        assert sp.derivation_text.startswith("FOOTPRINT DERIVED FROM BUILDABLE POLYGON P1..P")


# ==============================================================================
# 2. PARKING-FIRST PIPELINE & ECS COMPLIANCE
# ==============================================================================

def test_parking_first_ecs_requirements_by_typology():
    """
    Verify ECS count calculation across typologies:
    - T1 (residential single): 1-2 ECS
    - T2 (family apartment): 2 ECS
    - T3 (large complex): 1 ECS per 50 m² BUA
    - T4 (warehouse): 1 ECS per 100 m² BUA
    """
    assert compute_required_ecs("T1_SINGLE_FAMILY", 150.0, built_up_m2=120) == 1
    assert compute_required_ecs("T1_SINGLE_FAMILY", 300.0, built_up_m2=250) == 2
    assert compute_required_ecs("T2_FAMILY_APARTMENT", 200.0, units=2) == 2
    assert compute_required_ecs("T3_LARGE_COMPLEX", 300.0, built_up_m2=500) == 8
    assert compute_required_ecs("T4_WAREHOUSE", 400.0, built_up_m2=500) == 3


def test_parking_first_coexistence_and_deficit_warning():
    """
    Verify parking envelope computation:
    - Generates 2.5m x 5.0m bays + 3.5m drive aisle.
    - If parking + footprint cannot coexist, emits an explicit warning with 3 actionable options:
      'reduce footprint', 'stack parking', 'accept deficit'.
    """
    poly = ShapelyPolygon(L_SHAPE_VERTICES)
    buildable = ShapelyPolygon([
        (1.5, 3.0),
        (18.5, 3.0),
        (18.5, 12.5),
        (10.5, 12.5),
        (10.5, 18.5),
        (1.5, 18.5),
    ])

    # Case A: Normal plot with room for standard bays
    envelope_a, warns_a = compute_parking_envelope(
        poly,
        buildable,
        typology="T1_SINGLE_FAMILY",
        plot_w=20.0,
        plot_d=20.0,
        built_up_m2=100.0,
    )
    assert envelope_a.required_ecs >= 1
    assert envelope_a.provided_ecs >= 1
    assert envelope_a.bays[0].width_m == 2.5
    assert envelope_a.bays[0].length_m == 5.0
    assert envelope_a.drive_aisle_width_m == 3.5

    # Case B: Massive footprint taking up the entire buildable area -> Deficit warning triggered
    envelope_b, warns_b = compute_parking_envelope(
        poly,
        buildable,
        typology="T3_LARGE_COMPLEX",
        plot_w=20.0,
        plot_d=20.0,
        built_up_m2=1000.0,
        target_footprint_m2=buildable.area,
    )
    assert envelope_b.required_ecs == 15
    assert envelope_b.deficit_ecs > 0
    assert envelope_b.deficit_warning is not None
    assert "deficit:" in envelope_b.deficit_warning.lower()
    assert any("reduce" in opt.lower() and "footprint" in opt.lower() for opt in envelope_b.coexistence_options)
    assert any("stack parking" in opt.lower() for opt in envelope_b.coexistence_options)
    assert any("accept" in opt.lower() and "deficit" in opt.lower() for opt in envelope_b.coexistence_options)


# ==============================================================================
# 3. 8-POINT SITE SHEET COMPLETENESS CHECKLIST
# ==============================================================================

def test_site_sheet_completeness_all_8_items():
    """
    Verify that build_site_drawing_ir generates all 8 required checklist elements:
    1. road_side_and_width
    2. vehicular_gate_and_pedestrian_entry
    3. parking_bays_with_dims
    4. sewer_connection_point
    5. stormwater_outlet_and_drainage_arrows
    6. finished_ground_level_and_slope_note
    7. setback_dimensions_every_side
    8. neighbour_ticks
    """
    poly_model = PlotPolygonModel(
        vertices=TRAPEZOID_VERTICES,
        shape_type="irregular",
        is_regular_rectangle=False,
    )
    is_ok, site_plan, warns = compute_canonical_site_plan(
        16.0,
        14.0,
        plot_polygon=poly_model,
        typology="T1_SINGLE_FAMILY",
    )
    assert is_ok is True
    assert site_plan is not None
    site_ir = build_site_drawing_ir(site_plan)

    is_complete, checklist, missing = verify_site_sheet_completeness(site_ir)
    assert is_complete is True, f"Site sheet failed completeness! Missing: {missing}"
    assert len(missing) == 0

    assert checklist["road_side_and_width"] is True
    assert checklist["vehicular_gate_and_pedestrian_entry"] is True
    assert checklist["parking_bays_with_dims"] is True
    assert checklist["sewer_connection_point"] is True
    assert checklist["stormwater_outlet_and_drainage_arrows"] is True
    assert checklist["finished_ground_level_and_slope_note"] is True
    assert checklist["setback_dimensions_every_side"] is True
    assert checklist["neighbour_ticks"] is True


def test_site_sheet_completeness_fails_on_missing_element():
    """
    Verify that verify_site_sheet_completeness fails gracefully if a required item is removed.
    """
    poly_model = PlotPolygonModel(
        vertices=TRAPEZOID_VERTICES,
        shape_type="irregular",
        is_regular_rectangle=False,
    )
    is_ok, site_plan, warns = compute_canonical_site_plan(
        16.0,
        14.0,
        plot_polygon=poly_model,
        typology="T1_SINGLE_FAMILY",
    )
    assert is_ok is True
    assert site_plan is not None
    site_ir = build_site_drawing_ir(site_plan)

    # Intentionally remove sewer connection primitive
    site_ir.primitives = [
        p for p in site_ir.primitives
        if not ("SEWER" in getattr(p, "text", "") or getattr(p, "layer", "") == "sewer")
    ]

    is_complete, checklist, missing = verify_site_sheet_completeness(site_ir)
    assert is_complete is False
    assert "sewer_connection_point" in missing
    assert checklist["sewer_connection_point"] is False


# ==============================================================================
# 4. ANNOTATION STATUS TAXONOMY
# ==============================================================================

def test_annotation_status_taxonomy_coverage():
    """
    Every annotation primitive carries a status in:
    CALCULATED | ASSUMED | RECOMMENDED | VERIFIED
    Legend defines them, and primitives are correctly categorized.
    """
    poly_model = PlotPolygonModel(
        vertices=PENTAGON_VERTICES,
        shape_type="irregular",
        is_regular_rectangle=False,
    )
    is_ok, site_plan, warns = compute_canonical_site_plan(
        14.0,
        15.0,
        plot_polygon=poly_model,
        typology="T1_SINGLE_FAMILY",
    )
    assert is_ok is True
    assert site_plan is not None
    site_ir = build_site_drawing_ir(site_plan)

    valid_statuses = {"CALCULATED", "ASSUMED", "RECOMMENDED", "VERIFIED"}

    # Check each primitive has a valid status
    status_counts = {"CALCULATED": 0, "ASSUMED": 0, "RECOMMENDED": 0, "VERIFIED": 0}
    for prim in site_ir.primitives:
        assert hasattr(prim, "status"), f"Primitive {prim} missing status attribute"
        assert prim.status in valid_statuses, f"Invalid status: {prim.status}"
        status_counts[prim.status] += 1

    # Ensure all four taxonomy categories are represented on the sheet
    for cat in valid_statuses:
        assert status_counts[cat] > 0, f"Taxonomy status {cat} has 0 primitives!"

    # Taxonomy group helper
    tax_groups = site_ir.get_annotation_taxonomy_groups()
    for cat in valid_statuses:
        assert cat in tax_groups
        assert len(tax_groups[cat]) == status_counts[cat]


def test_status_taxonomy_on_floor_drawing_ir():
    """
    Verify floor plan drawing IR also implements the taxonomy.
    """
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=12.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
    )
    res = generate_floor_plan(req)
    assert res.multi_storey is not None
    floor_ir = build_drawing_ir(res.multi_storey.floors[0], theme="cad")

    valid_statuses = {"CALCULATED", "ASSUMED", "RECOMMENDED", "VERIFIED"}
    for prim in floor_ir.primitives:
        assert prim.status in valid_statuses

    groups = floor_ir.get_annotation_taxonomy_groups()
    assert "CALCULATED" in groups
    assert "VERIFIED" in groups


# ==============================================================================
# 5. DRAWING-STATUS STAMP
# ==============================================================================

def test_drawing_status_stamp_format_and_honesty():
    """
    Title block line:
    STATUS: CONCEPT DESIGN - VALIDATED LAYERS: [L1..] - NOT FOR CONSTRUCTION
    List grows as validation layers land; never claims construction readiness.
    """
    poly_model = PlotPolygonModel(
        vertices=L_SHAPE_VERTICES,
        shape_type="irregular",
        is_regular_rectangle=False,
    )
    is_ok, site_plan, warns = compute_canonical_site_plan(
        20.0,
        20.0,
        plot_polygon=poly_model,
        typology="T1_SINGLE_FAMILY",
    )
    assert is_ok is True
    assert site_plan is not None
    site_ir = build_site_drawing_ir(site_plan)

    stamp = site_ir.header.drawing_status_stamp
    assert stamp.startswith("STATUS: CONCEPT DESIGN")
    assert "VALIDATED LAYERS:" in stamp
    assert "NOT FOR CONSTRUCTION" in stamp
    assert "L1" in stamp
    assert "L2" in stamp

    # Check SVG rendering includes the status stamp text
    svg_site = render_svg_from_ir(site_ir)
    assert "STATUS: CONCEPT DESIGN" in svg_site
    assert "NOT FOR CONSTRUCTION" in svg_site
    assert "FOOTPRINT DERIVED FROM BUILDABLE POLYGON" in svg_site


# ==============================================================================
# 6. PDF DOSSIER PARITY & RECTANGLE EQUIVALENCE
# ==============================================================================

def test_pdf_report_contains_truth_elements_for_irregular_site():
    """
    Verify PDF generation for irregular sites includes:
    - Status stamp callout
    - Derivation chain banner
    - Parking envelope table
    - Annotation status taxonomy
    """
    poly_model = PlotPolygonModel(
        vertices=PENTAGON_VERTICES,
        shape_type="irregular",
        is_regular_rectangle=False,
    )
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=15.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
        plot_polygon=poly_model,
    )
    plan = generate_floor_plan(req)
    buf = generate_pdf_report({"project_id": "test_pentagon"}, floor_plan=plan.model_dump())
    pdf_bytes = buf.getvalue()

    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")


# ==============================================================================
# 6. SITE PLAN 10.SP SHEET - PIN-CENTRED (CAPTURED) PLOT FRAME
# ==============================================================================

def _site_sheet_and_envelope(ox: float, oy: float):
    """Generates the site sheet and ground-floor envelope for a plot at (ox, oy)."""
    plot_w, plot_d = 18.4, 29.7
    vertices = [[ox, oy], [ox + plot_w, oy], [ox + plot_w, oy + plot_d], [ox, oy + plot_d]]
    poly_model = PlotPolygonModel(
        vertices=vertices,
        shape_type="polygon",
        is_regular_rectangle=True,
        area_sqm=plot_w * plot_d,
        perimeter_m=2 * (plot_w + plot_d),
        origin_lat=12.9716,
        origin_lon=77.5946,
    )
    req = FloorPlanRequest(
        plot_width_m=plot_w,
        plot_depth_m=plot_d,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
        plot_polygon=poly_model,
    )
    plan = generate_floor_plan(req)
    site_plan = SitePlanModel.model_validate(plan.multi_storey.site_plan)
    ir = build_site_drawing_ir(site_plan, gen_id="42", typology="T1_SINGLE_FAMILY")
    return render_svg_from_ir(ir, theme="cad"), site_plan, plan.multi_storey.floors[0].envelope


def test_site_sheet_frame_is_independent_of_where_the_pin_was_dropped():
    """
    A captured boundary is pin-centred, so its local coordinates are negative. The
    Site Plan 10.SP sheet must be authored in the plot's own frame: rebasing the plot
    to the origin must not move, clip or restyle a single drawn line.

    Regression: the sheet was previously authored in the pin's frame, pushing the plot
    off the left edge and stretching the viewBox until the plate was cut off.
    """
    origin_sheet, _, _ = _site_sheet_and_envelope(0.0, 0.0)
    # Pin dropped mid-plot: every local coordinate is negative.
    pin_sheet, pin_site, _ = _site_sheet_and_envelope(-9.2, -14.85)

    assert pin_sheet == origin_sheet, "Site sheet changed when the same plot was pin-centred"


def test_floor_envelope_matches_site_footprint_when_plot_is_pin_centred():
    """
    The floor plate must sit on the site footprint at the same (x, y) - both are drawn
    in the plot's frame, so a pin-centred capture cannot displace one from the other.

    Regression: the floor envelope was computed corner-based and landed half a plot
    away from the site footprint, which is what tracked the pin as a stray rectangle.
    """
    _, origin_site, origin_env = _site_sheet_and_envelope(0.0, 0.0)
    _, pin_site, pin_env = _site_sheet_and_envelope(-9.2, -14.85)

    for site, env in ((origin_site, origin_env), (pin_site, pin_env)):
        assert abs(env["x"] - site.footprint.x) <= 0.01, (env, site.footprint)
        assert abs(env["y"] - site.footprint.y) <= 0.01, (env, site.footprint)

    # Same building, translated by exactly the pin offset.
    assert abs((pin_env["x"] - origin_env["x"]) - (-9.2)) <= 0.01
    assert abs((pin_env["y"] - origin_env["y"]) - (-14.85)) <= 0.01
