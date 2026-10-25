"""
test_plan_verdict_parity.py - one plan verdict, three surfaces.

Before this contract the same generation was read three ways: the plan card
turned red with a "FAIL stamp", the certificate panel said "CERTIFIED ·
ADVISORIES", and the exported PDF said "PLAN ADVISORIES".  The card even
promised the export carried a FAIL stamp it did not carry.

The verdict is now computed once, server-side (`app.services.plan_verdict`),
published as `plan_verdict`, and rendered verbatim by the card, the
certificate panel and the PDF.  These tests pin the computation, the PDF
rendering, and the storey/coverage cells of the page-1 spec grid.
"""
import io

from pypdf import PdfReader

from app.services.plan_verdict import (
    ADVISORY,
    CERTIFIED,
    FAIL_STAMP,
    compute_plan_verdict,
    page1_plan_warnings,
)
from app.services.report_service import generate_pdf_report

# The real 15 warnings from a certified-certificate generation whose rooms
# exceeded their catalogue maxima.  This is the exact payload that produced
# the card/PDF split.
ROOM_MAX_WARNINGS = [
    "RULE-FP-02: Wing 'wing_b' not present in footprint decomposition (single-rectangle plate) - floor plate mask for level 0 ignored.",
    "PROP-SPLIT: living split into 2 parts (aspect 1:2.38 over the 1:1.80 hard band); each part is inside the declared band.",
    "PROP-CEILING: bath_1 is 9.8 m² against its 8.0 m² declared ceiling; sanitary rooms are governed by fixture fit and are disclosed, not subdivided.",
    "PROP-IDEAL: bath_1 aspect 1:1.80 is outside the 1:1.50 ideal band but inside the 1:2.00 hard band (WARN).",
    "ROOM-MAX: dining_0_1 is 19.1 m², above its 14.0 m² catalogue maximum on floor 0; the 78.2 m² plate stretched it past its band.",
    "ROOM-MAX: bath_1 is 9.8 m², above its 6.0 m² catalogue maximum on floor 0; the 78.2 m² plate stretched it past its band.",
    "Swing resolution: Flipped door 'door_bath_1' (1.28,4.00,inward_right -> 1.28,4.00,inward_left).",
    "CIRC-REPAIR: added a door living -> dining_0_1 so no room is unreachable from the entry",
    "LAND-03 Circulation ratio 0.0% is outside the 12–20% target band.",
    "PLINTH: the built-up target (78.2 m²) exceeds the programme need (59.5 m²); the declared upgrade ladder absorbed 0.0 m² and 18.8 m² is left unbuilt.",
]

ADVISORY_WARNINGS = [
    "PROP-CEILING: puja is 9.6 m² against its 6.0 m² declared ceiling; the overage is disclosed.",
    "PLINTH: the built-up target (78.2 m²) exceeds the programme need (63.0 m²).",
    "Swing resolution: Flipped door 'door_kitchen' (5.68,4.00,inward_right -> 5.68,4.00,inward_left).",
]


def _base_data(storeys: int | None = None) -> dict:
    data = {
        "request_id": "BW-VERDICT",
        "timestamp": "2026-10-24T00:00:00Z",
        "coordinates": {"latitude": 12.97, "longitude": 77.59},
        "formatted_address": "Verdict Probe Site",
        "overall_suitability_score": 62.4,
        "suitability_verdict": "Conditionally Suitable",
        "degraded_mode": False,
        "warnings": [],
        "factors": [
            {
                "factor_id": "slope",
                "name": "Topographic Slope",
                "weight": 0.25,
                "raw_value": 12.1,
                "unit": "%",
                "score": 55.6,
                "status": "acceptable",
                "details": "Moderate slope.",
            }
        ],
        "cost_estimate": {"base_rate_per_sqft": 2200, "base_cost_inr": 4400000, "breakdown": []},
        "recommendation_items": [],
        "detailed_recommendations": [],
        "risks": [],
        "quality_grade": "standard",
    }
    if storeys is not None:
        data["storeys"] = storeys
    return data


def _plan(warnings, *, cert_valid=True, gate="WARN", verdict=None):
    plan = {
        "warnings": list(warnings),
        "validation_gate": {"overall_status": gate},
        "mathematical_certificate": {"is_valid": cert_valid},
    }
    if verdict:
        plan["plan_verdict"] = verdict
    return plan


def _pdf_text(plan: dict, storeys: int | None = None) -> str:
    buf = generate_pdf_report(_base_data(storeys), floor_plan=plan)
    raw = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(buf.getvalue())).pages)
    return " ".join(raw.split())


# --------------------------------------------------------------------------- #
# 1. The computation itself
# --------------------------------------------------------------------------- #

def test_certified_when_nothing_is_outstanding():
    assert compute_plan_verdict(_plan([], cert_valid=True, gate="PASS")) == CERTIFIED


def test_advisory_when_only_listed_relaxations_are_named():
    assert compute_plan_verdict(_plan(ADVISORY_WARNINGS, cert_valid=True, gate="WARN")) == ADVISORY


def test_room_max_on_a_valid_certificate_is_a_fail_stamp():
    """The exact regression: ROOM-MAX must not read as a plain advisory."""
    assert compute_plan_verdict(_plan(ROOM_MAX_WARNINGS, cert_valid=True, gate="WARN")) == FAIL_STAMP


def test_withheld_certificate_is_a_fail_stamp():
    assert compute_plan_verdict(_plan([], cert_valid=False, gate="WARN")) == FAIL_STAMP


def test_failed_gate_is_a_fail_stamp():
    assert compute_plan_verdict(_plan([], cert_valid=True, gate="FAIL")) == FAIL_STAMP


def test_resolver_noise_alone_never_escalates():
    noise = [
        "Swing resolution: Flipped door 'x' (1,1,inward_right -> 1,1,inward_left).",
        "CIRC-REPAIR: added a door a -> b",
        "LAND-03 Circulation ratio 0.0% is outside the 12–20% target band.",
        "RULE-FP-02: Wing 'wing_b' not present in footprint decomposition.",
    ]
    assert compute_plan_verdict(_plan(noise, cert_valid=True, gate="WARN")) == CERTIFIED
    assert page1_plan_warnings(noise) == []


# --------------------------------------------------------------------------- #
# 2. The three surfaces render the SAME token
# --------------------------------------------------------------------------- #

def test_pdf_renders_the_certified_verdict_verbatim():
    text = _pdf_text(_plan([], cert_valid=True, gate="PASS"))
    assert "Plan verdict: CERTIFIED" in text
    assert "PLAN CERTIFIED" in text


def test_pdf_renders_the_advisory_verdict_verbatim():
    text = _pdf_text(_plan(ADVISORY_WARNINGS, cert_valid=True, gate="WARN"))
    assert "Plan verdict: ADVISORY" in text
    assert "PLAN ADVISORIES" in text


def test_pdf_renders_the_fail_stamp_verdict_verbatim():
    text = _pdf_text(_plan(ROOM_MAX_WARNINGS, cert_valid=True, gate="WARN"))
    assert "Plan verdict: NOT-CERTIFIED-FAIL-STAMP" in text
    assert "PLAN NOT CERTIFIED - DRAWN WITH A FAIL STAMP" in text


def test_pdf_consumes_the_published_verdict_rather_than_re_deriving_it():
    """A payload whose verdict is ADVISORY renders ADVISORY even though its
    warnings would otherwise escalate: the server's verdict wins."""
    plan = _plan(ROOM_MAX_WARNINGS, cert_valid=True, gate="WARN", verdict="ADVISORY")
    text = _pdf_text(plan)
    assert "Plan verdict: ADVISORY" in text
    assert "NOT-CERTIFIED-FAIL-STAMP" not in text
    # ...while the rows themselves are still printed in full.
    for line in ROOM_MAX_WARNINGS:
        if page1_plan_warnings([line]):
            assert line in text, f"page-1 row dropped: {line}"


# --------------------------------------------------------------------------- #
# 3. The page-1 spec grid prints the analysed project
# --------------------------------------------------------------------------- #

def test_single_storey_pdf_says_ground_floor_not_g_plus_1():
    text = _pdf_text(_plan([], cert_valid=True, gate="PASS"), storeys=1)
    assert "Storeys Ground Floor" in text
    assert "G+1 Storeys" not in text
    assert "G+0 Storeys" not in text


def test_two_storey_pdf_says_g_plus_1():
    text = _pdf_text(_plan([], cert_valid=True, gate="PASS"), storeys=2)
    assert "G+1 Storeys" in text


def test_three_storey_pdf_says_g_plus_2():
    text = _pdf_text(_plan([], cert_valid=True, gate="PASS"), storeys=3)
    assert "G+2 Storeys" in text


def test_slope_is_its_own_labelled_cell_not_a_coverage_parenthetical():
    text = _pdf_text(_plan([], cert_valid=True, gate="PASS"), storeys=1)
    assert "Terrain Slope 12.1%" in text
    assert "Ground Coverage 60.0% Terrain Slope" in text
    assert "% Slope)" not in text
