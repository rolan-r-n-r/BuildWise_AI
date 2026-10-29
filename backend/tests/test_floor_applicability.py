"""Ontology law is per FLOOR, not per building.

Pins:
  * a ground entrance lobby is area-governed;
  * the same strip above ground is a landing, width-governed, so the lobby's
    area minimum is not applied on F1+;
  * a terrace band never inherits habitable-room area/aspect law;
  * the canonical warning fixture no longer prints those manufactured lines,
    while the ground-floor lobby shortfall IS still disclosed.
"""
import json
from pathlib import Path

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.ontology import ONTOLOGY

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "test-fixtures"
    / "plan_noncertified_55.json"
)


def test_ground_lobby_is_area_governed():
    for room_id, typology in (("lobby_spine", "residential_single"), ("floor_lobby", "residential_multi")):
        rule = ONTOLOGY.floor_area_rule(room_id, typology, 0)
        assert rule["area_applies"] is True, room_id
        assert rule["rule_id"] is None


def test_upper_landing_is_width_governed():
    for floor in (1, 2, 3):
        rule = ONTOLOGY.floor_area_rule("lobby_spine", "residential_single", floor)
        assert rule["area_applies"] is False, floor
        assert rule["rule_id"] == "CIRC-02-UPPER-LANDING-WIDTH"
        assert "NBC 2016 Pt 4 Cl 4.5" in rule["citation"]
        assert rule["min_width_m"] == pytest.approx(1.20)


def test_terrace_band_is_outdoor_on_every_level():
    for floor in (0, 1, 2, 3):
        rule = ONTOLOGY.floor_area_rule("terrace_band", "residential_single", floor, "terrace")
        assert rule["area_applies"] is False, floor
        assert rule["rule_id"] == "RULE-FP-04-TERRACE-STRIP"
        assert "Cl 10.2.1" in rule["citation"]


def test_certificate_fixture_no_longer_prints_manufactured_lines():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    request = FloorPlanRequest(**{**data["request"], "bypass_cache": True, "ai_provider": "mock"})
    plan = generate_floor_plan(request)
    warnings = list(plan.warnings or [])

    upper_lobby = [
        w for w in warnings
        if w.startswith("ROOM-MIN") and "lobby_spine_F" in w
        and any(f"_F{i}" in w for i in (1, 2, 3))
        and "catalogue minimum on floor" in w
    ]
    assert upper_lobby == [], upper_lobby
    terrace_law = [
        w for w in warnings
        if "terrace_band" in w and ("catalogue maximum" in w or "aspect ratio" in w)
    ]
    assert terrace_law == [], terrace_law
    # The ground entrance lobby is still judged by area: the fix must not hide it.
    assert any(
        w.startswith("ROOM-MIN: lobby_spine_F0") and "catalogue minimum on floor 0" in w
        for w in warnings
    ), [w for w in warnings if "lobby_spine_F0" in w][:3]
    # Any terrace line that remains must be the width/drainage disclosure, not
    # habitable-room area or aspect law.
    assert all(
        "catalogue minimum" not in w and "catalogue maximum" not in w
        for w in warnings if "terrace_band" in w
    )
