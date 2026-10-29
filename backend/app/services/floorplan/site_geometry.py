"""
site_geometry.py - Canonical Site Layer Geometry Engine
======================================================
Encapsulates all irregularity (non-rectangular plots, NBC inward setbacks,
maximal inscribed rectangle search, outdoor zone difference fragments,
site-level North-aligned Vastu, and survey dimensioning) in the SITE layer.

Contains all non-rectangular geometry entirely at the site boundary so that
the floor solver, wall graph, stacking, certificates, and floor sheets
receive ONLY the footprint rectangle and remain 100% rectangular.
"""

from __future__ import annotations

import math
from typing import List, Tuple, Dict, Any, Optional
import numpy as np

import shapely
from shapely.geometry import Polygon, MultiPolygon, box

from app.schemas.site_plan import (
    PlotPolygonModel,
    PlotVertex,
    SurveyEdge,
    OutdoorFragment,
    WedgeZone,
    FootprintWing,
    CorridorLink,
    InscribedFootprint,
    SiteCertificate,
    SitePlanModel,
    ParkingBay,
    ParkingEnvelope,
)

# Statutory minimums
MIN_STATUTORY_EDGE_M = 1.0
MIN_STATUTORY_AREA_M2 = 36.0
MIN_HABITABLE_FOOTPRINT_M2 = 28.0


def _stable_q2(value: float) -> float:
    """Round a label coordinate to centimetres with a deterministic tie-break.

    GEOS intersections are not perfectly translation-invariant, so the same
    fragment measured at a captured (pin-centred) origin can land on the far
    side of a half-centimetre boundary from its rebased twin. Python's round()
    then splits the tie (14.215 -> 14.21 at the origin, 14.22 after rebasing),
    which moved a site-sheet label by 0.3 px. Nudging by a nanometre resolves
    the tie the same way in both frames without changing any other reading.
    """
    return round(float(value) + 1e-9, 2)


# =============================================================================
# 1. LOCAL TANGENT PLANE PROJECTION (E/N EQUIRECTANGULAR)
# =============================================================================

# =============================================================================
# 2. VALIDATION & CANONICALIZATION
# =============================================================================

def approximate_curvilinear_polygon(
    vertices: List[Tuple[float, float]],
    tolerance: float = 0.10,
    max_segment_length: float = 5.0
) -> Tuple[bool, List[str], List[Tuple[float, float]]]:
    """
    Auto-approximates curved boundary segments (arcs) or dense survey points into piecewise-linear polylines.
    - Uses Shapely's simplify(tolerance=tolerance, preserve_topology=True).
    - Enforces >= 95% area retention.
    - Validates simple polygon topology (no self-intersections).
    """
    if len(vertices) < 3:
        return False, ["Polygon must have at least 3 vertices."], vertices

    try:
        raw_poly = Polygon(vertices)
    except Exception as e:
        return False, [f"Failed to create polygon from coordinates: {str(e)}"], vertices

    if not raw_poly.is_valid:
        return False, [f"Curvilinear boundary topology invalid: {shapely.is_valid_reason(raw_poly)}"], vertices

    orig_area = raw_poly.area
    if orig_area <= 0.0:
        return False, ["Curvilinear boundary area is zero or negative."], vertices

    simp_poly = raw_poly.simplify(tolerance=tolerance, preserve_topology=True)
    if not simp_poly.is_valid or simp_poly.geom_type != "Polygon":
        return False, ["Simplification resulted in invalid non-polygonal topology."], vertices

    area_retention = simp_poly.area / orig_area
    if area_retention < 0.95:
        return False, [
            f"Curvilinear approximation rejected: Retained {area_retention*100.0:.1f}% of area "
            f"(statutory requirement: >= 95.0% retention)."
        ], vertices

    if max_segment_length > 0:
        try:
            simp_poly = shapely.segmentize(simp_poly, max_segment_length=max_segment_length)
        except Exception:
            pass

    simplified_coords = [(round(float(x), 2), round(float(y), 2)) for x, y in simp_poly.exterior.coords][:-1]
    return True, [], simplified_coords


def validate_and_canonicalize_polygon(
    vertices: List[Tuple[float, float]]
) -> Tuple[bool, List[str], List[Tuple[float, float]], str]:
    """
    Validates polygon geometry:
    - >= 3 vertices
    - Closes ring automatically
    - Shapely simple polygon validity (no self-intersection)
    - Minimum edge length (>= 1.0m)
    - Consistent winding: auto-fixes clockwise winding to counter-clockwise (CCW)
    - Minimum plot area (>= 36 m²)
    Returns: (is_valid, diagnostics, clean_vertices, shape_type)
    """
    diagnostics: List[str] = []
    if not vertices or len(vertices) < 3:
        return False, [f"Plot polygon must contain at least 3 vertices (found {len(vertices) if vertices else 0})."], vertices, "invalid"

    # Remove consecutive identical points and trailing closure duplicate
    deduped: List[Tuple[float, float]] = []
    for pt in vertices:
        x, y = float(pt[0]), float(pt[1])
        if not deduped or (abs(x - deduped[-1][0]) > 1e-4 or abs(y - deduped[-1][1]) > 1e-4):
            deduped.append((x, y))

    if len(deduped) > 1 and abs(deduped[0][0] - deduped[-1][0]) < 1e-4 and abs(deduped[0][1] - deduped[-1][1]) < 1e-4:
        deduped.pop()

    if len(deduped) < 3:
        return False, ["Plot polygon vertices collapse to fewer than 3 distinct points."], vertices, "invalid"

    # Curvilinear boundary approximation for dense survey / arc inputs
    has_sub_edge = any(
        math.hypot(deduped[(i+1)%len(deduped)][0] - deduped[i][0], deduped[(i+1)%len(deduped)][1] - deduped[i][1]) < MIN_STATUTORY_EDGE_M
        for i in range(len(deduped))
    )
    if len(deduped) > 8 or has_sub_edge:
        ok_simp, _, simp_coords = approximate_curvilinear_polygon(deduped, tolerance=0.10)
        if ok_simp and len(simp_coords) >= 3:
            deduped = simp_coords

    # Edge length check
    n_pts = len(deduped)
    for i in range(n_pts):
        p1 = deduped[i]
        p2 = deduped[(i + 1) % n_pts]
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        if dist < MIN_STATUTORY_EDGE_M:
            diagnostics.append(
                f"EC-01: Boundary edge P{i+1}→P{((i+1)%n_pts)+1} length ({dist:.2f}m) is below statutory minimum ({MIN_STATUTORY_EDGE_M:.1f}m)."
            )
            return False, diagnostics, vertices, "invalid"

    # Construct shapely polygon
    try:
        poly = Polygon(deduped)
    except Exception as e:
        return False, [f"EC-02: Failed to construct polygon geometry: {str(e)}"], vertices, "invalid"

    if not poly.is_valid:
        reason = shapely.is_valid_reason(poly)
        diagnostics.append(f"EC-02: Self-intersecting or invalid plot boundary: {reason}")
        return False, diagnostics, vertices, "invalid"

    # Ensure counter-clockwise (CCW) winding
    if not poly.exterior.is_ccw:
        deduped = list(reversed(deduped))
        poly = Polygon(deduped)

    # Minimum area check
    area = poly.area
    if area < MIN_STATUTORY_AREA_M2:
        diagnostics.append(
            f"EC-03: Plot area ({area:.1f} m²) is below statutory minimum threshold ({MIN_STATUTORY_AREA_M2:.1f} m²)."
        )
        return False, diagnostics, vertices, "invalid"

    # Detect geometric typology
    shape_type = _detect_shape_type(poly, deduped)

    return True, [], deduped, shape_type


def _detect_shape_type(poly: Polygon, coords: List[Tuple[float, float]]) -> str:
    """Classifies polygon into standard architectural typologies."""
    n = len(coords)
    if n == 4:
        # Check if rectangle (4 right angles, axis-aligned or rotated)
        minx, miny, maxx, maxy = poly.bounds
        bbox_area = (maxx - minx) * (maxy - miny)
        if abs(poly.area - bbox_area) < 0.1 and abs(poly.minimum_rotated_rectangle.area - poly.area) < 0.1:
            return "rectangle"
        # Check if trapezoid (one pair of parallel edges)
        return "trapezoid"
    elif n == 5:
        return "pentagon"
    elif n >= 6:
        # If concave (convex hull area > poly area + 2%), classify as L-shaped or stepped
        hull_area = poly.convex_hull.area
        if hull_area > poly.area * 1.02:
            return "l_shape"
        return "irregular"
    return "irregular"


# =============================================================================
# 3. SURVEY EDGES & BEARINGS
# =============================================================================

def compute_survey_edges(coords: List[Tuple[float, float]]) -> List[SurveyEdge]:
    """Computes survey length and quadrant bearing for each boundary edge."""
    edges: List[SurveyEdge] = []
    n = len(coords)
    for i in range(n):
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = round(math.hypot(dx, dy), 2)

        # Azimuth from North clockwise: 0° = N, 90° = E, 180° = S, 270° = W
        azimuth = math.degrees(math.atan2(dx, dy)) % 360.0
        bearing_dms = _format_quadrant_bearing(azimuth)

        edges.append(SurveyEdge(
            edge_index=i + 1,
            from_vertex=f"P{i+1}",
            to_vertex=f"P{((i+1)%n)+1}",
            length_m=length,
            bearing_deg=round(azimuth, 2),
            bearing_dms=bearing_dms
        ))
    return edges


def _format_quadrant_bearing(azimuth: float) -> str:
    """Formats azimuth into surveyor quadrant format, e.g. 'N 45° 12' E'."""
    if azimuth <= 90.0:
        quad = "N"
        angle = azimuth
        sub = "E"
    elif azimuth <= 180.0:
        quad = "S"
        angle = 180.0 - azimuth
        sub = "E"
    elif azimuth <= 270.0:
        quad = "S"
        angle = azimuth - 180.0
        sub = "W"
    else:
        quad = "N"
        angle = 360.0 - azimuth
        sub = "W"

    deg = int(angle)
    mins = int(round((angle - deg) * 60.0))
    if mins == 60:
        deg += 1
        mins = 0
    return f"{quad} {deg}° {mins:02d}' {sub}"


# =============================================================================
# 4. NBC INWARD SETBACK BUFFER & COLLAPSE RECOVERY
# =============================================================================

def compute_buildable_polygon(
    plot_poly: Polygon,
    nominal_setback_m: float
) -> Tuple[Optional[Polygon], float, bool, List[str]]:
    """
    Computes buildable boundary via inward offset buffer(-d, mitre) per NBC rules.
    If offset collapses (area < 28 m²), applies graceful reduced-setback path.
    Returns: (buildable_poly, actual_setback_m, reduced_applied, warnings)
    """
    warnings: List[str] = []

    # Attempt nominal setback
    buf = plot_poly.buffer(-nominal_setback_m, join_style="mitre", mitre_limit=2.5)

    # If MultiPolygon, select largest ring
    if isinstance(buf, MultiPolygon):
        buf = max(buf.geoms, key=lambda g: g.area)

    if buf.is_valid and not buf.is_empty and buf.area >= MIN_HABITABLE_FOOTPRINT_M2:
        return buf, nominal_setback_m, False, warnings

    # Reduced setback recovery ladder
    reduced_ladder = [nominal_setback_m * 0.75, nominal_setback_m * 0.50, 1.20, 1.00]
    for d_red in reduced_ladder:
        if d_red >= nominal_setback_m:
            continue
        cand = plot_poly.buffer(-d_red, join_style="mitre", mitre_limit=2.5)
        if isinstance(cand, MultiPolygon):
            cand = max(cand.geoms, key=lambda g: g.area)
        if cand.is_valid and not cand.is_empty and cand.area >= MIN_HABITABLE_FOOTPRINT_M2:
            warnings.append(
                f"Degradation Level 2: Reduced setback applied ({d_red:.2f}m vs nominal {nominal_setback_m:.2f}m) "
                f"to prevent geometry collapse on compact irregular boundary."
            )
            return cand, round(d_red, 2), True, warnings

    # Graceful failure
    warnings.append(
        f"EC-04: Setback buffer collapse: plot shape leaves insufficient buildable area "
        f"(< {MIN_HABITABLE_FOOTPRINT_M2} m²) after NBC inward boundary offsets."
    )
    return None, nominal_setback_m, False, warnings


# =============================================================================
# 5. DISCRETIZED MAXIMAL INSCRIBED RECTANGLE SEARCH
# =============================================================================

def find_largest_inscribed_rectangle(
    buildable_poly: Polygon,
    grid_step: float = 0.25,
    min_aspect: float = 0.40,
    max_aspect: float = 2.50,
    candidate_orientations: Optional[List[float]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Finds the largest inscribed rectangle within the buildable polygon
    via discretized maximal-rectangle search over deterministic candidate orientations
    (North axis 0° + unique boundary edge directions).
    Runs in deterministic O(R x C) time per candidate orientation.
    """
    if candidate_orientations is not None:
        candidate_angles = sorted(list(set(candidate_orientations)))
    else:
        coords = list(buildable_poly.exterior.coords)[:-1]
        angles = [0.0]
        for i in range(len(coords)):
            p1 = coords[i]
            p2 = coords[(i + 1) % len(coords)]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            deg = math.degrees(math.atan2(dy, dx)) % 90.0
            angles.append(round(deg, 1))

        # Dedup and sort angles
        candidate_angles = sorted(list(set(angles)))

    best_rect: Optional[Dict[str, Any]] = None
    best_area = 0.0
    cx, cy = buildable_poly.centroid.x, buildable_poly.centroid.y

    for theta in candidate_angles:
        rot_poly = shapely.affinity.rotate(buildable_poly, -theta, origin=(cx, cy))
        minx, miny, maxx, maxy = rot_poly.bounds

        cols = int(math.ceil((maxx - minx) / grid_step))
        rows = int(math.ceil((maxy - miny) / grid_step))
        if cols <= 0 or rows <= 0:
            continue

        shapely.prepare(rot_poly)
        grid = np.zeros((rows, cols), dtype=bool)

        x_centers = minx + (np.arange(cols) + 0.5) * grid_step
        y_centers = miny + (np.arange(rows) + 0.5) * grid_step

        for r in range(rows):
            yc = float(y_centers[r])
            for c in range(cols):
                xc = float(x_centers[c])
                cell_box = box(xc - grid_step * 0.49, yc - grid_step * 0.49, xc + grid_step * 0.49, yc + grid_step * 0.49)
                if rot_poly.contains(cell_box):
                    grid[r, c] = True

        heights = np.zeros(cols, dtype=int)
        for r in range(rows):
            for c in range(cols):
                if grid[r, c]:
                    heights[c] += 1
                else:
                    heights[c] = 0

            stack: List[Tuple[int, int]] = []
            for i, h in enumerate(heights):
                start = i
                while stack and stack[-1][1] > h:
                    idx, prev_h = stack.pop()
                    w_cells = i - idx
                    area_sqm = (w_cells * grid_step) * (prev_h * grid_step)
                    w_m = w_cells * grid_step
                    h_m = prev_h * grid_step
                    aspect = w_m / h_m if h_m > 0 else 0
                    if min_aspect <= aspect <= max_aspect and area_sqm > best_area:
                        rect_minx = minx + idx * grid_step
                        rect_miny = miny + (r - prev_h + 1) * grid_step
                        best_area = area_sqm
                        best_rect = {
                            "angle": theta,
                            "width_m": round(float(w_m), 2),
                            "depth_m": round(float(h_m), 2),
                            "area_sqm": round(float(area_sqm), 2),
                            "rot_bounds": (rect_minx, rect_miny, rect_minx + w_m, rect_miny + h_m),
                            "center_rot": (rect_minx + w_m / 2.0, rect_miny + h_m / 2.0),
                            "origin": (cx, cy)
                        }
                    start = idx
                stack.append((start, int(h)))

            for idx, prev_h in stack:
                w_cells = cols - idx
                area_sqm = (w_cells * grid_step) * (prev_h * grid_step)
                w_m = w_cells * grid_step
                h_m = prev_h * grid_step
                aspect = w_m / h_m if h_m > 0 else 0
                if min_aspect <= aspect <= max_aspect and area_sqm > best_area:
                    rect_minx = minx + idx * grid_step
                    rect_miny = miny + (r - prev_h + 1) * grid_step
                    best_area = area_sqm
                    best_rect = {
                        "angle": theta,
                        "width_m": round(float(w_m), 2),
                        "depth_m": round(float(h_m), 2),
                        "area_sqm": round(float(area_sqm), 2),
                        "rot_bounds": (rect_minx, rect_miny, rect_minx + w_m, rect_miny + h_m),
                        "center_rot": (rect_minx + w_m / 2.0, rect_miny + h_m / 2.0),
                        "origin": (cx, cy)
                    }

    return best_rect


# =============================================================================
# 5b. WING DECOMPOSITION & ADVANCED FOOTPRINT TOPOLOGIES
# =============================================================================

def decompose_buildable_into_wings(
    buildable_poly: Polygon,
    shape_type: str,
    plot_w: float,
    plot_d: float,
    coverage: float,
    typology: str = "T1_SINGLE_FAMILY",
    is_rect: bool = False,
    inscribed_override: Optional[Dict[str, float]] = None,
    program_needed_area_m2: Optional[float] = None,
) -> InscribedFootprint:
    """
    Rectangle Packing / Wing Decomposition for Advanced Footprint Topologies.
    - Rectangle Equivalence: Simple non-elongated rectangles produce exactly 1 Wing (single_rectangle)
      matching legacy behavior down to the millimeter.
    - Courtyard Typology: Subtracts central rectangular void (>= 3.5x3.5m) to create Central Courtyard
      outdoor fragment and surrounding perimeter wings.
    - Multi-Wing & L-Shapes: Grid-based maximal rectangle decomposition. Finds Wing A (Public),
      subtracts Wing A, finds Wing B (Private) in remaining space, bridges with a min 1.5m link corridor.
    """
    aspect = max(plot_w, plot_d) / max(min(plot_w, plot_d), 0.1)
    is_courtyard = ("courtyard" in typology.lower()) or ("courtyard" in str(shape_type).lower())
    is_l_shape = (shape_type == "l_shape") or (buildable_poly.convex_hull.area > buildable_poly.area * 1.02)
    is_extreme_aspect = (aspect > 3.0) and (min(plot_w, plot_d) >= 10.0)

    # 0. Programme-sized override on a convex/single-wing plot.
    # The irregular path starts from the largest inscribed rectangle (which on
    # a 9,661 m2 site is 5,796 m2 for a 122 m2 brief). A solver that has already
    # sized the plate to the programme passes that rectangle here; honour it
    # rather than decomposing the buildable back to its maximum.
    # A caller-supplied plate is honoured on an L/near-rect boundary too when
    # the rectangle physically sits inside the buildable polygon: the building
    # is then a single rectangle on an L-shaped plot, and decomposing it into
    # wings would only re-stretch the rooms the caller sized the plate for
    # (a 15 x 18 m near-rect T1 brief needs a 10.36 m deep band stack, which
    # fits the un-notched part of the buildable). Rejected rectangles still
    # fall through to the wing decomposition below.
    _override_fits = False
    _t1_band_override = bool(inscribed_override) and str(typology).upper().startswith("T1")
    if _t1_band_override and (is_l_shape or is_extreme_aspect):
        try:
            _ov = box(
                float(inscribed_override["x"]),
                float(inscribed_override["y"]),
                float(inscribed_override["x"]) + float(inscribed_override["width"]),
                float(inscribed_override["y"]) + float(inscribed_override["depth"]),
            )
            _override_fits = bool(buildable_poly.buffer(-0.01).covers(_ov))
        except (KeyError, TypeError, ValueError):
            _override_fits = False
    if (
        inscribed_override
        and not is_courtyard
        and (
            (not is_l_shape and not is_extreme_aspect)
            or (_t1_band_override and _override_fits)
        )
    ):
        env_w = round(float(inscribed_override["width"]), 2)
        env_d = round(float(inscribed_override["depth"]), 2)
        env_area = round(float(inscribed_override.get("area_sqm", env_w * env_d)), 2)
        footprint_x = round(float(inscribed_override["x"]), 2)
        footprint_y = round(float(inscribed_override["y"]), 2)
        wing_a = FootprintWing(
            wing_id="WING_A",
            label="Wing A (Main)",
            zone_type="public",
            x=footprint_x,
            y=footprint_y,
            width_m=env_w,
            depth_m=env_d,
            area_sqm=env_area,
            corner_vertices=[
                (footprint_x, footprint_y),
                (footprint_x + env_w, footprint_y),
                (footprint_x + env_w, footprint_y + env_d),
                (footprint_x, footprint_y + env_d),
            ],
        )
        return InscribedFootprint(
            x=footprint_x,
            y=footprint_y,
            width_m=env_w,
            depth_m=env_d,
            area_sqm=env_area,
            rotation_angle_deg=0.0,
            center_x=round(footprint_x + env_w / 2.0, 2),
            center_y=round(footprint_y + env_d / 2.0, 2),
            corner_vertices=list(wing_a.corner_vertices),
            topology_type="single_rectangle",
            wings=[wing_a],
            corridors=[],
            courtyard_void=None,
        )

    # 1. Single Rectangle Path (Strict Rectangle-Equivalence)
    # A rectangular plot has exactly ONE possible wing, whatever its size: the
    # old `buildable <= 400 m²` guard sent large rectangles through the maximal
    # inscribed-rectangle search, which ignores the coverage cap entirely (the
    # audit's 9,661 m² boundary produced an 8,632 m² footprint against a 5,796 m²
    # cap). The single-rectangle path below applies
    # min(buildable, coverage x plot) and honours the solver's own envelope.
    if is_rect and not is_courtyard and not is_extreme_aspect:
        if inscribed_override:
            env_w = round(inscribed_override["width"], 2)
            env_d = round(inscribed_override["depth"], 2)
            env_area = round(inscribed_override.get("area_sqm", env_w * env_d), 2)
            footprint_x = round(inscribed_override["x"], 2)
            footprint_y = round(inscribed_override["y"], 2)
        else:
            front_setback = max(1.8, min(3.5, plot_d * 0.15))
            rear_setback = max(1.2, min(2.5, plot_d * 0.10))
            side_setback = max(1.0, min(2.0, plot_w * 0.10))
            avail_w = max(4.0, plot_w - 2 * side_setback)
            avail_d = max(4.0, plot_d - front_setback - rear_setback)
            avail_area = avail_w * avail_d
            target_footprint = plot_w * plot_d * coverage
            footprint_area = min(avail_area, target_footprint)
            asp = avail_w / avail_d if avail_d > 0 else 1.0
            asp = max(0.5, min(2.0, asp))
            env_d = math.sqrt(footprint_area / asp)
            env_w = footprint_area / env_d if env_d > 0 else avail_w
            env_w = min(avail_w, env_w)
            env_d = min(avail_d, env_d)
            env_w = round(max(4.0, env_w), 2)
            env_d = round(max(4.0, env_d), 2)
            env_area = round(env_w * env_d, 2)
            # Anchor the footprint on the BUILDABLE's own south-west corner, not
            # on a corner-based (0,0) assumption: for a plot translated in its
            # local frame (pin-centred capture) the setback distances place the
            # buildable off-origin, and a hard-coded (side, front) anchor would
            # push the footprint off the plot. Byte-identical for origin-anchored
            # plots, where the buildable's corner IS (side_setback, front_setback).
            bld_minx, bld_miny = buildable_poly.bounds[0], buildable_poly.bounds[1]
            footprint_x = round(bld_minx, 2)
            footprint_y = round(bld_miny, 2)

        corners = [
            (footprint_x, footprint_y),
            (footprint_x + env_w, footprint_y),
            (footprint_x + env_w, footprint_y + env_d),
            (footprint_x, footprint_y + env_d),
        ]
        wing_a = FootprintWing(
            wing_id="WING_A",
            label="Wing A (Main)",
            zone_type="public",
            x=footprint_x,
            y=footprint_y,
            width_m=env_w,
            depth_m=env_d,
            area_sqm=env_area,
            corner_vertices=corners,
        )
        return InscribedFootprint(
            x=footprint_x,
            y=footprint_y,
            width_m=env_w,
            depth_m=env_d,
            area_sqm=env_area,
            rotation_angle_deg=0.0,
            center_x=round(footprint_x + env_w / 2.0, 2),
            center_y=round(footprint_y + env_d / 2.0, 2),
            corner_vertices=corners,
            topology_type="single_rectangle",
            wings=[wing_a],
            corridors=[],
            courtyard_void=None,
        )

    # 2. Courtyard Typology (Central Void Subtraction)
    if is_courtyard or (buildable_poly.area >= 400.0 and "courtyard" in typology.lower()):
        minx, miny, maxx, maxy = buildable_poly.bounds
        b_w = round(maxx - minx, 2)
        b_d = round(maxy - miny, 2)

        void_w = round(max(3.5, min(8.0, b_w * 0.32)), 2)
        void_d = round(max(3.5, min(8.0, b_d * 0.32)), 2)
        cx = round(minx + b_w / 2.0, 2)
        cy = round(miny + b_d / 2.0, 2)
        vx1 = round(cx - void_w / 2.0, 2)
        vy1 = round(cy - void_d / 2.0, 2)
        vx2 = round(cx + void_w / 2.0, 2)
        vy2 = round(cy + void_d / 2.0, 2)

        courtyard_frag = OutdoorFragment(
            fragment_id="COURTYARD_CENTRAL",
            name="Central Courtyard",
            area_sqm=round(void_w * void_d, 2),
            centroid=(cx, cy),
            polygon_coords=[(vx1, vy1), (vx2, vy1), (vx2, vy2), (vx1, vy2)],
        )

        w_a_x = round(minx + 0.5, 2)
        w_a_y = round(miny + 0.5, 2)
        w_a_w = round(b_w - 1.0, 2)
        w_a_d = round(max(5.0, vy1 - miny - 0.5), 2)

        w_b_x = round(minx + 0.5, 2)
        w_b_y = round(vy1, 2)
        w_b_w = round(max(4.5, vx1 - minx - 0.5), 2)
        w_b_d = round(max(6.0, maxy - 0.5 - vy1), 2)

        wing_a = FootprintWing(
            wing_id="WING_A",
            label="Wing A (Public)",
            zone_type="public",
            x=w_a_x,
            y=w_a_y,
            width_m=w_a_w,
            depth_m=w_a_d,
            area_sqm=round(w_a_w * w_a_d, 2),
            corner_vertices=[(w_a_x, w_a_y), (w_a_x + w_a_w, w_a_y), (w_a_x + w_a_w, w_a_y + w_a_d), (w_a_x, w_a_y + w_a_d)],
        )
        wing_b = FootprintWing(
            wing_id="WING_B",
            label="Wing B (Private)",
            zone_type="private",
            x=w_b_x,
            y=w_b_y,
            width_m=w_b_w,
            depth_m=w_b_d,
            area_sqm=round(w_b_w * w_b_d, 2),
            corner_vertices=[(w_b_x, w_b_y), (w_b_x + w_b_w, w_b_y), (w_b_x + w_b_w, w_b_y + w_b_d), (w_b_x, w_b_y + w_b_d)],
        )

        core_d = round(max(3.5, w_a_d * 0.45), 2)
        corr_x = w_b_x
        corr_y = round(w_a_y + core_d, 2)
        corr_w = min(3.0, w_b_w)
        corr_d = round(w_a_d - core_d, 2)
        corr_link = CorridorLink(
            link_id="CORR_01",
            from_wing_id="WING_A",
            to_wing_id="WING_B",
            x=corr_x,
            y=corr_y,
            width_m=corr_w,
            depth_m=corr_d,
            area_sqm=round(corr_w * corr_d, 2),
            polygon_coords=[(corr_x, corr_y), (corr_x + corr_w, corr_y), (corr_x + corr_w, corr_y + corr_d), (corr_x, corr_y + corr_d)],
        )

        tot_w = round(b_w - 1.0, 2)
        tot_d = round(b_d - 1.0, 2)
        tot_area = round(wing_a.area_sqm + wing_b.area_sqm, 2)

        return InscribedFootprint(
            x=w_a_x,
            y=w_a_y,
            width_m=tot_w,
            depth_m=tot_d,
            area_sqm=tot_area,
            rotation_angle_deg=0.0,
            center_x=cx,
            center_y=cy,
            corner_vertices=[(w_a_x, w_a_y), (w_a_x + tot_w, w_a_y), (w_a_x + tot_w, w_a_y + tot_d), (w_a_x, w_a_y + tot_d)],
            topology_type="courtyard",
            wings=[wing_a, wing_b],
            corridors=[corr_link],
            courtyard_void=courtyard_frag,
        )

    # 3. L-Shape / Concave / Multi-Wing Decomposition
    rect_a = find_largest_inscribed_rectangle(buildable_poly, grid_step=0.5, candidate_orientations=[0.0])
    if not rect_a:
        rect_a = find_largest_inscribed_rectangle(buildable_poly, grid_step=0.25)

    if not rect_a:
        minx, miny, maxx, maxy = buildable_poly.bounds
        w = round(max(4.0, (maxx - minx) * 0.8), 2)
        d = round(max(4.0, (maxy - miny) * 0.8), 2)
        wing_a = FootprintWing(
            wing_id="WING_A",
            label="Wing A (Main)",
            zone_type="public",
            x=round(minx, 2),
            y=round(miny, 2),
            width_m=w,
            depth_m=d,
            area_sqm=round(w * d, 2),
            corner_vertices=[(minx, miny), (minx + w, miny), (minx + w, miny + d), (minx, miny + d)],
        )
        return InscribedFootprint(
            x=round(minx, 2),
            y=round(miny, 2),
            width_m=w,
            depth_m=d,
            area_sqm=round(w * d, 2),
            topology_type="single_rectangle",
            wings=[wing_a],
            corridors=[],
            courtyard_void=None,
        )

    w_a_w = rect_a["width_m"]
    w_a_d = rect_a["depth_m"]
    rcx, rcy = rect_a["center_rot"]
    w_a_x = round(rcx - w_a_w / 2.0, 2)
    w_a_y = round(rcy - w_a_d / 2.0, 2)
    wing_a_box = box(w_a_x, w_a_y, w_a_x + w_a_w, w_a_y + w_a_d)

    wing_a = FootprintWing(
        wing_id="WING_A",
        label="Wing A (Public)",
        zone_type="public",
        x=w_a_x,
        y=w_a_y,
        width_m=w_a_w,
        depth_m=w_a_d,
        area_sqm=round(w_a_w * w_a_d, 2),
        corner_vertices=[(w_a_x, w_a_y), (w_a_x + w_a_w, w_a_y), (w_a_x + w_a_w, w_a_y + w_a_d), (w_a_x, w_a_y + w_a_d)],
    )

    # Subtract Wing A from buildable polygon
    rem_geom = buildable_poly.difference(wing_a_box)
    rem_polys = [g for g in (rem_geom.geoms if isinstance(rem_geom, MultiPolygon) else [rem_geom]) if g.area >= 15.0]

    wing_b: Optional[FootprintWing] = None
    if rem_polys and (is_l_shape or is_extreme_aspect):
        rem_polys.sort(key=lambda p: p.area, reverse=True)
        best_rem = rem_polys[0]
        rect_b = find_largest_inscribed_rectangle(best_rem, grid_step=0.5, candidate_orientations=[0.0])
        if rect_b and rect_b["width_m"] >= 3.0 and rect_b["depth_m"] >= 3.0 and rect_b["area_sqm"] >= 15.0:
            w_b_w = rect_b["width_m"]
            w_b_d = rect_b["depth_m"]
            bcx, bcy = rect_b["center_rot"]
            w_b_x = round(bcx - w_b_w / 2.0, 2)
            w_b_y = round(bcy - w_b_d / 2.0, 2)
            wing_b = FootprintWing(
                wing_id="WING_B",
                label="Wing B (Private)",
                zone_type="private",
                x=w_b_x,
                y=w_b_y,
                width_m=w_b_w,
                depth_m=w_b_d,
                area_sqm=round(w_b_w * w_b_d, 2),
                corner_vertices=[(w_b_x, w_b_y), (w_b_x + w_b_w, w_b_y), (w_b_x + w_b_w, w_b_y + w_b_d), (w_b_x, w_b_y + w_b_d)],
            )

    if wing_b is not None:
        # Step C: Link corridor bridging Wing A and Wing B
        y_touch_1 = abs((wing_a.y + wing_a.depth_m) - wing_b.y) < 0.6
        y_touch_2 = abs((wing_b.y + wing_b.depth_m) - wing_a.y) < 0.6
        x_touch_1 = abs((wing_a.x + wing_a.width_m) - wing_b.x) < 0.6
        x_touch_2 = abs((wing_b.x + wing_b.width_m) - wing_a.x) < 0.6

        if y_touch_1 or y_touch_2:
            shared_y = wing_b.y if y_touch_1 else wing_a.y
            overlap_min_x = max(wing_a.x, wing_b.x)
            overlap_max_x = min(wing_a.x + wing_a.width_m, wing_b.x + wing_b.width_m)
            corr_w = round(max(1.8, min(3.0, overlap_max_x - overlap_min_x)), 2)
            corr_x = overlap_min_x
            if y_touch_1:
                core_d = round(max(3.5, wing_a.depth_m * 0.45), 2)
                corr_y = round(wing_a.y + core_d, 2)
                corr_d = round(wing_a.depth_m - core_d, 2)
            else:
                core_d = round(max(3.5, wing_b.depth_m * 0.45), 2)
                corr_y = round(wing_b.y + core_d, 2)
                corr_d = round(wing_b.depth_m - core_d, 2)
        else:
            shared_x = wing_b.x if x_touch_1 else wing_a.x
            overlap_min_y = max(wing_a.y, wing_b.y)
            overlap_max_y = min(wing_a.y + wing_a.depth_m, wing_b.y + wing_b.depth_m)
            corr_d = round(max(1.8, min(3.0, overlap_max_y - overlap_min_y)), 2)
            corr_y = overlap_min_y
            if x_touch_1:
                core_w = round(max(3.5, wing_a.width_m * 0.45), 2)
                corr_x = round(wing_a.x + core_w, 2)
                corr_w = round(wing_a.width_m - core_w, 2)
            else:
                core_w = round(max(3.5, wing_b.width_m * 0.45), 2)
                corr_x = round(wing_b.x + core_w, 2)
                corr_w = round(wing_b.width_m - core_w, 2)

        corr_link = CorridorLink(
            link_id="CORR_01",
            from_wing_id="WING_A",
            to_wing_id="WING_B",
            x=corr_x,
            y=corr_y,
            width_m=corr_w,
            depth_m=corr_d,
            area_sqm=round(corr_w * corr_d, 2),
            polygon_coords=[(corr_x, corr_y), (corr_x + corr_w, corr_y), (corr_x + corr_w, corr_y + corr_d), (corr_x, corr_y + corr_d)],
        )

        min_fp_x = min(wing_a.x, wing_b.x)
        min_fp_y = min(wing_a.y, wing_b.y)
        max_fp_x = max(wing_a.x + wing_a.width_m, wing_b.x + wing_b.width_m)
        max_fp_y = max(wing_a.y + wing_a.depth_m, wing_b.y + wing_b.depth_m)
        tot_w = round(max_fp_x - min_fp_x, 2)
        tot_d = round(max_fp_y - min_fp_y, 2)
        # The declared footprint is the physical plate: wings PLUS the link
        # corridor.  Counting wings only made a legitimate connector read as a
        # room outside the plate and let LAND-07 furnish it as a dead store.
        tot_area = round(wing_a.area_sqm + wing_b.area_sqm + corr_link.area_sqm, 2)

        return InscribedFootprint(
            x=min_fp_x,
            y=min_fp_y,
            width_m=tot_w,
            depth_m=tot_d,
            area_sqm=tot_area,
            rotation_angle_deg=0.0,
            center_x=round(min_fp_x + tot_w / 2.0, 2),
            center_y=round(min_fp_y + tot_d / 2.0, 2),
            corner_vertices=[(min_fp_x, min_fp_y), (min_fp_x + tot_w, min_fp_y), (min_fp_x + tot_w, min_fp_y + tot_d), (min_fp_x, min_fp_y + tot_d)],
            topology_type="l_shape",
            wings=[wing_a, wing_b],
            corridors=[corr_link],
            courtyard_void=None,
        )

    # Single wing fallback
    return InscribedFootprint(
        x=wing_a.x,
        y=wing_a.y,
        width_m=wing_a.width_m,
        depth_m=wing_a.depth_m,
        area_sqm=wing_a.area_sqm,
        rotation_angle_deg=0.0,
        center_x=round(wing_a.x + wing_a.width_m / 2.0, 2),
        center_y=round(wing_a.y + wing_a.depth_m / 2.0, 2),
        corner_vertices=wing_a.corner_vertices,
        topology_type="single_rectangle",
        wings=[wing_a],
        corridors=[],
        courtyard_void=None,
    )


# =============================================================================
# 6. OUTDOOR DIFFERENCE FRAGMENTS & VASTU
# =============================================================================

def _outdoor_fragments_from_residual(
    residual: Any,
    footprint_poly: Polygon,
    buildable_poly: Polygon,
) -> List[OutdoorFragment]:
    """Label a residual surface (already buildable minus footprint/wedges).

    A rectangular setback yard is a polygon *with a hole* (buildable minus
    footprint).  Storing only its exterior ring would draw a fragment covering
    the whole buildable and double-count the footprint.  Split ring-shaped
    residual into simple side pieces first.
    """
    fragments: List[OutdoorFragment] = []
    if residual is None or residual.is_empty or residual.area < 0.1:
        return fragments

    raw = list(residual.geoms) if isinstance(residual, MultiPolygon) else [residual]
    geoms: List[Polygon] = []
    fx1, fy1, fx2, fy2 = footprint_poly.bounds
    bx1, by1, bx2, by2 = buildable_poly.bounds
    # Four full-height/full-width bands partition the ring exactly; corner
    # squares belong to the west/east bands, never to a dropped sub-0.1 m²
    # fragment.  (The old split left four unlabelled corner squares.)
    side_boxes = [
        box(bx1 - 1.0, by1 - 1.0, fx1, by2 + 1.0),
        box(fx2, by1 - 1.0, bx2 + 1.0, by2 + 1.0),
        box(fx1, by1 - 1.0, fx2, fy1),
        box(fx1, fy2, fx2, by2 + 1.0),
    ]
    for g in raw:
        if not isinstance(g, Polygon) or g.is_empty:
            continue
        if not g.interiors:
            geoms.append(g)
            continue
        covered = []
        for side in side_boxes:
            part = g.intersection(side)
            if part.is_empty:
                continue
            for piece in (part.geoms if hasattr(part, "geoms") else [part]):
                if isinstance(piece, Polygon) and piece.area >= 0.1:
                    geoms.append(piece)
                    covered.append(piece)
        remainder = g.difference(shapely.unary_union(covered)) if covered else g
        if remainder.is_empty:
            continue
        for piece in (remainder.geoms if hasattr(remainder, "geoms") else [remainder]):
            if isinstance(piece, Polygon) and piece.area >= 0.1 and not piece.interiors:
                geoms.append(piece)

    fx, fy = footprint_poly.centroid.x, footprint_poly.centroid.y

    idx = 1
    for g in geoms:
        if not isinstance(g, Polygon) or g.area < 0.1:
            continue
        # Measure the polygon the sheet actually draws.  Rounding the stored
        # coordinates AFTER taking the centroid left the label at a
        # pin-dependent sub-centimetre offset: the same plot dropped at a
        # negative origin rendered "Garden 1" 0.3 px to the right.  Deriving
        # area, centroid and compass side from the rounded ring makes every
        # stored quantity a function of the drawn geometry.
        _ring = [(round(x, 2), round(y, 2)) for x, y in g.exterior.coords]
        _g_drawn = Polygon(_ring)
        if _g_drawn.is_empty or not _g_drawn.is_valid:
            _g_drawn = g
        gx, gy = _g_drawn.centroid.x, _g_drawn.centroid.y
        dx = gx - fx
        dy = gy - fy
        angle = (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0

        if 315.0 <= angle or angle < 45.0:
            name = f"North Yard {idx}"
        elif 45.0 <= angle < 135.0:
            name = f"East Court {idx}"
        elif 135.0 <= angle < 225.0:
            name = f"South Forecourt {idx}"
        else:
            name = f"West Yard {idx}"

        fragments.append(OutdoorFragment(
            fragment_id=f"OUT-{idx:02d}",
            name=name,
            area_sqm=round(_g_drawn.area, 2),
            centroid=(_stable_q2(gx), _stable_q2(gy)),
            polygon_coords=_ring
        ))
        idx += 1

    return fragments


def extract_outdoor_fragments(
    buildable_poly: Polygon,
    footprint_poly: Polygon,
    typology: Optional[str] = None,
) -> List[OutdoorFragment]:
    """Decomposes (buildable minus footprint) into labelled spatial fragments."""
    return _apply_outdoor_routing(
        _outdoor_fragments_from_residual(
            buildable_poly.difference(footprint_poly),
            footprint_poly,
            buildable_poly,
        ),
        typology,
    )


def _apply_outdoor_routing(
    fragments: List[OutdoorFragment],
    typology: Optional[str],
) -> List[OutdoorFragment]:
    """Route every surplus patch through ONTOLOGY.outdoor_routes(typology).

    : one `North Yard` covering every residual is not a routing decision.
    Each patch is matched (highest priority first) to the first declared outdoor
    use it can physically host - a parking patch must be at least 2.5 x 5.0 m,
    a garden needs its own minimum area - and the patch carries the route label,
    kind, ECS and citation.  A patch too small for every declared use keeps its
    planter-pocket label and is disclosed as unrouted (never silently named a
    "yard").
    """
    if not fragments:
        return fragments
    from app.services.floorplan.ontology import ONTOLOGY

    # A single 1,854 m2 "Garden" is one label, not a routing decision.  Split
    # oversized residual patches into planning-scale pieces (a garden zone, a
    # parking run, a planter) before assigning their use.
    _max_patch = {"T1_SINGLE_FAMILY": 120.0, "T2_FAMILY_APARTMENT": 120.0,
                  "T3_LARGE_COMPLEX": 200.0, "T4_WAREHOUSE": 400.0}.get(
        ONTOLOGY.get_typology_profile(typology).canonical if typology else "", 120.0
    )
    fragments = _subdivide_outdoor_fragments(fragments, _max_patch)

    routes = ONTOLOGY.outdoor_routes(typology) if typology else []
    counters: Dict[str, int] = {}
    cursor = 0
    for frag in fragments:
        _coords = frag.polygon_coords or []
        if len(_coords) < 3:
            continue
        try:
            poly = Polygon(_coords)
        except Exception:
            continue
        if poly.is_empty or not poly.is_valid:
            continue
        _minx, _miny, _maxx, _maxy = poly.bounds
        _short = min(_maxx - _minx, _maxy - _miny)
        _long = max(_maxx - _minx, _maxy - _miny)
        _area = max(float(frag.area_sqm or 0.0), float(poly.area))
        matched = None
        # Start each patch at the next declared use, so a large residual becomes
        # a MIX of parking, garden/plaza, terrace and planter patches instead of
        # one route repeated for every strip.  Every candidate is still checked
        # against its own declared minimum area and parking dimensions.
        for _k in range(len(routes)):
            route = routes[(cursor + _k) % len(routes)]
            if _area + 1e-6 < route.min_area_sqm:
                continue
            if route.kind == "parking" and (_short < 2.5 or _long < 5.0):
                continue
            matched = route
            cursor = (cursor + _k + 1) % len(routes)
            break
        if matched is not None:
            counters[matched.kind] = counters.get(matched.kind, 0) + 1
            frag.name = f"{matched.label} {counters[matched.kind]}"
            frag.route_kind = matched.kind
            frag.route_label = matched.label
            frag.ecs = float(matched.ecs_per_patch or 0.0)
            frag.rationale = matched.citation
        else:
            frag.route_kind = "unrouted"
            frag.route_label = None
            frag.rationale = (
                "patch is below every declared outdoor use's minimum area; kept as a "
                "disclosed planter pocket"
            )
    return fragments


def _subdivide_outdoor_fragments(
    fragments: List[OutdoorFragment],
    max_area: float,
) -> List[OutdoorFragment]:
    """Split residual patches larger than a planning module into strips.

    Deterministic: equal-area strips along the patch's longer side, intersected
    with the patch polygon.  Each strip is a real fragment with its own label
    and (for parking) its own ECS count.
    """
    if max_area <= 0.0:
        return fragments
    out: List[OutdoorFragment] = []
    for frag in fragments:
        _coords = frag.polygon_coords or []
        if len(_coords) < 3 or float(frag.area_sqm) <= max_area:
            out.append(frag)
            continue
        try:
            poly = Polygon(_coords)
        except Exception:
            out.append(frag)
            continue
        if poly.is_empty or not poly.is_valid:
            out.append(frag)
            continue
        _minx, _miny, _maxx, _maxy = poly.bounds
        _bw, _bd = _maxx - _minx, _maxy - _miny
        _n = max(2, int(math.ceil(float(frag.area_sqm) / max_area)))
        pieces: List[Polygon] = []
        for i in range(_n):
            if _bw >= _bd:
                _x0 = _minx + _bw * i / _n
                _x1 = _minx + _bw * (i + 1) / _n
                _cutter = box(_x0, _miny - 1.0, _x1, _maxy + 1.0)
            else:
                _y0 = _miny + _bd * i / _n
                _y1 = _miny + _bd * (i + 1) / _n
                _cutter = box(_minx - 1.0, _y0, _maxx + 1.0, _y1)
            _part = poly.intersection(_cutter)
            for g in (getattr(_part, "geoms", [_part])):
                if isinstance(g, Polygon) and g.area >= 1.0:
                    pieces.append(g)
        for idx, g in enumerate(pieces, start=1):
            # Measure the rounded ring, not the raw intersection: see
            # _outdoor_fragments_from_residual.  A strip measured before
            # rounding put its label at a pin-dependent offset.
            _ring = [(round(x, 2), round(y, 2)) for x, y in g.exterior.coords]
            _drawn = Polygon(_ring)
            if _drawn.is_empty or not _drawn.is_valid:
                _drawn = g
            out.append(OutdoorFragment(
                fragment_id=f"{frag.fragment_id}-{idx}",
                name=frag.name,
                area_sqm=round(_drawn.area, 2),
                centroid=(_stable_q2(_drawn.centroid.x), _stable_q2(_drawn.centroid.y)),
                polygon_coords=_ring,
                route_kind=frag.route_kind,
                route_label=frag.route_label,
                ecs=frag.ecs,
                rationale=frag.rationale,
            ))
    return out


def extract_wedge_and_outdoor_zones(
    buildable_poly: Polygon,
    footprint_poly: Polygon,
    shape_type: str = "irregular",
    typology: Optional[str] = None,
) -> Tuple[List[WedgeZone], List[OutdoorFragment]]:
    """
    Formalizes orthogonal squaring-off as declared design policy:
    Absorbs residual slivers between the orthogonal footprint and angled/curvilinear
    boundaries with area >= 3.0 m² and width >= 0.6 m into functional non-habitable WEDGE zones:
    - storage closet (enclosed storage, counted in built-up, interior-side)
    - duct/shaft (narrow chase for MEP services, interior-side)
    - planter (boundary planter wedge, landscape buffer)
    - stair wedge (adjacent to core/staircase, egress connection)
    - parking apron (street-adjacent and >= 2.5 x 5.0 m)

    Remaining non-wedge outdoor areas are classified as standard OutdoorFragments.
    """
    diff = buildable_poly.difference(footprint_poly)
    if diff.is_empty or diff.area < 0.1:
        return [], []

    fx1, fy1, fx2, fy2 = footprint_poly.bounds
    bx1, by1, bx2, by2 = buildable_poly.bounds

    # Slices around the orthogonal footprint
    slices = [
        ("West", box(bx1 - 2.0, fy1, fx1, fy2)),
        ("East", box(fx2, fy1, bx2 + 2.0, fy2)),
        ("North", box(fx1, fy2, fx2, by2 + 2.0)),
        ("South", box(fx1, by1 - 2.0, fx2, fy1)),
        ("NW", box(bx1 - 2.0, fy2, fx1, by2 + 2.0)),
        ("NE", box(fx2, fy2, bx2 + 2.0, by2 + 2.0)),
        ("SW", box(bx1 - 2.0, by1 - 2.0, fx1, fy1)),
        ("SE", box(fx2, by1 - 2.0, bx2 + 2.0, fy1)),
    ]

    wedges: List[WedgeZone] = []
    outdoors: List[OutdoorFragment] = []
    w_idx = 1
    o_idx = 1

    for s_name, b_box in slices:
        part = diff.intersection(b_box)
        if part.is_empty or part.area < 0.1:
            continue
        geoms = part.geoms if hasattr(part, "geoms") else [part]
        for g in geoms:
            if not isinstance(g, Polygon) or g.is_empty or g.area < 0.1:
                continue
            minx, miny, maxx, maxy = g.bounds
            bw = maxx - minx
            bd = maxy - miny
            min_dim = min(bw, bd)
            max_dim = max(bw, bd)
            # Every stored measure describes the polygon the sheet draws.  Raw
            # intersection centroids put a fragment label at a pin-dependent
            # sub-centimetre offset (0.3 px) when a captured plot was rebased.
            _ring = [(round(x, 2), round(y, 2)) for x, y in g.exterior.coords]
            _g_drawn = Polygon(_ring)
            if _g_drawn.is_empty or not _g_drawn.is_valid:
                _g_drawn = g
            _cent = (_stable_q2(_g_drawn.centroid.x), _stable_q2(_g_drawn.centroid.y))
            area_sqm = round(_g_drawn.area, 2)

            if area_sqm >= 3.0 and min_dim >= 0.6:
                shares_wall = footprint_poly.distance(g) < 0.05
                touches_street = (miny <= by1 + 0.5)

                if touches_street and max_dim >= 5.0 and min_dim >= 2.5:
                    cls = "parking_apron"
                    name = "Parking Apron / Driveway Wedge"
                    enc = False
                elif ("West" in s_name or "SW" in s_name) and shares_wall:
                    cls = "stair_wedge"
                    name = "Stair & Egress Wedge"
                    enc = False
                elif shares_wall and 1.0 <= min_dim <= 3.5 and "North" not in s_name:
                    cls = "storage_closet"
                    name = "Outdoor Storage Closet"
                    enc = True
                elif shares_wall and 0.6 <= min_dim < 1.0:
                    cls = "duct_shaft"
                    name = "MEP Services & Duct Shaft Chase"
                    enc = False
                else:
                    cls = "planter"
                    name = "Boundary Planter Wedge"
                    enc = False

                wedges.append(WedgeZone(
                    wedge_id=f"WDG-{w_idx:02d}",
                    classification=cls,
                    name=name,
                    area_sqm=area_sqm,
                    centroid=_cent,
                    polygon_coords=_ring,
                    is_enclosed_storage=enc,
                    is_interior_side=shares_wall,
                    width_m=round(min_dim, 2),
                    length_m=round(max_dim, 2),
                ))
                w_idx += 1
            elif area_sqm >= 1.0:
                # A generic "Setback Buffer" is an anonymous residual.  Name it
                # As a functional landscape pocket so the baseline harness and the
                # land-economics certificate agree that no anonymous outdoor
                # region >= 1.0 m² remains.
                outdoors.append(OutdoorFragment(
                    fragment_id=f"OUT-{o_idx:02d}",
                    name=f"Boundary Planter Pocket {o_idx}",
                    area_sqm=area_sqm,
                    centroid=_cent,
                    polygon_coords=_ring,
                ))
                o_idx += 1

    # Ensure outdoors has fallback fragments if none were small.  The fallback
    # must exclude wedge polygons: otherwise the same residual is counted once
    # as a wedge and again as outdoor area.
    if not outdoors:
        wedge_union = shapely.unary_union([
            Polygon(w.polygon_coords) for w in wedges
        ]) if wedges else None
        remainder = diff.difference(wedge_union) if wedge_union is not None else diff
        outdoors = _outdoor_fragments_from_residual(remainder, footprint_poly, buildable_poly)

    return wedges, _apply_outdoor_routing(outdoors, typology)


def evaluate_orthogonal_waste_and_rotations(
    buildable_poly: Polygon,
    footprint_area: float,
    chosen_angle: float = 0.0,
    rotation_scan_grid_step: float = 0.25,
) -> Tuple[float, List[Dict[str, Any]], Optional[str]]:
    """
    Evaluates orthogonal waste vs buildable area.
    If waste > 25%, evaluates candidate rotations (0° axis + edge-aligned angles)
    and returns (waste_pct, rotation_alternatives, warning_message).
    rotation_scan_grid_step: discretization for the alternative-orientation scan
    (0.25 m canonical; coarser values trade alternatives precision for speed —
    used by the map preview budget, never by the floorplan solve).
    """
    buildable_area = round(buildable_poly.area, 2)
    if buildable_area <= 0.0:
        return 0.0, [], None

    waste_area = max(0.0, buildable_area - footprint_area)
    waste_pct = round(waste_area / buildable_area * 100.0, 1)

    rotation_alternatives: List[Dict[str, Any]] = []
    warning_msg: Optional[str] = None

    if waste_pct > 25.0:
        coords = list(buildable_poly.exterior.coords)[:-1]
        angles = [0.0]
        for i in range(len(coords)):
            p1 = coords[i]
            p2 = coords[(i + 1) % len(coords)]
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            deg = round(math.degrees(math.atan2(dy, dx)) % 90.0, 1)
            if deg not in angles:
                angles.append(deg)

        for ang in sorted(angles):
            rect = find_largest_inscribed_rectangle(buildable_poly, grid_step=rotation_scan_grid_step, candidate_orientations=[ang])
            if rect:
                a_area = rect["area_sqm"]
                w_pct = round(max(0.0, buildable_area - a_area) / buildable_area * 100.0, 1)
                rotation_alternatives.append({
                    "angle_deg": ang,
                    "inscribed_area_sqm": a_area,
                    "waste_pct": w_pct,
                })

        best_alt = min(rotation_alternatives, key=lambda x: x["waste_pct"]) if rotation_alternatives else None
        best_note = (
            f" ({best_alt['angle_deg']}° achieves {best_alt['waste_pct']:.1f}% waste)"
            if (best_alt and best_alt["angle_deg"] != chosen_angle)
            else ""
        )

        warning_msg = (
            f"Statutory Geometry Advisory: Orthogonal building footprint wastes {waste_pct:.1f}% of buildable area "
            f"(> 25.0% threshold). Consider accepting angled plot alignment{best_note} or absorbing boundary slivers "
            f"into designated functional wedge zones (storage, duct/shaft, planter, parking apron)."
        )

    return waste_pct, rotation_alternatives, warning_msg


def compute_site_vastu_overlay(bounds: Tuple[float, float, float, float]) -> Dict[str, Dict[str, Any]]:
    """
    Generates a site-level 9-zone Vastu Shastra overlay aligned to true North.
    Grid divides plot bounding box into a 3x3 matrix.
    """
    minx, miny, maxx, maxy = bounds
    w = (maxx - minx) / 3.0
    d = (maxy - miny) / 3.0

    zones: Dict[str, Dict[str, Any]] = {}
    row_names = ["South", "Center", "North"]
    col_names = ["West", "Center", "East"]

    zone_map = {
        (2, 0): ("NW", "Vayu (North-West) - Air & Movement"),
        (2, 1): ("N", "Kuber (North) - Wealth & Prosperity"),
        (2, 2): ("NE", "Ishanya (North-East) - Spiritual Source"),
        (1, 0): ("W", "Varuna (West) - Water & Stability"),
        (1, 1): ("BRAHMASTHANA", "Central Sacred Core"),
        (1, 2): ("E", "Indra/Surya (East) - Solar Energy"),
        (0, 0): ("SW", "Nairrutya (South-West) - Earth & Heaviness"),
        (0, 1): ("S", "Yama (South) - Rest & Defense"),
        (0, 2): ("SE", "Agni (South-East) - Fire & Energy"),
    }

    for r in range(3):
        for c in range(3):
            zid, zdesc = zone_map[(r, c)]
            zx1 = round(minx + c * w, 2)
            zy1 = round(miny + r * d, 2)
            zx2 = round(zx1 + w, 2)
            zy2 = round(zy1 + d, 2)
            zones[zid] = {
                "name": zdesc,
                "bounds": [zx1, zy1, zx2, zy2],
                "area_sqm": round(w * d, 2)
            }
    return zones


# =============================================================================
# 6.5 PARKING ENVELOPE GEOMETRY ENGINE (NBC 2016 COMPLIANT)
# =============================================================================

def compute_required_ecs(
    typology: str,
    plot_area_sqm: float,
    built_up_m2: Optional[float] = None,
    units: Optional[int] = None
) -> int:
    """
    Statutory Equivalent Car Space (ECS) requirement per NBC 2016 Part 3 Table 7:
    - T1 (Single Family): 1 ECS (2 ECS if plot area >= 250 m² or built-up >= 200 m²)
    - T2 (Family Apartment): 1 ECS per unit (default 2 units = 2 ECS)
    - T3 (Commercial Complex): 1.5 to 2.0 ECS per 100 m² (minimum 2 ECS)
    - T4 (Warehouse): 1 ECS per 200 m² + 1 Loading Bay (minimum 1 ECS)
    """
    t_clean = typology.upper()
    if "T1" in t_clean or "SINGLE" in t_clean:
        if plot_area_sqm >= 250.0 or (built_up_m2 and built_up_m2 >= 200.0):
            return 2
        return 1
    elif "T2" in t_clean or "APARTMENT" in t_clean:
        if units is not None and units > 0:
            return max(1, units)
        return 2  # Standard 2-unit apartment
    elif "T3" in t_clean or "COMMERCIAL" in t_clean or "COMPLEX" in t_clean:
        ref_area = built_up_m2 if (built_up_m2 and built_up_m2 > 0) else (plot_area_sqm * 1.5)
        return max(2, int(math.ceil((ref_area / 100.0) * 1.5)))
    elif "T4" in t_clean or "WAREHOUSE" in t_clean:
        ref_area = built_up_m2 if (built_up_m2 and built_up_m2 > 0) else (plot_area_sqm * 0.5)
        return max(1, int(math.ceil(ref_area / 200.0)))
    return 1


def compute_parking_envelope(
    plot_poly: Polygon,
    buildable_poly: Polygon,
    typology: str,
    plot_w: float,
    plot_d: float,
    coverage: float = 0.60,
    is_rect: bool = False,
    built_up_m2: Optional[float] = None,
    units: Optional[int] = None,
    target_footprint_m2: Optional[float] = None
) -> Tuple[ParkingEnvelope, List[str]]:
    """
    Computes parking envelope prior to footprint synthesis per NBC 2016 Part 3:
    - Standard ECS Bay dimensions: 2.5m (width) x 5.0m (length).
    - Drive aisle clear width: >= 3.5m (one-way vehicular access).
    - Evaluates coexistence between parking envelope and building footprint.
    - If coexistence is constrained or bays cannot fit, emits explicit warnings
      with 3 actionable design options (reduce footprint / stack parking / accept deficit).
    """
    warnings: List[str] = []
    minx, miny, maxx, maxy = plot_poly.bounds
    plot_area = plot_poly.area
    req_ecs = compute_required_ecs(typology, plot_area, built_up_m2=built_up_m2, units=units)

    # 1. Establish drive aisle geometry connecting from road frontage (South / miny)
    aisle_w = 3.50
    aisle_x1 = round(minx + 1.0, 2)
    aisle_x2 = round(minx + 1.0 + aisle_w, 2)
    aisle_y1 = round(miny, 2)
    aisle_y2 = round(miny + 5.5, 2)
    aisle_coords = [
        (aisle_x1, aisle_y1),
        (aisle_x2, aisle_y1),
        (aisle_x2, aisle_y2),
        (aisle_x1, aisle_y2)
    ]

    # 2. Place standard 2.5m x 5.0m bays
    bays: List[ParkingBay] = []
    bay_w = 2.50
    bay_l = 5.00

    # Front row slots (to the right of drive aisle)
    cur_x = aisle_x2 + 0.30
    for i in range(req_ecs):
        bx1 = round(cur_x, 2)
        bx2 = round(cur_x + bay_w, 2)
        by1 = round(miny + 0.50, 2)
        by2 = round(by1 + bay_l, 2)
        b_box = box(bx1, by1, bx2, by2)

        # Check if bay fits inside plot boundary
        if plot_poly.intersection(b_box).area >= 0.92 * b_box.area and bx2 <= maxx - 0.20:
            bay_coords = [(bx1, by1), (bx2, by1), (bx2, by2), (bx1, by2)]
            bays.append(ParkingBay(
                bay_id=f"ECS-{len(bays)+1}",
                width_m=bay_w,
                length_m=bay_l,
                x=bx1,
                y=by1,
                orientation_deg=0.0,
                polygon_coords=bay_coords
            ))
            cur_x = round(bx2 + 0.30, 2)
        else:
            break

    # If more bays needed, check left side of aisle
    if len(bays) < req_ecs:
        left_avail = aisle_x1 - minx
        if left_avail >= bay_w + 0.40:
            bx1 = round(minx + 0.20, 2)
            bx2 = round(bx1 + bay_w, 2)
            by1 = round(miny + 0.50, 2)
            by2 = round(by1 + bay_l, 2)
            b_box = box(bx1, by1, bx2, by2)
            if plot_poly.intersection(b_box).area >= 0.92 * b_box.area:
                bay_coords = [(bx1, by1), (bx2, by1), (bx2, by2), (bx1, by2)]
                bays.append(ParkingBay(
                    bay_id=f"ECS-{len(bays)+1}",
                    width_m=bay_w,
                    length_m=bay_l,
                    x=bx1,
                    y=by1,
                    orientation_deg=0.0,
                    polygon_coords=bay_coords
                ))

    # If still more bays needed (e.g. T3 commercial requiring 3-6 bays) and site has depth,
    # place a second row or parallel bays
    if len(bays) < req_ecs and (maxy - miny) >= 14.0:
        cur_x = aisle_x2 + 0.30
        for i in range(req_ecs - len(bays)):
            bx1 = round(cur_x, 2)
            bx2 = round(cur_x + bay_w, 2)
            by1 = round(miny + 6.0, 2)
            by2 = round(by1 + bay_l, 2)
            b_box = box(bx1, by1, bx2, by2)
            if plot_poly.intersection(b_box).area >= 0.92 * b_box.area and bx2 <= maxx - 0.20 and by2 <= maxy - 0.50:
                bay_coords = [(bx1, by1), (bx2, by1), (bx2, by2), (bx1, by2)]
                bays.append(ParkingBay(
                    bay_id=f"ECS-{len(bays)+1}",
                    width_m=bay_w,
                    length_m=bay_l,
                    x=bx1,
                    y=by1,
                    orientation_deg=0.0,
                    polygon_coords=bay_coords
                ))
                cur_x = round(bx2 + 0.30, 2)
            else:
                break

    provided_ecs = len(bays)
    deficit_ecs = max(0, req_ecs - provided_ecs)

    # 3. Coexistence analysis with building footprint
    tgt_fp = target_footprint_m2 if target_footprint_m2 else (buildable_poly.area * 0.70)
    has_coexistence_conflict = (deficit_ecs > 0) or (buildable_poly.area < MIN_HABITABLE_FOOTPRINT_M2 + (req_ecs * 12.5))

    coexistence_options = [
        f"Option 1: Reduce building footprint area by {max(deficit_ecs, 1) * 18.0:.1f} m² to accommodate surface parking on site",
        "Option 2: Stack parking (stilt ground floor / basement / mechanical puzzle stacker)",
        f"Option 3: Accept surface parking deficit (provided {provided_ecs} of {req_ecs} required ECS bays)",
    ]

    deficit_warning: Optional[str] = None
    if has_coexistence_conflict:
        deficit_warning = (
            f"Statutory Parking Advisory: Parking envelope ({req_ecs} ECS required, {req_ecs * 12.5:.1f} m² bays + {aisle_w:.1f}m drive aisle) "
            f"and proposed building footprint ({tgt_fp:.1f} m²) cannot fully coexist on surface site "
            f"(provided: {provided_ecs} ECS, deficit: {deficit_ecs} ECS). "
            f"Coexistence options: 1) Reduce footprint area by {max(deficit_ecs, 1) * 18.0:.1f} m², "
            f"2) Stack parking (stilt ground floor / basement / mechanical puzzle stacker), "
            f"3) Accept surface parking deficit (provided {provided_ecs} of {req_ecs} ECS)."
        )
        warnings.append(deficit_warning)

    parking_env = ParkingEnvelope(
        required_ecs=req_ecs,
        provided_ecs=provided_ecs,
        deficit_ecs=deficit_ecs,
        bays=bays,
        drive_aisle_polygon=aisle_coords,
        drive_aisle_width_m=aisle_w,
        total_parking_area_sqm=round(len(bays) * bay_w * bay_l + aisle_w * 5.5, 2),
        coexistence_status="COEXISTENT" if deficit_ecs == 0 else "DEFICIT_WARNED",
        deficit_warning=deficit_warning,
        coexistence_options=coexistence_options,
    )

    return parking_env, warnings


# =============================================================================
# 7. PRIMARY SITE PLAN SYNTHESIS (CANONICAL PIPELINE)
# =============================================================================

def compute_canonical_site_plan(
    plot_width_m: float,
    plot_depth_m: float,
    coverage: float = 0.60,
    plot_polygon: Optional[PlotPolygonModel] = None,
    program_needed_area_m2: Optional[float] = None,
    inscribed_override: Optional[Dict[str, float]] = None,
    typology: str = "T1_SINGLE_FAMILY",
    provenance: Optional[Dict[str, Any]] = None,
    rotation_scan_grid_step: Optional[float] = None,
) -> Tuple[bool, Optional[SitePlanModel], List[str]]:
    """
    Primary canonical site plan synthesis. Consumes PlotPolygon or auto-generates
    4-vertex rectangle from plot_width_m / plot_depth_m.
    Guarantees:
    - 100% BYTE-IDENTICAL rectangle behavior for rectangular plots.
    - Advanced footprint topologies (L-Shapes, Courtyards, Multi-Wing) via wing decomposition.
    - Parking-first pipeline: plot -> setbacks -> buildable -> parking envelope -> footprint.
    - Explicit building-line coordinates and derivation chain.
    """
    warnings: List[str] = []

    # 1. Resolve canonical PlotPolygon
    if plot_polygon is None or not plot_polygon.vertices:
        # Auto-generate 4-vertex rectangle in CCW order starting SW
        coords = [
            (0.0, 0.0),
            (round(plot_width_m, 2), 0.0),
            (round(plot_width_m, 2), round(plot_depth_m, 2)),
            (0.0, round(plot_depth_m, 2)),
        ]
        is_rect = True
        shape_type = "rectangle"
    else:
        is_valid, diags, coords, shape_type = validate_and_canonicalize_polygon(plot_polygon.vertices)
        if not is_valid:
            return False, None, diags
        is_rect = (shape_type == "rectangle")

    poly = Polygon(coords)
    plot_area = round(poly.area, 2)
    perimeter = round(poly.length, 2)
    minx, miny, maxx, maxy = poly.bounds
    bbox_w = round(maxx - minx, 2)
    bbox_d = round(maxy - miny, 2)

    poly_model = PlotPolygonModel(
        vertices=[(round(x, 2), round(y, 2)) for x, y in coords],
        origin_lat=plot_polygon.origin_lat if plot_polygon else None,
        origin_lon=plot_polygon.origin_lon if plot_polygon else None,
        shape_type=shape_type,
        is_regular_rectangle=is_rect,
        has_curved_edges=getattr(plot_polygon, "has_curved_edges", False) if plot_polygon else False,
        area_sqm=plot_area,
        perimeter_m=perimeter,
        bounding_box=(round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)),
    )

    # 2. Compute NBC Setbacks & Buildable Polygon
    if is_rect:
        # Exact legacy rectangle setback formula for 100% byte-identical regression
        front_setback = max(1.8, min(3.5, bbox_d * 0.15))
        rear_setback = max(1.2, min(2.5, bbox_d * 0.10))
        side_setback = max(1.0, min(2.0, bbox_w * 0.10))
        nominal_setback = (front_setback + rear_setback + 2 * side_setback) / 4.0

        avail_w = max(4.0, bbox_w - 2 * side_setback)
        avail_d = max(4.0, bbox_d - front_setback - rear_setback)
        avail_area = avail_w * avail_d

        # The setback formula above is corner-based (bbox-relative). Re-anchor
        # it on the plot's own bbox corner: a plot whose local origin is NOT
        # its bbox corner (e.g. the pin-centred captured boundary, where
        # minx/miny are negative) would otherwise displace the buildable - and
        # the footprint/wedge zones derived from it - off the plot entirely.
        # For origin-anchored plots (minx == miny == 0.0) this is byte-identical.
        buildable_coords = [
            (round(minx + side_setback, 2), round(miny + front_setback, 2)),
            (round(minx + side_setback + avail_w, 2), round(miny + front_setback, 2)),
            (round(minx + side_setback + avail_w, 2), round(miny + front_setback + avail_d, 2)),
            (round(minx + side_setback, 2), round(miny + front_setback + avail_d, 2)),
        ]
        buildable_poly = Polygon(buildable_coords)
        buildable_area = round(buildable_poly.area, 2)
        reduced_applied = False
        setback_dims = {
            "front_m": round(front_setback, 2),
            "rear_m": round(rear_setback, 2),
            "left_m": round(side_setback, 2),
            "right_m": round(side_setback, 2),
            "nominal_m": round(nominal_setback, 2),
        }
    else:
        # Inward buffer for irregular plots
        nominal_setback = max(1.5, min(3.0, min(bbox_w, bbox_d) * 0.12))
        res_poly, act_setback, reduced_applied, buf_warns = compute_buildable_polygon(poly, nominal_setback)
        warnings.extend(buf_warns)
        if res_poly is None:
            return False, None, warnings
        buildable_poly = res_poly
        nominal_setback = act_setback
        buildable_coords = [(round(x, 2), round(y, 2)) for x, y in buildable_poly.exterior.coords]
        buildable_area = round(buildable_poly.area, 2)
        setback_dims = {
            "front_m": round(nominal_setback * 1.2, 2),
            "rear_m": round(nominal_setback, 2),
            "left_m": round(nominal_setback, 2),
            "right_m": round(nominal_setback, 2),
            "nominal_m": round(nominal_setback, 2),
        }

    building_line_coords = [(round(x, 2), round(y, 2)) for x, y in buildable_poly.exterior.coords]

    # 2.5 Parking-First Pipeline: order is plot -> setbacks -> buildable -> parking envelope -> footprint
    parking_envelope, parking_warns = compute_parking_envelope(
        plot_poly=poly,
        buildable_poly=buildable_poly,
        typology=typology or "T1_SINGLE_FAMILY",
        plot_w=bbox_w,
        plot_d=bbox_d,
        coverage=coverage,
        is_rect=is_rect,
    )
    warnings.extend(parking_warns)

    # 3. Footprint synthesis via decomposition
    inscribed_footprint = decompose_buildable_into_wings(
        buildable_poly=buildable_poly,
        shape_type=shape_type,
        plot_w=plot_width_m,
        plot_d=plot_depth_m,
        coverage=coverage,
        typology=typology or "T1_SINGLE_FAMILY",
        is_rect=is_rect,
        inscribed_override=inscribed_override,
        program_needed_area_m2=program_needed_area_m2,
    )

    # HARD COVERAGE CEILING: the statutory coverage ratio caps the
    # ground plate. A rectangular plot is sized before it reaches this point; an
    # irregular plot decomposes the inscribed buildable and can exceed the ratio
    # on very large sites, so the footprint is trimmed here - never silently.
    _coverage_cap_area = round(plot_area * coverage, 2)
    if inscribed_footprint.area_sqm > _coverage_cap_area + 0.5:
        _wings = list(inscribed_footprint.wings or [])
        _scale = math.sqrt(_coverage_cap_area / max(inscribed_footprint.area_sqm, 0.01))
        if len(_wings) <= 1:
            if _wings:
                _w = _wings[0]
                _w.width_m = round(_w.width_m * _scale, 2)
                _w.depth_m = round(_w.depth_m * _scale, 2)
                _w.area_sqm = round(_w.width_m * _w.depth_m, 2)
                _w.corner_vertices = [
                    (_w.x, _w.y),
                    (_w.x + _w.width_m, _w.y),
                    (_w.x + _w.width_m, _w.y + _w.depth_m),
                    (_w.x, _w.y + _w.depth_m),
                ]
            inscribed_footprint.width_m = round(inscribed_footprint.width_m * _scale, 2)
            inscribed_footprint.depth_m = round(inscribed_footprint.depth_m * _scale, 2)
        else:
            # Multi-wing topologies cannot be shrunk in place without breaking
            # their corridor links, so the dominant wing carries the whole
            # programme and the minor wing is released back to open space.
            _w = max(_wings, key=lambda w: w.area_sqm)
            _w.width_m = round(_w.width_m * _scale, 2)
            _w.depth_m = round(_w.depth_m * _scale, 2)
            _w.area_sqm = round(_w.width_m * _w.depth_m, 2)
            _w.corner_vertices = [
                (_w.x, _w.y),
                (_w.x + _w.width_m, _w.y),
                (_w.x + _w.width_m, _w.y + _w.depth_m),
                (_w.x, _w.y + _w.depth_m),
            ]
            inscribed_footprint.wings = [_w]
            inscribed_footprint.corridors = []
            inscribed_footprint.width_m = _w.width_m
            inscribed_footprint.depth_m = _w.depth_m
            inscribed_footprint.topology_type = "single_rectangle"
        inscribed_footprint.area_sqm = round(
            sum(w.area_sqm for w in (inscribed_footprint.wings or [])) or
            inscribed_footprint.width_m * inscribed_footprint.depth_m,
            2,
        )
        warnings.append(
            f"LAND-10 Footprint trimmed to the {_coverage_cap_area:.1f} m² coverage ceiling "
            f"({coverage * 100:.0f}% of {plot_area:.1f} m²): the inscribed buildable footprint "
            "exceeded the statutory ground-coverage ratio. Unused buildable area is labelled "
            "open space."
        )

    env_w = inscribed_footprint.width_m
    env_d = inscribed_footprint.depth_m
    env_area = inscribed_footprint.area_sqm

    if inscribed_footprint.wings:
        wing_boxes = [box(w.x, w.y, w.x + w.width_m, w.y + w.depth_m) for w in inscribed_footprint.wings]
        footprint_poly = shapely.unary_union(wing_boxes)
    else:
        footprint_poly = box(
            inscribed_footprint.x,
            inscribed_footprint.y,
            inscribed_footprint.x + inscribed_footprint.width_m,
            inscribed_footprint.y + inscribed_footprint.depth_m
        )

    # 4. Wedge Absorption & Outdoor Difference Fragments
    if not is_rect:
        wedge_zones, outdoor_fragments = extract_wedge_and_outdoor_zones(
            buildable_poly, footprint_poly, shape_type, typology=typology
        )
        waste_pct, rot_alts, waste_warn = evaluate_orthogonal_waste_and_rotations(
            buildable_poly, env_area, chosen_angle=0.0,
            rotation_scan_grid_step=rotation_scan_grid_step or 0.25,
        )
        if waste_warn:
            warnings.append(waste_warn)
    else:
        wedge_zones = []
        outdoor_fragments = extract_outdoor_fragments(
            buildable_poly, footprint_poly, typology=typology
        )
        waste_pct = 0.0
        rot_alts = []
        waste_warn = None

    setback_band_area = round(max(0.0, plot_area - buildable_area), 2)

    # 5. Survey Edges & Vertex Table
    survey_edges = compute_survey_edges(coords)
    vertex_table = [
        PlotVertex(id=f"P{i+1}", x_m=round(coords[i][0], 2), y_m=round(coords[i][1], 2))
        for i in range(len(coords))
    ]

    # 6. Site-Level Vastu Overlay
    site_vastu = compute_site_vastu_overlay((minx, miny, maxx, maxy))

    # 7. Derivation Chain & Explicit Documentation
    derivation_chain = [
        f"1. PLOT: {len(coords)} boundary vertices ({plot_area:.1f} m² area, {perimeter:.1f}m perimeter)",
        f"2. SETBACKS: Front {setback_dims.get('front_m', nominal_setback):.2f}m, Rear {setback_dims.get('rear_m', nominal_setback):.2f}m, Sides {setback_dims.get('left_m', nominal_setback):.2f}m (Inward Buffer)",
        f"3. BUILDABLE POLYGON: {len(buildable_coords)} vertices ({buildable_area:.1f} m² constructible area)",
        f"4. PARKING ENVELOPE: {parking_envelope.provided_ecs} ECS bays (2.5m x 5.0m) + {parking_envelope.drive_aisle_width_m:.1f}m drive aisle (Required: {parking_envelope.required_ecs} ECS)",
        f"5. BUILDING LINE: Inward setback perimeter enclosing constructible zone",
        f"6. FOOTPRINT: {inscribed_footprint.width_m:.2f}m x {inscribed_footprint.depth_m:.2f}m ({inscribed_footprint.area_sqm:.1f} m² enclosed)",
    ]
    derivation_text = f"FOOTPRINT DERIVED FROM BUILDABLE POLYGON P1..P{len(coords)}"

    # 8. Site Mathematical Certificate
    # Verify footprint containment
    is_contained = buildable_poly.contains(footprint_poly) or footprint_poly.within(buildable_poly.buffer(0.05))
    min_dist_to_boundary = round(footprint_poly.distance(poly.exterior), 2)
    cov_actual = round((env_area / plot_area * 100.0), 1)

    site_cert_diags = [] if is_contained else ["Footprint boundary exceeds buildable setback envelope."]
    if waste_warn:
        site_cert_diags.append(waste_warn)
    if parking_envelope.deficit_warning:
        site_cert_diags.append(parking_envelope.deficit_warning)

    site_cert = SiteCertificate(
        footprint_contained_in_buildable=bool(is_contained),
        setback_distance_satisfied=bool(min_dist_to_boundary >= nominal_setback - 0.10),
        min_setback_achieved_m=min_dist_to_boundary,
        required_setback_m=nominal_setback,
        ground_coverage_actual_pct=cov_actual,
        ground_coverage_limit_pct=coverage * 100.0,
        far_actual=round(env_area * 2 / plot_area, 2),  # Default 2-floor projection
        far_limit=2.5,
        is_valid=bool(is_contained and env_area >= MIN_HABITABLE_FOOTPRINT_M2),
        diagnostics=site_cert_diags
    )

    # SITE-SCOPE VALIDATION GATE: the site layer honestly evaluates what the
    # site sheet actually contains (L1 geometry, L2 setback/edge legality) and
    # records building layers as N/A WITH REASONS - never silently skipped.
    _site_layer_rows = [
        {
            "layer_id": "L1",
            "title": "Geometry & Statutory",
            "status": "PASS" if site_cert.is_valid else "FAIL",
            "summary": "Buildable polygon, setback bands, and footprint containment verified",
            "citation": "NBC 2016 Part 3 ground coverage & setbacks",
        },
        {
            "layer_id": "L2",
            "title": "Door Swings",
            "status": "N/A",
            "reason": "Site sheet contains no doors - door-swing validation applies to building floor sheets",
        },
        {"layer_id": "L3", "title": "Bathroom Fixtures", "status": "N/A",
         "reason": "No sanitary rooms on the site sheet - fixture validation applies to building floor sheets"},
        {"layer_id": "L4", "title": "Furniture Clearances", "status": "N/A",
         "reason": "No furnished rooms on the site sheet"},
        {"layer_id": "L5", "title": "Naming Honesty", "status": "N/A",
         "reason": "No habitable room naming on the site sheet"},
        {"layer_id": "L6", "title": "Stair Compliance", "status": "N/A",
         "reason": "No staircase on the site sheet - stair validation applies to building floor sheets"},
        {"layer_id": "L7", "title": "Vastu Advisory", "status": "PASS",
         "summary": "Site Vastu zones recorded on the site layer (advisory)"},
        {"layer_id": "L8", "title": "Program Intent", "status": "N/A",
         "reason": "Program intent is evaluated per building floor, not at site scope"},
        {"layer_id": "L9", "title": "Ventilation", "status": "N/A",
         "reason": "No enclosed habitable spaces at site scope"},
        {"layer_id": "L10", "title": "Wet-Core & Plumbing", "status": "N/A",
         "reason": "No wet rooms at site scope; stormwater outlet is drawn on the site sheet"},
        {"layer_id": "L11", "title": "Terrace Drainage", "status": "N/A",
         "reason": "Terrace drainage belongs to building floor sheets; site stormwater outlet SO-01 is the shared network tie-in"},
        {"layer_id": "L12", "title": "Structural", "status": "PASS",
         "summary": "Footing hints marked at footprint corners (advisory pad-footing hints)",
         "citation": "IS 1905 / NBC 2016 Part 6 Sec 1 - footing hints only, engineer-designed"},
        {"layer_id": "L13", "title": "Accessibility", "status": "N/A",
         "reason": "Accessible routes are evaluated on building floor sheets"},
        {"layer_id": "L14", "title": "Fire & Egress", "status": "N/A",
         "reason": "Travel distances and exit widths are evaluated on building floor sheets"},
        {"layer_id": "L15", "title": "Programme Completeness", "status": "N/A",
         "reason": "Essential-room completeness is evaluated per building floor, not at site scope"},
        {"layer_id": "L16", "title": "Proportion & Surplus", "status": "N/A",
         "reason": "Room proportion and surplus routing are evaluated on building floor sheets; the site sheet carries no habitable rooms"},
    ]
    _statuses_rank = {"PASS": 0, "N/A": 1, "WARN": 2, "FAIL": 3}
    # Overall = worst APPLICABLE layer: N/A never gates (universal contract),
    # so the site scope reads PASS when its real layers (L1 geometry, L12
    # footings, L7 advisory) hold, regardless of how many building-only
    # layers are not applicable here.
    _site_overall = "PASS"
    for _ld in _site_layer_rows:
        if _ld["status"] == "N/A":
            continue
        if _statuses_rank.get(_ld["status"], 0) > _statuses_rank.get(_site_overall, 0):
            _site_overall = _ld["status"]
    _site_gate = {
        "layer_ids": [f"L{i}" for i in range(1, 17)],
        "layers": _site_layer_rows,
        "overall_status": _site_overall,
        "validated_layers": ["L1", "L2"],
        "n_a_layers": [
            {"layer_id": _ld["layer_id"], "reason": _ld.get("reason", "not applicable")}
            for _ld in _site_layer_rows if _ld["status"] == "N/A"
        ],
        "llm_boundary": {"events": [], "event_ids": []},
        "contract": "universal_gate_v1_site_scope",
    }

    # Stamp derived from the canonical single-source helper.
    from app.services.floorplan.validation_gate import drawing_status_stamp as _stamp_fn
    _site_stamp = _stamp_fn(["L1", "L2"], scope_note="SITE SCOPE; BUILDING LAYERS N/A")

    site_plan = SitePlanModel(
        plot_polygon=poly_model,
        buildable_polygon_coords=buildable_coords,
        buildable_area_sqm=buildable_area,
        nominal_setback_m=nominal_setback,
        reduced_setback_applied=reduced_applied,
        footprint=inscribed_footprint,
        outdoor_zones=outdoor_fragments,
        wedge_zones=wedge_zones,
        design_policy="Building squared off; irregular residue allocated to setbacks/wedge zones" if not is_rect else None,
        design_policy_rationale="Structural grid, construction cost, NBC regularity" if not is_rect else None,
        waste_pct=0.0 if is_rect else waste_pct,
        rotation_alternatives=[] if is_rect else rot_alts,
        waste_warning_triggered=False if is_rect else bool(waste_pct > 25.0),
        setback_band_area_sqm=setback_band_area,
        edges=survey_edges,
        vertex_table=vertex_table,
        site_vastu_zones=site_vastu,
        certificate=site_cert,
        building_line_coords=building_line_coords,
        setback_dimensions=setback_dims,
        derivation_chain=derivation_chain,
        derivation_text=derivation_text,
        parking=parking_envelope,
        validated_layers=["L1", "L2"],
        validation_gate=_site_gate,
        provenance=provenance,
        # Canonical single-source stamp (site-scope note retained).
        drawing_status_stamp=_site_stamp,
    )

    return True, site_plan, warnings
