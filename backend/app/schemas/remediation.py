"""Remediation and advisory payloads for a generated plan.

The engine owns every number here. The browser sends the plan's own warnings and
a compact fact sheet; the server derives the options, re-solves each one, and
returns the measured effect. Nothing about an option - its existence, its title
number, or its predicted outcome - is invented by an LLM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.floorplan import FloorPlanRequest


class BaselineFacts(BaseModel):
    warning_count: int = 0
    failure_count: int = 0
    relaxation_count: int = 0
    plate_area_m2: Optional[float] = None


class RemediationIn(BaseModel):
    request: FloorPlanRequest
    warnings: List[str] = Field(default_factory=list)
    plan_verdict: Optional[str] = None
    rotation_alternatives: List[Dict[str, Any]] = Field(default_factory=list)
    scheme_alternatives: List[Dict[str, Any]] = Field(default_factory=list)
    # Base room ids the plan actually placed. Used only when the request had no
    # explicit required_rooms, so "reduce programme" can name real rooms.
    placed_rooms: List[str] = Field(default_factory=list)
    selected_scheme_id: Optional[str] = None
    # The ladder's selected rung (S0/S1/S2...). Used only to label the card
    # that is already the active plan as "current" and block a no-op re-solve:
    # the baseline request may not name the variant the ladder chose.
    strategy_selected: Optional[str] = None
    baseline: BaselineFacts = Field(default_factory=BaselineFacts)
    plan_hash: Optional[str] = None


class MeasuredEffect(BaseModel):
    """What the ENGINE produced when the option's inputs were re-solved."""

    verdict: str
    certificate_valid: bool
    gate_status: Optional[str] = None
    warning_count: int
    failure_count: int
    relaxation_count: int
    plate_area_m2: Optional[float] = None
    rooms_placed: int = 0
    floors: int = 0
    status: Optional[str] = None
    delta_warnings: int = 0
    delta_failures: int = 0
    engine_ms: float = 0.0


class RemediationOption(BaseModel):
    id: Literal[
        "service_row",
        "duplex",
        "single_unit",
        "add_storey",
        "reduce_programme",
        "accept_rotation",
        "enlarge_plate",
        "switch_scheme",
    ]
    title: str
    description: str
    patch: Dict[str, Any]
    effect: Optional[MeasuredEffect] = None
    error: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class RemediationOut(BaseModel):
    plan_hash: str
    options: List[RemediationOption]
    engine_ms: float
    note: str = (
        "Every predicted effect is a live engine re-solve of the same request "
        "with only this option's validated input changed. Applying it re-runs "
        "the engine and re-certifies the new plan."
    )


class AdvisoryOption(BaseModel):
    id: str
    title: str
    effect_line: str


class AdvisoryIn(BaseModel):
    plan_hash: str
    plan_verdict: str
    summary_line: str
    blocking_reasons: List[str] = Field(default_factory=list)
    warning_counts: Dict[str, int] = Field(default_factory=dict)
    options: List[AdvisoryOption] = Field(default_factory=list)
    allowed_numbers: List[str] = Field(default_factory=list)
    provider: Optional[str] = "groq"


class AdvisoryMeta(BaseModel):
    provider_requested: str = "groq"
    provider_used: str = ""
    narrative_class: str = "advisory_non_certified"
    fallback_reason: Optional[str] = None
    redactions: List[str] = Field(default_factory=list)
    cached: bool = False
    generation_time_ms: Optional[float] = None


class AdvisoryOut(BaseModel):
    narrative: Optional[str] = None
    # One advisor-worded sentence per option, keyed by the engine's option id.
    # Wording only: the option, its patch and its numbers stay the engine's.
    option_notes: Dict[str, str] = Field(default_factory=dict)
    meta: AdvisoryMeta
