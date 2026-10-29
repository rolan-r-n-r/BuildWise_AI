"""Geometry & coverage truth regressions.

Pinned to the audit register and to the probes that produced them:

  F01  probe_boundary_gen.log — a captured 108.5 x 89.1 m (9,661 m²) boundary
       produced an 8,632 m² footprint against a 5,796 m² cap, with a 8,553.8 m²
       dead corner and 78.24 m² of rooms.
  F02  "60 x 60, 60 % -> footprint 3,024 vs cap 2,160 (API)".
  F06  a coverage breach (coverage_within_limit / footprint_utilization) carried
       no warning.
  F21  status was unconditional, so an unplaceable brief still claimed "optimal".

The invariants these tests pin:
  1. The captured boundary - not the UI's clamped bbox - sets the plot area and
     the coverage ceiling, and it never 422s for a legitimately large site.
  2. The plate follows the programme and is HARD-capped by min(coverage, buildable).
     A 4-room brief on a hectare is a house, not an 8,632 m² slab.
  3. Rooms fill the plate: the ground floor's dead corner stays under 1.0 m².
  4. Every failed/limited land check is surfaced; a refusal names its numbers and
     never claims a clean status.
"""

import pytest

from app.schemas.floorplan import FloorPlanRequest, PlotPolygonModel
from app.services.floorplan.floorplan_service import generate_floor_plan

W, D = 108.479, 89.055  # the audited boundary (9,660.6 m²)
BOUNDARY_AREA = 9660.6
CAP_AT_60 = BOUNDARY_AREA * 0.60


def _boundary():
    return {
        "vertices": [[0.0, 0.0], [W, 0.0], [W, D], [0.0, D]],
        "shape_type": "rectangle",
        "area_sqm": BOUNDARY_AREA,
        "perimeter_m": 395.1,
        "bounding_box": [0.0, 0.0, W, D],
        "is_regular_rectangle": True,
    }


def _request(plot_w: float, plot_d: float) -> FloorPlanRequest:
    return FloorPlanRequest(
        plot_width_m=plot_w,
        plot_depth_m=plot_d,
        plot_polygon=_boundary(),
        required_rooms=["master_bed", "kitchen", "living", "bath_1"],
        vastu_strictness="high",
        building_typology="residential_single",
        quality_grade="standard",
        floors=1,
        built_up_area_sqft=2000,
        ground_coverage_ratio=0.6,
        ai_provider="mock",
        bypass_cache=True,
        seed="42",
    )


def test_captured_boundary_sets_the_coverage_ceiling_not_the_clamped_bbox():
    """The 9,661 m² boundary's cap is 5,796 m², never 60x60's 2,160 m².

    The request is accepted with the boundary's own bbox (the old schema clamped
    plot_width_m/plot_depth_m to 60 m and answered 422 for the true dims).
    """
    resp = generate_floor_plan(_request(W, D))
    report = resp.land_economics
    assert report is not None
    assert report.coverage_limit_area_sqm == pytest.approx(CAP_AT_60, abs=1.0)
    assert report.coverage_limit_area_sqm > 60.0 * 60.0 * 0.6 + 100.0, (
        "the ceiling must come from the captured boundary, not the clamped bbox"
    )


def test_programme_sized_plate_is_far_below_the_large_plot_cap():
    """A 4-room brief on a hectare is a house, not an 8,632 m² slab."""
    resp = generate_floor_plan(_request(60.0, 60.0))
    floors = resp.multi_storey.floors
    assert floors, "the audited brief must solve"
    plate = floors[0].envelope["area_sqm"]
    assert plate <= CAP_AT_60 + 1.0
    # The audited defect: 8,632 m² footprint for 78.24 m² of rooms.
    assert plate < 500.0, plate
    assert resp.land_economics.footprint_area_sqm == pytest.approx(plate, abs=0.5)


def test_rooms_fill_the_plate_and_dead_corner_stays_under_one_sqm():
    """The ground floor may not be mostly unassigned plate."""
    resp = generate_floor_plan(_request(60.0, 60.0))
    floor = resp.multi_storey.floors[0]
    plate = floor.envelope["area_sqm"]
    room_area = sum(r.area_sqm for r in floor.rooms)
    assert room_area / plate >= 0.85, (room_area, plate)
    report = resp.land_economics
    assert report.dead_corner_area_sqm <= 1.0, report.dead_corner_area_sqm
    assert report.certificate.checks.get("interior_dead_corners_zero") is True


def test_footprint_source_names_the_binding_constraint():
    """The report says WHY the plate is the size it is."""
    resp = generate_floor_plan(_request(60.0, 60.0))
    assert resp.land_economics.footprint_source in ("program", "coverage", "buildable")


def test_limited_land_checks_are_surfaced_not_silent():
    """A failing land check must produce a warning the client can render.

    At a deliberately binding 10 % cap the smallest plan the bands can draw
    (7.89 x 8.34 m, the stair/core minimum) still exceeds the 60 m2 ceiling.
    The engine must not hide that: it draws the fail-stamped plan, marks
    ``coverage_within_limit`` False and prints LAND-10 with BOTH numbers. A
    clean cap is covered by the 60 % tests above; this one pins the honesty
    path when the cap cannot be met at all.
    """
    tiny = PlotPolygonModel(
        vertices=[[-20.0, 0.0], [0.0, 0.0], [0.0, 30.0], [-20.0, 30.0]],
        shape_type="rectangle",
        area_sqm=600.0,
        perimeter_m=100.0,
        bounding_box=[-20.0, 0.0, 0.0, 30.0],
        is_regular_rectangle=True,
    )
    resp = generate_floor_plan(
        FloorPlanRequest(
            **{
                **_request(60.0, 60.0).model_dump(exclude={"plot_polygon"}),
                "plot_polygon": tiny,
                "floors": 2,
                "built_up_area_sqft": 6000,
                "ground_coverage_ratio": 0.10,
            }
        )
    )
    plate = resp.multi_storey.floors[0].envelope["area_sqm"]
    assert plate > 600.0 * 0.10, plate  # the minimum envelope cannot fit the cap
    assert resp.metrics.plot_coverage_pct > 10.0, resp.metrics.plot_coverage_pct
    land_rows = [w for w in (resp.warnings or []) if w.startswith("LAND-")]
    assert land_rows, resp.warnings
    assert any("coverage" in w.lower() and "exceeds" in w.lower() for w in land_rows), land_rows
    cert = resp.land_economics.certificate
    assert cert.checks.get("coverage_within_limit") is False


def test_unplaceable_brief_is_refused_with_numbers_and_never_optimal():
    """An 8 x 8 m plot cannot host 4 rooms at 60 % — refuse, don't pretend."""
    resp = generate_floor_plan(
        FloorPlanRequest(
            plot_width_m=8.0,
            plot_depth_m=8.0,
            required_rooms=["master_bed", "kitchen", "living", "bath_1"],
            vastu_strictness="high",
        )
    )
    assert resp.status == "failed"
    assert resp.unmet_requirements
    reasons = " ".join(u["reason"] for u in resp.unmet_requirements)
    assert "does not fit the statutory ground plate" in reasons, reasons
    # The refusal is machine-readable AND surfaced.
    assert any(w.startswith(("GEN-UNFIT", "GATE-FAIL")) for w in resp.warnings), resp.warnings
    assert resp.multi_storey.floors == []


def test_irregular_plate_uses_the_legal_ceiling_not_the_inscribed_rectangle():
    """The trapezoid buildable admits a 72 m² rectangle inside a 108 m² ceiling.

    Using the rectangle AS the ceiling made a 7 %-tight (legal) brief fail as a
    "statutory ceiling" refusal. It must solve, and the shortfall must be named.
    """
    poly = PlotPolygonModel(
        vertices=[(0.0, 0.0), (14.0, 0.0), (11.0, 16.0), (2.0, 16.0)],
        shape_type="polygon",
        is_regular_rectangle=False,
        area_sqm=0.0,
        perimeter_m=0.0,
        bounding_box=(0.0, 0.0, 14.0, 16.0),
    )
    resp = generate_floor_plan(
        FloorPlanRequest(
            plot_width_m=12.0,
            plot_depth_m=15.0,
            floors=1,
            building_typology="residential_single",
            vastu_strictness="high",
            bypass_cache=True,
            ai_provider="mock",
            seed="42",
            program_aware_footprint=True,
            plot_polygon=poly,
        )
    )
    assert resp.status != "failed", resp.unmet_requirements
    floors = resp.multi_storey.floors
    assert floors
    plate = floors[0].envelope["area_sqm"]
    # The legal ceiling (min(buildable, coverage x plot)) is larger than the
    # largest inscriable rectangle, and the plate stays inside it.
    assert plate <= 12.0 * 15.0 * 0.6 + 1.0
    assert any(w.startswith("PLATE-SHORT") for w in resp.warnings), resp.warnings


def test_programme_sized_plate_never_rounds_past_the_ceiling():
    """A plate on a 60x60 @60 % site must not round over the 2,160 m² cap.

    The cap is a ceiling, not a target: a hectare-scale plot is sized to its
    programme (LAND-11), so the plate can be far below the cap.  What must
    never happen is the footprint rounding ABOVE it.
    """
    resp = generate_floor_plan(
        FloorPlanRequest(
            plot_width_m=60.0,
            plot_depth_m=60.0,
            building_typology="residential_multi",
            floors=3,
            bypass_cache=True,
        )
    )
    cap = resp.land_economics.coverage_limit_area_sqm
    assert cap == pytest.approx(2160.0, abs=0.5)
    plate = resp.multi_storey.floors[0].envelope["area_sqm"]
    assert 0.0 < plate <= cap, (plate, cap)
    assert resp.land_economics.footprint_area_sqm == pytest.approx(plate, abs=0.5)


def test_site_preview_applies_the_coverage_ratio_it_is_given():
    """/api/site/preview must cap the preview footprint by the same ratio.

    The HUD used to show an unconstrained inscribed footprint (89 %) beside a
    60 % statutory cap because App.tsx never sent the ratio. The ratio now
    reaches the deterministic preview and it binds.
    """
    from app.schemas.request import BoundarySummary, PlotVertex
    from app.schemas.site_intelligence import SitePreviewRequest
    from app.services.site_preview_service import clear_preview_cache, compute_site_preview

    boundary = BoundarySummary(
        vertices=[
            PlotVertex(x=0.0, y=0.0),
            PlotVertex(x=20.0, y=0.0),
            PlotVertex(x=20.0, y=30.0),
            PlotVertex(x=0.0, y=30.0),
        ],
        origin_lat=12.9716,
        origin_lon=77.5946,
        shape_type="rectangle",
        area_sqm=600.0,
        perimeter_m=100.0,
        source="trace",
        frontage_edge_index=0,
    )
    clear_preview_cache()
    at_60 = compute_site_preview(SitePreviewRequest(boundary=boundary, ground_coverage_ratio=0.60))
    clear_preview_cache()
    at_75 = compute_site_preview(SitePreviewRequest(boundary=boundary, ground_coverage_ratio=0.75))

    assert at_60.plot["area_sqm"] == pytest.approx(600.0, abs=0.5)
    assert at_60.footprint["area_sqm"] <= 600.0 * 0.60 + 1.0
    assert at_75.footprint["area_sqm"] > at_60.footprint["area_sqm"], (
        "a higher allowed coverage must loosen the preview plate"
    )
    assert at_60.certificate["ground_coverage_limit_pct"] == pytest.approx(60.0, abs=0.5)
    assert at_75.certificate["ground_coverage_limit_pct"] == pytest.approx(75.0, abs=0.5)
    assert at_60.certificate["ground_coverage_actual_pct"] <= 60.5


def test_plate_width_clamp_does_not_discard_area():
    """A 6 x 24 m plot keeps its target area instead of losing it to the clamp.

    Clamping width and depth independently turned a 62.7 m² target into a
    48.1 m² plate, which then refused the brief for its own shortfall.
    """
    resp = generate_floor_plan(
        FloorPlanRequest(plot_width_m=6.0, plot_depth_m=24.0, floors=2)
    )
    floors = resp.multi_storey.floors
    if resp.status == "failed":
        # A 4.0 m buildable cannot carry the 2.10 m bath + 1.50 m spine + a
        # legal kitchen: the honest answer is a NAMED refusal, and that refusal
        # must quote the full clamped plate (the clamp regression this pin
        # exists for would show up as a 48 m² plate in the numbers).
        reasons = " ".join(str(u.get("reason") or "") for u in (resp.unmet_requirements or []))
        assert "does not fit the statutory ground plate" in reasons, reasons
        plate_text = reasons.split("ground plate (", 1)[1].split(" m²", 1)[0]
        assert float(plate_text) >= 55.0, reasons
        assert any(w.startswith("GEN-UNFIT") for w in resp.warnings), resp.warnings
        return
    assert len(floors) == 2
    plate = floors[0].envelope["area_sqm"]
    assert plate >= 55.0, plate
