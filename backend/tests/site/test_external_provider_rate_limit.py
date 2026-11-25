"""External providers answering 429 degrade honestly, never silently.

Rate-limit probe across Overpass,
Nominatim/Photon and Groq: each must disclose ASSUMED / UNKNOWN rather than
crash, hang, or return a fabricated success.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.ai.groq_adapter import GroqExplanationAdapter
from app.services import geocode_service, road_service


# --------------------------------------------------------------------------- #
#  Geocoding: Nominatim and Photon both rate-limited
# --------------------------------------------------------------------------- #

def test_geocode_429_returns_no_bearing_and_asks_for_manual_input(monkeypatch):
    async def limited(*_args, **_kwargs):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(geocode_service, "_search_nominatim", limited)
    monkeypatch.setattr(geocode_service, "_search_photon", limited)

    result = asyncio.run(geocode_service.geocode_search("e2e-429-probe-locality"))

    assert result["results"] == [], "a rate-limited lookup must not invent results"
    assert result["provider"] == "none"
    assert result["error"] and "manually" in result["error"].lower()


# --------------------------------------------------------------------------- #
#  Overpass: 429 on every attempt -> ASSUMED fallback with a named warning
# --------------------------------------------------------------------------- #

def test_overpass_429_degrades_to_the_assumed_frontage(monkeypatch):
    async def throttled(*_args, **_kwargs):
        return None

    async def always_429(*_args, **_kwargs):
        stub = MagicMock()
        stub.status_code = 429
        stub.text = '{"error": "Too Many Requests"}'
        return stub

    monkeypatch.setattr(road_service, "_overpass_throttle", throttled)
    monkeypatch.setattr(road_service, "_post_query", always_429)
    # Keep this probe from poisoning the cooldown for every later test.
    monkeypatch.setattr(road_service, "_mark_upstream_failed", lambda: None)
    monkeypatch.setattr(road_service, "_upstream_cooldown_remaining", lambda: 0.0)

    result, cached, warning = asyncio.run(
        road_service.fetch_nearest_road(
            26.9124, 75.7873, cache_category="e2e-429", cache_precision=6,
        )
    )

    assert cached is False
    assert result["is_fallback"] is True
    assert result["annotation"] == "ASSUMED"
    assert result["source"] == "assumed_fallback"
    assert result["bearing_degrees"] is None and result["approach_side"] == "unknown"
    assert warning and "manually" in warning.lower()
    assert "no bearing has been assumed" in warning.lower()


def test_overpass_5xx_opens_the_outage_cooldown(monkeypatch):
    """A retryable 5xx must trip the breaker, not just the transport path.

    Regression: `outage` was only ever set on httpx exceptions, so a 502 from
    the public instance opened no cooldown and EVERY later lookup (pin move,
    re-analysis) re-spent the full read budget to reach the same ASSUMED
    fallback.  Measured before the fix: two consecutive analyses each burned
    ~10 s on 502s.
    """
    marked: list[float] = []

    async def throttled(*_args, **_kwargs):
        return None

    async def always_502(*_args, **_kwargs):
        stub = MagicMock()
        stub.status_code = 502
        stub.text = "Bad Gateway"
        return stub

    monkeypatch.setattr(road_service, "_overpass_throttle", throttled)
    monkeypatch.setattr(road_service, "_post_query", always_502)
    monkeypatch.setattr(road_service, "_mark_upstream_failed", lambda: marked.append(1.0))
    monkeypatch.setattr(road_service, "_upstream_cooldown_remaining", lambda: 0.0)

    result, cached, _warning = asyncio.run(
        road_service.fetch_nearest_road(
            26.9124, 75.7873, cache_category="e2e-502", cache_precision=6,
        )
    )

    assert cached is False
    assert result["is_fallback"] is True
    assert marked, "a retryable 5xx must open the upstream cooldown"


# --------------------------------------------------------------------------- #
#  Groq: 429 on every candidate model -> deterministic mock, disclosed
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_groq_429_falls_back_to_mock_with_a_named_reason():
    adapter = GroqExplanationAdapter()
    adapter.api_key = "fake_key_for_test"

    throttled = MagicMock()
    throttled.status_code = 429
    throttled.text = '{"error": "rate limit exceeded"}'

    with patch("httpx.AsyncClient.post", return_value=throttled):
        _summary, recs, meta = await adapter.generate_explanation({
            "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
            "built_up_area_sqft": 2000.0,
            "quality_grade": "standard",
            "floors": 2,
        })

    assert meta["provider_requested"] == "groq"
    assert meta["provider_used"] == "mock_fallback"
    assert "429" in meta["fallback_reason"]
    assert recs, "the deterministic mock must still produce recommendations"
