"""Typology vocabulary accepted at the API boundary.

The UI sends the four plain identifiers; internal callers, persisted requests
and older fixtures also send the canonical T1..T4 keys, the aliases
``normalize_typology`` understands, and namespaced identifiers such as
``T3_COMMERCIAL_RETAIL`` / ``T4_INSTITUTIONAL`` (the engine resolves those by
their T-prefix).  Arbitrary strings used to fall through to T1, and an injected
string was echoed into the dossier.  The validator below accepts
the documented vocabulary plus namespaced T1..T4 identifiers, rejects anything
else, and names the accepted values in the 422.
"""

import re
from typing import Annotated, Literal, Optional

from pydantic import BeforeValidator

ACCEPTED_TYPOLOGY_HINT = (
    "residential_single, residential_multi, commercial, industrial, "
    "T1_SINGLE_FAMILY, T2_FAMILY_APARTMENT, T3_LARGE_COMPLEX, T4_WAREHOUSE "
    "(legacy T1_* through T4_* identifiers are also accepted)"
)

# Documented identifiers + every alias normalize_typology() recognises + the
# compound names older callers use.
_ACCEPTED_TYPOLOGIES = frozenset(
    {
        "residential_single",
        "residential_multi",
        "commercial",
        "industrial",
        "T1_SINGLE_FAMILY",
        "T2_FAMILY_APARTMENT",
        "T3_LARGE_COMPLEX",
        "T4_WAREHOUSE",
        # normalize_typology aliases
        "t1_single_family",
        "residential",
        "villa",
        "bungalow",
        "house",
        "t1",
        "t2_family_apartment",
        "apartment",
        "duplex",
        "builder_floor",
        "t2",
        "t3_large_complex",
        "complex",
        "office",
        "mixed_use",
        "t3",
        "t4_warehouse",
        "warehouse",
        "logistics",
        "shed",
        "factory",
        "t4",
        # compound identifiers used by existing callers/fixtures
        "commercial_office",
        "commercial_complex",
        "residential_apartment",
        "industrial_warehouse",
    }
)

# Namespaced legacy identifiers resolve by their T1..T4 prefix in the ontology
# (T3_COMMERCIAL_RETAIL -> T3, T4_INSTITUTIONAL -> T4).  Bounded by shape.
_LEGACY_TYPOLOGY_RE = re.compile(r"^T[1-4]_[A-Z0-9_]{2,40}$")


def validate_building_typology(value: Optional[str]) -> Optional[str]:
    """Return the typology identifier, or raise with the accepted vocabulary."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"building_typology must be a string. Accepted values: {ACCEPTED_TYPOLOGY_HINT}"
        )
    text = value.strip()
    if text in _ACCEPTED_TYPOLOGIES:
        return text
    if _LEGACY_TYPOLOGY_RE.match(text.upper()):
        return text
    raise ValueError(
        f"Unknown building_typology {text!r}. Accepted values: {ACCEPTED_TYPOLOGY_HINT}"
    )


BuildingTypology = Annotated[str, BeforeValidator(validate_building_typology)]

BuildingSource = Literal["trace", "rectangle", "preset", "import", "legacy"]

BOUNDARY_SOURCES = ("trace", "rectangle", "preset", "import", "legacy")

BoundaryShapeType = Literal[
    "rectangle",
    "irregular",
    "trapezoid",
    "l_shape",
    "pentagon",
    "polygon",
]

BOUNDARY_SHAPE_TYPES = (
    "rectangle",
    "irregular",
    "trapezoid",
    "l_shape",
    "pentagon",
    "polygon",
)
