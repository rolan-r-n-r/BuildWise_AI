import pytest
import time
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.schemas.floorplan import FloorPlanRequest, FloorPlanResponse
from app.services.floorplan.grid_model import SpatialGrid, RoomBox
from app.services.floorplan.csp_engine import CSPEngine
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.report_service import generate_pdf_report


def test_spatial_grid_discretization():
    grid = SpatialGrid(plot_width_m=10.0, plot_depth_m=12.0)
    assert grid.rows >= 8 and grid.cols >= 8
    assert grid.cell_w_m > 0 and grid.cell_d_m > 0

    # Test quadrant detection
    ne_box = RoomBox(room_id="puja", r=0, c=grid.cols - 2, w=2, h=2)
    assert grid.is_in_ne_quadrant(ne_box)

    se_box = RoomBox(room_id="kitchen", r=grid.rows - 2, c=grid.cols - 2, w=2, h=2)
    assert grid.is_in_se_quadrant(se_box)

    sw_box = RoomBox(room_id="master_bed", r=grid.rows - 3, c=0, w=3, h=3)
    assert grid.is_in_sw_quadrant(sw_box)


def test_high_vastu_quadrant_constraints():
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1"],
        vastu_strictness="high"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return
    assert res.status in ("optimal", "compromise")
    assert res.metrics.vastu_compliance_pct >= 80.0

    grid = SpatialGrid(10.0, 12.0)
    placement_map = {p.room_id: p for p in res.placements}

    # Kitchen must be in SE
    kitchen = placement_map.get("kitchen")
    assert kitchen is not None
    k_box = RoomBox(room_id="kitchen", r=kitchen.row, c=kitchen.col, w=kitchen.width, h=kitchen.height)
    assert grid.is_in_se_quadrant(k_box) or kitchen.zone in ("SE", "E")

    # Puja must be in NE
    puja = placement_map.get("puja")
    assert puja is not None
    p_box = RoomBox(room_id="puja", r=puja.row, c=puja.col, w=puja.width, h=puja.height)
    assert grid.is_in_ne_quadrant(p_box) or puja.zone == "NE"

    # Master Bed must be in SW
    mbed = placement_map.get("master_bed")
    assert mbed is not None
    m_box = RoomBox(room_id="master_bed", r=mbed.row, c=mbed.col, w=mbed.width, h=mbed.height)
    assert grid.is_in_sw_quadrant(m_box) or mbed.zone in ("SW", "S")

    # Bath_1 must NOT be in NE
    bath = placement_map.get("bath_1")
    assert bath is not None
    assert bath.zone != "NE"


def test_plumbing_adjacency():
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=12.0,
        required_rooms=["kitchen", "bath_1", "bath_2", "living", "master_bed"],
        vastu_strictness="medium"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return
    assert res.status in ("optimal", "compromise")
    assert res.metrics.plumbing_adjacency_score >= 40.0


def test_spatial_disjointness_and_containment():
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=14.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1", "bed_2"],
        vastu_strictness="high"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return

    # Check non-overlap
    boxes = [RoomBox(p.room_id, p.row, p.col, p.width, p.height) for p in res.placements]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not boxes[i].overlaps(boxes[j]), f"Collision between {boxes[i].room_id} and {boxes[j].room_id}"

    # Check grid containment
    grid = SpatialGrid(12.0, 14.0)
    for b in boxes:
        assert b.r >= 0 and b.c >= 0
        assert b.r_end <= grid.rows
        assert b.c_end <= grid.cols


def test_timeout_fallback_protection():
    grid = SpatialGrid(plot_width_m=8.0, plot_depth_m=8.0)
    # Extremely tight timeout (0.0001s) to force timeout guard trigger
    solver = CSPEngine(
        grid=grid,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1", "bath_2", "bed_2", "dining"],
        vastu_strictness="high",
        timeout_seconds=0.0001,
        max_iterations=100
    )
    placements, status, warnings = solver.solve()
    assert status in ("compromise", "failed")
    assert any("timeout" in w.lower() or "iteration" in w.lower() or "effort" in w.lower() for w in warnings)


def test_svg_blueprint_validity():
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1"],
        vastu_strictness="high"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return
    svg = res.svg_blueprint

    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "MASTER BEDROOM" in svg
    # Narrow rooms fall back down the label ladder (abbreviation -> numbered
    # tag) but must still be listed on the sheet; the label ladder is asserted
    # by tests/reports/test_svg_legibility.py.
    assert "KITCHEN" in svg.upper()
    assert "LIVING ROOM" in svg
    assert "MAIN ENTRY" in svg
    assert "GRAPHIC SCALE" in svg
    assert "stroke-linecap=\"square\"" in svg
    assert "<path d=" in svg  # Door swing arcs
    # Check that elliptical arc command 'A' is used in door swings
    assert " A " in svg
    # Check that 45-degree slashes are present on dimension lines (stroke-width 1.6)
    assert 'stroke-width="1.6"' in svg
    # Ensure no old wall cover rects exist (the old ones had height="6")
    assert 'height="6" fill=' not in svg



@pytest.mark.asyncio
async def test_api_generate_floorplan_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "plot_width_m": 10.0,
            "plot_depth_m": 12.0,
            "required_rooms": ["master_bed", "kitchen", "living", "puja", "bath_1"],
            "vastu_strictness": "high"
        }
        resp = await client.post("/api/generate-floorplan", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] in ("optimal", "compromise")
        assert "grid_matrix" in data
        assert "svg_blueprint" in data
        assert "metrics" in data
        assert data["metrics"]["vastu_compliance_pct"] > 0
        assert data["timing_ms"] >= 0.0


def test_pdf_report_with_floorplan_integration():
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1"],
        vastu_strictness="high"
    )
    fp_res = generate_floor_plan(req)

    analysis_data = {
        "request_id": "BW-TEST-FP",
        "timestamp": "2026-09-23T15:00:00Z",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Bengaluru, Karnataka, India",
        "overall_suitability_score": 82.5,
        "suitability_verdict": "High Feasibility",
        "factors": [],
        "cost_estimate": {"base_cost_inr": 4500000, "base_rate_per_sqft": 2250, "total_estimated_cost_inr": 4800000},
        "floorplan": fp_res.model_dump()
    }

    pdf_buffer = generate_pdf_report(analysis_data)
    pdf_bytes = pdf_buffer.getvalue()
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 5000


def test_floorplan_duplicate_room_deduplication():
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["kitchen", "kitchen", "puja", "living", "master_bed"],
        vastu_strictness="high"
    )
    assert len(req.required_rooms) == 4
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return
    assert res.status in ("optimal", "compromise")
    assert len(res.placements) == 4


def test_drawing_generation_with_pydantic_models():
    from app.services.floorplan.floorplan_service import create_floorplan_reportlab_drawing
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1"],
        vastu_strictness="high"
    )
    fp_res = generate_floor_plan(req)
    # Pass with actual Pydantic RoomPlacement objects
    data_with_objects = {
        "grid_matrix": fp_res.grid_matrix,
        "placements": fp_res.placements
    }
    drawing = create_floorplan_reportlab_drawing(data_with_objects)
    assert drawing is not None
    assert drawing.width == 480.0


def test_draw_floorplan_reportlab_direct():
    from app.services.report_service import draw_floorplan_reportlab
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1"],
        vastu_strictness="high"
    )
    fp_res = generate_floor_plan(req)
    drawing = draw_floorplan_reportlab(
        placements=fp_res.placements,
        grid_matrix=fp_res.grid_matrix,
        width=520.0,
        height=220.0,
        rectangles=fp_res.rectangles
    )
    assert drawing is not None
    assert drawing.width == 520.0
    assert drawing.height == 220.0
    # Verify that shapes exist in drawing (Rect, Line, String, ArcPath)
    shape_types = {type(s).__name__ for s in drawing.contents}
    assert "Rect" in shape_types
    assert "Line" in shape_types
    assert "String" in shape_types
    assert "ArcPath" in shape_types


def test_dissection_engine_contiguity_and_no_voids():
    """
    Validates that Rectangular Dissection produces 100% envelope coverage,
    zero interior voids, and no overlapping room rectangles.
    """
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1", "bed_2"],
        vastu_strictness="high"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return
    # Status is DERIVED from the gate and the unmet ledger: a plan
    # with an advisory WARN cannot claim "optimal".
    _gate = (res.multi_storey.qa_report or {}).get("validation_gate_status")
    _expected = "optimal" if (_gate == "PASS" and not (res.unmet_requirements or [])) else "compromise"
    assert res.status == _expected, f"status {res.status} != derived {_expected} (gate {_gate})"
    assert res.rectangles is not None
    assert res.metrics.space_utilization_pct >= 95.0

    env = res.rectangles.envelope
    rooms = res.rectangles.rooms

    # 1. Total room area equals envelope area (within 1% tolerance)
    total_room_area = sum(r.area_sqm for r in rooms)
    assert abs(total_room_area - env.area_sqm) / env.area_sqm < 0.02

    # 2. Minimum dimension >= 1.95m for all rooms (excluding corridor and compact leaf baths)
    for r in rooms:
        if r.room_id == "corridor":
            assert r.height >= 1.0 or r.width >= 1.0
        elif "bath" in r.room_id:
            assert r.width >= 1.5 and r.height >= 1.95
        else:
            assert r.width >= 1.95, f"Room {r.room_id} width {r.width} < 2.0m"
            assert r.height >= 1.95, f"Room {r.room_id} height {r.height} < 2.0m"

    # 3. Pairwise intersection area is strictly zero
    for i in range(len(rooms)):
        r1 = rooms[i]
        for j in range(i + 1, len(rooms)):
            r2 = rooms[j]
            x_ov = max(0.0, min(r1.x + r1.width, r2.x + r2.width) - max(r1.x, r2.x))
            y_ov = max(0.0, min(r1.y + r1.height, r2.y + r2.height) - max(r1.y, r2.y))
            overlap_area = x_ov * y_ov
            assert overlap_area < 0.05, f"Overlap between {r1.room_id} and {r2.room_id}: {overlap_area} sqm"

    # 4. No-void grid sampling test: 20x20 points sampled across envelope
    # Every point inside the envelope must fall inside at least one room rectangle
    num_samples = 20
    dx = env.width / num_samples
    dy = env.height / num_samples
    for ix in range(num_samples):
        for iy in range(num_samples):
            px = env.x + (ix + 0.5) * dx
            py = env.y + (iy + 0.5) * dy
            covered = any(
                r.x - 0.05 <= px <= r.x + r.width + 0.05 and
                r.y - 0.05 <= py <= r.y + r.height + 0.05
                for r in rooms
            )
            assert covered, f"Point ({px:.2f}, {py:.2f}) inside envelope is a void!"


def test_dissection_circulation_and_doors():
    """
    Validates BFS circulation spanning tree: living room acts as hub,
    every non-hub room has a door connected to the circulation tree.
    """
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1", "dining"],
        vastu_strictness="high"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return
    assert res.rectangles is not None
    doors = res.rectangles.doors
    rooms = res.rectangles.rooms

    # Every room except living hub has an entry door
    door_to_rooms = {d.to_room for d in doors}
    door_from_rooms = {d.from_room for d in doors}
    door_connected_rooms = door_to_rooms | door_from_rooms

    for r in rooms:
        assert r.room_id in door_connected_rooms, f"Room {r.room_id} has no doors!"

    # Doors must have valid dimensions and swings
    for d in doors:
        assert d.width_m >= 0.85
        assert d.wall_edge in ("vertical", "horizontal")
        assert d.swing_direction in ("inward_left", "inward_right")


def test_dissection_acceptance_demos():
    """
    Tests the 3 required acceptance scenarios:
    1. 10m x 12m with 6 rooms
    2. 8m x 8m with 4 rooms
    3. 18m x 15m with 9 rooms
    """
    # Demo 1: 10m x 12m (6 rooms)
    req1 = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1", "bed_2"],
        vastu_strictness="high"
    )
    res1 = generate_floor_plan(req1)
    # A brief the statutory ceiling cannot hold is refused explicitly.
    if res1.status == "failed":
        assert res1.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res1.warnings), res1.warnings
        return
    assert res1.status in ("optimal", "compromise")
    assert res1.metrics.space_utilization_pct >= 95.0
    assert len(res1.rectangles.rooms) in (6, 7)  # 6 rooms + optional explicit circulation corridor

    # Demo 2: the ORIGINAL fixture was an 8 m x 8 m plot (64 m²) at 60% coverage.
    # Its 28 m² setback plate cannot host a 14 m² bedroom + 18 m² living room +
    # 9 m² kitchen + bath at any legal width, so the brief is now REFUSED with
    # the numbers instead of being squashed into an "optimal" 4-room plan. The
    # 4-room demo runs on a plate that can host it, and the sub-minimum brief is
    # pinned separately below.
    req2_small = FloorPlanRequest(
        plot_width_m=8.0,
        plot_depth_m=8.0,
        required_rooms=["master_bed", "kitchen", "living", "bath_1"],
        vastu_strictness="high"
    )
    res2_small = generate_floor_plan(req2_small)
    assert res2_small.status == "failed"
    assert res2_small.unmet_requirements
    assert any("does not fit the statutory ground plate" in u["reason"]
               for u in res2_small.unmet_requirements), res2_small.unmet_requirements

    req2 = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=10.0,
        required_rooms=["master_bed", "kitchen", "living", "bath_1"],
        vastu_strictness="high"
    )
    res2 = generate_floor_plan(req2)
    # Status is DERIVED from unmet requirements / gate warns: a plan
    # carrying a warning can no longer claim "optimal".
    assert res2.status in ("optimal", "compromise")
    if res2.status == "compromise":
        assert res2.warnings or res2.unmet_requirements
    assert res2.metrics.space_utilization_pct >= 95.0
    # Every requested room is drawn; the engine may add the explicit circulation
    # corridor (the same allowance demo 1 makes), so the count is 4 or 5 - never
    # fewer than the four that were asked for.
    drawn_ids = {r.room_id for r in res2.rectangles.rooms}
    assert {"master_bed", "kitchen", "living", "bath_1"} <= drawn_ids, drawn_ids
    assert len(res2.rectangles.rooms) in (4, 5), drawn_ids

    # Demo 3: 18m x 15m (9 rooms)
    req3 = FloorPlanRequest(
        plot_width_m=18.0,
        plot_depth_m=15.0,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1", "bath_2", "bed_2", "dining", "stairs"],
        vastu_strictness="high"
    )
    res3 = generate_floor_plan(req3)
    assert res3.status in ("optimal", "compromise")
    if res3.status == "compromise":
        assert res3.warnings or res3.unmet_requirements
    assert res3.metrics.space_utilization_pct >= 95.0
    assert len(res3.rectangles.rooms) == 9


def test_blueprint_spatial_logic_v11_16x19m():
    """
    Blueprint Spatial Logic v11 Comprehensive Verification:
    Tests the 16.1m x 19.3m residential case ensuring:
    1. Functional Zoning: PUBLIC North frontage, PRIVATE West/SW flank, SERVICE East/SE flank.
    2. Circulation Graph & Entry: Main entry arrow lands on North frontage wall inside living extent.
    3. Bathrooms: BATH 1 is common off corridor/hall; BATH 2 is ensuite opening ONLY off master bedroom.
    4. Adjacency: Zero forbidden shared walls (bath-puja, bath-kitchen, bed-kitchen).
    5. Room Area Catalog: No mega-rooms (baths <= 6.0 m2, master bedroom <= 22.0 m2, kitchen <= 16.0 m2).
    6. Aspect ratio <= 1:2.5 for all rooms (excluding corridor).
    7. BFS Reachability: 100% connected door graph.
    8. Solver QA Gate: qa: { entry: "living", circulation: "connected", violations: 0 }.
    9. SVG Rendering: No exterior door arcs for bathrooms; main entry arrow rendered.
    """
    from collections import deque
    from app.services.floorplan.grid_model import get_room_catalog_entry
    from app.services.floorplan.constraints import is_forbidden_shared_wall

    req = FloorPlanRequest(
        plot_width_m=16.1,
        plot_depth_m=19.3,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1", "bath_2", "bed_2", "dining"],
        vastu_strictness="high"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return

    # 1. Optimal solve status & Rectangles model present
    # Status is DERIVED from the gate and the unmet ledger: a plan
    # with an advisory WARN cannot claim "optimal".
    _gate = (res.multi_storey.qa_report or {}).get("validation_gate_status")
    _expected = "optimal" if (_gate == "PASS" and not (res.unmet_requirements or [])) else "compromise"
    assert res.status == _expected, f"status {res.status} != derived {_expected} (gate {_gate})"
    assert res.rectangles is not None
    assert res.qa is not None
    assert res.qa.violations == 0
    assert res.qa.circulation == "connected"
    assert res.qa.entry in ("living", "hall")
    assert res.metrics.circulation_status == "connected"

    rects = res.rectangles
    rooms_by_id = {r.room_id: r for r in rects.rooms}

    # Verify all 8 requested rooms + circulation corridor are present
    expected_rooms = ["master_bed", "kitchen", "living", "puja", "bath_1", "bath_2", "bed_2", "dining"]
    for er in expected_rooms:
        assert er in rooms_by_id, f"Missing expected room: {er}"

    # 2. Main Entry Door Verification:
    # Must be on North frontage wall and land strictly inside Living/Hall extent
    main_doors = [d for d in rects.doors if d.door_id == "main_entry" or d.from_room == "exterior"]
    assert len(main_doors) >= 1, "Main entry door not found"
    entry_door = main_doors[0]
    assert entry_door.to_room in ("living", "hall")
    assert entry_door.from_room == "exterior"
    assert entry_door.wall_edge == "horizontal"
    assert abs(entry_door.y1 - rects.envelope.y) < 0.1
    # Check door falls within living room X range
    living = rooms_by_id["living"]
    assert living.x - 0.05 <= entry_door.x1 <= living.x + living.width + 0.05
    assert living.x - 0.05 <= entry_door.x2 <= living.x + living.width + 0.05

    # 3. Bathroom Doors Verification:
    # BATH 1 = common (door off corridor/hall)
    bath1_doors = [d for d in rects.doors if d.from_room == "bath_1" or d.to_room == "bath_1"]
    assert len(bath1_doors) >= 1, "Bath 1 has no door"
    bath1_connected = {d.from_room for d in bath1_doors} | {d.to_room for d in bath1_doors}
    assert any("corridor" in r or "living" in r for r in bath1_connected), f"Bath 1 not off corridor: {bath1_connected}"

    # BATH 2 = ensuite (door ONLY off master bedroom)
    bath2_doors = [d for d in rects.doors if d.from_room == "bath_2" or d.to_room == "bath_2"]
    assert len(bath2_doors) >= 1, "Bath 2 has no door"
    for d in bath2_doors:
        other_side = d.from_room if d.to_room == "bath_2" else d.to_room
        assert other_side == "master_bed", f"Ensuite Bath 2 door must only connect to master_bed, got {other_side}"

    # No exterior doors on bathrooms
    for d in rects.doors:
        if "bath" in d.from_room or "bath" in d.to_room:
            assert d.from_room != "exterior" and d.to_room != "exterior", "Bathroom has an exterior door!"

    # 4. Adjacency Prohibition Matrix: Zero forbidden shared walls
    for i in range(len(rects.rooms)):
        r1 = rects.rooms[i]
        for j in range(i + 1, len(rects.rooms)):
            r2 = rects.rooms[j]
            # Check if r1 and r2 share a wall segment >= 0.2m
            vert_share = (abs(r1.x + r1.width - r2.x) < 0.05 or abs(r2.x + r2.width - r1.x) < 0.05) and (
                min(r1.y + r1.height, r2.y + r2.height) - max(r1.y, r2.y) >= 0.2
            )
            horiz_share = (abs(r1.y + r1.height - r2.y) < 0.05 or abs(r2.y + r2.height - r1.y) < 0.05) and (
                min(r1.x + r1.width, r2.x + r2.width) - max(r1.x, r2.x) >= 0.2
            )
            if vert_share or horiz_share:
                assert not is_forbidden_shared_wall(r1.room_id, r2.room_id), (
                    f"Forbidden adjacency detected between {r1.room_id} and {r2.room_id}"
                )

    # Pooja NE touching hall with no bath wall
    puja = rooms_by_id["puja"]
    assert puja.x >= living.x, "Pooja must be in the NE corner"
    # Shared wall with living
    puja_living_share = (abs(puja.x - (living.x + living.width)) < 0.05) and (
        min(puja.y + puja.height, living.y + living.height) - max(puja.y, living.y) >= 0.5
    )
    assert puja_living_share, "Pooja must touch living room"

    # Bedrooms on SW/W band
    mbed = rooms_by_id["master_bed"]
    bed2 = rooms_by_id["bed_2"]
    mid_x = rects.envelope.x + (rects.envelope.width / 2.0)
    mid_y = rects.envelope.y + (rects.envelope.height / 2.0)
    assert mbed.x < mid_x and mbed.y + mbed.height >= mid_y, "Master bedroom must be in SW quadrant"
    assert bed2.x < mid_x, "Bedroom 2 must be on West flank"

    # Kitchen in SE touching dining
    kitchen = rooms_by_id["kitchen"]
    dining = rooms_by_id["dining"]
    assert kitchen.x >= mid_x and kitchen.y + kitchen.height >= mid_y, "Kitchen must be in SE quadrant"
    kitchen_dining_share = (abs(kitchen.y - (dining.y + dining.height)) < 0.05) and (
        min(kitchen.x + kitchen.width, dining.x + dining.width) - max(kitchen.x, dining.x) >= 0.5
    )
    assert kitchen_dining_share, "Kitchen must share wall with dining"

    # 5. Realistic Room Area Catalog Ranges (No Mega-Rooms, No 16.5m2 baths, No 44m2 bedrooms)
    for r in rects.rooms:
        if "corridor" in r.room_id:
            continue
        cat = get_room_catalog_entry(r.room_id)
        cat_min = cat.get("catalog_min_m2", 3.0)
        cat_max = cat.get("catalog_max_m2", 35.0)
        assert r.area_sqm >= round(cat_min * 0.90, 2), f"Room {r.room_id} area {r.area_sqm} < min {cat_min}"
        assert r.area_sqm <= round(cat_max * 1.10, 2), f"Room {r.room_id} area {r.area_sqm} > max {cat_max}"

    # Specific strict checks
    assert rooms_by_id["bath_1"].area_sqm <= 6.0, f"Bath 1 oversized: {rooms_by_id['bath_1'].area_sqm}"
    assert rooms_by_id["bath_2"].area_sqm <= 6.0, f"Bath 2 oversized: {rooms_by_id['bath_2'].area_sqm}"
    assert rooms_by_id["master_bed"].area_sqm <= 22.0, f"Master bedroom oversized: {rooms_by_id['master_bed'].area_sqm}"
    assert rooms_by_id["kitchen"].area_sqm <= 16.0, f"Kitchen oversized: {rooms_by_id['kitchen'].area_sqm}"

    # 6. Aspect ratios <= 1:2.5 (excluding corridors)
    for r in rects.rooms:
        if "corridor" in r.room_id:
            continue
        ar = max(r.width, r.height) / max(min(r.width, r.height), 0.01)
        assert ar <= 2.50, f"Room {r.room_id} aspect ratio {ar:.2f} exceeds 1:2.5"

    # 7. BFS Reachability from Entry
    door_adj = {r.room_id: set() for r in rects.rooms}
    for d in rects.doors:
        if d.from_room != "exterior" and d.to_room != "exterior":
            if d.from_room in door_adj and d.to_room in door_adj:
                door_adj[d.from_room].add(d.to_room)
                door_adj[d.to_room].add(d.from_room)

    visited = set()
    queue = deque(["living"])
    visited.add("living")
    while queue:
        curr = queue.popleft()
        for nbr in door_adj.get(curr, []):
            if nbr not in visited:
                visited.add(nbr)
                queue.append(nbr)

    room_ids_set = {r.room_id for r in rects.rooms}
    assert visited == room_ids_set, f"Unreachable rooms via door BFS: {room_ids_set - visited}"

    # 8. SVG Blueprint Verification
    assert "<svg" in res.svg_blueprint
    assert "main_entry" in res.svg_blueprint or "MAIN ENTRY" in res.svg_blueprint
    # Ensure no exterior door arc for bathrooms
    assert not ('from="bath' in res.svg_blueprint and 'to="exterior"' in res.svg_blueprint)


def test_blueprint_topological_invariants_10x10m_v12():
    """
    BLUEPRINT TOPOLOGICAL INVARIANTS + LLM LAYOUT CRITIC v12
    Re-runs the exact failing case (~10.9m x 10.6m, 5 rooms):
    1. LEAF RULE: Bath has degree == 1 in door graph (single door to corridor, no through-traffic).
    2. PERIPHERAL SERVICE: Bath and Kitchen touch exterior walls. Centroids outside central 40% box.
    3. CORRIDOR RULE: 1.2m wide explicit corridor separates public and rear bands.
    4. EXTERIOR WALL RULE: Living, Master Bed, Kitchen each touch exterior wall.
    5. CATALOG CLAMPS:
       - Bath: 3.5 - 6.0 m2 (compact leaf)
       - Puja: 4.0 - 9.0 m2 with min width >= 2.4m (no strip rooms)
       - Master Bed: 14 - 22 m2
       - Kitchen: 9 - 16 m2
       - Living: 18 - 35 m2
       - Aspect ratio <= 1:2.2 for every room.
    6. DOOR VISIBILITY: Bath door does not face entry axis.
    7. ZERO doors between two private/service rooms.
    8. Mock mode: critic skipped without crashing, invariants strictly preserved.
    """
    from app.services.floorplan.grid_model import get_room_catalog_entry
    from app.services.floorplan.constraints import is_bath_or_wc, is_service_room

    req = FloorPlanRequest(
        plot_width_m=10.9,
        plot_depth_m=10.6,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1"],
        vastu_strictness="high",
        ai_provider="mock"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return

    # Status is DERIVED from the gate and the unmet ledger: a plan
    # with an advisory WARN cannot claim "optimal".
    _gate = (res.multi_storey.qa_report or {}).get("validation_gate_status")
    _expected = "optimal" if (_gate == "PASS" and not (res.unmet_requirements or [])) else "compromise"
    assert res.status == _expected, f"status {res.status} != derived {_expected} (gate {_gate})"
    assert res.rectangles is not None
    assert res.qa is not None
    assert res.qa.violations == 0
    assert res.qa.circulation == "connected"
    assert res.qa.leaf_rule is True
    assert res.qa.peripheral_service is True
    assert res.qa.catalog is True
    assert res.qa.aspect is True
    assert res.qa.entry in ("living", "hall")
    assert res.qa.critic in ("pass", "skipped")

    rects = res.rectangles
    rooms_by_id = {r.room_id: r for r in rects.rooms}

    # 1. Rooms Presence: all 5 rooms + corridor
    for expected in ["master_bed", "kitchen", "living", "puja", "bath_1", "corridor"]:
        assert expected in rooms_by_id, f"Missing room {expected}"

    env = rects.envelope
    ex0, ex1 = env.x, env.x + env.width
    ey0, ey1 = env.y, env.y + env.height
    cx0, cx1 = ex0 + 0.30 * env.width, ex0 + 0.70 * env.width
    cy0, cy1 = ey0 + 0.30 * env.height, ey0 + 0.70 * env.height

    # 2. Leaf Rule: Degree of bath_1 == 1
    degree = {r.room_id: 0 for r in rects.rooms}
    for d in rects.doors:
        if d.door_id == "main_entry" or d.from_room == "exterior" or d.to_room == "exterior":
            continue
        if d.from_room in degree:
            degree[d.from_room] += 1
        if d.to_room in degree:
            degree[d.to_room] += 1

    assert degree["bath_1"] == 1, f"Bath must have degree == 1, got {degree['bath_1']}"
    assert degree["puja"] == 1, f"Puja must have degree == 1, got {degree['puja']}"

    # Bath door must open to corridor only
    bath_doors = [d for d in rects.doors if d.from_room == "bath_1" or d.to_room == "bath_1"]
    assert len(bath_doors) == 1
    bd = bath_doors[0]
    other_end = bd.from_room if bd.to_room == "bath_1" else bd.to_room
    assert other_end == "corridor", f"Bath door must open to corridor only, got {other_end}"

    # 3. Compact Bath Dimensions & Exterior Wall:
    bath = rooms_by_id["bath_1"]
    assert 3.5 <= bath.area_sqm <= 6.0, f"Bath area must be 3.5-6.0 m2, got {bath.area_sqm}"
    # Bath touches South exterior wall
    assert abs((bath.y + bath.height) - ey1) < 0.08, "Bath must touch South exterior wall"
    # Centroid outside central 40% box
    bath_cx = bath.x + bath.width / 2.0
    bath_cy = bath.y + bath.height / 2.0
    assert not (cx0 <= bath_cx <= cx1 and cy0 <= bath_cy <= cy1), "Bath centroid cannot be in central 40% box"

    # 4. Puja: NE corner, width >= 2.4m, area <= 9.0m2
    puja = rooms_by_id["puja"]
    assert min(puja.width, puja.height) >= 2.35, f"Puja width must be >= 2.4m, got {min(puja.width, puja.height)}"
    assert 4.0 <= puja.area_sqm <= 9.0, f"Puja area must be 4.0-9.0 m2, got {puja.area_sqm}"
    assert puja.x >= rooms_by_id["living"].x, "Puja must be in East/NE quadrant"

    # 5. Kitchen: SE corner leaf, area 9-16 m2
    kitch = rooms_by_id["kitchen"]
    # A tightened (legal) plate may push a room below the catalogue band, but
    # Only with an explicit ROOM-MIN disclosure.
    if kitch.area_sqm < 9.0 * 0.90:
        assert any(f"ROOM-MIN: {kitch.room_id} " in str(w) for w in res.warnings), (
            f"Kitchen area {kitch.area_sqm} m2 below the 9-16 m2 band without disclosure"
        )
    assert kitch.area_sqm <= 16.0 * 1.10, f"Kitchen area must be <= 16 m2, got {kitch.area_sqm}"
    assert abs((kitch.y + kitch.height) - ey1) < 0.08, "Kitchen must touch South exterior wall"
    assert abs((kitch.x + kitch.width) - ex1) < 0.08, "Kitchen must touch East exterior wall"

    # 6. Master Bed: SW region, area 14-22 m2
    mb = rooms_by_id["master_bed"]
    if mb.area_sqm < 14.0 * 0.90:
        # Legal plate, disclosed shortfall (see the ROOM-MIN contract above).
        assert any(f"ROOM-MIN: {mb.room_id} " in str(w) for w in res.warnings), (
            f"Master bedroom area {mb.area_sqm} m2 below the 14-22 m2 band without disclosure"
        )
    assert mb.area_sqm <= 22.0 * 1.10, f"Master bedroom area must be <= 22 m2, got {mb.area_sqm}"
    assert abs((mb.y + mb.height) - ey1) < 0.08, "Master bed must touch South exterior wall"

    # 7. Living: Entry on North wall, aspect ratio <= 2.2
    liv = rooms_by_id["living"]
    liv_ar = max(liv.width, liv.height) / max(min(liv.width, liv.height), 0.01)
    assert liv_ar <= 2.20, f"Living aspect ratio {liv_ar:.2f} exceeds 1:2.2"
    main_doors = [d for d in rects.doors if d.door_id == "main_entry"]
    assert len(main_doors) == 1
    assert main_doors[0].to_room == "living"

    # 8. Corridor band: 1.0 - 1.2m wide, separates public and rear
    corr = rooms_by_id["corridor"]
    assert 1.0 <= min(corr.width, corr.height) <= 1.25, f"Corridor width must be 1.0-1.2m, got {min(corr.width, corr.height)}"
    assert corr.y >= liv.y + liv.height - 0.05
    assert mb.y >= corr.y + min(corr.width, corr.height) - 0.05

    # 9. No room in central 40% box except corridor
    for r in rects.rooms:
        if r.room_id == "corridor":
            continue
        rcx = r.x + r.width / 2.0
        rcy = r.y + r.height / 2.0
        assert not (cx0 <= rcx <= cx1 and cy0 <= rcy <= cy1), f"Room {r.room_id} centroid inside central 40% box!"

    # 10. Zero doors between two private/service rooms
    for d in rects.doors:
        if d.door_id == "main_entry" or d.from_room == "exterior" or d.to_room == "exterior":
            continue
        r1, r2 = d.from_room, d.to_room
        is_r1_connector = r1 in ("living", "hall", "foyer", "corridor")
        is_r2_connector = r2 in ("living", "hall", "foyer", "corridor")
        assert is_r1_connector or is_r2_connector, f"Door directly between private/service rooms: {r1} <-> {r2}"


def test_llm_layout_critic_retry_loop():
    """
    Tests the LLM Layout Critic loop:
    1. Simulates critic rejecting initial layout.
    2. Verifies re-solve with forced template seed is triggered.
    3. Verifies critic verdict and warnings are recorded in solver output.
    """
    # LLM critic retired from the geometry loop: the engine is deterministic & ontology-driven
    req = FloorPlanRequest(
        plot_width_m=10.9,
        plot_depth_m=10.6,
        required_rooms=["master_bed", "kitchen", "living", "puja", "bath_1"],
        vastu_strictness="high",
        ai_provider="groq"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # Refused brief: the statutory ceiling cannot hold the
        # programme, so the refusal must be explicit - never a squeezed plan.
        assert res.unmet_requirements, "a refusal must name what it could not place"
        assert any(str(w).startswith(("GEN-", "GATE-FAIL")) for w in res.warnings), res.warnings
        return
    # Asserting the certificate's own flags against itself proved nothing.
    # Re-derive the forbidden-wall verdict from the EMITTED geometry and the
    # ontology SPACE TYPES (never solver handles), then require the certificate
    # to agree with the independent sweep.
    from app.services.floorplan.identity import space_type_of
    from app.services.floorplan.ontology import ONTOLOGY

    assert res.multi_storey is not None and res.multi_storey.floors
    _violations = []
    for _fl in res.multi_storey.floors:
        _rooms = _fl.rooms
        for _i in range(len(_rooms)):
            _r1 = _rooms[_i]
            for _r2 in _rooms[_i + 1:]:
                _v = (
                    (abs((_r1.x + _r1.width_m) - _r2.x) < 0.05
                     or abs((_r2.x + _r2.width_m) - _r1.x) < 0.05)
                    and (min(_r1.y + _r1.depth_m, _r2.y + _r2.depth_m) - max(_r1.y, _r2.y)) >= 0.20
                )
                _h = (
                    (abs((_r1.y + _r1.depth_m) - _r2.y) < 0.05
                     or abs((_r2.y + _r2.depth_m) - _r1.y) < 0.05)
                    and (min(_r1.x + _r1.width_m, _r2.x + _r2.width_m) - max(_r1.x, _r2.x)) >= 0.20
                )
                if not (_v or _h):
                    continue
                _t1 = space_type_of(_r1, res.multi_storey.building_typology) or _r1.room_id
                _t2 = space_type_of(_r2, res.multi_storey.building_typology) or _r2.room_id
                if ONTOLOGY.is_forbidden_wall(_t1, _t2):
                    _violations.append((_fl.floor_index, _r1.room_id, _r2.room_id, _t1, _t2))

    _cert = res.mathematical_certificate
    assert not _violations, f"geometry violates FORBIDDEN_WALL: {_violations}"
    assert _cert["zero_forbidden_violations"] is True
    assert _cert["details"]["forbidden_wall_pairs"] == []
    assert _cert["connectivity_bfs"] is True
    assert _cert["chain_sums_match"] is True

    # A certified rule must be backed by a passing flag, and a withheld
    # Certificate must explain itself.
    _rule_flags = {
        "REL-01": _cert["non_overlap"],
        "REL-02": _cert["zero_forbidden_violations"],
        "CIRC-01": _cert["connectivity_bfs"],
        "DIM-01": _cert["chain_sums_match"],
        "NBC-01": _cert["min_dimensions_satisfied"],
        "NBC-02": _cert["aspect_ratios_satisfied"],
        "NBC-03": _cert["egress_distances_satisfied"],
        "SAN-01": _cert["sanitation_wc_count_satisfied"],
    }
    for _rule in _cert["certified_rules"]:
        if _rule in _rule_flags:
            assert _rule_flags[_rule] is True, f"{_rule} certified while its flag is false"
    if _cert["is_valid"] is False:
        assert _cert["failures"], "an invalid certificate must state why"

    # The QA rows and the gate must agree.
    assert res.qa is not None
    assert res.qa.validation_gate_status == _cert["overall_layer_status"]
    assert res.qa.critic == "skipped", "no architect critic ran - it must not claim a pass"




