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

  NOT-CERTIFIED-FAIL-STAMP  certificate withheld, OR a hard statutory/safety
                            layer FAIL, OR an unlisted breach, OR a deviation
                            beyond its declared cap (a catalogue maximum, an
                            overlap, a selection fallback, a plate shortfall, a
                            hard proportion failure, "beyond the 1.40x cap").
  CERTIFIED                 certificate valid, every hard layer PASS, zero
                            unlisted breaches, and every quality deviation is
                            both listed and inside its declared cap.  Listed
                            within-cap deviations are printed on page 1 and in
                            the UI ledger; they do not withhold certification.
  ADVISORY                  legacy/transitional only - a valid certificate with
                            page-1 rows that are neither listed deviations nor
                            critical.  New plans should not need this state.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

CERTIFIED = "CERTIFIED"
ADVISORY = "ADVISORY"
FAIL_STAMP = "NOT-CERTIFIED-FAIL-STAMP"

# ONE definition, rendered verbatim by the certificate legend, the PDF and the
# landing claim map.  The pin in test_plan_verdict_parity reads the frontend
# constant and asserts it is byte-identical to this string.
CERTIFIED_DEFINITION = (
    "CERTIFIED = statutory/safety layers PASS + zero unlisted breaches + "
    "every quality deviation listed and inside its declared cap. "
    "NOT-CERTIFIED-FAIL-STAMP = statutory FAIL, unlisted breach, or beyond-cap deviation."
)

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

# Mirror of validation_gate.HARD_FAIL_LAYERS: a FAIL in any of these withholds
# certification regardless of how the quality layers are worded.
HARD_FAIL_LAYERS = frozenset({"L1", "L2", "L8", "L14", "L15"})

# Rows that disclose a bounded, declared relaxation.  They remain printed; they
# no longer count as a reason to withhold the certificate.
_LISTED_ROW = re.compile(
    r"(declared relaxation|certificate-listed relaxation|listed relaxation|"
    r"accepted at|inside the .* band|within the .* cap|declared ceiling|"
    r"^PROP-IDEAL|^PLINTH:)",
    re.IGNORECASE,
)
# A row that SAYS there is no listing is not a listing: GATE-L16 rows carry
# "... and no listed relaxation", and the naive substring match read that as a
# listed, within-cap deviation - the exact inversion this stage removes.
_NOT_LISTED_ROW = re.compile(r"\bno listed relaxation\b|\bunlisted\b", re.IGNORECASE)
_BEYOND_CAP = re.compile(r"beyond\b.*\bcap|unlisted breach", re.IGNORECASE)
_ROOM_ID = re.compile(r"\b([A-Za-z0-9_]+_F\d+)\b")
_ROOM_MAX = re.compile(
    r"is\s+([\d.]+)\s*m²,\s*above its\s+([\d.]+)\s*m²\s+catalogue maximum",
    re.IGNORECASE,
)
_SQUEEZE_ROOMS = re.compile(r"below their minimum:\s*(.+?)\)", re.IGNORECASE)


def _listed_room_ids(plan: Dict[str, Any]) -> set:
    """Rooms that carry at least one structured, declared relaxation."""
    rooms: List[Dict[str, Any]] = []
    ms = plan.get("multi_storey") or {}
    for floor in ms.get("floors") or []:
        rooms.extend(floor.get("rooms") or [])
    rooms.extend(plan.get("placements") or [])
    return {
        str(room.get("room_id"))
        for room in rooms
        if room.get("room_id") and room.get("relaxations")
    }


def _row_is_listed(plan: Dict[str, Any], w: Any, listed_rooms: set) -> bool:
    """True when a page-1 row is a declared, within-cap deviation.

    The row text alone cannot tell a listed shortfall from an unlisted one:
    the engine emits both a plain ``ROOM-MIN`` line and a structured
    ``relaxations`` entry on the room.  This reads the structure, not a magic
    substring, so a squeezed core/lobby does not fail a plan that listed it.
    """
    text = str(w or "").strip()
    if not text or _BEYOND_CAP.search(text) or _NOT_LISTED_ROW.search(text):
        return False
    if text.startswith("PROGRAMME-SQUEEZE"):
        match = _SQUEEZE_ROOMS.search(text)
        if not match:
            return False
        named = [part.strip() for part in match.group(1).split(",") if part.strip()]
        return bool(named) and all(room in listed_rooms for room in named)
    if text.startswith("ROOM-MAX"):
        match = _ROOM_MAX.search(text)
        if not match:
            return False
        measured = float(match.group(1))
        ceiling = float(match.group(2))
        return ceiling > 0 and measured / ceiling <= 1.40 + 1e-9
    if text.startswith("ROOM-MIN"):
        rooms = _ROOM_ID.findall(text)
        return bool(rooms) and all(room in listed_rooms for room in rooms)
    return bool(_LISTED_ROW.search(text))


def _gate_layers(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    qa = plan.get("qa") or {}
    cert = plan.get("mathematical_certificate") or {}
    gate = (
        plan.get("validation_gate")
        or qa.get("validation_gate")
        or (cert.get("details") or {}).get("validation_gate")
        or (plan.get("multi_storey") or {}).get("validation_gate")
        or {}
    )
    layers = gate.get("layers") if isinstance(gate, dict) else None
    return list(layers or [])


def _hard_layer_failed(plan: Dict[str, Any]) -> bool:
    for layer in _gate_layers(plan):
        if str(layer.get("layer_id") or "").upper() in HARD_FAIL_LAYERS and str(
            layer.get("status") or ""
        ).upper() == "FAIL":
            return True
    return False


def _is_listed_within_cap(w: Any) -> bool:
    """True for a deviation printed on page 1 that is declared and inside cap."""
    text = str(w or "").strip()
    if not text:
        return False
    if _BEYOND_CAP.search(text) or _NOT_LISTED_ROW.search(text):
        return False
    return bool(_LISTED_ROW.search(text))


def page1_plan_warnings(warnings: Optional[Iterable[Any]]) -> List[str]:
    """The page-1 rows: the only warnings that belong in a plan verdict."""
    out: List[str] = []
    for w in warnings or []:
        text = str(w or "").strip()
        if text and PAGE1_PLAN_WARNING_PATTERN.match(text):
            out.append(text)
    return out


# --------------------------------------------------------------------------- #
# TRUTH LABELS - the ONE grouping every surface prints.
#
# A CERTIFIED plan used to be headed "CERTIFICATE FAILURES 14" while its
# certificate held 0 failures: those rows were listed, within-cap deviations
# (relaxations the certificate itself accepts).  The certificate is now the
# only source of certificate-failure rows; deviations are their own group; the
# rows a FAIL stamp actually rests on are their own group too.  The counts are
# computed here and rendered verbatim by the screen, the print view and the
# PDF, so no surface can count a group its own way.
# --------------------------------------------------------------------------- #

CERTIFICATE_FAILURES_HEADING = "CERTIFICATE FAILURES ({count})"
LISTED_DEVIATIONS_HEADING = "LISTED DEVIATIONS ({count})"
UNRESOLVED_BREACHES_HEADING = "UNRESOLVED BREACHES ({count})"
TRUTH_SUMMARY_TEMPLATE = (
    "Certificate failures: {failures} \u00b7 Listed deviations: {deviations} \u00b7 "
    "Unresolved breaches: {breaches}"
)


def certificate_failure_lines(plan: Optional[Dict[str, Any]]) -> List[str]:
    """Exactly the certificate's own failure rows - never a warning total."""
    if not isinstance(plan, dict):
        return []
    cert = plan.get("mathematical_certificate") or {}
    return [str(f).strip() for f in (cert.get("failures") or []) if str(f).strip()]


def structured_deviation_rows(plan: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every room-level relaxation exactly as the certificate lists it.

    One row per structured relaxation record: room, rule id and the verbatim
    rationale.  Nothing is invented and nothing is dropped.
    """
    if not isinstance(plan, dict):
        return []
    rows: List[Dict[str, Any]] = []
    seen = set()

    def push(room: Dict[str, Any]) -> None:
        room_id = str(room.get("room_id") or room.get("room_name") or "room")
        for rx in room.get("relaxations") or []:
            if not isinstance(rx, dict):
                continue
            key = (room_id, str(rx.get("rule_id") or "RELAXATION"), str(rx.get("rationale") or ""))
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "room_id": room_id,
                    "rule_id": str(rx.get("rule_id") or "RELAXATION"),
                    "reason": str(rx.get("rationale") or "").strip(),
                    "source": "structured",
                }
            )

    ms = plan.get("multi_storey") or {}
    for floor in ms.get("floors") or []:
        for room in floor.get("rooms") or []:
            push(room)
    for room in plan.get("placements") or []:
        push(room)
    return rows


def _row_named_rooms(row: str) -> List[str]:
    """Room ids a page-1 row names (ROOM ids, or the squeeze room list)."""
    names = list(_ROOM_ID.findall(str(row)))
    match = _SQUEEZE_ROOMS.search(str(row))
    if match:
        names.extend(part.strip() for part in match.group(1).split(",") if part.strip())
    return names


def plan_truth_labels(plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The ONE truth-label grouping for a plan payload.

    Returns:
      certificate_failures  certificate.failures, verbatim, in order.
      listed_deviations     every listed, within-cap deviation row: one row per
                            page-1 deviation line (verbatim) plus every
                            structured relaxation with no page-1 line of its
                            own (room + rule + verbatim reason).
      unresolved_breaches  the page-1 rows a FAIL stamp rests on (critical and
                            not listed), plus any engine-log failure row that
                            never reached page 1 - the always-visible group.
      headings              the exact heading strings every surface prints.
      summary_line          the counts, stated separately.
    """
    plan = plan if isinstance(plan, dict) else {}
    failures = certificate_failure_lines(plan)
    structured = structured_deviation_rows(plan)
    listed_rooms = {row["room_id"] for row in structured}
    page1 = page1_plan_warnings(plan.get("warnings"))

    deviations: List[Dict[str, Any]] = []
    unresolved: List[str] = []
    for row in page1:
        if _unresolved_critical(plan, row, listed_rooms):
            unresolved.append(row)
            continue
        if _row_is_listed(plan, row, listed_rooms):
            rooms = _row_named_rooms(row)
            deviations.append(
                {
                    "room_id": rooms[0] if rooms else "",
                    # The rule column is the CODE, not the code plus the room id:
                    # a row without a colon ("ROOM-MIN room_F0: ...") used to
                    # print its whole prefix in the appendix's Rule column.
                    "rule_id": str(row.split(":", 1)[0]).strip().split(" ", 1)[0],
                    "reason": row,
                    "page1_row": row,
                    "source": "page1",
                }
            )
            continue
        # Neither a named breach nor a listed deviation: an advisory row.  It
        # is disclosed by the advisory tier and the full list, and never
        # counted as a failure.
    for row in structured:
        if any(d.get("page1_row") for d in deviations if d.get("room_id") == row["room_id"]):
            continue
        deviations.append({**row, "page1_row": None})

    page1_set = set(page1)
    for w in plan.get("warnings") or []:
        text = str(w or "").strip()
        if not text or text in page1_set:
            continue
        if CRITICAL_PLAN_WARNING_PATTERN.match(text) and not _row_is_listed(
            plan, text, listed_rooms
        ):
            # A failure-grade engine-log row that never reached page 1: it used
            # to sit in the always-visible certificate-failure block.  It stays
            # always visible, named for what it is.
            unresolved.append(text)

    headings = {
        "certificate_failures": CERTIFICATE_FAILURES_HEADING.format(count=len(failures)),
        "listed_deviations": LISTED_DEVIATIONS_HEADING.format(count=len(deviations)),
        "unresolved_breaches": UNRESOLVED_BREACHES_HEADING.format(count=len(unresolved)),
    }
    return {
        "certificate_failures": failures,
        "listed_deviations": deviations,
        "listed_deviation_rooms": len({d["room_id"] for d in structured if d["room_id"]}),
        "structured_relaxations": len(structured),
        "unresolved_breaches": unresolved,
        "headings": headings,
        "counts": {
            "certificate_failures": len(failures),
            "listed_deviations": len(deviations),
            "unresolved_breaches": len(unresolved),
        },
        "summary_line": TRUTH_SUMMARY_TEMPLATE.format(
            failures=len(failures),
            deviations=len(deviations),
            breaches=len(unresolved),
        ),
    }


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


def _unresolved_critical(plan: Dict[str, Any], w: Any, listed_rooms: set) -> bool:
    return is_critical_plan_warning(w) and not _row_is_listed(plan, w, listed_rooms)


def plan_verdict_reasons(plan: Optional[Dict[str, Any]]) -> List[str]:
    """The named facts behind the verdict, in the order they were checked."""
    if not isinstance(plan, dict):
        return []
    reasons: List[str] = []
    cert = plan.get("mathematical_certificate") or {}
    if cert.get("is_valid") is False:
        reasons.append("mathematical certificate WITHHELD")
    if _hard_layer_failed(plan):
        reasons.append("hard statutory/safety layer FAIL")
    elif _gate_status(plan) == "FAIL":
        reasons.append("validation gate FAIL")
    listed_rooms = _listed_room_ids(plan)
    for w in page1_plan_warnings(plan.get("warnings")):
        if _unresolved_critical(plan, w, listed_rooms) and w not in reasons:
            reasons.append(w)
    for f in cert.get("failures") or []:
        if str(f) not in reasons:
            reasons.append(str(f))
    return reasons


def compute_plan_verdict(plan: Optional[Dict[str, Any]]) -> str:
    """The one verdict for a plan payload (see module docstring)."""
    if not isinstance(plan, dict) or not plan:
        return CERTIFIED
    cert = plan.get("mathematical_certificate") or {}
    if cert.get("is_valid") is False:
        return FAIL_STAMP
    if _hard_layer_failed(plan) or _gate_status(plan) == "FAIL":
        return FAIL_STAMP
    if cert.get("failures"):
        return FAIL_STAMP
    rows = page1_plan_warnings(plan.get("warnings"))
    listed_rooms = _listed_room_ids(plan)
    if any(_unresolved_critical(plan, w, listed_rooms) for w in rows):
        return FAIL_STAMP
    # Every remaining row is a listed, within-cap deviation (or an advisory such
    # as the plinth reconciliation).  It stays on page 1; it does not block the
    # certificate.  A valid certificate with no hard failure is CERTIFIED.
    return CERTIFIED
