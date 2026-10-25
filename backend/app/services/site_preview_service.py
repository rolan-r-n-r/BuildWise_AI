"""
Site preview service.
===============================
Deterministic setbacks -> buildable -> footprint synthesis for the map
overlay. Reuses the canonical engine `compute_canonical_site_plan`
(single-source site math) - NO floor solve, NO LLM, NO network calls.

Contracts:
- Deterministic: keyed by SHA-256 of (canonical polygon, coverage, frontage,
  origin); identical inputs -> byte-identical geometry.
- p95 < 150 ms (pure Python + shapely on small polygons; hash cache on top).
- Annotation taxonomy CALCULATED / ASSUMED / RECOMMENDED / VERIFIED on every
  annotation; ASSUMED never renders as CALCULATED.
- Provenance (boundary source, frontage source, projection origin) flows
  end-to-end.
"""

import hashlib
import json
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import box
from shapely.ops import unary_union

from app.schemas.site_intelligence import SiteAnnotation, SitePreviewRequest, SitePreviewResponse
from app.schemas.site_plan import PlotPolygonModel, SitePlanModel
from app.services.boundary_service import boundary_bounds_violation
from app.services.floorplan.site_geometry import compute_canonical_site_plan

PREVIEW_CACHE_MAX_ENTRIES = 128
PREVIEW_CACHE_TTL_SECONDS = 3600

PROJECTION_NOTE = "local tangent plane (E/N, equirectangular, cos(lat))"
ENGINE_REF = "app.services.floorplan.site_geometry.compute_canonical_site_plan"

ANNOTATION_TAXONOMY: Dict[str, str] = {
    "CALCULATED": "Derived deterministically from the request inputs (server formulas)",
    "ASSUMED": "Defaulted input or heuristic not confirmed by the user",
    "RECOMMENDED": "Engineering suggestion derived from the computed geometry",
    "VERIFIED": "Confirmed by the user on the map (or external telemetry where noted)",
}


class BoundaryStatutoryViolation(ValueError):
    """Raised for EC-01/EC-03 violations; the endpoint maps this to HTTP 422."""


# --------------------------------------------------------------------------- #
#  Bounded TTL cache (mono-threaded asyncio: no locking needed)                #
# --------------------------------------------------------------------------- #

_preview_cache: "OrderedDict[str, Tuple[float, SitePreviewResponse]]" = OrderedDict()


def clear_preview_cache() -> None:
    _preview_cache.clear()


def _cache_get(key: str) -> Optional[SitePreviewResponse]:
    entry = _preview_cache.get(key)
    if entry is None:
        return None
    ts, resp = entry
    if time.monotonic() - ts > PREVIEW_CACHE_TTL_SECONDS:
        _preview_cache.pop(key, None)
        return None
    _preview_cache.move_to_end(key)
    return resp


def _cache_set(key: str, resp: SitePreviewResponse) -> None:
    _preview_cache[key] = (time.monotonic(), resp)
    _preview_cache.move_to_end(key)
    while len(_preview_cache) > PREVIEW_CACHE_MAX_ENTRIES:
        _preview_cache.popitem(last=False)


# --------------------------------------------------------------------------- #
#  Input hashing (determinism key)                                             #
# --------------------------------------------------------------------------- #

def preview_input_hash(
    vertices: List[Tuple[float, float]],
    origin_lat: float,
    origin_lon: float,
    coverage: float,
    frontage_edge_index: Optional[int],
    typology: str,
) -> str:
    canonical = json.dumps(
        {
            "vertices": [[round(x, 3), round(y, 3)] for x, y in vertices],
            "origin": [round(origin_lat, 7), round(origin_lon, 7)],
            "coverage": round(coverage, 4),
            "frontage_edge_index": frontage_edge_index,
            "typology": typology,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
#  Geometry serialization helpers                                              #
# --------------------------------------------------------------------------- #

def _ring(coords: List[Tuple[float, float]]) -> List[List[float]]:
    return [[round(x, 2), round(y, 2)] for x, y in coords]


def _footprint_ring(plan: SitePlanModel) -> Tuple[List[List[float]], Optional[str]]:
    """Exterior ring of the footprint (union of wings), mirroring site_geometry."""
    fp = plan.footprint
    if fp.wings:
        wing_boxes = [box(w.x, w.y, w.x + w.width_m, w.y + w.depth_m) for w in fp.wings]
        footprint_poly = unary_union(wing_boxes)
    else:
        footprint_poly = box(fp.x, fp.y, fp.x + fp.width_m, fp.y + fp.depth_m)

    if footprint_poly.geom_type == "MultiPolygon":
        footprint_poly = max(footprint_poly.geoms, key=lambda g: g.area)
        return _ring(list(footprint_poly.exterior.coords)), "footprint union resolved to largest part"
    return _ring(list(footprint_poly.exterior.coords)), None


# --------------------------------------------------------------------------- #
#  Annotations (taxonomy)                                                      #
# --------------------------------------------------------------------------- #

def _build_annotations(
    req: SitePreviewRequest,
    plan: SitePlanModel,
    warnings: List[str],
) -> List[SiteAnnotation]:
    ann: List[SiteAnnotation] = []
    cert = plan.certificate
    sd = plan.setback_dimensions
    bbox = plan.plot_polygon.bounding_box
    bbox_w = round(bbox[2] - bbox[0], 2)
    bbox_d = round(bbox[3] - bbox[1], 2)

    ann.append(SiteAnnotation(
        id="plot_area", label="Plot area", value=plan.plot_polygon.area_sqm, unit="m²",
        status="CALCULATED",
        basis="Shoelace area of the canonicalized boundary (server-authoritative recomputation)",
    ))
    ann.append(SiteAnnotation(
        id="plot_perimeter", label="Plot perimeter", value=plan.plot_polygon.perimeter_m, unit="m",
        status="CALCULATED",
        basis="Sum of canonical boundary edge lengths",
    ))
    ann.append(SiteAnnotation(
        id="setbacks", label="Setbacks (front/rear/side)",
        value=f"{sd.get('front_m', 0)} / {sd.get('rear_m', 0)} / {sd.get('left_m', 0)} m",
        status="CALCULATED",
        basis=f"NBC 2016 Part 3 setback formula on bounding box {bbox_w} x {bbox_d} m",
    ))
    ann.append(SiteAnnotation(
        id="buildable_area", label="Buildable area", value=plan.buildable_area_sqm, unit="m²",
        status="CALCULATED",
        basis="Plot polygon inward-buffered by the setback distances (inward buffer on irregular plots)",
    ))
    ann.append(SiteAnnotation(
        id="footprint_area", label="Footprint area", value=plan.footprint.area_sqm, unit="m²",
        status="CALCULATED",
        basis=f"Program-aware inscribed footprint ({plan.footprint.topology_type}) via wing decomposition",
    ))
    ann.append(SiteAnnotation(
        id="coverage_ratio", label="Ground coverage ratio",
        value=req.ground_coverage_ratio if req.ground_coverage_ratio is not None else 0.60,
        status="CALCULATED" if req.ground_coverage_ratio is not None else "ASSUMED",
        basis=(
            "User-specified in parameters"
            if req.ground_coverage_ratio is not None
            else "Default 0.60 applied - confirm in parameters to mark CALCULATED"
        ),
    ))
    ann.append(SiteAnnotation(
        id="ground_coverage_actual", label="Ground coverage (actual)",
        value=cert.ground_coverage_actual_pct, unit="%", status="CALCULATED",
        basis=f"Footprint area / plot area vs {cert.ground_coverage_limit_pct:.0f}% limit",
    ))
    ann.append(SiteAnnotation(
        id="far_actual", label="FAR (G+1 projection)", value=cert.far_actual,
        status="CALCULATED",
        basis="Footprint area x 2 floors / plot area (two-storey assumption; limit 2.5)",
    ))

    parking = plan.parking
    if parking is not None:
        ann.append(SiteAnnotation(
            id="parking", label="Parking (provided/required ECS)",
            value=f"{parking.provided_ecs} / {parking.required_ecs}",
            status="CALCULATED",
            basis="Parking-first pipeline: ECS envelope fitted before footprint (2.5 x 5.0 m bays)",
        ))
        if parking.deficit_ecs > 0:
            ann.append(SiteAnnotation(
                id="parking_deficit", label="Parking deficit",
                value=parking.deficit_ecs, unit="ECS",
                status="RECOMMENDED",
                basis="; ".join(parking.coexistence_options) or "Reduce footprint or stack parking",
            ))
            if parking.deficit_warning and parking.deficit_warning not in warnings:
                warnings.append(parking.deficit_warning)

    frontage_idx = (
        req.frontage_edge_index
        if req.frontage_edge_index is not None
        else req.boundary.frontage_edge_index
    )
    if frontage_idx is not None:
        edge = next((e for e in plan.edges if e.edge_index == frontage_idx), None)
        ann.append(SiteAnnotation(
            id="frontage", label="Frontage edge",
            value=f"P{frontage_idx + 1}-P{(frontage_idx + 1) % len(plan.edges) + 1}"
            if edge else f"edge {frontage_idx}",
            status="VERIFIED",
            basis="Confirmed by the user on the map (frontage confirmation step)",
        ))
    else:
        ann.append(SiteAnnotation(
            id="frontage", label="Frontage edge", value="not confirmed",
            status="ASSUMED",
            basis="Front setback applied to the default south-facing edge (legacy heuristic); confirm the frontage to mark VERIFIED",
        ))

    if not plan.plot_polygon.is_regular_rectangle:
        ann.append(SiteAnnotation(
            id="design_policy", label="Design policy", value=plan.design_policy,
            status="RECOMMENDED",
            basis=plan.design_policy_rationale or "Orthogonal squaring-off policy for non-orthogonal plots",
        ))
        if plan.waste_warning_triggered:
            alt_angles = ", ".join(str(a.get("angle_deg", a.get("angle", "?"))) for a in plan.rotation_alternatives[:4])
            ann.append(SiteAnnotation(
                id="waste", label="Orthogonal waste", value=plan.waste_pct, unit="%",
                status="RECOMMENDED",
                basis=f"Waste exceeds 25% of buildable area - evaluate rotation alternatives ({alt_angles})",
            ))
            warnings.append(
                f"Orthogonal waste {plan.waste_pct:.1f}% exceeds the 25% threshold - review rotation alternatives."
            )

    return ann


# --------------------------------------------------------------------------- #
#  Public entry point                                                          #
# --------------------------------------------------------------------------- #

def compute_site_preview(req: SitePreviewRequest) -> SitePreviewResponse:
    """
    Deterministic site preview. Raises BoundaryStatutoryViolation for
    EC-01/EC-03 input violations (mapped to HTTP 422 by the endpoint).
    """
    b = req.boundary
    n = len(b.vertices)

    # Statutory gates mirror /api/analyze exactly (same messages).
    shoelace = 0.0
    perim = 0.0
    min_edge = float("inf")
    for i in range(n):
        p1 = b.vertices[i]
        p2 = b.vertices[(i + 1) % n]
        shoelace += p1.x * p2.y - p2.x * p1.y
        perim += ((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2) ** 0.5
        min_edge = min(min_edge, ((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2) ** 0.5)
    area = round(abs(shoelace) / 2.0, 2)
    if area < 36.0:
        raise BoundaryStatutoryViolation(f"Boundary area {area} m² is below the statutory minimum 36 m².")
    if min_edge < 1.0:
        raise BoundaryStatutoryViolation(f"Boundary edge {min_edge:.2f} m is below the statutory minimum 1.00 m.")

    # Operational envelope: the solve below is a 0.75 m grid scan, so an
    # unbounded span turns one request into unbounded work.
    bounds_violation = boundary_bounds_violation([(v.x, v.y) for v in b.vertices])
    if bounds_violation:
        raise BoundaryStatutoryViolation(bounds_violation)

    coverage = req.ground_coverage_ratio if req.ground_coverage_ratio is not None else 0.60
    frontage_idx = (
        req.frontage_edge_index
        if req.frontage_edge_index is not None
        else b.frontage_edge_index
    )

    vertices = [(v.x, v.y) for v in b.vertices]
    input_hash = preview_input_hash(
        vertices, b.origin_lat, b.origin_lon, coverage, frontage_idx, "T1_SINGLE_FAMILY"
    )

    cached_resp = _cache_get(input_hash)
    if cached_resp is not None:
        # Refresh volatile echo fields; geometry stays byte-identical.
        return cached_resp.model_copy(
            update={"cached": True, "request_id": cached_resp.request_id,
                    "timestamp": cached_resp.timestamp, "compute_ms": cached_resp.compute_ms}
        )

    request_id = f"BW-SP-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()

    poly_model = PlotPolygonModel(
        vertices=[(round(x, 2), round(y, 2)) for x, y in vertices],
        origin_lat=b.origin_lat,
        origin_lon=b.origin_lon,
        shape_type=b.shape_type,
        area_sqm=area,
        perimeter_m=round(perim, 2),
    )
    minx = min(x for x, _ in vertices)
    maxx = max(x for x, _ in vertices)
    miny = min(y for _, y in vertices)
    maxy = max(y for _, y in vertices)

    t0 = time.perf_counter()
    ok, plan, geo_warnings = compute_canonical_site_plan(
        plot_width_m=round(maxx - minx, 2),
        plot_depth_m=round(maxy - miny, 2),
        coverage=coverage,
        plot_polygon=poly_model,
        typology="T1_SINGLE_FAMILY",
        # Coarse alternative-orientation scan keeps the p95 < 150 ms preview
        # budget; the floorplan solve re-scans at the canonical 0.25 m grid.
        rotation_scan_grid_step=0.75,
        provenance={
            "boundary_source": b.source,
            "frontage_source": "user_confirmed" if frontage_idx is not None else None,
            "projection": PROJECTION_NOTE,
            "origin": {"lat": b.origin_lat, "lon": b.origin_lon},
        },
    )
    compute_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    warnings: List[str] = list(geo_warnings)

    if not ok or plan is None:
        resp = SitePreviewResponse(
            request_id=request_id,
            timestamp=timestamp,
            input_hash=input_hash,
            cached=False,
            compute_ms=compute_ms,
            ok=False,
            plot={"vertices": _ring(vertices), "area_sqm": area, "perimeter_m": round(perim, 2)},
            setbacks={},
            buildable={},
            footprint={},
            parking={},
            wedges=[],
            certificate={},
            frontage=None,
            annotations=[],
            provenance={
                "boundary_source": b.source,
                "projection": PROJECTION_NOTE,
                "origin": {"lat": b.origin_lat, "lon": b.origin_lon},
                "engine": ENGINE_REF,
            },
            warnings=warnings or ["Site geometry could not be synthesized for this boundary."],
        )
        return resp

    fp_ring, fp_note = _footprint_ring(plan)
    if fp_note:
        warnings.append(fp_note)

    parking_dict: Dict[str, Any] = plan.parking.model_dump() if plan.parking is not None else {}
    frontage_dict: Optional[Dict[str, Any]] = None
    if frontage_idx is not None:
        edge = next((e for e in plan.edges if e.edge_index == frontage_idx), None)
        frontage_dict = {
            "edge_index": frontage_idx,
            "edge_bearing_deg": edge.bearing_deg if edge else None,
            "edge_bearing_dms": edge.bearing_dms if edge else None,
            "edge_length_m": edge.length_m if edge else None,
            "status": "VERIFIED",
        }

    resp = SitePreviewResponse(
        request_id=request_id,
        timestamp=timestamp,
        input_hash=input_hash,
        cached=False,
        compute_ms=compute_ms,
        ok=True,
        plot={
            "vertices": _ring(list(plan.plot_polygon.vertices)),
            "area_sqm": plan.plot_polygon.area_sqm,
            "perimeter_m": plan.plot_polygon.perimeter_m,
            "shape_type": plan.plot_polygon.shape_type,
            "winding": "ccw",
            "origin": {"lat": b.origin_lat, "lon": b.origin_lon},
            "projection_note": plan.plot_polygon.projection_note,
        },
        setbacks={
            **plan.setback_dimensions,
            "nominal_setback_m": plan.nominal_setback_m,
            "reduced_setback_applied": plan.reduced_setback_applied,
        },
        buildable={
            "vertices": _ring(list(plan.buildable_polygon_coords)),
            "area_sqm": plan.buildable_area_sqm,
            "setback_band_area_sqm": plan.setback_band_area_sqm,
        },
        footprint={
            "vertices": fp_ring,
            "area_sqm": plan.footprint.area_sqm,
            "topology_type": plan.footprint.topology_type,
            "wings": [
                {
                    "wing_id": w.wing_id,
                    "label": w.label,
                    "x": w.x,
                    "y": w.y,
                    "width_m": w.width_m,
                    "depth_m": w.depth_m,
                    "area_sqm": w.area_sqm,
                }
                for w in plan.footprint.wings
            ],
            "waste_pct": plan.waste_pct,
            "rotation_alternatives": plan.rotation_alternatives,
        },
        parking=parking_dict,
        wedges=[w.model_dump() for w in plan.wedge_zones],
        certificate=plan.certificate.model_dump(),
        frontage=frontage_dict,
        annotations=_build_annotations(req, plan, warnings),
        provenance={
            "boundary_source": b.source,
            "frontage_source": "user_confirmed" if frontage_idx is not None else None,
            "projection": PROJECTION_NOTE,
            "origin": {"lat": b.origin_lat, "lon": b.origin_lon},
            "engine": ENGINE_REF,
            "geometry_source": "deterministic geometry engine - no LLM, no network in this path",
            "annotation_taxonomy": ANNOTATION_TAXONOMY,
        },
        warnings=warnings,
    )
    _cache_set(input_hash, resp)
    return resp
