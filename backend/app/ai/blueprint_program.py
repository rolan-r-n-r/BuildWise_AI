import time
import json
import re
import hashlib
import logging
import threading
from collections import OrderedDict
import httpx
from typing import Dict, Any, Tuple, Optional, List

from app.schemas.room_program import RoomProgram, RoomSpec, VastuZone, SolverHints
from app.config import settings
from app.ai.gemini_adapter import to_gemini_schema

logger = logging.getLogger(__name__)

# =============================================================================
# 1. HARDCODED FALLBACK PROGRAMS PER TYPOLOGY (NBC 2016 & Vastu Shastra)
# =============================================================================

FALLBACK_PROGRAMS: Dict[str, RoomProgram] = {
    "residential_single": RoomProgram(
        rooms=[
            RoomSpec(name="Living Room", min_area_pct=16.0, max_area_pct=24.0, vastu_zone=VastuZone.CENTER, adjacency=["Dining Area", "Kitchen"], requires_plumbing=False, priority=1),
            RoomSpec(name="Master Bedroom", min_area_pct=14.0, max_area_pct=22.0, vastu_zone=VastuZone.SW, adjacency=["Primary Bath"], requires_plumbing=False, priority=1),
            RoomSpec(name="Kitchen", min_area_pct=8.0, max_area_pct=14.0, vastu_zone=VastuZone.SE, adjacency=["Dining Area"], requires_plumbing=True, priority=2),
            RoomSpec(name="Puja Room", min_area_pct=4.0, max_area_pct=8.0, vastu_zone=VastuZone.NE, adjacency=["Living Room"], requires_plumbing=False, priority=3),
            RoomSpec(name="Primary Bath", min_area_pct=5.0, max_area_pct=10.0, vastu_zone=VastuZone.NW, adjacency=["Master Bedroom"], requires_plumbing=True, priority=3),
            RoomSpec(name="Bedroom 2", min_area_pct=10.0, max_area_pct=18.0, vastu_zone=VastuZone.W, adjacency=["Common Bath"], requires_plumbing=False, priority=2),
            RoomSpec(name="Common Bath", min_area_pct=4.0, max_area_pct=8.0, vastu_zone=VastuZone.NW, adjacency=["Bedroom 2"], requires_plumbing=True, priority=3),
            RoomSpec(name="Dining Area", min_area_pct=8.0, max_area_pct=14.0, vastu_zone=VastuZone.W, adjacency=["Kitchen", "Living Room"], requires_plumbing=False, priority=2),
        ],
        design_intent="Standard NBC 2016 single-family residential layout with central living circulation, southeast Agni kitchen, northeast Ishanya puja, and southwest master retreat.",
        solver_hints=SolverHints(target_utilization=0.95, allow_corridors=True)
    ),
    "residential_multi": RoomProgram(
        rooms=[
            RoomSpec(name="Living Room", min_area_pct=18.0, max_area_pct=26.0, vastu_zone=VastuZone.CENTER, adjacency=["Dining Area", "Kitchen"], requires_plumbing=False, priority=1),
            RoomSpec(name="Master Bedroom", min_area_pct=15.0, max_area_pct=22.0, vastu_zone=VastuZone.SW, adjacency=["Primary Bath"], requires_plumbing=False, priority=1),
            RoomSpec(name="Bedroom 2", min_area_pct=12.0, max_area_pct=18.0, vastu_zone=VastuZone.W, adjacency=["Common Bath"], requires_plumbing=False, priority=2),
            RoomSpec(name="Kitchen", min_area_pct=9.0, max_area_pct=15.0, vastu_zone=VastuZone.SE, adjacency=["Dining Area"], requires_plumbing=True, priority=2),
            RoomSpec(name="Dining Area", min_area_pct=8.0, max_area_pct=14.0, vastu_zone=VastuZone.W, adjacency=["Kitchen", "Living Room"], requires_plumbing=False, priority=2),
            RoomSpec(name="Primary Bath", min_area_pct=5.0, max_area_pct=10.0, vastu_zone=VastuZone.NW, adjacency=["Master Bedroom"], requires_plumbing=True, priority=3),
            RoomSpec(name="Common Bath", min_area_pct=5.0, max_area_pct=10.0, vastu_zone=VastuZone.NW, adjacency=["Bedroom 2"], requires_plumbing=True, priority=3),
        ],
        design_intent="Efficient multi-family apartment unit stack optimizing wet services along northwest vertical plumbing chases and maximizing daylight along north/east facades.",
        solver_hints=SolverHints(target_utilization=0.95, allow_corridors=True)
    ),
    "commercial": RoomProgram(
        rooms=[
            RoomSpec(name="Retail Floor", min_area_pct=25.0, max_area_pct=40.0, vastu_zone=VastuZone.CENTER, adjacency=["Lobby", "Offices"], requires_plumbing=False, priority=1),
            RoomSpec(name="Lobby", min_area_pct=12.0, max_area_pct=20.0, vastu_zone=VastuZone.E, adjacency=["Retail Floor"], requires_plumbing=False, priority=1),
            RoomSpec(name="Offices", min_area_pct=18.0, max_area_pct=30.0, vastu_zone=VastuZone.SW, adjacency=["Retail Floor"], requires_plumbing=False, priority=2),
            RoomSpec(name="Restroom", min_area_pct=6.0, max_area_pct=12.0, vastu_zone=VastuZone.NW, adjacency=["Lobby"], requires_plumbing=True, priority=3),
            RoomSpec(name="Server Room", min_area_pct=5.0, max_area_pct=10.0, vastu_zone=VastuZone.W, adjacency=["Offices"], requires_plumbing=False, priority=3),
        ],
        design_intent="Commercial layout with open retail floor, welcoming entrance lobby, southwest management suites, and consolidated northwest sanitary core.",
        solver_hints=SolverHints(target_utilization=0.95, allow_corridors=True)
    ),
    "industrial": RoomProgram(
        rooms=[
            RoomSpec(name="Production Floor", min_area_pct=35.0, max_area_pct=55.0, vastu_zone=VastuZone.CENTER, adjacency=["Storage Bay", "Office"], requires_plumbing=False, priority=1),
            RoomSpec(name="Storage Bay", min_area_pct=20.0, max_area_pct=35.0, vastu_zone=VastuZone.SW, adjacency=["Production Floor"], requires_plumbing=False, priority=2),
            RoomSpec(name="Office", min_area_pct=10.0, max_area_pct=18.0, vastu_zone=VastuZone.E, adjacency=["Production Floor"], requires_plumbing=False, priority=2),
            RoomSpec(name="Utility WC", min_area_pct=5.0, max_area_pct=10.0, vastu_zone=VastuZone.NW, adjacency=["Office"], requires_plumbing=True, priority=3),
        ],
        design_intent="Light industrial facility configured for seamless workflow between storage loading, central production floor, and administrative office.",
        solver_hints=SolverHints(target_utilization=0.95, allow_corridors=True)
    )
}

# Bounded thread-safe in-memory cache: hash_key -> (timestamp, RoomProgram)
_PROGRAM_CACHE: "OrderedDict[str, Tuple[float, RoomProgram]]" = OrderedDict()
_PROGRAM_CACHE_LOCK = threading.Lock()
CACHE_TTL_SECONDS = 3600.0  # 1 hour
CACHE_MAX_ENTRIES = 256


def _cache_get_program(key: str) -> Optional[RoomProgram]:
    now = time.time()
    with _PROGRAM_CACHE_LOCK:
        entry = _PROGRAM_CACHE.get(key)
        if entry is None:
            return None
        cached_time, prog = entry
        if now - cached_time < CACHE_TTL_SECONDS:
            _PROGRAM_CACHE.move_to_end(key)
            return prog
        else:
            _PROGRAM_CACHE.pop(key, None)
            return None


def _cache_put_program(key: str, prog: RoomProgram) -> None:
    now = time.time()
    with _PROGRAM_CACHE_LOCK:
        _PROGRAM_CACHE[key] = (now, prog)
        _PROGRAM_CACHE.move_to_end(key)
        while len(_PROGRAM_CACHE) > CACHE_MAX_ENTRIES:
            _PROGRAM_CACHE.popitem(last=False)


def _compute_cache_key(
    typology: str,
    grade: str,
    storeys: Any,
    coverage: Any,
    notes: Optional[str],
    required_rooms: Optional[List[str]] = None,
    plot_width: Optional[float] = None,
    plot_depth: Optional[float] = None,
    vastu_strictness: Optional[str] = None,
    built_up_area: Optional[float] = None,
) -> str:
    clean_notes = (notes or "").strip().lower()
    rooms_key = ",".join(sorted(str(r).strip().lower() for r in (required_rooms or [])))
    pw = round(float(plot_width), 1) if plot_width is not None else ""
    pd = round(float(plot_depth), 1) if plot_depth is not None else ""
    vs = (vastu_strictness or "").strip().lower()
    # The plinth area is part of the programme identity: it selects the size tier,
    # so omitting it made the first generation at ANY area poison every later
    # request that shared typology/grade/storeys/coverage/plot.
    area_key = round(float(built_up_area), -1) if built_up_area is not None else ""
    raw = (
        f"{typology.strip().lower()}:{grade.strip().lower()}:{str(storeys).strip().lower()}:"
        f"{str(coverage).strip()}:{clean_notes}:{rooms_key}:{pw}:{pd}:{vs}:{area_key}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


SYSTEM_PROMPT = (
    "You are a space planner trained on NBC 2016 and Vastu Shastra.\n"
    "Given typology, built-up area, grade, storeys and client notes, output ONLY a JSON object "
    "matching the RoomProgram schema.\n"
    "CRITICAL FORMAT & ARITHMETIC RULES:\n"
    '1. "design_intent": "2-3 sentences explaining the design brief, layout zoning, and client alignment.",\n'
    '2. "rooms": array of room objects (each with name, min_area_pct, max_area_pct, vastu_zone, adjacency, requires_plumbing, priority),\n'
    '3. "solver_hints": {"target_utilization": 0.95, "allow_corridors": true}\n'
    "ARITHMETIC CONSTRAINTS:\n"
    "- sum(min_area_pct) MUST be <= 95 (e.g. 70-85%).\n"
    "- sum(max_area_pct) MUST be >= 100 (e.g. 110-140%). Ensure generous max percentages so their sum comfortably reaches at least 110%.\n"
    "- Each room's min_area_pct must be <= max_area_pct.\n"
    "- Room names must be unique.\n"
    "- Adjacency list must ONLY contain names of rooms present in the 'rooms' list.\n"
    "- Choose room mix appropriate to typology: Single-Family -> living, kitchen, bedrooms, "
    "baths, puja, utility; Multi-Family -> unit-stack logic; Commercial -> retail "
    "floor, lobby, offices, WC, server/store. Premium grade adds study/ensuite/ "
    "utility; Basic compresses circulation. Kitchen prefers SE, puja NE, baths NW/W "
    "per Vastu canon; co-locate plumbing rooms."
)

CATALOG_SPECS = {
    "master_bed": ("Master Bedroom", VastuZone.SW, 14.0, 22.0, False, 1),
    "living": ("Living Room", VastuZone.CENTER, 18.0, 28.0, False, 1),
    "kitchen": ("Kitchen", VastuZone.SE, 9.0, 15.0, True, 2),
    "puja": ("Puja Room", VastuZone.NE, 4.0, 8.0, False, 3),
    "bath_1": ("Primary Bath", VastuZone.NW, 5.0, 9.0, True, 3),
    "bath_2": ("Common Bath", VastuZone.NW, 4.0, 8.0, True, 3),
    "bed_2": ("Bedroom 2", VastuZone.W, 11.0, 18.0, False, 2),
    "dining": ("Dining Area", VastuZone.W, 8.0, 14.0, False, 2),
    "stairs": ("Staircase", VastuZone.SW, 5.0, 10.0, False, 3),
}


def _generate_mock_program(
    typology: str,
    grade: str,
    storeys: Any,
    coverage: Any,
    notes: str,
    built_up_area: float,
    required_rooms: Optional[List[str]] = None
) -> RoomProgram:
    """
    Deterministic architectural space planner for offline/mock mode or fallback tailoring.
    Intelligently integrates client notes (e.g. home office, powder room, study) and typology.
    """
    clean_typology = typology.strip().lower()
    clean_notes = notes.lower()

    # --- Plinth-area program sizing -----------------------------------------
    # The target built-up area must change the GENERATED PROGRAM, not only the
    # percentages downstream: a 500 sq ft brief cannot carry a guest suite, and
    # a 50,000 sq ft brief must not return a two-bedroom flat. Area per storey
    # selects the tier; an explicit required_rooms list still wins outright.
    try:
        _area = float(built_up_area or 0.0)
    except (TypeError, ValueError):
        _area = 0.0
    try:
        _storeys = max(1, int(float(storeys or 1)))
    except (TypeError, ValueError):
        _storeys = 1
    _per_storey_sqft = (_area / _storeys) if _area > 0.0 else 0.0
    if _per_storey_sqft <= 0.0:
        area_tier = "standard"
    elif _per_storey_sqft < 900.0:
        area_tier = "compact"
    elif _per_storey_sqft < 4200.0:
        area_tier = "standard"
    else:
        area_tier = "generous"
    area_note = (
        f" Targeting {_area:,.0f} sq ft across {_storeys} storey(s) "
        f"({_per_storey_sqft:,.0f} sq ft per floor)."
        if _area > 0.0
        else ""
    )

    if clean_typology == "commercial":
        rooms = [
            RoomSpec(name="Retail Floor", min_area_pct=26.0, max_area_pct=38.0, vastu_zone=VastuZone.CENTER, adjacency=["Lobby", "Offices"], requires_plumbing=False, priority=1),
            RoomSpec(name="Lobby", min_area_pct=14.0, max_area_pct=22.0, vastu_zone=VastuZone.E, adjacency=["Retail Floor"], requires_plumbing=False, priority=1),
            RoomSpec(name="Offices", min_area_pct=20.0, max_area_pct=30.0, vastu_zone=VastuZone.SW, adjacency=["Retail Floor"], requires_plumbing=False, priority=2),
            RoomSpec(name="Restroom", min_area_pct=6.0, max_area_pct=12.0, vastu_zone=VastuZone.NW, adjacency=["Lobby"], requires_plumbing=True, priority=3),
            RoomSpec(name="Server Room", min_area_pct=5.0, max_area_pct=10.0, vastu_zone=VastuZone.W, adjacency=["Offices"], requires_plumbing=False, priority=3),
        ]
        intent = "Commercial facility with open retail floor, welcoming entrance lobby, private executive suites, and centralized sanitary facilities per NBC 2016."
        return RoomProgram(rooms=rooms, design_intent=intent, solver_hints=SolverHints(target_utilization=0.95, allow_corridors=True))

    if clean_typology == "industrial":
        return FALLBACK_PROGRAMS["industrial"]

    # If explicit required_rooms are provided by caller, generate precisely for those rooms
    if required_rooms and len(required_rooms) >= 3:
        room_list = []
        for rid in required_rooms:
            clean_rid = rid.strip().lower()
            if clean_rid in CATALOG_SPECS:
                nm, z, mi, ma, pl, pr = CATALOG_SPECS[clean_rid]
                room_list.append(RoomSpec(
                    name=nm,
                    min_area_pct=mi,
                    max_area_pct=ma,
                    vastu_zone=z,
                    adjacency=[],
                    requires_plumbing=pl,
                    priority=pr
                ))
            else:
                room_list.append(RoomSpec(
                    name=clean_rid.replace("_", " ").title(),
                    min_area_pct=8.0,
                    max_area_pct=16.0,
                    vastu_zone=VastuZone.CENTER,
                    adjacency=[],
                    requires_plumbing=False,
                    priority=2
                ))
        names_present = {r.name for r in room_list}
        for r in room_list:
            if r.name == "Master Bedroom" and "Primary Bath" in names_present:
                r.adjacency.append("Primary Bath")
            elif r.name == "Bedroom 2" and "Common Bath" in names_present:
                r.adjacency.append("Common Bath")
            elif r.name == "Dining Area":
                if "Kitchen" in names_present:
                    r.adjacency.append("Kitchen")
                if "Living Room" in names_present:
                    r.adjacency.append("Living Room")
            elif r.name == "Kitchen" and "Dining Area" in names_present:
                r.adjacency.append("Dining Area")
            elif r.name == "Puja Room" and "Living Room" in names_present:
                r.adjacency.append("Living Room")
        rooms = room_list
        features_added = [r.name for r in rooms]
    else:
        # Default residential room mix, sized by the plinth-area tier.
        if area_tier == "compact":
            # Minimal habitable core: no guest wing, no separate dining bay.
            rooms = [
                RoomSpec(name="Living Room", min_area_pct=26.0, max_area_pct=34.0, vastu_zone=VastuZone.CENTER, adjacency=["Kitchen"], requires_plumbing=False, priority=1),
                RoomSpec(name="Master Bedroom", min_area_pct=22.0, max_area_pct=30.0, vastu_zone=VastuZone.SW, adjacency=["Primary Bath"], requires_plumbing=False, priority=1),
                RoomSpec(name="Kitchen", min_area_pct=12.0, max_area_pct=18.0, vastu_zone=VastuZone.SE, adjacency=[], requires_plumbing=True, priority=2),
                RoomSpec(name="Primary Bath", min_area_pct=7.0, max_area_pct=12.0, vastu_zone=VastuZone.NW, adjacency=["Master Bedroom"], requires_plumbing=True, priority=3),
            ]
        else:
            rooms = [
                RoomSpec(name="Living Room", min_area_pct=16.0, max_area_pct=24.0, vastu_zone=VastuZone.CENTER, adjacency=["Dining Area", "Kitchen"], requires_plumbing=False, priority=1),
                RoomSpec(name="Master Bedroom", min_area_pct=14.0, max_area_pct=22.0, vastu_zone=VastuZone.SW, adjacency=["Primary Bath"], requires_plumbing=False, priority=1),
                RoomSpec(name="Kitchen", min_area_pct=8.0, max_area_pct=14.0, vastu_zone=VastuZone.SE, adjacency=["Dining Area"], requires_plumbing=True, priority=2),
                RoomSpec(name="Primary Bath", min_area_pct=5.0, max_area_pct=10.0, vastu_zone=VastuZone.NW, adjacency=["Master Bedroom"], requires_plumbing=True, priority=3),
                RoomSpec(name="Bedroom 2", min_area_pct=10.0, max_area_pct=16.0, vastu_zone=VastuZone.W, adjacency=["Common Bath"], requires_plumbing=False, priority=2),
                RoomSpec(name="Common Bath", min_area_pct=4.0, max_area_pct=8.0, vastu_zone=VastuZone.NW, adjacency=["Bedroom 2"], requires_plumbing=True, priority=3),
                RoomSpec(name="Dining Area", min_area_pct=8.0, max_area_pct=12.0, vastu_zone=VastuZone.W, adjacency=["Kitchen", "Living Room"], requires_plumbing=False, priority=2),
            ]

        if area_tier == "generous":
            # Large briefs earn the extended program instead of a duplicate flat.
            rooms.extend([
                RoomSpec(name="Bedroom 3", min_area_pct=9.0, max_area_pct=14.0, vastu_zone=VastuZone.W, adjacency=["Common Bath"], requires_plumbing=False, priority=2),
                RoomSpec(name="Store Room", min_area_pct=4.0, max_area_pct=7.0, vastu_zone=VastuZone.SE, adjacency=["Kitchen"], requires_plumbing=False, priority=3),
            ])

        has_puja = "puja" in clean_notes or (clean_typology != "residential_multi" and area_tier != "compact")
        if has_puja:
            rooms.append(RoomSpec(name="Puja Room", min_area_pct=4.0, max_area_pct=8.0, vastu_zone=VastuZone.NE, adjacency=["Living Room"], requires_plumbing=False, priority=3))

        features_added = []
        # Client notes: home office / office / study
        if "home office" in clean_notes or "office" in clean_notes or "study" in clean_notes:
            rooms.append(RoomSpec(
                name="Home Office",
                min_area_pct=8.0,
                max_area_pct=14.0,
                vastu_zone=VastuZone.N,
                adjacency=["Living Room"],
                requires_plumbing=False,
                priority=2
            ))
            features_added.append("home office")

        # Client notes: powder room / powder
        if "powder" in clean_notes or "guest bath" in clean_notes or "powder room" in clean_notes:
            rooms.append(RoomSpec(
                name="Powder Room",
                min_area_pct=3.0,
                max_area_pct=6.0,
                vastu_zone=VastuZone.NW,
                adjacency=["Living Room"],
                requires_plumbing=True,
                priority=3
            ))
            features_added.append("powder room")

        # Premium grade additions if not already added
        if grade.lower() == "premium" and "home office" not in clean_notes and "study" not in clean_notes:
            rooms.append(RoomSpec(
                name="Study",
                min_area_pct=6.0,
                max_area_pct=10.0,
                vastu_zone=VastuZone.N,
                adjacency=["Living Room"],
                requires_plumbing=False,
                priority=3
            ))
            features_added.append("study")

    # Rebalance min/max percentages so sum(min) <= 95 and sum(max) >= 100
    min_sum = sum(r.min_area_pct for r in rooms)
    if min_sum > 95.0 or min_sum <= 0:
        scale = 88.0 / max(min_sum, 1.0)
        for r in rooms:
            r.min_area_pct = max(3.0, round(r.min_area_pct * scale, 1))

    max_sum = sum(r.max_area_pct for r in rooms)
    if max_sum < 100.0 or max_sum <= 0:
        scale = 110.0 / max(max_sum, 1.0)
        for r in rooms:
            r.max_area_pct = max(r.min_area_pct + 2.0, round(r.max_area_pct * scale, 1))

    feat_desc = f" tailored with dedicated {', '.join(features_added)}" if features_added else ""
    intent = (
        f"Custom {grade.capitalize()} residential design program{feat_desc}, "
        f"optimizing passive solar orientation, southeast Agni kitchen, and consolidated northwest wet zones "
        f"per NBC 2016 and Vastu canon.{area_note}"
    )

    return RoomProgram(rooms=rooms, design_intent=intent, solver_hints=SolverHints(target_utilization=0.95, allow_corridors=True))


async def generate_room_program(
    params: Dict[str, Any],
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None
) -> Tuple[RoomProgram, str]:
    """
    Synthesizes an architectural RoomProgram matching NBC 2016 and Vastu Shastra.
    Called BEFORE the geometry solver. Supports BYOK AI providers and deterministic mock generation.
    Returns: (RoomProgram, program_source: 'llm' | 'cache' | 'fallback')
    """
    typology = params.get("typology") or params.get("building_typology") or "residential_single"
    built_up_area = float(params.get("built_up_area") or params.get("built_up_area_sqft") or 2000.0)
    grade = params.get("grade") or params.get("quality_grade") or "standard"
    storeys = params.get("storeys") or params.get("floors") or 1
    coverage = params.get("coverage") or params.get("ground_coverage") or 60
    notes = (params.get("client_notes") or params.get("client_requirements") or "").strip()
    top_entrances = params.get("top_vastu_entrances") or ["NE", "N", "E"]
    solar_axis = params.get("solar_axis") or params.get("solar_axis_degrees") or 90.0
    wind_dir = params.get("prevailing_wind") or params.get("prevailing_wind_direction_degrees") or 240.0
    required_rooms = params.get("required_rooms")
    plot_width = params.get("plot_width_m")
    plot_depth = params.get("plot_depth_m")
    vastu_strictness = params.get("vastu_strictness")
    bypass_cache = bool(params.get("bypass_cache", False))

    selected_provider = (provider or params.get("ai_provider") or settings.DEFAULT_AI_PROVIDER or "mock").lower().strip()

    # 1. Check in-memory cache (TTL 1h) - bypassed on explicit regeneration
    cache_key = _compute_cache_key(
        typology, grade, storeys, coverage, notes,
        required_rooms=required_rooms,
        plot_width=plot_width,
        plot_depth=plot_depth,
        vastu_strictness=vastu_strictness,
        built_up_area=built_up_area,
    )
    if not bypass_cache:
        cached_program = _cache_get_program(cache_key)
        if cached_program is not None:
            return cached_program, "cache"

    # 2. Build User Prompt with explicit context
    req_rooms_note = ""
    if required_rooms:
        named_reqs = [CATALOG_SPECS.get(r, (r.replace("_", " ").title(),))[0] for r in required_rooms]
        req_rooms_note = (
            f"- MANDATORY CLIENT-REQUESTED ROOMS: {', '.join(named_reqs)}\n"
            f"  You MUST include EVERY ONE of these requested rooms in the 'rooms' array.\n"
        )

    user_prompt = (
        f"Project Specification Parameters:\n"
        f"- Typology: {typology}\n"
        f"- Built-up Plinth Area: {built_up_area:,.0f} sq ft\n"
        f"- Quality Specification Grade: {grade}\n"
        f"- Storeys: {storeys}\n"
        f"- Ground Coverage: {coverage}%\n"
        f"{req_rooms_note}"
        f"- Top Vastu Entrances: {', '.join(top_entrances) if isinstance(top_entrances, list) else top_entrances}\n"
        f"- Solar Orientation Axis: {solar_axis}° (Prevailing Wind: {wind_dir}°)\n"
        f"- Client Notes / Requirements: {notes if notes else 'None provided'}\n\n"
        f"CRITICAL REQUIREMENTS:\n"
        f"- Output MUST be a valid JSON object with 'design_intent', 'rooms', and 'solver_hints'.\n"
        f"- The sum of min_area_pct must be <= 95.\n"
        f"- The sum of max_area_pct must be >= 100 (give each room a generous max percentage, e.g. living 25%, bedrooms 20%, kitchen 15%, etc. so the sum reaches at least 110%)."
    )

    schema_json = json.dumps(RoomProgram.model_json_schema(), indent=2)

    def _clean_and_parse_llm_json(raw_text: str, target_typology: str) -> Optional[RoomProgram]:
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0).strip())
        except Exception:
            return None

        if not isinstance(data, dict):
            return None

        # Unwrap if wrapped inside e.g. {"room_program": {...}} or {"program": {...}}
        if "rooms" not in data:
            for k in ("room_program", "program", "data", "result", "payload"):
                if isinstance(data.get(k), dict) and "rooms" in data[k]:
                    data = dict(data[k])
                    break

        if "rooms" not in data or not isinstance(data["rooms"], list) or not data["rooms"]:
            return None

        # 1. Ensure design_intent is populated
        if not data.get("design_intent"):
            for alt in ("design_brief", "brief", "intent", "description", "summary", "notes", "concept"):
                if data.get(alt) and isinstance(data[alt], str) and data[alt].strip():
                    data["design_intent"] = data[alt].strip()
                    break

        if not data.get("design_intent") or not str(data["design_intent"]).strip():
            room_names = [r.get("name") for r in data["rooms"] if isinstance(r, dict) and r.get("name")]
            names_str = ", ".join(room_names[:4]) if room_names else "habitable spaces"
            data["design_intent"] = f"NBC 2016 {target_typology.replace('_', ' ').title()} architectural layout with {names_str}, organized for optimal daylighting, ventilation, and Vastu zoning."

        # 2. Normalize floating-point percentage sums
        valid_rooms = [r for r in data["rooms"] if isinstance(r, dict) and ("min_area_pct" in r or "max_area_pct" in r)]
        if valid_rooms:
            for r in valid_rooms:
                try:
                    r["min_area_pct"] = float(r.get("min_area_pct", 5.0))
                except (ValueError, TypeError):
                    r["min_area_pct"] = 5.0
                try:
                    r["max_area_pct"] = float(r.get("max_area_pct", max(10.0, r["min_area_pct"] * 1.5)))
                except (ValueError, TypeError):
                    r["max_area_pct"] = max(10.0, r["min_area_pct"] * 1.5)

                if r["min_area_pct"] > r["max_area_pct"]:
                    r["max_area_pct"] = r["min_area_pct"]

            min_sum = sum(r["min_area_pct"] for r in valid_rooms)
            if min_sum > 95.0:
                scale = 94.0 / min_sum
                for r in valid_rooms:
                    r["min_area_pct"] = round(r["min_area_pct"] * scale, 1)

            max_sum = sum(r["max_area_pct"] for r in valid_rooms)
            if max_sum < 100.0:
                scale = 105.0 / max(max_sum, 1.0)
                for r in valid_rooms:
                    r["max_area_pct"] = round(r["max_area_pct"] * scale, 1)

            for r in valid_rooms:
                if r["max_area_pct"] < r["min_area_pct"]:
                    r["max_area_pct"] = r["min_area_pct"]

        # 3. Clean adjacency references that don't match any room
        room_names_set = {r.get("name", "").strip().lower() for r in data["rooms"] if isinstance(r, dict) and r.get("name")}
        room_slugs_set = {n.replace(" ", "_") for n in room_names_set} | room_names_set
        for r in data["rooms"]:
            if isinstance(r, dict) and "adjacency" in r and isinstance(r["adjacency"], list):
                r["adjacency"] = [
                    adj for adj in r["adjacency"]
                    if isinstance(adj, str) and (adj.strip().lower() in room_names_set or adj.strip().lower().replace(" ", "_") in room_slugs_set)
                ]

        # 4. Deduplicate room names if LLM repeated a room name
        seen_names = set()
        deduped_rooms = []
        for r in data["rooms"]:
            if not isinstance(r, dict):
                continue
            nm = str(r.get("name", "Room")).strip()
            base_nm = nm
            c = 2
            while nm.lower() in seen_names:
                nm = f"{base_nm} {c}"
                c += 1
            seen_names.add(nm.lower())
            r["name"] = nm
            deduped_rooms.append(r)
        data["rooms"] = deduped_rooms

        try:
            return RoomProgram.model_validate(data)
        except Exception as e:
            logger.warning(f"Sanitized LLM payload failed validation: {e}")
            return None

    # 3. Provider Dispatch
    if selected_provider == "groq":
        target_key = api_key or settings.GROQ_API_KEY
        if target_key and not target_key.startswith("your_"):
            try:
                candidate_models = [
                    model or getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
                    "llama-3.3-70b-versatile",
                    "llama-3.1-8b-instant"
                ]
                for target_model in candidate_models:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        headers = {
                            "Authorization": f"Bearer {target_key}",
                            "Content-Type": "application/json"
                        }
                        payload = {
                            "model": target_model,
                            "response_format": {"type": "json_object"},
                            "messages": [
                                {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nSchema:\n{schema_json}"},
                                {"role": "user", "content": user_prompt}
                            ],
                            "temperature": 0.4,
                            "max_tokens": 1200
                        }
                        resp = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
                        if resp.status_code == 200:
                            content = resp.json()["choices"][0]["message"]["content"]
                            prog = _clean_and_parse_llm_json(content, typology)
                            if prog:
                                _cache_put_program(cache_key, prog)
                                return prog, "llm"
            except Exception as e:
                logger.warning(f"Groq room program generation failed: {e}")

    elif selected_provider == "gemini":
        target_key = api_key or settings.GEMINI_API_KEY
        if target_key and not target_key.startswith("your_"):
            try:
                gemini_schema = to_gemini_schema(RoomProgram.model_json_schema())
                active_model = model if model and model not in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash") else "gemini-2.5-flash-lite"
                candidate_models = [
                    active_model,
                    "gemini-2.5-flash-lite",
                    "gemini-3.5-flash",
                    "gemini-3.5-flash-lite",
                ]
                seen_m = set()
                candidate_models = [m for m in candidate_models if not (m in seen_m or seen_m.add(m))]
                discovered_dynamic = False

                for target_model in candidate_models:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
                    headers = {
                        "x-goog-api-key": target_key,
                        "Content-Type": "application/json",
                    }
                    async with httpx.AsyncClient(timeout=12.0) as client:
                        payload = {
                            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                            "contents": [{"parts": [{"text": user_prompt}]}],
                            "generationConfig": {
                                "temperature": 0.4,
                                "maxOutputTokens": 1500,
                                "responseMimeType": "application/json",
                                "responseSchema": gemini_schema
                            }
                        }
                        resp = await client.post(url, headers=headers, json=payload)
                        if resp.status_code == 200:
                            cands = resp.json().get("candidates", [])
                            if cands:
                                text = cands[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                prog = _clean_and_parse_llm_json(text, typology)
                                if prog:
                                    _cache_put_program(cache_key, prog)
                                    return prog, "llm"
                        elif resp.status_code == 404 and not discovered_dynamic:
                            discovered_dynamic = True
                            from app.ai.gemini_adapter import validate_gemini_key
                            _, _, live_models = await validate_gemini_key(target_key)
                            for lm in live_models:
                                if lm not in candidate_models:
                                    candidate_models.append(lm)
            except Exception as e:
                logger.warning(f"Gemini room program generation failed: {e}")

    elif selected_provider == "openai":
        target_key = api_key
        if target_key:
            try:
                target_model = model or "gpt-4o-mini"
                async with httpx.AsyncClient(timeout=12.0) as client:
                    headers = {
                        "Authorization": f"Bearer {target_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": target_model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nSchema:\n{schema_json}"},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.4,
                        "max_tokens": 1200
                    }
                    resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        prog = _clean_and_parse_llm_json(content, typology)
                        if prog:
                            _cache_put_program(cache_key, prog)
                            return prog, "llm"
            except Exception as e:
                logger.warning(f"OpenAI room program generation failed: {e}")

    elif selected_provider == "anthropic":
        target_key = api_key
        if target_key:
            try:
                target_model = model or "claude-3-5-haiku-20241022"
                async with httpx.AsyncClient(timeout=12.0) as client:
                    headers = {
                        "x-api-key": target_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": target_model,
                        "system": f"{SYSTEM_PROMPT}\n\nSchema:\n{schema_json}",
                        "messages": [{"role": "user", "content": user_prompt}],
                        "temperature": 0.4,
                        "max_tokens": 1500
                    }
                    resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
                    if resp.status_code == 200:
                        blocks = resp.json().get("content", [])
                        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                        prog = _clean_and_parse_llm_json(text, typology)
                        if prog:
                            _cache_put_program(cache_key, prog)
                            return prog, "llm"
            except Exception as e:
                logger.warning(f"Anthropic room program generation failed: {e}")

    # 4. Mock intelligent synthesis (handles zero-config, testing, and mock/deterministic provider)
    if selected_provider in ("mock", "default", "deterministic") or not notes or required_rooms:
        try:
            mock_prog = _generate_mock_program(typology, grade, storeys, coverage, notes, built_up_area, required_rooms=required_rooms)
            _cache_put_program(cache_key, mock_prog)
            return mock_prog, "llm"
        except Exception as e:
            logger.warning(f"Mock program generation fallback triggered: {e}")

    # 5. Deterministic Typology Fallback
    fallback = FALLBACK_PROGRAMS.get(typology.lower(), FALLBACK_PROGRAMS["residential_single"])
    return fallback, "fallback"


def generate_room_program_sync(
    params: Dict[str, Any],
    provider: Optional[str] = None
) -> Tuple[RoomProgram, str]:
    """
    Synchronous room program generator for unit tests and synchronous caller contexts.
    Checks 1h TTL cache first, then generates tailored program.
    """
    typology = params.get("typology") or params.get("building_typology") or "residential_single"
    built_up_area = float(params.get("built_up_area") or params.get("built_up_area_sqft") or 2000.0)
    grade = params.get("grade") or params.get("quality_grade") or "standard"
    storeys = params.get("storeys") or params.get("floors") or 1
    coverage = params.get("coverage") or params.get("ground_coverage") or 60
    notes = (params.get("client_notes") or params.get("client_requirements") or "").strip()
    required_rooms = params.get("required_rooms")
    plot_width = params.get("plot_width_m")
    plot_depth = params.get("plot_depth_m")
    vastu_strictness = params.get("vastu_strictness")
    bypass_cache = bool(params.get("bypass_cache", False))

    cache_key = _compute_cache_key(
        typology, grade, storeys, coverage, notes,
        required_rooms=required_rooms,
        plot_width=plot_width,
        plot_depth=plot_depth,
        vastu_strictness=vastu_strictness,
        built_up_area=built_up_area,
    )
    if not bypass_cache:
        cached_program = _cache_get_program(cache_key)
        if cached_program is not None:
            return cached_program, "cache"

    try:
        mock_prog = _generate_mock_program(typology, grade, storeys, coverage, notes, built_up_area, required_rooms=required_rooms)
        _cache_put_program(cache_key, mock_prog)
        return mock_prog, "llm"
    except Exception as e:
        logger.warning(f"Sync mock program generation fallback triggered: {e}")
        fallback = FALLBACK_PROGRAMS.get(typology.lower(), FALLBACK_PROGRAMS["residential_single"])
        return fallback, "fallback"

