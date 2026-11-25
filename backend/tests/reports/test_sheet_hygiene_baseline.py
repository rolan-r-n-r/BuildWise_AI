"""
test_sheet_hygiene_baseline.py - the six sheet-hygiene invariants
==================================================================
Pins all six sheet-hygiene invariants on ONE fresh, reproducible
baseline: a 16.1 x 19.3 m plot, G+1, T1 single-family.

  1. Door schedule LEVEL column reads the L0/L1 ladder - never "LLevel 0".
  2. Areas print with the superscript m² - never a bare "m2"/"sqm".
  3. No mid-word truncation. The baseline showed cuts inside a word.
     An ellipsis may only ever be a ".." TAIL after a complete word.
  4. ONE area source across all three surfaces: on-sheet room label area ==
     ROOM SCHEDULE area == the clear area the viewer's legend chip resolves
     (the room model's `area_sqm` is the GROSS area and must not leak here).
  5. Computed headroom >= 2.20 m (NBC statutory minimum).
  6. The ghost overlay rides upper floors only - never the ground floor,
     whose anchor core is already drawn on the sheet.
"""

import re

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.drawing_ir import _ellipsize_str, build_drawing_ir, render_svg_from_ir
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.living_quality import STAIR_MIN_HEADROOM_M
from app.services.floorplan.wall_graph import (
    FINISH_GRADE_TIERS,
    FINISH_ZONES_STANDARD,
    resolve_finish,
)

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


@pytest.fixture(scope="module")
def baseline():
    """The sheet hygiene baseline: one solve, shared by all six pins."""
    req = FloorPlanRequest(
        plot_width_m=PLOT_W,
        plot_depth_m=PLOT_D,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        required_rooms=ROOMS,
    )
    return SoleGeometryEngine(req).solve()


def _ir(model, floor):
    return build_drawing_ir(floor_data=floor, building_model=model, gen_id=GEN_ID)


def _sheet_text(model, floor) -> str:
    return re.sub(r"<[^>]+>", " ", render_svg_from_ir(_ir(model, floor)))


def test_1_door_schedule_level_column_is_l0_l1(baseline):
    """LEVEL prints L0/L1 - the KB regression was a doubled "LLevel 0"."""
    seen = set()
    for fl in baseline.floors:
        for door in (fl.wall_graph or {}).get("door_schedule", []):
            level = str(door.get("level", ""))
            assert level in ("L0", "L1"), f"door {door.get('tag')} level {level!r} off-ladder"
            seen.add(level)
        txt = _sheet_text(baseline, fl)
        assert "LLevel" not in txt, f"F{fl.floor_index}: 'LLevel' leaked onto the sheet"
        assert re.search(r"\bL[01]\b", txt), f"F{fl.floor_index}: no L-ladder level printed"
    assert seen == {"L0", "L1"}, f"baseline must exercise both levels, saw {sorted(seen)}"


def test_2_area_units_use_superscript(baseline):
    """m² everywhere; a bare 'm2'/'sqm' is a KB-baseline violation."""
    for fl in baseline.floors:
        txt = _sheet_text(baseline, fl)
        leaks = [m.group(0) for m in re.finditer(r"\b\d+(?:\.\d+)?\s*(?:m2|sqm)\b", txt, flags=re.I)]
        assert not leaks, f"F{fl.floor_index}: raw area unit(s) on the sheet: {leaks[:4]}"
        assert txt.count("m²") >= 5, f"F{fl.floor_index}: expected superscript m² labels"


def test_3_no_mid_word_truncation(baseline):
    """Every ellipsis is a tail after a complete word - in both directions."""
    # (a) Property: the fitter is word-aware at EVERY budget, over the whole
    #     reachable vocabulary (room names + both finish tiers).
    vocabulary = set()
    for fl in baseline.floors:
        for r in fl.rooms:
            vocabulary.add(r.room_name)
    for zone in list(FINISH_ZONES_STANDARD.values()) + [
        v for tier in FINISH_GRADE_TIERS.values() for v in tier.values()
    ]:
        if isinstance(zone, str):
            vocabulary.add(zone)
    assert len(vocabulary) > 10, "vocabulary probe found too few strings to be meaningful"
    for s in sorted(vocabulary):
        for budget in range(6, 60):
            out = _ellipsize_str(s, budget)
            if out == s:
                continue
            assert out.endswith(".."), f"truncated without a marker: {out!r}"
            visible = out[:-2].rstrip()
            # The visible head must be a prefix of the source that ended on a
            # word boundary (i.e. the next source char is a space) - or, for a
            # single overlong token, the source has no space to fall back to.
            if visible and len(visible) < len(s):
                nxt = s[len(visible)]
                assert nxt == " " or " " not in s[: len(visible)], (
                    f"mid-word cut: {s!r} @{budget} -> {out!r}"
                )

    # (b) The finish vocabulary the KB showed truncated is delivered in FULL by
    #     the data surface. (The label fitter is allowed to shorten a LABEL at a
    #     word boundary; a schedule row may never carry a cut string.)
    for fl in baseline.floors:
        for row in _ir(baseline, fl).room_schedule:
            fin = str(row.get("finish_zone", ""))
            assert fin, f"schedule row {row.get('room_id')} carries no finish_zone"
            for frag in KB_FRAGMENTS:
                assert not fin.endswith(frag), f"schedule finish truncated: {fin!r}"

    # (c) And they are absent from the rendered sheets themselves.
    for fl in baseline.floors:
        txt = _sheet_text(baseline, fl)
        for frag in KB_FRAGMENTS:
            assert frag not in txt, f"F{fl.floor_index}: KB fragment {frag!r} on the sheet"
        assert not re.search(r"\.\.[A-Za-z]", txt), f"F{fl.floor_index}: '..' inside a word"
        for m in re.finditer(r"[A-Za-z]{2,}\.\.", txt):
            assert len(m.group(0)[:-2]) >= 2, f"degenerate ellipsis {m.group(0)!r}"

    # (d) Positive control: the finish vocabulary that the KB cut is stored in
    #     FULL (the cut was a render-time artefact, never a data one).
    bath_finish = resolve_finish("Common Bath", "bath_1_F0", "standard")
    assert "Anti-Skid Ceramic Tile R10 + Full Height Dado" == bath_finish, (
        f"finish vocabulary drifted: {bath_finish!r}"
    )


def test_4_single_area_source_across_three_surfaces(baseline):
    """On-sheet label == ROOM SCHEDULE == the legend chip's clear area."""
    for fl in baseline.floors:
        ir = _ir(baseline, fl)
        wg = fl.wall_graph or {}
        clear_by_room = {
            r.get("room_id"): float(r.get("area_sqm"))
            for r in (wg.get("rooms") or [])
            if r.get("room_id") and r.get("area_sqm") is not None
        }
        assert clear_by_room, f"F{fl.floor_index}: wall graph carries no clear areas"
        txt = _sheet_text(baseline, fl)

        # Surface 2 - the ROOM SCHEDULE area column (printed at 1 decimal).
        for row in ir.room_schedule:
            rid = row.get("room_id")
            clear = row.get("clear_area_sqm")
            assert clear is not None, f"schedule row {rid} has no clear_area_sqm"
            assert abs(float(clear) - clear_by_room[rid]) < 0.005, (
                f"schedule area {clear} != wall-graph clear {clear_by_room[rid]} for {rid}"
            )
            assert f"{float(clear):.1f}m²" in txt, (
                f"F{fl.floor_index}: schedule area {float(clear):.1f}m² for {rid} is not on the sheet"
            )

        # Surface 1 - the on-sheet room label, parsed off the rendered sheet.
        label_areas = {float(m) for m in re.findall(r"(\d+\.\d)m²", txt)}
        for rid, clear in clear_by_room.items():
            assert round(clear, 1) in label_areas, (
                f"F{fl.floor_index}: on-sheet label for {rid} is missing {round(clear, 1)}m²"
            )

        # Surface 3 - the viewer's legend chip resolves the clear area from
        # these same schedule rows (BlueprintViewer.currentPlacements).
        for row in ir.room_schedule:
            rid = row.get("room_id")
            assert float(row.get("clear_area_sqm")) == clear_by_room[rid], (
                f"legend chip source for {rid} drifted from the drawing"
            )

        # The chip must be PINNED to clear, not to gross: prove the two differ.
        gross = {r.room_id: r.area_sqm for r in fl.rooms}
        diverged = [
            rid
            for rid, g in gross.items()
            if rid in clear_by_room and abs(g - clear_by_room[rid]) > 0.02
        ]
        assert diverged, (
            "baseline no longer distinguishes gross from clear area - the "
            "single-source pin would be vacuous"
        )


def test_5_headroom_token_at_least_2_20m(baseline):
    """Every computed headroom token resolves to >= 2.20 m clear."""
    assert STAIR_MIN_HEADROOM_M == 2.20, "the headroom floor drifted from 2.20 m"
    tokens = []
    for fl in baseline.floors:
        geom = fl.stair_geometry or {}
        notes = [v for k, v in geom.items() if k.endswith("headroom_note") and isinstance(v, str)]
        notes += [
            str(r.get("headroom_note"))
            for r in (geom.get("stair_schedule") or [])
            if isinstance(r, dict) and r.get("headroom_note")
        ]
        for note in notes:
            m = re.search(r"HEADROOM\s*>=\s*([0-9.]+)\s*m", note)
            assert m, f"unparsable headroom token {note!r}"
            value = float(m.group(1))
            assert value >= 2.20, f"headroom token {note!r} violates the 2.20 m floor"
            tokens.append(value)
    # The KB's violating 2.0 m line must not survive anywhere on the sheets.
    for fl in baseline.floors:
        txt = _sheet_text(baseline, fl)
        assert "HEADROOM >= 2.0m" not in txt, f"F{fl.floor_index}: KB 2.0 m headroom line"
    assert tokens and min(tokens) >= 2.20, f"no headroom token was exercised ({tokens})"


LABEL_DIMS_RE = re.compile(r"(\d+\.\d)m × (\d+\.\d)m \((\d+\.\d)m²\)")
SCHED_DIMS_RE = re.compile(r"(\d+\.\d+)m x (\d+\.\d+)m")

# The four rooms whose KB on-sheet labels carried dims but NO area line,
# mapped to the room_ids this engine assigns them on Ground.
KB_AREA_LESS_ROOMS = {
    "Dining Area": "dining_F0",
    "Staircase": "core_staircase_primary_F0",
    "Foyer": "lobby_spine_F0",
    "Guest Bath": "bath_1_F0",
}


def test_7_bonus_every_room_label_carries_its_area_line(baseline):
    """BONUS DEFECT: the KB sheet showed Dining/Staircase/Foyer/Guest Bath with
    dims but no "(X.Xm²)". Every label now carries its line - and that line is
    the CLEAR area from the same single source as the schedule."""
    for fl in baseline.floors:
        ir = _ir(baseline, fl)
        wg_clear = {
            r.get("room_id"): r for r in ((fl.wall_graph or {}).get("rooms") or [])
        }
        gross = {r.room_id: r.area_sqm for r in fl.rooms}
        labels = [
            p for p in ir.primitives
            if type(p).__name__ == "TextPrimitive" and not p.room_tag_circle
        ]
        badges = [
            p.room_tag_circle["room_idx"] for p in ir.primitives
            if type(p).__name__ == "TextPrimitive" and p.room_tag_circle
        ]
        assert labels, f"F{fl.floor_index}: no on-sheet room labels rendered"

        by_area = {round(float(r["clear_area_sqm"]), 1): r for r in ir.room_schedule}
        for p in labels:
            m = LABEL_DIMS_RE.search(p.dims_str or "")
            assert m, (
                f"F{fl.floor_index}: label {p.text!r} carries dims without an area "
                f"line ({p.dims_str!r}) - the KB bonus defect"
            )
            lw, ld, larea = (float(g) for g in m.groups())

            # (a) The area line is arithmetically true of its own dims (guards
            #     against the KB's stale "8.5m x 7.5m (64.2m²)").
            assert abs(lw * ld - larea) <= 0.05 * (lw + ld) + 0.1, (
                f"F{fl.floor_index}: label {p.text!r} dims {lw}x{ld} do not match "
                f"its area {larea}m²"
            )

            # (b) It resolves to exactly one ROOM SCHEDULE row, and the dims text
            #     agrees with that row's clear dims to the printed decimal.
            row = by_area.get(round(larea, 1))
            assert row is not None, (
                f"F{fl.floor_index}: label {p.text!r} area {larea}m² has no schedule row"
            )
            sm = SCHED_DIMS_RE.search(str(row.get("clear_dims") or ""))
            assert sm, f"schedule row {row.get('room_id')} has unparsable clear_dims"
            sw, sd = float(sm.group(1)), float(sm.group(2))
            assert abs(lw - sw) < 0.051 and abs(ld - sd) < 0.051, (
                f"F{fl.floor_index}: label {p.text!r} prints {lw}x{ld} but the schedule "
                f"prints {sw}x{sd} for {row.get('room_id')} - the KB conflation"
            )

            # (c) The printed area is CLEAR, never the gross/structural area.
            rid = row.get("room_id")
            g = gross.get(rid)
            if g is not None and abs(g - larea) > 0.5:
                assert abs(float(row["clear_area_sqm"]) - larea) <= 0.051, (
                    f"F{fl.floor_index}: label {p.text!r} area {larea}m² is not the "
                    f"wall-graph clear area for {rid}"
                )
                cw = wg_clear.get(rid, {}).get("width_m")
                if cw is not None:
                    assert abs(cw - lw) < 0.051, (
                        f"F{fl.floor_index}: label {p.text!r} width {lw} != clear {cw}"
                    )

        # (d) Full coverage: every room on the floor is EITHER a label carrying
        #     its area line OR a numbered badge whose index resolves to a
        #     schedule row that itself carries the clear dims + area.
        assert len(labels) + len(badges) == len(ir.room_schedule), (
            f"F{fl.floor_index}: {len(labels)} labels + {len(badges)} badges != "
            f"{len(ir.room_schedule)} schedule rows - a room is unrepresented"
        )
        by_number = {
            int(r.get("room_number")): r for r in ir.room_schedule
            if r.get("room_number") is not None
        }
        for idx in badges:
            row = by_number.get(int(idx))
            assert row is not None, f"F{fl.floor_index}: badge #{idx} has no schedule row"
            assert row.get("clear_dimensions") and row.get("clear_area_sqm"), (
                f"F{fl.floor_index}: badge #{idx} ({row.get('room_id')}) resolves to a "
                "schedule row without clear dims/area"
            )
    # (e) The four rooms the KB drew with dims but no area line carry one now.
    #     Resolved by room_id (labels may print an abbreviated name), so the
    #     assertion keys on the schedule row, not on the label's wording.
    ground = _ir(baseline, baseline.floors[0])
    rows = {r.get("room_id"): r for r in ground.room_schedule}
    ground_labels = [
        p for p in ground.primitives
        if type(p).__name__ == "TextPrimitive" and not p.room_tag_circle
    ]
    for kb_name, rid in KB_AREA_LESS_ROOMS.items():
        row = rows.get(rid)
        assert row is not None, f"Ground sheet has no {kb_name} schedule row ({rid})"
        area = float(row["clear_area_sqm"])
        hit = [p for p in ground_labels if f"({area:.1f}m²)" in (p.dims_str or "")]
        assert hit, (
            f"Ground {kb_name} label still lacks its (X.Xm²) area line "
            f"(expected {area:.1f}m²)"
        )
        dims = SCHED_DIMS_RE.search(str(row.get("clear_dims") or ""))
        assert dims, f"Ground {kb_name} schedule row has unparsable clear_dims"
        assert f"{float(dims.group(1)):.1f}m × {float(dims.group(2)):.1f}m" in hit[0].dims_str, (
            f"Ground {kb_name} label dims {hit[0].dims_str!r} diverge from the "
            f"schedule's clear dims {row.get('clear_dims')!r}"
        )


def test_6_ghost_overlay_only_above_ground(baseline):
    """The ghost anchor overlay rides upper floors only."""
    ground = _ir(baseline, baseline.floors[0])
    upper = _ir(baseline, baseline.floors[1])
    ground_ghosts = [p for p in ground.primitives if type(p).__name__ == "GhostPrimitive"]
    upper_ghosts = [p for p in upper.primitives if type(p).__name__ == "GhostPrimitive"]
    assert not ground_ghosts, (
        "ground floor must not carry the ghost overlay (its anchor core is on the sheet)"
    )
    assert upper_ghosts, "upper floor sheet lacks the ghost core overlay"
    assert "ghost" in _sheet_text(baseline, baseline.floors[1]).lower()

    # And the rendered sheet carries the machine-readable switch the viewer and
    # the ghost-core toggle key on: false on Ground, true on F1+.
    for fl in baseline.floors:
        svg = render_svg_from_ir(_ir(baseline, fl))
        expected = "false" if fl.floor_index == 0 else "true"
        assert f'data-ghost-overlay="{expected}"' in svg, (
            f"F{fl.floor_index}: data-ghost-overlay should be {expected}"
        )
