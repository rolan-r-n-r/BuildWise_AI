"""
test_invariant_sweep_standing.py - the adversarial sweep as a STANDING harness
==============================================================================
``scripts/qa_invariant_sweep.py`` runs the full 28-case adversarial matrix; that is
too slow for every test run. This module keeps the sweep wired into the suite by
re-running two pinned reproductions through the REAL sweep code:

  * T1-tiny-8x10 (seed 1003) - the refusal repro. It previously produced four
    "violations" (no land report, no gate, no certificate, no T1 programme)
    against a generation that had correctly refused the brief. The refusal now
    carries a full L1-L15 FAIL gate, and the sweep judges it on
    refusal-honesty (I10) instead of on rooms it never drew.
  * T1-rect-20x20 (seed 1002) - a solved plate that used to violate
    I5-SCHEDULE-AREA-FIELD and I5-SVG-SCHEDULE-TRUNCATED. Both must stay closed:
    the schedule publishes gross/clear areas separately and the sheet prints
    every room.

Run the full matrix with:
    python scripts/qa_invariant_sweep.py --quick
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[2]
for _p in (str(BACKEND), str(BACKEND / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from scripts import qa_invariant_sweep as sweep  # type: ignore[import-not-found]
except ImportError:
    import qa_invariant_sweep as sweep  # type: ignore[import-not-found]  # noqa: E402

_PLOTS = {p["key"]: p for p in sweep.PLOTS}


def _run(typ_key: str, typology: str, plot_key: str, seed: str):
    sweep.violations.clear()
    sweep.disclosed.clear()
    sweep.case_rows.clear()
    row = sweep.run_case(
        typ_key, typology, _PLOTS[plot_key], 1, "high", seed, quick=True
    )
    return row, list(sweep.violations)


@pytest.fixture(scope="module")
def declined_case():
    return _run("T1", "residential_single", "tiny-8x10", "1003")


@pytest.fixture(scope="module")
def rect_case():
    return _run("T1", "residential_single", "rect-20x20", "1002")


def test_refusal_repro_passes_sweep_as_honest_decline(declined_case):
    row, violations = declined_case
    assert row["declined"] is True, "the 8x10 m repro is expected to be refused"
    assert [v["code"] for v in violations] == [], (
        "a refusal must satisfy the refusal-honesty invariants (no land report / "
        "gate / certificate is EXPECTED when nothing was solved): "
        f"{[v['code'] for v in violations]}"
    )
    assert row["decline"]["gate"] == "FAIL"


def test_listed_minimum_breach_is_disclosed_not_failed():
    """Disclosed taxonomy: an NBC-01-listed shortfall is counted in DISCLOSED.

    T1 rect-12x15 draws a living room just under the catalogue width; the
    certificate lists that as NBC-01.  The sweep must report it in the disclosed
    register and keep I2 clean, otherwise the sweep re-fails a breach the
    certificate already publishes.
    """
    sweep.violations.clear()
    sweep.disclosed.clear()
    sweep.run_case("T1", "residential_single", _PLOTS["rect-12x15"], 1, "high", "1002", quick=True)
    codes = {v["code"] for v in sweep.disclosed}
    assert "I2-MINIMA-DISCLOSED" in codes or "I2-CLEAR-MINIMA-DISCLOSED" in codes, codes
    assert not [v for v in sweep.violations if v["code"].startswith("I2")], [
        v["detail"] for v in sweep.violations if v["code"].startswith("I2")
    ]


def test_unlisted_minimum_breach_still_fails():
    """A shortfall with no listed relaxation is a TRUE failure, not disclosed.

    Synthetic on purpose: The engine lists EVERY squeezed room on the room itself, so
    no generated plate can be relied on to produce an unlisted breach any more.
    The taxonomy still has to fail one when it exists - otherwise the engine's
    listing would make I2 structurally unable to speak - so the check is pinned
    on a bare room, then re-run with an NBC-01 entry to prove it flips to the
    DISCLOSED register.
    """
    def _resp(relaxations):
        room = SimpleNamespace(
            room_id="synthetic_bath_F0",
            zone_category="service",
            relaxations=relaxations,
            identity=None,
            area_sqm=2.50,
        )
        floor = SimpleNamespace(rooms=[room], room_schedule=[], floor_index=0)
        return SimpleNamespace(multi_storey=SimpleNamespace(floors=[floor]))

    row = {"below_minima": [{
        "room_id": "synthetic_bath_F0",
        "area_sqm": 2.50,
        "min_area_sqm": 3.50,
        "clear_min_width_m": 1.00,
        "min_width_m": 1.50,
        "ontology_id": "bath_1",
    }]}

    sweep.violations.clear()
    sweep.disclosed.clear()
    sweep.check_minima("SYN-unlisted-F1", _resp([]), row, warns=[])
    assert [v["code"] for v in sweep.violations] == ["I2-MINIMA"], [
        v["detail"] for v in sweep.disclosed
    ]

    sweep.violations.clear()
    sweep.disclosed.clear()
    sweep.check_minima(
        "SYN-listed-F1", _resp([{"rule_id": "NBC-01", "rationale": "synthetic"}]), row,
        warns=[],
    )
    assert not sweep.violations, [v["detail"] for v in sweep.violations]
    assert [v["code"] for v in sweep.disclosed] == ["I2-MINIMA-DISCLOSED"]

    # And the engine's own squeeze is listed: the trapezoid T2 plate draws
    # sub-catalogue unit rooms and every one of them carries NBC-01, so the
    # sweep reports no UNLISTED minimum breach there.
    sweep.violations.clear()
    sweep.disclosed.clear()
    sweep.run_case("T2", "residential_apartment", _PLOTS["trapezoid-14x16"], 1, "high", "1013", quick=True)
    assert not [v for v in sweep.violations if v["code"].startswith("I2")], [
        v["detail"] for v in sweep.violations if v["code"].startswith("I2")
    ]


def test_rect_repro_passes_sweep_with_zero_violations(rect_case):
    row, violations = rect_case
    assert not row["declined"], "the 20x20 m repro must be solved, not refused"
    assert [v["code"] for v in violations] == [], (
        f"sweep regressions on {row['case_id']}: "
        + "; ".join(f"{v['code']} {v['detail']}" for v in violations)
    )
