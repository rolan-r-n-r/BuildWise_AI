"""Compact T2 plate holds both unit programmes.

The canonical 12 x 15 apartment used to publish two units whose living rooms
were 11.7 / 14.5 m2 against a 16.0 m2 minimum. The earlier notes proposed
stacking the bath over the kitchen to free frontage, but that stack shares a
wall and is forbidden by the ontology's own HYG-02 law (foul room vs food
prep).  The plan implemented here survives the law: the stair moves to the
east flank, and the freed pocket beside the stair band carries Unit A's
bedroom and Unit B's bathroom.  Both unit rows then keep a full-width living
room and every room meets its catalogue gross minimum.
"""

from __future__ import annotations

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan

MIN_AREA = {"unit_living": 16.0, "unit_bed": 10.5, "unit_kitchen": 6.0, "unit_bath": 3.0}
MIN_WIDTH = {"unit_living": 3.40, "unit_bed": 3.00, "unit_kitchen": 1.80, "unit_bath": 1.20}


def _generate(width: float = 12.0, depth: float = 15.0, floors: int = 2,
              seed: str = "compact-t2"):
    return generate_floor_plan(FloorPlanRequest(
        plot_width_m=width,
        plot_depth_m=depth,
        building_typology="residential_apartment",
        floors=floors,
        vastu_strictness="high",
        ai_provider="mock",
        bypass_cache=True,
        seed=seed,
    ))


def _floor_rooms(response, floor_index: int = 0):
    return list(response.multi_storey.floors[floor_index].rooms or [])


def _units(rooms):
    found: dict[str, dict[str, object]] = {}
    for room in rooms:
        sid = getattr(room, "space_type_id", None)
        uid = getattr(room, "unit_id", None)
        if uid in ("Unit_A", "Unit_B") and sid in MIN_AREA:
            found.setdefault(uid, {})[sid] = room
    return found


def _touching(a, b, tol: float = 0.02) -> bool:
    overlap_x = min(a.x + a.width_m, b.x + b.width_m) - max(a.x, b.x)
    overlap_y = min(a.y + a.depth_m, b.y + b.depth_m) - max(a.y, b.y)
    return (abs(overlap_x) <= tol and overlap_y > 0.30) or (
        abs(overlap_y) <= tol and overlap_x > 0.30
    )


@pytest.mark.parametrize("floors", [1, 2, 4])
def test_compact_t2_units_meet_every_catalogue_gross_minimum(floors):
    response = _generate(floors=floors)
    assert response.multi_storey is not None

    for floor_index, floor in enumerate(response.multi_storey.floors):
        units = _units(floor.rooms or [])
        assert set(units) == {"Unit_A", "Unit_B"}, f"floor {floor_index}: {set(units)}"
        for uid, rooms in units.items():
            assert set(rooms) == set(MIN_AREA), f"{uid} floor {floor_index}: {sorted(rooms)}"
            for sid, room in rooms.items():
                assert room.area_sqm + 0.02 >= MIN_AREA[sid], (
                    f"{uid} {sid} area {room.area_sqm:.2f} < {MIN_AREA[sid]}"
                )
                assert min(room.width_m, room.depth_m) + 0.02 >= MIN_WIDTH[sid], (
                    f"{uid} {sid} clear {min(room.width_m, room.depth_m):.2f} "
                    f"< {MIN_WIDTH[sid]}"
                )


def test_compact_t2_certificate_audits_every_room_without_shortfalls():
    response = _generate(floors=2)
    cert = response.multi_storey.mathematical_certificate or {}
    details = cert.get("details") or {}

    assert cert.get("is_valid") is True
    assert cert.get("min_dimensions_satisfied") is True
    assert cert.get("aspect_ratios_satisfied") is True
    assert details.get("min_dimension_violations") == []
    assert details.get("aspect_violations") == []
    assert details.get("unverified_spaces") == []


def test_compact_t2_pocket_carries_bedroom_and_second_bath():
    response = _generate(floors=2)
    rooms = _floor_rooms(response)
    core = next(r for r in rooms if r.room_id.startswith("core_staircase"))
    bed_a = next(r for r in rooms if r.room_id.startswith("t2_unitA_bed"))
    bath_b = next(r for r in rooms if r.room_id.startswith("t2_unitB_bath"))

    band_top = core.y + core.depth_m
    for room in (bed_a, bath_b):
        assert core.y - 0.02 <= room.y <= band_top + 0.02
        assert room.y + room.depth_m <= band_top + 0.02

    # The pocket is fully used by the two nested rooms, not left as a foyer.
    assert not any(r.room_id.startswith("t2_amenity") for r in rooms)
    assert bed_a.x + bed_a.width_m <= bath_b.x + 0.02


def test_compact_t2_both_living_rooms_open_off_the_lobby():
    response = _generate(floors=2)
    rooms = _floor_rooms(response)
    lobby = next(r for r in rooms if r.room_id.startswith("lobby_spine"))
    units = _units(rooms)
    for uid in ("Unit_A", "Unit_B"):
        living = units[uid]["unit_living"]
        assert _touching(living, lobby), f"{uid} living does not meet the lobby"


def test_compact_t2_bath_never_shares_a_wall_with_the_kitchen():
    response = _generate(floors=2)
    for floor in response.multi_storey.floors:
        units = _units(list(floor.rooms or []))
        for uid in ("Unit_A", "Unit_B"):
            bath = units[uid]["unit_bath"]
            kitchen = units[uid]["unit_kitchen"]
            assert not _touching(bath, kitchen), f"{uid} bath shares a wall with its kitchen"


def test_compact_t2_rooms_do_not_overlap_or_leave_the_plate():
    response = _generate(floors=2)
    floors = response.multi_storey.floors
    env_w = max(r.x + r.width_m for r in floors[0].rooms)
    env_d = max(r.y + r.depth_m for r in floors[0].rooms)

    for floor_index, floor in enumerate(floors):
        rooms = floor.rooms
        for i, a in enumerate(rooms):
            assert a.x >= -0.01 and a.y >= -0.01
            assert a.x + a.width_m <= env_w + 0.01
            assert a.y + a.depth_m <= env_d + 0.01
            for b in rooms[i + 1:]:
                overlap_x = min(a.x + a.width_m, b.x + b.width_m) - max(a.x, b.x)
                overlap_y = min(a.y + a.depth_m, b.y + b.depth_m) - max(a.y, b.y)
                assert overlap_x <= 0.01 or overlap_y <= 0.01, (
                    f"floor {floor_index}: {a.room_id} overlaps {b.room_id}"
                )


def test_compact_t2_wet_rooms_stack_across_every_storey():
    response = _generate(floors=4)
    floors = response.multi_storey.floors
    for prefix in ("t2_unitA_bath", "t2_unitB_bath"):
        positions = set()
        for floor in floors:
            room = next(r for r in floor.rooms if r.room_id.startswith(prefix))
            positions.add((round(room.x, 2), round(room.y, 2),
                           round(room.width_m, 2), round(room.depth_m, 2)))
        assert len(positions) == 1, f"{prefix} moved between storeys: {positions}"


def test_compact_t2_is_deterministic_for_the_same_seed():
    first = _generate(floors=2, seed="deterministic-compact-t2")
    second = _generate(floors=2, seed="deterministic-compact-t2")

    def snapshot(response):
        return [
            (r.room_id, r.x, r.y, r.width_m, r.depth_m, r.area_sqm)
            for floor in response.multi_storey.floors
            for r in floor.rooms
        ]

    assert snapshot(first) == snapshot(second)


def test_row_plan_is_used_whenever_the_plate_rows_fit():
    """The pocket plan must not leak onto plates whose rows already fit.

    Plate policy: coverage is a ceiling, not a target, so an oversized plot is
    handed a programme-sized plate (20 x 20 -> 122.75 m2
    against a 240 m2 coverage cap).  On a plate whose rows genuinely fit, the
    historical row plan (with its t2_amenity strip) is still the plan; the
    pocket plan is reserved for plates the row cannot hold.
    """
    response = _generate(width=13.0, depth=17.0, floors=2)
    rooms = _floor_rooms(response)
    assert any(r.room_id.startswith("t2_amenity") for r in rooms)
    core = next(r for r in rooms if r.room_id.startswith("core_staircase"))
    bed_a = next(r for r in rooms if r.room_id.startswith("t2_unitA_bed"))
    assert bed_a.y + bed_a.depth_m <= core.y + 0.02


def test_oversized_t2_plot_gets_a_programme_sized_plate_not_the_coverage_cap():
    """Coverage is a ceiling: a 400 m2 plot must not stretch two units.

    Filling the 240 m2 cap with a 122.7 m2 brief stretched every unit past its
    catalogue band and is what pushed the T2 market-mix plates off the
    certificate.  The plate now follows the programme; both units stay.
    """
    response = _generate(width=20.0, depth=20.0, floors=2)
    plate = response.site_plan.footprint.area_sqm
    assert plate is not None
    assert plate <= 0.60 * 20.0 * 20.0 - 1.0
    assert plate <= 140.0
    units = _units(_floor_rooms(response))
    assert set(units) == {"Unit_A", "Unit_B"}


def test_compact_t2_gate_covers_all_layers_and_programme():
    response = _generate(floors=2)
    gate = response.multi_storey.validation_gate or {}
    layer_ids = [layer.get("layer_id") for layer in gate.get("layers", [])]
    assert layer_ids == [f"L{i}" for i in range(1, 17)]
    l15 = next(layer for layer in gate["layers"] if layer["layer_id"] == "L15")
    assert l15["status"] == "PASS"
    assert gate.get("overall_status") in ("PASS", "WARN")
