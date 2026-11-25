"""
Backend tests for /api/geocode, /api/geocode/reverse endpoints and geocode_service internals.

ALL HTTP calls are MOCKED — no live network calls made.
Tests:
  1. Nominatim success → returns results, caches, provider='nominatim'
  2. Cache HIT → returns without hitting network (cached=True)
  3. Throttle: _nominatim_throttle waits ~1 s between consecutive calls
  4. Nominatim error → fallback to Photon, provider='photon'
  5. Both providers fail → structured error response, no crash
  6. Query too short (min_length=1 enforced by FastAPI Query) → 422 if empty
  7. Error response shape: has results/provider/cached/error keys
  8. Photon result parsing produces correct lat/lon/display_name
  9. Manual-coordinate reverse geocode water probe classification & endpoint
"""

import asyncio
import time
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.services import geocode_service as svc
from app.services.geocode_service import _water_name

client = TestClient(app)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

NOMINATIM_RESPONSE = [
    {
        "place_id": 1,
        "display_name": "Bengaluru, Karnataka, India",
        "lat": "12.97194",
        "lon": "77.59369",
        "type": "city",
    }
]

PHOTON_RESPONSE = {
    "features": [
        {
            "geometry": {"type": "Point", "coordinates": [77.5937, 12.9719]},
            "properties": {
                "name": "Bengaluru",
                "state": "Karnataka",
                "country": "India",
            },
        }
    ]
}


def _make_nominatim_mock():
    """httpx.AsyncClient mock that returns NOMINATIM_RESPONSE."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=NOMINATIM_RESPONSE)
    return resp


def _make_photon_mock():
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=PHOTON_RESPONSE)
    return resp


def _make_error_mock():
    """Mock that raises on .raise_for_status()"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=Exception("HTTP 503"))
    return resp


def _fresh_cache():
    """Return a new _LruTtlCache so tests are isolated."""
    return svc._LruTtlCache(maxsize=512, ttl=86400)


# --------------------------------------------------------------------------- #
# 1. Nominatim success via HTTP endpoint
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_geocode_nominatim_success():
    """Nominatim returns results → provider='nominatim', results non-empty."""
    # Patch cache to avoid cross-test pollution
    fresh = _fresh_cache()
    with patch.object(svc, "_cache", fresh):
        # Patch throttle to skip the 1-second wait
        with patch.object(svc, "_nominatim_throttle", new=AsyncMock()):
            async_client_mock = AsyncMock()
            async_client_mock.__aenter__ = AsyncMock(return_value=async_client_mock)
            async_client_mock.__aexit__ = AsyncMock(return_value=False)
            async_client_mock.get = AsyncMock(return_value=_make_nominatim_mock())

            with patch("app.services.geocode_service.httpx.AsyncClient", return_value=async_client_mock):
                result = await svc.geocode_search("Bengaluru")

    assert result["provider"] == "nominatim"
    assert len(result["results"]) == 1
    assert result["results"][0]["display_name"] == "Bengaluru, Karnataka, India"
    assert abs(result["results"][0]["lat"] - 12.97194) < 0.001
    assert result["error"] is None
    assert result["cached"] is False


# --------------------------------------------------------------------------- #
# 2. Cache HIT — no network call
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_geocode_cache_hit():
    """A cached result is returned without any HTTP call."""
    fresh = _fresh_cache()
    cached_payload = {
        "results": [{"display_name": "Mumbai, India", "lat": 19.076, "lon": 72.877, "source": "nominatim"}],
        "provider": "nominatim",
        "cached": False,
        "error": None,
    }
    fresh.set("mumbai", cached_payload)

    with patch.object(svc, "_cache", fresh):
        with patch("app.services.geocode_service.httpx.AsyncClient") as mock_cls:
            result = await svc.geocode_search("Mumbai")
            mock_cls.assert_not_called()

    assert result["cached"] is True
    assert result["results"][0]["display_name"] == "Mumbai, India"


# --------------------------------------------------------------------------- #
# 3. Throttle: consecutive calls are spaced ≥ 1 s
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_nominatim_throttle_spacing():
    """Two consecutive throttle calls must be at least _RATE_INTERVAL apart."""
    # Reset the global timestamp to force a clean state
    svc._nominatim_last_call = 0.0

    # Release the lock so the test is not deadlocked
    # (The lock may be held from previous tests in theory — reset it)
    svc._nominatim_lock = asyncio.Lock()

    t0 = time.monotonic()
    await svc._nominatim_throttle()
    t1 = time.monotonic()
    await svc._nominatim_throttle()
    t2 = time.monotonic()

    gap = t2 - t1
    assert gap >= (svc._RATE_INTERVAL - 0.05), f"Throttle gap too short: {gap:.3f}s"


# --------------------------------------------------------------------------- #
# 4. Nominatim error → Photon fallback
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_geocode_fallback_to_photon():
    """When Nominatim raises, Photon is tried and its results are returned."""
    fresh = _fresh_cache()

    call_count = {"n": 0}

    async def mock_get_dispatch(url, **kwargs):
        call_count["n"] += 1
        if "nominatim" in url:
            raise Exception("Nominatim connection refused")
        return _make_photon_mock()

    # Build a single async client mock that dispatches by URL
    async_client_mock = AsyncMock()
    async_client_mock.__aenter__ = AsyncMock(return_value=async_client_mock)
    async_client_mock.__aexit__ = AsyncMock(return_value=False)
    async_client_mock.get = AsyncMock(side_effect=mock_get_dispatch)

    with patch.object(svc, "_cache", fresh):
        with patch.object(svc, "_nominatim_throttle", new=AsyncMock()):
            with patch("app.services.geocode_service.httpx.AsyncClient", return_value=async_client_mock):
                result = await svc.geocode_search("Bengaluru India")

    assert result["provider"] == "photon"
    assert len(result["results"]) >= 1
    assert result["results"][0]["source"] == "photon"
    assert result["error"] is None


# --------------------------------------------------------------------------- #
# 5. Both providers fail → structured error, no exception raised
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_geocode_both_fail_structured_error():
    """Both Nominatim and Photon fail → structured error response, never raises."""
    fresh = _fresh_cache()

    async def mock_get_always_fail(url, **kwargs):
        raise Exception("network error")

    async_client_mock = AsyncMock()
    async_client_mock.__aenter__ = AsyncMock(return_value=async_client_mock)
    async_client_mock.__aexit__ = AsyncMock(return_value=False)
    async_client_mock.get = AsyncMock(side_effect=mock_get_always_fail)

    with patch.object(svc, "_cache", fresh):
        with patch.object(svc, "_nominatim_throttle", new=AsyncMock()):
            with patch("app.services.geocode_service.httpx.AsyncClient", return_value=async_client_mock):
                result = await svc.geocode_search("nowhere special")

    # Must not raise; must return structured error
    assert isinstance(result, dict)
    assert "results" in result
    assert "error" in result
    assert result["results"] == []
    assert result["provider"] == "none"
    assert result["error"] is not None
    assert len(result["error"]) > 0


# --------------------------------------------------------------------------- #
# 6. Error response shape validation
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_geocode_response_always_has_required_keys():
    """Response always contains results/provider/cached/error regardless of outcome."""
    fresh = _fresh_cache()

    async_client_mock = AsyncMock()
    async_client_mock.__aenter__ = AsyncMock(return_value=async_client_mock)
    async_client_mock.__aexit__ = AsyncMock(return_value=False)
    async_client_mock.get = AsyncMock(side_effect=Exception("offline"))

    with patch.object(svc, "_cache", fresh):
        with patch.object(svc, "_nominatim_throttle", new=AsyncMock()):
            with patch("app.services.geocode_service.httpx.AsyncClient", return_value=async_client_mock):
                result = await svc.geocode_search("test query")

    for key in ("results", "provider", "cached", "error"):
        assert key in result, f"Missing key: {key}"
    assert isinstance(result["results"], list)
    assert isinstance(result["cached"], bool)


# --------------------------------------------------------------------------- #
# 7. HTTP endpoint integration test (via TestClient, mocked transport)
# --------------------------------------------------------------------------- #

def test_api_geocode_endpoint_success():
    """GET /api/geocode?q=Bengaluru returns 200 with correct shape."""
    mock_response = {
        "results": [
            {"display_name": "Bengaluru", "lat": 12.97, "lon": 77.59, "source": "nominatim"}
        ],
        "provider": "nominatim",
        "cached": False,
        "error": None,
    }

    with patch("app.main.geocode_search", new=AsyncMock(return_value=mock_response)):
        resp = client.get("/api/geocode?q=Bengaluru")

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "nominatim"
    assert len(data["results"]) == 1
    assert data["error"] is None


def test_api_geocode_endpoint_missing_q():
    """GET /api/geocode (no q param) → 422 Unprocessable Entity."""
    resp = client.get("/api/geocode")
    assert resp.status_code == 422


def test_api_geocode_endpoint_both_fail_graceful():
    """When geocode_search returns error, endpoint still returns 200 with error field."""
    mock_response = {
        "results": [],
        "provider": "none",
        "cached": False,
        "error": "Geocoding services temporarily unavailable.",
    }

    with patch("app.main.geocode_search", new=AsyncMock(return_value=mock_response)):
        resp = client.get("/api/geocode?q=nonexistentplace")

    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert data["error"] is not None


# --------------------------------------------------------------------------- #
# 8. Photon result parsing: lat/lon correctly extracted from GeoJSON
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_photon_result_lat_lon_extraction():
    """Photon GeoJSON [lon, lat] is correctly mapped to lat/lon fields."""
    fresh = _fresh_cache()

    photon_resp = {
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [72.8777, 19.0760]},  # [lon, lat]
                "properties": {"name": "Mumbai", "state": "Maharashtra", "country": "India"},
            }
        ]
    }

    photon_mock = MagicMock()
    photon_mock.raise_for_status = MagicMock()
    photon_mock.json = MagicMock(return_value=photon_resp)

    async_client_mock = AsyncMock()
    async_client_mock.__aenter__ = AsyncMock(return_value=async_client_mock)
    async_client_mock.__aexit__ = AsyncMock(return_value=False)
    async_client_mock.get = AsyncMock(return_value=photon_mock)

    with patch.object(svc, "_cache", fresh):
        # Bypass Nominatim entirely
        with patch.object(svc, "_search_nominatim", new=AsyncMock(side_effect=Exception("skip"))):
            with patch("app.services.geocode_service.httpx.AsyncClient", return_value=async_client_mock):
                result = await svc.geocode_search("Mumbai")

    assert result["provider"] == "photon"
    r = result["results"][0]
    assert abs(r["lat"] - 19.076) < 0.001, f"lat wrong: {r['lat']}"
    assert abs(r["lon"] - 72.8777) < 0.001, f"lon wrong: {r['lon']}"


# --------------------------------------------------------------------------- #
# 9. Manual-coordinate water probe (/api/geocode/reverse)
# --------------------------------------------------------------------------- #

def test_sea_payload_is_classified_as_water():
    payload = {
        "class": "natural",
        "type": "sea",
        "name": "Arabian Sea",
        "display_name": "Arabian Sea",
        "address": {"sea": "Arabian Sea"},
    }
    assert _water_name(payload) == "Arabian Sea"


def test_water_type_without_address_uses_display_name():
    payload = {
        "class": "natural",
        "type": "bay",
        "display_name": "Bay of Bengal, Indian Ocean",
        "address": {},
    }
    assert _water_name(payload) == "Bay of Bengal"


def test_land_payload_is_not_water():
    payload = {
        "class": "place",
        "type": "house",
        "display_name": "12, 4th Cross, Bengaluru, Karnataka, India",
        "address": {"road": "4th Cross", "city": "Bengaluru"},
    }
    assert _water_name(payload) is None


def test_road_named_after_water_is_not_mistaken_for_a_sea():
    # "Lake View Road" must not read as open water; only a water feature or a
    # water word in the display name does.
    payload = {
        "class": "highway",
        "type": "residential",
        "display_name": "Lake View Road, Bengaluru",
        "address": {"road": "Lake View Road"},
    }
    assert _water_name(payload) is None


def test_reverse_endpoint_rejects_out_of_range_coordinates():
    response = client.get("/api/geocode/reverse", params={"lat": 999, "lon": 77.59})
    assert response.status_code == 422, response.text
    assert "lat" in response.text


def test_reverse_endpoint_returns_the_probe_payload(monkeypatch):
    seen = {}

    async def fake_probe(lat: float, lon: float):
        seen["coords"] = (lat, lon)
        return {
            "address": "Arabian Sea",
            "water": True,
            "water_name": "Arabian Sea",
            "is_fallback": False,
            "cached": False,
        }

    monkeypatch.setattr("app.main.reverse_geocode_probe", fake_probe)
    response = client.get("/api/geocode/reverse", params={"lat": 12.97, "lon": 77.59})

    assert response.status_code == 200, response.text
    assert seen["coords"] == (12.97, 77.59)
    body = response.json()
    assert body["water"] is True
    assert body["water_name"] == "Arabian Sea"
    assert body["is_fallback"] is False
