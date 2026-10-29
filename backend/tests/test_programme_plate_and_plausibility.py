"""Programme-following plate and ontology-plausibility pins.

PLATES — a default brief on an oversized plot must get a programme-sized plate.
T2 had this policy; T1/T3/T4 fell through to the full coverage cap, and a 63 m2
brief on a 240 m2 cap stretched bath (15.9 vs 6.0), dining (23.3 vs 14.0) and
living (72.6 vs 35.0) past their catalogue bands.

PLAUSIBILITY — a market matrix must rate certification on plots the programme
can actually occupy.  A warehouse on 180 m2 is supposed to be DECLINED; counting
that decline against a certification rate measures the wrong thing.  The
classification is computed from the ontology, before and independently of any
solve.
"""
import sys

sys.path.insert(0, ".")

import pytest  # noqa: E402

from app.schemas.floorplan import FloorPlanRequest  # noqa: E402
from app.services.floorplan.engine import PROGRAM_PLATE_ALLOWANCE  # noqa: E402
from app.services.floorplan.ontology import ONTOLOGY  # noqa: E402
from app.services.floorplan.plausibility import (  # noqa: E402
    IMPLAUSIBLE,
    PLAUSIBLE,
    classify_site_plausibility,
    minimum_plot_area_sqm,
    outdoor_allowance_sqm,
    programme_need_sqm,
)
from app.services.floorplan.strategy_escalation import _CACHE, solve_with_escalation  # noqa: E402
from app.services.plan_verdict import CERTIFIED, compute_plan_verdict, plan_truth_labels  # noqa: E402


def _request(width=20.0, depth=20.0, typology="T1_SINGLE_FAMILY", floors=1):
    return FloorPlanRequest(
        plot_width_m=width,
        plot_depth_m=depth,
        building_typology=typology,
        floors=floors,
        ground_coverage_ratio=0.60,
        vastu_strictness="high",
        seed=f"s7-{typology[:2]}-{int(width)}x{int(depth)}-F{floors}",
        ai_provider="mock",
        bypass_cache=True,
        confirm_dwelling_deficit=True,
    )


def _solve(req):
    _CACHE.clear()
    return solve_with_escalation(req)


def _floor_rooms(response):
    if not response.multi_storey:
        return []
    return [room for floor in response.multi_storey.floors for room in floor.rooms]


# ---------------------------------------------------------------- plates


def test_t1_oversized_plot_gets_a_programme_sized_plate():
    """T1 on 20 x 20 must not get the 240 m2 coverage cap."""
    response = _solve(_request(typology="T1_SINGLE_FAMILY"))
    need = float(response.land_economics.program_needed_area_m2)
    plate = float(response.site_plan.footprint.area_sqm)
    assert need > 0.0
    assert plate <= need * PROGRAM_PLATE_ALLOWANCE + 1.5, (
        f"plate {plate} is not programme-sized against a need of {need}"
    )
    assert plate < 0.60 * 20.0 * 20.0 - 1.0, "the coverage cap must never be the target"
    assert response.land_economics.footprint_source == "program"


def test_t1_rooms_stay_inside_their_catalogue_bands():
    """No silent stretch: every ROOM-MAX row must be a listed, within-cap row.

    The dining room on this plate is 17.4 m2 against a 14.0 m2 catalogue
    maximum - inside the 1.40x listing cap, so it is disclosed as a deviation
    and never as a beyond-cap breach.  What may not happen is the older
    behaviour: bath 15.9 vs 6.0 (2.65x) and living 72.6 vs 35.0 (2.07x).
    """
    response = _solve(_request(typology="T1_SINGLE_FAMILY"))
    rooms = {room.room_id: float(room.area_sqm) for room in _floor_rooms(response)}
    assert rooms, "the T1 default brief must draw rooms"
    labels = plan_truth_labels(response.model_dump())
    for row in labels["unresolved_breaches"]:
        assert not row.startswith("ROOM-MAX"), f"a beyond-cap stretch remains: {row[:110]}"
    # The old stretch is gone: no room sits above 1.40x its catalogue maximum.
    for row in response.warnings:
        text = str(row)
        if text.startswith("ROOM-MAX"):
            measured, ceiling = [
                float(part) for part in __import__("re").findall(
                    r"([\d.]+)\s*m\u00b2", text
                )[:2]
            ]
            assert measured / ceiling <= 1.40 + 1e-9, text[:120]


def test_t1_surplus_is_routed_outdoors():
    response = _solve(_request(typology="T1_SINGLE_FAMILY"))
    economics = response.land_economics
    assert economics is not None
    assert economics.outdoor_area_sqm > 0.0, "the plot surplus must be routed outdoors"
    assert economics.footprint_area_sqm < economics.buildable_area_sqm
    zones = (response.site_plan.model_dump() if response.site_plan else {}).get("outdoor_zones") or []
    assert zones, "the surplus must carry its labelled outdoor zones"


def test_t2_calibrated_plate_is_unchanged():
    """The T2 branch is calibrated (single-unit core) and must not churn."""
    response = _solve(_request(typology="T2_FAMILY_APARTMENT"))
    plate = float(response.site_plan.footprint.area_sqm)
    assert plate <= 140.0, f"T2 plate {plate} left the calibrated band"
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED


def test_t3_and_t4_are_programme_sized_too():
    for typology in ("T3_LARGE_COMPLEX", "T4_WAREHOUSE"):
        response = _solve(_request(typology=typology))
        need = float(response.land_economics.program_needed_area_m2)
        plate = float(response.site_plan.footprint.area_sqm)
        assert plate <= need * PROGRAM_PLATE_ALLOWANCE + 1.5, (
            f"{typology}: plate {plate} not programme-sized (need {need})"
        )
        assert response.land_economics.footprint_source == "program"


def test_t4_oversized_plot_certifies():
    """T4 certifies on the oversized rectangular plate."""
    response = _solve(_request(typology="T4_WAREHOUSE"))
    assert compute_plan_verdict(response.model_dump()) == CERTIFIED


def test_plate_sizing_is_deterministic():
    first = _solve(_request(typology="T1_SINGLE_FAMILY"))
    second = _solve(_request(typology="T1_SINGLE_FAMILY"))
    plate_a = first.site_plan.footprint.area_sqm
    plate_b = second.site_plan.footprint.area_sqm
    assert plate_a == plate_b
    rooms_a = sorted((r.room_id, r.x, r.y, r.width_m, r.depth_m) for r in _floor_rooms(first))
    rooms_b = sorted((r.room_id, r.x, r.y, r.width_m, r.depth_m) for r in _floor_rooms(second))
    assert rooms_a == rooms_b


# ----------------------------------------------------------- plausibility


def test_minimum_plot_area_uses_the_ontology_programme_need():
    req = _request(width=12.0, depth=15.0, typology="T4_WAREHOUSE")
    need = programme_need_sqm(req)
    outdoor = outdoor_allowance_sqm("T4_WAREHOUSE")
    assert outdoor == ONTOLOGY.outdoor_routes("T4_WAREHOUSE")[0].min_area_sqm
    assert minimum_plot_area_sqm(need, outdoor) == round(
        need * PROGRAM_PLATE_ALLOWANCE + outdoor, 2
    )


def test_warehouse_on_180m2_is_implausible_with_a_named_reason():
    verdict = classify_site_plausibility(_request(width=12.0, depth=15.0, typology="T4_WAREHOUSE"))
    assert verdict["classification"] == IMPLAUSIBLE
    assert verdict["plausible"] is False
    assert verdict["plot_area_sqm"] == pytest.approx(180.0)
    assert verdict["minimum_plot_area_sqm"] > 180.0
    assert "named decline is the expected outcome" in verdict["reason"]
    # The classification is computed BEFORE any solve: no plan, no verdict,
    # no geometry involved.
    assert "programme_need_sqm" in verdict and verdict["programme_need_sqm"] > 0.0


def test_house_on_the_same_plot_is_plausible():
    verdict = classify_site_plausibility(_request(width=12.0, depth=15.0, typology="T1_SINGLE_FAMILY"))
    assert verdict["classification"] == PLAUSIBLE
    assert verdict["minimum_plot_area_sqm"] < verdict["plot_area_sqm"]
    assert "expected to fit" in verdict["reason"]


def test_plausibility_is_independent_of_the_solve():
    """A plausible case stays plausible whatever the plan's verdict is.

    This 20 x 20 m house now CERTIFIES.  The contract under test is the
    independence of the two measures, not the old failure: the classification is
    computed from the ontology before any geometry, and re-computing it after a
    full solve must return the same answer.
    """
    req = _request(width=20.0, depth=20.0, typology="T1_SINGLE_FAMILY")
    classification = classify_site_plausibility(req)
    response = _solve(req)
    assert classification["classification"] == PLAUSIBLE
    assert classify_site_plausibility(req)["classification"] == PLAUSIBLE
    assert compute_plan_verdict(response.model_dump())
