"""Contracts: deterministic constrained placement, scoring, ranking."""

from __future__ import annotations

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.scheme import SchemeProfileId
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.scheme_solver import generate_ranked_schemes


def _t1(floors: int = 1) -> FloorPlanRequest:
    return FloorPlanRequest(
        plot_width_m=12,
        plot_depth_m=15,
        building_typology="residential_single",
        floors=floors,
        seed="42",
    )


def _assert_hard_constraints(alternative):
    m = alternative.metrics
    assert m.forbidden_violations == 0
    assert m.min_area_violations == 0
    assert m.min_width_violations == 0
    assert m.egress_connected is True
    assert alternative.floors
    for floor in alternative.floors:
        assert floor.rooms
        assert floor.svg_blueprint_cad
        assert floor.svg_blueprint_paper


def test_t1_single_storey_portfolio_is_feasible_and_hard_constrained():
    portfolio = generate_ranked_schemes(_t1(1))
    assert portfolio.typology == "T1_SINGLE_FAMILY"
    assert len(portfolio.alternatives) == 3
    assert {a.profile for a in portfolio.alternatives} == {
        SchemeProfileId.MAX_AREA,
        SchemeProfileId.MAX_VASTU,
        SchemeProfileId.MAX_LIGHT_VENT,
    }
    for alternative in portfolio.alternatives:
        assert alternative.feasible is True
        _assert_hard_constraints(alternative)
        assert alternative.metrics.land_use_efficiency_pct > 50.0
        assert alternative.metrics.circulation_ratio_pct > 0.0
    assert [a.rank for a in portfolio.alternatives] == [1, 2, 3]
    assert portfolio.selected_scheme_id == portfolio.alternatives[0].scheme_id


def test_t1_three_storey_portfolio_is_deterministic_and_ranked():
    first = generate_ranked_schemes(_t1(3))
    second = generate_ranked_schemes(_t1(3))
    assert first.model_dump() == second.model_dump()
    assert len(first.alternatives) == 3
    for alternative in first.alternatives:
        assert alternative.feasible is True
        _assert_hard_constraints(alternative)
        assert len(alternative.floors) == 3
        # Cores are locked and identical on every storey.
        core_x = {
            (r.x, r.y, r.width_m)
            for f in alternative.floors for r in f.rooms if r.is_vertical_core
        }
        assert len(core_x) == 1
    assert [a.rank for a in first.alternatives] == [1, 2, 3]
    assert first.alternatives[0].score >= first.alternatives[1].score >= first.alternatives[2].score


def test_profiles_produce_distinct_weighted_outcomes():
    portfolio = generate_ranked_schemes(_t1(3))
    by_profile = {a.profile: a for a in portfolio.alternatives}
    max_area = by_profile[SchemeProfileId.MAX_AREA]
    max_light = by_profile[SchemeProfileId.MAX_LIGHT_VENT]
    # Max Area uses the statutory-minimum spine; Max Light+Vent widens it.
    assert max_area.provenance["solver_version"] == "stage2-band-solver-v1"
    assert max_area.metrics.circulation_ratio_pct < max_light.metrics.circulation_ratio_pct
    assert len({a.score for a in portfolio.alternatives}) >= 2
    for alternative in portfolio.alternatives:
        total_weight = sum(alternative.weights.model_dump().values())
        assert abs(total_weight - 1.0) < 1e-9


_VOLATILE_KEYS = {"solver_timing_ms", "timing_ms", "generated_at", "evaluated_at"}


def _without_wall_clock(value):
    if isinstance(value, dict):
        return {k: _without_wall_clock(v) for k, v in value.items() if k not in _VOLATILE_KEYS}
    if isinstance(value, list):
        return [_without_wall_clock(v) for v in value]
    return value


def test_legacy_geometry_is_unchanged_when_portfolio_requested():
    request = _t1(1)
    legacy = generate_floor_plan(request)
    with_portfolio = generate_floor_plan(request.model_copy(update={
        "include_scheme_alternatives": True,
    }))
    assert legacy.scheme_alternatives is None
    assert with_portfolio.scheme_alternatives is not None
    assert len(with_portfolio.scheme_alternatives) == 3
    assert _without_wall_clock(legacy.multi_storey.floors[0].model_dump()) == _without_wall_clock(
        with_portfolio.multi_storey.floors[0].model_dump()
    )
    assert _without_wall_clock(legacy.rectangles.model_dump()) == _without_wall_clock(
        with_portfolio.rectangles.model_dump()
    )
    assert with_portfolio.params_snapshot["selected_scheme_id"] == with_portfolio.selected_scheme_id


def test_user_selection_is_recorded_in_provenance():
    base = _t1(1)
    portfolio = generate_ranked_schemes(base)
    chosen = portfolio.alternatives[-1].scheme_id

    selected = generate_ranked_schemes(base.model_copy(update={"selected_scheme_id": chosen}))
    assert selected.selected_scheme_id == chosen
    assert selected.selection_source == "user"
    assert selected.provenance["deterministic"] is True
    assert selected.provenance["request_hash"]

    invalid = generate_ranked_schemes(base.model_copy(update={"selected_scheme_id": "does-not-exist"}))
    assert invalid.selection_source == "default_rank_invalid_selection"
    assert invalid.selected_scheme_id == invalid.alternatives[0].scheme_id


def test_required_rooms_are_not_silently_dropped():
    request = FloorPlanRequest(
        plot_width_m=12,
        plot_depth_m=15,
        building_typology="residential_single",
        floors=1,
        required_rooms=["living", "kitchen", "master_bedroom"],
    )
    portfolio = generate_ranked_schemes(request)
    for alternative in portfolio.alternatives:
        present = {
            r.space_type_id
            for f in alternative.floors for r in f.rooms
            if r.space_type_id
        }
        assert {"living", "kitchen", "master_bed"} <= present
        assert alternative.feasible is True


def test_terrace_band_plate_reuses_the_validated_rule_fp_geometry():
    from app.schemas.floorplan import TerraceBandSpec

    request = FloorPlanRequest(
        plot_width_m=12,
        plot_depth_m=15,
        building_typology="residential_single",
        floors=2,
        terrace_bands={1: TerraceBandSpec(edge="N", depth_m=2.0)},
    )
    portfolio = generate_ranked_schemes(request)
    # Contract change: the band profiles cannot re-partition a terrace
    # band, so the portfolio offers the ONE validated layout WITH a named
    # disclosure instead of three relabelled clones.
    assert len(portfolio.alternatives) == 1
    assert "RULE-FP" in (portfolio.provenance.get("fallback_reason") or "")
    assert portfolio.provenance.get("no_material_alternative")
    for alternative in portfolio.alternatives:
        assert alternative.provenance["solver"] == "legacy_rule_fp_fallback"
        assert len(alternative.floors) == 2
        assert any("RULE-FP" in w for w in alternative.warnings)


def test_typology_matrix_reports_explicit_feasibility_or_deficit():
    cases = [
        ("T2_FAMILY_APARTMENT", 24, 30, 2),
        ("T3_LARGE_COMPLEX", 24, 30, 2),
        ("T4_WAREHOUSE", 24, 30, 1),
    ]
    for typology, width, depth, floors in cases:
        request = FloorPlanRequest(
            plot_width_m=width,
            plot_depth_m=depth,
            building_typology=typology,
            floors=floors,
        )
        portfolio = generate_ranked_schemes(request)
        # T2/T3/T4 are unit/office/bay programmes the T1 band profiles do not
        # Re-partition: one drawn alternative, named as such.
        assert len(portfolio.alternatives) == 1
        assert portfolio.provenance.get("no_material_alternative")
        for alternative in portfolio.alternatives:
            if alternative.feasible:
                _assert_hard_constraints(alternative)
            else:
                assert alternative.warnings
                assert any(
                    "infeasible" in w.lower() or "not placed" in w.lower()
                    for w in alternative.warnings
                )
        assert portfolio.selected_scheme_id
