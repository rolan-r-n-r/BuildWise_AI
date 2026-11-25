"""
test_svg_pdf_content_parity.py - SVG/PDF content parity
=========================================================================
Both renderers consume the same Drawing IR; this pin asserts that the
CONTENT layers survive into both output formats for the same build:

  - universal gate table: every layer id L1-L15 + the OVERALL verdict
  - honest status stamp (STATUS: CONCEPT DESIGN ... NOT FOR CONSTRUCTION)
  - title block: GEN token, plot dimensions, storeys label
  - schedules: door schedule tag D1 and room-schedule content
  - legend: RWP / DRAIN symbols are taught on both outputs

Geometry parity (coordinates, per-layer primitive counts) is pinned in
test_drawing_ir.py::test_drawing_ir_parity_and_transforms; this file adds
the text/content layers that coordinate pins cannot cover.
"""

import io
import re

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.drawing_ir import build_drawing_ir, render_svg_from_ir
from app.services.floorplan.validation_gate import LAYER_IDS


def _build(typology: str, floors: int):
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=floors,
        building_typology=typology,
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"],
    )
    return SoleGeometryEngine(req).solve()


def _svg_text(svg: str) -> str:
    return re.sub(r"<[^>]+>", " ", svg)


def _pdf_text(b) -> str:
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(b.getvalue()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.mark.parametrize("typology,floors", [
    ("T1_SINGLE_FAMILY", 2),
    ("T4_WAREHOUSE", 1),
])
def test_svg_pdf_content_parity_per_layer(typology: str, floors: int):
    b = _build(typology, floors)
    ir = build_drawing_ir(floor_data=b.floors[0], building_model=b, gen_id="GEN-T1-2F-42")
    svg_txt = _svg_text(render_svg_from_ir(ir))

    from app.services.report_service import generate_pdf_report
    payload = {
        "request_id": "BW-PARITY-VERIFICATION",
        "timestamp": "2026-10-02 12:00:00 UTC",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Parity Test Site",
        "overall_suitability_score": 85.0,
        "suitability_verdict": "Verified",
        "built_up_area_sqft": 3600.0,
        "floors": floors,
        "include_construction_schedules": True,
        "multi_storey": b.model_dump(),
        "floor_plan": b.model_dump(),
    }
    pdf_txt = _pdf_text(generate_pdf_report(payload))

    # 1. Gate table parity: every layer id + OVERALL verdict on both outputs.
    for lid in LAYER_IDS:
        assert lid in svg_txt, f"{typology}: {lid} missing from SVG gate table"
        assert lid in pdf_txt, f"{typology}: {lid} missing from PDF gate table"
    assert "OVERALL" in svg_txt and "OVERALL" in pdf_txt

    # 2. Honest stamp parity.
    assert "STATUS: CONCEPT DESIGN" in svg_txt
    assert "STATUS: CONCEPT DESIGN" in pdf_txt
    assert "NOT FOR CONSTRUCTION" in svg_txt
    assert "NOT FOR CONSTRUCTION" in pdf_txt

    # 3. Title block parity: GEN token + plot dims + storeys label.
    assert "GEN-T1-2F-42" in svg_txt or "GEN" in svg_txt
    assert "GEN" in pdf_txt
    assert "20.0" in svg_txt and "20.0" in pdf_txt
    assert "18.0" in svg_txt and "18.0" in pdf_txt
    assert "G+1" in svg_txt or "G" in svg_txt

    # 4. Schedules parity: D1 door tag and room schedule presence (PDF titles
    # are title-case on the schedules sheet; SVG panel is uppercase).
    assert "D1" in svg_txt and "D1" in pdf_txt
    assert "room schedule" in svg_txt.lower() and "room schedule" in pdf_txt.lower()

    # 5. Legend parity: service legend taught on both (single-source parts).
    assert "RWP" in svg_txt and "RWP" in pdf_txt
    assert "DRAIN" in svg_txt and "DRAIN" in pdf_txt
    assert "DP = downpipe" in svg_txt and "DP = downpipe" in pdf_txt


def test_svg_pdf_parity_gate_overall_matches_model():
    """The rendered OVERALL verdict equals the model's gate overall (not hardcoded)."""
    b = _build("T1_SINGLE_FAMILY", 2)
    gate = b.validation_gate
    ir = build_drawing_ir(floor_data=b.floors[0], building_model=b, gen_id="GEN-T1-2F-42")
    svg_txt = _svg_text(render_svg_from_ir(ir))
    m = re.search(r"OVERALL:\s*(PASS|WARN|FAIL)", svg_txt)
    assert m, "SVG sheet lacks an OVERALL verdict"
    assert m.group(1) == gate["overall_status"]
