"""
test_generation_engine_completion.py - generation-engine contract tests.
==============================================================
Pins:
- Determinism: same seed -> byte-identical geometry/sheets (wall-clock timing
  fields excluded as measurements, not geometry).
- Explicit numeric seed honored by the engine; GEN/CERT tokens derive from it.
- Unsolved-requirements ledger: requested-but-unplaced rooms surface with
  explicit reasons; satisfied requests leave the ledger empty (zero silent
  skips for user requirements).
- Ontology catalog coverage: every front-end room chip exists in the ontology
  or resolves through the catalog normalizer (no orphan UI rooms).
"""
import re

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.typologies import get_typology_module
from app.services.floorplan.ontology import ONTOLOGY
from app.services.floorplan.grid_model import normalize_room_identifier


VOLATILE_KEYS = {"solver_timing_ms", "timing_ms", "generated_at", "evaluated_at"}


def _strip_volatile(obj):
    """Recursively removes wall-clock measurement fields for equality checks."""
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


def _build(**kw):
    return generate_floor_plan(FloorPlanRequest(**kw))


# --------------------------------------------------------------------------- #
#  Determinism pin: explicit same-seed byte-equality                         #
# --------------------------------------------------------------------------- #

def test_same_seed_byte_identical_geometry_default_seed():
    a = _build(plot_width_m=12, plot_depth_m=15, floors=2,
               required_rooms=["living", "kitchen", "master_bed"])
    b = _build(plot_width_m=12, plot_depth_m=15, floors=2,
               required_rooms=["living", "kitchen", "master_bed"])
    assert _strip_volatile(a.multi_storey.model_dump()) == _strip_volatile(b.multi_storey.model_dump())
    assert a.svg_blueprint == b.svg_blueprint
    assert a.svg_blueprint_paper == b.svg_blueprint_paper
    assert a.grid_matrix == b.grid_matrix
    assert a.generation_id == b.generation_id


def test_explicit_seed_changes_tokens_not_validity():
    r = _build(plot_width_m=12, plot_depth_m=15, floors=1, seed="7")
    assert r.seed == "7"
    assert r.generation_id == "GEN-T1-1F-7"
    r2 = _build(plot_width_m=12, plot_depth_m=15, floors=1, seed=7)
    assert r2.generation_id == "GEN-T1-1F-7"
    # Same explicit seed -> identical geometry (determinism holds for seeds != 42 too)
    assert _strip_volatile(r.multi_storey.model_dump()) == _strip_volatile(r2.multi_storey.model_dump())


def test_non_numeric_seed_falls_back_to_historical_42():
    r = _build(plot_width_m=12, plot_depth_m=15, floors=1, seed="GEN-F01")
    assert r.generation_id == "GEN-T1-1F-42"


# --------------------------------------------------------------------------- #
#  Unsolved requirements ledger                                                #
# --------------------------------------------------------------------------- #

def test_satisfied_requests_leave_ledger_empty():
    r = _build(plot_width_m=12, plot_depth_m=15, floors=2,
               required_rooms=["living", "kitchen", "master_bed"])
    assert r.unmet_requirements == []


def test_typology_mismatched_requests_surface_with_reason():
    r = _build(plot_width_m=12, plot_depth_m=15, floors=1,
               building_typology="T4_WAREHOUSE",
               required_rooms=["living", "kitchen", "master_bed", "puja"])
    assert r.unmet_requirements is not None
    ids = {u["room_id"] for u in r.unmet_requirements}
    assert {"living", "kitchen", "master_bed", "puja"} <= ids
    for u in r.unmet_requirements:
        assert "T4_WAREHOUSE" in u["reason"] or "program" in u["reason"]


def test_core_equivalence_requesting_stairs_satisfied_by_any_core():
    r = _build(plot_width_m=18, plot_depth_m=20, floors=3,
               required_rooms=["living", "kitchen", "master_bed", "stairs"])
    assert r.unmet_requirements == []


def test_unmet_requirements_absent_when_no_rooms_requested():
    r = _build(plot_width_m=12, plot_depth_m=15, floors=1)
    assert r.unmet_requirements == []


# --------------------------------------------------------------------------- #
#  Ontology catalog coverage (UI chips must resolve to real ontology spaces)   #
# --------------------------------------------------------------------------- #

def test_typology_program_ids_resolve_through_normalizer():
    """Every program space id must exist in the ontology - except declared composites.

    Contract: typology programs may not reference ontology-ghost ids.
    The only sanctioned exceptions are _COMPOSITE_IDS (unit/bay aggregates the
    solver renders as leaf rooms and never places as geometry).
    """
    composites_total = set()
    for typology in ("T1_SINGLE_FAMILY", "T2_FAMILY_APARTMENT", "T3_LARGE_COMPLEX", "T4_WAREHOUSE"):
        module = get_typology_module(typology)
        composites = set(getattr(module, "_COMPOSITE_IDS", []) or [])
        composites_total |= composites
        for level in range(1, 5):
            for entry in module.vertical_program(level):
                for sid in entry.get("space_ids", []):
                    # The normalizer must never destroy a canonical program id.
                    assert normalize_room_identifier(sid), sid
                    if sid in composites:
                        continue
                    spec = ONTOLOGY.get_space(sid)
                    assert spec is not None, f"{typology}: program id {sid!r} missing from ontology"
    assert composites_total, "composite-id contract must be exercised"


def test_composite_program_ids_never_placed_as_geometry():
    """Declared composites (apt_unit_N, heavy_bay, ...) must never become rooms."""
    composites_total = set()
    for typology, storeys in (("T1_SINGLE_FAMILY", 2), ("T2_FAMILY_APARTMENT", 2),
                              ("T3_LARGE_COMPLEX", 2), ("T4_WAREHOUSE", 1)):
        module = get_typology_module(typology)
        composites_total |= set(getattr(module, "_COMPOSITE_IDS", []) or [])
        r = _build(plot_width_m=18, plot_depth_m=20, floors=storeys, building_typology=typology)
        for fl in r.multi_storey.floors:
            for room in fl.rooms:
                base = re.sub(r"_F\d+$", "", room.room_id)
                assert base not in composites_total, (
                    f"{typology}: composite {base!r} must not be placed as geometry"
                )
    assert composites_total, "composite-id contract must be exercised"


def test_placed_core_rooms_are_real_ontology_cores():
    """Every placed vertical core must belong to the typology profile core_types.

    Plate room_ids use engine core_id prefixes (core_staircase_primary_F0...)
    that are deliberately not ontology ids; the single-source contract is that
    the building's vertical_cores[].core_type values are drawn exclusively
    from the typology profile in the ontology.
    """
    from app.services.floorplan.ontology import TYPOLOGY_PROFILES
    for typology in ("T1_SINGLE_FAMILY", "T2_FAMILY_APARTMENT", "T3_LARGE_COMPLEX", "T4_WAREHOUSE"):
        kw = dict(plot_width_m=18, plot_depth_m=20, floors=2, building_typology=typology)
        if typology == "T4_WAREHOUSE":
            kw["floors"] = 1
        r = _build(**kw)
        profile = TYPOLOGY_PROFILES[typology]
        vcs = r.multi_storey.vertical_cores
        assert vcs, f"{typology}: solver must declare at least one vertical core"
        for vc in vcs:
            assert vc.core_type in profile.core_types, (
                f"{typology}: core_type {vc.core_type!r} not in profile {profile.core_types}"
            )


# --------------------------------------------------------------------------- #
#  Snapshot / frontage coupling (audit 3.7: frontage in params_snapshot)       #
# --------------------------------------------------------------------------- #

def test_params_snapshot_includes_frontage_field():
    r = _build(plot_width_m=12, plot_depth_m=15, floors=1)
    snap = r.params_snapshot or {}
    assert "frontage_edge_index" in snap
    assert snap["frontage_edge_index"] is None
    assert "frontage_source" in snap
    # Stale-guard contract: polygon must be in the snapshot when captured.
    assert "plot_polygon" in snap
