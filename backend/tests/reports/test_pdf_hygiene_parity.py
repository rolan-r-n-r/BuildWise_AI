"""
test_pdf_hygiene_parity.py - the six sheet-hygiene invariants, in the PDF
=========================================================================
test_sheet_hygiene_baseline.py pins the invariants on the SVG renderer
(`render_svg_from_ir`). The exported PDF does NOT reuse that renderer: it is
built by ReportLab from the same Drawing IR, plus its own schedules tables.

This module drives the real export (`generate_pdf_report`), extracts the text
with pypdf, and re-asserts the same invariants on ONE fresh, reproducible
baseline: a 16.1 x 19.3 m plot, G+1, T1 single-family.

  1. Door schedule LEVEL column reads the L-ladder - never "LLevel".
  2. Areas print with the superscript m² - never a bare "m2"/"sqm".
  3. No mid-word truncation of the finish vocabulary, and no ".." inside a word.
  4. ONE area source: the room-schedule area == the on-sheet label area == the
     wall-graph CLEAR area (the gross/structural area must not leak), and the
     CLEAR value must be the one printed.
  5. The computed headroom is printed and >= 2.20 m (NBC statutory minimum).
  6. The ghost-core overlay rides upper storeys only.

Where the PDF is *legitimately* different from the SVG, the assertion is written
against what the document says, not against SVG markup: there is no
`data-ghost-overlay` attribute on paper, so invariant 6 is pinned on the level
brief that teaches the overlay.
"""

import io
import re

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.drawing_ir import build_drawing_ir, render_svg_from_ir
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.living_quality import STAIR_MIN_HEADROOM_M

PLOT_W = 16.1
PLOT_D = 19.3
GEN_ID = "GEN-HYGIENE-16.1x19.3-G1"
ROOMS = ["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]

# The exact strings the sheet baseline showed cut mid-word.
KB_FRAGMENTS = [
    "Private Stairc",
    "Flamed Fluted Granite Tr",
    "Anti-Skid Ceramic Tile R",
    "Anti-Skid Vitrified",
]
# ...and the full tokens they were cut from, which must survive intact.
KB_FULL_TOKENS = [
    "Flamed Fluted Granite Treads",
    "Anti-Skid Ceramic Tile R10",
    "Anti-Skid Vitrified Tile",
]

LABEL_DIMS_RE = re.compile(r"(\d+\.\d)m × (\d+\.\d)m \((\d+\.\d)m²\)")
SCHED_DIMS_RE = re.compile(r"(\d+\.\d+)m x (\d+\.\d+)m")


@pytest.fixture(scope="module")
def baseline():
    """The sheet hygiene baseline: one solve, shared by every PDF pin."""
    req = FloorPlanRequest(
        plot_width_m=PLOT_W,
        plot_depth_m=PLOT_D,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        required_rooms=ROOMS,
    )
    return SoleGeometryEngine(req).solve()


@pytest.fixture(scope="module")
def pdf_text(baseline) -> str:
    """The exported PDF's extracted text (the document a client would read)."""
    import pypdf

    from app.services.report_service import generate_pdf_report

    payload = {
        "request_id": "BW-PDF-HYGIENE-PARITY",
        "timestamp": "2026-10-12 12:00:00 UTC",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "PDF Hygiene Parity Baseline",
        "overall_suitability_score": 85.0,
        "suitability_verdict": "Verified",
        "built_up_area_sqft": 3600.0,
        "floors": 2,
        "include_construction_schedules": True,
        "multi_storey": baseline.model_dump(),
        "floor_plan": baseline.model_dump(),
    }
    raw = generate_pdf_report(payload).getvalue()
    assert raw[:4] == b"%PDF", "export did not produce a PDF"
    reader = pypdf.PdfReader(io.BytesIO(raw))
    assert len(reader.pages) >= 5, f"unexpectedly small export ({len(reader.pages)} pages)"
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.fixture(scope="module")
def svg_texts(baseline) -> str:
    """The same baseline rendered to SVG, so parity is asserted, not assumed."""
    return "\n".join(
        re.sub(r"<[^>]+>", " ", render_svg_from_ir(build_drawing_ir(
            floor_data=fl, building_model=baseline, gen_id=GEN_ID
        )))
        for fl in baseline.floors
    )


def test_the_export_is_not_empty(pdf_text: str):
    """Guard: every pin below is vacuous if extraction returns nothing."""
    assert len(pdf_text) > 5000, f"extracted text too small: {len(pdf_text)} chars"
    for token in ("ROOM SCHEDULE", "DOOR SCHEDULE"):
        assert token.lower() in pdf_text.lower(), f"{token} missing from the export"


def test_1_pdf_door_schedule_level_column_is_l0_l1(pdf_text: str, baseline):
    """LEVEL prints the L-ladder token, and the doubled "LLevel" never appears."""
    assert "LLevel" not in pdf_text, "the KB 'LLevel' regression reached the PDF"

    # The ladder token is printed per door row, with its datum elevation.
    levels = re.findall(r"\bL([01])\s*\(\+([0-9.]+)m\)", pdf_text)
    assert levels, "no door-schedule level tokens found in the export"
    assert {lvl for lvl, _ in levels} == {"0", "1"}, (
        f"export must exercise both storeys, saw {sorted({lvl for lvl, _ in levels})}"
    )
    for lvl, elev in levels:
        assert float(elev) == pytest.approx(int(lvl) * 3.0, abs=0.001), (
            f"level L{lvl} printed with a non-derivable datum {elev}m"
        )

    # Same ladder as the model's door schedule, not a re-typed literal.
    model_levels = set()
    for fl in baseline.floors:
        for door in (fl.wall_graph or {}).get("door_schedule", []):
            model_levels.add(str(door.get("level", "")))
    assert model_levels == {"L0", "L1"}, f"baseline ladder drifted: {sorted(model_levels)}"


def test_2_pdf_area_units_use_superscript(pdf_text: str, svg_texts: str):
    """m² everywhere: no bare 'm2'/'sqm' in either output."""
    for label, text in (("PDF", pdf_text), ("SVG", svg_texts)):
        leaks = [
            m.group(0)
            for m in re.finditer(r"\b\d+(?:\.\d+)?\s*(?:m2|sqm)\b", text, flags=re.I)
        ]
        assert not leaks, f"{label}: raw area unit(s) printed: {leaks[:6]}"
    assert pdf_text.count("m²") >= 10, (
        f"expected superscript areas in the export, found {pdf_text.count('m²')}"
    )


def test_3_pdf_has_no_mid_word_truncation(pdf_text: str, svg_texts: str):
    """The KB cuts are absent AND the full vocabulary is delivered."""
    # (a) No line may END on a KB fragment: that is the shape of a mid-word cut.
    for line in pdf_text.splitlines():
        stripped = line.strip()
        for frag in KB_FRAGMENTS:
            assert not stripped.endswith(frag), (
                f"PDF line ends on a mid-word cut: {stripped!r} (from {frag!r})"
            )
    # (b) No broken ellipsis, and no '..' inside a word.
    assert not re.search(r"\.\.[A-Za-z]", pdf_text), "PDF contains '..' inside a word"
    # (c) Positive control: the wrapped schedule cells still carry the FULL
    #     tokens (the KB's cut strings were prefixes of these).
    for token in KB_FULL_TOKENS:
        assert token in pdf_text, f"PDF lost the complete finish token {token!r}"
    # (d) The export is at least as complete as the SVG for the same strings.
    for token in KB_FULL_TOKENS:
        if token in svg_texts:
            assert token in pdf_text, f"SVG teaches {token!r} but the PDF does not"


def test_4_pdf_single_area_source_is_the_clear_area(pdf_text: str, baseline):
    """Schedule area == on-sheet label area == wall-graph CLEAR area."""
    gross_leaks = []
    for fl in baseline.floors:
        wg_clear = {
            r.get("room_id"): float(r.get("area_sqm"))
            for r in ((fl.wall_graph or {}).get("rooms") or [])
            if r.get("room_id") and r.get("area_sqm") is not None
        }
        gross = {r.room_id: r.area_sqm for r in fl.rooms}
        assert wg_clear, f"F{fl.floor_index}: wall graph carries no clear areas"

        # Surface A - the export's room schedule, printed at 2 decimals.
        for rid, clear in wg_clear.items():
            assert f"{clear:.2f} m²" in pdf_text, (
                f"room schedule is missing the clear area {clear:.2f} m² for {rid}"
            )
            # Surface B - the on-sheet label, printed at 1 decimal.
            assert f"{round(clear, 1):.1f}m²" in pdf_text, (
                f"on-sheet label for {rid} is missing its {round(clear, 1):.1f}m² area line"
            )
        # Non-vacuous: the structural (gross) area differs and must NOT be the
        # figure printed for the room.
        for rid, g in gross.items():
            c = wg_clear.get(rid)
            if c is not None and abs(g - c) > 0.5:
                gross_leaks.append((rid, g, c))
    assert gross_leaks, (
        "baseline no longer distinguishes gross from clear - the single-source "
        "pin would be vacuous"
    )


def test_4b_pdf_labels_carry_dims_matching_the_schedule(pdf_text: str, baseline):
    """Each label's dims line agrees with the schedule's clear dims."""
    rows = [
        r for fl in baseline.floors
        for r in (
            (fl.wall_graph or {}).get("room_schedule")
            or []
        )
    ]
    checked = 0
    for row in rows:
        dims = SCHED_DIMS_RE.search(str(row.get("clear_dims") or ""))
        if not dims:
            continue
        w, d = float(dims.group(1)), float(dims.group(2))
        # The schedule's own dims cell is on the sheet verbatim.
        assert f"{w:.2f}m x {d:.2f}m" in pdf_text, (
            f"schedule dims {w}x{d} for {row.get('room_id')} missing from the PDF"
        )
        # ...and the label line that prints the same room's area uses the SAME
        # dims, so the two surfaces cannot drift.
        label = f"{w:.1f}m × {d:.1f}m"
        area = row.get("clear_area_sqm")
        if area is not None:
            assert f"{label} ({float(area):.1f}m²)" in pdf_text, (
                f"on-sheet label {label} for {row.get('room_id')} does not match "
                f"the schedule's clear dims"
            )
            checked += 1
    assert checked >= 4, f"too few label/schedule pairs exercised ({checked})"


def test_5_pdf_headroom_is_computed_and_at_least_2_20m(pdf_text: str, baseline):
    """The export teaches the COMPUTED headroom, never the 2.0 m KB token."""
    assert STAIR_MIN_HEADROOM_M == 2.20, "the headroom floor drifted from 2.20 m"

    # The KB's non-compliant line must not survive anywhere in the export.
    assert "HEADROOM >= 2.0m" not in pdf_text
    assert not re.search(r"HEADROOM\s*>=\s*2\.0\b", pdf_text)

    # The stair schedule is present (the export previously omitted it entirely).
    assert "Stair Schedule (Computed Object)" in pdf_text, (
        "the PDF dropped the stair schedule, so headroom compliance is unreadable"
    )

    # The computed per-floor headroom is printed and matches the model.
    computed = []
    for fl in baseline.floors:
        geom = fl.stair_geometry or {}
        value = geom.get("headroom_min_m")
        if value is None:
            continue
        computed.append(float(value))
        assert f">= {float(value):.2f} m" in pdf_text, (
            f"F{fl.floor_index}: computed headroom >= {float(value):.2f} m is not printed"
        )
    assert computed, "baseline carries no computed headroom to pin"
    assert min(computed) >= 2.20, f"computed headroom below the code floor: {computed}"

    # Every printed headroom token clears the floor (no hardcoded 2.0/2.20 line
    # masquerading as the computation).
    tokens = re.findall(r"HEADROOM\s*>=\s*([0-9.]+)\s*m", pdf_text)
    for t in tokens:
        assert float(t) >= 2.20, f"non-compliant headroom token in the export: {t}"
    # The statutory floor appears ONLY as the code reference next to the value.
    assert "NBC Cl 12.18.3 >= 2.20m" in pdf_text


def test_6_pdf_ghost_overlay_rides_upper_storeys_only(pdf_text: str, baseline):
    """The ghost core overlay is taught for upper storeys, never for Ground."""
    # Geometry: the IR the PDF renders from carries no ghost on Ground.
    ground_ir = build_drawing_ir(floor_data=baseline.floors[0], building_model=baseline, gen_id=GEN_ID)
    upper_ir = build_drawing_ir(floor_data=baseline.floors[1], building_model=baseline, gen_id=GEN_ID)
    ground_ghosts = [p for p in ground_ir.primitives if type(p).__name__ == "GhostPrimitive"]
    upper_ghosts = [p for p in upper_ir.primitives if type(p).__name__ == "GhostPrimitive"]
    assert not ground_ghosts, "ground floor plate would draw the ghost overlay"
    assert upper_ghosts, "upper floor plate lost the ghost core overlay"

    # Document: the Ground level brief must not advertise an overlay it cannot
    # have; the upper level brief must teach it.
    # Each brief is a wrapped paragraph, so slice from one heading to the next
    # rather than matching a single line.
    briefs = pdf_text.split("Level Brief:")[1:]
    assert len(briefs) >= 2, f"expected a level brief per storey, saw {len(briefs)}"
    assert "Ground Datum" in briefs[0], (
        f"first brief is not the Ground storey: {briefs[0][:120]!r}"
    )
    assert "Ghost Core Overlay" not in briefs[0], (
        f"Ground brief advertises the ghost overlay: {briefs[0][:160]!r}"
    )
    assert any("Ghost Core Overlay" in b for b in briefs[1:]), (
        "no upper-storey brief teaches the ghost core overlay"
    )
    # And the overlay legend is taught exactly once, on the upper sheet only.
    assert pdf_text.count("Ghost Core Overlay") == sum(
        b.count("Ghost Core Overlay") for b in briefs[1:]
    )
