import pytest
from app.services.recommendation_service import (
    generate_recommendations,
    get_top_severity_recommendations
)
from app.schemas.response import (
    FactorScore,
    HazardProfile,
    SeismicProfile,
    FloodProfile,
    StormCycloneProfile,
    LandValueEstimate,
    MultiplierBreakdown,
    VastuAdvisory,
    RankedEntrance,
    RoomGridZone,
    SlopeReading,
    ReconciliationItem,
    RoadApproach,
    OrientationData,
    CostEstimate
)

def _build_dummy_inputs(
    seismic_zone="Zone II",
    seismic_factor=0.10,
    flood_level="low",
    flood_ratio=1.5,
    slope_pct=2.0,
    storm_level="low",
    max_gust=45.0,
    ind_rate=8500.0,
    is_override=False,
    drainage_dir="NE",
    drainage_status="favourable"
):
    factors = [
        FactorScore(factor_id="slope", name="Topographic Slope", weight=0.25, raw_value=slope_pct, unit="%", score=100.0, status="optimal", details=""),
        FactorScore(factor_id="flood_risk", name="Flood Risk", weight=0.20, raw_value=900.0, unit="m AMSL", score=90.0, status="optimal", details=""),
        FactorScore(factor_id="road_access", name="Road Access", weight=0.20, raw_value=120.0, unit="m", score=85.0, status="optimal", details=""),
        FactorScore(factor_id="environmental_comfort", name="Env Comfort", weight=0.15, raw_value=32.0, unit="deg C", score=80.0, status="optimal", details=""),
        FactorScore(factor_id="facility_proximity", name="Facility Proximity", weight=0.20, raw_value=75.0, unit="idx", score=75.0, status="optimal", details="")
    ]

    hazard = HazardProfile(
        seismic=SeismicProfile(
            zone=seismic_zone,
            zone_factor=seismic_factor,
            standard="BIS IS 1893:2016",
            district="Test District",
            event_count_50yr_250km=10 if seismic_zone in ["Zone IV", "Zone V"] else 0,
            event_count_display="10" if seismic_zone in ["Zone IV", "Zone V"] else "0",
            confidence="high"
        ),
        flood=FloodProfile(
            discharge_peak_to_mean_ratio=flood_ratio,
            pressure_level=flood_level,
            ndma_flood_prone=(flood_level == "high"),
            elevation_amsl_m=500.0,
            confidence="high"
        ),
        storm_cyclone=StormCycloneProfile(
            max_annual_gust_kmh=max_gust,
            extreme_rainfall_days=2.0,
            exposure_level=storm_level,
            ndma_cyclone_prone=(storm_level == "high"),
            confidence="high"
        ),
        overall_hazard_level="moderate"
    )

    land = LandValueEstimate(
        indicative_rate_per_sqft=ind_rate,
        base_table_rate_per_sqft=ind_rate if not is_override else 7000.0,
        is_user_override=is_override,
        locality_multiplier=1.05,
        multiplier_breakdown=MultiplierBreakdown(
            road_accessibility_score=85.0,
            road_contribution=0.075,
            facility_proximity_score=75.0,
            facility_contribution=0.025,
            net_multiplier=1.05,
            is_clamped=False
        ),
        plot_area_sqft=2000.0,
        ground_coverage_ratio_applied=0.60,
        land_cost_inr=(2000.0 * ind_rate) if ind_rate else None,
        construction_cost_inr=4000000.0,
        combined_project_total_inr=((2000.0 * ind_rate) + 4000000.0) if ind_rate else None,
        as_of_year=2024,
        jurisdiction_zone="Urban Test Zone",
        source_publication="State Gazette",
        disclaimer="Test disclaimer"
    )

    vastu = VastuAdvisory(
        ranked_entrances=[
            RankedEntrance(direction="NE", score=110.0, vastu_rationale="", practical_rationale="Ingress walkway clear.", is_approach_side=False),
            RankedEntrance(direction="E", score=100.0, vastu_rationale="", practical_rationale="", is_approach_side=False),
            RankedEntrance(direction="S", score=85.0, vastu_rationale="", practical_rationale="", is_approach_side=True)
        ],
        room_grid=[],
        slope_reading=SlopeReading(
            drainage_direction=drainage_dir,
            azimuth_degrees=45.0,
            auspiciousness=drainage_status,
            rationale="",
            remedy_notes="Elevate plinth" if drainage_status == "requires_remedy" else None
        ),
        reconciliation_notes=[],
        road_approach=RoadApproach(bearing_degrees=180.0, approach_side="S", distance_meters=20.0, is_fallback=False)
    )

    orientation = OrientationData(
        optimal_axis_degrees=90.0,
        axis_label="East-West",
        prevailing_wind_direction_degrees=240.0,
        solar_exposure_summary="",
        cross_ventilation_rating="Good",
        passive_design_rationale=""
    )

    cost = CostEstimate(
        base_rate_per_sqft=2200.0,
        terrain_multiplier=1.0,
        base_cost_inr=4000000.0,
        terrain_surcharge_inr=0.0,
        total_estimated_cost_inr=4000000.0,
        cost_range_min_inr=3700000.0,
        cost_range_max_inr=4300000.0,
        breakdown=[],
        disclaimer=""
    )

    return factors, hazard, land, vastu, orientation, cost


def test_recommendation_rule_firing_and_severities():
    # Scenario: Guwahati site (Zone V, High Flood, Slope 18%, High Storm)
    f, h, l, v, o, c = _build_dummy_inputs(
        seismic_zone="Zone V",
        seismic_factor=0.36,
        flood_level="high",
        flood_ratio=6.2,
        slope_pct=18.0,
        storm_level="high",
        max_gust=95.0,
        ind_rate=3800.0,
        is_override=False,
        drainage_dir="SW",
        drainage_status="requires_remedy"
    )

    items = generate_recommendations(f, h, l, v, o, c)
    rule_ids = [item.rule_id for item in items]

    # Verify critical rules fired
    assert "STR-001" in rule_ids
    assert "FLD-001" in rule_ids
    assert "SLP-001" in rule_ids
    assert "STM-001" in rule_ids

    # Verify advisory rules fired
    assert "VAS-001" in rule_ids
    assert "VAS-002" in rule_ids
    assert "LND-001" in rule_ids

    # Verify optimal rules fired
    assert "ACC-001" in rule_ids
    assert "CLM-001" in rule_ids

    # Check severity ordering: critical items must come first
    severities = [item.severity for item in items]
    critical_indices = [i for i, s in enumerate(severities) if s == "critical"]
    advisory_indices = [i for i, s in enumerate(severities) if s == "advisory"]
    optimal_indices = [i for i, s in enumerate(severities) if s == "optimal"]

    assert max(critical_indices) < min(advisory_indices)
    assert max(advisory_indices) < min(optimal_indices)


def test_recommendation_lnd003_when_rate_is_null():
    # Scenario: Land rate is null and no override supplied (Amendment 8)
    f, h, l, v, o, c = _build_dummy_inputs(ind_rate=None, is_override=False)
    items = generate_recommendations(f, h, l, v, o, c)
    rule_ids = [item.rule_id for item in items]
    assert "LND-003" in rule_ids
    assert "LND-001" not in rule_ids
    assert "LND-002" not in rule_ids

    lnd3_item = next(it for it in items if it.rule_id == "LND-003")
    assert lnd3_item.severity == "advisory"


def test_top_severity_recommendations_cap():
    # Amendment 10: AI adapter payload capped to top 8 items
    f, h, l, v, o, c = _build_dummy_inputs(
        seismic_zone="Zone V",
        flood_level="high",
        slope_pct=22.0,
        storm_level="high",
        ind_rate=4500.0,
        drainage_dir="S",
        drainage_status="requires_remedy"
    )
    items = generate_recommendations(f, h, l, v, o, c)
    assert len(items) > 8  # Full list has 9-10 items

    top_8 = get_top_severity_recommendations(items, limit=8)
    assert len(top_8) == 8
    # Top 8 must retain critical items first
    assert top_8[0].severity == "critical"
