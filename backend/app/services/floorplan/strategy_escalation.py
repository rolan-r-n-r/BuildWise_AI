"""strategy_escalation.py - bounded, deterministic search before a FAIL stamp.

The engine used to disclose a failing partition and stop.  This module tries an
ordered ladder on the SAME request, records every strategy it tried, and returns
the first fully certified plan - or the best measured attempt when none certifies.
It never weakens a gate: a strategy only "succeeds" when the resulting plan's own
verdict is CERTIFIED, with the certificate valid and the validation gate PASS.

Ladder (ordered, at most six solves including S0):

  S0  as-is
  S1  service-row depth variant (T2): kitchens move out of the unit rows
  S2  one-dwelling plate (V2) with the dwelling-count deficit disclosed;
      count-preserving vertical stacking is not implemented
  S3  coverage-headroom trial; the plate is re-measured and no growth is
      claimed when setbacks keep it unchanged
  S4  storey addition inside the engine's 4-storey cap
  S5  not implemented for T2; the chain says why and removes no room

Every tried strategy is public: the chain is attached to the plan, written as a
`STRATEGY-CHAIN` line in the warning ledger (and therefore page 1 of the PDF),
and rendered as a chip by the UI.  A tried-and-failed strategy is evidence, not
an excuse, and never disappears from the chain.
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.floorplan import FloorPlanRequest, FloorPlanResponse
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.plan_verdict import CERTIFIED, FAIL_STAMP, compute_plan_verdict

MAX_SOLVES = 6
CACHE_LIMIT = 48
T2_TYPOLOGY_ALIASES = ("residential_multi", "T2_FAMILY_APARTMENT", "apartment")

# process-local memo: (request hash, strategy id) -> response.  The engine is
# deterministic, so a cached dry-run is the same plan, not an approximation.
_CACHE: "OrderedDict[str, FloorPlanResponse]" = OrderedDict()


# Bump when the cache-key contract changes.  The cache is process-local, so
# this only protects a long-lived worker from mixing an old key shape with a
# new one after a code reload.
CACHE_KEY_VERSION = 2


def _plate_hash(request: FloorPlanRequest) -> str:
    """Canonical identity of the WHOLE request.

    The previous key hashed only the plate and a hand-picked subset of options.
    That let a request with ``units_per_floor=1`` reuse the warmed default
    two-unit plan, and it omitted other response-affecting switches (quality,
    optional layers, design intent, confirmation, environmental inputs).  The
    cached object is a whole ``FloorPlanResponse``, so the key must cover every
    input that can change any part of that response.

    ``model_dump(mode="json", exclude_none=True)`` gives a canonical, JSON-safe
    representation of every field, including nested programme, polygon and
    terrace models.  ``sort_keys`` removes dict insertion-order dependence.
    """
    payload = {
        "cache_key_version": CACHE_KEY_VERSION,
        "request": request.model_dump(mode="json", exclude_none=True),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:20]


def _cached_solve(request: FloorPlanRequest, strategy_id: str) -> FloorPlanResponse:
    key = f"{_plate_hash(request)}|{strategy_id}"
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit.model_copy(deep=True)
    response = generate_floor_plan(request)
    _CACHE[key] = response.model_copy(deep=True)
    while len(_CACHE) > CACHE_LIMIT:
        _CACHE.popitem(last=False)
    return response


def _facts(response: FloorPlanResponse) -> Dict[str, Any]:
    dump = response.model_dump()
    cert = dump.get("mathematical_certificate") or {}
    gate = (response.qa.validation_gate_status if response.qa else None) or ""
    verdict = compute_plan_verdict(dump)
    # A refusal has no geometry to certify.  compute_plan_verdict treats an
    # empty plan as CERTIFIED by design (legacy callers), so the ladder must
    # never read a failed response as a solved one.
    if response.multi_storey is None or response.status == "failed":
        verdict = FAIL_STAMP
    floors = (dump.get("multi_storey") or {}).get("floors") or []
    # A two-storey dwelling exists once, not once per level.  Prefer the
    # explicit ``dwelling_id``; legacy one-level plans have none and keep the
    # (floor, unit_id) grouping that produced the historical count.
    dwellings = {
        str(room.get("dwelling_id"))
        for floor in floors
        for room in (floor.get("rooms") or [])
        if room.get("dwelling_id")
    }
    if not dwellings:
        dwellings = {
            f"{int(floor.get('floor_index') or 0)}:{room.get('unit_id')}"
            for floor in floors
            for room in (floor.get("rooms") or [])
            if room.get("unit_id")
        }
    floor_units = {
        (int(floor.get("floor_index") or 0), str(room.get("unit_id")))
        for floor in floors
        for room in (floor.get("rooms") or [])
        if room.get("unit_id")
    }
    return {
        "verdict": verdict,
        "certificate_valid": bool(cert.get("is_valid")),
        "gate_status": str(gate).upper() or None,
        "warnings": len(dump.get("warnings") or []),
        "failures": len(cert.get("failures") or []),
        "plate_area_m2": _plate_area(dump),
        # A refusal draws nothing, so it has no certificate failures and few
        # warnings: without this fact the best-of metric would rank an empty
        # refusal above a drawn plan that carries real failures.
        "drawn": bool(floors) or bool(dump.get("placements")),
        "floors": int((dump.get("multi_storey") or {}).get("total_storeys") or request_floors(dump) or 1),
        "dwelling_count": len(dwellings),
        "floor_unit_count": len(floor_units),
    }


def _duplex_chain_facts(
    response: FloorPlanResponse,
    baseline: FloorPlanResponse,
    baseline_units: int,
) -> Dict[str, Any]:
    """Deterministic disclosure of what a duplex solve actually drew.

    The entry must describe the transformation, not merely call it "duplex":
    which floors each household owns, which rooms are the internal connection,
    whether the wet/core columns really align, which baseline identities were
    replaced, and the certificate's own failure text when the candidate did not
    pass.  Nothing here is inferred from metadata; every fact is read from the
    drawn rooms, doors and certificate.
    """
    dump = response.model_dump()
    floors = (dump.get("multi_storey") or {}).get("floors") or []
    cert = dump.get("mathematical_certificate") or {}
    dwelling_floors: Dict[str, set] = {}
    stairs: Dict[str, List[Dict[str, Any]]] = {}
    wet_rooms: Dict[tuple, List[tuple]] = {}
    # Principal corridor entrances per dwelling, read from the DRAWN doors.  The
    # entrance room is the dwelling's own hall (row layout) or, in the compact
    # fallback, its unit stair.  Both are private rooms, so a door from either
    # to common circulation is the household's entrance.
    entrance_floors: Dict[str, set] = {}
    core_boxes: set = set()
    core_by_floor: Dict[int, frozenset] = {}
    for floor in floors:
        z = int(floor.get("floor_index") or 0)
        rooms = floor.get("rooms") or []
        by_id = {str(room.get("room_id")): room for room in rooms}
        floor_core: set = set()
        for room in rooms:
            if room.get("is_vertical_core"):
                box = (
                    round(float(room.get("x") or 0.0), 2),
                    round(float(room.get("y") or 0.0), 2),
                    round(float(room.get("width_m") or 0.0), 2),
                    round(float(room.get("depth_m") or 0.0), 2),
                )
                core_boxes.add(box)
                floor_core.add(box)
            did = room.get("dwelling_id")
            if not did:
                continue
            did = str(did)
            dwelling_floors.setdefault(did, set()).add(z)
            sid = room.get("space_type_id")
            if sid == "unit_stair":
                stairs.setdefault(did, []).append({
                    "floor": z,
                    "room_id": room.get("room_id"),
                    "x": room.get("x"),
                    "y": room.get("y"),
                    "width_m": room.get("width_m"),
                    "depth_m": room.get("depth_m"),
                })
            if sid in ("unit_bath", "unit_kitchen"):
                wet_rooms.setdefault((did, sid), []).append((
                    z,
                    round(float(room.get("x") or 0.0), 2),
                    round(float(room.get("y") or 0.0), 2),
                    round(float(room.get("width_m") or 0.0), 2),
                    round(float(room.get("depth_m") or 0.0), 2),
                ))
        core_by_floor[z] = frozenset(floor_core)
        for door in floor.get("doors") or []:
            a = str(door.get("from_room") or "")
            b = str(door.get("to_room") or "")
            for here, other in ((a, b), (b, a)):
                here_room = by_id.get(here)
                other_room = by_id.get(other)
                if (
                    here_room is not None
                    and here_room.get("dwelling_id")
                    and other_room is not None
                    and other_room.get("zone_category") == "circulation"
                    # Common circulation only: the dwelling's own chase/stair
                    # repair door is not a corridor entrance and must never
                    # make an upper level look corridor-accessible.
                    and not other_room.get("dwelling_id")
                ):
                    entrance_floors.setdefault(str(here_room["dwelling_id"]), set()).add(z)
    levels = {
        did: sorted(int(z) for z in zs)
        for did, zs in sorted(dwelling_floors.items())
    }
    connections: List[Dict[str, Any]] = []
    for did in sorted(levels):
        pair = sorted(stairs.get(did, []), key=lambda row: (row["floor"], str(row["room_id"])))
        geometry_aligned = (
            len(pair) == 2
            and (pair[0]["x"], pair[0]["y"], pair[0]["width_m"], pair[0]["depth_m"])
            == (pair[1]["x"], pair[1]["y"], pair[1]["width_m"], pair[1]["depth_m"])
        )
        connections.append({
            "dwelling": did,
            "floors": levels[did],
            "internal_stairs": pair,
            "levels_joined": len(pair) == 2 and pair[1]["floor"] == pair[0]["floor"] + 1,
            "geometry_aligned": geometry_aligned,
            "corridor_access_floors": sorted(entrance_floors.get(did, set())),
        })
    wet_aligned = all(
        len(rows) == 2
        and rows[0][0] + 1 == rows[1][0]
        and rows[0][1:] == rows[1][1:]
        for rows in wet_rooms.values()
    ) if wet_rooms else False
    baseline_units_seen = sorted({
        str(room.get("unit_id"))
        for floor in ((baseline.model_dump().get("multi_storey") or {}).get("floors") or [])
        for room in (floor.get("rooms") or [])
        if room.get("unit_id")
    })
    duplex_units_seen = sorted({
        str(room.get("unit_id"))
        for floor in floors
        for room in (floor.get("rooms") or [])
        if room.get("unit_id")
    })
    level_units_per_floor = [
        len({str(room.get("unit_id")) for room in (floor.get("rooms") or []) if room.get("unit_id")})
        for floor in floors
    ]
    failures = [str(row) for row in (cert.get("failures") or [])]
    snapshot = dump.get("params_snapshot") or {}
    plate_policy = snapshot.get("duplex_layout") or {}
    stair_validation = snapshot.get("duplex_stair_validation") or {}
    # Single-entry is a measured fact: the lower level owns the corridor door
    # and the upper level has none.  A compact or row candidate that still
    # draws an upper corridor door must report dual access, not claim this.
    single_entry = bool(connections) and all(
        row.get("corridor_access_floors") == [min(row.get("floors") or [0])]
        for row in connections
    )
    upper_corridor_doors = sum(
        1
        for floor in floors
        if int(floor.get("floor_index") or 0) % 2 == 1
        for door in (floor.get("doors") or [])
        if (
            "_stair_" in str(door.get("from_room") or "")
            or "_stair_" in str(door.get("to_room") or "")
            or "_hall_" in str(door.get("from_room") or "")
            or "_hall_" in str(door.get("to_room") or "")
        )
        and (
            str(door.get("from_room") or "").startswith("lobby_")
            or str(door.get("from_room") or "").startswith("corridor_")
            or str(door.get("to_room") or "").startswith("lobby_")
            or str(door.get("to_room") or "").startswith("corridor_")
        )
    )
    return {
        "stacking_mode": "duplex",
        "stacking_contract": (
            "Each dwelling_id is one household spanning two consecutive storeys; "
            "dwelling_level names the lower/upper level-unit; the unit_stair pair "
            "at identical coordinates is the internal connection. Four level-units "
            "per plate are four households, not four flats per storey. "
            + (
                "Access is single-entry: the lower level owns the corridor door and "
                "the upper level is reached only through the internal stair."
                if single_entry else
                "Access is dual: both levels have a corridor door; this is disclosed, "
                "not presented as a single-entry dwelling."
            )
        ),
        "layout": plate_policy.get("layout"),
        "plate_policy": plate_policy,
        "stair_validation": stair_validation,
        "entrance_semantics": {
            "mode": "single_entry_duplex" if single_entry else "dual_access",
            "single_entry": single_entry,
            "upper_corridor_doors": upper_corridor_doors,
            "principal_entrance_floors": {
                row["dwelling"]: (row.get("corridor_access_floors") or [None])[0]
                for row in connections
            },
        },
        "dwelling_count_before": baseline_units,
        "dwelling_count_after": len(levels),
        "dwelling_ids": sorted(levels),
        "dwelling_floors": levels,
        "level_units_per_floor": level_units_per_floor,
        "internal_stair_connections": connections,
        "all_levels_joined": bool(connections) and all(c["levels_joined"] for c in connections),
        "wet_columns_aligned": wet_aligned,
        "core_continuity": {
            "aligned": len({value for value in core_by_floor.values()}) == 1,
            "distinct_core_footprints": len(core_boxes),
            "floors_with_identical_core": sorted(
                z for z, value in core_by_floor.items()
                if value == core_by_floor[min(core_by_floor)]
            ) if core_by_floor else [],
        },
        "identity": {
            "baseline_unit_ids": baseline_units_seen,
            "duplex_unit_ids": duplex_units_seen,
            "room_id_convention": "t2_<dwelling>_<space>_F<floor>",
            "dwelling_id_stable_across_levels": all(
                len(levels[did]) == 2 for did in levels
            ),
        },
        "certificate_valid": bool(cert.get("is_valid")),
        "certification_failures": failures,
        "why_not": failures[0] if failures else None,
    }


def request_floors(dump: Dict[str, Any]) -> int:
    return int((dump.get("multi_storey") or {}).get("total_storeys") or 1)


def _plate_area(dump: Dict[str, Any]) -> Optional[float]:
    site = dump.get("site_plan") or {}
    footprint = site.get("footprint") or {}
    if isinstance(footprint.get("area_sqm"), (int, float)):
        return round(float(footprint["area_sqm"]), 2)
    floors = (dump.get("multi_storey") or {}).get("floors") or []
    if floors:
        env = floors[0].get("envelope") or {}
        if isinstance(env.get("area_sqm"), (int, float)):
            return round(float(env["area_sqm"]), 2)
    return None


def _is_fully_certified(facts: Dict[str, Any]) -> bool:
    """A strategy succeeds only when the plan's own certificate says so.

    A WARN gate is not a failure: the calibrated verdict already separates
    listed, within-cap deviations from hard statutory fails, and the
    certificate's own failures list must be empty.  A FAIL gate can never pass.
    """
    return (
        facts["verdict"] == CERTIFIED
        and facts["certificate_valid"]
        and bool(facts.get("drawn"))
        and int(facts.get("failures") or 0) == 0
        and facts["gate_status"] in ("PASS", "WARN")
    )


def _strategy_specs(request: FloorPlanRequest, baseline: FloorPlanResponse) -> List[Dict[str, Any]]:
    """Ordered ladder for this request, with an explicit reason per skip."""
    specs: List[Dict[str, Any]] = []
    typology = str(request.building_typology or "")
    is_t2 = typology in T2_TYPOLOGY_ALIASES
    floors = int(request.floors or 1)
    coverage = float(request.ground_coverage_ratio or 0.60)

    specs.append({
        "id": "S1",
        "label": "service-row depth variant",
        "applicable": (
            is_t2
            and request.partition_variant not in ("service_row", "duplex")
            and request.units_per_floor != 4
        ),
        "patch": {"partition_variant": "service_row"},
        "disclosure": (
            "Move each T2 kitchen into the service strip beside the core so the "
            "bath, living room and bedroom get a legal face instead of a 1.4 m slot."
        ),
        "skip_reason": (
            "no deterministic depth-row variant is declared for this typology"
            if not is_t2
            else (
                "the request selects the duplex variant; the ladder will not "
                "rewrite an explicit variant into a different household layout"
                if request.partition_variant == "duplex"
                else (
                    "the request selects four floor-level units; the service row is a "
                    "two-unit variant, and switching it would change the programme"
                    if request.units_per_floor == 4
                    else "the service-row variant is already selected"
                )
            )
        ),
    })

    # S2: count-preserving two-storey dwellings (V3).  Four floor-level units
    # share the plate and are paired across storeys, so a four-storey building
    # keeps its original eight households instead of trading them for four.
    # The old one-unit V2 plate remains available as an explicit remediation,
    # but it is a dwelling-count change and is no longer the ladder's S2.
    # Applicability is a SITE question, not a property of the two-flat
    # baseline: an 18 x 24 m plot has a 9.88 x 12.42 m two-flat plate, below the
    # old depth floor, yet its 14.4 x 18.1 m buildable can hold the four-row
    # duplex plate.  The estimate below uses the same setback formula the
    # engine applies; the duplex solve still re-measures the real plate and
    # reports a named failure if it cannot fit.
    _plot_w = float(request.plot_width_m or 0.0)
    _plot_d = float(request.plot_depth_m or 0.0)
    _side = max(1.0, min(2.0, _plot_w * 0.10)) if _plot_w > 0 else 0.0
    _front = max(1.8, min(3.5, _plot_d * 0.15)) if _plot_d > 0 else 0.0
    _rear = max(1.2, min(2.5, _plot_d * 0.10)) if _plot_d > 0 else 0.0
    _avail_w = max(0.0, _plot_w - 2.0 * _side)
    _avail_d = max(0.0, _plot_d - _front - _rear)
    _coverage_ceiling = min(_avail_w * _avail_d, _plot_w * _plot_d * coverage)
    _duplex_plate_ok = bool(
        _avail_w >= 9.0
        and _avail_d >= 12.5
        and _coverage_ceiling >= 9.0 * 12.5
    )
    specs.append({
        "id": "S2",
        "label": "count-preserving two-storey dwellings (V3 duplex)",
        "applicable": (
            is_t2
            and request.partition_variant != "duplex"
            and request.units_per_floor != 4
            and floors >= 2
            and floors % 2 == 0
            and _duplex_plate_ok
        ),
        "patch": {"partition_variant": "duplex", "units_per_floor": 4},
        "disclosure": (
            "Solve four floor-level units per plate and pair floors 0/1 (and 2/3 "
            "on a four-storey building) into two-storey dwellings, each joined by "
            "one internal unit stair. The four level-units per floor are household "
            "levels, not four separate households on every floor: the total "
            "dwelling count is preserved, never reduced. Wet rooms keep identical "
            "footprints on both levels so the vertical plumbing stacks remain real."
        ),
        "skip_reason": (
            "the duplex plate is not declared for this typology"
            if not is_t2
            else (
                "a count-preserving duplex needs an even number of storeys (floor pairs)"
                if floors < 2 or floors % 2
                else (
                    "the setback buildable is too small for four household levels "
                    "(the engine needs at least 9.0 x 12.5 m of legal plate)"
                    if not _duplex_plate_ok
                    else "the request already selects the duplex variant"
                )
            )
        ),
    })

    # S3/S4 are declared for the T2 apartment case this ladder was built for.
    # Other typologies keep their existing plate/storey policy until their own
    # variants are pinned; silently growing a T1 house would be a programme
    # change the user did not ask for.
    specs.append({
        "id": "S3",
        # The name is deliberately a trial, not a promise: on a setback-bound
        # plate the coverage input can rise while the feasible plate does not.
        "label": "coverage headroom trial (plate re-measured)",
        "applicable": is_t2 and coverage < 0.70 - 1e-9,
        "patch": {"ground_coverage_ratio": min(0.70, round(coverage + 0.08, 2))},
        "disclosure": (
            f"Attempt raising ground coverage from {coverage * 100:.0f}% to "
            f"{min(0.70, coverage + 0.08) * 100:.0f}%; the feasible plate is "
            "re-measured under setbacks and FAR, and no growth is claimed if "
            "the plate area does not change."
        ),
        "skip_reason": (
            "plate growth is not declared for this typology"
            if not is_t2
            else "no coverage headroom remains below the 70% ceiling"
        ),
    })

    specs.append({
        "id": "S4",
        "label": "storey addition",
        "applicable": is_t2 and floors < 4,
        "patch": {"floors": min(4, floors + 1)},
        "disclosure": f"Add one storey (G+{floors - 1} -> G+{min(4, floors)}).",
        "skip_reason": (
            "storey addition is not declared for this typology"
            if not is_t2
            else "the engine's 4-storey cap is already reached"
        ),
    })

    # S5 is disabled for T2.  The T2 programme resolver does not consume
    # ``required_rooms``, so the old patch named rooms as removed while the
    # geometry still carried the same 30 rooms and 88 warnings.  An advertised
    # strategy that performs no change is worse than a skipped one: the chain
    # now says it is unsupported and why, and no room is claimed removed.
    required = [str(r) for r in (request.required_rooms or [])]
    optional = [
        r for r in required
        if any(
            str(r).lower().startswith(prefix)
            for prefix in ("study", "bed_2", "guest", "puja", "store", "utility", "office")
        )
    ]
    if not required:
        skip_reason = "the request has no explicit required_rooms to trim"
    elif not optional:
        skip_reason = "no declared optional room (study/bed_2/guest/puja/store/utility/office)"
    else:
        skip_reason = (
            "S5 optional-room trimming is not implemented for the T2 partitioner; "
            "no room was removed"
        )
    specs.append({
        "id": "S5",
        "label": "optional-room trim (not implemented for T2)",
        "applicable": False,
        "patch": {},
        "disclosure": (
            "S5 is disabled for T2 until the partitioner can omit a declared "
            "optional room; no room is removed by this strategy."
        ),
        "skip_reason": skip_reason,
    })
    return specs


def solve_with_escalation(request: FloorPlanRequest) -> FloorPlanResponse:
    """Try the ladder, disclose the chain, return the first certified plan.

    S0 is always solved.  A fully certified S0 short-circuits the search, so a
    good plan is never churned.  Otherwise each applicable strategy is solved at
    most once (six solves including S0) and the best measured attempt is kept.
    """
    baseline = _cached_solve(request, "S0")
    baseline_facts = _facts(baseline)
    coverage = float(request.ground_coverage_ratio or 0.60)
    chain: List[Dict[str, Any]] = [{
        "id": "S0",
        "label": "as-is",
        "status": "certified" if _is_fully_certified(baseline_facts) else "fail",
        "disclosure": "The requested plate and programme, solved exactly as supplied.",
        **baseline_facts,
    }]
    attempts: List[Tuple[Dict[str, Any], FloorPlanResponse]] = [(chain[0], baseline)]

    # The ladder's executable S1-S5 variants are T2 apartment strategies.  Other
    # typologies still publish a one-entry chain: a market-mix case must show
    # whether it certified at S0, not hide that fact behind a missing chain.
    if str(request.building_typology or "") not in T2_TYPOLOGY_ALIASES:
        chain_line = f"S0 {chain[0]['status']}"
        if baseline.multi_storey is not None:
            baseline.multi_storey.strategy_chain = chain
            baseline.multi_storey.strategy_chain_line = chain_line
            baseline.multi_storey.strategy_selected = "S0"
        if baseline.params_snapshot is not None:
            baseline.params_snapshot["strategy_chain"] = chain
            baseline.params_snapshot["strategy_selected"] = "S0"
        line = f"STRATEGY-CHAIN: {chain_line}"
        if line not in baseline.warnings:
            baseline.warnings.insert(0, line)
        return baseline

    if not _is_fully_certified(baseline_facts):
        for spec in _strategy_specs(request, baseline):
            if len(chain) >= MAX_SOLVES:
                break
            if not spec["applicable"]:
                chain.append({
                    "id": spec["id"],
                    "label": spec["label"],
                    "status": "skipped",
                    "disclosure": spec["disclosure"],
                    "skip_reason": spec["skip_reason"],
                    "verdict": None,
                    "certificate_valid": None,
                    "gate_status": None,
                    "warnings": None,
                    "failures": None,
                    "plate_area_m2": None,
                    "floors": None,
                })
                continue
            try:
                response = _cached_solve(request.model_copy(update=spec["patch"]), spec["id"])
                facts = _facts(response)
            except Exception as exc:  # noqa: BLE001 - a strategy must not sink the chain
                chain.append({
                    "id": spec["id"],
                    "label": spec["label"],
                    "status": "error",
                    "disclosure": spec["disclosure"],
                    "error": f"{type(exc).__name__}: {exc}"[:240],
                    "verdict": None,
                    "certificate_valid": None,
                    "gate_status": None,
                    "warnings": None,
                    "failures": None,
                    "plate_area_m2": None,
                    "floors": None,
                })
                continue
            status = "certified" if _is_fully_certified(facts) else "fail"
            baseline_units = int(baseline_facts.get("dwelling_count") or 0)
            measured_units = int(facts.get("dwelling_count") or 0)
            if (
                status == "certified"
                and spec["id"] == "S2"
                and baseline_units
                and measured_units != baseline_units
                and not bool(getattr(request, "confirm_dwelling_deficit", False))
            ):
                # Only a strategy that actually changes the household count is
                # confirmation-gated.  The count-preserving duplex path keeps
                # the baseline count, so it is not held behind the deficit gate.
                status = "pending_confirmation"
            entry = {
                "id": spec["id"],
                "label": spec["label"],
                "status": status,
                "disclosure": spec["disclosure"],
                "confirmation_required": status == "pending_confirmation",
                **facts,
            }
            if spec["id"] == "S2" and response.multi_storey is not None:
                entry.update(_duplex_chain_facts(response, baseline, baseline_units))
                if status == "fail":
                    entry["rejection_reason"] = (
                        "the drawn duplex candidate did not certify: "
                        + str(entry.get("why_not") or "see certification_failures")
                    )
            if spec["id"] == "S3":
                base_plate = baseline_facts.get("plate_area_m2")
                trial_plate = facts.get("plate_area_m2")
                if base_plate is not None and trial_plate is not None:
                    delta = round(float(trial_plate) - float(base_plate), 2)
                    entry["plate_delta_m2"] = delta
                    if abs(delta) <= 0.05:
                        entry["no_geometry_change"] = True
                        entry["disclosure"] = (
                            f"Coverage input raised from {coverage * 100:.0f}% to "
                            f"{min(0.70, coverage + 0.08) * 100:.0f}%, but the "
                            f"setback buildable keeps the plate at {float(trial_plate):.1f} m²; "
                            "no plate growth occurred."
                        )
                    else:
                        entry["no_geometry_change"] = False
                else:
                    entry["plate_delta_m2"] = None
            chain.append(entry)
            attempts.append((entry, response))
            if status == "certified":
                break

    certified = [pair for pair in attempts if pair[0].get("status") == "certified"]
    if certified:
        selected_entry, selected = certified[0]
    else:
        # A pending-confirmation strategy is evidence, not the active plan.
        # Best-of runs only over measured, non-pending attempts.
        candidates = [
            pair for pair in attempts
            if pair[0].get("status") in ("fail", "certified")
        ] or attempts
        # Best-of metric: a drawn plan always beats a refusal (an undrawn
        # response has no failures to count, so the raw counters alone would
        # select it), then fewest certificate failures, then fewest warnings,
        # then baseline order (S0 first) as the deterministic tie-break.
        selected_entry, selected = min(
            candidates,
            key=lambda pair: (
                0 if pair[0].get("drawn") else 1,
                int(pair[0].get("failures") or 0),
                int(pair[0].get("warnings") or 0),
            ),
        )

    chain_line = " -> ".join(
        f"{entry['id']} {entry['status']}" for entry in chain
    ) + f"; selected {selected_entry['id']}"
    pending = [entry for entry in chain if entry["status"] == "pending_confirmation"]
    if any(entry["status"] == "certified" for entry in chain):
        chain_line = " -> ".join(
            f"{entry['id']} {entry['status']}" for entry in chain
        )
    elif pending:
        chain_line = " -> ".join(
            f"{entry['id']} {entry['status']}" for entry in chain
        ) + (
            f"; selected {selected_entry['id']} (S2 certified but requires "
            "dwelling-count confirmation; shown as a remediation card)"
        )
    else:
        chain_line += " (no strategy certified; best measured attempt shown)"
    if selected_entry.get("stacking_mode") == "duplex":
        _before = int(selected_entry.get("dwelling_count_before") or 0)
        _after = int(selected_entry.get("dwelling_count_after") or 0)
        _level_units = int(selected_entry.get("floor_unit_count") or 0)
        chain_line += (
            f"; stacking duplex: {_after} dwellings on {_level_units} level-units "
            f"(before {_before}; count {'preserved' if _before == _after else 'changed'})"
        )
    else:
        # A duplex candidate that was measured but not selected is still
        # evidence: publish what it drew (and whether it preserved the count)
        # instead of dropping the only count-preserving attempt from the line.
        _duplex_entries = [e for e in chain if e.get("stacking_mode") == "duplex"]
        if _duplex_entries:
            _d = _duplex_entries[-1]
            _before = int(_d.get("dwelling_count_before") or 0)
            _after = int(_d.get("dwelling_count_after") or 0)
            _level_units = int(_d.get("floor_unit_count") or 0)
            if _after or _level_units:
                chain_line += (
                    f"; {_d['id']} duplex ({_d['status']}): {_after} dwellings on "
                    f"{_level_units} level-units (before {_before}; count "
                    f"{'preserved' if _before == _after else 'changed'})"
                )
    base_units = int(chain[0].get("dwelling_count") or 0)
    selected_units = int(selected_entry.get("dwelling_count") or 0)
    if base_units and selected_units and selected_units != base_units:
        chain_line += (
            f"; dwelling count {base_units} -> {selected_units} "
            f"({selected_units - base_units:+d}, programme change requiring confirmation)"
        )

    # Publish the chain on the plan itself.  It is an engine operation line, so
    # it is part of the warning ledger (and therefore the PDF's page-1 list), but
    # it can never become a hidden fact.
    if selected.multi_storey is not None:
        selected.multi_storey.strategy_chain = chain
        selected.multi_storey.strategy_chain_line = chain_line
        selected.multi_storey.strategy_selected = str(selected_entry["id"])
    if selected.params_snapshot is not None:
        selected.params_snapshot["strategy_chain"] = chain
        selected.params_snapshot["strategy_selected"] = selected_entry["id"]
    line = f"STRATEGY-CHAIN: {chain_line}"
    if line not in selected.warnings:
        selected.warnings.insert(0, line)
    return selected
