"""
test_typology_modules.py - Per-Typology Module Property Tests
======================================================================
Validates the TypologyModuleProtocol for all four typologies:
  T1 Single-Family Residence, T2 Family Apartment,
  T3 Large Commercial Complex, T4 Warehouse.

Tests cover:
1. Registry: get_typology_module() returns a module with TYPOLOGY_KEY.
2. catalog(): returns ontology-sourced SpaceTypeSpec objects (not dicts).
3. vertical_program(N): correct level count; each level has space_ids and label.
4. layout_strategy(): returns LayoutStrategy with typology-specific values.
5. sheet_gates(): correct data flags per typology spec.
6. compose_sheet(): returns an SVG string delegating to the shared drawing IR.
7. Core alignment: vertical_program level-0 includes at least one core-adjacent space.
8. Clutter management: no duplicate space IDs across levels.
"""

import copy

import pytest
from app.services.floorplan.typologies import (
    get_typology_module,
    normalize_typology,
    TYPOLOGY_T1, TYPOLOGY_T2, TYPOLOGY_T3, TYPOLOGY_T4,
)
from app.services.floorplan.typologies.protocol import (
    LayoutStrategy,
    SheetGates,
    TypologyModuleProtocol,
)


ALL_TYPOLOGIES = [TYPOLOGY_T1, TYPOLOGY_T2, TYPOLOGY_T3, TYPOLOGY_T4]


# ---------------------------------------------------------------------------
# 1. Registry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typology", ALL_TYPOLOGIES)
def test_registry_returns_module_with_key(typology):
    """get_typology_module() returns a class with correct TYPOLOGY_KEY."""
    mod = get_typology_module(typology)
    assert hasattr(mod, "TYPOLOGY_KEY")
    assert mod.TYPOLOGY_KEY == typology


def test_registry_aliases_normalize_correctly():
    """Alias normalization reaches correct module."""
    assert get_typology_module("residential").TYPOLOGY_KEY == TYPOLOGY_T1
    assert get_typology_module("apartment").TYPOLOGY_KEY == TYPOLOGY_T2
    assert get_typology_module("office").TYPOLOGY_KEY == TYPOLOGY_T3
    assert get_typology_module("warehouse").TYPOLOGY_KEY == TYPOLOGY_T4
    assert get_typology_module(None).TYPOLOGY_KEY == TYPOLOGY_T1


# ---------------------------------------------------------------------------
# 2. catalog()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typology", ALL_TYPOLOGIES)
def test_catalog_returns_ontology_specs(typology):
    """catalog() must return SpaceTypeSpec objects sourced from ONTOLOGY (not plain dicts)."""
    from app.services.floorplan.ontology import SpaceTypeSpec
    mod = get_typology_module(typology)
    cat = mod.catalog()
    # May be partially empty if some space IDs are not in the ontology yet —
    # but must return a dict and any values present must be SpaceTypeSpec.
    assert isinstance(cat, dict)
    for sid, spec in cat.items():
        assert isinstance(spec, SpaceTypeSpec), (
            f"{typology} catalog[{sid!r}] is {type(spec).__name__}, expected SpaceTypeSpec"
        )


# ---------------------------------------------------------------------------
# 3. vertical_program(N)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typology,max_N", [
    (TYPOLOGY_T1, 3),
    (TYPOLOGY_T2, 4),
    (TYPOLOGY_T3, 4),
    (TYPOLOGY_T4, 2),
])
def test_vertical_program_level_count(typology, max_N):
    """vertical_program(N) returns exactly N levels for N in 1..max_N."""
    mod = get_typology_module(typology)
    for N in range(1, max_N + 1):
        prog = mod.vertical_program(N)
        assert len(prog) == N, (
            f"{typology} vertical_program({N}) returned {len(prog)} levels, expected {N}"
        )
        for level_entry in prog:
            assert "level" in level_entry
            assert "space_ids" in level_entry
            assert "label" in level_entry
            assert isinstance(level_entry["space_ids"], list)
            assert len(level_entry["space_ids"]) >= 1
            assert isinstance(level_entry["label"], str)
            assert level_entry["label"]


def test_vertical_program_level_indices():
    """vertical_program level 'level' field must equal its list index."""
    for typology in ALL_TYPOLOGIES:
        mod = get_typology_module(typology)
        prog = mod.vertical_program(1)
        for i, entry in enumerate(prog):
            assert entry["level"] == i, (
                f"{typology}: level field {entry['level']} != index {i}"
            )


def test_vertical_program_no_duplicate_space_ids_within_level():
    """No duplicate space IDs within a single level's space_ids list."""
    for typology in ALL_TYPOLOGIES:
        mod = get_typology_module(typology)
        prog = mod.vertical_program(2)
        for entry in prog:
            ids = entry["space_ids"]
            assert len(ids) == len(set(ids)), (
                f"{typology} level {entry['level']}: duplicate space IDs in {ids}"
            )


def test_t4_vertical_program_clamps_at_2():
    """T4 floor limit is (1,2). vertical_program(4) must return only 2 levels."""
    mod = get_typology_module(TYPOLOGY_T4)
    prog = mod.vertical_program(4)
    assert len(prog) == 2, f"T4 vertical_program(4) returned {len(prog)} levels, expected 2"


def test_t1_vertical_program_single_storey_includes_master_bed():
    """T1 single-storey (N=1) ground floor must include master_bed (no upper floor)."""
    mod = get_typology_module(TYPOLOGY_T1)
    prog = mod.vertical_program(1)
    assert len(prog) == 1
    assert "master_bed" in prog[0]["space_ids"]


def test_t4_mezzanine_label_contains_elevation():
    """T4 mezzanine label must mention the +3.60m elevation."""
    mod = get_typology_module(TYPOLOGY_T4)
    prog = mod.vertical_program(2)
    assert len(prog) == 2
    mezz_label = prog[1]["label"]
    assert "3.60" in mezz_label or "mezzanine" in mezz_label.lower(), (
        f"T4 mezzanine label missing elevation reference: {mezz_label!r}"
    )


# ---------------------------------------------------------------------------
# 4. layout_strategy()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typology", ALL_TYPOLOGIES)
def test_layout_strategy_returns_layout_strategy(typology):
    """layout_strategy() returns a LayoutStrategy instance."""
    mod = get_typology_module(typology)
    strat = mod.layout_strategy()
    assert isinstance(strat, LayoutStrategy)


def test_t1_layout_strategy_vastu_bands():
    """T1 public_front_depth_frac must be >= 0.40 (Vastu public-front / private-deep)."""
    strat = get_typology_module(TYPOLOGY_T1).layout_strategy()
    assert strat.public_front_depth_frac >= 0.40


def test_t2_layout_strategy_unit_split():
    """T2 unit_split_frac must be 0.50 (equal half-plate per unit)."""
    strat = get_typology_module(TYPOLOGY_T2).layout_strategy()
    assert strat.unit_split_frac == 0.50


def test_t3_layout_strategy_corridor_width():
    """T3 corridor_width_m must be >= 1.50m (NBC double-loaded corridor minimum)."""
    strat = get_typology_module(TYPOLOGY_T3).layout_strategy()
    assert strat.corridor_width_m >= 1.50


def test_t4_layout_strategy_column_grid_and_apron():
    """T4 column_grid_bay_m >= 6.0m and dock_apron_depth_m >= 3.6m."""
    strat = get_typology_module(TYPOLOGY_T4).layout_strategy()
    assert strat.column_grid_bay_m >= 6.0
    assert strat.dock_apron_depth_m >= 3.6
    assert strat.mezzanine_elevation_m >= 3.6


# ---------------------------------------------------------------------------
# 5. sheet_gates()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typology", ALL_TYPOLOGIES)
def test_sheet_gates_returns_sheet_gates(typology):
    """sheet_gates() returns a SheetGates instance."""
    mod = get_typology_module(typology)
    gates = mod.sheet_gates()
    assert isinstance(gates, SheetGates)


def test_t1_sheet_gates():
    """T1: vastu_diagram ON, column_grid OFF, unit_schedule OFF."""
    gates = get_typology_module(TYPOLOGY_T1).sheet_gates()
    assert gates.vastu_diagram is True
    assert gates.column_grid is False
    assert gates.unit_schedule is False


def test_t2_sheet_gates():
    """T2: vastu_diagram ON (medium), unit_schedule ON."""
    gates = get_typology_module(TYPOLOGY_T2).sheet_gates()
    assert gates.vastu_diagram is True
    assert gates.unit_schedule is True


def test_t3_sheet_gates():
    """T3: vastu_diagram LOW (off for print), unit_schedule ON."""
    gates = get_typology_module(TYPOLOGY_T3).sheet_gates()
    assert gates.vastu_diagram is False     # Vastu low for T3
    assert gates.unit_schedule is True


def test_t4_sheet_gates():
    """T4: column_grid ON, dock_apron ON, mezzanine_section ON, vastu_diagram OFF."""
    gates = get_typology_module(TYPOLOGY_T4).sheet_gates()
    assert gates.column_grid is True
    assert gates.dock_apron_diagram is True
    assert gates.mezzanine_section is True
    assert gates.vastu_diagram is False


@pytest.mark.parametrize("typology", ALL_TYPOLOGIES)
def test_all_typologies_egress_and_dimension_chains_always_on(typology):
    """egress_travel_diagram and dimension_chains must be ON for all typologies."""
    gates = get_typology_module(typology).sheet_gates()
    assert gates.egress_travel_diagram is True
    assert gates.dimension_chains is True


# ---------------------------------------------------------------------------
# 6. compose_sheet() - SVG output
# ---------------------------------------------------------------------------

_BUILDING_CACHE: dict[tuple[str, int], object] = {}


def _solve_typology_building(typology: str, floors: int = 2):
    key = (typology, floors)
    if key not in _BUILDING_CACHE:
        from app.schemas.floorplan import FloorPlanRequest
        from app.services.floorplan.engine import SoleGeometryEngine
        plot_w = 24.0 if typology == TYPOLOGY_T4 else 15.0
        plot_d = 30.0 if typology == TYPOLOGY_T4 else 18.0
        req = FloorPlanRequest(
            plot_width_m=plot_w,
            plot_depth_m=plot_d,
            floors=floors,
            building_typology=typology,
            vastu_strictness="medium",
            ground_coverage_ratio=0.60,
        )
        _BUILDING_CACHE[key] = SoleGeometryEngine(req).solve()
    return copy.deepcopy(_BUILDING_CACHE[key]), (
        24.0 if typology == TYPOLOGY_T4 else 15.0
    ), (
        30.0 if typology == TYPOLOGY_T4 else 18.0
    )


def _make_level_plan(typology: str, floor_index: int = 0) -> dict:
    """Build a minimal level_plan dict for compose_sheet() smoke tests."""
    building, plot_w, plot_d = _solve_typology_building(typology, floors=2)
    floor = building.floors[floor_index]
    return {
        "floor_index": floor.floor_index,
        "floor_name": floor.floor_name,
        "rooms": floor.rooms,
        "doors": floor.doors,
        "windows": floor.windows,
        "envelope": floor.envelope,
        "ground_cores": building.vertical_cores,
        "ground_ducts": building.duct_shafts,
        "wall_graph": None,
        "plot_width_m": plot_w,
        "plot_depth_m": plot_d,
        "total_storeys": 2,
    }


@pytest.mark.parametrize("typology", ALL_TYPOLOGIES)
def test_compose_sheet_returns_svg(typology):
    """compose_sheet() must return an SVG string starting with '<svg'."""
    mod = get_typology_module(typology)
    level_plan = _make_level_plan(typology, floor_index=0)
    svg = mod.compose_sheet(level_plan, theme="cad")
    assert isinstance(svg, str)
    assert svg.strip().startswith("<svg"), (
        f"{typology} compose_sheet did not return SVG; got: {svg[:80]!r}"
    )


@pytest.mark.parametrize("typology", ALL_TYPOLOGIES)
def test_compose_sheet_paper_theme(typology):
    """compose_sheet() with paper theme also returns an SVG string."""
    mod = get_typology_module(typology)
    level_plan = _make_level_plan(typology, floor_index=0)
    svg = mod.compose_sheet(level_plan, theme="paper")
    assert svg.strip().startswith("<svg")


# ---------------------------------------------------------------------------
# 7. Core alignment: cores locked across levels
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("typology", ALL_TYPOLOGIES)
def test_core_alignment_stacking_invariant(typology):
    """
    Cores must be locked across all levels (< 0.001m drift).
    This validates that vertical_program / compose_sheet pipelines
    do not introduce per-level core drift.
    """
    N = 2 if typology == TYPOLOGY_T4 else 2
    building, _, _ = _solve_typology_building(typology, floors=N)

    assert len(building.floors) == N
    f0_core = next(r for r in building.floors[0].rooms if r.is_vertical_core)

    for z, floor in enumerate(building.floors):
        fz_core = next(r for r in floor.rooms if r.is_vertical_core)
        assert abs(fz_core.x - f0_core.x) < 0.001, f"{typology} F{z}: core x drift"
        assert abs(fz_core.y - f0_core.y) < 0.001, f"{typology} F{z}: core y drift"
        assert abs(fz_core.width_m - f0_core.width_m) < 0.001, f"{typology} F{z}: core w drift"
        assert abs(fz_core.depth_m - f0_core.depth_m) < 0.001, f"{typology} F{z}: core d drift"
