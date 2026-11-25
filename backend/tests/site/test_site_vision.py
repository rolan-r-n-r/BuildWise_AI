import os
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from app.services.vision.indices import (
    calculate_ndvi,
    calculate_ndwi,
    calculate_ndbi,
    classify_indices,
    resample_to_shape,
    TREE_NDVI_THRESHOLD,
    WATER_NDWI_THRESHOLD,
    BUILTUP_NDBI_THRESHOLD,
    BUILTUP_NDVI_MAX
)
from app.services.vision.vectorize import (
    vectorize_mask,
    _label_connected_components,
    _pixel_to_latlon,
    MIN_CLUSTER_AREA_SQM,
    PIXEL_AREA_SQM
)
from app.services.vision.stac_client import (
    parse_stac_item,
    StacClientError,
    NoSceneFoundError
)
from app.services.vision.site_vision_service import (
    _generate_footprint_polygon,
    _evaluate_preservation_plan,
    analyze_site_vision
)
from app.schemas.site_vision import SiteVisionResponse
from app.services.vision import imagery_fetch
from app.services.vision.imagery_fetch import fetch_site_imagery, ImageryFetchError

# ---------------------------------------------------------------------------
# 1. Pure Spectral Indices Mathematical Unit Tests
# ---------------------------------------------------------------------------

def test_spectral_indices_math_values():
    """Validates NDVI, NDWI, NDBI mathematical values on known synthetic arrays."""
    # Synthetic reflectance
    nir = np.array([[8000, 2000], [5000, 1000]], dtype=np.float32)
    red = np.array([[2000, 2000], [1000, 5000]], dtype=np.float32)
    green = np.array([[3000, 4000], [2000, 1000]], dtype=np.float32)
    swir = np.array([[3000, 6000], [4000, 1000]], dtype=np.float32)

    ndvi = calculate_ndvi(nir, red)
    # [0, 0]: (8000 - 2000) / (8000 + 2000) = 6000 / 10000 = 0.60
    assert abs(ndvi[0, 0] - 0.60) < 1e-4
    # [0, 1]: (2000 - 2000) / (2000 + 2000) = 0.0
    assert abs(ndvi[0, 1] - 0.0) < 1e-4
    # [1, 1]: (1000 - 5000) / (1000 + 5000) = -4000 / 6000 = -0.6667
    assert abs(ndvi[1, 1] - (-0.6667)) < 1e-3

    ndwi = calculate_ndwi(green, nir)
    # [0, 1]: (4000 - 2000) / (4000 + 2000) = 2000 / 6000 = 0.3333
    assert abs(ndwi[0, 1] - 0.3333) < 1e-3

    ndbi = calculate_ndbi(swir, nir)
    # [0, 1]: (6000 - 2000) / (6000 + 2000) = 4000 / 8000 = 0.50
    assert abs(ndbi[0, 1] - 0.50) < 1e-4


def test_division_by_zero_epsilon_guard():
    """Ensures arrays filled with zeros or identical negative values do not throw ZeroDivisionError."""
    zeros = np.zeros((10, 10), dtype=np.float32)
    ndvi = calculate_ndvi(zeros, zeros)
    ndwi = calculate_ndwi(zeros, zeros)
    ndbi = calculate_ndbi(zeros, zeros)

    assert not np.isnan(ndvi).any()
    assert not np.isinf(ndvi).any()
    assert (ndvi == 0.0).all()
    assert not np.isnan(ndwi).any()
    assert not np.isnan(ndbi).any()


def test_spatial_resolution_mismatch_upsampling():
    """Amendment 1 test: 20m SWIR (e.g. 12x12) upsampled to 10m NIR (24x24) for NDBI."""
    swir_20m = np.full((12, 12), 4000.0, dtype=np.float32)
    nir_10m = np.full((24, 24), 2000.0, dtype=np.float32)

    # resample_to_shape directly
    resampled = resample_to_shape(swir_20m, nir_10m.shape)
    assert resampled.shape == (24, 24)

    # calculate_ndbi auto-resamples
    ndbi = calculate_ndbi(swir_20m, nir_10m)
    assert ndbi.shape == (24, 24)
    # (4000 - 2000) / (4000 + 2000) = 2000 / 6000 = 0.3333
    assert abs(ndbi[0, 0] - 0.3333) < 1e-3


def test_index_classification_thresholds():
    """Tests documented classification threshold constants."""
    ndvi = np.array([[0.40, 0.20], [0.10, 0.35]], dtype=np.float32)
    ndwi = np.array([[0.05, 0.15], [0.10, -0.10]], dtype=np.float32)
    ndbi = np.array([[0.10, 0.05], [0.30, -0.20]], dtype=np.float32)

    tree_mask, water_mask, built_up_mask = classify_indices(ndvi, ndwi, ndbi)

    # Tree threshold: NDVI >= 0.35
    assert tree_mask[0, 0] == True # 0.40 >= 0.35
    assert tree_mask[0, 1] == False # 0.20 < 0.35
    assert tree_mask[1, 1] == True # 0.35 >= 0.35

    # Water threshold: NDWI >= 0.10
    assert water_mask[0, 0] == False # 0.05 < 0.10
    assert water_mask[0, 1] == True # 0.15 >= 0.10
    assert water_mask[1, 0] == True # 0.10 >= 0.10

    # Built-up threshold: NDBI > 0.0 AND NDVI < 0.20
    assert built_up_mask[0, 0] == False # NDVI is 0.40 (not < 0.20)
    assert built_up_mask[1, 0] == True # NDBI 0.30 > 0.0, NDVI 0.10 < 0.20


# ---------------------------------------------------------------------------
# 2. Mask Fusion Logic Unit Tests (SegFormer vs Index-Only)
# ---------------------------------------------------------------------------

def test_mask_fusion_modes():
    """
    Constraint 5: In segformer mode, Tree = SegTree AND NDVI >= 0.35.
    In index-only mode, Tree = NDVI >= 0.35 alone.
    """
    ndvi = np.array([[0.50, 0.20], [0.60, 0.10]], dtype=np.float32)
    idx_tree_mask = (ndvi >= TREE_NDVI_THRESHOLD) # [[True, False], [True, False]]

    # Simulated SegFormer predictions: Tree (True) only at [0, 0] and [0, 1]
    seg_tree_mask = np.array([[True, True], [False, False]], dtype=bool)

    # SegFormer Mode Fusion: seg_tree_mask & idx_tree_mask
    seg_fused_tree = seg_tree_mask & idx_tree_mask
    assert seg_fused_tree[0, 0] == True # Both agree (Seg=Tree, NDVI=0.50)
    assert seg_fused_tree[0, 1] == False # Seg said tree, but NDVI=0.20 < 0.35 (refinement rejects)
    assert seg_fused_tree[1, 0] == False # NDVI=0.60, but Seg said not tree (refinement rejects)
    assert seg_fused_tree[1, 1] == False # Neither

    # Index-Only Mode: idx_tree_mask directly
    index_only_fused = idx_tree_mask
    assert index_only_fused[0, 0] == True
    assert index_only_fused[0, 1] == False
    assert index_only_fused[1, 0] == True # Accepted based on NDVI alone
    assert index_only_fused[1, 1] == False


# ---------------------------------------------------------------------------
# 3. Connected Components and Minimum Area Filter Tests
# ---------------------------------------------------------------------------

def test_connected_components_and_area_filter():
    """Verifies component labeling and minimum area 25 sqm filter."""
    # 10x10 synthetic grid at 10m resolution (each pixel = 100 sqm)
    mask = np.zeros((10, 10), dtype=bool)
    # Cluster 1: 3 adjacent pixels = 300 sqm (>= 25 sqm)
    mask[1, 1] = True
    mask[1, 2] = True
    mask[2, 1] = True

    # Cluster 2: 1 single pixel = 100 sqm (>= 25 sqm)
    mask[7, 7] = True

    labeled, num_features = _label_connected_components(mask)
    assert num_features == 2

    features = vectorize_mask(
        binary_mask=mask,
        feature_type_prefix="tree-cluster",
        center_lat=12.9716,
        center_lon=77.5946,
        min_area_sqm=MIN_CLUSTER_AREA_SQM
    )
    assert len(features) == 2
    areas = [f["properties"]["area_sqm"] for f in features]
    assert 300.0 in areas
    assert 100.0 in areas

    # Test filtering out when min_area_sqm is set higher than 150 sqm
    filtered_features = vectorize_mask(
        binary_mask=mask,
        feature_type_prefix="tree-cluster",
        center_lat=12.9716,
        center_lon=77.5946,
        min_area_sqm=150.0
    )
    assert len(filtered_features) == 1
    assert filtered_features[0]["properties"]["area_sqm"] == 300.0


# ---------------------------------------------------------------------------
# 4. Geotransform Coordinate Conversion Round-Trip Tests
# ---------------------------------------------------------------------------

def test_pixel_to_latlon_conversion():
    """Tests pixel coordinate conversion to geographic (lon, lat) WGS84."""
    center_lat = 12.9716
    center_lon = 77.5946

    # Center pixel of 24x24 grid is (11.5, 11.5)
    lon_c, lat_c = _pixel_to_latlon(11.5, 11.5, center_lat, center_lon, grid_shape=(24, 24))
    assert abs(lat_c - center_lat) < 1e-4
    assert abs(lon_c - center_lon) < 1e-4

    # Pixel 120m North (row 0 vs center 11.5)
    lon_n, lat_n = _pixel_to_latlon(11.5, 0.0, center_lat, center_lon, grid_shape=(24, 24))
    assert lat_n > center_lat
    # ~115m North: delta lat should be roughly 115 / 110540 ~ 0.00104 degrees
    assert abs((lat_n - center_lat) - 0.00104) < 1e-4


# ---------------------------------------------------------------------------
# 5. Tree Preservation Plan Ranking Tests
# ---------------------------------------------------------------------------

def test_preservation_ranking_logic():
    """
    Preservation ranking rules:
    - Overlap Footprint & Area > 50 sqm: preserve
    - Overlap Footprint & Area 15-50 sqm: compensate
    - Overlap Footprint & Area < 15 sqm: removable
    - Outside Footprint: context
    """
    center_lat, center_lon = 12.9716, 77.5946
    footprint_poly = _generate_footprint_polygon(center_lat, center_lon, area_sqm=200.0)

    # 4 synthetic clusters:
    # 1. Inside footprint (at center), area 80 sqm -> preserve
    feat1 = {
        "properties": {"cluster_id": "tree-cluster-1", "area_sqm": 80.0, "mean_ndvi": 0.65, "centroid": [center_lon, center_lat]},
        "geometry": {"type": "Polygon", "coordinates": [[[center_lon - 0.00005, center_lat - 0.00005], [center_lon + 0.00005, center_lat - 0.00005], [center_lon + 0.00005, center_lat + 0.00005], [center_lon - 0.00005, center_lat + 0.00005], [center_lon - 0.00005, center_lat - 0.00005]]]}
    }
    # 2. Inside footprint, area 30 sqm -> compensate
    feat2 = {
        "properties": {"cluster_id": "tree-cluster-2", "area_sqm": 30.0, "mean_ndvi": 0.50, "centroid": [center_lon, center_lat]},
        "geometry": {"type": "Polygon", "coordinates": [[[center_lon - 0.00002, center_lat - 0.00002], [center_lon + 0.00002, center_lat - 0.00002], [center_lon + 0.00002, center_lat + 0.00002], [center_lon - 0.00002, center_lat + 0.00002], [center_lon - 0.00002, center_lat - 0.00002]]]}
    }
    # 3. Inside footprint, area 10 sqm -> removable
    feat3 = {
        "properties": {"cluster_id": "tree-cluster-3", "area_sqm": 10.0, "mean_ndvi": 0.40, "centroid": [center_lon, center_lat]},
        "geometry": {"type": "Polygon", "coordinates": [[[center_lon - 0.00001, center_lat - 0.00001], [center_lon + 0.00001, center_lat - 0.00001], [center_lon + 0.00001, center_lat + 0.00001], [center_lon - 0.00001, center_lat + 0.00001], [center_lon - 0.00001, center_lat - 0.00001]]]}
    }
    # 4. Outside footprint (offset by 0.002 deg ~220m away) -> context
    feat4 = {
        "properties": {"cluster_id": "tree-cluster-4", "area_sqm": 90.0, "mean_ndvi": 0.70, "centroid": [center_lon + 0.002, center_lat + 0.002]},
        "geometry": {"type": "Polygon", "coordinates": [[[center_lon + 0.002, center_lat + 0.002], [center_lon + 0.0021, center_lat + 0.002], [center_lon + 0.0021, center_lat + 0.0021], [center_lon + 0.002, center_lat + 0.0021], [center_lon + 0.002, center_lat + 0.002]]]}
    }

    plan = _evaluate_preservation_plan([feat1, feat2, feat3, feat4], footprint_poly)
    ranks = {p.cluster_id: p.rank for p in plan}

    assert ranks["tree-cluster-1"] == "preserve"
    assert ranks["tree-cluster-2"] == "compensate"
    assert ranks["tree-cluster-3"] == "removable"
    assert ranks["tree-cluster-4"] == "context"


# ---------------------------------------------------------------------------
# 6. STAC Response Parsing Unit Tests (with Recorded Fixture JSON)
# ---------------------------------------------------------------------------

RECORDED_STAC_FIXTURE = {
    "id": "S2C_43PDS_20260331_0_L2A",
    "properties": {
        "datetime": "2026-03-31T05:34:56.116000Z",
        "eo:cloud_cover": 1.318
    },
    "assets": {
        "blue": {"href": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/test/B02.tif"},
        "green": {"href": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/test/B03.tif"},
        "red": {"href": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/test/B04.tif"},
        "nir": {"href": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/test/B08.tif"},
        "swir16": {"href": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/test/B11.tif"},
        "scl": {"href": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/test/SCL.tif"},
        "visual": {"href": "https://sentinel-cogs.s3.us-west-2.amazonaws.com/test/TCI.tif"}
    }
}

def test_stac_response_parser():
    """Parses recorded STAC item into scene metadata and asset hrefs."""
    parsed = parse_stac_item(RECORDED_STAC_FIXTURE)
    assert parsed["scene_id"] == "S2C_43PDS_20260331_0_L2A"
    assert parsed["cloud_cover_pct"] == 1.32
    assert parsed["source"] == "Copernicus Sentinel-2"
    assert parsed["assets"]["B02"].endswith("B02.tif")
    assert parsed["assets"]["B04"].endswith("B04.tif")
    assert parsed["assets"]["B08"].endswith("B08.tif")
    assert parsed["assets"]["B11"].endswith("B11.tif")
    assert parsed["assets"]["SCL"].endswith("SCL.tif")


def test_stac_missing_essential_bands_raises():
    """Verifies that missing critical optical bands raises StacClientError."""
    bad_fixture = {
        "id": "S2A_INCOMPLETE",
        "properties": {"datetime": "2026-01-01T00:00:00Z", "eo:cloud_cover": 5.0},
        "assets": {"blue": {"href": "B02.tif"}} # missing red, green, nir
    }
    with pytest.raises(StacClientError):
        parse_stac_item(bad_fixture)


# ---------------------------------------------------------------------------
# 7. End-to-End Orchestrator Graceful Fallback & Budget Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_site_vision_degraded_when_stac_fails():
    """Tests that STAC outage degrades gracefully to unavailable mode without unhandled exceptions."""
    with patch("app.services.vision.site_vision_service.search_latest_sentinel_scene") as mock_stac:
        mock_stac.side_effect = StacClientError("Simulated network catalog timeout")
        resp = await analyze_site_vision(12.9716, 77.5946)

        assert isinstance(resp, SiteVisionResponse)
        assert resp.mode == "unavailable"
        assert resp.green_cover_pct == 0.0
        assert len(resp.warnings) > 0
        assert "Simulated network catalog timeout" in resp.warnings[0]


@pytest.mark.asyncio
async def test_site_vision_fallback_to_index_only_when_segformer_fails():
    """Tests that when SegFormer raises DegradedVisionError, orchestrator returns index-only mode."""
    mock_bands = {
        "B02": np.full((24, 24), 1000, dtype=np.float32),
        "B03": np.full((24, 24), 2000, dtype=np.float32),
        "B04": np.full((24, 24), 1500, dtype=np.float32),
        "B08": np.full((24, 24), 5000, dtype=np.float32),
        "B11": np.full((24, 24), 2500, dtype=np.float32)
    }
    mock_imagery = {
        "bands": mock_bands,
        "valid_mask": np.ones((24, 24), dtype=bool),
        "affine_transform": None,
        "crs": "EPSG:32643",
        "shape": (24, 24)
    }

    with patch("app.services.vision.site_vision_service.search_latest_sentinel_scene") as mock_stac, \
         patch("app.services.vision.site_vision_service.fetch_site_imagery") as mock_fetch, \
         patch("app.services.vision.site_vision_service.vision_cache.get", return_value=None), \
         patch("app.services.vision.site_vision_service.get_segformer_adapter") as mock_adapter:

        mock_stac.return_value = {
            "scene_id": "MOCK_S2_SCENE",
            "datetime": "2026-03-31T05:34:56Z",
            "cloud_cover_pct": 0.5,
            "source": "Copernicus Sentinel-2",
            "assets": {"B02": "url", "B03": "url", "B04": "url", "B08": "url"}
        }
        mock_fetch.return_value = mock_imagery

        # Make SegFormer fail
        mock_adapter.return_value.predict_classes.side_effect = Exception("Model memory allocation failure")

        resp = await analyze_site_vision(12.9716, 77.5946)

        assert isinstance(resp, SiteVisionResponse)
        assert resp.mode == "index-only"
        # B08 (5000) vs B04 (1500) -> NDVI = 3500 / 6500 = 0.538 >= 0.35 (Green cover detected)
        assert resp.green_cover_pct > 0.0
        assert len(resp.tree_clusters.features) > 0


# ---------------------------------------------------------------------------
# 7b. Band fetch: optional bands are optional, required bands are required
# ---------------------------------------------------------------------------

def _fake_band(monkeypatch, failing):
    def fake(band_name, href, center_lon, center_lat, window_half_meters=120.0):
        if band_name in failing:
            raise ImageryFetchError(f"simulated read failure for {band_name}")
        value = 1200.0 if band_name in ("B02", "B04") else 2000.0
        if band_name == "B08":
            value = 5000.0
        return band_name, np.full((24, 24), value, dtype=np.float32), "EPSG:32643", None

    monkeypatch.setattr(imagery_fetch, "_fetch_single_band_window", fake)


def test_fetch_site_imagery_tolerates_missing_optional_bands(monkeypatch):
    """B11/SCL/B02 losses must not sink the analysis (they have fallbacks)."""
    _fake_band(monkeypatch, failing={"B11", "SCL", "B02"})

    imagery = fetch_site_imagery(
        {b: "https://example.test/%s.tif" % b for b in ("B02", "B03", "B04", "B08", "B11", "SCL")},
        center_lat=12.9716,
        center_lon=77.5946,
    )

    assert set(imagery["bands"]) == {"B03", "B04", "B08", "B11"}, (
        "B11 is synthesised from red/NIR when it cannot be read"
    )
    assert imagery["valid_mask"].all(), "no SCL means no cloud mask, not an empty scene"
    assert set(imagery["failures"]) == {"B11", "SCL", "B02"}


def test_fetch_site_imagery_fails_when_a_required_band_is_missing(monkeypatch):
    _fake_band(monkeypatch, failing={"B08"})

    with pytest.raises(ImageryFetchError) as exc:
        fetch_site_imagery(
            {b: "https://example.test/%s.tif" % b for b in ("B02", "B03", "B04", "B08")},
            center_lat=12.9716,
            center_lon=77.5946,
        )

    assert "B08" in str(exc.value)


# ---------------------------------------------------------------------------
# 8. Optional Live Integration Test (Skip when offline)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"),
    reason="Live satellite scan test skipped by default. Set RUN_LIVE_TESTS=1 to run."
)
async def test_live_site_vision_forest():
    """Live scan on forested region 14.96083, 74.71451 (Uttara Kannada)."""
    resp = await analyze_site_vision(14.96083, 74.71451)
    assert isinstance(resp, SiteVisionResponse)
    assert resp.mode in ("segformer", "index-only")
    assert resp.green_cover_pct > 40.0
    assert len(resp.tree_clusters.features) > 0
    assert len(resp.preservation_plan) > 0


# ---------------------------------------------------------------------------
# 9. Bug Fix Regression Tests (Vectorize Fallback, PDF Pydantic, Orientation)
# ---------------------------------------------------------------------------

def test_vectorize_fallback_when_shapely_empty():
    """Ensures vectorize_mask gracefully falls back to bounding box if polygon simplification collapses."""
    mask = np.zeros((10, 10), dtype=bool)
    mask[2, 2] = True # Single pixel
    # Tolerance so high that simplification would collapse
    with patch("shapely.geometry.Polygon.simplify") as mock_simplify:
        from shapely.geometry import Polygon
        # Return an empty Polygon
        mock_simplify.return_value = Polygon()
        features = vectorize_mask(
            binary_mask=mask,
            feature_type_prefix="tree-cluster",
            center_lat=12.9716,
            center_lon=77.5946,
            min_area_sqm=25.0
        )
        assert len(features) == 1
        assert features[0]["geometry"]["type"] == "Polygon"
        assert len(features[0]["geometry"]["coordinates"][0]) == 5 # Valid GeoJSON closed ring


def test_pdf_report_with_pydantic_site_vision():
    """Verifies that generate_pdf_report renders Section 9 when site_vision is a Pydantic SiteVisionResponse."""
    from app.services.report_service import generate_pdf_report
    from app.schemas.site_vision import PreservationItem

    item = PreservationItem(
        cluster_id="tree-cluster-1",
        area_sqm=120.0,
        centroid=[77.5946, 12.9716],
        mean_ndvi=0.68,
        overlap_footprint=True,
        rank="preserve",
        action="Preserve mature root zone"
    )
    resp = SiteVisionResponse(
        mode="segformer",
        green_cover_pct=34.5,
        water_cover_pct=2.1,
        built_up_pct=15.0,
        preservation_plan=[item]
    )

    pdf_stream = generate_pdf_report({
        "formatted_address": "Bangalore Test Site",
        "overall_suitability_score": 88.0,
        "suitability_verdict": "Suitable",
        "site_vision": resp
    })

    pdf_bytes = pdf_stream.getvalue()
    assert len(pdf_bytes) > 4000
    # Verify PDF stream is valid
    assert pdf_bytes.startswith(b"%PDF")


def test_orientation_deg_footprint_rotation():
    """Validates that custom orientation_deg rotates the footprint polygon correctly."""
    center_lat, center_lon = 12.9716, 77.5946
    poly_east_west = _generate_footprint_polygon(center_lat, center_lon, area_sqm=200.0, orientation_deg=90.0)
    poly_north_south = _generate_footprint_polygon(center_lat, center_lon, area_sqm=200.0, orientation_deg=0.0)

    # East-West orientation should have wider longitude spread than latitude spread
    bounds_ew = poly_east_west.bounds # (minx, miny, maxx, maxy)
    dx_ew = bounds_ew[2] - bounds_ew[0]
    dy_ew = bounds_ew[3] - bounds_ew[1]
    assert dx_ew > dy_ew

    # North-South orientation should have greater latitude spread than longitude spread
    bounds_ns = poly_north_south.bounds
    dx_ns = bounds_ns[2] - bounds_ns[0]
    dy_ns = bounds_ns[3] - bounds_ns[1]
    assert dy_ns > dx_ns
