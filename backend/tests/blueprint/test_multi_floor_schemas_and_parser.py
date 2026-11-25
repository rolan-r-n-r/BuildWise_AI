import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.multi_floor_plan import (
    MultiStoreyBuildingModel,
    SingleFloorPlanModel,
    VerticalCoreSpec,
    DuctShaftSpec,
    MultiFloorRoomRectangle,
    MultiFloorDoorGeometry,
    MultiFloorWindowGeometry,
    StructuralGridSpec,
    ExtractedClientConstraints,
    OrientationPreferenceConstraint,
    SpatialAdjacencyConstraint,
)
from app.schemas.floorplan import (
    FloorPlanResponse,
    FloorPlanRequest,
    RoomPlacement,
    FloorPlanMetrics,
)
from app.ai.requirements_parser import (
    parse_client_requirements_fallback,
    parse_client_requirements_sync,
)


# =====================================================================
# 1. Pydantic Schema Validation Tests
# =====================================================================

def test_vertical_core_spec_validation():
    """Verify VerticalCoreSpec validates dimensions and riser/tread parameters."""
    core = VerticalCoreSpec(
        core_id="stair_main",
        core_type="staircase_dogleg",
        x=2.0,
        y=3.0,
        width_m=2.4,
        depth_m=3.6,
        riser_mm=160,
        tread_mm=270,
        landing_depth_m=1.2,
        continuous_across_floors=[0, 1],
    )
    assert core.core_id == "stair_main"
    assert core.core_type == "staircase_dogleg"
    assert core.riser_mm == 160
    assert core.tread_mm == 270
    assert core.continuous_across_floors == [0, 1]


def test_duct_shaft_spec():
    """Verify DuctShaftSpec validates plumbing wet shaft attributes."""
    duct = DuctShaftSpec(
        shaft_id="duct_1",
        shaft_type="plumbing_wet",
        x=5.0,
        y=4.5,
        width_m=0.8,
        depth_m=0.6,
        servicing_rooms=["master_bath", "kitchen"],
    )
    assert duct.shaft_id == "duct_1"
    assert duct.shaft_type == "plumbing_wet"
    assert "master_bath" in duct.servicing_rooms


def test_single_and_multi_floor_plan_models():
    """Verify SingleFloorPlanModel and MultiStoreyBuildingModel structure and serialization."""
    room1 = MultiFloorRoomRectangle(
        room_id="living_01",
        room_name="Living Room",
        floor_index=0,
        x=0.0,
        y=0.0,
        width_m=4.5,
        depth_m=5.0,
        area_sqm=22.5,
        zone="NE",
        zone_category="public",
        vastu_compliant=True,
    )
    door1 = MultiFloorDoorGeometry(
        door_id="door_main",
        floor_index=0,
        from_room="exterior",
        to_room="living_01",
        wall_edge="north",
        x1=1.5,
        y1=0.0,
        x2=2.5,
        y2=0.0,
        hinge_x=1.5,
        hinge_y=0.0,
        width_m=1.0,
        door_type="standard",
    )
    window1 = MultiFloorWindowGeometry(
        window_id="win_living",
        floor_index=0,
        room_id="living_01",
        wall_edge="north",
        x1=3.0,
        y1=0.0,
        x2=4.5,
        y2=0.0,
        width_m=1.5,
        sill_height_m=0.9,
    )
    core = VerticalCoreSpec(
        core_id="core_0",
        core_type="staircase_dogleg",
        x=4.5,
        y=0.0,
        width_m=2.4,
        depth_m=3.0,
        continuous_across_floors=[0, 1],
    )
    duct = DuctShaftSpec(
        shaft_id="duct_main",
        shaft_type="plumbing_wet",
        x=4.0,
        y=4.0,
        width_m=0.6,
        depth_m=0.6,
        servicing_rooms=["living_01"],
    )

    floor_g = SingleFloorPlanModel(
        floor_index=0,
        floor_name="Ground Floor",
        envelope={"x": 0.0, "y": 0.0, "width": 10.0, "depth": 12.0, "area_sqm": 120.0},
        rooms=[room1],
        doors=[door1],
        windows=[window1],
        circulation_status="connected",
        vastu_score_pct=88.0,
        built_up_area_sqm=120.0,
        carpet_area_sqm=96.0,
    )

    building = MultiStoreyBuildingModel(
        building_typology="T1_SINGLE_FAMILY",
        total_storeys=2,
        plot_width_m=10.0,
        plot_depth_m=12.0,
        ground_coverage_ratio=0.60,
        total_built_up_area_sqm=240.0,
        vertical_cores=[core],
        duct_shafts=[duct],
        floors=[floor_g],
        structural_grid=StructuralGridSpec(
            bay_spacing_x_m=5.0,
            bay_spacing_y_m=6.0,
            columns_x=[0.0, 5.0, 10.0],
            columns_y=[0.0, 6.0, 12.0],
            column_size_m=0.45,
        ),
    )

    assert building.total_storeys == 2
    assert len(building.floors) == 1
    assert building.floors[0].floor_name == "Ground Floor"
    assert building.vertical_cores[0].core_type == "staircase_dogleg"
    assert building.structural_grid is not None

    # Test serialization to dict and round-trip
    dump = building.model_dump()
    assert dump["building_typology"] == "T1_SINGLE_FAMILY"
    assert dump["floors"][0]["rooms"][0]["zone"] == "NE"


def test_floorplan_response_backward_compatibility():
    """Verify FloorPlanResponse handles single-floor responses without multi_storey, and accepts multi_storey."""
    dummy_placement = RoomPlacement(
        room_id="living",
        room_name="Living",
        row=0,
        col=0,
        width=4,
        height=4,
        area_sqm=16.0,
        width_m=4.0,
        depth_m=4.0,
        zone="NE",
        vastu_compliant=True,
    )
    dummy_metrics = FloorPlanMetrics(
        vastu_compliance_pct=90.0,
        plumbing_adjacency_score=85.0,
        space_utilization_pct=88.0,
        plot_coverage_pct=60.0,
        total_built_up_sqm=16.0,
        circulation_efficiency_pct=85.0,
    )

    # Legacy response (multi_storey is None)
    legacy_resp = FloorPlanResponse(
        status="optimal",
        grid_matrix=[["living"]],
        placements=[dummy_placement],
        svg_blueprint="<svg></svg>",
        metrics=dummy_metrics,
        timing_ms=15.0,
        iterations=1,
    )
    assert legacy_resp.multi_storey is None
    assert legacy_resp.metrics.vastu_compliance_pct == 90.0

    # With multi_storey populated
    building = MultiStoreyBuildingModel(
        building_typology="T1_SINGLE_FAMILY",
        total_storeys=2,
        plot_width_m=10.0,
        plot_depth_m=10.0,
        total_built_up_area_sqm=160.0,
        floors=[],
    )
    multi_resp = FloorPlanResponse(
        status="optimal",
        grid_matrix=[["living"]],
        placements=[dummy_placement],
        svg_blueprint="<svg></svg>",
        metrics=dummy_metrics,
        timing_ms=18.0,
        iterations=1,
        multi_storey=building,
    )
    assert multi_resp.multi_storey is not None
    assert multi_resp.multi_storey.total_storeys == 2


def test_floorplan_request_extracted_constraints():
    """Verify FloorPlanRequest accepts extracted_constraints without breaking."""
    constraints = ExtractedClientConstraints(
        target_bedroom_count=3,
        target_bathroom_count=2,
        specialized_spaces=["home_office"],
        orientation_preferences=[
            OrientationPreferenceConstraint(space="home_office", preferred_facing="North")
        ],
    )
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        required_rooms=["Living", "Kitchen", "Master Bedroom"],
        extracted_constraints=constraints,
    )
    assert req.extracted_constraints is not None
    assert req.extracted_constraints.target_bedroom_count == 3
    assert "home_office" in req.extracted_constraints.specialized_spaces


# =====================================================================
# 2. Deterministic Regex Fallback Parser Tests
# =====================================================================

def test_fallback_parser_empty_and_minimal():
    """Verify fallback parser handles empty and minimal strings with safe defaults."""
    res1 = parse_client_requirements_fallback("")
    assert res1.target_bedroom_count == 2
    assert res1.target_bathroom_count == 2
    assert res1.specialized_spaces == []
    assert res1.raw_notes == ""

    res2 = parse_client_requirements_fallback("   ")
    assert res2.target_bedroom_count == 2


def test_fallback_parser_bhk_and_baths():
    """Verify fallback parser extracts BHK numbers and bathroom counts."""
    # 3 BHK, 3 baths
    res = parse_client_requirements_fallback("Looking for a modern 3BHK with 3 bathrooms")
    assert res.target_bedroom_count == 3
    assert res.target_bathroom_count == 3

    # 4 bedroom, 2 toilet
    res2 = parse_client_requirements_fallback("Need 4 bedrooms and 2 toilets for our family")
    assert res2.target_bedroom_count == 4
    assert res2.target_bathroom_count == 2

    # 1 bed, 1 bath studio
    res3 = parse_client_requirements_fallback("Compact 1-bedroom flat with 1 attached bath")
    assert res3.target_bedroom_count == 1
    assert res3.target_bathroom_count == 1


def test_fallback_parser_specialized_spaces():
    """Verify detection of offices, pooja room, powder room, balconies, open kitchen, gym."""
    text = (
        "3 BHK duplex villa. Require a dedicated home office, a quiet study room, "
        "a traditional pooja room in the north-east, an open kitchen with breakfast counter, "
        "utility area, powder room for guests, and wide balconies."
    )
    res = parse_client_requirements_fallback(text)
    assert res.target_bedroom_count == 3
    assert "home_office" in res.specialized_spaces
    assert "study" in res.specialized_spaces
    assert "pooja_room" in res.specialized_spaces
    assert "open_kitchen" in res.specialized_spaces
    assert "powder_room" in res.specialized_spaces
    assert "utility_room" in res.specialized_spaces
    assert "balcony" in res.specialized_spaces


def test_fallback_parser_orientation_preferences():
    """Verify extraction of cardinal directions tied to specific rooms."""
    text = "Master bedroom facing south, study room facing north, and kitchen in east"
    res = parse_client_requirements_fallback(text)
    facings = [p.preferred_facing for p in res.orientation_preferences]

    assert "North" in facings
    assert "East" in facings
    assert "South" in facings


def test_fallback_parser_explicit_exclusions():
    """Verify negative constraints like 'no pooja room' or 'no balcony' are caught."""
    text = "2 BHK apartment, no pooja room, without balcony, strictly no dining room"
    res = parse_client_requirements_fallback(text)
    assert any("pooja" in exc.lower() for exc in res.explicit_exclusions)
    # Ensure pooja was not added to specialized_spaces
    assert "pooja_room" not in res.specialized_spaces


def test_parse_client_requirements_sync_wrapper():
    """Verify synchronous facade works smoothly."""
    res = parse_client_requirements_sync("3 BHK with private gym and home office", ai_provider="mock")
    assert res.target_bedroom_count == 3
    assert "gym" in res.specialized_spaces
    assert "home_office" in res.specialized_spaces


# =====================================================================
# 3. FastAPI Endpoint Tests (/api/parse-requirements)
# =====================================================================

def test_api_parse_requirements_endpoint():
    """Verify POST /api/parse-requirements returns 200 and ExtractedClientConstraints."""
    client = TestClient(app)
    payload = {
        "requirements_text": "3 BHK with north-facing home office and 2 baths",
        "ai_provider": "mock",
    }
    response = client.post("/api/parse-requirements", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["target_bedroom_count"] == 3
    assert data["target_bathroom_count"] == 2
    assert "home_office" in data["specialized_spaces"]
    assert len(data["orientation_preferences"]) >= 1
    assert data["orientation_preferences"][0]["preferred_facing"] == "North"


def test_api_parse_requirements_empty_payload():
    """Verify POST /api/parse-requirements with empty text returns defaults safely."""
    client = TestClient(app)
    response = client.post("/api/parse-requirements", json={"requirements_text": ""})
    assert response.status_code == 200
    data = response.json()
    assert data["target_bedroom_count"] == 2
    assert data["target_bathroom_count"] == 2
    assert data["specialized_spaces"] == []
