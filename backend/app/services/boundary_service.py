"""boundary_service.py - one source for the captured plot area (audit F07/F22).

The captured map boundary is the ONLY ground truth for the plot area. Before
this module the analyze endpoint echoed a validated ``boundary_summary`` and
then valued the land on an area derived from ``built_up_area_sqft / floors /
coverage`` - so a report could print "3,333 sq ft (captured boundary)" for a
103,990 sq ft plot. Two numbers, both labelled as the plot, and the label was
attached to the wrong one.

Contracts:
  * ``summarize_boundary`` recomputes the shoelace area server-side and records
    the client-reported area + delta, so the summary states which number is
    authoritative and by how much the client differed.
  * ``resolve_plot_area_sqft`` is the single decision for "what is the plot
    area": captured boundary > client-supplied area > coverage derivation.
    It returns the source so every surface can label the number honestly.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from app.utils.geo_utils import polygon_is_self_intersecting

# ITM/statutory conversion; 1 sq ft = 0.09290304 m² exactly.
SQM_PER_SQFT = 0.09290304

BOUNDARY_MIN_AREA_SQM = 36.0
BOUNDARY_MIN_EDGE_M = 1.0

# Upper bounds are NOT statutory: they are the operational envelope of the
# geometry engine.  The site-preview solve scans a 0.75 m grid over the plot,
# so its cost grows with the square of the span; an unbounded span let a single
# 1e9 m boundary occupy the worker indefinitely.  2000 m matches
# the FloorPlanRequest dimension cap, and 100 ha is far beyond any single
# building project this tool assesses.
BOUNDARY_MAX_SPAN_M = 2000.0
BOUNDARY_MAX_AREA_SQM = 1_000_000.0


class BoundaryValidationError(ValueError):
    """A boundary the statutory/geometry checks reject (maps to HTTP 422)."""


def _vertices_xy(boundary: Any) -> List[Tuple[float, float]]:
    return [(float(v.x), float(v.y)) for v in boundary.vertices]


def shoelace_area_sqm(vertices: Sequence[Tuple[float, float]]) -> float:
    total = 0.0
    n = len(vertices)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def perimeter_m(vertices: Sequence[Tuple[float, float]]) -> float:
    total = 0.0
    n = len(vertices)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    return total


def summarize_boundary(boundary: Any) -> dict:
    """Validate a captured boundary and return the authoritative summary.

    Raises ``BoundaryValidationError`` for the statutory minimums and for a
    self-intersecting outline (a bow-tie's shoelace area is meaningless and
    would silently corrupt plot area, valuation and the footprint cap).
    """
    vertices = _vertices_xy(boundary)
    if len(vertices) < 3:
        raise BoundaryValidationError("Boundary needs at least 3 vertices.")

    area = round(shoelace_area_sqm(vertices), 2)
    perim = perimeter_m(vertices)
    if area < BOUNDARY_MIN_AREA_SQM:
        raise BoundaryValidationError(
            f"Boundary area {area} m² is below the statutory minimum {BOUNDARY_MIN_AREA_SQM:.0f} m²."
        )
    min_edge = min(
        ((vertices[(i + 1) % len(vertices)][0] - vertices[i][0]) ** 2
         + (vertices[(i + 1) % len(vertices)][1] - vertices[i][1]) ** 2) ** 0.5
        for i in range(len(vertices))
    )
    if min_edge < BOUNDARY_MIN_EDGE_M:
        raise BoundaryValidationError(
            f"Boundary edge {min_edge:.2f} m is below the statutory minimum {BOUNDARY_MIN_EDGE_M:.2f} m."
        )
    if polygon_is_self_intersecting(vertices):
        raise BoundaryValidationError(
            "Boundary polygon is self-intersecting (bow-tie outline). "
            "Re-capture a simple, non-crossing plot boundary."
        )
    violation = boundary_bounds_violation(vertices)
    if violation:
        raise BoundaryValidationError(violation)

    client_area = getattr(boundary, "area_sqm", None)
    area_sqft = round(area / SQM_PER_SQFT, 1)
    delta_pct: Optional[float] = None
    if client_area is not None and float(client_area) > 0:
        delta_pct = round(abs(float(client_area) - area) / area * 100.0, 3)

    return {
        "vertex_count": len(vertices),
        "area_sqm": area,
        "area_sqft": area_sqft,
        "perimeter_m": round(perim, 2),
        "shape_type": boundary.shape_type,
        "source": boundary.source,
        "frontage_edge_index": boundary.frontage_edge_index,
        "frontage_annotation": "VERIFIED" if boundary.frontage_edge_index is not None else None,
        "origin": {"lat": boundary.origin_lat, "lon": boundary.origin_lon},
        "winding": "ccw" if _signed_area(vertices) > 0 else "cw",
        "captured": True,
        "authoritative": True,
        "client_area_sqm": round(float(client_area), 2) if client_area is not None else None,
        "area_delta_pct": delta_pct,
        "provenance": {
            "boundary_source": boundary.source,
            "projection": "local tangent plane (E/N, equirectangular, cos(lat))",
            "origin": {"lat": boundary.origin_lat, "lon": boundary.origin_lon},
            "area_method": "shoelace (server-recomputed, authoritative)",
        },
    }


def boundary_bounds_violation(vertices: Sequence[Tuple[float, float]]) -> Optional[str]:
    """Return the operational-limit message for an unbounded/oversized plot.

    Shared by ``summarize_boundary`` (/api/analyze) and the site-preview solve
    so both entry points refuse the same inputs with the same wording.  Without
    this the preview's grid scan is unbounded work for an unauthenticated
    request.
    """
    if not vertices:
        return None
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    span = max(max(xs) - min(xs), max(ys) - min(ys))
    if span > BOUNDARY_MAX_SPAN_M:
        return (
            f"Boundary span {span:,.0f} m exceeds the {BOUNDARY_MAX_SPAN_M:,.0f} m "
            "operational limit for site analysis. Capture the building plot, not a "
            "regional extent."
        )
    area = shoelace_area_sqm(vertices)
    if area > BOUNDARY_MAX_AREA_SQM:
        return (
            f"Boundary area {area:,.0f} m² exceeds the {BOUNDARY_MAX_AREA_SQM:,.0f} m² "
            "operational limit for site analysis."
        )
    return None


def _signed_area(vertices: Sequence[Tuple[float, float]]) -> float:
    total = 0.0
    n = len(vertices)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def resolve_plot_area_sqft(
    *,
    boundary_area_sqm: Optional[float] = None,
    requested_plot_area_sqft: Optional[float] = None,
    built_up_area_sqft: float,
    floors: int,
    ground_coverage_ratio: float,
) -> Tuple[float, str, List[str]]:
    """Decide the plot area and name its source.

    Returns ``(area_sqft, source, warnings)`` where ``source`` is one of
    ``captured_boundary`` | ``client_plot_area`` | ``derived_from_coverage``.
    A physically impossible request (ground footprint larger than the plot) is
    surfaced, never silently accepted.
    """
    warnings: List[str] = []
    gcr = max(0.40, min(0.75, float(ground_coverage_ratio or 0.60)))
    footprint_sqft = float(built_up_area_sqft) / max(int(floors), 1)

    if boundary_area_sqm is not None and float(boundary_area_sqm) > 0:
        captured = round(float(boundary_area_sqm) / SQM_PER_SQFT, 1)
        if requested_plot_area_sqft is not None and float(requested_plot_area_sqft) > 0:
            supplied = float(requested_plot_area_sqft)
            if abs(supplied - captured) / captured > 0.01:
                warnings.append(
                    f"PLOT-AREA: the captured boundary is {captured:,.0f} sq ft but the "
                    f"request supplied {supplied:,.0f} sq ft; the captured boundary is "
                    "authoritative for valuation and for the report."
                )
        if footprint_sqft > captured + 0.5:
            warnings.append(
                f"PLOT-AREA: the ground-floor footprint ({footprint_sqft:,.0f} sq ft = "
                f"built-up / {max(int(floors), 1)} storeys) exceeds the captured plot "
                f"area ({captured:,.0f} sq ft). The built-up area and the plot area "
                "cannot both be true."
            )
        return captured, "captured_boundary", warnings

    if requested_plot_area_sqft is not None and float(requested_plot_area_sqft) >= 200.0:
        supplied = round(float(requested_plot_area_sqft), 1)
        if footprint_sqft > supplied + 0.5:
            warnings.append(
                f"PLOT-AREA: the ground-floor footprint ({footprint_sqft:,.0f} sq ft) "
                f"exceeds the supplied plot area ({supplied:,.0f} sq ft)."
            )
        return supplied, "client_plot_area", warnings

    derived = round(footprint_sqft / gcr, 1)
    return derived, "derived_from_coverage", warnings
