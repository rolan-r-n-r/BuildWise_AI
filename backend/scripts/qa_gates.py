#!/usr/bin/env python3
"""qa_gates.py - the backend gate set every change must pass.

One command, one exit status.  Run from ``backend/`` (or by path):

    python scripts/qa_gates.py              # every gate
    python scripts/qa_gates.py --list       # print the command set
    python scripts/qa_gates.py --only parity

The gates are the ones a user-visible plan change can break:

  suite       the whole backend pytest suite
  parity      page-1 / SVG-vs-PDF / gate-integrity / PDF-hygiene contracts
  rectangle   the rectangle-equivalence block (the canonical plates must not
              be partitioned as irregular ones)
  matrix      the 64-case proportion matrix generated in TWO separate
              processes (PYTHONHASHSEED 0 and 1); warning lists, sponsor
              doors and door sets must be byte-identical
  sweep       qa_invariant_sweep.py over the full typology x plot x storey x
              strictness matrix

The sweep is allowed to exit non-zero for a DISCLOSED-only register.  It is a
transparency gate, not a green-washing gate: a TRUE FAILURE keeps it red, and
this runner reads the sweep's own verdict block instead of trusting the exit
code alone.  A run that prints a non-empty TRUE FAILURES block fails the gate;
a run whose failures are all DISCLOSED passes with the counts echoed.

Everything runs with the working directory set to ``backend/`` so the pytest
node ids and the sweep's output paths resolve the same way locally and in CI.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
PY = sys.executable

#: pytest node ids per gate.  Keeping them explicit means the CI log names the
#: contract that broke, not just "tests/".
PARITY_TESTS = [
    "tests/test_report_honesty_parity.py",
    "tests/test_svg_pdf_content_parity.py",
    "tests/test_pdf_report_v9.py",
    "tests/test_pdf_hygiene_parity.py",
    "tests/test_gate_integrity.py",
    "tests/test_proportion_surface.py",
]

RECTANGLE_TESTS = [
    "tests/test_floor_plate_variations.py::test_rectangle_equivalence_unaffected",
    "tests/test_floor_plate_variations.py::test_rectangle_equivalence_no_band_identical",
]


class Step:
    def __init__(self, key: str, label: str, argv: List[str], *, sweep: bool = False):
        self.key = key
        self.label = label
        self.argv = argv
        self.sweep = sweep


STEPS = [
    Step("suite", "backend test suite", [PY, "-m", "pytest", "tests/", "-q"]),
    Step("parity", "report / PDF / gate parity", [PY, "-m", "pytest", *PARITY_TESTS, "-q"]),
    Step("rectangle", "rectangle equivalence", [PY, "-m", "pytest", *RECTANGLE_TESTS, "-q"]),
    Step("matrix", "cross-process 64-case matrix determinism",
         [PY, "scripts/qa_circulation_determinism.py", "--matrix"]),
    Step("sweep", "invariant sweep (DISCLOSED-only tolerated)",
         [PY, "scripts/qa_invariant_sweep.py"], sweep=True),
]

_TRUE_FAILURES = re.compile(r"TRUE FAILURES\s*(?:\((\d+)\))?", re.I)
# The dash before the count is locale-dependent on Windows consoles (an em dash
# can arrive as cp1252 mojibake), so it is matched as "anything, non-greedy".
_VERDICT = re.compile(r"SWEEP RESULT:\s*(PASS|FAIL).*?(\d+)\s+true failure", re.I)


def run_step(step: Step) -> Tuple[bool, str, float]:
    started = time.time()
    proc = subprocess.run(
        step.argv,
        cwd=str(BACKEND),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    elapsed = time.time() - started
    output = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-14:])
    if not step.sweep:
        return proc.returncode == 0, tail, elapsed

    # Sweep: tolerate a non-zero exit only when the verdict names zero true
    # failures.  Both the verdict line and the grouped block are checked so a
    # reformatted report cannot silently turn the gate green.
    verdict = _VERDICT.search(output)
    grouped = _TRUE_FAILURES.search(output)
    grouped_n = grouped.group(1) if (grouped and grouped.group(1)) else None
    named = int(verdict.group(2)) if verdict else (int(grouped_n) if grouped_n else None)
    if named is None:
        return False, "sweep printed no verdict block\n" + tail, elapsed
    disclosed = re.search(r"(\d+)\s+disclosed", output, re.I)
    summary = (
        f"verdict={verdict.group(1).upper() if verdict else '?'} "
        f"true_failures={named} disclosed={disclosed.group(1) if disclosed else '?'}"
    )
    if named == 0:
        # Zero true failures: a non-zero exit here is only the DISCLOSED
        # register being reported, which is the tolerated case.
        return True, summary + " (exit tolerated: DISCLOSED-only register)", elapsed
    return False, summary + "\n" + tail, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="substring of one gate key")
    parser.add_argument("--list", action="store_true", help="print the command set and exit")
    args = parser.parse_args()

    steps = [s for s in STEPS if args.only is None or args.only in s.key]
    if not steps:
        print(f"no gate matches --only {args.only!r}; keys: "
              f"{', '.join(s.key for s in STEPS)}")
        return 2
    if args.list:
        for step in steps:
            print(f"{step.key:10s} {' '.join(step.argv)}")
        return 0

    print(f"QA gates - {REPO.name}/backend ({len(steps)} step(s))\n")
    failures: List[str] = []
    for step in steps:
        print(f"[gate] {step.key}: {step.label}")
        ok, detail, elapsed = run_step(step)
        print(f"[{'PASS' if ok else 'FAIL'}] {step.key} ({elapsed:.1f}s)")
        if detail:
            print("\n".join("    " + line for line in detail.splitlines()))
        print()
        if not ok:
            failures.append(step.key)

    if failures:
        print(f"GATES FAILED: {', '.join(failures)}")
        return 1
    print("GATES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
