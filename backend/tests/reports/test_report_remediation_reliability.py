"""Report download, remediation contract, and one-verdict reliability.

Pins the acceptance criteria for the T2 G+2 diagnostic fixture:

  * the supplied programme squeeze is a listed, within-cap deviation under the
    authoritative verdict - the dimension layer passes, the certificate is
    valid, and no surface says the plan carries a FAIL stamp;
  * the remediation endpoint never offers a duplex patch that the request
    schema rejects (the exact 422) and names the storey constraint instead;
  * a report is assembled once per canonical input and cannot be reused after
    an input, output-mode or template change;
  * page 1 carries the verdict, counts, top findings and actions, while the
    appendix keeps every finding verbatim.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfReader

from app.main import app
from app.schemas.floorplan import FloorPlanRequest
from app.schemas.remediation import BaselineFacts, RemediationIn
from app.services import report_service
from app.services.floorplan.remediation import build_options
from app.services.floorplan.strategy_escalation import solve_with_escalation
from app.services.plan_verdict import (
    CERTIFIED,
    FAIL_STAMP,
    compute_plan_verdict,
    plan_truth_labels,
)
from app.services.report_service import (
    REPORT_TEMPLATE_VERSION,
    clear_report_cache,
    generate_pdf_report,
    generate_pdf_report_with_cache,
    report_cache_key,
)

T2_G2 = dict(
    plot_width_m=15.0,
    plot_depth_m=18.0,
    required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "bed_2"],
    building_typology="residential_multi",
    floors=3,
    units_per_floor=2,
    ground_coverage_ratio=0.6,
    vastu_strictness="high",
    quality_grade="standard",
    ai_provider="mock",
    seed="fixture-scan-2",
    bypass_cache=True,
)


@pytest.fixture(scope="module")
def t2_plan() -> dict:
    response = solve_with_escalation(FloorPlanRequest(**T2_G2))
    dump = response.model_dump()
    # The API publishes the verdict on the response; mirror that boundary here.
    dump["plan_verdict"] = compute_plan_verdict(dump)
    return dump


def _analysis(warnings: list[str] | None = None) -> dict:
    return {
        "request_id": "BW-T2-G2-BASE",
        "timestamp": "2026-10-29T00:00:00Z",
        "coordinates": {"latitude": 12.97425, "longitude": 77.59219},
        "formatted_address": "T2 G+2 baseline site",
        "overall_suitability_score": 62.4,
        "suitability_verdict": "Conditionally Suitable",
        "built_up_area_sqft": 2000,
        "quality_grade": "standard",
        "floors": 3,
        "building_typology": "residential_multi",
        "degraded_mode": True,
        "warnings": warnings
        or ["Road network telemetry unavailable. Approach-side alignment bonus omitted."],
        "factors": [],
        "cost_estimate": {"base_rate_per_sqft": 2200, "base_cost_inr": 4400000, "breakdown": []},
        "recommendation_items": [],
        "detailed_recommendations": [],
        "risks": [],
    }


def _pdf(plan: dict, warnings: list[str] | None = None) -> bytes:
    buf = generate_pdf_report(_analysis(warnings), floor_plan=plan)
    return buf.getvalue()


def _pages(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages]


def _norm(text: str) -> str:
    return " ".join(text.split())


# --------------------------------------------------------------------------- #
# 1. One authoritative verdict for the supplied squeeze scenario
# --------------------------------------------------------------------------- #

def test_supplied_squeeze_is_a_listed_deviation_not_a_certificate_failure(t2_plan):
    cert = t2_plan["mathematical_certificate"]
    assert cert["is_valid"] is True
    assert cert["min_dimensions_satisfied"] is True
    assert cert["failures"] == []
    assert t2_plan["qa"]["validation_gate_status"] == "WARN"

    truth = plan_truth_labels(t2_plan)
    assert truth["counts"]["certificate_failures"] == 0
    assert truth["counts"]["listed_deviations"] > 0
    assert truth["counts"]["unresolved_breaches"] == 0
    assert compute_plan_verdict(t2_plan) == CERTIFIED

    squeeze = [w for w in t2_plan["warnings"] if w.startswith("PROGRAMME-SQUEEZE")]
    assert squeeze, "the diagnostic fixture must keep its programme-squeeze finding"
    assert "design finding, not a verdict" in squeeze[0]
    assert "FAIL stamp" not in squeeze[0]
    # The four squeezed rooms are individually listed on the rooms themselves.
    listed_rooms = {
        d["room_id"] for d in truth["listed_deviations"] if d.get("room_id")
    }
    assert {"t2_unitA_kitchen_F0", "t2_unitB_kitchen_F0"} <= listed_rooms


def test_api_ui_and_pdf_show_the_same_verdict_and_counts(t2_plan):
    truth = plan_truth_labels(t2_plan)
    pages = _pages(_pdf(t2_plan))
    page1 = _norm(pages[0])
    full = _norm(" ".join(pages))

    assert "Plan verdict: CERTIFIED" in page1
    assert "PLAN CERTIFIED" in page1
    for key in ("certificate_failures", "listed_deviations", "unresolved_breaches"):
        assert truth["headings"][key] in page1
    assert truth["summary_line"] in page1
    # The certificate block consumes the same verdict/counts, never a warning
    # total: no "CERTIFIED - ADVISORIES" from a merged warning list.
    assert "CERTIFIED - 10/10 invariants" in full
    assert f"{truth['counts']['listed_deviations']} listed deviations" in full
    assert "CERTIFIED - ADVISORIES" not in full

    # No contradictory FAIL-stamp language survives in the report, including
    # the raw engine ledger.
    for stale in (
        "drawn with a FAIL stamp",
        "still fails the dimension layer",
        "never claimed compliant",
        "certificate still fails",
    ):
        assert stale not in full, stale


def test_page1_is_a_summary_and_appendix_keeps_every_finding(t2_plan):
    pages = _pages(_pdf(t2_plan))
    page1 = _norm(pages[0])
    full = _norm(" ".join(pages))
    truth = plan_truth_labels(t2_plan)

    assert "Three most important findings" in page1
    assert "Recommended next actions" in page1
    assert "DATA DEGRADATION NOTICE" in page1
    assert "Certificate-owned counts" in page1
    # The complete ledger is a separate, verbatim appendix.
    assert "Complete Finding Ledger" in full
    assert "Raw engine findings log" in full
    for warning in t2_plan["warnings"]:
        assert _norm(warning) in full, f"finding dropped from the PDF: {warning[:90]}"
    assert len(pages) >= 4
    for index, text in enumerate(pages, start=1):
        assert f"Page {index} of {len(pages)}" in text


def test_failing_plan_is_never_certified_by_calling_its_breaches_deviations():
    failing = {
        "plan_verdict": FAIL_STAMP,
        "warnings": [
            "PROP-HARD: living_F0 proportion 1:3.2 beyond the 1.40x cap.",
            "ROOM-OVERLAP: bath_1 and bed_2 overlap by 5.0 m².",
        ],
        "validation_gate": {"overall_status": "FAIL"},
        "mathematical_certificate": {"is_valid": False, "failures": ["NBC-01 living"]},
    }
    labels = plan_truth_labels(failing)
    assert labels["counts"]["certificate_failures"] == 1
    assert labels["counts"]["unresolved_breaches"] == 2
    assert labels["counts"]["listed_deviations"] == 0
    assert compute_plan_verdict(failing) == FAIL_STAMP

    # Adding a room-level "relaxation" record does not launder a hard breach:
    # a beyond-cap proportion and an overlap stay unresolved, and a withheld
    # certificate stays withheld.
    laundered = {
        **failing,
        "placements": [
            {
                "room_id": "living_F0",
                "relaxations": [
                    {"rule_id": "PROP-HARD", "rationale": "declared relaxation"}
                ],
            },
            {
                "room_id": "bath_1",
                "relaxations": [
                    {"rule_id": "ROOM-OVERLAP", "rationale": "declared relaxation"}
                ],
            },
        ],
    }
    laundered_labels = plan_truth_labels(laundered)
    # The relaxation records are printed as deviations, but the two page-1
    # breaches remain unresolved and the verdict remains withheld.
    assert laundered_labels["counts"]["certificate_failures"] == 1
    assert laundered_labels["counts"]["unresolved_breaches"] == 2
    assert compute_plan_verdict(laundered) == FAIL_STAMP
    text = _norm(" ".join(_pages(_pdf(failing))))
    assert "Plan verdict: NOT-CERTIFIED-FAIL-STAMP" in text
    assert "PLAN NOT CERTIFIED" in text


# --------------------------------------------------------------------------- #
# 2. Remediation contract: the duplex 422 cannot be offered
# --------------------------------------------------------------------------- #

def test_duplex_on_odd_storeys_is_a_named_constraint_not_a_patch(t2_plan):
    warnings = list(t2_plan["warnings"])
    out = build_options(
        RemediationIn(
            request=FloorPlanRequest(**T2_G2),
            warnings=warnings,
            plan_verdict=t2_plan["plan_verdict"],
            baseline=BaselineFacts(
                warning_count=len(warnings),
                failure_count=0,
                relaxation_count=plan_truth_labels(t2_plan)["structured_relaxations"],
            ),
        )
    )
    by_id = {option.id: option for option in out.options}
    duplex = by_id["duplex"]
    assert duplex.available is False
    assert duplex.patch == {}
    assert duplex.effect is None
    assert "even number of storeys" in (duplex.constraint_reason or "")
    assert duplex.basis["input_change"] == "floors"
    # The actionable alternative is one storey away, and that request IS valid.
    assert by_id["add_storey"].patch == {"floors": 4}
    FloorPlanRequest(
        **{**T2_G2, "floors": 4, "partition_variant": "duplex", "units_per_floor": 4}
    )


def test_request_schema_still_rejects_the_underlying_invalid_duplex_request():
    with pytest.raises(ValidationError, match="even number of storeys"):
        FloorPlanRequest(
            **{**T2_G2, "partition_variant": "duplex", "units_per_floor": 4}
        )


def test_remediation_endpoint_returns_200_with_the_constraint(t2_plan):
    response = TestClient(app).post(
        "/api/floorplan/remediation",
        json={
            "request": T2_G2,
            "warnings": t2_plan["warnings"],
            "plan_verdict": t2_plan["plan_verdict"],
            "baseline": {
                "warning_count": len(t2_plan["warnings"]),
                "failure_count": 0,
                "relaxation_count": plan_truth_labels(t2_plan)["structured_relaxations"],
            },
        },
    )
    assert response.status_code == 200, response.text[:500]
    options = {o["id"]: o for o in response.json()["options"]}
    assert options["duplex"]["available"] is False
    assert options["duplex"]["patch"] == {}
    assert options["duplex"]["basis"]["type"] == "constraint"


def test_every_actionable_option_maps_to_evidence(t2_plan):
    out = build_options(
        RemediationIn(
            request=FloorPlanRequest(**T2_G2),
            warnings=list(t2_plan["warnings"]),
            baseline=BaselineFacts(warning_count=len(t2_plan["warnings"])),
        )
    )
    for option in out.options:
        assert option.basis, option.id
        if option.available:
            assert option.patch, option.id
            assert option.effect is not None, option.id
        else:
            assert option.constraint_reason, option.id


# --------------------------------------------------------------------------- #
# 3. Report cache: content-addressed, mode-addressed, never stale
# --------------------------------------------------------------------------- #

def test_report_cache_key_tracks_inputs_mode_and_template(t2_plan):
    data = _analysis()
    base = report_cache_key(data, floor_plan=t2_plan, options={"dossier_only": False})
    assert base == report_cache_key(data, floor_plan=t2_plan, options={"dossier_only": False})
    assert base != report_cache_key(
        {**data, "formatted_address": "A different site"},
        floor_plan=t2_plan,
        options={"dossier_only": False},
    )
    assert base != report_cache_key(
        data,
        floor_plan={**t2_plan, "warnings": [*t2_plan["warnings"], "ROOM-OVERLAP: x"]},
        options={"dossier_only": False},
    )
    assert base != report_cache_key(
        data,
        floor_plan=t2_plan,
        template_version=f"{REPORT_TEMPLATE_VERSION}-changed",
        options={"dossier_only": False},
    )
    assert base != report_cache_key(
        data, floor_plan=t2_plan, options={"dossier_only": True}
    )


def test_repeated_identical_report_reuses_bytes_but_changed_input_does_not(t2_plan):
    clear_report_cache()
    data = _analysis()
    first, first_hit = generate_pdf_report_with_cache(data, floor_plan=t2_plan)
    second, second_hit = generate_pdf_report_with_cache(data, floor_plan=t2_plan)
    assert first_hit is False
    assert second_hit is True
    assert first.getvalue() == second.getvalue()

    changed = {**data, "formatted_address": "A different site"}
    third, third_hit = generate_pdf_report_with_cache(changed, floor_plan=t2_plan)
    assert third_hit is False
    text = _norm(" ".join(_pages(third.getvalue())))
    assert "A different site" in text
    assert "T2 G+2 baseline site" not in text


def test_report_endpoint_advertises_a_hit_without_changing_the_contract(t2_plan):
    clear_report_cache()
    body = {
        "analysis_data": _analysis(),
        "site_vision": None,
        "floor_plan": t2_plan,
    }
    client = TestClient(app)
    first = client.post("/api/report", json=body)
    second = client.post("/api/report", json=body)
    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"].startswith("application/pdf")
    assert first.headers["X-Buildwise-Report-Cache"] == "miss"
    assert second.headers["X-Buildwise-Report-Cache"] == "hit"
    assert first.content == second.content
    assert first.content.startswith(b"%PDF")


def test_a_failed_build_is_not_cached(monkeypatch, t2_plan):
    clear_report_cache()
    data = _analysis()

    class Boom(RuntimeError):
        pass

    def explode(*args, **kwargs):
        raise Boom("layout failed")

    monkeypatch.setattr(report_service, "generate_pdf_report", explode)
    with pytest.raises(Boom):
        generate_pdf_report_with_cache(data, floor_plan=t2_plan)
    monkeypatch.undo()

    _, hit = generate_pdf_report_with_cache(data, floor_plan=t2_plan)
    assert hit is False, "a failed build must not leave a successful cache entry"
