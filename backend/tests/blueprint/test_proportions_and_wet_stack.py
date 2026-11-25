"""Room proportion in the band solver, and wet-stack honesty.

Contracts for room proportions and wet-stack alignment:

* room aspect ratios were only *scored*, never solved for, so a 23 m wide band
  produced 1:4.8 bedrooms and 47 m² bathrooms;
* cross-floor wet alignment relied on every storey having the same programme,
  while ``VERT-01-WET-STACK-ALIGN`` was stamped on every wet room regardless.

These tests pin the solver-side answers: frontage is allocated up to each
space's catalogue proportion, a band is split so its rooms can fill it, and a
wet room only claims VERT-01 when it measurably sits over one below.
"""

from __future__ import annotations

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan import constrained_solver as cs
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.ontology import ONTOLOGY

PLATES = [(12.0, 18.0), (13.0, 20.0), (10.0, 15.0), (23.0, 14.0)]
PROFILES = [None, "max_area", "max_vastu", "max_light_vent"]
ROOMS_1 = ["living", "kitchen", "master_bed", "bath_1", "dining"]
ROOMS_2 = ["living", "kitchen", "master_bed", "bed_2", "bath_1", "bath_2", "dining"]


def _generate(width: float, depth: float, floors: int, profile: str | None,
              rooms: list[str]):
    payload = dict(
        plot_width_m=width,
        plot_depth_m=depth,
        vastu_strictness="high",
        building_typology="residential_single",
        floors=floors,
        ground_coverage_ratio=0.6,
        ai_provider="mock",
        bypass_cache=True,
        seed="42",
        required_rooms=rooms,
    )
    if profile:
        payload["selected_scheme_id"] = profile
    return generate_floor_plan(FloorPlanRequest.model_validate(payload))


def _spec(room):
    return ONTOLOGY.get_space(room.space_type_id) if room.space_type_id else None


def _placed_aspect(room) -> float:
    """Aspect from the placed rectangle; never trust the stored field."""
    short = max(min(room.width_m, room.depth_m), 0.01)
    return max(room.width_m, room.depth_m) / short


def _programme_rooms(response):
    for floor in getattr(response.multi_storey, "floors", None) or []:
        for room in floor.rooms or []:
            if room.zone_category in ("circulation", "terrace"):
                continue
            spec = _spec(room)
            if spec is not None:
                yield floor, room, spec


def test_band_allocation_caps_frontage_at_the_catalogue_proportion():
    """Extra frontage is water-filled to the ceiling, not dumped by area weight."""
    engine = _engine_for(23.0, 14.0, 2)
    ctx = _ctx_for(engine)
    floors = {z: cs.expand_program(engine, z) for z in range(engine.total_storeys)}
    rooms = floors[0]
    depth = 3.34
    available = 18.7
    widths, over = cs._band_allocation(rooms, available, depth, cs._profile_area_bias("max_area"))
    assert widths is not None
    assert sum(widths.values()) == pytest.approx(available, abs=0.03)
    for room in rooms:
        ceiling = cs._aspect_ceiling(room, depth)
        assert widths[room.instance_id] <= ceiling + 0.02, (
            room.instance_id, widths[room.instance_id], ceiling
        )
    assert over == []


def test_band_assignment_prefers_a_split_its_rooms_can_fill():
    """A lone bathroom is not parked in an 18.7 m band when a filled split exists."""
    engine = _engine_for(23.0, 14.0, 2)
    ctx = _ctx_for(engine)
    floors = cs.expand_program(engine, 0)
    blocks = cs._must_components(floors)
    depth = 3.34
    south, north = cs._band_assignment(ctx, blocks, depth, "max_area")
    south_blocks = [blocks[i] for i in sorted(south)]
    north_blocks = [blocks[i] for i in sorted(north)]
    assert cs._band_capacity(south_blocks, depth) >= ctx.south_width - 0.05
    rear_depth = ctx.depth - depth - ctx.corridor_depth
    assert cs._band_capacity(north_blocks, rear_depth) >= ctx.width - 0.05


def test_every_disproportionate_room_is_disclosed_by_name():
    """Whatever the law cannot place in proportion is named in a warning.

     adds two legal outcomes beside ROOM-MAX disclosure: a room is SPLIT
    inside its band, or it is accepted as a room-listed PROP-ASPECT relaxation.
    What must never happen is an unlisted room outside its hard band.
    """
    undisclosed = []
    disclosed = 0
    acted = 0
    for width, depth in ((12.0, 18.0), (13.0, 20.0)):
        for floors_n, rooms in ((1, ROOMS_1), (2, ROOMS_2), (3, ROOMS_2)):
            for profile in PROFILES[1:]:
                resp = _generate(width, depth, floors_n, profile, rooms)
                lines = [w for w in (resp.warnings or []) if w.startswith(
                    ("ROOM-MAX", "PROP-HARD", "PROP-ASPECT"))]
                acted += sum(1 for w in (resp.warnings or []) if w.startswith("PROP-SPLIT"))
                for _floor, room, spec in _programme_rooms(resp):
                    if _placed_aspect(room) <= spec.max_aspect_ratio + 0.02:
                        continue
                    if any(room.room_id in line for line in lines):
                        disclosed += 1
                    else:
                        undisclosed.append(
                            (f"{width}x{depth}-F{floors_n}", profile, room.room_id,
                             f"{room.width_m}x{room.depth_m}")
                        )
    assert not undisclosed, undisclosed[:6]
    assert disclosed > 0 or acted > 0, (
        "expected the matrix to exercise the split, relaxation or disclosure path"
    )


def test_room_max_warning_is_raised_when_the_band_cannot_hold_proportion():
    """A deep plate that cannot be planned in proportion says so, with numbers."""
    resp = _generate(23.0, 14.0, 3, "max_area", ROOMS_2)
    lines = [w for w in (resp.warnings or []) if w.startswith("ROOM-MAX")]
    offenders = [
        (room.room_id, room.width_m, room.depth_m)
        for _floor, room, spec in _programme_rooms(resp)
        if _placed_aspect(room) > spec.max_aspect_ratio + 0.02
    ]
    if offenders:
        assert lines, offenders[:5]
        assert any("band" in line and "proportion" in line for line in lines), lines


def test_schema_normalizes_stored_aspect_at_construction():
    """A portrait room cannot be stored as 0.31:1 and slip a 1:3.25 check."""
    from app.schemas.multi_floor_plan import MultiFloorRoomRectangle

    room = MultiFloorRoomRectangle(
        room_id="portrait", room_name="Portrait", floor_index=0,
        x=0.0, y=0.0, width_m=1.20, depth_m=3.90, area_sqm=4.68,
        zone="W", aspect_ratio=0.31,
    )
    assert room.aspect_ratio == pytest.approx(3.25)


def test_stored_aspect_is_orientation_normalized_everywhere():
    """The schema stores max/min, so a writer cannot hide a stretch as 0.08:1."""
    mismatches = []
    narrow = 0
    for width, depth in ((12.0, 18.0), (18.0, 12.0)):
        resp = _generate(width, depth, 2, "max_area", ROOMS_2)
        for floor in getattr(resp.multi_storey, "floors", None) or []:
            for room in floor.rooms or []:
                short = max(min(room.width_m, room.depth_m), 0.01)
                measured = round(max(room.width_m, room.depth_m) / short, 2)
                if abs(room.aspect_ratio - measured) > 0.02:
                    mismatches.append((room.room_id, room.aspect_ratio, measured))
                if room.depth_m > room.width_m:
                    narrow += 1
    assert not mismatches, mismatches[:6]
    assert narrow > 0, "matrix must include portrait rooms to prove orientation is handled"


def test_vert01_is_only_claimed_where_the_room_actually_stacks():
    """No upper-storey wet room claims VERT-01 without sitting over a wet room."""
    false_claims = []
    for width, depth in PLATES:
        for floors_n in (2, 3):
            for profile in PROFILES:
                resp = _generate(width, depth, floors_n, profile, ROOMS_2)
                floors = list(getattr(resp.multi_storey, "floors", None) or [])
                for floor in floors:
                    if floor.floor_index == 0:
                        continue
                    below = next(
                        (f for f in floors if f.floor_index == floor.floor_index - 1), None
                    )
                    if below is None:
                        continue
                    lower_wet = [
                        (r.x, r.x + r.width_m)
                        for r in (below.rooms or [])
                        if _spec(r) is not None and _spec(r).is_wet
                    ]
                    for room in floor.rooms or []:
                        spec = _spec(room)
                        if spec is None or not spec.is_wet:
                            continue
                        span = max(room.width_m, 0.01)
                        covered = sum(
                            max(0.0, min(room.x + room.width_m, b) - max(room.x, a))
                            for a, b in lower_wet
                        )
                        if min(covered, span) / span >= 0.5:
                            continue
                        if "VERT-01-WET-STACK-ALIGN" in (room.applied_rules or []):
                            false_claims.append(
                                (f"{width}x{depth}-F{floors_n}", profile, room.room_id)
                            )
    assert not false_claims, false_claims[:6]


def _engine_for(width: float, depth: float, floors_n: int):
    from app.services.floorplan.engine import SoleGeometryEngine

    req = FloorPlanRequest.model_validate(dict(
        plot_width_m=width, plot_depth_m=depth, building_typology="residential_single",
        floors=floors_n, ground_coverage_ratio=0.6, bypass_cache=True,
        required_rooms=ROOMS_2,
    ))
    return SoleGeometryEngine(req)


def _ctx_for(engine):
    ok, _deg, envelope, _warnings = engine._compute_envelope()
    assert ok
    engine.program_needed_area_m2 = 0.0
    ctx = cs.build_plate_context(engine, envelope=envelope)
    assert ctx is not None
    return ctx
