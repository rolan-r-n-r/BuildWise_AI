"""Two-storey dwelling geometry, programme identity, adaptive V3 duplex layout,
plate policy and certification.

Merged from ``test_duplex_dwellings.py`` and ``test_adaptive_duplex_layout.py``:
- Target 12 x 18 m / four-storey T2 plate: count-preserving duplex (8 dwellings
  on 16 level-units), internal stair pairs, single-entry corridor rules,
  schema validation, L15 per-household completeness, byte-stability, cache
  parity, and S1/S2 ladder disclosures.
- Adaptive V3 row layout (18 x 24 m site): 3.64 m core band, measured clear
  faces above the catalogue, legal plate growth within coverage/setback
  ceilings, kitchen exterior daylight window, protected stair capacity,
  infeasible plate refusal, and solve budget.
"""
from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.engineering import VENT_WINDOW_HEIGHT_HABITABLE_M
from app.services.floorplan.floorplan_service import generate_floor_plan
import app.services.floorplan.strategy_escalation as ladder
from app.services.floorplan.strategy_escalation import (
    _CACHE,
    _facts,
    solve_with_escalation,
)
from app.services.plan_verdict import CERTIFIED, compute_plan_verdict


# ---------------------------------------------------------------------------
# Helpers (explicitly preserving both original parameter defaults)
# ---------------------------------------------------------------------------


def _req_dwellings(**extra) -> FloorPlanRequest:
    payload = dict(
        plot_width_m=12.0,
        plot_depth_m=18.0,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="stage11b-pin",
        ai_provider="mock",
        bypass_cache=True,
        partition_variant="duplex",
        units_per_floor=4,
    )
    payload.update(extra)
    return FloorPlanRequest(**payload)


def _req_adaptive(width: float = 18.0, depth: float = 24.0, **extra) -> FloorPlanRequest:
    payload = dict(
        plot_width_m=width,
        plot_depth_m=depth,
        building_typology="residential_multi",
        floors=4,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed="stage11c-pin",
        ai_provider="mock",
        bypass_cache=True,
        partition_variant="duplex",
        units_per_floor=4,
    )
    payload.update(extra)
    return FloorPlanRequest(**payload)


def _solve_dwellings(req=None):
    _CACHE.clear()
    return generate_floor_plan(req or _req_dwellings())


def _solve_adaptive(req=None):
    ladder._CACHE.clear()
    return generate_floor_plan(req or _req_adaptive())


def _stair_rooms(response):
    stairs = {}
    for floor in response.multi_storey.floors:
        for room in floor.rooms:
            if room.space_type_id == "unit_stair":
                stairs.setdefault(room.dwelling_id, []).append(room)
    return stairs


def _cert(response):
    return response.model_dump().get("mathematical_certificate") or {}


def _decision(response):
    return (response.params_snapshot or {}).get("duplex_layout") or {}


def _layer(response, layer_id):
    return next(l for l in response.qa.validation_gate["layers"] if l["layer_id"] == layer_id)


def _clear_pairs(response, floor_index: int):
    floor = next(f for f in response.multi_storey.floors if f.floor_index == floor_index)
    schedule = {
        str(row.get("room_id")): row
        for row in ((floor.wall_graph or {}).get("room_schedule") or [])
    }
    out = {}
    for room in floor.rooms:
        row = schedule.get(room.room_id) or {}
        match = re.findall(
            r"([\d.]+)\s*m\s*[x×]\s*([\d.]+)\s*m",
            str(row.get("clear_dimensions") or ""),
        )
        if match:
            out[room.room_id] = (float(match[0][0]), float(match[0][1]))
    return out


def _isolation_s2(req):
    original = ladder._strategy_specs

    def only_s2(request, baseline):
        return [spec for spec in original(request, baseline) if spec["id"] == "S2"]

    ladder._strategy_specs = only_s2
    try:
        ladder._CACHE.clear()
        return ladder.solve_with_escalation(req)
    finally:
        ladder._strategy_specs = original


_VOLATILE = {
    "generated_at", "solver_timing_ms", "engine_ms", "timing_ms", "timings_ms",
    "elapsed_ms", "total_ms", "latency_ms", "duration_ms", "evaluated_at",
}


def _stable_dump(response):
    """Everything but wall-clock readings, which are not a determinism claim."""
    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if k not in _VOLATILE}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub(response.model_dump())


# ---------------------------------------------------------------------------
# Duplex dwellings & programme identity (12 x 18 m compact fallback target)
# ---------------------------------------------------------------------------


def test_target_duplex_preserves_eight_dwellings_on_sixteen_level_units():
    response = _solve_dwellings()
    assert response.multi_storey is not None
    assert response.multi_storey.units_per_floor == 4
    facts = _facts(response)
    assert facts["dwelling_count"] == 8
    assert facts["floor_unit_count"] == 16
    ids = {
        room.dwelling_id
        for floor in response.multi_storey.floors
        for room in floor.rooms
        if room.dwelling_id
    }
    assert ids == {f"D{i}" for i in range(1, 9)}
    # Four households per plate, and the same household appears on exactly the
    # two levels of its pair.
    assert [len({r.dwelling_id for r in f.rooms if r.dwelling_id}) for f in response.multi_storey.floors] == [4, 4, 4, 4]
    for floor in response.multi_storey.floors:
        expected = ("lower", "upper")[floor.floor_index % 2]
        assert {r.dwelling_level for r in floor.rooms if r.dwelling_id} == {expected}


def test_internal_stair_pair_is_real_geometry_and_certificate_checks_it():
    response = _solve_dwellings()
    stairs = _stair_rooms(response)
    assert sorted(stairs) == [f"D{i}" for i in range(1, 9)]
    for dwelling, pair in stairs.items():
        assert len(pair) == 2, f"{dwelling} has {len(pair)} stair levels"
        a, b = sorted(pair, key=lambda r: r.floor_index)
        assert b.floor_index == a.floor_index + 1
        assert (a.x, a.y, a.width_m, a.depth_m) == (b.x, b.y, b.width_m, b.depth_m)
        assert a.unit_id == b.unit_id == dwelling
        assert a.dwelling_id == b.dwelling_id == dwelling
    cert = _cert(response)
    assert cert["unit_stairs_valid"] is True
    # Single-entry contract: the LOWER level owns the common-corridor door;
    # the UPPER level is reached only through the internal stair pair and
    # must not be drawn as a second corridor-accessible flat.  The stair is
    # still not a sealed box: it has real doors to the dwelling's bath and main
    # room, and the upper stair is a vertical portal in the reachability check.
    for floor in response.multi_storey.floors:
        common = {
            r.room_id for r in floor.rooms
            if r.zone_category == "circulation" and not r.dwelling_id
        }
        for stair in [r for r in floor.rooms if r.space_type_id == "unit_stair"]:
            touching = [
                door for door in floor.doors
                if stair.room_id in (door.from_room, door.to_room)
            ]
            has_corridor = any(
                door.from_room in common or door.to_room in common
                for door in touching
            )
            assert has_corridor == (floor.floor_index % 2 == 0), (
                f"{stair.room_id}: corridor access {has_corridor} on "
                f"floor {floor.floor_index}"
            )


def test_duplex_candidate_does_not_claim_certification_on_the_target():
    response = _solve_dwellings()
    cert = _cert(response)
    assert cert.get("is_valid") is False
    assert any(row.startswith("NBC-01 Room minimums") for row in cert.get("failures", []))
    # It is a real plan with a named shortfall, not a silent two-unit fallback.
    assert "DUPLEX" in response.generation_id
    assert response.multi_storey is not None
    assert len(response.multi_storey.floors) == 4
    assert response.qa is not None
    assert response.qa.validation_gate_status in ("WARN", "FAIL")


def test_duplex_is_not_a_silent_alias_for_the_two_unit_plate():
    response = _solve_dwellings()
    for floor in response.multi_storey.floors:
        units = {r.unit_id for r in floor.rooms if r.unit_id}
        assert units == {f"D{(floor.floor_index // 2) * 4 + n}" for n in range(1, 5)}
        assert "Unit_A" not in units and "Unit_B" not in units


def test_four_units_without_duplex_and_three_units_are_rejected():
    with pytest.raises(ValidationError, match="only with"):
        _req_dwellings(partition_variant=None)
    with pytest.raises(ValidationError, match="three-unit"):
        _req_dwellings(partition_variant=None, units_per_floor=3)
    with pytest.raises(ValidationError, match="four floor-level"):
        _req_dwellings(units_per_floor=2)


def test_duplex_requires_floor_pairs():
    with pytest.raises(ValidationError, match="even number of storeys"):
        _req_dwellings(floors=3)


def test_programme_completeness_groups_by_household_across_levels():
    response = _solve_dwellings()
    gate = response.qa.validation_gate
    l15 = next(layer for layer in gate["layers"] if layer["layer_id"] == "L15")
    assert l15["status"] == "PASS", l15
    assert set(l15["details"]["per_unit"]) == {f"D{i}" for i in range(1, 9)}
    for dwelling in (f"D{i}" for i in range(1, 9)):
        assert {"unit_living", "unit_kitchen", "unit_bed", "unit_bath"} <= set(
            l15["details"]["per_unit"][dwelling]
        )


def test_repeated_solves_are_byte_stable_for_the_duplex_plate():
    first = _solve_dwellings()
    second = _solve_dwellings()
    assert first.generation_id == second.generation_id
    assert _stable_dump(first) == _stable_dump(second)


def test_warm_and_cold_duplex_cache_entries_are_equivalent():
    _CACHE.clear()
    cold = generate_floor_plan(_req_dwellings())
    warm = generate_floor_plan(_req_dwellings())
    assert warm.generation_id == cold.generation_id
    assert _stable_dump(warm) == _stable_dump(cold)


def test_explicit_duplex_request_never_errors_an_impossible_service_row():
    _CACHE.clear()
    response = solve_with_escalation(_req_dwellings())
    chain = response.multi_storey.strategy_chain
    s1 = next(entry for entry in chain if entry["id"] == "S1")
    assert s1["status"] == "skipped"
    assert "will not" in s1["skip_reason"] and "explicit variant" in s1["skip_reason"]
    assert not [entry for entry in chain if entry["status"] == "error"]
    assert response.multi_storey.strategy_selected == "S0"


def test_ladder_skips_s2_on_odd_storeys_with_a_named_reason(monkeypatch):
    original = ladder._strategy_specs

    def only_s2(request, baseline):
        return [spec for spec in original(request, baseline) if spec["id"] == "S2"]

    monkeypatch.setattr(ladder, "_strategy_specs", only_s2)
    _CACHE.clear()
    response = solve_with_escalation(
        _req_dwellings(
            plot_width_m=12.0,
            plot_depth_m=15.0,
            floors=3,
            partition_variant=None,
            units_per_floor=2,
        )
    )
    s2 = next(entry for entry in response.multi_storey.strategy_chain if entry["id"] == "S2")
    assert s2["status"] == "skipped"
    assert "even number of storeys" in s2["skip_reason"]
    assert "stacking_mode" not in s2


def test_ladder_s2_discloses_stacking_and_never_reduces_the_count(monkeypatch):
    original = ladder._strategy_specs

    def only_s2(request, baseline):
        return [spec for spec in original(request, baseline) if spec["id"] == "S2"]

    monkeypatch.setattr(ladder, "_strategy_specs", only_s2)
    _CACHE.clear()
    # The ladder is entered by an ordinary two-unit request; S2 is the patch
    # that converts it to the duplex plate.
    response = solve_with_escalation(_req_dwellings(partition_variant=None, units_per_floor=2))
    chain = response.multi_storey.strategy_chain
    s2 = next(entry for entry in chain if entry["id"] == "S2")
    assert s2["stacking_mode"] == "duplex"
    assert s2["dwelling_count_before"] == 8
    assert s2["dwelling_count_after"] == 8
    assert s2["floor_unit_count"] == 16
    assert len(s2["internal_stair_connections"]) == 8
    assert all(row["levels_joined"] for row in s2["internal_stair_connections"])
    assert all(row["geometry_aligned"] for row in s2["internal_stair_connections"])
    assert s2["all_levels_joined"] is True
    assert s2["wet_columns_aligned"] is True
    assert s2["core_continuity"]["aligned"] is True
    assert s2["core_continuity"]["distinct_core_footprints"] == 2  # stair + lift
    assert s2["core_continuity"]["floors_with_identical_core"] == [0, 1, 2, 3]
    assert s2["identity"]["duplex_unit_ids"] == [f"D{i}" for i in range(1, 9)]
    assert s2["identity"]["baseline_unit_ids"] == ["Unit_A", "Unit_B"]
    assert s2["level_units_per_floor"] == [4, 4, 4, 4]
    assert s2["dwelling_floors"]["D1"] == [0, 1]
    assert s2["dwelling_floors"]["D8"] == [2, 3]
    assert "count preserved" in response.multi_storey.strategy_chain_line
    if s2["status"] == "fail":
        assert s2["why_not"] and "NBC-01" in s2["why_not"]
        assert s2["certification_failures"]
        assert s2["rejection_reason"].startswith("the drawn duplex candidate did not certify")
    # The candidate's own certificate invalid means it cannot be presented as
    # certified or selected as a CERTIFIED generation.
    if s2["status"] == "certified":
        assert s2["certificate_valid"] is True
    else:
        assert s2["status"] == "fail"
        assert s2["certificate_valid"] is False
    assert (response.plan_verdict != CERTIFIED) if s2["status"] == "fail" else True


# ---------------------------------------------------------------------------
# Adaptive V3 duplex geometry and certification
# ---------------------------------------------------------------------------


def test_row_layout_certifies_on_eighteen_by_twentyfour():
    response = _solve_adaptive()
    cert = _cert(response)
    decision = _decision(response)
    assert response.status != "failed"
    assert cert.get("is_valid") is True, cert.get("failures")
    assert cert.get("failures") == []
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED
    assert decision["layout"] == "core_band"
    assert decision["applied"] is True
    assert decision["plate"] == {"width": 13.2, "depth": 17.72, "area_sqm": 233.9}
    geometry = decision["layout_geometry"]
    assert geometry["kitchen_width_m"] == pytest.approx(2.10)
    assert geometry["kitchen_facade"] == "outer (end) facade"
    assert geometry["living_facade"] == "outer (end) facade"
    assert geometry["bath_facade"] == "unit side facade"
    assert [len({r.dwelling_id for r in f.rooms if r.dwelling_id}) for f in response.multi_storey.floors] == [4, 4, 4, 4]
    assert len({r.dwelling_id for f in response.multi_storey.floors for r in f.rooms if r.dwelling_id}) == 8
    assert len({(f.floor_index, r.unit_id) for f in response.multi_storey.floors for r in f.rooms if r.unit_id}) == 16
    assert cert.get("unit_stairs_valid") is True


def test_clear_faces_meet_the_catalogue_on_the_certified_plate():
    response = _solve_adaptive()
    minima = {
        "unit_living": (3.40, 16.0),
        "unit_bed": (3.00, 10.5),
        "unit_bath": (1.20, 3.0),
        "unit_kitchen": (1.80, 6.0),
    }
    for floor in response.multi_storey.floors:
        clear = _clear_pairs(response, floor.floor_index)
        for room in floor.rooms:
            if room.space_type_id not in minima:
                continue
            assert room.room_id in clear, room.room_id
            min_clear = min(clear[room.room_id])
            required, min_area = minima[room.space_type_id]
            assert min_clear >= required - 1e-6, (
                f"{room.room_id}: {min_clear:.2f} m clear < {required:.2f} m"
            )
            assert room.area_sqm >= min_area - 1e-6, (
                f"{room.room_id}: {room.area_sqm:.2f} m2 < {min_area:.2f} m2"
            )
            # The clear face must be the wall-deducted one, not the gross box.
            assert min_clear < min(room.width_m, room.depth_m) + 1e-6


def test_no_room_overlaps_or_escapes_the_envelope():
    response = _solve_adaptive()
    envelope = response.multi_storey.floors[0].envelope
    for floor in response.multi_storey.floors:
        rooms = floor.rooms
        assert len({r.room_id for r in rooms}) == len(rooms)
        for room in rooms:
            assert room.x >= -0.05 and room.y >= -0.05
            assert room.x + room.width_m <= envelope["width"] + 0.05
            assert room.y + room.depth_m <= envelope["depth"] + 0.05
        for i, first in enumerate(rooms):
            for second in rooms[i + 1:]:
                x_overlap = max(
                    0.0,
                    min(first.x + first.width_m, second.x + second.width_m)
                    - max(first.x, second.x),
                )
                y_overlap = max(
                    0.0,
                    min(first.y + first.depth_m, second.y + second.depth_m)
                    - max(first.y, second.y),
                )
                assert x_overlap * y_overlap < 0.05, (
                    f"{first.room_id} / {second.room_id} overlap"
                )


def test_dwelling_membership_and_internal_stair_pairs_are_real():
    response = _solve_adaptive()
    stairs = {}
    for floor in response.multi_storey.floors:
        for room in floor.rooms:
            if room.space_type_id == "unit_stair":
                stairs.setdefault(room.dwelling_id, []).append(room)
    assert sorted(stairs) == [f"D{i}" for i in range(1, 9)]
    for dwelling, pair in stairs.items():
        assert len(pair) == 2
        first, second = sorted(pair, key=lambda r: r.floor_index)
        assert second.floor_index == first.floor_index + 1
        assert (first.x, first.y, first.width_m, first.depth_m) == (
            second.x, second.y, second.width_m, second.depth_m
        )
        assert {first.dwelling_level, second.dwelling_level} == {"lower", "upper"}


# ---------------------------------------------------------------------------
# Single-entry access
# ---------------------------------------------------------------------------


def test_upper_level_is_stair_only_and_lower_level_owns_the_entrance():
    response = _solve_adaptive()
    for floor in response.multi_storey.floors:
        common = {
            room.room_id for room in floor.rooms
            if room.zone_category == "circulation" and not room.dwelling_id
        }
        # The dwelling's own hall is its principal entrance; the compact
        # fallback has no hall and enters through the unit stair.
        entrance_rooms = {
            room.room_id: room
            for room in floor.rooms
            if room.dwelling_id and (
                room.space_type_id == "unit_stair"
                or room.room_id.startswith(f"t2_{room.dwelling_id}_hall_")
            )
        }
        corridor_entrances = []
        for room_id, room in entrance_rooms.items():
            touching = [
                door for door in floor.doors
                if room_id in (door.from_room, door.to_room)
            ]
            if any(door.from_room in common or door.to_room in common for door in touching):
                corridor_entrances.append(room_id)
            # Every entrance room still opens into its own dwelling; and the
            # internal stair is never sealed.
            if room.space_type_id == "unit_stair":
                assert any(
                    door.from_room.startswith(f"t2_{room.dwelling_id}_")
                    or door.to_room.startswith(f"t2_{room.dwelling_id}_")
                    for door in touching
                )
        if floor.floor_index % 2 == 0:
            assert len(corridor_entrances) == 4
        else:
            assert corridor_entrances == []
        assert floor.circulation_status == "connected"


def test_isolated_s2_discloses_single_entry_and_count_preservation():
    response = _isolation_s2(_req_adaptive(units_per_floor=2, partition_variant=None))
    entry = next(row for row in response.multi_storey.strategy_chain if row["id"] == "S2")
    assert entry["status"] == "certified"
    assert entry["certificate_valid"] is True
    assert entry["certification_failures"] == []
    assert entry["layout"] == "core_band"
    assert entry["dwelling_count_before"] == 8
    assert entry["dwelling_count_after"] == 8
    assert entry["floor_unit_count"] == 16
    assert entry["all_levels_joined"] is True
    assert entry["wet_columns_aligned"] is True
    assert entry["core_continuity"]["aligned"] is True
    assert entry["entrance_semantics"] == {
        "mode": "single_entry_duplex",
        "single_entry": True,
        "upper_corridor_doors": 0,
        "principal_entrance_floors": {
            "D1": 0, "D2": 0, "D3": 0, "D4": 0,
            "D5": 2, "D6": 2, "D7": 2, "D8": 2,
        },
    }
    assert response.multi_storey.strategy_selected == "S2"
    assert "S2 certified" in response.multi_storey.strategy_chain_line
    assert "count preserved" in response.multi_storey.strategy_chain_line


# ---------------------------------------------------------------------------
# Plate policy
# ---------------------------------------------------------------------------


def test_plate_growth_is_disclosed_and_stays_inside_the_legal_ceiling():
    response = _solve_adaptive()
    decision = _decision(response)
    assert decision["layout"] == "core_band"
    assert decision["growth_applied"] is True
    assert decision["previous_plate"]["area_sqm"] == pytest.approx(123.25, abs=0.01)
    assert decision["plate"] == {"width": 13.2, "depth": 17.72, "area_sqm": 233.9}
    assert decision["area_delta_m2"] == pytest.approx(110.65, abs=0.01)
    assert decision["coverage_ceiling_m2"] == 259.2
    assert decision["coverage_headroom_m2"] == pytest.approx(25.3, abs=0.01)
    assert decision["depth_headroom_m"] == pytest.approx(0.38, abs=0.01)
    assert decision["width_headroom_m"] == pytest.approx(1.2, abs=0.01)
    assert "setback buildable depth (18.10 m)" in decision["binding_constraints"]
    assert "coverage ratio (259.20 m2)" in decision["binding_constraints"]
    assert decision["plate"]["area_sqm"] <= decision["coverage_ceiling_m2"]
    assert decision["plate"]["width"] <= decision["buildable_width_m"]
    assert decision["plate"]["depth"] <= decision["buildable_depth_m"]
    assert any(w.startswith("DUPLEX-PLATE: plate grown") for w in response.warnings)


def test_compact_target_cannot_grow_and_says_why():
    response = _solve_adaptive(_req_adaptive(12.0, 18.0))
    decision = _decision(response)
    assert decision["layout"] == "compact"
    assert decision["applied"] is False
    assert decision["previous_plate"] == {"width": 9.6, "depth": 13.5, "area_sqm": 129.6}
    assert "9.60 m wide" in decision["reason"]
    assert "12.80 m" in decision["reason"]
    assert any(w.startswith("DUPLEX-PLATE:") and "no gate is relaxed" in w for w in response.warnings)


def test_compact_target_keeps_the_named_failure_and_never_relabels_the_plan():
    response = _solve_adaptive(_req_adaptive(12.0, 18.0))
    cert = _cert(response)
    assert compute_plan_verdict(response.model_dump()) != CERTIFIED
    assert cert.get("is_valid") is False
    failures = [str(f) for f in (cert.get("failures") or [])]
    assert any(f.startswith("NBC-01 Room minimums") for f in failures)
    nbc01 = next(f for f in failures if f.startswith("NBC-01 Room minimums"))
    assert "0.89 m clear < 1.20 m" in nbc01
    assert "2.55 m clear < 3.40 m" in nbc01
    # The compact quadrant has no exterior kitchen wall; that is now a named
    # daylight failure as well, never a silent shaft-ventilation pass.
    assert any(f.startswith("GATE-L9 Ventilation") and "no exterior window" in f for f in failures)
    assert "DUPLEX" in response.generation_id
    assert _decision(response)["layout"] == "compact"
    # The compact fallback is still a real eight-household duplex, not V2.
    assert len({r.dwelling_id for f in response.multi_storey.floors for r in f.rooms if r.dwelling_id}) == 8


def test_certified_duplex_kitchens_all_have_a_modelled_exterior_window():
    # Release closure: every unit_kitchen declares daylight_req and
    # requires_exterior_wall, so a certified plan must carry a drawn window on
    # an exterior edge whose openable area reaches 1/8 of the kitchen floor
    # area.  A shaft is not daylight and is not accepted here.
    response = _solve_adaptive()
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED
    kitchens = 0
    for floor in response.multi_storey.floors:
        for room in floor.rooms:
            if "kitchen" not in room.room_id:
                continue
            kitchens += 1
            windows = [w for w in floor.windows if w.room_id == room.room_id]
            assert windows, room.room_id
            openable = sum(
                float(w.width_m) * VENT_WINDOW_HEIGHT_HABITABLE_M for w in windows
            )
            assert openable + 1e-6 >= room.area_sqm * 0.125, (
                room.room_id, room.area_sqm, openable
            )
    assert kitchens == 16
    l9 = _layer(response, "L9")
    assert not any(
        "kitchen has no exterior window" in str(f) for f in (l9.get("findings") or [])
    )


def test_certified_duplex_protected_stair_carries_the_storeys_it_serves():
    # Release closure: the previously reported 62-vs-63 shortfall charged the
    # whole building to the stair.  Each exit is now sized for the population it
    # serves, and the certified plan must prove capacity on both exits while
    # still reporting the unchanged building load.
    response = _solve_adaptive()
    l14 = _layer(response, "L14")
    assert l14["status"] == "PASS"
    protection = (l14.get("details") or {})["protection"]
    assert protection["capacity_satisfied"] is True
    assert protection["stair_occupants_served"] >= protection["stair_load_served"]
    assert protection["main_entry_occupants_served"] >= protection["main_entry_load_served"]
    assert protection["building_occupant_load"] == (
        protection["stair_load_served"] + protection["main_entry_load_served"]
    )
    assert protection["stair_load_served"] > 0
    for row in (l14.get("details") or {})["exit_width_table"]:
        assert row["capacity_satisfied"] is True, row


def test_infeasible_duplex_plates_are_refused_by_name_not_relabelled():
    # These legal sites cannot hold either the row plate or the compact
    # fallback at the catalogue minima.  Refuse the explicit duplex request
    # with its measured plate; never draw a two-unit plan and call it V3.
    for width, depth in ((15.0, 18.0), (20.0, 20.0)):
        with pytest.raises(ValueError, match="needs a feasible plate"):
            _solve_adaptive(_req_adaptive(width, depth))


def test_twelve_by_twentyfour_cannot_house_compliant_kitchens_and_is_refused():
    # The old 12 x 24 m "tight" certification drew windowless kitchens on a
    # 9.6 m plate.  With the kitchen on the outer facade the column needs
    # 6.40 m, so the two-column row plate needs 12.80 m: the site's 9.6 m
    # buildable cannot hold a compliant four-household layout, and the request
    # is refused by name instead of certified with a shaft-vented kitchen.
    with pytest.raises(ValueError, match="needs a feasible plate"):
        _solve_adaptive(_req_adaptive(12.0, 24.0))


# ---------------------------------------------------------------------------
# Stair scope, regressions, determinism, budget
# ---------------------------------------------------------------------------


def test_stair_validation_is_partial_and_says_what_it_did_not_check():
    response = _solve_adaptive()
    validation = (response.params_snapshot or {}).get("duplex_stair_validation") or {}
    assert validation["box_m"] == [1.2, 3.31]
    assert validation["envelope_match"] is True
    assert validation["aligned_pairs"] is True
    assert set(validation["not_validated"]) == {
        "tread depth", "riser height", "landing length",
        "headroom", "flight continuity", "handrail/guard geometry",
    }
    assert "partial geometric validation only" in validation["claim"]
    assert any(w.startswith("UNIT-STAIR-02:") for w in response.warnings)


def test_natural_ladders_still_select_their_first_certified_rung():
    # The certified site keeps its natural S0/S1 rung and never turns into V3.
    ladder._CACHE.clear()
    response = ladder.solve_with_escalation(_req_adaptive(18.0, 24.0, partition_variant=None, units_per_floor=2))
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED
    assert response.multi_storey.strategy_selected in ("S0", "S1")
    assert "DUPLEX" not in response.generation_id
    assert not any(r.dwelling_id for f in response.multi_storey.floors for r in f.rooms)


def test_twelve_by_eighteen_ladder_sizes_the_kitchen_sash_to_its_daylight_need():
    # Release closure: the 9.6 m buildable's service-row kitchen has a 2.2 m
    # facade.  The engine now sizes the kitchen sash to the 1/8 openable-area
    # requirement (1.25 m -> 1.50 m2 for the 11.92 m2 kitchen) instead of the
    # generic 1.20 m minimum.  The ladder therefore certifies because the DRAWN
    # geometry meets the rule - not because the rule was relaxed - and every
    # kitchen on the plan is measured against its own requirement here.
    ladder._CACHE.clear()
    response = ladder.solve_with_escalation(_req_adaptive(12.0, 18.0, partition_variant=None, units_per_floor=2))
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED
    failures = [str(f) for f in ((response.model_dump().get("mathematical_certificate") or {}).get("failures") or [])]
    assert not any("kitchen has no exterior window" in f for f in failures)
    kitchens = 0
    for floor in response.multi_storey.floors:
        for room in floor.rooms:
            if "kitchen" not in room.room_id:
                continue
            kitchens += 1
            windows = [w for w in floor.windows if w.room_id == room.room_id]
            assert windows, room.room_id
            openable = sum(float(w.width_m) * VENT_WINDOW_HEIGHT_HABITABLE_M for w in windows)
            assert openable + 1e-6 >= room.area_sqm * 0.125, room.room_id
    assert kitchens == 8


def test_cache_key_keeps_different_plates_and_layouts_apart():
    compact = _solve_adaptive(_req_adaptive(12.0, 18.0))
    wide = _solve_adaptive(_req_adaptive(18.0, 24.0))
    assert ladder._plate_hash(_req_adaptive(12.0, 18.0)) != ladder._plate_hash(_req_adaptive(18.0, 24.0))
    assert compact.generation_id == wide.generation_id  # same typology, storeys, seed
    compact_plate = _decision(compact).get("plate") or _decision(compact)["previous_plate"]
    wide_plate = _decision(wide).get("plate") or _decision(wide)["previous_plate"]
    assert compact_plate != wide_plate
    warm = generate_floor_plan(_req_adaptive(18.0, 24.0))
    assert _stable_dump(warm) == _stable_dump(wide)


def test_repeated_row_solves_are_byte_stable():
    first = _solve_adaptive()
    second = _solve_adaptive()
    assert _stable_dump(first) == _stable_dump(second)


def test_solve_budget_never_exceeds_six():
    response = _isolation_s2(_req_adaptive(units_per_floor=2, partition_variant=None))
    chain = response.multi_storey.strategy_chain
    assert len(chain) <= ladder.MAX_SOLVES
    assert sum(1 for entry in chain if entry["status"] in ("certified", "fail")) <= ladder.MAX_SOLVES
    assert ladder.MAX_SOLVES == 6
