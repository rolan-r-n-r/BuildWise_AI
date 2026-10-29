"""Capture the canonical NOT-CERTIFIED warning fixture from the live engine.

The fixture is rebuilt from a live solve (12 x 15 m plate, G+2, north terrace
band on F2, coverage 0.46 -> 55 engine messages, withheld certificate) rather
than hand-edited, and written as the payload the frontend warning-report pins
read.

Run from ``backend/``:

    venv/Scripts/python.exe scripts/capture_warning_fixture.py

It prints the fixture path and the counts; it never invents a line - every
warning and relaxation is serialized from the engine response.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.floorplan import FloorPlanRequest  # noqa: E402
from app.services.floorplan import __file__ as floorplan_init
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.plan_verdict import compute_plan_verdict, plan_verdict_reasons  # noqa: E402

OUT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "test-fixtures"
    / "plan_noncertified_55.json"
)
REMEDIATION_OUT = OUT.with_name("remediation_noncertified_55.json")

REQUEST = dict(
    plot_width_m=12.0,
    plot_depth_m=15.0,
    building_typology="residential_single",
    floors=3,
    ground_coverage_ratio=0.46,
    vastu_strictness="high",
    bypass_cache=True,
    ai_provider="mock",
    terrace_bands={2: {"edge": "N", "depth_m": 3.0}},
)


def collect_relaxations(resp) -> list[dict]:
    out: list[dict] = []
    ms = getattr(resp, "multi_storey", None)
    rooms = []
    if ms:
        for floor in ms.floors:
            rooms.extend(floor.rooms)
    else:
        rooms = list(resp.placements or [])
    for room in rooms:
        for rx in getattr(room, "relaxations", None) or []:
            data = rx if isinstance(rx, dict) else rx.model_dump()
            out.append(
                {
                    "room": room.room_id,
                    "room_name": room.room_name,
                    "rule_id": data.get("rule_id"),
                    "rationale": data.get("rationale"),
                    "measure": data.get("measure"),
                    "factor": data.get("factor"),
                }
            )
    return out


def main() -> int:
    resp = generate_floor_plan(FloorPlanRequest(**REQUEST))
    warnings = [str(w) for w in (resp.warnings or [])]
    relaxations = collect_relaxations(resp)
    cert = resp.mathematical_certificate or {}
    gate = (cert.get("details") or {}).get("validation_gate")
    if not isinstance(gate, dict):
        gate = getattr(resp.qa, "validation_gate", None) if resp.qa else None
    gate_status = gate.get("overall_status") if isinstance(gate, dict) else None
    verdict_payload = {
        "mathematical_certificate": cert,
        "warnings": warnings,
        "qa": {"validation_gate_status": gate_status},
    }
    plan_verdict = resp.plan_verdict or compute_plan_verdict(verdict_payload)
    verdict_reasons = plan_verdict_reasons(verdict_payload)
    rooms = []
    ms = getattr(resp, "multi_storey", None)
    if ms:
        for floor in ms.floors:
            rooms.extend(r.room_id for r in floor.rooms)
    else:
        rooms = [r.room_id for r in (resp.placements or [])]

    payload = {
        "fixture_id": "plan_noncertified_55",
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provenance": {
            "capture_script": "backend/scripts/capture_warning_fixture.py",
            "engine_entry": "app.services.floorplan.floorplan_service.generate_floor_plan",
            "floorplan_package": str(Path(floorplan_init).resolve()),
            "note": (
                "Live engine capture; the user's original 55-line payload was "
                "not in the repo. Same qualitative shape: withheld certificate, "
                "F2 terrace band, wide warning wall, room-level relaxations."
            ),
        },
        "request": REQUEST,
        "status": resp.status,
        "plan_verdict": plan_verdict,
        "plan_verdict_reasons": verdict_reasons,
        "generation_id": resp.generation_id,
        "room_ids": rooms,
        "warnings": warnings,
        "relaxations": relaxations,
        "certificate": {
            "is_valid": cert.get("is_valid"),
            "failures": list(cert.get("failures") or []),
            "certified_rules": list(cert.get("certified_rules") or []),
        },
        "gate": {
            "status": gate_status,
            "layers": [
                {
                    "layer_id": layer.get("layer_id"),
                    "status": layer.get("status"),
                    "summary": layer.get("summary"),
                }
                for layer in ((gate or {}).get("layers") or [])
            ],
        },
        "counts": {
            "warnings": len(warnings),
            "relaxations": len(relaxations),
            "relaxation_rooms": len({r["room"] for r in relaxations}),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(json.dumps(payload["counts"]), "verdict:", payload["plan_verdict"])

    # Remediation fixture: the same plan's options, measured live.
    from app.schemas.remediation import BaselineFacts, RemediationIn
    from app.services.floorplan.remediation import build_options

    placed = sorted({r.rsplit("_F", 1)[0] for r in rooms})
    remediation = build_options(
        RemediationIn(
            request=FloorPlanRequest(**REQUEST),
            warnings=warnings,
            plan_verdict=plan_verdict,
            placed_rooms=placed,
            baseline=BaselineFacts(
                warning_count=len(warnings),
                failure_count=len(payload["certificate"]["failures"]),
                relaxation_count=len(relaxations),
            ),
        )
    )
    REMEDIATION_OUT.write_text(
        json.dumps(
            {
                "fixture_id": "remediation_noncertified_55",
                "captured_at": payload["captured_at"],
                "plan_hash": remediation.plan_hash,
                "engine_ms": remediation.engine_ms,
                "options": [o.model_dump() for o in remediation.options],
                "provenance": {
                    "capture_script": "backend/scripts/capture_warning_fixture.py",
                    "note": (
                        "Every predicted effect is a live engine re-solve of the "
                        "canonical plan's request with only that option's validated "
                        "input changed."
                    ),
                },
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {REMEDIATION_OUT}")
    print(json.dumps([{o.id: (o.effect.warning_count if o.effect else o.error)} for o in remediation.options]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
