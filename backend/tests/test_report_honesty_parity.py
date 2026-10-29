"""Report/PDF honesty-parity contract tests.

The report UI and the PDF dossier consume the SAME AnalysisResponse. These
tests pin the shared contract:
  - the PDF warning banner lists exactly the warnings array (UI == PDF)
  - per-factor provenance status words in the PDF match the UI census rules
  - a null seismic zone can never render as a zone letter
"""
import io
import sys

sys.path.insert(0, ".")
from pypdf import PdfReader

from app.services.plan_verdict import plan_truth_labels
from app.services.report_service import generate_pdf_report, page1_plan_warnings


def _assert_banner_groups(text: str, plan: dict) -> None:
    """The grouped page-1 banner: same rows, under the canonical headings.

    Every page-1 row still survives into the PDF verbatim and in order; what
    changed is that the rows are now printed under CERTIFICATE FAILURES (n),
    LISTED DEVIATIONS (n) and UNRESOLVED BREACHES (n), each counted from the
    certificate-owned grouping rather than from one merged warning list.
    """
    labels = plan_truth_labels(plan)
    for key in ("certificate_failures", "listed_deviations", "unresolved_breaches"):
        assert labels["headings"][key] in text, f"heading missing from the PDF banner: {key}"
    assert labels["summary_line"] in text, "the banner must state its counts separately"
    # Certificate failures print verbatim, in order.
    positions = [text.find(f) for f in labels["certificate_failures"]]
    assert all(p >= 0 for p in positions), "a certificate failure row is missing"
    assert positions == sorted(positions), "certificate failure rows printed out of order"
    # Every page-1 row survives verbatim: as its own bullet (breach / advisory)
    # or as the quoted disclosure inside its listed-deviation row.
    page1 = page1_plan_warnings(plan.get("warnings"))
    for row in page1:
        assert row in text, f"page-1 row dropped from the PDF banner: {row[:90]}"
    # And the listed deviation rows keep their relative order.
    listed = [d["page1_row"] for d in labels["listed_deviations"] if d.get("page1_row")]
    listed_positions = [text.find(row) for row in listed]
    assert listed_positions == sorted(listed_positions), (
        "listed deviation rows printed out of order"
    )
    breaches = labels["unresolved_breaches"]
    breach_positions = [text.find(row) for row in breaches]
    assert breach_positions == sorted(breach_positions), "unresolved breach rows printed out of order"


def _base_data() -> dict:
    return {
        "request_id": "BW-PARITY",
        "timestamp": "2026-10-08T00:00:00Z",
        "coordinates": {"latitude": 12.97, "longitude": 77.59},
        "formatted_address": "Parity Probe Site",
        "overall_suitability_score": 72.0,
        "suitability_verdict": "Conditionally Suitable",
        "degraded_mode": True,
        "warnings": [
            "Microclimate telemetry unavailable. Latitudinal climate averages applied.",
            "Road network telemetry unavailable. Approach-side alignment bonus omitted.",
        ],
        "factors": [
            {
                "factor_id": "road_access",
                "name": "Road Access",
                "weight": 0.25,
                "raw_value": None,
                "unit": "meters",
                "score": 50.0,
                "status": "unknown",
                "details": "Telemetry unavailable this session.",
            },
            {
                "factor_id": "facility_proximity",
                "name": "Facility Proximity",
                "weight": 0.10,
                "raw_value": 1.0,
                "unit": "index",
                "score": 70.0,
                "status": "acceptable",
                "details": "Modelled proxy (not a measured survey).",
            },
            {
                "factor_id": "slope",
                "name": "Slope",
                "weight": 0.20,
                "raw_value": 2.5,
                "unit": "%",
                "score": 100.0,
                "status": "optimal",
                "details": "Flat to gentle grade measured from elevation samples.",
            },
        ],
        "cost_estimate": {
            "base_rate_per_sqft": 100,
            "base_cost_inr": 200000,
            "breakdown": [],
        },
        "recommendation_items": [],
        "detailed_recommendations": [],
        "risks": [],
    }


def _pdf_text(data: dict) -> str:
    buf = generate_pdf_report(data)
    raw = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(buf.getvalue())).pages)
    # pypdf inserts hard line-wraps inside a paragraph; normalize so verbatim
    # banner parity is asserted on the rendered words, not the wrap points.
    return " ".join(raw.split())


def test_warnings_banner_lists_every_warning_verbatim():
    text = _pdf_text(_base_data())
    assert "DATA DEGRADATION NOTICE" in text
    for w in _base_data()["warnings"]:
        assert w in text, f"warning missing from PDF banner: {w}"


def test_factor_provenance_words_match_ui_census_rules():
    text = _pdf_text(_base_data())
    # UNKNOWN: unmeasured factor
    assert "UNKNOWN" in text
    # ASSUMED: disclosed modelled-proxy details
    assert "ASSUMED" in text
    # VERIFIED: measured factor with clean details
    assert "VERIFIED" in text


def test_null_seismic_zone_never_renders_a_zone_letter():
    data = _base_data()
    data["hazard_profile"] = {
        "seismic": {
            "zone": None,
            "zone_factor": None,
            "standard": "BIS IS 1893:2016",
            "district": "Outside IS 1893 Jurisdiction",
            "event_count_display": "0",
            "confidence": "low",
        },
        "flood": {"pressure_level": "low", "confidence": "low"},
        "storm_cyclone": {"exposure_level": "low", "confidence": "low"},
        "overall_hazard_level": "low",
        "warnings": [],
    }
    text = _pdf_text(data)
    assert "NOT ASSESSED" in text, "null zone must surface the explicit not-assessed state"
    for zone in ("Zone II", "Zone III", "Zone IV", "Zone V"):
        assert zone not in text, f"fabricated {zone} leaked into the PDF"


PLAN_PAGE1_WARNINGS = [
    "ROOM-MIN: kitchen was squeezed below its 9.0 m² minimum on this plate.",
    "PROP-HARD: floor 0 kitchen 3.55 m² < 7.50 m² minimum; the certificate must fail.",
    "PROP-PLATE-CAP: kitchen aspect 1:9.85 beyond the 1.40x cap; justified per room.",
    "PROGRAMME-DEFICIT: the programme needs 122.7 m²; the plate provides 85.7 m².",
    "PROGRAMME-SQUEEZE: 12 rooms are below their minimums; the plan is drawn with a FAIL stamp.",
    "GATE-FAIL L1 Geometry & Statutory: room aspect exceeds the ontology hard band.",
    "PLATE-SHORT: the largest plate is 59.5 m² against a 78.2 m² programme.",
    "ROOM-OVERLAP: rooms 'bath_1' and 'bed_2' overlap by 5.02 m² on floor 0.",
    "SELECTION-FALLBACK: the selected partition cannot be drawn on this plate.",
    "PROP-IDEAL: living aspect 1:1.37 is outside the 1:1.20 ideal band (WARN).",
]


def _plan_payload() -> dict:
    return {
        "warnings": list(PLAN_PAGE1_WARNINGS),
        "validation_gate": {"overall_status": "FAIL"},
        "mathematical_certificate": {"is_valid": False},
    }


def test_print_page1_plan_warnings_equal_pdf_banner_verbatim():
    """The print banner list and the PDF page-1 list are the same strings.

    `page1_plan_warnings` is the backend mirror of
    frontend/src/services/planWarnings.ts; the in-app Print Report now reads
    the same merged list.  Every page-1 row must survive into the PDF verbatim
    (normalized only for pypdf's hard wraps), in order, with nothing dropped.
    """
    data = _base_data()
    data["warnings"] = [
        "Microclimate telemetry unavailable. Latitudinal climate averages applied.",
    ]
    expected = page1_plan_warnings(PLAN_PAGE1_WARNINGS)
    assert expected == PLAN_PAGE1_WARNINGS

    plan = _plan_payload()
    buf = generate_pdf_report(data, floor_plan=plan)
    raw = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(buf.getvalue())).pages)
    text = " ".join(raw.split())
    assert "PLAN NOT CERTIFIED - DRAWN WITH A FAIL STAMP" in text
    # The print banner and the PDF carry the same rows under the same headings:
    # nothing added, nothing dropped, nothing reworded between the two surfaces.
    _assert_banner_groups(text, plan)


def test_plan_verdict_survives_a_valid_certificate_with_named_deficits():
    """A valid certificate does not neutralise named deficits.

    This fixture carries ROOM-MIN / PROP-HARD / GATE-FAIL rows.  It used to
    render the amber "PLAN ADVISORIES" banner because the certificate was
    valid, while the plan card rendered a red FAIL stamp.  One verdict now
    governs: named deficits mean NOT-CERTIFIED-FAIL-STAMP on every surface,
    and the page-1 rows are still printed in full and verbatim.
    """
    plan = _plan_payload()
    plan["validation_gate"] = {"overall_status": "WARN"}
    plan["mathematical_certificate"] = {"is_valid": True}
    buf = generate_pdf_report(_base_data(), floor_plan=plan)
    raw = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(buf.getvalue())).pages)
    text = " ".join(raw.split())
    assert "PLAN NOT CERTIFIED - DRAWN WITH A FAIL STAMP" in text
    assert "Plan verdict: NOT-CERTIFIED-FAIL-STAMP" in text
    # The certificate records no failure rows here: the FAIL stamp rests on the
    # unresolved breaches, and the banner must say so in those terms.
    labels = plan_truth_labels(plan)
    assert labels["counts"]["certificate_failures"] == 0
    assert "CERTIFICATE FAILURES (0)" in text
    assert labels["counts"]["unresolved_breaches"] > 0
    _assert_banner_groups(text, plan)


def test_plan_advisories_page1_list_survives_a_certified_plan():
    """Only listed, within-cap deviations: certified, same verbatim page-1 list."""
    advisory_rows = [
        "PROP-CEILING: puja is 9.6 m² against its 6.0 m² declared ceiling.",
        "PLINTH: the built-up target (78.2 m²) exceeds the programme need (63.0 m²).",
    ]
    plan = {
        "warnings": advisory_rows,
        "validation_gate": {"overall_status": "WARN"},
        "mathematical_certificate": {"is_valid": True},
    }
    buf = generate_pdf_report(_base_data(), floor_plan=plan)
    raw = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(buf.getvalue())).pages)
    text = " ".join(raw.split())
    assert "PLAN CERTIFIED — LISTED DEVIATIONS PRINTED" in text
    assert "Plan verdict: CERTIFIED" in text
    # A certified plan prints CERTIFICATE FAILURES (0) and its two listed,
    # within-cap deviations under LISTED DEVIATIONS — never under failures.
    labels = plan_truth_labels(plan)
    assert labels["counts"]["certificate_failures"] == 0
    assert labels["counts"]["listed_deviations"] == 2
    assert labels["counts"]["unresolved_breaches"] == 0
    _assert_banner_groups(text, plan)


def test_assessed_zone_renders_normally():
    data = _base_data()
    data["hazard_profile"] = {
        "seismic": {
            "zone": "Zone II",
            "zone_factor": 0.10,
            "standard": "BIS IS 1893:2016",
            "district": "Bengaluru Urban",
            "event_count_display": "2",
            "confidence": "high",
        },
        "flood": {"pressure_level": "low", "confidence": "high"},
        "storm_cyclone": {"exposure_level": "low", "confidence": "high"},
        "overall_hazard_level": "low",
        "warnings": [],
    }
    text = _pdf_text(data)
    assert "Zone II" in text
    assert "NOT ASSESSED" not in text
