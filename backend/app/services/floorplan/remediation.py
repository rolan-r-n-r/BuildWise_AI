"""remediation.py - deterministic options with engine-measured effects.

A NOT-CERTIFIED plan must offer a next step, not just a warning wall. This
module derives at most five options from the plan's own evidence:

  add_storey        floors + 1
  reduce_programme  drop rooms the engine itself named as below minimum
  accept_rotation   adopt a rotation candidate the site solver evaluated
  enlarge_plate     raise the coverage input toward the programme's need
  switch_scheme     choose another feasible profile from the portfolio

Every option is then re-solved by the SAME engine with only that option's
validated input changed. The numbers shown to the reader are the dry-run's, and
applying the option re-runs the same request, so the new certificate is the
predicted one. The AI later words the options; it never adds one or supplies a
number.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.remediation import (
    BaselineFacts,
    MeasuredEffect,
    RemediationIn,
    RemediationOption,
    RemediationOut,
)
from app.services.floorplan.strategy_escalation import solve_with_escalation
from app.services.plan_verdict import compute_plan_verdict

# Rooms a client can give up without breaking circulation or sanitation. The
# engine named them as squeezed; the option offers the least load-bearing ones.
DROPPABLE_BASES = (
    "study",
    "bed_2",
    "guest_bed",
    "master_bed",
    "puja",
    "store",
    "utility",
    "home_office",
    "servant",
    "exercise",
)
FIXED_PREFIXES = (
    "core_",
    "lobby_",
    "link_",
    "corridor",
    "terrace_",
    "balcony",
    "living",
    "kitchen",
    "dining",
    "bath_",
    "ensuite_",
    "powder",
)
COVERAGE_CEILING = 0.70
MAX_DROPPED_ROOMS = 3


def plan_hash(request: FloorPlanRequest, warnings: List[str], verdict: Optional[str]) -> str:
    payload = {
        "request": request.model_dump(mode="json", exclude_none=True),
        "warnings": list(warnings),
        "verdict": verdict,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:20]


def _base_room(room_id: str) -> str:
    head, sep, tail = str(room_id).lower().rpartition("_f")
    return head if sep and tail.isdigit() else str(room_id).lower()


def droppable_rooms(
    warnings: List[str],
    required_rooms: List[str],
    placed_rooms: Optional[List[str]] = None,
) -> List[str]:
    """Rooms the engine named as below minimum that a client may drop."""
    named: List[str] = []
    for warning in warnings:
        if not warning.startswith("ROOM-MIN"):
            continue
        for token in warning.replace(":", " ").replace(",", " ").split():
            if "_F" not in token:
                continue
            room = token.strip(".;()[]'\"")
            head = room.split("_F")[0].lower()
            if not head or any(head.startswith(p) for p in FIXED_PREFIXES):
                continue
            if not any(head.startswith(b) or b.startswith(head) for b in DROPPABLE_BASES):
                continue
            if room not in named:
                named.append(room)
    room_pool = list(required_rooms or [])
    if not room_pool and placed_rooms:
        # No explicit programme in the request: the plan's own rooms are the
        # programme the reduction would revise.
        room_pool = list(dict.fromkeys(placed_rooms))
    if not room_pool:
        return []
    required_rooms = room_pool
    available = {str(r).lower() for r in required_rooms}
    out: List[str] = []
    for room in named:
        base = _base_room(room)
        match = next(
            (r for r in required_rooms if _base_room(str(r)) == base or str(r).lower() == base),
            None,
        )
        if match is None:
            continue
        if str(match).lower() in available:
            out.append(str(match))
            available.discard(str(match).lower())
        if len(out) >= MAX_DROPPED_ROOMS:
            break
    return out


def _rotate_polygon(vertices: List[Tuple[float, float]], angle_deg: float) -> List[List[float]]:
    """Rotate a polygon about its centroid, preserving area and winding."""
    if not vertices:
        return []
    cx = sum(v[0] for v in vertices) / len(vertices)
    cy = sum(v[1] for v in vertices) / len(vertices)
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return [
        [
            round(cx + (x - cx) * cos_a - (y - cy) * sin_a, 3),
            round(cy + (x - cx) * sin_a + (y - cy) * cos_a, 3),
        ]
        for x, y in vertices
    ]


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


def _room_count(dump: Dict[str, Any]) -> int:
    ms = dump.get("multi_storey") or {}
    if ms.get("floors"):
        return sum(len(fl.get("rooms") or []) for fl in ms["floors"])
    return len(dump.get("placements") or [])


def _relaxation_count(dump: Dict[str, Any]) -> int:
    rooms: List[Dict[str, Any]] = []
    ms = dump.get("multi_storey") or {}
    if ms.get("floors"):
        for fl in ms["floors"]:
            rooms.extend(fl.get("rooms") or [])
    else:
        rooms.extend(dump.get("placements") or [])
    return sum(len(r.get("relaxations") or []) for r in rooms)


def _apply_patch(request: FloorPlanRequest, patch: Dict[str, Any]) -> FloorPlanRequest:
    update = dict(patch)
    if "plot_polygon" in update and update["plot_polygon"] is not None:
        from app.schemas.floorplan import PlotPolygonModel

        base = request.plot_polygon
        update["plot_polygon"] = PlotPolygonModel(
            vertices=[tuple(v) for v in update["plot_polygon"]],
            origin_lat=base.origin_lat if base else None,
            origin_lon=base.origin_lon if base else None,
            shape_type=base.shape_type if base else "rectangle",
            has_curved_edges=bool(base.has_curved_edges) if base else False,
            is_regular_rectangle=False,
            area_sqm=base.area_sqm if base else 0.0,
            perimeter_m=base.perimeter_m if base else 0.0,
            bounding_box=base.bounding_box if base else (0.0, 0.0, 0.0, 0.0),
        )
    return request.model_copy(update=update)


def measure(
    request: FloorPlanRequest,
    patch: Dict[str, Any],
    baseline: BaselineFacts,
) -> Tuple[MeasuredEffect, Dict[str, Any]]:
    """Re-solve with the patch and measure what the engine actually produced."""
    started = time.perf_counter()
    patched = _apply_patch(request, patch)
    # The card's dry-run must take the SAME path as Apply: the API runs the
    # strategy ladder, which can select a different step and always publishes
    # the chain line.  Measuring with the bare engine made the card promise 91
    # messages while applying the option returned 92.
    response = solve_with_escalation(patched)
    dump = response.model_dump()
    verdict = compute_plan_verdict(dump)
    cert = dump.get("mathematical_certificate") or {}
    qa = dump.get("qa") or {}
    effects = MeasuredEffect(
        verdict=verdict,
        certificate_valid=bool(cert.get("is_valid")),
        gate_status=qa.get("validation_gate_status"),
        warning_count=len(dump.get("warnings") or []),
        failure_count=len(cert.get("failures") or []),
        relaxation_count=_relaxation_count(dump),
        plate_area_m2=_plate_area(dump),
        rooms_placed=_room_count(dump),
        floors=int((dump.get("multi_storey") or {}).get("total_storeys") or patched.floors or 1),
        status=dump.get("status"),
        delta_warnings=len(dump.get("warnings") or []) - baseline.warning_count,
        delta_failures=len(cert.get("failures") or []) - baseline.failure_count,
        engine_ms=round((time.perf_counter() - started) * 1000.0, 1),
    )
    evidence = {
        "generation_id": dump.get("generation_id"),
        "certificate_id": cert.get("certificate_id"),
        "plan_verdict": verdict,
    }
    return effects, evidence


def build_options(payload: RemediationIn) -> RemediationOut:
    """Derive every applicable option and re-solve each one."""
    request = payload.request
    warnings = list(payload.warnings)
    baseline = payload.baseline
    floors = int(request.floors or 1)
    coverage = float(request.ground_coverage_ratio or 0.60)
    options: List[RemediationOption] = []

    # The engine's own strategies come first: both were already solved by the
    # ladder, so their measured effects are real comparisons, not promises.
    # The currently selected strategy still appears, labelled "current" and
    # blocked in the UI, so the reader can see why it is not offered again.
    is_t2 = str(request.building_typology or "") in (
        "residential_multi", "T2_FAMILY_APARTMENT", "apartment"
    )
    current_variant = getattr(request, "partition_variant", None)
    current_units = getattr(request, "units_per_floor", None)
    # The ladder may have selected S1/S2 on a request that never named the
    # variant, so the plan's own selected strategy is part of "current" too.
    strategy_selected = str(getattr(payload, "strategy_selected", None) or "")
    service_row_current = current_variant == "service_row" or strategy_selected == "S1"
    duplex_current = current_variant == "duplex" or strategy_selected == "S2"
    single_unit_current = current_variant == "single_unit" or current_units == 1
    if is_t2:
        options.append(
            RemediationOption(
                id="service_row",
                title=(
                    "Service-row variant (current)"
                    if service_row_current
                    else "Use the service-row variant"
                ),
                description=(
                    "Move each unit's kitchen into the strip beside the core, so the "
                    "bath, living room and bedroom get a legal face. Two units stay two "
                    "units; only the depth-row split changes."
                ),
                patch={"partition_variant": "service_row", "units_per_floor": 2},
                details={
                    "engine_tried": True,
                    "strategy_id": "S1",
                    "current": service_row_current,
                    "apply_blocked_reason": (
                        "This is already the selected strategy."
                        if service_row_current
                        else None
                    ),
                },
            )
        )
        options.append(
            RemediationOption(
                id="duplex",
                title=(
                    "Two-storey dwellings (current)"
                    if duplex_current
                    else "Use two-storey dwellings (V3)"
                ),
                description=(
                    "Draw four floor-level units per plate and pair the storeys into "
                    "two-storey dwellings joined by internal unit stairs. The "
                    "household count is preserved (eight on a four-storey building), "
                    "not traded for four; wet rooms keep identical footprints so the "
                    "plumbing stacks remain real."
                ),
                patch={"partition_variant": "duplex", "units_per_floor": 4},
                details={
                    "engine_tried": True,
                    "strategy_id": "S2",
                    "requires_confirmation": False,
                    "dwelling_count_change": "preserved",
                    "current": duplex_current,
                    "apply_blocked_reason": (
                        "This is already the selected strategy."
                        if duplex_current
                        else None
                    ),
                },
            )
        )
        options.append(
            RemediationOption(
                id="single_unit",
                title=(
                    "One dwelling per floor (current)"
                    if single_unit_current
                    else "One dwelling per floor (V2)"
                ),
                description=(
                    "Give the dwelling the full south rectangle and keep the core, "
                    "lobby and amenity in the north strip. This is the S2 strategy "
                    "the engine searches when two units cannot both meet their "
                    "catalogue minima; the dwelling count is disclosed, not hidden."
                ),
                patch={
                    "partition_variant": "single_unit",
                    "units_per_floor": 1,
                    # The card's dry-run is the confirmed S2 plan: applying it
                    # is the explicit confirmation, after the UI's dialog.
                    "confirm_dwelling_deficit": True,
                },
                details={
                    "engine_tried": True,
                    "strategy_id": "S2_deficit",
                    "requires_confirmation": True,
                    "dwelling_count_change": "8 -> 4",
                    "current": single_unit_current,
                    "apply_blocked_reason": (
                        "This is already the selected strategy."
                        if single_unit_current
                        else None
                    ),
                },
            )
        )

    if floors < 6:
        options.append(
            RemediationOption(
                id="add_storey",
                title=f"Add a storey (G+{floors - 1} → G+{floors})" if floors > 1 else "Add a storey",
                description=(
                    "Move the squeezed programme onto another level instead of "
                    "compressing it onto this plate."
                ),
                patch={"floors": floors + 1},
            )
        )

    dropped = droppable_rooms(
        warnings,
        list(request.required_rooms or []),
        list(payload.placed_rooms or []),
    )
    if dropped:
        pool = list(request.required_rooms or payload.placed_rooms or [])
        remaining = [r for r in pool if r not in dropped]
        options.append(
            RemediationOption(
                id="reduce_programme",
                title="Reduce programme",
                description=(
                    "Drop the rooms the engine named as below minimum: "
                    + ", ".join(r.replace("_", " ") for r in dropped)
                    + "."
                ),
                patch={"required_rooms": remaining},
                details={"dropped_rooms": dropped, "remaining_rooms": remaining},
            )
        )

    rotation_candidates = [
        alt
        for alt in payload.rotation_alternatives
        if isinstance(alt, dict)
        and isinstance(alt.get("angle_deg"), (int, float))
        and abs(float(alt["angle_deg"])) > 0.01
    ]
    if rotation_candidates and request.plot_polygon and request.plot_polygon.vertices:
        best = min(rotation_candidates, key=lambda a: float(a.get("waste_pct", 100.0)))
        angle = round(float(best["angle_deg"]), 1)
        rotated = _rotate_polygon(
            [tuple(v) for v in request.plot_polygon.vertices],
            angle,
        )
        options.append(
            RemediationOption(
                id="accept_rotation",
                title=f"Accept rotation {angle:g}°",
                description=(
                    f"Rotate the footprint onto the axis the site solver measured: "
                    f"{float(best.get('waste_pct', 0.0)):.1f}% waste instead of the "
                    f"current alignment."
                ),
                patch={"plot_polygon": rotated},
                details={"angle_deg": angle, "waste_pct": best.get("waste_pct")},
            )
        )

    deficit = baseline.failure_count and any(
        w.startswith(("PROGRAMME-SQUEEZE", "PLATE-SHORT")) for w in warnings
    )
    if deficit and coverage < COVERAGE_CEILING:
        raised = min(COVERAGE_CEILING, round(coverage + 0.08, 2))
        options.append(
            RemediationOption(
                id="enlarge_plate",
                title="Enlarge the plate",
                description=(
                    f"Raise ground coverage from {coverage * 100:.0f}% to "
                    f"{raised * 100:.0f}% where setbacks and the site allow it."
                ),
                patch={"ground_coverage_ratio": raised},
                details={"from_coverage": coverage, "to_coverage": raised},
            )
        )

    candidates = [
        alt
        for alt in payload.scheme_alternatives
        if isinstance(alt, dict)
        and alt.get("feasible")
        and alt.get("scheme_id")
        and alt.get("scheme_id") != payload.selected_scheme_id
    ]
    if candidates:
        best_scheme = max(candidates, key=lambda a: float(a.get("score") or 0.0))
        label = str(best_scheme.get("label") or best_scheme.get("profile") or "another profile")
        options.append(
            RemediationOption(
                id="switch_scheme",
                title=f"Switch to {label}",
                description=(
                    "Re-solve the plate with the profile that scored best for this "
                    "programme and site."
                ),
                patch={
                    "selected_scheme_id": best_scheme["scheme_id"],
                    "include_scheme_alternatives": True,
                },
                details={
                    "scheme_id": best_scheme["scheme_id"],
                    "score": best_scheme.get("score"),
                },
            )
        )

    started = time.perf_counter()
    if options:
        with ThreadPoolExecutor(max_workers=min(4, len(options))) as pool:
            futures = [
                pool.submit(measure, request, option.patch, baseline) for option in options
            ]
            for option, future in zip(options, futures):
                try:
                    effect, evidence = future.result()
                    option.effect = effect
                    option.details = {**option.details, **evidence}
                    if option.id == "enlarge_plate" and effect.plate_area_m2:
                        option.title = f"Enlarge the plate to {effect.plate_area_m2:.1f} m²"
                except Exception as exc:  # noqa: BLE001 - one option must not sink the rest
                    option.error = str(exc)[:240]

    # When no validated configuration certifies, every card says so with the
    # best measured numbers instead of implying that Apply will certify it.
    measured = [o for o in options if o.effect is not None]
    any_certified = any(o.effect and o.effect.verdict == "CERTIFIED" for o in measured)
    if measured and not any_certified:
        best = min(
            measured,
            key=lambda o: (
                int(o.effect.failure_count or 0),
                int(o.effect.warning_count or 0),
            ),
        )
        for option in measured:
            option.details["no_certified_configuration"] = True
            option.details["best_option_id"] = best.id
            option.details["configuration_note"] = (
                "No validated configuration certifies this programme on this plate. "
                f"Best measured attempt: {best.id.replace('_', ' ')} - "
                f"{best.effect.failure_count} certificate failure(s), "
                f"{best.effect.warning_count} warning(s), "
                f"gate {best.effect.gate_status or 'unknown'}"
                + (
                    f", plate {best.effect.plate_area_m2:.1f} m2"
                    if best.effect.plate_area_m2
                    else ""
                )
                + ". Applying this card re-certifies the result; it does not promise certification."
            )

    return RemediationOut(
        plan_hash=payload.plan_hash or plan_hash(request, warnings, payload.plan_verdict),
        options=options,
        engine_ms=round((time.perf_counter() - started) * 1000.0, 1),
    )
