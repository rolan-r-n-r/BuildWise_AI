"""The manual-coordinate water probe.

The client asks this endpoint before accepting a manual pin; it must classify
open water from Nominatim's class/type/address, and must report
``is_fallback`` (not "land") when it could not answer.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.services.geocode_service import _water_name

client = TestClient(app)


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
