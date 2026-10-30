"""
test_plan_verdict_parity.py - one plan verdict, three surfaces.

Before this contract the same generation was read three ways: the plan card
turned red with a "FAIL stamp", the certificate panel said "CERTIFIED ·
ADVISORIES", and the exported PDF said "PLAN ADVISORIES".  The card even
promised the export carried a FAIL stamp it did not carry.

The verdict is now computed once, server-side (`app.services.plan_verdict`),
published as `plan_verdict`, and rendered verbatim by the card, the
certificate panel and the PDF.  The truth labels are owned by the same module:
CERTIFICATE FAILURES is exactly the certificate's own list, LISTED DEVIATIONS
is the listed within-cap rows, and UNRESOLVED BREACHES is what a FAIL stamp
rests on.  These tests pin the computation, the three groups and their counts
across the screen/print/PDF surfaces, the PDF rendering, and the
storey/coverage cells of the page-1 spec grid.
"""
import io
import json
import re
from pathlib import Path

from pypdf import PdfReader

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.strategy_escalation import _CACHE, solve_with_escalation
from app.services.plan_verdict import (
    ADVISORY,
    CERTIFICATE_FAILURES_HEADING,
    CERTIFIED,
    CERTIFIED_DEFINITION,
    FAIL_STAMP,
    LISTED_DEVIATIONS_HEADING,
    TRUTH_SUMMARY_TEMPLATE,
    UNRESOLVED_BREACHES_HEADING,
    compute_plan_verdict,
    page1_plan_warnings,
    plan_truth_labels,
    plan_verdict_reasons,
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


def test_certified_when_only_listed_within_cap_relaxations_are_named():
    """Listed, within-cap deviations are printed, not refused."""
    assert compute_plan_verdict(_plan(ADVISORY_WARNINGS, cert_valid=True, gate="WARN")) == CERTIFIED


def test_certified_definition_is_identical_on_backend_and_frontend():
    """Legend text == policy text == copy deck, byte-for-byte."""
    root = Path(__file__).resolve().parents[2]
    taxonomy = (root / "frontend/src/components/report/statusTaxonomy.ts").read_text(
        encoding="utf-8"
    )
    landing = (root / "frontend/src/landing/StandardsSection.tsx").read_text(
        encoding="utf-8"
    )
    assert f"export const CERTIFIED_DEFINITION = '{CERTIFIED_DEFINITION}';" in taxonomy
    assert "CERTIFIED_DEFINITION" in landing
    assert CERTIFIED_DEFINITION in _pdf_text(_plan([], cert_valid=True, gate="PASS"))


def test_room_max_on_a_valid_certificate_is_a_fail_stamp():
    """The exact regression: ROOM-MAX must not read as a plain advisory."""
    assert compute_plan_verdict(_plan(ROOM_MAX_WARNINGS, cert_valid=True, gate="WARN")) == FAIL_STAMP


def test_withheld_certificate_is_a_fail_stamp():
    assert compute_plan_verdict(_plan([], cert_valid=False, gate="WARN")) == FAIL_STAMP


def test_failed_gate_is_a_fail_stamp():
    assert compute_plan_verdict(_plan([], cert_valid=True, gate="FAIL")) == FAIL_STAMP


def test_unresolved_l14_shortfall_withholds_certification_on_every_surface():
    """Release-closure pin: a mandatory capacity finding cannot sit beside CERTIFIED.

    The certificate here even *claims* validity.  A hard-layer FAIL (L14 is in
    HARD_FAIL_LAYERS) must outvote it, the finding must stay on page-1 rows, and
    the PDF must print the same fail stamp.
    """
    finding = (
        "Stair exit width 1.00m serves ~50 occupants < stair load 60 "
        "(upper storeys; building load 80)"
    )
    row = f"GATE-FAIL L14 Fire & Egress: {finding}"
    plan = {
        "warnings": [row],
        "validation_gate": {
            "overall_status": "FAIL",
            "layers": [{"layer_id": "L14", "status": "FAIL", "findings": [finding]}],
        },
        "mathematical_certificate": {"is_valid": True, "failures": []},
    }
    assert compute_plan_verdict(plan) == FAIL_STAMP
    assert page1_plan_warnings(plan["warnings"]) == [row]
    assert row in plan_verdict_reasons(plan)
    text = _pdf_text(plan)
    assert "Plan verdict: NOT-CERTIFIED-FAIL-STAMP" in text
    assert "stair load 60" in text


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


def test_pdf_renders_the_certified_with_listed_deviation_verdict_verbatim():
    text = _pdf_text(_plan(ADVISORY_WARNINGS, cert_valid=True, gate="WARN"))
    assert "Plan verdict: CERTIFIED" in text
    assert "PLAN CERTIFIED" in text
    # The listed deviations still appear on page 1.
    for line in ADVISORY_WARNINGS:
        if page1_plan_warnings([line]):
            assert line in text


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
    assert "Plan verdict: NOT-CERTIFIED-FAIL-STAMP" not in text
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


# --------------------------------------------------------------------------- #
# 4. Truth labels: the certificate-failure group is the certificate's own
# --------------------------------------------------------------------------- #
#
# The bug these pins lock down: a CERTIFIED plan was headed "CERTIFICATE
# FAILURES 14" while its certificate held 0 failures - those rows were listed,
# within-cap deviations (relaxations the certificate accepts).  The grouping is
# owned by `plan_verdict.plan_truth_labels`:
#
#   CERTIFICATE FAILURES (n)   exactly len(certificate.failures), never a
#                              warning total, never a deviation count.
#   LISTED DEVIATIONS (m)      the listed, within-cap deviation rows.
#   UNRESOLVED BREACHES (k)    the rows a FAIL stamp actually rests on.
#
# Every pin here reads the real objects (certificate rows, deviation rows,
# page-1 rows), not a string that merely mentions a heading.

ROOT = Path(__file__).resolve().parents[2]
TS_SOURCE = ROOT / "frontend" / "src" / "services" / "warningReport.ts"

ROOM_MAX_BEYOND_CAP = (
    "ROOM-MAX: dining_0_1 is 23.3 m\u00b2, above its 14.0 m\u00b2 catalogue maximum "
    "on floor 0; the 240.0 m\u00b2 plate stretched it past its band."
)
ROOM_MIN_LISTED = (
    "ROOM-MIN: core_staircase_primary_F0 is 7.2 m\u00b2, below its 8.0 m\u00b2 catalogue "
    "minimum on floor 0; the 82.8 m\u00b2 plate cannot hold this programme comfortably."
)
PROP_HARD = (
    "PROP-HARD: floor 0 living_F0 3.00 m clear < 3.60 m minimum; the declared overflow "
    "moves cannot resolve it on this plate and the certificate must fail."
)
PLINTH_NOTE = (
    "PLINTH: the built-up target (129.6 m\u00b2) exceeds the programme need (122.7 m\u00b2)."
)


def _certified_payload() -> dict:
    """A certified plan whose only plan rows are listed deviations."""
    return {
        "plan_verdict": "CERTIFIED",
        "mathematical_certificate": {"is_valid": True, "failures": []},
        "validation_gate": {"overall_status": "WARN"},
        # A certified plan carries no hard failure: only listed deviations.
        "warnings": [ROOM_MIN_LISTED, PLINTH_NOTE],
        "multi_storey": {
            "floors": [
                {
                    "floor_index": 0,
                    "rooms": [
                        {
                            "room_id": "core_staircase_primary_F0",
                            "relaxations": [
                                {
                                    "rule_id": "NBC-01",
                                    "rationale": (
                                        "gross area 7.18 is below the catalogue minimum 8.00 "
                                        "(short by 0.82); the 82.8 m\u00b2 plate cannot hold the "
                                        "requested programme within its catalogue minimum. Listed "
                                        "as a relaxation on this room."
                                    ),
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


def _fail_stamped_payload() -> dict:
    """A fail-stamped plan: a withheld certificate names its own failures."""
    payload = _certified_payload()
    payload["plan_verdict"] = "NOT-CERTIFIED-FAIL-STAMP"
    payload["mathematical_certificate"] = {
        "is_valid": False,
        "failures": [
            "NBC-01 Room minimums: living_F0: 2.71 m clear < 3.60 m",
            "GATE-L16 Proportion & Surplus: F0 living_F0: 1:2.80 against a 1:1.80 band",
        ],
    }
    payload["validation_gate"] = {"overall_status": "FAIL"}
    payload["warnings"] = [
        PROP_HARD,
        ROOM_MAX_BEYOND_CAP,   # 23.3 / 14.0 = 1.66x - beyond the 1.40x cap
        ROOM_MIN_LISTED,       # room carries a structured relaxation -> listed
        PLINTH_NOTE,           # a listed within-cap disclosure, not a failure
    ]
    return payload


def _pdf_page1_text(plan: dict, pages: int = 2) -> str:
    data = {
        "request_id": "BW-TRUTH-LABELS",
        "timestamp": "2026-10-28T00:00:00Z",
        "coordinates": {"latitude": 12.97, "longitude": 77.59},
        "formatted_address": "Truth-label pin",
        "overall_suitability_score": 80.0,
        "suitability_verdict": "Suitable",
        "warnings": [],
        "factors": [],
        "cost_estimate": {"base_rate_per_sqft": 100, "base_cost_inr": 200000, "breakdown": []},
        "recommendation_items": [],
        "detailed_recommendations": [],
        "risks": [],
    }
    buf = generate_pdf_report(data, floor_plan=plan)
    raw = "".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(buf.getvalue())).pages[:pages]
    )
    return " ".join(raw.split())


def _pdf_all_text(plan: dict) -> str:
    """The whole report: page-1 summary plus Appendix A's complete ledger."""
    data = {
        "request_id": "BW-TRUTH-LABELS",
        "timestamp": "2026-10-28T00:00:00Z",
        "coordinates": {"latitude": 12.97, "longitude": 77.59},
        "formatted_address": "Truth-label pin",
        "overall_suitability_score": 80.0,
        "suitability_verdict": "Suitable",
        "warnings": [],
        "factors": [],
        "cost_estimate": {"base_rate_per_sqft": 100, "base_cost_inr": 200000, "breakdown": []},
        "recommendation_items": [],
        "detailed_recommendations": [],
        "risks": [],
    }
    buf = generate_pdf_report(data, floor_plan=plan)
    raw = "".join(
        page.extract_text() or "" for page in PdfReader(io.BytesIO(buf.getvalue())).pages
    )
    return " ".join(raw.split())


def test_certified_plan_reports_zero_certificate_failures():
    plan = _certified_payload()
    labels = plan_truth_labels(plan)
    cert = plan["mathematical_certificate"]
    assert labels["certificate_failures"] == cert["failures"] == []
    assert labels["counts"]["certificate_failures"] == 0
    assert labels["headings"]["certificate_failures"] == "CERTIFICATE FAILURES (0)"
    # The listed deviations must never be counted as certificate failures.
    # Two rows are listed: the ROOM-MIN with a structured relaxation on the
    # room, and the PLINTH reconciliation (a declared within-cap disclosure).
    assert labels["counts"]["listed_deviations"] == 2
    assert labels["counts"]["unresolved_breaches"] == 0


def test_listed_deviation_rows_are_the_rows_displayed():
    plan = _certified_payload()
    labels = plan_truth_labels(plan)
    shown = [d for d in labels["listed_deviations"]]
    assert len(shown) == labels["counts"]["listed_deviations"]
    # The room's structured relaxation is represented by its page-1 row, so it
    # is not shown twice; a deviation with no page-1 row is shown as a row.
    assert shown[0]["room_id"] == "core_staircase_primary_F0"
    assert shown[0]["rule_id"] == "ROOM-MIN"
    assert shown[0]["page1_row"] == ROOM_MIN_LISTED
    assert shown[0]["reason"] == ROOM_MIN_LISTED
    # PLINTH is a listed disclosure, and it is a row too.
    assert any(d["reason"] == PLINTH_NOTE for d in shown)
    assert [d["page1_row"] for d in shown if d.get("page1_row")] == [ROOM_MIN_LISTED, PLINTH_NOTE]


def test_fail_stamped_plan_displays_its_actual_failures():
    plan = _fail_stamped_payload()
    labels = plan_truth_labels(plan)
    assert labels["certificate_failures"] == plan["mathematical_certificate"]["failures"]
    assert labels["counts"]["certificate_failures"] == 2
    # PROP-HARD and the beyond-cap ROOM-MAX row are what the FAIL stamp rests
    # on; the listed ROOM-MIN row is not.
    assert PROP_HARD in labels["unresolved_breaches"]
    assert ROOM_MAX_BEYOND_CAP in labels["unresolved_breaches"]
    assert ROOM_MIN_LISTED not in labels["unresolved_breaches"]
    assert labels["counts"]["unresolved_breaches"] == 2
    assert labels["headings"]["unresolved_breaches"] == "UNRESOLVED BREACHES (2)"


def test_summary_counts_match_the_groups_exactly():
    for plan in (_certified_payload(), _fail_stamped_payload()):
        labels = plan_truth_labels(plan)
        expected = TRUTH_SUMMARY_TEMPLATE.format(
            failures=labels["counts"]["certificate_failures"],
            deviations=labels["counts"]["listed_deviations"],
            breaches=labels["counts"]["unresolved_breaches"],
        )
        assert labels["summary_line"] == expected
        assert labels["headings"]["listed_deviations"] == (
            "LISTED DEVIATIONS (%d)" % labels["counts"]["listed_deviations"]
        )


def test_page1_summary_keeps_every_row_in_the_complete_ledger():
    """Page 1 is a summary; no finding is dropped from the report.

    The banner carries the three certificate-owned counts, the top findings and
    the next actions.  Every page-1 row and certificate failure still survives
    verbatim in Appendix A.  This replaces the old expectation that a 49-row
    list had to be forced into the page-1 banner.
    """
    plan = _fail_stamped_payload()
    labels = plan_truth_labels(plan)
    page1 = _pdf_page1_text(plan, pages=1)
    for key in ("certificate_failures", "listed_deviations", "unresolved_breaches"):
        assert labels["headings"][key] in page1, f"heading missing from page 1: {key}"
    assert labels["summary_line"] in page1
    assert "Recommended next actions" in page1

    text = _pdf_all_text(plan)
    for row in page1_plan_warnings(plan["warnings"]):
        assert row in text, f"page-1 row missing from the report: {row[:80]}"
    for failure in plan["mathematical_certificate"]["failures"]:
        assert failure in text, f"certificate failure missing from the report: {failure}"


def test_pdf_group_headings_are_the_module_headings():
    text = _pdf_page1_text(_certified_payload())
    assert "CERTIFICATE FAILURES (0)" in text, (
        "a certified plan must print CERTIFICATE FAILURES (0) on its banner"
    )
    assert re.search(r"LISTED DEVIATIONS \(\d+\)", text)
    assert "UNRESOLVED BREACHES (0)" in text


def test_ui_prints_the_same_heading_templates():
    """Byte-identical heading templates in the one UI owner.

    The screen, the print view and the PDF must print the same heading strings;
    this reads the frontend source, the same way the verdict-definition parity
    pin does, so a one-sided reword fails here.
    """
    source = TS_SOURCE.read_text(encoding="utf-8")
    expected = {
        "CERTIFICATE FAILURES": CERTIFICATE_FAILURES_HEADING,
        "LISTED DEVIATIONS": LISTED_DEVIATIONS_HEADING,
        "UNRESOLVED BREACHES": UNRESOLVED_BREACHES_HEADING,
    }
    for label, template in expected.items():
        assert f"'{template}'" in source, (
            f"frontend/src/services/warningReport.ts does not carry the {label} template "
            f"verbatim ({template!r})"
        )
    assert TRUTH_SUMMARY_TEMPLATE in source, "the summary template must match the backend"


def test_certified_t2_fixture_keeps_its_measured_grouping():
    """The measured fixture: 0 certificate failures, 26 listed rows."""
    _CACHE.clear()
    plan = solve_with_escalation(
        FloorPlanRequest(
            plot_width_m=12.0,
            plot_depth_m=18.0,
            building_typology="residential_multi",
            floors=4,
            ground_coverage_ratio=0.60,
            vastu_strictness="high",
            seed="stage4-pin",
            ai_provider="mock",
            bypass_cache=True,
        )
    ).model_dump()
    assert compute_plan_verdict(plan) == "CERTIFIED"
    labels = plan_truth_labels(plan)
    page1 = page1_plan_warnings(plan.get("warnings"))
    assert labels["certificate_failures"] == (
        plan["mathematical_certificate"] or {}
    ).get("failures", []) == []
    assert labels["counts"]["certificate_failures"] == 0
    assert labels["counts"]["unresolved_breaches"] == 0
    # Displayed deviation rows cover every listed page-1 row exactly once.
    listed_page1 = [
        d["page1_row"] for d in labels["listed_deviations"] if d.get("page1_row")
    ]
    assert sorted(listed_page1) == sorted(page1)
    assert labels["counts"]["listed_deviations"] == len(page1)
    assert labels["structured_relaxations"] > 0


def test_canonical_55_warning_fixture_grouping():
    """The captured payload: 3 certificate failures, its own deviations."""
    fixture = json.loads(
        (ROOT / "frontend" / "src" / "test-fixtures" / "plan_noncertified_55.json").read_text(
            encoding="utf-8"
        )
    )
    rooms = {}
    for rx in fixture["relaxations"]:
        room = rooms.setdefault(rx["room"], {"room_id": rx["room"], "relaxations": []})
        room["relaxations"].append({"rule_id": rx["rule_id"], "rationale": rx["rationale"]})
    plan = {
        "plan_verdict": fixture["plan_verdict"],
        "mathematical_certificate": fixture["certificate"],
        "validation_gate": {"overall_status": fixture["gate"]["status"]},
        "warnings": fixture["warnings"],
        "multi_storey": {"floors": [{"floor_index": 0, "rooms": list(rooms.values())}]},
    }
    labels = plan_truth_labels(plan)
    assert labels["certificate_failures"] == fixture["certificate"]["failures"]
    assert labels["counts"]["certificate_failures"] == 3
    page1 = page1_plan_warnings(fixture["warnings"])
    # Fail-stamped: some page-1 rows are the breaches the stamp rests on.
    assert labels["counts"]["unresolved_breaches"] > 0
    assert page1, "the captured payload must carry page-1 rows"
    # Nothing on page 1 is silently dropped: every row is either a listed
    # deviation or a named breach.
    listed = {d["page1_row"] for d in labels["listed_deviations"] if d.get("page1_row")}
    breaches = set(labels["unresolved_breaches"])
    assert listed | breaches == set(page1), (
        "a page-1 row was neither listed nor named as a breach: "
        f"{sorted(set(page1) - listed - breaches)[:2]}"
    )
    assert listed & breaches == set(), "a row cannot be listed and a breach at once"
