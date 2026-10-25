#!/usr/bin/env python3
"""Cross-process determinism gate for the floor-plan engine.

This gate covers a failure mode an in-process re-solve cannot see: the same
request produced different circulation-repair sponsors (and warning lists) in different processes, because
``_ensure_egress_connectivity`` iterated a string-keyed set.  In-process
re-solves could not see it - the hash seed is fixed for the lifetime of an
interpreter.

Two modes, one exit status:

    python scripts/qa_circulation_determinism.py            # T2 / L-244 / 3 storeys
    python scripts/qa_circulation_determinism.py --matrix   # the 64-case matrix

Both run the engine in two CHILD processes with ``PYTHONHASHSEED=0`` and ``=1``
and require byte-identical warning lists, sponsor doors and door sets.  The
repro mode pins the L-shape fixture; matrix mode is the standing gate (wired
into ``qa_gates.py``).

Run from ``backend/`` (or by path).  ``--emit PATH`` is the child mode used by
the gate itself and by the pytest pin.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

BACKEND = Path(__file__).resolve().parents[1]
PY = sys.executable
BASELINE = Path(__file__).resolve().parent / "space_proportion_baseline.py"


def _load_baseline() -> Any:
    spec = importlib.util.spec_from_file_location("space_proportion_baseline", BASELINE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _repair_doors(resp: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for floor in (resp.multi_storey.floors if resp.multi_storey else []):
        for door in floor.doors:
            if "circulation_repair" in str(door.door_id):
                out.append({
                    "floor": floor.floor_index,
                    "door_id": str(door.door_id),
                    "from_room": str(door.from_room),
                    "to_room": str(door.to_room),
                    "door_type": str(door.door_type),
                    "x1": door.x1,
                    "y1": door.y1,
                    "x2": door.x2,
                    "y2": door.y2,
                })
    return out


def _door_signature(resp: Any) -> List[List[Any]]:
    """Every door on every storey, in engine order (a plan-level fingerprint)."""
    return [
        [floor.floor_index, str(door.door_id), str(door.from_room), str(door.to_room)]
        for floor in (resp.multi_storey.floors if resp.multi_storey else [])
        for door in floor.doors
    ]


def repro_digest() -> Dict[str, Any]:
    baseline = _load_baseline()
    resp = baseline.generate_floor_plan(
        baseline.build_request(baseline.L_244, "T2_FAMILY_APARTMENT", 3)
    )
    return {
        "case": "T2-L-244-3",
        "status": str(resp.status),
        "warning_count": len(resp.warnings or []),
        "warnings": [str(w) for w in (resp.warnings or [])],
        "repair_doors": _repair_doors(resp),
        "doors": _door_signature(resp),
    }


def matrix_digest() -> Dict[str, Any]:
    baseline = _load_baseline()
    cases: List[Dict[str, Any]] = []
    for plot in baseline.PLOTS:
        for typ_key, typ_raw in baseline.TYPOLOGIES:
            for floors in baseline.FLOORS:
                case_id = f"{typ_key}-{plot['label'].replace(' ', '_')}-F{floors}"
                resp = baseline.generate_floor_plan(
                    baseline.build_request(plot, typ_raw, floors)
                )
                cases.append({
                    "case_id": case_id,
                    "status": str(resp.status),
                    "warning_count": len(resp.warnings or []),
                    "warnings": [str(w) for w in (resp.warnings or [])],
                    "repair_doors": _repair_doors(resp),
                    "doors": _door_signature(resp),
                })
    return {"suite": "cross-process-determinism", "case_count": len(cases), "cases": cases}


def _emit(kind: str, path: str) -> int:
    payload = repro_digest() if kind == "repro" else matrix_digest()
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    Path(path).write_text(text, encoding="utf-8")
    return 0


def _run_child(kind: str, seed: int, path: Path) -> None:
    env = {**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [PY, str(Path(__file__).resolve()), "--case", kind, "--emit", str(path)],
        cwd=str(BACKEND),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"child (seed={seed}) failed with exit {proc.returncode}\n"
            f"{(proc.stdout or '')[-2000:]}\n{(proc.stderr or '')[-4000:]}"
        )


def compare(kind: str) -> int:
    label = "T2 / L-244 / 3 storeys" if kind == "repro" else "64-case matrix"
    print(f"Cross-process determinism - {label} (PYTHONHASHSEED 0 vs 1)")
    with tempfile.TemporaryDirectory(prefix="qa-determinism-") as tmp:
        paths = {seed: Path(tmp) / f"seed-{seed}.json" for seed in (0, 1)}
        for seed, path in paths.items():
            _run_child(kind, seed, path)
        try:
            left = json.loads(paths[0].read_text(encoding="utf-8"))
            right = json.loads(paths[1].read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"FAIL: a child emitted invalid JSON: {exc}")
            return 1

    if left == right:
        if kind == "repro":
            repair = left.get("repair_doors") or []
            print(
                f"PASS: warning_count={left['warning_count']} "
                f"sponsor_doors={len(repair)} identical across seeds"
            )
            for door in repair:
                print(f"  F{door['floor']}: {door['from_room']} -> {door['to_room']}")
        else:
            cases = left.get("cases") or []
            with_repairs = sum(1 for c in cases if c.get("repair_doors"))
            print(
                f"PASS: {len(cases)} cases byte-identical across seeds "
                f"(warning lists + doors; {with_repairs} cases exercise the repair path)"
            )
        return 0

    print("FAIL: the two processes disagree")
    if kind == "repro":
        for key in ("warning_count", "warnings", "repair_doors", "doors"):
            if left.get(key) != right.get(key):
                print(f"  differs: {key}")
                if key == "warnings":
                    import difflib
                    for line in difflib.unified_diff(
                        [str(w) for w in left.get("warnings", [])],
                        [str(w) for w in right.get("warnings", [])],
                        fromfile="seed-0", tofile="seed-1", lineterm="",
                    ):
                        print("   " + line)
    else:
        left_cases = {c["case_id"]: c for c in left.get("cases", [])}
        right_cases = {c["case_id"]: c for c in right.get("cases", [])}
        shown = 0
        for case_id in sorted(set(left_cases) | set(right_cases)):
            a, b = left_cases.get(case_id), right_cases.get(case_id)
            if a == b:
                continue
            print(f"  case {case_id}:")
            if a is None or b is None:
                print("    present in only one process")
            else:
                for key in ("warning_count", "warnings", "repair_doors", "doors"):
                    if a.get(key) != b.get(key):
                        print(f"    differs: {key}")
                        if key == "warnings":
                            import difflib
                            for line in difflib.unified_diff(
                                [str(w) for w in a.get("warnings", [])],
                                [str(w) for w in b.get("warnings", [])],
                                fromfile="seed-0", tofile="seed-1", lineterm="",
                            ):
                                print("     " + line)
            shown += 1
            if shown >= 5:
                remaining = sum(
                    1 for cid in set(left_cases) | set(right_cases)
                    if left_cases.get(cid) != right_cases.get(cid)
                ) - shown
                if remaining:
                    print(f"  ... {remaining} more differing case(s)")
                break
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("repro", "matrix"), default="repro")
    parser.add_argument("--matrix", action="store_true", help="alias for --case matrix")
    parser.add_argument("--emit", default=None, help="child mode: write the digest here")
    args = parser.parse_args()

    kind = "matrix" if args.matrix else args.case
    if args.emit:
        return _emit(kind, args.emit)
    return compare(kind)


if __name__ == "__main__":
    raise SystemExit(main())
