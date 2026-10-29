"""Deterministic constrained placement solver.

The solver consumes the canonical buildable envelope produced by the existing
``SoleGeometryEngine`` (setbacks, coverage, irregular sites and typology
profiles stay single-sourced).  It replaces heuristic plate partitioning with
an explicit constrained allocation:

1. Expand the typology programme from the ontology catalogue.
2. Union rooms joined by a derived ``MUST_ADJACENT`` rule into blocks.
3. Enumerate front/rear band assignments for those blocks.
4. Find the shallowest deterministic band depth that satisfies every floor's
   width, area, minimum-width and aspect-ratio constraints.
5. Allocate exact widths, place rooms, host doors/windows, and build the
   constructible wall graph.

Hard rules are checked with ``ONTOLOGY.resolve_space_id`` (the exact
normalizer), never with substring guessing.  Rooms that cannot fit are dropped
only with an explicit warning and a recorded area deficit; rooms are never
silently undersized.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.multi_floor_plan import (
    DuctShaftSpec,
    MultiFloorDoorGeometry,
    MultiFloorRoomRectangle,
    MultiFloorWindowGeometry,
    SingleFloorPlanModel,
    VerticalCoreSpec,
)
from app.services.floorplan.furniture import (
    minimum_width_for_set,
    repair_room_envelopes_for_furniture,
)
from app.services.floorplan.living_quality import place_and_audit_furniture_catalog
from app.services.floorplan.ontology import (
    FunctionType,
    ONTOLOGY,
    RelationType,
    SpaceTypeSpec,
    SpaceZone,
)
from app.services.floorplan.svg_generator import generate_multi_floor_blueprint_svg
from app.services.floorplan.wall_graph import build_constructible_wall_graph

EPS = 0.004
MIN_BAND_DEPTH = 2.40
MIN_ROOM_DEPTH = 2.00
CIRCULATION_CLEARANCE = 0.20


@dataclass
class ProgramRoom:
    """One instance of an ontology space in a floor programme."""

    instance_id: str
    spec: SpaceTypeSpec
    unit_id: Optional[str] = None
    display_name: str = ""
    required: bool = False
    essential: bool = False
    priority: int = 5  # lower = more important (kept longer)


@dataclass
class PlateContext:
    request: FloorPlanRequest
    engine: Any
    width: float
    depth: float
    buildable_area: float
    cores: List[VerticalCoreSpec]
    ducts: List[DuctShaftSpec]
    lobby_width: float
    corridor_depth: float
    core_column_width: float

    @property
    def south_width(self) -> float:
        return round(self.width - self.core_column_width - self.lobby_width, 4)


@dataclass
class FloorPlanResult:
    floor_index: int
    floor_name: str
    rooms: List[MultiFloorRoomRectangle] = field(default_factory=list)
    doors: List[MultiFloorDoorGeometry] = field(default_factory=list)
    windows: List[MultiFloorWindowGeometry] = field(default_factory=list)
    assignment: Dict[str, str] = field(default_factory=dict)
    dropped: List[ProgramRoom] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    band_depth: float = 0.0
    south_rooms: List[ProgramRoom] = field(default_factory=list)
    north_rooms: List[ProgramRoom] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. Programme expansion
# ---------------------------------------------------------------------------

_T1_ESSENTIAL = {"living", "kitchen", "dining", "master_bed", "bath_1"}
_T2_ESSENTIAL = {"unit_living", "unit_kitchen", "unit_bed", "unit_bath"}
_T3_ESSENTIAL = {"reception_lobby", "sanitary_block", "commercial_suite"}
_T4_ESSENTIAL = {"dock_bay", "dispatch", "storage_bay", "worker_amenity"}


def _priority(spec: SpaceTypeSpec) -> int:
    if spec.zone == SpaceZone.CIRCULATION:
        return 20
    if spec.hygiene_class.value == "sacred" or spec.function == FunctionType.WORSHIP:
        return 1
    if spec.is_wet:
        return 2
    if spec.function in (FunctionType.SLEEP, FunctionType.COOKING, FunctionType.SANITATION):
        return 3
    if spec.function in (FunctionType.SOCIAL, FunctionType.RECEPTION, FunctionType.WORK):
        return 4
    if spec.function in (FunctionType.STORAGE, FunctionType.TECHNICAL):
        return 4
    if spec.function in (FunctionType.EATING, FunctionType.MEETING):
        return 4
    return 5


def _mk(
    instance_id: str,
    spec: SpaceTypeSpec,
    *,
    unit_id: Optional[str] = None,
    suffix: str = "",
    required_ids: Optional[set] = None,
    essential_ids: Optional[set] = None,
) -> ProgramRoom:
    display = spec.name if not suffix else f"{spec.name} {suffix}".strip()
    req = bool(required_ids and (instance_id in required_ids or spec.id in required_ids))
    essential = bool(essential_ids and spec.id in essential_ids)
    return ProgramRoom(
        instance_id=instance_id,
        spec=spec,
        unit_id=unit_id,
        display_name=display,
        required=req,
        essential=essential,
        priority=_priority(spec),
    )


def expand_program(engine: Any, floor_index: int) -> List[ProgramRoom]:
    """Expand the typology catalogue into concrete floor programme instances."""
    typ = engine.typology
    request: FloorPlanRequest = engine.req
    required_ids = set(request.required_rooms or [])
    cat = ONTOLOGY.get_program_catalog(typ)
    rooms: List[ProgramRoom] = []

    if typ == "T1_SINGLE_FAMILY":
        specs = engine._resolve_floor_program(floor_index, request.required_rooms)
        for spec in specs:
            if spec.zone == SpaceZone.CIRCULATION:
                continue  # solver places its own lobby/corridor spine
            rooms.append(_mk(spec.id, spec, required_ids=required_ids, essential_ids=_T1_ESSENTIAL))
        return rooms

    if typ == "T2_FAMILY_APARTMENT":
        unit_specs = cat.unit.room_ids if cat.unit else []
        for letter in ("A", "B"):
            unit_id = f"U{letter}"
            for sid in unit_specs:
                spec = ONTOLOGY.get_space(sid)
                if not spec:
                    continue
                leaf = sid[5:] if sid.startswith("unit_") else sid
                instance = f"t2_unit{letter}_{leaf}"
                rooms.append(_mk(
                    instance, spec, unit_id=unit_id, suffix=f"Unit {letter}",
                    required_ids=required_ids,
                    essential_ids=_T2_ESSENTIAL,
                ))
        if floor_index == 0:
            guard = ONTOLOGY.get_space("guard_house")
            if guard:
                rooms.append(_mk("guard_house", guard, required_ids=required_ids))
        return rooms

    if typ == "T3_LARGE_COMPLEX":
        if floor_index == 0:
            ids = ["reception_lobby", "visitor_lounge", "conference_room",
                   "sanitary_block", "server_room", "electrical_room"]
            for sid in ids:
                spec = ONTOLOGY.get_space(sid)
                if spec:
                    rooms.append(_mk(sid, spec, required_ids=required_ids, essential_ids=_T3_ESSENTIAL))
        else:
            for letter in ("N", "E", "S"):
                for sid, label in (("commercial_suite", "Office Suite"), ("conference_suite", "Conference Suite")):
                    spec = ONTOLOGY.get_space(sid)
                    if not spec:
                        continue
                    instance = f"t3_suite_{letter.lower()}" if sid == "commercial_suite" else f"t3_conf_{letter.lower()}"
                    rooms.append(_mk(
                        instance, spec, unit_id=f"S{letter}", suffix=f"{label} {letter}",
                        required_ids=required_ids,
                        essential_ids=_T3_ESSENTIAL if sid == "commercial_suite" else None,
                    ))
            for sid in ("sanitary_block", "pantry"):
                spec = ONTOLOGY.get_space(sid)
                if spec:
                    rooms.append(_mk(sid, spec, required_ids=required_ids, essential_ids=_T3_ESSENTIAL))
        return rooms

    # T4 warehouse
    if floor_index == 0:
        for sid in ("dock_bay", "dispatch", "storage_bay", "worker_amenity",
                    "washdown_point", "guard_house"):
            spec = ONTOLOGY.get_space(sid)
            if spec:
                rooms.append(_mk(f"t4_{sid}", spec, required_ids=required_ids, essential_ids=_T4_ESSENTIAL))
    else:
        for sid in ("admin_office", "conf_room"):
            spec = ONTOLOGY.get_space(sid)
            if spec:
                rooms.append(_mk(f"t4_{sid}", spec, required_ids=required_ids))
    return rooms


# ---------------------------------------------------------------------------
# 2. Relation helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8192)
def _rules_for_ids(a_id: str, b_id: str):
    return tuple(ONTOLOGY.get_relations(a_id, b_id))


def _rel_rules(a: ProgramRoom, b: ProgramRoom):
    return _rules_for_ids(a.spec.id, b.spec.id)


def _must_components(rooms: Sequence[ProgramRoom]) -> List[List[ProgramRoom]]:
    parent = list(range(len(rooms)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if any(r.relation == RelationType.MUST_ADJACENT for r in _rel_rules(rooms[i], rooms[j])):
                union(i, j)

    groups: Dict[int, List[ProgramRoom]] = {}
    for i, room in enumerate(rooms):
        groups.setdefault(find(i), []).append(room)
    return [groups[k] for k in sorted(groups)]


def _south_affinity(block: Sequence[ProgramRoom], profile_id: str = "max_area") -> float:
    score = 0.0
    for room in block:
        spec = room.spec
        if spec.id in {"dock_bay", "dispatch", "guard_house", "foyer"}:
            score += 2.0
        if spec.zone == SpaceZone.PUBLIC:
            score += 1.5
        if spec.id in {"living", "dining", "kitchen", "unit_living", "unit_kitchen",
                       "reception_lobby", "visitor_lounge"}:
            score += 1.0
        if spec.zone in (SpaceZone.PRIVATE, SpaceZone.SERVICE):
            score -= 1.0
        if spec.id == "storage_bay":
            score -= 2.0
        if profile_id == "max_vastu":
            # Front band gets south exposure, rear band north exposure.  Let the
            # declared Vastu weights decide instead of a generic public/private split.
            south_w = float(spec.vastu_zone_weights.get("S", 0.0))
            north_w = float(spec.vastu_zone_weights.get("N", 0.0))
            score += 1.8 * (south_w - north_w)
            if spec.hygiene_class.value == "sacred":
                score -= 0.6  # puja prefers the north-east, i.e. the rear band's west end
        elif profile_id == "max_light_vent":
            # Daylight-led: put rooms that explicitly need daylight on the front
            # (south) side where the sun patch is deepest, but keep wet rooms
            # clustered for the plumbing stack.
            if spec.daylight_req and not spec.is_wet:
                score += 0.6
            if spec.is_wet:
                score -= 0.2
    return score


def _touching(a: MultiFloorRoomRectangle, b: MultiFloorRoomRectangle) -> Tuple[bool, float]:
    x_overlap = min(a.x + a.width_m, b.x + b.width_m) - max(a.x, b.x)
    y_overlap = min(a.y + a.depth_m, b.y + b.depth_m) - max(a.y, b.y)
    if x_overlap > -EPS and y_overlap > -EPS:
        # Shared wall: one axis overlap is (near) zero and the other positive.
        if abs(x_overlap) <= 0.05 and y_overlap > 0.10:
            return True, float(y_overlap)
        if abs(y_overlap) <= 0.05 and x_overlap > 0.10:
            return True, float(x_overlap)
    return False, 0.0


def _forbidden_pairs(rooms: Sequence[ProgramRoom]) -> set:
    out = set()
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if any(r.relation == RelationType.FORBIDDEN_WALL for r in _rel_rules(rooms[i], rooms[j])):
                out.add((rooms[i].instance_id, rooms[j].instance_id))
                out.add((rooms[j].instance_id, rooms[i].instance_id))
    return out


# ---------------------------------------------------------------------------
# 3. Plate context and band search
# ---------------------------------------------------------------------------

def build_plate_context(engine: Any, envelope: Optional[Dict[str, Any]] = None) -> Optional[PlateContext]:
    """Return a rectangular plate context, or None when RULE-FP geometry is needed.

    ``envelope`` lets a caller that has already computed the envelope (the
    engine's own solve, when a scheme profile is selected) reuse it instead of
    recomputing solver state.
    """
    request: FloorPlanRequest = engine.req
    if envelope is None:
        ok, _deg, envelope, _warnings = engine._compute_envelope()
        if not ok:
            return None
    # Multi-wing and terrace-band plates keep the fully validated RULE-FP path.
    site_plan = engine.site_plan
    if site_plan is not None:
        footprint = getattr(site_plan, "footprint", None)
        if footprint is not None and len(getattr(footprint, "wings", []) or []) > 1:
            return None
    if getattr(request, "terrace_bands", None):
        return None
    masks = getattr(request, "floor_plate_masks", None)
    if masks:
        # A mask that is 'present' everywhere does not change the plate: it is
        # the full envelope, which the band solver partitions. Treating ANY
        # mask as unsupported meant every captured (map) boundary silently fell
        # back to RULE-FP and the picker could never apply a profile there.
        carved = any(
            str(value).strip().lower() not in ("present", "none", "")
            for per_floor in masks.values()
            if isinstance(per_floor, dict)
            for value in per_floor.values()
        )
        if carved:
            return None

    width = float(envelope["width"])
    depth = float(envelope["depth"])
    if width < 5.0 or depth < 6.0:
        return None

    cores, ducts = engine._lock_vertical_anchors(envelope)
    if not cores:
        return None
    core_column = round(sum(float(c.width_m) for c in cores), 4)
    lobby_width = round(min(2.40, max(1.50, width * 0.16)), 2)
    if core_column + lobby_width >= width - 1.80:
        return None
    corridor_depth = round(
        max(1.10, min(1.50, float(engine.profile.egress_constants.get("min_corridor_width_m", 1.20)))),
        2,
    )
    buildable = float(getattr(site_plan, "buildable_area_sqm", 0.0) or 0.0)
    if buildable <= 0.0:
        buildable = width * depth
    return PlateContext(
        request=request,
        engine=engine,
        width=width,
        depth=depth,
        buildable_area=buildable,
        cores=cores,
        ducts=ducts,
        lobby_width=lobby_width,
        corridor_depth=corridor_depth,
        core_column_width=core_column,
    )


@lru_cache(maxsize=16384)
def _required_width_cached(spec_id: str, depth: float) -> float:
    spec = ONTOLOGY.get_space(spec_id)
    if spec is None or depth <= 0.05:
        return float("inf")
    required = max(float(spec.min_width_m), float(spec.min_area_sqm) / depth)
    # The allocation floor includes the actual furniture set at this
    # depth, not just the statutory empty-room minimum.  ``None`` means the set
    # cannot fit even on an arbitrarily wide room, so the depth is infeasible.
    items = tuple(spec.furniture_set or ())
    if items:
        furniture_width = minimum_width_for_set(items, round(float(depth), 2))
        if furniture_width is None:
            return float("inf")
        required = max(required, furniture_width)
    return round(required + 0.01, 4)


@lru_cache(maxsize=65536)
def _required_width_for_spec(spec_id: str, depth: float) -> float:
    """Memoised ``_required_width`` body: it is a function of spec and depth only.

    The band search asks for the same room's frontage floor at the same depth
    thousands of times (every candidate split re-measures the whole programme),
    so this cache is what makes the enumeration affordable.  It is keyed on the
    exact depth because the aspect term is a straight line in depth.
    """
    spec = ONTOLOGY.get_space(spec_id)
    if spec is None:
        return float("inf")
    base = _required_width_cached(spec_id, round(float(depth), 3))
    if base == float("inf"):
        return base
    limit = float(getattr(spec, "max_aspect_ratio", 0.0) or 0.0)
    if limit <= 0.0 or depth <= 0.05:
        return base
    proportional = depth / limit
    if proportional * depth <= float(spec.min_area_sqm) * 3.0:
        base = max(base, round(proportional + 0.01, 4))
    return base


def _required_width(room: ProgramRoom, depth: float) -> float:
    """Hard width floor: minimum width, minimum area, and proportion.

    Aspect is folded in only where it can be satisfied *inside* the room's
    comfort envelope (``depth / limit`` must not inflate the room past three
    times its catalogue area).  A 3.5 m² bath in a 3.3 m band needs 1.67 m of
    frontage to stay inside 1:2.0 - that is a real requirement and was the
    reason 1:2.17 baths kept appearing on otherwise generous plates.  In a
    10.9 m band the same rule would demand 5.5 m of frontage and 59 m², which is
    not a repair; there the band depth is the defect and ``ROOM-MAX`` discloses
    it instead.
    """
    return _required_width_for_spec(room.spec.id, float(depth))


def _block_width(block: Sequence[ProgramRoom], depth: float) -> float:
    return sum(_required_width(r, depth) for r in block)


def _block_capacity(block: Sequence[ProgramRoom], depth: float) -> float:
    """``_band_capacity`` of a single block: the frontage its rooms can fill."""
    total = 0.0
    for room in block:
        ceiling = _aspect_ceiling(room, depth)
        if ceiling == float("inf"):
            return float("inf")
        total += ceiling
    return total


def _blocks_fit(blocks: Sequence[List[ProgramRoom]], depth: float, available: float) -> bool:
    return _block_width([r for b in blocks for r in b], depth) <= available + EPS


def _forbidden_free_order(blocks: Sequence[List[ProgramRoom]]) -> Optional[List[List[ProgramRoom]]]:
    """Backtracking order with no forbidden block boundary (deterministic)."""
    n = len(blocks)
    if n == 0:
        return []
    bad = [[False] * n for _ in range(n)]
    has_forbidden = False
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            for ra in (blocks[i][-1],):
                for rb in (blocks[j][0],):
                    if any(r.relation == RelationType.FORBIDDEN_WALL for r in _rel_rules(ra, rb)):
                        bad[i][j] = True
                        has_forbidden = True
    if not has_forbidden:
        return [list(b) for b in blocks]

    order: List[int] = []
    used = [False] * n
    failed = set()

    def dfs(last: int) -> bool:
        if len(order) == n:
            return True
        key = (last, tuple(i for i in range(n) if not used[i]))
        if key in failed:
            return False
        for i in range(n):
            if used[i]:
                continue
            if last >= 0 and bad[last][i]:
                continue
            used[i] = True
            order.append(i)
            if dfs(i):
                return True
            order.pop()
            used[i] = False
        failed.add(key)
        return False

    if dfs(-1):
        return [list(blocks[i]) for i in order]
    return None


def _forbidden_free_order_exists(blocks: Sequence[List[ProgramRoom]]) -> bool:
    return _forbidden_free_order(blocks) is not None


def _band_capacity(blocks: Sequence[Sequence[ProgramRoom]], depth: float) -> float:
    """Frontage a band's programme can legitimately occupy at this depth.

    The sum of each room's aspect ceiling: beyond it, extra frontage would make
    the rooms disproportionate.  ``inf`` means at least one space carries no
    proportion bound (circulation, industrial bays), so the band can always be
    filled.
    """
    total = 0.0
    for block in blocks:
        for room in block:
            ceiling = _aspect_ceiling(room, depth)
            if ceiling == float("inf"):
                return float("inf")
            total += ceiling
    return total


def _band_assignment(
    ctx: PlateContext,
    blocks: Sequence[List[ProgramRoom]],
    band_depth: float,
    profile_id: str = "max_area",
) -> Optional[Tuple[set, set]]:
    """Choose the best front/rear split at a fixed band depth.

    A split is legal when both bands can physically hold their blocks (minimum
    width / area / furniture) *and* their frontage is within what those rooms
    can occupy in proportion.  Without the second test a wide plate could park a
    lone bathroom in an 18.7 m band and stretch it to 102 m² (audit: 1:4.8
    rooms).  Splits that cannot fill a band proportionally are still offered as
    a ranked fallback so the solver always returns geometry — the caller sees
    the overrun as a violation instead of an exception.
    """
    n = len(blocks)
    if n > 14:
        return None
    south_avail = ctx.south_width
    north_depth = ctx.depth - band_depth - ctx.corridor_depth
    north_avail = ctx.width
    if north_depth < MIN_ROOM_DEPTH:
        # Deep single-loaded plate: only the all-front assignment is legal.
        if _blocks_fit(blocks, band_depth, south_avail):
            return set(range(n)), set()
        return None
    # SUBSUBSET SUMS, NOT RE-MEASURED BLOCKS.  The enumeration below visits 2^n
    # splits per floor per depth and there are ~450 depth/floor evaluations in a
    # scan, so measuring each candidate band from scratch (the old `_blocks_fit`
    # per split) made a 14-room, 3-storey programme take ~15 s per profile.  Both
    # fit tests are sums over the blocks in a band, so they can be accumulated
    # once per mask with a low-bit step: identical predicates, identical
    # arithmetic, ~100x less work.
    south_w = [_block_width(block, band_depth) for block in blocks]
    north_w = [_block_width(block, north_depth) for block in blocks]
    south_cap = [_block_capacity(block, band_depth) for block in blocks]
    north_cap = [_block_capacity(block, north_depth) for block in blocks]
    south_aff = [_south_affinity(block, profile_id) for block in blocks]

    size = 1 << n
    sum_south_w = [0.0] * size
    sum_north_w = [0.0] * size
    sum_south_cap = [0.0] * size
    sum_north_cap = [0.0] * size
    sum_south_aff = [0.0] * size
    for mask in range(1, size):
        # Strip the HIGHEST set bit, so each mask accumulates its blocks in
        # ascending index order - the same left-to-right order the previous
        # per-candidate `sum(...)` used, and therefore the same float rounding.
        bit = mask.bit_length() - 1
        prev = mask ^ (1 << bit)
        sum_south_w[mask] = sum_south_w[prev] + south_w[bit]
        sum_north_w[mask] = sum_north_w[prev] + north_w[bit]
        sum_south_cap[mask] = sum_south_cap[prev] + south_cap[bit]
        sum_north_cap[mask] = sum_north_cap[prev] + north_cap[bit]
        sum_south_aff[mask] = sum_south_aff[prev] + south_aff[bit]

    candidates = []
    full = size - 1
    for north_mask in range(size):
        # Bit set = rear band, exactly as the old product((0, 1), repeat=n).
        south_mask = full ^ north_mask
        # At least one block must remain in the front band for the entry sequence.
        if south_mask == 0:
            continue
        if sum_south_w[south_mask] > south_avail + EPS:
            continue
        if sum_north_w[north_mask] > north_avail + EPS:
            continue
        score = sum_south_aff[south_mask]
        shortfall = max(0.0, south_avail - sum_south_cap[south_mask])
        shortfall += max(0.0, north_avail - sum_north_cap[north_mask])
        south_list = [i for i in range(n) if not (north_mask >> i) & 1]
        south_set = set(south_list)
        north_set = set(range(n)) - south_set
        candidates.append((round(shortfall, 2), score, tuple(south_list), south_set, north_set))

    # Proportion-filling splits first, then highest preference, then a
    # deterministic block-order tie break.  Only the best candidates need the
    # (more expensive) ordering feasibility test.
    candidates.sort(key=lambda item: (item[0], -item[1], item[2]))
    for _shortfall, _score, _key, south_set, north_set in candidates:
        south_blocks = [blocks[i] for i in sorted(south_set)]
        north_blocks = [blocks[i] for i in sorted(north_set)]
        if _forbidden_free_order_exists(south_blocks) and _forbidden_free_order_exists(north_blocks):
            return south_set, north_set
    return None


def _all_floor_proportion_cost(
    ctx: PlateContext,
    blocks_by_floor: Dict[int, List[List[ProgramRoom]]],
    assignments: Dict[int, Tuple[set, set]],
    depth: float,
    area_bias: Dict[str, float],
) -> Tuple[int, float]:
    """Sum ``_band_proportion_cost`` over every storey at one band depth."""
    violations = 0
    overflow = 0.0
    for z in sorted(blocks_by_floor):
        south_idx, north_idx = assignments[z]
        v, o = _band_proportion_cost(
            ctx, blocks_by_floor[z], south_idx, north_idx, depth, area_bias,
        )
        violations += v
        overflow += o
    return violations, round(overflow, 2)


def _band_proportion_cost(
    ctx: PlateContext,
    blocks: Sequence[List[ProgramRoom]],
    south_idx: set,
    north_idx: set,
    depth: float,
    area_bias: Dict[str, float],
) -> Tuple[int, float]:
    """How many rooms a proportional allocation cannot fit at this band depth.

    Counted per band before any ordering is chosen: frontage allocation depends
    on the room set and its ceilings, not on the left-to-right order, so this is
    a cheap proxy for the geometry ``_local_bands`` will build.
    """
    violations = 0
    overflow = 0.0
    rear_depth = round(ctx.depth - depth - ctx.corridor_depth, 4)
    for idx, band_depth_, available in (
        (sorted(south_idx), depth, ctx.south_width),
        (sorted(north_idx), rear_depth, ctx.width),
    ):
        rooms = [r for i in idx for r in blocks[i]]
        if not rooms or band_depth_ < MIN_ROOM_DEPTH:
            continue
        widths, over_cap = _band_allocation(rooms, available, band_depth_, area_bias)
        if widths is None:
            return violations + len(rooms), 1e6
        violations += len(over_cap)
        # A band shallower than a room's declared minimum clear width cannot
        # hold that room in ANY proportion: the depth is the short side.  Count
        # it like an aspect breach so the depth search walks past it instead of
        # Accepting a 2.8 m deep living room with 3.6 m minimum.
        for room in rooms:
            min_clear = float(getattr(room.spec, "min_width_m", 0.0) or 0.0)
            if min_clear > 0.0 and band_depth_ + 0.02 < min_clear:
                violations += 1
        # A deep band can also break proportion the other way: a 1.2 m wide bath
        # in a 10.7 m band is 1:8.9 even though its frontage was never capped.
        for room in rooms:
            limit = float(getattr(room.spec, "max_aspect_ratio", 0.0) or 0.0)
            if limit <= 0.0:
                continue
            width = widths[room.instance_id]
            if width <= 0.05:
                continue
            if max(band_depth_ / width, width / band_depth_) > limit + 0.02:
                violations += 1
        overflow += max(0.0, available - sum(widths.values()))
    return violations, round(overflow, 2)


def _search_band_layout(
    ctx: PlateContext,
    floors: Dict[int, List[ProgramRoom]],
    profile_id: str = "max_area",
) -> Tuple[Optional[float], Dict[int, Tuple[set, set]], Dict[int, List[ProgramRoom]], List[ProgramRoom]]:
    """Find the shallowest band depth feasible for every floor.

    Returns (band_depth, assignment_by_floor, rooms_by_floor, dropped_rooms).
    """
    working = {z: list(rooms) for z, rooms in floors.items()}
    dropped: List[ProgramRoom] = []
    core_min = max(float(c.depth_m) for c in ctx.cores)
    lower = max(MIN_BAND_DEPTH, core_min, 2.20)
    upper = ctx.depth - ctx.corridor_depth - MIN_ROOM_DEPTH

    for _attempt in range(40):
        if lower > upper + EPS:
            break
        blocks_by_floor = {z: _must_components(rooms) for z, rooms in working.items()}
        # Identical upper-floor programmes reuse one assignment evaluation.
        assignment_cache: Dict[Tuple[Any, ...], Optional[Tuple[set, set]]] = {}
        step = 0.10
        depth = lower
        best_candidate = None
        area_bias = _profile_area_bias(profile_id)
        while depth <= upper + EPS:
            assignments: Dict[int, Tuple[set, set]] = {}
            ok = True
            preference = 0.0
            for z, blocks in blocks_by_floor.items():
                signature = (tuple(tuple(r.instance_id for r in b) for b in blocks),
                             round(depth, 2), profile_id)
                if signature in assignment_cache:
                    chosen = assignment_cache[signature]
                else:
                    chosen = _band_assignment(ctx, blocks, depth, profile_id)
                    assignment_cache[signature] = chosen
                if chosen is None:
                    ok = False
                    break
                assignments[z] = chosen
                preference += sum(_south_affinity(blocks[i], profile_id) for i in chosen[0])
            if ok:
                # Proportion first: a shallow band gives every room a wide
                # frontage, which is what produced 1:4.8 bedrooms on a 23 m
                # plate.  Depth is scanned ascending and the first depth whose
                # allocation keeps every room inside its catalogue bound wins,
                # so the shallowest *proportional* band is chosen.  Preference
                # (Vastu / daylight) breaks ties between depths that are both
                # proportional, and Max Area takes the shallowest of those.
                violations, overflow = _all_floor_proportion_cost(
                    ctx, blocks_by_floor, assignments, depth, area_bias,
                )
                key = (violations, overflow, -preference, round(depth, 2))
                if best_candidate is None or key < best_candidate[0]:
                    best_candidate = (key, round(depth, 2), assignments)
                if violations == 0 and overflow <= 0.0:
                    break
            depth = round(depth + step, 2)

        if best_candidate is not None:
            chosen_depth, chosen_assignments = best_candidate[1], best_candidate[2]
            # Industrial / deep single-loaded plates: if every floor is all-front,
            # consume the rear band with programme rather than letting the spine
            # corridor swallow it as dead circulation.
            if chosen_assignments and all(not north for _south, north in chosen_assignments.values()):
                deep = round(upper, 2)
                deep_assignments: Dict[int, Tuple[set, set]] = {}
                ok_deep = True
                for z, blocks in blocks_by_floor.items():
                    chosen = _band_assignment(ctx, blocks, deep, profile_id)
                    if chosen is None or chosen[1]:
                        ok_deep = False
                        break
                    deep_assignments[z] = chosen
                if ok_deep:
                    return deep, deep_assignments, working, dropped
            return chosen_depth, chosen_assignments, working, dropped

        # No depth works: drop the least important optional room.  Dropping a
        # room is allowed even when it belonged to a MUST_ADJACENT block: the
        # rule only applies when both rooms are present.
        candidates: List[ProgramRoom] = []
        for z, room_list in working.items():
            for room in room_list:
                if room.essential or room.required:
                    continue
                candidates.append(room)
        if not candidates:
            break
        # Lowest importance = highest priority number; deterministic tie by id.
        victim = max(candidates, key=lambda r: (r.priority, r.instance_id))
        for z in list(working):
            working[z] = [r for r in working[z] if r.instance_id != victim.instance_id]
        dropped.append(victim)

    return None, {}, working, dropped


# ---------------------------------------------------------------------------
# 4. Width allocation and geometry
# ---------------------------------------------------------------------------

def _aspect_ceiling(room: ProgramRoom, depth: float) -> float:
    """Widest frontage this room may take at ``depth`` and stay in proportion.

    ``max_aspect_ratio`` is the catalogue's hard bound (1:2.2 for a habitable
    room, 1:2.0 for a bath).  A room may never be squeezed below its required
    frontage to satisfy proportion — minimum width, area and furniture still
    win — so the ceiling is floored at ``_required_width``.
    """
    limit = float(getattr(room.spec, "max_aspect_ratio", 0.0) or 0.0)
    floor_width = _required_width(room, depth)
    if limit <= 0.0 or depth <= 0.05:
        return float("inf")
    return max(depth * limit, floor_width)


def _band_allocation(
    rooms: Sequence[ProgramRoom],
    total: float,
    depth: float,
    area_bias: Dict[str, float],
) -> Tuple[Optional[Dict[str, float]], List[str]]:
    """Allocate frontage inside one band, capped by each room's proportion.

    Extra frontage is water-filled up to each room's aspect ceiling instead of
    being dumped on the room with the largest catalogue area (which used to turn
    a 23 m wide, 3.3 m deep band into a 1:4.8 bedroom).  When every room is at
    its ceiling and frontage is still left over, the band is wider than a
    proportional programme can use: the surplus is spread proportionally rather
    than left as unlabelled void, and the rooms that crossed their bound are
    returned so the caller can disclose them.

    Returns ``(widths, over_cap_room_ids)``; ``widths`` is ``None`` only when the
    hard floors (minimum width / area / furniture) cannot fit at this depth.
    """
    required = {r.instance_id: _required_width(r, depth) for r in rooms}
    if sum(required.values()) > total + EPS:
        return None, []
    ceilings = {r.instance_id: _aspect_ceiling(r, depth) for r in rooms}
    weights = {
        r.instance_id: max(0.01, float(r.spec.min_area_sqm) * area_bias.get(r.spec.id, 1.0))
        for r in rooms
    }
    widths = dict(required)
    extra = round(total - sum(required.values()), 4)
    for _ in range(len(rooms) + 2):
        if extra <= 1e-6:
            break
        slack = {
            rid: ceilings[rid] - widths[rid]
            for rid in widths
            if ceilings[rid] - widths[rid] > 1e-6
        }
        if not slack:
            break
        wsum = sum(weights[rid] for rid in slack) or 1.0
        granted = 0.0
        for rid in sorted(slack):
            move = min(extra * weights[rid] / wsum, slack[rid])
            widths[rid] += move
            granted += move
        extra = round(extra - granted, 6)
        if granted <= 1e-9:
            break
    if extra > 1e-6:
        # Wider than the programme's proportional capacity: spread the surplus
        # so the band stays filled (no void), and own the overrun.
        scale = total / max(sum(widths.values()), 0.01)
        widths = {rid: w * scale for rid, w in widths.items()}
        extra = 0.0
    rounded = {rid: round(w, 2) for rid, w in widths.items()}
    delta = round(total - sum(rounded.values()), 2)
    if rounded:
        # Give rounding residue to the room with the most proportional slack.
        target = max(
            rounded,
            key=lambda rid: (ceilings[rid] - rounded[rid], rounded[rid], rid),
        )
        rounded[target] = round(rounded[target] + delta, 2)
    # Repair rounding shortfalls without changing the total.
    for room in rooms:
        rid = room.instance_id
        deficit = room.spec.min_area_sqm - rounded[rid] * depth
        if deficit > 0:
            widest = max(rounded, key=lambda k: (rounded[k], k))
            move = min(rounded[widest] - _required_width(next(r for r in rooms if r.instance_id == widest), depth),
                       deficit / depth + 0.01)
            if move > 0:
                rounded[widest] = round(rounded[widest] - move, 2)
                rounded[rid] = round(rounded[rid] + move, 2)
    if abs(sum(rounded.values()) - total) > 0.02:
        return None, []
    if any(rounded[r.instance_id] + 0.005 < required[r.instance_id] for r in rooms):
        return None, []
    over_cap = [
        r.instance_id for r in rooms
        if ceilings[r.instance_id] != float("inf")
        and rounded[r.instance_id] > ceilings[r.instance_id] + 0.02
    ]
    return rounded, over_cap


def _allocate_widths(
    rooms: Sequence[ProgramRoom],
    total: float,
    depth: float,
    area_bias: Dict[str, float],
) -> Optional[Dict[str, float]]:
    widths, _over_cap = _band_allocation(rooms, total, depth, area_bias)
    return widths


def _zone_for(x: float, y: float, w: float, d: float, width: float, depth: float) -> str:
    fx = (x + w / 2.0) / max(width, 0.01)
    fy = (y + d / 2.0) / max(depth, 0.01)
    ns = "N" if fy >= 0.63 else ("S" if fy <= 0.37 else "")
    ew = "E" if fx >= 0.63 else ("W" if fx <= 0.37 else "")
    if not ns and not ew:
        return "CENTER"
    return f"{ns}{ew}" if ns and ew else (ns or ew)


def _zone_category(spec: SpaceTypeSpec, typology: str) -> str:
    # Dispatch is functionally a circulation code but geometrically an
    # industrial bay; counting it as spine would falsely inflate circulation.
    if spec.id == "dispatch":
        return "industrial_bay"
    if spec.zone == SpaceZone.CIRCULATION:
        return "circulation"
    if spec.function == FunctionType.OUTDOOR:
        return "terrace"
    if typology == "T4_WAREHOUSE" and spec.function in (
        FunctionType.LOADING, FunctionType.STORAGE, FunctionType.PRODUCTION,
    ):
        return "industrial_bay"
    return spec.zone.value


def _make_room(
    *,
    room_id: str,
    name: str,
    floor_index: int,
    unit_id: Optional[str],
    x: float,
    y: float,
    width: float,
    depth: float,
    plate_w: float,
    plate_d: float,
    spec: Optional[SpaceTypeSpec],
    typology: str,
    profile_id: str,
    is_core: bool = False,
    rationale: str = "",
) -> MultiFloorRoomRectangle:
    zone = _zone_for(x, y, width, depth, plate_w, plate_d)
    category = _zone_category(spec, typology) if spec else "circulation"
    vastu_ok = True
    applied: List[str] = []
    if spec:
        weight = float(spec.vastu_zone_weights.get(zone, 0.0))
        vastu_ok = weight >= -0.25
        if spec.is_wet:
            applied.append("VERT-01-WET-STACK-ALIGN")
        if spec.zone == SpaceZone.SERVICE:
            applied.append("CIRC-02-PERIPHERAL-SERVICE")
    return MultiFloorRoomRectangle(
        room_id=room_id,
        room_name=name,
        floor_index=floor_index,
        unit_id=unit_id,
        x=round(x, 2),
        y=round(y, 2),
        width_m=round(width, 2),
        depth_m=round(depth, 2),
        area_sqm=round(width * depth, 2),
        zone=zone,
        zone_category=category,
        vastu_compliant=vastu_ok,
        is_vertical_core=is_core,
        requires_exterior_wall=bool(spec.requires_exterior_wall) if spec else False,
        aspect_ratio=round(max(width / max(depth, 0.01), depth / max(width, 0.01)), 2),
        applied_rules=applied,
        space_type_id=spec.id if spec else None,
        scheme_profile=profile_id,
        orientation_rationale=rationale,
    )


def _vastu_x_key(block: Sequence[ProgramRoom]) -> float:
    """West/east preference of a block: -1 = west, 0 = centre, +1 = east."""
    total = 0.0
    for room in block:
        weights = room.spec.vastu_zone_weights
        west = max(weights.get("W", 0.0), weights.get("SW", 0.0), weights.get("NW", 0.0))
        east = max(weights.get("E", 0.0), weights.get("SE", 0.0), weights.get("NE", 0.0))
        centre = max(weights.get("N", 0.0), weights.get("S", 0.0), weights.get("CENTER", 0.0))
        total += (east - west) + 0.15 * centre
    return total


def _ordered_blocks(
    blocks: Sequence[List[ProgramRoom]],
    band: str,
    profile_id: str,
) -> List[List[ProgramRoom]]:
    def block_key(block: Sequence[ProgramRoom]):
        wet = 0 if profile_id == "max_vastu" else min(0 if r.spec.is_wet else 1 for r in block)
        if profile_id == "max_vastu":
            # Position the block by its west/east Vastu preference, not merely N/S.
            return (wet, _vastu_x_key(block), -sum(r.spec.min_area_sqm for r in block),
                    min(r.instance_id for r in block))
        if profile_id == "max_light_vent":
            need = sum((0.4 if r.spec.daylight_req else 0.0) + (0.2 if r.spec.is_wet else 0.0) for r in block)
            return (wet, -need, -sum(r.spec.min_area_sqm for r in block), min(r.instance_id for r in block))
        return (wet, -sum(r.spec.min_area_sqm for r in block), min(r.instance_id for r in block))
    return sorted((list(b) for b in blocks), key=block_key)


def _repair_forbidden(
    ordered: List[List[ProgramRoom]],
) -> List[List[ProgramRoom]]:
    """Deterministically order blocks so no forbidden pair shares a wall."""
    blocks = [list(b) for b in ordered]
    exact = _forbidden_free_order(blocks)
    if exact is not None:
        return exact
    if len(blocks) <= 7:
        best = None
        best_bad = 10**9
        for perm in itertools.permutations(range(len(blocks))):
            arranged = [blocks[i] for i in perm]
            bad = 0
            for i in range(len(arranged) - 1):
                if any(
                    r.relation == RelationType.FORBIDDEN_WALL
                    for r in _rel_rules(arranged[i][-1], arranged[i + 1][0])
                ):
                    bad += 1
            if bad < best_bad:
                best_bad = bad
                best = arranged
            if bad == 0:
                break
        if best is not None:
            blocks = best
        if best_bad == 0:
            return blocks
    for _pass in range(6):
        changed = False
        for i in range(len(blocks) - 1):
            left_last = blocks[i][-1]
            right_first = blocks[i + 1][0]
            if not any(r.relation == RelationType.FORBIDDEN_WALL
                       for r in _rel_rules(left_last, right_first)):
                continue
            for j in range(i + 2, len(blocks)):
                prev = blocks[j - 1][-1] if j > 0 else None
                nxt = blocks[j + 1][0] if j + 1 < len(blocks) else None
                cand_first = blocks[j][0]
                cand_last = blocks[j][-1]
                ok_prev = prev is None or not any(
                    r.relation == RelationType.FORBIDDEN_WALL for r in _rel_rules(prev, cand_first))
                ok_next = nxt is None or not any(
                    r.relation == RelationType.FORBIDDEN_WALL for r in _rel_rules(cand_last, nxt))
                if ok_prev and ok_next:
                    blocks[i + 1], blocks[j] = blocks[j], blocks[i + 1]
                    changed = True
                    break
            if changed:
                break
            # Only two blocks remain at this boundary: reversing their order
            # is the deterministic repair that keeps both blocks' must-pairs intact.
            if i + 2 >= len(blocks):
                left = blocks[i]
                right = blocks[i + 1]
                if left and right and any(
                    r.relation == RelationType.FORBIDDEN_WALL
                    for r in _rel_rules(left[-1], right[0])
                ):
                    blocks[i], blocks[i + 1] = right, left
                    changed = True
                    break
        if not changed:
            break
    return blocks


def _profile_area_bias(profile_id: str) -> Dict[str, float]:
    if profile_id == "max_area":
        return {
            "living": 1.80, "dining": 1.35, "unit_living": 1.65,
            "master_bed": 1.50, "bed_2": 1.35, "unit_bed": 1.30,
            "commercial_suite": 1.50, "reception_lobby": 1.35,
            "kitchen": 1.05, "unit_kitchen": 1.05,
            "bath_1": 0.85, "bath_2": 0.85, "bath_master": 0.90,
            "utility": 0.65, "store": 0.65, "puja": 0.80,
        }
    if profile_id == "max_vastu":
        return {
            "puja": 1.45, "master_bed": 1.25, "kitchen": 1.15,
            "living": 1.10, "dining": 1.10, "unit_living": 1.10,
            "unit_kitchen": 1.10, "bath_master": 1.05,
        }
    # max_light_vent: frontage follows daylight need, service rooms stay compact.
    return {
        "living": 1.45, "unit_living": 1.45, "dining": 1.25,
        "master_bed": 1.30, "bed_2": 1.30, "unit_bed": 1.30,
        "study": 1.30, "commercial_suite": 1.25, "reception_lobby": 1.20,
        "bath_1": 0.75, "bath_2": 0.75, "bath_master": 0.80,
        "utility": 0.55, "store": 0.55, "puja": 0.75,
    }


def _order_value(
    blocks: Sequence[List[ProgramRoom]],
    *,
    depth: float,
    total_width: float,
    start_x: float,
    y: float,
    plate_w: float,
    plate_d: float,
    profile_id: str,
    area_bias: Dict[str, float],
) -> float:
    rooms = [r for b in blocks for r in b]
    widths = _allocate_widths(rooms, total_width, depth, area_bias) if rooms else {}
    if widths is None:
        return -1e9
    value = 0.0
    x = start_x
    for room in rooms:
        w = widths[room.instance_id]
        zone = _zone_for(x, y, w, depth, plate_w, plate_d)
        spec = room.spec
        if profile_id == "max_vastu":
            value += float(spec.vastu_zone_weights.get(zone, 0.0))
        elif profile_id == "max_light_vent":
            corner = 1.0 if (abs(x - start_x) < 0.02 or abs(x + w - (start_x + total_width)) < 0.02) else 0.0
            value += (1.0 if spec.daylight_req else 0.3) + 0.35 * corner
        x += w
    return value


def _optimize_order(
    blocks: Sequence[List[ProgramRoom]],
    *,
    depth: float,
    total_width: float,
    start_x: float,
    y: float,
    plate_w: float,
    plate_d: float,
    profile_id: str,
    area_bias: Dict[str, float],
) -> List[List[ProgramRoom]]:
    """Choose the forbidden-free block order with the best profile objective."""
    if len(blocks) < 2 or len(blocks) > 6:
        return blocks
    best = None
    best_value = -1e9
    for perm in itertools.permutations(blocks, len(blocks)):
        arranged = [list(b) for b in perm]
        bad = False
        for i in range(len(arranged) - 1):
            if any(r.relation == RelationType.FORBIDDEN_WALL
                   for r in _rel_rules(arranged[i][-1], arranged[i + 1][0])):
                bad = True
                break
        if bad:
            continue
        value = _order_value(
            arranged, depth=depth, total_width=total_width, start_x=start_x,
            y=y, plate_w=plate_w, plate_d=plate_d, profile_id=profile_id,
            area_bias=area_bias,
        )
        if value > best_value + 1e-9:
            best_value = value
            best = arranged
    return best if best is not None else [list(b) for b in blocks]


def _local_bands(
    ctx: PlateContext,
    floor_index: int,
    profile_id: str,
    south_blocks: Sequence[List[ProgramRoom]],
    north_blocks: Sequence[List[ProgramRoom]],
    band_depth: float,
    floor_name: str,
    dropped: Sequence[ProgramRoom],
    forced_order: Optional[Dict[str, List[List[ProgramRoom]]]] = None,
) -> FloorPlanResult:
    result = FloorPlanResult(
        floor_index=floor_index,
        floor_name=floor_name,
        band_depth=round(band_depth, 2),
        dropped=list(dropped),
    )
    north_depth = round(ctx.depth - band_depth - ctx.corridor_depth, 4)
    if north_depth < MIN_ROOM_DEPTH:
        result.warnings.append(
            f"Scheme floor {floor_index}: rear band depth {north_depth:.2f}m is below "
            f"the {MIN_ROOM_DEPTH:.2f}m minimum; scheme rejected."
        )
        return result

    area_bias = _profile_area_bias(profile_id)
    if forced_order is not None:
        # Wet-stack repair pinned this band order; see _align_wet_stacks.
        south_ordered = [list(b) for b in forced_order.get("south", south_blocks)]
        north_ordered = [list(b) for b in forced_order.get("north", north_blocks)]
    elif profile_id in ("max_vastu", "max_light_vent"):
        south_ordered = _optimize_order(
            south_blocks, depth=band_depth, total_width=ctx.south_width,
            start_x=ctx.core_column_width + ctx.lobby_width, y=0.0,
            plate_w=ctx.width, plate_d=ctx.depth, profile_id=profile_id,
            area_bias=area_bias,
        )
        north_ordered = _optimize_order(
            north_blocks, depth=north_depth, total_width=ctx.width,
            start_x=0.0, y=band_depth + ctx.corridor_depth,
            plate_w=ctx.width, plate_d=ctx.depth, profile_id=profile_id,
            area_bias=area_bias,
        )
    else:
        south_ordered = _repair_forbidden(_ordered_blocks(south_blocks, "south", profile_id))
        north_ordered = _repair_forbidden(_ordered_blocks(north_blocks, "north", profile_id))
    south_rooms = [r for b in south_ordered for r in b]
    north_rooms = [r for b in north_ordered for r in b]
    result.south_rooms = south_rooms
    result.north_rooms = north_rooms
    south_w, _south_over = _band_allocation(
        south_rooms, ctx.south_width, band_depth, area_bias,
    ) if south_rooms else ({}, [])
    north_w, _north_over = _band_allocation(
        north_rooms, ctx.width, north_depth, area_bias,
    ) if north_rooms else ({}, [])
    if south_w is None or north_w is None:
        result.warnings.append(
            f"Scheme floor {floor_index}: width allocation failed at band depth {band_depth:.2f}m."
        )
        return result
    # Core column (all locked cores, enlarged to the shared band depth).
    x = 0.0
    core_rooms: List[MultiFloorRoomRectangle] = []
    for i, core in enumerate(ctx.cores):
        cw = float(core.width_m)
        core_room = _make_room(
            room_id=f"{core.core_id}_F{floor_index}",
            name=core.core_id.replace("_", " ").title(),
            floor_index=floor_index,
            unit_id=None,
            x=x, y=0.0, width=cw, depth=band_depth,
            plate_w=ctx.width, plate_d=ctx.depth,
            spec=None, typology=ctx.engine.typology, profile_id=profile_id,
            is_core=True,
            rationale="Locked vertical core; identical coordinates on every storey (VERT-03).",
        )
        core_rooms.append(core_room)
        x += cw

    lobby = _make_room(
        room_id=f"lobby_spine_F{floor_index}",
        name="Entry Lobby",
        floor_index=floor_index,
        unit_id=None,
        x=x, y=0.0, width=ctx.lobby_width, depth=band_depth,
        plate_w=ctx.width, plate_d=ctx.depth,
        spec=None, typology=ctx.engine.typology, profile_id=profile_id,
        rationale="Entry lobby between the stacked core and every room band.",
    )
    x += ctx.lobby_width

    rooms: List[MultiFloorRoomRectangle] = core_rooms + [lobby]
    south_x = x
    for room in south_rooms:
        w = south_w[room.instance_id]
        rooms.append(_make_room(
            room_id=f"{room.instance_id}_F{floor_index}",
            name=room.display_name,
            floor_index=floor_index,
            unit_id=room.unit_id,
            x=south_x, y=0.0, width=w, depth=band_depth,
            plate_w=ctx.width, plate_d=ctx.depth,
            spec=room.spec, typology=ctx.engine.typology, profile_id=profile_id,
            rationale=f"Front band: {profile_id} weighting; south daylight and entry side.",
        ))
        south_x += w

    # If no programme room fills the front band, extend the lobby to the east wall.
    if not south_rooms:
        lobby.width_m = round(ctx.width - ctx.core_column_width, 2)
        lobby.area_sqm = round(lobby.width_m * lobby.depth_m, 2)

    corridor = _make_room(
        room_id=f"spine_corridor_F{floor_index}",
        name="Spine Corridor",
        floor_index=floor_index,
        unit_id=None,
        x=0.0, y=band_depth, width=ctx.width, depth=ctx.corridor_depth,
        plate_w=ctx.width, plate_d=ctx.depth,
        spec=None, typology=ctx.engine.typology, profile_id=profile_id,
        rationale="Single egress spine connecting both bands; no dead-end room.",
    )
    rooms.append(corridor)

    north_y = band_depth + ctx.corridor_depth
    nx = 0.0
    for room in north_rooms:
        w = north_w[room.instance_id]
        rooms.append(_make_room(
            room_id=f"{room.instance_id}_F{floor_index}",
            name=room.display_name,
            floor_index=floor_index,
            unit_id=room.unit_id,
            x=nx, y=north_y, width=w, depth=north_depth,
            plate_w=ctx.width, plate_d=ctx.depth,
            spec=room.spec, typology=ctx.engine.typology, profile_id=profile_id,
            rationale=f"Rear band: {profile_id} weighting; north daylight, plumbing clustered west.",
        ))
        nx += w

    # A deep single-loaded plate already ends the front band at D - corridor;
    # the spine sits in the last corridor-depth strip.  No dead rear strip.

    result.rooms = rooms

    # Furniture demand is part of the solved plate.  Rebalance frontage
    # inside each band before openings are hosted so the wall graph and L4 audit
    # see the final room rectangles.
    for repair_line in repair_room_envelopes_for_furniture(rooms):
        if repair_line not in result.warnings:
            result.warnings.append(repair_line)

    # Assignments for scoring/provenance.
    for room in south_rooms:
        result.assignment[room.instance_id] = "south"
    for room in north_rooms:
        result.assignment[room.instance_id] = "north"

    # Doors and windows.
    result.doors, result.windows = _host_openings(
        ctx, floor_index, rooms, lobby, core_rooms, south_rooms, north_rooms,
        band_depth, north_depth, corridor,
    )

    # Furniture catalogue (does not move rooms; attaches minimum furniture + warnings).
    for room in rooms:
        if room.zone_category in ("circulation", "terrace"):
            continue
        _ok, _items, warns = place_and_audit_furniture_catalog(room)
        for w in warns:
            if w not in result.warnings:
                result.warnings.append(w)

    # Proportion is measured on the FINAL rectangles: furniture rebalancing and
    # the forced wet-stack order move frontage after the allocation, so a band
    # that was legal at allocation time can end up stretched. Disclosing from the
    # rooms themselves keeps the warning tied to the geometry on the sheet.
    for band_label, band_y in (("front", 0.0), ("rear", north_y)):
        offenders = []
        for room in rooms:
            if abs(room.y - band_y) > 0.05 or room.zone_category in ("circulation", "terrace"):
                continue
            spec = ONTOLOGY.get_space(room.space_type_id) if room.space_type_id else None
            if spec is None or spec.max_aspect_ratio <= 0:
                continue
            if room.aspect_ratio > spec.max_aspect_ratio + 0.02:
                offenders.append(
                    f"{room.room_id} {room.width_m:.2f}x{room.depth_m:.2f} m "
                    f"= 1:{room.aspect_ratio:.2f} (limit 1:{spec.max_aspect_ratio:.2f})"
                )
        if offenders:
            result.warnings.append(
                f"ROOM-MAX: floor {floor_index} {band_label} band cannot keep "
                f"{'; '.join(offenders)} inside the catalogue proportion at this "
                f"plate; the band is still filled so no frontage is left as void, "
                f"and the overrun is disclosed rather than hidden."
            )

    for room in dropped:
        result.warnings.append(
            f"Programme compression: dropped '{room.instance_id}' "
            f"({room.spec.min_area_sqm:.1f} m² minimum) to fit the "
            f"{ctx.width:.2f} x {ctx.depth:.2f} m envelope; rooms were not silently undersized."
        )
    return result


def _host_openings(
    ctx: PlateContext,
    floor_index: int,
    rooms: List[MultiFloorRoomRectangle],
    lobby: MultiFloorRoomRectangle,
    cores: List[MultiFloorRoomRectangle],
    south_rooms: Sequence[ProgramRoom],
    north_rooms: Sequence[ProgramRoom],
    band_depth: float,
    north_depth: float,
    corridor: MultiFloorRoomRectangle,
) -> Tuple[List[MultiFloorDoorGeometry], List[MultiFloorWindowGeometry]]:
    """Host one door per room on the spine and an entry door into the lobby."""
    doors: List[MultiFloorDoorGeometry] = []
    windows: List[MultiFloorWindowGeometry] = []
    by_id = {r.room_id: r for r in rooms}

    def add_door(from_id: str, to_id: str, x1: float, y1: float, x2: float, y2: float,
                 wall_edge: str, seq: int, fire: bool = False,
                 shutter: bool = False) -> None:
        doors.append(MultiFloorDoorGeometry(
            door_id=f"D{floor_index}_{seq:03d}",
            floor_index=floor_index,
            from_room=from_id,
            to_room=to_id,
            wall_edge=wall_edge,
            x1=round(x1, 2), y1=round(y1, 2), x2=round(x2, 2), y2=round(y2, 2),
            hinge_x=round(x1, 2), hinge_y=round(y1, 2),
            swing_direction="inward_right",
            width_m=0.90,
            door_type="dock_shutter" if shutter else ("fire_rated" if fire else "standard"),
        ))

    seq = 1
    # Entry door from the front exterior into the lobby.
    add_door("EXTERIOR", lobby.room_id, lobby.x + lobby.width_m / 2 - 0.45, 0.0,
             lobby.x + lobby.width_m / 2 + 0.45, 0.0, "south", seq)
    seq += 1
    # Every core and programme room opens directly onto the spine corridor.
    for core in cores:
        cx = core.x + core.width_m / 2
        add_door(core.room_id, corridor.room_id, cx - 0.45, band_depth,
                 cx + 0.45, band_depth, "north", seq, fire=True)
        seq += 1
    for room_spec in south_rooms:
        rid = f"{room_spec.instance_id}_F{floor_index}"
        r = by_id[rid]
        cx = r.x + r.width_m / 2
        add_door(rid, corridor.room_id, cx - 0.45, band_depth,
                 cx + 0.45, band_depth, "north", seq)
        seq += 1
    for room_spec in north_rooms:
        rid = f"{room_spec.instance_id}_F{floor_index}"
        r = by_id[rid]
        cx = r.x + r.width_m / 2
        add_door(rid, corridor.room_id, cx - 0.45, band_depth + ctx.corridor_depth,
                 cx + 0.45, band_depth + ctx.corridor_depth, "south", seq)
        seq += 1
    # Lobby to corridor.
    lx = lobby.x + lobby.width_m / 2
    add_door(lobby.room_id, corridor.room_id, lx - 0.45, band_depth,
             lx + 0.45, band_depth, "north", seq, fire=True)
    seq += 1

    wseq = 1
    for room in rooms:
        if room.zone_category in ("circulation", "terrace"):
            continue
        spec = None
        for candidate in south_rooms + north_rooms:
            if room.room_id == f"{candidate.instance_id}_F{floor_index}":
                spec = candidate.spec
                break
        if spec is None:
            continue
        if room.y <= 0.01:  # front band
            width = min(1.80, max(0.90, room.width_m * 0.55))
            x1 = room.x + (room.width_m - width) / 2
            windows.append(MultiFloorWindowGeometry(
                window_id=f"W{floor_index}_{wseq:03d}", floor_index=floor_index,
                room_id=room.room_id, wall_edge="south",
                x1=round(x1, 2), y1=0.0, x2=round(x1 + width, 2), y2=0.0,
                width_m=round(width, 2), sill_height_m=0.90 if spec.daylight_req else 1.50,
            ))
            wseq += 1
        elif room.y + room.depth_m >= ctx.depth - 0.01:  # rear band
            width = min(1.80, max(0.90, room.width_m * 0.55))
            x1 = room.x + (room.width_m - width) / 2
            y = round(ctx.depth, 2)
            windows.append(MultiFloorWindowGeometry(
                window_id=f"W{floor_index}_{wseq:03d}", floor_index=floor_index,
                room_id=room.room_id, wall_edge="north",
                x1=round(x1, 2), y1=y, x2=round(x1 + width, 2), y2=y,
                width_m=round(width, 2), sill_height_m=0.90 if spec.daylight_req else 1.50,
            ))
            wseq += 1
    return doors, windows


def _floor_name(index: int) -> str:
    names = ["Ground Floor (G)", "First Floor (G+1)", "Second Floor (G+2)", "Third Floor (G+3)"]
    return names[index] if index < len(names) else f"Floor {index}"


# ---------------------------------------------------------------------------
# 5. Wet-stack alignment (VERT-01)
# ---------------------------------------------------------------------------

def _wet_intervals(rooms: Sequence[MultiFloorRoomRectangle]) -> List[Tuple[float, float]]:
    """Frontage intervals occupied by wet rooms on one storey."""
    spans: List[Tuple[float, float]] = []
    for room in rooms:
        spec = ONTOLOGY.get_space(room.space_type_id) if room.space_type_id else None
        if spec is not None and spec.is_wet:
            spans.append((float(room.x), float(room.x) + float(room.width_m)))
    return spans


def _band_wet_span(
    ordered_blocks: Sequence[Sequence[ProgramRoom]],
    widths: Dict[str, float],
    start_x: float,
    lower_wet: Sequence[Tuple[float, float]],
) -> Tuple[float, float]:
    """(wet frontage, frontage sitting over a wet room below) for one band."""
    wet = 0.0
    covered = 0.0
    x = start_x
    for block in ordered_blocks:
        for room in block:
            width = widths.get(room.instance_id, 0.0)
            if width <= 0.0:
                continue
            if getattr(room.spec, "is_wet", False):
                wet += width
                covered += sum(
                    max(0.0, min(x + width, b) - max(x, a)) for a, b in lower_wet
                )
            x += width
    return wet, covered


def _forbidden_boundary(ordered_blocks: Sequence[Sequence[ProgramRoom]]) -> bool:
    """True when two adjacent blocks would share a forbidden wall."""
    for left, right in zip(ordered_blocks, list(ordered_blocks)[1:]):
        if not left or not right:
            continue
        if any(
            rule.relation == RelationType.FORBIDDEN_WALL
            for rule in _rel_rules(left[-1], right[0])
        ):
            return True
    return False


def _swap_orders(
    blocks: Sequence[List[ProgramRoom]], budget: int = 20,
) -> List[List[List[ProgramRoom]]]:
    """Identity plus every single swap of two blocks, forbidden-free only."""
    base = [list(b) for b in blocks]
    orders: List[List[List[ProgramRoom]]] = [base]
    for i in range(len(base)):
        for j in range(i + 1, len(base)):
            if len(orders) > budget:
                return orders
            candidate = [list(b) for b in base]
            candidate[i], candidate[j] = candidate[j], candidate[i]
            if _forbidden_boundary(candidate):
                continue
            orders.append(candidate)
    return orders


def _align_wet_stacks(
    ctx: PlateContext,
    results: List[FloorPlanResult],
    working: Dict[int, List[ProgramRoom]],
    assignments: Dict[int, Tuple[set, set]],
    band_depth: float,
    profile_id: str,
) -> None:
    """Re-order a storey's bands so its wet rooms sit over the storey below.

    Sharing one band depth and one programme made this hold by accident; a
    programme that differs by storey (a study added upstairs, a bathroom moved)
    could put an upstairs ensuite over a bedroom while the certificate still
    claimed VERT-01. The repair is a bounded, deterministic block swap inside
    the band that improves frontage coverage, and it is disclosed when used.
    """
    if len(results) < 2:
        return
    area_bias = _profile_area_bias(profile_id)
    rear_depth = round(ctx.depth - band_depth - ctx.corridor_depth, 4)
    south_start = ctx.core_column_width + ctx.lobby_width

    for z in range(1, len(results)):
        lower, current = results[z - 1], results[z]
        if not lower.rooms or not current.rooms:
            continue
        lower_wet = _wet_intervals(lower.rooms)
        if not lower_wet:
            continue
        current_wet = _wet_intervals(current.rooms)
        if not current_wet:
            continue

        def coverage(rooms: Sequence[MultiFloorRoomRectangle]) -> float:
            wet = covered = 0.0
            for room in rooms:
                spec = ONTOLOGY.get_space(room.space_type_id) if room.space_type_id else None
                if spec is None or not spec.is_wet:
                    continue
                wet += float(room.width_m)
                covered += sum(
                    max(0.0, min(room.x + room.width_m, b) - max(room.x, a))
                    for a, b in lower_wet
                )
            return covered / wet if wet > 0 else 1.0

        baseline = coverage(current.rooms)
        if baseline >= 0.999:
            continue

        blocks = _must_components(working.get(z, []))
        south_idx, north_idx = assignments.get(z, (set(), set()))
        south_blocks = [blocks[i] for i in sorted(south_idx)]
        north_blocks = [blocks[i] for i in sorted(north_idx)]
        south_rooms = [r for b in south_blocks for r in b]
        north_rooms = [r for b in north_blocks for r in b]
        south_widths, _ = _band_allocation(
            south_rooms, ctx.south_width, band_depth, area_bias,
        ) if south_rooms else ({}, [])
        north_widths, _ = _band_allocation(
            north_rooms, ctx.width, rear_depth, area_bias,
        ) if north_rooms else ({}, [])
        if south_widths is None or north_widths is None:
            continue

        base_south = [list(b) for b in south_blocks]
        base_north = [list(b) for b in north_blocks]
        candidates: List[Dict[str, List[List[ProgramRoom]]]] = []
        for order in _swap_orders(base_south):
            candidates.append({"south": order, "north": [list(b) for b in base_north]})
        for order in _swap_orders(base_north):
            candidates.append({"south": [list(b) for b in base_south], "north": order})
        # A wet room can also be on the wrong SIDE of the spine: only a
        # cross-band move puts it over the storey below.
        for i in range(len(base_south)):
            for j in range(len(base_north)):
                crossed_s = [list(b) for b in base_south]
                crossed_n = [list(b) for b in base_north]
                crossed_s[i], crossed_n[j] = crossed_n[j], crossed_s[i]
                if _forbidden_boundary(crossed_s) or _forbidden_boundary(crossed_n):
                    continue
                candidates.append({"south": crossed_s, "north": crossed_n})

        best_covered = baseline
        best_forced: Optional[Dict[str, List[List[ProgramRoom]]]] = None
        for forced in candidates:
            candidate_south = [r for b in forced["south"] for r in b]
            candidate_north = [r for b in forced["north"] for r in b]
            c_south_w, _ = _band_allocation(
                candidate_south, ctx.south_width, band_depth, area_bias,
            ) if candidate_south else ({}, [])
            c_north_w, _ = _band_allocation(
                candidate_north, ctx.width, rear_depth, area_bias,
            ) if candidate_north else ({}, [])
            if c_south_w is None or c_north_w is None:
                continue
            s_wet, s_cov = _band_wet_span(forced["south"], c_south_w, south_start, lower_wet)
            n_wet, n_cov = _band_wet_span(forced["north"], c_north_w, 0.0, lower_wet)
            total_wet = s_wet + n_wet
            if total_wet <= 0.0:
                continue
            score = (s_cov + n_cov) / total_wet
            if score <= best_covered + 1e-6:
                continue
            best_covered = score
            best_forced = forced

        if best_forced is None:
            continue
        rebuilt = _local_bands(
            ctx, z, profile_id, south_blocks, north_blocks, band_depth,
            current.floor_name, current.dropped, forced_order=best_forced,
        )
        after = coverage(rebuilt.rooms) if rebuilt.rooms else 0.0
        if after <= coverage(current.rooms) + 1e-6:
            continue
        rebuilt.warnings.insert(
            0,
            f"WET-STACK-ALIGN: floor {z} bands re-ordered so its wet rooms sit over "
            f"the floor below (frontage over wet: {baseline * 100:.0f}% -> "
            f"{after * 100:.0f}%).",
        )
        results[z] = rebuilt


def _stamp_room_max_claims(results: Sequence[FloorPlanResult]) -> None:
    """Disclose any final room a band could not keep in proportion.

    ``_local_bands`` already discloses from the rectangles it built, but a floor
    can be rebuilt for wet-stack alignment afterwards. This second pass reads the
    final geometry and adds a line only for rooms nothing has named yet.
    """
    for floor in results:
        if not floor.rooms:
            continue
        named = " ".join(
            line for line in floor.warnings if line.startswith("ROOM-MAX")
        )
        offenders = []
        for room in floor.rooms:
            if room.zone_category in ("circulation", "terrace"):
                continue
            spec = ONTOLOGY.get_space(room.space_type_id) if room.space_type_id else None
            if spec is None or spec.max_aspect_ratio <= 0:
                continue
            if room.aspect_ratio <= spec.max_aspect_ratio + 0.02:
                continue
            if room.room_id in named:
                continue
            offenders.append(
                f"{room.room_id} {room.width_m:.2f}x{room.depth_m:.2f} m "
                f"= 1:{room.aspect_ratio:.2f} (limit 1:{spec.max_aspect_ratio:.2f})"
            )
        if offenders:
            floor.warnings.append(
                f"ROOM-MAX: floor {floor.floor_index} keeps "
                f"{'; '.join(offenders)} outside the catalogue proportion at this "
                f"plate; the geometry is final and the overrun is disclosed here "
                f"rather than hidden."
            )


def _stamp_wet_stack_claims(results: Sequence[FloorPlanResult]) -> None:
    """Only label a wet room VERT-01 when the geometry actually stacks it.

    Every wet room used to carry ``VERT-01-WET-STACK-ALIGN`` unconditionally, so
    a bathroom hanging over a bedroom still read as aligned. The rule is now
    stamped from the measured frontage coverage, and a room that stays
    unaligned loses the claim and gains a numbered warning instead.
    """
    for z, floor in enumerate(results):
        if z == 0 or not floor.rooms:
            continue
        lower_wet = _wet_intervals(results[z - 1].rooms)
        if not lower_wet:
            continue
        for room in floor.rooms:
            spec = ONTOLOGY.get_space(room.space_type_id) if room.space_type_id else None
            if spec is None or not spec.is_wet:
                continue
            span = max(float(room.width_m), 0.01)
            covered = sum(
                max(0.0, min(room.x + room.width_m, b) - max(room.x, a))
                for a, b in lower_wet
            )
            coverage = min(covered, span) / span
            if coverage >= 0.5:
                continue
            room.applied_rules = [
                rule for rule in room.applied_rules
                if rule != "VERT-01-WET-STACK-ALIGN"
            ]
            floor.warnings.append(
                f"WET-STACK: floor {z} {room.room_id} sits {coverage * 100:.0f}% over a "
                f"wet room on floor {z - 1}; the VERT-01 alignment claim is withdrawn "
                f"for this room rather than asserted."
            )


def solve_rectangular_plate(
    ctx: PlateContext,
    *,
    profile_id: str = "max_area",
    floors: Optional[Dict[int, List[ProgramRoom]]] = None,
) -> List[FloorPlanResult]:
    """Solve all storeys on a shared band depth and return floor results."""
    if floors is None:
        floors = {z: expand_program(ctx.engine, z) for z in range(ctx.engine.total_storeys)}

    # Profile-specific spine width: Max Area buys area by using the statutory
    # minimum, Max Light+Vent buys cross-ventilation with a wider spine.
    from dataclasses import replace as _replace
    requested_corridor = {
        "max_area": 1.00,
        "max_vastu": 1.10,
        "max_light_vent": 1.20,
    }.get(profile_id, ctx.corridor_depth)
    ctx = _replace(ctx, corridor_depth=round(max(1.0, min(1.5, requested_corridor)), 2))

    band_depth, assignments, working, dropped = _search_band_layout(ctx, floors, profile_id)
    if band_depth is None:
        # Explicit infeasibility: keep the floor programmes and report deficits.
        out: List[FloorPlanResult] = []
        for z in sorted(floors):
            result = FloorPlanResult(
                floor_index=z, floor_name=_floor_name(z), dropped=list(dropped),
            )
            result.warnings.append(
                f"Scheme '{profile_id}' is infeasible on the {ctx.width:.2f} x {ctx.depth:.2f} m "
                f"envelope: the required programme cannot fit even after explicit optional-room "
                f"compression (deficit {sum(r.spec.min_area_sqm for r in dropped):.1f} m²)."
            )
            out.append(result)
        return out

    out = []
    for z in range(ctx.engine.total_storeys):
        room_list = working.get(z, [])
        blocks = _must_components(room_list)
        south_idx, north_idx = assignments.get(z, (set(), set()))
        south_blocks = [blocks[i] for i in sorted(south_idx)]
        north_blocks = [blocks[i] for i in sorted(north_idx)]
        result = _local_bands(
            ctx, z, profile_id, south_blocks, north_blocks, band_depth,
            _floor_name(z), dropped,
        )
        out.append(result)
    # VERT-01: an upper-storey wet room must sit over one below. Programmes
    # differ by storey, so the shared band depth alone does not guarantee it.
    _align_wet_stacks(ctx, out, working, assignments, band_depth, profile_id)
    _stamp_wet_stack_claims(out)
    _stamp_room_max_claims(out)
    return out


def finalize_floor(
    ctx: PlateContext,
    result: FloorPlanResult,
) -> SingleFloorPlanModel:
    """Build the wall graph + SVG for a solved floor."""
    env = {
        "x": 0.0, "y": 0.0,
        "width": ctx.width, "depth": ctx.depth,
        "area_sqm": round(ctx.width * ctx.depth, 2),
    }
    rooms = result.rooms
    doors = result.doors
    windows = result.windows
    corridor_rooms = [r for r in rooms if r.zone_category == "circulation"]
    wall_graph = None
    wg_obj = None
    if rooms:
        try:
            wg = build_constructible_wall_graph(
                floor_index=result.floor_index,
                envelope=env,
                raw_rooms=rooms,
                typology=ctx.engine.typology,
                floor_to_floor_height_m=ctx.engine.profile.floor_height_m,
                doors_in=doors,
                windows_in=windows,
                quality_grade=ctx.request.quality_grade or "standard",
            )
            wg_obj = wg
            wall_graph = wg.to_dict() if hasattr(wg, "to_dict") else wg
        except Exception as exc:  # surface, never silently drop the sheet
            result.warnings.append(f"Wall graph build failed on floor {result.floor_index}: {exc}")

    built_up = round(sum(r.area_sqm for r in rooms if r.zone_category != "terrace"), 2)
    carpet = round(sum(
        r.area_sqm for r in rooms
        if r.zone_category not in ("circulation", "terrace")
        and not any(k in r.room_id.lower() for k in ("store", "utility", "shaft"))
    ), 2)
    status = "connected" if _doors_connected(rooms, doors) else "disconnected"
    floor = SingleFloorPlanModel(
        floor_index=result.floor_index,
        floor_name=result.floor_name,
        envelope=env,
        rooms=rooms,
        doors=doors,
        windows=windows,
        circulation_status=status,
        built_up_area_sqm=built_up,
        carpet_area_sqm=carpet,
        wall_graph=wall_graph,
    )
    if wg_obj is not None:
        floor.door_schedule = list(getattr(wg_obj, "door_schedule", []) or [])
        floor.window_schedule = list(getattr(wg_obj, "window_schedule", []) or [])
        floor.room_schedule = list(getattr(wg_obj, "room_schedule", []) or [])
        floor.stair_schedule = list(getattr(wg_obj, "stair_schedule", []) or [])
        floor.stair_geometry = (
            wg_obj.stair_geometry.__dict__ if getattr(wg_obj, "stair_geometry", None) is not None
            else None
        )
    try:
        floor.svg_blueprint_cad = generate_multi_floor_blueprint_svg(
            floor_index=result.floor_index,
            floor_name=result.floor_name,
            rooms=rooms,
            doors=doors,
            windows=windows,
            envelope=env,
            ground_cores=ctx.cores,
            ground_ducts=ctx.ducts,
            theme="cad",
            include_ghost_overlay=result.floor_index > 0,
            building_typology=ctx.engine.typology,
            wall_graph=wall_graph,
            plot_width_m=ctx.engine.plot_w,
            plot_depth_m=ctx.engine.plot_d,
            total_storeys=ctx.engine.total_storeys,
            include_service_layer=bool(ctx.request.include_service_layer),
            include_structural_sheet=bool(ctx.request.include_structural_sheet),
        )
        floor.svg_blueprint_paper = generate_multi_floor_blueprint_svg(
            floor_index=result.floor_index,
            floor_name=result.floor_name,
            rooms=rooms,
            doors=doors,
            windows=windows,
            envelope=env,
            ground_cores=ctx.cores,
            ground_ducts=ctx.ducts,
            theme="paper",
            include_ghost_overlay=result.floor_index > 0,
            building_typology=ctx.engine.typology,
            wall_graph=wall_graph,
            plot_width_m=ctx.engine.plot_w,
            plot_depth_m=ctx.engine.plot_d,
            total_storeys=ctx.engine.total_storeys,
            include_service_layer=bool(ctx.request.include_service_layer),
            include_structural_sheet=bool(ctx.request.include_structural_sheet),
        )
    except Exception as exc:
        result.warnings.append(f"SVG generation failed on floor {result.floor_index}: {exc}")
    return floor


def _doors_connected(rooms: Sequence[MultiFloorRoomRectangle], doors: Sequence[MultiFloorDoorGeometry]) -> bool:
    if not rooms:
        return False
    ids = {r.room_id for r in rooms}
    adj: Dict[str, set] = {rid: set() for rid in ids}
    entry = None
    for d in doors:
        a, b = d.from_room, d.to_room
        if a == "EXTERIOR":
            entry = b
            continue
        if a in ids and b in ids:
            adj[a].add(b)
            adj[b].add(a)
    if entry is None:
        entry = next((r.room_id for r in rooms if "lobby" in r.room_id), None)
    if entry is None:
        return False
    seen = {entry}
    queue = [entry]
    while queue:
        cur = queue.pop(0)
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return ids <= seen
