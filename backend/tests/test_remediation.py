"""Deterministic remediation: options come from evidence, effects from the engine."""
import json
from pathlib import Path

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.remediation import BaselineFacts, RemediationIn
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.strategy_escalation import solve_with_escalation
from app.services.floorplan.remediation import (
    _apply_patch,
    build_options,
    droppable_rooms,
    plan_hash,
)
from app.services.plan_verdict import compute_plan_verdict

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "test-fixtures"
    / "plan_noncertified_55.json"
)


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def payload(fixture):
    request = FloorPlanRequest(**{**fixture["request"], "include_scheme_alternatives": True})
    placed = sorted({r.rsplit("_F", 1)[0] for r in fixture["room_ids"]})
    return RemediationIn(
        request=request,
        warnings=fixture["warnings"],
        plan_verdict=fixture["plan_verdict"],
        placed_rooms=placed,
        baseline=BaselineFacts(
            warning_count=len(fixture["warnings"]),
            failure_count=len(fixture["certificate"]["failures"]),
            relaxation_count=len(fixture["relaxations"]),
        ),
    )


@pytest.fixture(scope="module")
def result(payload):
    return build_options(payload)


def test_every_option_carries_a_measured_effect(result):
    assert result.options, "a NOT-CERTIFIED plan must offer a next step"
    for option in result.options:
        assert option.error is None, (option.id, option.error)
        assert option.effect is not None, option.id
        assert option.effect.verdict in {"CERTIFIED", "ADVISORY", "NOT-CERTIFIED-FAIL-STAMP"}
        assert option.effect.plate_area_m2 and option.effect.plate_area_m2 > 0
        assert option.effect.floors >= 1


def test_add_storey_is_one_more_storey(result, payload):
    option = next(o for o in result.options if o.id == "add_storey")
    assert option.patch == {"floors": (payload.request.floors or 1) + 1}
    assert option.effect.floors == (payload.request.floors or 1) + 1


def test_reduce_programme_only_drops_rooms_the_engine_named(fixture, payload, result):
    option = next(o for o in result.options if o.id == "reduce_programme")
    dropped = option.details["dropped_rooms"]
    assert dropped, "the fixture names squeezed rooms"
    for room in dropped:
        base = room.rsplit("_F", 1)[0]
        assert any(
            w.startswith("ROOM-MIN") and f"{base}_F" in w for w in fixture["warnings"]
        ), room
        assert room not in option.patch["required_rooms"]


def test_enlarge_plate_title_uses_the_measured_plate(result):
    option = next(o for o in result.options if o.id == "enlarge_plate")
    assert option.effect.plate_area_m2
    assert f"{option.effect.plate_area_m2:.1f}" in option.title
    assert option.patch["ground_coverage_ratio"] > (option.details["from_coverage"])


def test_dry_run_equals_the_post_apply_certificate(payload, result):
    """The predicted effect IS the plan you get when you apply the option."""
    for option in result.options:
        if option.id == "switch_scheme":
            continue  # portfolio selection needs its own parity pass
        # Apply runs the same ladder as the live API, so the dry-run comparison
        # must too (the chain line is part of the response).
        applied = solve_with_escalation(_apply_patch(payload.request, option.patch))
        dump = applied.model_dump()
        cert = dump.get("mathematical_certificate") or {}
        assert compute_plan_verdict(dump) == option.effect.verdict, option.id
        assert len(cert.get("failures") or []) == option.effect.failure_count, option.id
        assert len(dump.get("warnings") or []) == option.effect.warning_count, option.id
        assert bool(cert.get("is_valid")) == option.effect.certificate_valid, option.id


def test_droppable_rooms_ignores_fixed_elements(fixture):
    fixed = droppable_rooms(
        [
            "ROOM-MIN: living_F0 is 3.0 m clear",
            "ROOM-MIN: core_staircase_primary_F0 is 7.2 m²",
            "ROOM-MIN: lobby_spine_F0 is 6.1 m²",
            "ROOM-MIN: terrace_band_F2 aspect",
        ],
        ["living", "core_staircase_primary", "lobby_spine", "terrace_band"],
    )
    assert fixed == []


def test_t2_service_row_option_is_engine_tried_first():
    request = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=18.0,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="remediation-service-row",
        ai_provider="mock",
        bypass_cache=True,
    )
    out = build_options(
        RemediationIn(
            request=request,
            warnings=[],
            baseline=BaselineFacts(warning_count=0, failure_count=2),
        )
    )
    assert out.options[0].id == "service_row"
    option = out.options[0]
    assert option.patch == {"partition_variant": "service_row", "units_per_floor": 2}
    assert option.effect is not None and option.error is None
    assert option.effect.failure_count == 0


def test_current_strategy_is_labelled_and_blocked():
    request = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=18.0,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="stage5-current",
        ai_provider="mock",
        bypass_cache=True,
        partition_variant="single_unit",
        units_per_floor=1,
    )
    out = build_options(
        RemediationIn(
            request=request,
            warnings=[],
            baseline=BaselineFacts(warning_count=0, failure_count=0),
        )
    )
    by_id = {option.id: option for option in out.options}
    assert by_id["single_unit"].details["current"] is True
    assert "current" in by_id["single_unit"].title.lower()
    assert by_id["single_unit"].details["apply_blocked_reason"]
    # Switching away from S2 must also restore the two-unit count; otherwise
    # the patch is a no-op on the one-unit selector.
    assert by_id["service_row"].patch == {
        "partition_variant": "service_row",
        "units_per_floor": 2,
    }


def test_plan_hash_is_stable_and_request_bound(fixture, payload):
    h1 = plan_hash(payload.request, fixture["warnings"], fixture["plan_verdict"])
    h2 = plan_hash(payload.request, fixture["warnings"], fixture["plan_verdict"])
    assert h1 == h2
    other = payload.request.model_copy(update={"floors": 5})
    assert plan_hash(other, fixture["warnings"], fixture["plan_verdict"]) != h1
