"""Typology programme contract: the generation knows which building it is designing.

These tests pin the contract between the four typology programmes, the
canonical ontology room IDs, and the frontend catalog.  They also cover the
regression where legacy display IDs produced "unmet requirement" rows even
though the typology itself had been solved correctly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.ontology import ONTOLOGY
from app.services.floorplan.room_aliases import (
    LEGACY_ROOM_ALIASES,
    canonical_room_ids,
    normalize_room_ids,
    resolve_room_id,
)
from app.services.floorplan.typologies import (
    TYPOLOGY_T1,
    TYPOLOGY_T2,
    TYPOLOGY_T3,
    TYPOLOGY_T4,
    get_typology_catalog,
    normalize_typology,
)

LEGACY_FRONTEND_PROGRAMMES = {
    TYPOLOGY_T1: ["master_bed", "kitchen", "living", "stairs"],
    TYPOLOGY_T2: [
        "staircase_core",
        "lobby",
        "apt_a_living",
        "apt_a_kitchen",
        "apt_a_bed",
        "apt_a_bath",
        "apt_b_living",
        "apt_b_kitchen",
        "apt_b_bed",
        "apt_b_bath",
    ],
    TYPOLOGY_T3: [
        "fire_stair_1",
        "lift_bank",
        "corridor",
        "commercial_suite_a",
        "commercial_suite_b",
        "restroom_block",
    ],
    TYPOLOGY_T4: ["storage_bay", "loading_dock", "dispatch_buffer", "staff_amenities", "steel_stair"],
}

CANONICAL_FRONTEND_PROGRAMMES = {
    TYPOLOGY_T1: ["master_bed", "kitchen", "living", "t1_stair"],
    TYPOLOGY_T2: ["shared_stair", "floor_lobby", "unit_living", "unit_kitchen", "unit_bed", "unit_bath"],
    TYPOLOGY_T3: ["primary_stair", "lift_lobby", "spine_corridor", "commercial_suite", "sanitary_block"],
    TYPOLOGY_T4: ["storage_bay", "dock_bay", "dispatch", "worker_amenity", "ind_stair"],
}

CHARACTERISTIC_SPACES = {
    TYPOLOGY_T1: {"master_bed", "kitchen", "living"},
    TYPOLOGY_T2: {"unit_living", "unit_kitchen", "unit_bed", "unit_bath"},
    TYPOLOGY_T3: {"commercial_suite", "sanitary_block"},
    TYPOLOGY_T4: {"storage_bay", "dock_bay", "dispatch"},
}


def _generate(typology: str, rooms: list[str], floors: int = 2):
    return generate_floor_plan(
        FloorPlanRequest(
            plot_width_m=18,
            plot_depth_m=22,
            floors=floors,
            building_typology=typology,
            required_rooms=rooms,
        )
    )


def test_every_legacy_room_alias_resolves_to_a_canonical_catalog_id():
    for typology, aliases in LEGACY_ROOM_ALIASES.items():
        catalog = set(get_typology_catalog(typology))
        for legacy, canonical in aliases.items():
            assert canonical in catalog, f"{typology}: {legacy} -> missing {canonical}"
            assert resolve_room_id(typology, legacy) == canonical
            assert resolve_room_id(typology, canonical) == canonical


def test_alias_normalization_deduplicates_units_without_losing_order():
    normalized = normalize_room_ids(
        TYPOLOGY_T2,
        ["staircase_core", "lobby", "apt_a_living", "apt_b_living", "apt_a_kitchen"],
    )
    assert normalized == ["shared_stair", "floor_lobby", "unit_living", "unit_kitchen"]


@pytest.mark.parametrize("typology", [TYPOLOGY_T1, TYPOLOGY_T2, TYPOLOGY_T3, TYPOLOGY_T4])
def test_legacy_programme_is_solved_without_false_unmet_rows(typology):
    response = _generate(typology, LEGACY_FRONTEND_PROGRAMMES[typology])
    assert response.multi_storey.building_typology == typology
    assert response.multi_storey.unmet_requirements == []


@pytest.mark.parametrize("typology", [TYPOLOGY_T1, TYPOLOGY_T2, TYPOLOGY_T3, TYPOLOGY_T4])
def test_canonical_programme_is_solved_and_matches_topology(typology):
    response = _generate(typology, CANONICAL_FRONTEND_PROGRAMMES[typology])
    building = response.multi_storey
    assert building.building_typology == typology
    assert building.unmet_requirements == []

    placed_ids = {
        room.space_type_id
        for floor in building.floors
        for room in floor.rooms
        if room.space_type_id
    }
    assert CHARACTERISTIC_SPACES[typology] <= placed_ids

    room_names = {room.room_name.lower() for floor in building.floors for room in floor.rooms}
    if typology == TYPOLOGY_T1:
        assert any("bedroom" in name for name in room_names)
    elif typology == TYPOLOGY_T2:
        assert any("kitchen" in name for name in room_names)
        assert any("living" in name for name in room_names)
    elif typology == TYPOLOGY_T3:
        assert any("office" in name or "suite" in name for name in room_names)
        assert any("restroom" in name for name in room_names)
    elif typology == TYPOLOGY_T4:
        assert any("storage bay" in name for name in room_names)
        assert any("dock" in name for name in room_names)
        assert any("dispatch" in name for name in room_names)


@pytest.mark.parametrize("typology", [TYPOLOGY_T1, TYPOLOGY_T2, TYPOLOGY_T3, TYPOLOGY_T4])
def test_snapshot_records_canonical_intent_and_raw_request_token(typology):
    response = _generate(typology, CANONICAL_FRONTEND_PROGRAMMES[typology])
    assert response.params_snapshot["building_typology"] == typology
    assert normalize_typology(response.params_snapshot["requested_typology"]) == typology


def test_t2_apartments_emit_a_kitchen_in_every_unit_on_every_floor():
    response = _generate(TYPOLOGY_T2, CANONICAL_FRONTEND_PROGRAMMES[TYPOLOGY_T2])
    for floor in response.multi_storey.floors:
        kitchens = [room for room in floor.rooms if room.space_type_id == "unit_kitchen"]
        assert len(kitchens) == 2, f"floor {floor.floor_index}: {[r.room_id for r in kitchens]}"
        assert all(room.unit_id for room in kitchens)
        assert all(room.furniture and all(item.is_satisfied for item in room.furniture) for room in kitchens)


def test_wet_over_same_wet_class_is_not_a_hygiene_violation():
    same = ONTOLOGY.evaluate_vertical_stack("unit_kitchen", "unit_kitchen", upper_level=1)
    assert "VERT-02-NO-WET-OVER-HABITABLE" not in {rule.rule_id for rule in same}
    assert "VERT-01-WET-STACK-ALIGN" in {rule.rule_id for rule in same}

    kitchen_over_dining = ONTOLOGY.evaluate_vertical_stack("unit_kitchen", "dining", upper_level=1)
    assert "VERT-02-NO-WET-OVER-HABITABLE" in {rule.rule_id for rule in kitchen_over_dining}


def test_frontend_catalog_matches_backend_ontology_catalog():
    """Read the TS catalog and compare every ID/minimum to the ontology.

    The frontend needs a static catalog for the room picker, but it must not
    drift from the solver's programme vocabulary again.  Parsing the literal
    table is intentional: it fails loudly if someone edits one side only.
    """
    ts_path = Path(__file__).resolve().parents[3] / "frontend" / "src" / "services" / "typology.ts"
    assert ts_path.exists(), ts_path
    source = ts_path.read_text(encoding="utf-8")

    entry_re = re.compile(            r"\{\s*id:\s*'([^']+)'[^}]*?minAreaSqm:\s*([0-9.]+)[^}]*?minDimensionM:\s*([0-9.]+)",
        re.S,
    )
    for typology in (TYPOLOGY_T1, TYPOLOGY_T2, TYPOLOGY_T3, TYPOLOGY_T4):
        start = source.index(f"{typology}: [")
        end = source.index("],", start)
        block = source[start:end]
        entries = {
            match.group(1): (float(match.group(2)), float(match.group(3)))
            for match in entry_re.finditer(block)
        }
        backend = get_typology_catalog(typology)
        assert set(entries) == set(backend), f"{typology} ID drift: {set(entries) ^ set(backend)}"
        for room_id, (area, width) in entries.items():
            spec = backend[room_id]
            assert area == pytest.approx(float(spec["min_area_sqm"]), abs=0.01), room_id
            assert width == pytest.approx(float(spec["min_width_m"]), abs=0.01), room_id


def test_canonical_catalog_is_non_empty_and_aliases_do_not_add_rooms():
    for typology in (TYPOLOGY_T1, TYPOLOGY_T2, TYPOLOGY_T3, TYPOLOGY_T4):
        catalog = set(canonical_room_ids(typology))
        assert catalog
        assert set(LEGACY_ROOM_ALIASES.get(typology, {}).values()) <= catalog
