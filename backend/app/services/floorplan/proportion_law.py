"""Enforcement of the ontology's proportion and overflow law.

The ontology declares, per space type, a soft ideal band, hard
minimums, a hard planning ceiling, and the *legal moves* when a room exceeds
them (split, adjunct, circulation).  This module is the only place those
declarations are turned into geometry:

* **Hard aspect** -- a room outside ``max_aspect_ratio`` is split along its long
  axis until every part is inside the band.  The band is absolute; no tolerance
  factor is applied and no relaxation is invented.
* **Hard ceiling** -- a room above ``area_ceiling_sqm`` is split into the
  declared ``split_into`` types, or (when the action allows it) surrenders an
  end strip as the declared ``adjunct_kinds`` type.
* **Ideal band** -- a room inside the hard band but outside the ideal band is
  disclosed as WARN: no geometry moves.
* **Minimums** -- rooms below ``min_area_sqm`` / ``min_width_m`` are never
  resized by a split; they are disclosed and left to the certificate.
* **Spine threshold** -- elongated plates must be served by the spine-corridor
  typology (``PROPORTION_POLICY.spine_corridor_aspect_threshold``).

Every move is logged by rule id so the report and the certificate can name it.
A move that cannot be made without breaking another hard band is not made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.schemas.multi_floor_plan import MultiFloorRoomRectangle
from app.services.floorplan.identity import space_type_of
from app.services.floorplan.ontology import (
    ONTOLOGY,
    PROPORTION_POLICY,
    HygieneType,
    OverflowAction,
    SpaceTypeSpec,
)

EPS = 1e-6

# Adjunct kind -> the canonical space type that physically absorbs it.
ADJUNCT_SPACE_TYPE = {
    "wardrobe": "store",
    "ante": "foyer",
    "store": "store",
    "utility": "utility",
}

# Zone -> the report's zone_category bucket.
_ZONE_CATEGORY = {
    "public": "public",
    "private": "private",
    "service": "service",
    "circulation": "circulation",
}

# Space types whose proportion is governed by open-air/strip logic, not room law.
_ASPECT_EXEMPT = {"terrace", "balcony", "unit_balcony", "parking", "garden"}

# A split may leave the host's short side this close to its declared minimum.
# The shortfall is written onto the room's ``relaxations`` and surfaced by the
# certificate's NBC-01 relaxation list - it is never an unrecorded widening.
MIN_DIM_RELAXATION = 0.85

# Nominal wall build-up the certificate's clear-width schedule deducts from a
# gross room face (two half-walls).  A split part must survive that deduction:
# 2.83 m gross became 2.54 m clear and failed the 0.85 x 3.00 m floor by 1 cm.
WALL_DEDUCTION_M = 0.29

# When no legal split/adjunct exists (the plate cannot give the room a wider
# band), an aspect breach up to this factor may be ACCEPTED - but only as a
# room-stamped, certificate-listed relaxation with its measured factor.  The
# cap is the old degraded-plate tolerance (1.30, 1.40 under degradation), now
# auditable per room instead of applied silently by the certificate.  Beyond
# the cap the certificate must fail.
ASPECT_RELAXATION_CAP = 1.40


def _spec_for(room: Any, typology: Optional[str]) -> Optional[SpaceTypeSpec]:
    sid = space_type_of(room, typology)
    return ONTOLOGY.get_space(sid) if sid else None


def _dims(room: Any) -> Tuple[float, float]:
    return max(float(room.width_m), 0.0), max(float(room.depth_m), 0.0)


def _aspect(width: float, depth: float) -> float:
    return max(width, depth) / max(min(width, depth), 0.01)


def spine_corridor_required(envelope_width: float, envelope_depth: float) -> bool:
    """True when the plate is elongated enough to demand a spine corridor.

    The threshold is ontology policy, not a solver constant: a double-loaded
    spine only earns its circulation cost on a plate longer than
    ``spine_corridor_aspect_threshold`` times its depth.
    """
    if envelope_width <= 0.0 or envelope_depth <= 0.0:
        return False
    return _aspect(envelope_width, envelope_depth) > PROPORTION_POLICY.spine_corridor_aspect_threshold + EPS


@dataclass
class ProportionAudit:
    """What the law actually did on one floor."""

    floor_index: int
    splits: int = 0
    adjuncts: int = 0
    ideal_warnings: int = 0
    aspect_relaxations: int = 0
    hard_violations: List[str] = field(default_factory=list)
    spine_selected: bool = False
    log: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "floor_index": self.floor_index,
            "splits": self.splits,
            "adjuncts": self.adjuncts,
            "ideal_warnings": self.ideal_warnings,
            "aspect_relaxations": self.aspect_relaxations,
            "hard_violations": list(self.hard_violations),
            "spine_selected": self.spine_selected,
            "log": list(self.log),
        }


def _fit_parts(
    room: Any,
    parts: int,
    part_types: Sequence[str],
) -> bool:
    """True when ``parts`` strips of the host can all be legal rooms.

    A split is only a repair if every part clears its own type's minimum width
    and area, within the same 0.85 relaxation factor the certificate lists
    explicitly.  Different parts may have different types (a long living room
    may split into living + dining), so each part is measured against ITS
    declared minima, not the host's.
    """
    width, depth = _dims(room)
    along_x = width >= depth
    total = width if along_x else depth
    short_side = depth if along_x else width
    if parts < 2 or len(part_types) < parts:
        return False
    for i in range(parts):
        spec = ONTOLOGY.get_space(part_types[i])
        if spec is None:
            return False
        # Every part must be a legal room in ITS OWN right, within the SAME
        # declared 0.85 relaxation floor the certificate lists explicitly - and
        # inside its own ceiling (a part that is still over the ceiling would
        # immediately need splitting again).  A split that merely trades one
        # illegal proportion for two hard violations is not a repair.
        clear_short = short_side - WALL_DEDUCTION_M
        if clear_short + EPS < float(spec.min_width_m) * MIN_DIM_RELAXATION:
            return False
        part_area = (total / parts) * short_side
        # Area is not relaxed: a 27 m² living split into two 13.6 m² "living"
        # rooms is a downgrade, not a repair.  Only the clear WIDTH may take the
        # declared 0.85 relaxation (a 3.56 m band is 4 cm under 3.60 m).
        if part_area + EPS < float(spec.min_area_sqm):
            return False
        # A ceiling is a planning bound, not a certificate flag: a part up to
        # 1.20x its ceiling stays a disclosed PROP-CEILING overage.  Rejecting
        # every over-ceiling part forced a 38.8 m2 bedroom into THREE 2.83 m
        # wide strips (each legally ceiling-sized, but one below its clear
        # width) when TWO 4.25 m parts were the better repair.
        if spec.area_ceiling_sqm > 0.0 and part_area - EPS > float(spec.area_ceiling_sqm) * 1.20:
            return False
    return True


def _split_type_options(spec: SpaceTypeSpec, parts: int) -> List[List[str]]:
    """Legal part-type sequences for a split, most semantic first.

    The ontology's own ``split_into`` targets come first (a living room
    overflowing its band becomes living + dining/study), then the host type
    repeated (two bedrooms), then every declared target alone.
    """
    # A type may not "split into" itself: repeating the same room adds a wall
    # without changing what the space is, and it made the ladder subdivide its
    # own parts indefinitely.
    targets = [
        t for t in spec.split_into
        if t != spec.id and ONTOLOGY.get_space(t) is not None
    ]
    options: List[List[str]] = []
    if targets:
        options.append([spec.id] + [targets[min(i, len(targets) - 1)] for i in range(parts - 1)])
    return options


def _new_room_id(
    rooms: Sequence[MultiFloorRoomRectangle],
    space_type_id: str,
    floor_index: int,
) -> str:
    """A neutral id for a law-made room.

    Downstream phases resolve service/fixture meaning from the room id, not
    only from ``space_type_id``.  An id like ``t2_unitA_bath_F0_p1`` therefore
    made a carved STORE inherit a bathroom's fixtures.  The new id names the
    new type and nothing else.
    """
    taken = {str(r.room_id) for r in rooms}
    n = 1
    while f"{space_type_id}_{floor_index}_{n}" in taken:
        n += 1
    return f"{space_type_id}_{floor_index}_{n}"


def _new_part(
    host: MultiFloorRoomRectangle,
    *,
    part_index: int,
    x: float,
    y: float,
    width: float,
    depth: float,
    space_type_id: str,
    name: str,
    rule_id: str,
    room_id: str,
) -> MultiFloorRoomRectangle:
    spec = ONTOLOGY.get_space(space_type_id)
    zone = spec.zone.value if spec is not None else "public"
    part = host.model_copy(update={
        "room_id": room_id,
        "room_name": name,
        "x": round(x, 2),
        "y": round(y, 2),
        "width_m": round(width, 2),
        "depth_m": round(depth, 2),
        "area_sqm": round(width * depth, 2),
        "aspect_ratio": round(_aspect(width, depth), 2),
        "space_type_id": space_type_id,
        "identity": None,
        "zone_category": _ZONE_CATEGORY.get(zone, host.zone_category),
        "furniture": [],
        "fixtures": [],
        "relaxations": [],
        "applied_rules": list(host.applied_rules) + [rule_id],
    })
    return part


def _apply_split(
    rooms: List[MultiFloorRoomRectangle],
    index: int,
    host: MultiFloorRoomRectangle,
    parts: int,
    *,
    part_types: Sequence[str],
    rule_id: str,
    audit: ProportionAudit,
    reason: str,
) -> None:
    """Replace ``host`` in place with ``parts`` strips along its long axis."""
    width, depth = _dims(host)
    along_x = width >= depth
    total = width if along_x else depth
    start = host.x if along_x else host.y
    # Split on a 0.01 m grid: part boundaries are rounded, never the part
    # lengths, so the strips tile the host exactly and the plate's outer
    # dimensions cannot drift a centimetre per storey.
    edges = [round(start, 2)]
    for i in range(1, parts):
        edges.append(round(start + total * i / parts, 2))
    edges.append(round(start + total, 2))
    made: List[MultiFloorRoomRectangle] = []
    for i in range(parts):
        length = round(edges[i + 1] - edges[i], 2)
        if length <= 0.05:
            break
        _type = part_types[min(i, len(part_types) - 1)]
        _type_name = ONTOLOGY.get_space(_type).name if ONTOLOGY.get_space(_type) else host.room_name
        if along_x:
            part = _new_part(
                host,
                part_index=i + 1,
                x=edges[i],
                y=host.y,
                width=length,
                depth=depth,
                space_type_id=_type,
                name=_type_name,
                rule_id=rule_id,
                room_id=_new_room_id(rooms + made, _type, int(host.floor_index)),
            )
        else:
            part = _new_part(
                host,
                part_index=i + 1,
                x=host.x,
                y=edges[i],
                width=width,
                depth=length,
                space_type_id=_type,
                name=_type_name,
                rule_id=rule_id,
                room_id=_new_room_id(rooms + made, _type, int(host.floor_index)),
            )
        _part_spec = ONTOLOGY.get_space(part.space_type_id)
        if _part_spec is not None and min(part.width_m, part.depth_m) < float(_part_spec.min_width_m) - 0.01:
            part.relaxations.append({
                "rule_id": "PROP-SPLIT-MIN",
                "rationale": (
                    f"split part short side {min(part.width_m, part.depth_m):.2f} m is below "
                    f"the {float(_part_spec.min_width_m):.2f} m catalogue minimum; listed "
                    "as an explicit relaxation, not applied silently"
                ),
            })
        made.append(part)

    if len(made) < 2:
        return
    # Area must be conserved to the cent: a split is a repartition of the same
    # rectangle, so the parts' rounded areas are balanced against the host's
    # original area instead of drifting a cent per floor (which broke storey
    # equivalence and the terrace-band delta).
    original_area = round(width * depth, 2)
    made[-1].area_sqm = round(original_area - sum(p.area_sqm for p in made[:-1]), 2)
    # The first part keeps the host handle so schedules, doors already keyed on
    # the original id and the programme ledger stay stable.
    first = made[0]
    host.x, host.y = first.x, first.y
    host.width_m, host.depth_m = first.width_m, first.depth_m
    host.area_sqm = first.area_sqm
    host.aspect_ratio = first.aspect_ratio
    host.space_type_id = first.space_type_id
    host.identity = None
    if rule_id not in host.applied_rules:
        host.applied_rules.append(rule_id)
    rooms[index + 1:index + 1] = made[1:]
    audit.splits += 1
    audit.log.append(
        f"PROP-SPLIT: {host.room_id} split into {len(made)} parts ({reason}); "
        f"each part is inside the declared band."
    )


def _apply_adjunct(
    rooms: List[MultiFloorRoomRectangle],
    host: MultiFloorRoomRectangle,
    spec: SpaceTypeSpec,
    *,
    kind: str,
    overage_sqm: float,
    audit: ProportionAudit,
) -> bool:
    """Carve the declared adjunct off the host's long end. True when placed."""
    adjunct_type = ADJUNCT_SPACE_TYPE.get(str(kind))
    adjunct_spec = ONTOLOGY.get_space(adjunct_type) if adjunct_type else None
    if adjunct_spec is None:
        return False
    original_area = round(float(host.area_sqm), 2)
    width, depth = _dims(host)
    along_x = width >= depth
    total = width if along_x else depth
    short_side = depth if along_x else width
    if short_side < max(float(adjunct_spec.min_width_m), float(spec.min_width_m)) - EPS:
        return False
    # Aim at the ceiling overage, never below the adjunct's own minimum, never
    # above its own declared ceiling (a 30 m2 "store" is not an adjunct), and
    # never so deep that the host falls outside its hard aspect band.
    target_area = max(
        min(overage_sqm, float(adjunct_spec.area_ceiling_sqm) or overage_sqm),
        float(adjunct_spec.min_area_sqm),
        1.0,
    )
    strip = min(total - float(spec.min_width_m), target_area / max(short_side, 0.01))
    # A 0.95 m deep "store" is a shelf, not a room: the drawing, furniture and
    # egress phases all treat it as habitable, and a 2.1 x 3.3 m store cannot
    # carry its own name/dims/area label (the sheet falls back to a numbered
    # tag).  Carve only room-scale adjuncts.
    if strip < max(float(adjunct_spec.min_width_m), 2.40) - EPS:
        return False
    host_total = total - strip
    if host_total < float(spec.min_width_m) - EPS:
        return False
    if _aspect(host_total, short_side) > float(spec.max_aspect_ratio) + EPS:
        return False
    if strip * short_side < float(adjunct_spec.min_area_sqm) - EPS:
        return False
    # The adjunct must itself obey its declared hard band.  A 5.4 x 1.4 m
    # "store" is a 3.9:1 strip, not a usable store; carving it would trade a
    # ceiling disclosure for a new aspect violation.
    if _aspect(strip, short_side) > float(adjunct_spec.max_aspect_ratio) + EPS:
        return False

    if along_x:
        adj_x, adj_y = host.x + host_total, host.y
        adj_w, adj_d = strip, depth
        host.width_m = round(host_total, 2)
    else:
        adj_x, adj_y = host.x, host.y + host_total
        adj_w, adj_d = width, strip
        host.depth_m = round(host_total, 2)
    host.area_sqm = round(host.width_m * host.depth_m, 2)
    host.aspect_ratio = round(_aspect(host.width_m, host.depth_m), 2)

    adjunct = _new_part(
        host,
        part_index=1,
        x=adj_x,
        y=adj_y,
        width=adj_w,
        depth=adj_d,
        space_type_id=adjunct_type,
        name=adjunct_spec.name,
        rule_id="PROP-ADJUNCT",
        room_id=_new_room_id(rooms, adjunct_type, int(host.floor_index)),
    )
    # The adjunct is never a second frontage claim: it takes the host's
    # exterior condition, but drops the host's core/unit rules that do not
    # apply to a fitted store.
    adjunct.applied_rules = [r for r in adjunct.applied_rules if "CORE" not in r] + ["PROP-ADJUNCT"]
    # The host shrank by exactly this much: balance the cent so floor area is
    # conserved and the built-up ledger does not drift.
    adjunct.area_sqm = round(original_area - host.area_sqm, 2)
    rooms.append(adjunct)
    audit.adjuncts += 1
    audit.log.append(
        f"PROP-ADJUNCT: {host.room_id} over its {spec.area_ceiling_sqm:.1f} m² ceiling "
        f"by {overage_sqm:.1f} m²; a {adjunct_type} of {adjunct.area_sqm:.1f} m² was fitted "
        "at its end."
    )
    return True


def _enforce_room(
    rooms: List[MultiFloorRoomRectangle],
    index: int,
    typology: Optional[str],
    audit: ProportionAudit,
) -> None:
    room = rooms[index]
    spec = _spec_for(room, typology)
    if spec is None or room.is_vertical_core:
        return
    width, depth = _dims(room)
    if width <= 0.05 or depth <= 0.05:
        return
    aspect = _aspect(width, depth)
    area = width * depth

    # Circulation is the thing that *wires* rooms together; splitting a corridor
    # into two corridors adds a wall and a door and removes no circulation.  Its
    # ceiling is audited, never geometrically split.
    if room.zone_category == "circulation":
        if spec.area_ceiling_sqm > 0.0 and area > float(spec.area_ceiling_sqm) + 0.05:
            audit.log.append(
                f"PROP-CEILING: {room.room_id} is {area:.1f} m² against a "
                f"{float(spec.area_ceiling_sqm):.1f} m² circulation ceiling; circulation "
                "is disclosed, not split into rooms."
            )
        return

    # --- hard minimums: geometry is not resized here, only disclosed --------
    # The certificate's declared relaxation floor is the same MIN_DIM_RELAXATION
    # factor, and a shortfall inside it is stamped as NBC-01 by the certificate
    # pass.  Only a room BELOW that floor is a hard violation here, so the law
    # and the certificate can never disagree about which shortfall is fatal.
    if area < float(spec.min_area_sqm) * MIN_DIM_RELAXATION - 0.05:
        audit.hard_violations.append(
            f"{room.room_id} {area:.2f} m² < {spec.min_area_sqm:.2f} m² minimum"
        )
    if min(width, depth) < float(spec.min_width_m) * MIN_DIM_RELAXATION - 0.02:
        audit.hard_violations.append(
            f"{room.room_id} {min(width, depth):.2f} m clear < {spec.min_width_m:.2f} m minimum"
        )

    # --- hard ceiling: adjunct, else disclose -------------------------------
    # A ceiling overage is a planning maximum, not a certification flag.  The
    # only geometric move worth making is a small declared adjunct at the
    # room's end; subdividing a big room into more big rooms does not bring the
    # ROOM back inside its ceiling, it only adds walls (and its parts inherit
    # the same overage).  Everything else is disclosed.
    ceiling = float(spec.area_ceiling_sqm)
    if ceiling > 0.0 and area > ceiling + 0.05:
        action = spec.overflow_action
        overage = area - ceiling
        if spec.hygiene == HygieneType.FOUL:
            # Sanitary rooms are governed by fixture fit (L3) and wet-stack
            # alignment; carving a store out of a bathroom is not a proportion
            # repair.  Their ceiling is disclosed only.
            audit.log.append(
                f"PROP-CEILING: {room.room_id} is {area:.1f} m² against its "
                f"{ceiling:.1f} m² declared ceiling; sanitary rooms are governed by "
                "fixture fit and are disclosed, not subdivided."
            )
        elif action == OverflowAction.CIRCULATION:
            audit.log.append(
                f"PROP-CEILING: {room.room_id} is {area:.1f} m² against a "
                f"{ceiling:.1f} m² circulation ceiling; circulation is not split into rooms."
            )
        elif action in (OverflowAction.ADJUNCT, OverflowAction.SPLIT_OR_ADJUNCT) and spec.adjunct_kinds:
            for kind in spec.adjunct_kinds:
                if _apply_adjunct(rooms, room, spec, kind=str(kind.value), overage_sqm=overage, audit=audit):
                    return
            audit.log.append(
                f"PROP-CEILING: {room.room_id} is {area:.1f} m² against its "
                f"{ceiling:.1f} m² declared ceiling; no legal adjunct fits this plate, so "
                "the overage is disclosed rather than filled with a non-programme room."
            )
        else:
            # No split (a legal same-type split does not exist) and no adjunct
            # fits.  The plane stays as placed and the overage is disclosed;
            # inventing a room to absorb it would breach the very bands this
            # pass exists to enforce.
            audit.log.append(
                f"PROP-CEILING: {room.room_id} is {area:.1f} m² against its "
                f"{ceiling:.1f} m² declared ceiling; no legal split or adjunct fits "
                "this plate, so the overage is disclosed rather than filled with a "
                "non-programme room."
            )

    # Re-read: a split above replaced this room's geometry.
    room = rooms[index]
    width, depth = _dims(room)
    aspect = _aspect(width, depth)

    # --- hard aspect: split along the long axis ----------------------------
    if spec.id not in _ASPECT_EXEMPT and room.zone_category != "industrial_bay":
        limit = float(spec.max_aspect_ratio)
        if limit > 0.0 and aspect > limit + 0.02:
            needed = int((max(width, depth) / max(min(width, depth), 0.01)) / limit) + 1
            # Sanitary rooms are not split: cutting a 2.3:1 bath into two baths
            # duplicates a wet room, moves the wet/dry wall and - because the
            # split is per floor - puts the upper floor's bath over the bedroom
            # beside the shrunken one (VERT-02).  Their proportion is disclosed
            # and, where the plate allows nothing better, listed as a capped
            # relaxation; the wet stack stays where it was aligned.
            if spec.hygiene != HygieneType.FOUL:
                # `needed` is the MINIMUM parts implied by the band.  Two parts
                # can still be illegal (a 54.8 m2 living split into living +
                # dining gave a 27.4 m2 dining over its 25 m2 ceiling), so try
                # one and two more parts before declaring the room unsplittable.
                # The extra parts also use the declared overflow sequence.
                _split_done = False
                for _parts in range(needed, min(needed + 2, 4) + 1):
                    for types in _split_type_options(spec, _parts):
                        if not _fit_parts(room, _parts, types):
                            continue
                        _apply_split(
                            rooms, index, room, _parts, part_types=types,
                            rule_id="PROP-ASPECT",
                            audit=audit,
                            reason=f"aspect 1:{aspect:.2f} over the 1:{limit:.2f} hard band",
                        )
                        room = rooms[index]
                        width, depth = _dims(room)
                        aspect = _aspect(width, depth)
                        _split_done = True
                        break
                    if _split_done:
                        break
            if aspect > limit + 0.02:
                if aspect <= limit * ASPECT_RELAXATION_CAP + 0.02:
                    factor = aspect / limit
                    room.relaxations.append({
                        "rule_id": "PROP-ASPECT",
                        "rationale": (
                            f"aspect 1:{aspect:.2f} exceeds the 1:{limit:.2f} hard band; accepted "
                            f"at {factor:.2f}x as a listed certificate relaxation because the "
                            "plate cannot give this room a wider band or a legal split"
                        ),
                    })
                    audit.aspect_relaxations += 1
                    audit.log.append(
                        f"PROP-ASPECT: {room.room_id} aspect 1:{aspect:.2f} above the "
                        f"1:{limit:.2f} hard band; accepted at {factor:.2f}x as an explicit "
                        "certificate-listed relaxation (no legal split on this plate)."
                    )
                else:
                    # Beyond the cap is never silently accepted: the cap exists
                    # so a stretched room fails.  But a room that is ALSO below
                    # its catalogue minimum is squeezed by the plate, not by a
                    # layout preference, so the exact reason is stamped on the
                    # room.  It remains a hard violation (the gate FAILs and the
                    # deficit banner names it); the entry makes the breach
                    # individually justified and certificate-visible instead of
                    # a bare number.
                    _squeezed = (
                        area < float(spec.min_area_sqm) - 0.02
                        or min(width, depth) < float(spec.min_width_m) - 0.02
                    )
                    # EVERY beyond-cap room carries its own reason. A squeezed
                    # room (below catalogue minimum) and a stretched one (the
                    # band gave it length instead of width) fail for different
                    # causes; the certificate must name which, never print a
                    # bare ratio. Both remain hard violations.
                    room.relaxations.append({
                        "rule_id": "PROP-PLATE-CAP",
                        "rationale": (
                            (
                                f"aspect 1:{aspect:.2f} is {aspect / max(limit, 0.01):.2f}x the "
                                f"1:{limit:.2f} band, beyond the {ASPECT_RELAXATION_CAP:.2f}x cap, "
                                "and the room is below its catalogue minimum: the plate cannot "
                                "give it a wider band or a legal split. Disclosed as a programme "
                                "deficit, not accepted as compliant."
                            )
                            if _squeezed
                            else (
                                f"aspect 1:{aspect:.2f} is {aspect / max(limit, 0.01):.2f}x the "
                                f"1:{limit:.2f} band, beyond the {ASPECT_RELAXATION_CAP:.2f}x cap: "
                                "the plate's band gives this room length instead of width and no "
                                "legal split or adjunct fits without dropping programme. "
                                "Disclosed as a deficit, not accepted as compliant."
                            )
                        ),
                    })
                    audit.log.append(
                        f"PROP-PLATE-CAP: {room.room_id} aspect 1:{aspect:.2f} beyond the "
                        f"{ASPECT_RELAXATION_CAP:.2f}x cap; justified per room (plate cannot "
                        "host this room within its band) and still disclosed as a deficit."
                    )
                    audit.hard_violations.append(
                        f"{room.room_id} aspect 1:{aspect:.2f} > 1:{limit:.2f} hard band "
                        f"(beyond the {ASPECT_RELAXATION_CAP:.2f}x relaxation cap and cannot split)"
                    )
                return

        # --- soft ideal band: disclose only --------------------------------
        ideal = float(spec.ideal_aspect_max or 0.0)
        if ideal > 0.0 and ideal < aspect <= limit + 0.02:
            audit.ideal_warnings += 1
            audit.log.append(
                f"PROP-IDEAL: {room.room_id} aspect 1:{aspect:.2f} is outside the "
                f"1:{ideal:.2f} ideal band but inside the 1:{limit:.2f} hard band (WARN)."
            )


def enforce_proportion_law(
    rooms: List[MultiFloorRoomRectangle],
    *,
    floor_index: int,
    typology: Optional[str],
    envelope: Optional[Dict[str, float]] = None,
) -> ProportionAudit:
    """Apply the declared band law to one floor's rooms, in place.

    Returns an audit; the caller decides how warnings reach the response.  The
    function never leaves a room outside a hard band *silently*: every
    unresolved case is listed in ``hard_violations``.
    """
    audit = ProportionAudit(floor_index=floor_index)
    if envelope:
        audit.spine_selected = spine_corridor_required(
            float(envelope.get("width", 0.0) or 0.0),
            float(envelope.get("depth", 0.0) or 0.0),
        )
    if audit.spine_selected:
        # The spine threshold selects the spine-corridor TYPOLOGY: on an
        # elongated plate the lobby run is no longer a hall but the double-loaded
        # spine the rest of the plan is served from, and it is named and banded
        # as such.
        spine_spec = ONTOLOGY.get_space("spine_corridor")
        for room in rooms:
            if room.is_vertical_core or room.zone_category != "circulation":
                continue
            if not any(k in str(room.room_id).lower() for k in ("lobby", "corridor", "catwalk")):
                continue
            room.space_type_id = "spine_corridor"
            room.identity = None
            if spine_spec is not None:
                room.applied_rules = [
                    r for r in room.applied_rules if r != "PROP-SPINE-01"
                ] + ["PROP-SPINE-01"]
            audit.log.append(
                f"PROP-SPINE-01: plate exceeds 1:{PROPORTION_POLICY.spine_corridor_aspect_threshold:.2f}; "
                f"{room.room_id} is the double-loaded spine corridor, not a hall."
            )
            break
    # Enforce each room ONCE.  A split inserts its new parts after the host;
    # those parts are already legal by construction (``_fit_parts`` demands it)
    # and re-enforcing them made the ladder subdivide its own output.
    for room in list(rooms):
        index = next((i for i, r in enumerate(rooms) if r is room), None)
        if index is not None:
            _enforce_room(rooms, index, typology, audit)
    return audit


def carve_surplus_upgrade(
    rooms: List[MultiFloorRoomRectangle],
    plate: Any,
    *,
    floor_index: int,
    typology: Optional[str],
) -> List[str]:
    """Route plate surplus into the typology's declared upgrade ladder.

    Surplus that the programme does not use is currently either dead plate or a
    LAND-07 storage hole.  The ontology declares a priority order instead
    (``ONTOLOGY.upgrade_ladder``): spend the surplus on the first step the plate
    can actually host, as a real room with that type's band law.  Nothing is
    carved when no declared step fits, and a step whose target already exists
    up to ``max_count`` is skipped.
    """
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    if plate is None or plate.is_empty or not rooms:
        return []
    # Every placed room — terrace included — is assigned plate, not surplus.
    # Excluding terraces here made the ladder carve a utility room on top of an
    # upper-floor terrace (REL-01 overlap, 6 m² on the L-shape golden case):
    # a terrace is a declared use of the plate even though it is not a host.
    covered = unary_union([
        box(r.x, r.y, r.x + r.width_m, r.y + r.depth_m)
        for r in rooms
    ])
    surplus = plate.difference(covered)
    if surplus.is_empty:
        return []
    pieces = [
        g for g in (surplus.geoms if hasattr(surplus, "geoms") else [surplus])
        if isinstance(g, Polygon) and g.area >= 1.0
    ]
    # Only rectangular-ish pieces can host a rectangular room without guessing.
    pieces = [
        g for g in pieces
        if (g.bounds[2] - g.bounds[0]) * (g.bounds[3] - g.bounds[1]) <= g.area * 1.25
    ]
    # A carved room must have a host: it needs a shared wall long enough for a
    # door into an existing room.  A leftover patch floating inside the plate
    # (e.g. the 0.5 m seam between a wing's rooms) would otherwise become an
    # island room with no door - a ladder upgrade must never create one.
    host_walls = [
        (r, box(r.x, r.y, r.x + r.width_m, r.y + r.depth_m))
        for r in rooms if r.zone_category != "terrace"
    ]

    def _shared_wall_m(piece: Any) -> float:
        # The piece's own edge lying inside a room buffered by 2 cm: abutting
        # rectangles share a segment, while a floating patch never enters one.
        edges = piece.boundary
        return max(
            (edges.intersection(room_box.buffer(0.02)).length for _, room_box in host_walls),
            default=0.0,
        )

    pieces = [g for g in pieces if _shared_wall_m(g) >= 0.90]
    if not pieces:
        return []
    present = [space_type_of(r, typology) for r in rooms]
    steps = surplus_upgrade_candidates(
        typology,
        present_space_types=[p for p in present if p],
        surplus_sqm=max(g.area for g in pieces),
    )
    logs: List[str] = []
    for step in steps:
        if not step.space_type_id:
            continue  # a whole dwelling unit is not a single carved room
        spec = ONTOLOGY.get_space(step.space_type_id)
        if spec is None:
            continue
        for piece in sorted(pieces, key=lambda g: -g.area):
            minx, miny, maxx, maxy = piece.bounds
            avail_w = round(maxx - minx, 2)
            avail_d = round(maxy - miny, 2)
            # A ladder upgrade is a room, not a shelf: a 1.01 m wide "store"
            # carved out of a leftover seam is a sliver with a room label, not
            # a declared upgrade (L-244).  Require room-scale width, not just
            # the type's catalogue minimum.
            if min(avail_w, avail_d) < max(float(spec.min_width_m), 2.00) - 0.02:
                continue
            target_area = min(
                piece.area,
                max(step.min_surplus_sqm, float(spec.min_area_sqm)),
                float(spec.area_ceiling_sqm) if spec.area_ceiling_sqm > 0 else piece.area,
            )
            if target_area < float(spec.min_area_sqm) - 0.02:
                continue
            import math as _math
            limit = max(float(spec.max_aspect_ratio), 1.0)
            # Size the room inside its own hard band, then orient its long side
            # along the longer available run of the surplus piece.
            short_side = max(float(spec.min_width_m), _math.sqrt(target_area / limit))
            long_side = max(short_side, min(limit * short_side, target_area / max(short_side, 0.01)))
            if avail_w >= avail_d:
                width, depth = min(avail_w, long_side), min(avail_d, short_side)
            else:
                width, depth = min(avail_w, short_side), min(avail_d, long_side)
            if _aspect(width, depth) > limit + 0.02:
                continue
            if width * depth < float(spec.min_area_sqm) - 0.02:
                continue
            # The piece may be a ring around the placed rooms: its bounds are
            # not free floor.  The rectangle itself must be inside the free
            # piece and must share a wall with an existing room, or the carve
            # would drop a doorless island on top of a room.
            _rect = box(minx, miny, minx + width, miny + depth)
            if not piece.buffer(1e-6).covers(_rect):
                continue
            if _shared_wall_m(_rect) < 0.90:
                continue
            existing = sum(1 for r in rooms if str(r.room_id).startswith("prop_upgrade_"))
            room = MultiFloorRoomRectangle(
                room_id=f"prop_upgrade_{spec.id}_{floor_index}_{existing + 1}",
                room_name=spec.name,
                floor_index=floor_index,
                x=round(minx, 2),
                y=round(miny, 2),
                width_m=round(width, 2),
                depth_m=round(depth, 2),
                area_sqm=round(width * depth, 2),
                zone="CENTER",
                zone_category=_ZONE_CATEGORY.get(spec.zone.value, "public"),
                vastu_compliant=True,
                is_vertical_core=False,
                requires_exterior_wall=bool(spec.requires_exterior_wall),
                aspect_ratio=round(_aspect(width, depth), 2),
                space_type_id=spec.id,
                applied_rules=["PROP-LADDER-01"],
            )
            rooms.append(room)
            logs.append(
                f"PROP-LADDER: {piece.area:.1f} m² of surplus plate routed to the "
                f"declared '{step.label}' upgrade (priority {step.priority}) as "
                f"{room.room_id} ({room.area_sqm:.1f} m²), instead of dead plate or "
                "an unlabelled storage hole."
            )
            return logs
    return logs


def surplus_upgrade_candidates(
    typology: Optional[str],
    *,
    present_space_types: Iterable[str],
    surplus_sqm: float,
) -> List[Any]:
    """Declared ladder steps that this surplus can afford, in priority order.

    The ladder is data (``ONTOLOGY.upgrade_ladder``); this only filters it by
    the surplus at hand, the per-step count already built, and whether the
    typology's own programme already contains the target.
    """
    present = list(present_space_types)
    if surplus_sqm <= 0.0 or not typology:
        return []
    out: List[Any] = []
    for step in ONTOLOGY.upgrade_ladder(typology):
        if step.min_surplus_sqm > surplus_sqm + EPS:
            continue
        if step.space_type_id and step.space_type_id in present:
            built = sum(1 for p in present if p == step.space_type_id)
            if built >= step.max_count:
                continue
        out.append(step)
    return out
