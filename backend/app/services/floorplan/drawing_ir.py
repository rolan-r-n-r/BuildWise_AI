"""
drawing_ir.py - Shared Architectural Drawing Intermediate Representation (IR)
=============================================================================
Unified geometry intermediate for both SVG (web viewer) and ReportLab (PDF dossier/report).
Eliminates all backend coordinate discrepancies, scaling inconsistencies, and duplicate
geometry interpretation.

DOCUMENTED AXIS CONVENTION (METRIC CARTESIAN Y-UP):
---------------------------------------------------
- Spatial Units: METERS.
- Origin (0.0, 0.0): South-West corner of the building envelope.
- +X axis: Points East (Right), domain [0.0, envelope_width_m].
- +Y axis: Points North (Up), domain [0.0, envelope_depth_m].

CONVERSION FROM MODEL SPACE:
----------------------------
In MultiStoreyBuildingModel / wall_graph, coordinates are conventionally stored in screen space
where model Y increases Southwards (Y-down) from the North envelope boundary:
  x_ir = x_model
  y_ir = envelope_depth_m - y_model
For a rectangular bounding box (x, y, width, depth) in model space:
  x_ir = x
  y_ir = envelope_depth_m - (y + depth)
  w_ir = width
  h_ir = depth

BACKEND RENDERER TRANSFORMS:
----------------------------
1. SVG Backend (Y-Down, Canvas Origin at Top-Left):
   Flips Y ONCE at the top-level viewport projection:
     x_svg = margin_x + (x_ir * scale_px)
     y_svg = margin_y + ((envelope_depth_m - y_ir) * scale_px)

2. ReportLab PDF Backend (Y-Up, Canvas Origin at Bottom-Left):
   Natively matches IR Y-up orientation with a single uniform scale and origin per sheet:
     x_pt = origin_x + (x_ir * scale_pt)
     y_pt = origin_y + (y_ir * scale_pt)
   NO Y-FLIP IN REPORTLAB. Zero cumulative canvas transforms.

LAYER TAGS:
-----------
- 'fills': Room pastel fills, background panels.
- 'walls': Structural W1 exterior walls, W2 interior partitions, W3 lightweight shaft walls.
- 'openings': Hosted doors (leaf line + swing arc + tags + jamb rebates), windows (3-line symbol + tags).
- 'dims': 3-line dimension chains (overall, clear rooms, opening offsets) with 45° ticks.
- 'text': Room names, clear dimensions, area badges with halo pills.
- 'cores': Vertical circulation (stair flights, mid-landing, treads, UP/DN arrows, headroom text).
- 'ghost': Ground-floor anchor overlays on upper floors (F1+), MEP duct shafts.
- 'annotations': North arrow, metric graphic scale bar, title block with freshness token, structural tags.
"""

from __future__ import annotations

import math
import html
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Literal

from app.services.floorplan.identity import (
    identity_dict,
    identity_is_outdoor,
    identity_is_wet,
    identity_name,
)

# ReportLab imports (lazy or guarded if needed)
try:
    from reportlab.graphics.shapes import Drawing, Rect, Line, String, ArcPath, Circle, Polygon, PolyLine, Group
    from reportlab.lib import colors
except ImportError:
    Drawing = Rect = Line = String = ArcPath = Circle = Polygon = PolyLine = colors = None


# =============================================================================
# 1. DATA STRUCTURES FOR NORMALIZED PRIMITIVES
# =============================================================================

LayerTag = Literal["walls", "fills", "openings", "dims", "text", "cores", "ghost", "annotations", "site"]
AnnotationStatus = Literal["CALCULATED", "ASSUMED", "RECOMMENDED", "VERIFIED"]


@dataclass
class DrawingPrimitive:
    """Base class for all normalized drawing primitives."""
    layer: LayerTag
    status: AnnotationStatus = field(default="CALCULATED", kw_only=True)


@dataclass
class PolygonPrimitive(DrawingPrimitive):
    """Normalized polygon primitive in meters for site boundaries, setback bands, and outdoor fragments."""
    points: List[Tuple[float, float]] = field(default_factory=list)  # [(x_m, y_m)] in IR Cartesian Y-up meters
    fill_color: Optional[str] = None
    fill_opacity: float = 1.0
    stroke_color: Optional[str] = None
    stroke_width_m: float = 0.0
    dash_array: Optional[List[float]] = None
    hatch_pattern: Optional[str] = None  # e.g. "mf-hatch-setback"
    label: Optional[str] = None
    is_boundary: bool = False
    is_setback: bool = False
    is_footprint: bool = False


@dataclass
class PathPrimitive(DrawingPrimitive):
    """Normalized multi-segment path or boundary polyline in meters."""
    points: List[Tuple[float, float]] = field(default_factory=list)
    stroke_color: str = "#0F172A"
    stroke_width_m: float = 0.0
    dash_array: Optional[List[float]] = None
    fill_color: Optional[str] = None


@dataclass
class FillPrimitive(DrawingPrimitive):
    """Room fill rectangle or background patch in meters."""
    x: float          # SW corner X (meters)
    y: float          # SW corner Y (meters)
    w: float          # Width Eastward (meters)
    h: float          # Height Northward (meters)
    fill_color: str   # Hex or rgba string
    stroke_color: Optional[str] = None
    stroke_width_m: float = 0.0
    dash_array: Optional[List[float]] = None
    room_id: str = ""
    room_name: str = ""
    zone: str = ""
    is_core: bool = False


@dataclass
class WallPrimitive(DrawingPrimitive):
    """Constructible wall segment in meters."""
    wall_id: str
    wall_type: Literal["W1", "W2", "W3"]
    x1: float
    y1: float
    x2: float
    y2: float
    thickness_m: float
    is_exterior: bool = False
    is_load_bearing: bool = False
    dash_array: Optional[List[float]] = None


@dataclass
class OpeningPrimitive(DrawingPrimitive):
    """Hosted architectural opening (door or window) in meters."""
    opening_id: str
    opening_type: Literal["door", "window"]
    tag: str  # D1, D2..., W1, W2...
    wall_edge: str  # north, south, east, west, vertical, horizontal
    x1: float
    y1: float
    x2: float
    y2: float

    # Door specifics
    hinge_x: float = 0.0
    hinge_y: float = 0.0
    leaf_x: float = 0.0
    leaf_y: float = 0.0
    arc_center_x: float = 0.0
    arc_center_y: float = 0.0
    arc_radius_m: float = 0.9
    arc_start_deg: float = 0.0  # Counter-clockwise degrees from East (0°) in Y-up space
    arc_end_deg: float = 90.0
    arc_start_pt: Tuple[float, float] = (0.0, 0.0)
    arc_end_pt: Tuple[float, float] = (0.0, 0.0)
    svg_sweep_flag: int = 0
    door_jambs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = field(default_factory=list)
    tag_x: float = 0.0
    tag_y: float = 0.0
    unit_badge: Optional[Dict[str, Any]] = None

    # Window specifics
    outer_line: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
    glass_line: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
    inner_line: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
    window_jambs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = field(default_factory=list)


@dataclass
class StairPrimitive(DrawingPrimitive):
    """Constructed staircase core with flights, landing, treads, and annotations."""
    boundary: Tuple[float, float, float, float]  # (x, y, w, h) in meters
    landing_line: Tuple[Tuple[float, float], Tuple[float, float]]
    dividing_line: Tuple[Tuple[float, float], Tuple[float, float]]
    treads: List[Tuple[Tuple[float, float], Tuple[float, float]]] = field(default_factory=list)
    up_line: Tuple[Tuple[float, float], Tuple[float, float]] = ((0.0, 0.0), (0.0, 0.0))
    up_tip: List[Tuple[float, float]] = field(default_factory=list)
    up_text_pos: Tuple[float, float] = (0.0, 0.0)
    dn_line: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
    dn_tip: Optional[List[Tuple[float, float]]] = None
    dn_text_pos: Optional[Tuple[float, float]] = None
    headroom_text_pos: Tuple[float, float] = (0.0, 0.0)
    headroom_text: str = "HEADROOM >= 2.20m CLEAR"


@dataclass
class DimensionChainPrimitive(DrawingPrimitive):
    """3-line architectural dimension chain with 45° slash ticks and witness lines."""
    chain_id: str
    axis: Literal["horizontal", "vertical"]
    level: Literal["overall", "clear_rooms", "openings"]
    main_line: Tuple[Tuple[float, float], Tuple[float, float]]
    ticks: List[Tuple[float, float]] = field(default_factory=list)
    witness_lines: List[Tuple[Tuple[float, float], Tuple[float, float]]] = field(default_factory=list)
    segments: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class TextPrimitive(DrawingPrimitive):
    """On-plan typography with halo pill and metric clear dims."""
    x: float
    y: float
    text: str
    font_size_pt: float = 8.5
    font_weight: str = "bold"
    color: str = "#0F172A"
    halo: bool = True
    halo_w_m: float = 1.8
    halo_h_m: float = 0.55
    subtext: Optional[str] = None
    subtext_pt: float = 7.0
    subtext_color: str = "#64748B"
    lines: List[str] = field(default_factory=list)
    dims_str: Optional[str] = None
    dims_fs: float = 7.0
    total_h_m: float = 0.55
    room_tag_circle: Optional[Dict[str, Any]] = None


@dataclass
class GhostPrimitive(DrawingPrimitive):
    """Ghost core overlay for upper floors (F1+) showing foundation stacking."""
    core_rects: List[Tuple[float, float, float, float]] = field(default_factory=list)
    ghost_treads: List[Tuple[Tuple[float, float], Tuple[float, float]]] = field(default_factory=list)
    anchor_badge: Optional[Dict[str, Any]] = None
    duct_shafts: List[Tuple[float, float, float, float]] = field(default_factory=list)


@dataclass
class AnnotationPrimitive(DrawingPrimitive):
    """North arrow, graphic scale bar, title badge, and structural tags."""
    compass: Optional[Dict[str, Any]] = None
    scale_bar: Optional[Dict[str, Any]] = None
    title_block: Optional[Dict[str, Any]] = None
    entrance_pointer: Optional[Dict[str, Any]] = None
    structural_tags: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SheetHeaderInfo:
    """Freshness verification and sheet metadata."""
    gen_id: str
    plot_w_m: float
    plot_d_m: float
    storeys: int
    storeys_label: str
    floor_index: int
    floor_name: str
    elevation_m: float
    envelope_w_m: float
    envelope_d_m: float
    freshness_token: str
    typology: str = "T1_SINGLE_FAMILY"
    validated_layers: List[str] = field(default_factory=lambda: ["L1", "L2"])
    layer_statuses: List[Dict[str, Any]] = field(default_factory=list)
    overall_layer_status: str = "PASS"

    @property
    def drawing_status_stamp(self) -> str:
        # Single-source status stamp, shared with the validation gate module.
        from app.services.floorplan.validation_gate import drawing_status_stamp
        return drawing_status_stamp(self.validated_layers)


@dataclass
class FloorDrawingIR:
    """Complete, self-contained Normalized Architectural Drawing IR for a single storey."""
    envelope_w: float
    envelope_d: float
    header: SheetHeaderInfo
    primitives: List[DrawingPrimitive] = field(default_factory=list)
    door_schedule: List[Dict[str, Any]] = field(default_factory=list)
    window_schedule: List[Dict[str, Any]] = field(default_factory=list)
    room_schedule: List[Dict[str, Any]] = field(default_factory=list)
    stair_schedule: List[Dict[str, Any]] = field(default_factory=list)
    has_stepped_envelope: bool = False
    vertex_table: List[Dict[str, Any]] = field(default_factory=list)
    edge_schedule: List[Dict[str, Any]] = field(default_factory=list)
    design_policy: Optional[str] = None
    design_policy_rationale: Optional[str] = None
    checklist: Optional[Dict[str, Any]] = None
    annotation_taxonomy: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def drawing_status_stamp(self) -> str:
        return self.header.drawing_status_stamp

    def get_annotation_taxonomy_groups(self) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {
            "VERIFIED": [],
            "CALCULATED": [],
            "ASSUMED": [],
            "RECOMMENDED": []
        }
        for p in self.primitives:
            st = getattr(p, "status", "CALCULATED")
            if st not in groups:
                groups[st] = []
            if isinstance(p, TextPrimitive):
                groups[st].append(p.text)
            elif isinstance(p, DimensionChainPrimitive):
                groups[st].append(f"DimensionChain {p.chain_id} ({p.axis} {p.level})")
            elif isinstance(p, PolygonPrimitive):
                lbl = p.label or ("Footprint" if p.is_footprint else ("Setback" if p.is_setback else "Polygon"))
                groups[st].append(f"Polygon ({lbl})")
            elif isinstance(p, WallPrimitive):
                groups[st].append(f"Wall {p.wall_id}")
            elif isinstance(p, AnnotationPrimitive):
                groups[st].append("TitleBlock & Compass")
            else:
                lbl = getattr(p, "label", getattr(p, "text", type(p).__name__))
                groups[st].append(f"{type(p).__name__} ({lbl})")
        return groups


    def primitives_by_layer(self, layer: LayerTag) -> List[DrawingPrimitive]:
        return [p for p in self.primitives if p.layer == layer]

    def get_bbox_m(self) -> Tuple[float, float, float, float]:
        """Returns overall bounding box in IR meters: (min_x, min_y, max_x, max_y)."""
        # Base envelope
        min_x = 0.0
        max_x = self.envelope_w
        min_y = 0.0
        max_y = self.envelope_d

        # Include dimension chains & annotations margin
        return (-1.4, -0.6, max_x + 0.6, max_y + 1.4)


# =============================================================================
# 2. COLLISION AVOIDANCE HELPERS & IR BUILDER
# =============================================================================

ROOM_ABBREV_MAP: Dict[str, str] = {
    # T1
    "MASTER BEDROOM": "M.BED",
    "GUEST BATHROOM": "G.BATH",
    "ENTRANCE FOYER": "FOYER",
    "PRIVATE STAIRCASE": "STAIR",
    "LIVING ROOM": "LIVING",
    "DINING AREA": "DINING",
    "KITCHEN": "KTCHN",
    "PUJA ROOM": "PUJA",
    "CENTRAL LOBBY": "LOBBY",
    "BALCONY": "BALC",
    "CORRIDOR": "CORR",
    "BEDROOM 2": "BED 2",
    "BEDROOM 3": "BED 3",
    "BATHROOM 1": "BATH 1",
    "BATHROOM 2": "BATH 2",
    # T2
    "SHARED STAIRCASE CORE": "STAIR",
    "FLOOR ELEVATOR & STAIR LOBBY": "LOBBY",
    "UNIT A: LIVING & DINING": "U.A LIV",
    "UNIT A: BEDROOM": "U.A BED",
    "UNIT B: LIVING & DINING": "U.B LIV",
    "UNIT B: BEDROOM": "U.B BED",
    "SANITARY & UTILITY BLOCK": "UTILITY",
    # T3
    "ENCLOSED FIRE STAIR 1": "STAIR 1",
    "ENCLOSED FIRE STAIR 2": "STAIR 2",
    "ELEVATOR BANK & MAIN LOBBY": "LOBBY",
    "1.5M DOUBLE-LOADED CORRIDOR": "CORR",
    "COMMERCIAL SUITE NORTH (OPEN OFFICE)": "SUITE N",
    "COMMERCIAL SUITE SOUTH (EXECUTIVE)": "SUITE S",
    "COMMERCIAL SANITARY & RESTROOM CORE": "SAN/WC",
    # T4
    "INDUSTRIAL STEEL STAIRCASE CORE": "IND STAIR",
    "GROUND STAGING LOBBY": "STAGING",
    "LOADING DOCK BAYS (ROLLING SHUTTERS)": "DOCK BAYS",
    "DISPATCH & PALLET STAGING AREA": "DISPATCH",
    "CLEAR-SPAN INDUSTRIAL STORAGE BAY": "STORAGE",
    "STAFF LOCKER & SANITARY AMENITIES": "AMENITIES",
    "MEZZANINE ADMINISTRATIVE SUITE": "MEZZ ADMIN",
}


try:
    from reportlab.pdfbase.pdfmetrics import stringWidth as _rl_string_width
except Exception:  # pragma: no cover - reportlab guarded above too
    _rl_string_width = None


def _approx_text_width(text: str, fs: float) -> float:
    """Rendered width in px for the bold Helvetica labels the PDF draws.

    Uses ReportLab's exact metric tables when available so the collision
    resolver and the ReportLab renderer agree; falls back to a conservative
    0.62 * fs * len estimate otherwise (SVG backend styling is close).
    """
    if _rl_string_width is not None:
        try:
            return float(_rl_string_width(text, "Helvetica-Bold", fs))
        except Exception:
            pass
    return 0.62 * fs * len(text)


# Single-source service legend - rendered on the SVG sheet panel AND
# appended to the PDF blueprint page (report_service) so both outputs teach
# the same symbols (SVG/PDF content parity).
SERVICE_LEGEND_PARTS = [
    "dashed box = plumbing shaft (soil+vent stack, inspection access at foundation)",
    "diamond = stack",
    "RWP = rainwater pipe",
    "TB = transfer beam (verify support below)",
    "DRAIN = terrace rain-water outlet, slope 1:100 to site storm outlet SO-01",
    "DP = downpipe to SO-01; OVERFLOW = emergency weir on terrace edge",
]


def _ellipsize_str(s: str, max_len: int) -> str:
    """Word-aware ellipsis: never cuts a token mid-word.

    When the budget lands inside the final word, the whole word is dropped and
    the ellipsis is appended after the last complete word instead - so a reader
    sees "Private Stair..", never "Private Stairc". Whitespace is normalized
    and trailing spaces are trimmed before measuring.
    """
    s = " ".join(str(s).split())
    if len(s) <= max_len:
        return s
    budget = max_len - 2  # room for the ".." marker
    if budget <= 0:
        return s[:max(0, max_len - 1)] + (".." if max_len >= 2 else "")
    head = s[:budget]
    if budget >= len(s) or s[budget] == " ":
        # The budget lands exactly ON a word boundary - nothing is cut open.
        return head.rstrip() + ".."
    if " " in head:
        # The budget lands INSIDE the final word: drop that partial word
        # entirely. (Checking only for a space after the cut was the KB bug: a
        # trailing token with no space left produced "...Epoxy G..".)
        return head[: head.rfind(" ")].rstrip() + " .."
    # Single overlong token: there is no boundary to fall back to, so a
    # hard-cut is the only option - the marker keeps it honest.
    return head.rstrip() + ".."


def _fit_banner_line(text: str, max_chars: int, base_fs: float = 7.5,
                     min_fs: float = 4.8) -> tuple:
    """Fit a banner line onto the sheet without dropping the truth tail.

    Sheet truth: the freshness token carries the confirmed frontage
    edge and the polygon hash and must reach the sheet VERBATIM. If the line
    is longer than the banner budget the font is shrunk first; only when the
    canvas is too narrow even for ``min_fs`` is the TYPOLOGY head ellipsized -
    the ``FRTG``/``POLYHASH`` tail is always preserved in full.
    """
    text = str(text).strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return base_fs, text
    needed = base_fs * max_chars / float(len(text))
    if needed >= min_fs:
        return max(min_fs, needed), text
    idx = text.find(" | FRTG")
    if idx >= 0:
        tail = text[idx:]
        head_budget = max(8, max_chars - len(tail) - 4)
        return min_fs, _ellipsize_str(text[:idx], head_budget) + tail
    return min_fs, _ellipsize_str(text, max_chars)


def _wrap_status_stamp(stamp: str, max_chars: int) -> List[str]:
    """Wrap the drawing-status stamp for sheet display.

    Every emitted line repeats a "STATUS: CONCEPT DESIGN" prefix (sheet stamp
    assertions scan only lines carrying that prefix), and the legal tail
    "] - NOT FOR CONSTRUCTION" is always appended to the FINAL emitted line -
    no layer count or canvas width can drop ids or split the tail.
    """
    tail = "] - NOT FOR CONSTRUCTION"
    head = "STATUS: CONCEPT DESIGN - VALIDATED LAYERS: ["
    cont = "STATUS: CONCEPT DESIGN (cont) "
    inner = stamp[stamp.find("[") + 1:stamp.rfind("]")]
    ids = [t.strip() for t in inner.split(",") if t.strip()]
    lines: List[str] = []
    cur = head
    for i in ids:
        if len(cur) + len(i) + 2 <= max_chars or cur in (head, cont):
            cur = f"{cur}{i}, "
        else:
            lines.append(cur.rstrip(", "))
            cur = f"{cont}{i}, "
    cur = cur.rstrip(", ")
    if len(cur) + len(tail) > max_chars:
        # Tail would overflow its line: give it its own (prefixed) line.
        lines.append(cur)
        cur = cont.rstrip()
    lines.append(f"{cur}{tail}")
    return lines


def _get_abbrev(name: str) -> str:
    cleaned = name.strip().upper()
    if cleaned in ROOM_ABBREV_MAP:
        return ROOM_ABBREV_MAP[cleaned]
    short = cleaned
    for o, n in [
        ("BATHROOM", "BATH"),
        ("BEDROOM", "BED"),
        ("STAIRCASE", "STAIR"),
        ("CORRIDOR", "CORR"),
        ("ELEVATOR", "LIFT"),
        ("COMMERCIAL", "COMM"),
        ("INDUSTRIAL", "IND"),
        ("ADMINISTRATIVE", "ADMIN"),
    ]:
        short = short.replace(o, n)
    return short


def _wrap_text(text: str, max_w: float, fs: float) -> Optional[List[str]]:
    words = text.split()
    if not words:
        return []
    for w in words:
        if _approx_text_width(w, fs) > max_w:
            return None
    lines = []
    curr = words[0]
    for w in words[1:]:
        test_line = f"{curr} {w}"
        if _approx_text_width(test_line, fs) <= max_w:
            curr = test_line
        else:
            lines.append(curr)
            curr = w
    lines.append(curr)
    return lines


class BBox:
    def __init__(self, xmin: float, ymin: float, xmax: float, ymax: float):
        self.xmin = xmin
        self.ymin = ymin
        self.xmax = xmax
        self.ymax = ymax

    def intersects(self, other: "BBox", pad: float = 0.5) -> bool:
        return not (
            self.xmax + pad <= other.xmin or
            self.xmin - pad >= other.xmax or
            self.ymax + pad <= other.ymin or
            self.ymin - pad >= other.ymax
        )

    def intersection_area(self, other: "BBox") -> float:
        """Overlap area with another box in square pixels (0.0 when disjoint)."""
        w = min(self.xmax, other.xmax) - max(self.xmin, other.xmin)
        h = min(self.ymax, other.ymax) - max(self.ymin, other.ymin)
        return (w * h) if (w > 0.0 and h > 0.0) else 0.0


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        res = obj.get(key, default)
        return default if res is None else res
    res = getattr(obj, key, default)
    return default if res is None else res

def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _polygon_hash_short(poly: Any) -> str:
    """Sheet truth: deterministic 8-hex djb2 hash of the plot polygon.

    Hashes the canonical vertices formatted to 2 decimals so the SAME boundary
    always produces the SAME sheet marker (parity with the frontend
    sheetTruth.polygonHashShort in frontend/src/services/sheetTruth.ts -
    keep the two implementations byte-identical).
    """
    verts = _get(poly, "vertices", None) or []
    if not verts:
        return ""
    h = 5381
    for v in verts:
        if isinstance(v, dict):
            xs, ys = v.get("x", 0.0), v.get("y", 0.0)
        else:
            xs, ys = v[0], v[1]
        for c in (_safe_float(xs, 0.0), _safe_float(ys, 0.0)):
            for b in f"{c:.2f}".encode("utf-8"):
                h = ((h * 33) + b) & 0xFFFFFFFF
    return f"{h:08x}"


def build_drawing_ir(
    floor_data: Any,
    building_model: Optional[Any] = None,
    gen_id: Optional[str] = None,
    typology: Optional[str] = None,
    theme: str = "cad",
    plot_width_m: Optional[float] = None,
    plot_depth_m: Optional[float] = None,
    total_storeys: Optional[int] = None,
    elevation_m: Optional[float] = None,
) -> FloorDrawingIR:
    """
    Constructs a normalized FloorDrawingIR in meters, Y-up convention.
    Accepts SingleFloorPlanModel, dictionary payload, or RectanglesModel.
    """
    # 1. Resolve Envelope Dimensions
    env_obj = _get(floor_data, "envelope", {}) or {}
    if not env_obj or not _get(env_obj, "width"):
        rects_sub = _get(floor_data, "rectangles")
        if rects_sub:
            env_obj = _get(rects_sub, "envelope", {}) or {}
    env_w = _safe_float(_get(env_obj, "width", 10.0), 10.0)
    env_d = _safe_float(_get(env_obj, "depth", _get(env_obj, "height", 12.0)), 12.0)
    env_x = _safe_float(_get(env_obj, "x", 0.0), 0.0)
    env_y = _safe_float(_get(env_obj, "y", 0.0), 0.0)
    if env_w <= 0.0:
        env_w = 10.0
    if env_d <= 0.0:
        env_d = 12.0

    f_idx = _safe_int(_get(floor_data, "floor_index", 0), 0)
    f_name = str(_get(floor_data, "floor_name", f"Floor {f_idx}"))
    elevation_m = _safe_float(elevation_m, f_idx * 3.0) if elevation_m is not None else float(f_idx * 3.0)

    # Building parameters
    if plot_width_m is not None:
        plot_w = _safe_float(plot_width_m, env_w + 2.6)
    else:
        plot_w = _safe_float(_get(building_model, "plot_width_m", _get(floor_data, "plot_width_m", env_w + 2.6)), env_w + 2.6)

    if plot_depth_m is not None:
        plot_d = _safe_float(plot_depth_m, env_d + 3.8)
    else:
        plot_d = _safe_float(_get(building_model, "plot_depth_m", _get(floor_data, "plot_depth_m", env_d + 3.8)), env_d + 3.8)

    total_storeys = _safe_int(total_storeys, 1) if total_storeys is not None else _safe_int(_get(building_model, "total_storeys", _get(floor_data, "total_storeys", 1)), 1)

    bldg_typ = str(typology or _get(building_model, "building_typology", _get(floor_data, "building_typology", "T1_SINGLE_FAMILY"))).upper()

    storeys_label = f"G+{total_storeys - 1}" if total_storeys > 1 else "G"
    clean_gen = str(gen_id or _get(building_model, "seed", _get(floor_data, "seed", "GEN-F01")))
    # Sheet truth: the header must carry the confirmed frontage edge and
    # the polygon hash so any sheet can be traced back to the exact captured
    # boundary (stale-guard across viewer + sheets). Rectangle-legacy builds
    # without a polygon keep the historical token (byte-stable).
    _poly_hash = _polygon_hash_short(_get(building_model, "plot_polygon", None))
    _site_prov = _get(_get(building_model, "site_plan", None), "provenance", {}) or {}
    _frtg_idx = _site_prov.get("frontage_edge_index")
    _frtg_src = _site_prov.get("frontage_source")
    _truth_tail = ""
    if _frtg_idx is not None or _frtg_src or _poly_hash:
        _frtg_txt = str(_frtg_idx) if _frtg_idx is not None else "NA"
        if _frtg_src:
            _frtg_txt = f"{_frtg_txt} ({_frtg_src})"
        _truth_tail = f" | FRTG {_frtg_txt} | POLYHASH {_poly_hash or 'NA'}"
    freshness_token = f"GEN {clean_gen} | PLOT {plot_w:.1f}m FRONTAGE x {plot_d:.1f}m DEPTH | {storeys_label} | ENV {env_w:.2f}x{env_d:.2f}m{_truth_tail}"

    # Universal validation gate (L1-L15): stamped layer list + per-layer table.
    gate_data = _get(building_model, "validation_gate", None) or _get(floor_data, "validation_gate", None) or {}
    gate_layers_list = list(gate_data.get("layers") or [])
    gate_validated = list(gate_data.get("validated_layers") or [])
    gate_overall = str(gate_data.get("overall_status", "PASS"))

    header = SheetHeaderInfo(
        gen_id=clean_gen,
        plot_w_m=plot_w,
        plot_d_m=plot_d,
        storeys=total_storeys,
        storeys_label=storeys_label,
        floor_index=f_idx,
        floor_name=f_name,
        elevation_m=elevation_m,
        envelope_w_m=env_w,
        envelope_d_m=env_d,
        freshness_token=freshness_token,
        typology=bldg_typ,
        validated_layers=gate_validated or ["L1", "L2"],
        layer_statuses=gate_layers_list,
        overall_layer_status=gate_overall,
    )

    primitives: List[DrawingPrimitive] = []

    # 2. Extract Raw Components & Normalize Coordinates (Site Setback Resolution)
    rooms_list = _get(floor_data, "rooms", [])
    if not rooms_list:
        rects_sub = _get(floor_data, "rectangles")
        if rects_sub:
            rooms_list = _get(rects_sub, "rooms", []) or _get(rects_sub, "rectangles", [])
    if not rooms_list:
        rooms_list = _get(floor_data, "placements", []) or []

    doors_data = _get(floor_data, "doors", [])
    if not doors_data:
        rects_sub = _get(floor_data, "rectangles")
        if rects_sub:
            doors_data = _get(rects_sub, "doors", [])
    doors_data = doors_data or []

    windows_data = _get(floor_data, "windows", [])
    if not windows_data:
        rects_sub = _get(floor_data, "rectangles")
        if rects_sub:
            windows_data = _get(rects_sub, "windows", [])
    windows_data = windows_data or []

    # Detect if room coordinates are in site coordinates (setback included) rather than local envelope space
    raw_min_x = min((_safe_float(_get(r, "x", 0.0), 0.0) for r in rooms_list), default=0.0)
    raw_min_y = min((_safe_float(_get(r, "y", 0.0), 0.0) for r in rooms_list), default=0.0)
    raw_max_x = max((_safe_float(_get(r, "x", 0.0), 0.0) + _safe_float(_get(r, "width_m", _get(r, "width", 0.0)), 0.0) for r in rooms_list), default=env_w)
    raw_max_y = max((_safe_float(_get(r, "y", 0.0), 0.0) + _safe_float(_get(r, "depth_m", _get(r, "height", _get(r, "depth", 0.0))), 0.0) for r in rooms_list), default=env_d)

    offset_x = 0.0
    offset_y = 0.0

    if env_x > 0.01 and raw_min_x >= env_x - 0.05:
        offset_x = env_x
    elif raw_max_x > env_w + 0.05 and raw_min_x > 0.05:
        offset_x = raw_min_x

    if env_y > 0.01 and raw_min_y >= env_y - 0.05:
        offset_y = env_y
    elif raw_max_y > env_d + 0.05 and raw_min_y > 0.05:
        offset_y = raw_min_y

    env_wings = _get(env_obj, "wings", []) or []
    is_multi_wing = len(env_wings) > 1 or bool(_get(floor_data, "is_multi_wing", False))

    # Build normalized rooms in local envelope coordinates [0.0, env_w] × [0.0, env_d]
    norm_rooms: List[Dict[str, Any]] = []
    for r in rooms_list:
        rid = str(_get(r, "room_id", "") or "")
        r_identity = identity_dict(r)
        rname = identity_name(r, rid.replace("_", " ").title())
        rx = _safe_float(_get(r, "x", 0.0), 0.0) - offset_x
        ry = _safe_float(_get(r, "y", 0.0), 0.0) - offset_y
        rw = _safe_float(_get(r, "width_m", _get(r, "width", 0.0)), 0.0)
        rd = _safe_float(_get(r, "depth_m", _get(r, "height", _get(r, "depth", 0.0))), 0.0)
        area = _safe_float(_get(r, "area_sqm", rw * rd), rw * rd)
        zone = str(_get(r, "zone", "General"))
        is_core = bool(_get(r, "is_vertical_core", False) or "stair" in rid.lower() or "lift" in rid.lower())
        u_id = _get(r, "unit_id", None)
        norm_rooms.append({
            "room_id": rid,
            "room_name": rname,
            "x": rx,
            "y": ry,
            "width_m": rw,
            "depth_m": rd,
            "width": rw,
            "height": rd,
            "area_sqm": area,
            "zone": zone,
            # Carry zone_category - the terrace drainage set keys off it
            # (the key was previously dropped, leaving that block dead code).
            "zone_category": str(_get(r, "zone_category", "")),
            "space_type_id": str(_get(r, "space_type_id", r_identity.get("space_type_id", "")) or ""),
            "identity": r_identity,
            "is_outdoor": identity_is_outdoor(r),
            # Drainage/overflow symbols are for roof terraces only; a balcony is
            # still an outdoor identity but carries a guarded edge, not a
            # 1:100 roof slope.  Annotating every balcony as a terrace caused
            # label collisions on compact plates.
            "is_terrace_drainage": (
                r_identity.get("space_type_id") == "terrace"
                or str(_get(r, "zone_category", "")).lower() == "terrace"
            ),
            "is_wet": identity_is_wet(r),
            "is_vertical_core": is_core,
            "unit_id": u_id,
            "raw": r,
        })

    # Build normalized doors
    norm_doors: List[Dict[str, Any]] = []
    for d in doors_data:
        did = str(_get(d, "door_id", ""))
        mx1 = _safe_float(_get(d, "x1", 0.0), 0.0) - offset_x
        my1 = _safe_float(_get(d, "y1", 0.0), 0.0) - offset_y
        mx2 = _safe_float(_get(d, "x2", 0.0), 0.0) - offset_x
        my2 = _safe_float(_get(d, "y2", 0.0), 0.0) - offset_y
        mhx = _safe_float(_get(d, "hinge_x", mx1 + offset_x), mx1 + offset_x) - offset_x
        mhy = _safe_float(_get(d, "hinge_y", my1 + offset_y), my1 + offset_y) - offset_y
        norm_doors.append({
            "door_id": did,
            "from_room": str(_get(d, "from_room", "")),
            "to_room": str(_get(d, "to_room", "")),
            "wall_edge": str(_get(d, "wall_edge", "vertical")),
            "x1": mx1, "y1": my1,
            "x2": mx2, "y2": my2,
            "hinge_x": mhx, "hinge_y": mhy,
            "swing_direction": str(_get(d, "swing_direction", "inward_right")),
            "width_m": _safe_float(_get(d, "width_m", 0.9), 0.9),
            "name": str(_get(d, "name", "")),
            "raw": d,
        })

    # Build normalized windows
    norm_windows: List[Dict[str, Any]] = []
    for win in windows_data:
        wid = str(_get(win, "window_id", ""))
        mx1 = _safe_float(_get(win, "x1", 0.0), 0.0) - offset_x
        my1 = _safe_float(_get(win, "y1", 0.0), 0.0) - offset_y
        mx2 = _safe_float(_get(win, "x2", 0.0), 0.0) - offset_x
        my2 = _safe_float(_get(win, "y2", 0.0), 0.0) - offset_y
        norm_windows.append({
            "window_id": wid,
            "room_id": str(_get(win, "room_id", "")),
            "wall_edge": str(_get(win, "wall_edge", "north")),
            "x1": mx1, "y1": my1,
            "x2": mx2, "y2": my2,
            "width_m": _safe_float(_get(win, "width_m", 1.2), 1.2),
            "raw": win,
        })

    # Color palette
    color_map = {
        "master_bed": "#E0F2FE",
        "living": "#DCFCE7",
        "kitchen": "#FEF3C7",
        "puja": "#FEF9C3",
        "bath_1": "#E0F2FE",
        "bath_2": "#E0F2FE",
        "bed_2": "#F1F5F9",
        "dining": "#FCE7F3",
        "stairs": "#F5F3FF",
        "corridor": "#FFFFFF",
        "lobby": "#F1F5F9",
    }

    # Generate Room Fills Layer
    parsed_rooms = []
    for r in norm_rooms:
        rid = r["room_id"]
        rname = r["room_name"]
        rx = r["x"]
        ry = r["y"]
        rw = r["width_m"]
        rd = r["depth_m"]
        area = r["area_sqm"]
        zone = r["zone"]
        is_core = r["is_vertical_core"]

        # Map to IR SW corner (Y-up convention)
        if is_multi_wing:
            rx_ir = round(rx, 3)
            ry_ir = round(ry, 3)
        else:
            rx_ir = round(rx, 3)
            if abs(rx_ir) < 1e-4:
                rx_ir = 0.0
            ry_ir = round(env_d - (ry + rd), 3)
            if abs(ry_ir) < 1e-4:
                ry_ir = 0.0

        base_rid = rid
        for u in ("_u1", "_u2", "_u3", "_u4"):
            if base_rid.endswith(u):
                base_rid = base_rid[:-len(u)]
                break

        fc = color_map.get(rid, color_map.get(base_rid, "#F8FAFC"))
        if is_core:
            fc = "#FAF5FF"

        # A terrace is a non-carpet outdoor surface; a balcony keeps the normal
        # room fill (and stays in the fill-per-room count), while both remain
        # outdoor identities for the drainage service layer.
        _raw_terrace = r["raw"]
        is_terrace = (
            identity_dict(_raw_terrace).get("space_type_id") == "terrace"
            or str(_get(_raw_terrace, "zone_category", "")).lower() == "terrace"
            or "terrace" in rid.lower()
        )
        if is_terrace:
            fc = "#F8FAFC"
            poly_pts = [
                (rx_ir, ry_ir),
                (rx_ir + rw, ry_ir),
                (rx_ir + rw, ry_ir + rd),
                (rx_ir, ry_ir + rd)
            ]
            primitives.append(PolygonPrimitive(
                layer="fills",
                points=poly_pts,
                fill_color=fc,
                stroke_color="#94A3B8",
                stroke_width_m=0.115,
                hatch_pattern="mf-hatch-terrace",
                dash_array=None
            ))

        fill_prim = FillPrimitive(
            layer="fills",
            x=rx_ir,
            y=ry_ir,
            w=rw,
            h=rd,
            fill_color=fc,
            room_id=rid,
            room_name=rname,
            zone=zone,
            is_core=is_core
        )
        primitives.append(fill_prim)
        parsed_rooms.append((r["raw"], rx_ir, ry_ir, rw, rd, rid, rname, area, zone, is_core))

    # 2b. Interior-side Functional Wedge Zones (Ground floor sheet edge absorption)
    if f_idx == 0:
        sp_obj = _get(building_model, "site_plan", _get(floor_data, "site_plan", None))
        if sp_obj:
            w_zones = _get(sp_obj, "wedge_zones", []) or []
            fp_obj = _get(sp_obj, "footprint", {}) or {}
            fp_x = _safe_float(_get(fp_obj, "x", env_x), env_x)
            fp_y = _safe_float(_get(fp_obj, "y", env_y), env_y)
            for wz in w_zones:
                if _get(wz, "is_interior_side", False):
                    w_coords = _get(wz, "polygon_coords", [])
                    if w_coords:
                        w_pts_ir = [(float(pt[0]) - fp_x, float(pt[1]) - fp_y) for pt in w_coords]
                        primitives.append(PolygonPrimitive(
                            layer="fills",
                            points=w_pts_ir,
                            fill_color="#FEF3C7",
                            fill_opacity=0.60,
                            stroke_color="#D97706",
                            stroke_width_m=0.15,
                            dash_array=[3, 2],
                            hatch_pattern="mf-hatch-wedge",
                            is_boundary=False
                        ))
                        w_cent = _get(wz, "centroid", (0.0, 0.0))
                        w_name = str(_get(wz, "name", "Storage Wedge"))
                        w_area = float(_get(wz, "area_sqm", 0.0))
                        primitives.append(TextPrimitive(
                            layer="text",
                            x=round(float(w_cent[0]) - fp_x, 2),
                            y=round(float(w_cent[1]) - fp_y, 2),
                            text=w_name.upper(),
                            subtext=f"{w_area:.1f} m² | NON-CARPET",
                            font_size_pt=6.5,
                            font_weight="bold",
                            halo=True
                        ))

    # 3. Wall Graph & Walls Layer
    wg_dict = _get(floor_data, "wall_graph")
    if wg_dict is not None and hasattr(wg_dict, "to_dict"):
        wg_dict = wg_dict.to_dict()
    if wg_dict is None:
        try:
            from app.services.floorplan.wall_graph import build_constructible_wall_graph
            # Specification grade resolves the finish schedule; read it from the
            # floor record, the building model, or a captured params snapshot.
            _finish_grade = (
                _get(floor_data, "quality_grade", None)
                or _get(_get(floor_data, "params_snapshot", None), "quality_grade", None)
                or _get(building_model, "quality_grade", None)
                or _get(_get(building_model, "params_snapshot", None), "quality_grade", None)
                or "standard"
            )
            raw_wg = build_constructible_wall_graph(
                floor_index=f_idx,
                envelope={"width": env_w, "depth": env_d},
                raw_rooms=norm_rooms,
                typology=bldg_typ,
                floor_to_floor_height_m=3.0,
                doors_in=norm_doors,
                windows_in=norm_windows,
                quality_grade=str(_finish_grade),
            )
            if raw_wg:
                wg_dict = raw_wg.to_dict()
        except Exception:
            wg_dict = None

    if wg_dict and isinstance(wg_dict, dict) and "walls" in wg_dict:
        walls_data = wg_dict.get("walls", [])
        if isinstance(walls_data, dict):
            walls_data = list(walls_data.values())
        for w in walls_data:
            wt = str(_get(w, "wall_type", "W2"))
            wx1 = _safe_float(_get(w, "x1", 0.0), 0.0)
            wy1 = _safe_float(_get(w, "y1", 0.0), 0.0)
            wx2 = _safe_float(_get(w, "x2", 0.0), 0.0)
            wy2 = _safe_float(_get(w, "y2", 0.0), 0.0)
            th = _safe_float(_get(w, "thickness_m", 0.115), 0.115)
            is_ext = bool(_get(w, "is_exterior", wt == "W1"))
            is_lb = bool(_get(w, "is_load_bearing", wt == "W1"))

            # Convert to Y-up
            if is_multi_wing:
                wx1_ir = wx1
                wy1_ir = wy1
                wx2_ir = wx2
                wy2_ir = wy2
            else:
                wx1_ir = wx1
                wy1_ir = env_d - wy1
                wx2_ir = wx2
                wy2_ir = env_d - wy2

            primitives.append(WallPrimitive(
                layer="walls",
                wall_id=str(_get(w, "wall_id", "")),
                wall_type=wt if wt in ("W1", "W2", "W3", "W_PARAPET") else "W2",
                x1=wx1_ir,
                y1=wy1_ir,
                x2=wx2_ir,
                y2=wy2_ir,
                thickness_m=th,
                is_exterior=is_ext,
                is_load_bearing=is_lb,
                dash_array=[0.08, 0.06] if wt == "W3" else None
            ))
    else:
        # Fallback wall construction from envelope & room borders
        # Exterior Envelope W1 (230mm)
        primitives.append(WallPrimitive(layer="walls", wall_id="W_EXT_S", wall_type="W1", x1=0.0, y1=0.0, x2=env_w, y2=0.0, thickness_m=0.23, is_exterior=True, is_load_bearing=True))
        primitives.append(WallPrimitive(layer="walls", wall_id="W_EXT_N", wall_type="W1", x1=0.0, y1=env_d, x2=env_w, y2=env_d, thickness_m=0.23, is_exterior=True, is_load_bearing=True))
        primitives.append(WallPrimitive(layer="walls", wall_id="W_EXT_W", wall_type="W1", x1=0.0, y1=0.0, x2=0.0, y2=env_d, thickness_m=0.23, is_exterior=True, is_load_bearing=True))
        primitives.append(WallPrimitive(layer="walls", wall_id="W_EXT_E", wall_type="W1", x1=env_w, y1=0.0, x2=env_w, y2=env_d, thickness_m=0.23, is_exterior=True, is_load_bearing=True))

        # Interior Room Partitions W2 (115mm) from adjacent room borders
        seen_fallback_walls = set()
        for i, rA in enumerate(norm_rooms):
            for j in range(i + 1, len(norm_rooms)):
                rB = norm_rooms[j]
                # Check vertical boundary
                if abs((rA["x"] + rA["width_m"]) - rB["x"]) < 0.05 or abs((rB["x"] + rB["width_m"]) - rA["x"]) < 0.05:
                    x_b = (rA["x"] + rA["width_m"] + rB["x"]) / 2.0 if abs((rA["x"] + rA["width_m"]) - rB["x"]) < 0.05 else (rB["x"] + rB["width_m"] + rA["x"]) / 2.0
                    y_min = max(rA["y"], rB["y"])
                    y_max = min(rA["y"] + rA["depth_m"], rB["y"] + rB["depth_m"])
                    if y_max - y_min >= 0.40:
                        ekey = ("V", round(x_b, 2), round(y_min, 2), round(y_max, 2))
                        if ekey not in seen_fallback_walls:
                            seen_fallback_walls.add(ekey)
                            primitives.append(WallPrimitive(
                                layer="walls",
                                wall_id=f"W_INT_V_{len(seen_fallback_walls)}",
                                wall_type="W2",
                                x1=x_b,
                                y1=y_min if is_multi_wing else (env_d - y_min),
                                x2=x_b,
                                y2=y_max if is_multi_wing else (env_d - y_max),
                                thickness_m=0.115,
                                is_exterior=False,
                                is_load_bearing=False
                            ))
                # Check horizontal boundary
                if abs((rA["y"] + rA["depth_m"]) - rB["y"]) < 0.05 or abs((rB["y"] + rB["depth_m"]) - rA["y"]) < 0.05:
                    y_b = (rA["y"] + rA["depth_m"] + rB["y"]) / 2.0 if abs((rA["y"] + rA["depth_m"]) - rB["y"]) < 0.05 else (rB["y"] + rB["depth_m"] + rA["y"]) / 2.0
                    x_min = max(rA["x"], rB["x"])
                    x_max = min(rA["x"] + rA["width_m"], rB["x"] + rB["width_m"])
                    if x_max - x_min >= 0.40:
                        ekey = ("H", round(y_b, 2), round(x_min, 2), round(x_max, 2))
                        if ekey not in seen_fallback_walls:
                            seen_fallback_walls.add(ekey)
                            primitives.append(WallPrimitive(
                                layer="walls",
                                wall_id=f"W_INT_H_{len(seen_fallback_walls)}",
                                wall_type="W2",
                                x1=x_min,
                                y1=y_b if is_multi_wing else (env_d - y_b),
                                x2=x_max,
                                y2=y_b if is_multi_wing else (env_d - y_b),
                                thickness_m=0.115,
                                is_exterior=False,
                                is_load_bearing=False
                            ))

    # 4. Openings Layer (Doors & Windows)
    d_counter = 1
    for d in norm_doors:
        did = str(_get(d, "door_id", f"D{d_counter}"))
        wedge = str(_get(d, "wall_edge", "vertical"))
        swing = str(_get(d, "swing_direction", "inward_right"))
        dw = _safe_float(_get(d, "width_m", 0.9), 0.9)

        mx1 = _safe_float(_get(d, "x1", 0.0), 0.0)
        my1 = _safe_float(_get(d, "y1", 0.0), 0.0)
        mx2 = _safe_float(_get(d, "x2", 0.0), 0.0)
        my2 = _safe_float(_get(d, "y2", 0.0), 0.0)
        mhx = _safe_float(_get(d, "hinge_x", mx1), mx1)
        mhy = _safe_float(_get(d, "hinge_y", my1), my1)

        if is_multi_wing:
            hx_ir = mhx
            hy_ir = mhy
            if abs(mx1 - mhx) < 0.02 and abs(my1 - mhy) < 0.02:
                mcx, mcy = mx2, my2
            else:
                mcx, mcy = mx1, my1
            cx_ir = mcx
            cy_ir = mcy

            if wedge in ("vertical", "east", "west"):
                mlx = mhx - dw if "left" in swing else mhx + dw
                mly = mhy
            elif wedge == "south":
                mlx = mhx
                mly = mhy + dw
            elif wedge == "north":
                mlx = mhx
                mly = mhy - dw
            else:
                mlx = mhx
                mly = mhy + dw

            lx_ir = mlx
            ly_ir = mly

            # Keep the swing inside the building (see _door_leaf_inside).
            lx_ir, ly_ir = _door_leaf_inside(env_w, env_d, (hx_ir, hy_ir), (lx_ir, ly_ir))
            mlx = lx_ir
            mly = ly_ir

            ang_closed = round(math.degrees(math.atan2(cy_ir - hy_ir, cx_ir - hx_ir))) % 360
            ang_open = round(math.degrees(math.atan2(ly_ir - hy_ir, lx_ir - hx_ir))) % 360

            diff = (ang_open - ang_closed) % 360
            if diff in (90, 270):
                start_deg = min(ang_closed, ang_open)
                end_deg = start_deg + 90
            else:
                start_deg = min(ang_closed, ang_open)
                end_deg = start_deg + 90

            v1_x = mcx - mhx
            v1_y_svg = -(mcy - mhy)
            v2_x = mlx - mhx
            v2_y_svg = -(mly - mhy)
            cp = (v1_x * v2_y_svg) - (v1_y_svg * v2_x)
            svg_swp = 1 if cp > 0 else 0

            jambs = []
            if wedge in ("vertical", "east", "west"):
                jambs.append(((hx_ir - 0.08, hy_ir), (hx_ir + 0.08, hy_ir)))
                jambs.append(((cx_ir - 0.08, cy_ir), (cx_ir + 0.08, cy_ir)))
            else:
                jambs.append(((hx_ir, hy_ir - 0.08), (hx_ir, hy_ir + 0.08)))
                jambs.append(((cx_ir, cy_ir - 0.08), (cx_ir, cy_ir + 0.08)))
        else:
            hx_ir = mhx
            hy_ir = env_d - mhy

            if abs(mx1 - mhx) < 0.02 and abs(my1 - mhy) < 0.02:
                mcx, mcy = mx2, my2
            else:
                mcx, mcy = mx1, my1
            cx_ir = mcx
            cy_ir = env_d - mcy

            if wedge in ("vertical", "east", "west"):
                mlx = mhx - dw if "left" in swing else mhx + dw
                mly = mhy
            else:
                mlx = mhx
                mly = mhy - dw if "left" in swing else mhy + dw

            lx_ir = mlx
            ly_ir = env_d - mly

            # Keep the swing inside the building (see _door_leaf_inside).
            lx_ir, ly_ir = _door_leaf_inside(env_w, env_d, (hx_ir, hy_ir), (lx_ir, ly_ir))
            mlx = lx_ir
            mly = env_d - ly_ir

            ang_closed = round(math.degrees(math.atan2(cy_ir - hy_ir, cx_ir - hx_ir))) % 360
            ang_open = round(math.degrees(math.atan2(ly_ir - hy_ir, lx_ir - hx_ir))) % 360

            diff = (ang_open - ang_closed) % 360
            if diff == 90:
                start_deg = ang_closed
                end_deg = ang_closed + 90
            elif diff == 270:
                start_deg = ang_open
                end_deg = ang_open + 90
            else:
                start_deg = min(ang_closed, ang_open)
                end_deg = start_deg + 90

            v1_x = mcx - mhx
            v1_y = mcy - mhy
            v2_x = mlx - mhx
            v2_y = mly - mhy
            cp = (v1_x * v2_y) - (v1_y * v2_x)
            svg_swp = 1 if cp > 0 else 0

            jambs = []
            if wedge in ("vertical", "east", "west"):
                jambs.append(((hx_ir - 0.08, hy_ir), (hx_ir + 0.08, hy_ir)))
                jambs.append(((cx_ir - 0.08, cy_ir), (cx_ir + 0.08, cy_ir)))
            else:
                jambs.append(((hx_ir, hy_ir - 0.08), (hx_ir, hy_ir + 0.08)))
                jambs.append(((cx_ir, cy_ir - 0.08), (cx_ir, cy_ir + 0.08)))

        d_tag = f"D{d_counter}"
        d_counter += 1

        tag_x = (hx_ir + lx_ir) / 2.0
        tag_y = (hy_ir + ly_ir) / 2.0

        # Requirement C: T2/T3 unit entry door badges
        to_rm_id = str(_get(d, "to_room", ""))
        from_rm_id = str(_get(d, "from_room", ""))
        to_rm = next((r for r in rooms_list if str(_get(r, "room_id", "")) == to_rm_id), None)
        from_rm = next((r for r in rooms_list if str(_get(r, "room_id", "")) == from_rm_id), None)
        # A unit badge belongs on the unit *entry* door (shared lobby/corridor
        # on one side, unit room on the other).  Tagging every internal door of
        # the unit printed four identical "UNIT A" chips per flat, on top of
        # the bath, kitchen and bedroom tags.
        to_is_unit = bool(to_rm and _get(to_rm, "unit_id"))
        from_is_unit = bool(from_rm and _get(from_rm, "unit_id"))
        if to_is_unit and from_is_unit:
            matched_rm = None
        elif to_is_unit or from_is_unit:
            matched_rm = to_rm if to_is_unit else from_rm
        else:
            matched_rm = to_rm or from_rm
        unit_badge = None
        if matched_rm:
            u_id = str(_get(matched_rm, "unit_id", "") or "")
            r_name = str(_get(matched_rm, "room_name", "") or "")
            r_id = str(_get(matched_rm, "room_id", "") or "")
            comb = f"{u_id} {r_name} {r_id}"
            _rx = _safe_float(_get(matched_rm, "x", 0.0), 0.0)
            _ry = _safe_float(_get(matched_rm, "y", 0.0), 0.0)
            _rw = _safe_float(_get(matched_rm, "width_m", _get(matched_rm, "width", 0.0)), 0.0)
            _rd = _safe_float(_get(matched_rm, "depth_m", _get(matched_rm, "height", 0.0)), 0.0)
            # The room frame the badge may print inside (IR coordinates).
            # Badges ride a door hinge, but a hinge-relative offset puts two
            # adjacent unit entries on top of each other and on the stair
            # "UP" letter; the unit's own room is the collision-free anchor.
            _badge_rect = (
                (_rx, _ry, _rw, _rd)
                if is_multi_wing
                else (_rx, env_d - (_ry + _rd), _rw, _rd)
            )
            tag = None
            if "A" in u_id or "North" in comb or "suite_north" in r_id.lower() or "unit 1" in r_name.lower() or ("T3" in bldg_typ and ("reception" in r_id.lower() or "main_entry" in did.lower() or "reception" in to_rm_id.lower() or "reception" in from_rm_id.lower())):
                tag = "UNIT A"
            elif "B" in u_id or "South" in comb or "suite_south" in r_id.lower() or "unit 2" in r_name.lower() or ("T3" in bldg_typ and ("conference" in r_id.lower() or "lounge" in r_id.lower() or "conference" in to_rm_id.lower() or "visitor_lounge" in to_rm_id.lower())):
                tag = "UNIT B"
            elif u_id:
                tag = u_id.replace("_", " ").upper()
            if tag:
                unit_badge = {
                    "tag": tag,
                    "x": hx_ir + 0.1,
                    "y": hy_ir - 0.35,
                    "rect": _badge_rect,
                }

        op_prim = OpeningPrimitive(
            layer="openings",
            opening_id=did,
            opening_type="door",
            tag=d_tag,
            wall_edge=wedge,
            x1=min(hx_ir, cx_ir),
            y1=min(hy_ir, cy_ir),
            x2=max(hx_ir, cx_ir),
            y2=max(hy_ir, cy_ir),
            hinge_x=hx_ir,
            hinge_y=hy_ir,
            leaf_x=lx_ir,
            leaf_y=ly_ir,
            arc_center_x=hx_ir,
            arc_center_y=hy_ir,
            arc_radius_m=dw,
            arc_start_deg=start_deg,
            arc_end_deg=end_deg,
            arc_start_pt=(cx_ir, cy_ir),
            arc_end_pt=(lx_ir, ly_ir),
            svg_sweep_flag=svg_swp,
            door_jambs=jambs,
            tag_x=tag_x,
            tag_y=tag_y,
            unit_badge=unit_badge
        )
        primitives.append(op_prim)

    # Windows
    w_counter = 1
    for win in norm_windows:
        wid = str(_get(win, "window_id", f"W{w_counter}"))
        wedge = str(_get(win, "wall_edge", "north"))
        mx1 = _safe_float(_get(win, "x1", 0.0), 0.0)
        my1 = _safe_float(_get(win, "y1", 0.0), 0.0)
        mx2 = _safe_float(_get(win, "x2", 0.0), 0.0)
        my2 = _safe_float(_get(win, "y2", 0.0), 0.0)

        if is_multi_wing:
            x1_ir = mx1
            y1_ir = my1
            x2_ir = mx2
            y2_ir = my2
        else:
            x1_ir = mx1
            y1_ir = env_d - my1
            x2_ir = mx2
            y2_ir = env_d - my2

        length = math.hypot(x2_ir - x1_ir, y2_ir - y1_ir)
        if length > 0.01:
            ux = (x2_ir - x1_ir) / length
            uy = (y2_ir - y1_ir) / length
            nx = -uy
            ny = ux
        else:
            nx, ny = 0.0, 1.0

        offset_m = 0.06
        outer_p1 = (x1_ir + nx * offset_m, y1_ir + ny * offset_m)
        outer_p2 = (x2_ir + nx * offset_m, y2_ir + ny * offset_m)
        glass_p1 = (x1_ir, y1_ir)
        glass_p2 = (x2_ir, y2_ir)
        inner_p1 = (x1_ir - nx * offset_m, y1_ir - ny * offset_m)
        inner_p2 = (x2_ir - nx * offset_m, y2_ir - ny * offset_m)

        wjambs = [
            (outer_p1, inner_p1),
            (outer_p2, inner_p2),
        ]

        w_tag = f"W{w_counter}"
        w_counter += 1
        tag_x = (x1_ir + x2_ir) / 2.0
        tag_y = (y1_ir + y2_ir) / 2.0

        win_prim = OpeningPrimitive(
            layer="openings",
            opening_id=wid,
            opening_type="window",
            tag=w_tag,
            wall_edge=wedge,
            x1=min(x1_ir, x2_ir),
            y1=min(y1_ir, y2_ir),
            x2=max(x1_ir, x2_ir),
            y2=max(y1_ir, y2_ir),
            outer_line=(outer_p1, outer_p2),
            glass_line=(glass_p1, glass_p2),
            inner_line=(inner_p1, inner_p2),
            window_jambs=wjambs,
            tag_x=tag_x,
            tag_y=tag_y
        )
        primitives.append(win_prim)

    # 5. Staircase Primitive Layer
    stair_room = next((r for r in parsed_rooms if r[9]), None)
    if stair_room:
        _, s_rx, s_ry, s_rw, s_rd, _, _, _, _, _ = stair_room
        stair_geom = _get(floor_data, "stair_geometry") or (_get(wg_dict, "stair_geometry") if wg_dict else None)
        treads_per_fl = _safe_int(_get(stair_geom, "treads_per_flight", 8), 8)
        landing_depth = _safe_float(_get(stair_geom, "landing_depth_m", 1.2), 1.2)

        landing_d = max(0.9, min(s_rd * 0.40, landing_depth))
        landing_y = s_ry + s_rd - landing_d
        flight_h = s_rd - landing_d
        mid_x = s_rx + s_rw / 2.0

        treads_lines = []
        num_treads = max(4, min(12, treads_per_fl))
        for t in range(1, num_treads):
            ty = s_ry + (flight_h / num_treads) * t
            treads_lines.append(((s_rx + 0.05, ty), (mid_x - 0.05, ty)))
            treads_lines.append(((mid_x + 0.05, ty), (s_rx + s_rw - 0.05, ty)))

        fl1_cx = s_rx + (mid_x - s_rx) / 2.0
        up_arr_p1 = (fl1_cx, s_ry + 0.3)
        up_arr_p2 = (fl1_cx, landing_y - 0.2)
        up_tip = [(fl1_cx - 0.12, landing_y - 0.35), (fl1_cx, landing_y - 0.15), (fl1_cx + 0.12, landing_y - 0.35)]
        up_txt = (fl1_cx, s_ry + 0.2)

        dn_arr = None
        dn_tip = None
        dn_txt = None
        if f_idx > 0:
            fl2_cx = mid_x + (s_rx + s_rw - mid_x) / 2.0
            dn_arr = ((fl2_cx, landing_y - 0.2), (fl2_cx, s_ry + 0.3))
            dn_tip = [(fl2_cx - 0.12, s_ry + 0.45), (fl2_cx, s_ry + 0.25), (fl2_cx + 0.12, s_ry + 0.45)]
            dn_txt = (fl2_cx, landing_y - 0.35)

        # Headroom note as a compact tag inside the mid-landing (empty band);
        # the value is the AS-COMPUTED soffit headroom threaded from the stair
        # geometry (asserted >= 2.20m at source), not a fixed string.
        _headroom_computed = _safe_float(
            _get(stair_geom, "headroom_min_m", None) if stair_geom is not None else None,
            2.20,
        )
        stair_prim = StairPrimitive(
            layer="cores",
            boundary=(s_rx, s_ry, s_rw, s_rd),
            landing_line=((s_rx, landing_y), (s_rx + s_rw, landing_y)),
            dividing_line=((mid_x, s_ry), (mid_x, landing_y)),
            treads=treads_lines,
            up_line=(up_arr_p1, up_arr_p2),
            up_tip=up_tip,
            up_text_pos=up_txt,
            dn_line=dn_arr,
            dn_tip=dn_tip,
            dn_text_pos=dn_txt,
            headroom_text_pos=(s_rx + s_rw / 2.0, landing_y + landing_d / 2.0),
            headroom_text=f"CLr {_headroom_computed:.2f}m"
        )
        primitives.append(stair_prim)

    # 6. Ghost Core Overlay Layer (F1+)
    if f_idx > 0 and building_model:
        v_cores = _get(building_model, "vertical_cores", []) or []
        d_shafts = _get(building_model, "duct_shafts", []) or []
        ghost_core_rects = []
        ghost_tread_lines = []

        footprint_poly = None
        if is_multi_wing and env_wings:
            from shapely.geometry import box as shp_box
            from shapely.ops import unary_union
            wing_geoms = [
                shp_box(
                    _safe_float(_get(w, "x", 0.0), 0.0) - offset_x,
                    _safe_float(_get(w, "y", 0.0), 0.0) - offset_y,
                    _safe_float(_get(w, "x", 0.0), 0.0) - offset_x + _safe_float(_get(w, "width_m", 0.0), 0.0),
                    _safe_float(_get(w, "y", 0.0), 0.0) - offset_y + _safe_float(_get(w, "depth_m", 0.0), 0.0)
                )
                for w in env_wings
            ]
            footprint_poly = unary_union(wing_geoms) if wing_geoms else None

        for gc in v_cores:
            gc_x = _safe_float(_get(gc, "x", 0.0), 0.0)
            gc_y = _safe_float(_get(gc, "y", 0.0), 0.0)
            gc_w = _safe_float(_get(gc, "width_m", _get(gc, "width", 0.0)), 0.0)
            gc_d = _safe_float(_get(gc, "depth_m", _get(gc, "depth", _get(gc, "height", 0.0))), 0.0)
            if footprint_poly:
                core_b = shp_box(gc_x, gc_y, gc_x + gc_w, gc_y + gc_d)
                if not footprint_poly.intersects(core_b) or footprint_poly.intersection(core_b).area < 0.01:
                    continue
            if is_multi_wing:
                gc_x_ir = gc_x
                gc_y_ir = gc_y
            else:
                gc_x_ir = gc_x
                gc_y_ir = env_d - (gc_y + gc_d)
            ghost_core_rects.append((gc_x_ir, gc_y_ir, gc_w, gc_d))

            has_matching_stair = any(
                r[9] and abs(r[1] - gc_x_ir) < 0.2 and abs(r[2] - gc_y_ir) < 0.2
                for r in parsed_rooms
            )
            if not has_matching_stair:
                for t in range(1, 6):
                    t_y = gc_y_ir + (gc_d / 6.0) * t
                    ghost_tread_lines.append(((gc_x_ir + 0.1, t_y), (gc_x_ir + gc_w - 0.1, t_y)))

        ghost_shaft_rects = []
        # SERVICE-LAYER TOGGLE: duct shafts (service drawing) respect the
        # include_service_layer request flag; default ON keeps legacy behavior.
        _svc_on = bool(_get(building_model, "include_service_layer", True))
        for ds in ([] if not _svc_on else d_shafts):
            ds_x = _safe_float(_get(ds, "x", 0.0), 0.0)
            ds_y = _safe_float(_get(ds, "y", 0.0), 0.0)
            ds_w = _safe_float(_get(ds, "width_m", _get(ds, "width", 0.0)), 0.0)
            ds_d = _safe_float(_get(ds, "depth_m", _get(ds, "depth", _get(ds, "height", 0.0))), 0.0)
            if footprint_poly:
                shaft_b = shp_box(ds_x, ds_y, ds_x + ds_w, ds_y + ds_d)
                if not footprint_poly.intersects(shaft_b) or footprint_poly.intersection(shaft_b).area < 0.01:
                    continue
            if is_multi_wing:
                ghost_shaft_rects.append((ds_x, ds_y, ds_w, ds_d))
            else:
                ghost_shaft_rects.append((ds_x, env_d - (ds_y + ds_d), ds_w, ds_d))

        badge_dict = None
        if ghost_core_rects:
            # Match svg_generator.py candidate placement around core in circulation lobby
            gc_0 = v_cores[0] if v_cores else None
            gc_x_m = _safe_float(_get(gc_0, "x", 0.0), 0.0)
            gc_y_m = _safe_float(_get(gc_0, "y", 0.0), 0.0)
            gc_w_m = _safe_float(_get(gc_0, "width_m", _get(gc_0, "width", 0.0)), 0.0)
            gc_d_m = _safe_float(_get(gc_0, "depth_m", _get(gc_0, "depth", _get(gc_0, "height", 0.0))), 0.0)

            c_scale = 36.0
            c_mx = 75.0
            c_my = 75.0
            gx_s = c_mx + gc_x_m * c_scale
            gy_s = c_my + gc_y_m * c_scale
            gw_s = gc_w_m * c_scale
            gh_s = gc_d_m * c_scale
            l_len = 0.3 * c_scale
            b_w = 68.0
            b_h = 14.0

            # Door boxes in svg space
            d_boxes = []
            for d_tmp in doors_data:
                mhx_t = _safe_float(_get(d_tmp, "hinge_x", _get(d_tmp, "x1", 0.0)), 0.0)
                mhy_t = _safe_float(_get(d_tmp, "hinge_y", _get(d_tmp, "y1", 0.0)), 0.0)
                mdw_t = max(_safe_float(_get(d_tmp, "width_m", 0.9), 0.9) * c_scale, 22.0)
                wedge_t = str(_get(d_tmp, "wall_edge", "vertical"))
                swing_t = str(_get(d_tmp, "swing_direction", "inward_right"))
                if wedge_t in ("vertical", "east", "west"):
                    mlx_t = mhx_t - mdw_t if swing_t == "inward_left" else mhx_t + mdw_t
                    mly_t = mhy_t
                else:
                    mlx_t = mhx_t
                    mly_t = mhy_t - mdw_t if swing_t == "inward_left" else mhy_t + mdw_t
                thx_s = c_mx + mhx_t * c_scale
                thy_s = c_my + mhy_t * c_scale
                tlx_s = c_mx + mlx_t * c_scale
                tly_s = c_my + mly_t * c_scale
                td_cx = (thx_s + tlx_s) / 2.0
                td_cy = (thy_s + tly_s) / 2.0
                d_boxes.append(BBox(td_cx - 10.0, td_cy - 8.0, td_cx + 10.0, td_cy + 8.0))
                # The unit badge and door tag ride the hinge; reserve that corner so
                # the anchor badge never prints over the door furniture.
                d_boxes.append(BBox(thx_s + 2.0, thy_s - 24.0, thx_s + 46.0, thy_s + 28.0))

            cands = [
                (gx_s + gw_s + l_len, gy_s + gh_s - b_h - 4.0, gx_s + gw_s, gy_s + gh_s - 10.0, gx_s + gw_s + l_len, gy_s + gh_s - 4.0 - b_h / 2.0),
                (gx_s + gw_s + l_len, gy_s + gh_s / 2.0 - b_h / 2.0, gx_s + gw_s, gy_s + gh_s / 2.0, gx_s + gw_s + l_len, gy_s + gh_s / 2.0),
                (gx_s + gw_s / 2.0 - b_w / 2.0, gy_s + gh_s + l_len, gx_s + gw_s / 2.0, gy_s + gh_s, gx_s + gw_s / 2.0, gy_s + gh_s + l_len),
                (gx_s - l_len - b_w, gy_s + gh_s - b_h - 4.0, gx_s, gy_s + gh_s - 10.0, gx_s - l_len, gy_s + gh_s - 4.0 - b_h / 2.0),
                # Escape slots: on a door-dense plate every slot above can be occupied
                # by door furniture, so offer the mirrored side and top corners too.
                (gx_s - l_len - b_w, gy_s + gh_s / 2.0 - b_h / 2.0, gx_s, gy_s + gh_s / 2.0, gx_s - l_len, gy_s + gh_s / 2.0 - b_h / 2.0),
                (gx_s + gw_s + l_len, gy_s + l_len, gx_s + gw_s, gy_s + l_len + b_h / 2.0, gx_s + gw_s + l_len, gy_s + l_len + b_h / 2.0),
                (gx_s - l_len - b_w, gy_s + l_len, gx_s, gy_s + l_len + b_h / 2.0, gx_s - l_len, gy_s + l_len + b_h / 2.0),
                # Inside the ghost core itself (clear of its treads' annotations):
                # the one place on a dense plate that no room label can claim.
                (gx_s + max(2.0, (gw_s - b_w) / 2.0), gy_s + gh_s - b_h - 6.0, gx_s + gw_s / 2.0, gy_s + gh_s - 6.0, gx_s + gw_s / 2.0, gy_s + gh_s - b_h - 6.0),
            ]
            # Side-margin callout slots: outside the plan, level with the core.
            # Drawn with a leader, this is where the anchor note goes when the plate
            # is too dense to hold the badge anywhere inside.
            _margin_lo = max(2.0, c_mx - b_w - 4.0)
            _margin_hi = c_mx + env_w * c_scale + 6.0
            for _sy in (gy_s + gh_s - b_h - 4.0, gy_s + gh_s / 2.0 - b_h / 2.0, gy_s + l_len):
                cands.append((_margin_lo, _sy, _margin_lo + b_w, _sy + b_h / 2.0, _margin_lo + b_w, _sy + b_h / 2.0))
                cands.append((_margin_hi, _sy, _margin_hi, _sy + b_h / 2.0, _margin_hi, _sy + b_h / 2.0))
            # Room centroids carry the Level-3 numbered tag circle when a room is
            # too small for its name, so the anchor badge must dodge those too.
            room_tag_zones: List[BBox] = []
            for r_parsed in parsed_rooms:
                r_cx = c_mx + (r_parsed[1] + r_parsed[3] / 2.0) * c_scale
                r_cy = c_my + (env_d - (r_parsed[2] + r_parsed[4] / 2.0)) * c_scale
                room_tag_zones.append(BBox(r_cx - 9.0, r_cy - 9.0, r_cx + 9.0, r_cy + 9.0))

            # Stair annotations inside the core (UP / DN / clear headroom) are fixed
            # text, so the badge must leave them readable too.
            if 'stair_prim' in locals() and stair_prim is not None:
                for _tx, _ty in (stair_prim.up_text_pos, stair_prim.dn_text_pos, stair_prim.headroom_text_pos):
                    if _tx is None or _ty is None:
                        continue
                    _tx_px = c_mx + _tx * c_scale
                    _ty_px = c_my + (env_d - _ty) * c_scale
                    room_tag_zones.append(BBox(_tx_px - 20.0, _ty_px - 9.0, _tx_px + 20.0, _ty_px + 9.0))

            # Grid bubbles sit in the right margin; keep the badge off them.
            if not ("T1" in bldg_typ or "SINGLE" in bldg_typ):
                for _gy_m in (0.0, env_d / 2.0, env_d):
                    _gy_px = c_my + _gy_m * c_scale
                    _gx_px = c_mx + (env_w + 0.60) * c_scale
                    room_tag_zones.append(BBox(_gx_px - 10.0, _gy_px - 10.0, _gx_px + 10.0, _gy_px + 10.0))

            # Prefer a free slot; otherwise take the least-overlapping one so the
            # badge never lands squarely on top of a door tag or unit badge.
            def _badge_cost(c_cand: Tuple[float, ...]) -> float:
                cbx, cby = c_cand[0], c_cand[1]
                c_bbox = BBox(cbx, cby, cbx + b_w, cby + b_h)
                cost = 0.0
                for db in d_boxes:
                    if c_bbox.intersects(db):
                        cost += max(1.0, c_bbox.intersection_area(db))
                for rb in room_tag_zones:
                    if c_bbox.intersects(rb):
                        cost += max(1.0, c_bbox.intersection_area(rb))
                inside_plan = (
                    cbx >= c_mx and cbx + b_w <= c_mx + env_w * c_scale and
                    cby >= c_my and cby + b_h <= c_my + env_d * c_scale
                )
                in_side_margin = (
                    (cbx >= 2.0 and cbx + b_w <= c_mx - 4.0) or
                    (cbx >= c_mx + env_w * c_scale + 4.0 and cbx + b_w <= c_mx + env_w * c_scale + 64.0)
                )
                if inside_plan:
                    pass
                elif in_side_margin and cby >= c_my - 20.0:
                    cost += 30.0  # callout outside the plan: allowed, but not preferred
                else:
                    cost += 1000.0
                return cost

            chosen = min(cands, key=_badge_cost)

            ch_bx, ch_by, ch_lx1, ch_ly1, ch_lx2, ch_ly2 = chosen
            # Convert chosen candidate to IR Y-up meters
            bx_ir = (ch_bx - c_mx) / c_scale
            by_ir = env_d - ((ch_by + b_h - c_my) / c_scale)
            bw_ir = b_w / c_scale
            bh_ir = b_h / c_scale
            lx1_ir = (ch_lx1 - c_mx) / c_scale
            ly1_ir = env_d - ((ch_ly1 - c_my) / c_scale)
            lx2_ir = (ch_lx2 - c_mx) / c_scale
            ly2_ir = env_d - ((ch_ly2 - c_my) / c_scale)

            badge_dict = {
                "badge_x": bx_ir,
                "badge_y": by_ir,
                "badge_w": bw_ir,
                "badge_h": bh_ir,
                "leader_p1": (lx1_ir, ly1_ir),
                "leader_p2": (lx2_ir, ly2_ir),
                "text": "F0 CORE ANCHOR",
                "svg_badge_x": ch_bx,
                "svg_badge_y": ch_by,
                "svg_badge_w": b_w,
                "svg_badge_h": b_h,
            }

        ghost_prim = GhostPrimitive(
            layer="ghost",
            core_rects=ghost_core_rects,
            ghost_treads=ghost_tread_lines,
            anchor_badge=badge_dict,
            duct_shafts=ghost_shaft_rects
        )
        primitives.append(ghost_prim)

    # 7. Text & Typography Layer (Global Collision Resolution Engine)
    ghost_prim = None if 'ghost_prim' not in locals() else ghost_prim
    col_scale = 36.0
    col_mx = 75.0
    col_my = 75.0

    def col_px(xm: float) -> float:
        return col_mx + (xm * col_scale)

    def col_py(ym_from_north: float) -> float:
        return col_my + (ym_from_north * col_scale)

    fixed_obstacles: List[Tuple[str, BBox]] = []

    # Obstacle 1: Compass
    compass_cx = col_mx + env_w * col_scale + 20.0
    compass_cy = col_my - 39.0
    fixed_obstacles.append(("compass", BBox(compass_cx - 16.0, compass_cy - 16.0, compass_cx + 16.0, compass_cy + 16.0)))

    # Obstacle 2: Main Entrance
    if f_idx == 0:
        main_door = next((d for d in doors_data if _get(d, "door_id") == "D1" or "main" in str(_get(d, "name", "")).lower()), None)
        door_x_m = env_w * 0.45
        if main_door:
            mx1 = _safe_float(_get(main_door, "x1", 0.0), 0.0)
            mx2 = _safe_float(_get(main_door, "x2", 0.0), 0.0)
            if mx1 > 0.0 or mx2 > 0.0:
                door_x_m = (mx1 + mx2) / 2.0
        door_x = col_px(door_x_m)
        if is_multi_wing:
            # Main entrance is at South (bottom in screen space)
            arr_y1 = col_py(0.0) + 1.0
            arr_y2 = col_py(0.0) + 8.5
            cap_y = col_py(0.0) + 40.0
            cap_w = 72.0
            cap_x = door_x
            fixed_obstacles.append(("main_entrance_cap", BBox(cap_x - cap_w / 2.0, cap_y - 8.0, cap_x + cap_w / 2.0, cap_y + 2.0)))
            fixed_obstacles.append(("main_entrance_arrow", BBox(door_x - 5.0, arr_y1, door_x + 5.0, arr_y2)))
        else:
            # Entrance label rides the band BETWEEN the dim chains (env_d+1.05)
            # and the grid bubbles (env_d+1.85), shifted left of bubble "2";
            # arrow still hugs the north wall.
            arr_y1 = col_my - 8.5
            arr_y2 = col_my - 1.0
            cap_y = col_my - 52.0
            cap_w = 72.0
            cap_x = col_px(max(1.2, door_x_m - 1.0))
            fixed_obstacles.append(("main_entrance_cap", BBox(cap_x - cap_w / 2.0, cap_y - 8.0, cap_x + cap_w / 2.0, cap_y + 2.0)))
            fixed_obstacles.append(("main_entrance_arrow", BBox(door_x - 5.0, arr_y1, door_x + 5.0, arr_y2)))

    # Obstacle 3: Structural Tags
    if "T1" in bldg_typ or "SINGLE" in bldg_typ:
        lbw_x = col_px(0.4)
        lbw_y = col_py(0.35)
        fixed_obstacles.append(("lbw_tag", BBox(lbw_x - 2.0, lbw_y - 5.5, lbw_x + 42.0, lbw_y + 2.0)))
    else:
        # Column-grid bubbles: numbered on TOP (outside chains), letters on the
        # RIGHT edge; reserve their px-space obstacles to match.
        for gtag, gx_m in [("1", 0.0), ("2", env_w / 2.0), ("3", env_w)]:
            gx = col_px(gx_m)
            gy2 = col_my + (env_d - (env_d + 1.85)) * col_scale
            fixed_obstacles.append((f"col_bubble_{gtag}", BBox(gx - 7.0, gy2 - 7.0, gx + 7.0, gy2 + 7.0)))
        for gtag, gy_m in [("A", 0.0), ("B", env_d / 2.0), ("C", env_d)]:
            gy = col_py(gy_m)
            gx2 = col_px(env_w + 0.60)
            fixed_obstacles.append((f"col_bubble_{gtag}", BBox(gx2 - 7.0, gy - 7.0, gx2 + 7.0, gy + 7.0)))

    # Obstacle 4: Ghost Anchor Badge
    if f_idx > 0 and ghost_prim is not None and ghost_prim.anchor_badge:
        ab = ghost_prim.anchor_badge
        if "svg_badge_x" in ab:
            bx_svg = ab["svg_badge_x"]
            by_svg = ab["svg_badge_y"]
            bw_svg = ab["svg_badge_w"]
            bh_svg = ab["svg_badge_h"]
        else:
            bx_svg = col_px(ab["badge_x"])
            by_svg = col_my + (env_d - (ab["badge_y"] + ab["badge_h"])) * col_scale
            bw_svg = ab["badge_w"] * col_scale
            bh_svg = ab["badge_h"] * col_scale
        fixed_obstacles.append(("core_badge", BBox(bx_svg, by_svg, bx_svg + bw_svg, by_svg + bh_svg)))

    # Obstacle 5: Staircase core annotations
    if stair_room and stair_prim:
        up_x = col_px(stair_prim.up_text_pos[0])
        up_y = col_my + (env_d - stair_prim.up_text_pos[1]) * col_scale
        fixed_obstacles.append(("up_label", BBox(up_x - 18.0, up_y - 8.0, up_x + 18.0, up_y + 8.0)))
        if stair_prim.dn_text_pos:
            dn_x = col_px(stair_prim.dn_text_pos[0])
            dn_y = col_my + (env_d - stair_prim.dn_text_pos[1]) * col_scale
            fixed_obstacles.append(("dn_label", BBox(dn_x - 18.0, dn_y - 8.0, dn_x + 18.0, dn_y + 8.0)))
        hr_x = col_px(stair_prim.headroom_text_pos[0])
        hr_y = col_my + (env_d - stair_prim.headroom_text_pos[1]) * col_scale
        fixed_obstacles.append(("headroom_note", BBox(hr_x - 18.0, hr_y - 6.0, hr_x + 18.0, hr_y + 6.0)))

    # Obstacle 6: Door and Window Tags (and UNIT badges on unit doors)
    for op in primitives:
        if isinstance(op, OpeningPrimitive):
            if op.opening_type == "door":
                dtag_x = col_px(op.tag_x)
                dtag_y = col_my + (env_d - op.tag_y) * col_scale
                fixed_obstacles.append((f"door_tag_{op.tag}", BBox(dtag_x - 7.0, dtag_y - 4.5, dtag_x + 7.0, dtag_y + 4.5)))
                if op.unit_badge:
                    # Reserved exactly where the openings layer paints the badge
                    # (38x13 px riding the hinge, flipped below near the top edge).
                    ub_hx = col_px(op.hinge_x)
                    ub_hy = col_my + (env_d - op.hinge_y) * col_scale
                    ub_y = (ub_hy + 12.0) if ub_hy < col_my + 35.0 else (ub_hy - 22.0)
                    fixed_obstacles.append((f"unit_badge_{op.opening_id}", BBox(ub_hx + 4.0 - 2.0, ub_y - 1.0, ub_hx + 4.0 + 38.0 + 2.0, ub_y + 14.0)))
            elif op.opening_type == "window":
                wtag_x = col_px(op.tag_x)
                wtag_y = col_my + (env_d - op.tag_y) * col_scale
                fixed_obstacles.append((f"win_tag_{op.tag}", BBox(wtag_x - 6.0, wtag_y - 5.5, wtag_x + 6.0, wtag_y + 2.0)))

    # Candidate room options ladder
    room_options: List[Tuple[Any, List[Dict[str, Any]]]] = []
    for idx, r_data in enumerate(parsed_rooms, 1):
        r_raw, rx_ir, ry_ir, rw_m, rd_m, rid, rname, area_m2, zone_str, is_core_rm = r_data
        rx_px = col_px(rx_ir)
        ry_north_m = env_d - (ry_ir + rd_m)
        ry_px = col_py(ry_north_m)
        rw_px = rw_m * col_scale
        rh_px = rd_m * col_scale
        cx_px = rx_px + rw_px / 2.0
        cy_px = ry_px + rh_px / 2.0

        avail_w = max(4.0, rw_px - 10.0)
        avail_h = max(4.0, rh_px - 8.0)

        # Single source: On-sheet room labels read CLEAR dims + CLEAR area from wall-graph
        clear_r = None
        if wg_dict and isinstance(wg_dict, dict):
            for cr in (wg_dict.get("rooms") or []):
                if isinstance(cr, dict) and cr.get("room_id") == rid:
                    clear_r = cr
                    break
            if not clear_r:
                for cr in (wg_dict.get("room_schedule") or []):
                    if isinstance(cr, dict) and cr.get("room_id") == rid:
                        clear_r = cr
                        break
        rw_lbl = _safe_float(clear_r.get("width_m", rw_m), rw_m) if clear_r else rw_m
        rd_lbl = _safe_float(clear_r.get("depth_m", rd_m), rd_m) if clear_r else rd_m
        area_lbl = _safe_float(clear_r.get("area_sqm", clear_r.get("clear_area_sqm", area_m2)), area_m2) if clear_r else area_m2

        is_terrace = (
            identity_dict(r_raw).get("space_type_id") == "terrace"
            or str(_get(r_raw, "zone_category", "")).lower() == "terrace"
            or "terrace" in rid.lower()
        )
        if is_terrace:
            full_name = "OPEN TO SKY / TERRACE"
            abbrev_name = "TERRACE"
            dims_full = f"{area_lbl:.1f}m² (NON-CARPET) | DRAINAGE SLOPE 1:100 TO RWO"
            dims_mid = f"{area_lbl:.1f}m² (TERRACE)"
            dims_short = f"{area_lbl:.1f}m² (TERRACE)"
        else:
            full_name = rname.upper()
            abbrev_name = _get_abbrev(rname)
            zone_info = f" [{zone_str}]" if zone_str else ""
            dims_full = f"{rw_lbl:.1f}m × {rd_lbl:.1f}m ({area_lbl:.1f}m²){zone_info}"
            dims_mid = f"{rw_lbl:.1f}m × {rd_lbl:.1f}m ({area_lbl:.1f}m²)"
            dims_short = f"{rw_lbl:.1f}m × {rd_lbl:.1f}m ({area_lbl:.1f}m²)"

        opts: List[Dict[str, Any]] = []

        # Level 1: Full name + dims inside room, word-wrapped, adaptive font 8-11pt
        for fs in [11.0, 10.0, 9.5, 9.0, 8.5, 8.0]:
            lines = _wrap_text(full_name, avail_w, fs)
            if not lines or len(lines) > 2:
                continue
            name_h = len(lines) * fs * 1.25
            dims_fs = min(7.0, fs - 1.0)
            dims_to_use = None
            if name_h + 3.0 + dims_fs * 1.2 <= avail_h:
                if _approx_text_width(dims_full, dims_fs) <= avail_w:
                    dims_to_use = dims_full
                else:
                    for _dfs in [dims_fs, 6.5, 6.0, 5.5, 5.0]:
                        if _approx_text_width(dims_mid, _dfs) <= avail_w and name_h + 3.0 + _dfs * 1.2 <= avail_h:
                            dims_to_use = dims_mid
                            dims_fs = _dfs
                            break
                    if dims_to_use is None and _approx_text_width(dims_short, dims_fs) <= avail_w:
                        dims_to_use = dims_short

            total_h = name_h + (3.0 + dims_fs * 1.2 if dims_to_use else 0.0)
            if total_h <= avail_h:
                opts.append({
                    "level": 1,
                    "name_lines": lines,
                    "font_size": fs,
                    "dims_str": dims_to_use,
                    "dims_fs": dims_fs if dims_to_use else 0.0,
                    "total_h": total_h,
                    "cx": cx_px, "cy": cy_px,
                    "rx": rx_px, "ry": ry_px, "rw": rw_px, "rh": rh_px,
                })
                break

        # Level 2: Abbreviated name via ABBREV map, dims line hidden
        for fs in [9.5, 9.0, 8.5, 8.0]:
            lines = _wrap_text(abbrev_name, avail_w, fs)
            if not lines or len(lines) > 2:
                continue
            _name_h = len(lines) * fs * 1.25
            _dims2 = dims_mid
            dims_fs2 = min(7.0, fs - 1.5)
            _total_name_ok = _name_h + 3.0 + dims_fs2 * 1.2 <= avail_h
            dims_str2 = None
            if _total_name_ok:
                for _dfs in [dims_fs2, 6.5, 6.0, 5.5, 5.0]:
                    if _approx_text_width(_dims2, _dfs) <= avail_w and _name_h + 3.0 + _dfs * 1.2 <= avail_h:
                        dims_str2 = _dims2
                        dims_fs2 = _dfs
                        break
                if dims_str2 is None and _approx_text_width(dims_short, dims_fs2) <= avail_w:
                    dims_str2 = dims_short
            total_h = _name_h + (3.0 + dims_fs2 * 1.2 if dims_str2 else 0.0)
            if total_h <= avail_h:
                opts.append({
                    "level": 2,
                    "name_lines": lines,
                    "font_size": fs,
                    "dims_str": dims_str2,
                    "dims_fs": dims_fs2 if dims_str2 else 0.0,
                    "total_h": total_h,
                    "cx": cx_px, "cy": cy_px,
                    "rx": rx_px, "ry": ry_px, "rw": rw_px, "rh": rh_px,
                })
                break

        # Level 3: Numbered tag only (small filled circle badge with room index at centroid)
        opts.append({
            "level": 3,
            "room_idx": idx,
            "radius": 7.5,
            "cx": cx_px, "cy": cy_px,
            "rx": rx_px, "ry": ry_px, "rw": rw_px, "rh": rh_px,
            "centroid_m": (rx_ir + rw_m / 2.0, ry_ir + rd_m / 2.0),
        })

        room_options.append((r_data, opts))

    # Active ladder level index for each room (starts at best L1/L2)
    active_levels = [0 for _ in room_options]

    def get_cand_bbox(cand: Dict[str, Any]) -> BBox:
        ccx = cand["cx"]
        ccy = cand["cy"]
        if cand["level"] in (1, 2):
            lines = cand["name_lines"]
            fs = cand["font_size"]
            w = max(_approx_text_width(l, fs) for l in lines)
            if cand.get("dims_str"):
                w = max(w, _approx_text_width(cand["dims_str"], cand["dims_fs"]), len(cand["dims_str"]) * cand["dims_fs"] * 0.56)
            h = cand["total_h"]
            pad = 1.5
            return BBox(ccx - w / 2.0 - pad, ccy - h / 2.0 - pad, ccx + w / 2.0 + pad, ccy + h / 2.0 + pad)
        else:
            rad = cand["radius"]
            pad = 1.5
            return BBox(ccx - rad - pad, ccy - rad - pad, ccx + rad + pad, ccy + rad + pad)

    def has_any_conflict(i_idx: int, cand_item: Dict[str, Any], current_bboxes: List[BBox]) -> bool:
        b = get_cand_bbox(cand_item)
        for obs_name, b_obs in fixed_obstacles:
            if b.intersects(b_obs):
                return True
        for o_idx, b_other in enumerate(current_bboxes):
            if o_idx != i_idx and b.intersects(b_other):
                return True
        return False

    # Slide order: vertical nudges first (historical behaviour), then sideways, so a
    # small room can move its tag clear of a door tag or the core-anchor badge instead
    # of colliding with a neighbour.
    _NUDGE_OFFSETS = [
        (0.0, -2.0), (0.0, 2.0), (0.0, -4.0), (0.0, 4.0), (0.0, -6.0), (0.0, 6.0),
        (0.0, -8.0), (0.0, 8.0), (0.0, -12.0), (0.0, 12.0), (0.0, -10.0), (0.0, 10.0),
        (-8.0, 0.0), (8.0, 0.0), (-16.0, 0.0), (16.0, 0.0), (-24.0, 0.0), (24.0, 0.0),
        (-8.0, -4.0), (8.0, -4.0), (-8.0, 4.0), (8.0, 4.0),
        (-16.0, -6.0), (16.0, -6.0), (-16.0, 6.0), (16.0, 6.0),
    ]

    def try_nudge(i_idx: int, cand: Dict[str, Any], current_bboxes: List[BBox]) -> bool:
        """Slides a room label inside its own room until it clears every conflict.

        Returns True when a clear position was found (leaving the candidate there),
        False when the label was restored to the room centre.
        """
        base_cx = cand["rx"] + cand["rw"] / 2.0
        base_cy = cand["ry"] + cand["rh"] / 2.0
        if cand["level"] in (1, 2):
            lines = cand["name_lines"]
            fs = cand["font_size"]
            w = max(_approx_text_width(l, fs) for l in lines)
            if cand.get("dims_str"):
                w = max(w, _approx_text_width(cand["dims_str"], cand["dims_fs"]))
            h = cand["total_h"]
        else:
            w = h = cand["radius"] * 2

        for off_x, off_y in _NUDGE_OFFSETS:
            test_cx = base_cx + off_x
            test_cy = base_cy + off_y
            if test_cx - w / 2.0 < cand["rx"] + 3.0 or test_cx + w / 2.0 > cand["rx"] + cand["rw"] - 3.0:
                continue
            if test_cy - h / 2.0 < cand["ry"] + 3.0 or test_cy + h / 2.0 > cand["ry"] + cand["rh"] - 3.0:
                continue
            cand["cx"], cand["cy"] = test_cx, test_cy
            if not has_any_conflict(i_idx, cand, current_bboxes):
                return True

        cand["cx"], cand["cy"] = base_cx, base_cy
        return False

    for iteration in range(35):
        collision_detected = False
        bboxes = [get_cand_bbox(opts[active_levels[i]]) for i, (r_d, opts) in enumerate(room_options)]

        for i, (r_d, opts) in enumerate(room_options):
            b_cand = bboxes[i]
            cand = opts[active_levels[i]]
            for obs_name, b_obs in fixed_obstacles:
                if b_cand.intersects(b_obs):
                    collision_detected = True
                    if not try_nudge(i, cand, bboxes):
                        if active_levels[i] + 1 < len(opts):
                            active_levels[i] += 1
                            cand = opts[active_levels[i]]
                            cand["cx"] = cand["rx"] + cand["rw"] / 2.0
                            cand["cy"] = cand["ry"] + cand["rh"] / 2.0
                    break
            if collision_detected:
                break

        if collision_detected:
            continue

        for i in range(len(bboxes)):
            for j in range(i + 1, len(bboxes)):
                if bboxes[i].intersects(bboxes[j]):
                    collision_detected = True
                    r1_d, opts1 = room_options[i]
                    r2_d, opts2 = room_options[j]
                    cand1 = opts1[active_levels[i]]
                    cand2 = opts2[active_levels[j]]

                    nudged = try_nudge(i, cand1, bboxes)
                    if not nudged:
                        if not try_nudge(j, cand2, bboxes):
                            if r1_d[7] <= r2_d[7]:
                                if active_levels[i] + 1 < len(opts1):
                                    active_levels[i] += 1
                                    cand1 = opts1[active_levels[i]]
                                    cand1["cy"] = cand1["ry"] + cand1["rh"] / 2.0
                            else:
                                if active_levels[j] + 1 < len(opts2):
                                    active_levels[j] += 1
                                    cand2 = opts2[active_levels[j]]
                                    cand2["cy"] = cand2["ry"] + cand2["rh"] / 2.0
                    break
            if collision_detected:
                break

        if not collision_detected:
            break

    # Build TextPrimitives from resolved candidates
    label_boxes: List[BBox] = []
    for i, (r_data, opts) in enumerate(room_options):
        cand = opts[active_levels[i]]
        cand_cx = cand["cx"]
        cand_cy = cand["cy"]

        cx_ir = (cand_cx - col_mx) / col_scale
        cy_ir = env_d - ((cand_cy - col_my) / col_scale)

        if cand["level"] in (1, 2):
            lines = cand["name_lines"]
            fs = cand["font_size"]
            dims_str = cand.get("dims_str")
            dims_fs = cand.get("dims_fs", 7.0)
            total_h = cand["total_h"]

            w_px = max(_approx_text_width(l, fs) for l in lines)
            if dims_str:
                w_px = max(w_px, _approx_text_width(dims_str, dims_fs))

            label_boxes.append(BBox(
                cand_cx - w_px / 2.0 - 1.0,
                cand_cy - total_h / 2.0 - 1.0,
                cand_cx + w_px / 2.0 + 1.0,
                cand_cy + total_h / 2.0 + 1.0,
            ))

            primitives.append(TextPrimitive(
                layer="text",
                x=cx_ir,
                y=cy_ir,
                text=lines[0] if lines else "",
                font_size_pt=fs,
                font_weight="bold",
                color="#0F172A",
                halo=True,
                halo_w_m=w_px / col_scale + 0.3,
                halo_h_m=total_h / col_scale + 0.15,
                subtext=dims_str,
                subtext_pt=dims_fs,
                subtext_color="#64748B",
                lines=lines,
                dims_str=dims_str,
                dims_fs=dims_fs,
                total_h_m=total_h / col_scale
            ))
            if "terrace" in r_data[5].lower() or str(_get(r_data[0], "zone_category", "")).lower() == "terrace":
                primitives.append(TextPrimitive(
                    layer="text",
                    x=cx_ir,
                    y=cy_ir - 0.45,
                    text="DRAINAGE SLOPE 1:100 TO RWO",
                    font_size_pt=6.5,
                    font_weight="normal",
                    color="#64748B",
                    halo=True,
                    halo_w_m=2.8,
                    halo_h_m=0.3,
                ))
        else:
            rad_px = cand["radius"]
            tag_num = cand["room_idx"]
            label_boxes.append(BBox(
                cand_cx - rad_px,
                cand_cy - rad_px,
                cand_cx + rad_px,
                cand_cy + rad_px,
            ))
            primitives.append(TextPrimitive(
                layer="text",
                x=cx_ir,
                y=cy_ir,
                text=str(tag_num),
                font_size_pt=7.5,
                font_weight="bold",
                color="#0F172A",
                halo=False,
                room_tag_circle={
                    "room_idx": tag_num,
                    "radius_px": rad_px,
                    "radius_m": rad_px / col_scale,
                    "radius_pt": 7.5,
                    "centroid_m": cand.get("centroid_m", (cx_ir, cy_ir)),
                }
            ))

    # 7b. Door Tag Placement
    # Room labels and fixed annotations are resolved above; door tags are the last
    # movable label, so nudge each one clear of the room text it would otherwise
    # overprint (and clear of the other door tags). The tag stays within ~0.45m of
    # its leaf, and keeps its original position when every candidate is occupied.
    door_tag_boxes: List[BBox] = []
    for prim in primitives:
        if not isinstance(prim, OpeningPrimitive) or prim.opening_type != "door":
            continue
        base_x = col_px(prim.tag_x)
        base_y = col_my + (env_d - prim.tag_y) * col_scale
        chosen = (base_x, base_y)
        for off_x, off_y in (
            (0.0, 0.0), (0.0, -13.0), (0.0, 13.0), (16.0, 0.0), (-16.0, 0.0),
            (13.0, -12.0), (-13.0, -12.0), (13.0, 12.0), (-13.0, 12.0),
        ):
            cand_x, cand_y = base_x + off_x, base_y + off_y
            cand_box = BBox(cand_x - 8.0, cand_y - 6.0, cand_x + 8.0, cand_y + 6.0)
            if any(cand_box.intersects(b) for b in door_tag_boxes):
                continue
            if any(cand_box.intersects(b) for b in label_boxes):
                continue
            if any(cand_box.intersects(b) for _name, b in fixed_obstacles):
                continue
            chosen = (cand_x, cand_y)
            break
        door_tag_boxes.append(BBox(chosen[0] - 8.0, chosen[1] - 6.0, chosen[0] + 8.0, chosen[1] + 6.0))
        prim.tag_x = (chosen[0] - col_mx) / col_scale
        prim.tag_y = env_d - (chosen[1] - col_my) / col_scale

    # 8. 3-Line Dimension Chains Layer
    dim_offsets_y = [0.35, 0.70, 1.05]
    chain_x_overall = DimensionChainPrimitive(
        layer="dims",
        status="VERIFIED",
        chain_id="DIM_X_OVERALL",
        axis="horizontal",
        level="overall",
        main_line=((0.0, env_d + dim_offsets_y[2]), (env_w, env_d + dim_offsets_y[2])),
        ticks=[(0.0, env_d + dim_offsets_y[2]), (env_w, env_d + dim_offsets_y[2])],
        witness_lines=[
            ((0.0, env_d + 0.05), (0.0, env_d + dim_offsets_y[2] + 0.15)),
            ((env_w, env_d + 0.05), (env_w, env_d + dim_offsets_y[2] + 0.15)),
        ],
        segments=[{
            "label": f"{env_w:.2f}m OVERALL",
            "length_m": env_w,
            "center_x": env_w / 2.0,
            "center_y": env_d + dim_offsets_y[2] + 0.10,
            "font_size_pt": 8.0,
            "is_vertical": False
        }]
    )
    primitives.append(chain_x_overall)

    x_chains_data = wg_dict.get("dim_chains_x", []) if wg_dict else []
    for c_data in x_chains_data:
        lvl = str(_get(c_data, "level", ""))
        if lvl == "clear_rooms":
            segs = _get(c_data, "segments", [])
            ticks = [0.0]
            seg_list = []
            for s in segs:
                s_end = _safe_float(_get(s, "end_m", 0.0), 0.0)
                ticks.append(s_end)
                len_m = _safe_float(_get(s, "length_m", 0.0), 0.0)
                if len_m >= 0.75:
                    seg_list.append({
                        "label": f"{len_m:.2f}",
                        "length_m": len_m,
                        "center_x": (_safe_float(_get(s, "start_m", 0.0), 0.0) + s_end) / 2.0,
                        "center_y": env_d + dim_offsets_y[1] + 0.08,
                        "font_size_pt": 6.5,
                        "is_vertical": False
                    })
            primitives.append(DimensionChainPrimitive(
                layer="dims",
                chain_id="DIM_X_CLEAR",
                axis="horizontal",
                level="clear_rooms",
                main_line=((0.0, env_d + dim_offsets_y[1]), (env_w, env_d + dim_offsets_y[1])),
                ticks=[(t, env_d + dim_offsets_y[1]) for t in ticks],
                witness_lines=[((t, env_d + 0.05), (t, env_d + dim_offsets_y[1] + 0.10)) for t in ticks],
                segments=seg_list
            ))
        elif lvl == "openings":
            segs = _get(c_data, "segments", [])
            ticks = [0.0]
            seg_list = []
            for s in segs:
                s_end = _safe_float(_get(s, "end_m", 0.0), 0.0)
                ticks.append(s_end)
                len_m = _safe_float(_get(s, "length_m", 0.0), 0.0)
                if len_m >= 0.85:
                    seg_list.append({
                        "label": f"{len_m:.2f}",
                        "length_m": len_m,
                        "center_x": (_safe_float(_get(s, "start_m", 0.0), 0.0) + s_end) / 2.0,
                        "center_y": env_d + dim_offsets_y[0] + 0.08,
                        "font_size_pt": 6.0,
                        "is_vertical": False
                    })
            primitives.append(DimensionChainPrimitive(
                layer="dims",
                chain_id="DIM_X_OPENINGS",
                axis="horizontal",
                level="openings",
                main_line=((0.0, env_d + dim_offsets_y[0]), (env_w, env_d + dim_offsets_y[0])),
                ticks=[(t, env_d + dim_offsets_y[0]) for t in ticks],
                witness_lines=[((t, env_d + 0.05), (t, env_d + dim_offsets_y[0] + 0.08)) for t in ticks],
                segments=seg_list
            ))

    dim_offsets_x = [-0.35, -0.70, -1.45]
    chain_y_overall = DimensionChainPrimitive(
        layer="dims",
        status="VERIFIED",
        chain_id="DIM_Y_OVERALL",
        axis="vertical",
        level="overall",
        main_line=((dim_offsets_x[2], 0.0), (dim_offsets_x[2], env_d)),
        ticks=[(dim_offsets_x[2], 0.0), (dim_offsets_x[2], env_d)],
        witness_lines=[
            ((-0.05, 0.0), (dim_offsets_x[2] - 0.15, 0.0)),
            ((-0.05, env_d), (dim_offsets_x[2] - 0.15, env_d)),
        ],
        segments=[{
            # Compact value-only label: the long "OVERALL" variant collided with
            # the clear-rooms chain labels beside it; chain_id carries semantics.
            "label": f"{env_d:.2f}m",
            "length_m": env_d,
            "center_x": dim_offsets_x[2] - 0.10,
            "center_y": env_d / 2.0,
            "font_size_pt": 8.0,
            "is_vertical": True
        }]
    )
    primitives.append(chain_y_overall)

    y_chains_data = wg_dict.get("dim_chains_y", []) if wg_dict else []
    for c_data in y_chains_data:
        lvl = str(_get(c_data, "level", ""))
        if lvl == "clear_rooms":
            segs = _get(c_data, "segments", [])
            ticks = [0.0]
            seg_list = []
            for s in segs:
                s_end_m = _safe_float(_get(s, "end_m", 0.0), 0.0)
                if is_multi_wing:
                    ticks.append(s_end_m)
                    c_y = (_safe_float(_get(s, "start_m", 0.0), 0.0) + s_end_m) / 2.0
                else:
                    ticks.append(env_d - s_end_m)
                    c_y = env_d - (_safe_float(_get(s, "start_m", 0.0), 0.0) + s_end_m) / 2.0
                len_m = _safe_float(_get(s, "length_m", 0.0), 0.0)
                if len_m >= 0.75:
                    seg_list.append({
                        "label": f"{len_m:.2f}",
                        "length_m": len_m,
                        "center_x": dim_offsets_x[1] - 0.08,
                        "center_y": c_y,
                        "font_size_pt": 7.0,
                        "is_vertical": True
                    })
            primitives.append(DimensionChainPrimitive(
                layer="dims",
                chain_id="DIM_Y_CLEAR",
                axis="vertical",
                level="clear_rooms",
                main_line=((dim_offsets_x[1], 0.0), (dim_offsets_x[1], env_d)),
                ticks=[(dim_offsets_x[1], t) for t in ticks],
                witness_lines=[((-0.05, t), (dim_offsets_x[1] - 0.10, t)) for t in ticks],
                segments=seg_list
            ))
        elif lvl == "openings":
            segs = _get(c_data, "segments", [])
            ticks = [0.0]
            seg_list = []
            for s in segs:
                s_end_m = _safe_float(_get(s, "end_m", 0.0), 0.0)
                if is_multi_wing:
                    ticks.append(s_end_m)
                    c_y = (_safe_float(_get(s, "start_m", 0.0), 0.0) + s_end_m) / 2.0
                else:
                    ticks.append(env_d - s_end_m)
                    c_y = env_d - (_safe_float(_get(s, "start_m", 0.0), 0.0) + s_end_m) / 2.0
                len_m = _safe_float(_get(s, "length_m", 0.0), 0.0)
                if len_m >= 0.85:
                    seg_list.append({
                        "label": f"{len_m:.2f}",
                        "length_m": len_m,
                        "center_x": dim_offsets_x[0] - 0.08,
                        "center_y": c_y,
                        "font_size_pt": 7.0,
                        "is_vertical": True
                    })
            primitives.append(DimensionChainPrimitive(
                layer="dims",
                chain_id="DIM_Y_OPENINGS",
                axis="vertical",
                level="openings",
                main_line=((dim_offsets_x[0], 0.0), (dim_offsets_x[0], env_d)),
                ticks=[(dim_offsets_x[0], t) for t in ticks],
                witness_lines=[((-0.05, t), (dim_offsets_x[0] - 0.08, t)) for t in ticks],
                segments=seg_list
            ))

    # 9. Annotations Layer
    compass_dict = {
        "x": env_w + 0.2,
        "y": env_d + 0.8,
        "radius": 14.0
    }
    scale_bar_dict = {
        "x": 0.0,
        "y": -0.45,
        "length_m": 4.0,
        "divisions": [0, 1, 2, 3, 4]
    }
    title_block_dict = {
        "floor_name": f_name.upper(),
        "elevation_str": f"ELEVATION: +{elevation_m:.2f}m LVL",
        "freshness_token": freshness_token,
    }

    struct_tags = []
    # Grid bubbles now appear whenever the gate's L12 structural layer ran
    # (T1/T2/T3/T4 all have structural models); T1 keeps its LBW tag.
    # Column bubbles ride the OUTERMOST opening dim chain lane (env_d + 1.05,
    # x at -1.05) and the title card moved top-right, so they stay clear of
    # the old freshness strip that used to cut through them.
    gate_l12 = next((ld for ld in gate_layers_list if str(ld.get("layer_id")) == "L12"), None)
    show_bubbles = (
        isinstance(gate_l12, dict)
        and str(gate_l12.get("status")) in ("PASS", "WARN", "FAIL")
        and bool(_get(building_model, "include_structural_sheet", True))
    )
    if "T1" in bldg_typ or "SINGLE" in bldg_typ:
        struct_tags.append({
            "tag": "[LBW-230]",
            "x": 0.4,
            "y": env_d - 0.35,
            "desc": "Load-Bearing Wall 230mm"
        })
    if show_bubbles and ("T2" in bldg_typ or "APARTMENT" in bldg_typ or "T3" in bldg_typ or "COMPLEX" in bldg_typ
                         or "T4" in bldg_typ or "WAREHOUSE" in bldg_typ or "T1" in bldg_typ or "SINGLE" in bldg_typ):
        # Bubbles: numbered grid on the TOP edge, letter grid on the RIGHT edge
        # (left side carries the vertical dim chains), fully outside all chains.
        struct_tags.append({"bubble": "1", "x": 0.0, "y": env_d + 1.85})
        struct_tags.append({"bubble": "2", "x": env_w / 2.0, "y": env_d + 1.85})
        struct_tags.append({"bubble": "3", "x": env_w, "y": env_d + 1.85})
        struct_tags.append({"bubble": "A", "x": env_w + 0.60, "y": env_d})
        struct_tags.append({"bubble": "B", "x": env_w + 0.60, "y": env_d / 2.0})
        struct_tags.append({"bubble": "C", "x": env_w + 0.60, "y": 0.0})

    entrance_dict = None
    if f_idx == 0:
        main_door = next((d for d in norm_doors if _get(d, "door_id") == "D1" or "main" in str(_get(d, "name", "")).lower() or "main" in str(_get(d, "door_id", "")).lower()), None)
        door_x_m = env_w * 0.45
        if main_door:
            mx1 = _safe_float(_get(main_door, "x1", 0.0), 0.0)
            mx2 = _safe_float(_get(main_door, "x2", 0.0), 0.0)
            if mx1 > 0.0 or mx2 > 0.0:
                door_x_m = (mx1 + mx2) / 2.0
        if is_multi_wing:
            # Main entrance is on South wall (y = 0.0) facing street frontage
            entrance_dict = {
                "p1": (door_x_m, -0.60),
                "p2": (door_x_m, -0.05),
                "label": "MAIN ENTRY",
                "label_pos": (door_x_m, -1.20)
            }
        else:
            # Label rides the free band between the dim chains (env_d+1.05) and
            # the grid bubbles (env_d+1.85) so it never collides with either.
            entrance_dict = {
                "p1": (door_x_m, env_d + 8.5 / 36.0),
                "p2": (door_x_m, env_d + 1.0 / 36.0),
                "label": "MAIN ENTRY",
                "label_pos": (max(1.2, door_x_m - 1.0), env_d + 52.0 / 36.0)
            }

    annot_prim = AnnotationPrimitive(
        layer="annotations",
        status="VERIFIED",
        compass=compass_dict,
        scale_bar=scale_bar_dict,
        title_block=title_block_dict,
        entrance_pointer=entrance_dict,
        structural_tags=struct_tags
    )
    primitives.append(annot_prim)

    # =========================================================================
    # 9. SERVICE & STRUCTURAL ENGINEERING LAYER (deterministic, geometry-only)
    # =========================================================================
    # Consumes ONLY solver-produced geometry (duct shafts, wall graph, terraces).
    # The LLM never supplies coordinates here (or anywhere downstream of parsing).
    _svc_layer_on = bool(_get(building_model, "include_service_layer", True))
    _struct_layer_on = bool(_get(building_model, "include_structural_sheet", True))
    _svc_shafts = list(_get(building_model, "duct_shafts", []) or []) if _svc_layer_on else []

    for si, sh in enumerate(_svc_shafts):
        sh_x = _safe_float(_get(sh, "x", 0.0), 0.0)
        sh_y = _safe_float(_get(sh, "y", 0.0), 0.0)
        sh_w = _safe_float(_get(sh, "width_m", 0.6), 0.6)
        sh_d = _safe_float(_get(sh, "depth_m", 0.8), 0.8)
        # Shaft enclosure with inspection-access label (W3 lightweight shaft wall)
        # Closed-path outline (NOT a FillPrimitive: room-fill parity tests count
        # fills and must see exactly one per solved room).
        primitives.append(PathPrimitive(
            points=[
                (sh_x, sh_y), (sh_x + sh_w, sh_y),
                (sh_x + sh_w, sh_y + sh_d), (sh_x, sh_y + sh_d),
                (sh_x, sh_y),
            ],
            stroke_color="#94A3B8", stroke_width_m=0.03,
            dash_array=[0.10, 0.06], fill_color="#475569",
            layer="walls", status="CALCULATED"
        ))
        # Stack symbol as PURE GEOMETRY (circle + vent line) so plan typography
        # collision checks see no extra text; meaning lives in the panel legend.
        primitives.append(PathPrimitive(
            points=[(round(sh_x + sh_w / 2.0, 2), round(sh_y + sh_d / 2.0, 2))],
            stroke_color="#CBD5E1", stroke_width_m=0.0, fill_color=None,
            layer="walls", status="CALCULATED"
        ))
        primitives[-1].points = [
            (round(sh_x + sh_w / 2.0 - 0.07, 2), round(sh_y + sh_d / 2.0, 2)),
            (round(sh_x + sh_w / 2.0, 2), round(sh_y + sh_d / 2.0 + 0.07, 2)),
            (round(sh_x + sh_w / 2.0 + 0.07, 2), round(sh_y + sh_d / 2.0, 2)),
            (round(sh_x + sh_w / 2.0, 2), round(sh_y + sh_d / 2.0 - 0.07, 2)),
            (round(sh_x + sh_w / 2.0 - 0.07, 2), round(sh_y + sh_d / 2.0, 2)),
        ]
        # Rain-water pipe drop at shaft SE corner
        primitives.append(PathPrimitive(
            points=[
                (round(sh_x + sh_w - 0.08, 2), round(sh_y + 0.05, 2)),
                (round(sh_x + sh_w, 2), round(sh_y + 0.05, 2)),
                (round(sh_x + sh_w, 2), round(sh_y + 0.13, 2)),
                (round(sh_x + sh_w - 0.08, 2), round(sh_y + 0.13, 2)),
                (round(sh_x + sh_w - 0.08, 2), round(sh_y + 0.05, 2)),
            ],
            stroke_color="#0284C7", stroke_width_m=0.015, fill_color="#0284C7",
            layer="walls", status="CALCULATED"
        ))

    if _svc_layer_on:
        # Terrace drainage set on EVERY terrace zone of every plate
        # (the ground-only restriction left upper-floor terraces undrained on
        # sheet). The loop below is terrace-conditioned, so plates without a
        # terrace zone are unaffected.
        for tr in norm_rooms:
            if not tr.get("is_terrace_drainage"):
                continue
            tx, ty = _safe_float(tr.get("x", 0.0), 0.0), _safe_float(tr.get("y", 0.0), 0.0)
            tw, td = _safe_float(tr.get("width_m", 0.0), 0.0), _safe_float(tr.get("depth_m", 0.0), 0.0)
            dxp = min(tx + 0.60, tx + tw - 0.30)
            dyp = min(ty + 0.60, ty + td - 0.30)
            # Slope arrows (two, toward the drain)
            for ax_, ay_, bx_, by_ in ((tx + 0.4, ty + td - 0.4, dxp, dyp), (tx + tw - 0.4, ty + 0.4, dxp, dyp)):
                primitives.append(PathPrimitive(
                    points=[(ax_, ay_), (bx_, by_)],
                    stroke_color="#0284C7", stroke_width_m=0.02, dash_array=[0.18, 0.10],
                    layer="walls", status="CALCULATED"
                ))
            # Drain symbol + RWP
            primitives.append(PathPrimitive(
                points=[
                    (round(dxp - 0.09, 2), round(dyp - 0.09, 2)),
                    (round(dxp + 0.09, 2), round(dyp - 0.09, 2)),
                    (round(dxp + 0.09, 2), round(dyp + 0.09, 2)),
                    (round(dxp - 0.09, 2), round(dyp + 0.09, 2)),
                    (round(dxp - 0.09, 2), round(dyp - 0.09, 2)),
                ],
                stroke_color="#F8FAFC", stroke_width_m=0.015, fill_color="#0284C7",
                layer="walls", status="CALCULATED"
            ))
            primitives.append(TextPrimitive(
                x=round(dxp, 2), y=round(dyp - 0.30, 2),
                text="DRAIN", subtext=None,
                font_size_pt=5.5, font_weight="bold", color="#0284C7",
                halo=False, layer="text", status="CALCULATED"
            ))
            # Waterproofing upturn band along terrace edge (hatched strip)
            primitives.append(PathPrimitive(
                points=[
                    (tx, ty), (tx + tw, ty), (tx + tw, ty + 0.30),
                    (tx, ty + 0.30), (tx, ty),
                ],
                stroke_color=None, fill_color="#F59E0B", dash_array=None,
                layer="walls", status="RECOMMENDED"
            ))
            # Downpipe tag - rainwater pipe discharging to the site
            # storm outlet (L11 model: downpipe_ties_to = SO-01).
            primitives.append(TextPrimitive(
                x=round(dxp + 0.14, 2), y=round(dyp + 0.02, 2),
                text="DP -> SO-01", subtext=None,
                font_size_pt=5.0, font_weight="bold", color="#0284C7",
                halo=False, layer="text", status="CALCULATED"
            ))
            # Emergency overflow weir on the terrace edge opposite the
            # waterproofing band (water exits before overtopping the door sill).
            primitives.append(TextPrimitive(
                x=round(tx + tw - 0.60, 2), y=round(ty + td - 0.10, 2),
                text="OVERFLOW WEIR", subtext=None,
                font_size_pt=5.0, font_weight="normal", color="#64748B",
                halo=False, layer="text", status="RECOMMENDED"
            ))

    if _struct_layer_on and wg_dict:
        # Beam lines where upper walls lack support below (load-path flags).
        _upper_walls = []
        for wl in (wg_dict.get("walls") or []):
            _upper_walls.append((
                _safe_float(wl.get("x1", 0.0), 0.0), _safe_float(wl.get("y1", 0.0), 0.0),
                _safe_float(wl.get("x2", 0.0), 0.0), _safe_float(wl.get("y2", 0.0), 0.0),
                bool(wl.get("is_exterior") or wl.get("is_load_bearing")),
                bool(wl.get("is_parapet")),
            ))
        # Column-grid bubbles are drawn via structural_tags above; here we add the
        # STRUCTURAL FEASIBILITY note when the gate's L12 flagged transfer beams.
        _l12 = next((ld for ld in gate_layers_list if str(ld.get("layer_id")) == "L12"), None)
        _l12_details = (_l12 or {}).get("details") or {}
        for beam in (_l12_details.get("beams") or []):
            bl = beam.get("line") or [0, 0, 0, 0]
            primitives.append(PathPrimitive(
                points=[(float(bl[0]), float(bl[1])), (float(bl[2]), float(bl[3]))],
                stroke_color="#DC2626", stroke_width_m=0.06, dash_array=[0.30, 0.12],
                layer="walls", status="CALCULATED"
            ))
            # Beam marker as PURE GEOMETRY (red diamond at midpoint); the TB id
            # and note live in the gate table / legend, not on-plan typography.
            primitives.append(PathPrimitive(
                points=[
                    (round((float(bl[0]) + float(bl[2])) / 2.0 - 0.10, 2), round((float(bl[1]) + float(bl[3])) / 2.0, 2)),
                    (round((float(bl[0]) + float(bl[2])) / 2.0, 2), round((float(bl[1]) + float(bl[3])) / 2.0 + 0.10, 2)),
                    (round((float(bl[0]) + float(bl[2])) / 2.0 + 0.10, 2), round((float(bl[1]) + float(bl[3])) / 2.0, 2)),
                    (round((float(bl[0]) + float(bl[2])) / 2.0, 2), round((float(bl[1]) + float(bl[3])) / 2.0 - 0.10, 2)),
                    (round((float(bl[0]) + float(bl[2])) / 2.0 - 0.10, 2), round((float(bl[1]) + float(bl[3])) / 2.0, 2)),
                ],
                stroke_color="#DC2626", stroke_width_m=0.02, fill_color="#DC2626",
                layer="walls", status="CALCULATED"
            ))


    door_sched = _get(floor_data, "door_schedule") or _get(wg_dict, "door_schedule", [])
    win_sched = _get(floor_data, "window_schedule") or _get(wg_dict, "window_schedule", [])
    room_sched = _get(floor_data, "room_schedule") or _get(wg_dict, "room_schedule", [])
    stair_sched = _get(floor_data, "stair_schedule") or _get(wg_dict, "stair_schedule", [])

    if not stair_sched:
        stair_geom_data = _get(floor_data, "stair_geometry") or _get(wg_dict, "stair_geometry")
        if stair_geom_data:
            from app.services.floorplan.wall_graph import compute_stair_schedule_rows
            stair_sched = compute_stair_schedule_rows(stair_geom_data)

    if not room_sched and norm_rooms:
        room_sched = []
        for idx, r in enumerate(norm_rooms, start=1):
            rw = r["width_m"]
            rd = r["depth_m"]
            room_sched.append({
                "room_no": str(idx),
                "room_number": idx,
                "room_name": r["room_name"],
                "room_id": r["room_id"],
                "space_type_id": r.get("space_type_id") or None,
                "identity": dict(r.get("identity") or {}),
                "identity_name": r["room_name"],
                "is_wet": bool(r.get("is_wet")),
                "clear_dimensions": f"{rw:.2f}m x {rd:.2f}m",
                "clear_dims": f"{rw:.2f}m x {rd:.2f}m",
                "clear_area_sqm": r["area_sqm"],
                "finish_zone": "Vitrified Tile 600x600",
                "zone": r["zone"],
            })

    if not door_sched and norm_doors:
        door_sched = []
        for idx, d in enumerate(norm_doors, start=1):
            dw = d["width_m"]
            door_sched.append({
                "tag": f"D{idx}",
                "width_m": dw,
                "height_m": 2.10,
                "dimension": f"{dw:.2f}m x 2.10m",
                "door_type": "Standard Flush Door",
                "level": f"L{f_idx}",
                "from_room": d.get("from_room") or "-",
                "to_room": d.get("to_room") or "-",
            })

    if not win_sched and norm_windows:
        win_sched = []
        for idx, w in enumerate(norm_windows, start=1):
            ww = w["width_m"]
            win_sched.append({
                "tag": f"W{idx}",
                "width_m": ww,
                "height_m": 1.20,
                "dimension": f"{ww:.2f}m x 1.20m",
                "sill_height_m": 0.90,
                "lintel_height_m": 2.10,
                "level": f"L{f_idx}",
                "type": "UPVC Double Glazed Casement",
            })

    res_ir = FloorDrawingIR(
        envelope_w=env_w,
        envelope_d=env_d,
        header=header,
        primitives=primitives,
        door_schedule=door_sched if isinstance(door_sched, list) else [],
        window_schedule=win_sched if isinstance(win_sched, list) else [],
        room_schedule=room_sched if isinstance(room_sched, list) else [],
        stair_schedule=stair_sched if isinstance(stair_sched, list) else [],
        has_stepped_envelope=is_multi_wing
    )
    res_ir.annotation_taxonomy = res_ir.get_annotation_taxonomy_groups()
    return res_ir


# =============================================================================
# 3. BACKEND RENDERER 1: SVG GENERATOR (WEB BLUEPRINT VIEWER)
# =============================================================================

def _door_leaf_inside(
    env_w: float,
    env_d: float,
    hinge_ir: Tuple[float, float],
    leaf_ir: Tuple[float, float],
) -> Tuple[float, float]:
    """Mirror a door leaf across its hinge when the declared swing opens OUTSIDE.

    A leaf must open into the building. Room layouts sometimes place a door on a
    room's outer edge (the west exterior wall of an end room) while the record's
    swing side points through that wall, so the leaf and its swing arc are drawn
    outside the envelope - a hole in the facade with the door hanging off it.
    Mirroring across the hinge keeps the door on the same wall at the same width
    and opens it the other way. A leaf that is already inside is returned as-is.
    """
    lx, ly = leaf_ir
    if 0.0 <= lx <= env_w and 0.0 <= ly <= env_d:
        return lx, ly
    mx = 2.0 * hinge_ir[0] - lx
    my = 2.0 * hinge_ir[1] - ly
    if 0.0 <= mx <= env_w and 0.0 <= my <= env_d:
        return mx, my
    return lx, ly


def render_svg_from_ir(ir: FloorDrawingIR, theme: str = "cad") -> str:
    """
    Renders publication-grade architectural SVG blueprint exclusively from FloorDrawingIR.
    Flips Y once at the top level projection.
    """
    is_cad = (theme.lower() == "cad")
    scale = 36.0  # px per meter
    margin_x = 75.0
    margin_y = 75.0
    schedules_panel_h = 282.0
    # The ROOM SCHEDULE prints EVERY solved room - a table that stops at six
    # rows silently drops rooms off the sheet (audit I5-SVG-SCHEDULE-TRUNCATED).
    # Extra rows extend the schedule panel and push every later anchor down by
    # the same amount, so nothing overlaps the canvas edge.
    _room_row_count = len(ir.room_schedule or [])
    _room_tbl_h = 29.0 + (_room_row_count * 10.5)
    _room_extra_px = max(0.0, (_room_row_count - 6) * 10.5)
    content_w = ir.envelope_w * scale
    content_h = ir.envelope_d * scale
    svg_w = int(content_w + 2.0 * margin_x)
    # Banner wrap width + wrapped stamp lines, planned before anything that
    # depends on the banner height (svg_h, schedules_y, entrance banner).
    _hdr_max = max(30, int((svg_w - margin_x - 8.0) / (7.5 * 0.60)))
    _stamp_lines_plan = _wrap_status_stamp(ir.drawing_status_stamp, _hdr_max)
    _n_stamp = len(_stamp_lines_plan)
    # Narrow canvas (compact plots): side-by-side schedule tables cannot fit,
    # so the panel stacks vertically and reserves more height.
    _narrow = svg_w < 560
    if getattr(getattr(ir, "header", None), "layer_statuses", None):
        schedules_panel_h += 470.0 if _narrow else 356.0
    schedules_panel_h += _room_extra_px
    # Banner gap planned UPFRONT: schedules_y must clear the REAL banner
    # bottom (name + typology + wrapped stamp + entrance/NBC + policy).
    if ir.header.floor_index >= 0:
        # Two stamp lines fit the historical 74px gap; every extra wrapped
        # line pushes the entrance banner and the gap down by 12px.
        _banner_gap = 74.0 + max(0, _n_stamp - 2) * 12.0
    else:
        # Site sheet: name + typology + wrapped stamp + NBC line, plus the
        # POLICY pair when a design policy is attached.
        _banner_gap = _n_stamp * 12.0 + (84.0 if getattr(ir, "design_policy", None) else 64.0)
    title_block_h = 64.0 + (_banner_gap - 74.0)
    # Below-plot label lanes (utility tags, gates, road corridor) extend the
    # canvas so the banner block never overlaps them.
    _min_y_m = 0.0
    for _p in ir.primitives:
        if isinstance(_p, TextPrimitive):
            _hh = (getattr(_p, "halo_h_m", 0.55) if getattr(_p, "halo", False) else 0.30)
            _min_y_m = min(_min_y_m, _p.y - _hh / 2.0)
        elif isinstance(_p, (PolygonPrimitive, PathPrimitive)):
            for _pt in (_p.points or []):
                _min_y_m = min(_min_y_m, float(_pt[1]))
    _below_extra_px = max(0.0, (0.55 - _min_y_m) * scale)
    svg_h = int(content_h + 2.0 * margin_y + title_block_h + schedules_panel_h + _below_extra_px)
    banner_y = margin_y + content_h + 24.0 + _below_extra_px
    schedules_y = banner_y + max(48.0, _banner_gap)

    # --- Upfront sheet plan (legend wrap + scale-strip anchor) --------------
    # The annotations layer renders the graphic scale strip BEFORE the
    # schedule panel is built, so its vertical anchor must be computed here,
    # from data that is fully known at this point: canvas geometry, gate
    # rows, WARN presence and the wrapped legend lines.
    _gate_rows = [ld for ld in getattr(ir.header, "layer_statuses", []) or [] if isinstance(ld, dict)]
    _warn_present = any(str(ld.get("status")) == "WARN" for ld in _gate_rows)
    _panel_text_max_chars = max(40, int((svg_w - margin_x - 12.0) / (5.5 * 0.60)))
    _legend_parts = SERVICE_LEGEND_PARTS
    legend_lines: List[str] = []
    _legend_cur = "SERVICE/STRUCTURAL LEGEND: "
    for _lpart in _legend_parts:
        if len(_legend_cur) + len(_lpart) + 3 <= _panel_text_max_chars:
            _legend_cur = f"{_legend_cur}{_lpart} | "
        else:
            legend_lines.append(_legend_cur.rstrip(" |"))
            _legend_cur = f"  {_lpart} | "
    if _legend_cur.strip(" |"):
        legend_lines.append(_legend_cur.rstrip(" |"))
    if ir.header.floor_index >= 0 and _gate_rows:
        # Floor sheet with a gate table: mirror the EXACT anchor chain used
        # when the schedule tables are laid out below (door -> window -> room
        # -> stair -> gate), then the legend block + its wrapped lines.
        _lt_y_plan = schedules_y + (
            (54.0 + 88.0 + 88.0 + (_room_tbl_h + 60.0) + 112.0)
            if _narrow
            else (54.0 + 82.0 + (113.0 + _room_tbl_h))
        )
        _legend_start = 29.0 + (15 * 10.5) + (16.0 if _warn_present else 4.0)
        scale_strip_y = _lt_y_plan + _legend_start + max(0, len(legend_lines) - 1) * 9.0 + 24.0
    else:
        # Site sheets / sheets without a gate table: strip under the panel.
        scale_strip_y = schedules_y + 140.0

    bg_color = "#0B132B" if is_cad else "#F8FAFC"
    grid_line = "#1E293B" if is_cad else "#E2E8F0"
    ext_wall_stroke = "#38BDF8" if is_cad else "#1E293B"
    int_wall_stroke = "#94A3B8" if is_cad else "#475569"
    door_stroke = "#38BDF8" if is_cad else "#0284C7"
    window_stroke = "#0284C7" if is_cad else "#0369A1"
    core_stroke = "#F59E0B" if is_cad else "#D97706"
    text_primary = "#F8FAFC" if is_cad else "#0F172A"
    text_secondary = "#94A3B8" if is_cad else "#64748B"
    text_dim = "#64748B" if is_cad else "#94A3B8"

    def px(x_m: float) -> float:
        return margin_x + (x_m * scale)

    def py(y_m: float) -> float:
        return margin_y + ((ir.envelope_d - y_m) * scale)

    ghost_attr = ' data-ghost-overlay="true"' if ir.header.floor_index > 0 else ' data-ghost-overlay="false"'
    svg: List[str] = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w} {svg_h}" width="{svg_w}" height="{svg_h}"{ghost_attr} style="background-color: {bg_color}; font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif;">')

    svg.append(f"""
      <defs>
        <pattern id="mf-grid-{theme}" width="{scale}" height="{scale}" patternUnits="userSpaceOnUse">
          <path d="M {scale} 0 L 0 0 0 {scale}" fill="none" stroke="{grid_line}" stroke-width="0.75" />
          <path d="M {scale/2} 0 L {scale/2} {scale} M 0 {scale/2} L {scale} {scale/2}" fill="none" stroke="{grid_line}" stroke-width="0.25" stroke-dasharray="2 2" />
        </pattern>
        <pattern id="mf-hatch-setback" width="10" height="10" patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="0" y2="10" stroke="{text_dim}" stroke-width="0.6" opacity="0.10" />
        </pattern>
        <pattern id="mf-hatch-terrace" width="12" height="12" patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="0" y2="12" stroke="{text_dim}" stroke-width="0.8" opacity="0.25" stroke-dasharray="2 2" />
        </pattern>
        <pattern id="mf-hatch-wedge" width="10" height="10" patternTransform="rotate(135 0 0)" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="0" y2="10" stroke="#F59E0B" stroke-width="0.9" opacity="0.45" />
        </pattern>
        <pattern id="mf-hatch-footprint" width="12" height="12" patternTransform="rotate(45 0 0)" patternUnits="userSpaceOnUse">
          <line x1="0" y1="0" x2="0" y2="12" stroke="#D97706" stroke-width="0.8" opacity="0.20" />
        </pattern>
        <marker id="entry-arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 1 L 9 5 L 0 9 z" fill="#10B981" />
        </marker>
        <style>
          .ghost-core-overlay {{
            transition: opacity 0.2s ease;
          }}
          .ghost-core-overlay.hidden, [data-ghost-overlay="false"] .ghost-core-overlay {{
            display: none !important;
          }}
          text {{
            user-select: none;
          }}
        </style>
      </defs>
    """)

    svg.append(f'  <rect width="{svg_w}" height="{svg_h}" fill="{bg_color}" />')
    svg.append(f'  <rect x="{margin_x}" y="{margin_y}" width="{content_w}" height="{content_h}" fill="url(#mf-grid-{theme})" />')

    # PRESENTATION PHASES (data-bw-phase)
    # ------------------------------------------------------------------
    # The sheet is emitted layer by layer already; these inert groups make
    # that layer order addressable by the viewer's progressive reveal. They
    # carry no geometry, no style and no validation meaning — the SVG renders
    # identically with or without them (groups are transparent). Certification,
    # solver output and every drawn coordinate are untouched.
    svg.append('  <g data-bw-phase="envelope">')
    if getattr(ir, "has_stepped_envelope", False):
        svg.append(f'  <rect x="{margin_x}" y="{margin_y}" width="{content_w}" height="{content_h}" fill="none" stroke="{text_dim}" stroke-width="0.8" stroke-dasharray="4 4" />')
    else:
        svg.append(f'  <rect x="{margin_x}" y="{margin_y}" width="{content_w}" height="{content_h}" fill="none" stroke="{ext_wall_stroke}" stroke-width="4.5" stroke-linecap="square" />')
    svg.append('  </g>')

    # 0. Site & Irregular Polygon Layer (If present)
    svg.append('  <g data-bw-phase="site">')
    for p in [prim for prim in ir.primitives if isinstance(prim, (PolygonPrimitive, PathPrimitive))]:
        if isinstance(p, PolygonPrimitive) and p.points:
            pts_str = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in p.points)
            fill_val = f'url(#{p.hatch_pattern})' if p.hatch_pattern else (p.fill_color or "none")
            fill_op = f' fill-opacity="{p.fill_opacity}"' if p.fill_opacity < 1.0 and not p.hatch_pattern else ""
            stroke_val = p.stroke_color or "none"
            stroke_w = max(0.5, p.stroke_width_m * scale) if p.stroke_width_m > 0 else 1.0
            dash_str = f' stroke-dasharray="{" ".join(str(d) for d in p.dash_array)}"' if p.dash_array else ""
            svg.append(f'  <polygon points="{pts_str}" fill="{fill_val}"{fill_op} stroke="{stroke_val}" stroke-width="{stroke_w:.1f}"{dash_str} />')
        elif isinstance(p, PathPrimitive) and p.points:
            pts_str = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in p.points)
            stroke_w = max(0.5, p.stroke_width_m * scale) if p.stroke_width_m > 0 else 1.0
            dash_str = f' stroke-dasharray="{" ".join(str(d) for d in p.dash_array)}"' if p.dash_array else ""
            svg.append(f'  <polyline points="{pts_str}" fill="{p.fill_color or "none"}" stroke="{p.stroke_color}" stroke-width="{stroke_w:.1f}"{dash_str} />')

    svg.append('  </g>')

    # 1. Fills Layer
    svg.append('  <g data-bw-phase="rooms">')
    for f in ir.primitives_by_layer("fills"):
        if isinstance(f, FillPrimitive):
            rx_svg = px(f.x)
            ry_svg = py(f.y + f.h)
            rw_svg = f.w * scale
            rh_svg = f.h * scale
            # Room identity is presentation metadata only: it lets the viewer
            # highlight the selected room in place. Geometry, layer order and
            # the validation gate are untouched.
            room_attrs = ""
            if f.room_id:
                room_attrs = (
                    f' class="bw-room-fill"'
                    f' data-room-id="{html.escape(f.room_id, quote=True)}"'
                    f' data-room-name="{html.escape(f.room_name or "", quote=True)}"'
                    f' data-zone="{html.escape(f.zone or "", quote=True)}"'
                )
            svg.append(f'  <rect x="{rx_svg:.1f}" y="{ry_svg:.1f}" width="{rw_svg:.1f}" height="{rh_svg:.1f}" fill="{f.fill_color}" fill-opacity="0.15"{room_attrs} />')
    svg.append('  </g>')

    # 2. Ghost Layer
    svg.append('  <g data-bw-phase="ghost">')
    for g in ir.primitives_by_layer("ghost"):
        if isinstance(g, GhostPrimitive):
            svg.append('  <!-- GHOST CORE OVERLAY -->')
            svg.append('  <g id="ghost-core-overlay" class="ghost-core-overlay" data-visible="true">')
            ghost_stroke = "rgba(6,182,212,0.5)" if is_cad else "rgba(2,132,199,0.4)"
            for cx, cy, cw, ch in g.core_rects:
                svg.append(f'    <rect x="{px(cx):.1f}" y="{py(cy + ch):.1f}" width="{cw*scale:.1f}" height="{ch*scale:.1f}" fill="rgba(6,182,212,0.04)" stroke="{ghost_stroke}" stroke-width="1.4" stroke-dasharray="5 3" />')
            for p1, p2 in g.ghost_treads:
                svg.append(f'    <line x1="{px(p1[0]):.1f}" y1="{py(p1[1]):.1f}" x2="{px(p2[0]):.1f}" y2="{py(p2[1]):.1f}" stroke="{ghost_stroke}" stroke-width="0.8" stroke-dasharray="3 3" opacity="0.5" />')
            if g.anchor_badge:
                ab = g.anchor_badge
                lp1, lp2 = ab["leader_p1"], ab["leader_p2"]
                bx, by, bw, bh = ab["badge_x"], ab["badge_y"], ab["badge_w"], ab["badge_h"]
                svg.append(f'    <line id="f0-core-leader" class="f0-core-leader" x1="{px(lp1[0]):.1f}" y1="{py(lp1[1]):.1f}" x2="{px(lp2[0]):.1f}" y2="{py(lp2[1]):.1f}" stroke="{ghost_stroke}" stroke-width="1.0" />')
                svg.append(f'    <rect id="f0-core-anchor-badge" class="core-anchor-badge" x="{px(bx):.1f}" y="{py(by + bh):.1f}" width="{bw*scale:.1f}" height="{bh*scale:.1f}" rx="3" fill="#0E7490" opacity="0.85" />')
                svg.append(f'    <text x="{px(bx + bw/2.0):.1f}" y="{py(by + bh) + 9.8:.1f}" font-size="7.0" font-weight="700" fill="#CFFAFE" text-anchor="middle" letter-spacing="0.5">F0 CORE ANCHOR</text>')
            for dsx, dsy, dsw, dsh in g.duct_shafts:
                svg.append(f'    <rect x="{px(dsx):.1f}" y="{py(dsy + dsh):.1f}" width="{dsw*scale:.1f}" height="{dsh*scale:.1f}" fill="rgba(245,158,11,0.08)" stroke="#F59E0B" stroke-width="1.2" stroke-dasharray="4 3" />')
                svg.append(f'    <line x1="{px(dsx):.1f}" y1="{py(dsy + dsh):.1f}" x2="{px(dsx + dsw):.1f}" y2="{py(dsy):.1f}" stroke="#F59E0B" stroke-width="0.8" stroke-dasharray="2 2" opacity="0.5" />')
                svg.append(f'    <line x1="{px(dsx + dsw):.1f}" y1="{py(dsy + dsh):.1f}" x2="{px(dsx):.1f}" y2="{py(dsy):.1f}" stroke="#F59E0B" stroke-width="0.8" stroke-dasharray="2 2" opacity="0.5" />')
            svg.append('  </g>')

    svg.append('  </g>')

    # 3. Walls Layer
    svg.append('  <g data-bw-phase="walls">')
    for w in ir.primitives_by_layer("walls"):
        if isinstance(w, WallPrimitive):
            x1_s = px(w.x1)
            y1_s = py(w.y1)
            x2_s = px(w.x2)
            y2_s = py(w.y2)
            if w.wall_type == "W1":
                w_strk = ext_wall_stroke
                w_w = max(3.5, w.thickness_m * scale)
                dash = ""
            elif w.wall_type == "W3":
                w_strk = int_wall_stroke
                w_w = max(1.8, w.thickness_m * scale)
                dash = 'stroke-dasharray="3 2"'
            elif w.wall_type == "W_PARAPET":
                # Double line for parapet
                w_strk = ext_wall_stroke
                dx = x2_s - x1_s
                dy = y2_s - y1_s
                length = math.hypot(dx, dy)
                if length > 0.1:
                    nx = -dy / length * 2.0
                    ny = dx / length * 2.0
                    svg.append(f'  <line data-wall-type="W_PARAPET" data-wall-id="{w.wall_id}" x1="{x1_s + nx:.1f}" y1="{y1_s + ny:.1f}" x2="{x2_s + nx:.1f}" y2="{y2_s + ny:.1f}" stroke="{w_strk}" stroke-width="1.2" stroke-linecap="square" />')
                    svg.append(f'  <line data-wall-type="W_PARAPET" data-wall-id="{w.wall_id}" x1="{x1_s - nx:.1f}" y1="{y1_s - ny:.1f}" x2="{x2_s - nx:.1f}" y2="{y2_s - ny:.1f}" stroke="{w_strk}" stroke-width="1.2" stroke-linecap="square" />')
                    continue
                else:
                    w_w = max(2.0, w.thickness_m * scale)
                    dash = ""
            else:
                w_strk = int_wall_stroke
                w_w = max(2.4, w.thickness_m * scale)
                dash = ""
            svg.append(f'  <line x1="{x1_s:.1f}" y1="{y1_s:.1f}" x2="{x2_s:.1f}" y2="{y2_s:.1f}" stroke="{w_strk}" stroke-width="{w_w:.1f}" {dash} stroke-linecap="square" />')

    svg.append('  </g>')

    # 4. Cores Layer (Staircase)
    svg.append('  <g data-bw-phase="cores">')
    for st in ir.primitives_by_layer("cores"):
        if isinstance(st, StairPrimitive):
            bx, by, bw, bh = st.boundary
            svg.append(f'  <rect x="{px(bx):.1f}" y="{py(by + bh):.1f}" width="{bw*scale:.1f}" height="{bh*scale:.1f}" fill="none" stroke="{core_stroke}" stroke-width="2.6" stroke-dasharray="4 2" />')
            ll1, ll2 = st.landing_line
            svg.append(f'  <line x1="{px(ll1[0]):.1f}" y1="{py(ll1[1]):.1f}" x2="{px(ll2[0]):.1f}" y2="{py(ll2[1]):.1f}" stroke="{core_stroke}" stroke-width="1.8" />')
            dl1, dl2 = st.dividing_line
            svg.append(f'  <line x1="{px(dl1[0]):.1f}" y1="{py(dl1[1]):.1f}" x2="{px(dl2[0]):.1f}" y2="{py(dl2[1]):.1f}" stroke="{core_stroke}" stroke-width="1.4" />')
            for tp1, tp2 in st.treads:
                svg.append(f'  <line x1="{px(tp1[0]):.1f}" y1="{py(tp1[1]):.1f}" x2="{px(tp2[0]):.1f}" y2="{py(tp2[1]):.1f}" stroke="{core_stroke}" stroke-width="1.0" opacity="0.75" />')
            up1, up2 = st.up_line
            svg.append(f'  <line x1="{px(up1[0]):.1f}" y1="{py(up1[1]):.1f}" x2="{px(up2[0]):.1f}" y2="{py(up2[1]):.1f}" stroke="{core_stroke}" stroke-width="1.5" />')
            pts_str = " ".join(f"{px(p[0]):.1f},{py(p[1]):.1f}" for p in st.up_tip)
            svg.append(f'  <polyline points="{pts_str}" fill="none" stroke="{core_stroke}" stroke-width="1.5" />')
            svg.append(f'  <text x="{px(st.up_text_pos[0]):.1f}" y="{py(st.up_text_pos[1]):.1f}" font-size="7.0" font-weight="700" fill="{core_stroke}" text-anchor="middle">UP</text>')
            if st.dn_line and st.dn_tip and st.dn_text_pos:
                dn1, dn2 = st.dn_line
                svg.append(f'  <line x1="{px(dn1[0]):.1f}" y1="{py(dn1[1]):.1f}" x2="{px(dn2[0]):.1f}" y2="{py(dn2[1]):.1f}" stroke="{core_stroke}" stroke-width="1.5" />')
                pts_dn = " ".join(f"{px(p[0]):.1f},{py(p[1]):.1f}" for p in st.dn_tip)
                svg.append(f'  <polyline points="{pts_dn}" fill="none" stroke="{core_stroke}" stroke-width="1.5" />')
                svg.append(f'  <text x="{px(st.dn_text_pos[0]):.1f}" y="{py(st.dn_text_pos[1]):.1f}" font-size="7.0" font-weight="700" fill="{core_stroke}" text-anchor="middle">DN</text>')
            hrx, hry = st.headroom_text_pos
            svg.append(f'  <text x="{px(hrx):.1f}" y="{py(hry):.1f}" font-size="6.5" font-weight="700" fill="{core_stroke}" text-anchor="middle" letter-spacing="0.2">{st.headroom_text}</text>')

    # 4b. Unit-badge placement plan
    #  The unit entry tag is fixed-size typography riding a door hinge.  Two
    #  adjacent unit doors (T2 north/south entries) place two 38 x 13 px tags
    #  on the same hinge line, and the stair "UP" text or a door tag can sit
    #  right under them.  Score a deterministic candidate set against the
    #  on-plan text boxes already scheduled and the tags drawn so far, then
    #  take the least-overlapping spot instead of always printing to the
    #  right of the hinge.
    _badge_obstacles: List[Tuple[float, float, float, float]] = []
    for _tp in ir.primitives_by_layer("text"):
        if not isinstance(_tp, TextPrimitive):
            continue
        _hw = float(getattr(_tp, "halo_w_m", 1.8) or 1.8) / 2.0
        _hh = float(getattr(_tp, "halo_h_m", 0.55) or 0.55) / 2.0
        _badge_obstacles.append(
            (px(_tp.x - _hw), py(_tp.y + _hh), px(_tp.x + _hw), py(_tp.y - _hh))
        )
    # Every opening tag is a fixed 15 x 11 px box centred on its tag point.
    for _op in ir.primitives_by_layer("openings"):
        if isinstance(_op, OpeningPrimitive):
            _tx, _ty = px(_op.tag_x), py(_op.tag_y)
            _badge_obstacles.append((_tx - 7.5, _ty - 5.5, _tx + 7.5, _ty + 5.5))
    for _st in ir.primitives_by_layer("cores"):
        if not isinstance(_st, StairPrimitive):
            continue
        for _pos, _half_w in (
            (getattr(_st, "up_text_pos", None), 10.0),
            (getattr(_st, "dn_text_pos", None), 10.0),
        ):
            if _pos:
                _sx, _sy = px(_pos[0]), py(_pos[1])
                _badge_obstacles.append((_sx - _half_w, _sy - 6.0, _sx + _half_w, _sy + 6.0))
        _head = getattr(_st, "headroom_text_pos", None)
        if _head:
            _head_text = str(getattr(_st, "headroom_text", "") or "")
            _half_w = max(12.0, len(_head_text) * 2.4)
            _sx, _sy = px(_head[0]), py(_head[1])
            _badge_obstacles.append((_sx - _half_w, _sy - 5.5, _sx + _half_w, _sy + 5.5))

    def _rect_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
        w = min(a[2], b[2]) - max(a[0], b[0])
        h = min(a[3], b[3]) - max(a[1], b[1])
        return w * h if w > 0.0 and h > 0.0 else 0.0

    def _place_unit_badge(hx_s: float, hy_s: float, ub: Dict[str, Any]) -> Tuple[float, float]:
        ub_w, ub_h = 38.0, 13.0
        candidates: List[Tuple[float, float]] = []
        rect = ub.get("rect") if isinstance(ub, dict) else None
        if rect and float(rect[2]) > 0.20 and float(rect[3]) > 0.20:
            _rx, _ry, _rw, _rd = (float(v) for v in rect)
            left = px(_rx)
            right = px(_rx + _rw)
            bottom = py(_ry)
            top = py(_ry + _rd)

            def _clamp(v: float, lo: float, hi: float) -> float:
                return lo if hi < lo else min(max(v, lo), hi)

            # Four room corners and four edge midpoints, clamped so the chip
            # stays inside the room.  Corners carry door tags on small rooms;
            # the edge midpoints are the free fallback in a large living room.
            _spots = [
                (left + 2.0, top + 2.0, False, False),
                (right - 2.0, top + 2.0, True, False),
                (left + 2.0, bottom - 2.0, False, True),
                (right - 2.0, bottom - 2.0, True, True),
                ((left + right) / 2.0, top + 2.0, None, False),
                ((left + right) / 2.0, bottom - 2.0, None, True),
                (left + 2.0, (top + bottom) / 2.0, False, None),
                (right - 2.0, (top + bottom) / 2.0, True, None),
            ]
            for cx, cy, is_right, is_bottom in _spots:
                x = cx - ub_w / 2.0 if is_right is None else cx - (ub_w if is_right else 0.0)
                y = cy - ub_h / 2.0 if is_bottom is None else cy - (ub_h if is_bottom else 0.0)
                candidates.append((
                    _clamp(x, left + 2.0, right - ub_w - 2.0),
                    _clamp(y, top + 2.0, bottom - ub_h - 2.0),
                ))
            # Nearest spot first: the chip still reads as the unit's entry
            # marker rather than floating in the far end of the room.
            candidates.sort(key=lambda c: (c[0] - hx_s) ** 2 + (c[1] - hy_s) ** 2)
        # Hinge-relative fallbacks for a room too small to hold the chip.
        candidates.extend([
            (hx_s + 4.0, hy_s - 22.0), (hx_s + 4.0, hy_s + 12.0),
            (hx_s - ub_w - 4.0, hy_s - 22.0), (hx_s - ub_w - 4.0, hy_s + 12.0),
            (hx_s - ub_w / 2.0, hy_s - 38.0), (hx_s - ub_w / 2.0, hy_s + 20.0),
        ])
        best: Optional[Tuple[float, float, float, Tuple[float, float, float, float]]] = None
        for _cx, _cy in candidates:
            x = min(max(2.0, _cx), svg_w - ub_w - 2.0)
            y = min(max(2.0, _cy), svg_h - ub_h - 2.0)
            box = (x, y, x + ub_w, y + ub_h)
            score = sum(_rect_overlap(box, ob) for ob in _badge_obstacles)
            if best is None or score < best[0] - 1e-9:
                best = (score, x, y, box)
            if score <= 0.0:
                break
        _, x, y, box = best
        _badge_obstacles.append(box)
        return x, y

    svg.append('  </g>')

    # 5. Openings Layer (Doors & Windows)
    svg.append('  <g data-bw-phase="openings">')
    for op in ir.primitives_by_layer("openings"):
        if isinstance(op, OpeningPrimitive):
            if op.opening_type == "door":
                for jp1, jp2 in op.door_jambs:
                    svg.append(f'  <line x1="{px(jp1[0]):.1f}" y1="{py(jp1[1]):.1f}" x2="{px(jp2[0]):.1f}" y2="{py(jp2[1]):.1f}" stroke="{door_stroke}" stroke-width="1.8" />')
                hx_s, hy_s = px(op.hinge_x), py(op.hinge_y)
                lx_s, ly_s = px(op.leaf_x), py(op.leaf_y)
                svg.append(f'  <line x1="{hx_s:.1f}" y1="{hy_s:.1f}" x2="{lx_s:.1f}" y2="{ly_s:.1f}" stroke="{door_stroke}" stroke-width="2.0" />')
                sx_s, sy_s = px(op.arc_start_pt[0]), py(op.arc_start_pt[1])
                ex_s, ey_s = px(op.arc_end_pt[0]), py(op.arc_end_pt[1])
                r_s = op.arc_radius_m * scale
                svg.append(f'  <path d="M {sx_s:.1f} {sy_s:.1f} A {r_s:.1f} {r_s:.1f} 0 0 {op.svg_sweep_flag} {ex_s:.1f} {ey_s:.1f}" fill="none" stroke="{door_stroke}" stroke-width="1.4" stroke-dasharray="3 3" />')
                ptag_x = px(op.tag_x)
                ptag_y = py(op.tag_y)
                svg.append(f'  <rect x="{ptag_x - 7.5:.1f}" y="{ptag_y - 5.5:.1f}" width="15.0" height="11.0" rx="3" fill="{bg_color}" stroke="{door_stroke}" stroke-width="0.8" />')
                svg.append(f'  <text x="{ptag_x:.1f}" y="{ptag_y + 2.5:.1f}" font-size="6.0" font-weight="700" fill="{door_stroke}" text-anchor="middle">{op.tag}</text>')
                if op.unit_badge:
                    ub = op.unit_badge
                    ub_w = 38.0
                    ub_h = 13.0
                    ub_x, ub_y = _place_unit_badge(hx_s, hy_s, ub)
                    unit_badge_bg = "#FEF3C7" if not is_cad else "rgba(245, 158, 11, 0.15)"
                    unit_badge_stroke = "#D97706" if not is_cad else "#F59E0B"
                    unit_badge_text = "#92400E" if not is_cad else "#F59E0B"
                    svg.append(f'  <rect x="{ub_x:.1f}" y="{ub_y:.1f}" width="{ub_w:.1f}" height="{ub_h:.1f}" rx="2" fill="{unit_badge_bg}" stroke="{unit_badge_stroke}" stroke-width="0.8" class="badge" />')
                    svg.append(f'  <text x="{ub_x + ub_w/2.0:.1f}" y="{ub_y + 9.0:.1f}" font-size="7.0" font-weight="700" fill="{unit_badge_text}" text-anchor="middle">{ub["tag"]}</text>')
            elif op.opening_type == "window":
                if op.outer_line and op.glass_line and op.inner_line:
                    op1, op2 = op.outer_line
                    gp1, gp2 = op.glass_line
                    ip1, ip2 = op.inner_line
                    svg.append(f'  <line x1="{px(op1[0]):.1f}" y1="{py(op1[1]):.1f}" x2="{px(op2[0]):.1f}" y2="{py(op2[1]):.1f}" stroke="{window_stroke}" stroke-width="1.5" />')
                    svg.append(f'  <line x1="{px(gp1[0]):.1f}" y1="{py(gp1[1]):.1f}" x2="{px(gp2[0]):.1f}" y2="{py(gp2[1]):.1f}" stroke="{text_primary}" stroke-width="0.9" />')
                    svg.append(f'  <line x1="{px(ip1[0]):.1f}" y1="{py(ip1[1]):.1f}" x2="{px(ip2[0]):.1f}" y2="{py(ip2[1]):.1f}" stroke="{window_stroke}" stroke-width="1.5" />')
                pwtag_x = px(op.tag_x)
                pwtag_y = py(op.tag_y)
                svg.append(f'  <rect x="{pwtag_x - 7.5:.1f}" y="{pwtag_y - 5.5:.1f}" width="15.0" height="11.0" rx="3" fill="{bg_color}" stroke="{window_stroke}" stroke-width="0.8" />')
                svg.append(f'  <text x="{pwtag_x:.1f}" y="{pwtag_y + 2.5:.1f}" font-size="6.0" font-weight="700" fill="{window_stroke}" text-anchor="middle">{op.tag}</text>')

    svg.append('  </g>')

    # 6. Text & Typography Layer
    svg.append('  <g data-bw-phase="labels">')
    for t in ir.primitives_by_layer("text"):
        if isinstance(t, TextPrimitive):
            tx_s = px(t.x)
            ty_s = py(t.y)
            if t.room_tag_circle:
                b_fill = "#1E293B" if is_cad else "#E2E8F0"
                b_strk = "#38BDF8" if is_cad else "#0284C7"
                b_txt = "#F8FAFC" if is_cad else "#0F172A"
                tag_num = t.room_tag_circle["room_idx"]
                rad = t.room_tag_circle.get("radius_px", 7.5)
                cent = t.room_tag_circle.get("centroid_m")
                if cent:
                    cx_s, cy_s = px(cent[0]), py(cent[1])
                    dist_to_cent = math.hypot(tx_s - cx_s, ty_s - cy_s)
                    if dist_to_cent > rad + 2.0:
                        svg.append(f'  <line x1="{cx_s:.1f}" y1="{cy_s:.1f}" x2="{tx_s:.1f}" y2="{ty_s:.1f}" stroke="{b_strk}" stroke-width="1.0" stroke-dasharray="2 2" />')
                        svg.append(f'  <circle cx="{cx_s:.1f}" cy="{cy_s:.1f}" r="2.0" fill="{b_strk}" />')
                svg.append(f'  <circle id="room-tag-{tag_num}" class="room-tag-badge" cx="{tx_s:.1f}" cy="{ty_s:.1f}" r="{rad:.1f}" fill="{b_fill}" stroke="{b_strk}" stroke-width="1.2" />')
                svg.append(f'  <text x="{tx_s:.1f}" y="{ty_s + 2.5:.1f}" font-size="7.5" font-weight="700" fill="{b_txt}" text-anchor="middle">{tag_num}</text>')
            else:
                lines = t.lines if t.lines else [t.text]
                fs = t.font_size_pt
                total_h = t.total_h_m * scale
                top_y = ty_s - total_h / 2.0
                line_step = fs * 1.25

                if t.halo:
                    lines_to_measure = lines.copy()
                    if t.subtext:
                        lines_to_measure.append(t.subtext)
                    max_text_w_px = max((_approx_text_width(l, fs) for l in lines_to_measure), default=0.0)
                    hw = max(t.halo_w_m * scale, max_text_w_px + 14.0)
                    hh = max(t.halo_h_m * scale, (len(lines_to_measure) * fs * 1.3) + 8.0)
                    halo_fill = "rgba(11,19,43,0.85)" if is_cad else "rgba(255,255,255,0.92)"
                    svg.append(f'  <rect x="{tx_s - hw/2.0:.1f}" y="{ty_s - hh/2.0:.1f}" width="{hw:.1f}" height="{hh:.1f}" rx="3" fill="{halo_fill}" stroke="rgba(0,0,0,0.08)" stroke-width="0.5" />')

                for line_idx, line in enumerate(lines):
                    y_baseline = top_y + (line_idx + 0.85) * line_step
                    svg.append(f'  <text x="{tx_s:.1f}" y="{y_baseline:.1f}" font-size="{fs:.1f}" font-weight="700" fill="{text_primary}" text-anchor="middle" letter-spacing="0.5">{html.escape(line)}</text>')

                if t.subtext:
                    y_dims = top_y + len(lines) * line_step + 3.0 + 0.85 * t.subtext_pt
                    svg.append(f'  <text x="{tx_s:.1f}" y="{y_dims:.1f}" font-size="{t.subtext_pt:.1f}" font-weight="500" fill="{text_secondary}" text-anchor="middle">{html.escape(t.subtext)}</text>')

    svg.append('  </g>')

    # 7. Dimension Chains Layer
    svg.append('  <g data-bw-phase="dims">')
    def draw_slash_tick_svg(tx: float, ty: float):
        svg.append(f'  <line x1="{tx - 3.0:.1f}" y1="{ty + 3.0:.1f}" x2="{tx + 3.0:.1f}" y2="{ty - 3.0:.1f}" stroke="{ext_wall_stroke}" stroke-width="1.6" />')

    for dc in ir.primitives_by_layer("dims"):
        if isinstance(dc, DimensionChainPrimitive):
            p1, p2 = dc.main_line
            svg.append(f'  <line x1="{px(p1[0]):.1f}" y1="{py(p1[1]):.1f}" x2="{px(p2[0]):.1f}" y2="{py(p2[1]):.1f}" stroke="{text_dim}" stroke-width="0.9" />')
            for tk in dc.ticks:
                draw_slash_tick_svg(px(tk[0]), py(tk[1]))
            for wp1, wp2 in dc.witness_lines:
                svg.append(f'  <line x1="{px(wp1[0]):.1f}" y1="{py(wp1[1]):.1f}" x2="{px(wp2[0]):.1f}" y2="{py(wp2[1]):.1f}" stroke="{text_dim}" stroke-width="0.5" stroke-dasharray="2 2" />')
            for s_idx, seg in enumerate(dc.segments):
                lbl_x = px(seg["center_x"])
                lbl_y = py(seg["center_y"])
                lbl_txt = seg["label"]
                fs = max(7.0, seg.get("font_size_pt", 7.0))
                seg_len = _safe_float(seg.get("length_m", 2.0), 2.0)
                offset = 0.0
                if seg_len < 1.8:
                    offset = -7.0 if (s_idx % 2 == 0) else 7.0
                if seg.get("is_vertical"):
                    lbl_x += offset
                    svg.append(f'  <text x="{lbl_x:.1f}" y="{lbl_y:.1f}" font-size="{fs:.1f}" font-weight="700" fill="{text_primary}" text-anchor="middle" transform="rotate(-90 {lbl_x:.1f} {lbl_y:.1f})">{lbl_txt}</text>')
                else:
                    lbl_y += offset
                    svg.append(f'  <text x="{lbl_x:.1f}" y="{lbl_y:.1f}" font-size="{fs:.1f}" font-weight="700" fill="{text_primary}" text-anchor="middle">{lbl_txt}</text>')

    svg.append('  </g>')

    # 8. Annotations Layer
    svg.append('  <g data-bw-phase="annotations">')
    for annot in ir.primitives_by_layer("annotations"):
        if isinstance(annot, AnnotationPrimitive):
            if annot.compass:
                cx = px(annot.compass["x"])
                cy = py(annot.compass["y"])
                svg.append(f'  <g transform="translate({cx:.1f}, {cy:.1f})">')
                svg.append(f'    <circle cx="0" cy="0" r="14" fill="{bg_color}" stroke="{text_secondary}" stroke-width="1.2" />')
                svg.append(f'    <polygon points="0,-12 3,0 0,-2 -3,0" fill="{ext_wall_stroke}" />')
                svg.append(f'    <polygon points="0,12 3,0 0,2 -3,0" fill="{text_dim}" />')
                svg.append(f'    <text x="0" y="-15" font-size="8.5" font-weight="800" fill="{text_primary}" text-anchor="middle">N</text>')
                svg.append('  </g>')

            # Bottom strip: anchored below the legend block (or schedule panel
            # on sheets without a gate table) - planned upfront above.
            scale_y = scale_strip_y
            svg.append(f'  <g transform="translate({margin_x}, {scale_y})">')
            svg.append(f'    <text x="0" y="-12" font-size="7.0" font-weight="700" fill="{text_secondary}">GRAPHIC SCALE (METRIC)</text>')
            svg.append(f'    <rect x="0" y="0" width="{scale}" height="3" fill="{text_secondary}" />')
            svg.append(f'    <rect x="{scale}" y="0" width="{scale}" height="3" fill="{grid_line}" />')
            svg.append(f'    <text x="0" y="-4" font-size="7.0" fill="{text_secondary}">0</text>')
            svg.append(f'    <text x="{scale}" y="-4" font-size="7.0" fill="{text_secondary}">1m</text>')
            svg.append(f'    <text x="{scale*2}" y="-4" font-size="7.0" fill="{text_secondary}">2m (1:50)</text>')
            svg.append('  </g>')

            for stag in annot.structural_tags:
                if "tag" in stag:
                    stx, sty = px(stag["x"]), py(stag["y"])
                    svg.append(f'  <text x="{stx:.1f}" y="{sty:.1f}" font-size="6.5" font-weight="700" fill="{ext_wall_stroke}" text-anchor="start" letter-spacing="0.5">{stag["tag"]}</text>')
                elif "bubble" in stag:
                    bx, by = px(stag["x"]), py(stag["y"])
                    svg.append(f'  <circle cx="{bx:.1f}" cy="{by:.1f}" r="6.5" fill="{bg_color}" stroke="{ext_wall_stroke}" stroke-width="1.0" class="col-grid-bubble" />')
                    svg.append(f'  <text x="{bx:.1f}" y="{by + 2.5:.1f}" font-size="6.5" font-weight="700" fill="{text_primary}" text-anchor="middle">{stag["bubble"]}</text>')

            if annot.entrance_pointer:
                ep = annot.entrance_pointer
                ep1, ep2 = ep["p1"], ep["p2"]
                svg.append(f'  <line x1="{px(ep1[0]):.1f}" y1="{py(ep1[1]):.1f}" x2="{px(ep2[0]):.1f}" y2="{py(ep2[1]):.1f}" stroke="#10B981" stroke-width="2.6" marker-end="url(#entry-arrow)" />')
                lbl_pos = ep["label_pos"]
                svg.append(f'  <text x="{px(lbl_pos[0]):.1f}" y="{py(lbl_pos[1]):.1f}" font-size="8.5" font-weight="800" stroke="{bg_color}" stroke-width="3.2" stroke-linejoin="round" fill="#047857" paint-order="stroke fill" text-anchor="middle" letter-spacing="0.8">{ep["label"]}</text>')

    svg.append('  </g>')

    # Sheet furniture: title block, specification legend, schedules, validation
    # gate, watermark. The authoritative verdict itself is rendered in the
    # app chrome (PlanVerdictChip), outside this or any animated group.
    svg.append('  <g data-bw-phase="sheet">')

    typology_tag = f"TYPOLOGY: {ir.header.typology} | {ir.header.freshness_token}"
    svg.append(f'  <g transform="translate({margin_x}, {banner_y})">')
    if ir.header.floor_index >= 0:
        svg.append(f'    <text x="0" y="11.0" font-size="11.0" font-weight="700" fill="{text_primary}">{html.escape(ir.header.floor_name.upper())} (+{ir.header.elevation_m:.2f}m LVL)</text>')
        # Typology and stamp on SEPARATE lines: the combined line exceeded the
        # canvas on narrow plots and was clipped mid-word. Stamp always keeps
        # its tail ("NOT FOR CONSTRUCTION") - never ellipsized. _hdr_max was
        # planned upfront and the SAME wrap produced it, so schedules_y
        # already clears the true banner bottom.
        _tag_fs, _tag_txt = _fit_banner_line(typology_tag, _hdr_max)
        svg.append(f'    <text x="0" y="25.0" font-size="{_tag_fs:.2f}" font-weight="600" fill="{text_secondary}">{html.escape(_tag_txt)}</text>')
        _stamp_lines = _stamp_lines_plan
        for _si, _sline in enumerate(_stamp_lines):
            svg.append(f'    <text x="0" y="{38.0 + _si * 12.0:.1f}" font-size="7.5" font-weight="600" fill="{text_secondary}">{html.escape(_sline)}</text>')
        if ir.header.floor_index == 0:
            entrance_dir = "SOUTH" if (getattr(ir, "has_stepped_envelope", False)) else "NORTH"
            _entry_y = 38.0 + len(_stamp_lines) * 12.0 + 6.0
            svg.append(f'    <text x="0" y="{_entry_y:.1f}" font-size="8.5" font-weight="600" fill="#10B981">MAIN ENTRANCE: {entrance_dir} | MAIN ENTRY | NBC 2016 COMPLIANT</text>')
    else:
        svg.append(f'    <text x="0" y="11.0" font-size="11.0" font-weight="700" fill="{text_primary}">{html.escape(ir.header.floor_name.upper())}</text>')
        _tag_fs, _tag_txt = _fit_banner_line(typology_tag, _hdr_max, base_fs=8.5)
        svg.append(f'    <text x="0" y="24.0" font-size="{_tag_fs:.2f}" font-weight="500" fill="{text_secondary}">{html.escape(_tag_txt)}</text>')
        # Site stamp wrapped too: same plan, tail always kept, ids never
        # dropped; the NBC/POLICY lines flow BELOW the actual last line.
        for _si, _sline in enumerate(_stamp_lines_plan):
            svg.append(f'    <text x="0" y="{36.0 + _si * 12.0:.1f}" font-size="7.5" font-weight="800" fill="#DC2626">{html.escape(_sline)}</text>')
        _nbc_y = 36.0 + len(_stamp_lines_plan) * 12.0 + 12.0
        svg.append(f'    <text x="0" y="{_nbc_y:.1f}" font-size="8.5" font-weight="600" fill="#10B981">NBC 2016 SETBACK COMPLIANT | SURVEY COORD SYSTEM (EASTING, NORTHING)</text>')
        if getattr(ir, "design_policy", None):
            svg.append(f'    <text x="0" y="{_nbc_y + 11.0:.1f}" font-size="7.5" font-weight="600" fill="#D97706">POLICY: {html.escape(_ellipsize_str(str(ir.design_policy), _hdr_max))}</text>')
            if getattr(ir, "design_policy_rationale", None):
                svg.append(f'    <text x="0" y="{_nbc_y + 21.0:.1f}" font-size="6.5" font-weight="500" fill="{text_secondary}">Rationale: {html.escape(_ellipsize_str(str(ir.design_policy_rationale), _hdr_max))}</text>')
    svg.append('  </g>')

    svg.append(f'  <g transform="translate({margin_x}, {schedules_y})">')
    if ir.header.floor_index >= 0:
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}" letter-spacing="0.4">WALL TYPE SPECIFICATION (NBC 2016 COMPLIANT)</text>')
        svg.append(f'    <line x1="0" y1="18.0" x2="16.0" y2="18.0" stroke="{ext_wall_stroke}" stroke-width="4.0" />')
        svg.append(f'    <text x="22.0" y="20.0" font-size="6.5" font-weight="600" fill="{text_secondary}">W1: 230mm Exterior Structural Wall (Masonry/RCC) - NBC 2016 Pt 3 Cl 3.4.1</text>')
        svg.append(f'    <line x1="0" y1="29.0" x2="16.0" y2="29.0" stroke="{int_wall_stroke}" stroke-width="2.5" />')
        svg.append(f'    <text x="22.0" y="31.0" font-size="6.5" font-weight="600" fill="{text_secondary}">W2: 115mm Interior Partition Wall (Half-Brick Masonry)</text>')
        svg.append(f'    <line x1="0" y1="40.0" x2="16.0" y2="40.0" stroke="{int_wall_stroke}" stroke-width="1.8" stroke-dasharray="3 2" />')
        svg.append(f'    <text x="22.0" y="42.0" font-size="6.5" font-weight="600" fill="{text_secondary}">W3: 75mm Toilet / Shaft Lightweight Enclosure</text>')
    else:
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}" letter-spacing="0.4">SITE PLAN SPECIFICATION &amp; LEGEND</text>')
        svg.append(f'    <line x1="0" y1="18.0" x2="16.0" y2="18.0" stroke="{ext_wall_stroke}" stroke-width="3.5" />')
        svg.append(f'    <text x="22.0" y="20.0" font-size="6.5" font-weight="600" fill="{text_secondary}">Plot Boundary &amp; Cadastral Survey Perimeters</text>')
        svg.append(f'    <line x1="0" y1="29.0" x2="16.0" y2="29.0" stroke="#0284C7" stroke-width="2.0" stroke-dasharray="4 3" />')
        svg.append(f'    <text x="22.0" y="31.0" font-size="6.5" font-weight="600" fill="{text_secondary}">Statutory Buildable Envelope (Setbacks Deducted)</text>')
        svg.append(f'    <line x1="0" y1="40.0" x2="16.0" y2="40.0" stroke="#D97706" stroke-width="3.5" />')
        svg.append(f'    <text x="22.0" y="42.0" font-size="6.5" font-weight="600" fill="{text_secondary}">Proposed Building Footprint (Wing A + Wing B + Link)</text>')
        svg.append(f'    <line x1="0" y1="51.0" x2="16.0" y2="51.0" stroke="#F59E0B" stroke-width="2.5" stroke-dasharray="3 2" />')
        svg.append(f'    <text x="22.0" y="53.0" font-size="6.5" font-weight="600" fill="{text_secondary}">Functional Wedge Zone (Non-Habitable Absorption)</text>')
    svg.append('  </g>')

    if ir.header.floor_index >= 0:
        # Narrow canvases stack the schedule tables vertically (window under
        # door, stair under room, gate under stair) instead of two columns
        # that would clip past the right edge.
        _narrow_stack = _narrow
        door_tbl_y = schedules_y + 54.0
        svg.append(f'  <g transform="translate({margin_x}, {door_tbl_y})">')
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">DOOR SCHEDULE</text>')
        d_cols = [24.0, 52.0, 56.0, 36.0]
        d_heads = ["TAG", "W x H (m)", "TYPE", "LEVEL"]
        cx = 0.0
        for h_txt, cw in zip(d_heads, d_cols):
            svg.append(f'    <text x="{cx:.1f}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">{h_txt}</text>')
            cx += cw

        for r_idx, d_row in enumerate(ir.door_schedule[:5]):
            ry_pos = 29.0 + (r_idx * 10.5)
            d_tag = str(d_row.get("tag", f"D{r_idx+1}"))
            if "dimension" in d_row:
                d_wh = str(d_row["dimension"])
            elif "width_mm" in d_row and "height_mm" in d_row:
                d_wh = f"{d_row['width_mm']/1000.0:.2f}x{d_row['height_mm']/1000.0:.2f}"
            else:
                d_wh = f"{_safe_float(d_row.get('width_m', 0.9), 0.9):.2f}x{_safe_float(d_row.get('height_m', 2.1), 2.1):.2f}"
            d_tp = _ellipsize_str(d_row.get("door_type", d_row.get("type", "Standard")), 14)
            raw_lvl = d_row.get("level", ir.header.floor_index)
            # Canonical ladder: accept "L0" / "Level 0" / int, and strip a
            # legacy double-prefixed "LLevel 0" so the sheet can never print it.
            if isinstance(raw_lvl, str) and raw_lvl.startswith("LLevel "):
                d_lvl = f"L{raw_lvl[7:].strip()}"
            elif isinstance(raw_lvl, str) and raw_lvl.startswith("Level "):
                d_lvl = f"L{raw_lvl[6:].strip()}"
            elif isinstance(raw_lvl, str) and raw_lvl.startswith("L"):
                d_lvl = raw_lvl
            else:
                d_lvl = f"L{raw_lvl}"
            rcx = 0.0
            for val_txt, cw in zip([d_tag, d_wh, d_tp, d_lvl], d_cols):
                svg.append(f'    <text x="{rcx:.1f}" y="{ry_pos:.1f}" font-size="6.0" font-weight="500" fill="{text_dim}">{html.escape(val_txt)}</text>')
                rcx += cw
        svg.append('  </g>')

        if _narrow_stack:
            win_tbl_x = margin_x
            win_tbl_y = door_tbl_y + 88.0
        else:
            win_tbl_x = margin_x + max(180.0, (content_w - 20.0) / 2.0) + 10.0
            win_tbl_y = door_tbl_y
        svg.append(f'  <g transform="translate({win_tbl_x}, {win_tbl_y})">')
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">WINDOW SCHEDULE</text>')
        w_cols = [24.0, 52.0, 46.0, 46.0]
        w_heads = ["TAG", "W x H (m)", "SILL", "LINTEL"]
        cx = 0.0
        for h_txt, cw in zip(w_heads, w_cols):
            svg.append(f'    <text x="{cx:.1f}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">{h_txt}</text>')
            cx += cw

        for r_idx, w_row in enumerate(ir.window_schedule[:5]):
            ry_pos = 29.0 + (r_idx * 10.5)
            w_tag = str(w_row.get("tag", f"W{r_idx+1}"))
            if "dimension" in w_row:
                w_wh = str(w_row["dimension"])
            elif "width_mm" in w_row and "height_mm" in w_row:
                w_wh = f"{w_row['width_mm']/1000.0:.2f}x{w_row['height_mm']/1000.0:.2f}"
            else:
                w_wh = f"{_safe_float(w_row.get('width_m', 1.2), 1.2):.2f}x{_safe_float(w_row.get('height_m', 1.2), 1.2):.2f}"
            sill_v = w_row.get("sill_height_m", w_row.get("sill_m"))
            if sill_v is not None:
                w_sill = f"+{_safe_float(sill_v, 0.9):.2f}m"
            elif "sill_mm" in w_row:
                w_sill = f"+{w_row['sill_mm']/1000.0:.2f}m"
            else:
                w_sill = "+0.90m"
            lint_v = w_row.get("lintel_height_m", w_row.get("lintel_m"))
            if lint_v is not None:
                w_lint = f"+{_safe_float(lint_v, 2.1):.2f}m"
            elif "lintel_mm" in w_row:
                w_lint = f"+{w_row['lintel_mm']/1000.0:.2f}m"
            else:
                w_lint = "+2.10m"
            rcx = 0.0
            for val_txt, cw in zip([w_tag, w_wh, w_sill, w_lint], w_cols):
                svg.append(f'    <text x="{rcx:.1f}" y="{ry_pos:.1f}" font-size="6.0" font-weight="500" fill="{text_dim}">{html.escape(val_txt)}</text>')
                rcx += cw
        svg.append('  </g>')

        room_tbl_y = (win_tbl_y + 88.0) if _narrow_stack else (door_tbl_y + 82.0)
        svg.append(f'  <g transform="translate({margin_x}, {room_tbl_y})">')
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">ROOM SCHEDULE</text>')
        r_cols = [24.0, 80.0, 40.0, 56.0]
        r_heads = ["NO", "ROOM NAME", "CLEAR AREA", "CLEAR W x D"]
        cx = 0.0
        for h_txt, cw in zip(r_heads, r_cols):
            svg.append(f'    <text x="{cx:.1f}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">{h_txt}</text>')
            cx += cw

        for r_idx, r_row in enumerate(ir.room_schedule):
            ry_pos = 29.0 + (r_idx * 10.5)
            r_num = str(r_row.get("room_number", r_row.get("room_no", r_row.get("no", r_idx + 1))))
            r_name = _ellipsize_str(r_row.get("room_name", "Room"), 18)
            # The AREA column is CLEAR interior area, so it reads the clear
            # field by name and never falls back to the gross `area_sqm`.
            area_val = r_row.get("clear_area_sqm", r_row.get("clear_area_m2", r_row.get("area_sqm", r_row.get("area", 0.0))))
            r_area = f"{_safe_float(area_val, 0.0):.1f}m²"
            r_dims = r_row.get("clear_dimensions", r_row.get("clear_dims"))
            if not r_dims:
                r_dims = f"{_safe_float(r_row.get('width_m', 0.0), 0.0):.2f}x{_safe_float(r_row.get('depth_m', 0.0), 0.0):.2f}"
            rcx = 0.0
            for val_txt, cw in zip([r_num, r_name, r_area, r_dims], r_cols):
                svg.append(f'    <text x="{rcx:.1f}" y="{ry_pos:.1f}" font-size="6.0" font-weight="500" fill="{text_dim}">{html.escape(val_txt)}</text>')
                rcx += cw

        # NAMING HONESTY LEGEND: prints the ontology class threshold used per room.
        # RELATIVE offset inside the ROOM SCHEDULE group (which already carries
        # margin_x/room_tbl_y) - the old absolute naming_y double-translated and
        # pushed this block off-canvas.
        naming_rows = [rr for rr in ir.room_schedule if rr.get("naming_threshold_used")]
        naming_rel_y = 29.0 + (_room_row_count * 10.5) + 8.0
        svg.append(f'  <g transform="translate(0, {naming_rel_y:.1f})">')
        thresholds_line = "ROOM CLASS THRESHOLDS (NAMING HONESTY): Master Suite >= 14.0m² incl. wardrobe zone | Master Bedroom >= 11.5m² | Bedroom >= 9.5m²"
        thresholds_max = int((svg_w - margin_x - 12.0) / (6.0 * 0.60))
        svg.append(f'    <text x="0" y="0" font-size="6.0" font-weight="700" fill="{text_secondary}">{html.escape(_ellipsize_str(thresholds_line, thresholds_max))}</text>')
        for n_idx, n_row in enumerate(naming_rows[:3]):
            ny = 10.0 + (n_idx * 9.0)
            n_label = f"{n_row.get('room_name', n_row.get('room_id', 'Room'))}: {n_row.get('naming_threshold_used', '')}"
            n_max = int((svg_w - margin_x - 12.0) / (5.5 * 0.60))
            svg.append(f'    <text x="0" y="{ny:.1f}" font-size="5.5" font-weight="500" fill="{text_dim}">{html.escape(_ellipsize_str(n_label, n_max))}</text>')
        svg.append('  </g>')
        svg.append('  </g>')

        # STAIR SCHEDULE TABLE (COMPUTED OBJECT PER NBC 2016 CL 12.18)
        # Right-aligned against the schedule panel with a minimum offset so the
        # first column always clears the ROOM SCHEDULE area on narrow plots.
        if _narrow_stack:
            stair_tbl_x = margin_x
            stair_tbl_y = room_tbl_y + _room_tbl_h + 60.0
        else:
            stair_tbl_x = max(margin_x + 200.0, win_tbl_x)
            stair_tbl_y = room_tbl_y
        svg.append(f'  <g transform="translate({stair_tbl_x}, {stair_tbl_y})">')
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">STAIR SCHEDULE (COMPUTED OBJECT)</text>')
        s_cols = [66.0, 64.0, 64.0]
        s_heads = ["SPECIFICATION", "VALUE", "STATUTORY CODE"]
        cx = 0.0
        for h_txt, cw in zip(s_heads, s_cols):
            svg.append(f'    <text x="{cx:.1f}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">{h_txt}</text>')
            cx += cw

        s_row = ir.stair_schedule[0] if ir.stair_schedule else {
            "flight_width_m": "1.00 m",
            "tread_depth_mm": "265 mm",
            "riser_height_mm": "166.7 mm",
            "risers_per_flight": "9 (Treads: 8)",
            "landing_dims": "2.15 x 1.00 m",
            "floor_to_floor": "3.00 m",
            "headroom": ">= 2.20 m",
            "handrail_side": "Inner Well (950mm)",
            "travel_dir": "UP",
        }
        stair_entries = [
            ("Flight / Landing", f"{s_row.get('flight_width_m', '1.00 m')} wide", "NBC Cl 12.18 >= 1.0m"),
            ("T / R", f"T={str(s_row.get('tread_depth_mm', '265')).replace(' mm', '')} R={str(s_row.get('riser_height_mm', '166.7')).replace(' mm', '')}", "T>=250mm, R<=190mm"),
            ("Risers/Flight", str(s_row.get('risers_per_flight', '9')), "<= 12/flight, Blondel"),
            ("Headroom", str(s_row.get('headroom', '>= 2.20 m')), "NBC Cl 12.18.3 >= 2.20m"),
            ("Rail / Dir", "Inner Well, UP", "Rail 950mm cont."),
        ]
        for r_idx, (p_name, p_val, p_code) in enumerate(stair_entries):
            ry_pos = 29.0 + (r_idx * 10.5)
            rcx = 0.0
            for val_txt, cw in zip([p_name, p_val, p_code], s_cols):
                svg.append(f'    <text x="{rcx:.1f}" y="{ry_pos:.1f}" font-size="6.0" font-weight="500" fill="{text_dim}">{html.escape(str(val_txt))}</text>')
                rcx += cw
        svg.append('  </g>')

        # LANDING DIMENSIONS ROW (kept inside stair table block width)
        svg.append(f'  <g transform="translate({stair_tbl_x}, {stair_tbl_y})">')
        svg.append(f'    <text x="0.0" y="82.5" font-size="5.5" font-weight="500" fill="{text_dim}">Landing: {s_row.get("landing_dims", "2.15 x 1.00 m")} | Floor-to-floor: {s_row.get("floor_to_floor", "3.00 m")}</text>')
        svg.append('  </g>')

        # UNIVERSAL VALIDATION GATE - LAYER TABLE (L1-L16)
        # Every generation shows the full per-layer status table: PASS/WARN/FAIL
        # chips and N/A-with-reason rows. Never hidden, never silently skipped.
        layer_rows = [ld for ld in getattr(ir.header, "layer_statuses", []) or [] if isinstance(ld, dict)]
        if layer_rows:
            # legend_lines / _panel_text_max_chars / WARN presence were planned
            # UPFRONT (before the annotations layer), so the graphic scale strip
            # can anchor below the legend's true end. Nothing is recomputed
            # here; lt_x/lt_y come from the table anchors built just above.
            lt_x = margin_x
            lt_y = ((stair_tbl_y + 112.0) if _narrow_stack
                    else (room_tbl_y + 113.0 + _room_tbl_h))
            status_fill = {"PASS": "#047857", "WARN": "#B45309", "FAIL": "#DC2626", "N/A": "#64748B"}
            svg.append(f'  <g transform="translate({lt_x}, {lt_y})">')
            svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">VALIDATION GATE - LAYERS L1-L16 (OVERALL: {html.escape(str(getattr(ir.header, "overall_layer_status", "PASS")))})</text>')
            lid_x, lst_x, lsum_x = 0.0, 26.0, 62.0
            svg.append(f'    <text x="{lid_x}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">LAYER</text>')
            svg.append(f'    <text x="{lst_x}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">STATUS</text>')
            svg.append(f'    <text x="{lsum_x}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">SUMMARY</text>')
            _summary_max = max(24, int((svg_w - margin_x - lsum_x - 12.0) / (6.0 * 0.60)))
            _gate_rows_shown = layer_rows[:16]
            _row_step = 10.0 if len(_gate_rows_shown) > 15 else 10.5
            for row_idx, ld in enumerate(_gate_rows_shown):
                ry_pos = 29.0 + (row_idx * _row_step)
                lid = str(ld.get("layer_id", "?"))
                lstat = str(ld.get("status", "PASS"))
                lsum = _ellipsize_str(str(ld.get("summary", "")), _summary_max)
                if lstat == "N/A":
                    lsum = _ellipsize_str(f"N/A: {ld.get('reason', 'not applicable')}", _summary_max)
                fill = status_fill.get(lstat, "#64748B")
                svg.append(f'    <text x="{lid_x}" y="{ry_pos:.1f}" font-size="6.0" font-weight="700" fill="{text_primary}">{html.escape(lid)}</text>')
                svg.append(f'    <rect x="{lst_x - 2.0}" y="{ry_pos - 6.0:.1f}" width="30.0" height="8.5" rx="2" fill="{fill}" opacity="0.85" />')
                svg.append(f'    <text x="{lst_x + 13.0}" y="{ry_pos:.1f}" font-size="5.8" font-weight="800" fill="#F8FAFC" text-anchor="middle">{html.escape(lstat)}</text>')
                svg.append(f'    <text x="{lsum_x}" y="{ry_pos:.1f}" font-size="6.0" font-weight="500" fill="{text_dim}">{html.escape(lsum)}</text>')
            warn_rows = [ld for ld in layer_rows if str(ld.get("status")) == "WARN"]
            if warn_rows:
                warn_y = 29.0 + (len(_gate_rows_shown) * _row_step) + 4.0
                warn_labels = "; ".join(f"{ld.get('layer_id')}: {_ellipsize_str((ld.get('findings') or ['advisory'])[0] if ld.get('findings') else 'advisory', 40)}" for ld in warn_rows[:3])
                svg.append(f'    <text x="0" y="{warn_y:.1f}" font-size="5.5" font-weight="600" fill="#F59E0B">WARN CHIPS: {html.escape(_ellipsize_str(warn_labels, _panel_text_max_chars))}</text>')
            legend_y = 29.0 + (len(_gate_rows_shown) * _row_step) + (16.0 if warn_rows else 4.0)
            for li, lline in enumerate(legend_lines):
                svg.append(f'    <text x="0" y="{legend_y + li * 9.0:.1f}" font-size="5.5" font-weight="500" fill="{text_dim}">{html.escape(lline)}</text>')
            svg.append('  </g>')
    else:
        # Site sheet: Vertex Coordinates Table and Survey Edge Bearings Table
        tbl_y = schedules_y + 54.0
        svg.append(f'  <g transform="translate({margin_x}, {tbl_y})">')
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">PLOT BOUNDARY VERTICES (SURVEY COORD SYSTEM)</text>')
        v_cols = [32.0, 56.0, 56.0]
        v_heads = ["VERTEX", "EASTING (X)", "NORTHING (Y)"]
        cx = 0.0
        for h_txt, cw in zip(v_heads, v_cols):
            svg.append(f'    <text x="{cx:.1f}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">{h_txt}</text>')
            cx += cw
        for r_idx, v_row in enumerate(getattr(ir, "vertex_table", [])[:8]):
            ry_pos = 29.0 + (r_idx * 10.5)
            rcx = 0.0
            for val_txt, cw in zip([v_row.get("id", ""), v_row.get("x", ""), v_row.get("y", "")], v_cols):
                svg.append(f'    <text x="{rcx:.1f}" y="{ry_pos:.1f}" font-size="6.0" font-weight="500" fill="{text_dim}">{html.escape(str(val_txt))}</text>')
                rcx += cw
        svg.append('  </g>')

        edge_tbl_x = margin_x + max(180.0, (content_w - 20.0) / 2.0) + 10.0
        svg.append(f'  <g transform="translate({edge_tbl_x}, {tbl_y})">')
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">BOUNDARY SURVEY EDGES &amp; BEARINGS</text>')
        e_cols = [48.0, 48.0, 76.0]
        e_heads = ["EDGE", "LENGTH", "BEARING"]
        cx = 0.0
        for h_txt, cw in zip(e_heads, e_cols):
            svg.append(f'    <text x="{cx:.1f}" y="19.0" font-size="6.0" font-weight="700" fill="{text_secondary}">{h_txt}</text>')
            cx += cw
        for r_idx, e_row in enumerate(getattr(ir, "edge_schedule", [])[:8]):
            ry_pos = 29.0 + (r_idx * 10.5)
            rcx = 0.0
            for val_txt, cw in zip([e_row.get("edge", ""), e_row.get("length", ""), e_row.get("bearing", "")], e_cols):
                svg.append(f'    <text x="{rcx:.1f}" y="{ry_pos:.1f}" font-size="6.0" font-weight="500" fill="{text_dim}">{html.escape(str(val_txt))}</text>')
                rcx += cw
        svg.append('  </g>')

        tax_y = schedules_y + 145.0
        svg.append(f'  <g transform="translate({margin_x}, {tax_y})">')
        svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">ANNOTATION STATUS TAXONOMY (DRAWING HONESTY SYSTEM)</text>')
        svg.append(f'    <rect x="0" y="15.0" width="58.0" height="11.0" rx="2" fill="#047857" opacity="0.25" />')
        svg.append(f'    <text x="4.0" y="23.5" font-size="6.0" font-weight="800" fill="#10B981">VERIFIED</text>')
        svg.append(f'    <text x="64.0" y="23.5" font-size="6.0" font-weight="500" fill="{text_secondary}">Mathematically verified: boundary perimeter sums, setting-out points, building lines</text>')
        svg.append(f'    <rect x="0" y="29.0" width="58.0" height="11.0" rx="2" fill="#0369A1" opacity="0.25" />')
        svg.append(f'    <text x="4.0" y="37.5" font-size="6.0" font-weight="800" fill="#0284C7">CALCULATED</text>')
        svg.append(f'    <text x="64.0" y="37.5" font-size="6.0" font-weight="500" fill="{text_secondary}">Procedurally computed: setbacks, buildable polygon, parking bays, room envelopes</text>')
        svg.append(f'    <rect x="0" y="43.0" width="58.0" height="11.0" rx="2" fill="#B45309" opacity="0.25" />')
        svg.append(f'    <text x="4.0" y="51.5" font-size="6.0" font-weight="800" fill="#F59E0B">ASSUMED</text>')
        svg.append(f'    <text x="64.0" y="51.5" font-size="6.0" font-weight="500" fill="{text_secondary}">Planning assumptions: road width (9.0m), sewer invert (-1.2m), neighbour bounds</text>')
        svg.append(f'    <rect x="0" y="57.0" width="58.0" height="11.0" rx="2" fill="#6D28D9" opacity="0.25" />')
        svg.append(f'    <text x="4.0" y="65.5" font-size="6.0" font-weight="800" fill="#8B5CF6">RECOMMENDED</text>')
        svg.append(f'    <text x="64.0" y="65.5" font-size="6.0" font-weight="500" fill="{text_secondary}">Advisory guidance: drainage slope (1:100), vehicular/pedestrian entry positions</text>')
        svg.append('  </g>')

        # SITE VALIDATION GATE LAYER TABLE (honest scope: site layers only;
        # building layers recorded N/A with explicit reasons).
        site_layer_rows = [ld for ld in getattr(ir.header, "layer_statuses", []) or [] if isinstance(ld, dict)]
        if site_layer_rows:
            slt_y = tax_y + 108.0
            sfill = {"PASS": "#047857", "WARN": "#B45309", "FAIL": "#DC2626", "N/A": "#64748B"}
            svg.append(f'  <g transform="translate({margin_x}, {slt_y})">')
            svg.append(f'    <text x="0" y="8.0" font-size="7.5" font-weight="700" fill="{text_primary}">VALIDATION GATE - LAYERS L1-L16 (SITE SCOPE, OVERALL: {html.escape(str(getattr(ir.header, "overall_layer_status", "PASS")))})</text>')
            sl_id_x, sl_st_x, sl_sum_x = 0.0, 26.0, 62.0
            _site_rows_shown = site_layer_rows[:16]
            _site_step = 10.0 if len(_site_rows_shown) > 15 else 10.5
            for row_idx, ld in enumerate(_site_rows_shown):
                ry_pos = 21.0 + (row_idx * _site_step)
                sl_lid = str(ld.get("layer_id", "?"))
                sl_stat = str(ld.get("status", "PASS"))
                sl_sum = _ellipsize_str(str(ld.get("summary", "")), 60)
                if sl_stat == "N/A":
                    sl_sum = _ellipsize_str(f"N/A: {ld.get('reason', 'not applicable')}", 60)
                sl_fill = sfill.get(sl_stat, "#64748B")
                svg.append(f'    <text x="{sl_id_x}" y="{ry_pos:.1f}" font-size="6.0" font-weight="700" fill="{text_primary}">{html.escape(sl_lid)}</text>')
                svg.append(f'    <rect x="{sl_st_x - 2.0}" y="{ry_pos - 6.0:.1f}" width="30.0" height="8.5" rx="2" fill="{sl_fill}" opacity="0.85" />')
                svg.append(f'    <text x="{sl_st_x + 13.0}" y="{ry_pos:.1f}" font-size="5.8" font-weight="800" fill="#F8FAFC" text-anchor="middle">{html.escape(sl_stat)}</text>')
                svg.append(f'    <text x="{sl_sum_x}" y="{ry_pos:.1f}" font-size="6.0" font-weight="500" fill="{text_dim}">{html.escape(sl_sum)}</text>')
            svg.append('  </g>')

    wm_x = svg_w - 14.0
    wm_y = svg_h - 8.0
    svg.append(f'  <text x="{wm_x:.1f}" y="{wm_y:.1f}" font-size="8.0" font-weight="600" fill="{text_dim}" text-anchor="end" letter-spacing="0.5">BUILDWISE GENERATIVE CAD ENGINE</text>')
    svg.append('  </g>')

    svg.append('</svg>')
    return "\n".join(svg)


# =============================================================================
# 4. BACKEND RENDERER 2: REPORTLAB VECTOR DRAWING (PDF DOSSIER & REPORT)
# =============================================================================

def render_reportlab_from_ir(
    ir: FloorDrawingIR,
    width: float = 493.23,
    height: float = 405.0
) -> Drawing:
    """
    Renders publication-grade ReportLab vector drawing exclusively from FloorDrawingIR.
    Directly maps Y-up IR coordinates to ReportLab Y-up points with a single uniform scale
    and origin per sheet. No Y-flip, no geometry re-interpretation, zero offset bugs.
    """
    if Drawing is None:
        raise RuntimeError("ReportLab is not installed or available.")

    # Content-aware viewport: derive metric bounds from the drawn primitives so
    # nothing (site road corridor, footing hints, banner lanes, vertex labels,
    # column-grid bubbles) is clipped by a hardcoded margin again.
    min_x_m = -2.10
    max_x_m = ir.envelope_w + 1.05
    min_y_m = -0.90
    max_y_m = ir.envelope_d + 2.30

    for p in ir.primitives:
        pts_ca: List[Tuple[float, float]] = []
        if isinstance(p, (PolygonPrimitive, PathPrimitive)):
            pts_ca = [(float(px_), float(py_)) for px_, py_ in (p.points or [])]
        elif isinstance(p, WallPrimitive):
            pts_ca = [(p.x1, p.y1), (p.x2, p.y2)]
        elif isinstance(p, DimensionChainPrimitive):
            pts_ca = [p.main_line[0], p.main_line[1]]
        elif isinstance(p, StairPrimitive):
            bx_ca, by_ca, bw_ca, bh_ca = p.boundary
            pts_ca = [(bx_ca, by_ca), (bx_ca + bw_ca, by_ca + bh_ca)]
        elif isinstance(p, TextPrimitive):
            hw_ca = ((p.halo_w_m if p.halo else 1.0) / 2.0) + 0.15
            hh_ca = ((p.halo_h_m if p.halo else 0.45) / 2.0) + 0.15
            min_x_m = min(min_x_m, p.x - hw_ca)
            max_x_m = max(max_x_m, p.x + hw_ca)
            min_y_m = min(min_y_m, p.y - hh_ca)
            max_y_m = max(max_y_m, p.y + hh_ca)
            continue
        for px_ca, py_ca in pts_ca:
            min_x_m = min(min_x_m, px_ca)
            max_x_m = max(max_x_m, px_ca)
            min_y_m = min(min_y_m, py_ca)
            max_y_m = max(max_y_m, py_ca)

    min_x_m -= 0.15
    min_y_m -= 0.15
    max_x_m += 0.15
    max_y_m += 0.15

    span_w_m = max_x_m - min_x_m
    span_d_m = max_y_m - min_y_m

    # Reserve fixed lanes for sheet furniture so overlays never sit on the plan:
    # top strip (freshness/status) + title badge, and one unified bottom band
    # (scale bar + taxonomy + wall-type legend).
    pad_pt = 12.0
    top_reserve = 50.0
    bot_reserve = 54.0
    avail_w = width - (2.0 * pad_pt)
    avail_h = height - top_reserve - bot_reserve

    scale_pt = min(avail_w / max(span_w_m, 1.0), avail_h / max(span_d_m, 1.0))
    scale_pt = max(14.0, min(36.0, scale_pt))

    total_drawn_w = span_w_m * scale_pt
    total_drawn_h = span_d_m * scale_pt
    origin_x = (width - total_drawn_w) / 2.0 - (min_x_m * scale_pt)
    origin_y = bot_reserve + (avail_h - total_drawn_h) / 2.0 - (min_y_m * scale_pt)

    def _fit_text(s: str, fs: float, max_w: float) -> str:
        """Right-clamps a string to max_w points at Helvetica ~0.55*fs per char."""
        if not s:
            return s
        if len(s) * fs * 0.55 <= max_w:
            return s
        keep = max(4, int(max_w / (fs * 0.55)) - 1)
        return s[:keep].rstrip(" ,;]") + ".."

    def x_pt(x_m: float) -> float:
        return origin_x + (x_m * scale_pt)

    def y_pt(y_m: float) -> float:
        return origin_y + (y_m * scale_pt)

    drawing = Drawing(width, height)

    drawing.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#FFFFFF"), strokeColor=colors.HexColor("#E5E5EA"), strokeWidth=0.5, rx=6, ry=6))
    drawing.add(Rect(x_pt(0.0), y_pt(0.0), ir.envelope_w * scale_pt, ir.envelope_d * scale_pt, fillColor=None, strokeColor=colors.HexColor("#CBD5E1"), strokeWidth=0.75, strokeDashArray=[3, 3]))

    # 0. Site & Irregular Polygon Layer (If present)
    for p in [prim for prim in ir.primitives if isinstance(prim, (PolygonPrimitive, PathPrimitive))]:
        if isinstance(p, PolygonPrimitive) and p.points:
            pts: List[float] = []
            for x, y in p.points:
                pts.extend([x_pt(x), y_pt(y)])
            col = None
            if p.hatch_pattern:
                if p.hatch_pattern in ("mf-hatch-wedge", "mf-hatch-footprint"):
                    col = colors.HexColor("#FEF3C7")
                else:
                    col = colors.HexColor("#F1F5F9")
            elif p.fill_color:
                col = colors.HexColor(p.fill_color) if p.fill_color.startswith("#") else colors.HexColor("#E0F2FE")
            strk = colors.HexColor(p.stroke_color) if p.stroke_color and p.stroke_color.startswith("#") else None
            strk_w = max(0.5, p.stroke_width_m * scale_pt) if p.stroke_width_m > 0 else (1.0 if strk else 0)
            drawing.add(Polygon(points=pts, fillColor=col, strokeColor=strk, strokeWidth=strk_w, strokeDashArray=p.dash_array))
        elif isinstance(p, PathPrimitive) and p.points:
            pts = []
            for x, y in p.points:
                pts.extend([x_pt(x), y_pt(y)])
            strk = colors.HexColor(p.stroke_color) if p.stroke_color and p.stroke_color.startswith("#") else colors.HexColor("#0F172A")
            strk_w = max(0.5, p.stroke_width_m * scale_pt) if p.stroke_width_m > 0 else 1.0
            drawing.add(PolyLine(points=pts, strokeColor=strk, strokeWidth=strk_w, strokeDashArray=p.dash_array))

    # 1. Fills Layer
    for f in ir.primitives_by_layer("fills"):
        if isinstance(f, FillPrimitive):
            fx = x_pt(f.x)
            fy = y_pt(f.y)
            fw = f.w * scale_pt
            fh = f.h * scale_pt
            col = colors.HexColor(f.fill_color) if f.fill_color.startswith("#") else colors.HexColor("#F8FAFC")
            drawing.add(Rect(fx, fy, fw, fh, fillColor=col, strokeColor=None, strokeWidth=0))

    # 2. Ghost Layer
    for g in ir.primitives_by_layer("ghost"):
        if isinstance(g, GhostPrimitive):
            for gx, gy, gw, gh in g.core_rects:
                drawing.add(Rect(x_pt(gx), y_pt(gy), gw * scale_pt, gh * scale_pt, fillColor=colors.HexColor("#FAF5FF"), strokeColor=colors.HexColor("#9333EA"), strokeWidth=1.2, strokeDashArray=[4, 3]))
            for tp1, tp2 in g.ghost_treads:
                drawing.add(Line(x_pt(tp1[0]), y_pt(tp1[1]), x_pt(tp2[0]), y_pt(tp2[1]), strokeColor=colors.HexColor("#9333EA"), strokeWidth=0.8, strokeDashArray=[2, 2]))
            if g.anchor_badge:
                ab = g.anchor_badge
                bx, by, bw, bh = ab["badge_x"], ab["badge_y"], ab["badge_w"], ab["badge_h"]
                lp1, lp2 = ab["leader_p1"], ab["leader_p2"]
                drawing.add(Line(x_pt(lp1[0]), y_pt(lp1[1]), x_pt(lp2[0]), y_pt(lp2[1]), strokeColor=colors.HexColor("#9333EA"), strokeWidth=0.8))
                _badge_txt_w = len("F0 CORE ANCHOR") * 6.0 * 0.60 + 8.0
                _badge_w_pt = max(bw * scale_pt, _badge_txt_w)
                _badge_h_pt = max(bh * scale_pt, 11.0)
                drawing.add(Rect(x_pt(bx), y_pt(by), _badge_w_pt, _badge_h_pt, rx=2, ry=2, fillColor=colors.HexColor("#7E22CE"), strokeColor=None))
                drawing.add(String(x_pt(bx) + _badge_w_pt / 2.0, y_pt(by) + _badge_h_pt / 2.0 - 2.5, "F0 CORE ANCHOR", textAnchor="middle", fontSize=6.0, fontName="Helvetica-Bold", fillColor=colors.white))
            for dsx, dsy, dsw, dsh in g.duct_shafts:
                drawing.add(Rect(x_pt(dsx), y_pt(dsy), dsw * scale_pt, dsh * scale_pt, fillColor=colors.HexColor("#FEF3C7"), strokeColor=colors.HexColor("#D97706"), strokeWidth=0.8, strokeDashArray=[2, 2]))
                drawing.add(Line(x_pt(dsx), y_pt(dsy), x_pt(dsx + dsw), y_pt(dsy + dsh), strokeColor=colors.HexColor("#D97706"), strokeWidth=0.6, strokeDashArray=[2, 2]))
                drawing.add(Line(x_pt(dsx + dsw), y_pt(dsy), x_pt(dsx), y_pt(dsy + dsh), strokeColor=colors.HexColor("#D97706"), strokeWidth=0.6, strokeDashArray=[2, 2]))

    # 3. Walls Layer
    for w in ir.primitives_by_layer("walls"):
        if isinstance(w, WallPrimitive):
            wx1 = x_pt(w.x1)
            wy1 = y_pt(w.y1)
            wx2 = x_pt(w.x2)
            wy2 = y_pt(w.y2)
            if w.wall_type == "W1":
                drawing.add(Line(wx1, wy1, wx2, wy2, strokeColor=colors.HexColor("#0F172A"), strokeWidth=2.4))
            elif w.wall_type == "W3":
                drawing.add(Line(wx1, wy1, wx2, wy2, strokeColor=colors.HexColor("#64748B"), strokeWidth=1.0, strokeDashArray=[2, 2]))
            elif w.wall_type == "W_PARAPET":
                # Double line for parapet
                dx = wx2 - wx1
                dy = wy2 - wy1
                length = math.hypot(dx, dy)
                if length > 0.1:
                    nx = -dy / length * 1.5
                    ny = dx / length * 1.5
                    drawing.add(Line(wx1 + nx, wy1 + ny, wx2 + nx, wy2 + ny, strokeColor=colors.HexColor("#334155"), strokeWidth=0.9))
                    drawing.add(Line(wx1 - nx, wy1 - ny, wx2 - nx, wy2 - ny, strokeColor=colors.HexColor("#334155"), strokeWidth=0.9))
                else:
                    drawing.add(Line(wx1, wy1, wx2, wy2, strokeColor=colors.HexColor("#334155"), strokeWidth=1.5))
            else:
                drawing.add(Line(wx1, wy1, wx2, wy2, strokeColor=colors.HexColor("#475569"), strokeWidth=1.4))

    # 4. Cores Layer (Staircase)
    for st in ir.primitives_by_layer("cores"):
        if isinstance(st, StairPrimitive):
            bx, by, bw, bh = st.boundary
            drawing.add(Rect(x_pt(bx), y_pt(by), bw * scale_pt, bh * scale_pt, fillColor=None, strokeColor=colors.HexColor("#D97706"), strokeWidth=1.8, strokeDashArray=[3, 2]))
            ll1, ll2 = st.landing_line
            drawing.add(Line(x_pt(ll1[0]), y_pt(ll1[1]), x_pt(ll2[0]), y_pt(ll2[1]), strokeColor=colors.HexColor("#D97706"), strokeWidth=1.4))
            dl1, dl2 = st.dividing_line
            drawing.add(Line(x_pt(dl1[0]), y_pt(dl1[1]), x_pt(dl2[0]), y_pt(dl2[1]), strokeColor=colors.HexColor("#D97706"), strokeWidth=1.2))
            for tp1, tp2 in st.treads:
                drawing.add(Line(x_pt(tp1[0]), y_pt(tp1[1]), x_pt(tp2[0]), y_pt(tp2[1]), strokeColor=colors.HexColor("#CBD5E1"), strokeWidth=0.75))
            up1, up2 = st.up_line
            drawing.add(Line(x_pt(up1[0]), y_pt(up1[1]), x_pt(up2[0]), y_pt(up2[1]), strokeColor=colors.HexColor("#6366F1"), strokeWidth=1.2))
            pts_up = []
            for p in st.up_tip:
                pts_up.extend([x_pt(p[0]), y_pt(p[1])])
            drawing.add(Polygon(pts_up, fillColor=colors.HexColor("#6366F1"), strokeColor=None))
            drawing.add(String(x_pt(st.up_text_pos[0]), y_pt(st.up_text_pos[1]), "UP", fontSize=6.0, fontName="Helvetica-Bold", fillColor=colors.HexColor("#4F46E5"), textAnchor="middle"))
            if st.dn_line and st.dn_tip and st.dn_text_pos:
                dn1, dn2 = st.dn_line
                drawing.add(Line(x_pt(dn1[0]), y_pt(dn1[1]), x_pt(dn2[0]), y_pt(dn2[1]), strokeColor=colors.HexColor("#6366F1"), strokeWidth=1.2))
                pts_dn = []
                for p in st.dn_tip:
                    pts_dn.extend([x_pt(p[0]), y_pt(p[1])])
                drawing.add(Polygon(pts_dn, fillColor=colors.HexColor("#6366F1"), strokeColor=None))
                drawing.add(String(x_pt(st.dn_text_pos[0]), y_pt(st.dn_text_pos[1]), "DN", fontSize=6.0, fontName="Helvetica-Bold", fillColor=colors.HexColor("#4F46E5"), textAnchor="middle"))
            hrx, hry = st.headroom_text_pos
            drawing.add(String(x_pt(hrx), y_pt(hry) - 2.5, st.headroom_text, fontSize=5.5, fontName="Helvetica-Bold", fillColor=colors.HexColor("#D97706"), textAnchor="middle"))

    # 5. Openings Layer (Doors & Windows)
    for op in ir.primitives_by_layer("openings"):
        if isinstance(op, OpeningPrimitive):
            if op.opening_type == "door":
                for jp1, jp2 in op.door_jambs:
                    drawing.add(Line(x_pt(jp1[0]), y_pt(jp1[1]), x_pt(jp2[0]), y_pt(jp2[1]), strokeColor=colors.HexColor("#0284C7"), strokeWidth=1.5))
                drawing.add(Line(x_pt(op.hinge_x), y_pt(op.hinge_y), x_pt(op.leaf_x), y_pt(op.leaf_y), strokeColor=colors.HexColor("#0284C7"), strokeWidth=1.6))
                arc = ArcPath(strokeColor=colors.HexColor("#0284C7"), strokeWidth=0.8, strokeDashArray=[2, 2], fillColor=None)
                arc.addArc(x_pt(op.arc_center_x), y_pt(op.arc_center_y), op.arc_radius_m * scale_pt, op.arc_start_deg, op.arc_end_deg)
                drawing.add(arc)
                drawing.add(Rect(x_pt(op.tag_x) - 7.5, y_pt(op.tag_y) - 5.5, 15.0, 11.0, rx=2, ry=2, fillColor=colors.HexColor("#FFFFFF"), strokeColor=colors.HexColor("#0284C7"), strokeWidth=0.8))
                drawing.add(String(x_pt(op.tag_x), y_pt(op.tag_y) - 2.0, op.tag, textAnchor="middle", fontSize=6.0, fontName="Helvetica-Bold", fillColor=colors.HexColor("#0284C7")))
                if op.unit_badge:
                    ub = op.unit_badge
                    ub_w_pt = 38.0
                    ub_h_pt = 13.0
                    ub_x_pt = x_pt(op.hinge_x) + 4.0
                    ub_y_pt = y_pt(op.hinge_y) + 4.0
                    # Same room-corner anchor as the SVG sheet, so the vector
                    # PDF does not print the chip on the door tag or the stair
                    # "UP" letter.
                    _rect_ir = ub.get("rect") if isinstance(ub, dict) else None
                    if _rect_ir and float(_rect_ir[2]) > 0.20 and float(_rect_ir[3]) > 0.20:
                        _rx, _ry, _rw, _rd = (float(v) for v in _rect_ir)
                        _left = x_pt(_rx)
                        _right = x_pt(_rx + _rw)
                        _bottom = y_pt(_ry)
                        _top = y_pt(_ry + _rd)
                        _corners = [
                            (_left + 2.0, _top - ub_h_pt - 2.0),
                            (_right - ub_w_pt - 2.0, _top - ub_h_pt - 2.0),
                            (_left + 2.0, _bottom + 2.0),
                            (_right - ub_w_pt - 2.0, _bottom + 2.0),
                        ]
                        _corners.sort(
                            key=lambda c: (c[0] - x_pt(op.hinge_x)) ** 2
                            + (c[1] - y_pt(op.hinge_y)) ** 2
                        )
                        ub_x_pt, ub_y_pt = _corners[0]

                        def _clamp_pt(v: float, lo: float, hi: float) -> float:
                            return lo if hi < lo else min(max(v, lo), hi)

                        ub_x_pt = _clamp_pt(ub_x_pt, _left + 2.0, _right - ub_w_pt - 2.0)
                        ub_y_pt = _clamp_pt(ub_y_pt, _bottom + 2.0, _top - ub_h_pt - 2.0)
                    drawing.add(Rect(ub_x_pt, ub_y_pt, ub_w_pt, ub_h_pt, rx=2, ry=2, fillColor=colors.HexColor("#FEF3C7"), strokeColor=colors.HexColor("#D97706"), strokeWidth=0.8))
                    drawing.add(String(ub_x_pt + ub_w_pt / 2.0, ub_y_pt + 3.0, ub["tag"], textAnchor="middle", fontSize=7.0, fontName="Helvetica-Bold", fillColor=colors.HexColor("#D97706")))
            elif op.opening_type == "window":
                if op.outer_line and op.glass_line and op.inner_line:
                    op1, op2 = op.outer_line
                    gp1, gp2 = op.glass_line
                    ip1, ip2 = op.inner_line
                    drawing.add(Line(x_pt(op1[0]), y_pt(op1[1]), x_pt(op2[0]), y_pt(op2[1]), strokeColor=colors.HexColor("#0284C7"), strokeWidth=1.2))
                    drawing.add(Line(x_pt(gp1[0]), y_pt(gp1[1]), x_pt(gp2[0]), y_pt(gp2[1]), strokeColor=colors.HexColor("#0F172A"), strokeWidth=0.8))
                    drawing.add(Line(x_pt(ip1[0]), y_pt(ip1[1]), x_pt(ip2[0]), y_pt(ip2[1]), strokeColor=colors.HexColor("#0284C7"), strokeWidth=1.2))
                    for jp1, jp2 in op.window_jambs:
                        drawing.add(Line(x_pt(jp1[0]), y_pt(jp1[1]), x_pt(jp2[0]), y_pt(jp2[1]), strokeColor=colors.HexColor("#0F172A"), strokeWidth=0.8))
                drawing.add(Rect(x_pt(op.tag_x) - 7.5, y_pt(op.tag_y) - 5.5, 15.0, 11.0, rx=2, ry=2, fillColor=colors.HexColor("#FFFFFF"), strokeColor=colors.HexColor("#0369A1"), strokeWidth=0.8))
                drawing.add(String(x_pt(op.tag_x), y_pt(op.tag_y) - 2.0, op.tag, textAnchor="middle", fontSize=6.0, fontName="Helvetica-Bold", fillColor=colors.HexColor("#0369A1")))

    # 6. Text & Typography Layer
    # 6. Text & Typography Layer
    for t in ir.primitives_by_layer("text"):
        if isinstance(t, TextPrimitive):
            tx = x_pt(t.x)
            ty = y_pt(t.y)
            if t.room_tag_circle:
                rad_pt = t.room_tag_circle.get("radius_pt", 7.5)
                tag_num = t.room_tag_circle.get("room_idx", 1)
                drawing.add(Circle(tx, ty, rad_pt, fillColor=colors.HexColor("#F1F5F9"), strokeColor=colors.HexColor("#0284C7"), strokeWidth=1.0))
                drawing.add(String(tx, ty - 2.5, str(tag_num), textAnchor="middle", fontSize=7.0, fontName="Helvetica-Bold", fillColor=colors.HexColor("#0F172A")))
            else:
                lines = t.lines if t.lines else [t.text]
                # Typography scales with the sheet so the collision-resolved
                # px-space layout (36px/m) reproduces exactly at scale_pt/m.
                # A 5pt floor keeps small-scale site labels legible.
                _ratio = scale_pt / 36.0
                fs = max(t.font_size_pt * _ratio, min(t.font_size_pt, 5.0))
                sub_fs = max(t.subtext_pt * _ratio, min(t.subtext_pt, 4.5))
                total_h_pt = len(lines) * fs * 1.25 + (sub_fs * 1.25 + 3.0 if t.subtext else 0.0)
                top_y_pt = ty + total_h_pt / 2.0

                if t.halo:
                    # Halo must cover the REAL rendered text block, not just the
                    # declared metric hint - prevents pill-vs-text overflow.
                    _tw_pt = max([len(l) * fs * 0.55 for l in lines] + [len(t.subtext) * sub_fs * 0.55 if t.subtext else 0.0])
                    hw = max(t.halo_w_m * scale_pt, _tw_pt + 8.0)
                    hh = max(t.halo_h_m * scale_pt, total_h_pt + 4.0)
                    drawing.add(Rect(tx - hw / 2.0, ty - hh / 2.0, hw, hh, rx=3, ry=3, fillColor=colors.Color(1, 1, 1, alpha=0.92), strokeColor=colors.Color(0, 0, 0, alpha=0.08), strokeWidth=0.5))

                curr_y = top_y_pt - fs * 0.85
                for line in lines:
                    drawing.add(String(tx, curr_y, line, textAnchor="middle", fontSize=fs, fontName="Helvetica-Bold", fillColor=colors.HexColor(t.color)))
                    curr_y -= fs * 1.25
                if t.subtext:
                    curr_y -= 2.0
                    drawing.add(String(tx, curr_y, t.subtext, textAnchor="middle", fontSize=sub_fs, fontName="Helvetica", fillColor=colors.HexColor(t.subtext_color)))

    # 7. Dimension Chains Layer
    def draw_slash_tick_rl(tx: float, ty: float):
        drawing.add(Line(tx - 3.0, ty - 3.0, tx + 3.0, ty + 3.0, strokeColor=colors.HexColor("#0F172A"), strokeWidth=1.4))

    for dc in ir.primitives_by_layer("dims"):
        if isinstance(dc, DimensionChainPrimitive):
            p1, p2 = dc.main_line
            drawing.add(Line(x_pt(p1[0]), y_pt(p1[1]), x_pt(p2[0]), y_pt(p2[1]), strokeColor=colors.HexColor("#334155"), strokeWidth=0.9))
            for tk in dc.ticks:
                draw_slash_tick_rl(x_pt(tk[0]), y_pt(tk[1]))
            for wp1, wp2 in dc.witness_lines:
                drawing.add(Line(x_pt(wp1[0]), y_pt(wp1[1]), x_pt(wp2[0]), y_pt(wp2[1]), strokeColor=colors.HexColor("#94A3B8"), strokeWidth=0.5, strokeDashArray=[2, 2]))
            for seg in dc.segments:
                lbl_x = x_pt(seg["center_x"])
                lbl_y = y_pt(seg["center_y"])
                lbl_txt = seg["label"]
                fs = seg.get("font_size_pt", 7.0)
                # Vertical chains read bottom-to-top on the SVG sheet. The PDF
                # renderer used horizontal text for them, so the overall and
                # clear-chain labels piled into one unreadable run at the left
                # edge. Rotate the String, preserving the same anchor point.
                label = String(0, 0, lbl_txt, textAnchor="middle", fontSize=fs, fontName="Helvetica-Bold", fillColor=colors.HexColor("#0F172A"))
                if seg.get("is_vertical"):
                    group = Group(label)
                    group.translate(lbl_x, lbl_y)
                    group.rotate(90)
                    drawing.add(group)
                else:
                    label.x = lbl_x
                    label.y = lbl_y
                    drawing.add(label)

    # 8. Annotations Layer
    for annot in ir.primitives_by_layer("annotations"):
        if isinstance(annot, AnnotationPrimitive):
            # Compass sits left of the top-right title badge, inside the reserved
            # top strip (never over the plan).
            compass_x = width - 40.0
            compass_y = height - 66.0
            drawing.add(Circle(compass_x, compass_y, 14, fillColor=colors.HexColor("#F8FAFC"), strokeColor=colors.HexColor("#0F172A"), strokeWidth=1.0))
            drawing.add(Polygon([compass_x, compass_y + 11, compass_x + 4, compass_y, compass_x, compass_y + 2, compass_x - 4, compass_y], fillColor=colors.HexColor("#0F172A"), strokeColor=None))
            drawing.add(Polygon([compass_x, compass_y - 11, compass_x + 4, compass_y, compass_x, compass_y - 2, compass_x - 4, compass_y], fillColor=colors.HexColor("#94A3B8"), strokeColor=None))
            drawing.add(String(compass_x, compass_y + 14, "N", fontName="Helvetica-Bold", fontSize=8.0, textAnchor="middle", fillColor=colors.HexColor("#0F172A")))

            # Graphic scale now renders exclusively inside the unified bottom
            # band (cell 3); the legacy free-floating bar drew underneath the
            # wall-types cell and was removed.

            for stag in annot.structural_tags:
                if "tag" in stag:
                    drawing.add(String(x_pt(stag["x"]), y_pt(stag["y"]), stag["tag"], fontName="Helvetica-Bold", fontSize=6.5, fillColor=colors.HexColor("#0284C7")))
                elif "bubble" in stag:
                    bx, by = x_pt(stag["x"]), y_pt(stag["y"])
                    drawing.add(Circle(bx, by, 6.5, fillColor=colors.white, strokeColor=colors.HexColor("#0284C7"), strokeWidth=1.0))
                    drawing.add(String(bx, by - 2.5, stag["bubble"], fontName="Helvetica-Bold", fontSize=6.5, textAnchor="middle", fillColor=colors.HexColor("#0F172A")))

            # Title Block Banner & Freshness Verification Token
            # Anchored top-right so it can never cover the plan interior.
            badge_w = 250.0
            badge_h = 42.0
            badge_x = width - badge_w - 12.0
            badge_y = height - badge_h - 12.0
            drawing.add(Rect(badge_x, badge_y, badge_w, badge_h, rx=4, ry=4, fillColor=colors.Color(1, 1, 1, alpha=0.96), strokeColor=colors.HexColor("#CBD5E1"), strokeWidth=0.75))
            drawing.add(String(badge_x + 8.0, badge_y + 28.0, _fit_text(f"{ir.header.floor_name.upper()} (+{ir.header.elevation_m:.2f}m LVL)", 8.0, badge_w - 16.0), fontName="Helvetica-Bold", fontSize=8.0, fillColor=colors.HexColor("#0F172A")))
            drawing.add(String(badge_x + 8.0, badge_y + 17.0, _fit_text(ir.header.freshness_token, 5.0, badge_w - 16.0), fontName="Helvetica", fontSize=5.0, fillColor=colors.HexColor("#0284C7")))
            # Stamp must fit the badge at 5pt Helvetica (~2.9pt/char):
            # ellipsize the layer list middle but ALWAYS keep the legal tail.
            _stamp_full = ir.drawing_status_stamp
            if len(_stamp_full) > 80:
                _tail = " - NOT FOR CONSTRUCTION"
                _stamp_badge = _stamp_full[:80 - len(_tail) - 2].rstrip(" ,]") + ".." + _tail
            else:
                _stamp_badge = _stamp_full
            drawing.add(String(badge_x + 8.0, badge_y + 6.0, _stamp_badge, fontName="Helvetica-Bold", fontSize=5.0, fillColor=colors.HexColor("#DC2626")))

            # Drawing Header Top Freshness Verification Line (width-clamped so it
            # can never run off-sheet or through the compass/badge).
            drawing.add(String(12.0, height - 5.0, _fit_text(f"{ir.header.freshness_token} | {ir.drawing_status_stamp}", 5.5, width - 24.0), fontName="Helvetica-Bold", fontSize=5.5, fillColor=colors.HexColor("#DC2626")))

            # Unified bottom reference band: wall types + taxonomy + graphic scale
            # in ONE reserved lane (never overlaps the plan or the title badge).
            band_x = 12.0
            band_w = width - 24.0
            band_h = 44.0
            band_y = 6.0
            drawing.add(Rect(band_x, band_y, band_w, band_h, rx=4, ry=4, fillColor=colors.Color(1, 1, 1, alpha=0.96), strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=0.5))
            # Cell 1: Wall types
            drawing.add(String(band_x + 6.0, band_y + 30.0, "WALL TYPES (NBC 2016):", fontName="Helvetica-Bold", fontSize=5.5, fillColor=colors.HexColor("#334155")))
            drawing.add(Line(band_x + 6.0, band_y + 21.0, band_x + 20.0, band_y + 21.0, strokeColor=colors.HexColor("#0F172A"), strokeWidth=2.2))
            drawing.add(String(band_x + 23.0, band_y + 19.5, "W1: 230mm Ext.", fontName="Helvetica", fontSize=5.0, fillColor=colors.HexColor("#475569")))
            drawing.add(Line(band_x + 6.0, band_y + 10.0, band_x + 20.0, band_y + 10.0, strokeColor=colors.HexColor("#475569"), strokeWidth=1.3))
            drawing.add(String(band_x + 23.0, band_y + 8.5, "W2: 115mm / W3: 75mm", fontName="Helvetica", fontSize=5.0, fillColor=colors.HexColor("#475569")))
            # Cell 2: Annotation taxonomy
            cell2_x = band_x + 118.0
            drawing.add(Line(cell2_x, band_y + 4.0, cell2_x, band_y + band_h - 4.0, strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=0.5))
            drawing.add(String(cell2_x + 6.0, band_y + 30.0, "ANNOTATION TAXONOMY:", fontName="Helvetica-Bold", fontSize=5.5, fillColor=colors.HexColor("#0F172A")))
            drawing.add(String(cell2_x + 6.0, band_y + 21.0, "[VERIFIED] Boundary & chains", fontName="Helvetica", fontSize=4.8, fillColor=colors.HexColor("#475569")))
            drawing.add(String(cell2_x + 6.0, band_y + 14.0, "[CALCULATED] Setbacks & rooms", fontName="Helvetica", fontSize=4.8, fillColor=colors.HexColor("#475569")))
            drawing.add(String(cell2_x + 6.0, band_y + 7.0, "[ASSUMED] Road & sewer | [RECOMMENDED] Slope 1:100", fontName="Helvetica", fontSize=4.8, fillColor=colors.HexColor("#475569")))
            # Cell 3: Graphic scale
            cell3_x = band_x + band_w - 118.0
            drawing.add(Line(cell3_x, band_y + 4.0, cell3_x, band_y + band_h - 4.0, strokeColor=colors.HexColor("#E2E8F0"), strokeWidth=0.5))
            drawing.add(String(cell3_x + 6.0, band_y + 30.0, "GRAPHIC SCALE (METRIC)", fontName="Helvetica-Bold", fontSize=5.5, fillColor=colors.HexColor("#64748B")))
            meter_w_pt = 1.0 * scale_pt
            meter_w_pt = min(meter_w_pt, 22.0)
            sb_x = cell3_x + 6.0
            sb_y = band_y + 14.0
            for i in range(4):
                bx = sb_x + (i * meter_w_pt)
                bcol = colors.HexColor("#0F172A") if i % 2 == 0 else colors.HexColor("#E2E8F0")
                drawing.add(Rect(bx, sb_y, meter_w_pt, 4, fillColor=bcol, strokeColor=colors.HexColor("#0F172A"), strokeWidth=0.5))
                drawing.add(String(bx, sb_y - 7, f"{i}m" if i > 0 else "0", fontName="Helvetica", fontSize=5.5, textAnchor="middle", fillColor=colors.HexColor("#64748B")))
            drawing.add(String(sb_x + 4 * meter_w_pt, sb_y - 7, "4m", fontName="Helvetica", fontSize=5.5, textAnchor="middle", fillColor=colors.HexColor("#64748B")))

    return drawing


# =============================================================================
# 5. SITE PLAN DRAWING IR BUILDER (SHEET 10.SP / SITE SURVEY)
# =============================================================================

# Site-plan fields that carry geometry, rebased by _rebase_site_geometry below.
_SITE_PAIR_KEYS = frozenset({
    "vertices", "buildable_polygon_coords", "building_line_coords", "polygon_coords",
    "corner_vertices", "centroid", "drive_aisle_polygon",
})
_SITE_X_KEYS = frozenset({"x", "x_m", "center_x", "cx", "hinge_x", "minx"})
_SITE_Y_KEYS = frozenset({"y", "y_m", "center_y", "cy", "hinge_y", "miny"})


def _is_pair(val: Any) -> bool:
    return (
        isinstance(val, (list, tuple))
        and len(val) == 2
        and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in val)
    )


def _rebase_site_geometry(node: Any, dx: float, dy: float) -> Any:
    """Translate every coordinate of a dumped site plan by (dx, dy).

    A captured boundary is pin-centred, so its local coordinates can be negative
    (plot bbox minx/miny < 0) while the site sheet's layout math - road corridor,
    edge callouts, label lanes - is authored for a plot whose south-west corner is
    the origin. Rebasing the geometry onto that corner puts drawing and layout in
    one frame. No rounding is applied, so an exact (0, 0) offset is a no-op.
    """
    if isinstance(node, dict):
        out: Dict[str, Any] = {}
        for key, val in node.items():
            if key in _SITE_PAIR_KEYS and isinstance(val, (list, tuple)):
                if _is_pair(val):
                    out[key] = (float(val[0]) + dx, float(val[1]) + dy)
                else:
                    out[key] = [
                        (float(p[0]) + dx, float(p[1]) + dy) if _is_pair(p) else _rebase_site_geometry(p, dx, dy)
                        for p in val
                    ]
            elif key == "bounding_box" and isinstance(val, (list, tuple)) and len(val) == 4:
                out[key] = (float(val[0]) + dx, float(val[1]) + dy, float(val[2]) + dx, float(val[3]) + dy)
            elif key in _SITE_X_KEYS and isinstance(val, (int, float)) and not isinstance(val, bool):
                out[key] = float(val) + dx
            elif key in _SITE_Y_KEYS and isinstance(val, (int, float)) and not isinstance(val, bool):
                out[key] = float(val) + dy
            else:
                out[key] = _rebase_site_geometry(val, dx, dy)
        return out
    if isinstance(node, list):
        return [_rebase_site_geometry(v, dx, dy) for v in node]
    return node


def build_site_drawing_ir(
    site_plan: Any,
    gen_id: str = "GEN-SITE-01",
    typology: str = "T1_SINGLE_FAMILY"
) -> FloorDrawingIR:
    """
    Constructs a dedicated FloorDrawingIR for the Site Plan Sheet (Sheet 10.SP / 10.0),
    including:
    - Outer polygon boundary with solid stroke
    - Dashed buildable setback outline
    - Hatched setback band (buffer difference)
    - Rotated footprint boundary with orientation angle note
    - Outdoor zone fragments with areas
    - Per-edge survey dimensions (length and bearing)
    - Vertex coordinate markers P1..Pn
    - North arrow and metric graphic scale
    """
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    # Rebase FIRST: everything below (both the drawing and the layout math) must
    # read the plot's south-west corner as the origin.
    _plot_probe = _get(site_plan, "plot_polygon", {}) or {}
    _probe_bbox = _get(_plot_probe, "bounding_box", None)
    if isinstance(_probe_bbox, (list, tuple)) and len(_probe_bbox) == 4:
        _base_x, _base_y = float(_probe_bbox[0]), float(_probe_bbox[1])
    else:
        _probe_verts = _get(_plot_probe, "vertices", []) or []
        _base_x = min((float(p[0]) for p in _probe_verts), default=0.0)
        _base_y = min((float(p[1]) for p in _probe_verts), default=0.0)
    if _base_x or _base_y:
        _dumped = site_plan.model_dump() if hasattr(site_plan, "model_dump") else site_plan
        if isinstance(_dumped, dict):
            site_plan = _rebase_site_geometry(_dumped, -_base_x, -_base_y)

    plot_poly = _get(site_plan, "plot_polygon", {})
    vertices = _get(plot_poly, "vertices", []) or []
    buildable_coords = _get(site_plan, "buildable_polygon_coords", []) or []
    building_line_coords = _get(site_plan, "building_line_coords", []) or []
    setback_dimensions = _get(site_plan, "setback_dimensions", {}) or {}
    parking = _get(site_plan, "parking", None)
    footprint = _get(site_plan, "footprint", {}) or {}
    outdoor_zones = _get(site_plan, "outdoor_zones", []) or []
    wedge_zones = _get(site_plan, "wedge_zones", []) or []
    edges = _get(site_plan, "edges", []) or []
    vertex_table = _get(site_plan, "vertex_table", []) or []

    nominal_setback = float(_get(site_plan, "nominal_setback_m", 1.5))
    sb_front = float(setback_dimensions.get("front", nominal_setback))
    sb_rear = float(setback_dimensions.get("rear", nominal_setback))
    sb_s1 = float(setback_dimensions.get("side1", setback_dimensions.get("side", nominal_setback)))
    sb_s2 = float(setback_dimensions.get("side2", setback_dimensions.get("side", nominal_setback)))

    bounds = _get(plot_poly, "bounding_box", (0.0, 0.0, 10.0, 10.0))
    minx, miny, maxx, maxy = bounds
    bbox_w = max(float(maxx - minx), 10.0)
    bbox_d = max(float(maxy - miny), 10.0)

    primitives: List[DrawingPrimitive] = []

    # 0. Road Corridor (ASSUMED)
    primitives.append(PathPrimitive(
        points=[(-1.0, -1.0), (bbox_w + 1.0, -1.0)],
        stroke_color="#64748B",
        stroke_width_m=0.25,
        dash_array=[4, 4],
        layer="fills",
        status="ASSUMED"
    ))

    # 1. Fills: Setback band, buildable polygon, building line, outdoor fragments, wedge zones, and footprint
    if vertices:
        primitives.append(PolygonPrimitive(
            points=[(float(pt[0]), float(pt[1])) for pt in vertices],
            fill_color="#F1F5F9",
            hatch_pattern="mf-hatch-setback",
            stroke_color="#475569",
            stroke_width_m=0.25,
            is_setback=True,
            layer="fills"
        ))

    if buildable_coords:
        primitives.append(PolygonPrimitive(
            points=[(float(pt[0]), float(pt[1])) for pt in buildable_coords],
            fill_color="#FFFFFF",
            fill_opacity=0.90,
            stroke_color="#0284C7",
            stroke_width_m=0.20,
            dash_array=[4, 3],
            is_boundary=True,
            layer="fills"
        ))

    if building_line_coords:
        primitives.append(PolygonPrimitive(
            points=[(float(pt[0]), float(pt[1])) for pt in building_line_coords],
            stroke_color="#DC2626",
            stroke_width_m=0.20,
            dash_array=[5, 3],
            label="Building Line",
            is_boundary=True,
            layer="fills",
            status="CALCULATED"
        ))

    for frag in outdoor_zones:
        fcoords = _get(frag, "polygon_coords", [])
        if fcoords:
            primitives.append(PolygonPrimitive(
                points=[(float(pt[0]), float(pt[1])) for pt in fcoords],
                fill_color="#E0F2FE",
                fill_opacity=0.45,
                stroke_color="#38BDF8",
                stroke_width_m=0.15,
                layer="fills"
            ))

    for wz in wedge_zones:
        wcoords = _get(wz, "polygon_coords", [])
        if wcoords:
            primitives.append(PolygonPrimitive(
                points=[(float(pt[0]), float(pt[1])) for pt in wcoords],
                fill_color="#FEF3C7",
                fill_opacity=0.70,
                stroke_color="#D97706",
                stroke_width_m=0.22,
                dash_array=[3, 2],
                hatch_pattern="mf-hatch-wedge",
                layer="fills"
            ))

    wings = _get(footprint, "wings", []) or []
    corridors = _get(footprint, "corridors", []) or []
    courtyard_void = _get(footprint, "courtyard_void", None)

    if len(wings) > 1:
        # Multi-wing / L-shape rendering
        for w_idx, wing in enumerate(wings, start=1):
            w_pts = _get(wing, "corner_vertices", [])
            if w_pts:
                primitives.append(PolygonPrimitive(
                    points=[(float(pt[0]), float(pt[1])) for pt in w_pts],
                    fill_color="#FEF3C7",
                    fill_opacity=0.65,
                    stroke_color="#D97706",
                    stroke_width_m=0.35,
                    hatch_pattern="mf-hatch-footprint",
                    is_footprint=True,
                    layer="fills"
                ))
                nw_c = len(w_pts)
                for k in range(nw_c):
                    c1 = w_pts[k]
                    c2 = w_pts[(k + 1) % nw_c]
                    primitives.append(WallPrimitive(
                        wall_id=f"{_get(wing, 'wing_id', f'W{w_idx}')}_W_{k + 1}",
                        wall_type="W1",
                        x1=float(c1[0]),
                        y1=float(c1[1]),
                        x2=float(c2[0]),
                        y2=float(c2[1]),
                        thickness_m=0.30,
                        is_exterior=True,
                        layer="walls"
                    ))
        for c_idx, corr in enumerate(corridors, start=1):
            c_pts = _get(corr, "polygon_coords", [])
            if c_pts:
                primitives.append(PolygonPrimitive(
                    points=[(float(pt[0]), float(pt[1])) for pt in c_pts],
                    fill_color="#FEF3C7",
                    fill_opacity=0.45,
                    stroke_color="#D97706",
                    stroke_width_m=0.25,
                    is_footprint=True,
                    layer="fills"
                ))
    else:
        # Legacy single rectangle path
        corner_verts = _get(footprint, "corner_vertices", [])
        if not corner_verts and footprint:
            fx = float(_get(footprint, "x", 0.0))
            fy = float(_get(footprint, "y", 0.0))
            fw = float(_get(footprint, "width_m", 10.0))
            fd = float(_get(footprint, "depth_m", 10.0))
            corner_verts = [(fx, fy), (fx + fw, fy), (fx + fw, fy + fd), (fx, fy + fd)]

        if corner_verts:
            primitives.append(PolygonPrimitive(
                points=[(float(pt[0]), float(pt[1])) for pt in corner_verts],
                fill_color="#FEF3C7",
                fill_opacity=0.60,
                stroke_color="#D97706",
                stroke_width_m=0.35,
                is_footprint=True,
                layer="fills"
            ))
            n_c = len(corner_verts)
            for k in range(n_c):
                c1 = corner_verts[k]
                c2 = corner_verts[(k + 1) % n_c]
                primitives.append(WallPrimitive(
                    wall_id=f"FP_W_{k + 1}",
                    wall_type="W1",
                    x1=float(c1[0]),
                    y1=float(c1[1]),
                    x2=float(c2[0]),
                    y2=float(c2[1]),
                    thickness_m=0.30,
                    is_exterior=True,
                    layer="walls"
                ))

    # 2. Walls: Boundary survey edges
    n_v = len(vertices)
    for e in edges:
        idx = int(_get(e, "edge_index", 1)) - 1
        p1 = vertices[idx % n_v]
        p2 = vertices[(idx + 1) % n_v]
        primitives.append(WallPrimitive(
            wall_id=f"BND_{idx + 1}",
            wall_type="W1",
            x1=float(p1[0]),
            y1=float(p1[1]),
            x2=float(p2[0]),
            y2=float(p2[1]),
            thickness_m=0.25,
            is_exterior=True,
            layer="walls"
        ))

    # 3. Dims & Text: Edge labels (length + bearing) & vertex markers
    # Edge labels sit OUTSIDE the boundary so they never collide with the
    # setback band, parking aisle, or building-line annotation lanes.
    cen_x = sum(float(v[0]) for v in vertices) / max(n_v, 1)
    cen_y = sum(float(v[1]) for v in vertices) / max(n_v, 1)
    for e in edges:
        idx = int(_get(e, "edge_index", 1)) - 1
        p1 = vertices[idx % n_v]
        p2 = vertices[(idx + 1) % n_v]
        mx = (float(p1[0]) + float(p2[0])) / 2.0
        my = (float(p1[1]) + float(p2[1])) / 2.0
        dx = float(p2[0]) - float(p1[0])
        dy = float(p2[1]) - float(p1[1])
        L = math.hypot(dx, dy)
        if L > 0:
            nx = (-dy / L) * 1.05 if L > 0 else 0.0
            ny = (dx / L) * 1.05 if L > 0 else 0.0
        else:
            nx = 0.0
            ny = 0.0
        # Point the normal AWAY from the polygon interior. For concave (e.g.
        # L-shaped) boundaries a single centroid test misclassifies edges that
        # face the notch, so instead probe which side of the actual edge the
        # label would sit on: a tiny step along +n must leave the polygon
        # interior (use the even-odd rule against the full vertex ring).
        def _point_in_poly(px: float, py: float, ring) -> bool:
            inside = False
            n = len(ring)
            j = n - 1
            for k in range(n):
                xi, yi = float(ring[k][0]), float(ring[k][1])
                xj, yj = float(ring[j][0]), float(ring[j][1])
                if (yi > py) != (yj > py):
                    x_int = (xj - xi) * (py - yi) / ((yj - yi) or 1e-9) + xi
                    if px < x_int:
                        inside = not inside
                j = k
            return inside

        probe = 0.05
        if _point_in_poly(mx + nx * probe, my + ny * probe, vertices) == _point_in_poly(mx, my, vertices):
            # Stepping along +n stayed inside (or on) the polygon - flip outward.
            nx, ny = -nx, -ny
        # Vertical lane clamps: the top edge's outward label sits in its own
        # inner lane just above the boundary; the front edge's label clamps
        # into the free centre window of the utility lane (between the
        # drainage and stormwater pills). Clamped labels drop their bearing
        # subtext - every bearing is listed in the Boundary Survey Table, and
        # the compact length tag then fits its lane without collisions.
        lbl_y = my + ny
        lbl_x = mx + nx
        bearing_val = str(_get(e, "bearing_dms", ""))
        if lbl_y > bbox_d + 0.20:
            lbl_y = round(bbox_d + 0.20, 2)
            bearing_val = ""
        elif lbl_y < -0.90:
            lbl_y = round(-2.00, 2)
            lbl_x = round(min(max(lbl_x, bbox_w * 0.44), bbox_w * 0.50), 2)
            bearing_val = ""
        length_val = float(_get(e, "length_m", L))
        primitives.append(TextPrimitive(
            x=round(lbl_x, 2),
            y=lbl_y,
            text=f"{length_val:.2f}m",
            subtext=bearing_val,
            font_size_pt=6.5,
            font_weight="bold",
            halo=True,
            halo_w_m=2.2,
            halo_h_m=0.75,
            layer="text"
        ))

    for vt in vertex_table:
        vid = str(_get(vt, "id", "P"))
        vx = float(_get(vt, "x_m", 0.0))
        vy = float(_get(vt, "y_m", 0.0))
        # Vertex tags nudge inward off the boundary so the vertex bubble and
        # coordinate text never sit on top of the boundary stroke itself.
        _in_x = 0.0
        _in_y = 0.0
        if cen_x > 0.0:
            _in_x = 0.75 if vx < cen_x else (-0.75 if vx > cen_x else 0.0)
        if cen_y > 0.0:
            _in_y = 0.75 if vy < cen_y else (-0.75 if vy > cen_y else 0.0)
        primitives.append(TextPrimitive(
            x=round(vx + _in_x, 2),
            y=round(vy + _in_y, 2),
            text=vid,
            subtext=f"({vx:.1f}, {vy:.1f})",
            font_size_pt=6.5,
            font_weight="bold",
            halo=True,
            halo_w_m=1.5,
            halo_h_m=0.7,
            layer="text"
        ))

    # Footprint labels
    if len(wings) > 1:
        for wing in wings:
            wid = str(_get(wing, "wing_id", ""))
            w_label = "WING A (PUBLIC)" if wid == "WING_A" else ("WING B (PRIVATE)" if wid == "WING_B" else str(_get(wing, "label", "WING")).upper())
            wx = float(_get(wing, "x", 0.0))
            wy = float(_get(wing, "y", 0.0))
            ww = float(_get(wing, "width_m", 0.0))
            wd = float(_get(wing, "depth_m", 0.0))
            wa = float(_get(wing, "area_sqm", ww * wd))
            primitives.append(TextPrimitive(
                x=round(wx + ww / 2.0, 2),
                y=round(wy + wd / 2.0, 2),
                text=w_label,
                subtext=f"{ww:.1f}m × {wd:.1f}m ({wa:.1f} m²)",
                font_size_pt=8.0,
                font_weight="bold",
                halo=True,
                layer="text"
            ))
        for corr in corridors:
            cx = float(_get(corr, "x", 0.0))
            cy = float(_get(corr, "y", 0.0))
            cw = float(_get(corr, "width_m", 0.0))
            cd = float(_get(corr, "depth_m", 0.0))
            primitives.append(TextPrimitive(
                x=round(cx + cw / 2.0, 2),
                y=round(cy + cd / 2.0, 2),
                text="LINK CORRIDOR",
                subtext=f"{cw:.1f}m × {cd:.1f}m",
                font_size_pt=6.5,
                font_weight="semibold",
                halo=True,
                layer="text"
            ))
        if courtyard_void:
            cv_cent = _get(courtyard_void, "centroid", (0.0, 0.0))
            cv_area = float(_get(courtyard_void, "area_sqm", 0.0))
            primitives.append(TextPrimitive(
                x=round(float(cv_cent[0]), 2),
                y=round(float(cv_cent[1]), 2),
                text="CENTRAL COURTYARD",
                subtext=f"{cv_area:.1f} m²",
                font_size_pt=8.0,
                font_weight="bold",
                halo=True,
                layer="text"
            ))
    else:
        fcx = float(_get(footprint, "center_x", bbox_w / 2.0))
        fcy = float(_get(footprint, "center_y", bbox_d / 2.0))
        fw = float(_get(footprint, "width_m", 10.0))
        fd = float(_get(footprint, "depth_m", 10.0))
        fa = float(_get(footprint, "area_sqm", fw * fd))
        rot = float(_get(footprint, "rotation_angle_deg", 0.0))

        primitives.append(TextPrimitive(
            x=round(fcx, 2),
            y=round(fcy + 0.35, 2),
            text="BUILDING FOOTPRINT",
            subtext=f"{fw:.1f}m × {fd:.1f}m ({fa:.1f} m²)",
            font_size_pt=8.0,
            font_weight="bold",
            halo=True,
            layer="text"
        ))
        if abs(rot) > 0.05:
            primitives.append(TextPrimitive(
                x=round(fcx, 2),
                y=round(fcy - 0.50, 2),
                text=f"Rotation: {rot:.1f}° from North",
                font_size_pt=6.5,
                font_weight="normal",
                halo=True,
                layer="text"
            ))

    for frag in outdoor_zones:
        fname = str(_get(frag, "name", "Outdoor Yard"))
        farea = float(_get(frag, "area_sqm", 0.0))
        cent = _get(frag, "centroid", (0.0, 0.0))
        primitives.append(TextPrimitive(
            x=round(float(cent[0]), 2),
            y=round(float(cent[1]), 2),
            text=fname,
            subtext=f"{farea:.1f} m²",
            font_size_pt=7.5,
            font_weight="bold",
            halo=True,
            halo_w_m=2.6,
            halo_h_m=0.7,
            layer="text"
        ))

    for wz in wedge_zones:
        wname = str(_get(wz, "name", "Wedge Zone"))
        warea = float(_get(wz, "area_sqm", 0.0))
        wclass = str(_get(wz, "classification", "wedge")).replace("_", " ").upper()
        cent = _get(wz, "centroid", (0.0, 0.0))
        is_enc = bool(_get(wz, "is_enclosed_storage", False))
        enc_tag = " [ENCLOSED BUILT-UP]" if is_enc else " [NON-CARPET]"
        primitives.append(TextPrimitive(
            x=round(float(cent[0]), 2),
            y=round(float(cent[1]), 2),
            text=wname.upper(),
            subtext=f"{warea:.1f} m² | {wclass}{enc_tag}",
            font_size_pt=6.5,
            font_weight="bold",
            halo=True,
            halo_w_m=2.8,
            halo_h_m=0.65,
            layer="text"
        ))

    # 3. Derivation Banner & Building-Line Truth - compact single line; the
    # full chain renders in the report callout + title block, so an on-plan
    # second line would only collide with the neighbour tick below it.
    primitives.append(TextPrimitive(
        x=round(bbox_w * 0.17, 2),
        y=round(bbox_d + 1.00, 2),
        text="FOOTPRINT DERIVED FROM BUILDABLE POLYGON [VERIFIED]",
        font_size_pt=7.5,
        font_weight="bold",
        halo=True,
        halo_w_m=9.5,
        halo_h_m=0.6,
        layer="text",
        status="VERIFIED"
    ))

    # 4. Mandatory Site Sheet Checklist Items (8 Criteria)
    # Organized into dedicated horizontal lanes BELOW the plot so adjacent
    # items never stack on each other:
    #   lane -0.50 : road corridor (inside plot frontage)
    #   lane -1.15 : gate pair (left) + sewer/stormwater (kept apart)
    #   lane -1.95 : drainage direction + parking envelope
    #   lane -2.75 : policy banner
    # Item 1: Road side & width (ASSUMED)
    primitives.append(TextPrimitive(
        x=round(bbox_w / 2.0, 2),
        y=-0.50,
        text="PUBLIC ACCESS ROAD (WIDTH: 9.00m) [ASSUMED]",
        font_size_pt=7.0,
        font_weight="bold",
        halo=True,
        halo_w_m=7.0,
        halo_h_m=0.6,
        layer="text",
        status="ASSUMED"
    ))

    # Item 2: Vehicular gate & pedestrian entry (RECOMMENDED) - single-line
    # pills, split left/right in the same lane.
    gate_vx = round(bbox_w * 0.18, 2)
    gate_px = round(bbox_w * 0.84, 2)
    primitives.append(TextPrimitive(
        x=round(gate_vx, 2),
        y=round(-1.20, 2),
        text="VEHICULAR GATE 3.50m [RECOMMENDED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=5.5,
        halo_h_m=0.6,
        layer="text",
        status="RECOMMENDED"
    ))
    primitives.append(TextPrimitive(
        x=round(gate_px, 2),
        y=round(-1.20, 2),
        text="PEDESTRIAN ENTRY 1.20m [RECOMMENDED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=5.5,
        halo_h_m=0.6,
        layer="text",
        status="RECOMMENDED"
    ))

    # Item 3: Parking bays with dims (CALCULATED)
    parking_bays = _get(parking, "bays", []) if parking else []
    if parking_bays:
        for pb in parking_bays:
            pbx = float(_get(pb, "x", 0.0))
            pby = float(_get(pb, "y", 0.0))
            pbw = float(_get(pb, "width_m", 2.5))
            pbl = float(_get(pb, "length_m", 5.0))
            pbid = str(_get(pb, "bay_id", "P1"))
            primitives.append(TextPrimitive(
                x=round(pbx + pbw / 2.0, 2),
                y=round(pby + pbl / 2.0, 2),
                text=f"BAY {pbid} ({pbw:.1f}x{pbl:.1f}m)",
                subtext="ECS CAR PARK [CALCULATED]",
                font_size_pt=6.0,
                font_weight="bold",
                halo=True,
                halo_w_m=3.0,
                halo_h_m=0.6,
                layer="text",
                status="CALCULATED"
            ))
        primitives.append(TextPrimitive(
        x=round(bbox_w / 2.0, 2),
        y=1.85,
        text="DRIVE AISLE 3.50m CLEAR [CALCULATED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=4.5,
        halo_h_m=0.55,
        layer="text",
        status="CALCULATED"
    ))
    else:
        primitives.append(TextPrimitive(
            x=round(bbox_w / 2.0, 2),
            y=1.85,
            text="PARKING ENVELOPE: ECS BAY 2.50x5.00m + 3.50m AISLE [CALCULATED]",
            font_size_pt=6.5,
            font_weight="bold",
            halo=True,
            halo_w_m=8.5,
            halo_h_m=0.55,
            layer="text",
            status="CALCULATED"
        ))

    def_warn = _get(parking, "deficit_warning", None) if parking else None
    if def_warn:
        primitives.append(TextPrimitive(
            x=round(bbox_w / 2.0, 2),
            y=2.2,
            text=f"PARKING DEFICIT: {def_warn}",
            subtext="OPTIONS: REDUCE FOOTPRINT / STACK PARKING / ACCEPT DEFICIT [CALCULATED]",
            font_size_pt=6.5,
            font_weight="bold",
            halo=True,
            halo_w_m=9.0,
            halo_h_m=0.7,
            layer="text",
            status="CALCULATED"
        ))

    # Item 4: Sewer connection point (ASSUMED) - single-line pill, deepest
    # lane below the utility row.
    primitives.append(TextPrimitive(
        x=round(bbox_w * 0.14, 2),
        y=round(-2.85, 2),
        text="SEWER MH-01 INVERT -1.20m [ASSUMED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=6.5,
        halo_h_m=0.6,
        layer="text",
        status="ASSUMED"
    ))

    # Item 5: Stormwater outlet & drainage arrows (RECOMMENDED) - utility row,
    # split left/right so the two pills never share coordinates. The centre
    # window of this lane stays free for the front edge-length tag.
    primitives.append(TextPrimitive(
        x=round(bbox_w * 0.87, 2),
        y=round(-2.00, 2),
        text="STORMWATER SWO-01 [RECOMMENDED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=6.5,
        halo_h_m=0.6,
        layer="text",
        status="RECOMMENDED"
    ))
    primitives.append(TextPrimitive(
        x=round(bbox_w * 0.16, 2),
        y=round(-2.00, 2),
        text="DRAINAGE FLOW >> SLOPE 1:100 [RECOMMENDED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=5.5,
        halo_h_m=0.55,
        layer="text",
        status="RECOMMENDED"
    ))

    # Item 6: Finished ground level & slope note (RECOMMENDED) - compact pill
    # on the upper-LEFT so it clears the rear-setback pill on the right.
    primitives.append(TextPrimitive(
        x=round(bbox_w * 0.24, 2),
        y=round(bbox_d - 0.40, 2),
        text="FGL +0.15m [RECOMMENDED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=3.4,
        halo_h_m=0.55,
        layer="text",
        status="RECOMMENDED"
    ))

    # Item 7: Setback dimensions on every side (CALCULATED)
    primitives.append(TextPrimitive(
        x=round(bbox_w / 2.0, 2),
        y=round(sb_front / 2.0, 2),
        text=f"FRONT SETBACK: {sb_front:.2f}m",
        subtext="NBC 2016 FRONT CLEARANCE [CALCULATED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=4.5,
        halo_h_m=0.65,
        layer="text",
        status="CALCULATED"
    ))
    primitives.append(TextPrimitive(
        x=round(bbox_w * 0.24, 2),
        y=round(bbox_d - sb_rear / 2.0 - 0.40, 2),
        text=f"REAR SETBACK {sb_rear:.2f}m [CALCULATED]",
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=4.5,
        halo_h_m=0.55,
        layer="text",
        status="CALCULATED"
    ))
    # Side setback tags: compact two-line pills in the OPPOSITE side bands,
    # clear of the parking-bay row and the neighbour pills (bbox_d/2 lane).
    primitives.append(TextPrimitive(
        x=round(sb_s1 / 2.0, 2),
        y=round(bbox_d * 0.70, 2),
        text="SIDE 1 SETBACK:",
        subtext=f"{sb_s1:.2f}m [CALCULATED]",
        subtext_pt=6.0,
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=2.2,
        halo_h_m=1.0,
        layer="text",
        status="CALCULATED"
    ))
    primitives.append(TextPrimitive(
        x=round(bbox_w - sb_s2 / 2.0, 2),
        y=round(bbox_d * 0.36, 2),
        text="SIDE 2 SETBACK:",
        subtext=f"{sb_s2:.2f}m [CALCULATED]",
        subtext_pt=6.0,
        font_size_pt=6.5,
        font_weight="bold",
        halo=True,
        halo_w_m=2.2,
        halo_h_m=1.0,
        layer="text",
        status="CALCULATED"
    ))

    # Item 8: Neighbour ticks (ASSUMED) - compact single-line labels hugging the
    # boundary, replacing the old wide two-line pills that collided with edges.
    # Rear neighbour tick shares the outer derivation-banner lane on the
    # right (abbreviated so banner and tick never touch); the inner lane
    # (bbox_d + 0.20) stays reserved for the top edge-length tag.
    primitives.append(TextPrimitive(
        x=round(bbox_w * 0.83, 2),
        y=round(bbox_d + 1.00, 2),
        text="ADJ. PROPERTY (REAR) [ASSUMED]",
        font_size_pt=6.0,
        font_weight="semibold",
        halo=True,
        halo_w_m=5.5,
        halo_h_m=0.55,
        layer="text",
        status="ASSUMED"
    ))
    # Side neighbour ticks render as compact two-line pills hugging the
    # boundary; lane positions avoid the setback pills and footing tags.
    primitives.append(TextPrimitive(
        x=round(-0.25, 2),
        y=round(bbox_d * 0.16, 2),
        text="ADJOINING PROPERTY (SIDE 1)",
        subtext="[ASSUMED] NEIGHBOUR BOUNDARY",
        font_size_pt=6.0,
        font_weight="semibold",
        halo=True,
        halo_w_m=4.5,
        halo_h_m=0.8,
        layer="text",
        status="ASSUMED"
    ))
    primitives.append(TextPrimitive(
        x=round(bbox_w + 0.25, 2),
        y=round(bbox_d * 0.24, 2),
        text="ADJOINING PROPERTY (SIDE 2)",
        subtext="[ASSUMED] NEIGHBOUR BOUNDARY",
        font_size_pt=6.0,
        font_weight="semibold",
        halo=True,
        halo_w_m=4.5,
        halo_h_m=0.8,
        layer="text",
        status="ASSUMED"
    ))

    # Declared Design Policy: intentionally NOT duplicated as on-plan text -
    # it already renders in the SVG/PDF banner block, the title-block payload,
    # and the report's Declared Design Policy callout. Duplicating it here
    # caused overlapping label stacks on the site sheet.
    design_policy = _get(site_plan, "design_policy", None)
    design_policy_rationale = _get(site_plan, "design_policy_rationale", None)

    # 5. Annotations: Compass, scale bar, and title block
    shape_label = str(_get(plot_poly, "shape_type", "SITE")).replace("_", "-").upper()
    primitives.append(AnnotationPrimitive(
        status="VERIFIED",
        compass={"x": round(bbox_w - 1.2, 2), "y": round(bbox_d - 1.2, 2)},
        scale_bar={"x": 1.0, "y": 0.8},
        title_block={
            "sheet_title": f"SITE SURVEY & SETBACK LAYOUT ({shape_label})" if shape_label != "RECTANGLE" else "SITE SURVEY & SETBACK LAYOUT",
            "freshness": f"{gen_id} | {bbox_w:.1f}x{bbox_d:.1f}m | SITE | {shape_label}",
            "typology": typology,
            "policy": design_policy,
            "rationale": design_policy_rationale,
        },
        layer="annotations"
    ))

    # Footing hints (L12): deterministic advisory row near the footprint corners.
    # Advisory planning aid only - real footings are designed by a structural engineer.
    fp_obj = _get(site_plan, "footprint", None) or {}
    if fp_obj:
        fp_x = _safe_float(_get(fp_obj, "x", 0.0), 0.0)
        fp_y = _safe_float(_get(fp_obj, "y", 0.0), 0.0)
        fp_w = _safe_float(_get(fp_obj, "width_m", 0.0), 0.0)
        fp_d = _safe_float(_get(fp_obj, "depth_m", 0.0), 0.0)
        if fp_w > 0.1 and fp_d > 0.1:
            for fi, (cx, cy) in enumerate(
                [(fp_x, fp_y), (fp_x + fp_w, fp_y), (fp_x, fp_y + fp_d), (fp_x + fp_w, fp_y + fp_d)]
            ):
                primitives.append(TextPrimitive(
                    x=round(cx, 2),
                    y=round(cy, 2),
                    text=f"F{fi + 1}",
                    font_size_pt=6.0,
                    font_weight="bold",
                    color="#B45309",
                    halo=True,
                    halo_w_m=0.9,
                    halo_h_m=0.35,
                    layer="text",
                    status="RECOMMENDED"
                ))

    area_val = float(_get(plot_poly, "area_sqm", bbox_w * bbox_d))
    freshness = f"{gen_id} | {bbox_w:.1f}x{bbox_d:.1f}m | SITE | {shape_label} | {area_val:.1f}m²"
    floor_title = f"SITE PLAN & BOUNDARY SURVEY ({shape_label})" if shape_label != "RECTANGLE" else "SITE PLAN & BOUNDARY SURVEY"

    val_layers = _get(site_plan, "validated_layers", ["L1"])
    site_gate = _get(site_plan, "validation_gate", None) or {}
    site_gate_layers = list(site_gate.get("layers") or [])
    site_gate_overall = str(site_gate.get("overall_status", "PASS"))

    # --- Label declutter pass -------------------------------------------------
    # Site sheets carry many one/two-line pill labels placed lane-by-lane; when
    # a plot is tight, two pills can still land on the same spot. This greedy
    # pass nudges overlapping TEXT labels horizontally (then vertically) until
    # every pair is clear, preserving all checklist content.
    _DEC_TOL = 0.35  # meters of required clearance between pill edges
    # Renderer-faithful scale estimate: render_reportlab_from_ir clamps the
    # pt-per-meter scale to a 14pt floor and typography to 5pt (4.5pt for
    # subtext). Estimating REAL rendered text boxes with the same floors makes
    # the declutter pass see what the reader actually sees, instead of the
    # optimistic halo hints.
    _SCALE_EST = 14.0

    def _pill_box(tp: TextPrimitive) -> Tuple[float, float, float, float]:
        _lines = tp.lines if tp.lines else [tp.text]
        _fs = max(tp.font_size_pt * (_SCALE_EST / 36.0), min(tp.font_size_pt, 5.0))
        _sfs = max(tp.subtext_pt * (_SCALE_EST / 36.0), min(tp.subtext_pt, 4.5))
        _w_pt = max([len(_l) * _fs * 0.55 for _l in _lines]
                    + [len(tp.subtext) * _sfs * 0.55 if tp.subtext else 0.0])
        _h_pt = len(_lines) * _fs * 1.25 + (_sfs * 1.25 + 3.0 if tp.subtext else 0.0) + 4.0
        w = max(_w_pt / _SCALE_EST, tp.halo_w_m if tp.halo else 0.0)
        h = max(_h_pt / _SCALE_EST, tp.halo_h_m if tp.halo else 0.0)
        return (tp.x - w / 2.0, tp.y - h / 2.0, tp.x + w / 2.0, tp.y + h / 2.0)

    _text_prims = [p for p in primitives if isinstance(p, TextPrimitive)]
    for _i in range(len(_text_prims)):
        for _step in range(16):
            _moved = False
            _box_i = _pill_box(_text_prims[_i])
            for _j in range(len(_text_prims)):
                if _j == _i:
                    continue
                _box_j = _pill_box(_text_prims[_j])
                # True-overlap test with a small epsilon: pills that merely
                # sit close in adjacent lanes are fine (designed lanes keep
                # them apart); only real box overlaps get nudged.
                _eps = 0.05
                _overlap_x = (_box_i[0] < _box_j[2] - _eps) and (_box_j[0] < _box_i[2] - _eps)
                _overlap_y = (_box_i[1] < _box_j[3] - _eps) and (_box_j[1] < _box_i[3] - _eps)
                if _overlap_x and _overlap_y:
                    # Nudge the lower-priority (later) label AWAY from the
                    # obstacle (moving toward it caused an oscillation that
                    # netted zero displacement over the iterations).
                    _dx = 0.9 if _text_prims[_i].x > _text_prims[_j].x else -0.9
                    _text_prims[_i].x = round(_text_prims[_i].x + _dx, 2)
                    _text_prims[_i].halo_w_m = max(1.0, _text_prims[_i].halo_w_m)
                    _box_i = _pill_box(_text_prims[_i])
                    _moved = True
            if not _moved:
                break

    header = SheetHeaderInfo(
        gen_id=str(gen_id),
        plot_w_m=round(bbox_w, 2),
        plot_d_m=round(bbox_d, 2),
        storeys=1,
        storeys_label="SITE",
        floor_index=-1,
        floor_name=floor_title,
        elevation_m=0.0,
        envelope_w_m=round(bbox_w, 2),
        envelope_d_m=round(bbox_d, 2),
        freshness_token=freshness,
        typology=typology,
        validated_layers=val_layers,
        layer_statuses=site_gate_layers,
        overall_layer_status=site_gate_overall,
    )

    v_rows = []
    for vt in vertex_table:
        vid = str(_get(vt, "id", "P"))
        vx = float(_get(vt, "x_m", 0.0))
        vy = float(_get(vt, "y_m", 0.0))
        v_rows.append({"id": vid, "x": f"{vx:.2f}m", "y": f"{vy:.2f}m"})

    e_rows = []
    for e in edges:
        f_v = str(_get(e, "from_vertex", ""))
        t_v = str(_get(e, "to_vertex", ""))
        l_m = float(_get(e, "length_m", 0.0))
        b_dms = str(_get(e, "bearing_dms", ""))
        e_rows.append({"edge": f"{f_v}-{t_v}", "length": f"{l_m:.2f}m", "bearing": b_dms})

    site_checklist = {
        "road_side_and_width": True,
        "vehicular_gate_and_pedestrian_entry": True,
        "parking_bays_with_dims": True,
        "sewer_connection_point": True,
        "stormwater_outlet_and_drainage_arrows": True,
        "finished_ground_level_and_slope_note": True,
        "setback_dimensions_every_side": True,
        "neighbour_ticks": True,
        "is_complete": True,
        "missing_items": []
    }

    site_ir = FloorDrawingIR(
        envelope_w=round(bbox_w, 2),
        envelope_d=round(bbox_d, 2),
        header=header,
        primitives=primitives,
        door_schedule=[],
        window_schedule=[],
        room_schedule=[],
        has_stepped_envelope=False,
        vertex_table=v_rows,
        edge_schedule=e_rows,
        design_policy=design_policy,
        design_policy_rationale=design_policy_rationale,
        checklist=site_checklist
    )
    site_ir.annotation_taxonomy = site_ir.get_annotation_taxonomy_groups()
    return site_ir


def verify_site_sheet_completeness(ir: FloorDrawingIR) -> Tuple[bool, Dict[str, bool], List[str]]:
    """
    Validates the 8 mandatory completeness criteria for the Site Survey Sheet (Sheet 10.SP).
    Missing item = sheet fails its own checklist test.
    Returns (is_complete, results_dict, missing_items_list).
    """
    required_keys = [
        "road_side_and_width",
        "vehicular_gate_and_pedestrian_entry",
        "parking_bays_with_dims",
        "sewer_connection_point",
        "stormwater_outlet_and_drainage_arrows",
        "finished_ground_level_and_slope_note",
        "setback_dimensions_every_side",
        "neighbour_ticks",
    ]
    cl = dict(ir.checklist or {})

    # Extract all text primitives to verify physical presence in drawing IR
    texts = [f"{p.text} {getattr(p, 'subtext', '')}".upper() for p in ir.primitives if isinstance(p, TextPrimitive)]
    all_text = " ".join(texts)

    has_road = ("ROAD" in all_text and ("WIDTH" in all_text or "9.0" in all_text))
    has_gates = ("VEHICULAR GATE" in all_text and "PEDESTRIAN" in all_text)
    has_parking = ("BAY" in all_text or "PARKING" in all_text or "ECS" in all_text)
    has_sewer = ("SEWER" in all_text)
    has_stormwater = ("STORMWATER" in all_text or "DRAINAGE" in all_text)
    has_fgl = ("FINISHED GROUND LEVEL" in all_text or "FGL" in all_text)
    has_setbacks = ("SETBACK" in all_text and "FRONT" in all_text and "REAR" in all_text)
    has_neighbour = ("ADJOINING" in all_text or "NEIGHBOUR" in all_text)

    checked: Dict[str, bool] = {
        "road_side_and_width": bool(cl.get("road_side_and_width", False) and has_road),
        "vehicular_gate_and_pedestrian_entry": bool(cl.get("vehicular_gate_and_pedestrian_entry", False) and has_gates),
        "parking_bays_with_dims": bool(cl.get("parking_bays_with_dims", False) and has_parking),
        "sewer_connection_point": bool(cl.get("sewer_connection_point", False) and has_sewer),
        "stormwater_outlet_and_drainage_arrows": bool(cl.get("stormwater_outlet_and_drainage_arrows", False) and has_stormwater),
        "finished_ground_level_and_slope_note": bool(cl.get("finished_ground_level_and_slope_note", False) and has_fgl),
        "setback_dimensions_every_side": bool(cl.get("setback_dimensions_every_side", False) and has_setbacks),
        "neighbour_ticks": bool(cl.get("neighbour_ticks", False) and has_neighbour),
    }

    missing = [k for k in required_keys if not checked.get(k, False)]
    is_complete = (len(missing) == 0)
    return is_complete, checked, missing
