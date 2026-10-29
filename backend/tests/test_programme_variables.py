"""Programme-variable pins: representative-floor solve and stack.

The reported T2 case repeated one unit partition on every storey, so every
finding was disclosed four times with a different floor number.  These tests
prove the variable is declared (not a hidden constant), that the governing floor
is solved once, that stacking reproduces the same geometry, and that the
shortcut is disclosed rather than silent.
"""
from __future__ import annotations

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.programme_variables import get_programme_variables


T2_G4 = dict(
    plot_width_m=12.0,
    plot_depth_m=18.0,
    building_typology="residential_multi",
    floors=4,
    ground_coverage_ratio=0.60,
    vastu_strictness="high",
    seed="stage2",
    ai_provider="mock",
    bypass_cache=True,
)


def _geometry(resp):
    return [
        (
            fl.floor_index,
            r.room_id,
            round(r.x, 3),
            round(r.y, 3),
            round(r.width_m, 3),
            round(r.depth_m, 3),
        )
        for fl in resp.multi_storey.floors
        for r in fl.rooms
    ]


def test_t2_units_per_floor_is_a_declared_range():
    variables = get_programme_variables("T2_FAMILY_APARTMENT")
    # Three units are not implemented; the contract advertises only what the
    # partitioner can actually draw.
    assert variables.units_per_floor_range == (1, 2)
    assert variables.default_units_per_floor == 2
    assert variables.searches_units_per_floor is True
    assert variables.resolve_units(None) == 2
    assert variables.resolve_units(1) == 1
    assert variables.resolve_units(2) == 2
    # A request can never be silently clamped into the declared range.
    with pytest.raises(ValueError, match="outside the implemented range"):
        variables.resolve_units(3)
    with pytest.raises(ValueError, match="outside the implemented range"):
        variables.resolve_units(99)


def test_t1_and_single_unit_typologies_do_not_search_units():
    t1 = get_programme_variables("T1_SINGLE_FAMILY")
    assert t1.units_per_floor_range == (1, 1)
    assert t1.searches_units_per_floor is False
    assert t1.representative_floor is None  # living below, bedrooms above


def test_stack_solve_partitions_t2_once(monkeypatch):
    calls = []
    original = SoleGeometryEngine._partition_floor_plate

    def counting(self, floor_index, *args, **kwargs):
        calls.append(floor_index)
        return original(self, floor_index, *args, **kwargs)

    monkeypatch.setattr(SoleGeometryEngine, "_partition_floor_plate", counting)
    generate_floor_plan(FloorPlanRequest(**T2_G4))

    assert calls == [0], f"expected one governing-floor solve, got {calls}"


def test_stack_solve_is_geometrically_identical_to_per_floor_solving(monkeypatch):
    on = generate_floor_plan(FloorPlanRequest(**T2_G4))
    original = SoleGeometryEngine._stack_solve_applicable
    monkeypatch.setattr(SoleGeometryEngine, "_stack_solve_applicable", lambda self: False)
    try:
        off = generate_floor_plan(FloorPlanRequest(**T2_G4))
    finally:
        monkeypatch.setattr(SoleGeometryEngine, "_stack_solve_applicable", original)

    assert _geometry(on) == _geometry(off)
    # Every storey carries its own room ids; a stack must never reuse F0's id.
    ids = [r.room_id for fl in on.multi_storey.floors for r in fl.rooms]
    assert len(ids) == len(set(ids))


def test_stack_solve_disclosed_and_reduces_repeated_findings(monkeypatch):
    on = generate_floor_plan(FloorPlanRequest(**T2_G4))
    original = SoleGeometryEngine._stack_solve_applicable
    monkeypatch.setattr(SoleGeometryEngine, "_stack_solve_applicable", lambda self: False)
    try:
        off = generate_floor_plan(FloorPlanRequest(**T2_G4))
    finally:
        monkeypatch.setattr(SoleGeometryEngine, "_stack_solve_applicable", original)

    stack_lines = [w for w in on.warnings if w.startswith("STACK-SOLVE:")]
    assert len(stack_lines) == 1
    assert "F0" in stack_lines[0]
    for floor in ("F1", "F2", "F3"):
        assert floor in stack_lines[0]
    assert len(on.warnings) < len(off.warnings)
    # Nothing is hidden: every certificate failure still exists on both arms.
    assert len(on.mathematical_certificate["failures"]) == len(
        off.mathematical_certificate["failures"]
    )


def test_no_stack_when_a_floor_genuinely_differs():
    # A selected scheme profile re-partitions every floor from its own weights;
    # stacking it would certify one floor's geometry under another's mask.
    profiled = generate_floor_plan(
        FloorPlanRequest(**{**T2_G4, "selected_scheme_id": "max_area"})
    )
    assert profiled.multi_storey is not None
    assert not any(w.startswith("STACK-SOLVE:") for w in profiled.warnings)

    # T1 declares no representative floor: living below, bedrooms above.
    t1 = generate_floor_plan(
        FloorPlanRequest(
            plot_width_m=12.0,
            plot_depth_m=15.0,
            building_typology="residential_single",
            floors=3,
            ground_coverage_ratio=0.55,
            seed="stage2",
            ai_provider="mock",
            bypass_cache=True,
        )
    )
    assert t1.multi_storey is not None
    assert not any(w.startswith("STACK-SOLVE:") for w in t1.warnings)


def test_programme_variables_are_disclosed_with_the_plan():
    resp = generate_floor_plan(FloorPlanRequest(**T2_G4))
    declared = resp.multi_storey.programme_variables
    assert declared["typology"] == "T2_FAMILY_APARTMENT"
    assert declared["units_per_floor_range"] == [1, 2]
    assert declared["unit_stacking"] == "duplex"
    assert declared["amenity_placement"] == "all"
    assert resp.multi_storey.units_per_floor == 2
