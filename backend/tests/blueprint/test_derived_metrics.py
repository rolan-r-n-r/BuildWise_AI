"""Derived metrics: every printed percentage is derived from the plan (regression pins).

Repro: the engine used to emit
    vastu_score_pct      = 90.0 if strictness == "high" else 82.0
    plumbing_stack_alignment_pct = 100.0
    space_utilization_pct = 100.0
    circulation_efficiency_pct = 100.0
    prefer_adjacency_score = 94.5
regardless of geometry. These tests fail if any of them becomes a constant again.
"""

from __future__ import annotations

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.derived_metrics import (
    building_wet_riser_pct,
    circulation_efficiency_pct,
    vastu_pct,
    wet_riser_pct_by_floor,
)
from app.services.floorplan.floorplan_service import generate_floor_plan


def _generate(**overrides):
    payload = dict(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        floors=1,
        vastu_strictness="high",
        ai_provider="mock",
        seed="1001",
        bypass_cache=True,
    )
    payload.update(overrides)
    return generate_floor_plan(FloorPlanRequest(**payload))


def _rooms(building):
    return [room for floor in building.floors for room in floor.rooms]


def test_vastu_score_is_the_measured_share_not_a_strictness_constant():
    response = _generate()
    measured = vastu_pct(_rooms(response.multi_storey))
    assert response.metrics.vastu_compliance_pct == pytest.approx(measured, abs=0.1)
    # The old constants were 90.0 / 82.0; a measured plan is free to differ.
    assert response.metrics.vastu_compliance_pct not in (90.0, 82.0) or (
        measured == pytest.approx(response.metrics.vastu_compliance_pct, abs=0.1)
    )


def test_plumbing_score_is_measured_not_the_old_constant():
    # WHY THIS PIN IS 0 % - AND WHY "0 % IS UNREACHABLE" IS NOT THE CONTRACT.
    #
    # The closeout note asked for a comment proving 0 % unreachable.  It is
    # unreachable, so no such proof exists; the drawn plate below measures 0.0
    # and the pin has to record the mechanism instead of a false invariant:
    #
    #  1. ``wet_riser_pct_by_floor`` returns ``None`` for a floor with no wet
    #     room ("nothing to align") and 0.0 when a floor HAS wet rooms but none
    #     qualify.  On the ground floor a wet room qualifies only when it shares
    #     a wall with a circulation room (the riser column runs there) or with
    #     another wet room (derived_metrics.py, wet_riser_pct_by_floor).
    #  2. This four-room selection on 12x15 is drawn WITHOUT a circulation room
    #     at all - the same response says so independently (LAND-03: circulation
    #     ratio 0.0 % is outside the 12-20 % band) - and the partitioner places
    #     master_bed between bath_1 and kitchen, so the two wet rooms are not
    #     adjacent either.  Neither wet room has a riser to reach: the honest
    #     score is 0.0.  It was 0.0 at HEAD as well; what changed is that 100.0
    #     (the fabricated constant) is gone.
    #  3. The control below scores the same function at 100 % on a plate that
    #     seats the wet block against the spine, proving 0.0 is this plate's
    #     measurement and not a broken metric.
    response = _generate(
        required_rooms=["living", "kitchen", "master_bed", "bath_1"],
    )
    floors = response.multi_storey.floors
    expected = wet_riser_pct_by_floor(floors)
    # Premise of the 0 %: no circulation room is drawn, so no riser column
    # exists for a wet room to share a wall with.
    assert not any(
        str(getattr(r, "zone_category", "")) == "circulation"
        for f in floors
        for r in (f.rooms or [])
    ), "fixture premise broken: this plate now draws a circulation room"
    assert expected == [0.0], expected
    assert response.metrics.plumbing_adjacency_score == pytest.approx(
        building_wet_riser_pct(floors), abs=0.1
    )
    assert response.metrics.plumbing_adjacency_score == pytest.approx(0.0, abs=0.1)
    # Control: the same measured function moves with the geometry.
    seated = _generate(
        plot_width_m=10.0,
        plot_depth_m=12.0,
        floors=2,
    )
    assert building_wet_riser_pct(seated.multi_storey.floors) == pytest.approx(100.0, abs=0.1)


def test_space_and_circulation_are_derived_from_areas():
    response = _generate()
    floors = response.multi_storey.floors
    built_up = sum(floor.built_up_area_sqm for floor in floors)
    envelope = sum((floor.envelope or {}).get("area_sqm", 0.0) for floor in floors)
    assert response.metrics.space_utilization_pct == pytest.approx(
        100.0 * built_up / envelope, abs=0.15
    )
    assert response.metrics.circulation_efficiency_pct == pytest.approx(
        circulation_efficiency_pct(_rooms(response.multi_storey)), abs=0.15
    )


def test_prefer_adjacency_is_not_invented():
    response = _generate()
    certificate = response.multi_storey.mathematical_certificate or {}
    assert certificate.get("prefer_adjacency_score") is None


def test_tolerated_minimum_is_a_declared_relaxation_with_a_warning():
    response = _generate()
    certificate = response.multi_storey.mathematical_certificate or {}
    declared = (certificate.get("details") or {}).get("declared_relaxations") or []
    assert declared, "the 12x15 T1 plate has a sub-minimum clear face; it must be declared"
    declared_rooms = {entry["room"] for entry in declared}
    warnings = [w for w in response.warnings if w.startswith("ROOM-MIN ") and "declared relaxation" in w]
    for room_id in declared_rooms:
        assert any(room_id in warning for warning in warnings), room_id
    # The relaxation is also carried on the room itself, not just in prose.
    relaxed = {
        room.room_id
        for floor in response.multi_storey.floors
        for room in floor.rooms
        if any(rel.get("rule_id") == "NBC-01" for rel in (room.relaxations or []))
    }
    assert declared_rooms <= relaxed
