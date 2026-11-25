"""Gate & certificate integrity contract tests.

Verifies:
  - Forbidden-wall law compares space types, not solver handles.
  - Certificate is recomputed after land mutation, and land checks are gate-bearing.
  - QA rows cannot contradict the gate.
  - A withheld certificate states why, and certified rules are backed by passing flags.
  - An evaluator that did not run FAILs the gate; genuine N/A never gates.
  - Gate/certificate fields survive the response schema.
  - Forbidden verdict is re-derived from emitted geometry.
  - Refusal honesty: refused brief carries full fail gate with reasons.
  - PDF verdict is derived: never claims 100% beside warnings, and un-run gate != pass.
  - Gross and clear areas keep their own field names in the schedule.
  - Sheet room schedule prints every solved room with clear area.
"""

from __future__ import annotations

import io
import re
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from app.schemas.floorplan import FloorPlanQA, FloorPlanRequest
from app.services.floorplan.drawing_ir import (
    _ellipsize_str,
    build_drawing_ir,
    render_svg_from_ir,
)
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.identity import space_type_of
from app.services.floorplan.ontology import ONTOLOGY, MathematicalValidityCertificate
from app.services.floorplan.validation_gate import (
    LAYER_IDS,
    build_gate_layers,
    ensure_all_layers,
    make_layer,
    overall_status,
)

BASE_ROOMS = ["living", "kitchen", "master_bed", "bath_1", "dining", "stairs"]
BASELINE_PLOT_W = 16.1
BASELINE_PLOT_D = 19.3
BASELINE_GEN_ID = "GEN-GATE-16.1x19.3-G1"


def _solve(typology: str, floors: int) -> Any:
    req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=floors,
        building_typology=typology,
        vastu_strictness="medium",
        required_rooms=list(BASE_ROOMS),
    )
    return SoleGeometryEngine(req).solve()


@pytest.fixture(scope="module")
def solved():
    """One shared solve: the PDF/SVG hygiene baseline (8 rooms on floor 0)."""
    req = FloorPlanRequest(
        plot_width_m=BASELINE_PLOT_W,
        plot_depth_m=BASELINE_PLOT_D,
        floors=2,
        building_typology="T1_SINGLE_FAMILY",
        required_rooms=list(BASE_ROOMS),
    )
    return SoleGeometryEngine(req).solve()


def _touching_pairs(rooms: List[Any]) -> List[tuple]:
    """Pairs of rooms sharing >= 0.20 m of wall (the certificate's own test)."""
    pairs = []
    for i in range(len(rooms)):
        r1 = rooms[i]
        for r2 in rooms[i + 1:]:
            v = (
                (abs((r1.x + r1.width_m) - r2.x) < 0.05
                 or abs((r2.x + r2.width_m) - r1.x) < 0.05)
                and (min(r1.y + r1.depth_m, r2.y + r2.depth_m) - max(r1.y, r2.y)) >= 0.20
            )
            h = (
                (abs((r1.y + r1.depth_m) - r2.y) < 0.05
                 or abs((r2.y + r2.depth_m) - r1.y) < 0.05)
                and (min(r1.x + r1.width_m, r2.x + r2.width_m) - max(r1.x, r2.x)) >= 0.20
            )
            if v or h:
                pairs.append((r1, r2))
    return pairs


def _forbidden_pairs(building: Any) -> List[tuple]:
    typology = building.building_typology
    found = []
    for fl in building.floors:
        for r1, r2 in _touching_pairs(fl.rooms):
            t1 = space_type_of(r1, typology) or r1.room_id
            t2 = space_type_of(r2, typology) or r2.room_id
            if ONTOLOGY.is_forbidden_wall(t1, t2):
                found.append((fl.floor_index, r1.room_id, r2.room_id, t1, t2))
    return found


# =============================================================================
# Forbidden wall sweep over real generations
# =============================================================================

@pytest.mark.parametrize("typology,floors", [
    ("T1_SINGLE_FAMILY", 1),
    ("T1_SINGLE_FAMILY", 2),
    ("T2_FAMILY_APARTMENT", 2),
    ("T3_LARGE_COMPLEX", 1),
    ("T4_WAREHOUSE", 1),
])
def test_forbidden_sweep_agrees_with_certificate(typology: str, floors: int):
    """5 generations: no forbidden pair in geometry, and the cert says so."""
    b = _solve(typology, floors)
    assert b.floors, f"{typology} F{floors}: no floors to audit"
    violations = _forbidden_pairs(b)
    assert not violations, f"{typology} F{floors}: forbidden walls in geometry: {violations}"

    cert = b.mathematical_certificate
    assert cert["zero_forbidden_violations"] is True
    assert cert["details"]["forbidden_wall_pairs"] == []


def test_forbidden_law_is_not_satisfiable_with_solver_handles():
    """Solver handles never trigger a law; space types do."""
    assert ONTOLOGY.is_forbidden_wall("t3_sanitary_F0", "electrical_room_F0") is False
    assert ONTOLOGY.is_forbidden_wall("sanitary_block", "electrical_room") is True


# =============================================================================
# Land mutation precedes the certificate, land checks gate L1
# =============================================================================

@pytest.mark.parametrize("typology,floors", [
    ("T1_SINGLE_FAMILY", 1),
    ("T1_SINGLE_FAMILY", 2),
    ("T2_FAMILY_APARTMENT", 2),
])
def test_certificate_describes_the_FINAL_geometry(typology: str, floors: int):
    """Mutation equality: recompute every geometric invariant from the emitted
    rooms and require the certificate's flags to match.
    """
    b = _solve(typology, floors)
    cert = b.mathematical_certificate

    overlap = True
    containment = True
    for fl in b.floors:
        env = fl.envelope
        for r in fl.rooms:
            if (r.x < -0.05 or r.y < -0.05
                    or r.x + r.width_m > env["width"] + 0.05
                    or r.y + r.depth_m > env["depth"] + 0.05):
                containment = False
        for i in range(len(fl.rooms)):
            for j in range(i + 1, len(fl.rooms)):
                r1, r2 = fl.rooms[i], fl.rooms[j]
                x_ov = max(0.0, min(r1.x + r1.width_m, r2.x + r2.width_m) - max(r1.x, r2.x))
                y_ov = max(0.0, min(r1.y + r1.depth_m, r2.y + r2.depth_m) - max(r1.y, r2.y))
                if x_ov * y_ov >= 0.05:
                    overlap = False

    assert cert["non_overlap"] is overlap, "cert overlap verdict is stale"
    assert cert["containment"] is containment, "cert containment verdict is stale"
    assert cert["zero_forbidden_violations"] is (not _forbidden_pairs(b))

    final_ids = {r.room_id for fl in b.floors for r in fl.rooms}
    assert set(cert["details"]["per_room_travel_distances"]) == final_ids
    assert b.land_economics is not None
    assert b.land_economics.footprint_area_sqm > 0


def _fake_cert(**over: Any) -> Any:
    base = dict(
        non_overlap=True, containment=True, chain_sums_match=True,
        zero_forbidden_violations=True, connectivity_bfs=True,
        vertical_stack_valid=True, core_continuity_valid=True,
        no_wet_over_terrace_valid=True, cores_stack_aligned=True,
        min_dimensions_satisfied=True, aspect_ratios_satisfied=True,
        egress_distances_satisfied=True, l2_door_swings_valid=True,
        l3_fixture_clearances_satisfied=True, l4_furniture_clearances_satisfied=True,
        details={"living_quality_layers": {}},
    )
    base.update(over)
    return SimpleNamespace(**base)


def _gate_with_land(checks: Dict[str, bool]) -> Dict[str, Dict[str, Any]]:
    layers = build_gate_layers(
        engine=SimpleNamespace(structural_grid=None),
        cert=_fake_cert(),
        floors=[],
        duct_shafts=[],
        typology="T1_SINGLE_FAMILY",
        pi_ok=True,
        pi_warns=[],
        statutory_audit={"occupant_load": 0},
        land_cert=SimpleNamespace(checks=checks),
    )
    return {ld["layer_id"]: ld for ld in layers}


def test_land_fail_is_gate_bearing():
    """A provable land violation fails L1 - it cannot sit beside a PASS gate."""
    rows = _gate_with_land({"coverage_within_limit": False})
    assert rows["L1"]["status"] == "FAIL"
    assert any("coverage" in f.lower() for f in rows["L1"]["findings"])


def test_land_advisory_is_warning_not_failure():
    """Planning ratios are advisory: they WARN, they do not forge a law."""
    rows = _gate_with_land({"circulation_within_12_20": False})
    assert rows["L1"]["status"] == "WARN"
    assert any("circulation" in f.lower() for f in rows["L1"]["findings"])


def test_land_pass_does_not_downgrade_gate():
    rows = _gate_with_land({"coverage_within_limit": True, "program_fits_footprint": True})
    assert rows["L1"]["status"] == "PASS"


# =============================================================================
# Did-not-run FAILs; genuine N/A never gates
# =============================================================================

def test_missing_evaluator_fails_the_gate():
    """The fallback row for an absent evaluator is FAIL, not N/A."""
    layers = ensure_all_layers([make_layer("L1", "PASS", summary="evaluated")])
    by_id = {l.layer_id: l for l in layers}
    assert len(layers) == len(LAYER_IDS)
    assert by_id["L1"].status == "PASS"
    for lid in LAYER_IDS:
        if lid == "L1":
            continue
        assert by_id[lid].status == "FAIL", f"{lid} absent evaluator did not fail"
        assert by_id[lid].findings


def test_genuine_na_with_reason_does_not_gate():
    """A layer that truly does not apply is N/A-with-reason and never gates."""
    layers = [
        make_layer(lid, "N/A" if lid == "L11" else "PASS",
                   reason="no terrace requested" if lid == "L11" else None)
        for lid in LAYER_IDS
    ]
    assert overall_status(layers) == "PASS"
    assert each_na_has_reason(layers)


def each_na_has_reason(layers: List[Any]) -> bool:
    return all(l.reason for l in layers if l.status == "N/A")


# =============================================================================
# QA rows and certificate explanation
# =============================================================================

@pytest.mark.parametrize("typology", ["T1_SINGLE_FAMILY", "T3_LARGE_COMPLEX"])
def test_qa_rows_never_contradict_the_gate(typology: str):
    """The gate verdict is carried explicitly; the critic never fakes a pass."""
    b = _solve(typology, 1)
    gate_status = b.validation_gate["overall_status"]
    assert b.qa_report["validation_gate_status"] == gate_status
    assert b.qa_report["validation_gate"]["overall_status"] == gate_status

    cert = b.mathematical_certificate
    assert cert["overall_layer_status"] == gate_status
    hard = {"L1", "L2", "L8", "L14", "L15"}
    hard_failed = any(
        ld["status"] == "FAIL" and ld["layer_id"] in hard
        for ld in cert["layer_statuses"]
    )
    if hard_failed:
        assert cert["is_valid"] is False
        assert cert["failures"]


@pytest.mark.parametrize("typology,floors", [
    ("T1_SINGLE_FAMILY", 1),
    ("T2_FAMILY_APARTMENT", 2),
    ("T4_WAREHOUSE", 1),
])
def test_certificate_explains_every_withheld_verdict(typology: str, floors: int):
    """A false verdict has a stated reason; a certified rule has a passing flag."""
    b = _solve(typology, floors)
    cert = b.mathematical_certificate
    flag_map = {
        "REL-01": "non_overlap",
        "REL-02": "zero_forbidden_violations",
        "CIRC-01": "connectivity_bfs",
        "DIM-01": "chain_sums_match",
        "NBC-01": "min_dimensions_satisfied",
        "NBC-02": "aspect_ratios_satisfied",
        "NBC-03": "egress_distances_satisfied",
        "SAN-01": "sanitation_wc_count_satisfied",
        "VERT-01": "vertical_stack_valid",
        "VERT-02": "no_wet_over_terrace_valid",
    }
    for rule, flag in flag_map.items():
        if rule in cert["certified_rules"]:
            assert cert[flag] is True, f"{rule} certified while {flag} is false"
    if cert["is_valid"] is False:
        assert cert["failures"], "invalid certificate must explain itself"
        assert all(len(f) > 10 for f in cert["failures"])


# =============================================================================
# Response schema carries the gate/certificate fields
# =============================================================================

def test_qa_schema_carries_gate_and_invariant_fields():
    fields = set(FloorPlanQA.model_fields)
    assert {"validation_gate", "validation_gate_status",
            "invariants_verified", "invariants_total"} <= fields
    assert "failures" in MathematicalValidityCertificate.model_fields

    qa = FloorPlanQA(
        entry="living",
        circulation="connected",
        validation_gate={"overall_status": "WARN", "layers": []},
        validation_gate_status="WARN",
        invariants_verified=12,
        invariants_total=14,
    )
    dumped = qa.model_dump()
    assert dumped["validation_gate"]["overall_status"] == "WARN"
    assert dumped["validation_gate_status"] == "WARN"
    assert (dumped["invariants_verified"], dumped["invariants_total"]) == (12, 14)


def test_solved_building_keeps_gate_on_every_surface():
    """The gate reaches the building model, qa_report and every floor sheet."""
    b = _solve("T1_SINGLE_FAMILY", 2)
    assert b.validation_gate["overall_status"] in ("PASS", "WARN", "FAIL")
    assert b.qa_report["validation_gate"]["contract"] == "universal_gate_v1"
    for fl in b.floors:
        assert fl.validation_gate["overall_status"] == b.validation_gate["overall_status"]


# =============================================================================
# Refusal honesty
# =============================================================================

def test_refusal_carries_full_fail_gate():
    """T1 on an 8x10 m plot: refused, gate present, nothing claims compliance."""
    req = FloorPlanRequest(
        plot_width_m=8.0,
        plot_depth_m=10.0,
        floors=1,
        building_typology="T1_SINGLE_FAMILY",
        required_rooms=list(BASE_ROOMS),
        seed="1003",
    )
    building = SoleGeometryEngine(req).solve()

    assert building.floors == [] or not any(f.rooms for f in building.floors), (
        "the repro plot is expected to be refused; if the engine now places this "
        "programme, re-pin this test to a smaller plate rather than deleting it"
    )
    assert building.global_metrics.get("status") == "failed"
    assert building.warnings, "a refusal must surface at least one warning"
    assert building.unmet_requirements, "a refusal must name the unmet requirements"
    assert all(str(u.reason or "").strip() for u in building.unmet_requirements)

    gate = building.validation_gate or {}
    layers = gate.get("layers") or []
    assert len(layers) == 16, f"refusal gate must keep the L1-L16 contract, got {len(layers)}"
    assert gate.get("overall_status") == "FAIL", "a refusal is never a pass"
    assert [l["layer_id"] for l in layers] == [f"L{i}" for i in range(1, 17)]

    passing = [l["layer_id"] for l in layers if l["status"] == "PASS"]
    assert passing == [], f"refusal fabricated passing layers: {passing}"
    for layer in layers:
        if layer["status"] == "N/A":
            assert str(layer.get("reason") or "").strip(), (
                f"{layer['layer_id']} is N/A without a printed reason"
            )
    cert = building.mathematical_certificate
    assert cert is None or not cert.is_valid, "a refusal must not be certified"


# =============================================================================
# PDF verdict is derived, never unconditional
# =============================================================================

def _pdf_text(payload: dict) -> str:
    import pypdf
    from app.services.report_service import generate_pdf_report

    raw = generate_pdf_report(payload).getvalue()
    assert raw[:4] == b"%PDF"
    reader = pypdf.PdfReader(io.BytesIO(raw))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return re.sub(r"\s+", " ", text)


def _payload(building) -> dict:
    data = building.model_dump()
    return {
        "request_id": "BW-GATE-VERDICT",
        "timestamp": "2026-10-21 12:00:00 UTC",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Gate verdict baseline",
        "overall_suitability_score": 85.0,
        "suitability_verdict": "Verified",
        "built_up_area_sqft": 3600.0,
        "floors": 2,
        "include_construction_schedules": True,
        "multi_storey": data,
        "floor_plan": data,
    }


def test_pdf_drops_all_clear_verdict_beside_warnings(solved):
    payload = _payload(solved)
    payload["multi_storey"]["warnings"] = list(
        payload["multi_storey"].get("warnings") or []
    ) + ["GATE-PIN: a surfaced advisory must suppress the all-clear verdict."]

    text = _pdf_text(payload)
    # The certificate block now prints the SAME certificate-owned verdict and
    # counts as page 1.  An advisory outside the page-1 finding set no longer
    # invents a second "CERTIFIED - ADVISORIES" severity from a warning total;
    # the all-clear wording is still gone.
    assert "100% SATISFIED" not in text, "PDF still claims 100% beside a warning"
    assert "NOT CERTIFIED -" in text, "PDF did not print the withheld-certificate verdict"
    assert "9 unresolved breaches" in text, "the certificate block lost its own breach count"


def test_pdf_never_claims_all_clear_when_gate_did_not_run(solved):
    payload = _payload(solved)
    cert = payload["multi_storey"].get("mathematical_certificate") or {}
    details = cert.get("details") or {}
    details.pop("validation_gate", None)
    cert["details"] = details
    payload["multi_storey"]["mathematical_certificate"] = cert
    payload["multi_storey"]["validation_gate"] = {}
    payload["multi_storey"]["warnings"] = []

    text = _pdf_text(payload)
    assert "100% SATISFIED" not in text, "an un-run gate must never read as all-clear"
    assert "UNVERIFIED - GATE DID NOT RUN" in text.upper()


# =============================================================================
# Gross and clear areas keep their own field names
# =============================================================================

def test_schedule_publishes_gross_and_clear_areas_separately(solved):
    rows = [r for fl in solved.floors for r in (fl.room_schedule or [])]
    assert rows, "baseline produced no room schedule"
    model = {
        (fl.floor_index, r.room_id): r.area_sqm
        for fl in solved.floors for r in fl.rooms
    }
    saw_difference = False
    for row in rows:
        gross = float(row["area_sqm"])
        clear = float(row["clear_area_sqm"])
        assert "gross_area_sqm" in row, "schedule must name the gross area explicitly"
        assert abs(float(row["gross_area_sqm"]) - gross) <= 1e-6
        if abs(gross - clear) > 0.05:
            saw_difference = True
            assert clear < gross, (
                f"{row['room_id']}: clear area {clear} is not the wall-deducted "
                f"interior of the gross area {gross}"
            )
    assert saw_difference, (
        "no room distinguishes gross from clear area - this baseline can no longer "
        "prove the two fields are separate"
    )
    for fl in solved.floors:
        for row in fl.room_schedule or []:
            assert abs(float(row["area_sqm"]) - model[(fl.floor_index, row["room_id"])]) <= 1e-6


# =============================================================================
# Sheet prints every row, in clear-area terms
# =============================================================================

def _room_schedule_block(svg: str) -> str:
    start = svg.find("ROOM SCHEDULE")
    assert start >= 0, "sheet has no ROOM SCHEDULE table"
    end = svg.find("ROOM CLASS", start)
    return svg[start:end if end > 0 else len(svg)]


@pytest.mark.parametrize("floor_index", [0])
def test_sheet_room_schedule_renders_every_room(solved, floor_index):
    floor = solved.floors[floor_index]
    ir = build_drawing_ir(floor_data=floor, building_model=solved, gen_id=BASELINE_GEN_ID)
    assert len(ir.room_schedule) > 6, (
        "baseline must exceed the old six-row cap to pin the truncation fix; "
        f"got {len(ir.room_schedule)} rows"
    )
    block = _room_schedule_block(render_svg_from_ir(ir))

    missing = []
    for row in ir.room_schedule:
        shown = _ellipsize_str(row["room_name"], 18)
        if shown not in block:
            missing.append((row["room_id"], shown))
    assert missing == [], f"sheet dropped {len(missing)} schedule row(s): {missing}"

    for row in ir.room_schedule:
        assert f"{float(row['clear_area_sqm']):.1f}m²" in block, (
            f"{row['room_id']}: clear area not printed in the schedule"
        )
