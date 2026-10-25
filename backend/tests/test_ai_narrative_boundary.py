"""
test_ai_narrative_boundary.py - the LLM narrates, it never certifies.

A live Groq run returned, beside a certified 62.5 score:

    "The standard grade (approx Rs 2,500/sqft) ... around Rs 5 million"
    "feasibility_score": "78"
    "... Zone III ..."                      (the engine says Zone II / 0.10)

The top-level report fields were already pinned to the deterministic engines,
but `ai_metadata` travelled verbatim and its text is what the report renders as
commentary.  These tests hold the boundary:

  * a hostile narrative asserting score 99, Zone V and Rs 1/sqft changes
    ZERO report numbers, zones or verdicts;
  * every one of those claims is removed from the narrative before it leaves
    the server, and the removal is disclosed;
  * ordinary descriptive text (percentages, room counts) is left alone.
"""
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.ai_narrative import sanitize_narrative

client = TestClient(app)


def _mock_http(url, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _fallback_json(url)
    return resp


def _fallback_json(url):
    if "nominatim" in url:
        return {"display_name": "Bengaluru Urban, Karnataka, India",
                "address": {"city": "Bengaluru", "state": "Karnataka"}}
    if "earthquake.usgs.gov" in url:
        return {"features": []}
    if "flood-api.open-meteo.com" in url:
        return {"daily": {"river_discharge": [0.02] * 10}}
    if "archive-api.open-meteo.com" in url:
        times = [f"{y}-06-15" for y in range(2015, 2025)]
        return {"daily": {"time": times, "wind_gusts_10m_max": [55.0] * 10,
                          "precipitation_sum": [15.0] * 10}}
    if "api.open-meteo.com" in url:
        return {"elevation": [920.0]}
    if "api.open-elevation.com" in url:
        return {"results": [{"elevation": 920.0}]}
    return {}


@pytest.fixture
def mock_external_http():
    with patch("httpx.AsyncClient.get", side_effect=_mock_http), \
         patch("httpx.AsyncClient.post", side_effect=_mock_http):
        yield


class _HostileAdapter:
    """An adapter that lies about every report value it can name."""

    async def generate_explanation(self, _intermediate):
        return (
            "This site scores 99/100 and sits in Zone V (Z=0.36). "
            "Construction will cost ₹1/sqft, about ₹1 lakh total.",
            ["Proceed without any further study."],
            {
                "provider_requested": "groq",
                "provider_used": "groq (hostile-test)",
                "generation_time_ms": "1.0",
                "parameter_reflection": (
                    "Feasibility score 99 out of 100, Zone V, at ₹1/sqft — "
                    "a ₹1 lakh total on a 60% coverage plate."
                ),
                "feasibility_score": "99",
            },
        )


ANALYZE_BODY = {
    "latitude": 12.9716,
    "longitude": 77.5946,
    "built_up_area_sqft": 2000.0,
    "quality_grade": "standard",
    "building_typology": "residential_single",
    "floors": 1,
    "ai_provider": "groq",
}


def _analyze_with_hostile_narrative():
    with patch("app.main.get_ai_adapter", return_value=_HostileAdapter()):
        return client.post("/api/analyze", json=ANALYZE_BODY)


def test_hostile_narrative_cannot_change_any_report_value(mock_external_http):
    resp = _analyze_with_hostile_narrative()
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # The certified score is the deterministic one, never the model's 99.
    assert data["feasibility_score"] == int(round(data["overall_suitability_score"]))
    assert data["feasibility_score"] != 99

    # The seismic zone is the engine's, never the model's Zone V.
    assert data["hazard_profile"]["seismic"]["zone"] != "Zone V"

    # The cost block is the engine's, never Rs 1/sqft.
    assert data["cost_estimate"]["base_rate_per_sqft"] != 1
    assert data["cost_breakdown"] == data["cost_estimate"]


def test_hostile_narrative_claims_are_removed_and_the_removal_is_disclosed(mock_external_http):
    resp = _analyze_with_hostile_narrative()
    assert resp.status_code == 200, resp.text
    data = resp.json()

    reflection = data["ai_metadata"]["parameter_reflection"]
    assert "₹" not in reflection
    assert "Zone V" not in reflection
    assert "99" not in reflection
    assert "/sqft" not in reflection.lower()

    assert "feasibility_score" not in data["ai_metadata"], (
        "the model's self-reported score must not travel beside the certified one"
    )
    assert data["ai_metadata"]["narrative_class"] == "advisory_non_certified"
    redactions = data["ai_metadata"]["narrative_redactions"]
    for kind in ("rate", "amount", "score", "zone"):
        assert kind in redactions, f"{kind} claim was not disclosed as removed"

    # The summary is narrative too.
    summary = data["engineering_summary"]
    assert "₹" not in summary and "Zone V" not in summary and "99/100" not in summary


def test_the_report_pdf_never_carries_the_hostile_claims(mock_external_http):
    from io import BytesIO

    from pypdf import PdfReader

    resp = _analyze_with_hostile_narrative()
    assert resp.status_code == 200
    analysis = resp.json()

    report = client.post("/api/report", json={"analysis_data": analysis})
    assert report.status_code == 200, report.text
    text = " ".join(
        " ".join((p.extract_text() or "").split())
        for p in PdfReader(BytesIO(report.content)).pages
    )
    assert "Zone V" not in text
    assert "₹1/sqft" not in text
    assert "99/100" not in text
    # The engine's own reading is still there.
    assert analysis["hazard_profile"]["seismic"]["zone"] in text


def test_descriptive_numbers_survive():
    text = "Ground coverage is 60% on a 213 m² plot with a 12.1% slope and 4 rooms."
    clean, redactions = sanitize_narrative(text)
    assert clean == text
    assert redactions == []


def test_sanitizer_is_idempotent():
    once, _ = sanitize_narrative("Cost ₹5 lakh at ₹2,500/sqft, score 88, Zone IV.")
    twice, second_redactions = sanitize_narrative(once)
    assert twice == once
    assert second_redactions == []


@pytest.mark.asyncio
async def test_removing_the_groq_key_discloses_the_deterministic_fallback(monkeypatch):
    """Key removal must never read as an AI answer.

    With no GROQ_API_KEY the adapter must return the deterministic engine's
    text AND label it `mock_fallback` with the reason. The report panel keys its
    "Deterministic engine narrative" label off `provider_used`, so a false
    "AI narrative" claim is impossible when the key is gone.
    """
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")

    from app.ai.groq_adapter import GroqExplanationAdapter

    adapter = GroqExplanationAdapter()
    adapter.api_key = ""
    summary, recommendations, meta = await adapter.generate_explanation(
        {
            "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
            "formatted_address": "Bengaluru, Karnataka",
            "overall_suitability_score": 62.5,
            "cost_estimate": {"total_estimated_cost_inr": 4850000.0},
        }
    )

    assert summary
    assert recommendations is not None
    assert meta["provider_requested"] == "groq"
    assert meta["provider_used"] == "mock_fallback"
    assert "GROQ_API_KEY" in meta["fallback_reason"]
