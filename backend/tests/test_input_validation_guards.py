"""Input-boundary pins for non-finite numbers and enum-like fields.

Non-finite numbers: a raw `NaN` vertex was accepted by json.loads, survived validation and
blew up response serialisation as a 500.  Every non-finite numeric on the
boundary path must now be a 422 that names the offending field.

Enum-like fields: `building_typology` (and the other enum-like request strings) were free
text; an unknown value fell through `normalize_typology` to T1, and an injected
string was echoed into the dossier.  The 422 must list the accepted values.
"""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.schemas.floorplan import FloorPlanRequest
from app.schemas.site_plan import PlotPolygonModel

client = TestClient(app)


def _boundary(**overrides):
    payload = {
        "vertices": [
            {"x": 0.0, "y": 0.0},
            {"x": 12.0, "y": 0.0},
            {"x": 12.0, "y": 9.0},
            {"x": 0.0, "y": 9.0},
        ],
        "origin_lat": 12.97425,
        "origin_lon": 77.59219,
        "shape_type": "rectangle",
        "area_sqm": 108.0,
        "perimeter_m": 42.0,
        "source": "trace",
        "frontage_edge_index": 0,
    }
    payload.update(overrides)
    return payload


def _error_locs(response) -> list:
    return [
        ".".join(str(part) for part in err.get("loc", []))
        for err in response.json().get("detail", [])
    ]


def _analyze_payload(**overrides):
    payload = {
        "latitude": 12.97425,
        "longitude": 77.59219,
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "building_typology": "residential_single",
        "floors": 1,
        "ai_provider": "mock",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
#  Non-finite coordinates are a 422, never a 500
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_preview_rejects_non_finite_vertex_with_422_naming_the_field(bad):
    # json.dumps refuses to emit non-finite floats, so build the raw body the
    # way an API client does: a placeholder string swapped for the literal.
    body = json.dumps(
        {
            "boundary": _boundary(
                vertices=[
                    {"x": "__NON_FINITE__", "y": 0.0},
                    {"x": 12.0, "y": 0.0},
                    {"x": 12.0, "y": 9.0},
                    {"x": 0.0, "y": 9.0},
                ]
            )
        }
    ).replace('"__NON_FINITE__"', bad)
    assert bad in body

    response = client.post(
        "/api/site/preview",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422, response.text
    locs = _error_locs(response)
    assert any(loc == "body.boundary.vertices.0.x" for loc in locs), locs
    assert "finite" in response.text.lower()


def test_analyze_rejects_non_finite_boundary_vertex():
    body = json.dumps(_analyze_payload(boundary=_boundary())).replace('"x": 0.0', '"x": NaN', 1)

    response = client.post(
        "/api/analyze",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422, response.text
    assert any(loc.endswith("boundary.vertices.0.x") for loc in _error_locs(response))


def test_polygon_model_rejects_non_finite_tuple_and_names_the_index():
    with pytest.raises(ValidationError) as exc:
        PlotPolygonModel(vertices=[(0.0, 0.0), (float("nan"), 4.0), (4.0, 4.0)])
    assert "vertices[1].x" in str(exc.value)


def test_analyze_rejects_non_finite_plot_area():
    response = client.post(
        "/api/analyze",
        content=json.dumps(_analyze_payload(plot_area_sqft="__NON_FINITE__")).replace(
            '"__NON_FINITE__"', "Infinity"
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert "plot_area_sqft" in response.text


# --------------------------------------------------------------------------- #
#  Enum-like inputs list their accepted values
# --------------------------------------------------------------------------- #

def test_analyze_rejects_unknown_typology_listing_accepted_values():
    response = client.post(
        "/api/analyze",
        json=_analyze_payload(building_typology="<script>alert(1)</script>"),
    )

    assert response.status_code == 422, response.text
    detail = response.text
    for accepted in (
        "residential_single",
        "residential_multi",
        "commercial",
        "industrial",
        "T1_SINGLE_FAMILY",
        "T4_WAREHOUSE",
    ):
        assert accepted in detail, f"{accepted} missing from the 422 detail"


def test_analyze_accepts_the_canonical_typology_key():
    # No network is reached: an invalid request stops at validation, so a valid
    # one is proven by the fact that it does NOT return 422.  (The endpoint test
    # with mocked upstreams covers the 200 path.)
    response = client.post(
        "/api/analyze",
        json=_analyze_payload(building_typology="T2_FAMILY_APARTMENT", floors=99),
    )
    assert response.status_code == 422
    locs = _error_locs(response)
    assert "body.floors" in locs, locs
    assert not any("building_typology" in loc for loc in locs), locs


def test_boundary_rejects_unknown_shape_type_listing_accepted_values():
    response = client.post(
        "/api/site/preview",
        json={"boundary": _boundary(shape_type="hexagon")},
    )
    assert response.status_code == 422, response.text
    assert "hexagon" in response.text
    assert "l_shape" in response.text


def test_boundary_rejects_unknown_source_listing_accepted_values():
    response = client.post(
        "/api/site/preview",
        json={"boundary": _boundary(source="telepathy")},
    )
    assert response.status_code == 422, response.text
    assert "telepathy" in response.text
    assert "preset" in response.text


def test_floorplan_request_rejects_unknown_typology():
    with pytest.raises(ValidationError) as exc:
        FloorPlanRequest(building_typology="residential_mansion")
    assert "residential_mansion" in str(exc.value)
    assert "residential_single" in str(exc.value)


@pytest.mark.parametrize(
    "typology",
    [
        "apartment",
        "warehouse",
        "commercial_office",
        "commercial_complex",
        "residential_apartment",
        "industrial_warehouse",
        "T3_COMMERCIAL_RETAIL",
        "T4_INSTITUTIONAL",
    ],
)
def test_floorplan_request_accepts_the_existing_typology_vocabulary(typology):
    """Validation must not turn supported legacy identifiers into 422s."""
    request = FloorPlanRequest(building_typology=typology)
    assert request.building_typology == typology


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quality_grade": "gold"},
        {"ai_provider": "gpt-9"},
        {"ground_coverage_ratio": float("inf")},
        {"built_up_area_sqft": float("nan")},
    ],
)
def test_floorplan_request_rejects_enum_and_non_finite_scalars(kwargs):
    with pytest.raises(ValidationError):
        FloorPlanRequest(**kwargs)
