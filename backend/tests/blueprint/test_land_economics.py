"""Contracts: land economics, programme fit and residual absorption."""

from __future__ import annotations

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.site_plan import PlotPolygonModel
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.site_geometry import approximate_curvilinear_polygon

ACUTE_TRAPEZOID = [(0.0, 0.0), (16.0, 0.0), (12.0, 14.0), (3.0, 14.0)]


def _t1(**overrides) -> FloorPlanRequest:
    data = dict(
        plot_width_m=12,
        plot_depth_m=15,
        building_typology="residential_single",
        floors=1,
    )
    data.update(overrides)
    return FloorPlanRequest(**data)


def test_land_economics_report_is_attached_and_matches_multi_storey():
    response = generate_floor_plan(_t1())
    report = response.land_economics
    assert report is not None
    assert response.multi_storey.land_economics is not None
    assert report.model_dump() == response.multi_storey.land_economics.model_dump()
    # A T1 plate follows the band stack, so it is programme-sized on a 12 x 15 m
    # plot (the 108 m2 coverage plate left the service row outside its catalogue
    # band and never certified).
    assert report.footprint_source == "program"
    assert report.footprint_area_sqm == pytest.approx(101.08, abs=0.1)
    assert report.program_needed_area_m2 > 0
    assert report.program_deficit_sqm == pytest.approx(0.0, abs=0.5)
    assert report.waste_pct == pytest.approx(0.0, abs=0.1)
    assert report.anonymous_outdoor_area_sqm == pytest.approx(0.0, abs=0.1)
    # The programme-sized T1 plate reports circulation 22.7 % against the
    # 12-20 % target band (LAND-03), so the certificate is an honest WARN.  The
    # invariants that make the plate legal are asserted directly instead of
    # pinning a PASS the geometry cannot claim.
    assert report.certificate.status == (
        "PASS" if all(report.certificate.checks.values()) else "WARN"
    )
    assert report.certificate.checks["program_fits_footprint"] is True
    assert report.certificate.checks["footprint_contained_in_buildable"] is True
    assert report.certificate.checks["coverage_within_limit"] is True
    assert report.certificate.checks["anonymous_outdoor_zero"] is True
    assert response.params_snapshot["land_economics_status"] == report.certificate.status
    assert response.params_snapshot["footprint_source"] == "program"
    assert response.params_snapshot["program_aware_footprint"] is False
    assert set(report.certificate.checks) >= {
        "footprint_contained_in_buildable",
        "coverage_within_limit",
        "program_fits_footprint",
        "circulation_within_12_20",
        "anonymous_outdoor_zero",
    }


def test_program_aware_footprint_shrinks_to_programme_and_labels_outdoor():
    response = generate_floor_plan(_t1(program_aware_footprint=True))
    report = response.land_economics
    footprint = response.site_plan.footprint
    assert report.footprint_source == "program"
    assert footprint.area_sqm < 108.0
    assert report.footprint_area_sqm == pytest.approx(footprint.area_sqm, abs=0.05)
    assert report.program_needed_area_m2 == pytest.approx(report.footprint_area_sqm, abs=1.0)
    assert report.program_deficit_sqm <= 0.5
    assert report.footprint_utilization_pct < 100.0
    assert report.outdoor_area_sqm > 0.0
    assert report.waste_pct == pytest.approx(0.0, abs=0.1)
    assert report.anonymous_outdoor_area_sqm == pytest.approx(0.0, abs=0.1)
    assert report.footprint_area_sqm + report.outdoor_area_sqm + report.wedge_area_sqm == pytest.approx(
        report.buildable_area_sqm, abs=1.0
    )
    assert report.footprint_utilization_pct >= 90.0
    assert report.certificate.checks["anonymous_outdoor_zero"] is True
    assert report.certificate.checks["footprint_utilization_90"] is True
    # Furniture gap is closed at solve time: the programme
    # plate now holds every catalogue set, so the certificate can pass honestly.
    assert report.furniture_fit_pct >= 80.0
    assert report.certificate.checks["furniture_fit"] is True
    assert report.certificate.status == "PASS"


# Wall-clock provenance keys (when the gate ran / how long the solve took) are
# measurement metadata, not solver output. Two identical solves legitimately
# differ by a clock tick, so equality is asserted on everything else at full
# depth - the same convention as space_engine_baseline.canonical_response and
# test_validation_gate.test_gate_determinism_seed42.
_VOLATILE_KEYS = {"solver_timing_ms", "timing_ms", "generated_at", "evaluated_at"}


def _without_wall_clock(value):
    if isinstance(value, dict):
        return {k: _without_wall_clock(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, list):
        return [_without_wall_clock(v) for v in value]
    return value


def test_program_aware_footprint_is_deterministic():
    first = generate_floor_plan(_t1(program_aware_footprint=True, seed="42"))
    second = generate_floor_plan(_t1(program_aware_footprint=True, seed="42"))
    assert first.site_plan.footprint.model_dump() == second.site_plan.footprint.model_dump()
    assert first.land_economics.model_dump() == second.land_economics.model_dump()
    assert _without_wall_clock(first.multi_storey.floors[0].model_dump()) == _without_wall_clock(
        second.multi_storey.floors[0].model_dump()
    ), "two identical solves differ in solver output (wall-clock keys excluded)"


def test_program_deficit_is_explicit_never_silent():
    # The acute trapezoid's inscribed footprint is 63 m² against a ~78 m²
    # programme; the deficit must be reported rather than squeezed.
    request = FloorPlanRequest(
        plot_width_m=16,
        plot_depth_m=14,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=PlotPolygonModel(
            vertices=ACUTE_TRAPEZOID,
            shape_type="trapezoid",
            is_regular_rectangle=False,
        ),
    )
    response = generate_floor_plan(request)
    report = response.land_economics
    assert report.program_deficit_sqm > 1.0
    assert report.certificate.checks["program_fits_footprint"] is False
    assert report.certificate.status == "FAIL"
    assert any("LAND-01" in warning for warning in response.warnings)
    assert any("Programme deficit" in warning for warning in report.warnings)


def test_residual_slivers_are_absorbed_or_labelled_on_irregular_plot():
    request = FloorPlanRequest(
        plot_width_m=16,
        plot_depth_m=14,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=PlotPolygonModel(
            vertices=ACUTE_TRAPEZOID,
            shape_type="trapezoid",
            is_regular_rectangle=False,
        ),
    )
    response = generate_floor_plan(request)
    report = response.land_economics
    assert report.anonymous_outdoor_area_sqm == pytest.approx(0.0, abs=0.5)
    assert report.waste_pct == pytest.approx(0.0, abs=0.5)
    assert report.certificate.checks["anonymous_outdoor_zero"] is True
    # Every absorbed piece is labelled, never an anonymous fragment.
    for sliver in report.slivers:
        assert sliver.absorbed_as in {"planter", "storage_closet"}
        assert sliver.area_sqm >= 1.0
    assert report.sliver_count == report.absorbed_residual_count
    # Disjoint accounting: the same square metre must not be both a wedge and
    # an outdoor fragment.
    assert report.footprint_area_sqm + report.outdoor_area_sqm + report.wedge_area_sqm == pytest.approx(
        report.buildable_area_sqm, abs=0.2
    )


def test_l_shape_dead_corner_is_absorbed_as_connected_storage():
    request = FloorPlanRequest(
        plot_width_m=14,
        plot_depth_m=14,
        floors=1,
        building_typology="residential_single",
        plot_polygon=PlotPolygonModel(
            vertices=[(0, 0), (14, 0), (14, 8), (8, 8), (8, 14), (0, 14)],
            shape_type="l_shape",
            is_regular_rectangle=False,
        ),
    )
    response = generate_floor_plan(request)
    report = response.land_economics
    assert report.dead_corner_area_sqm < 1.0
    assert report.certificate.checks["interior_dead_corners_zero"] is True
    storage = [r for r in response.multi_storey.floors[0].rooms if r.room_id.startswith("storage_dead_")]
    assert len(storage) == 1
    assert storage[0].area_sqm == pytest.approx(3.08, abs=0.05)
    storage_doors = [
        d for d in response.multi_storey.floors[0].doors
        if storage[0].room_id in (d.from_room, d.to_room)
    ]
    assert len(storage_doors) == 1
    assert response.multi_storey.mathematical_certificate["connectivity_bfs"] is True
    assert response.multi_storey.mathematical_certificate["is_valid"] is True
    assert any("LAND-07" in warning for warning in response.warnings)


def test_program_aware_irregular_plot_reports_inscribed_source():
    request = FloorPlanRequest(
        plot_width_m=16,
        plot_depth_m=14,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        program_aware_footprint=True,
        plot_polygon=PlotPolygonModel(
            vertices=ACUTE_TRAPEZOID,
            shape_type="trapezoid",
            is_regular_rectangle=False,
        ),
    )
    report = generate_floor_plan(request).land_economics
    assert report.program_aware_footprint is True
    assert report.footprint_source == "inscribed"
    assert report.program_deficit_sqm > 1.0
    assert any("LAND-06" in warning for warning in report.warnings)


def test_large_rectangular_program_aware_footprint_uses_the_override():
    response = generate_floor_plan(FloorPlanRequest(
        plot_width_m=24,
        plot_depth_m=30,
        building_typology="T4_WAREHOUSE",
        floors=2,
        program_aware_footprint=True,
    ))
    report = response.land_economics
    assert response.site_plan.buildable_area_sqm == pytest.approx(480.0, abs=0.1)
    assert report.footprint_area_sqm < 480.0
    assert report.footprint_area_sqm == pytest.approx(
        response.site_plan.footprint.area_sqm, abs=0.1
    )
    assert report.footprint_source == "program"
    assert report.program_deficit_sqm <= 0.5
    assert report.certificate.checks["coverage_within_limit"] is True


def test_rectangular_programme_yard_has_no_unlabelled_corners():
    response = generate_floor_plan(FloorPlanRequest(
        plot_width_m=12,
        plot_depth_m=15,
        building_typology="commercial",
        floors=1,
        program_aware_footprint=True,
    ))
    report = response.land_economics
    assert report.footprint_area_sqm < report.buildable_area_sqm
    assert report.outdoor_area_sqm > 0.0
    assert report.waste_area_sqm == pytest.approx(0.0, abs=0.05)
    assert report.anonymous_outdoor_area_sqm == pytest.approx(0.0, abs=0.05)
    assert report.footprint_area_sqm + report.outdoor_area_sqm + report.wedge_area_sqm == pytest.approx(
        report.buildable_area_sqm, abs=0.05
    )
    assert report.certificate.checks["anonymous_outdoor_zero"] is True


def test_curvilinear_residual_absorption_keeps_labelled_geometry():
    straight = [(0.0, 0.0), (20.0, 0.0), (20.0, 12.0)]
    arc = []
    import math
    for step in range(1, 50):
        angle = (math.pi / 2.0) * (step / 49.0)
        arc.append((round(12.0 + 8.0 * math.cos(angle), 3),
                    round(12.0 + 8.0 * math.sin(angle), 3)))
    is_ok, _diags, approx = approximate_curvilinear_polygon(straight + arc + [(0.0, 20.0)], tolerance=0.10)
    assert is_ok
    request = FloorPlanRequest(
        plot_width_m=20,
        plot_depth_m=20,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        plot_polygon=PlotPolygonModel(
            vertices=approx,
            shape_type="irregular",
            has_curved_edges=True,
            is_regular_rectangle=False,
        ),
    )
    response = generate_floor_plan(request)
    report = response.land_economics
    assert report.anonymous_outdoor_area_sqm == pytest.approx(0.0, abs=0.5)
    assert report.waste_pct == pytest.approx(0.0, abs=0.5)
    assert report.certificate.checks["anonymous_outdoor_zero"] is True


def test_program_aware_alias_and_default_envelope_unchanged():
    aliased = FloorPlanRequest.model_validate({
        "plotWidthM": 12,
        "plotDepthM": 15,
        "buildingTypology": "residential_single",
        "programAwareFootprint": True,
    })
    assert aliased.program_aware_footprint is True
    legacy = generate_floor_plan(_t1())
    # The default T1 envelope is the band stack (living 3.60 + stair box +
    # service tail 3.60 = 10.54 m deep), not the retired 9.60 x 11.25 m coverage
    # plate. The alias contract still holds: parsing the camelCase key does not
    # itself move the default envelope.
    assert legacy.multi_storey.floors[0].envelope["width"] == pytest.approx(9.59, abs=0.02)
    assert legacy.multi_storey.floors[0].envelope["depth"] == pytest.approx(10.54, abs=0.02)
    assert legacy.multi_storey.floors[0].envelope["area_sqm"] <= 12.0 * 15.0 * 0.60 + 0.1
