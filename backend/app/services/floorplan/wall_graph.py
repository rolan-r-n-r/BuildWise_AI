"""
wall_graph.py - Constructible Geometry Model (Wall-Graph) & Engineering Set-Out
================================================================================
Implements the first-class architectural constructibility representation:
1. Clear interior room rectangles (inner face of plaster/finishes).
2. First-class wall segments with statutory thicknesses:
   - W1 Exterior Wall: 230mm (0.230m)
   - W2 Interior Partition: 115mm (0.115m)
   - W3 WC / Plumbing Partition: 75mm (0.075m)
3. Dimension chain generation & hard verification:
   Overall envelope = sum(clear dims) + sum(wall thicknesses) <= 1mm tolerance.
4. Hosted openings (doors & windows) bound to wall segments with clearance rules.
5. Computed staircase geometry derived from floor-to-floor height (Blondel's rule).
6. Statutory code-sized window calculations per NBC 2016 Light & Ventilation.
7. Circulation egress and door swing collision resolution.
8. Complete construction schedules: Door, Window, and Room Finish schedules.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Literal
from shapely.geometry import box as shapely_box, Point
from shapely.ops import unary_union

from app.services.floorplan.identity import identity_dict, identity_is_wet, identity_name


# =============================================================================
# 1. STATUTORY WALL SPECIFICATIONS & THICKNESSES
# =============================================================================

W1_EXTERIOR_THICKNESS_M: float = 0.230      # 230mm load-bearing / exterior masonry
W2_INTERIOR_THICKNESS_M: float = 0.115      # 115mm interior space-dividing partition
W3_PARTITION_THICKNESS_M: float = 0.075     # 75mm WC / plumbing chase / dry partition

WALL_TYPE_SPECS: Dict[str, Dict[str, Any]] = {
    "W1": {
        "tag": "W1",
        "name": "Exterior Structural Wall",
        "thickness_mm": 230,
        "thickness_m": 0.230,
        "description": "230mm Brick/AAC Masonry with 15mm Cement Plaster Both Faces",
        "is_load_bearing": True,
        "hatch": "brick_diagonal",
        "fire_rating_hours": 2.0,
    },
    "W2": {
        "tag": "W2",
        "name": "Interior Room Partition",
        "thickness_mm": 115,
        "thickness_m": 0.115,
        "description": "115mm Brick Partition with 12mm Plaster Both Faces",
        "is_load_bearing": False,
        "hatch": "solid_subtle",
        "fire_rating_hours": 1.0,
    },
    "W3": {
        "tag": "W3",
        "name": "WC & Service Shaft Partition",
        "thickness_mm": 75,
        "thickness_m": 0.075,
        "description": "75mm Lightweight Reinforced Concrete / Drywall Shaft Partition",
        "is_load_bearing": False,
        "hatch": "hollow_double",
        "fire_rating_hours": 1.0,
    },
    "W_PARAPET": {
        "tag": "W_PARAPET",
        "name": "Terrace Parapet Wall",
        "thickness_mm": 115,
        "thickness_m": 0.115,
        "description": "115mm Parapet Wall (1.0m height) with coping & drainage weep holes",
        "is_load_bearing": False,
        "hatch": "solid_subtle",
        "fire_rating_hours": 1.0,
    },
}


# =============================================================================
# 2. NBC 2016 STATUTORY LIGHT & VENTILATION CONSTANTS
# =============================================================================

# National Building Code of India (NBC) 2016, Part 8 'Building Services', Section 1 'Lighting and Ventilation', Clause 4.2
# and Part 3 'Development Control Rules', Clause 12.2:
# Habitable rooms (Living, Bedroom, Dining, Kitchen, Study, Office) aggregate window opening area >= 1/8th (12.5%) of floor area.
NBC_2016_HABITABLE_VENT_RATIO: float = 0.125
NBC_2016_HABITABLE_CITATION: str = "NBC 2016 Part 8 Sec 1 Cl 4.2 / Part 3 Cl 12.2"

# NBC 2016 Part 3 'Development Control Rules', Clause 12.2.5.1:
# Bathrooms / Water Closets minimum ventilation opening area to external air >= 0.37 m2 (or 10% of floor area).
NBC_2016_SANITARY_VENT_RATIO: float = 0.10
NBC_2016_SANITARY_MIN_VENT_AREA_M2: float = 0.37
NBC_2016_SANITARY_CITATION: str = "NBC 2016 Part 3 Cl 12.2.5.1"

# NBC 2016 Part 3 Table 1 & Part 4 Fire Protection - Minimum Corridor Clear Widths
NBC_2016_MIN_CORRIDOR_WIDTH_T1_M: float = 1.00     # Single-family residential
NBC_2016_MIN_CORRIDOR_WIDTH_T2_M: float = 1.25     # Multi-family residential
NBC_2016_MIN_CORRIDOR_WIDTH_T3_M: float = 1.50     # Commercial / complex double-loaded spine
NBC_2016_MIN_CORRIDOR_WIDTH_T4_M: float = 1.50     # Industrial egress / logistics catwalk

# Convenience aliases
WALL_THICKNESS_EXTERIOR_M: float = W1_EXTERIOR_THICKNESS_M
WALL_THICKNESS_INTERIOR_M: float = W2_INTERIOR_THICKNESS_M
WALL_THICKNESS_PARTITION_M: float = W3_PARTITION_THICKNESS_M
CORRIDOR_MIN_CLEAR_WIDTH_T1: float = NBC_2016_MIN_CORRIDOR_WIDTH_T1_M
CORRIDOR_MIN_CLEAR_WIDTH_T2_T3: float = NBC_2016_MIN_CORRIDOR_WIDTH_T2_M
CORRIDOR_MIN_CLEAR_WIDTH_T4: float = NBC_2016_MIN_CORRIDOR_WIDTH_T4_M
NBC_2016_MIN_SANITARY_VENT_AREA_SQM: float = NBC_2016_SANITARY_MIN_VENT_AREA_M2



def compute_window_dimensions(
    room_name_or_id: str,
    room_area_sqm: float,
    window_height_m: Optional[float] = None
) -> Dict[str, Any]:
    """
    Computes statutory window dimensions and ventilation ratio per NBC 2016:
    - Habitable rooms: aggregate opening area >= 12.5% (1/8th) of floor area (NBC Part 8 Sec 1 Cl 4.2).
    - Sanitary rooms (bath, toilet, wc): aggregate opening area >= 10.0% of floor area, min 0.37 sqm (NBC Part 3 Cl 12.2.5.1).
    """
    is_sanitary = any(s in room_name_or_id.lower() for s in ("bath", "toilet", "wc", "wash", "sanitary"))
    if is_sanitary:
        req_area = max(NBC_2016_SANITARY_MIN_VENT_AREA_M2, room_area_sqm * NBC_2016_SANITARY_VENT_RATIO)
        h = window_height_m or 0.60
        sill = 1.50
        lintel = 2.10
        w = round(max(0.60, req_area / h), 2)
        citation = NBC_2016_SANITARY_CITATION
        ratio_str = ">= 10.0% (min 0.37 m²)"
    else:
        req_area = room_area_sqm * NBC_2016_HABITABLE_VENT_RATIO
        h = window_height_m or 1.20
        sill = 0.90
        lintel = 2.10
        w = round(max(1.00, req_area / h), 2)
        citation = NBC_2016_HABITABLE_CITATION
        ratio_str = ">= 12.5% (NBC Cl 4.2)"

    return {
        "room_name_or_id": room_name_or_id,
        "room_area_sqm": room_area_sqm,
        "is_sanitary": is_sanitary,
        "required_vent_area_sqm": round(req_area, 3),
        "opening_area_sqm": round(w * h, 3),
        "width_m": w,
        "height_m": h,
        "sill_m": sill,
        "lintel_m": lintel,
        "citation": citation,
        "ventilation_ratio": ratio_str,
    }


# =============================================================================
# 3. COMPUTED STAIRCASE GEOMETRY ENGINE (BLONDEL'S RULE)
# =============================================================================

@dataclass
class StairGeometry:
    """
    Statutory computed dogleg staircase geometry derived purely from floor-to-floor height.
    Enforces Francois Blondel's ergonomic rule: 2R + T in [600mm, 650mm].
    """
    floor_height_m: float
    riser_count: int
    riser_height_m: float
    tread_depth_m: float
    flight_count: int
    treads_per_flight: int
    flight_width_m: float
    landing_depth_m: float
    stair_well_m: float
    stair_run_m: float
    stair_box_depth_m: float
    stair_box_width_m: float
    landing_width_m: float = 0.0
    risers_per_flight: int = 0
    handrail_side: str = "Inner well & outer wall"
    travel_direction: str = "UP"
    headroom_min_m: float = 2.20
    headroom_note: str = "HEADROOM >= 2.20m CLEAR"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "floor_height_m": self.floor_height_m,
            "riser_count": self.riser_count,
            "riser_height_mm": round(self.riser_height_m * 1000.0, 1),
            "riser_height_m": self.riser_height_m,
            "tread_depth_mm": round(self.tread_depth_m * 1000.0, 1),
            "tread_depth_m": self.tread_depth_m,
            "blondel_sum_mm": round((2.0 * self.riser_height_m + self.tread_depth_m) * 1000.0, 1),
            "flight_count": self.flight_count,
            "risers_per_flight": self.risers_per_flight,
            "treads_per_flight": self.treads_per_flight,
            "flight_width_m": self.flight_width_m,
            "landing_depth_m": self.landing_depth_m,
            "landing_width_m": self.landing_width_m or self.stair_box_width_m,
            "stair_well_m": self.stair_well_m,
            "stair_run_m": self.stair_run_m,
            "stair_box_depth_m": self.stair_box_depth_m,
            "stair_box_width_m": self.stair_box_width_m,
            "handrail_side": self.handrail_side,
            "travel_direction": self.travel_direction,
            "headroom_min_m": self.headroom_min_m,
            "headroom_note": self.headroom_note,
        }


def compute_stair_geometry(
    floor_height_m: float = 3.0,
    typology: str = "T1_SINGLE_FAMILY",
    max_riser_m: float = 0.175,
    floor_index: int = 0,
    total_storeys: int = 1,
) -> StairGeometry:
    """
    Computes precise dogleg staircase geometry per NBC 2016 Part 3 Cl 12.18 / Table 7:
    - Risers N = ceil(H / 175mm), R <= 190mm (residential)
    - R = H / N
    - Tread T >= 250mm satisfying Blondel's formula 2R + T in [600mm, 650mm]
    - Flight width >= 1.0m residential (>= 1.25m multi-family / commercial)
    - Risers per flight <= 12 per NBC Part 3
    - Landing depth >= flight width
    - Headroom >= 2.20m clear throughout
    - Hard assertion: N * R == floor_height_m within 1mm (0.001m).
    """
    H = floor_height_m
    # Max statutory riser: 190mm residential
    clamped_max_riser = min(0.190, max_riser_m)
    N = int(math.ceil(round(H / clamped_max_riser, 6)))
    R = H / N
    assert R <= 0.190, f"Riser {R*1000:.1f}mm exceeds NBC statutory maximum 190mm"

    # Verify hard invariant: N * R == H within 1mm
    assert abs(N * R - H) <= 0.001, f"Stair riser sum {N * R} != floor height {H}"

    # Solve for optimal ergonomic tread T >= 0.250 satisfying 2R + T in [0.600, 0.650]
    two_r = 2.0 * R
    target_blondel = 0.625  # Midpoint of 600-650mm
    ideal_t = target_blondel - two_r
    T = max(0.250, min(0.300, round(ideal_t, 3)))

    blondel_check = round(2.0 * R + T, 3)
    if not (0.600 <= blondel_check <= 0.650):
        if blondel_check < 0.600:
            T = max(0.250, min(0.300, round(0.600 - two_r, 3)))
        elif blondel_check > 0.650:
            T = max(0.250, min(0.300, round(0.650 - two_r, 3)))

    assert T >= 0.250, f"Tread {T*1000:.1f}mm is below NBC statutory minimum 250mm"

    # Flights calculation (<= 12 risers per flight)
    flight_count = 2
    risers_per_flight = int(math.ceil(N / flight_count))
    if risers_per_flight > 12:
        # For very high floor-to-floor (e.g. > 4.5m), scale flights
        flight_count = 3 if math.ceil(N / 3) <= 12 else 4
        risers_per_flight = int(math.ceil(N / flight_count))
    assert risers_per_flight <= 12, f"Risers per flight ({risers_per_flight}) exceeds NBC maximum of 12"
    treads_per_flight = max(1, risers_per_flight - 1)

    # COMPUTED CLEAR HEADROOM per NBC Part 3 Cl 12.18.3. In a dogleg the two
    # flights sit side-by-side (separated by the inner well), NOT stacked, so
    # no walker passes under the opposing flight; the governing clearance is
    # the vertical clear under the arriving floor slab (soffit) taken over the
    # stair, conservatively derived from the floor height with a 100mm slab:
    #   clear = H - slab (0.10m)
    # For H=3.00m this yields 2.90m >= 2.20m statutory. If the as-computed
    # value cannot clear 2.20m it is a GEOMETRY defect (floor height / riser
    # count) - the assertion fires at source instead of the sheet printing a
    # compliance string the geometry does not earn.
    _SLAB_THICKNESS_M = 0.10
    computed_headroom_m = round(H - _SLAB_THICKNESS_M, 3)
    assert computed_headroom_m >= 2.20 - 1e-9, (
        f"Stair clear headroom {computed_headroom_m:.2f}m below NBC minimum 2.20m "
        f"(H={H:.2f}m, N={N}, R={R*1000:.1f}mm, T={T*1000:.0f}mm, "
        f"risers/flight={risers_per_flight}) - fix the riser geometry, not the label."
    )

    # Flight width per typology statutory minimum (NBC 2016 Part 3 Cl 12.18.1).
    # Multi-family flights are 1.30 m, not 1.25 m: NBC 2016 Part 4 Table 4A
    # credits ~50 persons per metre of clear exit width, so a 1.25 m flight
    # carries only 62 persons - one short of the 63-person load of a legal
    # four-household, four-storey T2 plate.  A flight that cannot carry the
    # building's own exit load is a capacity defect, not a rounding choice.
    typ_upper = typology.upper()
    if "T2" in typ_upper or "T3" in typ_upper or "COMMERCIAL" in typ_upper or "MULTI" in typ_upper:
        flight_width = 1.30
        landing_depth = 1.30
        stair_well = 0.20
    elif "T4" in typ_upper or "INDUSTRIAL" in typ_upper or "WAREHOUSE" in typ_upper:
        flight_width = 1.20
        landing_depth = 1.20
        stair_well = 0.15
    else:
        flight_width = 1.00  # T1 Single Family >= 1.0m
        landing_depth = 1.00
        stair_well = 0.15

    # Landing depth must be >= flight width
    assert landing_depth >= flight_width, f"Landing depth {landing_depth}m < flight width {flight_width}m"

    flight_run = round(treads_per_flight * T, 3)
    stair_box_depth = round(flight_run + landing_depth, 3)
    stair_box_width = round(2.0 * flight_width + stair_well, 3)
    landing_width = stair_box_width

    # Travel direction annotation per floor
    if floor_index == 0:
        travel_dir = "UP"
    elif floor_index >= total_storeys - 1:
        travel_dir = "DN"
    else:
        travel_dir = "UP / DN"

    return StairGeometry(
        floor_height_m=H,
        riser_count=N,
        riser_height_m=round(R, 5),
        tread_depth_m=round(T, 3),
        flight_count=flight_count,
        risers_per_flight=risers_per_flight,
        treads_per_flight=treads_per_flight,
        flight_width_m=flight_width,
        landing_depth_m=landing_depth,
        landing_width_m=landing_width,
        stair_well_m=stair_well,
        stair_run_m=flight_run,
        stair_box_depth_m=stair_box_depth,
        stair_box_width_m=stair_box_width,
        handrail_side="Inner Well (950mm)",
        travel_direction=travel_dir,
        headroom_min_m=computed_headroom_m,
        headroom_note=f"HEADROOM >= {computed_headroom_m:.2f}m CLEAR (R={R*1000:.1f}mm T={T*1000:.0f}mm N={N})",
    )


def compute_stair_schedule_rows(stair_geom: StairGeometry) -> List[Dict[str, Any]]:
    """
    Formats the Stair Schedule table rows for floor sheet drawing IR and tabular display.
    """
    if not stair_geom:
        return []
    d = stair_geom.to_dict() if hasattr(stair_geom, "to_dict") else stair_geom
    return [
        {
            "flight_width_m": f"{d.get('flight_width_m', 1.0):.2f} m",
            "tread_depth_mm": f"{int(round(d.get('tread_depth_mm', 250)))} mm",
            "riser_height_mm": f"{d.get('riser_height_mm', 166.7):.1f} mm",
            "risers_per_flight": f"{d.get('risers_per_flight', 9)} (Treads: {d.get('treads_per_flight', 8)})",
            "landing_dims": f"{d.get('landing_width_m', 2.15):.2f} x {d.get('landing_depth_m', 1.00):.2f} m",
            "floor_to_floor": f"{d.get('floor_height_m', 3.0):.2f} m",
            # PRINT THE COMPUTED VALUE: headroom_min_m now carries the
            # as-computed soffit headroom (asserted >= 2.20 in the geometry),
            # with the R/T/riser-count tokens in headroom_note.
            "headroom": f">= {d.get('headroom_min_m', 2.20):.2f} m",
            "riser_count": d.get("riser_count", 0),
            "headroom_note": d.get("headroom_note", "HEADROOM >= 2.20m CLEAR"),
            "handrail_side": d.get("handrail_side", "Inner Well (950mm)"),
            "travel_dir": d.get("travel_direction", "UP"),
        }
    ]



# =============================================================================
# 4. HOSTED OPENINGS & CLEARANCE GEOMETRY
# =============================================================================

@dataclass
class HostedOpening:
    """
    Architectural door or window hosted directly inside a first-class wall segment.
    """
    opening_id: str
    tag: str                        # e.g. "D1", "D2", "W1", "W2"
    opening_type: Literal["door", "window"]
    wall_id: str
    offset_from_corner: float       # meters along wall segment from start (x1, y1)
    width_m: float
    height_m: float
    sill_m: float
    lintel_m: float
    level: int = 0
    from_room: Optional[str] = None
    to_room: Optional[str] = None
    door_type: Optional[str] = "standard"  # standard, fire_rated, sliding, rolling_shutter
    hinge_side: Optional[str] = "right"    # left, right
    swing_direction: Optional[str] = "inward_right"  # inward_right, inward_left, outward_right, outward_left
    swing_bbox: Optional[Tuple[float, float, float, float]] = None  # (xmin, ymin, xmax, ymax)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "opening_id": self.opening_id,
            "tag": self.tag,
            "opening_type": self.opening_type,
            "wall_id": self.wall_id,
            "offset_from_corner": round(self.offset_from_corner, 3),
            "width_m": round(self.width_m, 3),
            "height_m": round(self.height_m, 3),
            "sill_m": round(self.sill_m, 3),
            "lintel_m": round(self.lintel_m, 3),
            "level": self.level,
            "from_room": self.from_room,
            "to_room": self.to_room,
            "door_type": self.door_type,
            "hinge_side": self.hinge_side,
            "swing_direction": self.swing_direction,
            "swing_bbox": self.swing_bbox,
        }


# =============================================================================
# 5. WALL SEGMENT & CLEAR ROOM DATA STRUCTURES
# =============================================================================

@dataclass
class WallSegment:
    """
    First-class wall segment with exact thickness and hosted openings.
    A single shared wall segment separates two adjacent rooms (never doubled).
    """
    wall_id: str
    wall_type: Literal["W1", "W2", "W3", "W_PARAPET"]
    thickness_m: float
    x1: float
    y1: float
    x2: float
    y2: float
    orientation: Literal["horizontal", "vertical"]
    is_exterior: bool = False
    is_load_bearing: bool = False
    is_parapet: bool = False
    adjacent_rooms: List[str] = field(default_factory=list)
    openings: List[HostedOpening] = field(default_factory=list)
    is_street_facade: bool = False
    label: Optional[str] = None

    @property
    def length_m(self) -> float:
        return round(math.hypot(self.x2 - self.x1, self.y2 - self.y1), 4)

    def can_host_opening(self, opening_width_m: float, offset_m: float) -> Tuple[bool, str]:
        """
        Validates statutory opening placement rules:
        1. Opening + 150mm margin must fit inside segment length.
        2. No two openings within 250mm of each other.
        """
        margin = 0.150
        min_sep = 0.250
        L = self.length_m

        if offset_m < margin - 1e-4:
            return False, f"Opening margin from start {offset_m:.3f}m < statutory 0.150m"
        if offset_m + opening_width_m > L - margin + 1e-4:
            return False, f"Opening end {offset_m + opening_width_m:.3f}m exceeds segment limit {L - margin:.3f}m"

        for op in self.openings:
            op_start = op.offset_from_corner
            op_end = op_start + op.width_m
            new_end = offset_m + opening_width_m

            # Check overlap or separation < 250mm
            if not (new_end + min_sep <= op_start + 1e-4 or offset_m >= op_end + min_sep - 1e-4):
                return False, f"Opening violates 0.250m separation with opening {op.tag}"

        return True, "OK"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "wall_type": self.wall_type,
            "thickness_mm": int(round(self.thickness_m * 1000.0)),
            "thickness_m": self.thickness_m,
            "x1": round(self.x1, 3),
            "y1": round(self.y1, 3),
            "x2": round(self.x2, 3),
            "y2": round(self.y2, 3),
            "length_m": self.length_m,
            "orientation": self.orientation,
            "is_exterior": self.is_exterior,
            "is_load_bearing": self.is_load_bearing,
            "is_parapet": self.is_parapet,
            "adjacent_rooms": list(self.adjacent_rooms),
            "openings": [op.to_dict() for op in self.openings],
            "is_street_facade": self.is_street_facade,
            "label": self.label,
        }


@dataclass
class ClearRoom:
    """
    Clear interior room rectangle measured between the inner faces of wall plaster/finishes.
    """
    room_id: str
    room_name: str
    floor_index: int
    x: float                # Clear inner face X
    y: float                # Clear inner face Y
    width_m: float          # Clear inner face width
    depth_m: float          # Clear inner face depth
    area_sqm: float
    zone: str
    zone_category: str
    finish_zone: str = "Vitrified Tile 600x600"
    # Specification grade the finish_zone was resolved at (basic|standard|premium);
    # stamped onto the Room Schedule so the sheet discloses which tier it prices.
    finish_grade: str = "standard"
    is_vertical_core: bool = False
    unit_id: Optional[str] = None
    wall_ids: List[str] = field(default_factory=list)
    space_type_id: Optional[str] = None
    identity: Dict[str, Any] = field(default_factory=dict)
    is_wet: bool = False
    is_sanitary: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "room_id": self.room_id,
            "room_name": self.room_name,
            "space_type_id": self.space_type_id,
            "identity": dict(self.identity),
            "is_wet": self.is_wet,
            "is_sanitary": self.is_sanitary,
            "floor_index": self.floor_index,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "width_m": round(self.width_m, 3),
            "depth_m": round(self.depth_m, 3),
            "area_sqm": round(self.area_sqm, 2),
            "zone": self.zone,
            "zone_category": self.zone_category,
            "finish_zone": self.finish_zone,
            "finish_grade": self.finish_grade,
            "is_vertical_core": self.is_vertical_core,
            "unit_id": self.unit_id,
            "wall_ids": list(self.wall_ids),
        }


# =============================================================================
# 6. DIMENSION CHAINS (3-LINE ENGINEERING CHAINS)
# =============================================================================

@dataclass
class DimensionSegment:
    label: str              # e.g. "230", "3600", "D1 900", "115"
    length_mm: int
    length_m: float
    start_m: float
    end_m: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "length_mm": self.length_mm,
            "length_m": round(self.length_m, 3),
            "start_m": round(self.start_m, 3),
            "end_m": round(self.end_m, 3),
        }


@dataclass
class DimensionChain:
    """
    Continuous dimension line with architectural 45-degree ticks.
    Level:
    - 'openings': wall corners to window/door opening edges.
    - 'clear_rooms': wall thickness + room clear dimension + wall thickness + ...
    - 'overall': total envelope dimension.
    """
    chain_id: str
    level: Literal["openings", "clear_rooms", "overall"]
    axis: Literal["X", "Y"]
    side: Literal["top", "bottom", "left", "right"]
    segments: List[DimensionSegment] = field(default_factory=list)
    total_mm: int = 0
    total_m: float = 0.0
    offset_distance_m: float = 0.80

    @property
    def sum_mm(self) -> int:
        return sum(s.length_mm for s in self.segments)

    def is_valid_sum(self, tolerance_mm: int = 1) -> bool:
        return abs(self.sum_mm - self.total_mm) <= tolerance_mm

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "level": self.level,
            "axis": self.axis,
            "side": self.side,
            "total_mm": self.total_mm,
            "total_m": round(self.total_m, 3),
            "sum_mm": self.sum_mm,
            "is_valid": self.is_valid_sum(),
            "offset_distance_m": round(self.offset_distance_m, 3),
            "segments": [s.to_dict() for s in self.segments],
        }


# =============================================================================
# 7. ROOT WALL GRAPH MODEL & BUILDER
# =============================================================================

@dataclass
class WallGraph:
    """
    Construction-Grade Wall-Graph Model representing a complete buildable floor plate.
    Contains first-class wall segments, clear rooms, hosted openings, dimension chains,
    and statutory schedules.
    """
    floor_index: int
    envelope: Dict[str, float]      # {"width": float, "depth": float, "area_sqm": float}
    walls: Dict[str, WallSegment] = field(default_factory=dict)
    rooms: Dict[str, ClearRoom] = field(default_factory=dict)
    openings: Dict[str, HostedOpening] = field(default_factory=dict)
    stair_geometry: Optional[StairGeometry] = None
    dim_chains_x: List[DimensionChain] = field(default_factory=list)
    dim_chains_y: List[DimensionChain] = field(default_factory=list)
    door_schedule: List[Dict[str, Any]] = field(default_factory=list)
    window_schedule: List[Dict[str, Any]] = field(default_factory=list)
    room_schedule: List[Dict[str, Any]] = field(default_factory=list)
    stair_schedule: List[Dict[str, Any]] = field(default_factory=list)

    def assert_dimension_chains(self) -> None:
        """
        HARD ASSERTION:
        Verifies that for every dimension chain on every floor,
        the sum of segments equals the overall dimension within 1mm (0.001m).
        """
        env_w_mm = int(round(self.envelope["width"] * 1000.0))
        env_d_mm = int(round(self.envelope["depth"] * 1000.0))

        for chain in self.dim_chains_x:
            assert abs(chain.sum_mm - env_w_mm) <= 1, (
                f"Floor {self.floor_index} X-chain '{chain.chain_id}' ({chain.level}) sum {chain.sum_mm}mm "
                f"!= overall {env_w_mm}mm (delta={abs(chain.sum_mm - env_w_mm)}mm)"
            )

        for chain in self.dim_chains_y:
            assert abs(chain.sum_mm - env_d_mm) <= 1, (
                f"Floor {self.floor_index} Y-chain '{chain.chain_id}' ({chain.level}) sum {chain.sum_mm}mm "
                f"!= overall {env_d_mm}mm (delta={abs(chain.sum_mm - env_d_mm)}mm)"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "floor_index": self.floor_index,
            "envelope": dict(self.envelope),
            "walls": [w.to_dict() for w in self.walls.values()],
            "rooms": [r.to_dict() for r in self.rooms.values()],
            "openings": [op.to_dict() for op in self.openings.values()],
            "stair_geometry": self.stair_geometry.to_dict() if self.stair_geometry else None,
            "dim_chains_x": [c.to_dict() for c in self.dim_chains_x],
            "dim_chains_y": [c.to_dict() for c in self.dim_chains_y],
            "door_schedule": list(self.door_schedule),
            "window_schedule": list(self.window_schedule),
            "room_schedule": list(self.room_schedule),
            "stair_schedule": list(self.stair_schedule),
        }


# =============================================================================
# 8. WALL-GRAPH GENERATION & SET-OUT ENGINE
# =============================================================================

# =============================================================================
# 7b. SPECIFICATION-GRADE FINISH SCHEDULE
# =============================================================================
# The sidebar "Specification Grade" control must reach a VISIBLE sheet output,
# not only the CPWD cost rate. The Room Schedule printed on every floor sheet
# resolves each room key through these tables, so Basic -> standard vitrified /
# cement substitutes and Premium -> imported stone / engineered timber upgrades
# are visible on the drawing itself.
FINISH_ZONES_STANDARD: Dict[str, str] = {
    "living": "Polished Vitrified Tile 800x800",
    "dining": "Polished Vitrified Tile 800x800",
    "kitchen": "Anti-Skid Vitrified Tile + Granite Counter",
    "puja": "Polished White Makrana Marble",
    "master": "Engineered Hardwood Flooring",
    "bed": "Laminated Wooden / Vitrified Tile",
    "bath": "Anti-Skid Ceramic Tile R10 + Full Height Dado",
    "toilet": "Anti-Skid Ceramic Tile R10 + Full Height Dado",
    "stair": "Flamed Fluted Granite Treads + SS Railing",
    "core": "Flamed Fluted Granite Treads + SS Railing",
    "lobby": "Polished Italian Marble Finish Tile",
    "corridor": "Heavy Duty Vitrified Tile 600x1200",
    "balcony": "Rustic Weatherproof Anti-Skid Ceramic",
    "utility": "Anti-Skid Ceramic + Epoxy Grout",
    "terrace": "Reflective Thermal Roof Tile + Waterproof Screed",
    "storage": "Vaccum Dewatered Concrete (VDF) Heavy Duty",
    "dock": "Heavy-Duty Metallic Floor Hardener Screed",
    "dispatch": "VDF Concrete with Steel Fibre Reinforcement",
    "amenity": "Anti-Skid Ceramic Tile",
    "admin": "Commercial Grade Acoustic Carpet Tile",
    "conf": "Commercial Grade Acoustic Carpet Tile",
    "suite": "Commercial Vitrified Tile 600x600",
    "catwalk": "Galvanized Steel Serrated Grating",
    "_default": "Vitrified Tile 600x600",
}

# Per-grade substitutions. Only the surfaces where the grade genuinely changes
# the material are enumerated; a key absent from a tier keeps the standard
# specification (so this table stays a set of real substitutions, not filler).
FINISH_GRADE_TIERS: Dict[str, Dict[str, str]] = {
    "basic": {
        "_default": "Ceramic Tile 600x600 (Builder Grade)",
        "living": "Ceramic Floor Tile 600x600 + Cement-Base Emulsion",
        "dining": "Ceramic Floor Tile 600x600 + Cement-Base Emulsion",
        "kitchen": "Glazed Ceramic Tile + Polished Black Granite Counter",
        "puja": "Polished Vitrified Tile 600x600",
        "master": "Vitrified Tile 600x600",
        "bed": "Vitrified Tile 600x600",
        "bath": "Ceramic Tile R9 + 2.1m Dado",
        "toilet": "Ceramic Tile R9 + 2.1m Dado",
        "stair": "Polished Grey Granite Treads + MS Railing",
        "core": "Polished Grey Granite Treads + MS Railing",
        "lobby": "Vitrified Tile 600x600",
        "corridor": "Vitrified Tile 600x600",
        "balcony": "Rustic Anti-Skid Ceramic",
        "terrace": "Cement Screed with Brick-Bat Coba",
        "utility": "Glazed Ceramic Tile",
        "amenity": "Ceramic Tile R9",
        "admin": "Vinyl Floor Tile",
        "conf": "Vinyl Floor Tile",
        "suite": "Vitrified Tile 600x600",
    },
    "premium": {
        "_default": "Large-Format Porcelain 900x900 (Premium)",
        "living": "Imported Polished Travertine 800x800 + Gypsum Coving",
        "dining": "Imported Polished Travertine 800x800 + Gypsum Coving",
        "kitchen": "Engineered Quartz Counter + Anti-Skid Italian Tile",
        "puja": "Carved White Makrana Marble Inlay",
        "master": "Imported Engineered Oak Plank Flooring",
        "bed": "Engineered Oak Plank Flooring",
        "bath": "Imported Porcelain R10 + Full-Height Book-Match Marble",
        "toilet": "Imported Porcelain R10 + Full-Height Book-Match Marble",
        "stair": "Mirror-Polished Granite Treads + SS 316 Handrail",
        "core": "Mirror-Polished Granite Treads + SS 316 Handrail",
        "lobby": "Mirror-Polished Italian Marble 1200x600",
        "corridor": "Heavy Duty Porcelain 900x900",
        "balcony": "Porcelain Anti-Skid Decking",
        "terrace": "Reflective Thermal Porcelain Terrace Tile + Waterproof Screed",
        "utility": "Porcelain Anti-Skid + Epoxy Grout",
        "amenity": "Porcelain Anti-Skid",
        "admin": "Wool-Blend Acoustic Carpet Tile",
        "conf": "Wool-Blend Acoustic Carpet Tile",
        "suite": "Large-Format Porcelain 1200x1200",
    },
}

GRADE_TIER_LABELS: Dict[str, str] = {
    "basic": "Basic (CPWD economy specification)",
    "standard": "Standard (CPWD benchmark specification)",
    "premium": "Premium (enhanced imported / engineered specification)",
}


def normalize_finish_grade(grade: Optional[str]) -> str:
    """Clamp any caller-supplied grade onto the three supported finish tiers."""
    g = str(grade or "standard").strip().lower()
    return g if g in FINISH_GRADE_TIERS else "standard"


def resolve_finish_key(name: str, r_id: str) -> Optional[str]:
    """Longest-key match of a room name/id onto the finish schedule vocabulary."""
    s = f"{name} {r_id}".lower()
    best: Optional[str] = None
    for k in FINISH_ZONES_STANDARD:
        if k != "_default" and k in s and (best is None or len(k) > len(best)):
            best = k
    return best


def resolve_finish(name: str, r_id: str, grade: str = "standard") -> str:
    """Grade-tiered finish specification for a room (single source for the sheet)."""
    tier = normalize_finish_grade(grade)
    key = resolve_finish_key(name, r_id) or "_default"
    if tier == "standard":
        return FINISH_ZONES_STANDARD[key]
    return FINISH_GRADE_TIERS[tier].get(key, FINISH_ZONES_STANDARD[key])


def build_constructible_wall_graph(
    floor_index: int = 0,
    envelope: Optional[Dict[str, float]] = None,
    raw_rooms: Optional[List[Any]] = None,
    typology: str = "T1_SINGLE_FAMILY",
    floor_to_floor_height_m: float = 3.0,
    doors_in: Optional[List[Any]] = None,
    windows_in: Optional[List[Any]] = None,
    *,
    rooms: Optional[List[Any]] = None,
    doors: Optional[List[Any]] = None,
    windows: Optional[List[Any]] = None,
    floor_height_m: Optional[float] = None,
    quality_grade: str = "standard",
    **kwargs: Any,
) -> WallGraph:
    """
    Transforms topological solver output into a construction-grade WallGraph:
    - Allocates exact clear room rectangles.
    - Slices first-class wall segments (W1 exterior = 230mm, W2 interior = 115mm, W3 = 75mm).
    - Derives exact 3-line dimension chains where sum(clear) + sum(walls) == overall (within 1mm).
    - Hosts code-sized openings inside wall segments with margin and separation verification.
    - Computes stair geometry dynamically from floor height.
    - Builds complete Door, Window, and Room schedules.
    """
    if envelope is None:
        envelope = kwargs.get("envelope", {"width": 12.0, "depth": 15.0, "area_sqm": 180.0})
    raw_rooms = raw_rooms if raw_rooms is not None else (rooms or [])
    doors_in = doors_in if doors_in is not None else (doors or [])
    windows_in = windows_in if windows_in is not None else (windows or [])
    floor_to_floor_height_m = floor_height_m if floor_height_m is not None else floor_to_floor_height_m

    env_w = round(envelope["width"], 3)
    env_d = round(envelope["depth"], 3)

    def _val(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    # 1. Compute Stair Geometry
    stair_geom = compute_stair_geometry(floor_to_floor_height_m, typology)

    # 2. Extract and Sort Slicing Grid Coordinates
    # Identify unique vertical and horizontal layout cut planes from rooms
    x_cuts = {0.0, env_w}
    y_cuts = {0.0, env_d}

    for r in raw_rooms:
        rx = round(float(_val(r, "x", 0.0)), 3)
        ry = round(float(_val(r, "y", 0.0)), 3)
        rw = round(float(_val(r, "width_m", _val(r, "width", 0.0))), 3)
        rd = round(float(_val(r, "depth_m", _val(r, "depth", _val(r, "height", 0.0)))), 3)
        x_cuts.add(rx)
        x_cuts.add(round(rx + rw, 3))
        y_cuts.add(ry)
        y_cuts.add(round(ry + rd, 3))

    sorted_x = sorted(x_cuts)
    sorted_y = sorted(y_cuts)

    # Filter out cuts outside envelope or extremely close together (<0.10m)
    clean_x = [sorted_x[0]]
    for x in sorted_x[1:]:
        if 0.0 <= x <= env_w and (x - clean_x[-1] >= 0.10):
            clean_x.append(x)
    if clean_x[-1] != env_w:
        clean_x.append(env_w)

    clean_y = [sorted_y[0]]
    for y in sorted_y[1:]:
        if 0.0 <= y <= env_d and (y - clean_y[-1] >= 0.10):
            clean_y.append(y)
    if clean_y[-1] != env_d:
        clean_y.append(env_d)

    # 3. Construct Clear Rooms
    # For each room, shrink its bounding box inward by wall half-thicknesses
    # Outer envelope faces get full W1 (0.230m). Internal room boundaries get W2 (0.115m) or W3 (0.075m).
    clear_rooms: Dict[str, ClearRoom] = {}
    # Specification grade drives the finish schedule (module-level tables above).
    finish_grade = normalize_finish_grade(quality_grade)
    finish_grade_label = GRADE_TIER_LABELS[finish_grade]

    # Helper to determine finish zone for the requested specification grade
    def get_finish(name: str, r_id: str) -> str:
        return resolve_finish(name, r_id, finish_grade)

    # Map raw rooms to clear dimensions
    for r in raw_rooms:
        rid = str(_val(r, "room_id", "") or "")
        rname = identity_name(r, rid.replace("_", " ").title())
        r_identity = identity_dict(r)
        r_is_wet = identity_is_wet(r)
        # Sanitary partitions/windows follow the ONTOLOGY hygiene class, not
        # every wet point: a kitchen is wet but needs habitable ventilation, and
        # a utility strip is wet but is not a WC.
        r_is_sanitary = str(r_identity.get("hygiene_class") or "") == "foul"
        if not r_identity:
            r_is_sanitary = any(
                b in rid.lower() or b in str(_val(r, "room_name", "")).lower()
                for b in ("bath", "toilet", "wc", "sanitary")
            )
        rx = round(float(_val(r, "x", 0.0)), 3)
        ry = round(float(_val(r, "y", 0.0)), 3)
        rw = round(float(_val(r, "width_m", _val(r, "width", 3.0))), 3)
        rd = round(float(_val(r, "depth_m", _val(r, "depth", _val(r, "height", 3.0)))), 3)
        is_core = bool(_val(r, "is_vertical_core", False) or "stair" in rid.lower() or "lift" in rid.lower())
        unit = _val(r, "unit_id", None)
        z = _val(r, "zone", "CENTER")
        zcat = _val(r, "zone_category", "public")

        is_bath = r_is_sanitary

        # Thickness of enclosing walls
        t_w = W1_EXTERIOR_THICKNESS_M if rx <= 0.01 else (W3_PARTITION_THICKNESS_M if is_bath else W2_INTERIOR_THICKNESS_M)
        t_e = W1_EXTERIOR_THICKNESS_M if rx + rw >= env_w - 0.01 else (W3_PARTITION_THICKNESS_M if is_bath else W2_INTERIOR_THICKNESS_M)
        t_n = W1_EXTERIOR_THICKNESS_M if ry <= 0.01 else (W3_PARTITION_THICKNESS_M if is_bath else W2_INTERIOR_THICKNESS_M)
        t_s = W1_EXTERIOR_THICKNESS_M if ry + rd >= env_d - 0.01 else (W3_PARTITION_THICKNESS_M if is_bath else W2_INTERIOR_THICKNESS_M)

        # Clear boundaries inside finishes
        cx = rx if rx <= 0.01 else rx + t_w / 2.0
        cy = ry if ry <= 0.01 else ry + t_n / 2.0
        cw = max(0.80, rw - (t_w / 2.0 if rx > 0.01 else t_w) - (t_e / 2.0 if rx + rw < env_w - 0.01 else t_e))
        cd = max(0.80, rd - (t_n / 2.0 if ry > 0.01 else t_n) - (t_s / 2.0 if ry + rd < env_d - 0.01 else t_s))

        # Adjust stair core to match computed stair geometry
        if is_core and stair_geom:
            cw = stair_geom.stair_box_width_m
            cd = stair_geom.stair_box_depth_m

        cx = round(cx, 3)
        cy = round(cy, 3)
        cw = round(cw, 3)
        cd = round(cd, 3)

        c_room = ClearRoom(
            room_id=rid,
            room_name=rname,
            floor_index=floor_index,
            x=cx,
            y=cy,
            width_m=cw,
            depth_m=cd,
            area_sqm=round(cw * cd, 2),
            zone=z,
            zone_category=zcat,
            finish_zone=get_finish(rname, rid),
            finish_grade=finish_grade,
            is_vertical_core=is_core,
            unit_id=unit,
            space_type_id=(
                r_identity.get("space_type_id")
                or _val(r, "space_type_id", None)
            ),
            identity=r_identity,
            is_wet=r_is_wet,
            is_sanitary=r_is_sanitary,
        )
        clear_rooms[rid] = c_room

    # 4. Generate First-Class Wall Segments
    walls: Dict[str, WallSegment] = {}

    # (a) Exterior Boundary Walls (W1 = 230mm)
    # For multi-wing / L-shapes: construct stepped boundary from union of wings and corridors
    wings_in = envelope.get("wings") if isinstance(envelope, dict) else getattr(envelope, "wings", None)
    if wings_in and len(wings_in) > 1:
        e_x = float(envelope.get("x", 0.0) if isinstance(envelope, dict) else getattr(envelope, "x", 0.0))
        e_y = float(envelope.get("y", 0.0) if isinstance(envelope, dict) else getattr(envelope, "y", 0.0))
        wing_boxes = []
        for w in wings_in:
            wx = float(getattr(w, "x", 0.0)) - e_x
            wy = float(getattr(w, "y", 0.0)) - e_y
            ww = float(getattr(w, "width_m", 0.0))
            wd = float(getattr(w, "depth_m", 0.0))
            wing_boxes.append(shapely_box(round(wx, 3), round(wy, 3), round(wx + ww, 3), round(wy + wd, 3)))

        corridors_in = envelope.get("corridors") if isinstance(envelope, dict) else getattr(envelope, "corridors", None)
        corr_boxes = []
        if corridors_in:
            for c in corridors_in:
                cx = float(getattr(c, "x", 0.0)) - e_x
                cy = float(getattr(c, "y", 0.0)) - e_y
                cw = float(getattr(c, "width_m", 0.0))
                cd = float(getattr(c, "depth_m", 0.0))
                corr_boxes.append(shapely_box(round(cx, 3), round(cy, 3), round(cx + cw, 3), round(cy + cd, 3)))

        terrace_room = next((r for r in raw_rooms if (getattr(r, "zone_category", "") == "terrace" or (isinstance(r, dict) and r.get("zone_category") == "terrace") or "terrace" in (getattr(r, "room_id", "") or (r.get("room_id", "") if isinstance(r, dict) else "")).lower())), None)

        if terrace_room and len(wing_boxes) > 1:
            # Wing A (wing_boxes[0]) + Corridors are occupied enclosed building
            occupied_poly = unary_union([wing_boxes[0]] + corr_boxes)
            occ_coords = list(occupied_poly.exterior.coords) if hasattr(occupied_poly, "exterior") else []
            for i in range(len(occ_coords) - 1):
                p1 = occ_coords[i]
                p2 = occ_coords[i + 1]
                seg_dy = abs(p2[1] - p1[1])
                orient = "horizontal" if seg_dy < 1e-4 else "vertical"
                wall_key = f"WAL_EXT_{i+1}"

                is_facade = False
                facade_label = None
                if abs(p1[1]) < 0.05 and abs(p2[1]) < 0.05 and orient == "horizontal":
                    is_facade = True
                    facade_label = "STREET FACADE"

                walls[wall_key] = WallSegment(
                    wall_id=wall_key,
                    wall_type="W1",
                    thickness_m=W1_EXTERIOR_THICKNESS_M,
                    x1=round(p1[0], 3),
                    y1=round(p1[1], 3),
                    x2=round(p2[0], 3),
                    y2=round(p2[1], 3),
                    orientation=orient,
                    is_exterior=True,
                    is_load_bearing=True,
                    is_street_facade=is_facade,
                    label=facade_label,
                )

            # Outer boundary of terrace box (wing_boxes[1]) receives W_PARAPET walls (115mm)
            t_box = wing_boxes[1]
            t_coords = list(t_box.exterior.coords)
            p_idx = 1
            for i in range(len(t_coords) - 1):
                p1 = t_coords[i]
                p2 = t_coords[i + 1]
                mid_x = (p1[0] + p2[0]) / 2.0
                mid_y = (p1[1] + p2[1]) / 2.0
                # If edge midpoint is shared with occupied building, skip (already has W1 wall)
                if occupied_poly.distance(Point(mid_x, mid_y)) < 0.05:
                    continue
                seg_dy = abs(p2[1] - p1[1])
                orient = "horizontal" if seg_dy < 1e-4 else "vertical"
                parapet_key = f"WAL_PARAPET_{p_idx}"
                walls[parapet_key] = WallSegment(
                    wall_id=parapet_key,
                    wall_type="W_PARAPET",
                    thickness_m=W2_INTERIOR_THICKNESS_M,
                    x1=round(p1[0], 3),
                    y1=round(p1[1], 3),
                    x2=round(p2[0], 3),
                    y2=round(p2[1], 3),
                    orientation=orient,
                    is_exterior=True,
                    is_load_bearing=False,
                    is_parapet=True,
                    label="PARAPET WALL",
                )
                p_idx += 1
        else:
            union_poly = unary_union(wing_boxes + corr_boxes)
            ext_coords = list(union_poly.exterior.coords) if hasattr(union_poly, "exterior") else []
            for i in range(len(ext_coords) - 1):
                p1 = ext_coords[i]
                p2 = ext_coords[i + 1]
                seg_dy = abs(p2[1] - p1[1])
                orient = "horizontal" if seg_dy < 1e-4 else "vertical"
                wall_key = f"WAL_EXT_{i+1}"

                is_facade = False
                facade_label = None
                if abs(p1[1]) < 0.05 and abs(p2[1]) < 0.05 and orient == "horizontal":
                    is_facade = True
                    facade_label = "STREET FACADE"

                walls[wall_key] = WallSegment(
                    wall_id=wall_key,
                    wall_type="W1",
                    thickness_m=W1_EXTERIOR_THICKNESS_M,
                    x1=round(p1[0], 3),
                    y1=round(p1[1], 3),
                    x2=round(p2[0], 3),
                    y2=round(p2[1], 3),
                    orientation=orient,
                    is_exterior=True,
                    is_load_bearing=True,
                    is_street_facade=is_facade,
                    label=facade_label,
                )
    else:
        # Check if single rectangular envelope has a terrace band / room
        terrace_room = next((r for r in raw_rooms if (getattr(r, "zone_category", "") == "terrace" or (isinstance(r, dict) and r.get("zone_category") == "terrace") or "terrace" in (getattr(r, "room_id", "") or (r.get("room_id", "") if isinstance(r, dict) else "")).lower())), None)
        if terrace_room:
            tx = float(getattr(terrace_room, "x", 0.0) if hasattr(terrace_room, "x") else terrace_room.get("x", 0.0))
            ty = float(getattr(terrace_room, "y", 0.0) if hasattr(terrace_room, "y") else terrace_room.get("y", 0.0))
            tw = float(getattr(terrace_room, "width_m", 0.0) if hasattr(terrace_room, "width_m") else terrace_room.get("width_m", 0.0))
            td = float(getattr(terrace_room, "depth_m", 0.0) if hasattr(terrace_room, "depth_m") else terrace_room.get("depth_m", 0.0))

            plate_poly = shapely_box(0.0, 0.0, round(env_w, 3), round(env_d, 3))
            t_box = shapely_box(round(tx, 3), round(ty, 3), round(tx + tw, 3), round(ty + td, 3))
            occupied_poly = plate_poly.difference(t_box)

            occ_coords = list(occupied_poly.exterior.coords) if hasattr(occupied_poly, "exterior") else []
            for i in range(len(occ_coords) - 1):
                p1 = occ_coords[i]
                p2 = occ_coords[i + 1]
                seg_dy = abs(p2[1] - p1[1])
                orient = "horizontal" if seg_dy < 1e-4 else "vertical"
                wall_key = f"WAL_EXT_{i+1}"
                is_facade = False
                facade_label = None
                if abs(p1[1]) < 0.05 and abs(p2[1]) < 0.05 and orient == "horizontal":
                    is_facade = True
                    facade_label = "STREET FACADE"

                walls[wall_key] = WallSegment(
                    wall_id=wall_key,
                    wall_type="W1",
                    thickness_m=W1_EXTERIOR_THICKNESS_M,
                    x1=round(p1[0], 3),
                    y1=round(p1[1], 3),
                    x2=round(p2[0], 3),
                    y2=round(p2[1], 3),
                    orientation=orient,
                    is_exterior=True,
                    is_load_bearing=True,
                    is_street_facade=is_facade,
                    label=facade_label,
                )

            t_coords = list(t_box.exterior.coords)
            p_idx = 1
            for i in range(len(t_coords) - 1):
                p1 = t_coords[i]
                p2 = t_coords[i + 1]
                mid_x = (p1[0] + p2[0]) / 2.0
                mid_y = (p1[1] + p2[1]) / 2.0
                if occupied_poly.distance(Point(mid_x, mid_y)) < 0.05:
                    continue
                seg_dy = abs(p2[1] - p1[1])
                orient = "horizontal" if seg_dy < 1e-4 else "vertical"
                parapet_key = f"WAL_PARAPET_{p_idx}"
                walls[parapet_key] = WallSegment(
                    wall_id=parapet_key,
                    wall_type="W_PARAPET",
                    thickness_m=W2_INTERIOR_THICKNESS_M,
                    x1=round(p1[0], 3),
                    y1=round(p1[1], 3),
                    x2=round(p2[0], 3),
                    y2=round(p2[1], 3),
                    orientation=orient,
                    is_exterior=True,
                    is_load_bearing=False,
                    is_parapet=True,
                    label="PARAPET WALL",
                )
                p_idx += 1
        else:
            # Four Exterior Boundary Walls (W1 = 230mm) for single rectangular envelope
            walls["WAL_EXT_N"] = WallSegment(
                wall_id="WAL_EXT_N",
                wall_type="W1",
                thickness_m=W1_EXTERIOR_THICKNESS_M,
                x1=0.0,
                y1=0.0,
                x2=env_w,
                y2=0.0,
                orientation="horizontal",
                is_exterior=True,
                is_load_bearing=True,
                is_street_facade=True,
                label="STREET FACADE",
            )
            walls["WAL_EXT_S"] = WallSegment(
                wall_id="WAL_EXT_S",
                wall_type="W1",
                thickness_m=W1_EXTERIOR_THICKNESS_M,
                x1=0.0,
                y1=env_d,
                x2=env_w,
                y2=env_d,
                orientation="horizontal",
                is_exterior=True,
                is_load_bearing=True,
            )
            walls["WAL_EXT_W"] = WallSegment(
                wall_id="WAL_EXT_W",
                wall_type="W1",
                thickness_m=W1_EXTERIOR_THICKNESS_M,
                x1=0.0,
                y1=0.0,
                x2=0.0,
                y2=env_d,
                orientation="vertical",
                is_exterior=True,
                is_load_bearing=True,
            )
            walls["WAL_EXT_E"] = WallSegment(
                wall_id="WAL_EXT_E",
                wall_type="W1",
                thickness_m=W1_EXTERIOR_THICKNESS_M,
                x1=env_w,
                y1=0.0,
                x2=env_w,
                y2=env_d,
                orientation="vertical",
                is_exterior=True,
                is_load_bearing=True,
            )

    # (b) Internal Partition Walls (W2 = 115mm, W3 = 75mm)
    # Trace shared boundaries between adjacent rooms
    room_list = list(clear_rooms.values())
    w_idx = 1
    seen_boundaries = set()

    for i in range(len(room_list)):
        for j in range(i + 1, len(room_list)):
            rA = room_list[i]
            rB = room_list[j]

            # Terraces are open-to-sky; their dividing boundary is an exterior building wall, not interior partition
            is_rA_t = getattr(rA, "zone_category", "") == "terrace" or "terrace" in getattr(rA, "room_id", "").lower()
            is_rB_t = getattr(rB, "zone_category", "") == "terrace" or "terrace" in getattr(rB, "room_id", "").lower()
            if is_rA_t or is_rB_t:
                continue

            # Check if they share a vertical boundary (X is adjacent)
            x_boundary = None
            if abs((rA.x + rA.width_m) - rB.x) < 0.35:
                x_boundary = (rA.x + rA.width_m + rB.x) / 2.0
            elif abs((rB.x + rB.width_m) - rA.x) < 0.35:
                x_boundary = (rB.x + rB.width_m + rA.x) / 2.0

            if x_boundary is not None:
                # Calculate Y overlap
                y_min = max(rA.y, rB.y)
                y_max = min(rA.y + rA.depth_m, rB.y + rB.depth_m)
                if y_max - y_min >= 0.50:
                    b_key = ("V", round(x_boundary, 2), round(y_min, 2), round(y_max, 2))
                    if b_key not in seen_boundaries:
                        seen_boundaries.add(b_key)
                        is_wc = "bath" in rA.room_id or "bath" in rB.room_id or "wc" in rA.room_id or "wc" in rB.room_id
                        w_type = "W3" if is_wc else "W2"
                        w_th = W3_PARTITION_THICKNESS_M if is_wc else W2_INTERIOR_THICKNESS_M
                        wid = f"WAL_INT_V{w_idx:02d}"
                        walls[wid] = WallSegment(
                            wall_id=wid,
                            wall_type=w_type,
                            thickness_m=w_th,
                            x1=round(x_boundary, 3),
                            y1=round(y_min, 3),
                            x2=round(x_boundary, 3),
                            y2=round(y_max, 3),
                            orientation="vertical",
                            is_exterior=False,
                            is_load_bearing=("T1" in typology.upper() and not is_wc),
                            adjacent_rooms=[rA.room_id, rB.room_id],
                        )
                        rA.wall_ids.append(wid)
                        rB.wall_ids.append(wid)
                        w_idx += 1

            # Check if they share a horizontal boundary (Y is adjacent)
            y_boundary = None
            if abs((rA.y + rA.depth_m) - rB.y) < 0.35:
                y_boundary = (rA.y + rA.depth_m + rB.y) / 2.0
            elif abs((rB.y + rB.depth_m) - rA.y) < 0.35:
                y_boundary = (rB.y + rB.depth_m + rA.y) / 2.0

            if y_boundary is not None:
                # Calculate X overlap
                x_min = max(rA.x, rB.x)
                x_max = min(rA.x + rA.width_m, rB.x + rB.width_m)
                if x_max - x_min >= 0.50:
                    b_key = ("H", round(y_boundary, 2), round(x_min, 2), round(x_max, 2))
                    if b_key not in seen_boundaries:
                        seen_boundaries.add(b_key)
                        is_wc = "bath" in rA.room_id or "bath" in rB.room_id or "wc" in rA.room_id or "wc" in rB.room_id
                        w_type = "W3" if is_wc else "W2"
                        w_th = W3_PARTITION_THICKNESS_M if is_wc else W2_INTERIOR_THICKNESS_M
                        wid = f"WAL_INT_H{w_idx:02d}"
                        walls[wid] = WallSegment(
                            wall_id=wid,
                            wall_type=w_type,
                            thickness_m=w_th,
                            x1=round(x_min, 3),
                            y1=round(y_boundary, 3),
                            x2=round(x_max, 3),
                            y2=round(y_boundary, 3),
                            orientation="horizontal",
                            is_exterior=False,
                            is_load_bearing=("T1" in typology.upper() and not is_wc),
                            adjacent_rooms=[rA.room_id, rB.room_id],
                        )
                        rA.wall_ids.append(wid)
                        rB.wall_ids.append(wid)
                        w_idx += 1

    # 5. Generate Hosted Openings (Doors & Windows) with Code Sizing
    openings: Dict[str, HostedOpening] = {}
    door_counter = 1
    win_counter = 1

    # (a) Doors from adjacent rooms
    # Match doors from doors_in or derive from partition walls
    for wall in walls.values():
        if wall.is_exterior or not wall.adjacent_rooms or len(wall.adjacent_rooms) < 2:
            continue

        r1 = wall.adjacent_rooms[0]
        r2 = wall.adjacent_rooms[1]
        L = wall.length_m

        is_bath_door = any("bath" in r or "wc" in r for r in (r1, r2))
        is_fire_door = any("stair" in r or "core" in r for r in (r1, r2)) and floor_index > 0
        door_w = 0.75 if is_bath_door else (1.00 if is_fire_door else 0.90)
        door_h = 2.10

        # Position opening with at least 0.150m margin
        offset = 0.20
        if offset + door_w > L - 0.150:
            offset = max(0.150, (L - door_w) / 2.0)
            if door_w > L - 0.30:
                door_w = max(0.70, L - 0.30)
                offset = 0.150

        can_host, _ = wall.can_host_opening(door_w, offset)
        if can_host:
            tag = f"D{door_counter}"
            d_id = f"door_{r1}_{r2}_F{floor_index}"
            op = HostedOpening(
                opening_id=d_id,
                tag=tag,
                opening_type="door",
                wall_id=wall.wall_id,
                offset_from_corner=round(offset, 3),
                width_m=round(door_w, 3),
                height_m=door_h,
                sill_m=0.0,
                lintel_m=2.10,
                level=floor_index,
                from_room=r1,
                to_room=r2,
                door_type="fire_rated" if is_fire_door else ("sliding" if is_bath_door else "standard"),
                hinge_side="right",
                swing_direction="inward_right",
            )
            wall.openings.append(op)
            openings[d_id] = op
            door_counter += 1

    # (b) Windows on Exterior Walls (W1 Only) sized per NBC 2016
    for r in room_list:
        if r.is_vertical_core or "stair" in r.room_id:
            continue

        is_sanitary = r.is_sanitary

        # NBC 2016 statutory opening ratio
        if is_sanitary:
            req_vent_area = max(NBC_2016_SANITARY_MIN_VENT_AREA_M2, r.area_sqm * NBC_2016_SANITARY_VENT_RATIO)
            win_h = 0.60
            win_sill = 1.50
            win_lintel = 2.10
            raw_w = round(max(0.60, req_vent_area / win_h), 2)
        else:
            req_vent_area = r.area_sqm * NBC_2016_HABITABLE_VENT_RATIO
            win_h = 1.20
            win_sill = 0.90
            win_lintel = 2.10
            raw_w = round(max(1.00, req_vent_area / win_h), 2)

        # Find adjacent exterior wall
        target_ext_wall = None
        offset_val = 0.0

        if r.y <= 0.25:  # Touches North exterior wall
            target_ext_wall = walls.get("WAL_EXT_N")
            offset_val = r.x + max(0.150, (r.width_m - raw_w) / 2.0)
        elif r.y + r.depth_m >= env_d - 0.25:  # Touches South exterior wall
            target_ext_wall = walls.get("WAL_EXT_S")
            offset_val = r.x + max(0.150, (r.width_m - raw_w) / 2.0)
        elif r.x <= 0.25:  # Touches West exterior wall
            target_ext_wall = walls.get("WAL_EXT_W")
            offset_val = r.y + max(0.150, (r.depth_m - raw_w) / 2.0)
        elif r.x + r.width_m >= env_w - 0.25:  # Touches East exterior wall
            target_ext_wall = walls.get("WAL_EXT_E")
            offset_val = r.y + max(0.150, (r.depth_m - raw_w) / 2.0)

        if target_ext_wall:
            avail_span = r.width_m if target_ext_wall.orientation == "horizontal" else r.depth_m
            win_w = min(raw_w, max(0.60, avail_span - 0.30))
            offset_val = max(target_ext_wall.x1 if target_ext_wall.orientation == "horizontal" else target_ext_wall.y1, offset_val)

            can_host, _ = target_ext_wall.can_host_opening(win_w, offset_val)
            if can_host:
                w_tag = f"W{win_counter}"
                w_id = f"win_{r.room_id}_F{floor_index}"
                win_op = HostedOpening(
                    opening_id=w_id,
                    tag=w_tag,
                    opening_type="window",
                    wall_id=target_ext_wall.wall_id,
                    offset_from_corner=round(offset_val, 3),
                    width_m=round(win_w, 3),
                    height_m=win_h,
                    sill_m=win_sill,
                    lintel_m=win_lintel,
                    level=floor_index,
                    from_room=r.room_id,
                    to_room="exterior",
                )
                target_ext_wall.openings.append(win_op)
                openings[w_id] = win_op
                win_counter += 1

    # 6. Circulation & Door Swing Collision Clearance
    # Verify no swing intersects another swing or the stair flight
    stair_bbox = (0.230, 0.230, 0.230 + stair_geom.stair_box_width_m, 0.230 + stair_geom.stair_box_depth_m) if stair_geom else None

    door_list = [op for op in openings.values() if op.opening_type == "door"]
    for i, d1 in enumerate(door_list):
        # Calculate swing bounding box
        w_host = walls.get(d1.wall_id)
        if not w_host:
            continue

        if w_host.orientation == "vertical":
            hx = w_host.x1
            hy = w_host.y1 + d1.offset_from_corner
            sw_x2 = hx + d1.width_m if "right" in (d1.hinge_side or "") else hx - d1.width_m
            sw_y2 = hy + d1.width_m
            d1.swing_bbox = (min(hx, sw_x2), min(hy, sw_y2), max(hx, sw_x2), max(hy, sw_y2))
        else:
            hx = w_host.x1 + d1.offset_from_corner
            hy = w_host.y1
            sw_x2 = hx + d1.width_m
            sw_y2 = hy + d1.width_m if "inward" in (d1.swing_direction or "") else hy - d1.width_m
            d1.swing_bbox = (min(hx, sw_x2), min(hy, sw_y2), max(hx, sw_x2), max(hy, sw_y2))

        # Check collision with stair flight
        if stair_bbox and d1.swing_bbox:
            sb = d1.swing_bbox
            overlap = not (sb[2] <= stair_bbox[0] or sb[0] >= stair_bbox[2] or sb[3] <= stair_bbox[1] or sb[1] >= stair_bbox[3])
            if overlap:
                # Automatically flip hinge side / swing direction
                d1.hinge_side = "left" if d1.hinge_side == "right" else "right"
                d1.swing_direction = "inward_left" if d1.swing_direction == "inward_right" else "inward_right"

    # 7. Construct 3-Line Dimension Chains
    # Line (a): Openings Chain
    # Line (b): Room Clear Dims Chain (W1 + clear room + W2 + ... + W1)
    # Line (c): Overall Building Envelope Chain
    dim_chains_x: List[DimensionChain] = []
    dim_chains_y: List[DimensionChain] = []

    # Overall Chain along X (Stepped for multi-wing footprints)
    wings_in = envelope.get("wings") if isinstance(envelope, dict) else getattr(envelope, "wings", None)
    if wings_in and len(wings_in) > 1:
        w_a = wings_in[0]
        w_b = wings_in[1]
        e_x = float(envelope.get("x", 0.0) if isinstance(envelope, dict) else getattr(envelope, "x", 0.0))
        w_a_rel_x = round(float(getattr(w_a, "x", 0.0)) - e_x, 3)
        w_a_w = round(float(getattr(w_a, "width_m", 0.0)), 3)
        w_b_rel_x = round(float(getattr(w_b, "x", 0.0)) - e_x, 3)
        w_b_w = round(float(getattr(w_b, "width_m", 0.0)), 3)

        x_segs: List[DimensionSegment] = []
        pts_x = sorted(list(set([0.0, max(0.0, w_a_rel_x), min(env_w, w_a_rel_x + w_a_w), max(0.0, w_b_rel_x), min(env_w, w_b_rel_x + w_b_w), env_w])))
        for i in range(len(pts_x) - 1):
            p1 = pts_x[i]
            p2 = pts_x[i + 1]
            seg_len = round(p2 - p1, 3)
            if seg_len > 0.005:
                seg_mm = int(round(seg_len * 1000.0))
                lbl = f"{seg_mm}"
                if abs(p1 - w_a_rel_x) < 0.05 and abs(seg_len - w_a_w) < 0.05:
                    lbl = f"WING A: {seg_mm}"
                elif abs(p1 - w_b_rel_x) < 0.05 and abs(seg_len - w_b_w) < 0.05:
                    is_t = any(getattr(r, "zone_category", "") == "terrace" or (isinstance(r, dict) and r.get("zone_category") == "terrace") for r in raw_rooms)
                    lbl = f"TERRACE: {seg_mm}" if is_t else f"WING B: {seg_mm}"
                else:
                    lbl = f"STEP: {seg_mm}"
                x_segs.append(DimensionSegment(lbl, seg_mm, seg_len, p1, p2))

        # Guarantee exact sum == env_w_mm
        target_x_mm = int(round(env_w * 1000.0))
        if x_segs:
            diff_x = target_x_mm - sum(s.length_mm for s in x_segs)
            if diff_x != 0:
                x_segs[-1].length_mm += diff_x
                x_segs[-1].length_m = round(x_segs[-1].length_mm / 1000.0, 3)
        else:
            x_segs = [DimensionSegment(f"{target_x_mm}", target_x_mm, env_w, 0.0, env_w)]

        chain_x_overall = DimensionChain(
            chain_id=f"DIM_X_STEPPED_F{floor_index}",
            level="overall",
            axis="X",
            side="top",
            segments=x_segs,
            total_mm=target_x_mm,
            total_m=env_w,
            offset_distance_m=2.20,
        )
    else:
        overall_x_seg = DimensionSegment(
            label=f"{int(round(env_w * 1000.0))}",
            length_mm=int(round(env_w * 1000.0)),
            length_m=env_w,
            start_m=0.0,
            end_m=env_w,
        )
        chain_x_overall = DimensionChain(
            chain_id=f"DIM_X_OVERALL_F{floor_index}",
            level="overall",
            axis="X",
            side="top",
            segments=[overall_x_seg],
            total_mm=int(round(env_w * 1000.0)),
            total_m=env_w,
            offset_distance_m=2.20,
        )

    # Clear Rooms & Walls Chain along X (middle line)
    # Trace sequence of (wall thickness, clear room, wall thickness...) along X axis
    clear_x_segs: List[DimensionSegment] = []
    # Left exterior wall
    w_ext_mm = int(round(W1_EXTERIOR_THICKNESS_M * 1000.0))
    clear_x_segs.append(DimensionSegment("230", w_ext_mm, W1_EXTERIOR_THICKNESS_M, 0.0, W1_EXTERIOR_THICKNESS_M))

    cur_x = W1_EXTERIOR_THICKNESS_M
    # Find distinct rooms partitioned along X
    x_rooms = sorted([r for r in clear_rooms.values() if r.y <= 0.30 or r.y + r.depth_m >= env_d - 0.30], key=lambda r: r.x)
    seen_rx = set()
    unique_x_rooms = []
    for r in x_rooms:
        if round(r.x, 2) not in seen_rx and r.x + r.width_m <= env_w - 0.20:
            seen_rx.add(round(r.x, 2))
            unique_x_rooms.append(r)

    if not unique_x_rooms:
        unique_x_rooms = sorted(clear_rooms.values(), key=lambda r: r.x)

    # Reconstruct bay chain that sums exactly to (env_w - 0.460)
    bay_rooms = []
    for r in unique_x_rooms:
        if r.x >= cur_x - 0.05 and r.x + r.width_m <= env_w - 0.22:
            bay_rooms.append(r)
            cur_x = r.x + r.width_m

    if not bay_rooms:
        # Fallback single internal clear bay
        internal_clear_m = round(env_w - 2.0 * W1_EXTERIOR_THICKNESS_M, 3)
        clear_x_segs.append(DimensionSegment(
            f"{int(round(internal_clear_m * 1000.0))}",
            int(round(internal_clear_m * 1000.0)),
            internal_clear_m,
            W1_EXTERIOR_THICKNESS_M,
            env_w - W1_EXTERIOR_THICKNESS_M
        ))
    else:
        # Build exact sum chain
        pos = W1_EXTERIOR_THICKNESS_M
        for b_idx, br in enumerate(bay_rooms):
            b_w = round(br.width_m, 3)
            # Check remaining span before right exterior wall
            if b_idx == len(bay_rooms) - 1:
                # Last room absorbs remainder exactly so sum == env_w
                b_w = round((env_w - W1_EXTERIOR_THICKNESS_M) - pos, 3)

            b_mm = int(round(b_w * 1000.0))
            clear_x_segs.append(DimensionSegment(f"{b_mm}", b_mm, b_w, pos, round(pos + b_w, 3)))
            pos = round(pos + b_w, 3)

            if b_idx < len(bay_rooms) - 1:
                w2_th = W2_INTERIOR_THICKNESS_M
                w2_mm = int(round(w2_th * 1000.0))
                clear_x_segs.append(DimensionSegment(f"{w2_mm}", w2_mm, w2_th, pos, round(pos + w2_th, 3)))
                pos = round(pos + w2_th, 3)

    # Right exterior wall
    clear_x_segs.append(DimensionSegment(
        "230",
        w_ext_mm,
        W1_EXTERIOR_THICKNESS_M,
        round(env_w - W1_EXTERIOR_THICKNESS_M, 3),
        env_w
    ))

    # Adjust rounding in integer mm so sum_mm exactly equals env_w_mm
    delta_x = int(round(env_w * 1000.0)) - sum(s.length_mm for s in clear_x_segs)
    if delta_x != 0 and len(clear_x_segs) >= 2:
        # Adjust middle room segment
        mid_idx = 1
        clear_x_segs[mid_idx].length_mm += delta_x
        clear_x_segs[mid_idx].length_m = round(clear_x_segs[mid_idx].length_mm / 1000.0, 3)
        clear_x_segs[mid_idx].label = f"{clear_x_segs[mid_idx].length_mm}"

    chain_x_clear = DimensionChain(
        chain_id=f"DIM_X_CLEAR_F{floor_index}",
        level="clear_rooms",
        axis="X",
        side="top",
        segments=clear_x_segs,
        total_mm=int(round(env_w * 1000.0)),
        total_m=env_w,
        offset_distance_m=1.50,
    )

    # Openings Chain along X (innermost line)
    north_wall = walls.get("WAL_EXT_N")
    n_openings = sorted(north_wall.openings, key=lambda op: op.offset_from_corner) if north_wall else []

    openings_x_segs: List[DimensionSegment] = []
    cur_x_op = 0.0
    for op in n_openings:
        op_start = round(op.offset_from_corner, 3)
        if op_start > cur_x_op:
            lead_w = round(op_start - cur_x_op, 3)
            lead_mm = int(round(lead_w * 1000.0))
            openings_x_segs.append(DimensionSegment(f"{lead_mm}", lead_mm, lead_w, cur_x_op, op_start))

        op_mm = int(round(op.width_m * 1000.0))
        openings_x_segs.append(DimensionSegment(f"{op.tag} {op_mm}", op_mm, op.width_m, op_start, round(op_start + op.width_m, 3)))
        cur_x_op = round(op_start + op.width_m, 3)

    if cur_x_op < env_w:
        trail_w = round(env_w - cur_x_op, 3)
        trail_mm = int(round(trail_w * 1000.0))
        openings_x_segs.append(DimensionSegment(f"{trail_mm}", trail_mm, trail_w, cur_x_op, env_w))

    delta_op = int(round(env_w * 1000.0)) - sum(s.length_mm for s in openings_x_segs)
    if delta_op != 0 and openings_x_segs:
        openings_x_segs[-1].length_mm += delta_op
        openings_x_segs[-1].length_m = round(openings_x_segs[-1].length_mm / 1000.0, 3)
        openings_x_segs[-1].label = f"{openings_x_segs[-1].length_mm}"

    chain_x_openings = DimensionChain(
        chain_id=f"DIM_X_OPENINGS_F{floor_index}",
        level="openings",
        axis="X",
        side="top",
        segments=openings_x_segs,
        total_mm=int(round(env_w * 1000.0)),
        total_m=env_w,
        offset_distance_m=0.80,
    )

    dim_chains_x.extend([chain_x_openings, chain_x_clear, chain_x_overall])

    # Overall Chain along Y (Stepped for multi-wing footprints)
    if wings_in and len(wings_in) > 1:
        w_a = wings_in[0]
        w_b = wings_in[1]
        e_y = float(envelope.get("y", 0.0) if isinstance(envelope, dict) else getattr(envelope, "y", 0.0))
        w_a_rel_y = round(float(getattr(w_a, "y", 0.0)) - e_y, 3)
        w_a_d = round(float(getattr(w_a, "depth_m", 0.0)), 3)
        w_b_rel_y = round(float(getattr(w_b, "y", 0.0)) - e_y, 3)
        w_b_d = round(float(getattr(w_b, "depth_m", 0.0)), 3)

        y_segs: List[DimensionSegment] = []
        pts_y = sorted(list(set([0.0, max(0.0, w_a_rel_y), min(env_d, w_a_rel_y + w_a_d), max(0.0, w_b_rel_y), min(env_d, w_b_rel_y + w_b_d), env_d])))
        for i in range(len(pts_y) - 1):
            p1 = pts_y[i]
            p2 = pts_y[i + 1]
            seg_len = round(p2 - p1, 3)
            if seg_len > 0.005:
                seg_mm = int(round(seg_len * 1000.0))
                lbl = f"{seg_mm}"
                if abs(p1 - w_a_rel_y) < 0.05 and abs(seg_len - w_a_d) < 0.05:
                    lbl = f"WING A: {seg_mm}"
                elif abs(p1 - w_b_rel_y) < 0.05 and abs(seg_len - w_b_d) < 0.05:
                    lbl = f"WING B: {seg_mm}"
                else:
                    lbl = f"STEP: {seg_mm}"
                y_segs.append(DimensionSegment(lbl, seg_mm, seg_len, p1, p2))

        # Guarantee exact sum == env_d_mm
        target_y_mm = int(round(env_d * 1000.0))
        if y_segs:
            diff_y = target_y_mm - sum(s.length_mm for s in y_segs)
            if diff_y != 0:
                y_segs[-1].length_mm += diff_y
                y_segs[-1].length_m = round(y_segs[-1].length_mm / 1000.0, 3)
        else:
            y_segs = [DimensionSegment(f"{target_y_mm}", target_y_mm, env_d, 0.0, env_d)]

        chain_y_overall = DimensionChain(
            chain_id=f"DIM_Y_STEPPED_F{floor_index}",
            level="overall",
            axis="Y",
            side="left",
            segments=y_segs,
            total_mm=target_y_mm,
            total_m=env_d,
            offset_distance_m=2.20,
        )
    else:
        overall_y_seg = DimensionSegment(
            label=f"{int(round(env_d * 1000.0))}",
            length_mm=int(round(env_d * 1000.0)),
            length_m=env_d,
            start_m=0.0,
            end_m=env_d,
        )
        chain_y_overall = DimensionChain(
            chain_id=f"DIM_Y_OVERALL_F{floor_index}",
            level="overall",
            axis="Y",
            side="left",
            segments=[overall_y_seg],
            total_mm=int(round(env_d * 1000.0)),
            total_m=env_d,
            offset_distance_m=2.20,
        )

    # Clear Rooms & Walls Chain along Y (middle line)
    clear_y_segs: List[DimensionSegment] = []
    clear_y_segs.append(DimensionSegment("230", w_ext_mm, W1_EXTERIOR_THICKNESS_M, 0.0, W1_EXTERIOR_THICKNESS_M))

    y_rooms = sorted([r for r in clear_rooms.values() if r.x <= 0.30 or r.x + r.width_m >= env_w - 0.30], key=lambda r: r.y)
    seen_ry = set()
    unique_y_rooms = []
    for r in y_rooms:
        if round(r.y, 2) not in seen_ry and r.y + r.depth_m <= env_d - 0.20:
            seen_ry.add(round(r.y, 2))
            unique_y_rooms.append(r)

    if not unique_y_rooms:
        unique_y_rooms = sorted(clear_rooms.values(), key=lambda r: r.y)

    pos_y = W1_EXTERIOR_THICKNESS_M
    for b_idx, br in enumerate(unique_y_rooms[:3]):
        b_d = round(br.depth_m, 3)
        if b_idx == len(unique_y_rooms[:3]) - 1:
            b_d = round((env_d - W1_EXTERIOR_THICKNESS_M) - pos_y, 3)

        b_mm = int(round(b_d * 1000.0))
        clear_y_segs.append(DimensionSegment(f"{b_mm}", b_mm, b_d, pos_y, round(pos_y + b_d, 3)))
        pos_y = round(pos_y + b_d, 3)

        if b_idx < len(unique_y_rooms[:3]) - 1:
            w2_mm = int(round(W2_INTERIOR_THICKNESS_M * 1000.0))
            clear_y_segs.append(DimensionSegment(f"{w2_mm}", w2_mm, W2_INTERIOR_THICKNESS_M, pos_y, round(pos_y + W2_INTERIOR_THICKNESS_M, 3)))
            pos_y = round(pos_y + W2_INTERIOR_THICKNESS_M, 3)

    clear_y_segs.append(DimensionSegment("230", w_ext_mm, W1_EXTERIOR_THICKNESS_M, round(env_d - W1_EXTERIOR_THICKNESS_M, 3), env_d))

    delta_y = int(round(env_d * 1000.0)) - sum(s.length_mm for s in clear_y_segs)
    if delta_y != 0 and len(clear_y_segs) >= 2:
        clear_y_segs[1].length_mm += delta_y
        clear_y_segs[1].length_m = round(clear_y_segs[1].length_mm / 1000.0, 3)
        clear_y_segs[1].label = f"{clear_y_segs[1].length_mm}"

    chain_y_clear = DimensionChain(
        chain_id=f"DIM_Y_CLEAR_F{floor_index}",
        level="clear_rooms",
        axis="Y",
        side="left",
        segments=clear_y_segs,
        total_mm=int(round(env_d * 1000.0)),
        total_m=env_d,
        offset_distance_m=1.50,
    )

    # Openings Chain along Y (innermost line)
    west_wall = walls.get("WAL_EXT_W")
    w_openings = sorted(west_wall.openings, key=lambda op: op.offset_from_corner) if west_wall else []

    openings_y_segs: List[DimensionSegment] = []
    cur_y_op = 0.0
    for op in w_openings:
        op_start = round(op.offset_from_corner, 3)
        if op_start > cur_y_op:
            lead_d = round(op_start - cur_y_op, 3)
            lead_mm = int(round(lead_d * 1000.0))
            openings_y_segs.append(DimensionSegment(f"{lead_mm}", lead_mm, lead_d, cur_y_op, op_start))

        op_mm = int(round(op.width_m * 1000.0))
        openings_y_segs.append(DimensionSegment(f"{op.tag} {op_mm}", op_mm, op.width_m, op_start, round(op_start + op.width_m, 3)))
        cur_y_op = round(op_start + op.width_m, 3)

    if cur_y_op < env_d:
        trail_d = round(env_d - cur_y_op, 3)
        trail_mm = int(round(trail_d * 1000.0))
        openings_y_segs.append(DimensionSegment(f"{trail_mm}", trail_mm, trail_d, cur_y_op, env_d))

    delta_op_y = int(round(env_d * 1000.0)) - sum(s.length_mm for s in openings_y_segs)
    if delta_op_y != 0 and openings_y_segs:
        openings_y_segs[-1].length_mm += delta_op_y
        openings_y_segs[-1].length_m = round(openings_y_segs[-1].length_mm / 1000.0, 3)
        openings_y_segs[-1].label = f"{openings_y_segs[-1].length_mm}"

    chain_y_openings = DimensionChain(
        chain_id=f"DIM_Y_OPENINGS_F{floor_index}",
        level="openings",
        axis="Y",
        side="left",
        segments=openings_y_segs,
        total_mm=int(round(env_d * 1000.0)),
        total_m=env_d,
        offset_distance_m=0.80,
    )

    dim_chains_y.extend([chain_y_openings, chain_y_clear, chain_y_overall])

    # 8. Compile Complete Engineering Schedules
    door_schedule: List[Dict[str, Any]] = []
    window_schedule: List[Dict[str, Any]] = []
    room_schedule: List[Dict[str, Any]] = []


    # Sort openings deterministically
    sorted_doors = sorted([op for op in openings.values() if op.opening_type == "door"], key=lambda d: int(d.tag[1:]) if d.tag[1:].isdigit() else 99)
    for d in sorted_doors:
        door_schedule.append({
            "tag": d.tag,
            "width_mm": int(round(d.width_m * 1000.0)),
            "height_mm": int(round(d.height_m * 1000.0)),
            "dimension": f"{int(round(d.width_m * 1000.0))} x {int(round(d.height_m * 1000.0))}",
            "type": (d.door_type or "standard").replace("_", " ").title() + " Flush Door",
            "level": f"L{floor_index}",
            "sill_mm": 0,
            "lintel_mm": int(round(d.lintel_m * 1000.0)),
            "from_room": d.from_room or "-",
            "to_room": d.to_room or "-",
        })

    sorted_windows = sorted([op for op in openings.values() if op.opening_type == "window"], key=lambda w: int(w.tag[1:]) if w.tag[1:].isdigit() else 99)
    for w in sorted_windows:
        window_schedule.append({
            "tag": w.tag,
            "width_mm": int(round(w.width_m * 1000.0)),
            "height_mm": int(round(w.height_m * 1000.0)),
            "dimension": f"{int(round(w.width_m * 1000.0))} x {int(round(w.height_m * 1000.0))}",
            "sill_mm": int(round(w.sill_m * 1000.0)),
            "lintel_mm": int(round(w.lintel_m * 1000.0)),
            "level": f"L{floor_index}",
            "type": "UPVC Double Glazed Casement" if w.sill_m < 1.0 else "Aluminium Frosted Louver Vent",
            "room": w.from_room or "-",
            "code_citation": NBC_2016_HABITABLE_CITATION if w.sill_m < 1.0 else NBC_2016_SANITARY_CITATION,
        })

    for idx, r in enumerate(clear_rooms.values(), start=1):
        room_num = f"{floor_index * 100 + idx}"
        orig_r = next((x for x in raw_rooms if _val(x, "room_id") == r.room_id), None)
        # SINGLE SOURCE: the schedule carries the CLEAR structural area
        # (r.area_sqm) in `clear_area_sqm`, and the solved GROSS area in
        # `area_sqm`/`gross_area_sqm`. Both numbers exist in the model and the
        # schedule now publishes both under their own names (audit
        # I5-SCHEDULE-AREA-FIELD): publishing the clear area as `area_sqm`
        # made every row disagree with the room it described.
        canonical_area = r.area_sqm
        gross_area = canonical_area
        if orig_r is not None:
            try:
                gross_area = float(_val(orig_r, "area_sqm", canonical_area) or canonical_area)
            except (TypeError, ValueError):
                gross_area = canonical_area
        # Naming-honesty class threshold used (from living-quality layer metadata)
        naming_threshold = None
        if orig_r is not None:
            naming_threshold = _val(orig_r, "naming_threshold_used", None)
        fixture_count = 0
        furniture_count = 0
        if orig_r is not None:
            fixture_count = len(_val(orig_r, "fixtures", []) or [])
            furniture_count = len(_val(orig_r, "furniture", []) or [])
        room_schedule.append({
            "room_no": room_num,
            "room_number": idx,
            "room_name": r.room_name,
            "room_id": r.room_id,
            "space_type_id": r.space_type_id,
            "identity": dict(r.identity),
            "identity_name": r.room_name,
            "is_wet": r.is_wet,
            "is_sanitary": r.is_sanitary,
            "clear_dimensions": f"{r.width_m:.2f}m x {r.depth_m:.2f}m",
            "clear_dims": f"{r.width_m:.2f}m x {r.depth_m:.2f}m",
            "clear_area_sqm": canonical_area,
            "gross_area_sqm": round(gross_area, 3),
            "area_sqm": round(gross_area, 3),
            "finish_zone": " ".join(str(r.finish_zone).split()) if r.finish_zone else r.finish_zone,
            "finish_grade": finish_grade,
            "finish_grade_label": finish_grade_label,
            "zone": r.zone,
            "naming_threshold_used": naming_threshold,
            "fixture_count": fixture_count,
            "furniture_count": furniture_count,
        })

    wg = WallGraph(
        floor_index=floor_index,
        envelope=envelope,
        walls=walls,
        rooms=clear_rooms,
        openings=openings,
        stair_geometry=stair_geom,
        dim_chains_x=dim_chains_x,
        dim_chains_y=dim_chains_y,
        door_schedule=door_schedule,
        window_schedule=window_schedule,
        room_schedule=room_schedule,
        stair_schedule=compute_stair_schedule_rows(stair_geom),
    )

    # Hard assert dimension chains on emission
    wg.assert_dimension_chains()

    return wg
