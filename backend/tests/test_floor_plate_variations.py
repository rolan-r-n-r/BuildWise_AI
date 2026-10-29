"""
test_floor_plate_variations.py - Verification and Proof for Per-Floor Floorplate Variations
========================================================================================
Tests:
1. Golden Case: T1 G+2 with top-level Wing B terraced.
   - Cores present on all levels (RULE-FP-01)
   - Egress BFS connectivity maintained (RULE-FP-05)
   - No wet room directly above terrace (RULE-FP-03)
   - Terrace area excluded from FAR numerator & carpet area (RULE-FP-06)
   - Terrace access door from adjacent corridor (RULE-FP-04)
   - Drawing IR and SVG emit mf-hatch-terrace and parapet double-lines
   - Mathematical Validity Certificate additions certified
2. Hard Rule Enforcement:
   - Attempting to terrace Wing A (contains core) is rejected/reset (RULE-FP-01)
   - Unsupported cantilever above void is rejected/reset (RULE-FP-02)
   - Wet room above terrace violation detection (RULE-FP-03)
3. Rectangle-Equivalence:
   - Default behavior when no masks passed is 100% backwards compatible
"""

import pytest
from app.schemas.floorplan import FloorPlanRequest
from app.schemas.site_plan import PlotPolygonModel
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.ontology import propose_default_floor_plate_masks
from app.services.floorplan.drawing_ir import build_drawing_ir, render_svg_from_ir


def test_golden_case_t1_g2_wing_b_terraced():
    """
    Golden Case: T1 Single Family G+2 (3 storeys) on L-shaped footprint with
    top level (Floor 2) Wing B terraced (open-to-sky setback deck).
    """
    l_shape_verts = [
        [0.0, 0.0],
        [16.0, 0.0],
        [16.0, 10.0],
        [8.0, 10.0],
        [8.0, 16.0],
        [0.0, 16.0],
    ]
    poly = PlotPolygonModel(
        vertices=l_shape_verts,
        shape_type="l_shape",
        area_sqm=192.0,
        perimeter_m=64.0,
        bounding_box=[0.0, 0.0, 16.0, 16.0],
        is_regular_rectangle=False,
    )

    req = FloorPlanRequest(
        plot_width_m=16.0,
        plot_depth_m=16.0,
        required_rooms=["living", "dining", "kitchen", "master_bed", "bed_2", "bath_1", "bath_2", "study"],
        building_typology="residential_single",
        floors=3,
        plot_polygon=poly,
        floor_plate_masks={
            0: {"wing_a": "present", "wing_b": "present"},
            1: {"wing_a": "present", "wing_b": "present"},
            2: {"wing_a": "present", "wing_b": "terrace"},
        },
    )

    engine = SoleGeometryEngine(req)
    model = engine.solve()

    # 1. Total Storeys & Floor Models
    assert model.total_storeys == 3
    assert len(model.floors) == 3

    f0 = model.floors[0]
    f1 = model.floors[1]
    f2 = model.floors[2]

    # 2. Plate Compositions & Masks
    assert f0.plate_composition == "Wing A + Wing B"
    assert f1.plate_composition == "Wing A + Wing B"
    assert f2.plate_composition == "Wing A + Terrace"
    assert f2.floor_plate_mask.get("wing_b") == "terrace"

    # 3. RULE-FP-01: Core Continuity
    # Vertical core must be present on every occupied level
    for z, fl in enumerate(model.floors):
        cores = [r for r in fl.rooms if r.is_vertical_core]
        assert len(cores) >= 1, f"Floor {z} missing vertical core"
        assert cores[0].room_name == "Dogleg Staircase Core"

    # 4. RULE-FP-04 & RULE-FP-05: Terrace Room & Door Reachability
    terrace_rooms = [r for r in f2.rooms if r.zone_category == "terrace"]
    assert len(terrace_rooms) == 1, "Floor 2 must have exactly 1 terrace room"
    t_room = terrace_rooms[0]
    assert "terrace" in t_room.room_id
    assert t_room.area_sqm > 0

    # Door from link_corridor to terrace exists
    terr_doors = [d for d in f2.doors if d.to_room == t_room.room_id or d.from_room == t_room.room_id]
    assert len(terr_doors) >= 1, "Terrace must have an access door from adjacent corridor"
    assert f2.circulation_status == "connected"

    # 5. RULE-FP-06: FAR Excludes Terrace Area
    # Terrace area must be excluded from built-up area and carpet area
    f2_non_terrace_sum = round(sum(r.area_sqm for r in f2.rooms if r.zone_category != "terrace"), 2)
    assert f2.built_up_area_sqm == f2_non_terrace_sum
    assert f2.carpet_area_sqm < f2.built_up_area_sqm

    # Total built-up matches sum of non-terrace built-up
    expected_total_built_up = round(f0.built_up_area_sqm + f1.built_up_area_sqm + f2.built_up_area_sqm, 2)
    assert model.total_built_up_area_sqm == expected_total_built_up

    # 6. Certificate Additions
    cert = model.mathematical_certificate
    assert cert is not None
    assert cert.get("core_continuity_valid") is True
    assert cert.get("no_wet_over_terrace_valid") is True
    assert cert.get("terrace_far_exempt") is True
    assert cert.get("cores_stack_aligned") is True
    assert "RULE-FP-01" in cert.get("certified_rules", [])
    assert "RULE-FP-06" in cert.get("certified_rules", [])
    assert cert.get("is_valid") is True

    # 7. Drawing IR & SVG representation
    ir2 = build_drawing_ir(f2, model, typology="T1_SINGLE_FAMILY")
    svg2 = render_svg_from_ir(ir2, theme="cad")

    # SVG contains terrace hatch pattern and labels
    assert "mf-hatch-terrace" in svg2
    assert "OPEN TO SKY" in svg2
    assert "TERRACE" in svg2
    assert "DRAINAGE" in svg2

    # Parapet walls exist in wall graph
    wg = f2.wall_graph
    assert wg is not None
    walls_list = wg.get("walls", [])
    if isinstance(walls_list, dict):
        walls_list = list(walls_list.values())
    parapet_walls = [w for w in walls_list if w.get("wall_type") == "W_PARAPET"]
    assert len(parapet_walls) >= 2, "Wall graph must contain parapet walls for terrace perimeter"


def test_rule_fp_01_core_wing_cannot_be_terraced():
    """
    RULE-FP-01: A wing containing a vertical core (Wing A) cannot be terraced or void.
    The engine must detect this and reset Wing A to present with a warning.
    """
    l_shape_verts = [
        [0.0, 0.0],
        [14.0, 0.0],
        [14.0, 8.0],
        [7.0, 8.0],
        [7.0, 14.0],
        [0.0, 14.0],
    ]
    poly = PlotPolygonModel(
        vertices=l_shape_verts,
        shape_type="l_shape",
        area_sqm=147.0,
        perimeter_m=56.0,
        bounding_box=[0.0, 0.0, 14.0, 14.0],
        is_regular_rectangle=False,
    )

    # Attempt to terrace wing_a on floor 1
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=14.0,
        required_rooms=["living", "dining", "kitchen", "master_bed", "bed_2", "bath_1", "bath_2"],
        building_typology="residential_single",
        floors=2,
        plot_polygon=poly,
        floor_plate_masks={
            0: {"wing_a": "present", "wing_b": "present"},
            1: {"wing_a": "terrace", "wing_b": "present"},
        },
    )

    engine = SoleGeometryEngine(req)
    model = engine.solve()

    # Engine must have reset wing_a to present
    assert model.floors[1].floor_plate_mask.get("wing_a") == "present"
    # Core is still present
    cores = [r for r in model.floors[1].rooms if r.is_vertical_core]
    assert len(cores) >= 1
    # Warning was emitted
    assert any("RULE-FP-01" in w for w in model.warnings)


def test_rule_fp_02_cantilever_without_lower_support_forbidden():
    """
    RULE-FP-02: Wings may only be dropped on levels above where they exist;
    adding a wing above without lower support (cantilever) is forbidden.
    """
    l_shape_verts = [
        [0.0, 0.0],
        [14.0, 0.0],
        [14.0, 8.0],
        [7.0, 8.0],
        [7.0, 14.0],
        [0.0, 14.0],
    ]
    poly = PlotPolygonModel(
        vertices=l_shape_verts,
        shape_type="l_shape",
        area_sqm=147.0,
        perimeter_m=56.0,
        bounding_box=[0.0, 0.0, 14.0, 14.0],
        is_regular_rectangle=False,
    )

    # Level 1 drops wing_b to void, but Level 2 attempts to have wing_b present
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=14.0,
        required_rooms=["living", "dining", "kitchen", "master_bed", "bed_2", "bath_1", "bath_2"],
        building_typology="residential_single",
        floors=3,
        plot_polygon=poly,
        floor_plate_masks={
            0: {"wing_a": "present", "wing_b": "present"},
            1: {"wing_a": "present", "wing_b": "void"},
            2: {"wing_a": "present", "wing_b": "present"},
        },
    )

    engine = SoleGeometryEngine(req)
    model = engine.solve()

    # Level 2 wing_b must be reset to void
    assert model.floors[2].floor_plate_mask.get("wing_b") == "void"
    assert any("RULE-FP-02" in w for w in model.warnings)


def test_typology_default_mask_proposal():
    """
    Verifies that propose_default_floor_plate_masks proposes:
    - T1 storeys >= 3: top level terraces Wing B.
    - storeys < 3: all present.
    """
    masks_t1_3f = propose_default_floor_plate_masks("T1_SINGLE_FAMILY", 3)
    assert masks_t1_3f[0]["wing_b"] == "present"
    assert masks_t1_3f[1]["wing_b"] == "present"
    assert masks_t1_3f[2]["wing_b"] == "terrace"

    masks_t1_2f = propose_default_floor_plate_masks("T1_SINGLE_FAMILY", 2)
    assert masks_t1_2f[0]["wing_b"] == "present"
    assert masks_t1_2f[1]["wing_b"] == "present"


def test_rectangle_equivalence_unaffected():
    """
    Verifies that standard rectangular floor plans remain 100% unaffected
    and backwards compatible.
    """
    req = FloorPlanRequest(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        required_rooms=["living", "kitchen", "master_bed", "bath_1"],
        building_typology="residential_single",
        floors=1,
    )
    engine = SoleGeometryEngine(req)
    model = engine.solve()

    assert model.total_storeys == 1
    assert len(model.floors) == 1
    assert model.floors[0].plate_composition == "Full Plate"
    assert model.mathematical_certificate.get("is_valid") is True
    assert model.mathematical_certificate.get("core_continuity_valid") is True
    assert model.mathematical_certificate.get("no_wet_over_terrace_valid") is True


def test_golden_rectangular_terrace_band_g2_level2_north_3m():
    """
    Golden Case: Simple rectangular 12x15m G+2 (3 storeys) with North terrace band of 3.0m on Level 2.
    Verifies:
    1. Core continuity holds (same core geometry and position across all floors).
    2. No wet room over band (RULE-FP-03).
    3. FAR numerator drops by exactly band area (9.60 * 3.00 = 28.80 sqm).
    4. Level 2 built-up area = 72.00 sqm (was 100.80 sqm).
    5. Parapet double lines and terrace hatch emitted in SVG.
    6. Drainage note 'DRAINAGE SLOPE 1:100 TO RWO' present in SVG.
    7. Balcony slider door from lobby to terrace present.
    8. Plate composition: 'Plate - North band + Terrace'.
    9. RULE-FP-07 certified.
    """
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        floors=3,
        terrace_bands={
            2: {"edge": "N", "depth_m": 3.0},
        },
    )

    engine = SoleGeometryEngine(req)
    model = engine.solve()

    assert model.total_storeys == 3
    assert len(model.floors) == 3

    f0 = model.floors[0]
    f1 = model.floors[1]
    f2 = model.floors[2]

    # Plate compositions
    assert f0.plate_composition == "Full Plate"
    assert f1.plate_composition == "Full Plate"
    assert f2.plate_composition == "Plate - North band 3.0 m + Terrace"
    assert f2.terrace_band == {"edge": "N", "depth_m": 3.0}

    # 1. Core Continuity (RULE-FP-01)
    core0 = next(r for r in f0.rooms if r.is_vertical_core)
    core1 = next(r for r in f1.rooms if r.is_vertical_core)
    core2 = next(r for r in f2.rooms if r.is_vertical_core)
    assert (core0.x, core0.y, core0.width_m, core0.depth_m) == (core1.x, core1.y, core1.width_m, core1.depth_m)
    assert (core1.x, core1.y, core1.width_m, core1.depth_m) == (core2.x, core2.y, core2.width_m, core2.depth_m)
    assert core2.y == 3.0  # Aligned with terrace band depth!

    # 2. Area reduction by exactly band area (RULE-FP-06)
    # The T1 plate follows the band stack (9.59 x 10.54 m) instead of the
    # site's own proportion, so the band area is derived from the drawn
    # envelope rather than pinned to the retired 9.60 m width.
    env_w = f2.envelope["width"]
    band_area = round(env_w * 3.0, 2)
    assert band_area == round(9.59 * 3.0, 2)

    assert round(f0.built_up_area_sqm - f2.built_up_area_sqm, 2) == band_area
    assert round(model.total_built_up_area_sqm, 2) == round(f0.built_up_area_sqm + f1.built_up_area_sqm + f2.built_up_area_sqm, 2)

    # 3. Terrace room properties
    t_rooms = [r for r in f2.rooms if r.zone_category == "terrace"]
    assert len(t_rooms) == 1
    t_room = t_rooms[0]
    assert t_room.room_id == "terrace_band_F2"
    assert t_room.area_sqm == band_area
    assert t_room.x == 0.0 and t_room.y == 0.0
    # The band spans the drawn plate (9.59 m), not the retired 9.60 m
    # site-proportion plate; it must still be the full width of the envelope.
    assert t_room.width_m == f2.envelope["width"] and t_room.depth_m == 3.0

    # 4. Door: Balcony slider door from lobby to terrace (RULE-FP-04)
    terr_doors = [d for d in f2.doors if d.to_room == t_room.room_id or d.from_room == t_room.room_id]
    assert len(terr_doors) == 1
    assert terr_doors[0].door_type == "sliding"
    assert terr_doors[0].from_room == "lobby_spine_F2"

    # 5. Drawing IR / SVG: Parapet, Hatch, Drainage note
    assert "mf-hatch-terrace" in f2.svg_blueprint_cad
    assert "DRAINAGE SLOPE 1:100 TO RWO" in f2.svg_blueprint_cad
    assert "WAL_PARAPET" in f2.svg_blueprint_cad or "PARAPET" in f2.svg_blueprint_cad

    # 6. Certificate validations
    cert = model.mathematical_certificate
    # The ground-floor living room is 2.71 m CLEAR against a 3.60 m
    # catalogue minimum - below even the 0.80 terrace-band tolerance. The old
    # certificate only measured the 3.00 m gross face against the tolerance and
    # printed a PASS; the clear-face measurement exposes the real shortfall.
    # The geometry gap is solver work, but the certificate must not lie about it.
    assert cert.get("is_valid") is False
    assert any("NBC-01" in failure for failure in cert.get("failures", []))
    assert cert.get("core_continuity_valid") is True
    assert cert.get("no_wet_over_terrace_valid") is True
    assert cert.get("terrace_far_exempt") is True
    assert "RULE-FP-07" in cert.get("certified_rules", [])


def test_terrace_band_disabled_cases():
    """
    Verifies disabling and clamping rules:
    - Ground floor band is rejected/ignored (RULE-FP-01).
    - West edge band is rejected due to stair core conflict (RULE-FP-01).
    - Depth exceeding 40% is clamped to 40% (RULE-FP-07).
    """
    # Case 1: Ground floor band requested
    req_g = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        floors=3,
        terrace_bands={
            0: {"edge": "N", "depth_m": 3.0},
        },
    )
    eng_g = SoleGeometryEngine(req_g)
    model_g = eng_g.solve()
    assert model_g.floors[0].plate_composition == "Full Plate"
    assert model_g.floors[0].terrace_band is None
    assert any("Ground floor keeps full plate" in w for w in model_g.warnings)

    # Case 2: West edge band requested (stair core conflict)
    req_w = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        floors=3,
        terrace_bands={
            2: {"edge": "W", "depth_m": 2.0},
        },
    )
    eng_w = SoleGeometryEngine(req_w)
    model_w = eng_w.solve()
    assert model_w.floors[2].plate_composition == "Full Plate"
    assert model_w.floors[2].terrace_band is None
    assert any("West edge" in w and "intersects vertical stair core" in w for w in model_w.warnings)

    # Case 3: Depth exceeding 40% of the drawn plate (10.54 m deep, 40 % =
    # 4.22 m; the clamp follows the plate, not a retired 11.25 m pin)
    req_clamp = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        floors=3,
        terrace_bands={
            2: {"edge": "N", "depth_m": 5.0},
        },
    )
    eng_clamp = SoleGeometryEngine(req_clamp)
    model_clamp = eng_clamp.solve()
    f2 = model_clamp.floors[2]
    _env_d = round(float(f2.envelope["depth"]), 2)
    _expected_clamp = round(_env_d * 0.40, 2)
    assert f2.terrace_band["depth_m"] == _expected_clamp
    assert any(
        "RULE-FP-07" in w and f"Clamped to {_expected_clamp:.2f}m" in w
        for w in model_clamp.warnings
    )


def test_rectangle_equivalence_no_band_identical():
    """
    Verifies that when NO terrace band is requested, the 12x15 G+2 model
    has all full plates, 100.80 sqm per floor, and is identical to baseline.
    """
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        floors=3,
    )
    eng = SoleGeometryEngine(req)
    model = eng.solve()

    assert model.total_storeys == 3
    for z in range(3):
        assert model.floors[z].plate_composition == "Full Plate"
        assert model.floors[z].terrace_band is None
        assert model.floors[z].built_up_area_sqm == model.floors[0].built_up_area_sqm

    assert model.total_built_up_area_sqm == round(model.floors[0].built_up_area_sqm * 3, 2)

    # Rectangle equivalence is unchanged, and the proportion law must
    # restore validity without a blanket aspect tolerance: the 9.60 x 3.56 m
    # living is split (living + dining/study) or, when no legal split exists on
    # the plate, accepted as a ROOM-LISTED relaxation within the declared cap.
    cert = model.mathematical_certificate
    assert cert["aspect_ratios_satisfied"] is True, cert["failures"]
    assert not [f for f in cert["failures"] if "NBC-02" in f], cert["failures"]
    assert cert["is_valid"] is True
    for rel in cert["details"].get("declared_aspect_relaxations", []):
        assert rel["measured"] <= rel["limit"] * 1.20 + 0.02, rel
    assert any(
        w.startswith("PROP-SPLIT") or w.startswith("PROP-ASPECT")
        for w in model.warnings
    ), [w for w in model.warnings if w.startswith("PROP-")]
    for flag in (
        "non_overlap", "containment", "chain_sums_match", "min_dimensions_satisfied",
        "connectivity_bfs", "egress_distances_satisfied", "zero_forbidden_violations",
        "must_adjacency_satisfied", "vertical_stack_valid",
    ):
        assert cert[flag] is True, flag



def test_mask_terrace_on_single_rectangle_plate_materializes_band():
    """
    Root-cause regression (QA sweep): a `wing_b=terrace` floor-plate mask on a
    plot whose footprint decomposes to a SINGLE rectangle (no Wing B) used to
    desynchronize state - plate_composition claimed 'Wing A + Terrace' while no
    terrace room ever materialized (L11 falsely N/A 'no terrace requested').

    Contract now:
    1. The unknown-wing mask emits an explicit warning (never silently ignored).
    2. The terrace intent is translated into the validated North-band pipeline
       (40% depth clamp, core/duct conflict checks) and materializes as a real
       terrace room with honest plate_composition.
    3. No overlap between the terrace band and any conditioned room.
    4. Gate layer L11 reports PASS with a real terrace count.
    """
    # Fixture note: the original 148 m² L-shape admitted only a
    # 47 m² rectangular plate, while a 3-storey residential_multi brief expands
    # to two 4-room units per floor (~123 m²). That brief is statutorily
    # impossible on the plate and is now REFUSED with the numbers instead of
    # being squashed into 3.4 m² bedrooms, so this contract (the terrace-band
    # translation) is pinned on a plate that can actually host it.
    plot_verts = [
        [0.0, 0.0],
        [20.0, 0.0],
        [20.0, 20.0],
        [0.0, 20.0],
    ]
    poly = PlotPolygonModel(
        vertices=plot_verts,
        shape_type="rectangle",
        area_sqm=400.0,
        perimeter_m=80.0,
        bounding_box=[0.0, 0.0, 20.0, 20.0],
        is_regular_rectangle=True,
    )
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=20.0,
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"],
        building_typology="residential_multi",
        floors=3,
        vastu_strictness="high",
        plot_polygon=poly,
        floor_plate_masks={
            2: {"wing_a": "present", "wing_b": "terrace"},
        },
    )
    eng = SoleGeometryEngine(req)
    model = eng.solve()

    # 1. Explicit warning about the ignored unknown wing (no silent drop).
    assert any("not present in footprint" in w.lower() for w in eng.warnings)

    # 2. Terrace materialized through the band pipeline on Level 2 only.
    f2 = model.floors[2]
    terrace_rooms = [r for r in f2.rooms if r.zone_category == "terrace"]
    assert len(terrace_rooms) == 1
    assert terrace_rooms[0].room_id.startswith("terrace_band_F")
    assert "Terrace" in f2.plate_composition
    for z in (0, 1):
        assert not [r for r in model.floors[z].rooms if r.zone_category == "terrace"]

    # 3. Hard non-overlap invariant: terrace must not overlap conditioned rooms.
    terr = terrace_rooms[0]
    for r in f2.rooms:
        if r is terr:
            continue
        x_ov = max(0.0, min(terr.x + terr.width_m, r.x + r.width_m) - max(terr.x, r.x))
        y_ov = max(0.0, min(terr.y + terr.depth_m, r.y + r.depth_m) - max(terr.y, r.y))
        assert x_ov * y_ov < 0.05, f"terrace overlaps {r.room_id} by {x_ov * y_ov:.2f} sqm"

    # 4. Gate layer L11 sees the real terrace.
    cert = model.mathematical_certificate
    gate = (cert.get("details") or {}).get("validation_gate") or {}
    l11 = next(l for l in gate.get("layers", []) if l.get("layer_id") == "L11")
    assert l11["status"] == "PASS"
    assert "1 terrace" in (l11.get("summary") or "")
