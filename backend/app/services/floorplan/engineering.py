"""
engineering.py - Engineering Layer Engines 
=====================================================
Deterministic, geometry-only audits backing the universal validation gate
layers L9-L14 (engineering extensions). Every function is pure: it consumes
solved floor models / shaft specs and returns JSON-serializable audit dicts.
No LLM, no network, no randomness.

Layer constants carry explicit code citations (NBC 2016) so the certificate
and sheet tables are self-justifying.
"""

import math
from typing import Any, Dict, List, Optional, Tuple

from app.services.floorplan.wall_graph import (
    NBC_2016_HABITABLE_VENT_RATIO,
    NBC_2016_SANITARY_VENT_RATIO,
    NBC_2016_MIN_SANITARY_VENT_AREA_SQM,
    NBC_2016_MIN_CORRIDOR_WIDTH_T1_M,
    NBC_2016_MIN_CORRIDOR_WIDTH_T2_M,
    NBC_2016_MIN_CORRIDOR_WIDTH_T4_M,
)

# =============================================================================
# CONSTANTS (with citations)
# =============================================================================

# --- L9 Ventilation ----------------------------------------------------------
# Sanitary/kitchen shaft-vented opening per NBC 2016 Part 3 Cl 12.2.5.1.
VENT_WINDOW_HEIGHT_HABITABLE_M: float = 1.20   # assumed operable sash height
VENT_WINDOW_HEIGHT_SANITARY_M: float = 0.60    # high sill ventilator height
VENT_EDGE_JAMB_LOSS_M: float = 0.20            # masonry jamb deduction per edge
VENT_MIN_WINDOW_AREA_SQM: float = 0.30         # practical minimum ventilator
VENT_CITATION: str = "NBC 2016 Part 8 Sec 1 Cl 4.2 (habitable 12.5%) / Part 3 Cl 12.2.5.1 (sanitary 10%, min 0.37 m2)"

# --- L10 Wet-core & Plumbing --------------------------------------------------
WET_CORE_MAX_RUN_M: float = 6.0      # max horizontal soil/waste run without shaft drop (Time-Saver Standards / IS 1172 practice)
WET_CORE_CITATION: str = "NBC 2016 Part 9 Plumbing Sec 3 / IS 1172 - wet stacks grouped; short horizontal soil runs"
WET_ID_KEYWORDS: Tuple[str, ...] = ("bath", "toilet", "wc", "kitchen", "wash", "sanitary", "utility", "worker_amenity", "pantry")
DRY_ZONE_CATEGORIES = ("circulation", "terrace", "industrial_bay")

# --- L11 Terrace Drainage ------------------------------------------------------
TERRACE_SLOPE_RATIO: str = "1:100"           # NBC 2016 Part 3 Cl 10.2.1 / CPWD spec
TERRACE_SLOPE_CITATION: str = "NBC 2016 Part 3 Cl 10.2.1 terrace drainage slope >= 1:100 to rain water outlets"
TERRACE_PARAPET_MIN_H_M: float = 1.00        # NBC 2016 Part 3 Cl 10.1 parapet >= 1.0m
TERRACE_WP_BAND_M: float = 0.30              # waterproofing upturn band at parapet junction (CPWD practice)
SITE_STORM_OUTLET_ID: str = "SO-01"          # site stormwater outlet - the single network tie-in

# --- L12 Structural -------------------------------------------------------------
# Practical clear-span ceilings before intermediate columns are forced, per typology.
TYP_MAX_SPAN_M: Dict[str, float] = {
    "T1_SINGLE_FAMILY": 4.5,
    "T2_FAMILY_APARTMENT": 4.5,
    "T3_LARGE_COMPLEX": 6.0,
    "T4_WAREHOUSE": 6.0,
}
STRUCTURAL_SPAN_CITATION: str = "NBC 2016 Part 6 Sec 2 (Structural Design); RCC beam span/depth practice for residential spans"
STRUCTURAL_LOAD_PATH_CITATION: str = "NBC 2016 Part 6 Sec 2 Cl 6.1 load-path continuity; walls must bear on walls/beams below"
STRUCTURAL_COLUMN_SIZE_M: float = 0.30
STRUCTURAL_SUPPORT_TOL_M: float = 0.15       # point-to-wall support tolerance
STRUCTURAL_CONTINUITY_TOL: float = 0.95      # >= 95% of upper wall length must land on support below
FOOTING_HINT_CITATION: str = "IS 1905 / NBC 2016 Part 6 Sec 1 - isolated pad footing hints at column bases"

# --- L13 Accessibility ----------------------------------------------------------
ACCESS_CORRIDOR_MIN_M: Dict[str, float] = {
    "T1_SINGLE_FAMILY": NBC_2016_MIN_CORRIDOR_WIDTH_T1_M,       # 1.00
    "T2_FAMILY_APARTMENT": NBC_2016_MIN_CORRIDOR_WIDTH_T2_M,    # 1.25
    "T3_LARGE_COMPLEX": NBC_2016_MIN_CORRIDOR_WIDTH_T4_M,       # 1.50
    "T4_WAREHOUSE": NBC_2016_MIN_CORRIDOR_WIDTH_T4_M,           # 1.50
}
ACCESS_DOOR_MIN_INTERIOR_M: float = 0.90     # clear leaf width
ACCESS_DOOR_MIN_ENTRANCE_M: float = 1.00
ACCESS_MANEUVER_CIRCLE_M: float = 1.50       # wheelchair 1500mm turning circle
ACCESS_THRESHOLD_NOTE: str = "ENTRY THRESHOLD: <= 15mm upstand, ramped approach max 1:12 where level change exceeds 15mm"
ACCESS_CITATION: str = "NBC 2016 Part 3 Cl 8 (Accessibility) / Annex B: 1500mm turning circle, corridor clear widths, door clear widths"
# Public/commercial typologies carry full applicability; private dwellings get
# advisory-level checks (WARN, not FAIL) per Part 3 Cl 8 scope.
ACCESS_FULL_APPLICABILITY: Tuple[str, ...] = ("T3_LARGE_COMPLEX", "T4_WAREHOUSE")

# --- L14 Fire & Egress -----------------------------------------------------------
FIRE_EGRESS_CITATION: str = "NBC 2016 Part 4 Cl 4.4 (travel distance <= 30m non-sprinklered) / Part 3 Cl 12.18 (exit widths)"
FIRE_OCCUPANT_PER_M_EXIT: float = 50.0       # persons served per 1.0m clear exit width (Part 4 Table 4A approximation)
BEDROOM_EGRESS_KEYWORD: str = "bed"

_EG_EPS = 1e-9


# =============================================================================
# SHARED GEOMETRY HELPERS (also used by drawing_ir for service-layer drawing)
# =============================================================================

def point_segment_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance from point (px,py) to segment (x1,y1)-(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    seg_len2 = dx * dx + dy * dy
    if seg_len2 <= _EG_EPS:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def segment_intersects_box(seg: Tuple[Tuple[float, float], Tuple[float, float]],
                           box: Tuple[float, float, float, float],
                           shrink: float = 0.02) -> bool:
    """True if the segment passes through the interior of the box (x0,y0,x1,y1).
    Endpoints are shrunk inward so mere adjacency (touching a corner/edge) does not count."""
    (x0, y0, x1, y1) = box
    if x1 - x0 <= 2 * shrink or y1 - y0 <= 2 * shrink:
        return False
    (ax, ay), (bx, by) = seg
    # Shrink segment endpoints toward each other by `shrink` to avoid endpoint-touch hits.
    seg_len = math.hypot(bx - ax, by - ay)
    if seg_len <= 2 * shrink:
        return False
    ux, uy = (bx - ax) / seg_len, (by - ay) / seg_len
    ax2, ay2 = ax + ux * shrink, ay + uy * shrink
    bx2, by2 = bx - ux * shrink, by - uy * shrink

    # Liang-Barsky clip of the shrunk segment to the shrunk box.
    bx0, by0, bx1, by1 = x0 + shrink, y0 + shrink, x1 - shrink, y1 - shrink
    dx, dy = bx2 - ax2, by2 - ay2
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax2 - bx0), (dx, bx1 - ax2), (-dy, ay2 - by0), (dy, by1 - ay2)):
        if abs(p) <= _EG_EPS:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return False
            t0 = max(t0, t)
        else:
            if t < t0:
                return False
            t1 = min(t1, t)
    return t0 <= t1


def largest_free_square_m(room: Tuple[float, float, float, float],
                          obstacles: List[Tuple[float, float, float, float]],
                          side_m: float, step_m: float = 0.10) -> Optional[Tuple[float, float]]:
    """Finds a placement (x, y) for a `side_m` square inside `room` avoiding `obstacles`.
    Deterministic bottom-left-first scan. Returns None when no placement exists."""
    rx, ry, rw, rd = room
    if rw + _EG_EPS < side_m or rd + _EG_EPS < side_m:
        return None

    def _free(x: float, y: float) -> bool:
        for ox, oy, ow, od in obstacles:
            if x < ox + ow - _EG_EPS and x + side_m > ox + _EG_EPS and \
               y < oy + od - _EG_EPS and y + side_m > oy + _EG_EPS:
                return False
        return True

    ny = int(math.floor((rd - side_m) / step_m))
    nx = int(math.floor((rw - side_m) / step_m))
    for j in range(ny + 1):
        y = round(ry + j * step_m, 3)
        for i in range(nx + 1):
            x = round(rx + i * step_m, 3)
            if _free(x, y):
                return (x, y)
    return None


def is_wet_room(room_id: str, zone_category: str = "", is_core: bool = False) -> bool:
    """A room is 'wet' when its identity or service classification demands plumbing."""
    if is_core:
        return False
    rid = (room_id or "").lower()
    if zone_category == "service" or "bath" in rid or "toilet" in rid or "wc" in rid:
        return True
    return any(k in rid for k in WET_ID_KEYWORDS)


def _rect(rectish: Any) -> Tuple[float, float, float, float]:
    return (
        float(getattr(rectish, "x", 0.0) or 0.0),
        float(getattr(rectish, "y", 0.0) or 0.0),
        float(getattr(rectish, "width_m", 0.0) or 0.0),
        float(getattr(rectish, "depth_m", 0.0) or 0.0),
    )


# =============================================================================
# L9 - VENTILATION REGISTRY
# =============================================================================

def _is_sanitary_identity(room_id: str) -> bool:
    rid = (room_id or "").lower()
    return any(k in rid for k in ("bath", "toilet", "wc", "wash", "sanitary", "utility"))


def compute_ventilation_registry(floors: List[Any], duct_shafts: List[Any]) -> Dict[str, Any]:
    """
    Per wet-room ventilation compliance record (NBC 2016 Part 8 Sec 1 Cl 4.2 /
    Part 3 Cl 12.2.5.1):
    - external opening area >= coded ratio of floor area -> 'external_opening'
    - else room served by a plumbing_wet shaft -> 'shaft_vent'
    - else flagged for mechanical ventilation -> WARN
    """
    records: List[Dict[str, Any]] = []

    def _shaft_serves(rid: str, shaft: Any) -> bool:
        srv = getattr(shaft, "servicing_rooms", None)
        if srv is None and isinstance(shaft, dict):
            srv = shaft.get("servicing_rooms", [])
        for s in (srv or []):
            k = str(s).lower()
            if rid.lower() == k or rid.lower().endswith(k) or k in rid.lower():
                return True
        return False

    for fl in floors:
        env = getattr(fl, "envelope", None) or {}
        ew = float(env.get("width", 0.0) or 0.0)
        ed = float(env.get("depth", 0.0) or 0.0)
        windows_by_room: Dict[str, List[Any]] = {}
        for w in (getattr(fl, "windows", None) or []):
            windows_by_room.setdefault(getattr(w, "room_id", None) or w.get("room_id", ""), []).append(w)

        for r in (getattr(fl, "rooms", None) or []):
            rid = getattr(r, "room_id", "")
            # Resolved identity is the single source: a dry archive deck in a
            # service zone must not be treated as a wet room merely because of
            # its zone category.  Fall back to the legacy predicate only when
            # the identity object is absent.
            identity = getattr(r, "identity", None)
            if identity is not None:
                is_wet = bool(getattr(identity, "is_wet", False))
            else:
                is_wet = is_wet_room(
                    rid, getattr(r, "zone_category", ""), getattr(r, "is_vertical_core", False)
                )
            if not is_wet:
                continue
            area = float(getattr(r, "area_sqm", 0.0) or 0.0)
            sanitary = _is_sanitary_identity(rid)
            if sanitary:
                req_ratio = NBC_2016_SANITARY_VENT_RATIO
                req_area = max(NBC_2016_MIN_SANITARY_VENT_AREA_SQM, area * req_ratio)
            else:
                req_ratio = NBC_2016_HABITABLE_VENT_RATIO
                req_area = area * req_ratio

            # (a) Real windows on this room
            wins = windows_by_room.get(rid, [])
            open_area = 0.0
            window_area = 0.0
            if wins:
                h = VENT_WINDOW_HEIGHT_SANITARY_M if sanitary else VENT_WINDOW_HEIGHT_HABITABLE_M
                for w in wins:
                    ww = float(getattr(w, "width_m", 0.0) or (w.get("width_m", 0.0) if isinstance(w, dict) else 0.0))
                    open_area += max(0.0, ww) * h
                window_area = open_area

            # DAYLIGHT / EXTERIOR-OPENING RULE (habitable kitchens).
            # A shaft is a mechanical exhaust path, not daylight: NBC 2016
            # Part 3 Cl 12.2.3 (and this repository's own unit_kitchen spec:
            # daylight_req=True, requires_exterior_wall=True) requires a
            # kitchen to open onto the outer air.  Only a MODELLED window on an
            # exterior edge counts; the exterior-edge heuristic below is a
            # planning aid for other wet rooms and cannot prove a kitchen
            # window that was never drawn.
            space_id = str(getattr(r, "space_type_id", None) or "").lower()
            room_name = str(getattr(r, "room_name", "") or "").lower()
            is_kitchen = space_id == "unit_kitchen" or "kitchen" in space_id or "kitchen" in room_name
            daylight_required = bool(is_kitchen)
            daylight_ok = (not daylight_required) or (window_area + _EG_EPS >= req_area)
            daylight_mode = (
                None
                if not daylight_required
                else ("external_window" if daylight_ok else "no_daylight")
            )

            # (b) Exterior-edge heuristic when no modeled window exists
            ext_edge = None
            if open_area <= _EG_EPS:
                gaps = {
                    "west": r.x,
                    "east": ew - (r.x + r.width_m),
                    "south": r.y,
                    "north": ed - (r.y + r.depth_m),
                }
                for edge, gap in gaps.items():
                    if gap <= _EG_EPS:
                        ext_edge = edge
                        break
                if ext_edge:
                    edge_len = r.depth_m if ext_edge in ("west", "east") else r.width_m
                    open_area = max(0.0, edge_len - VENT_EDGE_JAMB_LOSS_M) * (
                        VENT_WINDOW_HEIGHT_SANITARY_M if sanitary else VENT_WINDOW_HEIGHT_HABITABLE_M
                    )
            open_area = max(open_area, 0.0)

            shaft = next((s for s in (duct_shafts or []) if _shaft_serves(rid, s)), None)
            if not daylight_ok:
                mode, status = "no_daylight", "fail"
            elif open_area >= req_area - 1e-6:
                mode, status = "external_opening", "pass"
            elif shaft is not None:
                mode, status = "shaft_vent", "pass"
            else:
                mode, status = "mechanical_flagged", "warn"

            records.append({
                "room_id": rid,
                "room_name": getattr(r, "room_name", rid),
                "floor_index": getattr(fl, "floor_index", 0),
                "area_sqm": round(area, 2),
                "required_vent_area_sqm": round(req_area, 3),
                "provided_open_area_sqm": round(open_area, 3),
                "ratio_required": req_ratio,
                "external_edge": ext_edge,
                "shaft_id": (getattr(shaft, "shaft_id", None) or (shaft or {}).get("shaft_id") if shaft else None),
                "daylight_required": daylight_required,
                "daylight_mode": daylight_mode,
                "modelled_window_area_sqm": round(window_area, 3),
                "daylight_ok": bool(daylight_ok),
                "mode": mode,
                "status": status,
                "citation": VENT_CITATION,
            })

    warn_count = sum(1 for rec in records if rec["status"] == "warn")
    daylight_rooms = [rec for rec in records if rec.get("daylight_required")]
    daylight_failures = [rec for rec in daylight_rooms if not rec.get("daylight_ok")]
    daylight_findings = [
        f"{rec['room_id']} (F{rec['floor_index']}): kitchen has no exterior window "
        f"({rec['modelled_window_area_sqm']:.2f} m2 of the {rec['required_vent_area_sqm']:.2f} m2 "
        "daylight opening required); a shaft is not daylight (NBC 2016 Part 3 Cl 12.2.3)"
        for rec in daylight_failures
    ]
    if daylight_failures:
        status = "fail"
    elif warn_count:
        status = "warn"
    else:
        status = "pass"
    return {
        "records": records,
        "total_rooms": len(records),
        "external_opening_count": sum(1 for rec in records if rec["mode"] == "external_opening"),
        "shaft_vent_count": sum(1 for rec in records if rec["mode"] == "shaft_vent"),
        "mechanical_flagged_count": warn_count,
        "daylight_required_count": len(daylight_rooms),
        "daylight_failure_count": len(daylight_failures),
        "daylight_findings": daylight_findings,
        "status": status,
        "citation": VENT_CITATION,
    }


# =============================================================================
# L10 - WET-CORE & PLUMBING AUDIT
# =============================================================================

def compute_wet_core_audit(floors: List[Any], duct_shafts: List[Any]) -> Dict[str, Any]:
    """
    Verifies wet rooms are grouped on shared plumbing walls / shafts:
    - each wet room is associated with a plumbing_wet shaft (or within WET_CORE_MAX_RUN_M),
    - the straight soil/waste run from room to shaft never crosses a dry room,
    - shafts are defined once globally (vertical alignment by construction).
    """
    findings: List[str] = []
    crossings: List[Dict[str, Any]] = []
    associations: List[Dict[str, Any]] = []
    served_count = 0

    def _shaft_rect(s: Any) -> Tuple[float, float, float, float]:
        return (
            float(getattr(s, "x", 0.0) or (s.get("x", 0.0) if isinstance(s, dict) else 0.0)),
            float(getattr(s, "y", 0.0) or (s.get("y", 0.0) if isinstance(s, dict) else 0.0)),
            float(getattr(s, "width_m", 0.0) or (s.get("width_m", 0.0) if isinstance(s, dict) else 0.0)),
            float(getattr(s, "depth_m", 0.0) or (s.get("depth_m", 0.0) if isinstance(s, dict) else 0.0)),
        )

    def _shaft_id(s: Any) -> str:
        return str(getattr(s, "shaft_id", None) or (s.get("shaft_id", "?") if isinstance(s, dict) else "?"))

    def _shaft_serving(s: Any) -> List[str]:
        srv = getattr(s, "servicing_rooms", None)
        if srv is None and isinstance(s, dict):
            srv = s.get("servicing_rooms", [])
        return [str(x).lower() for x in (srv or [])]

    for fl in floors:
        rooms = list(getattr(fl, "rooms", None) or [])
        wet = [r for r in rooms if is_wet_room(r.room_id, getattr(r, "zone_category", ""), getattr(r, "is_vertical_core", False))]
        for r in wet:
            rx, ry, rw, rd = _rect(r)
            rcx, rcy = rx + rw / 2.0, ry + rd / 2.0
            best, best_d = None, float("inf")
            for s in (duct_shafts or []):
                sx, sy, sw, sd = _shaft_rect(s)
                scx, scy = sx + sw / 2.0, sy + sd / 2.0
                rid_lc = r.room_id.lower()
                srv = _shaft_serving(s)
                if any(rid_lc == k or k in rid_lc for k in srv):
                    best, best_d = s, 0.0
                    break
                d = math.hypot(max(0.0, max(sx - (rx + rw), rx - (sx + sw))),
                               max(0.0, max(sy - (ry + rd), ry - (sy + sd))))
                if d < best_d:
                    best_d, best = d, s
            if best is None:
                findings.append(f"F{getattr(fl, 'floor_index', 0)} {r.room_id}: no plumbing shaft available for association")
                associations.append({"room_id": r.room_id, "floor_index": getattr(fl, "floor_index", 0),
                                     "shaft_id": None, "run_m": None, "associated": False})
                continue
            associations.append({
                "room_id": r.room_id,
                "floor_index": getattr(fl, "floor_index", 0),
                "shaft_id": _shaft_id(best),
                "run_m": round(best_d, 2),
                "associated": True,
            })
            if best_d <= _EG_EPS or r.room_id.lower() in _shaft_serving(best):
                served_count += 1
            elif best_d <= WET_CORE_MAX_RUN_M:
                served_count += 1
            else:
                findings.append(
                    f"F{getattr(fl, 'floor_index', 0)} {r.room_id}: wet run {best_d:.2f}m to shaft "
                    f"{_shaft_id(best)} exceeds {WET_CORE_MAX_RUN_M:.1f}m grouping guideline"
                )

            # Soil/waste run must not cross a dry room outside the shaft.
            sx, sy, sw, sd = _shaft_rect(best)
            seg = ((rcx, rcy), (sx + sw / 2.0, sy + sd / 2.0))
            for o in rooms:
                if o.room_id == r.room_id or getattr(o, "is_vertical_core", False):
                    continue
                if is_wet_room(o.room_id, getattr(o, "zone_category", ""), getattr(o, "is_vertical_core", False)):
                    continue
                if getattr(o, "zone_category", "") in DRY_ZONE_CATEGORIES:
                    continue
                ox, oy, ow, od = _rect(o)
                if segment_intersects_box(seg, (ox, oy, ox + ow, oy + od)):
                    crossings.append({
                        "floor_index": getattr(fl, "floor_index", 0),
                        "from_room": r.room_id,
                        "shaft_id": _shaft_id(best),
                        "through_room": o.room_id,
                    })
                    findings.append(
                        f"F{getattr(fl, 'floor_index', 0)}: soil run {r.room_id} -> {_shaft_id(best)} "
                        f"crosses dry room {o.room_id} (must be re-routed through shaft/corridor)"
                    )

    total_wet = len(associations)
    associated = sum(1 for a in associations if a["associated"])
    status = "pass" if (not findings and total_wet == associated) else "warn"
    return {
        "wet_room_count": total_wet,
        "associated_count": associated,
        "crossings": crossings,
        "findings": findings,
        "status": status,
        "citation": WET_CORE_CITATION,
    }


# =============================================================================
# L11 - TERRACE DRAINAGE SET
# =============================================================================

def compute_terrace_drainage(floors: List[Any], site_outlet_id: str = SITE_STORM_OUTLET_ID) -> Dict[str, Any]:
    """
    For every terrace zone, produces the drainage set anchors (drain point,
    slope arrows, downpipe drop, waterproofing band, overflow note) used both
    by the audit (L11) and by the service-layer drawing. The downpipe ties to
    the site stormwater outlet id.
    """
    terraces: List[Dict[str, Any]] = []
    for fl in floors:
        for r in (getattr(fl, "rooms", None) or []):
            if getattr(r, "zone_category", "") != "terrace":
                continue
            rx, ry, rw, rd = _rect(r)
            # Drain point: 0.6m inboard from the SW corner (deterministic).
            dx_ = min(rx + 0.60, rx + rw - 0.30)
            dy_ = min(ry + 0.60, ry + rd - 0.30)
            # Downpipe: at the outer (south/west) facade midpoint.
            rwp = (round(rx + rw / 2.0, 2), round(ry + 0.15, 2))
            terraces.append({
                "floor_index": getattr(fl, "floor_index", 0),
                "room_id": getattr(r, "room_id", "terrace"),
                "rect": [round(rx, 2), round(ry, 2), round(rw, 2), round(rd, 2)],
                "drain_point": [round(dx_, 2), round(dy_, 2)],
                "slope_ratio": TERRACE_SLOPE_RATIO,
                "downpipe_point": rwp,
                "downpipe_ties_to": site_outlet_id,
                "waterproofing_band_m": TERRACE_WP_BAND_M,
                "parapet_min_h_m": TERRACE_PARAPET_MIN_H_M,
                "overflow_note": "Overflow scupper at parapet +25mm above finished level",
            })

    status = "pass" if terraces else "n/a"
    reason = (None if terraces
              else "No terrace zone on any floor of this generation")
    return {
        "terraces": terraces,
        "terrace_count": len(terraces),
        "status": status,
        "reason": reason,
        "site_outlet_id": site_outlet_id,
        "citation": TERRACE_SLOPE_CITATION,
    }


# =============================================================================
# L12 - STRUCTURAL MODEL (columns, beams, load-path, footings)
# =============================================================================

def _wall_segments(wall_graph: Optional[Dict[str, Any]], ext_only: bool = False,
                   load_bearing_too: bool = True) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
    segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for w in ((wall_graph or {}).get("walls") or []):
        if ext_only and not (w.get("is_exterior") or (load_bearing_too and w.get("is_load_bearing"))):
            continue
        segs.append(((float(w.get("x1", 0.0)), float(w.get("y1", 0.0))),
                     (float(w.get("x2", 0.0)), float(w.get("y2", 0.0)))))
    return segs


def _dedupe_points(pts: List[Tuple[float, float]], tol: float = 0.05) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for p in pts:
        if not any(abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol for q in out):
            out.append((round(p[0], 2), round(p[1], 2)))
    return out


def compute_structural_model(floors: List[Any], typology: str,
                             structural_grid: Any = None) -> Dict[str, Any]:
    """
    Structural layer model:
    - column grid at exterior/load-bearing wall intersections, with intermediate
      columns inserted wherever consecutive spacing exceeds the typology span limit,
    - floor-to-floor load-path continuity: every upper exterior/load-bearing wall
      must bear on support below within tolerance, else a transfer beam is flagged,
    - footing hints for every ground-level column.
    """
    max_span = TYP_MAX_SPAN_M.get(typology, 4.5)
    columns: List[Dict[str, Any]] = []
    beams: List[Dict[str, Any]] = []
    notes: List[str] = []

    if floors:
        ground = floors[0]
        segs = _wall_segments(getattr(ground, "wall_graph", None), ext_only=True)
        pts: List[Tuple[float, float]] = []
        for (a, b) in segs:
            pts.extend([a, b])
        pts = _dedupe_points(pts)

        # Enforce span limit along each ground wall segment: insert intermediate columns.
        for (a, b) in segs:
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length <= _EG_EPS:
                continue
            n_needed = int(math.ceil(length / max_span))
            for i in range(1, n_needed):
                t = i / n_needed
                pts.append((round(a[0] + t * (b[0] - a[0]), 2), round(a[1] + t * (b[1] - a[1]), 2)))
            if n_needed > 1:
                notes.append(
                    f"Ground wall ({a[0]:.1f},{a[1]:.1f})-({b[0]:.1f},{b[1]:.1f}): {n_needed} bays "
                    f"(span limit {max_span:.1f}m for {typology})"
                )
        for idx, (px, py) in enumerate(sorted(set(pts))):
            columns.append({
                "column_id": f"C{idx + 1:02d}",
                "floor_index": 0,
                "x": px,
                "y": py,
                "size_m": STRUCTURAL_COLUMN_SIZE_M,
                "footing_hint": f"Isolated pad footing, proven bearing at -1.50m ({FOOTING_HINT_CITATION})",
            })

    # Floor-to-floor load-path continuity (upper walls must land on support below).
    for z in range(1, len(floors)):
        lower_segs = _wall_segments(getattr(floors[z - 1], "wall_graph", None), ext_only=True)
        upper_segs = _wall_segments(getattr(floors[z], "wall_graph", None), ext_only=True)
        for (a, b) in upper_segs:
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length <= 0.30:
                continue
            n_samples = max(4, int(math.ceil(length / 0.25)))
            supported_pts = 0
            for i in range(n_samples + 1):
                t = i / n_samples
                sx, sy = a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
                if any(point_segment_distance(sx, sy, la[0], la[1], lb[0], lb[1]) <= STRUCTURAL_SUPPORT_TOL_M
                       for (la, lb) in lower_segs):
                    supported_pts += 1
            ratio = supported_pts / (n_samples + 1)
            if ratio < STRUCTURAL_CONTINUITY_TOL:
                beams.append({
                    "beam_id": f"TB-F{z}-{len(beams) + 1:02d}",
                    "floor_index": z,
                    "line": [round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2)],
                    "support_ratio": round(ratio, 2),
                    "note": (
                        f"Transfer beam required: wall above supported over {ratio * 100:.0f}% of length "
                        f"(< {STRUCTURAL_CONTINUITY_TOL * 100:.0f}% tolerance). {STRUCTURAL_LOAD_PATH_CITATION}"
                    ),
                })

    status = "pass" if not beams else "warn"
    return {
        "columns": columns,
        "column_count": len(columns),
        "beams": beams,
        "beam_count": len(beams),
        "footing_hints": [c["footing_hint"] for c in columns[:1]],
        "max_span_m": max_span,
        "notes": notes,
        "status": status,
        "citation": STRUCTURAL_SPAN_CITATION,
    }


# =============================================================================
# L13 - ACCESSIBILITY AUDIT
# =============================================================================

def compute_accessibility_audit(floors: List[Any], typology: str) -> Dict[str, Any]:
    """
    Accessibility layer: corridor clear widths, interior/entrance door widths,
    1500mm bathroom maneuvering circle where flagged, entrance threshold note.
    Applicability: T3/T4 fully; T1/T2 advisory (WARN, never FAIL).
    """
    min_corridor = ACCESS_CORRIDOR_MIN_M.get(typology, 1.00)
    full_scope = typology in ACCESS_FULL_APPLICABILITY
    findings: List[str] = []
    corridor_checks: List[Dict[str, Any]] = []
    door_checks: List[Dict[str, Any]] = []
    circle_checks: List[Dict[str, Any]] = []

    for fl in floors:
        f_idx = getattr(fl, "floor_index", 0)
        for r in (getattr(fl, "rooms", None) or []):
            rid = (getattr(r, "room_id", "") or "")
            rid_lc = rid.lower()
            if "corridor" in rid_lc and getattr(r, "zone_category", "") == "circulation":
                width = min(float(getattr(r, "width_m", 0.0) or 0.0), float(getattr(r, "depth_m", 0.0) or 0.0))
                ok = width + 1e-6 >= min_corridor
                corridor_checks.append({"room_id": rid, "floor_index": f_idx, "clear_width_m": round(width, 2),
                                        "required_m": min_corridor, "pass": ok})
                if not ok:
                    findings.append(
                        f"F{f_idx} {rid}: corridor clear width {width:.2f}m < {min_corridor:.2f}m "
                        f"({typology} requirement)"
                    )
            if getattr(r, "zone_category", "") == "service" and (
                "bath" in rid_lc or "wc" in rid_lc or "toilet" in rid_lc
            ):
                fixtures = [
                    (float(fx.x), float(fx.y), float(fx.width_m), float(fx.depth_m))
                    for fx in (getattr(r, "fixtures", None) or [])
                ]
                placement = largest_free_square_m(
                    (float(r.x), float(r.y), float(r.width_m), float(r.depth_m)),
                    fixtures, ACCESS_MANEUVER_CIRCLE_M,
                )
                circle_checks.append({
                    "room_id": rid,
                    "floor_index": f_idx,
                    "circle_m": ACCESS_MANEUVER_CIRCLE_M,
                    "achieved": placement is not None,
                    "position": list(placement) if placement else None,
                })
                if placement is None and full_scope:
                    findings.append(
                        f"F{f_idx} {rid}: 1500mm wheelchair maneuvering circle not achievable in sanitary room"
                    )

        for d in (getattr(fl, "doors", None) or []):
            dw = float(getattr(d, "width_m", 0.0) or 0.0)
            d_id = (getattr(d, "door_id", "") or "")
            is_entrance = f_idx == 0 and (d_id.upper().startswith("D1") or "main" in d_id.lower())
            req = ACCESS_DOOR_MIN_ENTRANCE_M if is_entrance else ACCESS_DOOR_MIN_INTERIOR_M
            # Sliding shutters/dock doors are industrial equipment, not accessible-route doors.
            if getattr(d, "door_type", "standard") in ("dock_shutter",):
                continue
            ok = dw + 1e-6 >= req
            door_checks.append({"door_id": d_id, "floor_index": f_idx, "clear_width_m": round(dw, 2),
                                "required_m": req, "entrance": is_entrance, "pass": ok})
            if not ok and is_entrance:
                findings.append(f"F0 {d_id}: entrance door clear width {dw:.2f}m < {req:.2f}m")

    status = "pass" if not findings else ("fail" if full_scope else "warn")
    return {
        "corridor_checks": corridor_checks,
        "door_checks": door_checks,
        "circle_checks": circle_checks,
        "applicability": "full" if full_scope else "advisory",
        "entrance_threshold_note": ACCESS_THRESHOLD_NOTE,
        "findings": findings,
        "status": status,
        "citation": ACCESS_CITATION,
    }


# =============================================================================
# L14 - FIRE & EGRESS EXTENSION
# =============================================================================

def compute_fire_egress_audit(floors: List[Any], typology: str,
                              egress_distances_satisfied: bool,
                              occupant_load: int = 0) -> Dict[str, Any]:
    """
    Fire/egress extension: bedroom egress (corridor door + escape-window note),
    travel-distance verdict (from L1 engine BFS), and exit width table.
    """
    findings: List[str] = []
    bedroom_egress: List[Dict[str, Any]] = []

    for fl in floors:
        f_idx = getattr(fl, "floor_index", 0)
        room_ids = {getattr(r, "room_id", "") for r in (getattr(fl, "rooms", None) or [])}
        window_rooms = {getattr(w, "room_id", None) or (w.get("room_id", "") if isinstance(w, dict) else "")
                        for w in (getattr(fl, "windows", None) or [])}
        door_rooms = set()
        for d in (getattr(fl, "doors", None) or []):
            door_rooms.add(getattr(d, "from_room", None) or "")
            door_rooms.add(getattr(d, "to_room", None) or "")
        for rid in sorted(room_ids):
            if BEDROOM_EGRESS_KEYWORD not in rid.lower():
                continue
            has_door = rid in door_rooms
            has_window = rid in window_rooms
            bedroom_egress.append({
                "room_id": rid,
                "floor_index": f_idx,
                "corridor_door": has_door,
                "escape_window": has_window,
                "note": "Escape window: openable clear >= 0.35 m2, sill <= 1.0m" if has_window else None,
            })
            if not has_door:
                findings.append(f"F{f_idx} {rid}: bedroom has no door on the egress network")
            if not has_window:
                findings.append(f"F{f_idx} {rid}: no escape window - note required on safety plan")

    # Exit width table (ground floor)
    #
    # EXIT CAPACITY IS SIZED BY THE POPULATION EACH EXIT SERVES (NBC 2016 Part 4
    # Table 4A).  Ground-floor occupants discharge directly through the main
    # entry; the protected stair carries the storeys above it.  Charging the
    # whole building's population to a single stair double-counts the ground
    # floor, and - because a wider stair enlarges the plate and therefore the
    # load - makes a compliant width unattainable by construction.  The
    # BUILDING occupant load is unchanged and still reported here; only its
    # attribution to the two exits is measured.  A shortfall on either exit is
    # a hard capacity FAIL, never a warning.
    exit_rows: List[Dict[str, Any]] = []
    ground = floors[0] if floors else None
    main_width = 0.0
    if ground is not None:
        for d in (getattr(ground, "doors", None) or []):
            d_id = (getattr(d, "door_id", "") or "")
            if d_id.upper().startswith("D1") or "main" in d_id.lower():
                main_width = float(getattr(d, "width_m", 0.0) or 0.0)
                break
    stair_width = 1.00
    if ground is not None:
        ss = (getattr(ground, "stair_schedule", None) or [])
        if ss and isinstance(ss[0], dict):
            try:
                stair_width = float(str(ss[0].get("flight_width_m", "1.00")).split()[0])
            except (ValueError, IndexError):
                stair_width = 1.00

    def _floor_area(fl: Any) -> float:
        env = getattr(fl, "envelope", None) or {}
        area = float(env.get("area_sqm", 0.0) or 0.0)
        if area <= 0.0:
            area = sum(
                float(getattr(r, "area_sqm", 0.0) or 0.0)
                for r in (getattr(fl, "rooms", None) or [])
            )
        return max(0.0, area)

    ground_area = _floor_area(ground) if ground is not None else 0.0
    total_area = sum(_floor_area(fl) for fl in floors)
    ground_load = 0
    if occupant_load > 0 and total_area > 0.0:
        ground_load = int(round(occupant_load * (ground_area / total_area)))
    ground_load = max(0, min(int(occupant_load), ground_load))
    stair_load = max(0, int(occupant_load) - ground_load)

    served_main = main_width * FIRE_OCCUPANT_PER_M_EXIT
    served_stair = stair_width * FIRE_OCCUPANT_PER_M_EXIT
    main_capacity_ok = served_main + 1e-9 >= ground_load
    stair_capacity_ok = served_stair + 1e-9 >= stair_load
    capacity_satisfied = bool(main_capacity_ok and stair_capacity_ok)
    if not stair_capacity_ok:
        findings.append(
            f"Stair exit width {stair_width:.2f}m serves ~{served_stair:.0f} occupants "
            f"< stair load {stair_load} (upper storeys; building load {occupant_load})"
        )
    if not main_capacity_ok:
        findings.append(
            f"Main entry width {main_width:.2f}m serves ~{served_main:.0f} occupants "
            f"< ground-floor load {ground_load}"
        )
    exit_rows.append({
        "exit": "Main Entry Door",
        "clear_width_m": round(main_width, 2),
        "occupants_served": round(served_main, 0),
        "load_served": ground_load,
        "capacity_satisfied": bool(main_capacity_ok),
        "code": "NBC 2016 Part 4 Table 4A (~50 persons per 1.0m)",
    })
    exit_rows.append({
        "exit": "Protected Stair",
        "clear_width_m": round(stair_width, 2),
        "occupants_served": round(served_stair, 0),
        "load_served": stair_load,
        "capacity_satisfied": bool(stair_capacity_ok),
        "code": "NBC 2016 Part 3 Cl 12.18 / Part 4",
    })

    status = "pass"
    if not egress_distances_satisfied:
        status = "fail"
        findings.append("Travel distance exceeds profile maximum (non-sprinklered) - see L1 egress check")
    elif not capacity_satisfied:
        status = "fail"
    elif findings:
        status = "warn"
    return {
        "bedroom_egress": bedroom_egress,
        "exit_width_table": exit_rows,
        "occupant_load": occupant_load,
        "protection": {
            "stair_clear_width_m": round(stair_width, 2),
            "stair_occupants_served": round(served_stair, 0),
            "stair_load_served": stair_load,
            "main_entry_clear_width_m": round(main_width, 2),
            "main_entry_occupants_served": round(served_main, 0),
            "main_entry_load_served": ground_load,
            "building_occupant_load": occupant_load,
            "governing_occupant_load": stair_load,
            "capacity_satisfied": bool(capacity_satisfied),
            "load_basis": (
                "NBC 2016 Part 4 Table 4A - each exit is sized for the population "
                "it serves (ground floor exits at grade; the protected stair "
                "carries the storeys above). The building total is unchanged."
            ),
            "persons_per_metre": FIRE_OCCUPANT_PER_M_EXIT,
            "code": "NBC 2016 Part 4 Table 4A exit capacity / Part 3 Cl 12.18",
        },
        "findings": findings,
        "status": status,
        "citation": FIRE_EGRESS_CITATION,
    }
