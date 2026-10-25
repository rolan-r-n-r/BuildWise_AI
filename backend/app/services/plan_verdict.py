"""plan_verdict.py - ONE verdict for a generated plan.

Before this module the same generation could be read three ways:

  * the plan card turned red with a "FAIL stamp" as soon as a ROOM-MAX line
    appeared (frontend ``planWarnings.ts``);
  * the certificate panel said "CERTIFIED · ADVISORIES" (gate WARN only);
  * the exported PDF said "PLAN ADVISORIES - DISCLOSED ON THE DRAWING"
    (``report_service`` only triggered the red banner on a withheld
    certificate or a FAIL gate).

Same warnings, three severities, and the card explicitly promised an export
stamp the export did not carry.

The verdict is computed HERE and published on the response as
``plan_verdict``.  Every surface renders that string verbatim; none of them
re-derives a severity of its own.

Rules (deterministic, no model, no network):

  NOT-CERTIFIED-FAIL-STAMP  certificate withheld, OR gate FAIL, OR any
                            critical plan warning (a named squeezed room, a
                            catalogue maximum, an overlap, a selection
                            fallback, a plate shortfall, a hard proportion
                            failure).
  ADVISORY                  certificate valid, gate PASS/WARN, and at least one
                            page-1 advisory row (a listed relaxation, a ceiling
                            overage, a plinth reconciliation).
  CERTIFIED                 none of the above.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

CERTIFIED = "CERTIFIED"
ADVISORY = "ADVISORY"
FAIL_STAMP = "NOT-CERTIFIED-FAIL-STAMP"

# Exactly the rows page 1 of the report prints for a plan.  Mirrors
# frontend/src/services/planWarnings.ts (kept in sync by the parity pin).
PAGE1_PLAN_WARNING_PATTERN = re.compile(
    r"^(PROP-|PROGRAMME-|PLINTH:|ROOM-MIN|ROOM-MAX|ROOM-OVERLAP|SELECTION-FALLBACK|GATE-FAIL|PLATE-SHORT)"
)

# A listed relaxation (PROP-ASPECT / PROP-SPLIT / PROP-CEILING) is disclosed,
# not refused.  These are the rows that make a plan NOT certified.
CRITICAL_PLAN_WARNING_PATTERN = re.compile(
    r"^(GATE-FAIL|PROGRAMME-DEFICIT|PROGRAMME-SQUEEZE|PLATE-SHORT|PROP-HARD|"
    r"PROP-PLATE-CAP|PROPORTION-FAIL|ROOM-MIN|ROOM-MAX|ROOM-OVERLAP|SELECTION-FALLBACK)\b"
)

VERDICT_LABEL = {
    CERTIFIED: "CERTIFIED",
    ADVISORY: "ADVISORY",
    FAIL_STAMP: "NOT-CERTIFIED-FAIL-STAMP",
}


def page1_plan_warnings(warnings: Optional[Iterable[Any]]) -> List[str]:
    """The page-1 rows: the only warnings that belong in a plan verdict."""
    out: List[str] = []
    for w in warnings or []:
        text = str(w or "").strip()
        if text and PAGE1_PLAN_WARNING_PATTERN.match(text):
            out.append(text)
    return out


def is_critical_plan_warning(w: Any) -> bool:
    return bool(CRITICAL_PLAN_WARNING_PATTERN.match(str(w or "")))


def _gate_status(plan: Dict[str, Any]) -> Optional[str]:
    qa = plan.get("qa") or {}
    cert = plan.get("mathematical_certificate") or {}
    gate = (
        plan.get("validation_gate")
        or qa.get("validation_gate")
        or (cert.get("details") or {}).get("validation_gate")
        or (plan.get("multi_storey") or {}).get("validation_gate")
        or {}
    )
    status = qa.get("validation_gate_status") or (gate or {}).get("overall_status")
    return str(status).upper() if status else None


def plan_verdict_reasons(plan: Optional[Dict[str, Any]]) -> List[str]:
    """The named facts behind the verdict, in the order they were checked."""
    if not isinstance(plan, dict):
        return []
    reasons: List[str] = []
    cert = plan.get("mathematical_certificate") or {}
    if cert.get("is_valid") is False:
        reasons.append("mathematical certificate WITHHELD")
    status = _gate_status(plan)
    if status == "FAIL":
        reasons.append("validation gate FAIL")
    for w in page1_plan_warnings(plan.get("warnings")):
        if is_critical_plan_warning(w) and w not in reasons:
            reasons.append(w)
    return reasons


def compute_plan_verdict(plan: Optional[Dict[str, Any]]) -> str:
    """The one verdict for a plan payload (see module docstring)."""
    if not isinstance(plan, dict) or not plan:
        return CERTIFIED
    cert = plan.get("mathematical_certificate") or {}
    if cert.get("is_valid") is False:
        return FAIL_STAMP
    if _gate_status(plan) == "FAIL":
        return FAIL_STAMP
    rows = page1_plan_warnings(plan.get("warnings"))
    if any(is_critical_plan_warning(w) for w in rows):
        return FAIL_STAMP
    if rows:
        return ADVISORY
    return CERTIFIED
