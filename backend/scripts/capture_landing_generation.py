#!/usr/bin/env python
"""
capture_landing_generation.py — capture the REAL blueprint-engine output that the
marketing landing's 3D hero extrudes from, and freeze it as a runtime asset.

WHY DIRECT INVOCATION RATHER THAN HTTP
--------------------------------------
This calls the exact function the ``POST /api/generate-floorplan`` handler calls
(``app.services.floorplan.floorplan_service.generate_floor_plan`` — see the call at
``app/main.py:835``) with ``ai_provider="mock"`` and a numeric seed. It does not go
through FastAPI because ``app/services/__init__.py`` eagerly imports
``app.services.vision`` (torch + transformers + rasterio) — a ~2 GB stack with
nothing to do with the generative plan. To stop that import from running, a
namespace stub for ``app.services`` is installed in ``sys.modules`` before the
floorplan package is imported. **No engine geometry, schema or solver code is
stubbed, patched or mocked.**

DETERMINISM
-----------
Re-running the engine reproduces the geometry, rooms, metrics, certificate flags,
site plan and both SVGs bit-for-bit. Only timestamps and solve durations move
(``timing_ms``, ``solver_timing_ms``, ``generated_at``, ``validation_gate.evaluated_at``),
so the provenance hash is taken over a **canonical** payload with exactly those
fields removed. Both hashes are recorded.

WHAT IT WRITES
--------------
  backend/data/landing-captures/<name>.full.json     raw, untracked evidence
The raw capture never enters the bundle: it is 750 KB+ and holds the whole
response, INCLUDING the SVG sheets (`svg_blueprint_paper`, `site_plan.svg_site_plan`)
that this script no longer writes out — see the asset note below.

WHAT IT NO LONGER WRITES, AND WHY
---------------------------------
Three consumers of this capture have been removed from the landing, so their
assets are gone from `frontend/public/`: the 3D hero's trimmed payload (it read
`<name>.json`), and the two SVG sheets (`<name>.blueprint.svg`, `<name>.site.svg`)
that the hero's poster rung and a later drawing section mounted. Rather than
keep generating files nothing fetches, the writes are gated on the hero's plan
cache existing again (`HERO_ASSETS_CONSUMER` below): the SVG markup is still in
the raw capture, so nothing is lost, and a returning hero gets its assets back by
restoring that one module.

The same rule applies to the geometry module. It used to be emitted into
`frontend/src/landing/planGeometry.ts` for the landing's drawing, then into a parked
copy of that drawing under `frontend/quarantine/landing-plan-build/` when the section
was removed. Both are gone: nothing draws this geometry today, so nothing is written
(the gate is `GEOMETRY_CONSUMER` below). Everything the module contained is in the raw
capture, and a future drawing gets its data back by restoring a consumer and this
one constant.

WHY THERE IS ALSO A GEOMETRY MODULE
-----------------------------------
The engine's own sheets are the real deliverable but they are DOCUMENTS — 582 x 1222
and 690 x 1455, drawn for print, with a vertex table, two schedules and a 14-row gate
table beside the plan — and a print document scaled into a marketing column reads as
grey texture. So the same generation is also emitted as geometry: the plot, the
buildable envelope, the footprint and the ground floor's room rectangles as numbers,
for a page to draw with its own line weights. That is the only form in which this
geometry is legible at page size, and it is the engine's own geometry, not a redrawing
of it.

WHEN IT IS WRITTEN AT ALL. Only while something consumes it. The component that drew
this geometry was removed from the landing (sixth attempt at that section: five were
pictures of output, the last a scroll-scrubbed build-up) and the parked copy of it was
deleted too, so today this emitter is dormant and `GEOMETRY_CONSUMER` is absent. Point
that constant at a live consumer — and, if the consumer lives in `src/`, move
`GEOMETRY_TS` back there — and the module starts being written again.

The ECS bay polygons are deliberately NOT carried over: in the residential capture the
bay and its drive aisle extend across the building line (bay y 0.5-5.5 m against a
footprint starting at y 1.95 m), so drawing them would show a car parked inside the
living room. The script checks this per capture and says so in the emitted module.

Usage (from the backend directory):
    .venv-audit/Scripts/python.exe scripts/capture_landing_generation.py
"""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any, Dict

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
RAW_DIR = BACKEND / "data" / "landing-captures"
PUBLIC_DIR = REPO / "frontend" / "public" / "landing"
GEOMETRY_TS = REPO / "frontend" / "quarantine" / "landing-plan-build" / "planGeometry.ts"

# The drawing that read GEOMETRY_TS. It was deleted with the section it belonged to, so
# the emitter stays dormant until a consumer exists again — see the module docstring.
# Without this gate the script recreates the folder it was asked to remove, which is
# exactly what it did the first time this ran after that deletion.
GEOMETRY_CONSUMER = REPO / "frontend" / "quarantine" / "landing-plan-build" / "PlanBuild.tsx"

# The trimmed hero payload and the two SVG posters had exactly one consumer between
# them: the 3D hero (its plan cache). That hero was quarantined and then deleted, so
# writing a ~150 KB payload and ~78 KB of sheets that nothing fetches would ship dead
# weight in every build — and an audit found the pages serving them were stale copies
# nobody noticed. Both writes are therefore gated on the consumer existing again.
HERO_ASSETS_CONSUMER = REPO / "frontend" / "src" / "landing" / "hero3d" / "planCache.ts"

sys.path.insert(0, str(BACKEND))

# Import the floorplan engine WITHOUT executing app/services/__init__.py, which
# pulls the torch/rasterio site-vision stack. A namespace package keeps the real
# submodule files importable and leaves every engine module untouched.
_stub = types.ModuleType("app.services")
_stub.__path__ = [str(BACKEND / "app" / "services")]  # type: ignore[attr-defined]
sys.modules["app.services"] = _stub

from app.services.floorplan.floorplan_service import generate_floor_plan  # noqa: E402
from app.schemas.floorplan import FloorPlanRequest  # noqa: E402

# Fields that legitimately vary between two runs of the same deterministic seed.
VOLATILE = {"timing_ms", "solver_timing_ms", "generated_at", "evaluated_at"}

# Room geometry the massing needs. Everything else on a room (fixtures, furniture,
# applied_rules, relaxations, naming thresholds) is ~500–1150 bytes per room of
# solver auditing that a hero cannot draw, and is what makes the raw capture large.
ROOM_KEEP = (
    "room_id", "room_name", "floor_index", "x", "y", "width_m", "depth_m",
    "area_sqm", "zone", "zone_category", "vastu_compliant", "is_vertical_core",
)

FLOOR_KEEP = (
    "floor_index", "floor_name", "envelope", "vastu_score_pct",
    "plumbing_stack_alignment_pct", "built_up_area_sqm", "carpet_area_sqm",
    "circulation_status",
)

SITE_PLAN_KEEP = (
    "plot_polygon", "buildable_polygon_coords", "buildable_area_sqm", "footprint",
    "setback_dimensions", "setback_band_area_sqm", "nominal_setback_m",
    "reduced_setback_applied", "outdoor_zones", "wedge_zones", "parking",
    "site_vastu_zones",
)

CERT_KEEP = (
    "certificate_id", "is_valid", "overall_layer_status", "certified_rules",
    "layer_statuses", "zero_forbidden_violations", "aspect_ratios_satisfied",
    "chain_sums_match", "connectivity_bfs", "containment", "core_continuity_valid",
    "cores_stack_aligned", "egress_distances_satisfied", "l2_door_swings_valid",
    "l3_fixture_clearances_satisfied", "l4_furniture_clearances_satisfied",
    "l8_program_intent_satisfied", "min_dimensions_satisfied",
    "must_adjacency_satisfied", "no_wet_over_terrace_valid", "non_overlap",
    "parking_count_satisfied", "prefer_adjacency_score",
    "sanitation_wc_count_satisfied", "terrace_far_exempt", "vertical_stack_valid",
)


def strip_volatile(value: Any) -> Any:
    """Recursively drop run-to-run volatile keys so the hash is reproducible."""
    if isinstance(value, dict):
        return {k: strip_volatile(v) for k, v in sorted(value.items()) if k not in VOLATILE}
    if isinstance(value, list):
        return [strip_volatile(v) for v in value]
    return value


def sha256_of(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def pick(source: Dict[str, Any], keys) -> Dict[str, Any]:
    return {k: source[k] for k in keys if k in source and source[k] is not None}


def trim(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The hero's narrow view of a real generation (see module docstring)."""
    ms = payload.get("multi_storey") or {}
    sp = payload.get("site_plan") or {}
    cert = payload.get("mathematical_certificate") or {}

    floors = []
    for floor in ms.get("floors") or []:
        out = pick(floor, FLOOR_KEEP)
        out["rooms"] = [pick(room, ROOM_KEEP) for room in floor.get("rooms") or []]
        floors.append(out)

    site_plan = pick(sp, SITE_PLAN_KEEP)
    # The endpoint's top-level plot_polygon is only populated when the caller sent
    # one; the canonical polygon always lives in the site plan. One place to read.
    plot_polygon = payload.get("plot_polygon") or site_plan.get("plot_polygon")

    return {
        "status": payload.get("status"),
        "generation_id": payload.get("generation_id"),
        "seed": payload.get("seed") or ms.get("seed"),
        "program_source": payload.get("program_source"),
        "placement_source": payload.get("placement_source"),
        "iterations": payload.get("iterations"),
        "metrics": payload.get("metrics"),
        "warnings": payload.get("warnings"),
        "unmet_requirements": payload.get("unmet_requirements"),
        "plot_polygon": plot_polygon,
        "mathematical_certificate": pick(cert, CERT_KEEP) or pick(ms.get("mathematical_certificate") or {}, CERT_KEEP),
        "multi_storey": {
            **pick(ms, ("building_typology", "total_storeys", "plot_width_m", "plot_depth_m",
                        "ground_coverage_ratio", "total_built_up_area_sqm", "vertical_cores",
                        "duct_shafts", "seed")),
            "floors": floors,
        },
        "site_plan": site_plan,
    }


# ---------------------------------------------------------------------------
# The landing's drawing, emitted as a TypeScript module.
# ---------------------------------------------------------------------------

# The module's prose. Generated alongside the numbers so the two can never
# disagree about where those numbers came from.
GEOMETRY_HEADER = '''/**
 * planGeometry.ts — the geometry of the landing's sample generation.
 *
 * GENERATED FILE — DO NOT EDIT BY HAND. Written by
 * `backend/scripts/capture_landing_generation.py`, which runs the real engine once
 * (deterministic seed) and emits what follows. Regenerate with:
 *
 *     cd backend && .venv-audit/Scripts/python.exe scripts/capture_landing_generation.py
 *
 * PARKED, WITH ITS CONSUMER. This module is the sample generation reduced to geometry —
 * the primitives a page can draw legibly at page size, rather than the engine's own
 * print sheets, which are documents (582x1222 and 690x1455, with a vertex table, two
 * schedules and a 14-row gate table beside the plan). The component that drew it is
 * `PlanBuild.tsx` / `SectionShell.tsx` in this folder, removed from the landing and kept
 * here with its data; nothing in `src/` imports this file.
 *
 * THE TWO FRAMES, both the engine's own and both unmodified:
 *   - SITE  (plot frame, metres) — origin at vertex P1, +x east, +y north.
 *     `plot`, `buildable` and `footprint` are in this frame.
 *   - ROOMS (envelope frame, metres) — the floor's rooms are reported in the building
 *     envelope's own frame, so a room occupies (x, y) to (x + width, y + depth) inside
 *     `groundFloor.envelope`. That is how the solver reports them.
 *
 * PROVENANCE. The seed, generation id and canonical payload sha256 below are the
 * same ones `landing/sample.ts` records, and the drawings are reproducible from
 * them: only timing fields move between runs.
 */
'''


def num(value: Any) -> str:
    """Compact numeric literal: 9.749999 becomes 9.75, 1.5625 stays exact."""
    if isinstance(value, bool) or value is None:
        return "0"
    if isinstance(value, int):
        return str(value)
    return f"{round(float(value), 4):g}"


def ts_str(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def poly_literal(coords) -> str:
    """A polygon as a list of [x, y] pairs, rounded, wrapped."""
    points = [f"[{num(c[0])}, {num(c[1])}]" for c in coords]
    if sum(len(p) for p in points) < 70:
        return "[" + ", ".join(points) + "]"
    inner = "\n".join(f"      {p}," for p in points)
    return "[\n" + inner + "\n    ]"


def room_literal(room: Dict[str, Any]) -> str:
    return (
        f"    {{ name: {ts_str(room.get('room_name') or '')}, x: {num(room.get('x'))}, "
        f"y: {num(room.get('y'))}, width: {num(room.get('width_m'))}, "
        f"depth: {num(room.get('depth_m'))}, areaSqm: {num(room.get('area_sqm'))}, "
        f"category: {ts_str(room.get('zone_category') or 'other')}, core: {str(bool(room.get('is_vertical_core'))).lower()} }},"
    )


def bays_overlap_footprint(site_plan: Dict[str, Any]) -> bool:
    """True when any ECS bay crosses the building line (axis-aligned check)."""
    fp = site_plan.get("footprint") or {}
    fx, fy = float(fp.get("x") or 0), float(fp.get("y") or 0)
    fx2, fy2 = fx + float(fp.get("width_m") or 0), fy + float(fp.get("depth_m") or 0)
    for bay in (site_plan.get("parking") or {}).get("bays") or []:
        coords = bay.get("polygon_coords") or []
        if not coords:
            continue
        xs = [float(c[0]) for c in coords]
        ys = [float(c[1]) for c in coords]
        if min(xs) < fx2 and max(xs) > fx and min(ys) < fy2 and max(ys) > fy:
            return True
    return False


def write_geometry_module(payload: Dict[str, Any], canonical_hash: str) -> Path:
    """Emit the landing's drawing data from a real generation."""
    ms = payload.get("multi_storey") or {}
    sp = payload.get("site_plan") or {}
    plot = sp.get("plot_polygon") or payload.get("plot_polygon") or {}
    fp = sp.get("footprint") or {}
    parking = sp.get("parking") or {}
    floors = ms.get("floors") or []
    ground = floors[0] if floors else {}
    upper = floors[1] if len(floors) > 1 else {}
    envelope = ground.get("envelope") or {}
    setbacks = sp.get("setback_dimensions") or {}
    cert = payload.get("mathematical_certificate") or {}

    bay_note = (
        " *\n * NOTE — THE ECS BAY IS NOT DRAWN FROM GEOMETRY. In this capture the bay and its\n"
        " * drive aisle cross the building line, so the module carries the parking COUNT and\n"
        " * the aisle width as figures and no bay polygon. The page states the count; it does\n"
        " * not picture a car inside the living room.\n"
        if bays_overlap_footprint(sp)
        else ""
    )

    rooms = "\n".join(room_literal(r) for r in ground.get("rooms") or [])
    rooms = rooms.replace("', x:", "',\n      x:")

    body = f"""
/** One [x, y] pair in metres. */
export type PlanPoint = readonly [number, number];

/** A rectangle in the frame its sheet declares. */
export interface PlanRect {{
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly depth: number;
}}

/** One solved room, in the envelope frame. */
export interface PlanRoom {{
  readonly name: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly depth: number;
  readonly areaSqm: number;
  readonly category: string;
  /** True for the vertical core — the staircase the floors share. */
  readonly core: boolean;
}}

export interface PlanGeometry {{
  readonly seed: string;
  readonly generationId: string;
  readonly canonicalSha256: string;
  readonly typology: string;
  readonly storeys: number;
  /** Ground coverage as a fraction of the plot (the request's 0.60). */
  readonly coverageRatio: number;
  readonly builtUpAreaSqm: number;
  readonly plot: {{
    readonly shapeType: string;
    readonly areaSqm: number;
    readonly perimeterM: number;
    readonly widthM: number;
    readonly depthM: number;
    readonly vertices: readonly PlanPoint[];
  }};
  readonly buildable: {{
    readonly areaSqm: number;
    readonly vertices: readonly PlanPoint[];
  }};
  /** The plot's area that the envelope leaves over — the setback band (real field). */
  readonly setbackBandAreaSqm: number;
  /** Setbacks in metres, as the site solver applied them. */
  readonly setbacksM: {{
    readonly front: number;
    readonly rear: number;
    readonly left: number;
    readonly right: number;
    readonly nominal: number;
  }};
  readonly footprint: PlanRect & {{
    readonly areaSqm: number;
    readonly topology: string;
  }};
  readonly parking: {{
    readonly required: number;
    readonly provided: number;
    readonly driveAisleWidthM: number;
  }};
  readonly groundFloor: {{
    readonly name: string;
    readonly envelope: PlanRect;
    readonly builtUpAreaSqm: number;
    readonly carpetAreaSqm: number;
    readonly rooms: readonly PlanRoom[];
  }};
  readonly firstFloor: {{
    readonly name: string;
    readonly builtUpAreaSqm: number;
    readonly carpetAreaSqm: number;
    readonly roomCount: number;
  }};
  readonly certificate: {{
    readonly id: string;
    readonly isValid: boolean;
    readonly overallLayerStatus: string;
  }};
}}

/**
 * The sample generation, reduced to what the landing's drawing needs.{bay_note} */
export const PLAN_GEOMETRY: PlanGeometry = {{
  seed: {ts_str(payload.get('seed') or ms.get('seed') or '')},
  generationId: {ts_str(payload.get('generation_id') or '')},
  canonicalSha256: {ts_str(canonical_hash)},
  typology: {ts_str(ms.get('building_typology') or '')},
  storeys: {num(ms.get('total_storeys'))},
  coverageRatio: {num(ms.get('ground_coverage_ratio'))},
  builtUpAreaSqm: {num(ms.get('total_built_up_area_sqm'))},
  plot: {{
    shapeType: {ts_str(plot.get('shape_type') or '')},
    areaSqm: {num(plot.get('area_sqm'))},
    perimeterM: {num(plot.get('perimeter_m'))},
    widthM: {num(ms.get('plot_width_m'))},
    depthM: {num(ms.get('plot_depth_m'))},
    vertices: {poly_literal(plot.get('vertices') or [])},
  }},
  buildable: {{
    areaSqm: {num(sp.get('buildable_area_sqm'))},
    vertices: {poly_literal(sp.get('buildable_polygon_coords') or [])},
  }},
  setbackBandAreaSqm: {num(sp.get('setback_band_area_sqm'))},
  setbacksM: {{
    front: {num(setbacks.get('front_m'))},
    rear: {num(setbacks.get('rear_m'))},
    left: {num(setbacks.get('left_m'))},
    right: {num(setbacks.get('right_m'))},
    nominal: {num(setbacks.get('nominal_m'))},
  }},
  footprint: {{
    x: {num(fp.get('x'))},
    y: {num(fp.get('y'))},
    width: {num(fp.get('width_m'))},
    depth: {num(fp.get('depth_m'))},
    areaSqm: {num(fp.get('area_sqm'))},
    topology: {ts_str(fp.get('topology_type') or '')},
  }},
  parking: {{
    required: {num(parking.get('required_ecs'))},
    provided: {num(parking.get('provided_ecs'))},
    driveAisleWidthM: {num(parking.get('drive_aisle_width_m'))},
  }},
  groundFloor: {{
    name: {ts_str(ground.get('floor_name') or 'Ground Floor')},
    envelope: {{
      x: {num(envelope.get('x'))},
      y: {num(envelope.get('y'))},
      width: {num(envelope.get('width'))},
      depth: {num(envelope.get('depth'))},
    }},
    builtUpAreaSqm: {num(ground.get('built_up_area_sqm'))},
    carpetAreaSqm: {num(ground.get('carpet_area_sqm'))},
    rooms: [
{rooms}
    ],
  }},
  firstFloor: {{
    name: {ts_str(upper.get('floor_name') or 'First Floor')},
    builtUpAreaSqm: {num(upper.get('built_up_area_sqm'))},
    carpetAreaSqm: {num(upper.get('carpet_area_sqm'))},
    roomCount: {len(upper.get('rooms') or [])},
  }},
  certificate: {{
    id: {ts_str(cert.get('certificate_id') or '')},
    isValid: {str(bool(cert.get('is_valid'))).lower()},
    overallLayerStatus: {ts_str(cert.get('overall_layer_status') or '')},
  }},
}};
"""
    GEOMETRY_TS.parent.mkdir(parents=True, exist_ok=True)
    GEOMETRY_TS.write_text(GEOMETRY_HEADER + body, encoding="utf-8")
    return GEOMETRY_TS


def capture(name: str, request: FloorPlanRequest, geometry: bool = False) -> None:
    """Run one generation and freeze what the landing reads from it.

    ``geometry`` marks the capture the landing's DRAWING is built from. Only one
    capture may set it: `planGeometry.ts` is a single generation, and it has to be
    the same one `landing/sample.ts` quotes its figures from.
    """
    response = generate_floor_plan(request)
    payload = response.model_dump(mode="json")

    canonical = strip_volatile(payload)
    canonical_hash = sha256_of(canonical)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    trim_doc = {
        "_provenance": {
            "captured_by": "backend/scripts/capture_landing_generation.py",
            "engine": "app.services.floorplan.floorplan_service.generate_floor_plan",
            "endpoint_equivalent": "POST /api/generate-floorplan (JSON branch, app/main.py:835)",
            "invocation": "direct — see module docstring (HTTP app eagerly imports the torch vision stack)",
            "ai_provider": request.ai_provider,
            "seed": request.seed,
            "generation_id": payload.get("generation_id"),
            "canonical_sha256": canonical_hash,
            "hash_note": "sha256 over the full response with only run-volatile fields removed "
                         f"({', '.join(sorted(VOLATILE))}); geometry, rooms, metrics, certificate and SVGs are bit-identical across runs",
            "fields_dropped": "room fixtures/furniture/applied_rules/relaxations, certificate details, "
                              "qa_report, validation_gate, grid_matrix, rectangles, placements, duplicate svg_blueprint",
            "purpose": "marketing landing hero massing, hotspot anchors and fallback posters",
        },
        "request": request.model_dump(mode="json"),
        "plan": trim(payload),
    }

    raw_path = RAW_DIR / f"{name}.full.json"
    raw_path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")

    hero_assets_wanted = HERO_ASSETS_CONSUMER.exists()

    json_path = PUBLIC_DIR / f"{name}.json"
    if hero_assets_wanted:
        PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(trim_doc, separators=(",", ":")) + "\n", encoding="utf-8")
    elif json_path.exists():
        json_path.unlink()  # consumer is gone; do not keep a dead asset in public/

    geometry_path = (
        write_geometry_module(payload, canonical_hash)
        if geometry and GEOMETRY_CONSUMER.exists()
        else None
    )

    svg_files = {}
    if hero_assets_wanted:
        for suffix, key in (("blueprint", "svg_blueprint_paper"), ("site", None)):
            svg = payload.get(key) if key else (payload.get("site_plan") or {}).get("svg_site_plan")
            if not svg:
                svg = (payload.get("multi_storey") or {}).get("site_plan", {}).get("svg_site_plan") if not key else svg
            if isinstance(svg, str) and svg.strip():
                p = PUBLIC_DIR / f"{name}.{suffix}.svg"
                p.write_text(svg, encoding="utf-8")
                svg_files[suffix] = p

    raw_bytes = raw_path.stat().st_size
    print(f"\n=== {name} ===")
    print(f"  canonical sha256  : {canonical_hash}")
    print(f"  generation_id     : {payload.get('generation_id')} seed={request.seed} status={payload.get('status')}")
    print(f"  raw evidence      : {raw_path.relative_to(REPO)} ({raw_bytes/1024:.0f} KB, untracked)")
    if geometry_path:
        print(f"  drawing geometry  : {geometry_path.relative_to(REPO)} ({geometry_path.stat().st_size/1024:.1f} KB)")
    else:
        print("  drawing geometry  : not written — no consumer (geometry is in the raw capture)")
    if hero_assets_wanted:
        trim_bytes = json_path.stat().st_size
        print(f"  hero payload      : {json_path.relative_to(REPO)} ({trim_bytes/1024:.0f} KB, "
              f"{100*trim_bytes/raw_bytes:.0f}% of raw)")
    else:
        print("  hero payload      : not written — no consumer (hero3d plan cache absent)")
    for suffix, path in svg_files.items():
        print(f"  poster {suffix:<9}  : {path.relative_to(REPO)} ({path.stat().st_size/1024:.0f} KB)")
    if not hero_assets_wanted:
        print("  posters           : not written — no consumer (SVG markup is in the raw capture above)")
    plan = trim_doc["plan"]
    ms = plan["multi_storey"]
    print(f"  plot              : {plan['plot_polygon']['shape_type']} "
          f"{plan['plot_polygon']['area_sqm']} m², {len(plan['plot_polygon']['vertices'])} vertices")
    print(f"  storeys           : {ms['building_typology']} × {ms['total_storeys']}, "
          f"built-up {ms['total_built_up_area_sqm']} m²")
    for fl in ms["floors"]:
        env = fl.get("envelope") or {}
        print(f"    {fl['floor_name']:<20} envelope {env.get('width')}×{env.get('depth')} m, "
              f"{len(fl['rooms'])} rooms, vastu {fl.get('vastu_score_pct')}")
    sp = plan["site_plan"]
    fp = sp.get("footprint") or {}
    print(f"  footprint         : {fp.get('topology_type')} {fp.get('width_m')}×{fp.get('depth_m')} m, "
          f"wings={len(fp.get('wings') or [])}, setbacks={sp.get('setback_dimensions')}")
    print(f"  outdoor zones     : {[z.get('name') for z in (sp.get('outdoor_zones') or [])]}")
    print(f"  parking           : provided={((sp.get('parking') or {}).get('provided_ecs'))} "
          f"required={((sp.get('parking') or {}).get('required_ecs'))}")
    cert = plan["mathematical_certificate"]
    print(f"  certificate       : {cert.get('certificate_id')} valid={cert.get('is_valid')} "
          f"status={cert.get('overall_layer_status')}")
    print(f"  warnings          : {len(plan.get('warnings') or [])}")


def main() -> None:
    # 1) THE HERO — a regular plot, two storeys, deterministic seed.
    capture(
        "generated-plan",
        FloorPlanRequest(
            plot_width_m=15.0,
            plot_depth_m=13.0,
            building_typology="residential_single",
            floors=2,
            ground_coverage_ratio=0.60,
            quality_grade="standard",
            vastu_strictness="high",
            ai_provider="mock",
            seed="20261016",
            latitude=12.9716,
            longitude=77.5946,
            client_notes="Landing hero massing generation.",
        ),
        geometry=True,
    )

    # 2) PROOF OF IRREGULAR CADASTRAL SUPPORT — a six-vertex, non-rectilinear plot.
    #    Same engine, different geometry; the irregular-plot proof and the
    #    landing honesty checks both read this capture.
    capture(
        "generated-plan-irregular",
        FloorPlanRequest(
            plot_polygon={
                "vertices": [
                    [0.0, 0.0], [18.4, 0.0], [21.6, 6.9],
                    [19.1, 15.8], [7.2, 17.4], [0.0, 11.2],
                ],
                "origin_lat": 12.9716,
                "origin_lon": 77.5946,
                "shape_type": "irregular",
                "is_regular_rectangle": False,
            },
            building_typology="residential_single",
            floors=2,
            ground_coverage_ratio=0.60,
            quality_grade="standard",
            vastu_strictness="high",
            ai_provider="mock",
            seed="20261016",
            latitude=12.9716,
            longitude=77.5946,
            client_notes="Irregular cadastral plot proof generation.",
        ),
    )


if __name__ == "__main__":
    main()
