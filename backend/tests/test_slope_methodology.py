"""The slope methodology popover is generated from the engine table.

The report used to disclose a band table the engine did not implement
("100 at ≤2%, −5 per % up to 6%, …").  These pins fail if either side moves
without the other: every band row is evaluated, every row's numbers must appear
in the generated sentence, and the served disclosure must be that sentence.
"""

import pytest

from app.services.methodology import (
    SLOPE_BANDS,
    methodology_notes,
    slope_band_for,
    slope_formula_text,
    slope_score_for,
)
from app.services.suitability_service import calculate_slope_score


def _probe_values(band):
    """Values governed by this band (both edges included)."""
    upper = band["upper_pct"]
    lower = band["lower_pct"]
    if lower is None:
        return [0.0, 1.5, 3.0]
    if upper is None:
        return [lower + 0.1, lower + 10.0, lower + 40.0]
    return [lower + 0.1, lower + (upper - lower) / 2, upper]


@pytest.mark.parametrize("band", SLOPE_BANDS)
def test_engine_evaluates_the_disclosed_row(band):
    for slope in _probe_values(band):
        expected = round(slope_score_for(slope, band), 1)
        score, status, details = calculate_slope_score(slope)
        assert score == expected, (slope, score, expected)
        assert status == band["status"]
        assert details == band["detail"].format(slope=slope)


def test_band_assignment_is_monotonic_across_boundaries():
    for band in SLOPE_BANDS:
        upper = band["upper_pct"]
        lower = band["lower_pct"]
        if upper is not None:
            assert slope_band_for(upper) is band
        if lower is not None:
            assert slope_band_for(lower + 1e-6) is band


def test_disclosure_names_every_row_of_the_table():
    text = slope_formula_text()
    assert text.startswith("Piecewise linear score:")
    for band in SLOPE_BANDS:
        assert f"{band['anchor_score']:g}" in text
        assert f"{band['rate_per_pct']:g}" in text
        assert f"{band['floor_score']:g}" in text
        if band["upper_pct"] is not None:
            assert f"{band['upper_pct']:g}%" in text
    # The old, wrong disclosure must never come back.
    assert "≤2%" not in text
    assert "−5 per %" not in text


def test_disclosure_reproduces_the_measured_value():
    # Measured cross-check: slope 12.12% scored 55.6 (= 70 − 3.5 × 4.12).
    assert calculate_slope_score(12.12)[0] == 55.6
    assert "3.5 × (grade − 8)" in slope_formula_text()


def test_served_disclosure_is_the_generated_sentence():
    assert methodology_notes()["slope"] == slope_formula_text()
