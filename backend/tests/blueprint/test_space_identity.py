"""Contracts: one ontology identity through labels, schedules, legend and PDF."""

from __future__ import annotations

import io
import re

import pytest

from app.schemas.floorplan import FloorPlanRequest
from app.schemas.multi_floor_plan import MultiFloorRoomRectangle
from app.services.floorplan.drawing_ir import build_drawing_ir, render_svg_from_ir
from app.services.floorplan.engine import SoleGeometryEngine
from app.services.floorplan.identity import (
    apply_room_identity,
    identity_dict,
    identity_is_outdoor,
    identity_is_wet,
    resolve_space_identity,
)
from app.services.floorplan.living_quality import audit_and_enforce_naming_honesty
from app.services.floorplan.ontology import ONTOLOGY


TYPOLOGIES = [
    ("T1_SINGLE_FAMILY", "residential_single"),
    ("T2_FAMILY_APARTMENT", "apartment"),
    ("T3_LARGE_COMPLEX", "commercial"),
    ("T4_WAREHOUSE", "warehouse"),
]


def _build(typology: str, floors: int = 2):
    req = FloorPlanRequest(
        plot_width_m=24.0,
        plot_depth_m=30.0,
        floors=floors,
        building_typology=typology,
    )
    return SoleGeometryEngine(req).solve()


def _all_rooms(building):
    return [r for fl in building.floors for r in fl.rooms]


@pytest.mark.parametrize("canonical,alias", TYPOLOGIES)
def test_every_room_gets_a_resolved_identity(canonical, alias):
    building = _build(alias)
    rooms = _all_rooms(building)
    assert rooms
    assert all(r.identity is not None for r in rooms)
    assert all(r.identity.source == "ontology" for r in rooms), [
        (r.room_id, r.identity.space_type_id) for r in rooms if r.identity.source != "ontology"
    ]
    assert all(r.space_type_id == r.identity.space_type_id for r in rooms)
    for r in rooms:
        assert r.identity.name == r.room_name
        assert r.identity.min_area_sqm > 0
        assert r.identity.min_width_m > 0
        assert r.identity.zone in {"public", "private", "service", "circulation"}

    summary = building.global_metrics["space_identity"]
    assert summary["rooms"] == len(rooms)
    assert summary["resolved"] == len(rooms)
    assert summary["fallback"] == []
    assert summary["coverage_pct"] == 100.0
    assert building.qa_report["space_identity"] == summary


def test_identity_is_serialized_on_flat_and_multi_storey_models():
    response = SoleGeometryEngine(
        FloorPlanRequest(
            plot_width_m=24.0,
            plot_depth_m=30.0,
            floors=1,
            building_typology="residential_single",
        )
    ).solve_floorplan_response()
    rect_rooms = response.rectangles.rooms if response.rectangles else []
    assert rect_rooms
    assert all(r.identity is not None for r in rect_rooms)
    assert all(p.identity is not None for p in response.placements)
    flat = {r.room_id: r.identity.name for r in rect_rooms}
    multi = {
        r.room_id: r.identity.name
        for fl in response.multi_storey.floors
        for r in fl.rooms
    }
    assert flat == multi


@pytest.mark.parametrize("canonical,alias", TYPOLOGIES)
def test_schedule_rows_read_the_same_identity(canonical, alias):
    building = _build(alias)
    checked = 0
    for fl in building.floors:
        model_rooms = {r.room_id: r for r in fl.rooms}
        for row in fl.room_schedule:
            rid = row["room_id"]
            room = model_rooms[rid]
            assert row["room_name"] == room.identity.name
            assert row["identity_name"] == room.identity.name
            assert row["space_type_id"] == room.identity.space_type_id
            assert row["identity"]["space_type_id"] == room.identity.space_type_id
            assert row["is_wet"] is room.identity.is_wet
            checked += 1
    assert checked > 0


def test_svg_and_pdf_labels_read_the_identity():
    building = _build("residential_single")
    fl = building.floors[0]
    ir = build_drawing_ir(floor_data=fl, building_model=building, gen_id="GEN-IDENTITY")
    svg = render_svg_from_ir(ir)
    svg_text = re.sub(r"<[^>]+>", " ", svg)

    from app.services.report_service import generate_pdf_report

    payload = {
        "request_id": "BW-IDENTITY",
        "timestamp": "2026-10-20 12:00:00 UTC",
        "multi_storey": building.model_dump(),
        "floor_plan": building.model_dump(),
        "floors": building.total_storeys,
    }
    pdf = generate_pdf_report(payload)
    import pypdf

    pdf_text = " ".join(
        " ".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(pdf.getvalue())).pages).split()
    )

    # The schedule is the complete label surface; SVG may abbreviate a core
    # label to its symbol, so assert the schedule carries every identity name
    # and that both rendered outputs carry the non-core labels.
    schedule_names = {row["room_name"] for row in ir.room_schedule}
    assert schedule_names == {room.identity.name for room in fl.rooms}
    # A large room's on-sheet label is the identity name; small rooms fall to
    # abbreviated tags/numbers by design.  The PDF legend is complete, so every
    # identity name must survive to the dossier.
    assert "LIVING ROOM" in svg_text.upper()
    for room in fl.rooms:
        assert room.identity.name in pdf_text, f"{room.room_id}: {room.identity.name} missing from PDF legend"


def test_pdf_legend_keeps_repeated_names_instead_of_deduping():
    from reportlab.platypus import Paragraph

    from app.services.report_service import make_floorplan_legend

    rooms = [
        {
            "room_id": f"bath_{i}",
            "room_name": "Common Bath",
            "space_type_id": "bath_2",
            "identity": {
                "space_type_id": "bath_2",
                "name": "Common Bath",
                "zone": "service",
                "function": "sanitation",
                "hygiene_class": "wet",
                "clear_area_basis": "clear_face",
                "min_area_sqm": 2.8,
                "min_width_m": 1.2,
                "max_aspect_ratio": 2.0,
                "is_wet": True,
                "source": "ontology",
            },
            "zone": "W",
            "zone_category": "service",
            "is_vertical_core": False,
        }
        for i in (1, 2)
    ]
    table = make_floorplan_legend({"rectangles": {"rooms": rooms}})
    text = " ".join(
        cell.text
        for row in table._cellvalues
        for cell in row
        if isinstance(cell, Paragraph)
    )
    assert text.count("Common Bath") == 2
    assert "1." in text and "2." in text
    assert "[Service]" in text
    assert "bath_2" in text


def test_service_layers_use_identity_outdoor_and_wet_flags():
    building = _build("residential_single")
    assert identity_is_outdoor({"identity": {"function": "outdoor"}})
    assert identity_is_wet({"identity": {"is_wet": True}})
    assert not identity_is_wet({"identity": {"is_wet": False}, "room_name": "Bathroom"})

    outdoor = [r for fl in building.floors for r in fl.rooms if identity_is_outdoor(r)]
    assert outdoor, "T1 with an upper floor should carry a balcony/terrace identity"
    for room in outdoor:
        assert room.identity.function == "outdoor"

    # Roof terraces (not balconies) receive the drainage layer.  The symbol is
    # selected from the identity's space_type_id, not a room-id substring.
    terrace = resolve_space_identity("terrace_F1", "T1_SINGLE_FAMILY").model_dump()
    floor_data = {
        "floor_index": 1,
        "floor_name": "First Floor",
        "envelope": {"x": 0, "y": 0, "width": 10, "depth": 10, "area_sqm": 100},
        "rooms": [{
            "room_id": "terrace_F1",
            "room_name": terrace["name"],
            "x": 0, "y": 0, "width_m": 5, "depth_m": 4, "area_sqm": 20,
            "zone": "N", "zone_category": "terrace",
            "space_type_id": "terrace", "identity": terrace,
        }],
        "doors": [], "windows": [],
    }
    ir = build_drawing_ir(
        floor_data=floor_data,
        building_model={
            "building_typology": "T1_SINGLE_FAMILY",
            "total_storeys": 2,
            "plot_width_m": 10,
            "plot_depth_m": 10,
            "seed": 42,
            "include_service_layer": True,
            "include_structural_sheet": False,
        },
        gen_id="GEN-IDENTITY",
        typology="T1_SINGLE_FAMILY",
    )
    prims = [p for p in ir.primitives if getattr(p, "layer", None) == "text"]
    texts = " ".join(getattr(p, "text", "") for p in prims).upper()
    assert "DRAIN" in texts
    assert "OVERFLOW" in texts


def test_resolver_corrects_coarse_aliases_and_unit_scope():
    assert ONTOLOGY.resolve_space_id("lobby_spine_F0", "T4_WAREHOUSE") == "distribution_lobby"
    assert ONTOLOGY.resolve_space_id("t4_deck_F1", "T4_WAREHOUSE") == "archive_deck"
    assert ONTOLOGY.resolve_space_id("t4_util_west_F1", "T4_WAREHOUSE") == "utility_strip"
    assert ONTOLOGY.resolve_space_id("t4_catwalk_F1", "T4_WAREHOUSE") == "viewing_catwalk"

    unit_a = resolve_space_identity("t2_unitA_bed_F0", "T2_FAMILY_APARTMENT", unit_id="Unit_A")
    unit_b = resolve_space_identity("t2_unitB_bed_F0", "T2_FAMILY_APARTMENT", unit_id="Unit_B")
    assert unit_a.space_type_id == unit_b.space_type_id == "unit_bed"
    assert unit_a.name == "Unit A Bedroom"
    assert unit_b.name == "Unit B Bedroom"
    assert unit_a.name != unit_b.name


def test_suite_identity_follows_l5_threshold():
    small = MultiFloorRoomRectangle(
        room_id="master_bed_F0",
        room_name="Master Suite",
        floor_index=0,
        x=0,
        y=0,
        width_m=3.0,
        depth_m=4.0,
        area_sqm=12.0,
        zone="SW",
        zone_category="private",
    )
    big = MultiFloorRoomRectangle(
        room_id="master_bed_F1",
        room_name="Master Suite",
        floor_index=1,
        x=0,
        y=0,
        width_m=3.75,
        depth_m=4.0,
        area_sqm=15.0,
        zone="SW",
        zone_category="private",
    )
    audit_and_enforce_naming_honesty([small, big])
    apply_room_identity(small, "T1_SINGLE_FAMILY")
    apply_room_identity(big, "T1_SINGLE_FAMILY")

    assert small.room_name == "Master Bedroom"
    assert small.identity.space_type_id == "master_bed"
    assert small.identity.name == "Master Bedroom"
    assert big.room_name == "Master Suite"
    assert big.identity.space_type_id == "master_suite"
    assert big.identity.name == "Master Suite"


def test_l5_does_not_mistake_an_ensuite_bath_for_a_master_suite():
    bath = MultiFloorRoomRectangle(
        room_id="ensuite_bath_F1",
        room_name="Master Bath (En-suite)",
        floor_index=1,
        x=0,
        y=0,
        width_m=3.2,
        depth_m=3.75,
        area_sqm=12.0,
        zone="W",
        zone_category="service",
    )
    assert audit_and_enforce_naming_honesty([bath]) == []
    assert bath.room_name == "Master Bath (En-suite)"
    assert bath.naming_threshold_used is None


def test_terrace_band_and_wing_ids_resolve_to_the_terrace_identity():
    """SPACE-IDENTITY fallback pin: solver-emitted outdoor ids are scheduled.

    `terrace_band_F2` / `terrace_wing_b_F1` are created by the solver, not by a
    typology programme.  They used to strip their floor suffix to an id the
    ontology did not know and stamp `unresolved:*` on every terrace, emitting
    a SPACE-IDENTITY fallback warning on a correctly-drawn plan.
    """
    req = FloorPlanRequest(
        plot_width_m=18.0,
        plot_depth_m=18.0,
        floors=3,
        building_typology="residential_single",
        terrace_bands={2: {"edge": "N", "depth_m": 3.0}},
    )
    building = SoleGeometryEngine(req).solve()
    terrace_rooms = [
        r for fl in building.floors for r in fl.rooms if r.zone_category == "terrace"
    ]
    assert any(r.room_id.startswith("terrace_band_") for r in terrace_rooms)
    for room in terrace_rooms:
        assert room.identity is not None
        assert room.identity.source == "ontology", (room.room_id, room.identity.space_type_id)
        assert room.identity.space_type_id == "terrace"
        assert room.identity.name == room.room_name
        assert ONTOLOGY.get_space(room.identity.space_type_id) is not None

    # The dropped-wing terrace id resolves too (same outdoor schedule entry).
    for rid in ("terrace_wing_b_F1", "terrace_band_F2"):
        resolved = ONTOLOGY.resolve_space_id(rid, "T1_SINGLE_FAMILY")
        assert resolved == "terrace", rid

    assert not [w for w in building.warnings if w.startswith("SPACE-IDENTITY")]
    summary = building.global_metrics["space_identity"]
    assert summary["fallback"] == []
    assert summary["coverage_pct"] == 100.0


def test_unknown_room_gets_an_explicit_fallback_identity():
    identity = resolve_space_identity(
        "mystery_room_F0",
        "T1_SINGLE_FAMILY",
        existing_name="Mystery Room",
        existing_zone_category="service",
    )
    assert identity.source == "fallback"
    assert identity.space_type_id == "unresolved:mystery_room_F0"
    assert identity.name == "Mystery Room"
    assert identity.zone == "service"
    assert identity.clear_area_basis == "gross"
