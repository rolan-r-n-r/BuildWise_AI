"""API contracts: no silent duplex, no unconfirmed dwelling-count trade."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.floorplan import FloorPlanRequest
from app.schemas.remediation import BaselineFacts, RemediationIn
import app.services.floorplan.strategy_escalation as ladder
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.remediation import build_options
from app.services.floorplan.strategy_escalation import (
    _CACHE,
    _facts,
    solve_with_escalation,
)

client = TestClient(app)


def _req(**extra) -> FloorPlanRequest:
    return FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=18.0,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="stage6-pin",
        ai_provider="mock",
        bypass_cache=True,
        **extra,
    )


def test_duplex_is_accepted_as_its_own_drawn_variant():
    request = _req(partition_variant="duplex", units_per_floor=4)
    assert request.partition_variant == "duplex"
    response = solve_with_escalation(request)
    assert response.multi_storey is not None
    assert "DUPLEX" in response.generation_id
    assert response.multi_storey.units_per_floor == 4
    assert len({*[r.dwelling_id for f in response.multi_storey.floors for r in f.rooms if r.dwelling_id]}) == 8


def test_api_accepts_duplex_and_never_claims_it_for_a_two_unit_plan():
    """The API accepts V3; the returned token must match the drawn variant.

    A duplex S0 that fails may be superseded by a certified later rung.  That
    is allowed only if the returned generation token names the rung that was
    actually drawn; a DUPLEX token on a two-unit plan is the silent alias this
    contract forbids.
    """
    response = client.post(
        "/api/generate-floorplan",
        json={
            "plot_width_m": 12.0,
            "plot_depth_m": 18.0,
            "building_typology": "residential_multi",
            "floors": 4,
            "partition_variant": "duplex",
            "seed": "stage6-pin",
        },
    )
    assert response.status_code == 200, response.text[:400]
    dump = response.json()
    ms = dump["multi_storey"]
    chain = ms["strategy_chain"]
    s0 = next(entry for entry in chain if entry["id"] == "S0")
    assert s0["dwelling_count"] == 8
    token = dump["generation_id"]
    # The token carries the variant and the drawn unit count: -DUPLEX-U4.
    if "-DUPLEX" in token:
        assert ms["units_per_floor"] == 4
        assert any(room["room_id"].startswith("t2_D1_stair") for room in ms["floors"][0]["rooms"])
    else:
        assert ms["strategy_selected"] != "S2"
        assert ms["units_per_floor"] == 2


def _duplex_api_body(width: float, depth: float) -> dict:
    return {
        "plot_width_m": width,
        "plot_depth_m": depth,
        "building_typology": "residential_multi",
        "floors": 4,
        "ground_coverage_ratio": 0.60,
        "vastu_strictness": "high",
        "seed": "v1-closure-api",
        "ai_provider": "mock",
        "bypass_cache": True,
        "partition_variant": "duplex",
        "units_per_floor": 4,
    }


def test_explicit_duplex_api_answers_each_plate_with_its_measured_outcome():
    """Release-closure P0-01: infeasible duplex sites fail honestly, never 500.

    15 x 18 m and 20 x 20 m have no legal plate that can hold the layout: 422
    carrying the typed, measured refusal.  12 x 18 m is drawable but cannot
    certify: 200 with a fail stamp on real geometry.  18 x 24 m certifies, and
    the verdict must agree with its certificate.
    """
    for width, depth in ((15.0, 18.0), (20.0, 20.0)):
        response = client.post("/api/generate-floorplan", json=_duplex_api_body(width, depth))
        assert response.status_code == 422, response.text[:400]
        detail = str(response.json().get("detail"))
        assert "FLOORPLAN-DUPLEX-PLATE-INFEASIBLE" in detail
        assert "needs a feasible plate" in detail

    compact = client.post("/api/generate-floorplan", json=_duplex_api_body(12.0, 18.0))
    assert compact.status_code == 200, compact.text[:400]
    compact_body = compact.json()
    assert compact_body["plan_verdict"] == "NOT-CERTIFIED-FAIL-STAMP"
    assert "-DUPLEX" in compact_body["generation_id"]
    assert compact_body["multi_storey"]["units_per_floor"] == 4
    assert (compact_body.get("mathematical_certificate") or {}).get("is_valid") is False

    wide = client.post("/api/generate-floorplan", json=_duplex_api_body(18.0, 24.0))
    assert wide.status_code == 200, wide.text[:400]
    wide_body = wide.json()
    assert wide_body["plan_verdict"] == "CERTIFIED"
    assert (wide_body.get("mathematical_certificate") or {}).get("is_valid") is True
    assert wide_body["multi_storey"]["units_per_floor"] == 4


def _only_s2(monkeypatch):
    """Isolate the S2 rung.

    On every market plate probed, S1's service row now certifies before S2 can
    run, so a natural request would never exercise the dwelling-count gate.
    The gate is still a live safety contract: isolate S2 and keep S0 failing.
    """
    original = ladder._strategy_specs

    def only_s2(request, baseline):
        return [s for s in original(request, baseline) if s["id"] == "S2"]

    monkeypatch.setattr(ladder, "_strategy_specs", only_s2)


def test_unconfirmed_s2_is_count_preserving_and_not_deficit_gated(monkeypatch):
    _only_s2(monkeypatch)
    _CACHE.clear()
    response = solve_with_escalation(_req())
    ms = response.multi_storey
    assert ms is not None
    s2 = next(entry for entry in ms.strategy_chain if entry["id"] == "S2")
    assert s2["stacking_mode"] == "duplex"
    assert s2["dwelling_count_before"] == s2["dwelling_count_after"] == 8
    assert s2["confirmation_required"] is False if "confirmation_required" in s2 else True
    assert "requires dwelling-count confirmation" not in ms.strategy_chain_line
    # A count-preserving S2 that fails its own certificate is never selected as
    # a CERTIFIED generation, and an unconfirmed one is never silently active.
    if s2["status"] == "certified":
        assert s2["certificate_valid"] is True
    else:
        assert s2["status"] == "fail"


def test_explicit_single_unit_deficit_remains_confirmation_gated():
    _CACHE.clear()
    request = _req()
    out = build_options(
        RemediationIn(
            request=request,
            warnings=[],
            baseline=BaselineFacts(warning_count=0, failure_count=0),
        )
    )
    card = next(option for option in out.options if option.id == "single_unit")
    assert card.details["requires_confirmation"] is True
    assert card.details["strategy_id"] == "S2_deficit"
    assert card.patch["confirm_dwelling_deficit"] is True
    assert card.effect is not None
    direct = generate_floor_plan(_req(partition_variant="single_unit", units_per_floor=1, confirm_dwelling_deficit=True))
    assert direct.multi_storey is not None
    facts = _facts(direct)
    # Four one-level dwellings on four storeys, even though every floor reuses
    # the same unit handle.  The dwelling count groups (floor, unit), not raw ids.
    assert facts["dwelling_count"] == 4
    assert facts["floor_unit_count"] == 4
    # The card's effect is the MEASURED verdict, never a promise.  V2's
    # three-room north row gives its kitchen no exterior wall (living and
    # bedroom own the two facade ends), so the kitchen-daylight rule fails it
    # honestly; the card stays available as a dwelling-count change with a
    # fail-stamped effect until the V2 plan is redesigned.
    assert card.effect.verdict == "NOT-CERTIFIED-FAIL-STAMP"
    assert card.effect.certificate_valid is False
    direct_failures = [
        str(row)
        for row in (
            (direct.model_dump().get("mathematical_certificate") or {}).get("failures") or []
        )
    ]
    assert any("kitchen has no exterior window" in row for row in direct_failures)
