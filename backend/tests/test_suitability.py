import pytest
from app.services.suitability_service import (
    calculate_slope_score,
    calculate_flood_score,
    calculate_road_access_score,
    calculate_facility_score,
    evaluate_land_suitability
)
from app.schemas.response import FloodProfile

def test_slope_score_boundaries():
    score_flat, status_flat, _ = calculate_slope_score(2.0)
    assert score_flat == 100.0
    assert status_flat == "optimal"

    score_gentle, status_gentle, _ = calculate_slope_score(6.0)
    assert 70.0 <= score_gentle < 85.0
    assert status_gentle == "optimal"

    score_steep, status_steep, _ = calculate_slope_score(18.0)
    assert 20.0 <= score_steep <= 45.0
    assert status_steep == "critical"

def test_flood_score_boundaries():
    score_high_elev, status_high, _ = calculate_flood_score(500.0, 800.0)
    assert score_high_elev >= 80.0
    assert status_high == "optimal"

    score_low_elev, status_low, _ = calculate_flood_score(5.0, 1800.0)
    assert score_low_elev < 75.0

def test_overall_suitability_weights():
    climate = {
        "temperature_max_c": 30.0,
        "temperature_min_c": 20.0,
        "wind_speed_kmh": 12.0,
        "annual_precipitation_mm": 900.0
    }
    score, verdict, factors = evaluate_land_suitability(
        lat=12.97,
        lon=77.59,
        elevation_m=920.0,
        slope_pct=2.5,
        climate=climate
    )
    assert len(factors) == 5
    total_weight = sum(f.weight for f in factors)
    assert pytest.approx(total_weight, 0.001) == 1.0
    assert 0.0 <= score <= 100.0
    assert verdict in ["Suitable", "Conditionally Suitable", "Challenging"]


def test_road_access_score_uses_real_distance_not_trig_proxy():
    """
    Road accessibility derives from the measured
    Overpass distance, or reports an honest unknown - never a coordinate
    trigonometry proxy presented as measured data.
    """
    score_close, status_close, details_close, raw_close = calculate_road_access_score(30.0, True)
    assert score_close == 90.0
    assert status_close == "optimal"
    assert raw_close == 30.0
    assert "30 m" in details_close

    score_far, status_far, _, raw_far = calculate_road_access_score(400.0, True)
    assert score_far == 55.0
    assert status_far == "acceptable"
    assert raw_far == 400.0

    # Overpass reachable but no mapped road within 500 m -> critical, disclosed
    score_none, status_none, details_none, raw_none = calculate_road_access_score(None, True)
    assert status_none == "critical"
    assert raw_none is None
    assert "No mapped road within 500 m" in details_none

    # Service unreachable -> honest 'unknown', never fabricated
    score_unknown, status_unknown, details_unknown, raw_unknown = calculate_road_access_score(None, False)
    assert status_unknown == "unknown"
    assert raw_unknown is None
    assert "not measured" in details_unknown.lower()


def test_facility_score_is_labelled_proxy():
    """Facility proximity must disclose that it is a modelled proxy."""
    _, _, details = calculate_facility_score(12.97, 77.59)
    assert "proxy" in details.lower()
    assert "verify" in details.lower()


def test_facility_score_osm_measured():
    """Measured OSM facility counts must score accurately across tiers."""
    # Optimal: >= 15
    score_opt, status_opt, details_opt = calculate_facility_score(12.97, 77.59, facility_count=22)
    assert score_opt == 90.0
    assert status_opt == "optimal"
    assert "22 facilities" in details_opt
    assert "OpenStreetMap" in details_opt

    # Acceptable: 5-14
    score_acc, status_acc, details_acc = calculate_facility_score(12.97, 77.59, facility_count=8)
    assert score_acc == 75.0
    assert status_acc == "acceptable"

    # Developing: 1-4
    score_dev, status_dev, details_dev = calculate_facility_score(12.97, 77.59, facility_count=2)
    assert score_dev == 60.0
    assert status_dev == "acceptable"

    # Critical: 0
    score_zero, status_zero, details_zero = calculate_facility_score(12.97, 77.59, facility_count=0)
    assert score_zero == 45.0
    assert status_zero == "critical"
    assert "zero civic amenities" in details_zero.lower()


def test_evaluate_land_suitability_with_facility_count():
    climate = {"temperature_max_c": 30.0, "temperature_min_c": 18.0, "wind_speed_kmh": 10.0, "annual_precipitation_mm": 800.0}
    _, _, factors = evaluate_land_suitability(
        lat=12.97, lon=77.59, elevation_m=900.0, slope_pct=2.0, climate=climate,
        facility_count=18
    )
    fac_factor = next(f for f in factors if f.factor_id == "facility_proximity")
    assert fac_factor.name == "Proximity to Facilities (OpenStreetMap)"
    assert fac_factor.raw_value == 18.0
    assert fac_factor.score == 90.0


def test_flood_score_fuses_hazard_profile_conservatively():
    """
    When a hazard FloodProfile is supplied, the worse of the
    elevation proxy and the discharge pressure level governs, so the report
    carries one consistent flood signal.
    """
    # Elevation proxy alone would score high (920 m AMSL, modest rain)
    base_score, _, _ = calculate_flood_score(920.0, 900.0)
    assert base_score >= 75.0

    high_profile = FloodProfile(
        discharge_peak_to_mean_ratio=8.0,
        pressure_level="high",
        ndma_flood_prone=False,
        elevation_amsl_m=920.0,
        confidence="high",
    )
    fused_score, fused_status, fused_details = calculate_flood_score(920.0, 900.0, flood_profile=high_profile)
    assert fused_score < base_score  # conservative fusion
    assert fused_status == "critical"
    assert "HIGH flood pressure" in fused_details

    low_profile = FloodProfile(
        discharge_peak_to_mean_ratio=1.2,
        pressure_level="low",
        ndma_flood_prone=False,
        elevation_amsl_m=920.0,
        confidence="high",
    )
    fused_low, _, details_low = calculate_flood_score(920.0, 900.0, flood_profile=low_profile)
    # Conservative fusion: 'low' pressure caps the proxy at 85.0
    assert fused_low == 85.0
    assert fused_low <= base_score
    assert "low flood pressure" in details_low
