import io
import time
import pytest
import pypdf
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def _mock_http_response(url: str, **kwargs):
    resp = MagicMock()
    resp.status_code = 200

    if "nominatim" in url:
        if "26.14" in url or "91.73" in url:
            resp.json.return_value = {
                "display_name": "GS Road, Guwahati, Kamrup Metropolitan, Assam, India",
                "address": {"city": "Guwahati", "state": "Assam"}
            }
        elif "25.59" in url or "85.13" in url:
            resp.json.return_value = {
                "display_name": "Patna, Patna District, Bihar, India",
                "address": {"city": "Patna", "state": "Bihar"}
            }
        else:
            resp.json.return_value = {
                "display_name": "Bengaluru Urban, Karnataka, India",
                "address": {"city": "Bengaluru", "state": "Karnataka"}
            }
    elif "earthquake.usgs.gov" in url:
        if "26.14" in url or "91.73" in url:
            resp.json.return_value = {
                "features": [
                    {
                        "properties": {"mag": 6.8, "time": 1600000000000, "place": "Assam Tectonic Belt"},
                        "geometry": {"coordinates": [91.73, 26.14, 10.0]}
                    },
                    {
                        "properties": {"mag": 5.4, "time": 1500000000000, "place": "Kamrup District"},
                        "geometry": {"coordinates": [91.75, 26.12, 15.0]}
                    }
                ]
            }
        else:
            resp.json.return_value = {"features": []}
    elif "flood-api.open-meteo.com" in url:
        if "25.59" in url or "85.13" in url:
            resp.json.return_value = {
                "daily": {"river_discharge": [20.0, 25.0, 30.0, 180.0, 25.0, 20.0, 22.0, 24.0, 20.0, 25.0]}
            }
        else:
            resp.json.return_value = {
                "daily": {"river_discharge": [0.02, 0.04, 0.01, 0.03, 0.01, 0.02, 0.01, 0.02, 0.01, 0.02]}
            }
    elif "archive-api.open-meteo.com" in url:
        times = [f"{y}-06-15" for y in range(2015, 2025)]
        gusts = [55.0] * 10
        precips = [15.0] * 10
        resp.json.return_value = {
            "daily": {"time": times, "wind_gusts_10m_max": gusts, "precipitation_sum": precips}
        }
    elif "api.open-elevation.com" in url:
        if "25.59" in url:
            resp.json.return_value = {"results": [{"elevation": 53.0}]}
        elif "26.14" in url:
            resp.json.return_value = {"results": [{"elevation": 55.0}]}
        else:
            resp.json.return_value = {"results": [{"elevation": 920.0}]}
    else:
        resp.json.return_value = {}

    return resp

def _mock_http_post(url: str, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    if "overpass-api.de" in url:
        resp.json.return_value = {
            "elements": [
                {
                    "geometry": [
                        {"lat": 12.972, "lon": 77.595},
                        {"lat": 12.973, "lon": 77.596}
                    ]
                }
            ]
        }
    else:
        resp.json.return_value = {}
    return resp

@pytest.fixture
def mock_external_http():
    with patch("httpx.AsyncClient.get", side_effect=_mock_http_response), \
         patch("httpx.AsyncClient.post", side_effect=_mock_http_post):
        yield


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "mock" in data["ai_adapters_available"]
    assert data["active_default_ai"] == "mock"


def test_status_endpoint():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "online"
    assert "groq" in data
    assert "gemini" in data
    assert "default_provider" in data


def test_rate_limiter():
    from app.main import check_rate_limit, _client_request_history
    from fastapi import HTTPException

    ip = "99.99.99.99"
    _client_request_history[ip] = []
    
    # 30 requests should succeed
    for _ in range(30):
        check_rate_limit(ip)
    
    # 31st request should trigger 429
    with pytest.raises(HTTPException) as exc_info:
        check_rate_limit(ip)
    assert exc_info.value.status_code == 429



def test_analyze_endpoint(mock_external_http):
    payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 1500.0,
        "quality_grade": "standard",
        "building_typology": "residential_single",
        "floors": 1,
        "ai_provider": "mock"
    }
    response = client.post("/api/analyze", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "request_id" in data
    assert 0.0 <= data["overall_suitability_score"] <= 100.0
    assert len(data["factors"]) == 5
    assert "optimal_axis_degrees" in data["orientation"]
    assert data["cost_estimate"]["total_estimated_cost_inr"] > 0
    assert len(data["detailed_recommendations"]) > 0
    assert data["ai_metadata"]["provider_used"] == "mock"
    # The popover text is generated from the slope band table and served
    # with the analysis, so the report never re-states a hand-copied formula.
    assert data["methodology"]["slope"].startswith("Piecewise linear score:")
    assert "3.5 × (grade − 8)" in data["methodology"]["slope"]

    # New modules verification
    assert "hazard_profile" in data
    assert data["hazard_profile"]["seismic"]["zone"] in ["Zone II", "Zone III", "Zone IV", "Zone V"]
    assert "land_value" in data
    assert data["land_value"]["locality_multiplier"] >= 0.85
    assert "vastu_advisory" in data
    assert len(data["vastu_advisory"]["ranked_entrances"]) == 3
    assert "recommendation_items" in data
    assert len(data["recommendation_items"]) > 0


def test_differential_bengaluru_vs_guwahati(mock_external_http):
    """
    Deterministic differential check (Amendment 11 fixture-backed):
    Bengaluru site returns Zone II with low seismic history.
    Guwahati site returns Zone V with non-empty event list / high seismic hazard.
    """
    # 1. Bengaluru site
    blr_resp = client.post("/api/analyze", json={
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock"
    })
    assert blr_resp.status_code == 200
    blr_data = blr_resp.json()
    blr_seismic = blr_data["hazard_profile"]["seismic"]
    assert blr_seismic["zone"] == "Zone II"
    assert blr_seismic["zone_factor"] == 0.10

    # 2. Guwahati site
    gau_resp = client.post("/api/analyze", json={
        "latitude": 26.1445,
        "longitude": 91.7362,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock"
    })
    assert gau_resp.status_code == 200
    gau_data = gau_resp.json()
    gau_seismic = gau_data["hazard_profile"]["seismic"]
    assert gau_seismic["zone"] == "Zone V"
    assert gau_seismic["zone_factor"] == 0.36
    # Guwahati has significant tectonic history
    assert gau_seismic["zone_factor"] > blr_seismic["zone_factor"]


def test_differential_river_adjacent_vs_upland(mock_external_http):
    """
    Flood indicator check: river-adjacent site (Patna Ganga bank, ~50m AMSL)
    exhibits higher flood pressure than upland Deccan plateau (Bengaluru, ~920m AMSL).
    """
    blr_resp = client.post("/api/analyze", json={
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock"
    })
    blr_flood = blr_resp.json()["hazard_profile"]["flood"]

    patna_resp = client.post("/api/analyze", json={
        "latitude": 25.5941,
        "longitude": 85.1376,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock"
    })
    patna_flood = patna_resp.json()["hazard_profile"]["flood"]

    # Patna is flood-prone Gangetic lowlands; Bengaluru is Deccan upland
    assert patna_flood["elevation_amsl_m"] < blr_flood["elevation_amsl_m"]
    assert patna_flood["ndma_flood_prone"] is True
    assert blr_flood["ndma_flood_prone"] is False


def test_pdf_report_endpoint_and_timing(mock_external_http):
    """
    Tests vector PDF generation and asserts compilation remains strictly under 3.0 seconds.
    """
    analyze_payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "building_typology": "residential_single",
        "floors": 1,
        "ai_provider": "mock"
    }
    analyze_resp = client.post("/api/analyze", json=analyze_payload)
    assert analyze_resp.status_code == 200
    analysis_data = analyze_resp.json()

    # Time report generation
    t0 = time.time()
    report_resp = client.post("/api/report", json={"analysis_data": analysis_data})
    duration = time.time() - t0

    assert report_resp.status_code == 200
    assert report_resp.headers["content-type"] == "application/pdf"
    assert len(report_resp.content) > 1000
    assert report_resp.content.startswith(b"%PDF")
    assert duration < 3.0  # Must be strictly under 3.0 seconds


def test_pdf_report_with_unlisted_and_null_land_values(mock_external_http):
    """
    Verifies vector PDF compiles cleanly when land rates are unlisted, zero, or null.
    Prevents regressions on unsupported format string passed to NoneType.__format__.
    """
    analyze_resp = client.post("/api/analyze", json={
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock"
    })
    base_data = analyze_resp.json()

    # Case 1: Unlisted rate (rate is None, land_cost is None)
    data_unlisted = dict(base_data)
    data_unlisted["land_value"] = {
        "indicative_rate_per_sqft": None,
        "locality_multiplier": 1.05,
        "land_cost_inr": None,
        "plot_area_sqft": 3333.3,
        "combined_project_total_inr": None,
        "source_publication": "Unlisted Location",
        "disclaimer": "Rate verification required.",
        "is_user_override": False
    }
    resp1 = client.post("/api/report", json={"analysis_data": data_unlisted})
    assert resp1.status_code == 200
    assert resp1.content.startswith(b"%PDF")

    # Case 2: Zero rate passed from client
    data_zero = dict(base_data)
    data_zero["land_value"] = {
        "indicative_rate_per_sqft": 0,
        "locality_multiplier": 1.0,
        "land_cost_inr": None,
        "plot_area_sqft": 3000.0,
        "combined_project_total_inr": None,
        "is_user_override": False
    }
    resp2 = client.post("/api/report", json={"analysis_data": data_zero})
    assert resp2.status_code == 200
    assert resp2.content.startswith(b"%PDF")

    # Case 3: land_value is None entirely
    data_no_land = dict(base_data)
    data_no_land["land_value"] = None
    resp3 = client.post("/api/report", json={"analysis_data": data_no_land})
    assert resp3.status_code == 200
    assert resp3.content.startswith(b"%PDF")

    # Case 4: Hazard null fields
    data_null_hazards = dict(base_data)
    data_null_hazards["hazard_profile"]["flood"]["discharge_peak_to_mean_ratio"] = None
    data_null_hazards["hazard_profile"]["seismic"]["zone_factor"] = None
    data_null_hazards["hazard_profile"]["storm_cyclone"]["max_annual_gust_kmh"] = None
    data_null_hazards["hazard_profile"]["storm_cyclone"]["extreme_rainfall_days"] = None
    resp4 = client.post("/api/report", json={"analysis_data": data_null_hazards})
    assert resp4.status_code == 200
    assert resp4.content.startswith(b"%PDF")


def test_offline_resilience():
    """
    Verifies that when all external network calls fail, the system completes
    a full analysis with deterministic warnings and degraded_mode set to True.
    """
    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")), \
         patch("httpx.AsyncClient.post", side_effect=Exception("Connection refused")):
        resp = client.post("/api/analyze", json={
            "latitude": 12.9716,
            "longitude": 77.5946,
            "built_up_area_sqft": 2000.0,
            "quality_grade": "standard",
            "floors": 1,
            "ai_provider": "mock"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["degraded_mode"] is True
        assert len(data["warnings"]) > 0
        assert data["overall_suitability_score"] > 0
        assert data["hazard_profile"]["seismic"]["zone"] == "Zone II"


@pytest.mark.skip_when_offline
def test_live_api_integration():
    """
    Amendment 11: Exactly one live-API integration test marked skip-when-offline.
    Tests live external network endpoints when online.
    """
    resp = client.post("/api/analyze", json={
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 1500.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "hazard_profile" in data
    assert data["hazard_profile"]["seismic"]["zone"] == "Zone II"


def test_full_user_journey_unified_report(mock_external_http):
    """
    Simulates the full user journey:
    1. POST /api/analyze -> analysis_data
    2. POST /api/site-vision -> site_vision
    3. POST /api/generate-floorplan -> floor_plan
    4. POST /api/report with baseline (no site_vision, no floor_plan) vs unified
    Extracts text using pypdf to assert section presence and page count metrics.
    """
    import io
    import pypdf

    # a. Analyze
    analyze_resp = client.post("/api/analyze", json={
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock"
    })
    assert analyze_resp.status_code == 200
    analysis_data = analyze_resp.json()

    # b. Site Vision
    import numpy as np
    mock_bands = {
        "B02": np.full((24, 24), 1000, dtype=np.float32),
        "B03": np.full((24, 24), 2000, dtype=np.float32),
        "B04": np.full((24, 24), 1500, dtype=np.float32),
        "B08": np.full((24, 24), 5000, dtype=np.float32),
        "B11": np.full((24, 24), 2500, dtype=np.float32)
    }
    mock_imagery = {
        "bands": mock_bands,
        "valid_mask": np.ones((24, 24), dtype=bool),
        "affine_transform": None,
        "crs": "EPSG:32643",
        "shape": (24, 24)
    }

    with patch("app.services.vision.site_vision_service.search_latest_sentinel_scene") as mock_stac, \
         patch("app.services.vision.site_vision_service.fetch_site_imagery") as mock_fetch:

        mock_stac.return_value = {
            "scene_id": "MOCK_S2_SCENE",
            "datetime": "2026-03-31T05:34:56Z",
            "cloud_cover_pct": 0.5,
            "source": "Copernicus Sentinel-2",
            "assets": {"B02": "url", "B03": "url", "B04": "url", "B08": "url"}
        }
        mock_fetch.return_value = mock_imagery

        sv_resp = client.post("/api/site-vision", json={
            "latitude": 12.9716,
            "longitude": 77.5946,
            "plot_area_sqft": 2000.0
        })
        assert sv_resp.status_code == 200
        site_vision = sv_resp.json()

    # c. Floor Plan
    fp_resp = client.post("/api/generate-floorplan", json={
        "plot_width_m": 10.0,
        "plot_depth_m": 12.0,
        "required_rooms": ["master_bed", "kitchen", "living", "puja", "bath_1"],
        "vastu_strictness": "high"
    })
    assert fp_resp.status_code == 200
    floor_plan = fp_resp.json()

    # Baseline report (omitting both site_vision and floor_plan)
    resp_base = client.post("/api/report", json={
        "analysis_data": analysis_data,
        "site_vision": None,
        "floor_plan": None
    })
    assert resp_base.status_code == 200
    assert resp_base.content.startswith(b"%PDF-1.4")
    base_size = len(resp_base.content)

    # d. Unified report with ALL THREE objects combined
    resp_full = client.post("/api/report", json={
        "analysis_data": analysis_data,
        "site_vision": site_vision,
        "floor_plan": floor_plan
    })
    assert resp_full.status_code == 200
    assert resp_full.content.startswith(b"%PDF-1.4")
    full_size = len(resp_full.content)

    # Assert significant size increase due to vector blueprint drawing and section additions
    assert full_size > base_size + 1000, f"Expected size increase with floor_plan, got {full_size} vs {base_size}"

    # Extract text from both PDFs using pypdf
    reader_base = pypdf.PdfReader(io.BytesIO(resp_base.content))
    base_text = "".join(page.extract_text() or "" for page in reader_base.pages)

    reader_full = pypdf.PdfReader(io.BytesIO(resp_full.content))
    full_text = "".join(page.extract_text() or "" for page in reader_full.pages)

    # Assert baseline text does NOT contain Sections 9 or 10
    assert "Ecological Site Vision" not in base_text
    assert "Generative Architectural Blueprint" not in base_text

    # Assert unified text contains both sections
    assert "Ecological Site Vision" in full_text
    assert "Generative Architectural Blueprint" in full_text

    # Assert unified page count is greater than or equal to baseline page count
    assert len(reader_full.pages) >= len(reader_base.pages)


def test_generate_floorplan_pdf_streaming(mock_external_http):
    """
    Verifies that /api/generate-floorplan streams a multi-page PDF dossier when format='pdf',
    and /api/report includes multi-storey Sheet 10.0 and floor sheets when multi_storey is present.
    """
    # 1. Test /api/generate-floorplan?format=pdf directly
    fp_payload = {
        "plot_width_m": 22.0,
        "plot_depth_m": 18.0,
        "floors": 4,
        "building_typology": "T2_FAMILY_APARTMENT",
        "vastu_strictness": "medium",
        "required_rooms": ["living", "kitchen", "master_bed", "bath_1", "dining", "stairs", "lift"]
    }
    pdf_resp = client.post("/api/generate-floorplan?format=pdf", json=fp_payload)
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF")

    reader = pypdf.PdfReader(io.BytesIO(pdf_resp.content))
    assert len(reader.pages) >= 5
    full_text = "".join(page.extract_text() or "" for page in reader.pages)
    assert "10.0" in full_text
    assert "Multi-Storey Architectural Dossier" in full_text
    assert "10.1" in full_text
    assert "10.2" in full_text
    assert "10.3" in full_text
    assert "10.4" in full_text

    # 2. Test /api/report with multi_storey floor plan payload
    json_resp = client.post("/api/generate-floorplan", json=fp_payload)
    assert json_resp.status_code == 200
    fp_json = json_resp.json()
    assert "multi_storey" in fp_json
    assert len(fp_json["multi_storey"]["floors"]) == 4

    analyze_resp = client.post("/api/analyze", json={
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 4000.0,
        "quality_grade": "premium",
        "building_typology": "T2_FAMILY_APARTMENT",
        "floors": 4,
        "ai_provider": "mock"
    })
    analysis_data = analyze_resp.json()

    report_resp = client.post("/api/report", json={
        "analysis_data": analysis_data,
        "floor_plan": fp_json
    })
    assert report_resp.status_code == 200
    assert report_resp.headers["content-type"] == "application/pdf"
    assert report_resp.content.startswith(b"%PDF")

    rep_reader = pypdf.PdfReader(io.BytesIO(report_resp.content))
    rep_text = "".join(page.extract_text() or "" for page in rep_reader.pages)
    assert "Multi-Storey Architectural Dossier & Core Stacking Analysis" in rep_text
    assert "Sheet 10.1" in rep_text
    assert "100% Locked" in rep_text or "Vertical Cores Locked" in rep_text


def test_llm_metadata_cannot_override_deterministic_scores(mock_external_http):
    """
    AI adapters narrate only. A malicious/hallucinating
    LLM metadata block must never change feasibility_score, cost_breakdown, or
    vastu_compliance - those fields always mirror the deterministic engines.
    """
    resp = client.post("/api/analyze", json={
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock"
    })
    assert resp.status_code == 200
    data = resp.json()

    # feasibility_score must equal the deterministic MCDA score
    assert data["feasibility_score"] == int(round(data["overall_suitability_score"]))

    # cost/vastu blocks must equal the deterministic engines
    assert data["cost_breakdown"] == data["cost_estimate"]
    assert data["vastu_compliance"] == data["vastu_advisory"]


def test_analyze_rejects_self_intersecting_boundary(mock_external_http):
    """Bow-tie polygons are rejected (422), not silently accepted."""
    payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 1500.0,
        "quality_grade": "standard",
        "floors": 1,
        "ai_provider": "mock",
        "boundary": {
            # Asymmetric bow-tie: shoelace area is 150 m2 (>= 36), all edges
            # >= 1 m, but the outline genuinely crosses itself.
            "vertices": [
                {"x": 0.0, "y": 0.0},
                {"x": 30.0, "y": 10.0},
                {"x": 30.0, "y": 0.0},
                {"x": 0.0, "y": 20.0},
            ],
            "origin_lat": 12.9716,
            "origin_lon": 77.5946,
            "shape_type": "irregular",
            "area_sqm": 150.0,
            "perimeter_m": 97.7,
            "source": "trace",
            "frontage_edge_index": None,
        },
    }
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 422
    assert "self-intersecting" in resp.json()["detail"]


def test_report_endpoint_rejects_invalid_payload(mock_external_http):
    """/api/report validates payload structure instead of rendering garbage."""
    # Non-numeric latitude in coordinates
    resp1 = client.post("/api/report", json={
        "analysis_data": {
            "coordinates": {"latitude": "12.5; DROP TABLE", "longitude": 77.59},
            "overall_suitability_score": 80.0,
        }
    })
    assert resp1.status_code == 422

    # Non-numeric overall_suitability_score
    resp2 = client.post("/api/report", json={
        "analysis_data": {
            "coordinates": {"latitude": 12.5, "longitude": 77.59},
            "overall_suitability_score": "excellent",
        }
    })
    assert resp2.status_code == 422

    # Out-of-range latitude
    resp3 = client.post("/api/report", json={
        "analysis_data": {
            "coordinates": {"latitude": 999.0, "longitude": 77.59},
            "overall_suitability_score": 80.0,
        }
    })
    assert resp3.status_code == 422

    # Non-object analysis_data
    resp4 = client.post("/api/report", json={"analysis_data": [1, 2, 3]})
    assert resp4.status_code == 422


def test_rate_limiter_prunes_idle_ips():
    """Idle IP buckets are removed so the history map cannot grow unboundedly."""
    from app.main import check_rate_limit, _client_request_history, _LAST_HISTORY_PRUNE

    target_ip = "98.76.54.32"
    idle_ip = "11.22.33.44"
    # Reset the prune gate so this test's call definitely sweeps
    _LAST_HISTORY_PRUNE[0] = 0.0
    # Age both buckets beyond the window
    _client_request_history[target_ip] = [time.time() - 3600.0]
    _client_request_history[idle_ip] = [time.time() - 3600.0]

    check_rate_limit(target_ip)  # triggers global prune, then a fresh visit

    # The unrelated idle bucket must be gone entirely
    assert idle_ip not in _client_request_history
    # The target bucket was re-created by the fresh visit (only fresh timestamps)
    fresh = _client_request_history[target_ip]
    assert fresh and all(time.time() - t < 60.0 for t in fresh)

