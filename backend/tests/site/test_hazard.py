import pytest
from unittest.mock import patch, MagicMock
from app.services.hazard_service import (
    match_seismic_zone,
    check_ndma_flags,
    compute_overall_hazard_level,
    fetch_usgs_seismic_data,
    fetch_open_meteo_flood_data,
    fetch_era5_storm_data,
    evaluate_hazard_profile
)

def test_seismic_zone_lookup_hits():
    # Bengaluru -> Zone II (0.10)
    z, f, std, dist, warn = match_seismic_zone("Bengaluru Urban, Karnataka, India", 12.97, 77.59)
    assert z == "Zone II"
    assert f == 0.10
    assert warn is None

    # Delhi -> Zone IV (0.24)
    z, f, std, dist, warn = match_seismic_zone("Connaught Place, New Delhi, Delhi", 28.61, 77.20)
    assert z == "Zone IV"
    assert f == 0.24
    assert warn is None

    # Guwahati -> Zone V (0.36)
    z, f, std, dist, warn = match_seismic_zone("GS Road, Guwahati, Kamrup, Assam", 26.14, 91.73)
    assert z == "Zone V"
    assert f == 0.36
    assert warn is None


def test_seismic_zone_lookup_miss():
    # Coordinates outside India must return zone=None
    # ("Not Assessed") - never a fabricated default Zone III.
    z, f, std, dist, warn = match_seismic_zone("Remote Outpost, Atlantis", 0.0, 0.0)
    assert z is None
    assert f is None
    assert warn is not None
    assert "outside the IS 1893:2016" in warn

    # In-India unlisted district still gets the conservative default with a warning
    z_in, f_in, std_in, dist_in, warn_in = match_seismic_zone("Unknown Taluk, Unlisted State", 15.0, 75.0)
    assert z_in == "Zone III"
    assert f_in == 0.16
    assert warn_in is not None
    assert "not matched" in warn_in.lower()


def test_seismic_zone_coordinate_box_is_moderate_confidence():
    # Coordinate-cluster box matches carry a
    # moderate-confidence warning instead of silently claiming high confidence.
    z, f, std, dist, warn = match_seismic_zone("Some Locality", 12.9, 77.4)  # Bengaluru box
    assert z == "Zone II"
    assert warn is not None
    assert "coordinate cluster" in warn


def test_ndma_flags():
    # Flood prone check
    flood_kamrup, _ = check_ndma_flags("Kamrup Metropolitan, Assam")
    assert flood_kamrup is True

    # Cyclone prone check
    _, cyclone_puri = check_ndma_flags("Puri, Odisha")
    assert cyclone_puri is True

    # Non-hazard district
    flood_blr, cyclone_blr = check_ndma_flags("Bengaluru, Karnataka")
    assert flood_blr is False
    assert cyclone_blr is False


def test_overall_hazard_aggregation_rules():
    # Amendment 7 test matrix
    # 1. Base max(flood, storm)
    assert compute_overall_hazard_level("low", "low", "Zone II", 0) == "low"
    assert compute_overall_hazard_level("low", "moderate", "Zone II", 0) == "moderate"
    assert compute_overall_hazard_level("high", "low", "Zone II", 0) == "high"

    # 2. Zone IV upgrade (+1 level)
    assert compute_overall_hazard_level("low", "low", "Zone IV", 0) == "moderate"
    assert compute_overall_hazard_level("low", "moderate", "Zone IV", 0) == "high"
    assert compute_overall_hazard_level("high", "low", "Zone IV", 0) == "high"

    # 3. Zone V with events -> at least high
    assert compute_overall_hazard_level("low", "low", "Zone V", 5) == "high"
    assert compute_overall_hazard_level("moderate", "low", "Zone V", 1) == "high"

    # 4. Zone V with high flood OR high storm -> critical
    assert compute_overall_hazard_level("high", "low", "Zone V", 2) == "critical"
    assert compute_overall_hazard_level("low", "high", "Zone V", 0) == "critical"
    assert compute_overall_hazard_level("high", "high", "Zone V", 3) == "critical"


@pytest.mark.asyncio
async def test_usgs_seismic_parsing_and_cap():
    # Mock HTTP response with 250 events (simulating capping per Amendment 2.a)
    mock_features = []
    for i in range(250):
        mock_features.append({
            "properties": {
                "mag": 5.0 + (i % 3) * 0.5,
                "time": 1600000000000 + i * 1000,
                "place": f"Epicenter {i}"
            },
            "geometry": {"coordinates": [91.7 + i*0.01, 26.1 + i*0.01, 10.0]}
        })

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"features": mock_features}

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        res, fallback = await fetch_usgs_seismic_data(26.14, 91.73)
        assert fallback is False
        assert res["event_count"] == 250
        assert res["is_capped"] is True
        assert res["event_count_display"] == "250+"
        assert len(res["recent_major_events"]) == 5
        assert res["max_magnitude"] is not None


@pytest.mark.asyncio
async def test_open_meteo_flood_guards():
    # 1. Normal discharge series -> ratio computed and capped at 20.0
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "daily": {"river_discharge": [1.0, 2.0, 1.0, 30.0, 1.0, 2.0, 1.0, 1.0, 1.0, 1.0]}
    }
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        ratio, fallback = await fetch_open_meteo_flood_data(25.59, 85.13)
        assert fallback is False
        assert ratio is not None
        assert ratio <= 20.0  # Capped at 20.0

    # 2. Negligible flow (<0.1 m3/s) -> ratio is None (Amendment 3)
    mock_resp_dry = MagicMock()
    mock_resp_dry.status_code = 200
    mock_resp_dry.json.return_value = {
        "daily": {"river_discharge": [0.02, 0.05, 0.01, 0.08, 0.03, 0.01, 0.02, 0.04, 0.01, 0.02]}
    }
    with patch("httpx.AsyncClient.get", return_value=mock_resp_dry):
        ratio_dry, fallback_dry = await fetch_open_meteo_flood_data(12.97, 77.59)
        assert fallback_dry is False
        assert ratio_dry is None


@pytest.mark.asyncio
async def test_era5_storm_parsing():
    # 10 years of data
    times = []
    gusts = []
    precips = []
    for y in range(2015, 2025):
        for d in range(1, 30):
            times.append(f"{y}-07-{d:02d}")
            gusts.append(60.0 if d == 15 else 30.0)
            precips.append(55.0 if d == 10 else 5.0)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "daily": {"time": times, "wind_gusts_10m_max": gusts, "precipitation_sum": precips}
    }
    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        max_gust, ext_days, fallback = await fetch_era5_storm_data(13.08, 80.27)
        assert fallback is False
        assert max_gust == 60.0
        assert ext_days == 1.0


@pytest.mark.asyncio
async def test_evaluate_hazard_profile_offline_fallback():
    # Force HTTP client exception
    with patch("httpx.AsyncClient.get", side_effect=Exception("Network error")):
        profile, warnings = await evaluate_hazard_profile(12.9716, 77.5946, 920.0, "Bengaluru, Karnataka")
        assert profile.seismic.zone == "Zone II"
        assert profile.flood.pressure_level in ["low", "moderate"]
        assert len(warnings) > 0


@pytest.mark.asyncio
async def test_geocode_failure_does_not_silently_misfire_ndma():
    """
    When the reverse-geocode fallback identifier is
    passed, NDMA district name matching must be skipped with an explicit
    warning instead of silently returning false flags.
    """
    with patch("httpx.AsyncClient.get", side_effect=Exception("Network error")):
        profile, warnings = await evaluate_hazard_profile(26.14, 91.73, 55.0, "Site Location (26.1400N, 91.7362E)")
        joined = " ".join(warnings)
        assert "Reverse geocoding unavailable" in joined
        assert profile.flood.ndma_flood_prone is False
        assert profile.flood.confidence == "low"


@pytest.mark.asyncio
async def test_hazard_profile_outside_india_not_assessed():
    """Non-India coordinates yield zone=None, never a default zone."""
    with patch("httpx.AsyncClient.get", side_effect=Exception("Network error")):
        profile, warnings = await evaluate_hazard_profile(51.5074, -0.1278, 11.0, "London, United Kingdom")
        assert profile.seismic.zone is None
        assert profile.seismic.zone_factor is None
        assert profile.seismic.confidence == "low"
        assert any("outside the IS 1893:2016" in w for w in warnings)
