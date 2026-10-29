"""Deterministic site plausibility from the programme ontology.

A market matrix that rates a warehouse on a 180 m2 plot against the same
certification target as a house measures the wrong thing: the engine is
SUPPOSED to decline that programme, and its named decline is an honest answer,
not a certification failure.  The separation is computed here, from the
ontology alone - never from whether the solver happened to succeed.

    minimum_plot_area = programme_need x 1.15 + outdoor_allowance

  * ``programme_need`` is the ontology's own requirement for the largest floor
    (``land_economics.compute_program_needed_area``): the catalogue minimum
    areas plus the declared circulation (max(8 m2, 14%)), walls (8%) and core.
  * ``1.15`` is the project's construction/rounding allowance
    (``engine.PROGRAM_PLATE_ALLOWANCE``), not a new constant.
  * ``outdoor_allowance`` is the typology's highest-priority declared outdoor
    route (``ONTOLOGY.outdoor_routes``): the one labelled provision - garden,
    resident parking, visitor plaza, truck/trailer parking - the typology must
    be able to deliver outdoors.  Routes beyond it are optional upgrades, so
    they do not raise the floor.

The rule is deliberately independent of the solve: a programme over a plot's
minimum is IMPLAUSIBLE whether or not the engine manages to draw something, and
a plausible plot stays rated whether or not it certifies.
"""

from __future__ import annotations

from typing import Any, Dict

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.land_economics import compute_program_needed_area
from app.services.floorplan.engine import PROGRAM_PLATE_ALLOWANCE, SoleGeometryEngine
from app.services.floorplan.ontology import ONTOLOGY

PLAUSIBLE = "PLAUSIBLE"
IMPLAUSIBLE = "IMPLAUSIBLE"


def programme_need_sqm(req: FloorPlanRequest) -> float:
    """The ontology's programme need for this request (no solve, no geometry)."""
    engine = SoleGeometryEngine(req)
    return float(compute_program_needed_area(engine))


def outdoor_allowance_sqm(typology: str) -> float:
    """The typology's first labelled outdoor provision, from the ontology."""
    routes = ONTOLOGY.outdoor_routes(typology)
    return float(routes[0].min_area_sqm) if routes else 0.0


def minimum_plot_area_sqm(programme_need: float, outdoor_allowance: float) -> float:
    return round(programme_need * PROGRAM_PLATE_ALLOWANCE + outdoor_allowance, 2)


def classify_site_plausibility(req: FloorPlanRequest) -> Dict[str, Any]:
    """PLAUSIBLE / IMPLAUSIBLE for one request, with the numbers behind it."""
    engine = SoleGeometryEngine(req)
    need = float(compute_program_needed_area(engine))
    outdoor = outdoor_allowance_sqm(req.building_typology)
    plot_area = float(engine._plot_plan_area())
    minimum = minimum_plot_area_sqm(need, outdoor)
    plausible = plot_area + 1e-6 >= minimum
    routes = ONTOLOGY.outdoor_routes(req.building_typology)
    return {
        "classification": PLAUSIBLE if plausible else IMPLAUSIBLE,
        "plausible": plausible,
        "plot_area_sqm": round(plot_area, 2),
        "programme_need_sqm": round(need, 2),
        "programme_need_allowance_sqm": round(need * PROGRAM_PLATE_ALLOWANCE, 2),
        "outdoor_allowance_sqm": round(outdoor, 2),
        "outdoor_route": (routes[0].label if routes else None),
        "minimum_plot_area_sqm": minimum,
        "reason": (
            f"plot {plot_area:.1f} m2 >= minimum {minimum:.1f} m2 "
            f"(programme need {need:.1f} m2 x {PROGRAM_PLATE_ALLOWANCE:g} + "
            f"{outdoor:.1f} m2 {routes[0].label if routes else 'outdoor'}); "
            "the programme is expected to fit this plot"
            if plausible
            else (
                f"plot {plot_area:.1f} m2 < minimum {minimum:.1f} m2 "
                f"(programme need {need:.1f} m2 x {PROGRAM_PLATE_ALLOWANCE:g} + "
                f"{outdoor:.1f} m2 {routes[0].label if routes else 'outdoor'}); "
                "a named decline is the expected outcome"
            )
        ),
    }
