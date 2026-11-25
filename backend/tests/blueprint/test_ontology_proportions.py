"""Proportion law as ontology data.

Pins the declarative layer that will enforce:

* every catalogued space has an ideal band, a hard ceiling and an overflow route;
* the ideal band is reachable at the type's own minimum area and clear width;
* fixture-fit rectangles obey the same minima and hard aspect band;
* split/adjunct targets exist, and every typology has a priority-ordered
  upgrade ladder plus labeled outdoor routing;
* the policy states that hard limits are absolute and records the ~2.5:1
  spine-corridor threshold.

No solver is exercised here: this is the data gate the solver must obey.
"""

from __future__ import annotations

import math

import pytest

from app.services.floorplan.ontology import (
    CITE_BATH,
    ONTOLOGY,
    PROPORTION_BANDS,
    PROPORTION_POLICY,
    TYPOLOGY_OUTDOOR_ROUTING,
    TYPOLOGY_PROFILES,
    TYPOLOGY_UPGRADE_LADDERS,
    UNIVERSAL_SPACE_CATALOG,
    FunctionType,
    HygieneType,
    OverflowAction,
    SpaceTypeSpec,
)

TYPOLOGIES = set(TYPOLOGY_PROFILES)


def _spec_for(id_: str, **overrides) -> SpaceTypeSpec:
    payload = dict(
        id=id_,
        name="Test",
        typologies=["T1_SINGLE_FAMILY"],
        function=FunctionType.SOCIAL,
        hygiene=HygieneType.CLEAN,
        min_area_sqm=10.0,
        min_width_m=2.0,
        max_aspect_ratio=2.0,
    )
    payload.update(overrides)
    return SpaceTypeSpec(**payload)


def test_band_catalog_covers_every_space_exactly_once():
    assert set(PROPORTION_BANDS) == set(UNIVERSAL_SPACE_CATALOG)
    assert len(PROPORTION_BANDS) == len(UNIVERSAL_SPACE_CATALOG)


def test_every_band_is_internally_coherent_and_cited():
    for sid, band in PROPORTION_BANDS.items():
        spec = UNIVERSAL_SPACE_CATALOG[sid]
        assert 1.0 <= band.ideal_aspect_max <= spec.max_aspect_ratio, sid
        assert band.area_ceiling_sqm > spec.min_area_sqm, sid
        assert band.citation.strip(), sid
        assert spec.proportion_citation == band.citation, sid
        assert spec.ideal_aspect_max == band.ideal_aspect_max, sid
        assert spec.area_ceiling_sqm == band.area_ceiling_sqm, sid


def test_ideal_band_is_reachable_at_the_type_minimum_area():
    """No type may declare an ideal proportion its own minimum cannot hold."""
    failures = []
    for sid, spec in UNIVERSAL_SPACE_CATALOG.items():
        # A rectangle at min area and ideal aspect must still honour min width.
        short = math.sqrt(spec.min_area_sqm / spec.ideal_aspect_max)
        if short + 1e-9 < spec.min_width_m:
            failures.append((sid, round(short, 3), spec.min_width_m, spec.ideal_aspect_max))
        if spec.min_area_sqm + 1e-9 < spec.min_width_m ** 2:
            failures.append((sid, "area<width^2", spec.min_area_sqm, spec.min_width_m))
    assert not failures, failures


def test_area_ceiling_exceeds_minimum_and_contains_the_fixture_envelope():
    for sid, spec in UNIVERSAL_SPACE_CATALOG.items():
        assert spec.area_ceiling_sqm > spec.min_area_sqm, sid
        if spec.fixture_min_width_m is not None:
            fixture_area = spec.fixture_min_width_m * spec.fixture_min_depth_m
            assert fixture_area <= spec.area_ceiling_sqm + 1e-9, sid


def test_fixture_minimums_obey_room_minima_and_hard_band():
    checked = 0
    for sid, spec in UNIVERSAL_SPACE_CATALOG.items():
        if spec.fixture_min_width_m is None:
            assert spec.fixture_min_depth_m is None, sid
            continue
        checked += 1
        short, long = sorted((spec.fixture_min_width_m, spec.fixture_min_depth_m))
        assert short + 1e-9 >= spec.min_width_m, sid
        assert short * long + 1e-9 >= spec.min_area_sqm, sid
        assert long / short <= spec.max_aspect_ratio + 1e-9, sid
    # Bathrooms, kitchens and utilities are the fixture-bearing families.
    assert checked >= 10, checked


def test_overflow_routes_are_executable():
    for sid, spec in UNIVERSAL_SPACE_CATALOG.items():
        for target in spec.split_into:
            assert target in UNIVERSAL_SPACE_CATALOG, (sid, target)
        if spec.overflow_action in (OverflowAction.SPLIT, OverflowAction.SPLIT_OR_ADJUNCT):
            assert spec.split_into, sid
        if spec.overflow_action in (OverflowAction.ADJUNCT, OverflowAction.SPLIT_OR_ADJUNCT):
            assert spec.adjunct_kinds, sid
        if spec.overflow_action == OverflowAction.CIRCULATION:
            assert not spec.split_into and not spec.adjunct_kinds, sid


def test_upgrade_ladders_are_priority_ordered_and_permitted():
    assert set(TYPOLOGY_UPGRADE_LADDERS) == TYPOLOGIES
    for typology, steps in TYPOLOGY_UPGRADE_LADDERS.items():
        priorities = [step.priority for step in steps]
        assert priorities == sorted(set(priorities)), typology
        for step in steps:
            assert (step.space_type_id is None) != (step.module is None), (typology, step.label)
            if step.space_type_id is not None:
                target = UNIVERSAL_SPACE_CATALOG[step.space_type_id]
                assert typology in target.typologies, (typology, step.space_type_id)
                assert step.min_surplus_sqm + 1e-9 >= target.min_area_sqm, step.label
            else:
                assert step.module == "dwelling_unit", (typology, step.module)
                assert step.min_surplus_sqm >= 41.0, "T2 unit needs carpet minimum + walls"


def test_every_typology_has_labeled_outdoor_routing():
    assert set(TYPOLOGY_OUTDOOR_ROUTING) == TYPOLOGIES
    for typology, routes in TYPOLOGY_OUTDOOR_ROUTING.items():
        priorities = [route.priority for route in routes]
        assert priorities == sorted(set(priorities)), typology
        assert all(route.label.strip() for route in routes), typology
        assert all(route.min_area_sqm > 0 for route in routes), typology
        kinds = {route.kind for route in routes}
        assert "planter" in kinds, typology
        for route in routes:
            if route.kind == "parking":
                assert route.ecs_per_patch and route.ecs_per_patch >= 1.0, typology
                assert route.min_area_sqm + 1e-9 >= 12.5 * route.ecs_per_patch, typology
            else:
                assert route.ecs_per_patch is None, typology


def test_policy_separates_hard_limits_from_the_ideal_band():
    assert PROPORTION_POLICY.hard_limits_absolute is True
    assert PROPORTION_POLICY.relaxation_requires_certificate_entry is True
    assert 0.0 < PROPORTION_POLICY.ideal_band_warn_threshold_pct <= 100.0
    assert PROPORTION_POLICY.spine_corridor_aspect_threshold == pytest.approx(2.50)
    assert "Neufert" in PROPORTION_POLICY.citation


def test_schema_rejects_a_band_that_breaks_the_hard_limit():
    with pytest.raises(ValueError):
        _spec_for("living", ideal_aspect_max=5.0)
    with pytest.raises(ValueError):
        _spec_for("living", area_ceiling_sqm=1.0)
    with pytest.raises(ValueError):
        _spec_for(
            "bath_1",
            fixture_min_width_m=1.0,
            fixture_min_depth_m=4.0,
            min_area_sqm=3.5,
            min_width_m=1.5,
            max_aspect_ratio=2.0,
        )


def test_new_store_and_wellness_types_carry_the_same_law():
    for sid in ("store", "wellness_room"):
        spec = ONTOLOGY.get_space(sid)
        assert spec is not None
        assert spec.ideal_aspect_max > 0
        assert spec.area_ceiling_sqm > spec.min_area_sqm
        band = ONTOLOGY.proportion_band(sid)
        assert band is not None and band.citation


def test_registry_accessors_resolve_aliases_and_typologies():
    assert ONTOLOGY.proportion_band("bath_1_F0").ideal_aspect_max == pytest.approx(1.50)
    assert ONTOLOGY.upgrade_ladder("apartment")[0].module == "dwelling_unit"
    assert ONTOLOGY.outdoor_routes("warehouse")[0].kind == "parking"
    assert CITE_BATH in ONTOLOGY.proportion_band("bath_1").citation
