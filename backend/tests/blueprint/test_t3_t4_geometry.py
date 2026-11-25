"""T3/T4 geometry and T3 service-row pins.

The market matrix left T3 at 2/13 and T4 at 4/8.  The failures were
not wedge geometry: on the regular plates the template either reserved a
front band shallower than the reception's declared relaxation floor (T3), or
measured solver rooms against the placement catalogue's generic 16 m2
fragment instead of their resolved space type (T3 suites, T4 mezzanine), or
left a sub-metre utility strip on a T4 upper floor.

For the T3 ground-floor electrical service row: wide plates resolve the two
separately declared spaces (electrical_room and mep_room) inside the same
service strip (side-by-side, or depth-stacked on 40x60).

Every pin below uses the unchanged market-mix input (same seed, programme,
coverage and plausibility labels) so a geometry change cannot pass by editing
the brief.
"""
from __future__ import annotations

import re

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.site_plan import PlotPolygonModel
from app.services.floorplan.strategy_escalation import _CACHE, solve_with_escalation
from app.services.plan_verdict import (
    CERTIFIED,
    compute_plan_verdict,
    plan_truth_labels,
    plan_verdict_reasons,
)

PLOTS = {
    "rect12x15": {"w": 12.0, "d": 15.0},
    "rect15x18": {"w": 15.0, "d": 18.0},
    "rect18x24": {"w": 18.0, "d": 24.0},
    "rect20x20": {"w": 20.0, "d": 20.0},
    "nearrect15x18": {
        "w": 15.0,
        "d": 18.0,
        "polygon": [[0, 0], [15, 0], [15, 14], [11, 14], [11, 18], [0, 18]],
    },
    "rect30x40": {"w": 30.0, "d": 40.0},
    "rect40x60": {"w": 40.0, "d": 60.0},
}
TYPOLOGIES = {"T3": "T3_LARGE_COMPLEX", "T4": "T4_WAREHOUSE"}


def _polygon(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    area = 0.0
    perimeter = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        area += x1 * y2 - x2 * y1
        perimeter += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    return PlotPolygonModel(
        vertices=points,
        shape_type="l_shape",
        area_sqm=round(abs(area) / 2.0, 2),
        perimeter_m=round(perimeter, 2),
        bounding_box=[min(xs), min(ys), max(xs), max(ys)],
        is_regular_rectangle=False,
    )


def _request(case: str) -> FloorPlanRequest:
    typ_key, plot_key, floor_key = case.split("-")
    plot = PLOTS[plot_key]
    return FloorPlanRequest(
        plot_width_m=plot["w"],
        plot_depth_m=plot["d"],
        plot_polygon=_polygon(plot["polygon"]) if plot.get("polygon") else None,
        building_typology=TYPOLOGIES[typ_key],
        floors=int(floor_key[1:]),
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed=f"market7-{case}",
        ai_provider="mock",
        bypass_cache=True,
        confirm_dwelling_deficit=True,
    )


def _solve(case: str):
    _CACHE.clear()
    return solve_with_escalation(_request(case))


def _floors(response):
    if response.multi_storey is None:
        return []
    return list(response.multi_storey.floors)


def _rooms(response):
    return [room for floor in _floors(response) for room in floor.rooms]


def _room(response, room_id: str):
    matches = [room for room in _rooms(response) if room.room_id == room_id]
    assert matches, f"{room_id} not drawn"
    return matches[0]


_ROOM_MAX = re.compile(r"is\s+([\d.]+)\s*m²,\s*above its\s+([\d.]+)\s*m²\s+catalogue maximum")


def _assert_no_beyond_cap_max(response):
    for row in response.warnings:
        match = _ROOM_MAX.search(str(row))
        if match:
            measured, ceiling = float(match.group(1)), float(match.group(2))
            assert measured / ceiling <= 1.40 + 1e-9, row


# ---------------------------------------------------------------------------
# Improved cases: the seven market-mix verdicts that moved to CERTIFIED.
# ---------------------------------------------------------------------------

IMPROVED = [
    "T3-rect12x15-F1",
    "T3-rect18x24-F1",
    "T3-rect30x40-F1",
    "T4-rect18x24-F3",
    "T4-rect20x20-F3",
    "T4-rect30x40-F3",
    "T4-rect40x60-F3",
]


@pytest.mark.parametrize("case", IMPROVED)
def test_improved_t3_t4_case_certifies_with_a_valid_certificate(case):
    response = _solve(case)
    dump = response.model_dump()
    assert compute_plan_verdict(dump) == CERTIFIED, plan_verdict_reasons(dump)[:4]
    assert response.multi_storey is not None
    cert = dump.get("mathematical_certificate") or {}
    assert cert.get("is_valid") is True
    assert not cert.get("failures")
    assert not plan_truth_labels(dump)["unresolved_breaches"]
    _assert_no_beyond_cap_max(response)


# ---------------------------------------------------------------------------
# T3 ground floor: the front band is geometry, not a disclaimer.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["T3-rect12x15-F1", "T3-rect18x24-F1", "T3-rect30x40-F1"])
def test_t3_front_band_clears_the_reception_floor(case):
    response = _solve(case)
    reception = _room(response, "reception_F0")
    clear_face = min(float(reception.width_m), float(reception.depth_m))
    # The certificate's declared relaxation floor is 0.85 x 4.00 = 3.40 m
    # clear.  The old 3.23 m band failed it outright; the reserved band must
    # now leave the room above that floor, with the remaining relaxation
    # printed rather than hidden.
    assert clear_face >= 3.40, f"reception clear face {clear_face:.2f} m"
    assert not any(
        row.startswith("PROP-HARD") and "reception_F0" in row for row in response.warnings
    )


def test_t3_front_band_preserves_the_service_row_minima():
    """The reception fix may not trade one squeeze for another."""
    response = _solve("T3-rect12x15-F1")
    for room_id, min_area in (
        ("server_room_F0", 10.0),
        ("electrical_room_F0", 6.0),
        ("t3_sanitary_F0", 6.0),
    ):
        room = _room(response, room_id)
        assert float(room.area_sqm) >= min_area * 0.85 - 0.05, (room_id, room.area_sqm)
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED


def test_t3_compact_plate_failure_is_named_not_hidden():
    """The two compact plates still fail, and they fail on the server face.

    A 108-109 m2 plate cannot hold a 4.0 m reception face, a 2.5 m clear
    server face and the remaining service row at once.  The reception must not
    be the blocker any more; the honest residual is the server clear width.
    """
    for case in ("T3-rect20x20-F1", "T3-nearrect15x18-F1"):
        response = _solve(case)
        reasons = " ".join(plan_verdict_reasons(response.model_dump()))
        assert "reception_F0" not in reasons, (case, reasons[:300])
        assert "server_room_F0" in reasons, (case, reasons[:300])
        assert compute_plan_verdict(response.model_dump()) != CERTIFIED


def test_t3_three_storey_plate_short_is_not_promoted():
    """A 162 m2 plate against a 190 m2 programme stays a named shortfall.

    The programme figure is 189.8 m2, not the 189.2 m2 pinned before the
    protected-stair capacity fix: multi-family flights widened from 1.25 m to
    1.30 m so the stair can carry its occupant load, and the wider stair box
    is part of the programme need.  The verdict and the named shortfall are
    unchanged; only the measured need moved with the geometry.
    """
    response = _solve("T3-rect15x18-F3")
    assert compute_plan_verdict(response.model_dump()) == "NOT-CERTIFIED-FAIL-STAMP"
    text = " ".join(response.warnings)
    assert "PLATE-SHORT" in text
    assert "PROGRAMME-DEFICIT" in text
    assert "189.8" in text


# ---------------------------------------------------------------------------
# T4 upper floor: no sub-metre utility strip; mezzanine bands are read from
# the resolved ontology type, not the 16 m2 placement fragment.
# ---------------------------------------------------------------------------


def test_t4_upper_floor_has_no_submetre_utility_sliver():
    response = _solve("T4-rect20x20-F3")
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED
    upper = [f for f in _floors(response) if f.floor_index > 0]
    assert upper
    for floor in upper:
        ids = {room.room_id for room in floor.rooms}
        assert "t4_util_west_F1" not in ids and "t4_util_west_F2" not in ids
        for room in floor.rooms:
            assert min(float(room.width_m), float(room.depth_m)) >= 1.0 - 1e-9, (
                room.room_id,
                room.width_m,
                room.depth_m,
            )


def test_t4_mezzanine_is_measured_against_its_own_ceiling():
    """A 76 m2 archive deck is legal against 1:4.0 / 60 m2, not a 16 m2 row."""
    response = _solve("T4-rect20x20-F3")
    deck = next(room for room in _rooms(response) if room.room_id == "t4_deck_F1")
    assert float(deck.area_sqm) > 16.0
    assert float(deck.area_sqm) <= 60.0 * 1.40
    assert not any("t4_deck_F1" in row and "16.0 m² catalogue" in row for row in response.warnings)
    catwalk = next(room for room in _rooms(response) if room.room_id == "t4_catwalk_F1")
    assert float(catwalk.area_sqm) > 16.0
    assert not any("t4_catwalk_F1" in row and "16.0 m² catalogue" in row for row in response.warnings)


# ---------------------------------------------------------------------------
# Cross-typology controls: no churn.
# ---------------------------------------------------------------------------


def test_t4_ground_floor_chain_is_unchanged():
    response = _solve("T4-rect18x24-F1")
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED
    for room_id in ("t4_dock_bay_F0", "t4_dispatch_F0", "t4_storage_bay_F0"):
        assert _room(response, room_id) is not None


def test_t2_control_is_unchanged():
    """The shared catalogue fallback must not demote a certified T2 plan."""
    req = FloorPlanRequest(
        plot_width_m=15.0,
        plot_depth_m=18.0,
        building_typology="T2_FAMILY_APARTMENT",
        floors=1,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="market7-T2-rect15x18-F1",
        ai_provider="mock",
        bypass_cache=True,
        confirm_dwelling_deficit=True,
    )
    _CACHE.clear()
    response = solve_with_escalation(req)
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED


# ---------------------------------------------------------------------------
# T3 ground-floor electrical service row
# ---------------------------------------------------------------------------

TARGETS = [
    "T3-rect18x24-F3",
    "T3-rect20x20-F3",
    "T3-rect30x40-F3",
    "T3-rect40x60-F3",
]
SERVICE_IDS = (
    "t3_sanitary_F0",
    "t3_service_spine_F0",
    "electrical_room_F0",
    "mep_room_F0",
    "server_room_F0",
)


def _floor0(response):
    assert response.multi_storey is not None
    return next(floor for floor in response.multi_storey.floors if floor.floor_index == 0)


def _floor_rooms(floor):
    return {room.room_id: room for room in floor.rooms}


def _floor_room(floor, room_id: str):
    rooms = _floor_rooms(floor)
    assert room_id in rooms, f"{room_id} not drawn"
    return rooms[room_id]


def _assert_no_overlap_and_contained(floor):
    envelope = floor.envelope or {}
    width = float(envelope.get("width", 0.0))
    depth = float(envelope.get("depth", 0.0))
    rooms = list(floor.rooms)
    for index, left in enumerate(rooms):
        assert left.x >= -0.02 and left.y >= -0.02, left.room_id
        assert left.x + left.width_m <= width + 0.02, left.room_id
        assert left.y + left.depth_m <= depth + 0.02, left.room_id
        for right in rooms[index + 1:]:
            overlap_x = max(
                0.0,
                min(left.x + left.width_m, right.x + right.width_m)
                - max(left.x, right.x),
            )
            overlap_y = max(
                0.0,
                min(left.y + left.depth_m, right.y + right.depth_m)
                - max(left.y, right.y),
            )
            assert overlap_x * overlap_y < 0.05, (left.room_id, right.room_id)


@pytest.mark.parametrize("case", TARGETS)
def test_t3_electrical_and_mep_are_separate_catalogue_rooms(case):
    response = _solve(case)
    dump = response.model_dump()
    assert compute_plan_verdict(dump) == CERTIFIED
    cert = dump.get("mathematical_certificate") or {}
    assert cert.get("is_valid") is True
    assert not cert.get("failures")
    assert not plan_truth_labels(dump)["unresolved_breaches"]

    floor = _floor0(response)
    rooms = _floor_rooms(floor)
    for required in (
        "reception_F0",
        "visitor_lounge_F0",
        "conference_room_F0",
        "t3_sanitary_F0",
        "server_room_F0",
        "electrical_room_F0",
        "mep_room_F0",
    ):
        assert required in rooms, (case, required, sorted(rooms))

    electrical = rooms["electrical_room_F0"]
    mep = rooms["mep_room_F0"]
    server = rooms["server_room_F0"]
    assert (electrical.space_type_id or "") == "electrical_room"
    assert (mep.space_type_id or "") == "mep_room"
    assert "electrical" in electrical.room_name.lower(), electrical.room_name
    assert "mep" in mep.room_name.lower(), mep.room_name
    assert electrical.area_sqm <= 22.0 + 0.05, (case, electrical.area_sqm)
    assert mep.area_sqm <= 20.0 + 0.05, (case, mep.area_sqm)
    assert server.area_sqm <= 28.0 + 0.05, (case, server.area_sqm)
    for room in (electrical, mep, server):
        assert min(room.width_m, room.depth_m) >= 2.0 - 0.02, (
            case,
            room.room_id,
            room.width_m,
            room.depth_m,
        )
    # The split must be a real repartition of the service strip, not an
    # independently drawn box with a gap or an overlap.
    san = rooms["t3_sanitary_F0"]
    spine = rooms["t3_service_spine_F0"]
    assert abs((san.x + san.width_m) - spine.x) <= 0.02
    assert abs((spine.x + spine.width_m) - electrical.x) <= 0.02
    if mep.x > electrical.x + 0.02:
        # Side-by-side: one full-depth row, west to east.
        assert abs(electrical.y - mep.y) <= 0.02
        assert abs(electrical.depth_m - mep.depth_m) <= 0.02
        assert abs((electrical.x + electrical.width_m) - mep.x) <= 0.02
        assert abs((mep.x + mep.width_m) - server.x) <= 0.02
    else:
        # Depth-stacked: the block keeps the full strip width and sits between
        # the repaired spine and the server, electrical south / MEP north.
        assert abs(electrical.x - mep.x) <= 0.02
        assert abs(electrical.width_m - mep.width_m) <= 0.02
        assert abs((electrical.y + electrical.depth_m) - mep.y) <= 0.02
        assert abs((electrical.depth_m + mep.depth_m) - server.depth_m) <= 0.02
        assert abs((electrical.x + electrical.width_m) - server.x) <= 0.02
    _assert_no_overlap_and_contained(floor)

    # Every service room must remain accessible; the row is a technical suite,
    # so a door to an adjacent service room or the spine is sufficient.
    door_rooms = {
        endpoint
        for door in floor.doors
        for endpoint in (door.from_room, door.to_room)
    }
    for room_id in ("electrical_room_F0", "mep_room_F0", "server_room_F0"):
        assert room_id in door_rooms, (case, room_id, sorted(door_rooms))

    technical_overages = [
        row
        for row in response.warnings
        if "ROOM-MAX" in str(row)
        and any(
            room_id in str(row)
            for room_id in ("electrical_room_F0", "mep_room_F0", "server_room_F0")
        )
    ]
    assert not technical_overages, (case, technical_overages)
    assert not any(str(row).startswith("PROP-HARD") for row in response.warnings), (
        case,
        [row for row in response.warnings if str(row).startswith("PROP-HARD")],
    )
    for room_id in ("electrical_room_F0", "mep_room_F0"):
        assert not any(
            f"PROP-CEILING: {room_id}" in str(row) for row in response.warnings
        ), (case, room_id)


def test_t3_40x60_uses_depth_stacked_block_when_row_split_breaches_mep_aspect():
    """The 40x60 strip cannot hold two full-depth compliant rooms.

    A full-depth MEP strip that meets the 20 m2 cap is 1:3.85, beyond its 2.0
    aspect cap; the width that meets the aspect cap is over 20 m2.  The engine
    therefore stacks the two rooms in depth after the furniture repair has
    finalised the sanitary/spine width, keeping both inside their catalogue
    bands and the server at its 3.5 m allocation.
    """
    response = _solve("T3-rect40x60-F3")
    floor = _floor0(response)
    rooms = _floor_rooms(floor)
    electrical = rooms["electrical_room_F0"]
    mep = rooms["mep_room_F0"]
    server = rooms["server_room_F0"]
    spine = rooms["t3_service_spine_F0"]
    assert (electrical.space_type_id or "") == "electrical_room"
    assert (mep.space_type_id or "") == "mep_room"
    assert abs(electrical.x - mep.x) <= 0.02
    assert abs(electrical.width_m - mep.width_m) <= 0.02
    assert abs((electrical.y + electrical.depth_m) - mep.y) <= 0.02
    assert abs((electrical.depth_m + mep.depth_m) - server.depth_m) <= 0.02
    assert abs((spine.x + spine.width_m) - electrical.x) <= 0.02
    assert abs((electrical.x + electrical.width_m) - server.x) <= 0.02
    assert electrical.area_sqm <= 22.0 + 0.05
    assert mep.area_sqm <= 20.0 + 0.05
    assert server.width_m == pytest.approx(3.50, abs=0.02)
    cert = response.model_dump().get("mathematical_certificate") or {}
    assert cert.get("is_valid") is True
    assert not cert.get("failures")
    assert not plan_truth_labels(response.model_dump())["unresolved_breaches"]
    assert not any(
        "ROOM-MAX: electrical_room_F0" in str(row) for row in response.warnings
    )
    assert not any("ROOM-MAX: mep_room_F0" in str(row) for row in response.warnings)
    _assert_no_overlap_and_contained(floor)
