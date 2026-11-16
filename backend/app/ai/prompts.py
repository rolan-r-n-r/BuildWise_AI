"""
Prompts for BuildWise Civil and Structural Engineering AI adapters.
Adheres strictly to CPWD benchmarks, IS 456, IS 1893, and NBC 2016.
"""
"""
Prompts for BuildWise Civil and Structural Engineering AI adapters.
Adheres strictly to CPWD benchmarks, IS 456, IS 1893, and NBC 2016.
"""
from typing import Dict, Any, Optional

CIVIL_ENGINEER_SYSTEM_PROMPT = """You are an elite Indian Civil and Structural Engineer AI and Chief Architectural Site Planning Consultant, specializing in CPWD (Central Public Works Department) benchmarks, IS 456 (Plain and Reinforced Concrete), IS 1893:2016 (Criteria for Earthquake Resistant Design), and NBC 2016 (National Building Code of India).

Your task is to analyze a construction site feasibility study using the authoritative deterministic telemetry and calculations provided, and synthesize a rigorous, highly insightful civil engineering narrative.

CRITICAL RULES:
1. MATHEMATICAL ACCURACY & AUTHORITATIVE FIDELITY: The provided suitability score, certified CPWD cost schedule, seismic zone, measured slope, and orientation data are already certified and authoritative. Do NOT contradict, recalculate, or invent conflicting numbers. Do NOT fabricate arbitrary currency amounts or guess alternate seismic zones.
2. PARAMETER REFLECTION: Your analysis must explicitly reflect the user inputs. For the specific storey count and typology, provide concrete structural recommendations under IS 456 (e.g., foundation typology, concrete grade M25/M30, reinforcement ductility detailing per IS 13920, lateral load resisting systems). Reflect any provided client brief requirements into functional planning and spatial zoning.
3. SEISMIC ZONE: Ground structural recommendations in the certified Seismic Zone provided in the dossier under IS 1893. Deeply analyze how seismic ductility, measured terrain slope, soil drainage, and wind exposure govern the building envelope and substructure.
4. NO FLUFF: Output ONLY valid JSON matching the specified response schema. No markdown wrapping, no introductory commentary, no trailing prose."""


def build_rich_site_analysis_prompt(analysis_data: Dict[str, Any]) -> str:
    """
    Builds a comprehensive civil engineering prompt containing the complete certified
    deterministic telemetry and calculations so the AI model provides deep, contextual
    intelligence without hallucinating report figures.
    """
    coords = analysis_data.get("coordinates", {})
    lat = coords.get("latitude", 0.0)
    lon = coords.get("longitude", 0.0)
    address = analysis_data.get("formatted_address", "Selected Site")

    area = analysis_data.get("built_up_area_sqft", 2000.0)
    grade = analysis_data.get("quality_grade", "standard")
    typology = analysis_data.get("building_typology", "residential_single")
    floors = analysis_data.get("floors", 1)
    storeys_str = f"G+{floors - 1}" if isinstance(floors, int) and floors > 1 else ("G" if floors == 1 else str(floors))
    coverage = analysis_data.get("ground_coverage_ratio", 0.60)
    client_reqs = analysis_data.get("client_requirements", "")

    # Topography & Factors
    factors = {f.get("factor_id"): f for f in analysis_data.get("factors", []) if isinstance(f, dict)}
    slope_factor = factors.get("slope", {})
    slope_pct = slope_factor.get("raw_value", 2.0)
    slope_score = slope_factor.get("score", 100.0)

    road_factor = factors.get("road_access", factors.get("road", {}))
    road_dist = road_factor.get("raw_value")

    # Hazard profile
    hazard = analysis_data.get("hazard_profile", {})
    seismic = hazard.get("seismic", {})
    seismic_zone = seismic.get("zone", "Zone II")
    seismic_factor = seismic.get("zone_factor", 0.10)
    flood = hazard.get("flood", {})
    flood_level = flood.get("pressure_level", "low")
    storm = hazard.get("storm_cyclone", {})
    storm_level = storm.get("exposure_level", "low")
    max_gust = storm.get("max_annual_gust_kmh", 45.0)

    # Orientation & Climate
    orientation = analysis_data.get("orientation", {})
    optimal_axis = orientation.get("optimal_axis_degrees", 90.0)
    axis_label = orientation.get("axis_label", "East-West")
    vent_rating = orientation.get("cross_ventilation_rating", "Good")
    wind_dir = orientation.get("prevailing_wind_direction_degrees", 225.0)

    # Cost & Valuation
    cost = analysis_data.get("cost_estimate", {})
    base_rate = cost.get("base_rate_per_sqft", 2200.0)
    terrain_mult = cost.get("terrain_multiplier", 1.0)
    total_cost = cost.get("total_estimated_cost_inr", 0.0)

    land_val = analysis_data.get("land_value", {})
    ind_rate = land_val.get("indicative_rate_per_sqft")
    land_cost = land_val.get("land_cost_inr")

    # Vastu & Access
    vastu = analysis_data.get("vastu_advisory", {})
    ranked_ents = vastu.get("ranked_entrances", [])
    top_ent = ranked_ents[0] if ranked_ents else {"direction": "North-East", "score": 100.0}
    road_app = vastu.get("road_approach", {})
    app_side = road_app.get("approach_side", "north")

    # Composite Score
    score = analysis_data.get("overall_suitability_score", 75.0)
    verdict = analysis_data.get("suitability_verdict", "Suitable")

    lines = [
        "PERFORM ADVANCED CIVIL & STRUCTURAL ENGINEERING SYNTHESIS FOR THE FOLLOWING CERTIFIED SITE DOSSIER:",
        "",
        "1. PROJECT SPECIFICATIONS & USER INPUTS:",
        f"  - Location: {address} (Lat: {lat:.5f}, Lon: {lon:.5f})",
        f"  - Built-Up Area: {area:,.0f} sq ft",
        f"  - Typology: {typology}",
        f"  - Height / Storeys: {storeys_str} ({floors} levels total)",
        f"  - Specification Grade: {grade.capitalize()}",
        f"  - Ground Coverage Target: {coverage * 100:.0f}%",
    ]

    if client_reqs and str(client_reqs).strip():
        lines.append(f"  - Client Design Brief: {str(client_reqs).strip()}")

    lines.extend([
        "",
        "2. AUTHORITATIVE DETERMINISTIC EVALUATION:",
        f"  - Composite Suitability Score: {score:.1f} / 100 (Verdict: {verdict})",
        f"  - Measured Terrain Slope: {slope_pct:.1f}% (Substructure Multiplier: {terrain_mult}x, Slope Score: {slope_score:.1f}/100)",
        f"  - Seismic Hazard (BIS IS 1893:2016): {seismic_zone} (Zone Factor Z={seismic_factor})",
        f"  - Hydrological Flood Pressure: {flood_level.upper()}",
        f"  - Meteorological Wind Exposure: {storm_level.upper()} (Peak Gusts: {max_gust} km/h)",
        f"  - Bioclimatic Optimal Axis: {optimal_axis:.0f}° ({axis_label}) with prevailing wind at {wind_dir:.0f}°, ventilation rating: {vent_rating}",
        f"  - Primary Recommended Entrance: {top_ent.get('direction', 'NE')} facade ({top_ent.get('score', 100):.0f}/100) from {app_side} road approach",
        f"  - Road Distance: {f'{road_dist:.1f} meters' if road_dist is not None else 'Direct frontage verified'}",
        f"  - Certified CPWD Benchmark Total: INR {total_cost:,.0f} (Base rate approx INR {base_rate:,.0f}/sqft)",
    ])

    if ind_rate is not None and land_cost is not None:
        lines.append(f"  - Indicative Land Valuation: INR {ind_rate:,.0f}/sqft (Estimated Outlay: INR {land_cost:,.0f})")

    lines.extend([
        "",
        "3. REQUIRED SYNTHESIS DELIVERABLES:",
        "Provide a detailed JSON response containing:",
        "  - parameter_reflection: A concise 2-sentence explanation of how the user's specific inputs (area, grade, storeys, brief) governed this engineering analysis.",
        "  - feasibility_score: The integer suitability score matching the deterministic engine.",
        "  - structural_recommendations: 3-6 specific structural design requirements under IS 456 / IS 1893.",
        "  - structured_analysis: A detailed object containing:",
        "      * executive_summary: High-level engineering narrative synthesizing site feasibility, project constraints, and architectural alignment.",
        "      * overall_assessment: Clear engineering evaluation of site suitability and balance between opportunities and risks.",
        "      * key_strengths: 3-5 top positive site attributes based on measured data.",
        "      * key_concerns: Top engineering challenges, hazard exposure, or logistical constraints.",
        "      * engineering_considerations: Specific structural, foundation, drainage, and civil engineering considerations.",
        "      * environmental_and_hazards: Seismic ductility, flood prevention, wind resistance, and passive orientation insights.",
        "      * financial_considerations: Contextual analysis of CPWD cost drivers, terrain surcharges, and budget allocation without inventing new rates.",
        "      * required_investigations: Mandatory tests and site surveys before construction.",
        "      * recommended_next_steps: Prioritized chronological actions for planning and engineering teams."
    ])

    return "\n".join(lines)


def build_user_prompt(
    lat: float,
    lon: float,
    area: float,
    grade: str,
    typology: str,
    storeys: str,
    coverage: int,
    client_requirements: Optional[str] = None,
) -> str:
    """
    Standardized user prompt preserved for backward compatibility.
    """
    prompt = (
        f"Analyze this site: Lat={lat}, Lon={lon}, Area={area} sqft, "
        f"Grade={grade}, Typology={typology}, Storeys={storeys}, Ground Coverage={coverage}%."
    )
    reqs = (client_requirements or "").strip()
    if reqs:
        prompt += f"\nClient requirements that must be reflected in the narrative: {reqs}"
    return prompt
