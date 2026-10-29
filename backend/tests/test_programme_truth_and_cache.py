"""Programme truth and solver-cache correctness.

Four contracts could otherwise report something the engine did not draw, or
reuse a plan for a different request:

  * the ladder cache key omitted ``units_per_floor`` (and other inputs);
  * T2 advertised three units but drew two;
  * S5 claimed to trim optional rooms on a T2 resolver that ignores them;
  * S3 could raise coverage while the setback-bound plate stayed the same.

These pins exercise the actual cache and the public solve path, not a
``bypass_cache=True`` shortcut.
"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.programme_variables import get_programme_variables
from app.services.floorplan.strategy_escalation import (
    _CACHE,
    _cached_solve,
    _plate_hash,
    solve_with_escalation,
)


BASE = dict(
    plot_width_m=12.0,
    plot_depth_m=18.0,
    building_typology="residential_multi",
    floors=4,
    ground_coverage_ratio=0.60,
    vastu_strictness="high",
    seed="stage11a-pin",
    ai_provider="mock",
    bypass_cache=True,
)


def _req(**extra) -> FloorPlanRequest:
    return FloorPlanRequest(**{**BASE, **extra})


def _geometry(response) -> str:
    rooms = [
        [
            room.room_id,
            round(float(room.x), 3),
            round(float(room.y), 3),
            round(float(room.width_m), 3),
            round(float(room.depth_m), 3),
        ]
        for floor in (response.multi_storey.floors if response.multi_storey else [])
        for room in floor.rooms
    ]
    return hashlib.sha256(
        json.dumps(rooms, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _drawn_units(response) -> set[str]:
    return {
        str(room.unit_id)
        for floor in (response.multi_storey.floors if response.multi_storey else [])
        for room in floor.rooms
        if getattr(room, "unit_id", None)
    }


def test_cache_distinguishes_units_per_floor_in_both_orders():
    _CACHE.clear()
    default = _cached_solve(_req(), "S0")
    one = _cached_solve(_req(units_per_floor=1), "S0")

    assert _plate_hash(_req()) != _plate_hash(_req(units_per_floor=1))
    assert default.generation_id != one.generation_id
    assert default.multi_storey.units_per_floor == 2
    assert one.multi_storey.units_per_floor == 1
    assert _drawn_units(default) == {"Unit_A", "Unit_B"}
    assert _drawn_units(one) == {"Unit_A"}

    # Warm the cache in the opposite order: the same collision must not appear
    # in reverse.
    _CACHE.clear()
    first_one = _cached_solve(_req(units_per_floor=1), "S0")
    then_default = _cached_solve(_req(), "S0")
    assert first_one.multi_storey.units_per_floor == 1
    assert then_default.multi_storey.units_per_floor == 2
    assert _drawn_units(first_one) == {"Unit_A"}
    assert _drawn_units(then_default) == {"Unit_A", "Unit_B"}


def test_cache_key_covers_units_and_response_affecting_options():
    base = _req()
    variants = [
        {"units_per_floor": 1},
        {"confirm_dwelling_deficit": True},
        {"quality_grade": "premium"},
        {"client_notes": "a different brief"},
        {"include_service_layer": False},
        {"include_structural_sheet": False},
        {"include_scheme_alternatives": True},
        {"design_intent": "passive_ventilation"},
        {"solar_axis_degrees": 180.0},
        {"prevailing_wind_direction_degrees": 270.0},
    ]
    hashes = {_plate_hash(base)}
    for patch in variants:
        hashes.add(_plate_hash(base.model_copy(update=patch)))
    assert len(hashes) == len(variants) + 1


def test_cache_key_is_canonical_for_equivalent_structured_inputs():
    left = _req(floor_plate_masks={0: {"wing_a": "present", "wing_b": "void"}})
    right = _req(floor_plate_masks={0: {"wing_b": "void", "wing_a": "present"}})
    assert _plate_hash(left) == _plate_hash(right)


def test_confirmed_and_unconfirmed_requests_do_not_share_a_cache_entry():
    _CACHE.clear()
    unconfirmed = _cached_solve(_req(confirm_dwelling_deficit=False), "S2")
    confirmed = _cached_solve(_req(confirm_dwelling_deficit=True), "S2")
    assert _plate_hash(_req(confirm_dwelling_deficit=False)) != _plate_hash(
        _req(confirm_dwelling_deficit=True)
    )
    # Both are the same engine plan (confirmation is a ladder decision), but
    # they must be separate cache entries so a future payload divergence cannot
    # leak across the confirmation boundary.
    assert _geometry(confirmed) == _geometry(unconfirmed)
    assert len(_CACHE) == 2


def test_optional_scheme_payload_is_not_reused_from_the_default_solve():
    _CACHE.clear()
    default = _cached_solve(_req(), "S0")
    portfolio = _cached_solve(_req(include_scheme_alternatives=True), "S0")
    assert default.scheme_alternatives is None
    assert portfolio.scheme_alternatives
    assert _plate_hash(_req()) != _plate_hash(
        _req(include_scheme_alternatives=True)
    )
    assert len(_CACHE) == 2


def test_warm_and_cold_solves_are_equivalent_for_the_same_request():
    _CACHE.clear()
    cold = _cached_solve(_req(), "S0")
    warm = _cached_solve(_req(), "S0")
    assert warm.generation_id == cold.generation_id
    assert _geometry(warm) == _geometry(cold)
    assert warm.multi_storey.units_per_floor == cold.multi_storey.units_per_floor
    assert warm.warnings == cold.warnings
    assert warm.mathematical_certificate == cold.mathematical_certificate


def test_t2_three_units_is_rejected_not_reported_over_two_units():
    with pytest.raises(ValidationError, match="not implemented for T2"):
        _req(units_per_floor=3)

    # Direct engine/programme callers cannot silently clamp either.
    with pytest.raises(ValueError, match="outside the implemented range"):
        get_programme_variables("T2_FAMILY_APARTMENT").resolve_units(3)

    response = TestClient(app).post(
        "/api/generate-floorplan",
        json={
            "plot_width_m": 12.0,
            "plot_depth_m": 18.0,
            "building_typology": "residential_multi",
            "floors": 4,
            "units_per_floor": 3,
            "seed": "stage11a-pin",
        },
    )
    assert response.status_code == 422, response.text[:400]
    assert "not implemented for T2" in response.text
    assert "one-unit V2" in response.text


@pytest.mark.parametrize(
    "alias",
    [
        "residential_multi",
        "T2_FAMILY_APARTMENT",
        "t2_family_apartment",
        "apartment",
        "duplex",
        "builder_floor",
        "t2",
    ],
)
def test_every_t2_alias_refuses_three_units_with_a_named_422(alias):
    """The schema guard must cover every alias the engine resolves to T2."""
    with pytest.raises(ValidationError, match="not implemented for T2"):
        _req(building_typology=alias, units_per_floor=3)


def test_engine_level_unit_resolution_keeps_its_declared_fallback():
    """The engine resolver still reports the count it can actually draw.

    The API boundary rejects an out-of-range request for every typology before
    a solve starts.  A direct engine/programme caller keeps the declared
    fallback, and the resolved count is the one the partitioner draws.
    """
    assert get_programme_variables("T1_SINGLE_FAMILY").resolve_units(3) == 1
    assert get_programme_variables("T3_LARGE_COMPLEX").resolve_units(3) == 2
    assert get_programme_variables("T4_WAREHOUSE").resolve_units(2) == 1


def test_supported_t2_unit_counts_match_drawn_units():
    for requested, expected in ((1, {"Unit_A"}), (2, {"Unit_A", "Unit_B"})):
        response = generate_floor_plan(_req(units_per_floor=requested))
        assert response.multi_storey is not None
        assert response.multi_storey.units_per_floor == requested
        assert _drawn_units(response) == expected


def test_s5_is_disabled_for_t2_and_never_claims_a_removed_room():
    _CACHE.clear()
    request = _req(
        floors=3,
        plot_depth_m=15.0,
        required_rooms=["living", "kitchen", "bed_2", "study", "bath_1", "dining"],
        seed="stage11a-s5",
    )
    response = solve_with_escalation(request)
    chain = response.multi_storey.strategy_chain
    s5 = next(entry for entry in chain if entry["id"] == "S5")

    assert s5["status"] == "skipped"
    assert "not implemented for the T2 partitioner" in s5["skip_reason"]
    assert "no room was removed" in s5["skip_reason"]
    assert "Drop" not in s5["disclosure"]
    assert "no room is removed" in s5["disclosure"]

    # The selected geometry is the same T2 programme; the old patch claimed a
    # trim that this resolver never performed.
    default = generate_floor_plan(request.model_copy(update={"required_rooms": None}))
    assert _geometry(response) == _geometry(default)


def test_s3_reports_no_plate_growth_when_setbacks_bind():
    _CACHE.clear()
    response = solve_with_escalation(
        _req(floors=3, plot_depth_m=15.0, seed="stage11a-s3")
    )
    chain = response.multi_storey.strategy_chain
    s3 = next(entry for entry in chain if entry["id"] == "S3")

    assert "trial" in s3["label"]
    assert s3["status"] == "fail"
    assert s3["plate_delta_m2"] == 0.0
    assert s3["no_geometry_change"] is True
    assert "no plate growth" in s3["disclosure"]
    assert s3["plate_area_m2"] == chain[0]["plate_area_m2"] == 108.0
