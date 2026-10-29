"""
Sidebar control wiring contract + live delta tests.
===================================================

Every control in the Site Coordinates sidebar tile must reach at least one
VISIBLE output. This module is the permanent regression gate for that promise:

  1. Live deltas   — moving a control changes the produced artefact
                     (cost string, sheet finish schedule, room programme,
                     footprint, storey count, narrative source).
  2. Dead-control  — no sidebar field survives without a named backend
                     consumer (static consumer map, asserted by source scan).

A control that is silently dropped (sent but never read) fails here.
"""
import io
import re
from pathlib import Path

import pytest

from app.ai.blueprint_program import _generate_mock_program, generate_room_program
from app.ai.mock_adapter import MockExplanationAdapter
from app.ai.prompts import build_user_prompt
from app.schemas.floorplan import FloorPlanRequest
from app.services.cost_service import calculate_construction_cost
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.wall_graph import (
    FINISH_GRADE_TIERS,
    GRADE_TIER_LABELS,
    build_constructible_wall_graph,
    normalize_finish_grade,
    resolve_finish,
)
from app.services.report_service import generate_pdf_report

BACKEND_APP = Path(__file__).resolve().parents[1] / "app"

ROOMS = [
    {"room_id": "living", "room_name": "Living Room", "x": 0.0, "y": 0.0, "width_m": 5.0, "depth_m": 3.4, "area_sqm": 17.0, "zone": "CENTER", "zone_category": "public"},
    {"room_id": "kitchen", "room_name": "Kitchen", "x": 5.0, "y": 0.0, "width_m": 3.4, "depth_m": 3.4, "area_sqm": 11.6, "zone": "SE", "zone_category": "service"},
    {"room_id": "master", "room_name": "Master Bedroom", "x": 0.0, "y": 3.4, "width_m": 4.2, "depth_m": 3.6, "area_sqm": 15.1, "zone": "SW", "zone_category": "private"},
    {"room_id": "bath", "room_name": "Primary Bath", "x": 4.2, "y": 3.4, "width_m": 4.2, "depth_m": 3.6, "area_sqm": 15.1, "zone": "NW", "zone_category": "service"},
]
ENVELOPE = {"width": 8.4, "depth": 7.0, "area_sqm": 58.8}


# =============================================================================
# 1. SPECIFICATION GRADE -> CPWD rate AND sheet finish schedule
# =============================================================================

def test_grade_changes_cpwd_rate_and_total_cost():
    """Grade must move the cost estimate (the original, already-working wiring)."""
    totals = {}
    rates = {}
    for grade in ("basic", "standard", "premium"):
        est = calculate_construction_cost(area_sqft=2000.0, quality_grade=grade, slope_pct=1.0, floors=1)
        totals[grade] = est.total_estimated_cost_inr
        rates[grade] = est.base_rate_per_sqft
    assert rates["basic"] < rates["standard"] < rates["premium"]
    assert totals["basic"] < totals["standard"] < totals["premium"]


def test_grade_changes_room_schedule_finish_on_sheets():
    """
    The specification grade must reach the ROOM SCHEDULE finish column, not only
    the cost rate. Before this gate the finish vocabulary was hardcoded per room
    name and every grade printed identical materials.
    """
    schedules = {}
    for grade in ("basic", "standard", "premium"):
        wg = build_constructible_wall_graph(
            floor_index=0, envelope=ENVELOPE, raw_rooms=ROOMS, quality_grade=grade
        )
        schedules[grade] = {r["room_id"]: r["finish_zone"] for r in wg.room_schedule}
        # Every row discloses the tier it was priced at.
        assert all(r["finish_grade"] == grade for r in wg.room_schedule)
        assert all(r["finish_grade_label"] == GRADE_TIER_LABELS[grade] for r in wg.room_schedule)

    assert schedules["basic"]["living"] != schedules["standard"]["living"]
    assert schedules["standard"]["living"] != schedules["premium"]["living"]
    assert "Ceramic" in schedules["basic"]["living"]
    assert "Travertine" in schedules["premium"]["living"]
    # Basic must never print a premium-only material anywhere in the schedule.
    premium_only = ("Marble Inlay", "Travertine", "Oak Plank", "Mirror-Polished")
    for finish in schedules["basic"].values():
        assert not any(m in finish for m in premium_only), finish


def test_resolve_finish_is_grade_tiered_and_defaults_safely():
    assert resolve_finish("Living Room", "living", "standard") == "Polished Vitrified Tile 800x800"
    assert "Ceramic" in resolve_finish("Living Room", "living", "basic")
    assert "Travertine" in resolve_finish("Living Room", "living", "premium")
    # Unknown room types still move with the grade (no silently grade-blind row).
    assert resolve_finish("Vault", "", "basic") == FINISH_GRADE_TIERS["basic"]["_default"]
    assert resolve_finish("Vault", "", "premium") == FINISH_GRADE_TIERS["premium"]["_default"]
    # An unknown/empty grade clamps to standard rather than crashing.
    assert normalize_finish_grade(None) == "standard"
    assert normalize_finish_grade("Gold-Plated") == "standard"


def _pdf_text(payload_grade: str) -> str:
    req = FloorPlanRequest(
        plot_width_m=15.0,
        plot_depth_m=18.0,
        building_typology="residential_single",
        quality_grade=payload_grade,
        floors=1,
        vastu_strictness="medium",
    )
    res = generate_floor_plan(req)
    payload = {
        "request_id": f"TEST-{payload_grade}",
        "timestamp": "2026-01-01 00:00:00 UTC",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Test Site",
        "overall_suitability_score": 80.0,
        "suitability_verdict": "Suitable",
        "built_up_area_sqft": 2400.0,
        "quality_grade": payload_grade,
        "floors": 1,
        "building_typology": "residential_single",
        "include_construction_schedules": True,
    }
    buf = generate_pdf_report(payload, floor_plan=res.model_dump(), include_construction_schedules=True)
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(buf.getvalue()))
    return "\n".join(page.extract_text() for page in reader.pages)


def test_grade_reaches_the_printed_sheet_finish_tier():
    """The rendered PDF must show the grade tier and grade-specific materials."""
    basic_text = _pdf_text("basic")
    premium_text = _pdf_text("premium")

    assert "Room Schedule" in basic_text
    assert GRADE_TIER_LABELS["basic"].split(" (")[0] in basic_text
    assert "Finish tier:" in basic_text
    # The two sheets must not print the same finish vocabulary.
    assert "Ceramic Floor Tile 600x600" in basic_text
    assert "Imported Polished Travertine" in premium_text
    assert "Imported Polished Travertine" not in basic_text


# =============================================================================
# 2. BUILT-UP PLINTH AREA -> ROOM PROGRAMME SIZING
# =============================================================================

def test_plinth_area_changes_generated_programme():
    """
    A 500 sq ft brief and a 50,000 sq ft brief must not produce the same plan.
    Before this gate the deterministic planner accepted `built_up_area` and
    never read it, so the default (mock) engine returned an identical programme
    at every size.
    """
    small = _generate_mock_program("residential_single", "standard", 1, 0.6, "", 500.0)
    medium = _generate_mock_program("residential_single", "standard", 1, 0.6, "", 2000.0)
    large = _generate_mock_program("residential_single", "standard", 1, 0.6, "", 50000.0)

    small_names = {r.name for r in small.rooms}
    medium_names = {r.name for r in medium.rooms}
    large_names = {r.name for r in large.rooms}

    assert len(small.rooms) < len(medium.rooms) <= len(large.rooms)
    # Compact brief: habitable core only, no guest wing.
    assert "Bedroom 2" not in small_names
    assert "Dining Area" not in small_names
    # Generous brief earns the extended programme.
    assert "Bedroom 3" in large_names
    assert "Store Room" in large_names
    assert small_names < medium_names
    # The programme records the target it was sized for.
    assert "500 sq ft" in small.design_intent
    assert "50,000 sq ft" in large.design_intent


def test_area_scaling_reaches_the_planner_through_the_public_entrypoint():
    """The real call path (generate_room_program) must honour the area too."""
    import asyncio

    async def run(area: float):
        return await generate_room_program(
            {
                "typology": "residential_single",
                "quality_grade": "standard",
                "storeys": 1,
                "coverage": 0.6,
                "built_up_area": area,
                "client_notes": f"area scaling probe {area}",
                "bypass_cache": True,
            },
            provider="mock",
        )

    small_prog, _ = asyncio.run(run(600.0))
    large_prog, _ = asyncio.run(run(30000.0))
    assert len(large_prog.rooms) > len(small_prog.rooms)


def test_storeys_split_the_plinth_area_per_floor():
    """Storeys must divide the plinth area onto each plate before sizing."""
    one_floor = _generate_mock_program("residential_single", "standard", 1, 0.6, "", 3000.0)
    four_floors = _generate_mock_program("residential_single", "standard", 4, 0.6, "", 3000.0)
    assert len(one_floor.rooms) > len(four_floors.rooms)
    assert "750 sq ft per floor" in four_floors.design_intent


# =============================================================================
# 3. CLIENT REQUIREMENTS -> NARRATIVE
# =============================================================================

@pytest.mark.asyncio
async def test_client_requirements_reach_the_narrative():
    brief = "2 baths, north-facing study, open kitchen"
    adapter = MockExplanationAdapter()
    summary, _recs, meta = await adapter.generate_explanation(
        {
            "quality_grade": "standard",
            "built_up_area_sqft": 1800,
            "floors": 1,
            "client_requirements": brief,
            "overall_suitability_score": 72.0,
            "cost_estimate": {"total_estimated_cost_inr": 3960000.0},
            "coordinates": {"latitude": 12.97, "longitude": 77.59},
        }
    )
    assert brief in meta["parameter_reflection"]
    assert summary  # the narrative itself still renders


def test_client_requirements_are_appended_to_the_llm_user_prompt():
    with_brief = build_user_prompt(12.9, 77.6, 1800, "standard", "residential_single", "G", 60, client_requirements="2 baths")
    without_brief = build_user_prompt(12.9, 77.6, 1800, "standard", "residential_single", "G", 60)
    assert "2 baths" in with_brief
    assert "client requirements" not in without_brief.lower()
    assert without_brief.strip().endswith("Ground Coverage=60%.")


# =============================================================================
# 4. COVERAGE / STOREYS / TYPOLOGY -> SOLVED GEOMETRY
# =============================================================================

def _ground_envelope_area(coverage: float) -> float:
    # A 12 x 15 m plot: at 40 % the coverage ceiling (72 m2) is BELOW the
    # programme need, so the cap binds; at 75 % it is not. On a 20 x 25 m plot
    # the plate is programme-sized at both settings, which is the correct
    # ceiling-not-target behaviour but cannot demonstrate a cap.
    res = generate_floor_plan(
        FloorPlanRequest(
            plot_width_m=12.0,
            plot_depth_m=15.0,
            building_typology="residential_single",
            ground_coverage_ratio=coverage,
            floors=1,
            vastu_strictness="medium",
        )
    )
    assert res.multi_storey is not None
    return float(res.multi_storey.floors[0].envelope["area_sqm"])


def test_ground_coverage_ratio_caps_the_footprint():
    sparse = _ground_envelope_area(0.40)
    dense = _ground_envelope_area(0.75)
    assert dense > sparse, "a binding coverage limit must cap the footprint"


def test_storeys_change_the_floor_count():
    def floors_for(n: int) -> int:
        res = generate_floor_plan(
            FloorPlanRequest(
                plot_width_m=18.0,
                plot_depth_m=20.0,
                building_typology="residential_single",
                floors=n,
                vastu_strictness="medium",
            )
        )
        assert res.multi_storey is not None
        return len(res.multi_storey.floors)

    assert floors_for(1) == 1
    assert floors_for(3) == 3


def test_typology_selects_the_engine_programme():
    def placements(typology: str):
        res = generate_floor_plan(
            FloorPlanRequest(
                plot_width_m=20.0,
                plot_depth_m=22.0,
                building_typology=typology,
                floors=1,
                vastu_strictness="medium",
            )
        )
        names = [r.room_name.lower() for r in (res.rectangles.rooms if res.rectangles else [])]
        return names

    commercial = placements("commercial")
    residential = placements("residential_single")
    assert commercial and residential
    assert not any("bed" in n for n in commercial)
    assert any("bed" in n for n in residential)


# =============================================================================
# 5. DEAD-CONTROL REGRESSION GATE
# =============================================================================

# Every sidebar field, and the backend module that must READ it. The regex is
# matched against the consumer module's source; a control whose consumer
# disappears (or that is renamed without rewiring) fails this test.
FIELD_CONSUMERS = {
    "latitude": ["services/orientation_service.py", "services/hazard_service.py"],
    "longitude": ["services/orientation_service.py", "services/hazard_service.py"],
    "built_up_area_sqft": ["services/cost_service.py", "ai/blueprint_program.py"],
    "quality_grade": ["services/cost_service.py", "services/floorplan/wall_graph.py"],
    "building_typology": ["services/floorplan/engine.py"],
    "floors": ["services/floorplan/engine.py", "services/cost_service.py"],
    "ground_coverage_ratio": ["services/floorplan/engine.py", "services/landvalue_service.py"],
    "client_requirements": ["ai/mock_adapter.py", "ai/prompts.py"],
    "ai_provider": ["ai/blueprint_program.py", "main.py"],
    "extracted_constraints": ["services/floorplan/engine.py"],
}


@pytest.mark.parametrize("field,consumers", sorted(FIELD_CONSUMERS.items()))
def test_every_sidebar_field_has_a_real_consumer(field, consumers):
    """No sidebar control may be decorative: each must be read by >=1 engine."""
    searched = {}
    for rel in consumers:
        path = BACKEND_APP / rel
        assert path.exists(), f"declared consumer module missing: {rel}"
        src = path.read_text(encoding="utf-8")
        searched[rel] = src
        if re.search(rf"\b{re.escape(field)}\b", src):
            return
    pytest.fail(
        f"sidebar field '{field}' has no consumer in {consumers} (searched "
        f"{len(searched)} module(s)) — the control is dead; wire it or remove it"
    )


def test_no_sidebar_wire_field_is_missing_from_the_request_schema():
    """The wire contract must expose every field the tile sends."""
    src = (BACKEND_APP / "schemas" / "request.py").read_text(encoding="utf-8")
    for field in ("latitude", "longitude", "built_up_area_sqft", "quality_grade",
                  "building_typology", "floors", "ground_coverage_ratio", "client_requirements"):
        assert f"{field}:" in src, f"{field} missing from AnalysisRequest schema"
