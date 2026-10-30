import io
import pytest
import pypdf
from app.services.report_service import (
    CONTENT_WIDTH_PT,
    draw_floorplan_reportlab,
    generate_pdf_report,
    make_land_economics_table,
)
from app.schemas.floorplan import FloorPlanRequest
from app.services.floorplan.floorplan_service import generate_floor_plan
from app.schemas.site_vision import SiteVisionResponse, PreservationItem


def test_pdf_report_v9_comprehensive():
    # 1. Prepare floorplan
    fp_req = FloorPlanRequest(
        plot_width_m=12.0,
        plot_depth_m=15.0,
        required_rooms=["master_bed", "living", "kitchen", "puja", "dining", "bath_1", "bed_2"],
        vastu_strictness="high"
    )
    fp_res = generate_floor_plan(fp_req)

    # 2. Prepare site vision
    item = PreservationItem(
        cluster_id="tree-cluster-1",
        area_sqm=120.0,
        centroid=[77.5946, 12.9716],
        mean_ndvi=0.68,
        overlap_footprint=True,
        rank="preserve",
        action="Preserve mature root zone with protective silt fencing"
    )
    sv_res = SiteVisionResponse(
        mode="segformer",
        green_cover_pct=34.5,
        water_cover_pct=2.1,
        built_up_pct=15.0,
        preservation_plan=[item]
    )

    # 3. Prepare full payload with duplicate rule IDs and parameter reflection
    payload = {
        "request_id": "BW-2026-TEST-9999",
        "timestamp": "2026-09-24 14:30:00 UTC",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "45 Richmond Road, Bengaluru, Karnataka, India",
        "overall_suitability_score": 83.5,
        "suitability_verdict": "High Feasibility",
        "built_up_area_sqft": 2400.0,
        "quality_grade": "premium",
        "floors": 2,
        "parameter_reflection": "Analysis strictly reflects 2,400 sq ft area with Premium grade finishes and G+1 storeys.",
        "engineering_summary": "Comprehensive structural feasibility confirms excellent soil bearing capacity and optimal orientation.",
        "factors": [
            {"factor_id": "slope", "name": "Topographic Slope", "weight": 0.25, "score": 92.0, "status": "Optimal", "raw_value": 1.5, "unit": "%", "details": "Nearly flat gradient with natural drainage"},
            {"factor_id": "flood_risk", "name": "Flood Inundation Risk", "weight": 0.25, "score": 85.0, "status": "Optimal", "raw_value": 0.2, "unit": "m", "details": "Low catchment accumulation area"},
            {"factor_id": "road_access", "name": "Road Connectivity", "weight": 0.20, "score": 80.0, "status": "Optimal", "raw_value": 12.0, "unit": "m", "details": "12m wide asphalt access corridor"},
            {"factor_id": "facility_proximity", "name": "Urban Infrastructure", "weight": 0.15, "score": 75.0, "status": "Optimal", "raw_value": 1.2, "unit": "km", "details": "Proximity to power grid and water mains"},
            {"factor_id": "environmental_comfort", "name": "Passive Solar Index", "weight": 0.15, "score": 82.0, "status": "Optimal", "raw_value": 90, "unit": "deg", "details": "Favourable east-west axis orientation"}
        ],
        "hazard_profile": {
            "seismic": {"zone": "Zone II", "zone_factor": 0.10, "event_count_display": "2", "max_magnitude": 3.8},
            "flood": {"discharge_peak_to_mean_ratio": 1.4, "pressure_level": "low", "ndma_flood_prone": False},
            "storm_cyclone": {"max_annual_gust_kmh": 62.4, "extreme_rainfall_days": 1.2, "ndma_cyclone_prone": False}
        },
        "orientation": {
            "optimal_axis_degrees": 90,
            "axis_label": "East-West",
            "prevailing_wind_direction_degrees": 240.0,
            "cross_ventilation_rating": "Optimal",
            "passive_design_rationale": "Orienting principal fenestrations along the North-South axis minimizes peak solar thermal gain."
        },
        "vastu_advisory": {
            "road_approach": {"approach_side": "north", "is_fallback": False},
            "ranked_entrances": [{"direction": "North-East", "score": 95}, {"direction": "North", "score": 88}],
            "slope_reading": {"drainage_direction": "North-East", "auspiciousness": "optimal", "remedy_notes": "Natural grade slopes towards Ishanya (NE), fostering ideal drainage."},
            "overall_compliance_rating": "Optimal"
        },
        "cost_estimate": {
            "base_cost_inr": 4800000,
            "base_rate_per_sqft": 2000,
            "terrain_multiplier": 1.05,
            "terrain_surcharge_inr": 240000,
            "total_estimated_cost_inr": 5040000,
            "cost_range_min_inr": 4662000,
            "cost_range_max_inr": 5418000,
            "breakdown": [
                {"category": "Substructure & Foundation", "amount_inr": 882000, "percentage": 17.5, "description": "Earthwork, isolated RCC footings, and anti-termite treatment."},
                {"category": "Superstructure RCC", "amount_inr": 1764000, "percentage": 35.0, "description": "RCC M25 grade frame, columns, beams, and 125mm slab."},
                {"category": "Masonry & Plaster", "amount_inr": 756000, "percentage": 15.0, "description": "AAC lightweight blocks with 12mm cement plaster."},
                {"category": "Finishes & MEP", "amount_inr": 1638000, "percentage": 32.5, "description": "Vitrified flooring, CPWD specification sanitary and electrical fittings."}
            ]
        },
        "land_value": {
            "indicative_rate_per_sqft": 4500,
            "plot_area_sqft": 2000,
            "land_cost_inr": 9000000,
            "combined_project_total_inr": 14040000,
            "locality_multiplier": 1.15,
            "source_publication": "Karnataka Stamps & Registration Dept Circle Rates 2026",
            "disclaimer": "Indicative baseline circle rate. Market transactions may vary by ±15%."
        },
        "risks": [
            {"title": "Expansive Clay Subsoil", "severity": "moderate", "description": "Black cotton soil pockets detected in local geological strata.", "mitigation_strategy": "Design under-reamed piles or sand cushion beneath isolated footings."},
            {"title": "Monsoon Water Logging", "severity": "low", "description": "Potential localized surface runoff accumulation during storm events.", "mitigation_strategy": "Incorporate perimeter peripheral swales and rainwater harvesting recharge pits."}
        ],
        "recommendation_items": [
            # Include duplicated rule_ids to verify deduplication
            {"rule_id": "RULE-STR-01", "category_label": "Structural", "severity": "high", "trigger_condition": "Seismic Zone II & G+1", "source_data_ref": "IS 1893:2016", "recommendation_text": "Adopt ductile detailing of reinforced concrete frames per IS 13920."},
            {"rule_id": "RULE-STR-01", "category_label": "Structural", "severity": "high", "trigger_condition": "Seismic Zone II & G+1", "source_data_ref": "IS 1893:2016", "recommendation_text": "Adopt ductile detailing of reinforced concrete frames per IS 13920."},
            {"rule_id": "RULE-GEO-02", "category_label": "Geotechnical", "severity": "advisory", "trigger_condition": "Expansive subgrade", "source_data_ref": "IS 2911:2010", "recommendation_text": "Conduct standard penetration test (SPT) boreholes up to 6m depth."},
            {"rule_id": "RULE-GEO-02", "category_label": "Geotechnical", "severity": "advisory", "trigger_condition": "Expansive subgrade", "source_data_ref": "IS 2911:2010", "recommendation_text": "Conduct standard penetration test (SPT) boreholes up to 6m depth."}
        ]
    }

    # Generate PDF
    pdf_buffer = generate_pdf_report(payload, site_vision=sv_res.model_dump(), floor_plan=fp_res.model_dump())
    pdf_bytes = pdf_buffer.getvalue()
    assert pdf_bytes.startswith(b"%PDF"), "Must produce valid PDF binary"

    # Read and inspect PDF structure
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    num_pages = len(reader.pages)
    assert num_pages >= 3, f"Expected multi-page report, got {num_pages} pages"

    # Check font embedding (Inter must be in font list)
    fonts_embedded = set()
    for page in reader.pages:
        if "/Resources" in page and "/Font" in page["/Resources"]:
            for font_key, font_obj in page["/Resources"]["/Font"].items():
                base_font = str(font_obj.get("/BaseFont", ""))
                fonts_embedded.add(base_font)

    inter_fonts = [f for f in fonts_embedded if "Inter" in f]
    assert len(inter_fonts) > 0, f"Inter fonts must be embedded in PDF font list, found: {fonts_embedded}"

    # Extract all text across pages
    full_text = ""
    pages_text = []
    for idx, page in enumerate(reader.pages):
        t = page.extract_text() or ""
        pages_text.append(t)
        full_text += f"\n--- PAGE {idx+1} ---\n" + t

    # 1. Verify calibration paragraph appears EXACTLY ONCE
    calib_needle = "AI Parameter Calibration"
    assert full_text.count(calib_needle) == 1, (
        f"Expected '{calib_needle}' to appear exactly 1 time, but found {full_text.count(calib_needle)} times"
    )

    # 2. Verify section headers exist and are in exact tab order
    expected_sections = [
        "01  Multi-Criteria Land Suitability Assessment",
        "02  Engineering Commentary & Action Plan",
        "03  Hazard History & Climate Stress Profile",
        "04  Site Constraints & Risk Mitigation Matrix",
        "05  Ecological Site Vision & Tree Preservation Plan",
        "06  Passive Solar & Aerodynamic Orientation Strategy",
        "07  Vastu Shastra & Functional Planning Advisory",
        "08  Preliminary Construction Cost Estimate",
        "09  Indicative Land Valuation & Project Outlay",
        "10  Generative Architectural Blueprint"
    ]
    last_pos = -1
    for sec in expected_sections:
        # Check that sec appears in full_text
        # Clean spacing for robust match
        sec_num = sec[:2]
        sec_title = sec[4:]
        assert sec_num in full_text, f"Section number {sec_num} missing"
        assert sec_title in full_text, f"Section title '{sec_title}' missing"

        pos = full_text.find(sec_title)
        assert pos > last_pos, f"Section '{sec_title}' at pos {pos} is out of order (previous was {last_pos})"
        last_pos = pos

    # 3. Verify Blueprint has dedicated page
    # Find which page has Section 10
    blueprint_page_idx = -1
    for idx, pt in enumerate(pages_text):
        if "Generative Architectural Blueprint" in pt:
            blueprint_page_idx = idx
            break
    assert blueprint_page_idx >= 0, "Blueprint section must be found"
    # Blueprint page should contain Blueprint header and solver stat tiles
    bp_text = pages_text[blueprint_page_idx]
    assert "Vastu Compliance" in bp_text
    assert "Plumbing Adjacency" in bp_text
    assert "Space Utilization" in bp_text
    assert "FRONTAGE" in bp_text

    # 4. Verify Ecology 5-tile stat strip
    eco_text = ""
    for pt in pages_text:
        if "Ecological Site Vision" in pt:
            eco_text = pt
            break
    assert "Green Cover" in eco_text
    assert "Canopy Clusters" in eco_text
    assert "Water Cover" in eco_text
    assert "Built-up Ratio" in eco_text
    assert "Acquisition" in eco_text
    assert "Copernicus Sentinel-2" in eco_text

    # 5. Verify Footers have "Page X of Y" and "BuildWise AI - Confidential Preliminary Assessment"
    for idx, pt in enumerate(pages_text):
        expected_footer = f"Page {idx+1} of {num_pages}"
        assert expected_footer in pt, f"Footer '{expected_footer}' missing on page {idx+1}"
        assert "BuildWise AI - Confidential Preliminary Assessment" in pt, f"Confidential title missing on page {idx+1}"

    # 6. Verify Cost table has +/- range line
    assert "Range: INR" in full_text
    assert "±7.5%" in full_text or "+/-7.5%" in full_text

    # 7. Verify Unique rule IDs in Action plan (no duplicates)
    action_page_text = ""
    for pt in pages_text:
        if "Engineering Commentary & Action Plan" in pt:
            action_page_text += pt
    # Both RULE-STR-01 and RULE-GEO-02 were supplied twice in the payload; they should only appear once
    assert action_page_text.count("RULE-STR-01") == 1, "Duplicate RULE-STR-01 found in Action Plan"
    assert action_page_text.count("RULE-GEO-02") == 1, "Duplicate RULE-GEO-02 found in Action Plan"


def test_pdf_report_edge_cases():
    """Verify that report_service handles None fields, missing sections, string-numbers, and malformed inputs gracefully."""
    # 1. Completely empty payload
    buf1 = generate_pdf_report({})
    assert buf1.getvalue().startswith(b"%PDF")

    # 2. Explicit None for all major sections
    payload_none = {
        "factors": None,
        "risks": None,
        "recommendation_items": None,
        "detailed_recommendations": None,
        "hazard_profile": None,
        "orientation": None,
        "vastu_advisory": None,
        "cost_estimate": None,
        "land_value": None,
        "floor_plan": None,
        "site_vision": None
    }
    buf2 = generate_pdf_report(payload_none)
    assert buf2.getvalue().startswith(b"%PDF")

    # 3. String representations of numeric values
    payload_strings = {
        "overall_suitability_score": "82.5",
        "floors": "3",
        "cost_estimate": {
            "base_cost_inr": "1000000",
            "base_rate_per_sqft": "2500",
            "total_estimated_cost_inr": "1200000",
            "cost_range_min_inr": "1100000",
            "cost_range_max_inr": "1300000",
            "breakdown": [
                {"category": "Civil", "amount_inr": "500000", "percentage": "41.7", "description": "Works"}
            ]
        }
    }
    buf3 = generate_pdf_report(payload_strings)
    assert buf3.getvalue().startswith(b"%PDF")

    # 4. Site vision with None values in metrics and items
    sv_none = {
        "mode": "segformer",
        "green_cover_pct": None,
        "water_cover_pct": None,
        "built_up_pct": None,
        "tree_clusters": None,
        "preservation_plan": [
            {"cluster_id": "c1", "area_sqm": None, "rank": None, "action": None}
        ]
    }
    buf4 = generate_pdf_report({"request_id": "TEST-SV-NONE"}, site_vision=sv_none)
    assert buf4.getvalue().startswith(b"%PDF")

    # 5. Floor plan with None fields in rectangles
    fp_none = {
        "metrics": {
            "vastu_compliance_pct": None,
            "plumbing_adjacency_score": None,
            "space_utilization_pct": None,
            "total_built_up_sqm": None
        },
        "rectangles": {
            "envelope": {"x": None, "y": None, "width": None, "height": None},
            "rooms": [{"room_id": "living", "x": None, "y": None, "width": None, "height": None, "area_sqm": None}],
            "doors": [{"door_id": "d1", "x1": None, "y1": None, "x2": None, "y2": None}],
            "windows": [{"window_id": "w1", "x1": None, "y1": None, "x2": None, "y2": None}]
        }
    }
    buf5 = generate_pdf_report({"request_id": "TEST-FP-NONE"}, floor_plan=fp_none)
    assert buf5.getvalue().startswith(b"%PDF")


def test_pdf_report_multi_storey_dossier():
    """
    Verifies that multi-storey floor plan generates Sheet 10.0 (Stacking Analysis)
    and dedicated A4 sheets for each floor level (10.1, 10.2, etc.) with exact Page X of Y footers.
    """
    fp_req = FloorPlanRequest(
        plot_width_m=20.0,
        plot_depth_m=18.0,
        floors=4,
        building_typology="T2_FAMILY_APARTMENT",
        vastu_strictness="medium",
        required_rooms=["living", "kitchen", "master_bed", "bath_1", "dining", "stairs", "lift"]
    )
    fp_res = generate_floor_plan(fp_req)
    assert fp_res.multi_storey is not None
    assert len(fp_res.multi_storey.floors) == 4

    payload = {
        "request_id": "BW-2026-MULTI-STOREY-TEST",
        "timestamp": "2026-09-25 12:00:00 UTC",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Bengaluru Multi-Storey Test Site",
        "overall_suitability_score": 88.0,
        "suitability_verdict": "Optimal Development Suitability",
        "built_up_area_sqft": 4800.0,
        "quality_grade": "premium",
        "floors": 4,
        "building_typology": "T2_FAMILY_APARTMENT",
        "engineering_summary": "4-storey residential apartment with continuous locked core shafts.",
    }

    pdf_buf = generate_pdf_report(payload, floor_plan=fp_res.model_dump())
    pdf_bytes = pdf_buf.getvalue()
    assert pdf_bytes.startswith(b"%PDF")

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    num_pages = len(reader.pages)
    # Minimal payload (1 page) + Sheet 10.0 (dossier incl. universal gate layer
    # table) + the land-economics certificate page (kept together with
    # the legal advisory so neither orphans) + 4 floor sheets = 8 structural
    # pages.  This fixture is certified but its plan carries PROP-* advisories,
    # and those rows now print on page 1 for parity with the in-app Print
    # Report, so the banner paginates and adds pages. The anti-orphan
    # intent is checked structurally below: every dossier/floor sheet present
    # and continuous "Page N of M" footers on every page.
    assert num_pages >= 8, f"Expected at least 8 structural pages, got {num_pages}"

    pages_text = [page.extract_text() for page in reader.pages]
    full_text = "\n--- PAGE ---\n".join(pages_text)

    # 1. Verify Sheet 10.0 Stacking Analysis
    assert "10.0" in full_text
    assert "Multi-Storey Architectural Dossier & Core Stacking Analysis" in full_text
    assert "Vertical Cores Locked" in full_text or "100% Locked" in full_text
    assert "NBC 2016" in full_text

    # 2. Verify all 4 floor sheets exist
    assert "10.1" in full_text
    assert "10.2" in full_text
    assert "10.3" in full_text
    assert "10.4" in full_text
    assert "Ground Floor" in full_text or "GROUND FLOOR" in full_text
    assert "Elevation" in full_text

    # 2b. The land-economics certificate is a content layer on the
    # dossier, with its own verdict, not a browser-side re-derivation.
    assert "LAND ECONOMICS" in full_text
    assert "SPACE-EFFICIENCY" in full_text

    # 3. Verify running footer consistency on all pages
    for idx, pt in enumerate(pages_text):
        expected_footer = f"Page {idx+1} of {num_pages}"
        assert expected_footer in pt, f"Footer '{expected_footer}' missing on page {idx+1}"


def test_land_economics_table_is_four_columns_and_stays_inside_the_frame():
    """Four KPI cells must not make ReportLab invent a fifth, off-page column.

    Regression: the table declared three widths but appended four KPI cells.
    ReportLab padded every row to four columns, grew the table to 636 pt and
    centred it off-page, so the first and last columns were clipped on the
    continuation page of every dossier ("D ECONOMICS...", "-use efficiency").
    """
    land = {
        "land_use_efficiency_pct": 90.0,
        "circulation_ratio_pct": 12.0,
        "waste_area_sqm": 0.0,
        "waste_pct": 0.0,
        "footprint_utilization_pct": 99.0,
        "footprint_area_sqm": 108.0,
        "footprint_source": "coverage",
        "program_deficit_sqm": 0.0,
        "floor_area_ratio": 0.6,
        "sliver_count": 0,
        "absorbed_residual_count": 0,
        "certificate": {
            "status": "WARN",
            "checks": {"land_use": True, "circulation": False},
            "warnings": ["LAND-03 Circulation ratio 21.5% is outside the 12-20% target band."],
        },
    }
    flowables = make_land_economics_table(land)
    table = next(flowable for flowable in flowables if hasattr(flowable, "_cellvalues"))
    assert [len(row) for row in table._cellvalues] == [4, 4, 4, 4, 4]
    table.wrap(CONTENT_WIDTH_PT, 1000.0)
    assert table._width <= CONTENT_WIDTH_PT + 0.01, (
        f"land table {table._width:.2f} pt exceeds the A4 frame {CONTENT_WIDTH_PT:.2f} pt"
    )


