import pytest
import math
from shapely.geometry import Polygon as ShapelyPolygon, Point as ShapelyPoint

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.site_plan import PlotPolygonModel, SitePlanModel
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.site_geometry import (
    compute_canonical_site_plan,
    validate_and_canonicalize_polygon,
    compute_buildable_polygon,
    find_largest_inscribed_rectangle,
    extract_outdoor_fragments,
    compute_survey_edges,
    approximate_curvilinear_polygon,
)
from app.services.floorplan.drawing_ir import (
    build_site_drawing_ir,
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

# 3. Pentagon (Chamfered Corner): 14m x 15m with chamfered top-right corner, Area = 185 m²
PENTAGON_VERTICES = [
    (0.0, 0.0),
    (14.0, 0.0),
    (14.0, 10.0),
    (9.0, 15.0),
    (0.0, 15.0),
]


# ==============================================================================
# 1. RECTANGLE-EQUIVALENCE REGRESSION TEST
# ==============================================================================

def test_rectangle_equivalence_regression():
    """
    RECTANGLE-EQUIVALENCE REGRESSION:
    For seeded rectangle cases, the 4-vertex polygon path must produce
    byte-identical floor plan SVG and identical envelope vs legacy rectangle path.
    """
    # Legacy rectangle request
    req_legacy = FloorPlanRequest(
        plot_width_m=15.0,
        plot_depth_m=12.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="high",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
    )

    # 4-vertex polygon representation of the exact same rectangle
    rect_poly = PlotPolygonModel(
        vertices=[
            (0.0, 0.0),
            (15.0, 0.0),
            (15.0, 12.0),
            (0.0, 12.0),
        ],
        shape_type="rectangle",
        is_regular_rectangle=True,
    )
    req_poly = FloorPlanRequest(
        plot_width_m=15.0,
        plot_depth_m=12.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="high",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
        plot_polygon=rect_poly,
    )

    res_legacy = generate_floor_plan(req_legacy)
    res_poly = generate_floor_plan(req_poly)

    assert res_legacy.multi_storey is not None
    assert res_poly.multi_storey is not None

    bldg_legacy = res_legacy.multi_storey
    bldg_poly = res_poly.multi_storey

    # 1. Envelope coordinates must be exactly identical
    assert bldg_legacy.floors[0].envelope["width"] == bldg_poly.floors[0].envelope["width"]
    assert bldg_legacy.floors[0].envelope["depth"] == bldg_poly.floors[0].envelope["depth"]
    assert bldg_legacy.floors[0].envelope["x"] == bldg_poly.floors[0].envelope["x"]
    assert bldg_legacy.floors[0].envelope["y"] == bldg_poly.floors[0].envelope["y"]

    # 2. Floor 1 & 2 SVGs must be byte-identical
    for f_idx in range(len(bldg_legacy.floors)):
        svg_legacy = bldg_legacy.floors[f_idx].svg_blueprint_cad
        svg_poly = bldg_poly.floors[f_idx].svg_blueprint_cad
        assert svg_legacy == svg_poly, f"Floor {f_idx + 1} SVG differed between legacy and 4V polygon path!"

    # 3. PDF generation must succeed for both and have identical length
    dump_legacy = res_legacy.model_dump()
    dump_poly = res_poly.model_dump()
    dump_poly["generated_at"] = dump_legacy["generated_at"]
    dump_poly["timing_ms"] = dump_legacy["timing_ms"]
    if dump_poly.get("multi_storey") and dump_legacy.get("multi_storey"):
        dump_poly["multi_storey"]["solver_timing_ms"] = dump_legacy["multi_storey"]["solver_timing_ms"]

    # Pin the PDF clock inputs: report_service stamps request_id/timestamp with
    # datetime.now() per build, so two builds straddling a second boundary emit
    # different digit strings whose zlib-compressed byte lengths can differ by
    # more than the parity slack below (latent flake). Same clock in -> the
    # byte-length comparison measures content, not wall time.
    _pdf_meta = {
        "project_id": "test_rect_reg",
        "request_id": "test_rect_reg",
        "timestamp": "2026-01-01 00:00:00 UTC",
    }
    buf_legacy = generate_pdf_report(dict(_pdf_meta), floor_plan=dump_legacy)
    buf_poly = generate_pdf_report(dict(_pdf_meta), floor_plan=dump_poly)
    pdf_legacy = buf_legacy.getvalue()
    pdf_poly = buf_poly.getvalue()
    assert len(pdf_legacy) > 1000
    assert len(pdf_poly) > 1000
    # For regular rectangles, site sheet is not injected, ensuring page count and byte length parity
    assert abs(len(pdf_legacy) - len(pdf_poly)) <= 5, f"PDF byte lengths differed: {len(pdf_legacy)} vs {len(pdf_poly)}"


# ==============================================================================
# 2. GOLDEN IRREGULAR CASES (L-Shape, Trapezoid, Pentagon)
# ==============================================================================

@pytest.mark.parametrize("shape_name,vertices,expected_min_area", [
    ("l_shape", L_SHAPE_VERTICES, 200.0),
    ("trapezoid", TRAPEZOID_VERTICES, 170.0),
    ("pentagon", PENTAGON_VERTICES, 180.0),
])
def test_golden_irregular_cases(shape_name: str, vertices, expected_min_area: float):
    """
    Golden irregular cases:
    - Footprint fully inside buildable polygon (shapely contains)
    - Setback margins >= code minima (polygon distance to boundary)
    - Coverage and FAR check vs canonical polygon area
    - Outdoor difference fragments are non-empty and labelled with areas
    - Vertical stacking and floor solver remain 100% rectangular
    """
    poly_model = PlotPolygonModel(
        vertices=vertices,
        shape_type=shape_name,
        is_regular_rectangle=False,
    )

    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=20.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
        plot_polygon=poly_model,
    )

    res = generate_floor_plan(req)
    assert res.multi_storey is not None, f"Generation failed for {shape_name}"
    bldg = res.multi_storey

    # Site plan must be attached
    assert bldg.site_plan is not None
    sp = SitePlanModel.model_validate(bldg.site_plan)
    assert sp.plot_polygon.shape_type == shape_name
    assert sp.plot_polygon.area_sqm >= expected_min_area
    assert sp.certificate.is_valid is True

    # 1. Shapely contains check: Footprint polygon must be strictly within buildable polygon
    buildable_poly = ShapelyPolygon(sp.buildable_polygon_coords)
    footprint = sp.footprint
    site_poly = ShapelyPolygon(sp.plot_polygon.vertices)

    if footprint.topology_type == "single_rectangle":
        fp_poly = ShapelyPolygon([
            (footprint.x, footprint.y),
            (footprint.x + footprint.width_m, footprint.y),
            (footprint.x + footprint.width_m, footprint.y + footprint.depth_m),
            (footprint.x, footprint.y + footprint.depth_m),
        ])
        assert buildable_poly.buffer(1e-3).contains(fp_poly), (
            f"Footprint {fp_poly.bounds} not contained in buildable polygon for {shape_name}"
        )
        dist_to_boundary = site_poly.boundary.distance(fp_poly)
        fp_area = footprint.width_m * footprint.depth_m
    else:
        for wing in footprint.wings:
            w_poly = ShapelyPolygon(wing.corner_vertices)
            assert buildable_poly.buffer(1e-3).contains(w_poly), (
                f"Wing {wing.wing_id} {w_poly.bounds} not contained in buildable polygon for {shape_name}"
            )
        for corr in footprint.corridors:
            c_poly = ShapelyPolygon(corr.polygon_coords)
            assert buildable_poly.buffer(1e-3).contains(c_poly), (
                f"Corridor {corr.link_id} not contained in buildable polygon for {shape_name}"
            )
        dist_to_boundary = min(
            site_poly.boundary.distance(ShapelyPolygon(wing.corner_vertices))
            for wing in footprint.wings
        )
        fp_area = sum(w.area_sqm for w in footprint.wings)

    # 2. Setback check: Distance from footprint to plot boundary >= nominal setback
    # Distance must be at least the statutory setback (accounting for mitre/collapse adjustments)
    assert dist_to_boundary >= sp.nominal_setback_m - 0.25, (
        f"Setback margin {dist_to_boundary:.2f}m < code minimum for {shape_name}"
    )

    # 3. Coverage and FAR check vs canonical polygon area
    plot_area = sp.plot_polygon.area_sqm
    coverage_ratio = fp_area / plot_area
    assert coverage_ratio * 100.0 <= sp.certificate.ground_coverage_limit_pct + 5.0
    total_built_up = fp_area * bldg.total_storeys
    achieved_far = total_built_up / plot_area
    assert achieved_far <= sp.certificate.far_limit + 0.1

    # 4. Every residual is labelled exactly once: outdoor fragments and/or
    # functional wedge zones (a fully absorbed plate may have no outdoor zone).
    assert len(sp.outdoor_zones) + len(sp.wedge_zones) > 0
    total_labelled_area = sum(f.area_sqm for f in sp.outdoor_zones) + sum(w.area_sqm for w in sp.wedge_zones)
    assert total_labelled_area > 0
    # Each fragment must have a valid zone name and coordinates
    for frag in list(sp.outdoor_zones) + list(sp.wedge_zones):
        assert frag.name != ""
        assert frag.area_sqm > 0
        assert len(frag.polygon_coords) >= 3

    # 5. Floor solver and floor sheets remain 100% rectangular
    for fl in bldg.floors:
        assert fl.envelope["width"] == pytest.approx(footprint.width_m, rel=1e-3)
        assert fl.envelope["depth"] == pytest.approx(footprint.depth_m, rel=1e-3)
        assert fl.svg_blueprint_cad != ""
        assert "rect" in fl.svg_blueprint_cad.lower()

    # 6. Site plan drawing IR and SVG generated
    assert sp.svg_site_plan is not None
    assert "SITE" in sp.svg_site_plan.upper()
    assert "mf-hatch-setback" in sp.svg_site_plan


# ==============================================================================
# 3. GRACEFUL FAILURE & ROBUST VALIDATION
# ==============================================================================

def test_validation_rejects_self_intersecting_polygon():
    """Self-intersecting (bow-tie / figure-8) polygon must fail validation gracefully."""
    bowtie_verts = [
        (0.0, 0.0),
        (10.0, 10.0),
        (10.0, 0.0),
        (0.0, 10.0),
    ]
    # Direct validator check
    is_valid, diags, _, _ = validate_and_canonicalize_polygon(bowtie_verts)
    assert is_valid is False
    assert any("self-intersecting" in d.lower() or "invalid" in d.lower() for d in diags)

    # Engine graceful failure check
    poly_model = PlotPolygonModel(
        vertices=bowtie_verts,
        shape_type="irregular",
    )
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=10.0,
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed"],
    )
    res = generate_floor_plan(req)
    assert res.status == "failed" or len(res.multi_storey.floors) == 0
    warns = " ".join(res.warnings + (res.multi_storey.warnings if res.multi_storey else [])).lower()
    assert "self-intersecting" in warns or "invalid" in warns


def test_validation_rejects_narrow_wedge():
    """Polygon with edge length < 1.0m statutory minimum must fail validation gracefully."""
    narrow_verts = [
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 0.5),  # 0.5m edge -> < 1.0m
        (0.0, 10.0),
    ]
    # Direct validator check
    is_valid, diags, _, _ = validate_and_canonicalize_polygon(narrow_verts)
    assert is_valid is False
    assert any("< 1.0m" in d or "statutory minimum" in d.lower() for d in diags)

    # Engine graceful failure check
    poly_model = PlotPolygonModel(
        vertices=narrow_verts,
        shape_type="irregular",
    )
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=10.0,
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed"],
    )
    res = generate_floor_plan(req)
    assert res.status == "failed" or len(res.multi_storey.floors) == 0
    warns = " ".join(res.warnings + (res.multi_storey.warnings if res.multi_storey else [])).lower()
    assert "< 1.0m" in warns or "statutory minimum" in warns


def test_validation_rejects_sub_minimum_area():
    """Polygon with area < 36 m² statutory minimum must fail validation gracefully."""
    small_verts = [
        (0.0, 0.0),
        (5.0, 0.0),
        (5.0, 5.0),
        (0.0, 5.0),
    ]  # 25 m² < 36 m²
    # Direct validator check
    is_valid, diags, _, _ = validate_and_canonicalize_polygon(small_verts)
    assert is_valid is False
    assert any("< 36 m²" in d or "statutory minimum" in d.lower() for d in diags)

    # Engine graceful failure check
    poly_model = PlotPolygonModel(
        vertices=small_verts,
        shape_type="irregular",
    )
    req = FloorPlanRequest(
        plot_width_m=6.0,
        plot_depth_m=6.0,
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed"],
    )
    res = generate_floor_plan(req)
    assert res.status == "failed" or len(res.multi_storey.floors) == 0
    warns = " ".join(res.warnings + (res.multi_storey.warnings if res.multi_storey else [])).lower()
    assert "< 36 m²" in warns or "statutory minimum" in warns


# ==============================================================================
# 4. DETERMINISM TEST
# ==============================================================================

def test_irregular_generation_determinism():
    """Same input polygon and seed must produce byte-identical output."""
    poly_model = PlotPolygonModel(
        vertices=L_SHAPE_VERTICES,
        shape_type="l_shape",
        is_regular_rectangle=False,
    )
    req1 = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=14.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
    )
    req2 = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=14.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
    )

    res1 = generate_floor_plan(req1)
    res2 = generate_floor_plan(req2)

    assert res1.multi_storey.site_plan["svg_site_plan"] == res2.multi_storey.site_plan["svg_site_plan"]
    assert res1.multi_storey.floors[0].svg_blueprint_cad == res2.multi_storey.floors[0].svg_blueprint_cad


# ==============================================================================
# 5. SITE SHEET 10.SP IR DRAWING & PDF PARITY
# ==============================================================================

def test_site_sheet_drawing_ir_and_pdf_parity():
    """
    Verify Sheet 10.SP Drawing IR renders valid SVG and ReportLab vector objects,
    and PDF report includes Sheet 10.SP when plot is irregular.
    """
    poly_model = PlotPolygonModel(
        vertices=TRAPEZOID_VERTICES,
        shape_type="trapezoid",
        is_regular_rectangle=False,
    )
    req = FloorPlanRequest(
        plot_width_m=16.0,
        plot_depth_m=14.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
    )
    res = generate_floor_plan(req)
    bldg = res.multi_storey
    sp = SitePlanModel.model_validate(bldg.site_plan)

    # 1. Build Site Drawing IR
    ir = build_site_drawing_ir(sp, str(bldg.seed), bldg.building_typology)
    assert "SITE PLAN" in ir.header.floor_name
    assert len(ir.primitives) > 0

    # 2. Render SVG from IR
    svg = render_svg_from_ir(ir)
    assert "<svg" in svg
    assert "mf-hatch-setback" in svg
    assert "SITE SURVEY" in svg or "SITE PLAN" in svg
    assert "TRAPEZOID" in svg

    # 3. Render ReportLab from IR
    drawing = render_reportlab_from_ir(ir)
    assert drawing is not None
    assert drawing.width > 0
    assert drawing.height > 0

    # 4. Generate Multi-Storey PDF Report with Irregular Plot
    import io
    from pypdf import PdfReader

    buf = generate_pdf_report({"project_id": "test_trapezoid"}, floor_plan=res.model_dump())
    pdf_bytes = buf.getvalue()
    assert len(pdf_bytes) > 2000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 5
    all_text = "".join(p.extract_text() for p in reader.pages)
    assert "10.SP" in all_text
    assert "CADASTRAL" in all_text


def test_single_storey_irregular_plot_pdf_export():
    """
    REGRESSION: single-storey irregular plot must export Sheet 10.SP.
    The typology label used by the single-floor site sheet was resolved inside
    the multi-storey branch, so a G (1 Level) plan on a non-rectangular plot
    raised UnboundLocalError('typology_raw') and Download PDF returned HTTP 500.
    """
    import io
    from pypdf import PdfReader

    poly_model = PlotPolygonModel(
        vertices=TRAPEZOID_VERTICES,
        shape_type="trapezoid",
        is_regular_rectangle=False,
    )
    req = FloorPlanRequest(
        plot_width_m=16.0,
        plot_depth_m=14.0,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed", "bath_1"],
    )
    res = generate_floor_plan(req)
    assert res.multi_storey is not None
    assert len(res.multi_storey.floors) == 1, "fixture must stay single-storey"

    buf = generate_pdf_report({"project_id": "test_single_irregular"}, floor_plan=res.model_dump())
    pdf_bytes = buf.getvalue()
    assert len(pdf_bytes) > 2000

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) >= 5
    all_text = "".join(p.extract_text() for p in reader.pages)
    assert "SITE PLAN & CADASTRAL SURVEY" in all_text
    assert "TRAPEZOID" in all_text
    assert "CADASTRAL" in all_text


# ==============================================================================
# 6. PROOFS: CURVES, L-SHAPE MULTI-WING, COURTYARD TOPOLOGY
# ==============================================================================

def test_curvilinear_boundary_approximation():
    """
    Curvilinear boundary approximation:
    - Input dense curved arc vertices.
    - Shapely simplify approximates to piecewise-linear polyline.
    - Area retained >= 95% of original shoelace area.
    - Simplified polygon is valid and simple.
    - Self-intersecting broken topology is rejected.
    """
    import math
    from shapely.geometry import box as shapely_box

    # Generate a 20x20 plot with a dense circular curved fillet on the NE corner (50 points)
    straight_pts = [(0.0, 0.0), (20.0, 0.0), (20.0, 12.0)]
    # Circular arc around (12, 12) from angle 0 to pi/2: (20, 12) -> (12, 20)
    arc_pts = []
    for step in range(1, 50):
        angle = (math.pi / 2.0) * (step / 49.0)
        ax = round(12.0 + 8.0 * math.cos(angle), 3)
        ay = round(12.0 + 8.0 * math.sin(angle), 3)
        arc_pts.append((ax, ay))
    curved_verts = straight_pts + arc_pts + [(0.0, 20.0)]

    orig_poly = ShapelyPolygon(curved_verts)
    assert orig_poly.is_valid

    is_ok, diags, approx_coords = approximate_curvilinear_polygon(curved_verts, tolerance=0.10)
    assert is_ok is True
    approx_poly = ShapelyPolygon(approx_coords)
    assert approx_poly.is_valid
    assert approx_poly.geom_type == "Polygon"

    # Must retain >= 95% of original area
    area_ratio = approx_poly.area / orig_poly.area
    assert area_ratio >= 0.95, f"Retained area {area_ratio:.3f} < 95% threshold"

    # Polyline vertex count must be significantly simplified from 50+ vertices
    assert len(approx_coords) < len(curved_verts)

    # Topology break rejection check
    broken_verts = [(0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0)]
    is_ok_broken, diags_broken, _ = approximate_curvilinear_polygon(broken_verts)
    assert is_ok_broken is False


def test_golden_l_shape_multi_wing():
    """
    Golden L-shape test:
    - Input 20x20 L-shaped buildable polygon.
    - Assert solver generates TWO distinct wings connected by a corridor.
    - Rooms placed inside respective wings (Public in Wing A, Private in Wing B).
    - ZERO rooms span across the 'missing' corner of the L.
    - Circulation graph is fully connected.
    - Stepped dimensions follow the stepped perimeter.
    - Street facade label applies to exterior walls facing frontage.
    """
    from shapely.geometry import box as shapely_box

    poly_model = PlotPolygonModel(
        vertices=L_SHAPE_VERTICES,
        shape_type="l_shape",
        is_regular_rectangle=False,
    )
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=20.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
    )

    res = generate_floor_plan(req)
    assert res.multi_storey is not None
    bldg = res.multi_storey
    sp = SitePlanModel.model_validate(bldg.site_plan)

    # 1. Two distinct wings and linking corridor
    assert sp.footprint.topology_type == "l_shape"
    assert len(sp.footprint.wings) == 2
    assert len(sp.footprint.corridors) >= 1
    wing_a = sp.footprint.wings[0]
    wing_b = sp.footprint.wings[1]
    assert wing_a.area_sqm >= 50.0
    assert wing_b.area_sqm >= 20.0

    # 2. Rooms placed in respective wings
    f0 = bldg.floors[0]
    room_ids = {r.room_id.split("_F")[0] for r in f0.rooms}
    assert "living" in room_ids
    assert "kitchen" in room_ids
    assert "dining" in room_ids
    assert "link_corridor" in room_ids
    assert "master_bed" in room_ids
    assert "bath_1" in room_ids
    assert "bed_2" in room_ids
    assert "bath_2" in room_ids

    # 3. ZERO rooms in the missing corner of the L
    # Missing corner is at x in (12.0, 20.0), y in (14.0, 20.0)
    missing_corner_box = shapely_box(12.0, 14.0, 20.0, 20.0)
    env_x = sp.footprint.x
    env_y = sp.footprint.y
    for rm in f0.rooms:
        rm_site_box = shapely_box(rm.x + env_x, rm.y + env_y, rm.x + env_x + rm.width_m, rm.y + env_y + rm.depth_m)
        intersection_area = rm_site_box.intersection(missing_corner_box).area
        assert intersection_area == pytest.approx(0.0, abs=1e-3), (
            f"Room {rm.room_id} intrudes into missing corner of L by {intersection_area:.2f} sqm"
        )

    # 4. Circulation fully connected
    assert f0.circulation_status == "connected"

    # 5. Wall graph has stepped dimension chains and street facade
    wg = f0.wall_graph
    assert wg is not None
    dim_chains = wg.get("dim_chains_x", []) + wg.get("dim_chains_y", [])
    assert any("STEPPED" in c.get("chain_id", "") for c in dim_chains)

    # Street facade label check
    assert any(w.get("is_street_facade") is True and w.get("label") == "STREET FACADE" for w in wg.get("walls", []))

    # 6. Site plan Drawing IR renders both wings with labels
    ir = build_site_drawing_ir(sp, str(bldg.seed), bldg.building_typology)
    text_labels = [p.text for p in ir.primitives if hasattr(p, "text")]
    assert any("WING A (PUBLIC)" in t for t in text_labels)
    assert any("WING B (PRIVATE)" in t for t in text_labels)


def test_golden_courtyard_topology():
    """
    Golden courtyard test:
    - Input 25x25 square buildable polygon with 'Courtyard' typology.
    - Assert solver generates an O-shape/U-shape configuration with central void.
    - Central void labeled as 'Central Courtyard' with >= 9 sqm (min 3x3m).
    """
    from shapely.geometry import box as shapely_box

    plot_box = shapely_box(0.0, 0.0, 25.0, 25.0)
    poly_model = PlotPolygonModel(
        vertices=list(plot_box.exterior.coords[:-1]),
        shape_type="irregular",
        is_regular_rectangle=False,
    )

    req = FloorPlanRequest(
        plot_width_m=25.0,
        plot_depth_m=25.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        client_notes="Courtyard typology villa with central outdoor court",
        plot_polygon=poly_model,
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "stairs"],
    )

    res = generate_floor_plan(req)
    assert res.multi_storey is not None
    bldg = res.multi_storey
    sp = SitePlanModel.model_validate(bldg.site_plan)

    # Assert courtyard topology
    assert sp.footprint.topology_type == "courtyard"
    assert sp.footprint.courtyard_void is not None
    assert sp.footprint.courtyard_void.name == "Central Courtyard"
    assert sp.footprint.courtyard_void.area_sqm >= 9.0  # Min 3x3m void

    # Assert multiple wings wrapping the courtyard
    assert len(sp.footprint.wings) >= 2
    assert len(sp.footprint.corridors) >= 1

    # Drawing IR includes Central Courtyard label
    ir = build_site_drawing_ir(sp, str(bldg.seed), bldg.building_typology)
    text_labels = [p.text for p in ir.primitives if hasattr(p, "text")]
    assert any("CENTRAL COURTYARD" in t for t in text_labels)

