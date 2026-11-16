"""
test_blueprint_ai_analysis.py — Tests for the AI Blueprint Warning and Plan Advisor service.
Verifies categorization into 7 standard categories, issue grouping, prioritized actions, and deterministic execution.
"""
import pytest
from app.schemas.blueprint_ai import (
    BlueprintAIAnalysisRequest,
    BlueprintAIAnalysisResponse,
)
from app.services.blueprint_ai_advisor import (
    DeterministicWarningAnalyzer,
    BlueprintAIAdvisorService,
)


def test_deterministic_warning_analyzer_categorization():
    sample_warnings = [
        "FAIL-L4: Core accessibility violation: staircase egress blocked by corridor pinch point.",
        "PROP-DIM-01: Master Bedroom aspect ratio 2.45:1 exceeds maximum allowable 2.2:1.",
        "NBC 2016: Kitchen habitable room area 4.8 sqm is below statutory minimum 5.0 sqm.",
        "Circulation clearance violation: secondary passage width 0.85m is below 1.0m requirement.",
        "Vertical stacking deviation: Floor 2 toilet wet wall shifted 1.2m away from Ground Floor shaft.",
        "Vastu advisory: Master Bedroom placed in North-East quadrant contrary to South-West recommendation.",
        "Relaxed high Vastu strictness to medium to accommodate all requested room sizes.",
    ]

    req = BlueprintAIAnalysisRequest(
        warnings=sample_warnings,
        plan_verdict="NOT-CERTIFIED-FAIL-STAMP",
        built_up_area_sqft=2200.0,
        floors=2,
        building_typology="residential_single",
    )

    resp = DeterministicWarningAnalyzer.analyze_deterministic(req)

    assert isinstance(resp, BlueprintAIAnalysisResponse)
    cats = resp.categorized_warnings

    # Verify the 7 categories classification
    assert "Critical Issues" in cats
    assert any("FAIL-L4" in w.original_warning for w in cats["Critical Issues"])
    critical_w = cats["Critical Issues"][0]
    assert critical_w.severity == "critical"
    assert critical_w.requires_professional_review is True
    assert critical_w.ai_priority == "critical"
    assert "rejection" in critical_w.potential_risk.lower()

    assert "Space & Dimension" in cats
    assert any("PROP-DIM" in w.original_warning for w in cats["Space & Dimension"])
    dim_w = [w for w in cats["Space & Dimension"] if "PROP-DIM" in w.original_warning][0]
    assert dim_w.affected_element == "Master Bedroom"

    assert "Building Code & Compliance" in cats
    assert any("NBC 2016" in w.original_warning for w in cats["Building Code & Compliance"])

    assert "Circulation & Accessibility" in cats
    assert any("Circulation clearance" in w.original_warning for w in cats["Circulation & Accessibility"])

    assert "Structural & Engineering" in cats
    assert any("Vertical stacking" in w.original_warning for w in cats["Structural & Engineering"])

    assert "Architectural & Layout" in cats
    assert any("Vastu advisory" in w.original_warning for w in cats["Architectural & Layout"])

    assert "Optimization Opportunities" in cats
    assert any("Relaxed" in w.original_warning for w in cats["Optimization Opportunities"])

    # Verify Grouped Issues
    assert len(resp.grouped_issues) >= 1

    # Verify Prioritized Actions
    assert len(resp.prioritized_actions) >= 3
    # Critical should be first in prioritized actions
    assert resp.prioritized_actions[0].priority.lower() == "critical"

    # Verify Overall Assessment
    assessment = resp.blueprint_assessment
    assert assessment.ready_for_review is False  # Because FAIL-L4 exists
    assert assessment.professional_review_required is True
    assert len(assessment.key_concerns) >= 1
    assert len(assessment.next_steps) >= 3


@pytest.mark.asyncio
async def test_blueprint_ai_advisor_service_execution_and_caching():
    service = BlueprintAIAdvisorService()

    req = BlueprintAIAnalysisRequest(
        warnings=[
            "PROP-DIM-02: Living Room width 2.8m is below comfortable proportion.",
            "Circulation: hallway clearance 0.95m requires expansion.",
        ],
        plan_verdict="ADVISORY",
        built_up_area_sqft=1800.0,
        floors=1,
        ai_provider="deterministic",
    )

    resp1 = await service.analyze_blueprint(req, user=None)
    assert resp1.blueprint_assessment.ready_for_review is True
    assert resp1.meta["execution_mode"] == "deterministic"

    # Second call should hit the LRU cache
    resp2 = await service.analyze_blueprint(req, user=None)
    assert resp2.blueprint_assessment.overall_status_summary == resp1.blueprint_assessment.overall_status_summary
