"""Proportion-law enforcement.

These tests pin the *solver behaviour* the ontology data declares:

* hard aspect bands split a room along its long axis (never a silent stretch);
* hard ceilings split into the declared ``split_into`` types;
* the ideal band only WARNs;
* an unresolvable breach is named, never passed;
* an accepted aspect relaxation is room-stamped, capped and certificate-listed;
* an elongated plate selects the spine-corridor typology;
* surplus plate is spent on the declared upgrade ladder.
"""

from __future__ import annotations

import pytest
from shapely.geometry import box

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.multi_floor_plan import MultiFloorRoomRectangle
from app.services.floorplan import proportion_law as pl
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.ontology import ONTOLOGY


def _room(room_id: str, width: float, depth: float, *, zone_category: str = "private") -> MultiFloorRoomRectangle:
    return MultiFloorRoomRectangle(
        room_id=room_id,
        room_name=room_id.replace("_", " ").title(),
        floor_index=0,
        x=0.0,
        y=0.0,
        width_m=width,
        depth_m=depth,
        area_sqm=round(width * depth, 2),
        zone="S",
        zone_category=zone_category,
        vastu_compliant=True,
        is_vertical_core=False,
        requires_exterior_wall=True,
        aspect_ratio=round(max(width, depth) / min(width, depth), 2),
    )


def _aspect(room) -> float:
    return max(room.width_m, room.depth_m) / min(room.width_m, room.depth_m)


def test_hard_aspect_is_split_into_legal_parts_and_area_is_conserved():
    living = ONTOLOGY.get_space("living")
    room = _room("living_F0", 9.6, 3.56, zone_category="public")
    original_area = room.area_sqm
    rooms = [room]

    audit = pl.enforce_proportion_law(
        rooms, floor_index=0, typology="T1_SINGLE_FAMILY",
        envelope={"width": 9.6, "depth": 11.25},
    )

    assert len(rooms) == 2
    assert audit.splits == 1
    for part in rooms:
        assert _aspect(part) <= living.max_aspect_ratio + 0.02, part.room_id
        assert "PROP-SPLIT" in part.applied_rules or "PROP-ASPECT" in part.applied_rules
    assert sum(r.area_sqm for r in rooms) == pytest.approx(original_area, abs=0.02)
    assert any(line.startswith("PROP-SPLIT: living_F0") for line in audit.log)


def test_ceiling_overflow_without_a_legal_move_is_disclosed():
    """A 25 m² square kitchen has no legal route: a 5 x 1 m "store" would be a
    5:1 strip, and a split part cannot fit the utility ceiling.  It is named,
    not filled with an invented room."""
    room = _room("kitchen_F0", 5.0, 5.0, zone_category="service")
    rooms = [room]

    audit = pl.enforce_proportion_law(rooms, floor_index=0, typology="T1_SINGLE_FAMILY")

    assert len(rooms) == 1
    assert audit.adjuncts == 0
    assert any("PROP-CEILING: kitchen_F0" in line for line in audit.log)


def test_ceiling_adjunct_is_capped_by_its_own_declared_ceiling():
    """An over-size pooja room may shed a store, but never more than the store's
    own 8 m² ceiling - and the adjunct must itself be inside its band."""
    room = _room("puja_F0", 2.4, 6.0, zone_category="service")
    rooms = [room]

    audit = pl.enforce_proportion_law(rooms, floor_index=0, typology="T1_SINGLE_FAMILY")

    assert audit.adjuncts >= 1
    added = [r for r in rooms if r is not room]
    assert added
    store = ONTOLOGY.get_space("store")
    for part in added:
        assert part.area_sqm <= store.area_ceiling_sqm + 0.02, (part.room_id, part.area_sqm)
        assert part.area_sqm >= store.min_area_sqm - 0.02, (part.room_id, part.area_sqm)
        aspect = max(part.width_m, part.depth_m) / min(part.width_m, part.depth_m)
        assert aspect <= store.max_aspect_ratio + 0.02, (part.room_id, aspect)
    assert sum(r.area_sqm for r in rooms) == pytest.approx(14.4, abs=0.02)


def test_ideal_band_is_warn_only_and_moves_no_geometry():
    room = _room("living_F0", 4.6, 3.0, zone_category="public")  # 1.53 vs ideal 1.20, hard 1.80
    rooms = [room]

    audit = pl.enforce_proportion_law(rooms, floor_index=0, typology="T1_SINGLE_FAMILY")

    assert len(rooms) == 1
    assert audit.splits == 0
    assert audit.ideal_warnings == 1
    assert rooms[0].width_m == 4.6 and rooms[0].depth_m == 3.0


def test_unresolvable_breach_is_named_never_passed():
    # Short side 2.2 m is below 0.85 x the 3.60 m living minimum, so no split
    # can legalise it.  The audit must name it.
    room = _room("living_F0", 12.0, 2.2, zone_category="public")
    audit = pl.enforce_proportion_law([room], floor_index=0, typology="T1_SINGLE_FAMILY")

    assert audit.hard_violations
    assert any("living_F0" in line for line in audit.hard_violations)


def test_relaxation_is_capped_and_room_stamped():
    within = _room("kitchen_F0", 2.35, 4.96, zone_category="service")  # 2.11 vs 1.80 = 1.17x
    audit = pl.enforce_proportion_law([within], floor_index=0, typology="T1_SINGLE_FAMILY")
    assert audit.aspect_relaxations == 1
    assert any(rel.get("rule_id") == "PROP-ASPECT" for rel in within.relaxations)
    assert not audit.hard_violations

    beyond = _room("kitchen_F1", 1.9, 6.0, zone_category="service")  # 3.16 vs 1.80 = 1.76x
    audit2 = pl.enforce_proportion_law([beyond], floor_index=1, typology="T1_SINGLE_FAMILY")
    assert audit2.hard_violations
    assert not any(rel.get("rule_id") == "PROP-ASPECT" for rel in beyond.relaxations)


def test_spine_threshold_selects_the_spine_corridor_identity():
    lobby = _room("lobby_spine_F0", 2.0, 9.0, zone_category="circulation")
    audit = pl.enforce_proportion_law(
        [lobby], floor_index=0, typology="T3_LARGE_COMPLEX",
        envelope={"width": 24.0, "depth": 8.0},
    )
    assert audit.spine_selected is True
    assert lobby.space_type_id == "spine_corridor"
    assert "PROP-SPINE-01" in lobby.applied_rules
    assert any(line.startswith("PROP-SPINE-01") for line in audit.log)

    short_lobby = _room("lobby_spine_F1", 2.0, 4.0, zone_category="circulation")
    audit2 = pl.enforce_proportion_law(
        [short_lobby], floor_index=1, typology="T3_LARGE_COMPLEX",
        envelope={"width": 12.0, "depth": 10.0},
    )
    assert audit2.spine_selected is False
    assert short_lobby.space_type_id is None


def test_surplus_ladder_carves_a_declared_upgrade():
    # Both rooms fill the south strip, so the surplus is one clean rectangle.
    rooms = [
        _room("living_F0", 6.0, 4.0, zone_category="public"),
        _room("bath_1_F0", 6.0, 4.0, zone_category="service").model_copy(
            update={"x": 6.0}
        ),
    ]
    plate = box(0.0, 0.0, 12.0, 10.0)
    logs = pl.carve_surplus_upgrade(
        rooms, plate, floor_index=0, typology="T1_SINGLE_FAMILY"
    )

    assert logs and logs[0].startswith("PROP-LADDER:")
    carved = [r for r in rooms if r.room_id.startswith("prop_upgrade_")]
    assert len(carved) == 1
    step_types = {s.space_type_id for s in ONTOLOGY.upgrade_ladder("T1_SINGLE_FAMILY")}
    assert carved[0].space_type_id in step_types
    assert carved[0].area_sqm >= ONTOLOGY.get_space(carved[0].space_type_id).min_area_sqm - 0.02


def test_generation_splits_instead_of_stretching_and_stays_certified():
    resp = generate_floor_plan(FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        floors=3,
        bypass_cache=True,
    ))
    cert = resp.multi_storey.mathematical_certificate

    assert cert["aspect_ratios_satisfied"] is True, cert["failures"]
    assert cert["is_valid"] is True, cert["failures"]
    # The guarantee is "split instead of stretching": a PROP-SPLIT is the proof
    # when a band is too long, but a plate whose bands already fit every room
    # needs none.  Either a split ran, or no room is outside its band (the loop
    # below is the stronger, geometry-measured form of the same claim).
    _stretched_unlisted = []
    for floor in resp.multi_storey.floors:
        for room in floor.rooms:
            if room.zone_category in ("circulation", "terrace"):
                continue
            spec = ONTOLOGY.get_space(room.space_type_id or room.room_id)
            if spec is None or _aspect(room) <= spec.max_aspect_ratio + 0.02:
                continue
            listed = any(
                str(rel.get("rule_id")) == "PROP-ASPECT" for rel in (room.relaxations or [])
            )
            if not listed:
                _stretched_unlisted.append(room.room_id)
    assert any(w.startswith("PROP-SPLIT:") for w in resp.warnings) or not _stretched_unlisted, (
        f"rooms stretched past their band with no split and no listing: {_stretched_unlisted}"
    )
    for floor in resp.multi_storey.floors:
        for room in floor.rooms:
            if room.zone_category in ("circulation", "terrace"):
                continue
            spec = ONTOLOGY.get_space(room.space_type_id or room.room_id)
            if spec is None:
                continue
            listed = any(
                str(rel.get("rule_id")) == "PROP-ASPECT" for rel in (room.relaxations or [])
            )
            if _aspect(room) > spec.max_aspect_ratio + 0.02 and not listed:
                pytest.fail(f"{room.room_id} 1:{_aspect(room):.2f} exceeds its band unlisted")
            if listed:
                assert _aspect(room) <= spec.max_aspect_ratio * pl.ASPECT_RELAXATION_CAP + 0.02
    for rel in cert["details"].get("declared_aspect_relaxations", []):
        assert rel["measured"] <= rel["limit"] * pl.ASPECT_RELAXATION_CAP + 0.02


def _l_plot_polygon():
    from app.schemas.floorplan import PlotPolygonModel
    return PlotPolygonModel(
        vertices=[(0.0, 0.0), (8.1, 0.0), (8.1, 8.1), (18.0, 8.1), (18.0, 18.0), (0.0, 18.0)],
        shape_type="l_shape",
        has_curved_edges=False,
        is_regular_rectangle=False,
        area_sqm=243.81,
        perimeter_m=0.0,
        bounding_box=(0.0, 0.0, 18.0, 18.0),
    )


def _touching(a, b, *, min_run: float = 0.5) -> bool:
    v = (abs((a.x + a.width_m) - b.x) < 0.05 or abs((b.x + b.width_m) - a.x) < 0.05) and (
        min(a.y + a.depth_m, b.y + b.depth_m) - max(a.y, b.y) >= min_run
    )
    h = (abs((a.y + a.depth_m) - b.y) < 0.05 or abs((b.y + b.depth_m) - a.y) < 0.05) and (
        min(a.x + a.width_m, b.x + b.width_m) - max(a.x, b.x) >= min_run
    )
    return bool(v or h)


@pytest.mark.parametrize("typology", ["residential_multi", "commercial_office"])
def test_l_plate_three_storeys_is_solved_and_ladder_rooms_are_hosted(typology):
    """The L plate with a lift used to raise UnboundLocalError, and the surplus
    ladder used to carve a doorless island inside a free ring.  Both are
    regressions: this pins a solved three-storey L and a hosted ladder room."""
    resp = generate_floor_plan(FloorPlanRequest(
        plot_width_m=18.0,
        plot_depth_m=18.0,
        building_typology=typology,
        floors=3,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        bypass_cache=True,
        ai_provider="mock",
        seed="42",
        plot_polygon=_l_plot_polygon(),
    ))
    assert resp.multi_storey is not None, resp.warnings
    cert = resp.multi_storey.mathematical_certificate
    assert not any("prop_upgrade_" in str(f) for f in cert["failures"]), cert["failures"]

    ground = resp.multi_storey.floors[0]
    ladder = [r for r in ground.rooms if r.room_id.startswith("prop_upgrade_")]
    for room in ladder:
        assert any(
            _touching(room, other) for other in ground.rooms if other is not room
        ), f"{room.room_id} is an island: no shared wall"


def test_land07_never_furnishes_the_wing_link_corridor():
    resp = generate_floor_plan(FloorPlanRequest(
        plot_width_m=18.0,
        plot_depth_m=18.0,
        building_typology="residential_single",
        floors=1,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        bypass_cache=True,
        ai_provider="mock",
        seed="42",
        plot_polygon=_l_plot_polygon(),
    ))
    fp = resp.site_plan.footprint
    assert fp.corridors
    ground = resp.multi_storey.floors[0]
    for corr in fp.corridors:
        from shapely.geometry import box as shp_box
        corr_poly = shp_box(
            corr.x - fp.x, corr.y - fp.y,
            corr.x - fp.x + corr.width_m, corr.y - fp.y + corr.depth_m,
        )
        for room in ground.rooms:
            room_poly = shp_box(room.x, room.y, room.x + room.width_m, room.y + room.depth_m)
            if room.room_id.startswith("dead_corner"):
                assert room_poly.intersection(corr_poly).area <= 0.01, (
                    f"{room.room_id} was poured onto the link corridor"
                )
