"""Ontology contract tests.

Pins the semantics layer as DATA, not solver code:
  * every space carries zone / hygiene class / orientation / furniture set;
  * the relation algebra reproduces an independent expected matrix for ALL pairs;
  * the vertical law (wet alignment, core continuity, T4 mezzanine) is explicit;
  * T2 unit + shared core/parking and T4 industrial chain/wet points are complete.
"""

from __future__ import annotations

import pytest

from app.services.floorplan.ontology import (
    EXPLICIT_OVERRIDES,
    ONTOLOGY,
    EgressRole,
    FireHazard,
    FloorLoad,
    FunctionType,
    HygieneClass,
    HygieneType,
    OntologyRegistry,
    PublicAccess,
    RelationType,
    SecurityLevel,
    ServiceSide,
    SpaceTypeSpec,
    SpaceZone,
    VisitorDepth,
)

VASTU_DIRS = {"N", "NE", "E", "SE", "S", "SW", "W", "NW", "CENTER"}
CANONICAL_TYPOLOGIES = {
    "T1_SINGLE_FAMILY",
    "T2_FAMILY_APARTMENT",
    "T3_LARGE_COMPLEX",
    "T4_WAREHOUSE",
}


# ---------------------------------------------------------------------------
# Schema / data completeness
# ---------------------------------------------------------------------------

def test_every_space_has_complete_semantics():
    assert len(ONTOLOGY.all_spaces) >= 50
    for spec in ONTOLOGY.all_spaces.values():
        assert spec.zone in SpaceZone, spec.id
        assert spec.hygiene_class in HygieneClass, spec.id
        assert spec.min_area_sqm > 0, spec.id
        assert spec.min_width_m > 0, spec.id
        assert spec.max_aspect_ratio > 0, spec.id
        assert spec.clear_area_basis in ("clear_face", "carpet", "gross"), spec.id
        assert spec.typologies and set(spec.typologies) <= CANONICAL_TYPOLOGIES, spec.id
        assert set(spec.vastu_zone_weights) <= VASTU_DIRS, spec.id
        assert set(spec.orientation_preference) <= VASTU_DIRS, spec.id
        assert set(spec.orientation_avoid) <= VASTU_DIRS, spec.id
        assert not (set(spec.orientation_preference) & set(spec.orientation_avoid)), spec.id
        assert spec.furniture_set == list(dict.fromkeys(spec.furniture_set)), spec.id


def test_habitable_spaces_declare_a_furniture_set():
    for spec in ONTOLOGY.all_spaces.values():
        if spec.zone in (SpaceZone.PUBLIC, SpaceZone.PRIVATE):
            assert spec.furniture_set, f"habitable space {spec.id} has no furniture set"
    assert ONTOLOGY.get_space("kitchen").furniture_set == [
        "kitchen_cooktop", "kitchen_sink", "kitchen_fridge",
    ]
    assert "bed_king" in ONTOLOGY.get_space("master_bed").furniture_set


def test_semantic_classes_match_the_canonical_examples():
    kitchen = ONTOLOGY.get_space("kitchen")
    assert kitchen.zone == SpaceZone.SERVICE
    assert kitchen.hygiene_class == HygieneClass.COOKING
    assert kitchen.orientation_avoid and "NE" in kitchen.orientation_avoid

    puja = ONTOLOGY.get_space("puja")
    assert puja.zone == SpaceZone.PRIVATE
    assert puja.hygiene_class == HygieneClass.SACRED

    dining = ONTOLOGY.get_space("dining")
    assert dining.zone == SpaceZone.PUBLIC
    assert dining.hygiene_class == HygieneClass.EATING

    server = ONTOLOGY.get_space("server_room")
    assert server.hygiene_class == HygieneClass.TECHNICAL

    bath = ONTOLOGY.get_space("bath_1")
    assert bath.hygiene_class == HygieneClass.WET
    assert bath.zone == SpaceZone.SERVICE

    study = ONTOLOGY.get_space("study")
    assert study.zone == SpaceZone.PRIVATE

    # New T4 wet point and T3 pantry are real catalogue entries.
    assert ONTOLOGY.get_space("washdown_point").hygiene_class == HygieneClass.WET
    assert ONTOLOGY.get_space("pantry").hygiene_class == HygieneClass.WET


def test_schema_rejects_invalid_data():
    with pytest.raises(ValueError):
        SpaceTypeSpec(
            id="bad_min_area", name="Bad", typologies=["T1_SINGLE_FAMILY"],
            function=FunctionType.SOCIAL, hygiene=HygieneType.CLEAN,
            min_area_sqm=0.0, min_width_m=1.0,
        )
    with pytest.raises(ValueError):
        SpaceTypeSpec(
            id="bad_typology", name="Bad", typologies=["T9_UNKNOWN"],
            function=FunctionType.SOCIAL, hygiene=HygieneType.CLEAN,
            min_area_sqm=1.0, min_width_m=1.0,
        )
    with pytest.raises(ValueError):
        SpaceTypeSpec(
            id="bad_vastu", name="Bad", typologies=["T1_SINGLE_FAMILY"],
            function=FunctionType.SOCIAL, hygiene=HygieneType.CLEAN,
            min_area_sqm=1.0, min_width_m=1.0,
            vastu_zone_weights={"NORTH": 1.0},
        )


# ---------------------------------------------------------------------------
# Derived relation matrix: implementation == independent expectation
# ---------------------------------------------------------------------------

def _expected_rule_ids(a: SpaceTypeSpec, b: SpaceTypeSpec) -> set[str]:
    """Independent restatement of the attribute algebra in the Appendix spec."""
    rules: set[str] = set()

    # 1. foul vs sacred
    if (a.hygiene == HygieneType.FOUL and b.hygiene == HygieneType.SACRED) or (
        b.hygiene == HygieneType.FOUL and a.hygiene == HygieneType.SACRED
    ):
        rules |= {
            "HYG-01-FOUL-SACRED-WALL",
            "HYG-01-FOUL-SACRED-DOOR",
            "HYG-01-FOUL-SACRED-ABOVE",
        }

    # 2. foul / odor >= 2 vs food & social
    food_social = {
        FunctionType.COOKING, FunctionType.EATING,
        FunctionType.RECEPTION, FunctionType.MEETING,
    }
    a_foul = a.hygiene == HygieneType.FOUL or (
        a.odor_emit >= 2 and a.function != FunctionType.COOKING
    )
    b_foul = b.hygiene == HygieneType.FOUL or (
        b.odor_emit >= 2 and b.function != FunctionType.COOKING
    )
    if (a_foul and b.function in food_social) or (b_foul and a.function in food_social):
        rules |= {"HYG-02-FOUL-FOOD-WALL", "HYG-02-FOUL-FOOD-DOOR"}

    # 3. wet vs technical / secure
    a_wet = a.hygiene in (HygieneType.WET, HygieneType.FOUL) or a.moisture_emit >= 2
    b_wet = b.hygiene in (HygieneType.WET, HygieneType.FOUL) or b.moisture_emit >= 2
    a_tech = a.function == FunctionType.TECHNICAL or a.security == SecurityLevel.SECURE
    b_tech = b.function == FunctionType.TECHNICAL or b.security == SecurityLevel.SECURE
    if (a_wet and b_tech) or (b_wet and a_tech):
        rules |= {"SAF-01-WET-TECH-WALL", "SAF-01-WET-TECH-ABOVE"}

    # 4. noise emitter vs sensitive
    if (a.noise_emit >= 2 and b.noise_sensitive >= 2) or (
        b.noise_emit >= 2 and a.noise_sensitive >= 2
    ):
        rules.add("NOI-01-EMIT-SENSITIVE-SEP")

    # 4b. quiet vs social
    social = {FunctionType.SOCIAL, FunctionType.RECEPTION, FunctionType.MEETING}
    if (a.noise_sensitive >= 2 and b.function in social) or (
        b.noise_sensitive >= 2 and a.function in social
    ):
        rules.add("NOI-02-QUIET-SOCIAL-SEP")

    # 5. cooking vs eating
    if (a.function == FunctionType.COOKING and b.function == FunctionType.EATING) or (
        b.function == FunctionType.COOKING and a.function == FunctionType.EATING
    ):
        rules.add("FUNC-01-COOK-EAT-ADJ")

    # 6. reception vs front circulation
    if (
        a.function == FunctionType.RECEPTION
        and b.function == FunctionType.CIRCULATION
        and b.visitor_depth == VisitorDepth.FRONT
    ) or (
        b.function == FunctionType.RECEPTION
        and a.function == FunctionType.CIRCULATION
        and a.visitor_depth == VisitorDepth.FRONT
    ):
        rules.add("ACC-01-RECEPTION-FRONT-ADJ")

    # 7. loading vs dispatch
    if (a.function == FunctionType.LOADING and b.id == "dispatch") or (
        b.function == FunctionType.LOADING and a.id == "dispatch"
    ):
        rules.add("LOG-01-LOAD-DISPATCH-ADJ")

    # 8. dispatch vs storage
    if (a.id == "dispatch" and b.function == FunctionType.STORAGE) or (
        b.id == "dispatch" and a.function == FunctionType.STORAGE
    ):
        rules.add("LOG-02-DISPATCH-STORAGE-ADJ")

    # 9. core vs lobby
    if (a.is_vertical_core and b.function == FunctionType.CIRCULATION and not b.is_vertical_core) or (
        b.is_vertical_core and a.function == FunctionType.CIRCULATION and not a.is_vertical_core
    ):
        rules.add("CIRC-01-CORE-LOBBY-ADJ")

    # 10. wet vs wet (only if no forbidden wall already derived)
    if a_wet and b_wet and not any(r.startswith("HYG-01") or r.startswith("HYG-02") or r.startswith("SAF-01") for r in rules):
        rules.add("HYG-03-WET-WET-COUPLE")

    # 11. security vs front
    if (a.function == FunctionType.SECURITY and b.visitor_depth == VisitorDepth.FRONT) or (
        b.function == FunctionType.SECURITY and a.visitor_depth == VisitorDepth.FRONT
    ):
        rules.add("SEC-01-GUARD-GATE-ADJ")

    # 12. back-of-house vs public (only if no must-adjacent already derived)
    if (
        (a.service_side.value == "back_of_house" and b.public_access == PublicAccess.PUBLIC)
        or (b.service_side.value == "back_of_house" and a.public_access == PublicAccess.PUBLIC)
    ) and not any(r in rules for r in {
        "FUNC-01-COOK-EAT-ADJ",
        "CIRC-01-CORE-LOBBY-ADJ",
        "LOG-01-LOAD-DISPATCH-ADJ",
        "LOG-02-DISPATCH-STORAGE-ADJ",
        "ACC-01-RECEPTION-FRONT-ADJ",
    }):
        rules.add("ACC-02-BOH-PUBLIC-SEP")

    return rules


def test_derived_matrix_matches_independent_expected_matrix():
    spaces = list(ONTOLOGY.all_spaces.values())
    override_keys = set(ONTOLOGY.all_overrides) | {
        (b, a) for (a, b) in ONTOLOGY.all_overrides
    }
    mismatches = []
    for i, a in enumerate(spaces):
        for b in spaces[i:]:
            if (a.id, b.id) in override_keys:
                continue
            actual = {r.rule_id for r in ONTOLOGY.get_relations(a.id, b.id)}
            expected = _expected_rule_ids(a, b)
            if actual != expected:
                mismatches.append((a.id, b.id, sorted(actual - expected), sorted(expected - actual)))
    assert not mismatches, f"{len(mismatches)} pair(s) differ from the expected algebra: {mismatches[:10]}"


def test_relation_matrix_is_symmetric_and_well_formed():
    spaces = list(ONTOLOGY.all_spaces.values())
    for a in spaces:
        for b in spaces:
            ab = ONTOLOGY.get_relations(a.id, b.id)
            ba = ONTOLOGY.get_relations(b.id, a.id)
            assert [r.rule_id for r in ab] == [r.rule_id for r in ba], (a.id, b.id)
            ids = [r.rule_id for r in ab]
            assert len(ids) == len(set(ids)), (a.id, b.id)
            for rule in ab:
                assert rule.rule_id and rule.citation and rule.description
                assert rule.rationale is not None


def test_canonical_relations_are_derived_not_hardcoded_pairs():
    # The five Appendix laws must come from attributes, not the override table.
    derived_pairs = {
        ("bath_1", "puja"),
        ("bath_1", "kitchen"),
        ("kitchen", "dining"),
        ("shared_stair", "floor_lobby"),
        ("living", "study"),
    }
    for pair in derived_pairs:
        assert pair not in EXPLICIT_OVERRIDES
        assert (pair[1], pair[0]) not in EXPLICIT_OVERRIDES

    assert ONTOLOGY.is_forbidden_wall("bath_1", "puja") is True
    assert ONTOLOGY.is_forbidden_door_facing("bath_1", "puja") is True
    assert ONTOLOGY.is_forbidden_wall("bath_1", "server_room") is True
    assert ONTOLOGY.is_must_adjacent("kitchen", "dining") is True
    assert ONTOLOGY.is_must_adjacent("shared_stair", "floor_lobby") is True

    quiet_social = ONTOLOGY.get_relations("study", "living")
    assert any(r.rule_id == "NOI-02-QUIET-SOCIAL-SEP" for r in quiet_social)
    assert any(r.relation == RelationType.PREFER_SEPARATE for r in quiet_social)


# ---------------------------------------------------------------------------
# Vertical law
# ---------------------------------------------------------------------------

def test_vertical_wet_stack_alignment_is_positive_law():
    rules = ONTOLOGY.evaluate_vertical_stack("bath_1", "bath_1", upper_level=1)
    by_id = {r.rule_id: r for r in rules}
    assert "VERT-01-WET-STACK-ALIGN" in by_id
    assert by_id["VERT-01-WET-STACK-ALIGN"].relation == RelationType.MUST_STACK
    assert "VERT-01-WET-STACK" not in by_id
    assert "VERT-02-NO-WET-OVER-HABITABLE" not in by_id


def test_vertical_no_wet_over_habitable_or_terrace_and_core_continuity():
    over_bed = ONTOLOGY.evaluate_vertical_stack("bath_1", "master_bed", upper_level=1)
    assert any(r.relation == RelationType.FORBIDDEN_ABOVE for r in over_bed)
    # Same wet class stacked (kitchen over kitchen) is the preferred plumbing
    # condition, not a hygiene violation; T2 repeats a kitchen on every unit
    # floor.  Foul drainage over a *different* wet class stays forbidden.
    over_kitchen = ONTOLOGY.evaluate_vertical_stack("kitchen", "kitchen", upper_level=1)
    assert not any(r.rule_id == "VERT-02-NO-WET-OVER-HABITABLE" for r in over_kitchen)
    over_kitchen = ONTOLOGY.evaluate_vertical_stack("bath_1", "kitchen", upper_level=1)
    assert any(r.rule_id == "VERT-02-NO-WET-OVER-HABITABLE" for r in over_kitchen)
    core_over_core = ONTOLOGY.evaluate_vertical_stack("t1_stair", "t1_stair", upper_level=1)
    assert not any(r.relation == RelationType.FORBIDDEN_ABOVE for r in core_over_core)
    core_over_living = ONTOLOGY.evaluate_vertical_stack("t1_stair", "living", upper_level=1)
    assert any(r.rule_id == "VERT-03-CORE-CONTINUITY" for r in core_over_living)
    over_terrace = ONTOLOGY.evaluate_vertical_stack("bath_1", "terrace", upper_level=1)
    assert any(r.rule_id == "VERT-06-NO-WET-OVER-TERRACE" for r in over_terrace)
    assert next(r for r in over_terrace if r.rule_id == "VERT-06-NO-WET-OVER-TERRACE").relation == RelationType.FORBIDDEN_ABOVE


def test_vertical_mezzanine_fire_separation_and_heavy_load():
    rules = ONTOLOGY.evaluate_vertical_stack("admin_office", "storage_bay", upper_level=1)
    by_id = {r.rule_id: r for r in rules}
    assert "VERT-05-MEZZANINE-FIRE-SEPARATION" in by_id
    assert by_id["VERT-05-MEZZANINE-FIRE-SEPARATION"].rationale.value == "FIRE_SAFETY"
    heavy = ONTOLOGY.evaluate_vertical_stack("storage_bay", "storage_bay", upper_level=1)
    assert any(r.rule_id == "VERT-04-HEAVY-LOAD-GROUND" for r in heavy)


def test_t4_loading_dispatch_storage_chain_law():
    missing = ONTOLOGY.evaluate_typology_chain("warehouse", [("t4_dock_bay", "t4_dispatch")])
    assert [r.rule_id for r in missing] == ["LOG-03-DISPATCH-STORAGE_BAY-CHAIN"]
    complete = ONTOLOGY.evaluate_typology_chain(
        "warehouse",
        [("t4_dock_bay", "t4_dispatch"), ("t4_dispatch", "t4_storage_bay")],
    )
    assert complete == []
    # The chain links are themselves derived MUST_ADJACENT relations.
    assert ONTOLOGY.is_must_adjacent("dock_bay", "dispatch") is True
    assert ONTOLOGY.is_must_adjacent("dispatch", "storage_bay") is True


# ---------------------------------------------------------------------------
# Typology catalogs
# ---------------------------------------------------------------------------

def test_typology_program_catalogs_are_complete():
    for canonical in CANONICAL_TYPOLOGIES:
        catalog = ONTOLOGY.get_program_catalog(canonical)
        assert catalog.canonical == canonical
        assert catalog.required_spaces
        for sid in catalog.required_spaces + catalog.wet_points + catalog.industrial_chain:
            assert sid in ONTOLOGY.all_spaces, f"{canonical}: unknown space '{sid}'"
        for sid in catalog.wet_points:
            assert ONTOLOGY.get_space(sid).is_wet, sid


def test_t2_unit_shared_core_and_parking_definition():
    catalog = ONTOLOGY.get_program_catalog("apartment")
    unit = catalog.unit
    core = catalog.shared_core
    assert unit is not None and core is not None
    assert {"unit_living", "unit_kitchen", "unit_bed", "unit_bath", "unit_utility", "unit_balcony"} <= set(unit.room_ids)
    assert {"shared_stair", "lift_core", "floor_lobby"} <= set(core.space_ids)
    assert core.parking_ecs_per_unit >= 1.0
    assert "100 m2" in core.parking_rule
    assert unit.min_carpet_area_sqm >= 41.0
    # Every unit wet point is a wet-class space used by the unit.
    for sid in unit.wet_points:
        assert sid in unit.room_ids
        assert ONTOLOGY.get_space(sid).is_wet


def test_t4_industrial_program_and_mezzanine():
    catalog = ONTOLOGY.get_program_catalog("warehouse")
    assert catalog.industrial_chain == ["dock_bay", "dispatch", "storage_bay"]
    assert catalog.wet_points == ["worker_amenity", "washdown_point"]
    assert catalog.mezzanine_levels == [1]
    for sid in ("dock_bay", "dispatch", "storage_bay", "admin_office", "conf_room", "admin_catwalk", "ind_stair"):
        assert sid in catalog.required_spaces
    assert ONTOLOGY.get_space("storage_bay").min_area_sqm == 80.0
    assert ONTOLOGY.get_space("admin_office").min_area_sqm == 35.0


def test_room_id_normalizer_is_exact_and_typology_aware():
    assert ONTOLOGY.resolve_space_id("bath_1_F0") == "bath_1"
    assert ONTOLOGY.resolve_space_id("t2_unitA_bath_F0") == "unit_bath"
    assert ONTOLOGY.resolve_space_id("t2_unitB_living_F3") == "unit_living"
    assert ONTOLOGY.resolve_space_id("guest_bed_F0") == "bed_2"
    assert ONTOLOGY.resolve_space_id("ensuite_bath_F1") == "bath_master"
    assert ONTOLOGY.resolve_space_id("t3_suite_N_F1") == "commercial_suite"
    assert ONTOLOGY.resolve_space_id("t4_dock_bay_F0") == "dock_bay"
    assert ONTOLOGY.resolve_space_id("t4_storage_bay_F1") == "storage_bay"
    assert ONTOLOGY.resolve_space_id("core_staircase_primary_F0", "T1_SINGLE_FAMILY") == "t1_stair"
    assert ONTOLOGY.resolve_space_id("core_staircase_primary_F0", "T2_FAMILY_APARTMENT") == "shared_stair"
    assert ONTOLOGY.resolve_space_id("lobby_spine_F2", "T3_LARGE_COMPLEX") == "spine_corridor"
    # Corrected three coarse aliases: a T4 distribution lobby is not a
    # mezzanine catwalk, an archive deck is not heavy storage, and the utility
    # strip is a wet service space.  Each now has its own ontology record.
    assert ONTOLOGY.resolve_space_id("lobby_spine_F2", "T4_WAREHOUSE") == "distribution_lobby"
    assert ONTOLOGY.resolve_space_id("t4_deck_F1", "T4_WAREHOUSE") == "archive_deck"
    assert ONTOLOGY.resolve_space_id("t4_util_west_F1", "T4_WAREHOUSE") == "utility_strip"
    assert ONTOLOGY.resolve_space_id("t4_catwalk_F1", "T4_WAREHOUSE") == "viewing_catwalk"
    assert ONTOLOGY.resolve_space_id("link_corridor_F0", "T3_LARGE_COMPLEX") == "spine_corridor"
    assert ONTOLOGY.resolve_space_id("link_corridor_F0") == "central_lobby"
    # The T2 mixed-use amenity is floor-dependent and explicitly resolved.
    assert ONTOLOGY.resolve_space_id("t2_amenity_F0", "T2_FAMILY_APARTMENT") == "foyer"
    assert ONTOLOGY.resolve_space_id("t2_amenity_F1", "T2_FAMILY_APARTMENT") == "unit_utility"
    # No partial-substring guessing: unknown ids stay unknown.
    assert ONTOLOGY.resolve_space_id("bathroom_widget") is None


def test_typology_profiles():
    """Verify all 4 typology profiles have statutory egress, sanitation, and parking data."""
    profiles = ONTOLOGY.all_typologies
    assert "T1_SINGLE_FAMILY" in profiles
    assert "T2_FAMILY_APARTMENT" in profiles
    assert "T3_LARGE_COMPLEX" in profiles
    assert "T4_WAREHOUSE" in profiles

    t1 = profiles["T1_SINGLE_FAMILY"]
    assert t1.vastu_weight_scale == 1.0
    assert "NBC 2016" in t1.egress_constants["citation"]
    assert t1.egress_constants["max_travel_distance_non_sprinklered_m"] == 30.0

    t3 = profiles["T3_LARGE_COMPLEX"]
    assert t3.vastu_weight_scale < t1.vastu_weight_scale
    assert t3.egress_constants["min_corridor_width_m"] == 1.50
    assert "dead_end_corridor_max_m" in t3.egress_constants

    t4 = profiles["T4_WAREHOUSE"]
    assert t4.vastu_weight_scale <= 0.1
    assert t4.floor_height_m >= 6.0


def test_override_precedence():
    """Tests that explicit overrides supersede default derived algebra."""
    # 1. Puja vs Living: override specifies PREFER_ADJACENT
    puja_liv_rules = ONTOLOGY.get_relations("puja", "living")
    assert len(puja_liv_rules) == 1
    assert puja_liv_rules[0].is_override is True
    assert puja_liv_rules[0].rule_id == "OVR-01-PUJA-LIVING"
    assert puja_liv_rules[0].relation == RelationType.PREFER_ADJACENT

    # 2. Master Bed vs Bath 1: override specifies MUST_ADJACENT for ensuite
    mbed_bath_rules = ONTOLOGY.get_relations("master_bed", "bath_1")
    assert len(mbed_bath_rules) == 1
    assert mbed_bath_rules[0].is_override is True
    assert mbed_bath_rules[0].rule_id == "OVR-02-ENSUITE-MASTER"
    assert mbed_bath_rules[0].relation == RelationType.MUST_ADJACENT

    # 3. Kitchen vs Utility: override specifies MUST_ADJACENT
    kitch_util_rules = ONTOLOGY.get_relations("kitchen", "utility")
    assert len(kitch_util_rules) == 1
    assert kitch_util_rules[0].is_override is True
    assert kitch_util_rules[0].rule_id == "OVR-04-UTILITY-KITCHEN"
    assert kitch_util_rules[0].relation == RelationType.MUST_ADJACENT


def test_zero_solver_change_extensibility():
    """Verify that a brand new custom space type can be registered and queried dynamically."""
    custom_registry = OntologyRegistry()

    lab_spec = SpaceTypeSpec(
        id="biotech_lab",
        name="Bio-Tech Cleanroom Lab",
        typologies=["T3_LARGE_COMPLEX"],
        function=FunctionType.PRODUCTION,
        hygiene=HygieneType.SACRED,  # Requires ultra-clean sterile conditions
        odor_emit=0, moisture_emit=0, grease_emit=0, noise_emit=1,
        noise_sensitive=3, acoustic_privacy=3,
        public_access=PublicAccess.RESTRICTED,
        visitor_depth=VisitorDepth.DEEP,
        security=SecurityLevel.SECURE,
        service_side=ServiceSide.BACK_OF_HOUSE,
        fire_hazard=FireHazard.MEDIUM,
        egress_role=EgressRole.NONE,
        floor_load=FloorLoad.NORMAL,
        daylight_req=False,
        ventilation_req="mechanical",
        min_area_sqm=50.0,
        min_width_m=6.00,
        max_aspect_ratio=1.50,
        permitted_levels=[1, 2],
    )

    custom_registry.register_space(lab_spec)

    # Cleanroom (sacred hygiene) vs Bathroom (foul hygiene) -> Algebra automatically triggers
    rules = custom_registry.get_relations("biotech_lab", "bath_1")
    assert any(r.rule_id == "HYG-01-FOUL-SACRED-WALL" for r in rules)
    assert custom_registry.is_forbidden_wall("biotech_lab", "bath_1") is True

    # Wet stack test: bath over cleanroom -> forbidden above
    v_rules = custom_registry.evaluate_vertical_stack(upper_space_id="bath_1", lower_space_id="biotech_lab", upper_level=2)
    assert any(r.rule_id == "VERT-02-NO-WET-OVER-HABITABLE" for r in v_rules)
