"""T3 ground-floor electrical service row.

The T3 ground plate used to draw one "MEP & Electrical" strip that absorbed the
whole technical programme.  On a wide three-storey plate that strip reached
35.5-46.3 m2 against the electrical room's 22 m2 placement maximum.  The
correction resolves the two separately declared spaces (electrical_room and
mep_room) inside the same service strip.  Wide plates split side-by-side; the
40x60 plate, where a full-depth MEP strip would breach its 2.0 aspect cap, is
split in depth and re-anchored after the furniture row repair.

These pins use the unchanged market-mix inputs.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

import pytest  # noqa: E402

from app.schemas.floorplan import FloorPlanRequest  # noqa: E402
from app.services.floorplan.strategy_escalation import _CACHE, solve_with_escalation  # noqa: E402
from app.services.plan_verdict import (  # noqa: E402
    CERTIFIED,
    compute_plan_verdict,
    plan_truth_labels,
)

PLOTS = {
    "rect18x24": {"w": 18.0, "d": 24.0},
    "rect20x20": {"w": 20.0, "d": 20.0},
    "rect30x40": {"w": 30.0, "d": 40.0},
    "rect40x60": {"w": 40.0, "d": 60.0},
}
TYPOLOGY = "T3_LARGE_COMPLEX"
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


def _request(case: str) -> FloorPlanRequest:
    typ_key, plot_key, floor_key = case.split("-")
    plot = PLOTS[plot_key]
    return FloorPlanRequest(
        plot_width_m=plot["w"],
        plot_depth_m=plot["d"],
        plot_polygon=None,
        building_typology=TYPOLOGY,
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


def _floor0(response):
    assert response.multi_storey is not None
    return next(floor for floor in response.multi_storey.floors if floor.floor_index == 0)


def _rooms(floor):
    return {room.room_id: room for room in floor.rooms}


def _room(floor, room_id: str):
    rooms = _rooms(floor)
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
    rooms = _rooms(floor)
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
    rooms = _rooms(floor)
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
