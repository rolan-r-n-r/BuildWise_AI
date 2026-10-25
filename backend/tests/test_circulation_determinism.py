"""Circulation repair must not depend on the process hash seed.

The failure mode: ``_ensure_egress_connectivity`` built ``reachable_rooms`` by
iterating the ``seen`` SET, so the sponsor tie-break followed Python's
per-process string hashing.  The same T2 / L-244 / 3-storey request repaired a
different door (and reported 42, 44 or 46 warnings) in different processes.

This pin runs the fixture in two separate interpreters - the same hole the old
in-process determinism tests could not see - and requires identical sponsor
doors, warning lists and warnings counts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
GATE = BACKEND / "scripts" / "qa_circulation_determinism.py"


def _digest(seed: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="qa15-pin-") as tmp:
        out = Path(tmp) / "digest.json"
        proc = subprocess.run(
            [sys.executable, str(GATE), "--case", "repro", "--emit", str(out)],
            cwd=str(BACKEND),
            env={**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONIOENCODING": "utf-8"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        assert proc.returncode == 0, (
            f"determinism probe (seed={seed}) failed:\n{proc.stdout}\n{proc.stderr}"
        )
        return json.loads(out.read_text(encoding="utf-8"))


def test_circulation_repair_is_hash_seed_independent() -> None:
    first = _digest(0)
    second = _digest(1)

    # The fixture must actually exercise the repair path, or the pin proves
    # nothing about sponsor selection.
    assert first["repair_doors"], "the fixture no longer exercises the repair"
    assert len(first["repair_doors"]) == len(second["repair_doors"])

    assert first["warning_count"] == second["warning_count"]
    assert first["warnings"] == second["warnings"]
    assert first["repair_doors"] == second["repair_doors"]
    assert first["doors"] == second["doors"]

    # The sponsor is named in the warning and in the door id; an order-dependent
    # host would show up as a different room here.
    sponsors = {(d["from_room"], d["to_room"]) for d in first["repair_doors"]}
    assert sponsors == {(d["from_room"], d["to_room"]) for d in second["repair_doors"]}
    assert all(d["door_id"].startswith("door_circulation_repair_")
               for d in first["repair_doors"])
