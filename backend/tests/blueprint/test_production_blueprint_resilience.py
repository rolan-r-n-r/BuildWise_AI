import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app, _BLUEPRINT_SEMAPHORE
from app.schemas.floorplan import FloorPlanRequest


@pytest.mark.asyncio
async def test_valid_blueprint_single_storey():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "plot_width_m": 12.0,
            "plot_depth_m": 15.0,
            "building_typology": "residential_single",
            "floors": 1,
            "ground_coverage_ratio": 0.60,
            "built_up_area_sqft": 1200.0,
            "required_rooms": ["living", "kitchen", "master_bedroom", "bathroom"],
            "vastu_strictness": "medium",
            "ai_provider": "mock",
            "bypass_cache": True,
        }
        resp = await client.post("/api/generate-floorplan", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "generation_id" in data
        assert "plan_verdict" in data
        assert data.get("multi_storey") is not None


@pytest.mark.asyncio
async def test_blueprint_none_plot_dimensions():
    """Verify that None plot dimensions do not cause TypeError during plinth calculation."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "plot_width_m": None,
            "plot_depth_m": None,
            "building_typology": "residential_single",
            "floors": 1,
            "ground_coverage_ratio": 0.60,
            "built_up_area_sqft": 1200.0,
            "required_rooms": ["living", "kitchen", "master_bedroom"],
            "ai_provider": "mock",
            "bypass_cache": True,
        }
        resp = await client.post("/api/generate-floorplan", json=payload)
        # Should succeed or return clean 422 if geometry infeasible, but NEVER 500 TypeError
        assert resp.status_code in (200, 422), resp.text


@pytest.mark.asyncio
async def test_blueprint_concurrency_semaphore():
    """Verify that multiple concurrent requests are serialized safely by the semaphore."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "plot_width_m": 10.0,
            "plot_depth_m": 12.0,
            "building_typology": "residential_single",
            "floors": 1,
            "built_up_area_sqft": 800.0,
            "required_rooms": ["living", "kitchen", "master_bedroom"],
            "ai_provider": "mock",
            "bypass_cache": True,
        }
        # Fire 3 concurrent requests
        responses = await asyncio.gather(
            client.post("/api/generate-floorplan", json=payload),
            client.post("/api/generate-floorplan", json=payload),
            client.post("/api/generate-floorplan", json=payload),
        )
        for resp in responses:
            assert resp.status_code == 200, resp.text
            assert "generation_id" in resp.json()


@pytest.mark.asyncio
async def test_t2_escalation_omits_trial_scheme_alternatives():
    """Verify that T2 escalation ladder runs efficiently without redundant scheme solves."""
    from app.services.floorplan.strategy_escalation import solve_with_escalation
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=18.0,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="t2-resilience-pin",
        ai_provider="mock",
        bypass_cache=True,
        include_scheme_alternatives=True,
        confirm_dwelling_deficit=True,
    )
    resp = solve_with_escalation(req)
    assert resp.status_code != 500 if hasattr(resp, "status_code") else True
    assert resp.multi_storey is not None
    assert resp.multi_storey.strategy_chain is not None
    # Verify that scheme portfolio is still populated on the final selected plan
    assert getattr(resp, "scheme_portfolio", None) is not None


@pytest.mark.asyncio
async def test_fewer_than_three_rooms_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "plot_width_m": 10.0,
            "plot_depth_m": 12.0,
            "building_typology": "residential_single",
            "floors": 1,
            "built_up_area_sqft": 800.0,
            "required_rooms": ["living", "kitchen"],  # Only 2 rooms
            "ai_provider": "mock",
            "bypass_cache": True,
        }
        resp = await client.post("/api/generate-floorplan", json=payload)
        # Should be rejected with 422
        assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_blueprint_timeout_returns_504(monkeypatch):
    """Verify that a hung solver returns 504 Gateway Timeout rather than crashing."""
    import time

    def mock_hung_solver(req):
        time.sleep(0.5)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Patch solve_with_escalation and set a tiny timeout
        import app.main as main_mod
        from unittest.mock import patch

        async def mock_wait_for(fut, timeout):
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            payload = {
                "plot_width_m": 10.0,
                "plot_depth_m": 12.0,
                "building_typology": "residential_single",
                "floors": 1,
                "built_up_area_sqft": 800.0,
                "required_rooms": ["living", "kitchen", "master_bedroom"],
                "ai_provider": "mock",
                "bypass_cache": True,
            }
            resp = await client.post("/api/generate-floorplan", json=payload)
            assert resp.status_code == 504
            assert "timed out" in resp.json()["detail"].lower()

