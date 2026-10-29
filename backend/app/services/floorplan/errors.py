"""Typed refusals for floor-plan generation.

A design refusal is a client-fixable answer, not a server fault: the request is
valid, the site is real, and the engine has measured that the requested layout
cannot be drawn on the legal plate.  The API must answer such a refusal with a
4xx naming the measured reason (release contract: infeasible requests fail
honestly).  String matching on the exception message cannot provide that
guarantee, so refusals carry a stable code.

Only genuinely infeasible *designs* use this class.  Internal faults keep their
own exception types and stay 5xx.
"""

from __future__ import annotations

from typing import Optional


class DesignInfeasibleError(ValueError):
    """The requested design cannot be drawn on the measured legal geometry.

    Attributes:
        code: stable machine-readable refusal code (never localised).
        reason: deterministic, measured explanation shown to the caller.
    """

    default_code = "FLOORPLAN-DESIGN-INFEASIBLE"

    def __init__(self, reason: str, *, code: Optional[str] = None) -> None:
        self.code = str(code or self.default_code)
        self.reason = str(reason)
        super().__init__(self.reason)


class DuplexPlateInfeasibleError(DesignInfeasibleError):
    """An explicit duplex request whose legal plate cannot hold the layout."""

    default_code = "FLOORPLAN-DUPLEX-PLATE-INFEASIBLE"
