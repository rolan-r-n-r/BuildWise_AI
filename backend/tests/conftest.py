import os
import socket
import tempfile
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.database import init_db
from app.main import app
from app.utils.cache_utils import cache, hazard_cache


def is_online():
    try:
        # Check connection to a reliable DNS IP with 1.0s timeout
        socket.create_connection(("8.8.8.8", 53), timeout=1.0)
        return True
    except OSError:
        return False


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "skip_when_offline: mark test to skip if host has no external internet connection"
    )


def pytest_runtest_setup(item):
    if "skip_when_offline" in item.keywords:
        if not is_online():
            pytest.skip("Test skipped: host is offline or external endpoints unreachable")


@pytest.fixture(autouse=True)
def clear_caches_between_tests():
    cache.clear()
    hazard_cache.clear()
    yield
    cache.clear()
    hazard_cache.clear()


@pytest.fixture
def api_client():
    return TestClient(app)


def _mock_http_response(url: str, **kwargs):
    resp = MagicMock()
    resp.status_code = 200

    if "nominatim" in url:
        if "26.14" in url or "91.73" in url:
            resp.json.return_value = {
                "display_name": "GS Road, Guwahati, Kamrup Metropolitan, Assam, India",
                "address": {"city": "Guwahati", "state": "Assam"},
            }
        elif "25.59" in url or "85.13" in url:
            resp.json.return_value = {
                "display_name": "Patna, Patna District, Bihar, India",
                "address": {"city": "Patna", "state": "Bihar"},
            }
        else:
            resp.json.return_value = {
                "display_name": "Bengaluru Urban, Karnataka, India",
                "address": {"city": "Bengaluru", "state": "Karnataka"},
            }
    elif "earthquake.usgs.gov" in url:
        if "26.14" in url or "91.73" in url:
            resp.json.return_value = {
                "features": [
                    {
                        "properties": {"mag": 6.8, "time": 1600000000000, "place": "Assam Tectonic Belt"},
                        "geometry": {"coordinates": [91.73, 26.14, 10.0]},
                    },
                    {
                        "properties": {"mag": 5.4, "time": 1500000000000, "place": "Kamrup District"},
                        "geometry": {"coordinates": [91.75, 26.12, 15.0]},
                    },
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
        resp.json.return_value = {
            "daily": {"time": times, "wind_gusts_10m_max": [55.0] * 10, "precipitation_sum": [15.0] * 10}
        }
    elif "api.open-meteo.com/v1/forecast" in url:
        resp.json.return_value = {
            "current": {
                "temperature_2m": 28.0,
                "wind_speed_10m": 12.0,
                "wind_direction_10m": 240.0,
            },
            "daily": {
                "temperature_2m_max": [32.0] * 7,
                "temperature_2m_min": [20.0] * 7,
                "precipitation_sum": [5.0] * 7,
            },
        }
    elif "open-meteo.com/v1/elevation" in url or "elevation-api" in url:
        if "25.59" in url:
            resp.json.return_value = {"elevation": [53.0, 53.5, 52.5, 53.0, 53.0]}
        elif "26.14" in url:
            resp.json.return_value = {"elevation": [55.0, 55.5, 54.5, 55.0, 55.0]}
        else:
            resp.json.return_value = {"elevation": [920.0, 921.0, 919.0, 920.5, 919.5]}
    elif "api.open-elevation.com" in url:
        if "25.59" in url:
            resp.json.return_value = {"results": [{"elevation": 53.0}]}
        elif "26.14" in url:
            resp.json.return_value = {"results": [{"elevation": 55.0}]}
        else:
            resp.json.return_value = {"results": [{"elevation": 920.0}]}
    elif "worldpop" in url:
        resp.json.return_value = {"data": {"total_population": 12500.0}}
    elif "stac" in url or "earth-search" in url or "planetarycomputer" in url:
        resp.json.return_value = {"features": []}
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
                        {"lat": 12.973, "lon": 77.596},
                    ]
                }
            ]
        }
    elif "stac" in url or "earth-search" in url or "planetarycomputer" in url:
        resp.json.return_value = {"features": []}
    else:
        resp.json.return_value = {}
    return resp


@pytest.fixture
def mock_external_http(monkeypatch):
    async def _async_get(self, url: str, *args, **kwargs):
        return _mock_http_response(str(url), **kwargs)

    async def _async_post(self, url: str, *args, **kwargs):
        return _mock_http_post(str(url), **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "get", _async_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", _async_post)
    yield


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def isolated_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    orig_path = settings.DATABASE_PATH
    settings.DATABASE_PATH = path
    init_db(db_path=path)
    yield path
    settings.DATABASE_PATH = orig_path
    try:
        os.remove(path)
    except OSError:
        pass
