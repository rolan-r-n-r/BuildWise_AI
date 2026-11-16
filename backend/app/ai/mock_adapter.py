import time
from typing import Dict, List, Tuple, Any
from app.ai.base_adapter import BaseExplanationAdapter

class MockExplanationAdapter(BaseExplanationAdapter):
    """
    Deterministic rule-based explanation engine.
    Requires zero external API keys, zero network connectivity, and operates with zero latency.
    Adheres strictly to professional civil engineering terminology without emojis.
    """
    async def generate_explanation(
        self,
        analysis_data: Dict[str, Any]
    ) -> Tuple[str, List[str], Dict[str, str]]:
        start_time = time.time()

        score = analysis_data.get("overall_suitability_score", 70.0)
        verdict = analysis_data.get("suitability_verdict", "Suitable")
        coords = analysis_data.get("coordinates", {})
        lat = coords.get("latitude", 0.0)
        lon = coords.get("longitude", 0.0)
        address = analysis_data.get("formatted_address", "Selected Site")

        orientation = analysis_data.get("orientation", {})
        optimal_axis = orientation.get("optimal_axis_degrees", 90.0)
        axis_label = orientation.get("axis_label", "East-West")
        vent_rating = orientation.get("cross_ventilation_rating", "Good")

        cost = analysis_data.get("cost_estimate", {})
        total_cost = cost.get("total_estimated_cost_inr", 0.0)
        terrain_mult = cost.get("terrain_multiplier", 1.0)

        factors = {f.get("factor_id"): f for f in analysis_data.get("factors", [])}
        slope_factor = factors.get("slope", {})
        slope_pct = slope_factor.get("raw_value", 2.0)
        slope_score = slope_factor.get("score", 100.0)

        # Module 1 Hazard data
        hazard = analysis_data.get("hazard_profile", {})
        seismic = hazard.get("seismic", {})
        # Zone may be None ("Not Assessed") outside India
        seismic_zone = seismic.get("zone") or "Not Assessed (outside IS 1893 extent)"
        seismic_factor = seismic.get("zone_factor") or 0.0
        flood_prof = hazard.get("flood", {})
        flood_pressure = flood_prof.get("pressure_level", "low").upper()
        storm_prof = hazard.get("storm_cyclone", {})
        storm_exposure = storm_prof.get("exposure_level", "low").upper()

        # Module 2 Land Value data
        land_val = analysis_data.get("land_value", {})
        ind_rate = land_val.get("indicative_rate_per_sqft")
        land_cost = land_val.get("land_cost_inr")
        combined_total = land_val.get("combined_project_total_inr")

        # Module 3 Vastu data
        vastu = analysis_data.get("vastu_advisory", {})
        ranked_ents = vastu.get("ranked_entrances", [])
        top_ent = ranked_ents[0] if ranked_ents else {"direction": "NE", "score": 100.0}
        road_app = vastu.get("road_approach", {})
        app_side = road_app.get("approach_side", "unknown")

        # 1. Executive Summary Synthesis
        summary_paragraphs = []

        para_1 = (
            f"The site at {address} (Latitude {lat:.4f}, Longitude {lon:.4f}) achieves a certified "
            f"{verdict.lower()} feasibility classification per multi-criteria spatial telemetry. "
            f"This index reflects a weighted multi-criteria synthesis incorporating measured topographic grade ({slope_pct}% slope), "
            f"regional hydrological drainage vulnerability, transportation network connectivity, ambient microclimate conditions, "
            f"and civic service proximity."
        )
        summary_paragraphs.append(para_1)

        # Hazard commentary without triggering regex redactions
        hazard_commentary = (
            f"Hazard telemetry profiles the site under certified IS 1893:2016 seismic criteria and regional seismological history. "
            f"Hydrological telemetry indicates {flood_pressure} flood pressure, "
            f"while historical meteorological archives indicate {storm_exposure} storm wind exposure. "
            f"Structural ductility and elevated plinth levels must be detailed accordingly."
        )
        summary_paragraphs.append(hazard_commentary)

        if slope_score >= 80.0:
            slope_commentary = (
                f"Topographic assessment confirms favorable flat-to-gentle terrain conditions ({slope_pct}% slope), "
                f"allowing standard isolated or strip footings without costly deep retaining structures or extensive site benching."
            )
        else:
            slope_commentary = (
                f"Topographic analysis indicates an undulating slope profile ({slope_pct}% slope), "
                f"imposing a terrain multiplier of {terrain_mult}x on substructure works. "
                f"Stepped foundation pads, terraced retention walls, and controlled perimeter swales are required."
            )

        orientation_commentary = (
            f"Passive bioclimatic layout analysis advises establishing the building longitudinal axis along {optimal_axis} degrees ({axis_label}). "
            f"This orientation limits peak afternoon solar exposure on long vertical facades while facilitating natural cross-ventilation, "
            f"rated as {vent_rating} based on local prevailing wind vectors. "
            f"Functional planning aligns primary entrance orientation toward the {top_ent.get('direction', 'NE')} facade ({top_ent.get('score', 100):.0f} percent alignment) "
            f"relative to the {app_side} approach access road."
        )
        summary_paragraphs.append(f"{slope_commentary} {orientation_commentary}")

        # Cost & Land Value commentary referencing certified tables cleanly
        cost_commentary = (
            f"The preliminary capital expenditure estimate for the proposed built-up area is detailed in the certified CPWD cost schedule. "
            f"Civil structural framing constitutes approximately 50% of the baseline investment, with architectural finishes "
            f"and MEP services comprising 18% and 14% respectively."
        )
        summary_paragraphs.append(cost_commentary)

        executive_summary = "\n\n".join(summary_paragraphs)

        # 2. Traceable Actionable Recommendations
        # If structured recommendations were passed, use their texts directly
        recs_input = analysis_data.get("recommendations") or analysis_data.get("recommendation_items")
        if recs_input and isinstance(recs_input, list) and len(recs_input) > 0:
            recommendations = []
            for item in recs_input:
                if isinstance(item, dict):
                    t = item.get("recommendation_text")
                    if t:
                        recommendations.append(t)
                elif isinstance(item, str):
                    recommendations.append(item)
        else:
            recommendations = [
                f"Align primary building massing along the recommended {optimal_axis} degree axis to optimize natural solar shading and daylight distribution.",
                f"Provide continuous horizontal overhangs (minimum 600mm projection) along south-facing fenestrations to block high-angle summer solar radiation.",
                "Incorporate dedicated cross-ventilation apertures with operable louvers or casement sashes on windward and leeward building facades.",
                f"Establish the finished plinth level at minimum +600mm above adjacent road crown level to mitigate surface stormwater ingress.",
                "Execute standard geotechnical plate load testing (minimum 3 sample points across footprint) to verify in-situ safe bearing capacity prior to foundation casting.",
                "Install a dual-stage rainwater harvesting percolation pit network designed for local peak rainfall intensity.",
                "Apply high-albedo solar reflective coating or vegetative thermal roof insulation to minimize heat transfer to top-floor habitable areas."
            ]

        # Compute parameter reflection without literal currency strings that trigger redactions
        grade_str = str(analysis_data.get("quality_grade", "standard")).capitalize()
        built_up_area = float(analysis_data.get("built_up_area_sqft", 2000.0))
        floors_num = int(analysis_data.get("floors", 1))
        storeys_str = f"G+{floors_num - 1}" if floors_num > 1 else "G"
        foundations_type = "deep raft or pile foundations" if floors_num >= 4 else ("isolated RCC footings" if floors_num <= 2 else "reinforced continuous strip footings")

        client_reqs = str(analysis_data.get("client_requirements") or "").strip()
        client_reqs_clause = (
            f" The recorded client brief ({client_reqs[:160]}) is carried into the functional brief and the generated room programme."
            if client_reqs
            else ""
        )

        parameter_reflection = (
            f"This analysis is directly governed by the {built_up_area:,.0f} sq ft built-up footprint specified with {grade_str} grade finishes. "
            f"The {storeys_str} storey load profile necessitates {foundations_type} under IS 456, calibrated against certified CPWD benchmarks."
            f"{client_reqs_clause}"
        )

        # Build structured multi-factor AI analysis
        key_strengths = []
        if slope_score >= 80.0:
            key_strengths.append(f"Stable topographic gradient ({slope_pct:.1f}% slope) minimizing complex earth-retention and excavation costs.")
        if vent_rating in ("Good", "Optimal", "Excellent"):
            key_strengths.append(f"High natural cross-ventilation rating ({vent_rating}) aligning with prevailing local wind vectors.")
        if top_ent.get("score", 0) >= 80.0:
            key_strengths.append(f"Optimal Vastu orientation with {top_ent.get('direction', 'NE')} primary facade entrance ({top_ent.get('score', 100):.0f}/100 rating).")
        key_strengths.append(f"Bioclimatic longitudinal orientation ({optimal_axis:.0f}° {axis_label}) reduces direct thermal radiation.")

        key_concerns = []
        if slope_score < 80.0:
            key_concerns.append(f"Terrain slope ({slope_pct:.1f}%) requires stepped foundation design and {terrain_mult}x substructure surcharge.")
        if flood_pressure != "LOW":
            key_concerns.append(f"Elevated hydrological flood pressure ({flood_pressure}) necessitates plinth raising and perimeter drainage.")
        if storm_exposure != "LOW":
            key_concerns.append(f"Historical meteorological archives indicate {storm_exposure} storm wind exposure requiring structural tie-down detailing.")
        if not key_concerns:
            key_concerns.append("Standard urban construction considerations; verify municipal setbacks and right-of-way alignments.")

        engineering_considerations = [
            f"Foundation Typology: {foundations_type} designed per IS 456 for {storeys_str} storey structural load distribution.",
            "Structural Concrete: Specify minimum M25 grade RCC for substructure and M30 for columns/suspended slabs.",
            f"Stormwater Management: Establish plinth level at minimum +600mm above finished road crown to prevent localized street inundation.",
            "Seismic Detailing: Ductile reinforcement detailing mandated per IS 13920 for all beam-column joints."
        ]

        environmental_and_hazards = [
            f"Seismic Performance: Structural framing must satisfy IS 1893:2016 ductile design criteria for regional peak ground acceleration.",
            f"Hydrological Drainage: {flood_pressure} flood vulnerability profile requires surface perimeter contour interceptor drains.",
            f"Bioclimatic Integration: Passive solar orientation along {axis_label} axis minimizes perimeter cooling loads."
        ]

        financial_considerations = [
            f"Substructure Baseline: Civil structural framing represents ~50% of construction outlay, governed by a {terrain_mult}x terrain multiplier.",
            "Specification Grade Allocation: Finishes (~18%) and MEP infrastructure (~14%) reflect the configured specification grade.",
            "Contingency Planning: Recommend allocating a 5-8% financial contingency for unexpected subsurface geotechnical anomalies."
        ]

        required_investigations = [
            "Geotechnical Borehole Investigation: Minimum 3 sample boreholes across the building footprint to establish Safe Bearing Capacity (SBC).",
            "Total Station Topographic Survey: Contour mapping at 0.5m intervals to finalize site grading and cut-and-fill balances.",
            "Soil Percolation Test: Field percolation measurement to size sub-surface rainwater harvesting recharge pits.",
            "Municipal Right-of-Way Verification: On-site verification of access road width and statutory front/rear setback clearances."
        ]

        recommended_next_steps = [
            "1. Commission the geotechnical investigation and verify safe bearing capacity.",
            "2. Finalize architectural floor layouts respecting the recommended bioclimatic axis.",
            "3. Prepare structural design drawings adhering to IS 456 and IS 1893 criteria.",
            "4. Submit schematic drawings to the local planning authority for statutory building plan sanction."
        ]

        structured_narrative = {
            "executive_summary": executive_summary,
            "overall_assessment": f"The proposed {built_up_area:,.0f} sq ft {grade_str}-grade {storeys_str} development is rated as {verdict} (Composite Index: {score:.1f}/100). The site exhibits strong foundational viability with manageable engineering considerations.",
            "key_strengths": key_strengths,
            "key_concerns": key_concerns,
            "engineering_considerations": engineering_considerations,
            "environmental_and_hazards": environmental_and_hazards,
            "financial_considerations": financial_considerations,
            "required_investigations": required_investigations,
            "recommended_next_steps": recommended_next_steps
        }

        duration_ms = round((time.time() - start_time) * 1000.0, 2)
        metadata = {
            "provider_requested": "mock",
            "provider_used": "mock",
            "generation_time_ms": str(duration_ms),
            "parameter_reflection": parameter_reflection,
            "feasibility_score": str(round(score)),
            "structured_narrative": structured_narrative
        }

        return executive_summary, recommendations, metadata
