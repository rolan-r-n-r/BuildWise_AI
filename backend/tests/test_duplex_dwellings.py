"""Two-storey dwelling geometry and programme identity.

The target is the 12 x 18 m / four-storey T2 plate.  A count-preserving duplex
must draw four floor-level units per storey and pair floors 0/1 and 2/3, giving
eight households on sixteen level-units.  Every household gets one internal
stair pair with an identical footprint on consecutive levels.  If that geometry
cannot meet a catalogue minimum, the candidate must say so and fail its own
certificate; it must never be called certified, and it must never fall back to
the two-unit V2 plan.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.strategy_escalation import (
    _CACHE,
    _facts,
    solve_with_escalation,
)
from app.services.plan_verdict import CERTIFIED


def _req(**extra) -> FloorPlanRequest:
    payload = dict(
        plot_width_m=12.0,
        plot_depth_m=18.0,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="stage11b-pin",
        ai_provider="mock",
        bypass_cache=True,
        partition_variant="duplex",
        units_per_floor=4,
    )
    payload.update(extra)
    return FloorPlanRequest(**payload)


def _solve(req=None):
    _CACHE.clear()
    return generate_floor_plan(req or _req())


def _stair_rooms(response):
    stairs = {}
    for floor in response.multi_storey.floors:
        for room in floor.rooms:
            if room.space_type_id == "unit_stair":
                stairs.setdefault(room.dwelling_id, []).append(room)
    return stairs


def _cert(response):
    return response.model_dump().get("mathematical_certificate") or {}


def test_target_duplex_preserves_eight_dwellings_on_sixteen_level_units():
    response = _solve()
    assert response.multi_storey is not None
    assert response.multi_storey.units_per_floor == 4
    facts = _facts(response)
    assert facts["dwelling_count"] == 8
    assert facts["floor_unit_count"] == 16
    ids = {
        room.dwelling_id
        for floor in response.multi_storey.floors
        for room in floor.rooms
        if room.dwelling_id
    }
    assert ids == {f"D{i}" for i in range(1, 9)}
    # Four households per plate, and the same household appears on exactly the
    # two levels of its pair.
    assert [len({r.dwelling_id for r in f.rooms if r.dwelling_id}) for f in response.multi_storey.floors] == [4, 4, 4, 4]
    for floor in response.multi_storey.floors:
        expected = ("lower", "upper")[floor.floor_index % 2]
        assert {r.dwelling_level for r in floor.rooms if r.dwelling_id} == {expected}


def test_internal_stair_pair_is_real_geometry_and_certificate_checks_it():
    response = _solve()
    stairs = _stair_rooms(response)
    assert sorted(stairs) == [f"D{i}" for i in range(1, 9)]
    for dwelling, pair in stairs.items():
        assert len(pair) == 2, f"{dwelling} has {len(pair)} stair levels"
        a, b = sorted(pair, key=lambda r: r.floor_index)
        assert b.floor_index == a.floor_index + 1
        assert (a.x, a.y, a.width_m, a.depth_m) == (b.x, b.y, b.width_m, b.depth_m)
        assert a.unit_id == b.unit_id == dwelling
        assert a.dwelling_id == b.dwelling_id == dwelling
    cert = _cert(response)
    assert cert["unit_stairs_valid"] is True
    # Single-entry contract: the LOWER level owns the common-corridor door;
    # the UPPER level is reached only through the internal stair pair and
    # must not be drawn as a second corridor-accessible flat.  The stair is
    # still not a sealed box: it has real doors to the dwelling's bath and main
    # room, and the upper stair is a vertical portal in the reachability check.
    for floor in response.multi_storey.floors:
        common = {
            r.room_id for r in floor.rooms
            if r.zone_category == "circulation" and not r.dwelling_id
        }
        for stair in [r for r in floor.rooms if r.space_type_id == "unit_stair"]:
            touching = [
                door for door in floor.doors
                if stair.room_id in (door.from_room, door.to_room)
            ]
            has_corridor = any(
                door.from_room in common or door.to_room in common
                for door in touching
            )
            assert has_corridor == (floor.floor_index % 2 == 0), (
                f"{stair.room_id}: corridor access {has_corridor} on "
                f"floor {floor.floor_index}"
            )


def test_duplex_candidate_does_not_claim_certification_on_the_target():
    response = _solve()
    cert = _cert(response)
    assert cert.get("is_valid") is False
    assert any(row.startswith("NBC-01 Room minimums") for row in cert.get("failures", []))
    # It is a real plan with a named shortfall, not a silent two-unit fallback.
    assert "DUPLEX" in response.generation_id
    assert response.multi_storey is not None
    assert len(response.multi_storey.floors) == 4
    assert response.qa is not None
    assert response.qa.validation_gate_status in ("WARN", "FAIL")


def test_duplex_is_not_a_silent_alias_for_the_two_unit_plate():
    response = _solve()
    for floor in response.multi_storey.floors:
        units = {r.unit_id for r in floor.rooms if r.unit_id}
        assert units == {f"D{(floor.floor_index // 2) * 4 + n}" for n in range(1, 5)}
        assert "Unit_A" not in units and "Unit_B" not in units


def test_four_units_without_duplex_and_three_units_are_rejected():
    with pytest.raises(ValidationError, match="only with"):
        _req(partition_variant=None)
    with pytest.raises(ValidationError, match="three-unit"):
        _req(partition_variant=None, units_per_floor=3)
    with pytest.raises(ValidationError, match="four floor-level"):
        _req(units_per_floor=2)


def test_duplex_requires_floor_pairs():
    with pytest.raises(ValidationError, match="even number of storeys"):
        _req(floors=3)


def test_programme_completeness_groups_by_household_across_levels():
    response = _solve()
    gate = response.qa.validation_gate
    l15 = next(layer for layer in gate["layers"] if layer["layer_id"] == "L15")
    assert l15["status"] == "PASS", l15
    assert set(l15["details"]["per_unit"]) == {f"D{i}" for i in range(1, 9)}
    for dwelling in (f"D{i}" for i in range(1, 9)):
        assert {"unit_living", "unit_kitchen", "unit_bed", "unit_bath"} <= set(
            l15["details"]["per_unit"][dwelling]
        )


_VOLATILE = {
    "generated_at", "solver_timing_ms", "engine_ms", "timing_ms", "timings_ms",
    "elapsed_ms", "total_ms", "latency_ms", "duration_ms", "evaluated_at",
}


def _stable_dump(response):
    """Everything but wall-clock readings, which are not a determinism claim."""
    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if k not in _VOLATILE}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub(response.model_dump())


def test_repeated_solves_are_byte_stable_for_the_duplex_plate():
    first = _solve()
    second = _solve()
    assert first.generation_id == second.generation_id
    assert _stable_dump(first) == _stable_dump(second)


def test_warm_and_cold_duplex_cache_entries_are_equivalent():
    _CACHE.clear()
    cold = generate_floor_plan(_req())
    warm = generate_floor_plan(_req())
    assert warm.generation_id == cold.generation_id
    assert _stable_dump(warm) == _stable_dump(cold)


def test_explicit_duplex_request_never_errors_an_impossible_service_row():
    _CACHE.clear()
    response = solve_with_escalation(_req())
    chain = response.multi_storey.strategy_chain
    s1 = next(entry for entry in chain if entry["id"] == "S1")
    assert s1["status"] == "skipped"
    assert "will not" in s1["skip_reason"] and "explicit variant" in s1["skip_reason"]
    assert not [entry for entry in chain if entry["status"] == "error"]
    assert response.multi_storey.strategy_selected == "S0"


def test_ladder_skips_s2_on_odd_storeys_with_a_named_reason(monkeypatch):
    import app.services.floorplan.strategy_escalation as ladder

    original = ladder._strategy_specs

    def only_s2(request, baseline):
        return [spec for spec in original(request, baseline) if spec["id"] == "S2"]

    monkeypatch.setattr(ladder, "_strategy_specs", only_s2)
    _CACHE.clear()
    response = solve_with_escalation(
        _req(
            plot_width_m=12.0,
            plot_depth_m=15.0,
            floors=3,
            partition_variant=None,
            units_per_floor=2,
        )
    )
    s2 = next(entry for entry in response.multi_storey.strategy_chain if entry["id"] == "S2")
    assert s2["status"] == "skipped"
    assert "even number of storeys" in s2["skip_reason"]
    assert "stacking_mode" not in s2


def test_ladder_s2_discloses_stacking_and_never_reduces_the_count(monkeypatch):
    import app.services.floorplan.strategy_escalation as ladder

    original = ladder._strategy_specs

    def only_s2(request, baseline):
        return [spec for spec in original(request, baseline) if spec["id"] == "S2"]

    monkeypatch.setattr(ladder, "_strategy_specs", only_s2)
    _CACHE.clear()
    # The ladder is entered by an ordinary two-unit request; S2 is the patch
    # that converts it to the duplex plate.
    response = solve_with_escalation(_req(partition_variant=None, units_per_floor=2))
    chain = response.multi_storey.strategy_chain
    s2 = next(entry for entry in chain if entry["id"] == "S2")
    assert s2["stacking_mode"] == "duplex"
    assert s2["dwelling_count_before"] == 8
    assert s2["dwelling_count_after"] == 8
    assert s2["floor_unit_count"] == 16
    assert len(s2["internal_stair_connections"]) == 8
    assert all(row["levels_joined"] for row in s2["internal_stair_connections"])
    assert all(row["geometry_aligned"] for row in s2["internal_stair_connections"])
    assert s2["all_levels_joined"] is True
    assert s2["wet_columns_aligned"] is True
    assert s2["core_continuity"]["aligned"] is True
    assert s2["core_continuity"]["distinct_core_footprints"] == 2  # stair + lift
    assert s2["core_continuity"]["floors_with_identical_core"] == [0, 1, 2, 3]
    assert s2["identity"]["duplex_unit_ids"] == [f"D{i}" for i in range(1, 9)]
    assert s2["identity"]["baseline_unit_ids"] == ["Unit_A", "Unit_B"]
    assert s2["level_units_per_floor"] == [4, 4, 4, 4]
    assert s2["dwelling_floors"]["D1"] == [0, 1]
    assert s2["dwelling_floors"]["D8"] == [2, 3]
    assert "count preserved" in response.multi_storey.strategy_chain_line
    if s2["status"] == "fail":
        assert s2["why_not"] and "NBC-01" in s2["why_not"]
        assert s2["certification_failures"]
        assert s2["rejection_reason"].startswith("the drawn duplex candidate did not certify")
    # The candidate's own certificate invalid means it cannot be presented as
    # certified or selected as a CERTIFIED generation.
    if s2["status"] == "certified":
        assert s2["certificate_valid"] is True
    else:
        assert s2["status"] == "fail"
        assert s2["certificate_valid"] is False
    assert (response.plan_verdict != CERTIFIED) if s2["status"] == "fail" else True
