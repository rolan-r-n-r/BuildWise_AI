"""
test_site_ai_analysis.py — Tests for enhanced Site Feasibility AI Analysis.
Verifies prompt richness, structured output schema, deterministic mock generation, and absence of ugly redaction tags.
"""
import pytest
from app.ai.prompts import build_rich_site_analysis_prompt, CIVIL_ENGINEER_SYSTEM_PROMPT
from app.ai.mock_adapter import MockExplanationAdapter
from app.schemas.response import SiteFeasibilityAIAnalysis, AnalysisResponse
from app.services.ai_narrative import sanitize_narrative


@pytest.mark.asyncio
async def test_build_rich_site_analysis_prompt():
    sample_data = {
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Cubbon Park, Bengaluru, Karnataka",
        "built_up_area_sqft": 2400.0,
        "quality_grade": "premium",
        "building_typology": "residential_single",
        "floors": 2,
        "ground_coverage_ratio": 0.55,
        "client_requirements": "Open courtyard with north-facing pooja room and solar panels.",
        "overall_suitability_score": 82.5,
        "suitability_verdict": "Suitable",
        "factors": [
            {"factor_id": "slope", "raw_value": 3.2, "score": 92.0},
            {"factor_id": "road_access", "raw_value": 12.0, "score": 95.0},
        ],
        "hazard_profile": {
            "seismic": {"zone": "Zone II", "zone_factor": 0.10},
            "flood": {"pressure_level": "low"},
            "storm_cyclone": {"exposure_level": "moderate", "max_annual_gust_kmh": 52.0},
        },
        "orientation": {
            "optimal_axis_degrees": 95.0,
            "axis_label": "East-West",
            "cross_ventilation_rating": "Optimal",
            "prevailing_wind_direction_degrees": 230.0,
        },
        "cost_estimate": {
            "base_rate_per_sqft": 3500.0,
            "terrain_multiplier": 1.05,
            "total_estimated_cost_inr": 8820000.0,
        },
        "land_value": {
            "indicative_rate_per_sqft": 14000.0,
            "land_cost_inr": 33600000.0,
        },
        "vastu_advisory": {
            "ranked_entrances": [{"direction": "North-East", "score": 98.0}],
            "road_approach": {"approach_side": "east"},
        },
    }

    prompt = build_rich_site_analysis_prompt(sample_data)

    # Verify all essential dimensions are present in the prompt
    assert "Cubbon Park, Bengaluru" in prompt
    assert "2,400 sq ft" in prompt
    assert "G+1" in prompt
    assert "Open courtyard" in prompt
    assert "3.2%" in prompt  # slope
    assert "Zone II" in prompt
    assert "East-West" in prompt
    assert "North-East" in prompt
    assert "INR 8,820,000" in prompt


@pytest.mark.asyncio
async def test_mock_adapter_structured_narrative_and_no_redactions():
    sample_data = {
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Bengaluru Site",
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "building_typology": "residential_single",
        "floors": 1,
        "overall_suitability_score": 78.0,
        "suitability_verdict": "Suitable",
        "factors": [
            {"factor_id": "slope", "raw_value": 2.0, "score": 95.0},
        ],
        "hazard_profile": {
            "seismic": {"zone": "Zone II", "zone_factor": 0.10},
            "flood": {"pressure_level": "low"},
            "storm_cyclone": {"exposure_level": "low", "max_annual_gust_kmh": 40.0},
        },
        "orientation": {
            "optimal_axis_degrees": 90.0,
            "axis_label": "East-West",
            "cross_ventilation_rating": "Good",
            "prevailing_wind_direction_degrees": 225.0,
        },
        "cost_estimate": {
            "total_estimated_cost_inr": 4400000.0,
            "terrain_multiplier": 1.0,
        },
        "vastu_advisory": {
            "ranked_entrances": [{"direction": "NE", "score": 95.0}],
            "road_approach": {"approach_side": "north"},
        },
    }

    adapter = MockExplanationAdapter()
    summary, recs, meta = await adapter.generate_explanation(sample_data)

    # Verify summary and parameter reflection
    assert len(summary) > 50
    assert len(recs) >= 3

    # Verify that sanitizing narrative on the deterministic mock produces ZERO redactions!
    clean_summary, summary_redactions = sanitize_narrative(summary)
    assert len(summary_redactions) == 0, f"Redactions found in mock summary: {summary_redactions}"
    assert "[amount removed" not in clean_summary
    assert "[zone removed" not in clean_summary
    assert "[rate removed" not in clean_summary

    param_ref = meta.get("parameter_reflection", "")
    clean_ref, ref_redactions = sanitize_narrative(param_ref)
    assert len(ref_redactions) == 0, f"Redactions found in parameter reflection: {ref_redactions}"
    assert "[amount removed" not in clean_ref

    # Verify structured narrative exists and validates against SiteFeasibilityAIAnalysis
    sn_raw = meta.get("structured_narrative")
    assert sn_raw is not None
    assert isinstance(sn_raw, dict)

    sn = SiteFeasibilityAIAnalysis.model_validate(sn_raw)
    assert len(sn.executive_summary) > 50
    assert len(sn.key_strengths) >= 2
    assert len(sn.key_concerns) >= 1
    assert len(sn.engineering_considerations) >= 3
    assert len(sn.environmental_and_hazards) >= 2
    assert len(sn.financial_considerations) >= 2
    assert len(sn.required_investigations) >= 3
    assert len(sn.recommended_next_steps) >= 3
