import asyncio
import time
import math
import logging
from typing import Dict, Any, Optional, List
import numpy as np

from app.config import settings
from app.utils.cache_utils import vision_cache
from app.services.vision.stac_client import (
    search_latest_sentinel_scene,
    StacClientError,
    NoSceneFoundError,
    StacTimeoutError
)
from app.services.vision.imagery_fetch import (
    fetch_site_imagery,
    ImageryFetchError
)
from app.services.vision.indices import (
    calculate_ndvi,
    calculate_ndwi,
    calculate_ndbi,
    classify_indices,
    WATER_NDWI_THRESHOLD
)
from app.services.vision.segmentation import (
    get_segformer_adapter,
    DegradedVisionError
)
from app.services.vision.vectorize import (
    vectorize_mask
)
from app.schemas.site_vision import (
    SiteVisionResponse,
    SceneMetadata,
    PreservationItem,
    GeoJsonFeatureCollection,
    GeoJsonFeature,
    GeoJsonGeometry
)

logger = logging.getLogger(__name__)

# End-to-end ceiling for one scan, used only to disclose a slow run.  It is the
# imagery budget (26 s cold COG range read) plus SegFormer CPU inference (up to
# ~9 s), because those two are the honest floor on a cold cache; the previous
# 20 s predated the COG reads being measured and fired on every successful cold
# scan, reading as a fault when the scan had in fact completed.
SERVER_BUDGET_SECONDS: float = 40.0

def _generate_footprint_polygon(
    center_lat: float,
    center_lon: float,
    area_sqm: float = 185.8, # ~2000 sq ft
    aspect_ratio: float = 1.75,
    orientation_deg: float = 90.0 # East-West default
) -> Any:
    """
    Constructs a Shapely Polygon representing the building footprint layout.
    """
    try:
        from shapely.geometry import Polygon
    except ImportError:
        return None

    width_m = math.sqrt(area_sqm / aspect_ratio)
    length_m = width_m * aspect_ratio
    half_l = length_m / 2.0
    half_w = width_m / 2.0

    a_rad = math.radians(orientation_deg)
    long_e = math.sin(a_rad)
    long_n = math.cos(a_rad)

    short_angle = a_rad + math.pi / 2.0
    short_e = math.sin(short_angle)
    short_n = math.cos(short_angle)

    corners = [
        (-half_l, -half_w),
        (half_l, -half_w),
        (half_l, half_w),
        (-half_l, half_w)
    ]

    lat_rad = math.radians(center_lat)
    poly_coords = []
    for cx, cy in corners:
        m_east = cx * long_e + cy * short_e
        m_north = cx * long_n + cy * short_n
        d_lat = m_north / 110540.0
        d_lng = m_east / (111320.0 * max(math.cos(lat_rad), 0.01))
        poly_coords.append((center_lon + d_lng, center_lat + d_lat))

    poly_coords.append(poly_coords[0])
    return Polygon(poly_coords)


def _evaluate_preservation_plan(
    tree_features: List[Dict[str, Any]],
    footprint_poly: Any
) -> List[PreservationItem]:
    """
    Ranks tree clusters according to footprint overlap and area thresholds:
    - Overlap Footprint & Area > 50 sqm: preserve
    - Overlap Footprint & Area 15-50 sqm: compensate
    - Overlap Footprint & Area < 15 sqm: removable
    - Outside Footprint: context
    """
    preservation_plan: List[PreservationItem] = []

    try:
        from shapely.geometry import shape, Point
        has_shapely = True
    except ImportError:
        has_shapely = False

    for feat in tree_features:
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        cluster_id = props.get("cluster_id", "cluster")
        area_sqm = float(props.get("area_sqm", 0.0))
        mean_ndvi = float(props.get("mean_ndvi", 0.0))
        centroid = props.get("centroid", [0.0, 0.0])

        overlaps = False
        if footprint_poly is not None and has_shapely:
            try:
                cluster_shape = shape(geom)
                overlaps = cluster_shape.intersects(footprint_poly)
            except Exception:
                centroid_pt = Point(centroid[0], centroid[1])
                overlaps = footprint_poly.contains(centroid_pt)

        # Classification rules
        if overlaps:
            if area_sqm > 50.0:
                rank = "preserve"
                action = "High-priority canopy retention. Modify architectural setback or basement excavation line to preserve mature root zone."
            elif area_sqm >= 15.0:
                rank = "compensate"
                action = "Canopy within construction envelope. Tree transplantation or mandatory 3:1 compensatory afforestation required."
            else:
                rank = "removable"
                action = "Low-density vegetative growth. Selective clearance permitted with organic green mulch recycling."
        else:
            rank = "context"
            action = "Exterior site greenery. Retain for boundary aesthetics, microclimate cooling, and passive wind buffering."

        props["overlap_footprint"] = overlaps
        props["preservation_rank"] = rank
        props["rank"] = rank

        preservation_plan.append(PreservationItem(
            cluster_id=cluster_id,
            area_sqm=area_sqm,
            centroid=centroid,
            mean_ndvi=mean_ndvi,
            overlap_footprint=overlaps,
            rank=rank,
            action=action
        ))

    # Sort: preserve first, then compensate, removable, and context
    rank_order = {"preserve": 0, "compensate": 1, "removable": 2, "context": 3}
    preservation_plan.sort(key=lambda p: (rank_order.get(p.rank, 4), -p.area_sqm))
    return preservation_plan


async def analyze_site_vision(
    latitude: float,
    longitude: float,
    plot_area_sqft: Optional[float] = None,
    mode_override: Optional[str] = None,
    orientation_deg: Optional[float] = None
) -> SiteVisionResponse:
    """
    Orchestrates the satellite vision pipeline:
    1. STAC query with 4s timeout.
    2. Windowed COG fetch with 8s timeout.
    3. Pure spectral index math (NDVI, NDWI, NDBI).
    4. Optional SegFormer semantic segmentation on CPU.
    5. Mask fusion & vectorization.
    6. Preservation planning against proposed footprint.
    7. Multi-tier graceful degradation and 20s budget enforcement.
    """
    start_time = time.time()
    timing: Dict[str, float] = {}
    warnings: List[str] = []

    effective_plot_sqft = plot_area_sqft if (plot_area_sqft and plot_area_sqft >= 200.0) else 2000.0
    plot_area_sqm = effective_plot_sqft * 0.092903

    # Step 1: STAC Search for Sentinel-2 Scene
    stac_t0 = time.time()
    try:
        scene_info = await search_latest_sentinel_scene(latitude, longitude)
        timing["stac_ms"] = round((time.time() - stac_t0) * 1000.0, 1)
    except (NoSceneFoundError, StacTimeoutError, StacClientError, Exception) as exc:
        timing["stac_ms"] = round((time.time() - stac_t0) * 1000.0, 1)
        timing["total_ms"] = round((time.time() - start_time) * 1000.0, 1)
        logger.warning("STAC scene search failed: %s", exc)
        return SiteVisionResponse(
            mode="unavailable",
            scene_metadata=None,
            green_cover_pct=0.0,
            water_cover_pct=0.0,
            built_up_pct=0.0,
            tree_clusters=GeoJsonFeatureCollection(features=[]),
            water_bodies=GeoJsonFeatureCollection(features=[]),
            preservation_plan=[],
            warnings=[f"Satellite imagery unavailable: {exc}"],
            timing_ms=timing
        )

    scene_id = scene_info["scene_id"]

    # Check 7-day TTL cache keyed on 0.002 deg grid (~220m) + scene_id
    cached_payload = vision_cache.get(
        latitude, longitude, "site_vision", grid_step=0.002, scene_id=scene_id
    )
    if cached_payload:
        logger.info("Serving SiteVisionResponse from 7-day spatial cache (%s)", scene_id)
        cached_resp = SiteVisionResponse(**cached_payload)
        cached_resp.timing_ms["cached"] = 1.0
        return cached_resp

    scene_meta = SceneMetadata(
        id=scene_id,
        datetime=scene_info["datetime"],
        cloud_cover_pct=scene_info["cloud_cover_pct"],
        source=scene_info["source"]
    )

    # Step 2: Fetch windowed COG imagery
    #
    # IN A WORKER THREAD.  This is a synchronous GDAL /vsicurl/ read over a
    # ThreadPoolExecutor; called directly from this coroutine it BLOCKED the
    # uvicorn event loop for the whole fetch (measured: /api/health took 11.5 s
    # while one site-vision scan was in flight, so every other request on the
    # app - analysis, report, floor plan - queued behind a satellite download).
    fetch_t0 = time.time()
    try:
        imagery = await asyncio.to_thread(
            fetch_site_imagery,
            asset_urls=scene_info["assets"],
            center_lat=latitude,
            center_lon=longitude,
        )
        timing["fetch_ms"] = round((time.time() - fetch_t0) * 1000.0, 1)
    except (ImageryFetchError, Exception) as exc:
        timing["fetch_ms"] = round((time.time() - fetch_t0) * 1000.0, 1)
        timing["total_ms"] = round((time.time() - start_time) * 1000.0, 1)
        logger.warning("COG imagery fetch failed: %s", exc)
        return SiteVisionResponse(
            mode="unavailable",
            scene_metadata=scene_meta,
            green_cover_pct=0.0,
            water_cover_pct=0.0,
            built_up_pct=0.0,
            tree_clusters=GeoJsonFeatureCollection(features=[]),
            water_bodies=GeoJsonFeatureCollection(features=[]),
            preservation_plan=[],
            warnings=[f"Satellite spectral band retrieval failed: {exc}"],
            timing_ms=timing
        )

    bands = imagery["bands"]
    valid_mask = imagery["valid_mask"]
    affine_transform = imagery["affine_transform"]
    crs = imagery["crs"]

    # Step 3: Pure spectral indices math
    ndvi = calculate_ndvi(bands["B08"], bands["B04"])
    ndwi = calculate_ndwi(bands["B03"], bands["B08"])
    ndbi = calculate_ndbi(bands["B11"], bands["B08"])

    idx_tree_mask, idx_water_mask, built_up_mask = classify_indices(
        ndvi, ndwi, ndbi, valid_mask=valid_mask
    )

    # Step 4: Semantic Segmentation (SegFormer) or Index-Only Mode
    active_mode = "index-only"
    seg_tree_mask = None
    seg_water_mask = None
    inference_t0 = time.time()

    should_run_segformer = (
        getattr(settings, "ENABLE_SEGFORMER", False)
        and mode_override != "index-only"
    )

    if "B02" not in bands:
        # The optional blue band did not arrive; SegFormer cannot run on
        # red/green alone.  Say so instead of failing the scan.
        warnings.append(
            "SegFormer segmentation skipped: the blue (B02) band was unavailable. "
            "Spectral-index vegetation and water detection are unaffected."
        )
        timing["inference_ms"] = 0.0
    elif not should_run_segformer:
        active_mode = "index-only"
        timing["inference_ms"] = 0.0
        if mode_override == "segformer":
            warnings.append(
                "SegFormer deep learning segmentation is disabled in this environment to protect memory limits; "
                "operating in high-precision spectral index mode."
            )
    else:
        try:
            # Model load + CPU inference are blocking work too - keep them off
            # the event loop like the imagery read above.
            adapter = await asyncio.to_thread(get_segformer_adapter)
            seg_tree_mask, seg_water_mask = await asyncio.to_thread(
                lambda: adapter.predict_classes(
                    b04_red=bands["B04"],
                    b03_green=bands["B03"],
                    b02_blue=bands["B02"],
                )
            )
            active_mode = "segformer"
            timing["inference_ms"] = round((time.time() - inference_t0) * 1000.0, 1)
        except DegradedVisionError as exc:
            warnings.append(str(exc))
            active_mode = "index-only"
            timing["inference_ms"] = round((time.time() - inference_t0) * 1000.0, 1)
        except Exception as exc:
            warnings.append(f"Deep learning segmentation bypassed: {exc}")
            active_mode = "index-only"
            timing["inference_ms"] = round((time.time() - inference_t0) * 1000.0, 1)

    # Step 5: Deterministic Mask Fusion
    # Constraint 5: Final tree mask = SegFormer tree AND NDVI >= 0.35 in segformer mode; NDVI >= 0.35 in index-only mode
    if active_mode == "segformer" and seg_tree_mask is not None:
        final_tree_mask = seg_tree_mask & idx_tree_mask & valid_mask
        final_water_mask = (seg_water_mask | idx_water_mask) & (ndwi >= WATER_NDWI_THRESHOLD) & valid_mask
    else:
        final_tree_mask = idx_tree_mask & valid_mask
        final_water_mask = idx_water_mask & valid_mask

    # Step 6: Vectorize Tree Clusters & Water Bodies
    tree_features = vectorize_mask(
        binary_mask=final_tree_mask,
        feature_type_prefix="tree-cluster",
        center_lat=latitude,
        center_lon=longitude,
        affine_transform=affine_transform,
        crs=crs,
        metric_grid=ndvi,
        min_area_sqm=25.0
    )

    water_features = vectorize_mask(
        binary_mask=final_water_mask,
        feature_type_prefix="water-body",
        center_lat=latitude,
        center_lon=longitude,
        affine_transform=affine_transform,
        crs=crs,
        metric_grid=ndwi,
        min_area_sqm=25.0
    )

    # Step 7: Proposed Footprint Layout & Preservation Plan
    footprint_poly = _generate_footprint_polygon(
        center_lat=latitude,
        center_lon=longitude,
        area_sqm=min(plot_area_sqm * 0.60, 250.0), # Plinth coverage
        orientation_deg=orientation_deg if orientation_deg is not None else 90.0
    )

    preservation_plan = _evaluate_preservation_plan(tree_features, footprint_poly)

    # Step 8: Metric Aggregations
    # Total valid pixels in the 240m x 240m scene
    total_valid = max(int(np.sum(valid_mask)), 1)

    # Built-up percentage across the surveyed window
    built_up_pixels = int(np.sum(built_up_mask & valid_mask))
    built_up_pct = round((built_up_pixels / total_valid) * 100.0, 1)

    # Surface water percentage
    water_pixels = int(np.sum(final_water_mask))
    water_pct = round((water_pixels / total_valid) * 100.0, 1)

    # Green Cover Index: tree canopy pixels divided by total valid pixels in the surveyed site window
    tree_pixels = int(np.sum(final_tree_mask))
    green_cover_pct = min(100.0, round((tree_pixels / total_valid) * 100.0, 1))

    # Format GeoJSON FeatureCollections
    tree_fc = GeoJsonFeatureCollection(
        features=[
            GeoJsonFeature(
                geometry=GeoJsonGeometry(**f["geometry"]),
                properties=f["properties"]
            )
            for f in tree_features
        ]
    )

    water_fc = GeoJsonFeatureCollection(
        features=[
            GeoJsonFeature(
                geometry=GeoJsonGeometry(**f["geometry"]),
                properties=f["properties"]
            )
            for f in water_features
        ]
    )

    timing["total_ms"] = round((time.time() - start_time) * 1000.0, 1)

    # Server-side 20s budget check
    if timing["total_ms"] > (SERVER_BUDGET_SECONDS * 1000.0):
        warnings.append(f"Server-side execution time ({timing['total_ms']:.0f}ms) approached latency budget.")

    response = SiteVisionResponse(
        mode=active_mode, # type: ignore
        scene_metadata=scene_meta,
        green_cover_pct=green_cover_pct,
        water_cover_pct=water_pct,
        built_up_pct=built_up_pct,
        tree_clusters=tree_fc,
        water_bodies=water_fc,
        preservation_plan=preservation_plan,
        warnings=warnings,
        timing_ms=timing
    )

    # Cache response in 7-day TTL spatial grid cache
    try:
        vision_cache.set(
            latitude, longitude, "site_vision", response.model_dump(),
            grid_step=0.002, scene_id=scene_id
        )
    except Exception as exc:
        logger.debug("Failed to write to vision_cache: %s", exc)

    return response
