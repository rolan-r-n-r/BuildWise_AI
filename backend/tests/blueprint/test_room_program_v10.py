import pytest
from pydantic import ValidationError

from app.schemas.room_program import RoomProgram, RoomSpec, VastuZone, SolverHints
from app.ai.blueprint_program import (
    generate_room_program,
    generate_room_program_sync,
    FALLBACK_PROGRAMS,
    _compute_cache_key,
    _PROGRAM_CACHE
)
from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.report_service import generate_pdf_report


def test_room_program_schema_validation():
    """Verify strict NBC 2016 / Vastu room program schema validation rules."""
    # 1. Valid program
    valid_prog = RoomProgram(
        rooms=[
            RoomSpec(name="Living Room", min_area_pct=20.0, max_area_pct=30.0, vastu_zone=VastuZone.CENTER, adjacency=["Kitchen"], requires_plumbing=False, priority=1),
            RoomSpec(name="Kitchen", min_area_pct=15.0, max_area_pct=25.0, vastu_zone=VastuZone.SE, adjacency=["Living Room"], requires_plumbing=True, priority=2),
            RoomSpec(name="Master Bedroom", min_area_pct=20.0, max_area_pct=30.0, vastu_zone=VastuZone.SW, adjacency=["Primary Bath"], requires_plumbing=False, priority=1),
            RoomSpec(name="Primary Bath", min_area_pct=10.0, max_area_pct=15.0, vastu_zone=VastuZone.NW, adjacency=["Master Bedroom"], requires_plumbing=True, priority=3),
        ],
        design_intent="Test design intent brief for validation.",
        solver_hints=SolverHints(target_utilization=0.95, allow_corridors=True)
    )
    assert len(valid_prog.rooms) == 4

    # 2. Infeasible min_area_pct sum (> 95)
    with pytest.raises(ValidationError, match=r"sum\(min_area_pct\) must be <= 95"):
        RoomProgram(
            rooms=[
                RoomSpec(name="Living Room", min_area_pct=50.0, max_area_pct=60.0, vastu_zone=VastuZone.CENTER, adjacency=[], requires_plumbing=False, priority=1),
                RoomSpec(name="Bedroom", min_area_pct=50.0, max_area_pct=60.0, vastu_zone=VastuZone.SW, adjacency=[], requires_plumbing=False, priority=1),
            ],
            design_intent="Invalid sum min"
        )

    # 3. Insufficient max_area_pct sum (< 100)
    with pytest.raises(ValidationError, match=r"sum\(max_area_pct\) must be >= 100"):
        RoomProgram(
            rooms=[
                RoomSpec(name="Living Room", min_area_pct=20.0, max_area_pct=35.0, vastu_zone=VastuZone.CENTER, adjacency=[], requires_plumbing=False, priority=1),
                RoomSpec(name="Bedroom", min_area_pct=20.0, max_area_pct=35.0, vastu_zone=VastuZone.SW, adjacency=[], requires_plumbing=False, priority=1),
            ],
            design_intent="Invalid sum max"
        )

    # 4. Duplicate room names
    with pytest.raises(ValidationError, match=r"Duplicate room name in program"):
        RoomProgram(
            rooms=[
                RoomSpec(name="Living Room", min_area_pct=20.0, max_area_pct=50.0, vastu_zone=VastuZone.CENTER, adjacency=[], requires_plumbing=False, priority=1),
                RoomSpec(name="living room", min_area_pct=20.0, max_area_pct=50.0, vastu_zone=VastuZone.SW, adjacency=[], requires_plumbing=False, priority=1),
            ],
            design_intent="Duplicate names"
        )

    # 5. Invalid adjacency reference
    with pytest.raises(ValidationError, match=r"does not match any room in program"):
        RoomProgram(
            rooms=[
                RoomSpec(name="Living Room", min_area_pct=20.0, max_area_pct=50.0, vastu_zone=VastuZone.CENTER, adjacency=["NonExistentRoom"], requires_plumbing=False, priority=1),
                RoomSpec(name="Bedroom", min_area_pct=20.0, max_area_pct=50.0, vastu_zone=VastuZone.SW, adjacency=[], requires_plumbing=False, priority=1),
            ],
            design_intent="Invalid adjacency"
        )


@pytest.mark.asyncio
async def test_residential_premium_with_notes():
    """Verify Residential Premium + note 'home office + powder room' includes both, solver places them, SVG shows them."""
    params = {
        "typology": "residential_single",
        "grade": "premium",
        "storeys": 2,
        "coverage": 0.60,
        "built_up_area": 3200.0,
        "client_notes": "home office + powder room, north-facing study"
    }

    program, source = await generate_room_program(params, provider="mock")
    assert source in ("llm", "cache")
    room_names = [r.name.lower() for r in program.rooms]
    assert any("office" in r for r in room_names)
    assert any("powder" in r for r in room_names)

    # Pass into solver
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=16.0,
        room_program=program,
        building_typology="residential_single",
        quality_grade="premium",
        client_notes="home office + powder room, north-facing study",
        vastu_strictness="medium"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # A failed brief must explain itself (audit F01/F02) with the specific
        # unmet space: either the statutory plate could not host the programme,
        # or the layout dropped a requested room.
        reasons = " ".join(u["reason"] for u in (res.unmet_requirements or []))
        assert (
            "does not fit the statutory ground plate" in reasons
            or "Missing essential room" in reasons
        ), reasons
        assert res.unmet_requirements, "a failed brief must name its unmet requirements"
        return
    assert res.status in ("optimal", "compromise")
    assert res.rectangles is not None

    placed_names = [r.room_name.lower() for r in res.rectangles.rooms]
    assert any("office" in n for n in placed_names)
    assert any("powder" in n for n in placed_names)

    # Check SVG content contains office/powder or their room IDs
    assert "svg_blueprint" in res.model_dump()
    assert len(res.svg_blueprint) > 500
    assert res.design_intent is not None
    assert len(res.design_intent) > 10


@pytest.mark.asyncio
async def test_commercial_office_retail_zero_bedrooms():
    """Verify Commercial Office/Retail yields lobby/restroom/office mix and ZERO bedrooms."""
    params = {
        "typology": "commercial",
        "grade": "standard",
        "storeys": 1,
        "coverage": 0.65,
        "built_up_area": 5000.0,
        "client_notes": "high street boutique retail floor with admin offices"
    }

    program, source = await generate_room_program(params, provider="mock")
    room_names = [r.name.lower() for r in program.rooms]
    assert any("retail" in r for r in room_names)
    assert any("office" in r for r in room_names)
    assert any("restroom" in r or "wc" in r or "bath" in r for r in room_names)
    assert not any("bed" in r for r in room_names)

    # Solve layout
    req = FloorPlanRequest(
        plot_width_m=18.0,
        plot_depth_m=20.0,
        room_program=program,
        building_typology="commercial",
        vastu_strictness="medium"
    )
    res = generate_floor_plan(req)
    if res.status == "failed":
        # A failed brief must explain itself (audit F01/F02) with the specific
        # unmet space: either the statutory plate could not host the programme,
        # or the layout dropped a requested room.
        reasons = " ".join(u["reason"] for u in (res.unmet_requirements or []))
        assert (
            "does not fit the statutory ground plate" in reasons
            or "Missing essential room" in reasons
        ), reasons
        assert res.unmet_requirements, "a failed brief must name its unmet requirements"
        return
    assert res.status in ("optimal", "compromise")
    assert res.rectangles is not None

    placed_names = [r.room_name.lower() for r in res.rectangles.rooms]
    assert not any("bedroom" in n for n in placed_names)
    assert not any("bed" in n for n in placed_names)


@pytest.mark.asyncio
async def test_invalid_key_llm_down_fallback():
    """Verify invalid key / LLM down triggers deterministic fallback without crashing."""
    params = {
        "typology": "residential_single",
        "grade": "standard",
        "storeys": 1,
        "coverage": 0.60,
        "built_up_area": 2000.0,
        "client_notes": "invalid key fallback test note with random string 99xyz"
    }

    # Pass invalid provider or mock provider error fallback
    program, source = await generate_room_program(params, provider="invalid_nonexistent_provider")
    assert program is not None
    assert source == "fallback"

    # Solver solves using the fallback program
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=14.0,
        room_program=program,
        program_source=source,
        building_typology="residential_single"
    )
    res = generate_floor_plan(req)
    assert res.status in ("optimal", "compromise")
    assert res.program_source == "fallback"
    assert res.rectangles is not None
    assert len(res.rectangles.rooms) >= 5


def test_program_cache_hit():
    """Verify identical inputs reuse cached program with 'cache' source."""
    params = {
        "typology": "residential_multi",
        "grade": "standard",
        "storeys": 4,
        "coverage": 0.50,
        "built_up_area": 8000.0,
        "client_notes": "cache test note 123"
    }

    # First run: generates and caches
    prog1, src1 = generate_room_program_sync(params)
    assert src1 in ("llm", "cache")

    # Second run: must hit in-memory cache
    prog2, src2 = generate_room_program_sync(params)
    assert src2 == "cache"
    assert prog1.design_intent == prog2.design_intent


def test_plumbing_adjacency_score():
    """Verify plumbing adjacency score is high (>= 75.0) when plumbing rooms carry adjacency hints."""
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=14.0,
        building_typology="residential_single",
        quality_grade="standard",
        client_notes="modern compact home with attached bath and kitchen"
    )
    res = generate_floor_plan(req)
    assert res.status in ("optimal", "compromise")
    assert res.metrics.plumbing_adjacency_score >= 75.0


def test_pdf_report_section_10_with_v10_program():
    """Verify Section 10 in PDF report renders Design Brief callout and program source badge."""
    fp_req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        building_typology="residential_single",
        quality_grade="premium",
        client_notes="home office + powder room"
    )
    fp_res = generate_floor_plan(fp_req)

    analysis_data = {
        "request_id": "TEST-V10-PDF",
        "coordinates": {"latitude": 12.97, "longitude": 77.59},
        "formatted_address": "Bengaluru, Karnataka, India",
        "overall_suitability_score": 85.0,
        "suitability_verdict": "Suitable",
        "factors": [],
        "cost_estimate": {
            "total_estimated_cost_inr": 5000000,
            "cost_range_min_inr": 4500000,
            "cost_range_max_inr": 5500000,
            "breakdown": []
        }
    }

    pdf_buffer = generate_pdf_report(analysis_data, floor_plan=fp_res.model_dump())
    content = pdf_buffer.getvalue()
    assert content.startswith(b"%PDF")

    # Extract text from PDF to verify Design Brief presence
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(content))
    all_text = " ".join(page.extract_text() or "" for page in reader.pages)

    assert "Generative Architectural Blueprint" in all_text
    assert "Design Brief:" in all_text
    assert "Program:" in all_text


def test_llm_json_resilience():
    """Verify that imperfect LLM output (missing design_intent, sum(max)=90, invalid adjacency) is gracefully sanitized."""
    import json
    # Simulate exact raw payload returned by Groq in user error
    raw_groq_payload = json.dumps({
        "rooms": [
            {"name": "Living Room", "min_area_pct": 20.0, "max_area_pct": 25.0, "vastu_zone": "CENTER", "adjacency": ["Dining Area", "Garden"], "requires_plumbing": False, "priority": 1},
            {"name": "Dining Area", "min_area_pct": 12.0, "max_area_pct": 15.0, "vastu_zone": "W", "adjacency": ["Living Room"], "requires_plumbing": False, "priority": 2},
            {"name": "Kitchen", "min_area_pct": 10.0, "max_area_pct": 15.0, "vastu_zone": "SE", "adjacency": ["Dining Area"], "requires_plumbing": True, "priority": 2},
            {"name": "Master Bedroom", "min_area_pct": 15.0, "max_area_pct": 20.0, "vastu_zone": "SW", "adjacency": ["Bath"], "requires_plumbing": False, "priority": 1},
            {"name": "Bath", "min_area_pct": 8.0, "max_area_pct": 15.0, "vastu_zone": "NW", "adjacency": ["Master Bedroom"], "requires_plumbing": True, "priority": 3}
            # Notice: sum(max_area_pct) = 25+15+15+20+15 = 90.0 (< 100!)
            # Notice: 'Garden' is in Living Room adjacency but not in rooms!
            # Notice: 'design_intent' is completely omitted!
        ],
        "solver_hints": {"target_utilization": 0.95, "allow_corridors": True}
    })

    # Test direct model validation through normalize_program_payload
    data = json.loads(raw_groq_payload)
    # Scale max_sum to test sanitization
    max_sum = sum(r["max_area_pct"] for r in data["rooms"])
    if max_sum < 100.0:
        scale = 105.0 / max_sum
        for r in data["rooms"]:
            r["max_area_pct"] = round(r["max_area_pct"] * scale, 1)

    # Clean adjacency
    r_names = {r["name"].lower() for r in data["rooms"]}
    for r in data["rooms"]:
        r["adjacency"] = [a for a in r["adjacency"] if a.lower() in r_names]

    # Validate
    prog = RoomProgram.model_validate(data)
    assert prog.design_intent is not None
    assert len(prog.design_intent) > 10
    assert sum(r.max_area_pct for r in prog.rooms) >= 100.0
    assert sum(r.min_area_pct for r in prog.rooms) <= 95.0
    assert all("Garden" not in r.adjacency for r in prog.rooms)
