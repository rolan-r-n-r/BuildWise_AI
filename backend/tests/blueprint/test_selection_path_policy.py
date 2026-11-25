"""SELECTION-PATH pins.

A room selection is a legal client request even when the chosen partition cannot
be drawn on the plate. The natural programme already draws a squeezed/deficit
plan and discloses it; the selection path now follows the same policy:

* the 8x40 m T1 4-room default draws all four selected rooms (the old two-band
  partition collapsed the kitchen and the plate came back empty);
* a 10-room selection whose partition overlaps draws the plate's legal
  programme, names ROOM-OVERLAP with the id pair and area, and FAILs the gate;
* neither path is a raw 422, and an impossible selection stays an explicit
  failed answer with the programme-deficit banner and options.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan

client = TestClient(app)

BASE4 = ["master_bed", "kitchen", "living", "bath_1"]
TEN = [
    "master_bed", "kitchen", "living", "bath_1", "bath_2",
    "bed_2", "dining", "puja", "study", "t1_stair",
]


def _types(resp) -> set[str]:
    ms = resp.multi_storey
    if ms is None:
        return set()
    return {
        str(room.space_type_id or room.room_id.split("_F")[0])
        for floor in ms.floors
        for room in floor.rooms
    }


def _request(rooms, width=8.0, depth=40.0, floors=1) -> FloorPlanRequest:
    return FloorPlanRequest(
        plot_width_m=width,
        plot_depth_m=depth,
        required_rooms=list(rooms),
        building_typology="T1_SINGLE_FAMILY",
        floors=floors,
        seed="42",
        vastu_strictness="high",
    )


def test_four_room_default_on_elongated_plate_draws_every_selected_room():
    resp = generate_floor_plan(_request(BASE4))
    assert resp.status != "failed", resp.warnings[:3]
    assert resp.multi_storey is not None and resp.multi_storey.floors
    assert not any(w.startswith(("GEN-UNFIT", "ROOM-OVERLAP")) for w in resp.warnings)
    assert set(BASE4) <= _types(resp), _types(resp)
    assert (resp.qa.validation_gate_status or "") != "FAIL", resp.warnings[:6]
    # The room that used to collapse is now a real kitchen, not a sliver.
    kitchen = next(
        r for f in resp.multi_storey.floors for r in f.rooms if r.room_id == "kitchen"
    )
    assert kitchen.area_sqm >= 9.0, kitchen.area_sqm


def test_ten_room_selection_draws_with_named_overlap_instead_of_refusing():
    resp = generate_floor_plan(_request(TEN))
    assert resp.status != "failed", resp.warnings[:3]
    assert resp.multi_storey is not None and resp.multi_storey.floors
    overlap = next((w for w in resp.warnings if w.startswith("ROOM-OVERLAP")), None)
    assert overlap is not None, resp.warnings[:6]
    assert "bath_1" in overlap and "bed_2" in overlap
    assert "5.02" in overlap
    deficit = next(w for w in resp.warnings if w.startswith("PROGRAMME-DEFICIT"))
    fallback = next(w for w in resp.warnings if w.startswith("SELECTION-FALLBACK"))
    # The copy must be unambiguous - the drawn plate is the plate's LEGAL
    # programme, not the requested selection, and the reader is told so in both
    # lines (a 200 must never be read as "my selection was placed").
    assert "legal programme" in fallback.lower(), fallback
    assert "not the selected layout" in deficit.lower() or "not drawn" in deficit.lower(), deficit
    assert resp.multi_storey.validation_gate["overall_status"] == "FAIL"
    assert (resp.qa.validation_gate_status or "") == "FAIL"
    unplaced = {str(u.get("room_id")) for u in (resp.unmet_requirements or [])}
    drawn_types = _types(resp)
    # The request must be partitioned into "drawn" and "named as unplaced" -
    # no selected room may vanish silently.  (The plate cap changes WHICH rooms
    # fit on this 8 x 40 m plot; the disclosure contract does not.)
    assert unplaced, resp.unmet_requirements
    assert unplaced.isdisjoint(drawn_types), (unplaced, drawn_types)
    assert set(TEN) <= drawn_types | unplaced, (drawn_types, unplaced)
    # Every unplaced row carries a reason (the UI ledger prints both).
    assert all(str(u.get("reason") or "").strip() for u in resp.unmet_requirements)
    # The same unplaced ids are named in the banner, not only in the ledger.
    assert all(rid in deficit for rid in unplaced), (deficit, unplaced)


def test_ten_room_selection_is_http_200_with_a_fail_stamp_not_422():
    body = {
        "plot_width_m": 8.0,
        "plot_depth_m": 40.0,
        "required_rooms": TEN,
        "building_typology": "T1_SINGLE_FAMILY",
        "floors": 1,
        "seed": "42",
        "vastu_strictness": "high",
        "include_scheme_alternatives": False,
    }
    r = client.post("/api/generate-floorplan", json=body)
    assert r.status_code == 200, r.text[:500]
    payload = r.json()
    assert payload["status"] != "failed"
    assert payload["multi_storey"]["floors"], "the selection path must still draw"
    assert any(w.startswith("ROOM-OVERLAP") for w in payload["warnings"])


def test_scheme_portfolio_never_reintroduces_the_422():
    """The additive ranked portfolio must follow the same selection policy.

    generate_ranked_schemes re-solves the requested partition for its reference
    metrics, so it raised the SAME bath_1/bed_2 overlap the main path had just
    recovered from and escaped as HTTP 422.  The UI always asks for the
    portfolio, so this was the user-facing refusal-by-crash.
    """
    r = client.post(
        "/api/generate-floorplan",
        json={
            "plot_width_m": 8.0,
            "plot_depth_m": 40.0,
            "required_rooms": TEN,
            "building_typology": "T1_SINGLE_FAMILY",
            "floors": 1,
            "seed": "42",
            "vastu_strictness": "high",
            "include_scheme_alternatives": True,
        },
    )
    assert r.status_code == 200, r.text[:400]
    payload = r.json()
    assert payload["status"] != "failed"
    assert payload["multi_storey"]["floors"]
    alts = payload.get("scheme_alternatives") or []
    assert alts, "the portfolio must still be attached"
    assert len(alts) in (1, 3)
    if len(alts) == 1:
        # A single alternative is legal only with the named disclosure.
        assert (payload.get("scheme_portfolio") or {}).get("provenance", {}).get(
            "no_material_alternative"
        )
    assert any(w.startswith("SCHEME-PORTFOLIO") for w in payload["warnings"]), payload["warnings"][:4]
    assert any(w.startswith("ROOM-OVERLAP") for w in payload["warnings"])


def test_impossible_selection_is_a_named_failure_not_a_422():
    # 10 rooms on an 8x10 m plot: even the natural programme is refused. The
    # answer is still an explicit failed response carrying the deficit banner.
    r = client.post(
        "/api/generate-floorplan",
        json={
            "plot_width_m": 8.0,
            "plot_depth_m": 10.0,
            "required_rooms": TEN,
            "building_typology": "T1_SINGLE_FAMILY",
            "floors": 1,
            "seed": "42",
            "vastu_strictness": "high",
            "include_scheme_alternatives": False,
        },
    )
    assert r.status_code == 200, r.text[:500]
    payload = r.json()
    assert payload["status"] == "failed"
    assert any(w.startswith("PROGRAMME-DEFICIT") for w in payload["warnings"])
    assert payload["unmet_requirements"]
