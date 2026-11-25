"""A multi-wing plate must carry the REQUESTED typology's programme.

The multi-wing partitioner used to draw the T1 residence on every typology, so
a T2 plate came back with living/kitchen/master_bed, a T3 plate with no office
cell and a T4 plate with no bay.  The product the user asked for was silently
swapped for a house.  These pins run the real entry point on an L-shaped plate
and judge the drawn programme's ontology types against the typology catalogue.

A refusal is allowed (an L-wing cannot always host a warehouse) but it must be a
named refusal - gate FAIL, deficit/UNFIT warning - never a T1 drawing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.floorplan import FloorPlanRequest  # noqa: E402
from app.schemas.site_plan import PlotPolygonModel  # noqa: E402
from app.services.floorplan.floorplan_service import generate_floor_plan  # noqa: E402

#: 18 x 18 L plate (the L-244 shape): a main block plus a wing, big enough that
#: T2 and T3 can actually be drawn, small enough that T4 must refuse.
L_PLATE = [(0, 0), (18, 0), (18, 10), (10, 10), (10, 18), (0, 18)]

TYPOLOGY_MARKERS = {
    "T2_FAMILY_APARTMENT": {"unit_living", "unit_kitchen", "unit_bed", "unit_bath", "unit_balcony"},
    "T3_LARGE_COMPLEX": {"commercial_suite", "conference_suite", "sanitary_block", "server_room",
                         "reception_lobby", "mep_room"},
    "T4_WAREHOUSE": {"storage_bay", "dock_bay", "dispatch", "worker_amenity",
                     "admin_catwalk", "washdown_point"},
}
#: Rooms that belong to the single-family programme and to nothing else.
T1_ONLY = {"living", "kitchen", "master_bed", "bed_2", "puja", "dining",
           "bath_1", "bath_2", "study", "guest_bed"}


def _l_plate():
    return PlotPolygonModel(
        vertices=L_PLATE,
        shape_type="polygon",
        has_curved_edges=False,
        is_regular_rectangle=False,
        area_sqm=0.0,
        perimeter_m=0.0,
        bounding_box=(0, 0, 18, 18),
    )


def _generate(typology: str, floors: int = 2):
    return generate_floor_plan(FloorPlanRequest(
        plot_width_m=18.0,
        plot_depth_m=18.0,
        ground_coverage_ratio=0.60,
        building_typology=typology,
        floors=floors,
        plot_polygon=_l_plate(),
        vastu_strictness="high",
        bypass_cache=True,
        ai_provider="mock",
        seed="42",
        include_scheme_alternatives=True,
    ))


def _types(response) -> set:
    ms = response.multi_storey
    if ms is None:
        return set()
    return {
        str(r.space_type_id or (r.identity.space_type_id if r.identity else ""))
        for f in ms.floors for r in f.rooms
    } - {""}


@pytest.mark.parametrize("typology, markers", sorted(TYPOLOGY_MARKERS.items()))
def test_l_plate_draws_the_requested_typology_not_the_t1_residence(typology, markers):
    resp = _generate(typology)
    assert resp.multi_storey is not None, resp.warnings[:4]
    types = _types(resp)
    drawn_rooms = sum(len(f.rooms) for f in resp.multi_storey.floors)

    if drawn_rooms == 0:
        # Refusal is a legitimate answer on this plate - but only a NAMED one.
        gate = resp.multi_storey.validation_gate or {}
        assert str(gate.get("overall_status")).upper() == "FAIL", gate
        assert any(
            w.startswith(("GEN-UNFIT", "LAND-01", "PROGRAMME-DEFICIT")) for w in resp.warnings
        ), resp.warnings[:5]
        assert resp.unmet_requirements, "a refusal must name what could not be placed"
        return

    assert types, "a drawn plate with no resolved space type cannot be judged"
    # The typology's own programme must appear...
    assert markers & types, (
        f"{typology} drew no programme room of its own; types={sorted(types)}"
    )
    # ...and the T1 residence must not be standing in for it.
    leaked = types & T1_ONLY
    assert not leaked, (
        f"{typology} fell back to the T1 residence programme: {sorted(leaked)}"
    )


def test_t1_l_plate_still_draws_the_residence_programme():
    """Control: the T1 path is unchanged by the typology dispatch."""
    resp = _generate("residential_single")
    assert resp.multi_storey is not None
    types = _types(resp)
    assert {"living", "kitchen"} <= types, sorted(types)
    assert not (types & {"unit_living", "commercial_suite", "storage_bay"}), sorted(types)


def test_l_plate_apartment_has_a_shared_core_and_two_units():
    """The T2 floor is units + ONE shared core, not a house with a stair."""
    resp = _generate("residential_apartment")
    assert resp.multi_storey is not None
    floor = resp.multi_storey.floors[0]
    ids = [r.room_id for r in floor.rooms]
    types = _types(resp)

    cores = [r for r in floor.rooms if r.is_vertical_core]
    assert len(cores) == 1, ids
    assert "unit_living" in types and "unit_bed" in types, sorted(types)
    # Both wings carry a part of the requested programme (A around the core,
    # B in the other wing) rather than the second wing being left as a house
    # bedroom.
    assert any("unitA" in rid for rid in ids), ids
    assert any("unitB" in rid for rid in ids), ids


def test_single_alternative_is_disclosed_for_the_multi_wing_portfolio():
    """An L plate offers its one validated layout WITH the reason named."""
    resp = _generate("residential_apartment")
    alts = resp.scheme_alternatives or []
    portfolio = resp.scheme_portfolio
    assert portfolio is not None
    assert len(alts) == 1, [a.scheme_id for a in alts]
    disclosure = (portfolio.provenance or {}).get("no_material_alternative")
    assert disclosure and "no materially different alternative" in disclosure.lower()
    # The single card is the drawn geometry, not an empty placeholder.
    assert alts[0].floors and any(f.rooms for f in alts[0].floors)
