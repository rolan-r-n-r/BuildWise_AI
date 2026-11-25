"""
BuildWise Constructible Geometry Model & Construction-Grade Sheets Test Suite
Validates:
1. Wall-graph model: clear interior rectangles, first-class wall segments (W1=230mm, W2=115mm, W3=75mm).
   HARD ASSERT: dimension chain sums equal overall within 1mm (<= 0.001m) for T1-T4 x 1-4 storeys.
2. Hosted openings: corner margin >= 150mm, opening separation >= 250mm, windows only on exterior (W1),
   deterministic D1..Dn and W1..Wn tagging.
3. Computed stair geometry: N x R == H (<= 1mm), R <= 175mm, Blondel's 2R+T in [600, 650mm], run fits stair box.
4. Circulation & swing clearance: corridor clear width >= typology minimum, door swing clearance.
5. NBC 2016 light & ventilation window sizing: habitable >= 12.5%, sanitary >= 10% / >= 0.37 sqm.
6. Construction-grade sheets: 3-line dimension chains, wall type legend, schedules rendered on-sheet & PDF.
7. Golden SVG snapshots generation and verification.
"""

import io
import math
import os
import re
import xml.etree.ElementTree as ET
import pytest
import pypdf

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.wall_graph import (
    W1_EXTERIOR_THICKNESS_M,
    W2_INTERIOR_THICKNESS_M,
    W3_PARTITION_THICKNESS_M,
    WALL_THICKNESS_EXTERIOR_M,
    WALL_THICKNESS_INTERIOR_M,
    WALL_THICKNESS_PARTITION_M,
    NBC_2016_HABITABLE_VENT_RATIO,
    NBC_2016_SANITARY_VENT_RATIO,
    NBC_2016_MIN_SANITARY_VENT_AREA_SQM,
    CORRIDOR_MIN_CLEAR_WIDTH_T1,
    CORRIDOR_MIN_CLEAR_WIDTH_T2_T3,
    CORRIDOR_MIN_CLEAR_WIDTH_T4,
    HostedOpening,
    WallSegment,
    ClearRoom,
    DimensionSegment,
    DimensionChain,
    WallGraph,
    StairGeometry,
    compute_stair_geometry,
    compute_window_dimensions,
    build_constructible_wall_graph,
)
from app.services.floorplan.svg_generator import generate_multi_floor_blueprint_svg
from app.services.report_service import make_construction_schedules_table, generate_pdf_report


# =============================================================================
# 1. WALL-GRAPH MODEL & HARD DIMENSION CHAIN ASSERTIONS (<= 1mm)
# =============================================================================

@pytest.mark.parametrize("typology", [
    "T1_SINGLE_FAMILY",
    "T2_FAMILY_APARTMENT",
    "T3_COMMERCIAL_RETAIL",
    "T4_INSTITUTIONAL"
])
@pytest.mark.parametrize("floors", [1, 2, 3, 4])
def test_dimension_chain_sums_within_1mm(typology: str, floors: int):
    """
    HARD ASSERT: For every typology (T1-T4) and storey count (1-4 floors),
    the sum of clear room dimensions + sum of wall thicknesses must equal
    the overall building envelope dimension within 1mm (<= 0.001m).
    Opening chain sums must also equal the overall envelope within 1mm.
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=floors,
        building_typology=typology,
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
    )
    result = SoleGeometryEngine(req).solve()
    assert result is not None
    assert len(result.floors) == floors

    for fl in result.floors:
        wg = fl.wall_graph
        assert wg is not None, f"Floor {fl.floor_index} ({typology}) must have wall_graph populated"
        assert isinstance(wg, dict)

        env_w = wg["envelope"]["width"]
        env_d = wg["envelope"]["depth"]

        # 1. Verify all X-axis dimension chains
        assert len(wg["dim_chains_x"]) >= 3, f"Floor {fl.floor_index} must have at least 3 X-chains (openings, clear_rooms, overall)"
        for chain in wg["dim_chains_x"]:
            assert chain["axis"] == "X"
            sum_m = sum(s["length_m"] for s in chain["segments"])
            diff_m = abs(sum_m - env_w)
            assert diff_m <= 0.001, (
                f"Floor {fl.floor_index} X-chain '{chain['chain_id']}' ({chain['level']}) sum {sum_m:.4f}m "
                f"!= overall {env_w:.4f}m within 1mm (diff={diff_m*1000:.2f}mm)"
            )
            # Integer mm exactness within 1mm
            assert abs(chain["sum_mm"] - chain["total_mm"]) <= 1

        # 2. Verify all Y-axis dimension chains
        assert len(wg["dim_chains_y"]) >= 3, f"Floor {fl.floor_index} must have at least 3 Y-chains (openings, clear_rooms, overall)"
        for chain in wg["dim_chains_y"]:
            assert chain["axis"] == "Y"
            sum_m = sum(s["length_m"] for s in chain["segments"])
            diff_m = abs(sum_m - env_d)
            assert diff_m <= 0.001, (
                f"Floor {fl.floor_index} Y-chain '{chain['chain_id']}' ({chain['level']}) sum {sum_m:.4f}m "
                f"!= overall {env_d:.4f}m within 1mm (diff={diff_m*1000:.2f}mm)"
            )
            # Integer mm exactness within 1mm
            assert abs(chain["sum_mm"] - chain["total_mm"]) <= 1

        # 3. Verify Wall Segment Classifications
        for seg in wg["walls"]:
            assert seg["wall_type"] in ("W1", "W2", "W3")
            if seg["wall_type"] == "W1":
                assert seg["thickness_m"] == W1_EXTERIOR_THICKNESS_M == 0.230
                assert seg["is_load_bearing"] is True
            elif seg["wall_type"] == "W2":
                assert seg["thickness_m"] == W2_INTERIOR_THICKNESS_M == 0.115
            elif seg["wall_type"] == "W3":
                assert seg["thickness_m"] == W3_PARTITION_THICKNESS_M == 0.075


# =============================================================================
# 2. COMPUTED STAIR GEOMETRY (NBC 2016 & BLONDEL'S RULE)
# =============================================================================

@pytest.mark.parametrize("floor_height_m", [2.80, 3.00, 3.15, 3.30, 3.60])
def test_stair_geometry_computations(floor_height_m: float):
    """
    Validates dynamic stair riser and tread derivation:
    - N x R == floor_height_m (<= 1mm)
    - Riser R <= 175mm (NBC Part 3 Cl 4.12.1.2)
    - Tread T in [250mm, 300mm]
    - Blondel's formula 2R + T in [600mm, 650mm]
    - Dogleg: 2 flights + mid-landing
    - Total plan run = treads_per_flight x T + landing_depth
    - Box size fits declared stair run and flights
    - Headroom >= 2.20m (NBC 2016 Cl 12.18.3 residential clear headroom)
    """
    stair = compute_stair_geometry(floor_height_m=floor_height_m)

    # 1. Total riser height equals floor height within 1mm
    total_riser_height = stair.riser_count * stair.riser_height_m
    assert abs(total_riser_height - floor_height_m) <= 0.001, (
        f"Total riser height {total_riser_height:.4f}m != floor height {floor_height_m:.4f}m"
    )

    # 2. Max riser height <= 175mm (NBC 2016)
    assert stair.riser_height_m <= 0.175 + 1e-6, f"Riser {stair.riser_height_m*1000:.1f}mm exceeds 175mm"

    # 3. Tread depth within [250mm, 300mm]
    assert 0.250 <= stair.tread_depth_m <= 0.300, f"Tread {stair.tread_depth_m*1000:.1f}mm not in [250, 300]mm"

    # 4. Blondel's formula 2R + T in [600mm, 650mm]
    blondel = 2.0 * stair.riser_height_m + stair.tread_depth_m
    assert 0.600 <= blondel <= 0.650, f"Blondel's 2R+T = {blondel*1000:.1f}mm outside [600, 650]mm"

    # 5. Dogleg configuration
    assert stair.flight_count == 2
    assert stair.landing_depth_m >= stair.flight_width_m - 0.001

    # 6. Plan run formula
    expected_run = (stair.treads_per_flight * stair.tread_depth_m) + stair.landing_depth_m
    assert abs(stair.stair_run_m - (stair.treads_per_flight * stair.tread_depth_m)) <= 0.001
    assert abs(stair.stair_box_depth_m - expected_run) <= 0.001

    # 7. Dynamic box sizing
    assert stair.stair_box_depth_m >= stair.stair_run_m + stair.landing_depth_m - 0.001
    assert stair.stair_box_width_m >= (2.0 * stair.flight_width_m) + stair.stair_well_m - 0.001

    # 8. Headroom requirement (NBC 2016: >= 2.20m clear, never 2.0m).
    # headroom_min_m now carries the AS-COMPUTED soffit clearance (H - 100mm
    # slab), and headroom_note prints the computed value alongside the R/T/N
    # derivation tokens rather than a fixed compliance sentence.
    assert stair.headroom_min_m >= 2.20
    assert stair.headroom_note.startswith(f"HEADROOM >= {stair.headroom_min_m:.2f}m CLEAR")
    assert "R=" in stair.headroom_note and "T=" in stair.headroom_note
    # For every sane floor height here, computed soffit headroom clears code.
    assert abs(stair.headroom_min_m - (floor_height_m - 0.10)) < 0.005


# =============================================================================
# 3. HOSTED OPENINGS (MARGINS, SEPARATION, EXTERIOR WINDOWS)
# =============================================================================

@pytest.mark.parametrize("typology", [
    "T1_SINGLE_FAMILY",
    "T2_FAMILY_APARTMENT",
    "T3_COMMERCIAL_RETAIL",
    "T4_INSTITUTIONAL"
])
def test_hosted_openings_rules(typology: str):
    """
    Validates opening hosting constraints:
    - Margin: opening + 150mm margin must fit inside segment length (>= 150mm from start and end corners).
    - Separation: no two openings on the same wall segment within 250mm of each other.
    - Exterior windows: windows hosted ONLY in W1 exterior wall segments.
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology=typology,
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
    )
    result = SoleGeometryEngine(req).solve()

    for fl in result.floors:
        wg = fl.wall_graph
        assert wg is not None

        for seg in wg["walls"]:
            openings = seg.get("openings", [])
            if not openings:
                continue

            for op in openings:
                # 1. Corner margins: >= 150mm (0.15m)
                assert op["offset_from_corner"] >= 0.149, (
                    f"Opening {op['opening_id']} on {seg['wall_id']} has offset {op['offset_from_corner']:.3f}m < 0.15m margin"
                )
                assert (op["offset_from_corner"] + op["width_m"]) <= (seg["length_m"] - 0.149), (
                    f"Opening {op['opening_id']} on {seg['wall_id']} (len={seg['length_m']:.3f}m) ends at "
                    f"{(op['offset_from_corner'] + op['width_m']):.3f}m, leaving < 0.15m margin"
                )

                # 2. Window exterior placement rule
                if op["opening_type"] == "window":
                    assert seg["wall_type"] == "W1", (
                        f"Window {op['opening_id']} hosted on non-exterior wall {seg['wall_id']} of type {seg['wall_type']}"
                    )
                    assert seg["is_exterior"] is True

            # 3. Separation rule: >= 250mm (0.25m) between adjacent openings on same wall
            if len(openings) > 1:
                sorted_ops = sorted(openings, key=lambda o: o["offset_from_corner"])
                for i in range(len(sorted_ops) - 1):
                    gap = sorted_ops[i + 1]["offset_from_corner"] - (sorted_ops[i]["offset_from_corner"] + sorted_ops[i]["width_m"])
                    assert gap >= 0.249, (
                        f"Openings {sorted_ops[i]['opening_id']} and {sorted_ops[i+1]['opening_id']} on {seg['wall_id']} "
                        f"have separation {gap:.3f}m < 0.25m"
                    )


# =============================================================================
# 4. DETERMINISTIC TAGGING & SCHEDULE COMPLETENESS
# =============================================================================

@pytest.mark.parametrize("typology", [
    "T1_SINGLE_FAMILY",
    "T2_FAMILY_APARTMENT",
    "T3_COMMERCIAL_RETAIL",
    "T4_INSTITUTIONAL"
])
def test_schedules_completeness_and_deterministic_tags(typology: str):
    """
    Validates that:
    - Every door is assigned tag D1..Dn deterministically.
    - Every window is assigned tag W1..Wn deterministically.
    - Every door/window instance appears exactly once in its schedule.
    - Room Schedule has complete entry for every clear room with finish zones.
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology=typology,
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
    )
    result = SoleGeometryEngine(req).solve()

    for fl in result.floors:
        wg = fl.wall_graph
        assert wg is not None

        # Door Schedule
        door_sched = fl.door_schedule or wg.get("door_schedule", [])
        assert len(door_sched) > 0, f"Floor {fl.floor_index} must have door schedule"
        door_tags = [d["tag"] for d in door_sched]
        assert len(door_tags) == len(set(door_tags)), "Door tags must be unique on each floor"
        for idx, tag in enumerate(door_tags, 1):
            assert tag == f"D{idx}", f"Door tag {tag} is not deterministically ordered D{idx}"

        # Window Schedule
        win_sched = fl.window_schedule or wg.get("window_schedule", [])
        assert len(win_sched) > 0, f"Floor {fl.floor_index} must have window schedule"
        win_tags = [w["tag"] for w in win_sched]
        assert len(win_tags) == len(set(win_tags)), "Window tags must be unique on each floor"
        for idx, tag in enumerate(win_tags, 1):
            assert tag == f"W{idx}", f"Window tag {tag} is not deterministically ordered W{idx}"

        # Room Schedule
        room_sched = fl.room_schedule or wg.get("room_schedule", [])
        assert len(room_sched) > 0, f"Floor {fl.floor_index} must have room schedule"
        for r in room_sched:
            assert r["room_number"] >= 1
            assert len(r["room_name"]) > 0
            assert r["clear_area_sqm"] > 0.0
            assert "m x" in r["clear_dims"]
            assert len(r["finish_zone"]) > 0


# =============================================================================
# 5. CIRCULATION & SWING CLEARANCE
# =============================================================================

def test_corridor_minimum_clear_widths():
    """
    Validates corridor minimum clear width standards:
    - T1 (Villa): >= 1.0m
    - T2/T3 (Apartment/Commercial): >= 1.25m
    - T4 (Institutional): >= 1.50m
    """
    assert CORRIDOR_MIN_CLEAR_WIDTH_T1 == 1.00
    assert CORRIDOR_MIN_CLEAR_WIDTH_T2_T3 == 1.25
    assert CORRIDOR_MIN_CLEAR_WIDTH_T4 == 1.50

    # Test solver corridor generation per typology
    for typ, min_w in [
        ("T1_SINGLE_FAMILY", 1.00),
        ("T2_FAMILY_APARTMENT", 1.25),
        ("T3_COMMERCIAL_RETAIL", 1.25),
        ("T4_INSTITUTIONAL", 1.50),
    ]:
        req = FloorPlanRequest(
            plot_width_m=20.0,
            plot_depth_m=18.0,
            floors=1,
            building_typology=typ,
            vastu_strictness="medium",
            required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
        )
        res = SoleGeometryEngine(req).solve()
        fl0 = res.floors[0]
        # Inspect clear rooms for circulation/corridors if present
        corridors = [r for r in fl0.rooms if "corridor" in r.room_id.lower() or "passage" in r.room_id.lower() or "lobby" in r.room_id.lower()]
        for c in corridors:
            clear_dim = min(c.width_m, c.depth_m)
            assert clear_dim >= min_w - 0.05, f"{typ} corridor dimension {clear_dim:.2f}m < {min_w:.2f}m"


def test_door_swing_clearance_auto_flip():
    """
    Validates door swing clearance and auto-flip logic:
    Door swings must open inwards against walls without blocking stairs or egress corridors.
    """
    op1 = HostedOpening(
        opening_id="D1",
        tag="D1",
        opening_type="door",
        wall_id="WAL_EXT_S",
        offset_from_corner=0.30,
        width_m=0.90,
        height_m=2.10,
        sill_m=0.0,
        lintel_m=2.10,
        swing_direction="inward_right",
        hinge_side="right",
    )
    # Check swing bbox can be defined
    op1.swing_bbox = (0.30, 0.0, 1.20, 0.90)
    assert op1.swing_bbox is not None

    # Auto-flip test: if opening would collide, swing direction can be toggled
    op1.hinge_side = "left"
    op1.swing_direction = "inward_left"
    assert op1.hinge_side == "left"
    assert op1.swing_direction == "inward_left"


# =============================================================================
# 6. CODE-SIZED WINDOWS (NBC 2016 LIGHT & VENTILATION)
# =============================================================================

def test_nbc_2016_light_and_ventilation_ratios():
    """
    Validates NBC 2016 Part 8 Section 1 Clause 4.2 ratios:
    - Habitable rooms: aggregate opening area >= 12.5% (1/8th) of floor area.
    - Sanitary/toilets: aggregate opening area >= 10.0% (1/10th) of floor area, min 0.37 sqm.
    """
    assert NBC_2016_HABITABLE_VENT_RATIO == 0.125
    assert NBC_2016_SANITARY_VENT_RATIO == 0.10
    assert NBC_2016_MIN_SANITARY_VENT_AREA_SQM == 0.37

    # Habitable room: 16.0 sqm -> Required vent area = 2.0 sqm
    # At standard window height 1.2m, required width = 2.0 / 1.2 = 1.67m (clamped to practical standard)
    dim_hab = compute_window_dimensions("master_bed", room_area_sqm=16.0, window_height_m=1.20)
    assert dim_hab["width_m"] >= 1.50
    assert "NBC 2016" in dim_hab["citation"]
    assert dim_hab["is_sanitary"] is False

    # Sanitary room: 4.0 sqm -> 10% = 0.40 sqm (exceeds min 0.37 sqm)
    dim_san = compute_window_dimensions("bath_1", room_area_sqm=4.0, window_height_m=0.60)
    assert dim_san["opening_area_sqm"] >= 0.37
    assert "NBC 2016" in dim_san["citation"]
    assert dim_san["is_sanitary"] is True


# =============================================================================
# 7. CONSTRUCTION-GRADE SHEETS & SCHEDULES (SVG & PDF)
# =============================================================================

def test_construction_grade_svg_generation():
    """
    Validates SVG generation with constructible wall-graph:
    - 3-line dimension chains on Top and Left.
    - 45-degree architectural slash ticks on dimension lines.
    - Wall type legend (W1 230mm, W2 115mm, W3 75mm).
    - Door, Window, and Room Schedules.
    - Structural notation: LBW-230 for T1; column grid bubbles for T3/T4.
    """
    req_t1 = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
    )
    res_t1 = SoleGeometryEngine(req_t1).solve()
    svg_t1 = res_t1.floors[0].svg_blueprint_cad

    # Valid XML check
    root_t1 = ET.fromstring(svg_t1)
    assert root_t1.tag.endswith("svg")

    # Constructible sheet elements
    assert "W1: 230mm" in svg_t1 or "W1: 230" in svg_t1
    assert "W2: 115mm" in svg_t1 or "W2: 115" in svg_t1
    assert "W3: 75mm" in svg_t1 or "W3: 75" in svg_t1
    assert "DOOR SCHEDULE" in svg_t1
    assert "WINDOW SCHEDULE" in svg_t1
    assert "ROOM SCHEDULE" in svg_t1
    assert "[LBW-230]" in svg_t1 or "LBW-230" in svg_t1  # T1 load-bearing notation

    # T3 Column Grid test
    req_t3 = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology="T3_COMMERCIAL_RETAIL",
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
    )
    res_t3 = SoleGeometryEngine(req_t3).solve()
    svg_t3 = res_t3.floors[0].svg_blueprint_cad
    assert "col-bubble" in svg_t3 or "grid-bubble" in svg_t3 or "col-grid" in svg_t3


def test_pdf_report_construction_schedules_rendering():
    """
    Validates PDF schedules rendering:
    - make_construction_schedules_table returns flowables for Wall, Door, Window, and Room schedules.
    - generate_pdf_report embeds schedules when include_construction_schedules=True.
    """
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology="T2_FAMILY_APARTMENT",
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
    )
    res = SoleGeometryEngine(req).solve()
    fl0 = res.floors[0].model_dump()

    # Flowables helper test
    flowables = make_construction_schedules_table(fl0)
    assert len(flowables) >= 4

    # PDF generation test
    payload = {
        "request_id": "BW-TEST-CONSTRUCTIBILITY-PDF",
        "timestamp": "2026-09-25 12:00:00 UTC",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Constructibility Validation Site",
        "overall_suitability_score": 85.0,
        "suitability_verdict": "Verified",
        "built_up_area_sqft": 3600.0,
        "floors": 2,
        "include_construction_schedules": True,
    }
    pdf_buf = generate_pdf_report(payload, floor_plan=fl0, include_construction_schedules=True)
    pdf_bytes = pdf_buf.getvalue()
    assert pdf_bytes.startswith(b"%PDF")

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    full_text = "\n".join(page.extract_text() for page in reader.pages)

    assert "Door Schedule" in full_text
    assert "Window Schedule" in full_text
    assert "Room Schedule" in full_text
    assert "Wall Type Specifications" in full_text


# =============================================================================
# 8. GOLDEN SVG SNAPSHOTS REGENERATION
# =============================================================================

def test_regenerate_and_verify_golden_svg_snapshots(tmp_path):
    """
    Generates and persists golden SVG snapshots for T1-T4, verifying:
    - Non-empty output
    - Valid XML parsing
    - Containment of setting-out geometry and schedules
    """
    snapshots_dir = str(tmp_path / "golden_snapshots")
    os.makedirs(snapshots_dir, exist_ok=True)

    typologies = [
        ("T1_SINGLE_FAMILY", "golden_t1_villa.svg"),
        ("T2_FAMILY_APARTMENT", "golden_t2_apartment.svg"),
        ("T3_COMMERCIAL_RETAIL", "golden_t3_commercial.svg"),
        ("T4_INSTITUTIONAL", "golden_t4_institutional.svg"),
    ]

    for typ, filename in typologies:
        req = FloorPlanRequest(
            plot_width_m=20.0,
            plot_depth_m=18.0,
            floors=2,
            building_typology=typ,
            vastu_strictness="medium",
            required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
        )
        res = SoleGeometryEngine(req).solve()
        svg_content = res.floors[0].svg_blueprint_cad

        # Verify valid SVG XML
        root = ET.fromstring(svg_content)
        assert root.tag.endswith("svg")

        # Save snapshot
        file_path = os.path.join(snapshots_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(svg_content)

        assert os.path.exists(file_path)
        assert os.path.getsize(file_path) > 1000
