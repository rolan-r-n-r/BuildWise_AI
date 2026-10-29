"""Escalation-ladder pins: bounded, deterministic, disclosed, cached, no churn.

The ladder exists to solve before stamping.  These tests hold it to its contract:
at most six engine solves, every tried strategy disclosed, S1 measured against
S0 on the same request, a certified S0 never re-solved, and a cached dry-run
returning the same plan.
"""
from __future__ import annotations

import hashlib
import io
import json

import pytest
from pypdf import PdfReader

from app.schemas.floorplan import FloorPlanRequest
from app.services.report_service import generate_pdf_report
from app.services.floorplan import strategy_escalation as escalation
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.strategy_escalation import solve_with_escalation
from app.services.plan_verdict import CERTIFIED, compute_plan_verdict


def _req(seed: str = "stage3-pin") -> FloorPlanRequest:
    return FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=18.0,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed=seed,
        ai_provider="mock",
        bypass_cache=True,
        confirm_dwelling_deficit=True,
    )


def test_t2_chain_is_ordered_bounded_and_disclosed():
    escalation._CACHE.clear()
    response = solve_with_escalation(_req())
    chain = response.multi_storey.strategy_chain
    assert chain is not None
    # The ladder stops at the first fully certified result.  The service-row
    # variant is a real executable strategy, so the T2 case certifies at S1 -
    # without changing the dwelling count - instead of walking the whole chain.
    # The V2 rung stays one rung further down.
    assert [entry["id"] for entry in chain[:2]] == ["S0", "S1"]
    assert chain[-1]["id"] == "S1"
    assert chain[-1]["status"] == "certified"
    assert chain[-1]["failures"] == 0
    assert chain[-1]["dwelling_count"] == chain[0]["dwelling_count"] == 8
    # At most six solves: S0 + five alternatives.
    assert len([e for e in chain if e["status"] in ("fail", "certified", "error")]) <= 6
    assert response.multi_storey.strategy_selected == "S1"
    assert response.multi_storey.strategy_chain_line.startswith("S0 fail -> S1 certified")
    assert "service strip" in chain[-1]["disclosure"]
    assert all(entry.get("disclosure") for entry in chain)
    assert any(w.startswith("STRATEGY-CHAIN:") for w in response.warnings)


def test_s1_is_measured_against_s0_on_the_same_request():
    escalation._CACHE.clear()
    response = solve_with_escalation(_req("stage3-s1"))
    by_id = {entry["id"]: entry for entry in response.multi_storey.strategy_chain}
    assert by_id["S0"]["failures"] == 2
    assert by_id["S1"]["failures"] == 0
    assert by_id["S1"]["warnings"] < by_id["S0"]["warnings"]
    assert by_id["S0"]["plate_area_m2"] == by_id["S1"]["plate_area_m2"]


def test_skipped_strategies_say_why():
    """A strategy the ladder did not run is disclosed with its reason.

    When S1 certifies the chain stops and no skipped row is invented.  When
    nothing certifies the chain walks to the end, and every strategy that
    could not run is published as ``skipped`` with the reason - never silently
    dropped from the record.
    """
    escalation._CACHE.clear()
    stopped_early = solve_with_escalation(_req("stage3-skip"))
    assert not any(
        entry["id"] in ("S3", "S4", "S5")
        for entry in stopped_early.multi_storey.strategy_chain
    )

    escalation._CACHE.clear()
    # The 129.6 m2 plate carries no legal two-unit row and no single-unit row
    # either, so the ladder exhausts and must disclose what it could not run.
    exhausted = solve_with_escalation(
        _req("stage3-skip").model_copy(
            update={"plot_width_m": 12.0, "plot_depth_m": 15.0}
        )
    )
    chain = exhausted.multi_storey.strategy_chain
    skipped = [entry for entry in chain if entry["status"] == "skipped"]
    assert skipped, "an exhausted ladder must disclose its unrun strategies"
    assert all(entry.get("skip_reason") for entry in skipped)
    by_id = {entry["id"]: entry for entry in chain}
    assert by_id["S4"]["skip_reason"] == "the engine's 4-storey cap is already reached"
    assert by_id["S5"]["skip_reason"] == "the request has no explicit required_rooms to trim"
    # A skipped strategy was never solved: it carries no measurements.
    assert by_id["S4"]["warnings"] is None and by_id["S4"]["plate_area_m2"] is None


def test_certified_s0_short_circuits(monkeypatch):
    escalation._CACHE.clear()
    monkeypatch.setattr(escalation, "_is_fully_certified", lambda facts: True)
    calls = []
    original = escalation.generate_floor_plan

    def counting(request):
        calls.append(request)
        return original(request)

    monkeypatch.setattr(escalation, "generate_floor_plan", counting)
    response = solve_with_escalation(_req("stage3-certified"))
    assert len(calls) == 1
    assert len(response.multi_storey.strategy_chain) == 1
    assert response.multi_storey.strategy_selected == "S0"


def test_strategy_chain_is_printed_on_pdf_page_one():
    chain_line = "S0 fail -> S1 certified"
    # A long page-1 deficit list used to push the chain onto page 2, and the
    # old pin searched every page so it could not see the regression.  The
    # chain must stay on PAGE 1 even when the banner fills the page.
    warnings = [
        f"ROOM-MIN: probe_room_{i}_F0 is below its catalogue minimum on this plate"
        for i in range(80)
    ]
    plan = {
        "strategy_chain_line": chain_line,
        "plan_verdict": "NOT-CERTIFIED-FAIL-STAMP",
        "warnings": warnings,
        "mathematical_certificate": {"is_valid": True},
        "validation_gate": {"overall_status": "PASS"},
        "multi_storey": {"strategy_chain_line": chain_line},
    }
    data = {
        "request_id": "BW-CHAIN",
        "timestamp": "2026-10-26T00:00:00Z",
        "coordinates": {"latitude": 12.97, "longitude": 77.59},
        "formatted_address": "Chain Probe Site",
        "overall_suitability_score": 80.0,
        "suitability_verdict": "Suitable",
        "warnings": [],
        "factors": [],
        "cost_estimate": {"base_rate_per_sqft": 100, "base_cost_inr": 200000, "breakdown": []},
        "recommendation_items": [],
        "detailed_recommendations": [],
        "risks": [],
    }
    buf = generate_pdf_report(data, floor_plan=plan)
    pages = PdfReader(io.BytesIO(buf.getvalue())).pages
    page_one = " ".join((pages[0].extract_text() or "").split())
    assert f"Strategy chain: {chain_line}" in page_one
    # Disclosure is not moved or shortened: every deficit row remains present
    # across the page-1 banner continuation.
    all_text = " ".join(
        " ".join((page.extract_text() or "").split()) for page in pages
    )
    assert all(f"probe_room_{i}_F0" in all_text for i in range(80))


def test_non_t2_plan_is_not_churned():
    escalation._CACHE.clear()
    request = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        floors=2,
        ground_coverage_ratio=0.55,
        seed="stage3-t1",
        ai_provider="mock",
        bypass_cache=True,
    )
    baseline = generate_floor_plan(request)
    response = solve_with_escalation(request)
    assert response.multi_storey is not None
    # One-entry chain: S0 is named, and no T2 strategy is run on a T1 plate.
    assert [entry["id"] for entry in response.multi_storey.strategy_chain] == ["S0"]
    assert response.multi_storey.strategy_selected == "S0"
    assert any(w.startswith("STRATEGY-CHAIN: S0") for w in response.warnings)
    assert response.generation_id == baseline.generation_id
    assert [r.room_id for f in response.multi_storey.floors for r in f.rooms] == [
        r.room_id for f in baseline.multi_storey.floors for r in f.rooms
    ]


def test_repeated_request_uses_the_cache(monkeypatch):
    escalation._CACHE.clear()
    calls = []
    original = escalation.generate_floor_plan

    def counting(request):
        calls.append(request)
        return original(request)

    monkeypatch.setattr(escalation, "generate_floor_plan", counting)
    first = solve_with_escalation(_req("stage3-cache"))
    first_calls = len(calls)
    second = solve_with_escalation(_req("stage3-cache"))
    assert len(calls) == first_calls
    assert second.multi_storey.strategy_selected == first.multi_storey.strategy_selected


# ---------------------------------------------------------------------------
# S2 one-dwelling plate: real geometry, measured and disclosed
# ---------------------------------------------------------------------------


def _s2_req(**extra) -> FloorPlanRequest:
    return FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=18.0,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="stage5-pin",
        ai_provider="mock",
        bypass_cache=True,
        # The single-unit variant changes the dwelling count, so these
        # certification pins exercise the explicitly confirmed path.
        confirm_dwelling_deficit=True,
        **extra,
    )


def _digest(response) -> str:
    """Geometry-only digest: ids and rectangles, no verdicts or warnings."""
    rooms = [
        [
            room.room_id,
            round(float(room.x), 2),
            round(float(room.y), 2),
            round(float(room.width_m), 2),
            round(float(room.depth_m), 2),
        ]
        for floor in (response.multi_storey.floors if response.multi_storey else [])
        for room in floor.rooms
    ]
    blob = json.dumps(rooms, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def test_t2_129_certifies_at_the_first_named_strategy_without_a_deficit():
    """Programme-led plate sizing moves this case from S2 to S1.

    S1 keeps all eight dwellings, so it is strictly better than the S2
    dwelling-count trade and the ladder must stop there.
    """
    escalation._CACHE.clear()
    response = solve_with_escalation(_s2_req())
    ms = response.multi_storey
    assert ms is not None
    assert ms.strategy_selected == "S1"
    assert response.status == "compromise"
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED
    cert = response.model_dump().get("mathematical_certificate") or {}
    assert cert.get("is_valid") is True
    assert not (cert.get("failures") or [])
    assert "S1 certified" in (ms.strategy_chain_line or "")
    assert "dwelling count" not in (ms.strategy_chain_line or "")
    assert [entry["id"] for entry in ms.strategy_chain] == ["S0", "S1"]


def test_s2_geometry_is_materially_different_from_s0_and_s1():
    escalation._CACHE.clear()
    s0 = generate_floor_plan(_s2_req())
    s1 = generate_floor_plan(_s2_req(partition_variant="service_row"))
    s2 = generate_floor_plan(_s2_req(partition_variant="single_unit", units_per_floor=1))
    digests = {_digest(s0), _digest(s1), _digest(s2)}
    assert len(digests) == 3, "S0, S1 and S2 must be three distinct plates"
    # The certificate is measured on the V2 plate, not inherited from S0.  V2's
    # three-room north row gives the kitchen no exterior wall, and the kitchen
    # daylight rule (NBC 2016 Part 3 Cl 12.2.3) is a hard gate: the plate is
    # fail-stamped until its kitchen geometry is redesigned.  Geometry
    # distinctness is what this pin owns; the verdict is asserted honestly.
    cert = s2.model_dump().get("mathematical_certificate") or {}
    assert cert.get("is_valid") is False
    assert any("kitchen has no exterior window" in str(f) for f in (cert.get("failures") or []))
    assert compute_plan_verdict(s2.model_dump()) == "NOT-CERTIFIED-FAIL-STAMP"


def test_strategy_change_changes_the_generation_token():
    escalation._CACHE.clear()
    s0 = generate_floor_plan(_s2_req())
    s1 = generate_floor_plan(_s2_req(partition_variant="service_row"))
    s2 = generate_floor_plan(_s2_req(partition_variant="single_unit", units_per_floor=1))
    assert s0.generation_id != s1.generation_id
    assert s0.generation_id != s2.generation_id
    assert s1.generation_id != s2.generation_id
    assert s2.generation_id.endswith("-SINGLE_UNIT-U1")


def test_units_per_floor_one_never_draws_a_two_unit_partition():
    escalation._CACHE.clear()
    response = generate_floor_plan(_s2_req(partition_variant="service_row", units_per_floor=1))
    ms = response.multi_storey
    assert ms is not None
    for floor in ms.floors:
        units = {
            str(room.unit_id)
            for room in floor.rooms
            if getattr(room, "unit_id", None)
        }
        assert units <= {"Unit_A"}, (floor.floor_index, units)
        assert not any("unitB" in room.room_id for room in floor.rooms)
        assert not any("Unit_B" in str(room.room_id) for room in floor.rooms)


def test_s2_soil_stacks_have_zero_dry_room_crossings():
    escalation._CACHE.clear()
    response = generate_floor_plan(_s2_req(partition_variant="single_unit", units_per_floor=1))
    cert = response.model_dump().get("mathematical_certificate") or {}
    l10 = next(
        layer for layer in cert.get("layer_statuses") or [] if layer["layer_id"] == "L10"
    )
    assert l10["status"] == "PASS", l10["summary"]
    assert "0 dry-room crossings" in l10["summary"]


def test_s0_geometry_is_frozen_not_churned():
    """S0-geometry-freeze: an explicit selection keeps byte-identical geometry.

    V2's kitchen fails the hard daylight rule, so the freeze is pinned on its
    actual, fail-stamped result: the ladder must not re-draw or churn the plate
    it already measured, and the token must name the same generation.
    """
    escalation._CACHE.clear()
    request = _s2_req(partition_variant="single_unit", units_per_floor=1)
    s0 = generate_floor_plan(request)
    assert compute_plan_verdict(s0.model_dump()) == "NOT-CERTIFIED-FAIL-STAMP"
    ladder_response = solve_with_escalation(request)
    assert ladder_response.multi_storey.strategy_selected == "S0"
    assert _digest(ladder_response) == _digest(s0)
    assert ladder_response.generation_id == s0.generation_id
