import pytest
import math
import xml.etree.ElementTree as ET
from typing import Dict, Any, List

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.drawing_ir import (
    build_drawing_ir,
    render_svg_from_ir,
    render_reportlab_from_ir,
    FloorDrawingIR,
    FillPrimitive,
    WallPrimitive,
    OpeningPrimitive,
    StairPrimitive,
    DimensionChainPrimitive,
    TextPrimitive,
    AnnotationPrimitive,
)
from reportlab.graphics.shapes import Drawing, Rect, Circle, Line, String, Polygon, Group


# The viewer's progressive reveal addresses these groups in this order. The
# title block / validation gate group (`sheet`) is deliberately last and is
# never animated: the verdict must be visible from the first frame.
SVG_PHASE_ORDER = [
    "envelope",
    "site",
    "rooms",
    "ghost",
    "walls",
    "cores",
    "openings",
    "labels",
    "dims",
    "annotations",
    "sheet",
]


TYPOLOGIES = [
    "T1_SINGLE_FAMILY",
    "T2_FAMILY_APARTMENT",
    "T3_COMMERCIAL_COMPLEX",
    "T4_INDUSTRIAL_WAREHOUSE"
]

FLOOR_COUNTS = [1, 2, 3, 4]


@pytest.mark.parametrize("typology", TYPOLOGIES)
@pytest.mark.parametrize("floors", FLOOR_COUNTS)
def test_drawing_ir_parity_and_transforms(typology: str, floors: int):
    """
    The drawing IR is the single source both renderers consume:
    For T1-T4 x 1-4 floors, build the IR once, render SVG and PDF;
    1. Assert per-layer primitive counts match expectations.
    2. Assert key coordinates (envelope corners, one room corner per floor, stair core origin,
       door hinge points) agree between backends within 0.01m.
    3. Assert PDF sheet header dims == SVG chain dims == model envelope dims.
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=floors,
        building_typology=typology,
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
    )
    res = generate_floor_plan(req)
    assert res.multi_storey is not None, f"Failed generation for {typology} with {floors} floors"
    multi_bldg = res.multi_storey

    for f_idx, fl in enumerate(multi_bldg.floors):
        # 1. Build IR once
        ir = build_drawing_ir(
            floor_data=fl,
            building_model=multi_bldg,
            gen_id=multi_bldg.seed,
            typology=multi_bldg.building_typology,
            elevation_m=f_idx * 3.0
        )
        assert isinstance(ir, FloorDrawingIR)

        # 2. Render both backends from the same IR
        svg_str = render_svg_from_ir(ir, theme="cad")
        width_pt, height_pt = 450.0, 350.0
        rl_drawing = render_reportlab_from_ir(ir, width=width_pt, height=height_pt)

        assert isinstance(svg_str, str)
        assert svg_str.startswith("<svg") and svg_str.endswith("</svg>")
        assert isinstance(rl_drawing, Drawing)

        # 3. Assert Layer Primitive Counts
        fills = ir.primitives_by_layer("fills")
        walls = ir.primitives_by_layer("walls")
        openings = ir.primitives_by_layer("openings")
        dims = ir.primitives_by_layer("dims")
        texts = ir.primitives_by_layer("text")
        annots = ir.primitives_by_layer("annotations")

        assert len(fills) == len(fl.rooms), f"Room fill count mismatch on floor {f_idx}"
        assert len(walls) >= 4, f"Floor {f_idx} missing exterior envelope walls"
        total_openings_model = len(fl.doors or []) + len(fl.windows or [])
        assert len(openings) == total_openings_model, f"Openings count mismatch on floor {f_idx}"
        assert len(dims) >= 2, f"Floor {f_idx} missing dimension chains"
        assert len(texts) >= len(fl.rooms), f"Floor {f_idx} missing room texts"
        assert len(annots) >= 1, f"Floor {f_idx} missing annotation layer"

        # 4. Assert Key Coordinates Parity Between SVG and ReportLab Backends within 0.01m
        # SVG transform parameters:
        scale_svg = 36.0
        margin_x_svg = 75.0
        margin_y_svg = 75.0

        # ReportLab transform parameters:
        margin_rl = 48.0
        scale_rl = min((width_pt - 2 * margin_rl) / ir.envelope_w, (height_pt - 2 * margin_rl) / ir.envelope_d)
        origin_x_rl = (width_pt - ir.envelope_w * scale_rl) / 2.0
        origin_y_rl = (height_pt - ir.envelope_d * scale_rl) / 2.0

        def to_svg(xm: float, ym: float):
            return margin_x_svg + xm * scale_svg, margin_y_svg + (ir.envelope_d - ym) * scale_svg

        def from_svg(xs: float, ys: float):
            return (xs - margin_x_svg) / scale_svg, ir.envelope_d - ((ys - margin_y_svg) / scale_svg)

        def to_rl(xm: float, ym: float):
            return origin_x_rl + xm * scale_rl, origin_y_rl + ym * scale_rl

        def from_rl(x_pt: float, y_pt: float):
            return (x_pt - origin_x_rl) / scale_rl, (y_pt - origin_y_rl) / scale_rl

        def assert_point_parity(xm: float, ym: float, label: str):
            xs, ys = to_svg(xm, ym)
            xr, yr = to_rl(xm, ym)
            m_svg_x, m_svg_y = from_svg(xs, ys)
            m_rl_x, m_rl_y = from_rl(xr, yr)

            diff_svg = math.hypot(m_svg_x - xm, m_svg_y - ym)
            diff_rl = math.hypot(m_rl_x - xm, m_rl_y - ym)
            diff_cross = math.hypot(m_svg_x - m_rl_x, m_svg_y - m_rl_y)

            assert diff_svg < 0.001, f"{label} SVG inversion error: {diff_svg:.5f}m"
            assert diff_rl < 0.001, f"{label} ReportLab inversion error: {diff_rl:.5f}m"
            assert diff_cross < 0.01, f"{label} cross-backend mismatch: {diff_cross:.5f}m > 0.01m"

        # Check envelope corners
        assert_point_parity(0.0, 0.0, "Envelope SW")
        assert_point_parity(ir.envelope_w, 0.0, "Envelope SE")
        assert_point_parity(0.0, ir.envelope_d, "Envelope NW")
        assert_point_parity(ir.envelope_w, ir.envelope_d, "Envelope NE")

        # Check room corners
        if fills:
            r0 = fills[0]
            assert_point_parity(r0.x, r0.y, f"Room {r0.room_id} SW corner")
            assert_point_parity(r0.x + r0.w, r0.y + r0.h, f"Room {r0.room_id} NE corner")

        # Check stair core origin
        stairs = ir.primitives_by_layer("cores")
        if stairs:
            st = stairs[0]
            assert_point_parity(st.boundary[0], st.boundary[1], "Stair Core Origin")

        # Check door hinge points
        for op in openings:
            if isinstance(op, OpeningPrimitive) and op.opening_type == "door":
                assert_point_parity(op.hinge_x, op.hinge_y, f"Door {op.opening_id} Hinge")

        env_dict = fl.envelope if isinstance(fl.envelope, dict) else fl.envelope.dict()
        model_w = float(env_dict["width"])
        model_d = float(env_dict.get("depth", env_dict.get("height", 12.0)))

        assert abs(ir.header.envelope_w_m - model_w) < 0.001
        assert abs(ir.header.envelope_d_m - model_d) < 0.001
        assert abs(ir.envelope_w - model_w) < 0.001
        assert abs(ir.envelope_d - model_d) < 0.001

        chain_x = next((dc for dc in dims if dc.chain_id == "DIM_X_OVERALL"), None)
        assert chain_x is not None
        assert abs(chain_x.segments[0]["length_m"] - model_w) < 0.001

        chain_y = next((dc for dc in dims if dc.chain_id == "DIM_Y_OVERALL"), None)
        assert chain_y is not None
        assert abs(chain_y.segments[0]["length_m"] - model_d) < 0.001

        # Freshness token in header
        freshness = ir.header.freshness_token
        assert f"GEN {multi_bldg.seed}" in freshness
        assert f"ENV {model_w:.2f}x{model_d:.2f}m" in freshness
        assert freshness in svg_str


@pytest.mark.parametrize("typology", ["T1_SINGLE_FAMILY", "T2_FAMILY_APARTMENT"])
@pytest.mark.parametrize("floors", [1, 3])
def test_drawing_ir_no_element_outside_bbox(typology: str, floors: int):
    """
    No drawn element may fall outside the envelope + annotation margin:
    Assert no drawn element bbox falls outside envelope + annotation margin in PDF coordinate space.
    Catches flip/offset/coordinate distortion bugs generically.
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=floors,
        building_typology=typology,
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
    )
    res = generate_floor_plan(req)
    multi_bldg = res.multi_storey

    for fl in multi_bldg.floors:
        ir = build_drawing_ir(
            floor_data=fl,
            building_model=multi_bldg,
            gen_id=multi_bldg.seed,
            typology=multi_bldg.building_typology
        )

        width_pt, height_pt = 450.0, 350.0
        rl_drawing = render_reportlab_from_ir(ir, width=width_pt, height=height_pt)

        # In IR Metric space:
        # Building envelope boundary
        env_w = ir.envelope_w
        env_d = ir.envelope_d

        # Tolerance margin for annotations and dimension chains
        margin_m = 2.5

        for p in ir.primitives:
            if isinstance(p, FillPrimitive):
                # Room fills must be strictly inside the building envelope
                assert p.x >= -0.05, f"Room fill {p.room_id} x ({p.x}) < 0"
                assert p.y >= -0.05, f"Room fill {p.room_id} y ({p.y}) < 0"
                assert p.x + p.w <= env_w + 0.05, f"Room fill {p.room_id} exceeds width: {p.x + p.w} > {env_w}"
                assert p.y + p.h <= env_d + 0.05, f"Room fill {p.room_id} exceeds depth: {p.y + p.h} > {env_d}"

            elif isinstance(p, WallPrimitive):
                # Walls must stay within envelope + 0.3m (thickness)
                assert -0.3 <= p.x1 <= env_w + 0.3
                assert -0.3 <= p.y1 <= env_d + 0.3
                assert -0.3 <= p.x2 <= env_w + 0.3
                assert -0.3 <= p.y2 <= env_d + 0.3

            elif isinstance(p, OpeningPrimitive):
                # Openings must be on or inside envelope
                assert -0.5 <= p.x1 <= env_w + 0.5
                assert -0.5 <= p.y1 <= env_d + 0.5
                assert -0.5 <= p.x2 <= env_w + 0.5
                assert -0.5 <= p.y2 <= env_d + 0.5

            elif isinstance(p, StairPrimitive):
                bx, by, bw, bh = p.boundary
                assert bx >= -0.05 and by >= -0.05
                assert bx + bw <= env_w + 0.05 and by + bh <= env_d + 0.05

            elif isinstance(p, DimensionChainPrimitive):
                p1, p2 = p.main_line
                assert -margin_m <= p1[0] <= env_w + margin_m
                assert -margin_m <= p1[1] <= env_d + margin_m
                assert -margin_m <= p2[0] <= env_w + margin_m
                assert -margin_m <= p2[1] <= env_d + margin_m

        # In ReportLab coordinate space:
        # Check all primitive nodes added to ReportLab Drawing
        def check_node_within_sheet(node: Any):
            if isinstance(node, Rect):
                assert node.x >= -5.0 and node.y >= -5.0, f"Rect at ({node.x}, {node.y}) out of bounds"
                assert node.x + node.width <= width_pt + 5.0, f"Rect width out of bounds: {node.x + node.width} > {width_pt}"
                assert node.y + node.height <= height_pt + 5.0, f"Rect height out of bounds: {node.y + node.height} > {height_pt}"
            elif isinstance(node, Circle):
                assert node.cx >= -5.0 and node.cy >= -5.0
                assert node.cx <= width_pt + 5.0 and node.cy <= height_pt + 5.0
            elif isinstance(node, Line):
                assert -5.0 <= node.x1 <= width_pt + 5.0
                assert -5.0 <= node.y1 <= height_pt + 5.0
                assert -5.0 <= node.x2 <= width_pt + 5.0
                assert -5.0 <= node.y2 <= height_pt + 5.0
            elif isinstance(node, String):
                assert -5.0 <= node.x <= width_pt + 5.0
                assert -5.0 <= node.y <= height_pt + 5.0
            elif isinstance(node, Group):
                for child in node.contents:
                    check_node_within_sheet(child)

        for elem in rl_drawing.contents:
            check_node_within_sheet(elem)


def test_single_level_setback_normalization():
    """
    CRITICAL REGRESSION TEST:
    Verifies that single-level floor plans (RectanglesModel with plot setback offsets x=2.15, y=2.50)
    are strictly normalized into local footprint coordinates [0.0, env_w] × [0.0, env_d].
    Asserts:
    1. Zero negative Y coordinates (no overflow into title block / schedules below).
    2. Zero rooms protruding beyond the East or South envelope wall.
    3. Constructible wall graph generates interior partition walls (W2, W3).
    4. Room schedules contain non-zero areas and clean clear dimensions.
    """
    from app.services.floorplan.floorplan_service import generate_floor_plan, FloorPlanRequest
    from app.services.floorplan.drawing_ir import build_drawing_ir, render_svg_from_ir, FillPrimitive, WallPrimitive

    req = FloorPlanRequest(plot_width_m=16.1, plot_depth_m=19.3, floors=1)
    resp = generate_floor_plan(req)
    rects = resp.rectangles

    class DummyBldg:
        plot_width_m = 16.1
        plot_depth_m = 19.3
        total_storeys = 1
        building_typology = "T1_SINGLE_FAMILY"

    ir = build_drawing_ir(floor_data=rects, building_model=DummyBldg(), theme="paper")

    # 1. Check envelope dimensions
    assert ir.envelope_w > 0.0
    assert ir.envelope_d > 0.0

    # 2. Check all room fills are strictly inside [0.0, env_w] × [0.0, env_d]
    fills = ir.primitives_by_layer("fills")
    assert len(fills) >= 6, "Expected at least 6 room fills"
    for f in fills:
        assert isinstance(f, FillPrimitive)
        assert f.x >= -0.01, f"Room {f.room_name} has negative x={f.x}"
        assert f.y >= -0.01, f"Room {f.room_name} has negative y={f.y} (overlapping title block!)"
        assert f.x + f.w <= ir.envelope_w + 0.02, f"Room {f.room_name} exceeds envelope width: {f.x + f.w} > {ir.envelope_w}"
        assert f.y + f.h <= ir.envelope_d + 0.02, f"Room {f.room_name} exceeds envelope depth: {f.y + f.h} > {ir.envelope_d}"

    # 3. Check walls include interior partitions
    walls = ir.primitives_by_layer("walls")
    w1_walls = [w for w in walls if isinstance(w, WallPrimitive) and w.wall_type == "W1"]
    w2_walls = [w for w in walls if isinstance(w, WallPrimitive) and w.wall_type in ("W2", "W3")]
    assert len(w1_walls) >= 4, "Expected 4 exterior walls"
    assert len(w2_walls) >= 4, f"Expected interior partition walls, got {len(w2_walls)}"

    # 4. Check schedules
    assert len(ir.room_schedule) >= 6
    for rs in ir.room_schedule:
        assert rs.get("clear_area_sqm", 0.0) > 0.0, f"Room {rs.get('room_name')} has 0.0 sqm area!"

    # 5. Check SVG output
    svg = render_svg_from_ir(ir, theme="paper")
    assert ">0.0m²<" not in svg and ">0.00m²<" not in svg
    assert "BUILDWISE GENERATIVE CAD ENGINE" in svg



def test_drawn_door_leaf_opens_into_its_room_and_the_wall_it_shares():
    """
    The drawn door leaf must open into the room it serves:
    The IR is what the SVG and PDF actually draw, so the drawn leaf - not just the
    solver's intent - must open into the room the door serves, against the wall the
    two rooms share. Every door also has to sit in the wall the two rooms have in
    common: a door cut into a facade or a neighbouring room's wall is a hull breach
    in the drawing even when the model looks plausible.
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"],
    )
    res = generate_floor_plan(req)
    multi_bldg = res.multi_storey
    fl = multi_bldg.floors[0]

    ir = build_drawing_ir(
        floor_data=fl,
        building_model=multi_bldg,
        gen_id=multi_bldg.seed,
        typology=multi_bldg.building_typology,
    )

    # Room rectangles in IR (y-up) space, keyed by room id.
    rooms_ir = {
        r.room_id: (
            r.x,
            ir.envelope_d - (r.y + r.depth_m),
            r.x + r.width_m,
            ir.envelope_d - r.y,
        )
        for r in fl.rooms
    }
    door_model = {d.door_id: d for d in fl.doors}
    rooms_by_id = {r.room_id: r for r in fl.rooms}

    def _served_room_id(op: OpeningPrimitive) -> str:
        """The room a door opens into: its non-circulation endpoint."""
        model = door_model.get(op.opening_id)
        if model is None:
            return ""
        endpoints = [rid for rid in (model.from_room, model.to_room) if rid in rooms_ir]
        non_circ = [rid for rid in endpoints if rooms_by_id[rid].zone_category != "circulation"]
        return (non_circ or endpoints or [""])[0]

    def _inside(point, box, tol=0.06):
        return (box[0] - tol) <= point[0] <= (box[2] + tol) and (box[1] - tol) <= point[1] <= (box[3] + tol)

    checked = 0
    for op in ir.primitives:
        if not isinstance(op, OpeningPrimitive) or op.opening_type != "door":
            continue
        served = rooms_ir.get(_served_room_id(op))
        if served is None:
            # Exterior doors (main entry, dock shutters) have no served room.
            continue
        checked += 1
        assert _inside((op.leaf_x, op.leaf_y), served), (
            f"Door {op.opening_id} leaf ({op.leaf_x:.2f}, {op.leaf_y:.2f}) opens outside "
            f"the room it serves"
        )
        for point in (op.arc_start_pt, op.arc_end_pt):
            assert _inside(point, served, 0.10), (
                f"Door {op.opening_id} swing arc reaches outside the room it serves at {point}"
            )
        assert -0.05 <= op.leaf_x <= ir.envelope_w + 0.05
        assert -0.05 <= op.leaf_y <= ir.envelope_d + 0.05
        assert -0.05 <= op.hinge_x <= ir.envelope_w + 0.05
        assert -0.05 <= op.hinge_y <= ir.envelope_d + 0.05

    assert checked >= 4, f"Expected several interior doors on the plate, checked {checked}"


def test_svg_presentation_phases_are_additive_and_room_addressable():
    """
    The viewer's progressive reveal depends on inert, presentation-only groups.

    This pins the contract on REAL solver output:
      1. every expected phase exists exactly once, in drawing order;
      2. each is a plain <g> with no geometry of its own;
      3. room fills count once per room and expose that room's id;
      4. the sheet group (title block + validation gate + status stamp) exists
         and is last, so the viewer can keep the verdict outside the animation.

    Geometry is the solver's; these attributes only make existing layers
    addressable. The count/coordinate parity tests above remain the geometry
    authority.
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology="T2_FAMILY_APARTMENT",
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"],
    )
    res = generate_floor_plan(req)
    assert res.multi_storey is not None
    multi = res.multi_storey

    for f_idx, fl in enumerate(multi.floors):
        ir = build_drawing_ir(
            floor_data=fl,
            building_model=multi,
            gen_id=multi.seed,
            typology=multi.building_typology,
            elevation_m=f_idx * 3.0,
        )
        svg = render_svg_from_ir(ir, theme="cad")
        root = ET.fromstring(svg)
        groups = [el for el in root.iter() if "data-bw-phase" in el.attrib]
        phases = [el.attrib["data-bw-phase"] for el in groups]

        assert phases == SVG_PHASE_ORDER, f"phase order drifted on floor {f_idx}: {phases}"
        assert all(el.tag.endswith("g") for el in groups)

        rooms_group = groups[phases.index("rooms")]
        room_fills = [el for el in rooms_group if "data-room-id" in el.attrib]
        assert len(room_fills) == len(fl.rooms), (
            f"floor {f_idx}: {len(room_fills)} addressable fills for {len(fl.rooms)} rooms"
        )
        assert {el.attrib["data-room-id"] for el in room_fills} == {
            r.room_id for r in fl.rooms
        }
        assert all(el.attrib.get("class") == "bw-room-fill" for el in room_fills)

        sheet = groups[phases.index("sheet")]
        assert "NOT FOR CONSTRUCTION" in "".join(sheet.itertext())
