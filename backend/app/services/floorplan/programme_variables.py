"""Declarative programme variables per typology.

The solver used to treat the programme as a constant: two T2 units on every
floor, the same partition repeated storey after storey, and an amenity strip on
every level.  The values below make the design variables explicit so the
escalation ladder can search them without inventing geometry:

  units_per_floor       how many dwellings share one plate (a RANGE, not a number;
                        only values the partitioner can actually draw are declared)
  unit_stacking         "repeat" for a fresh floor plan, "duplex" when a unit may
                        occupy two storeys and be stacked vertically
  amenity_placement     where the shared amenity strip belongs
  representative_floor  which floor governs a stack-solved building

Nothing here changes a gate, a minimum or a certificate rule; it only names the
choices the engine already made implicitly.  Defaults reproduce the historic
geometry exactly, which the regression pins assert.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ProgrammeVariables:
    """The design variables a typology exposes to the solver."""

    typology: str
    units_per_floor_range: Tuple[int, int]
    default_units_per_floor: int
    unit_stacking: str  # "repeat" | "duplex"
    amenity_placement: str  # "all" | "ground" | "upper"
    representative_floor: Optional[str] = None  # None = solve every floor
    per_floor_roles: Dict[int, str] = field(default_factory=dict)
    # V3: when a dwelling spans two storeys, a plate draws four floor-level
    # units so that two two-storey dwellings are produced per floor pair.  The
    # count is declared separately from ``units_per_floor_range`` because the
    # latter is the ordinary (one-level) dwelling range exposed to the API.
    duplex_units_per_floor: int = 1
    duplex_storeys_per_dwelling: int = 1

    def resolve_units(self, requested: Optional[int], variant: Optional[str] = None) -> int:
        """Resolve a requested unit count without silently inventing a layout.

        ``None`` keeps the declared default.  For T2 - the typology whose
        range was over-declared - a value outside the range is an explicit
        refusal, never a clamp: a request for three units must not be answered
        with a two-unit plan that merely reports three.  The API layer rejects
        the same value before the engine is constructed; this guard protects
        direct engine callers too.  Other typologies keep the historical clamp
        and report the resolved value, so a previously tolerated request does
        not become a server error in this stage.

        ``variant='duplex'`` is the explicit V3 doorway: it draws
        ``duplex_units_per_floor`` floor-level units and accepts only that
        count (or ``None``), never a conventional one- or two-unit count.
        """
        low, high = self.units_per_floor_range
        if variant == "duplex":
            if self.duplex_storeys_per_dwelling < 2:
                raise ValueError(
                    f"{self.typology} does not declare a multi-storey dwelling"
                )
            if requested is None:
                return int(self.duplex_units_per_floor)
            try:
                value = int(requested)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"units_per_floor={requested!r} is not an integer; the "
                    f"duplex variant draws {self.duplex_units_per_floor} "
                    "floor-level units per plate"
                ) from exc
            if value != int(self.duplex_units_per_floor):
                raise ValueError(
                    f"units_per_floor={value} is not the duplex floor-level "
                    f"count ({self.duplex_units_per_floor}) for {self.typology}; "
                    "the engine will not draw a different unit count while "
                    "reporting the requested one"
                )
            return value
        if requested is None:
            return max(low, min(high, self.default_units_per_floor))
        try:
            value = int(requested)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"units_per_floor={requested!r} is not an integer; {self.typology} "
                f"supports {low}-{high} drawn units per floor"
            ) from exc
        if not low <= value <= high:
            if self.typology == "T2_FAMILY_APARTMENT":
                raise ValueError(
                    f"units_per_floor={value} is outside the implemented range for "
                    f"{self.typology} ({low}-{high}); the engine will not draw a "
                    "different unit count while reporting the requested one"
                )
            return max(low, min(high, value))
        return value

    @property
    def searches_units_per_floor(self) -> bool:
        low, high = self.units_per_floor_range
        return high > low

    def as_dict(self) -> Dict[str, object]:
        return {
            "typology": self.typology,
            "units_per_floor_range": list(self.units_per_floor_range),
            "default_units_per_floor": self.default_units_per_floor,
            "unit_stacking": self.unit_stacking,
            "amenity_placement": self.amenity_placement,
            "representative_floor": self.representative_floor,
            "per_floor_roles": dict(self.per_floor_roles),
            "duplex_units_per_floor": self.duplex_units_per_floor,
            "duplex_storeys_per_dwelling": self.duplex_storeys_per_dwelling,
        }


_VARIABLES: Dict[str, ProgrammeVariables] = {
    # A single-family house is one dwelling on every storey and its floors are
    # genuinely different (living below, bedrooms above), so a representative
    # floor cannot stand in for the others.
    "T1_SINGLE_FAMILY": ProgrammeVariables(
        typology="T1_SINGLE_FAMILY",
        units_per_floor_range=(1, 1),
        default_units_per_floor=1,
        unit_stacking="repeat",
        amenity_placement="all",
        representative_floor=None,
        per_floor_roles={0: "public + service", 1: "private"},
    ),
    # T2 is the reported x4 case: one unit partition was repeated on every
    # storey.  Units per floor is a real variable (1-2); three units are not
    # implemented, so the contract does not advertise them.  A repeated upper
    # storey can be solved once and stacked.
    "T2_FAMILY_APARTMENT": ProgrammeVariables(
        typology="T2_FAMILY_APARTMENT",
        units_per_floor_range=(1, 2),
        default_units_per_floor=2,
        unit_stacking="duplex",
        amenity_placement="all",
        representative_floor="ground",
        per_floor_roles={0: "entry + two units", 1: "two units", 2: "two units", 3: "two units"},
        duplex_units_per_floor=4,
        duplex_storeys_per_dwelling=2,
    ),
    "T3_LARGE_COMPLEX": ProgrammeVariables(
        typology="T3_LARGE_COMPLEX",
        units_per_floor_range=(1, 2),
        default_units_per_floor=1,
        unit_stacking="repeat",
        amenity_placement="ground",
        representative_floor=None,
        per_floor_roles={0: "public + plant", 1: "rentable suites"},
    ),
    "T4_WAREHOUSE": ProgrammeVariables(
        typology="T4_WAREHOUSE",
        units_per_floor_range=(1, 1),
        default_units_per_floor=1,
        unit_stacking="repeat",
        amenity_placement="ground",
        representative_floor=None,
        per_floor_roles={0: "industrial chain", 1: "admin + amenity"},
    ),
}


def get_programme_variables(typology: str) -> ProgrammeVariables:
    """Registry lookup with a conservative T1 fallback (never a guess)."""
    return _VARIABLES.get(typology, _VARIABLES["T1_SINGLE_FAMILY"])
