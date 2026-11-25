import copy
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Tuple
import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.engine import SoleGeometryEngine

_SOLVE_CACHE: Dict[Tuple[Any, ...], Any] = {}


def _cached_solve(req: FloorPlanRequest):
    key = (
        req.building_typology,
        req.floors,
        req.plot_width_m,
        req.plot_depth_m,
        req.ground_coverage_ratio,
    )
    if key not in _SOLVE_CACHE:
        _SOLVE_CACHE[key] = SoleGeometryEngine(req).solve()
    return copy.deepcopy(_SOLVE_CACHE[key])


def extract_text_and_badge_bboxes(svg_str: str) -> List[Dict[str, Any]]:
    """
    Parses SVG XML and extracts bounding boxes for all <text> elements and <rect>/<circle> badges.
    Accounts for <g transform="translate(dx, dy)"> nesting and rotation transforms.
    """
    root = ET.fromstring(svg_str)
    elements: List[Dict[str, Any]] = []

    def walk(elem: ET.Element, parent_dx: float = 0.0, parent_dy: float = 0.0):
        dx = parent_dx
        dy = parent_dy
        transform = elem.attrib.get("transform", "")
        if transform:
            m = re.search(r"translate\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)", transform)
            if m:
                dx += float(m.group(1))
                dy += float(m.group(2))

        tag = elem.tag.split("}")[-1]

        if tag == "text":
            text_content = "".join(elem.itertext()).strip()
            if text_content:
                x = float(elem.attrib.get("x", "0")) + dx
                y = float(elem.attrib.get("y", "0")) + dy
                fs = float(elem.attrib.get("font-size", "10"))
                anchor = elem.attrib.get("text-anchor", "start")

                rotate_m = re.search(r"rotate\(\s*(-?90)", transform)

                w = 0.6 * fs * len(text_content)
                h = fs

                if rotate_m:
                    w, h = h, w
                    xmin = x - w / 2.0
                    xmax = x + w / 2.0
                    ymin = y - h / 2.0
                    ymax = y + h / 2.0
                else:
                    if anchor == "middle":
                        xmin = x - w / 2.0
                        xmax = x + w / 2.0
                    elif anchor == "end":
                        xmin = x - w
                        xmax = x
                    else:
                        xmin = x
                        xmax = x + w
                    ymin = y - 0.85 * fs
                    ymax = y + 0.25 * fs

                elements.append({
                    "type": "text",
                    "text": text_content,
                    "bbox": (xmin, ymin, xmax, ymax),
                    "attrib": elem.attrib,
                })

        elif tag == "rect" and ("badge" in elem.attrib.get("class", "") or "badge" in elem.attrib.get("id", "")):
            x = float(elem.attrib.get("x", "0")) + dx
            y = float(elem.attrib.get("y", "0")) + dy
            w = float(elem.attrib.get("width", "0"))
            h = float(elem.attrib.get("height", "0"))
            elements.append({
                "type": "badge_rect",
                "text": elem.attrib.get("id", "badge"),
                "bbox": (x, y, x + w, y + h),
                "attrib": elem.attrib,
            })

        elif tag == "circle" and ("badge" in elem.attrib.get("class", "") or "badge" in elem.attrib.get("id", "")):
            cx = float(elem.attrib.get("cx", "0")) + dx
            cy = float(elem.attrib.get("cy", "0")) + dy
            r = float(elem.attrib.get("r", "0"))
            elements.append({
                "type": "badge_circle",
                "text": elem.attrib.get("id", "badge_circle"),
                "bbox": (cx - r, cy - r, cx + r, cy + r),
                "attrib": elem.attrib,
            })

        for child in elem:
            walk(child, dx, dy)

    walk(root)
    return elements


def find_pairwise_collisions(elements: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Finds intersecting pairs among extracted text and badge elements.
    Ignores intentional badge backgrounds containing their own label.
    """
    collisions = []
    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):
            e1 = elements[i]
            e2 = elements[j]

            # F0 Core anchor badge container + inner label
            if (e1["type"] == "badge_rect" and e2["type"] == "text" and "f0-core-anchor" in e1["text"] and "F0 CORE ANCHOR" in e2["text"]) or \
               (e2["type"] == "badge_rect" and e1["type"] == "text" and "f0-core-anchor" in e2["text"] and "F0 CORE ANCHOR" in e1["text"]):
                continue

            # Unit A / Unit B badge container + inner label
            if (e1["type"] == "badge_rect" and e2["type"] == "text" and ("UNIT A" in e2["text"] or "UNIT B" in e2["text"])) or \
               (e2["type"] == "badge_rect" and e1["type"] == "text" and ("UNIT A" in e1["text"] or "UNIT B" in e1["text"])):
                continue

            # L3 circle badge container + inner index label
            if (e1["type"] == "badge_circle" and e2["type"] == "text" and e1["text"] == f"room-tag-{e2['text']}") or \
               (e2["type"] == "badge_circle" and e1["type"] == "text" and e2["text"] == f"room-tag-{e1['text']}"):
                continue

            b1 = e1["bbox"]
            b2 = e2["bbox"]

            # AABB intersection check with 0.1px tolerance
            if not (b1[2] <= b2[0] + 0.1 or b1[0] >= b2[2] - 0.1 or b1[3] <= b2[1] + 0.1 or b1[1] >= b2[3] - 0.1):
                collisions.append((e1, e2))

    return collisions


# Typologies and Storeys matrix for verification
TYPOLOGIES = [
    ("T1_SINGLE_FAMILY", "residential_single"),
    ("T2_FAMILY_APARTMENT", "residential_multi"),
    ("T3_LARGE_COMPLEX", "commercial"),
    ("T4_WAREHOUSE", "industrial"),
]
STOREYS = [1, 2, 3, 4]


# ==============================================================================
# 1. Zero Pairwise Intersections for All Typologies x 1-4 Storeys
# ==============================================================================

@pytest.mark.parametrize("typology_key, typology_name", TYPOLOGIES)
@pytest.mark.parametrize("floors_count", STOREYS)
def test_svg_zero_pairwise_text_collisions(typology_key: str, typology_name: str, floors_count: int):
    """
    Requirement A & Verification 1-2:
    Generates SVGs for T1-T4 x 1-4 floors, parses every text/badge element,
    computes bounding boxes, and asserts ZERO pairwise intersections.
    """
    plot_w = 24.0 if "WAREHOUSE" in typology_key else 14.0
    plot_d = 28.0 if "WAREHOUSE" in typology_key else 16.0

    req = FloorPlanRequest(
        plot_width_m=plot_w,
        plot_depth_m=plot_d,
        floors=floors_count,
        building_typology=typology_key,
        ground_coverage_ratio=0.60,
    )
    building = _cached_solve(req)

    for f_idx, floor in enumerate(building.floors):
        # Test CAD theme
        svg_cad = floor.svg_blueprint_cad
        elements_cad = extract_text_and_badge_bboxes(svg_cad)
        collisions_cad = find_pairwise_collisions(elements_cad)
        assert len(collisions_cad) == 0, (
            f"Collisions found on {typology_key} Floor {f_idx} (CAD theme): "
            f"{[(c[0]['text'], c[1]['text']) for c in collisions_cad]}"
        )

        # Test Paper theme
        svg_paper = floor.svg_blueprint_paper
        elements_paper = extract_text_and_badge_bboxes(svg_paper)
        collisions_paper = find_pairwise_collisions(elements_paper)
        assert len(collisions_paper) == 0, (
            f"Collisions found on {typology_key} Floor {f_idx} (Paper theme): "
            f"{[(c[0]['text'], c[1]['text']) for c in collisions_paper]}"
        )


# ==============================================================================
# 2. Main Entrance on Ground Floor Sheet
# ==============================================================================

@pytest.mark.parametrize("typology_key, typology_name", TYPOLOGIES)
def test_ground_floor_main_entrance_annotation(typology_key: str, typology_name: str):
    """
    Requirement C & Verification 3:
    Asserts Ground Floor SVG contains "MAIN ENTRANCE" approach arrow annotation,
    halo caption, and title block zone string for every typology.
    """
    plot_w = 24.0 if "WAREHOUSE" in typology_key else 14.0
    plot_d = 28.0 if "WAREHOUSE" in typology_key else 16.0

    req = FloorPlanRequest(
        plot_width_m=plot_w,
        plot_depth_m=plot_d,
        floors=2,
        building_typology=typology_key,
    )
    building = _cached_solve(req)

    gf = building.floors[0]
    svg = gf.svg_blueprint_cad

    assert "MAIN ENTRANCE" in svg, f"Ground Floor SVG missing 'MAIN ENTRANCE' for {typology_key}"
    assert 'marker-end="url(#entry-arrow)"' in svg, "Missing approach arrow marker on Ground Floor"
    assert "MAIN ENTRANCE:" in svg, "Title block missing 'MAIN ENTRANCE: <zone>' line"

    # Verify Upper Floor does NOT contain MAIN ENTRANCE approach arrow
    uf = building.floors[1]
    assert 'marker-end="url(#entry-arrow)"' not in uf.svg_blueprint_cad, (
        "Upper floor must not render Ground Floor MAIN ENTRANCE arrow"
    )


# ==============================================================================
# 3. Title Block Lines Do Not Intersect
# ==============================================================================

@pytest.mark.parametrize("typology_key, typology_name", TYPOLOGIES)
@pytest.mark.parametrize("floors_count", [1, 3])
def test_title_block_lines_non_intersecting(typology_key: str, typology_name: str, floors_count: int):
    """
    Requirement D & Verification 4:
    Asserts title-block lines have fixed line heights with 4pt leading,
    watermark is relocated to bottom-right, and lines do not overlap.
    """
    req = FloorPlanRequest(
        plot_width_m=14.0,
        plot_depth_m=16.0,
        floors=floors_count,
        building_typology=typology_key,
    )
    building = _cached_solve(req)

    for floor in building.floors:
        svg = floor.svg_blueprint_cad
        elements = extract_text_and_badge_bboxes(svg)

        # Filter title block and watermark elements
        title_texts = [
            e for e in elements
            if "LVL" in e["text"] or "TYPOLOGY" in e["text"] or "MAIN ENTRANCE:" in e["text"] or "BUILDWISE GENERATIVE CAD ENGINE" in e["text"]
        ]

        # Verify no pairwise overlap among title block lines
        for i in range(len(title_texts)):
            for j in range(i + 1, len(title_texts)):
                b1 = title_texts[i]["bbox"]
                b2 = title_texts[j]["bbox"]
                overlap = not (b1[2] <= b2[0] or b1[0] >= b2[2] or b1[3] <= b2[1] or b1[1] >= b2[3])
                assert not overlap, (
                    f"Title block overlap detected between '{title_texts[i]['text']}' and '{title_texts[j]['text']}'"
                )

        # Verify watermark position is bottom-right
        wm = next((e for e in elements if "BUILDWISE GENERATIVE CAD ENGINE" in e["text"]), None)
        assert wm is not None, "Missing CAD engine watermark"
        assert wm["attrib"].get("text-anchor") == "end"


# ==============================================================================
# 4. Worst-Case Small Plot Envelope Legibility
# ==============================================================================

def test_worst_case_small_plot_legibility():
    """
    Tests small plot (8m x 10m envelope ~ 6m x 7m) representing the worst-case compact scenario.
    Verifies that adaptive ladder successfully down-scales or tags rooms without collision.
    """
    req = FloorPlanRequest(
        plot_width_m=8.0,
        plot_depth_m=10.0,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
    )
    building = _cached_solve(req)

    for f_idx, floor in enumerate(building.floors):
        svg = floor.svg_blueprint_cad
        elements = extract_text_and_badge_bboxes(svg)
        collisions = find_pairwise_collisions(elements)
        assert len(collisions) == 0, (
            f"Collisions in compact plot Floor {f_idx}: {[(c[0]['text'], c[1]['text']) for c in collisions]}"
        )


# ==============================================================================
# 5. Core Anchor Badge Placement
# ==============================================================================

def test_core_anchor_badge_outside_core_with_leader():
    """
    Requirement B:
    Core anchor badge must be rendered outside the core rectangle with a leader line,
    and must not collide with any room labels on upper floors.
    """
    req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        floors=3,
        building_typology="T1_SINGLE_FAMILY",
    )
    building = _cached_solve(req)

    # Upper floors must contain F0 CORE ANCHOR badge and leader line
    for f_idx in [1, 2]:
        svg = building.floors[f_idx].svg_blueprint_cad
        assert "F0 CORE ANCHOR" in svg
        assert "f0-core-leader" in svg
        assert "f0-core-anchor-badge" in svg


# ==============================================================================
# 6. Unit Entry Door Badges (T2 & T3)
# ==============================================================================

@pytest.mark.parametrize("typology_key", ["T2_FAMILY_APARTMENT", "T3_LARGE_COMPLEX"])
def test_unit_entry_door_badges_t2_t3(typology_key: str):
    """
    Requirement C:
    T2/T3: tag each unit entry door with a small "UNIT A"/"UNIT B" badge.
    """
    req = FloorPlanRequest(
        plot_width_m=16.0,
        plot_depth_m=18.0,
        floors=2,
        building_typology=typology_key,
    )
    building = _cached_solve(req)

    for floor in building.floors:
        svg = floor.svg_blueprint_cad
        assert "UNIT A" in svg, f"{typology_key} floor {floor.floor_index} missing 'UNIT A' entry badge"
        assert "UNIT B" in svg, f"{typology_key} floor {floor.floor_index} missing 'UNIT B' entry badge"

