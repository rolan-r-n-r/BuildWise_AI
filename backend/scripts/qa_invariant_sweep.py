#!/usr/bin/env python3
"""qa_invariant_sweep.py - adversarial invariant sweep for the space engine.

Runs the live public entry point (``generate_floor_plan``) across the adversarial
matrix and checks the eight invariants independently of the engine's own
certificate:

    I1 relations      forbidden wall / door-facing / above pairs, from ontology
    I2 minima         room area & width against SpaceTypeSpec, warn-or-fix only
    I3 egress         BFS connectivity, travel distance, core continuity, T4 chain
    I4 land           anonymous slivers, wedge labels, circulation band, parking
    I5 identity       label == schedule == SVG == model, naming honesty
    I6 determinism    same seed + inputs -> byte-identical payload
    I7 schemes        three ranked, materially different, honest deltas
    I8 layers         gate present, ventilation zero-miss, furniture, certificate
    I9 typology       returned rooms carry the requested typology's programme

Every violation is recorded with the case id, the seed and the payload it came
from so it can be pinned as a regression test.

Usage (from backend/):
    python scripts/qa_invariant_sweep.py                    # full matrix
    python scripts/qa_invariant_sweep.py --quick            # 1 storey, high strictness
    python scripts/qa_invariant_sweep.py --only T3-T2-L-shape-14x14-F2
"""

from __future__ import annotations

import argparse
import html
import itertools
import json
import logging
import re
import sys
import traceback
import warnings
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.site_plan import PlotPolygonModel
from app.services.floorplan.constrained_solver import _touching
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.floorplan.ontology import ONTOLOGY, RelationType
from app.services.floorplan.validation_gate import LAYER_IDS

from space_engine_baseline import (  # measurement-side helpers, no engine change
    canonical_response,
    measure,
)

OUT_DIR = Path(__file__).resolve().parents[2] / "docs_ignore" / "space-engine"

TYPOLOGIES = [
    ("T1", "residential_single"),
    ("T2", "residential_apartment"),
    ("T3", "commercial_complex"),
    ("T4", "industrial_warehouse"),
]

PLOTS: List[Dict[str, Any]] = [
    {"key": "rect-12x15", "w": 12.0, "d": 15.0, "poly": None},
    {"key": "rect-20x20", "w": 20.0, "d": 20.0, "poly": None},
    {"key": "tiny-8x10", "w": 8.0, "d": 10.0, "poly": None},
    {"key": "huge-40x60", "w": 40.0, "d": 60.0, "poly": None},
    {"key": "l-shape-14x14", "w": 14.0, "d": 14.0,
     "poly": [(0, 0), (14, 0), (14, 8), (8, 8), (8, 14), (0, 14)]},
    {"key": "trapezoid-14x16", "w": 14.0, "d": 16.0,
     "poly": [(0, 0), (14, 0), (11, 16), (2, 16)]},
    {"key": "curvilinear-14x14", "w": 15.8, "d": 14.0,
     "poly": [(0, 0), (14, 0), (15, 3), (15.8, 7), (15, 11), (14, 14), (0, 14)]},
]

STRICTNESS = ("low", "medium", "high")
FLOORS = (1, 2, 3, 4)

violations: List[Dict[str, Any]] = []
# LISTED breaches: a shortfall the certificate already discloses with a rule id
# and rationale.  Counted and reported in their own column, never failed.
disclosed: List[Dict[str, Any]] = []
case_rows: List[Dict[str, Any]] = []


def add(code: str, severity: str, case_id: str, detail: str, **extra: Any) -> None:
    violations.append({
        "code": code,
        "severity": severity,
        "case_id": case_id,
        "detail": detail,
        **{k: v for k, v in extra.items() if v not in (None, "", [], {})},
    })


def add_disclosed(code: str, case_id: str, detail: str, **extra: Any) -> None:
    disclosed.append({
        "code": code,
        "severity": "DISCLOSED",
        "case_id": case_id,
        "detail": detail,
        **{k: v for k, v in extra.items() if v not in (None, "", [], {})},
    })


def _certificate_measures(room: Any) -> bool:
    """Mirror the L1 domain: circulation/terraces are not habitable minima."""
    if room is None:
        return False
    if str(getattr(room, "zone_category", "")) in ("circulation", "terrace"):
        return False
    rid = str(getattr(room, "room_id", ""))
    return "corridor" not in rid and "terrace" not in rid


def _listed_minimum_relaxation(room: Any) -> Optional[Dict[str, Any]]:
    """The NBC-01 relaxation the certificate lists for a room, if any."""
    for rel in (getattr(room, "relaxations", None) or []):
        rid = rel.get("rule_id") if isinstance(rel, dict) else getattr(rel, "rule_id", None)
        if str(rid) == "NBC-01":
            return rel if isinstance(rel, dict) else {"rule_id": rid}
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def room_ontology_id(room: Any) -> Optional[str]:
    sid = getattr(room, "space_type_id", None)
    if sid:
        return sid
    ident = getattr(room, "identity", None)
    if ident is not None:
        return getattr(ident, "space_type_id", None)
    return ONTOLOGY.resolve_space_id(str(getattr(room, "room_id", "")), None)


def dedup_warnings(resp: Any) -> List[str]:
    ms = resp.multi_storey
    raw = list(resp.warnings or []) + list((ms.warnings if ms else []) or [])
    if ms is not None:
        raw += list((ms.land_economics.warnings if ms.land_economics else []) or [])
    return list(dict.fromkeys(raw))


def touching(a: Any, b: Any) -> bool:
    try:
        ok, _run = _touching(a, b)
        return bool(ok)
    except Exception:
        return False


def overlap_area(a: Any, b: Any) -> float:
    x = min(a.x + a.width_m, b.x + b.width_m) - max(a.x, b.x)
    y = min(a.y + a.depth_m, b.y + b.depth_m) - max(a.y, b.y)
    return max(0.0, x) * max(0.0, y)


def make_request(typology: str, plot: Dict[str, Any], floors: int,
                 strictness: str, seed: str, *, schemes: bool = False) -> FloorPlanRequest:
    kwargs: Dict[str, Any] = dict(
        plot_width_m=plot["w"],
        plot_depth_m=plot["d"],
        building_typology=typology,
        floors=floors,
        vastu_strictness=strictness,
        bypass_cache=True,
        ai_provider="mock",
        seed=seed,
        include_scheme_alternatives=schemes,
    )
    if plot["poly"]:
        verts = plot["poly"]
        xs = [p[0] for p in verts]
        ys = [p[1] for p in verts]
        kwargs["plot_polygon"] = PlotPolygonModel(
            vertices=verts,
            shape_type="polygon",
            has_curved_edges=plot["key"].startswith("curvilinear"),
            is_regular_rectangle=False,
            area_sqm=0.0,
            perimeter_m=0.0,
            bounding_box=(min(xs), min(ys), max(xs), max(ys)),
        )
    return FloorPlanRequest(**kwargs)


def rooms_by_floor(resp: Any) -> List[List[Any]]:
    ms = resp.multi_storey
    if ms is None:
        return []
    return [list(f.rooms or []) for f in ms.floors]


# ---------------------------------------------------------------------------
# I1 - relations
# ---------------------------------------------------------------------------

def check_relations(case_id: str, resp: Any) -> Dict[str, int]:
    counts = {"forbidden_wall": 0, "forbidden_door": 0, "forbidden_above": 0, "pairs": 0}
    floors = rooms_by_floor(resp)

    for rooms in floors:
        for a, b in itertools.combinations(rooms, 2):
            if a.zone_category == "terrace" or b.zone_category == "terrace":
                continue
            if not touching(a, b):
                continue
            ia, ib = room_ontology_id(a), room_ontology_id(b)
            if not ia or not ib:
                continue
            counts["pairs"] += 1
            for rule in ONTOLOGY.get_relations(ia, ib):
                if rule.relation == RelationType.FORBIDDEN_WALL:
                    counts["forbidden_wall"] += 1
                    add("I1-FORBIDDEN-WALL", "CRITICAL", case_id,
                        f"{a.room_id} ({ia}) shares a wall with {b.room_id} ({ib}) "
                        f"[{getattr(rule, 'rule_id', 'rule')}]",
                        rooms=[a.room_id, b.room_id])
                elif rule.relation == RelationType.FORBIDDEN_DOOR_FACING:
                    counts["forbidden_door"] += 1
                    add("I1-FORBIDDEN-DOOR", "MAJOR", case_id,
                        f"{a.room_id} / {b.room_id} touch and are forbidden door-facing "
                        f"[{getattr(rule, 'rule_id', 'rule')}]",
                        rooms=[a.room_id, b.room_id])

    for lower, upper in zip(floors, floors[1:]):
        for a in lower:
            for b in upper:
                if a.zone_category == "terrace" or b.zone_category == "terrace":
                    continue
                if overlap_area(a, b) < 0.5:
                    continue
                ia, ib = room_ontology_id(a), room_ontology_id(b)
                if not ia or not ib:
                    continue
                for rule in ONTOLOGY.get_relations(ia, ib) + ONTOLOGY.get_relations(ib, ia):
                    if rule.relation == RelationType.FORBIDDEN_ABOVE:
                        counts["forbidden_above"] += 1
                        add("I1-FORBIDDEN-ABOVE", "CRITICAL", case_id,
                            f"{b.room_id} ({ib}) sits above {a.room_id} ({ia}) "
                            f"[{getattr(rule, 'rule_id', 'rule')}]",
                            rooms=[a.room_id, b.room_id])
    return counts


# ---------------------------------------------------------------------------
# I4 - land, I3 - egress, I8 - layers
# ---------------------------------------------------------------------------

def _envelope_dead_area(resp: Any) -> float:
    """Interior area of each building envelope not covered by any placed room.

    Multi-wing plates are an L/courtyard, not their bounding box: the dead area
    is measured against the wing union so the missing corner is not counted.
    """
    site = getattr(resp, "site_plan", None)
    wings = list(getattr(getattr(site, "footprint", None), "wings", []) or [])
    worst = 0.0
    for floor in (resp.multi_storey.floors if resp.multi_storey else []):
        env = floor.envelope or {}
        if not env:
            continue
        ox, oy = float(env.get("x", 0.0)), float(env.get("y", 0.0))
        if len(wings) > 1:
            shape = box(0, 0, 0, 0)
            for w in wings:
                shape = shape.union(box(w.x, w.y, w.x + w.width_m, w.y + w.depth_m))
            # Rooms are envelope-local; wings are in site coordinates.
            rooms_poly = box(0, 0, 0, 0)
            for r in floor.rooms:
                rooms_poly = rooms_poly.union(
                    box(r.x + ox, r.y + oy, r.x + r.width_m + ox, r.y + r.depth_m + oy))
            worst = max(worst, round(shape.difference(rooms_poly).area, 2))
        else:
            env_poly = box(ox, oy, ox + float(env.get("width", 0.0)), oy + float(env.get("depth", 0.0)))
            rooms_poly = box(0, 0, 0, 0)
            for r in floor.rooms:
                rooms_poly = rooms_poly.union(
                    box(r.x + ox, r.y + oy, r.x + r.width_m + ox, r.y + r.depth_m + oy))
            worst = max(worst, round(env_poly.difference(rooms_poly).area, 2))
    return worst


def check_land(case_id: str, resp: Any, row: Dict[str, Any], warns: Sequence[str]) -> Dict[str, Any]:
    ms = resp.multi_storey
    le = ms.land_economics if ms else None
    out: Dict[str, Any] = {}

    if le is None:
        add("I4-NO-LAND-REPORT", "MAJOR", case_id, "response carries no land economics report")
        return out

    checks = le.certificate.checks
    out["land_status"] = le.certificate.status
    site = getattr(resp, "site_plan", None)
    ground_env = (ms.floors[0].envelope or {}) if ms.floors else {}
    env_area = float(ground_env.get("area_sqm") or 0.0)
    site_fp = float(le.footprint_area_sqm or 0.0)
    if env_area and abs(site_fp - env_area) > 1.0:
        add("I4-SITE-BUILDING-MISMATCH", "CRITICAL", case_id,
            f"site plan footprint {site_fp:.1f} m2 vs ground floor envelope {env_area:.1f} m2")
    if checks.get("coverage_within_limit") is False:
        add("I4-COVERAGE-EXCEEDED", "CRITICAL", case_id,
            f"site footprint {le.footprint_area_sqm:.1f} m2 exceeds coverage cap "
            f"{le.coverage_limit_area_sqm:.1f} m2 on a {le.buildable_area_sqm:.1f} m2 buildable plate")
    if row.get("is_rect") and env_area and le.buildable_area_sqm and env_area > le.buildable_area_sqm + 1.0:
        add("I4-ENVELOPE-OUTSIDE-BUILDABLE", "CRITICAL", case_id,
            f"building envelope {env_area:.1f} m2 exceeds the {le.buildable_area_sqm:.1f} m2 "
            "setback buildable plate")
    if checks.get("program_fits_footprint") is False:
        if not any("deficit" in w.lower() for w in warns):
            add("I4-SILENT-DEFICIT", "CRITICAL", case_id,
                f"programme deficit {le.program_deficit_sqm:.2f} m2 without a deficit warning")
    if checks.get("circulation_within_12_20") is False:
        if not any("circulation ratio" in w.lower() for w in warns):
            add("I4-SILENT-CIRCULATION", "MAJOR", case_id,
                f"circulation {le.circulation_ratio_pct:.1f}% outside band with no warning")
    if le.sliver_count:
        add("I4-SLIVER", "MAJOR", case_id,
            f"{le.sliver_count} unlabelled residual region(s), wedge={le.wedge_area_sqm:.1f} m2")
    if le.anonymous_outdoor_area_sqm > 0.5:
        add("I4-ANONYMOUS-OUTDOOR", "MAJOR", case_id,
            f"{le.anonymous_outdoor_area_sqm:.2f} m2 of unlabelled outdoor area")
    dead = _envelope_dead_area(resp)
    out["envelope_dead_sqm"] = dead
    if dead > 1.0:
        add("I4-INTERIOR-DEAD", "MAJOR", case_id,
            f"{dead:.2f} m2 of the building envelope is not assigned to any room"
            + (" [warning present]" if any("LAND-05" in w or "dead" in w.lower() for w in warns) else " [no warning]"),
            area=dead)
    if row.get("waste_pct", 0.0) > 25.0 and not any("waste" in w.lower() for w in warns):
        add("I4-UNWARNED-WASTE", "MAJOR", case_id,
            f"waste {row['waste_pct']:.1f}% of buildable with no waste warning")
    if le.wedge_area_sqm > 0.5 and not (getattr(site, "wedge_zones", None) or []):
        add("I4-WEDGE-UNLABELLED", "MAJOR", case_id,
            f"{le.wedge_area_sqm:.2f} m2 wedge area with no labelled wedge zone")
    if le.certificate.status == "FAIL" and not le.warnings:
        add("I4-FAIL-NO-WARNING", "MAJOR", case_id,
            f"land certificate FAIL {checks} with no warning")
    return out


def check_egress(case_id: str, resp: Any, row: Dict[str, Any]) -> Dict[str, Any]:
    ms = resp.multi_storey
    out: Dict[str, Any] = {}
    if ms is None:
        return out
    cert = ms.mathematical_certificate or {}
    for key in ("connectivity_bfs", "egress_distances_satisfied", "core_continuity_valid",
                "cores_stack_aligned", "must_adjacency_satisfied"):
        if key in cert:
            out[key] = bool(cert[key])
            if not cert[key]:
                add("I3-" + key.upper().replace("_", "-"), "CRITICAL", case_id,
                    f"certificate {key}=False")
    disconnected = [f.floor_index for f in ms.floors if f.circulation_status != "connected"]
    if disconnected:
        add("I3-DISCONNECTED", "CRITICAL", case_id, f"disconnected floors: {disconnected}")
    out["disconnected_floors"] = disconnected

    if ms.vertical_cores:
        for core in ms.vertical_cores:
            cont = list(core.continuous_across_floors or [])
            if len(cont) != ms.total_storeys:
                add("I3-CORE-NOT-CONTINUOUS", "CRITICAL", case_id,
                    f"core {core.core_id} continuous on {cont} of {ms.total_storeys} storeys")
    out["cores"] = len(ms.vertical_cores)

    if resp.multi_storey.building_typology == "T4_WAREHOUSE":
        ground = ms.floors[0].rooms if ms.floors else []
        ids = {room_ontology_id(r) for r in ground}
        wanted = {"dock_bay", "dispatch", "storage_bay"}
        missing = wanted - ids
        if missing:
            add("I3-T4-CHAIN-MISSING", "CRITICAL", case_id,
                f"T4 ground floor missing {sorted(missing)}, rooms={sorted(i for i in ids if i)}")
        else:
            by_id = {room_ontology_id(r): r for r in ground}
            target = ["dock_bay", "dispatch", "storage_bay"]
            start = by_id[target[0]]
            seen = {target[0]}
            frontier = [start]
            while frontier:
                cur = frontier.pop()
                for other in target:
                    if other in seen:
                        continue
                    if touching(cur, by_id[other]) or touching(by_id[other], cur):
                        seen.add(other)
                        frontier.append(by_id[other])
            if not set(target).issubset(seen):
                add("I3-T4-CHAIN-BROKEN", "CRITICAL", case_id,
                    f"T4 loading-dispatch-storage chain broken: connected={sorted(seen)}")
            out["t4_chain"] = sorted(seen)
    return out


def check_layers(case_id: str, resp: Any, row: Dict[str, Any], warns: Sequence[str]) -> Dict[str, Any]:
    ms = resp.multi_storey
    out: Dict[str, Any] = {}
    if ms is None:
        return out
    gate = ms.validation_gate or {}
    layers = gate.get("layers") or []
    out["gate"] = gate.get("overall_status")
    if len(layers) != len(LAYER_IDS):
        add("I8-GATE-LAYER-COUNT", "MAJOR", case_id, f"gate has {len(layers)} layers")
    cert = ms.mathematical_certificate or {}
    if not cert:
        add("I8-NO-CERTIFICATE", "MAJOR", case_id, "no mathematical certificate")
    else:
        valid = bool(cert.get("is_valid"))
        out["cert_valid"] = valid
        if gate.get("overall_status") == "PASS" and not valid:
            add("I8-CERT-GATE-DISAGREE", "MAJOR", case_id,
                "gate PASS but mathematical certificate is_valid=False")

    l9 = next((l for l in layers if l.get("layer_id") == "L9"), None)
    if l9 is not None:
        records = ((l9.get("details") or {}).get("records") or [])
        misses = [r for r in records if r.get("status") != "pass"]
        if misses:
            # A miss the gate itself names is DISCLOSED, not silent: an L9 FAIL
            # lands on the plan's warning ledger and withholds certification.
            # The sweep still records it in its own register; only a miss with
            # no named L9 disclosure is a TRUE failure.  Kitchen daylight
            # shortfalls are exactly this case - the plate cannot draw a
            # compliant kitchen, the plan is fail-stamped, and calling that a
            # silent defect made the gate red for an honest answer.
            named = str(l9.get("status", "")).upper() == "FAIL" and any(
                str(w).startswith("GATE-FAIL L9") or "no exterior window" in str(w)
                for w in warns
            )
            if named:
                add_disclosed(
                    "I8-VENT-DISCLOSED", case_id,
                    f"{len(misses)} ventilation misses of {len(records)} records, named by L9",
                )
            else:
                add("I8-VENT-MISS", "MAJOR", case_id,
                    f"{len(misses)} ventilation misses of {len(records)} records")
        out["vent_records"] = len(records)

    if row.get("furniture_pass_pct") is not None and row["furniture_pass_pct"] < 100.0:
        if not any("furniture" in w.lower() for w in warns):
            add("I8-SILENT-FURNITURE", "MAJOR", case_id,
                f"furniture fits {row['furniture_pass_pct']:.1f}% of furnished rooms with no warning")
    out["furniture"] = row.get("furniture_pass_pct")

    le = ms.land_economics
    if le is not None and le.certificate.status == "FAIL" and gate.get("overall_status") == "PASS":
        add("I8-CERTIFICATE-CONTRADICTION", "MAJOR", case_id,
            f"building gate PASS while land certificate FAIL: {le.certificate.checks}")
    return out


# ---------------------------------------------------------------------------
# I2 / I5
# ---------------------------------------------------------------------------

def check_minima(case_id: str, resp: Any, row: Dict[str, Any], warns: Sequence[str]) -> int:
    """I2 — certificate minima, with DISCLOSED vs FAIL taxonomy.

    The sweep must judge the SAME domain and the SAME relaxations the L1
    certificate publishes.  A circulation spine has no habitable minimum; a
    shortfall the certificate lists as an NBC-01 relaxation is DISCLOSED (named
    in its own register, not a failure).  Only an UNLISTED shortfall fails I2.
    Clear AREA is not an L1 minimum either: the certificate measures gross area
    and wall-deducted clear WIDTH, so flagging clear area produced a wall of
    false red on plans the certificate had honestly disclosed.
    """
    ms = resp.multi_storey
    floors = list(ms.floors) if ms else []
    by_id = {r.room_id: r for floor in floors for r in floor.rooms}

    below = row.get("below_minima") or []
    for item in below:
        rid = item["room_id"]
        room = by_id.get(rid)
        if not _certificate_measures(room):
            continue
        reasons = []
        if item["area_sqm"] + 0.02 < item["min_area_sqm"]:
            reasons.append(f"area {item['area_sqm']} < {item['min_area_sqm']} m2")
        if item["clear_min_width_m"] + 0.02 < item["min_width_m"]:
            reasons.append(f"width {item['clear_min_width_m']} < {item['min_width_m']} m")
        if not reasons:
            continue
        named = any(rid in w for w in warns)
        listed = _listed_minimum_relaxation(room)
        detail = f"{rid} ({item['ontology_id']}) gross: " + ", ".join(reasons)
        if listed is not None:
            add_disclosed("I2-MINIMA-DISCLOSED", case_id,
                          detail + " — listed NBC-01 relaxation", room=rid)
        else:
            add("I2-MINIMA", "CRITICAL", case_id,
                detail + ("" if named else " [no explicit warning]"),
                room=rid)

    # Clear-face WIDTH: the schedule carries the wall-deducted dimension the
    # statutory minimum is written against; the model only exposes gross.
    for floor in floors:
        floor_by_id = {r.room_id: r for r in floor.rooms}
        for srow in (floor.room_schedule or []):
            rid = str(srow.get("room_id") or "")
            room = floor_by_id.get(rid)
            if room is None or not room.identity or not _certificate_measures(room):
                continue
            dims = str(srow.get("clear_dimensions") or srow.get("clear_dims") or "")
            match = re.findall(r"([\d.]+)\s*m\s*[x×]\s*([\d.]+)\s*m", dims)
            if not match:
                continue
            w, d = (float(match[0][0]), float(match[0][1]))
            clear_area = srow.get("clear_area_sqm")
            min_w = float(room.identity.min_width_m)
            if min(w, d) + 0.02 >= min_w:
                continue
            named = any(rid in wmsg for wmsg in warns)
            detail = (
                f"{rid} clear {w:.2f}x{d:.2f} m ({clear_area} m2) below "
                f"{min_w:.2f} m clear width"
            )
            if _listed_minimum_relaxation(room) is not None:
                add_disclosed("I2-CLEAR-MINIMA-DISCLOSED", case_id,
                              detail + " — listed NBC-01 relaxation", room=rid)
            else:
                add("I2-CLEAR-MINIMA", "CRITICAL", case_id,
                    detail + ("" if named else " [no explicit warning]"),
                    room=rid)
    return len(below)


def _sg(text: str) -> str:
    return html.unescape(text).strip()


def _svg_schedule_rows(svg: str) -> List[str]:
    """Room names rendered in the sheet's ROOM SCHEDULE table (no plan labels)."""
    labels = [_sg(t) for t in re.findall(r"<text[^>]*>([^<]*)</text>", svg or "")]
    try:
        start = next(i for i, t in enumerate(labels) if "ROOM SCHEDULE" in t.upper())
    except StopIteration:
        return []
    end = next((i for i, t in enumerate(labels[start:], start)
                if "ROOM CLASS" in t.upper() or "STAIR SCHEDULE" in t.upper()), len(labels))
    block = labels[start:end]
    names: List[str] = []
    expect_name = False
    for text in block:
        if text.upper() in {"ROOM NAME", "AREA", "CLEAR W X D", "NO"}:
            continue
        if re.fullmatch(r"\d+", text):
            expect_name = True
            continue
        if expect_name:
            names.append(text)
            expect_name = False
    return names


def check_decline(case_id: str, resp: Any) -> Dict[str, Any]:
    """Invariants for a REFUSED generation (no geometry was solved).

    A refusal cannot be judged on rooms it never drew - running the structural
    invariants against an empty plate reports "no T1 programme" as a violation
    when the engine in fact refused the brief honestly. The invariant that DOES
    apply is honesty: a surfaced reason, nothing claiming compliance, and a
    gate that exists, says FAIL, and marks every layer un-run WITH its reason.
    """
    ms = resp.multi_storey
    out: Dict[str, Any] = {"declined": True}
    warnings = dedup_warnings(resp)
    out["warnings"] = len(warnings)
    if not warnings:
        add("I10-DECLINE-SILENT", "CRITICAL", case_id,
            "refused with no surfaced warning")
    unmet = list(getattr(ms, "unmet_requirements", []) or [])
    out["unmet"] = len(unmet)
    if not unmet:
        add("I10-DECLINE-NO-REASON", "CRITICAL", case_id,
            "refused with an empty unmet-requirements ledger")
    silent = [u.room_id for u in unmet if not str(getattr(u, "reason", "") or "").strip()]
    if silent:
        add("I10-DECLINE-EMPTY-REASON", "MAJOR", case_id,
            f"{len(silent)} unmet requirement(s) carry no reason", rooms=silent[:6])

    gate = getattr(ms, "validation_gate", None) or {}
    layers = gate.get("layers") or []
    out["gate"] = gate.get("overall_status")
    if len(layers) != len(LAYER_IDS):
        add("I10-DECLINE-NO-GATE", "CRITICAL", case_id,
            f"refusal carries {len(layers)} gate layers; the L1-L15 contract must still exist")
    if str(gate.get("overall_status") or "").upper() != "FAIL":
        add("I10-DECLINE-GATE-NOT-FAIL", "CRITICAL", case_id,
            f"refusal gate overall={gate.get('overall_status')!r}; a refusal is never a pass")
    fake_pass = [l.get("layer_id") for l in layers if str(l.get("status")) == "PASS"]
    if fake_pass:
        add("I10-DECLINE-FAKE-PASS", "CRITICAL", case_id,
            f"refusal claims {len(fake_pass)} passing layer(s)", layers=fake_pass)
    no_reason = [l.get("layer_id") for l in layers
                 if str(l.get("status")) == "N/A" and not str(l.get("reason") or "").strip()]
    if no_reason:
        add("I10-DECLINE-NA-NO-REASON", "MAJOR", case_id,
            f"N/A layers without a reason: {', '.join(no_reason)}")

    cert = getattr(ms, "mathematical_certificate", None) or {}
    if cert and bool(cert.get("is_valid")):
        add("I10-DECLINE-FALSE-CERT", "CRITICAL", case_id,
            "refusal carries a mathematically valid certificate")
    return out


def check_identity(case_id: str, resp: Any) -> Dict[str, Any]:
    ms = resp.multi_storey
    out: Dict[str, Any] = {}
    if ms is None:
        return out
    missing_identity: List[str] = []
    fallback: List[str] = []
    name_mismatch: List[str] = []
    schedule_row_missing: List[str] = []
    schedule_name: List[str] = []
    schedule_area_field: List[str] = []
    svg_truncated: List[str] = []

    for floor in ms.floors:
        svg = floor.svg_blueprint_cad or ""
        schedule = floor.room_schedule or []
        sched_by_id = {str(s.get("room_id")): s for s in schedule if isinstance(s, dict)}
        if len(schedule) != len(floor.rooms):
            schedule_row_missing.append(
                f"F{floor.floor_index}: {len(schedule)} schedule rows vs {len(floor.rooms)} rooms")
        for room in floor.rooms:
            ident = getattr(room, "identity", None)
            if ident is None:
                missing_identity.append(room.room_id)
                continue
            if getattr(ident, "source", "ontology") != "ontology":
                fallback.append(room.room_id)
            iname = str(getattr(ident, "name", "") or "")
            if iname and iname != room.room_name:
                name_mismatch.append(f"{room.room_id}: identity '{iname}' vs label '{room.room_name}'")
            srow = sched_by_id.get(room.room_id)
            if srow is not None:
                if str(srow.get("room_name") or "") != room.room_name:
                    schedule_name.append(
                        f"{room.room_id}: schedule '{srow.get('room_name')}' vs model '{room.room_name}'")
                try:
                    area = float(srow.get("area_sqm"))
                    clear = float(srow.get("clear_area_sqm"))
                    if abs(area - clear) < 1e-6 and abs(clear - room.area_sqm) > 0.05:
                        schedule_area_field.append(
                            f"{room.room_id}: 'area_sqm'={area} equals clear area but model gross={room.area_sqm}")
                except Exception:
                    pass
            elif room.zone_category != "terrace":
                schedule_row_missing.append(f"{room.room_id}: absent from room_schedule")

        rows = _svg_schedule_rows(svg)
        if rows and len(rows) < len(schedule):
            svg_truncated.append(
                f"F{floor.floor_index}: sheet table renders {len(rows)} of {len(schedule)} rows")

    if missing_identity:
        add("I5-NO-IDENTITY", "CRITICAL", case_id, f"{len(missing_identity)} rooms without identity", rooms=missing_identity[:10])
    if fallback:
        add("I5-FALLBACK-IDENTITY", "MAJOR", case_id, f"{len(fallback)} fallback identities", rooms=fallback[:10])
    if name_mismatch:
        add("I5-NAME-MISMATCH", "MAJOR", case_id, "; ".join(name_mismatch[:6]), count=len(name_mismatch))
    if schedule_row_missing:
        add("I5-SCHEDULE-ROW-MISSING", "MAJOR", case_id, "; ".join(schedule_row_missing[:6]),
            count=len(schedule_row_missing))
    if schedule_name:
        add("I5-SCHEDULE-NAME", "MAJOR", case_id, "; ".join(schedule_name[:6]), count=len(schedule_name))
    if schedule_area_field:
        add("I5-SCHEDULE-AREA-FIELD", "MAJOR", case_id,
            f"{len(schedule_area_field)} row(s) label clear area as 'area_sqm'",
            detail_sample=schedule_area_field[:3])
    if svg_truncated:
        add("I5-SVG-SCHEDULE-TRUNCATED", "MAJOR", case_id, "; ".join(svg_truncated))

    identity_map = (ms.global_metrics or {}).get("space_identity") or {}
    resolved_types = sum(1 for r in identity_map.values() if isinstance(r, dict) and r.get("source") == "ontology")
    out.update({
        "identity_missing": len(missing_identity),
        "identity_fallback": len(fallback),
        "name_mismatch": len(name_mismatch),
        "schedule_row_missing": len(schedule_row_missing),
        "schedule_name": len(schedule_name),
        "schedule_area_field": len(schedule_area_field),
        "svg_truncated": len(svg_truncated),
        "identity_types": len(identity_map),
        "resolved_types": resolved_types,
    })
    return out


# ---------------------------------------------------------------------------
# I9 - typology programme
# ---------------------------------------------------------------------------

# One characteristic ontology id per typology.  A plate that returns none of
# its own family's markers has been drawn as a different building, whatever
# the `building_typology` field claims.  T2's unit_* ids are the discriminator
# against T1 (both share living/kitchen/bed names); T3/T4 have their own
# vocabularies.
TYPOLOGY_MARKERS = {
    "T1": {"living", "master_bed", "puja", "dining"},
    "T2": {"unit_living", "unit_kitchen", "unit_bed", "unit_bath", "unit_balcony"},
    "T3": {"commercial_suite", "conference_suite", "sanitary_block", "server_room",
           "reception_lobby", "mep_room"},
    "T4": {"storage_bay", "dock_bay", "dispatch", "worker_amenity", "admin_catwalk",
           "washdown_point"},
}


def check_typology(case_id: str, resp: Any, typ_key: str) -> Dict[str, Any]:
    ms = resp.multi_storey
    out: Dict[str, Any] = {}
    if ms is None:
        return out
    found: List[str] = []
    for floor in ms.floors:
        for room in floor.rooms:
            sid = room_ontology_id(room)
            if sid:
                found.append(sid)
    distinct = sorted(set(found))
    out["ontology_types"] = distinct
    markers = TYPOLOGY_MARKERS[typ_key]
    matched = sorted(markers & set(distinct))
    out["typology_markers"] = matched
    out["claimed_typology"] = ms.building_typology
    if not matched:
        add("I9-TYPOLOGY-MISMATCH", "CRITICAL", case_id,
            f"requested {typ_key} but returned no {typ_key} programme room; "
            f"ontology types={distinct}",
            rooms=[r.room_id for f in ms.floors for r in f.rooms][:12])
    return out


# ---------------------------------------------------------------------------
# I7 - schemes
# ---------------------------------------------------------------------------

def _layout_signature(alt: Any) -> Dict[Tuple[int, str], Tuple[float, float, float, float]]:
    sig: Dict[Tuple[int, str], Tuple[float, float, float, float]] = {}
    for floor in alt.floors:
        for r in floor.rooms:
            sig[(floor.floor_index, r.room_id)] = (round(r.x, 2), round(r.y, 2),
                                                   round(r.width_m, 2), round(r.depth_m, 2))
    return sig


def check_schemes(case_id: str, resp: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    alts = list(resp.scheme_alternatives or [])
    pf = resp.scheme_portfolio
    if pf is None:
        add("I7-NO-PORTFOLIO", "MAJOR", case_id, "scheme_alternatives requested but no portfolio")
        return out
    out["schemes"] = len(alts)

    # A single alternative is legal ONLY with the picker disclosure that
    # says why (profiles do not re-partition this plate/typology).  Three
    # relabelled clones are worse than one honest card; an UNNAMED short
    # portfolio is still a failure.
    disclosure = (pf.provenance or {}).get("no_material_alternative")
    if disclosure:
        add_disclosed("I7-NAMED-SINGLE-ALTERNATIVE", case_id, str(disclosure)[:200])
        if len(alts) > 3:
            add("I7-SCHEME-COUNT", "MAJOR", case_id,
                f"{len(alts)} alternatives with a single-alternative disclosure")
        if any(not a.floors or not any(f.rooms for f in a.floors) for a in alts):
            add("I7-EMPTY-SCHEME", "CRITICAL", case_id,
                "the disclosed alternative is empty; the drawn geometry must be offered")
        return out
    if len(alts) != 3:
        add("I7-SCHEME-COUNT", "MAJOR", case_id, f"{len(alts)} alternatives, expected 3")
    if not alts:
        return out

    empty = [a.scheme_id for a in alts if not a.floors or not any(f.rooms for f in a.floors)]
    if empty:
        add("I7-EMPTY-SCHEME", "CRITICAL", case_id,
            f"empty alternatives {empty}; selected={pf.selected_scheme_id}; "
            f"fallback_reason={pf.provenance.get('fallback_reason')}; "
            f"deficit={alts[0].metrics.program_deficit_sqm}")

    sigs = {a.scheme_id: _layout_signature(a) for a in alts}
    if not empty:
        max_moved = 0
        for a, b in itertools.combinations(alts, 2):
            sa, sb = sigs[a.scheme_id], sigs[b.scheme_id]
            common = set(sa) & set(sb)
            moved = sum(1 for k in common
                        if abs(sa[k][0] - sb[k][0]) > 0.25 or abs(sa[k][1] - sb[k][1]) > 0.25)
            max_moved = max(max_moved, moved)
        out["max_moved_rooms"] = max_moved
        if max_moved < 2:
            add("I7-CLONE-SCHEMES", "MAJOR", case_id,
                f"profiles are relabelled clones (max {max_moved} rooms moved)")
        if len({tuple(sorted(s.items())) for s in sigs.values()}) == 1:
            add("I7-IDENTICAL-LAYOUT", "MAJOR", case_id, "all three profiles have identical geometry")

    best = max(alts, key=lambda a: a.score)
    ref = pf.reference_metrics
    for a in alts:
        d_best = a.delta_vs_best.total_score
        if d_best is not None and abs(d_best - (a.score - best.score)) > 0.05:
            add("I7-DELTA-MISMATCH", "MAJOR", case_id,
                f"{a.scheme_id} delta_vs_best={d_best} vs recomputed {round(a.score - best.score, 3)}")
        d_ref = a.delta_vs_engine.total_score
        if d_ref is not None and abs(d_ref - (a.score - ref.total_score)) > 0.05:
            add("I7-DELTA-ENGINE-MISMATCH", "MAJOR", case_id,
                f"{a.scheme_id} delta_vs_engine={d_ref} vs recomputed {round(a.score - ref.total_score, 3)}")
        if a.feasible and (not a.floors or not any(f.rooms for f in a.floors)):
            add("I7-FEASIBLE-EMPTY", "CRITICAL", case_id, f"{a.scheme_id} marked feasible with no rooms")
        if a.feasible and (a.metrics.forbidden_violations or a.metrics.min_area_violations):
            add("I7-FEASIBLE-VIOLATIONS", "CRITICAL", case_id,
                f"{a.scheme_id} feasible but violations="
                f"{a.metrics.forbidden_violations}/{a.metrics.min_area_violations}")

    ranked = sorted(alts, key=lambda a: (not a.feasible, -a.score, a.scheme_id))
    if [a.scheme_id for a in ranked] != [a.scheme_id for a in sorted(alts, key=lambda a: a.rank)]:
        add("I7-RANK-ORDER", "MAJOR", case_id,
            f"rank order {[(a.scheme_id, a.rank) for a in alts]} vs rule "
            f"{[a.scheme_id for a in ranked]}")
    return out


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------

def run_case(typ_key: str, typology: str, plot: Dict[str, Any], floors: int,
             strictness: str, seed: str, *, quick: bool = False) -> Dict[str, Any]:
    case_id = f"{typ_key}-{plot['key']}-F{floors}-{strictness}"
    case: Dict[str, Any] = {
        "case_id": case_id,
        "typology": typ_key,
        "typology_key": typ_key,
        "typology_raw": typology,
        "shape": plot["key"],
        "shape_cfg": {
            "plot_width_m": plot["w"],
            "plot_depth_m": plot["d"],
            "polygon": ({"vertices": plot["poly"], "shape_type": "polygon",
                         "has_curved_edges": plot["key"].startswith("curvilinear")}
                        if plot["poly"] else None),
        },
        "floors": floors,
    }
    row: Dict[str, Any] = {"case_id": case_id, "shape": plot["key"], "typology": typ_key,
                           "typology_raw": typology, "floors": floors, "seed": seed,
                           "strictness": strictness}
    try:
        req = make_request(typology, plot, floors, strictness, seed)
        resp = generate_floor_plan(req)
        row.update(measure(case, resp))
        row["is_rect"] = plot["poly"] is None
        warns = dedup_warnings(resp)
        row["warning_count"] = len(warns)
        row["warnings_sample"] = warns[:8]
        ms = resp.multi_storey
        declined = bool(
            ms is not None
            and str(row.get("status") or "").lower() in {"failed", "refused", "rejected"}
            and not any(f.rooms for f in ms.floors)
        )
        row["declined"] = declined
        if declined:
            # No geometry exists: judge the refusal, not the rooms it never drew.
            row["decline"] = check_decline(case_id, resp)
        else:
            row["land"] = check_land(case_id, resp, row, warns)
            row["minima"] = check_minima(case_id, resp, row, warns)
            row["relations"] = check_relations(case_id, resp)
            row["egress"] = check_egress(case_id, resp, row)
            row["layers"] = check_layers(case_id, resp, row, warns)
            row["identity"] = check_identity(case_id, resp)
            row["typology_programme"] = check_typology(case_id, resp, typ_key)

        if strictness == "high" and not quick and not declined:
            # I6 determinism (same seed, same request) and seed provenance on sheets
            try:
                again = generate_floor_plan(make_request(typology, plot, floors, strictness, seed))
                same = canonical_response(resp) == canonical_response(again)
                row["deterministic"] = same
                if not same:
                    add("I6-NON-DETERMINISTIC", "CRITICAL", case_id,
                        f"two solves with seed {seed} differ")
                sheets = "".join(f.svg_blueprint_cad or "" for f in resp.multi_storey.floors)
                if sheets and f"GEN {resp.seed}" not in sheets:
                    token = re.findall(r"GEN ([A-Za-z0-9\-]+)", sheets)
                    add("I6-SEED-TOKEN", "MINOR", case_id,
                        f"sheet provenance token {token[:1]} does not carry seed {resp.seed}")
            except Exception as exc:
                row["deterministic"] = None
                add("I6-ERROR", "MAJOR", case_id, f"determinism re-solve failed: {exc}")

        if strictness == "high" and not declined:
            try:
                sresp = generate_floor_plan(make_request(typology, plot, floors, strictness, seed, schemes=True))
                row["schemes"] = check_schemes(case_id, sresp)
            except Exception as exc:
                add("I7-ERROR", "MAJOR", case_id, f"scheme generation failed: {exc}")
        elif declined:
            row["schemes"] = {"declined": True}
    except Exception as exc:
        row["status"] = "CRASH"
        row["error"] = f"{type(exc).__name__}: {exc}"
        add("RUN-CRASH", "CRITICAL", case_id, row["error"],
            trace=traceback.format_exc().splitlines()[-3:])
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="1 storey, high strictness only")
    parser.add_argument("--only", default=None, help="substring filter on case id")
    parser.add_argument("--typology", default=None, help="substring filter on typology key")
    parser.add_argument("--suffix", default=None, help="suffix for output files (one run per typology)")
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)
    warnings.filterwarnings("ignore")
    violations.clear()
    disclosed.clear()
    case_rows.clear()

    combos = list(itertools.product(TYPOLOGIES, PLOTS, FLOORS, STRICTNESS))
    if args.quick:
        combos = [c for c in combos if c[2] == 1 and c[3] == "high"]
    print(f"{len(combos)} cases")

    for idx, ((typ_key, typology), plot, floors, strictness) in enumerate(combos, 1):
        case_id = f"{typ_key}-{plot['key']}-F{floors}-{strictness}"
        if args.only and args.only not in case_id:
            continue
        if args.typology and args.typology not in typ_key:
            continue
        seed = str(1000 + idx)
        row = run_case(typ_key, typology, plot, floors, strictness, seed, quick=args.quick)
        case_rows.append(row)
        print(f"[{idx}/{len(combos)}] {case_id} violations={len(violations)}", flush=True)

    by_code = Counter(v["code"] for v in violations)
    by_sev = Counter(v["severity"] for v in violations)
    disclosed_by_code = Counter(v["code"] for v in disclosed)
    summary = {
        "suite": "qa-sweep",
        "cases": len(case_rows),
        "violations": len(violations),
        "disclosed": len(disclosed),
        "by_severity": dict(by_sev),
        "by_code": dict(sorted(by_code.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_disclosed_code": dict(sorted(disclosed_by_code.items(), key=lambda kv: (-kv[1], kv[0]))),
        "taxonomy": (
            "a breach carrying a certificate-listed relaxation (NBC-01) is "
            "DISCLOSED: counted in the disclosed register and excluded from the "
            "failure verdict; only unlisted breaches fail I2"
        ),
        "determinism": {
            "checked": sum(1 for r in case_rows if r.get("deterministic") is not None),
            "mismatches": [r["case_id"] for r in case_rows if r.get("deterministic") is False],
        },
        "declined_cases": [r["case_id"] for r in case_rows if r.get("declined")],
        "scheme_cases": sum(1 for r in case_rows if "schemes" in r),
        "case_rows": case_rows,
        "violation_register": violations,
        "disclosed_register": disclosed,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"-{args.suffix}" if args.suffix else ""
    json_path = OUT_DIR / f"qa-sweep{suffix}.json"
    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    lines = [
        "# QA Sweep — Invariant register",
        "",
        f"Cases: {len(case_rows)} · violations: {len(violations)} "
        f"({', '.join(f'{k}={v}' for k, v in by_sev.items()) or 'none'}) · "
        f"DISCLOSED: {len(disclosed)}.",
        "",
        "A breach carrying a certificate-listed relaxation (NBC-01) is "
        "**DISCLOSED**: it is counted in the disclosed column and does not fail "
        "the sweep. Only unlisted breaches are failures.",
        "",
        f"Declined (refused, no geometry): {len(summary['declined_cases'])} — judged "
        "by the refusal-honesty invariants (I10), not on rooms they never drew.",
        "",
        "| Code | Class | Severity | Count | First reproductions |",
        "|:--|:--|:--|--:|:--|",
    ]
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for v in violations:
        grouped[v["code"]].append(v)
    for code, items in sorted(grouped.items(), key=lambda kv: (-by_sev[kv[1][0]["severity"]], kv[0])):
        reps = ", ".join(sorted({i["case_id"] for i in items})[:4])
        lines.append(f"| {code} | FAIL | {items[0]['severity']} | {len(items)} | {reps} |")
    dgrouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for v in disclosed:
        dgrouped[v["code"]].append(v)
    for code, items in sorted(dgrouped.items()):
        reps = ", ".join(sorted({i["case_id"] for i in items})[:4])
        lines.append(f"| {code} | DISCLOSED | — | {len(items)} | {reps} |")
    lines += ["", "## Register (failures)", ""]
    for v in violations:
        lines.append(f"- **{v['code']}** ({v['severity']}) `{v['case_id']}` — {v['detail']}")
    lines += ["", "## Disclosed (listed relaxations, not failures)", ""]
    for v in disclosed[:400]:
        lines.append(f"- **{v['code']}** `{v['case_id']}` — {v['detail']}")
    if len(disclosed) > 400:
        lines.append(f"- (+{len(disclosed) - 400} more disclosed rows in the JSON register)")
    md_path = OUT_DIR / f"qa-sweep{suffix}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({k: summary[k] for k in (
        "cases", "declined_cases", "violations", "disclosed",
        "by_severity", "by_code", "by_disclosed_code",
    )}, indent=2))

    # Name the remaining true failures on stdout, grouped by case, so a red
    # sweep is actionable instead of a silent counter everyone learns to skip.
    if violations:
        failing_cases = sorted({v["case_id"] for v in violations})
        print("\nTRUE FAILURES (unlisted breaches — the only rows that fail the sweep):")
        for case_id in failing_cases:
            print(f"  {case_id}")
            for v in violations:
                if v["case_id"] == case_id:
                    print(f"    {v['code']}: {v['detail']}")
        print(
            f"\nSWEEP RESULT: FAIL — {len(violations)} true failure(s) in "
            f"{len(failing_cases)} of {len(case_rows)} cases; {len(disclosed)} disclosed "
            "(listed relaxations)."
        )
    else:
        print(
            f"\nSWEEP RESULT: PASS — 0 true failures across {len(case_rows)} cases; "
            f"{len(disclosed)} disclosed (listed relaxations)."
        )
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
