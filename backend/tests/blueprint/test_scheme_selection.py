"""Scheme selection contracts: choosing a scheme profile re-solves the plate.

The picker used to be decorative: it recorded a scheme id and shipped the same
drawing. These tests pin the behaviour that replaced it:

* selecting a profile changes the geometry that owns the certificate, and
* every outcome (applied / recorded only / refused) is recorded structurally, so
  the sheet and the PDF can never claim a profile shaped a plan it did not, and
* the land-economics certificate reaches the PDF as a content layer.
"""
import io

import pypdf
import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.services.report_service import generate_pdf_report

ROOMS = ["living", "kitchen", "master_bed", "bath_1", "dining"]
PROFILES = ("max_area", "max_vastu", "max_light_vent")


def _req(**overrides) -> FloorPlanRequest:
    payload = dict(
        plot_width_m=13.0,
        plot_depth_m=20.0,
        vastu_strictness="high",
        building_typology="residential_single",
        ground_coverage_ratio=0.6,
        ai_provider="mock",
        bypass_cache=True,
        seed="42",
        required_rooms=list(ROOMS),
    )
    payload.update(overrides)
    return FloorPlanRequest.model_validate(payload)


def _geometry(response):
    floors = response.multi_storey.floors if response.multi_storey else []
    return [
        [
            (r.room_id, round(r.x, 2), round(r.y, 2), round(r.width_m, 2), round(r.depth_m, 2))
            for r in floor.rooms
        ]
        for floor in floors
    ]


def _gate_status(response) -> str:
    gate = (response.qa.validation_gate if response.qa else None) or {}
    return str(gate.get("overall_status") or "")


def test_single_storey_selection_repartitions_the_plate():
    baseline = generate_floor_plan(_req())
    applied = {p: generate_floor_plan(_req(selected_scheme_id=p)) for p in PROFILES}

    base_geom = _geometry(baseline)
    assert base_geom, "baseline must carry geometry"

    for profile, response in applied.items():
        snap = response.params_snapshot or {}
        assert snap.get("scheme_selection_status") == "applied", profile
        assert snap.get("scheme_profile") == profile
        assert response.selected_scheme_id == profile
        assert _geometry(response) != base_geom, (
            f"selecting '{profile}' must change the geometry, not relabel it"
        )
        assert response.land_economics is not None

    assert len({str(_geometry(r)) for r in applied.values()}) == len(PROFILES)


def test_multistorey_selection_applies_and_keeps_the_core_stack():
    baseline = generate_floor_plan(_req(floors=3))
    response = generate_floor_plan(_req(floors=3, selected_scheme_id="max_area"))
    snap = response.params_snapshot or {}

    assert snap.get("scheme_selection_status") == "applied"
    assert _geometry(response) != _geometry(baseline)
    assert _gate_status(response) != "FAIL"

    floors = response.multi_storey.floors
    core_boxes = set()
    for floor in floors:
        cores = [r for r in floor.rooms if getattr(r, "is_vertical_core", False)]
        assert cores, f"floor {floor.floor_index} lost its vertical core"
        core_boxes.add(tuple(round(v, 2) for v in (
            cores[0].x, cores[0].y, cores[0].width_m, cores[0].depth_m,
        )))
    assert len(core_boxes) == 1, f"core not stacked across storeys: {core_boxes}"

    # The spec the certificate compares against must follow the placed core.
    spec = response.multi_storey.vertical_cores[0]
    placed = next(r for r in floors[0].rooms if getattr(r, "is_vertical_core", False))
    assert (round(spec.x, 2), round(spec.y, 2)) == (round(placed.x, 2), round(placed.y, 2))


@pytest.mark.parametrize("profile", PROFILES)
def test_plate_that_cannot_be_partitioned_is_recorded_only(profile):
    # A terrace-band plate is owned by RULE-FP; the band solver declines it.
    payload = dict(floors=3, terrace_bands={"2": {"edge": "N", "depth_m": 2.5}})
    baseline = generate_floor_plan(_req(**payload))
    response = generate_floor_plan(_req(selected_scheme_id=profile, **payload))
    snap = response.params_snapshot or {}

    assert snap.get("scheme_selection_status") == "recorded_only"
    assert snap.get("scheme_profile") is None
    assert _geometry(response) == _geometry(baseline)
    assert any(w.startswith("SCHEME-SELECTION:") for w in response.warnings)


def test_captured_boundary_masks_that_carve_nothing_still_apply():
    """A captured (map) boundary sends floor_plate_masks; all-'present' is the
    full envelope, so the profile must still be able to re-partition it."""
    masks = {0: {"wing_a": "present", "wing_b": "present"}}
    baseline = generate_floor_plan(_req(floor_plate_masks=masks))
    response = generate_floor_plan(
        _req(selected_scheme_id="max_vastu", floor_plate_masks=masks)
    )
    snap = response.params_snapshot or {}

    assert snap.get("scheme_selection_status") == "applied"
    assert _geometry(response) != _geometry(baseline)


def test_masks_that_carve_a_terrace_still_fall_back_to_rule_fp():
    masks = {0: {"wing_a": "present", "wing_b": "terrace"}}
    baseline = generate_floor_plan(_req(floor_plate_masks=masks))
    response = generate_floor_plan(
        _req(selected_scheme_id="max_vastu", floor_plate_masks=masks)
    )
    snap = response.params_snapshot or {}

    # A carved plate is RULE-FP's; the selection is recorded, never faked.
    assert snap.get("scheme_selection_status") == "recorded_only"
    assert _geometry(response) == _geometry(baseline)


def test_selection_outcome_matches_the_geometry_it_ships():
    """Every selection either changed the plan or says why it did not."""
    cases = [
        dict(floors=1),
        dict(floors=2),
        dict(floors=3, required_rooms=["living", "kitchen", "master_bed", "bath_1"]),
    ]
    for case in cases:
        baseline = _geometry(generate_floor_plan(_req(**case)))
        for profile in PROFILES:
            response = generate_floor_plan(_req(selected_scheme_id=profile, **case))
            status = (response.params_snapshot or {}).get("scheme_selection_status")
            geom = _geometry(response)
            if status == "applied":
                assert geom != baseline, (case, profile)
                assert (response.params_snapshot or {}).get("scheme_profile") == profile
            elif status in ("recorded_only", "rejected_non_compliant"):
                assert geom == baseline, (case, profile, status)
                assert (response.params_snapshot or {}).get("scheme_profile") is None
            else:
                pytest.fail(f"selection status not recorded: {case} {profile} -> {status}")


def test_alternatives_keep_their_geometry_but_not_their_sheets():
    """The picker needs metrics + rooms; the SVG bodies belong to the chosen plan."""
    response = generate_floor_plan(_req(floors=2, include_scheme_alternatives=True))
    assert response.scheme_alternatives

    for alternative in response.scheme_alternatives:
        assert alternative.metrics.total_score is not None
        assert alternative.floors, "alternative geometry must survive the trim"
        for floor in alternative.floors:
            assert floor.rooms
            assert floor.svg_blueprint_cad is None
            assert floor.svg_blueprint_paper is None

    # The chosen plan's own sheets are untouched.
    assert response.multi_storey.floors[0].svg_blueprint_cad


def test_selection_is_deterministic():
    first = generate_floor_plan(_req(floors=2, selected_scheme_id="max_vastu"))
    second = generate_floor_plan(_req(floors=2, selected_scheme_id="max_vastu"))
    assert first.generation_id == second.generation_id
    assert _geometry(first) == _geometry(second)
    assert (first.params_snapshot or {}).get("seed") == (second.params_snapshot or {}).get("seed")


def test_no_selection_records_no_selection_status():
    response = generate_floor_plan(_req(floors=2))
    snap = response.params_snapshot or {}
    assert "scheme_selection_status" not in snap
    assert "scheme_profile" not in snap


def test_pdf_carries_land_economics_and_the_selection_outcome():
    response = generate_floor_plan(_req(floors=2, selected_scheme_id="max_area"))
    assert response.land_economics is not None

    buffer = generate_pdf_report({}, floor_plan=response.model_dump())
    reader = pypdf.PdfReader(io.BytesIO(buffer.getvalue()))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)

    assert "LAND ECONOMICS" in text
    assert "SPACE-EFFICIENCY" in text
    assert "SCHEME SELECTION" in text
    assert "max_area" in text
    # The certificate's own verdict is printed, not a browser-side re-derivation.
    assert response.land_economics.certificate.status in text
