"""
test_boundary_bounds_guard.py - operational envelope for captured boundaries.
============================================================================
Regression pin for the operational envelope.

The site-preview solve scans a 0.75 m grid over the plot, so its cost grows
with the square of the boundary span.  Before this guard a single request with
a 1e9 m boundary kept the worker busy indefinitely: /api/health stopped
answering and the API had to be restarted.  Both boundary entry points now
refuse the same oversized input with the same wording.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.boundary_service import (
    BOUNDARY_MAX_AREA_SQM,
    BOUNDARY_MAX_SPAN_M,
    BoundaryValidationError,
    boundary_bounds_violation,
    summarize_boundary,
)

client = TestClient(app)


def _boundary(vertices, area_sqm=216.0):
    return {
        "vertices": [{"x": x, "y": y} for x, y in vertices],
        "origin_lat": 12.9716,
        "origin_lon": 77.5946,
        "shape_type": "rectangle",
        "area_sqm": area_sqm,
        "perimeter_m": 60.0,
        "source": "trace",
        "frontage_edge_index": 0,
    }


def _square(side):
    return [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]


def test_bounds_helper_rejects_unbounded_span():
    assert boundary_bounds_violation(_square(12.0)) is None
    violation = boundary_bounds_violation(_square(1e9))
    assert violation is not None
    assert f"{BOUNDARY_MAX_SPAN_M:,.0f} m" in violation


def test_bounds_helper_rejects_oversized_area():
    # 1500 x 1500 m = 2.25 km²: inside the span? No - span 1500 m is allowed,
    # area 2,250,000 m² is over the 100 ha ceiling.
    violation = boundary_bounds_violation(_square(1500.0))
    assert violation is not None
    assert f"{BOUNDARY_MAX_AREA_SQM:,.0f} m" in violation


def test_summarize_boundary_refuses_unbounded_span():
    with pytest.raises(BoundaryValidationError) as exc:
        summarize_boundary(type("B", (), {
            "vertices": [type("V", (), {"x": x, "y": y})() for x, y in _square(1e9)],
            "shape_type": "rectangle",
            "source": "trace",
            "frontage_edge_index": 0,
            "origin_lat": 12.9716,
            "origin_lon": 77.5946,
            "area_sqm": 1e18,
        })())
    assert "operational limit" in str(exc.value)


def test_summarize_boundary_still_accepts_a_real_plot():
    summary = summarize_boundary(type("B", (), {
        "vertices": [type("V", (), {"x": x, "y": y})() for x, y in _square(12.0)],
        "shape_type": "rectangle",
        "source": "trace",
        "frontage_edge_index": 0,
        "origin_lat": 12.9716,
        "origin_lon": 77.5946,
        "area_sqm": 144.0,
    })())
    assert summary["area_sqm"] == 144.0


def test_site_preview_returns_422_instead_of_hanging():
    resp = client.post("/api/site/preview", json={"boundary": _boundary(_square(1e9), area_sqm=1e18)})
    assert resp.status_code == 422, resp.text
    assert "operational limit" in resp.json()["detail"]


def test_site_preview_bounds_check_precedes_the_grid_scan():
    """A span just over the limit is refused before any geometry work runs."""
    resp = client.post(
        "/api/site/preview",
        json={"boundary": _boundary(_square(BOUNDARY_MAX_SPAN_M + 1.0), area_sqm=4.0e6)},
    )
    assert resp.status_code == 422, resp.text
