"""Machine-readable methodology tables.

The report's methodology popovers are the disclosure that lets a reviewer
validate an engineering score.  The slope popover used to be a hand-written
string ("100 at ≤2%, −5 per % up to 6%, …") that described a band table the
engine did not implement.  The band table below is now the ONE
definition: ``calculate_slope_score`` evaluates it, and ``slope_formula_text``
renders the same rows into the sentence the report shows.  A pin asserts the
two agree, so the disclosure cannot drift from the calculation again.

Scores are 0-100.  Each band applies between ``lower_pct`` (exclusive, except
the first band) and ``upper_pct`` (inclusive); the score runs linearly from
``anchor_score`` at the lower bound at ``rate_per_pct`` per percentage point,
never below ``floor_score``.
"""

from typing import Any, Dict, Tuple

# Band rows are ordered; the final band is open-ended (upper_pct = None).
SLOPE_BANDS: Tuple[Dict[str, Any], ...] = (
    {
        "upper_pct": 3.0,
        "lower_pct": None,
        "anchor_score": 100.0,
        "rate_per_pct": 0.0,
        "floor_score": 100.0,
        "status": "optimal",
        "detail": (
            "Flat terrain ({slope}% grade). Ideal for conventional shallow "
            "footings with minimal cut-and-fill."
        ),
    },
    {
        "upper_pct": 8.0,
        "lower_pct": 3.0,
        "anchor_score": 85.0,
        "rate_per_pct": 3.0,
        "floor_score": 70.0,
        "status": "optimal",
        "detail": (
            "Gentle slope ({slope}% grade). Natural storm drainage advantage; "
            "standard stepped footings recommended."
        ),
    },
    {
        "upper_pct": 15.0,
        "lower_pct": 8.0,
        "anchor_score": 70.0,
        "rate_per_pct": 3.5,
        "floor_score": 45.0,
        "status": "acceptable",
        "detail": (
            "Moderate slope ({slope}% grade). Requires site benching, reinforced "
            "retaining structures, and slope stability analysis."
        ),
    },
    {
        "upper_pct": 25.0,
        "lower_pct": 15.0,
        "anchor_score": 45.0,
        "rate_per_pct": 2.5,
        "floor_score": 20.0,
        "status": "critical",
        "detail": (
            "Steep slope ({slope}% grade). Significant excavation costs, stepped "
            "terracing, and deep pier/raft foundations required."
        ),
    },
    {
        "upper_pct": None,
        "lower_pct": 25.0,
        "anchor_score": 20.0,
        "rate_per_pct": 1.0,
        "floor_score": 10.0,
        "status": "critical",
        "detail": (
            "Extreme slope ({slope}% grade). Severe landslide/erosion "
            "vulnerability. Unsuitable for standard civil structures."
        ),
    },
)


def slope_band_for(slope_pct: float) -> Dict[str, Any]:
    """Return the band row that governs ``slope_pct`` (last band is open-ended)."""
    for band in SLOPE_BANDS:
        upper = band["upper_pct"]
        if upper is None or slope_pct <= upper:
            return band
    return SLOPE_BANDS[-1]


def slope_score_for(slope_pct: float, band: Dict[str, Any]) -> float:
    """Evaluate one band row at ``slope_pct`` (same arithmetic as the engine)."""
    lower = band["lower_pct"]
    if lower is None or band["rate_per_pct"] == 0.0:
        return float(band["anchor_score"])
    raw = band["anchor_score"] - (slope_pct - lower) * band["rate_per_pct"]
    return max(float(band["floor_score"]), raw)


def slope_formula_text() -> str:
    """Render the band table as the sentence the report's popover shows."""
    first = SLOPE_BANDS[0]
    parts = [f"{first['anchor_score']:g} at ≤{first['upper_pct']:g}% grade"]
    for band in SLOPE_BANDS[1:]:
        segment = (
            f"{band['anchor_score']:g} − {band['rate_per_pct']:g} × "
            f"(grade − {band['lower_pct']:g})"
        )
        if band["upper_pct"] is None:
            segment += f" to a floor of {band['floor_score']:g}"
        else:
            segment += (
                f" down to {band['floor_score']:g} through "
                f"{band['upper_pct']:g}%"
            )
        parts.append(segment)
    return "Piecewise linear score: " + "; ".join(parts) + "."


def methodology_notes() -> Dict[str, str]:
    """Generated disclosure strings keyed by factor id, served with /api/analyze."""
    return {"slope": slope_formula_text()}
