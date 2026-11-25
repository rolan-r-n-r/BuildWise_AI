"""
test_site_intelligence.py — site intelligence contract & boundary bounds guard tests.
=====================================================================================
Covers:
- /api/nearest-road Overpass proxy: hit, cache, honest fallback (Amendment 1:
  no fabricated geometry), "no road mapped" case, 1 req/s throttle.
- /api/site/preview: determinism, hash cache, statutory 422s, taxonomy
  serialization (CALCULATED/ASSUMED/RECOMMENDED/VERIFIED), p95 < 150 ms,
  rectangle golden values, provenance block, frontage annotation.
- Operational envelope bounds guard for captured boundaries (span/area 422s).
- Vastu delegation to the shared road service keeps its public contract.
"""
import time

import httpx
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from shapely.geometry import Polygon

from app.main import app
from app.schemas.site_intelligence import ANNOTATION_STATUSES, SitePreviewRequest
from app.schemas.request import PlotVertex, BoundarySummary as _BS
from app.services.boundary_service import (
    BOUNDARY_MAX_AREA_SQM,
    BOUNDARY_MAX_SPAN_M,
    BoundaryValidationError,
    boundary_bounds_violation,
    summarize_boundary,
)
from app.services.road_service import fetch_nearest_road  # noqa: F401 - re-exported contract
import app.services.road_service as road_service
from app.services.site_preview_service import compute_site_preview, clear_preview_cache
from app.services.vastu_service import fetch_nearest_road_approach

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_throttle_and_preview_cache():
    road_service._overpass_last_call = 0.0
    road_service._upstream_down_until = 0.0
    clear_preview_cache()
    yield
    road_service._overpass_last_call = 0.0
    road_service._upstream_down_until = 0.0
    clear_preview_cache()


# --------------------------------------------------------------------------- #
#  Fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #

def _overpass_ok_json():
    return {
        "elements": [
            {
                "type": "way",
                "id": 1,
                "tags": {"highway": "residential", "name": "MG Road"},
                "geometry": [
                    {"lat": 12.9710, "lon": 77.5946},
                    {"lat": 12.9710, "lon": 77.5960},
                ],
            }
        ]
    }


def _preview_boundary_rect():
    # 12 x 18 m CCW rectangle, area 216 m2, edges 12/18 m.
    verts = [
        PlotVertex(x=0.0, y=0.0),
        PlotVertex(x=12.0, y=0.0),
        PlotVertex(x=12.0, y=18.0),
        PlotVertex(x=0.0, y=18.0),
    ]
    return _BS(
        vertices=verts,
        origin_lat=12.9716,
        origin_lon=77.5946,
        shape_type="rectangle",
        area_sqm=216.0,
        perimeter_m=60.0,
        source="trace",
        frontage_edge_index=0,
    )


def _preview_boundary_rect_translated(dx=0.0, dy=0.0):
    """The same 12 x 18 m CCW rectangle, merely moved inside its local frame.

    The captured boundary is pin-centred, so its vertices are NOT anchored on
    the bbox corner (minx/miny are negative). Regression pin for the frame bug
    that displaced the buildable/footprint off the plot.
    """
    verts = [
        PlotVertex(x=dx + 0.0, y=dy + 0.0),
        PlotVertex(x=dx + 12.0, y=dy + 0.0),
        PlotVertex(x=dx + 12.0, y=dy + 18.0),
        PlotVertex(x=dx + 0.0, y=dy + 18.0),
    ]
    return _BS(
        vertices=verts,
        origin_lat=12.9716,
        origin_lon=77.5946,
        shape_type="rectangle",
        area_sqm=216.0,
        perimeter_m=60.0,
        source="trace",
        frontage_edge_index=0,
    )


def _preview_request(with_frontage=True, coverage=None):
    b = _preview_boundary_rect()
    if not with_frontage:
        b.frontage_edge_index = None
    return SitePreviewRequest(boundary=b, ground_coverage_ratio=coverage)


def _hexagon_preview_request():
    import math
    verts = []
    for i in range(6):
        ang = (i * 2 * math.pi) / 6
        verts.append(PlotVertex(x=round(12 * math.cos(ang), 3), y=round(12 * math.sin(ang), 3)))
    return SitePreviewRequest(
        boundary=_BS(
            vertices=verts,
            origin_lat=12.9716,
            origin_lon=77.5946,
            shape_type="polygon",
            area_sqm=374.0,
            perimeter_m=72.0,
            source="trace",
            frontage_edge_index=0,
        ),
        ground_coverage_ratio=0.6,
    )


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


# --------------------------------------------------------------------------- #
#  /api/nearest-road                                                           #
# --------------------------------------------------------------------------- #

def test_nearest_road_overpass_hit():
    with patch("httpx.AsyncClient.post", return_value=_mock_response(_overpass_ok_json())):
        resp = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is True
    assert data["cached"] is False
    assert data["degraded"] is False
    road = data["road"]
    assert road["road_name"] == "MG Road"
    assert road["highway_class"] == "residential"
    assert road["bearing_degrees"] == pytest.approx(180.0, abs=1.0)
    assert road["approach_side"] == "S"
    assert road["is_fallback"] is False
    assert road["nearest_point"]["lat"] == pytest.approx(12.9710, abs=1e-4)
    assert data["provenance"]["source"] == "osm_overpass"
    assert data["provenance"]["annotation"] == "VERIFIED"
    assert "OpenStreetMap" in data["provenance"]["attribution"]


def test_nearest_road_cache_hit_avoids_upstream():
    with patch("httpx.AsyncClient.post", return_value=_mock_response(_overpass_ok_json())):
        first = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
        assert first.status_code == 200
        assert first.json()["cached"] is False
    # Upstream now unreachable: the 24h cache must still answer.
    with patch("httpx.AsyncClient.post", side_effect=Exception("network down")):
        second = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
    assert second.status_code == 200
    data = second.json()
    assert data["cached"] is True
    assert data["found"] is True
    assert data["road"]["bearing_degrees"] == pytest.approx(180.0, abs=1.0)


def test_nearest_road_fallback_never_fabricates_geometry():
    with patch("httpx.AsyncClient.post", side_effect=Exception("Overpass timeout")):
        resp = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
    assert data["degraded"] is True
    assert data["warning"]
    assert data["road"]["bearing_degrees"] is None
    assert data["road"]["approach_side"] == "unknown"
    assert data["road"]["is_fallback"] is True
    assert data["provenance"]["annotation"] == "ASSUMED"
    assert data["provenance"]["source"] == "assumed_fallback"


def test_nearest_road_no_mapped_road_is_honest_empty():
    with patch("httpx.AsyncClient.post", return_value=_mock_response({"elements": []})):
        resp = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
    assert data["degraded"] is True
    assert "No mapped road" in data["warning"]
    assert data["provenance"]["annotation"] == "ASSUMED"


def test_nearest_road_retries_transient_504():
    """The public instance answers 504 when its OWN query budget expires; that
    is transient, so the retry must recover a measured road instead of
    degrading the frontage to ASSUMED."""
    with patch(
        "httpx.AsyncClient.post",
        side_effect=[
            _mock_response(None, status=504),
            _mock_response(_overpass_ok_json()),
        ],
    ) as post:
        resp = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
    assert post.call_count == 2
    data = resp.json()
    assert data["found"] is True
    assert data["degraded"] is False
    assert data["road"]["road_name"] == "MG Road"
    assert data["provenance"]["annotation"] == "VERIFIED"


def test_nearest_road_does_not_retry_query_errors():
    """A 4xx other than 429 means OUR query is wrong; retrying is pointless."""
    with patch("httpx.AsyncClient.post", return_value=_mock_response(None, status=400)) as post:
        resp = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
    assert post.call_count == 1
    data = resp.json()
    assert data["found"] is False
    assert data["degraded"] is True
    assert data["road"]["bearing_degrees"] is None
    # A query error must NOT open the outage cooldown: the next lookup still
    # goes upstream (and, when the query is fixed, measures a road).
    with patch("httpx.AsyncClient.post", return_value=_mock_response(_overpass_ok_json())) as retry_post:
        after = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
    assert retry_post.call_count == 1
    assert after.json()["found"] is True


def test_nearest_road_failure_cooldown_skips_upstream_and_stays_honest():
    """Burst failures must not make every frontage step pay the full budget:
    inside the cooldown the answer is instant, still ASSUMED, and the upstream
    is left alone."""
    with patch("httpx.AsyncClient.post", side_effect=Exception("Overpass 504")) as post:
        first = client.get("/api/nearest-road", params={"lat": 12.9716, "lon": 77.5946})
        assert first.json()["degraded"] is True
        assert post.call_count >= 1
        post.reset_mock()
        t0 = time.monotonic()
        second = client.get("/api/nearest-road", params={"lat": 12.9832, "lon": 77.6088})
        elapsed = time.monotonic() - t0
    assert post.call_count == 0, "a failing upstream must not be hammered inside the cooldown"
    assert elapsed < 0.5, f"cooldown answer must be immediate (took {elapsed:.2f}s)"
    data = second.json()
    assert data["found"] is False
    assert data["degraded"] is True
    assert data["road"]["bearing_degrees"] is None
    assert data["road"]["approach_side"] == "unknown"
    assert data["provenance"]["annotation"] == "ASSUMED"


def test_nearest_road_query_uses_tag_index_not_regex():
    """Regression pin: the `["highway"~"^(primary|...)$"]` regex makes
    Overpass scan every road instead of using its tag index, which pushed the
    public instance past its own query budget (measured 504s at 6-9 s). The
    class filter belongs on our side."""
    q = road_service._build_query(12.9716, 77.5946)
    assert 'way["highway"]' in q
    assert "~" not in q
    assert f"around:{road_service._QUERY_RADIUS_M}" in q
    assert f"[timeout:{int(road_service._QL_TIMEOUT_S)}]" in q


def test_timeout_budget_lets_the_server_give_up_first():
    """Regression pin for the blank-log outage: with a 3.5 s client timeout
    against a 4 s query budget, the client always aborted a query the server
    was still answering, so every lookup degraded to ASSUMED."""
    assert road_service._QL_TIMEOUT_S < road_service._ATTEMPT_READ_TIMEOUT_S
    assert road_service._TOTAL_BUDGET_S >= road_service._QL_TIMEOUT_S * 2
    assert road_service._MIN_RETRY_BUDGET_S > road_service._QL_TIMEOUT_S


def test_describe_failure_names_message_less_timeouts():
    """httpx timeouts stringify to '' - the old log read "query failed:" with
    no cause. The exception TYPE must always be reported."""
    label = road_service._describe_failure(httpx.ReadTimeout(""))
    assert "ReadTimeout" in label
    assert road_service._describe_failure(OSError("getaddrinfo failed")).endswith(
        "getaddrinfo failed"
    )


def test_road_class_filter_accepts_vehicular_rejects_footways():
    assert road_service._is_road_way({"highway": "residential"})
    assert road_service._is_road_way({"highway": "primary"})
    assert road_service._is_road_way({"highway": "residential;service"})
    assert not road_service._is_road_way({"highway": "footway"})
    assert not road_service._is_road_way({"highway": "cycleway"})
    assert not road_service._is_road_way({})


def test_parse_ignores_closer_non_vehicular_ways():
    """The tag-index query now returns footways/steps too; the nearest ROAD must
    still win over a closer footpath."""
    payload = {
        "elements": [
            {"tags": {"highway": "footway"}, "geometry": [{"lat": 12.97161, "lon": 77.59461}]},
            {
                "tags": {"highway": "residential", "name": "MG Road"},
                "geometry": [{"lat": 12.9710, "lon": 77.5946}],
            },
        ]
    }
    parsed = road_service._parse_overpass_elements(payload, 12.9716, 77.5946)
    assert parsed is not None
    assert parsed["highway_class"] == "residential"
    assert parsed["road_name"] == "MG Road"
    assert parsed["distance_meters"] > 50
    assert parsed["approach_side"] == "S"


@pytest.mark.asyncio
async def test_overpass_throttle_enforces_one_request_per_second():
    road_service._overpass_last_call = 0.0
    t0 = time.monotonic()
    await road_service._overpass_throttle()
    first = time.monotonic() - t0
    await road_service._overpass_throttle()
    second = time.monotonic() - t0 - first
    assert first < 0.5, "first call must not wait"
    assert second >= 0.9, f"second immediate call must be throttled to ~1s (got {second:.2f}s)"


@pytest.mark.asyncio
async def test_vastu_delegates_to_shared_road_service():
    """The extraction must preserve the vastu public contract (RoadApproach, warning)."""
    with patch("httpx.AsyncClient.post", side_effect=Exception("Overpass timeout")):
        approach, warning = await fetch_nearest_road_approach(12.9716, 77.5946)
        assert approach.is_fallback is True
        assert approach.bearing_degrees is None
        assert approach.approach_side == "unknown"
        assert "Road network telemetry unavailable" in warning

    # The failure above deliberately opens the shared upstream cooldown; model
    # its expiry so this half still exercises the real success path.
    road_service._upstream_down_until = 0.0

    with patch("httpx.AsyncClient.post", return_value=_mock_response(_overpass_ok_json())):
        approach, warning = await fetch_nearest_road_approach(12.9716, 77.5946)
        assert approach.is_fallback is False
        assert approach.approach_side == "S"
        assert warning is None


# --------------------------------------------------------------------------- #
#  /api/site/preview                                                           #
# --------------------------------------------------------------------------- #

def test_preview_rectangle_golden_values():
    resp = compute_site_preview(_preview_request())
    assert resp.ok is True
    assert resp.plot["area_sqm"] == pytest.approx(216.0, abs=0.5)
    # Legacy rectangle setback formula: front max(1.8, min(3.5, 18*0.15))=2.7,
    # rear max(1.2, min(2.5, 18*0.10))=1.8, side max(1.0, min(2.0, 12*0.10))=1.2.
    assert resp.setbacks["front_m"] == pytest.approx(2.7)
    assert resp.setbacks["rear_m"] == pytest.approx(1.8)
    assert resp.setbacks["left_m"] == pytest.approx(1.2)
    assert resp.setbacks["right_m"] == pytest.approx(1.2)
    # Buildable: (12-2.4) x (18-2.7-1.8) = 9.6 x 13.5 = 129.6 m2
    assert resp.buildable["area_sqm"] == pytest.approx(129.6, abs=0.1)
    assert resp.buildable["vertices"] == [[1.2, 2.7], [10.8, 2.7], [10.8, 16.2], [1.2, 16.2]]
    assert resp.footprint["area_sqm"] <= resp.buildable["area_sqm"]
    assert resp.certificate["footprint_contained_in_buildable"] is True
    assert resp.frontage is not None
    assert resp.frontage["status"] == "VERIFIED"
    assert resp.provenance["boundary_source"] == "trace"
    assert "no LLM" in resp.provenance["geometry_source"]


def test_preview_geometry_is_translation_equivariant():
    """Moving a plot inside its own local frame moves its buildable with it.

    The legacy rectangle setback formula is corner-based; on a pin-centred
    capture (negative minx/miny) that displaced the buildable - and the
    footprint derived from it - by half the plot size to the north-east, which
    the map rendered as extra boundaries sitting beside the real plot.
    """
    POINT = 2
    base = compute_site_preview(_preview_request(coverage=0.6))
    dx, dy = -6.0, -9.0
    shifted = compute_site_preview(
        SitePreviewRequest(
            boundary=_preview_boundary_rect_translated(dx, dy),
            ground_coverage_ratio=0.6,
        )
    )

    def shifted_ring(ring):
        return [[round(x + dx, POINT), round(y + dy, POINT)] for x, y in ring]

    assert shifted.buildable["vertices"] == shifted_ring(base.buildable["vertices"])
    assert shifted.footprint["vertices"] == shifted_ring(base.footprint["vertices"])


def test_preview_buildable_and_footprint_stay_inside_a_pin_centred_plot():
    dx, dy = -6.0, -9.0
    resp = compute_site_preview(
        SitePreviewRequest(
            boundary=_preview_boundary_rect_translated(dx, dy),
            ground_coverage_ratio=0.6,
        )
    )
    plot = Polygon(resp.plot["vertices"])
    assert Polygon(resp.buildable["vertices"]).within(plot)
    assert Polygon(resp.footprint["vertices"]).within(plot)
    assert resp.certificate["footprint_contained_in_buildable"] is True
    assert resp.certificate["is_valid"] is True
    # The plot's own ring is echoed verbatim; only the derived geometry moved.
    assert resp.plot["vertices"] == [
        [dx, dy],
        [dx + 12.0, dy],
        [dx + 12.0, dy + 18.0],
        [dx, dy + 18.0],
    ]


def test_preview_deterministic_and_hash_cached():
    r1 = compute_site_preview(_preview_request())
    clear_preview_cache()
    r2 = compute_site_preview(_preview_request())

    def geometry_of(r):
        d = r.model_dump()
        for k in ("request_id", "timestamp", "compute_ms", "cached"):
            d.pop(k)
        return d

    assert r1.input_hash == r2.input_hash
    assert geometry_of(r1) == geometry_of(r2), "identical inputs must yield byte-identical geometry"

    r3 = compute_site_preview(_preview_request())  # cache hit this time
    assert r3.cached is True
    assert r3.input_hash == r1.input_hash
    assert geometry_of(r3) == geometry_of(r1)


def test_preview_input_hash_responds_to_inputs():
    base = compute_site_preview(_preview_request())
    req_other_coverage = _preview_request(coverage=0.5)
    assert base.input_hash != compute_site_preview(req_other_coverage).input_hash


def test_preview_taxonomy_statuses_and_frontage_annotations():
    resp = compute_site_preview(_preview_request())
    statuses = {a.status for a in resp.annotations}
    assert statuses <= set(ANNOTATION_STATUSES)
    frontage_ann = next(a for a in resp.annotations if a.id == "frontage")
    assert frontage_ann.status == "VERIFIED"
    coverage_ann = next(a for a in resp.annotations if a.id == "coverage_ratio")
    assert coverage_ann.status == "ASSUMED"  # ratio omitted -> defaulted input
    assert "Default" in coverage_ann.basis

    resp2 = compute_site_preview(_preview_request(coverage=0.55))
    coverage_ann2 = next(a for a in resp2.annotations if a.id == "coverage_ratio")
    assert coverage_ann2.status == "CALCULATED"

    resp3 = compute_site_preview(_preview_request(with_frontage=False))
    frontage_ann3 = next(a for a in resp3.annotations if a.id == "frontage")
    assert frontage_ann3.status == "ASSUMED"
    assert resp3.frontage is None
    assert resp3.provenance["frontage_source"] is None


def test_preview_statutory_area_violation_422():
    b = _preview_boundary_rect()
    small = [PlotVertex(x=0.0, y=0.0), PlotVertex(x=5.0, y=0.0), PlotVertex(x=5.0, y=6.0), PlotVertex(x=0.0, y=6.0)]
    b.vertices = small  # 30 m2 < 36 m2
    req = SitePreviewRequest(boundary=b)
    with pytest.raises(Exception):
        compute_site_preview(req)
    resp = client.post("/api/site/preview", json=req.model_dump())
    assert resp.status_code == 422
    assert "36" in resp.json()["detail"]


def test_preview_statutory_edge_violation_422():
    b = _BS(
        vertices=[
            PlotVertex(x=0.0, y=0.0),
            PlotVertex(x=40.0, y=0.0),
            PlotVertex(x=40.0, y=14.0),
            PlotVertex(x=40.8, y=14.0),
            PlotVertex(x=40.8, y=30.0),
            PlotVertex(x=0.0, y=30.0),
        ],
        origin_lat=12.9716,
        origin_lon=77.5946,
        shape_type="irregular",
        area_sqm=1210.0,
        perimeter_m=141.6,
        source="trace",
        frontage_edge_index=0,
    )
    resp = client.post("/api/site/preview", json=SitePreviewRequest(boundary=b).model_dump())
    assert resp.status_code == 422
    assert "1.00" in resp.json()["detail"]


def test_preview_p95_latency_under_150ms():
    req = _hexagon_preview_request()
    compute_site_preview(req)  # warm-up (imports, shapely)
    clear_preview_cache()
    times = []
    for _ in range(12):
        clear_preview_cache()
        t0 = time.perf_counter()
        resp = compute_site_preview(req)
        times.append((time.perf_counter() - t0) * 1000.0)
        assert resp.ok is True
    times.sort()
    p95 = times[int(0.95 * (len(times) - 1))]
    assert p95 < 150.0, f"p95 preview latency {p95:.1f} ms exceeds the 150 ms contract"


def test_preview_irregular_plot_wedges_and_policy():
    resp = compute_site_preview(_hexagon_preview_request())
    assert resp.ok is True
    assert resp.plot["shape_type"] in ("polygon", "irregular", "pentagon")
    policy_ann = next((a for a in resp.annotations if a.id == "design_policy"), None)
    assert policy_ann is not None and policy_ann.status == "RECOMMENDED"
    assert resp.provenance["annotation_taxonomy"]["ASSUMED"]


# --------------------------------------------------------------------------- #
#  Operational envelope bounds guard for captured boundaries                   #
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
#  Shared mock helper                                                          #
# --------------------------------------------------------------------------- #

def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp
