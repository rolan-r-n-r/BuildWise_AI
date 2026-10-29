"""
validation_gate.py - Universal Validation Gate 
=========================================================
Every generation - any typology, any floor count - is judged by the same
contract: the full L1-L15 layer stack. No layer is ever silently skipped;
when a layer does not apply, it is recorded as N/A WITH AN EXPLICIT REASON.

Layer map:
  L1  Geometry & statutory invariants   (engine certificate core)
  L2  Door swings                       (living_quality)
  L3  Bathroom fixture clearances       (living_quality)
  L4  Furniture clearances              (living_quality)
  L5  Naming honesty                    (living_quality)
  L6  Stair as computed object          (wall_graph / living_quality)
  L7  Vastu scoring                     (profile scores, advisory)
  L8  Program intent                    (living_quality)
  L9  Ventilation                       (engineering)
  L10 Wet-core & plumbing               (engineering)
  L11 Terrace drainage                  (engineering)
  L12 Structural                        (engineering)
  L13 Accessibility                     (engineering)
  L14 Fire & egress                     (engineering)
  L15 Programme completeness            (essential rooms present per typology/unit)
  L16 Proportion & surplus              (hard bands, listed relaxations, ceiling
                                         overage, void ratio, surplus routing)

Overall status = worst layer (FAIL > WARN > N/A > PASS). Concretely:
  overall = FAIL if any FAIL
  else WARN if any WARN
  else PASS
A layer that genuinely does not apply is recorded N/A WITH AN EXPLICIT REASON
and never counts as a pass. A layer whose evaluator DID NOT RUN is a FAIL: an
absent evaluator is not evidence of compliance.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("buildwise.validation_gate")

# Canonical layer order rendered on sheets and UI panels.
LAYER_IDS: List[str] = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8",
                        "L9", "L10", "L11", "L12", "L13", "L14", "L15", "L16"]

LAYER_TITLES: Dict[str, str] = {
    "L1": "Geometry & Statutory",
    "L2": "Door Swings",
    "L3": "Bathroom Fixtures",
    "L4": "Furniture Clearances",
    "L5": "Naming Honesty",
    "L6": "Stair Compliance",
    "L7": "Vastu Advisory",
    "L8": "Program Intent",
    "L9": "Ventilation",
    "L10": "Wet-Core & Plumbing",
    "L11": "Terrace Drainage",
    "L12": "Structural",
    "L13": "Accessibility",
    "L14": "Fire & Egress",
    "L15": "Programme Completeness",
    "L16": "Proportion & Surplus",
}

STATUS_ORDER = {"PASS": 0, "N/A": 1, "WARN": 2, "FAIL": 3}

# Layers whose FAIL invalidates the whole certificate (hard layers).
HARD_FAIL_LAYERS = {"L1", "L2", "L8", "L14", "L15"}

# Land-economics checks that a plan can DISPROVE (geometry/statutory facts).
# These are L1-bearing: a PASS gate beside a failing land certificate is a
# Contradiction. Planning ratios are advisory (WARN), not provable
# violations of a law.
_LAND_ADVISORY_CHECKS = {"circulation_within_12_20", "footprint_utilization_90"}

_LAND_CHECK_LABELS = {
    "site_plan_present": "site plan present",
    "site_plan": "site plan present",
    "geometry": "land geometry readable",
    "footprint_contained_in_buildable": "footprint inside the setback buildable",
    "coverage_within_limit": "ground coverage within the statutory limit",
    "program_fits_footprint": "programme fits the footprint",
    "interior_dead_corners_zero": "no interior dead corner >= 1 m²",
    "residuals_labelled": "every residual labelled",
    "anonymous_outdoor_zero": "no anonymous outdoor sliver",
    "circulation_within_12_20": "circulation ratio within the 12-20% band",
    "footprint_utilization_90": "footprint utilisation >= 90%",
    "furniture_fit": "furniture sets fit their rooms",
}


@dataclass
class LayerStatus:
    """Per-layer gate result. `status` is one of PASS | WARN | FAIL | N/A."""
    layer_id: str
    title: str
    status: str                     # "PASS" | "WARN" | "FAIL" | "N/A"
    summary: str = ""
    reason: Optional[str] = None    # mandatory when status == N/A
    findings: List[str] = field(default_factory=list)
    citation: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "layer_id": self.layer_id,
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
        }
        if self.status == "N/A":
            d["reason"] = self.reason or "not_applicable"
        if self.findings:
            d["findings"] = self.findings
        if self.citation:
            d["citation"] = self.citation
        if self.details is not None:
            d["details"] = self.details
        return d


def crash_status(layer_id: str) -> str:
    """Status for a layer whose evaluator CRASHED.

    A crashed evaluator verified nothing. For a hard layer that is a FAIL (the
    plan cannot be certified on an unverified claim); for an advisory layer the
    gate records a WARN so the crash stays visible without voiding a geometry
    the other layers did verify.
    """
    return "FAIL" if layer_id in HARD_FAIL_LAYERS else "WARN"


def make_layer(layer_id: str, status: str, summary: str = "",
               reason: Optional[str] = None, findings: Optional[List[str]] = None,
               citation: Optional[str] = None,
               details: Optional[Dict[str, Any]] = None) -> LayerStatus:
    """Factory that enforces the N/A-with-reason contract and clamps statuses."""
    st = str(status).upper()
    if st not in STATUS_ORDER:
        st = "WARN"
    if st == "N/A" and not reason:
        reason = "No applicable subjects found in this generation"
    findings = findings or []
    if st == "WARN" and not findings and summary:
        # Warnings are surfaced as chips and must never be hidden without a cause.
        findings = [summary]
    return LayerStatus(layer_id, LAYER_TITLES.get(layer_id, layer_id), st,
                       summary, reason, findings, citation, details)


def ensure_all_layers(layers: List[LayerStatus]) -> List[LayerStatus]:
    """Append a FAIL row for every declared layer that nobody evaluated.

    The gate may NEVER return fewer layers than its contract declares: a
    missing evaluator is an unverified claim, and an unverified claim fails
    .
    """
    present = {l.layer_id for l in layers}
    for lid in LAYER_IDS:
        if lid not in present:
            layers.append(make_layer(
                lid, "FAIL",
                summary=f"{LAYER_TITLES.get(lid, lid)} was not evaluated",
                findings=["Layer evaluator did not run - an absent evaluator cannot pass"],
            ))
    return layers


def overall_status(layers: List[LayerStatus]) -> str:
    """Overall = worst layer. N/A never gates validity."""
    worst = "PASS"
    for l in layers:
        if STATUS_ORDER.get(l.status, 0) > STATUS_ORDER.get(worst, 0):
            worst = l.status
    return "FAIL" if worst == "FAIL" else ("WARN" if worst == "WARN" else "PASS")


def overall_from_dicts(layer_dicts: List[Dict[str, Any]]) -> str:
    """Same as overall_status() but over serialized dicts (UI/PDF consumers)."""
    worst = "PASS"
    for d in layer_dicts or []:
        s = str(d.get("status", "PASS")).upper()
        if STATUS_ORDER.get(s, 0) > STATUS_ORDER.get(worst, 0):
            worst = s
    return "FAIL" if worst == "FAIL" else ("WARN" if worst == "WARN" else "PASS")


# Essential programme per typology.  These are the rooms a dwelling/unit or
# operating building cannot function without; optional spaces (study, puja,
# balcony, utility) are deliberately not gated here.
_T1_ESSENTIAL = ({"living", "kitchen"},
                 {"master_bed", "bed_2", "master_suite"},
                 {"bath_1", "bath_2", "bath_master", "powder_room"})
_T2_UNIT_ESSENTIAL = ("unit_living", "unit_kitchen", "unit_bed", "unit_bath")
_T3_ESSENTIAL_ANY = {"commercial_suite", "conference_suite", "conference_room",
                     "reception_lobby", "reception"}
_T4_ESSENTIAL = ("dock_bay", "dispatch", "storage_bay", "worker_amenity")


def _room_space_id(room: Any) -> Optional[str]:
    sid = getattr(room, "space_type_id", None)
    if sid:
        return str(sid)
    ident = getattr(room, "identity", None)
    if isinstance(ident, dict):
        sid = ident.get("space_type_id")
    else:
        sid = getattr(ident, "space_type_id", None)
    if sid:
        return str(sid)
    from app.services.floorplan.ontology import ONTOLOGY
    return ONTOLOGY.resolve_space_id(str(getattr(room, "room_id", "")), None)


def assess_programme_completeness(
    floors: List[Any], typology: str
) -> Dict[str, Any]:
    """Return the essential-room verdict for the requested typology.

    This is presence, not size: a plan can pass L15 while an individual room
    is below its area target (that is L1/I2 territory).  Its job is to stop the
    silent deletion of an essential room - the failure mode that let a T2 flat
    without a kitchen pass every other layer.
    """
    rooms = [r for f in (floors or []) for r in (getattr(f, "rooms", None) or [])]
    if not rooms:
        return {"status": "N/A", "reason": "No floor plates to audit",
                "missing": [], "per_unit": {}, "rooms_checked": 0}

    typed = [(r, _room_space_id(r)) for r in rooms]
    missing: List[str] = []
    per_unit: Dict[str, List[str]] = {}

    if typology == "T2_FAMILY_APARTMENT":
        # A two-storey dwelling keeps its living/kitchen/bath on one level and
        # its bedroom on the other.  Completeness therefore belongs to the
        # household (``dwelling_id``), not to one floor's level-unit: checking
        # each floor separately would demand a bedroom downstairs and a kitchen
        # upstairs from a perfectly complete maisonette.  Legacy one-level plans
        # have no dwelling_id and keep the per-floor unit grouping unchanged.
        dwelling_ids = {
            str(getattr(room, "dwelling_id", "") or "")
            for room, _sid in typed
        } - {""}
        if dwelling_ids:
            units: Dict[str, set] = {uid: set() for uid in dwelling_ids}
            for room, sid in typed:
                uid = str(getattr(room, "dwelling_id", "") or "")
                if uid:
                    units.setdefault(uid, set()).add(sid)
            per_unit = {uid: sorted(s for s in units[uid] if s) for uid in sorted(units)}
            for uid in sorted(units):
                for need in _T2_UNIT_ESSENTIAL:
                    if need not in units[uid]:
                        missing.append(f"{need} in {uid}")
        else:
            units = {}
            for room, sid in typed:
                uid = str(getattr(room, "unit_id", "") or "")
                if uid:
                    units.setdefault(uid, set()).add(sid)
            if not units:
                missing.append("no unit-identified rooms (T2 programme not materialised)")
            for uid in sorted(units):
                per_unit[uid] = sorted(s for s in units[uid] if s)
                for need in _T2_UNIT_ESSENTIAL:
                    if need not in units[uid]:
                        missing.append(f"{need} in {uid}")
    elif typology == "T3_LARGE_COMPLEX":
        ids = {sid for _r, sid in typed if sid}
        if "sanitary_block" not in ids:
            missing.append("sanitary_block")
        if not (ids & _T3_ESSENTIAL_ANY):
            missing.append("commercial/conference/reception space")
    elif typology == "T4_WAREHOUSE":
        ids = {sid for _r, sid in typed if sid}
        missing.extend(need for need in _T4_ESSENTIAL if need not in ids)
    else:
        ids = {sid for _r, sid in typed if sid}
        any_bed, any_bath = _T1_ESSENTIAL[1], _T1_ESSENTIAL[2]
        missing.extend(need for need in _T1_ESSENTIAL[0] if need not in ids)
        if not (ids & any_bed):
            missing.append("bedroom")
        if not (ids & any_bath):
            missing.append("bathroom")

    return {
        "status": "FAIL" if missing else "PASS",
        "missing": missing,
        "per_unit": per_unit,
        "rooms_checked": len(rooms),
        "typology": typology,
    }


# =============================================================================
# LLM BOUNDARY EVENT LOG
# =============================================================================

def log_llm_boundary_event(event: str, detail: Dict[str, Any]) -> str:
    """
    Emits an auditable event for the LLM-boundary invariant: the LLM may parse
    client TEXT only; any attempt by LLM output to carry explicit coordinates
    or geometry MUST be ignored by the solver and logged here. Returns an event
    id for the certificate details trail.
    """
    eid = f"LLMB-{uuid.uuid4().hex[:8].upper()}"
    logger.warning(
        "LLM-boundary event %s: %s %s",
        eid, event, {k: detail.get(k) for k in ("keys", "fields", "count") if k in detail}
    )
    return eid


LGEOMETRY_KEYS = {
    "x", "y", "width_m", "depth_m", "width", "depth", "height", "x1", "y1", "x2", "y2",
    "polygon", "polygon_coords", "vertices", "rooms_geometry", "geometry", "rectangles",
    "placements_geometry", "coords", "coordinates", "points", "w", "h",
}


def sanitize_llm_constraints(constraints: Any, source: str = "unknown") -> Dict[str, Any]:
    """
    Enforces the LLM-boundary invariant on parsed client constraints:
    strips any coordinate/geometry-bearing keys (LLM output may never place
    geometry), logs every strip as a boundary event, and returns a sanitized
    copy plus an audit trail. Deterministic; no network.
    """
    events: List[Dict[str, Any]] = []
    if constraints is None:
        return {"sanitized": None, "events": events, "event_ids": []}

    if not isinstance(constraints, dict):
        # Pydantic models: inspect the serialized form UNION the raw __dict__.
        # model_dump() alone can hide attribute-level extras injected by callers
        # that bypassed validation (model_construct) - those must be detected too.
        try:
            dumped = dict(constraints.model_dump())
            raw = {k: v for k, v in vars(constraints).items()
                   if not k.startswith("_") and not k.startswith("model_")}
            merged = {**raw, **dumped}
            constraints = merged
        except AttributeError:
            constraints = dict(constraints)

    stripped: List[str] = []
    clean: Dict[str, Any] = {}
    for k, v in constraints.items():
        if k in LGEOMETRY_KEYS or (isinstance(v, (list, tuple)) and k.lower().endswith(
                ("coords", "vertices", "polygon", "points", "geometry", "rectangles"))):
            stripped.append(k)
            continue
        clean[k] = v
    event_ids: List[str] = []
    if stripped:
        detail = {"fields": stripped, "source": source}
        eid = log_llm_boundary_event("geometry_fields_stripped_from_llm_constraints", detail)
        events.append({"event_id": eid, **detail})
        event_ids.append(eid)
    return {"sanitized": clean, "events": events, "event_ids": event_ids}


# =============================================================================
# GATE BUILDER - consumes engine state, returns serialized layer statuses
# =============================================================================

def _status_from_str(s: Any) -> str:
    t = str(s or "").lower()
    if t.startswith("fail"):
        return "FAIL"
    if t.startswith("warn"):
        return "WARN"
    if t.startswith("n/a") or t == "na" or t.startswith("na"):
        return "N/A"
    return "PASS"


def build_gate_layers(
    engine: Any,
    cert: Any,
    floors: List[Any],
    duct_shafts: List[Any],
    typology: str,
    pi_ok: bool,
    pi_warns: List[str],
    statutory_audit: Dict[str, Any],
    plate_masks: Any = None,
    land_cert: Any = None,
) -> List[Dict[str, Any]]:
    """
    Runs the universal gate over ALL layers L1-L15 and returns the serialized
    per-layer status list (for cert.details["validation_gate"]["layers"]).
    Import-time isolation: engineering imports are local so the gate can never
    break legacy certificate emission.
    """
    from app.services.floorplan.engineering import (
        compute_ventilation_registry,
        compute_wet_core_audit,
        compute_terrace_drainage,
        compute_structural_model,
        compute_accessibility_audit,
        compute_fire_egress_audit,
    )

    layers: List[LayerStatus] = []

    # ---------------------------------------------------------------- L1
    l1_broken = not (cert.non_overlap and cert.containment and cert.chain_sums_match
                     and cert.zero_forbidden_violations and cert.connectivity_bfs
                     and cert.vertical_stack_valid and cert.core_continuity_valid
                     and cert.no_wet_over_terrace_valid and cert.cores_stack_aligned)
    l1_findings: List[str] = []
    # ASPECT. A listed relaxation is not a pass on the band: the
    # gate WARNs and names it.  An UNLISTED breach (beyond the declared cap)
    # sets the certificate's own aspect_ratios_satisfied flag to False, so it is
    # reported here as well; it does not by itself refuse the plan, because the
    # refusal path is reserved for infeasible briefs (a drawn, disclosed breach
    # Is still a usable sheet). Making this gate-bearing is.
    if not cert.aspect_ratios_satisfied:
        l1_findings.append(
            "Room aspect ratio exceeds the ontology hard band and is not a declared "
            "relaxation"
        )
    if not cert.non_overlap:
        l1_findings.append("Room footprint overlap detected (>= 0.05 sqm)")
    if not cert.containment:
        l1_findings.append("Room outside envelope boundary")
    if not cert.chain_sums_match:
        l1_findings.append("Dimension chain sum deviates from overall (>1mm)")
    if not cert.zero_forbidden_violations:
        l1_findings.append("Forbidden adjacency violation present")
    if not cert.connectivity_bfs:
        l1_findings.append("Circulation graph not fully reachable")
    if not cert.vertical_stack_valid:
        l1_findings.append("Vertical stacking invariant violated")
    if not cert.core_continuity_valid:
        l1_findings.append("Vertical core discontinuous across levels")
    if not cert.no_wet_over_terrace_valid:
        l1_findings.append("Wet room directly above terrace/open-to-sky")
    if not cert.cores_stack_aligned:
        l1_findings.append("Cores not stack-aligned across storeys")
    min_dim_note = "" if cert.min_dimensions_satisfied else (
        "NBC minimum dimensions met under bounded degradation tolerance")
    aspect_note = "" if cert.aspect_ratios_satisfied else (
        "Room aspect ratio outside the ontology hard band (industrial bays exempt)")
    # Listed aspect relaxations are not a pass on the band: they are accepted
    # exceptions.  The gate WARNs and names them so a reader never mistakes a
    # declared relaxation for a satisfied invariant.
    _aspect_relaxations = list(
        (getattr(cert, "details", {}) or {}).get("declared_aspect_relaxations") or []
    )
    if _aspect_relaxations:
        l1_findings.append(
            f"{len(_aspect_relaxations)} aspect relaxation(s) declared and listed in the "
            "certificate; the hard band was not met for those rooms"
        )
    l1_advisory = (
        (not cert.min_dimensions_satisfied)
        or (not cert.aspect_ratios_satisfied)
        or bool(_aspect_relaxations)
    )
    l1_status = "FAIL" if l1_broken else ("PASS" if not l1_advisory else "WARN")
    # Zero-silent-skips: chain-sum precision must be verifiable. A
    # solved floor without serialized dimension chains is a silent skip and
    # invalidates the gate; when chains exist they are machine-verified in the
    # engine (see dimension_chain_audit in cert.details).
    chain_audit = (getattr(cert, "details", {}) or {}).get("dimension_chain_audit") or {}
    if chain_audit.get("floors_without_chains"):
        l1_status = "FAIL"
        l1_findings.append(
            "Dimension chain verification unavailable on floor(s) "
            + ", ".join(str(z) for z in chain_audit["floors_without_chains"])
            + " - dimension set-out not machine-verified (silent-skip guard)"
        )
    # LAND IS GATE-BEARING: the space-efficiency certificate used
    # to be a side panel, so a generation could report PASS beside a FAILing
    # land certificate. Geometry/statutory land checks now decide L1.
    _land_fail: List[str] = []
    _land_advisory: List[str] = []
    if land_cert is not None:
        # Accept either the report or its certificate.
        _land_report = land_cert
        _land_cert = getattr(land_cert, "certificate", land_cert)
        _need = float(getattr(_land_report, "program_needed_area_m2", 0.0) or 0.0)
        _deficit = float(getattr(_land_report, "program_deficit_sqm", 0.0) or 0.0)
        _deficit_ratio = (_deficit / _need) if _need > 0 else 0.0
        for _name, _ok in (getattr(_land_cert, "checks", {}) or {}).items():
            if _ok:
                continue
            _label = _LAND_CHECK_LABELS.get(_name, _name.replace("_", " "))
            # A SMALL programme deficit is a tight-but-legal plate: the rooms
            # are disclosed by name, the gate WARNs, and the status is
            # "compromise". Only a material deficit (>15 %, the same threshold
            # that refuses a collapsed brief) is a land FAIL. The certificate
            # Itself still reports the check as failed either way.
            #
            # An INSCRIBED-CAPPED plate is a different case: on a tapered
            # boundary the largest orthogonal rectangle is smaller than the
            # coverage ceiling, so the shortfall is a property of the boundary,
            # not of the brief.  Refusing it would hide a plan the partitioner
            # can draw and disclose (PLATE-SHORT + ROOM-MIN + L16); the deficit
            # stays printed on the certificate and LAND-06 names the cause.
            # Refusal remains for a plate the brief has collapsed (the engine's
            # own GEN-UNFIT path runs before the gate).
            _inscribed_capped = (
                str(getattr(_land_report, "footprint_source", "") or "") == "inscribed"
                and float(getattr(_land_report, "footprint_area_sqm", 0.0) or 0.0)
                < float(getattr(_land_report, "coverage_limit_area_sqm", 0.0) or 0.0) - 1.0
            )
            _small_deficit = _name == "program_fits_footprint" and (
                0.0 < _deficit_ratio <= 0.15
                or (_inscribed_capped and _deficit_ratio <= 0.35)
            )
            if _name in _LAND_ADVISORY_CHECKS or _small_deficit:
                _land_advisory.append(
                    f"LAND: {_label} failed"
                    + (f" ({_deficit:.1f} m² short, {_deficit_ratio * 100.0:.1f}%)"
                       if _name == "program_fits_footprint" else "")
                )
            else:
                _land_fail.append(f"LAND: {_label} failed")
        if _land_fail:
            l1_status = "FAIL"
            l1_findings.extend(_land_fail)
        elif _land_advisory:
            if l1_status == "PASS":
                l1_status = "WARN"
            l1_findings.extend(_land_advisory)
    _land_note = ""
    if _land_fail:
        _land_note = f"; {len(_land_fail)} land check(s) failed"
    elif _land_advisory:
        _land_note = f"; {len(_land_advisory)} land advisory"
    n_chains = int(chain_audit.get("chains_checked", 0) or 0)
    layers.append(make_layer(
        "L1", l1_status,
        summary=("All geometric & statutory invariants hold" if l1_status == "PASS"
                 else (min_dim_note or aspect_note
                       or "Declared, certificate-listed relaxations accepted"))
        + (f"; {n_chains} dimension chains verified within 1mm" if n_chains else "")
        + _land_note,
        findings=l1_findings,
        citation="NBC 2016 Part 3 / Part 8; engine invariants REL-01, CONT-01, DIM-01, CIRC-01, VERT-01..05",
    ))

    # ---------------------------------------------------------------- L2-L8
    lq = getattr(cert, "details", {}).get("living_quality_layers", {}) if cert else {}

    l2_ok = bool(getattr(cert, "l2_door_swings_valid", True))
    layers.append(make_layer(
        "L2", "PASS" if l2_ok else "FAIL",
        summary="Zero door-swing collisions after resolution" if l2_ok else "Residual swing collisions",
        citation="NBC 2016 Part 3 Cl 12.16 door clear widths; swing-containment invariant",
    ))

    l3_ok = bool(getattr(cert, "l3_fixture_clearances_satisfied", True))
    layers.append(make_layer(
        "L3", "PASS" if l3_ok else "WARN",
        summary="All bathroom fixtures meet coded clearances" if l3_ok else "Fixture clearance advisory",
        citation="NBC 2016 Part 9 / NKBA planning standards",
    ))

    l4_ok = bool(getattr(cert, "l4_furniture_clearances_satisfied", True))
    layers.append(make_layer(
        "L4", "PASS" if l4_ok else "WARN",
        summary="Furniture sets placed with circulation envelopes" if l4_ok else "Furniture clearance advisory",
        citation="Architectural Graphic Standards; NBC 2016 Part 9 room minima",
    ))

    l5_status = _status_from_str(lq.get("L5_naming_honesty", "pass"))
    layers.append(make_layer(
        "L5", l5_status,
        summary="Room names match ontological thresholds (demote-only)" if l5_status == "PASS"
        else "Naming threshold advisory",
        citation="Ontology SpaceTypeSpec class thresholds (Master Suite >= 14.0 m2)",
    ))

    l6_status = _status_from_str(lq.get("L6_stair_compliance", "pass"))
    layers.append(make_layer(
        "L6", l6_status,
        summary="Stair verified as computed object (T/R/width/headroom)" if l6_status == "PASS"
        else "Stair compliance advisory",
        citation="NBC 2016 Part 3 Cl 12.18",
    ))

    l7_status = _status_from_str(lq.get("L7_vastu", "pass"))
    layers.append(make_layer(
        "L7", l7_status,
        summary="Vastu scoring recorded (advisory layer)" if l7_status == "PASS"
        else "Vastu advisory note",
        citation="Project Vastu ontology zone weights (advisory, non-statutory)",
    ))

    layers.append(make_layer(
        "L8", "PASS" if pi_ok else "FAIL",
        summary="Program intent satisfied (bedrooms upstairs, zoning, terrace ratio)" if pi_ok
        else "Program intent violated",
        findings=list(pi_warns or []),
        citation="NBC 2016 Part 3; program-intent engine rules",
    ))
    # Terrace-ratio justification warning - when open terrace exceeds
    # the applicable threshold, the layer must carry the conversion guidance,
    # even where the engine's hard L8 verdict passes (passive_ventilation).
    lq_audit = (lq or {}).get("program_intent_audit") or {}
    ratio_pct = lq_audit.get("terrace_ratio_pct")
    if ratio_pct is not None and not lq_audit.get("terrace_ratio_satisfied", True):
        l8_prev = layers[-1]
        layers[-1] = make_layer(
            "L8", l8_prev.status,
            summary=(f"Program intent: terrace ratio {ratio_pct}% exceeds applicable threshold - "
                     "conversion guidance issued"),
            findings=list(dict.fromkeys(
                list(l8_prev.findings)
                + [w for w in (pi_warns or []) if "Terrace Ratio" in w]
            )),
            citation="NBC 2016 Part 3; program-intent engine rules",
        )

    # ------------------------------------------------------- L9-L14 (engineering)
    try:
        vent = compute_ventilation_registry(floors, duct_shafts)
        _vent_findings = [
            f"{r['room_id']} (F{r['floor_index']}): mechanical ventilation flagged"
            for r in vent["records"] if r["status"] == "warn"
        ]
        _vent_findings.extend(vent.get("daylight_findings") or [])
        layers.append(make_layer(
            "L9", _status_from_str(vent["status"]),
            summary=(f"{vent['external_opening_count']} external, {vent['shaft_vent_count']} shaft, "
                     f"{vent['mechanical_flagged_count']} mechanical-flagged"
                     + (f"; {vent['daylight_failure_count']} kitchen(s) without a "
                        "daylight/exterior opening"
                        if vent.get("daylight_failure_count") else "")),
            findings=_vent_findings,
            citation=vent["citation"],
            details={"records": vent["records"], "total_rooms": vent["total_rooms"],
                     "daylight_required_count": vent.get("daylight_required_count", 0),
                     "daylight_failure_count": vent.get("daylight_failure_count", 0)},
        ))
    except Exception as exc:  # defensive: a layer engine bug must never kill the gate
        logger.exception("L9 ventilation layer crashed")
        layers.append(make_layer("L9", crash_status("L9"),
                                 summary=f"Layer evaluation error: {exc} - not verified",
                                 findings=["Evaluator crashed; this layer is unverified"],
                                 reason=None, citation=None))

    try:
        wet = compute_wet_core_audit(floors, duct_shafts)
        layers.append(make_layer(
            "L10", _status_from_str(wet["status"]),
            summary=(f"{wet['associated_count']}/{wet['wet_room_count']} wet rooms shaft-grouped, "
                     f"{len(wet['crossings'])} dry-room crossings"),
            findings=list(wet["findings"]),
            citation=wet["citation"],
            details={"associations": wet.get("associations") if isinstance(wet, dict) else None,
                     "crossings": wet["crossings"]},
        ))
    except Exception as exc:
        logger.exception("L10 wet-core layer crashed")
        layers.append(make_layer("L10", crash_status("L10"),
                                 summary=f"Layer evaluation error: {exc} - not verified",
                                 findings=["Evaluator crashed; this layer is unverified"]))

    try:
        terr = compute_terrace_drainage(floors)
        l11_reason = terr.get("reason")
        if terr["status"] == "n/a" and not l11_reason:
            # Honest N/A: distinguish "no terrace requested" from "terrace plate
            # variation existed but did not materialize as a room object".
            masks = plate_masks or {}
            has_mask_terrace = any(
                str(v).lower() == "terrace"
                for m in masks.values() if isinstance(m, dict)
                for v in m.values()
            )
            l11_reason = ("Terrace plate variation present but no terrace zone "
                          "materialized in this generation"
                          if has_mask_terrace else
                          "No terrace zone on any floor of this generation")
        layers.append(make_layer(
            "L11", _status_from_str(terr["status"]),
            summary=(f"{terr['terrace_count']} terrace(s): slope {terr['terraces'][0]['slope_ratio']} to drain, "
                     f"downpipe -> {terr['site_outlet_id']}") if terr["terrace_count"] else "No terrace",
            reason=l11_reason if terr["status"] == "n/a" else None,
            citation=terr["citation"],
            details={"terraces": terr["terraces"]},
        ))
    except Exception as exc:
        logger.exception("L11 terrace-drainage layer crashed")
        layers.append(make_layer("L11", crash_status("L11"),
                                 summary=f"Layer evaluation error: {exc} - not verified",
                                 findings=["Evaluator crashed; this layer is unverified"]))

    try:
        struct = compute_structural_model(floors, typology,
                                          getattr(engine, "structural_grid", None))
        # Load-path continuity wording - the summary states the floor-to-floor
        # continuity verdict explicitly (never only as a flagged-beam count).
        n_transfer = int(struct.get("beam_count", 0) or 0)
        load_path_note = (
            f"load-path continuity verified floor-to-floor ({n_transfer} transfer beam(s) flagged)"
            if n_transfer == 0 else
            f"load-path gaps flagged: {n_transfer} transfer beam(s) required"
        )
        layers.append(make_layer(
            "L12", _status_from_str(struct["status"]),
            summary=(f"{struct['column_count']} columns (span <= {struct['max_span_m']:.1f}m), "
                     f"{load_path_note}"),
            findings=[b["note"] for b in struct["beams"]],
            citation=struct["citation"],
            details={"columns": struct["columns"][:40], "beams": struct["beams"],
                     "footing_hints": struct["footing_hints"]},
        ))
    except Exception as exc:
        logger.exception("L12 structural layer crashed")
        layers.append(make_layer("L12", crash_status("L12"),
                                 summary=f"Layer evaluation error: {exc} - not verified",
                                 findings=["Evaluator crashed; this layer is unverified"]))

    try:
        acc = compute_accessibility_audit(floors, typology)
        layers.append(make_layer(
            "L13", _status_from_str(acc["status"]),
            summary=(f"Applicability {acc['applicability']}: "
                     f"{len(acc['corridor_checks'])} corridors, "
                     f"{len(acc['door_checks'])} doors, "
                     f"{len(acc['circle_checks'])} sanitary circles"),
            findings=list(acc["findings"]),
            citation=acc["citation"],
            details={"corridor_checks": acc["corridor_checks"],
                     "circle_checks": acc["circle_checks"]},
        ))
    except Exception as exc:
        logger.exception("L13 accessibility layer crashed")
        layers.append(make_layer("L13", crash_status("L13"),
                                 summary=f"Layer evaluation error: {exc} - not verified",
                                 findings=["Evaluator crashed; this layer is unverified"]))

    try:
        occ = int(statutory_audit.get("occupant_load", 0) or 0)
        fire = compute_fire_egress_audit(floors, typology,
                                         bool(getattr(cert, "egress_distances_satisfied", True)),
                                         occupant_load=occ)
        _protection = fire.get("protection") or {}
        _cap_note = ""
        if _protection:
            _cap_note = (
                f"; stair {_protection.get('stair_clear_width_m', 0.0):.2f} m carries "
                f"~{_protection.get('stair_occupants_served', 0.0):.0f} of "
                f"{_protection.get('governing_occupant_load', 0)} occupants"
                + ("" if _protection.get("capacity_satisfied") else " - CAPACITY SHORTFALL")
            )
        layers.append(make_layer(
            "L14", _status_from_str(fire["status"]),
            summary=(f"Travel distances {'verified' if bool(getattr(cert, 'egress_distances_satisfied', True)) else 'EXCEEDED'}; "
                     f"{len(fire['bedroom_egress'])} bedroom egress checks, "
                     f"{len(fire['exit_width_table'])} exit rows{_cap_note}"),
            findings=list(fire["findings"]),
            citation=fire["citation"],
            details={"exit_width_table": fire["exit_width_table"],
                     "bedroom_egress": fire["bedroom_egress"],
                     "protection": _protection},
        ))
    except Exception as exc:
        logger.exception("L14 fire-egress layer crashed")
        layers.append(make_layer("L14", crash_status("L14"),
                                 summary=f"Layer evaluation error: {exc} - not verified",
                                 findings=["Evaluator crashed; this layer is unverified"]))

    # ---------------------------------------------------------------- L15
    try:
        completeness = assess_programme_completeness(floors, typology)
        l15_status = completeness["status"]
        l15_reason = completeness.get("reason")
        l15_missing = completeness.get("missing") or []
        layers.append(make_layer(
            "L15", l15_status,
            summary=("All essential programme rooms present" if l15_status == "PASS"
                     else (l15_reason or "Missing essential programme rooms: " + ", ".join(l15_missing))),
            reason=l15_reason if l15_status == "N/A" else None,
            findings=[f"Missing essential room: {m}" for m in l15_missing],
            citation="NBC 2016 Part 3 occupancy requirements; typology programme catalogue",
            details={"missing": l15_missing, "per_unit": completeness.get("per_unit") or {},
                     "rooms_checked": completeness.get("rooms_checked", 0)},
        ))
    except Exception as exc:
        logger.exception("L15 programme-completeness layer crashed")
        layers.append(make_layer("L15", "FAIL",
                                 summary=f"Completeness audit unavailable: {exc}",
                                 findings=["Essential rooms could not be verified"],
                                 citation="NBC 2016 Part 3 occupancy requirements"))

    # ---------------------------------------------------------------- L16
    # PROPORTION & SURPLUS (Refusal and disclosure).
    #
    # The ontology declares a hard aspect band, a planning ceiling and a
    # relaxation cap.  This layer is where a reader can SEE the result per room,
    # and it is gate-bearing: an unlisted breach beyond the cap FAILs the layer
    # (the plan is still drawn and exported - refusal is reserved for statutory,
    # egress and stacking failures), while listed relaxations and ceiling
    # overages WARN.
    try:
        from app.services.floorplan.ontology import ONTOLOGY
        from app.services.floorplan.identity import space_type_of
        from app.services.floorplan.proportion_law import ASPECT_RELAXATION_CAP

        _aspect_exempt = {"commercial_suite", "industrial_bay"}
        rows: List[Dict[str, Any]] = []
        beyond: List[str] = []
        relaxed: List[Dict[str, Any]] = []
        ceilings: List[Dict[str, Any]] = []
        checked = 0
        for _fl in floors:
            for _r in _fl.rooms:
                if _r.zone_category in ("circulation", "terrace") or _r.zone_category == "industrial_bay":
                    continue
                _sid = space_type_of(_r, typology) or _r.room_id
                _spec = ONTOLOGY.get_space(_sid)
                if _spec is None or _spec.id in _aspect_exempt:
                    continue
                _w, _d = float(_r.width_m), float(_r.depth_m)
                if _w <= 0.05 or _d <= 0.05:
                    continue
                checked += 1
                _aspect = max(_w, _d) / min(_w, _d)
                _band = float(_spec.max_aspect_ratio or 0.0)
                _rel = next(
                    (rel for rel in (_r.relaxations or [])
                     if str(rel.get("rule_id")) == "PROP-ASPECT"),
                    None,
                )
                _justified = next(
                    (rel for rel in (_r.relaxations or [])
                     if str(rel.get("rule_id")) == "PROP-PLATE-CAP"),
                    None,
                )
                _over = _band > 0.0 and _aspect > _band + 0.02
                _beyond_cap = _over and _aspect > _band * ASPECT_RELAXATION_CAP + 0.02
                _ceiling = float(_spec.area_ceiling_sqm or 0.0)
                _area = float(_r.area_sqm)
                _ceiling_over = _ceiling > 0.0 and _area > _ceiling + 0.05
                rows.append({
                    "floor": int(_fl.floor_index),
                    "room_id": _r.room_id,
                    "space_type_id": _spec.id,
                    "measured_aspect": round(_aspect, 2),
                    "band": round(_band, 2),
                    "band_pct": round(100.0 * _aspect / _band, 1) if _band else None,
                    "inside_band": not _over,
                    "relaxation_rule": (str(_rel.get("rule_id")) if _rel else None),
                    "relaxation_factor": (
                        round(_aspect / _band, 2) if (_rel and _band) else None
                    ),
                    "area_sqm": round(_area, 2),
                    "area_ceiling_sqm": round(_ceiling, 2) if _ceiling else None,
                    "ceiling_overage_sqm": (
                        round(_area - _ceiling, 2) if _ceiling_over else 0.0
                    ),
                    "beyond_cap_justification": (
                        str(_justified.get("rationale")) if _justified else None
                    ),
                })
                if _rel is not None:
                    relaxed.append({
                        "room": _r.room_id, "floor": int(_fl.floor_index),
                        "rule_id": str(_rel.get("rule_id")),
                        "measured": round(_aspect, 2), "band": round(_band, 2),
                    })
                if _beyond_cap:
                    beyond.append(
                        f"F{_fl.floor_index} {_r.room_id}: 1:{_aspect:.2f} against a "
                        f"1:{_band:.2f} band ({_aspect / max(_band, 0.01):.2f}x, cap "
                        f"{ASPECT_RELAXATION_CAP:.2f}x) and no listed relaxation"
                    )
                if _ceiling_over:
                    ceilings.append({
                        "room": _r.room_id, "floor": int(_fl.floor_index),
                        "area_sqm": round(_area, 2), "ceiling_sqm": round(_ceiling, 2),
                        "overage_sqm": round(_area - _ceiling, 2),
                        "rationale": "planning ceiling, disclosed not stretched",
                    })

        _dead = float(getattr(land_cert, "dead_corner_area_sqm", 0.0) or 0.0)
        _fp_area = float(getattr(land_cert, "footprint_area_sqm", 0.0) or 0.0)
        _void_ratio = round(100.0 * _dead / _fp_area, 2) if _fp_area > 0.0 else 0.0
        _justified_rows = [
            {"room": r["room_id"], "floor": r["floor"],
             "measured": r["measured_aspect"], "band": r["band"],
             "reason": r["beyond_cap_justification"]}
            for r in rows if r.get("beyond_cap_justification")
        ]
        _surplus = {
            "outdoor_sqm": round(float(getattr(land_cert, "outdoor_area_sqm", 0.0) or 0.0), 2),
            "anonymous_outdoor_sqm": round(
                float(getattr(land_cert, "anonymous_outdoor_area_sqm", 0.0) or 0.0), 2
            ),
            "residual_slivers": int(getattr(land_cert, "sliver_count", 0) or 0),
            "absorbed_slivers": int(getattr(land_cert, "absorbed_residual_count", 0) or 0),
            "sliver_labels": [
                str(getattr(s, "absorbed_as", "") or "unassigned")
                for s in (getattr(land_cert, "slivers", []) or [])[:12]
            ],
            "dead_corner_sqm": round(_dead, 2),
            "void_ratio_pct": _void_ratio,
        }

        if checked == 0:
            layers.append(make_layer(
                "L16", "N/A",
                summary="No proportion-governed room on this plan (circulation/terrace only)",
                reason="every room is exempt from the room-band law",
                citation="NBC 2016 Part 3; Neufert Architects' Data (bands); ontology PROPORTION_BANDS",
            ))
        else:
            _status = "FAIL" if beyond else ("WARN" if (relaxed or ceilings) else "PASS")
            _findings: List[str] = []
            _findings.extend(beyond)
            if relaxed:
                _findings.append(
                    f"{len(relaxed)} listed aspect relaxation(s): "
                    + ", ".join(f"{r['room']} {r['measured']:.2f}/{r['band']:.2f}" for r in relaxed[:8])
                )
            if ceilings:
                _findings.append(
                    f"{len(ceilings)} room(s) over their planning ceiling: "
                    + ", ".join(f"{c['room']} +{c['overage_sqm']:.1f} m²" for c in ceilings[:8])
                )
            if _surplus["anonymous_outdoor_sqm"] > 0.5:
                _findings.append(
                    f"{_surplus['anonymous_outdoor_sqm']:.1f} m² of outdoor area is unlabelled"
                )
            layers.append(make_layer(
                "L16", _status,
                summary=(
                    f"{checked - len(relaxed) - len(beyond)}/{checked} rooms inside the hard band; "
                    f"{len(relaxed)} listed relaxation(s); {len(beyond)} beyond the "
                    f"{ASPECT_RELAXATION_CAP:.2f}x cap; {len(ceilings)} ceiling overage(s); "
                    f"void {_void_ratio:.1f}% of the plate"
                ),
                reason=None,
                findings=_findings,
                citation=(
                    "ontology PROPORTION_BANDS + PROPORTION_POLICY; NBC 2016 Part 3; "
                    "Neufert Architects' Data (ideal/hard bands); planning ceilings are "
                    "declared bounds, not statutory maxima"
                ),
                details={
                    "rooms_checked": checked,
                    "rooms": rows,
                    "relaxations": relaxed,
                    "beyond_cap": beyond,
                    "justified_beyond_cap": _justified_rows,
                    "ceiling_overages": ceilings,
                    "surplus": _surplus,
                    "relaxation_cap": ASPECT_RELAXATION_CAP,
                    "refusal_policy": (
                        "A proportion FAIL is drawn and exported with a FAIL "
                        "stamp; refusal is reserved for statutory/egress/stacking failures"
                    ),
                },
            ))
    except Exception as exc:
        logger.exception("L16 proportion layer crashed")
        layers.append(make_layer(
            "L16", "FAIL",
            summary=f"Layer evaluation error: {exc} - proportion not verified",
            findings=["Evaluator crashed; the proportion law is unverified"],
        ))

    # Enforce completeness: every declared layer is present or explicitly FAILs.
    layers = ensure_all_layers(layers)

    layers.sort(key=lambda l: LAYER_IDS.index(l.layer_id))
    return [l.to_dict() for l in layers]


def refusal_gate_report(reason: str) -> Dict[str, Any]:
    """Gate payload for a REFUSED generation (no geometry was solved).

    A refusal is a verdict, not an absence: the caller must still receive the
    full L1-L15 contract, every layer explicitly N/A WITH the refusal reason,
    and an overall FAIL. Emitting no gate at all let a refused plan look like
    a plan whose gate had never been asked for (: absence is not a
    pass), and gave the certificate/UI surfaces nothing to render.
    """
    note = (str(reason or "").strip() or "Generation refused before any geometry was solved")
    layers: List[LayerStatus] = [
        make_layer(
            lid, "N/A",
            summary="Not evaluated: generation refused",
            reason=note,
            findings=["No geometry to evaluate - the brief was refused, not certified"],
        )
        for lid in LAYER_IDS
    ]
    dicts = [l.to_dict() for l in layers]
    return {
        "layer_ids": list(LAYER_IDS),
        "layers": dicts,
        "overall_status": "FAIL",
        "validated_layers": [],
        "n_a_layers": [{"layer_id": d["layer_id"], "reason": note} for d in dicts],
        "llm_boundary": {"events": [], "event_ids": []},
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contract": "universal_gate_v1",
        "refused": True,
        "refusal_reason": note,
    }


def assemble_gate_report(layer_dicts: List[Dict[str, Any]],
                         llm_boundary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Bundles the serialized gate into the certificate details payload."""
    overall = overall_from_dicts(layer_dicts)
    return {
        "layer_ids": LAYER_IDS,
        "layers": layer_dicts,
        "overall_status": overall,
        "validated_layers": [d["layer_id"] for d in layer_dicts if d["status"] != "N/A"],
        "n_a_layers": [{"layer_id": d["layer_id"], "reason": d.get("reason", "not_applicable")}
                       for d in layer_dicts if d["status"] == "N/A"],
        "llm_boundary": llm_boundary or {"events": [], "event_ids": []},
        "evaluated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "contract": "universal_gate_v1",
    }


# =============================================================================
# HONEST DRAWING-STATUS STAMP (single source)
# =============================================================================

STAMP_HEAD = "STATUS: CONCEPT DESIGN - VALIDATED LAYERS: ["
def drawing_status_stamp(validated_layers: Optional[List[str]],
                         scope_note: Optional[str] = None) -> str:
    """Canonical honest stamp, e.g.
    'STATUS: CONCEPT DESIGN - VALIDATED LAYERS: [L1, L2] - NOT FOR CONSTRUCTION'.

    Every sheet/PDF surface must derive its stamp from this helper. The
    sheet-wrap logic in drawing_ir._wrap_status_stamp parses exactly this
    format (head prefix per line + legal tail on the final line); do not
    re-word here without updating that parser.
    """
    layers_str = ", ".join(validated_layers or [])
    note = f" ({scope_note})" if scope_note else ""
    # The scope note sits AFTER the closing bracket: the sheet wrap parser
    # treats everything inside [...] as layer ids.
    return f"{STAMP_HEAD}{layers_str}]{note} - NOT FOR CONSTRUCTION"
