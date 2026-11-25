"""
test_analyze_boundary.py - boundary contract for /api/analyze.
=====================================================================
The captured boundary is additive and optional:
  - request may carry it (frontend wizard) or omit it (legacy clients)
  - server RE-COMPUTES shoelace area/perimeter (authoritative) and echoes
    a read-only boundary_summary block with provenance
  - statutory violations (EC-03 area < 36 m2, EC-01 edge < 1 m) return 422
  - responses WITHOUT a boundary are byte-comparable to the boundary-less shape
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _base_payload():
    return {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "built_up_area_sqft": 1500.0,
        "quality_grade": "standard",
        "building_typology": "residential_single",
        "floors": 1,
        "ai_provider": "mock",
    }


def _boundary_payload(area_multiplier=1.0):
    # 12 x 18 m rectangle -> 216 m2, perimeter 60 m, all edges >= 1 m.
    w, d = 12.0 * area_multiplier, 18.0 * area_multiplier
    return {
        "vertices": [
            {"x": -w / 2, "y": -d / 2},
            {"x": w / 2, "y": -d / 2},
            {"x": w / 2, "y": d / 2},
            {"x": -w / 2, "y": d / 2},
        ],
        "origin_lat": 12.9716,
        "origin_lon": 77.5946,
        "shape_type": "rectangle",
        "area_sqm": 216.0 * area_multiplier * area_multiplier,
        "perimeter_m": 2 * (w + d),
        "source": "trace",
        "frontage_edge_index": 0,
    }


def test_analyze_without_boundary_unchanged(mock_external_http):
    """Legacy behavior preserved: no boundary in request -> none in response."""
    resp = client.post("/api/analyze", json=_base_payload())
    assert resp.status_code == 200
    data = resp.json()
    assert "boundary_summary" in data  # additive field exists in schema
    assert data["boundary_summary"] is None


def test_analyze_with_boundary_echoes_validated_summary(mock_external_http):
    """Server recomputes the authoritative area/perimeter and echoes provenance."""
    payload = _base_payload()
    payload["boundary"] = _boundary_payload()
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    bs = data["boundary_summary"]
    assert bs is not None
    assert bs["vertex_count"] == 4
    assert abs(bs["area_sqm"] - 216.0) < 0.5
    assert abs(bs["perimeter_m"] - 60.0) < 0.5
    assert bs["shape_type"] == "rectangle"
    assert bs["source"] == "trace"
    assert bs["frontage_edge_index"] == 0
    assert bs["winding"] in ("cw", "ccw")
    assert bs["provenance"]["boundary_source"] == "trace"
    assert bs["provenance"]["projection"].startswith("local tangent plane")
    assert bs["provenance"]["origin"]["lat"] == 12.9716


def test_analyze_boundary_below_statutory_area_rejected(mock_external_http):
    """EC-03: area < 36 m2 must 422 with the statutory reason."""
    payload = _base_payload()
    payload["boundary"] = _boundary_payload(area_multiplier=0.3)  # ~19.4 m2
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 422
    assert "36" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Captured boundary IS the reported plot area
# ---------------------------------------------------------------------------

SQM_PER_SQFT = 0.09290304
# Audit probe case: a 103,990 sq ft captured boundary (3,333 sq ft was the
# coverage-derived number the report used to print under this label).
PROBE_BOUNDARY_SQFT = 103990.0
PROBE_BOUNDARY_SQM = PROBE_BOUNDARY_SQFT * SQM_PER_SQFT


def _probe_boundary_payload():
    """A 100 m x 96.6099 m rectangle whose shoelace area is the probe area."""
    w = 100.0
    d = PROBE_BOUNDARY_SQM / w
    return {
        "vertices": [
            {"x": 0.0, "y": 0.0},
            {"x": w, "y": 0.0},
            {"x": w, "y": d},
            {"x": 0.0, "y": d},
        ],
        "origin_lat": 12.9716,
        "origin_lon": 77.5946,
        "shape_type": "rectangle",
        "area_sqm": round(PROBE_BOUNDARY_SQM, 2),
        "perimeter_m": round(2 * (w + d), 2),
        "source": "trace",
        "frontage_edge_index": 0,
    }


def test_captured_boundary_sets_the_report_plot_area(mock_external_http):
    """Report plot area == boundary shoelace area (+/- 0.1%), not coverage."""
    payload = _base_payload()
    payload["floors"] = 1
    payload["built_up_area_sqft"] = 1500.0
    payload["boundary"] = _probe_boundary_payload()

    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    boundary = data["boundary_summary"]
    assert boundary["authoritative"] is True
    assert boundary["captured"] is True
    assert abs(boundary["area_sqm"] - PROBE_BOUNDARY_SQM) < 0.5
    assert abs(boundary["area_sqft"] - PROBE_BOUNDARY_SQFT) / PROBE_BOUNDARY_SQFT < 0.001

    lv = data["land_value"]
    assert lv["plot_area_source"] == "captured_boundary"
    assert abs(lv["plot_area_sqft"] - PROBE_BOUNDARY_SQFT) / PROBE_BOUNDARY_SQFT < 0.001, (
        f"report plot area {lv['plot_area_sqft']} sq ft != captured boundary "
        f"{PROBE_BOUNDARY_SQFT} sq ft"
    )
    assert abs(lv["boundary_area_sqft"] - PROBE_BOUNDARY_SQFT) / PROBE_BOUNDARY_SQFT < 0.001
    # The coverage derivation (1500 / 0.60 = 2,500) must not leak into the report.
    assert abs(lv["plot_area_sqft"] - 2500.0) > 1000.0


def test_rectangle_fallback_labels_a_derived_plot_area(mock_external_http):
    """No boundary: derived area, honestly labelled - never 'captured boundary'."""
    payload = _base_payload()
    payload["floors"] = 2
    payload["built_up_area_sqft"] = 1500.0
    payload["ground_coverage_ratio"] = 0.60

    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    lv = data["land_value"]

    assert data["boundary_summary"] is None
    assert lv["plot_area_source"] == "derived_from_coverage"
    assert lv["boundary_area_sqft"] is None
    # 1500 built-up / 2 storeys / 60% coverage = 1,250 sq ft plot.
    assert abs(lv["plot_area_sqft"] - 1250.0) < 0.5


def test_client_plot_area_disagreement_is_surfaced(mock_external_http):
    """A supplied plot area that contradicts the boundary is disclosed."""
    payload = _base_payload()
    payload["boundary"] = _probe_boundary_payload()
    payload["plot_area_sqft"] = 2500.0  # coverage-derived, contradicts the capture

    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["land_value"]["plot_area_source"] == "captured_boundary"
    assert abs(data["land_value"]["plot_area_sqft"] - PROBE_BOUNDARY_SQFT) / PROBE_BOUNDARY_SQFT < 0.001
    assert any("PLOT-AREA" in w for w in data["warnings"]), data["warnings"]


def test_built_up_area_larger_than_the_plot_is_surfaced(mock_external_http):
    """A ground floor bigger than the plot cannot be true - say so."""
    payload = _base_payload()
    payload["floors"] = 1
    payload["built_up_area_sqft"] = 5000.0
    payload["boundary"] = _boundary_payload()  # 216 m² = 2,325 sq ft

    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["land_value"]["plot_area_source"] == "captured_boundary"
    assert any("PLOT-AREA" in w for w in data["warnings"]), data["warnings"]
    assert any(
        "footprint" in w.lower() and "exceeds" in w.lower() for w in data["warnings"]
    ), data["warnings"]


def test_client_reported_boundary_area_is_reconciled(mock_external_http):
    """The server shoelace value wins; the client's number and delta are echoed."""
    payload = _base_payload()
    boundary = _probe_boundary_payload()
    boundary["area_sqm"] = round(PROBE_BOUNDARY_SQM * 2.0, 2)  # client is wrong
    payload["boundary"] = boundary

    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    bs = data["boundary_summary"]
    assert abs(bs["area_sqm"] - PROBE_BOUNDARY_SQM) < 0.5, "server shoelace must win"
    assert bs["client_area_sqm"] is not None
    assert bs["area_delta_pct"] > 1.0
    assert any("BOUNDARY-AREA" in w for w in data["warnings"]), data["warnings"]


def test_analyze_boundary_edge_below_minimum_rejected(mock_external_http):
    """EC-01: an edge < 1 m must 422 with the statutory reason."""
    payload = _base_payload()
    # 40 x 30 m rectangle with a 0.8 m notch edge on the East side:
    # area stays > 36 m2, but the notch edge violates EC-01.
    b = {
        "vertices": [
            {"x": 0.0, "y": 0.0},
            {"x": 40.0, "y": 0.0},
            {"x": 40.0, "y": 14.0},
            {"x": 40.8, "y": 14.0},
            {"x": 40.8, "y": 30.0},
            {"x": 0.0, "y": 30.0},
        ],
        "origin_lat": 12.9716,
        "origin_lon": 77.5946,
        "shape_type": "irregular",
        "area_sqm": 1210.0,
        "perimeter_m": 141.6,
        "source": "trace",
        "frontage_edge_index": 0,
    }
    payload["boundary"] = b
    resp = client.post("/api/analyze", json=payload)
    assert resp.status_code == 422
    assert "1.00" in resp.json()["detail"]
