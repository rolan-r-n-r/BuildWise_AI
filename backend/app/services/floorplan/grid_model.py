from dataclasses import dataclass
from typing import Tuple, Dict, Any, Optional

@dataclass(frozen=True)
class RoomBox:
    room_id: str
    r: int
    c: int
    w: int
    h: int

    @property
    def r_end(self) -> int:
        return self.r + self.h

    @property
    def c_end(self) -> int:
        return self.c + self.w

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def centroid(self) -> Tuple[float, float]:
        return (self.r + self.h / 2.0, self.c + self.w / 2.0)

    def overlaps(self, other: "RoomBox") -> bool:
        if self.r_end <= other.r or other.r_end <= self.r:
            return False
        if self.c_end <= other.c or other.c_end <= self.c:
            return False
        return True

    def shares_wall_with(self, other: "RoomBox") -> bool:
        # Check horizontal adjacency (touching along vertical wall)
        if self.c_end == other.c or other.c_end == self.c:
            overlap_h = max(0, min(self.r_end, other.r_end) - max(self.r, other.r))
            if overlap_h > 0:
                return True
        # Check vertical adjacency (touching along horizontal wall)
        if self.r_end == other.r or other.r_end == self.r:
            overlap_w = max(0, min(self.c_end, other.c_end) - max(self.c, other.c))
            if overlap_w > 0:
                return True
        return False

    def manhattan_distance_to(self, other: "RoomBox") -> int:
        # Distance between bounding boxes (0 if touching/sharing wall)
        dr = 0
        if self.r_end < other.r:
            dr = other.r - self.r_end
        elif other.r_end < self.r:
            dr = self.r - other.r_end

        dc = 0
        if self.c_end < other.c:
            dc = other.c - self.c_end
        elif other.c_end < self.c:
            dc = self.c - other.c_end

        return dr + dc


ROOM_CATALOG: Dict[str, Dict[str, Any]] = {
    "master_bed": {
        "name": "Master Bedroom",
        "functional_zone": "PRIVATE",
        "catalog_min_m2": 14.0,
        "catalog_max_m2": 22.0,
        "area_cells": 12,
        "shapes": [(4, 3), (3, 4)],  # (w, h)
        "canonical_zone": "SW",
        "allowed_secondary": ["S", "W"],
        "prohibited": ["NE"],
        "wet": False
    },
    "living": {
        "name": "Living Room",
        "functional_zone": "PUBLIC",
        "catalog_min_m2": 18.0,
        "catalog_max_m2": 35.0,
        "area_cells": 15,
        "shapes": [(5, 3), (3, 5), (4, 4)],
        "canonical_zone": "Center",
        "allowed_secondary": ["N", "E"],
        "prohibited": [],
        "wet": False
    },
    "foyer": {
        "name": "Entry Foyer",
        "functional_zone": "PUBLIC",
        "catalog_min_m2": 3.0,
        "catalog_max_m2": 10.0,
        "area_cells": 4,
        "shapes": [(2, 2), (3, 2), (2, 3)],
        "canonical_zone": "N",
        "allowed_secondary": ["Center", "NE", "E"],
        "prohibited": ["SW"],
        "wet": False
    },
    "kitchen": {
        "name": "Kitchen",
        "functional_zone": "SERVICE",
        "catalog_min_m2": 9.0,
        "catalog_max_m2": 16.0,
        "area_cells": 8,
        "shapes": [(4, 2), (2, 4), (3, 3)],
        "canonical_zone": "SE",
        "allowed_secondary": ["NW", "E"],
        "prohibited": ["NE", "SW"],
        "wet": True
    },
    "puja": {
        "name": "Puja Room",
        "functional_zone": "PUBLIC",
        "catalog_min_m2": 4.0,
        "catalog_max_m2": 9.0,
        "area_cells": 4,
        "shapes": [(2, 2), (2, 1), (1, 2)],
        "canonical_zone": "NE",
        "allowed_secondary": ["N", "E"],
        "prohibited": ["S", "SW"],
        "wet": False
    },
    "bath_1": {
        "name": "Common Bath",
        "functional_zone": "SERVICE",
        "catalog_min_m2": 3.5,
        "catalog_max_m2": 6.0,
        "area_cells": 4,
        "shapes": [(2, 2), (1, 3), (3, 1)],
        "canonical_zone": "NW",
        "allowed_secondary": ["W", "S", "SE"],
        "prohibited": ["NE"],
        "wet": True
    },
    "bath_2": {
        "name": "Primary Bath",
        "functional_zone": "SERVICE",
        "catalog_min_m2": 3.5,
        "catalog_max_m2": 6.0,
        "area_cells": 4,
        "shapes": [(2, 2), (1, 3)],
        "canonical_zone": "NW",
        "allowed_secondary": ["W", "S", "SE"],
        "prohibited": ["NE"],
        "wet": True
    },
    "wc": {
        "name": "Water Closet",
        "functional_zone": "SERVICE",
        "catalog_min_m2": 1.5,
        "catalog_max_m2": 2.5,
        "area_cells": 2,
        "shapes": [(2, 1), (1, 2)],
        "canonical_zone": "NW",
        "allowed_secondary": ["W", "S"],
        "prohibited": ["NE"],
        "wet": True
    },
    "bed_2": {
        "name": "Bedroom 2",
        "functional_zone": "PRIVATE",
        "catalog_min_m2": 10.0,
        "catalog_max_m2": 18.0,
        "area_cells": 9,
        "shapes": [(3, 3), (4, 3), (3, 4)],
        "canonical_zone": "W",
        "allowed_secondary": ["NW", "S"],
        "prohibited": ["NE"],
        "wet": False
    },
    "dining": {
        "name": "Dining Area",
        "functional_zone": "SERVICE",
        "catalog_min_m2": 9.0,
        "catalog_max_m2": 14.0,
        "area_cells": 8,
        "shapes": [(4, 2), (2, 4), (3, 2)],
        "canonical_zone": "W",
        "allowed_secondary": ["Center", "E", "SE"],
        "prohibited": [],
        "wet": False
    },
    "study": {
        "name": "Study Room",
        "functional_zone": "PRIVATE",
        "catalog_min_m2": 8.0,
        "catalog_max_m2": 12.0,
        "area_cells": 6,
        "shapes": [(3, 2), (2, 3)],
        "canonical_zone": "NE",
        "allowed_secondary": ["N", "W"],
        "prohibited": ["SW"],
        "wet": False
    },
    "utility": {
        "name": "Utility",
        "functional_zone": "SERVICE",
        "catalog_min_m2": 3.0,
        "catalog_max_m2": 6.0,
        "area_cells": 4,
        "shapes": [(2, 2), (2, 1)],
        "canonical_zone": "SE",
        "allowed_secondary": ["NW", "S"],
        "prohibited": ["NE"],
        "wet": True
    },
    "stairs": {
        "name": "Staircase",
        "functional_zone": "SERVICE",
        "catalog_min_m2": 6.0,
        "catalog_max_m2": 10.0,
        "area_cells": 6,
        "shapes": [(3, 2), (2, 3), (2, 2)],
        "canonical_zone": "SW",
        "allowed_secondary": ["W", "S", "NW"],
        "prohibited": ["NE"],
        "wet": False
    },
    "corridor": {
        "name": "Circulation Foyer",
        "functional_zone": "PUBLIC",
        "catalog_min_m2": 4.0,
        "catalog_max_m2": 12.0,
        "area_cells": 6,
        "shapes": [(3, 2), (2, 3), (4, 1), (1, 4)],
        "canonical_zone": "Center",
        "allowed_secondary": ["N", "S", "E", "W"],
        "prohibited": [],
        "wet": False
    },
    # T3 office/commercial cells.  Without these the fragment fallback (16 m2)
    # stamped a 25 m2 reception and a 27 m2 conference room as catalogue
    # maxima on every market-mix plate.  The ranges are the typology's own
    # front-of-house/technical bands, not residential bedroom limits.
    "reception": {
        "name": "Reception Lobby", "functional_zone": "PUBLIC",
        "catalog_min_m2": 12.0, "catalog_max_m2": 40.0,
        "area_cells": 12, "shapes": [(4, 3), (3, 4), (5, 3)],
        "canonical_zone": "NW", "allowed_secondary": ["N", "W"],
        "prohibited": [], "wet": False,
    },
    "visitor_lounge": {
        "name": "Visitor Lounge", "functional_zone": "PUBLIC",
        "catalog_min_m2": 10.0, "catalog_max_m2": 36.0,
        "area_cells": 10, "shapes": [(4, 3), (3, 4)],
        "canonical_zone": "NW", "allowed_secondary": ["N", "E"],
        "prohibited": [], "wet": False,
    },
    "conference_room": {
        "name": "Conference Room", "functional_zone": "PUBLIC",
        "catalog_min_m2": 12.0, "catalog_max_m2": 60.0,
        "area_cells": 12, "shapes": [(5, 3), (4, 4), (6, 3)],
        "canonical_zone": "E", "allowed_secondary": ["N", "S"],
        "prohibited": [], "wet": False,
    },
    "conference_suite": {
        "name": "Conference Suite", "functional_zone": "PUBLIC",
        "catalog_min_m2": 12.0, "catalog_max_m2": 60.0,
        "area_cells": 12, "shapes": [(5, 3), (4, 4)],
        "canonical_zone": "E", "allowed_secondary": ["N", "S"],
        "prohibited": [], "wet": False,
    },
    "electrical_room": {
        "name": "Electrical Room", "functional_zone": "SERVICE",
        "catalog_min_m2": 4.0, "catalog_max_m2": 22.0,
        "area_cells": 4, "shapes": [(3, 2), (2, 3)],
        "canonical_zone": "SE", "allowed_secondary": ["S", "E"],
        "prohibited": ["NE"], "wet": False,
    },
    "server_room": {
        "name": "Server Room", "functional_zone": "SERVICE",
        "catalog_min_m2": 6.0, "catalog_max_m2": 28.0,
        "area_cells": 6, "shapes": [(3, 2), (2, 3)],
        "canonical_zone": "E", "allowed_secondary": ["N", "S"],
        "prohibited": [], "wet": False,
    },
    "mep_room": {
        "name": "MEP Plant Room", "functional_zone": "SERVICE",
        "catalog_min_m2": 6.0, "catalog_max_m2": 30.0,
        "area_cells": 6, "shapes": [(3, 2), (2, 3)],
        "canonical_zone": "NE", "allowed_secondary": ["N", "E"],
        "prohibited": [], "wet": False,
    },
    # T4 industrial bays.  A 16 m2 loading dock is not a room catalogue row;
    # the fallback made every warehouse case fail ROOM-MAX by 4x.
    "t4_dock_bay": {
        "name": "Loading Dock Bay", "functional_zone": "INDUSTRIAL",
        "catalog_min_m2": 40.0, "catalog_max_m2": 180.0,
        "area_cells": 40, "shapes": [(8, 5), (10, 4)],
        "canonical_zone": "N", "allowed_secondary": ["E", "W"],
        "prohibited": [], "wet": False,
    },
    "t4_dispatch": {
        "name": "Dispatch & Staging", "functional_zone": "INDUSTRIAL",
        "catalog_min_m2": 20.0, "catalog_max_m2": 100.0,
        "area_cells": 20, "shapes": [(6, 4), (5, 4)],
        "canonical_zone": "NE", "allowed_secondary": ["N", "E"],
        "prohibited": [], "wet": False,
    },
    "t4_storage_bay": {
        "name": "Storage Bay", "functional_zone": "INDUSTRIAL",
        "catalog_min_m2": 40.0, "catalog_max_m2": 260.0,
        "area_cells": 40, "shapes": [(10, 6), (8, 8)],
        "canonical_zone": "S", "allowed_secondary": ["SW", "SE"],
        "prohibited": [], "wet": False,
    },
    "worker_amenity": {
        "name": "Worker Amenity", "functional_zone": "SERVICE",
        "catalog_min_m2": 8.0, "catalog_max_m2": 30.0,
        "area_cells": 8, "shapes": [(4, 2), (3, 3)],
        "canonical_zone": "W", "allowed_secondary": ["SW", "NW"],
        "prohibited": [], "wet": True,
    },
    "washdown_point": {
        "name": "Washdown Point", "functional_zone": "SERVICE",
        "catalog_min_m2": 4.0, "catalog_max_m2": 20.0,
        "area_cells": 4, "shapes": [(3, 2), (2, 3)],
        "canonical_zone": "SW", "allowed_secondary": ["W", "S"],
        "prohibited": [], "wet": True,
    },
    "admin_office": {
        "name": "Admin Office", "functional_zone": "PUBLIC",
        "catalog_min_m2": 10.0, "catalog_max_m2": 45.0,
        "area_cells": 10, "shapes": [(4, 3), (3, 4)],
        "canonical_zone": "NW", "allowed_secondary": ["N", "W"],
        "prohibited": [], "wet": False,
    },
    "upper_store": {
        "name": "Upper Floor Store", "functional_zone": "SERVICE",
        "catalog_min_m2": 4.0, "catalog_max_m2": 24.0,
        "area_cells": 4, "shapes": [(3, 2), (2, 3)],
        "canonical_zone": "SE", "allowed_secondary": ["S", "E"],
        "prohibited": [], "wet": False,
    },
    "t4_util_west": {
        "name": "Utility West", "functional_zone": "SERVICE",
        "catalog_min_m2": 4.0, "catalog_max_m2": 20.0,
        "area_cells": 4, "shapes": [(3, 2), (2, 3)],
        "canonical_zone": "W", "allowed_secondary": ["SW", "NW"],
        "prohibited": [], "wet": True,
    },
}


def normalize_room_identifier(room_id: str) -> str:
    import re
    r = room_id.lower().strip().replace(" ", "_")
    # Strip the per-level suffix used on solved floor plates (living_F0 -> living).
    r = re.sub(r"_f\d+$", "", r)
    if r in ("hall", "living_room", "family_living"):
        return "living"
    if r in ("pooja", "puja_room", "mandir", "prayer"):
        return "puja"
    if r in ("master", "master_bedroom", "primary_bedroom", "bed_1"):
        return "master_bed"
    if r in ("kitchen_room", "kitchenette", "cook_room"):
        return "kitchen"
    if r in ("toilet", "washroom", "restroom", "powder_room"):
        return "wc"
    if r in ("primary_bath", "ensuite_bath", "ensuite", "attached_bath"):
        return "bath_2"
    if r in ("bathroom", "bath", "common_bath"):
        return "bath_1"
    if r in ("bedroom_2", "guest_bed", "bed"):
        return "bed_2"
    if r in ("dining_room", "dinning"):
        return "dining"
    if r in ("utility_room", "work_area"):
        return "utility"
    return r


def get_explicit_room_catalog_entry(room_id: str) -> Optional[Dict[str, Any]]:
    """The catalogue row for this room id, or None when only the generic fallback applies.

    Plate sizing needs to know whether a row is real: a foyer/landing has no
    catalogue maximum, and applying the generic 8 m2 fallback to it inflated
    the programme by rooms the catalogue never described.
    """
    norm = normalize_room_identifier(room_id)
    if norm in ROOM_CATALOG:
        return ROOM_CATALOG[norm]
    for k, v in ROOM_CATALOG.items():
        if norm.startswith(k) or k in norm:
            return v
    return None


def get_room_catalog_entry(room_id: str) -> Dict[str, Any]:
    explicit = get_explicit_room_catalog_entry(room_id)
    if explicit is not None:
        return explicit
    norm = normalize_room_identifier(room_id)
    # Fallback generic room
    return {
        "name": norm.replace("_", " ").title(),
        "functional_zone": "PRIVATE",
        "catalog_min_m2": 8.0,
        "catalog_max_m2": 16.0,
        "area_cells": 8,
        "canonical_zone": "Center",
        "allowed_secondary": ["N", "S", "E", "W"],
        "prohibited": [],
        "wet": False
    }


class SpatialGrid:
    """
    Represents the discretized building envelope on a 2D integer coordinate system.
    """
    def __init__(self, plot_width_m: float, plot_depth_m: float):
        self.plot_width_m = float(plot_width_m)
        self.plot_depth_m = float(plot_depth_m)
        ar = self.plot_width_m / max(self.plot_depth_m, 0.1)

        # Discretize grid dimension R x C (rows = North-South, cols = West-East)
        if 0.85 <= ar <= 1.15:
            self.rows = 10
            self.cols = 10
        elif ar > 1.15:
            self.rows = 10
            self.cols = min(14, max(8, round(10.0 * ar)))
        else:
            self.cols = 10
            self.rows = min(14, max(8, round(10.0 / ar)))

        self.cell_w_m = self.plot_width_m / self.cols
        self.cell_d_m = self.plot_depth_m / self.rows

    def get_zone(self, box: RoomBox) -> str:
        cr, cc = box.centroid
        r_third = self.rows / 3.0
        c_third = self.cols / 3.0

        if cr < r_third:
            row_pos = "N"
        elif cr < 2.0 * r_third:
            row_pos = "M"
        else:
            row_pos = "S"

        if cc < c_third:
            col_pos = "W"
        elif cc < 2.0 * c_third:
            col_pos = "M"
        else:
            col_pos = "E"

        if row_pos == "N" and col_pos == "W":
            return "NW"
        elif row_pos == "N" and col_pos == "M":
            return "N"
        elif row_pos == "N" and col_pos == "E":
            return "NE"
        elif row_pos == "M" and col_pos == "W":
            return "W"
        elif row_pos == "M" and col_pos == "M":
            return "Center"
        elif row_pos == "M" and col_pos == "E":
            return "E"
        elif row_pos == "S" and col_pos == "W":
            return "SW"
        elif row_pos == "S" and col_pos == "M":
            return "S"
        else:
            return "SE"

    def is_in_zone(self, box: RoomBox, target_zone: str) -> bool:
        return self.get_zone(box) == target_zone

    def is_in_se_quadrant(self, box: RoomBox) -> bool:
        cr, cc = box.centroid
        return cr >= (self.rows / 2.0) and cc >= (self.cols / 2.0)

    def is_in_ne_quadrant(self, box: RoomBox) -> bool:
        cr, cc = box.centroid
        return cr < (self.rows / 2.0) and cc >= (self.cols / 2.0)

    def is_in_sw_quadrant(self, box: RoomBox) -> bool:
        cr, cc = box.centroid
        return cr >= (self.rows / 2.0) and cc < (self.cols / 2.0)

    def is_in_nw_quadrant(self, box: RoomBox) -> bool:
        cr, cc = box.centroid
        return cr < (self.rows / 2.0) and cc < (self.cols / 2.0)
