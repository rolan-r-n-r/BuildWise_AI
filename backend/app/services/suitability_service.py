import math
from typing import Any, List, Optional, Tuple
from app.schemas.response import FactorScore
from app.services.methodology import slope_band_for, slope_score_for


def calculate_slope_score(slope_pct: float) -> Tuple[float, str, str]:
    """
    Computes slope suitability score (0-100), status, and engineering description.

    The bands live in app.services.methodology.SLOPE_BANDS; the same rows render
    the report's methodology popover, so the disclosure cannot describe a table
    the engine does not implement.
    """
    band = slope_band_for(slope_pct)
    score = slope_score_for(slope_pct, band)
    status = band["status"]
    details = band["detail"].format(slope=slope_pct)

    return round(score, 1), status, details


def calculate_flood_score(
    elevation_m: float,
    annual_precip_mm: float,
    flood_profile: Optional[Any] = None
) -> Tuple[float, str, str]:
    """
    Computes hydrological flood risk approximation score (0-100), status, and description.

    When a hazard-module FloodProfile is supplied, the
    river-discharge / NDMA pressure level is fused with the elevation/precip
    proxy so the report carries ONE consistent flood signal (conservative: the
    worse of the two signals governs).
    """
    # Coastal or extreme low-lying penalty (< 10m AMSL)
    elevation_penalty = max(0.0, (15.0 - elevation_m) * 2.5) if elevation_m < 15.0 else 0.0
    precip_penalty = max(0.0, (annual_precip_mm - 1200.0) * 0.02)

    score = max(15.0, min(100.0, 95.0 - elevation_penalty - precip_penalty))
    source_note = "terrain elevation and rainfall proxy"

    if flood_profile is not None:
        level = getattr(flood_profile, "pressure_level", None)
        if level is None and isinstance(flood_profile, dict):
            level = flood_profile.get("pressure_level")
        if level in ("low", "moderate", "high"):
            pressure_score = {"low": 85.0, "moderate": 55.0, "high": 30.0}[level]
            score = min(score, pressure_score)
            if level == "high":
                source_note = "river discharge telemetry / NDMA atlas (HIGH flood pressure)"
            elif level == "moderate":
                source_note = "river discharge telemetry / NDMA atlas (moderate flood pressure)"
            else:
                source_note = "river discharge telemetry / NDMA atlas (low flood pressure)"

    if score >= 75.0:
        status = "optimal"
        details = f"Favorable elevation ({elevation_m:.0f}m AMSL) with controlled surface runoff vulnerability ({source_note})."
    elif score >= 50.0:
        status = "acceptable"
        details = (
            f"Moderate elevation ({elevation_m:.0f}m AMSL) and {annual_precip_mm:.0f}mm rainfall require plinth height "
            f"elevation (+600mm) and perimeter swales ({source_note})."
        )
    else:
        status = "critical"
        details = (
            f"Elevated flood vulnerability: low elevation ({elevation_m:.0f}m AMSL), {annual_precip_mm:.0f}mm/yr rainfall, "
            f"{source_note}."
        )

    return round(score, 1), status, details


def calculate_road_access_score(
    road_distance_m: Optional[float],
    road_service_available: bool
) -> Tuple[float, str, str, Optional[float]]:
    """
    Road accessibility is scored from the real
    OpenStreetMap/Overpass distance to the nearest mapped road (500 m query
    radius) instead of a coordinate trigonometry proxy.

    Returns (score, status, details, raw_value_meters).
    - road_service_available=False  -> honest 'unknown' neutral score (50),
      never a fabricated claim.
    - available but no mapped road within 500 m -> explicit critical status.
    """
    if not road_service_available:
        return (
            50.0,
            "unknown",
            "Road access not measured (OpenStreetMap road service unavailable). "
            "Neutral score applied; verify physical access manually.",
            None,
        )

    if road_distance_m is None:
        return (
            35.0,
            "critical",
            "No mapped road within 500 m in OpenStreetMap. Restricted connectivity - "
            "confirm physical site access and haulage route manually.",
            None,
        )

    d = float(road_distance_m)
    if d <= 50.0:
        score, status = 90.0, "optimal"
    elif d <= 100.0:
        score, status = 80.0, "optimal"
    elif d <= 250.0:
        score, status = 70.0, "acceptable"
    else:
        score, status = 55.0, "acceptable"

    return (
        score,
        status,
        f"Nearest mapped road (OpenStreetMap) is {d:.0f} m from the site pin. "
        + (
            "Direct frontage access feasible for construction vehicle movement."
            if d <= 100.0
            else "Internal approach road/track may be required for heavy vehicle access."
        ),
        round(d, 1),
    )


def calculate_environmental_comfort_score(climate: dict) -> Tuple[float, str, str]:
    """
    Computes environmental thermal and microclimatic comfort score (0-100).
    """
    temp_max = climate.get("temperature_max_c", 32.0)
    temp_min = climate.get("temperature_min_c", 20.0)
    wind_speed = climate.get("wind_speed_kmh", 12.0)

    heat_penalty = max(0.0, (temp_max - 32.0) * 2.2)
    cold_penalty = max(0.0, (16.0 - temp_min) * 1.5)
    wind_benefit = min(10.0, wind_speed * 0.4) if wind_speed < 25.0 else -10.0

    score = max(25.0, min(100.0, 85.0 - heat_penalty - cold_penalty + wind_benefit))

    if score >= 75.0:
        status = "optimal"
        details = f"Mild microclimate with pleasant ambient ventilation ({wind_speed} km/h) and moderate peak summer temps ({temp_max} deg C)."
    elif score >= 50.0:
        status = "acceptable"
        details = f"Moderate thermal stress (peak {temp_max} deg C). Requires thermal insulation, radiant barriers, and solar shading."
    else:
        status = "critical"
        details = f"Severe climatic heat exposure (peak {temp_max} deg C). Mechanical HVAC dependency and high envelope insulation essential."

    return round(score, 1), status, details


def calculate_facility_score(lat: float, lon: float) -> Tuple[float, str, str]:
    """
    Computes proximity to municipal utilities and civic services (0-100).

    This remains a DETERMINISTIC MODELLED PROXY (no
    municipal-utility dataset is integrated yet). It is explicitly labelled as
    a proxy, its weight is reduced (0.10), and it never emits factual claims
    about specific infrastructure being present.
    """
    utility_factor = (math.sin(lat * 0.8 + 1.2) ** 2 + math.cos(lon * 0.8 - 0.4) ** 2) / 2.0
    score = round(60.0 + utility_factor * 35.0, 1)

    proxy_prefix = "Modelled proxy index (not a measured survey): "
    if score >= 80.0:
        status = "optimal"
        details = proxy_prefix + (
            "Locality model suggests municipal electrical grid, water supply mains, and civic services are likely proximate. "
            "Verify with the local authority."
        )
    elif score >= 60.0:
        status = "acceptable"
        details = proxy_prefix + (
            "Locality model suggests a suburban infrastructure zone; utility lines likely available but on-site stormwater "
            "soakway and septic connection may be required. Verify with the local authority."
        )
    else:
        status = "critical"
        details = proxy_prefix + (
            "Locality model suggests a developing peripheral zone; independent borewell, rainwater harvesting, and off-grid "
            "power provisions may be required. Verify with the local authority."
        )

    return score, status, details


def evaluate_land_suitability(
    lat: float,
    lon: float,
    elevation_m: float,
    slope_pct: float,
    climate: dict,
    road_distance_m: Optional[float] = None,
    road_service_available: bool = False,
    flood_profile: Optional[Any] = None
) -> Tuple[float, str, List[FactorScore]]:
    """
    Executes full Multi-Criteria Decision Analysis (MCDA) across 5 standard engineering factors.
    Weights:
      Slope: 25% | Flood Risk: 20% | Road Access: 25% (real OSM distance)
      Environmental Comfort: 20% | Facility Proximity: 10% (modelled proxy)
    """
    # 1. Slope
    s_score, s_status, s_details = calculate_slope_score(slope_pct)
    factor_slope = FactorScore(
        factor_id="slope",
        name="Topographic Slope",
        weight=0.25,
        raw_value=round(slope_pct, 1),
        unit="%",
        score=s_score,
        status=s_status,
        details=s_details
    )

    # 2. Flood Risk (unified with hazard-module FloodProfile when supplied)
    f_score, f_status, f_details = calculate_flood_score(
        elevation_m, climate.get("annual_precipitation_mm", 900.0), flood_profile=flood_profile
    )
    factor_flood = FactorScore(
        factor_id="flood_risk",
        name="Flood Risk Assessment",
        weight=0.20,
        raw_value=round(elevation_m, 1),
        unit="m AMSL",
        score=f_score,
        status=f_status,
        details=f_details
    )

    # 3. Road Access (real Overpass distance; honest unknown state)
    r_score, r_status, r_details, r_raw = calculate_road_access_score(road_distance_m, road_service_available)
    factor_road = FactorScore(
        factor_id="road_access",
        name="Road Accessibility",
        weight=0.25,
        raw_value=r_raw,
        unit="m distance" if r_raw is not None else "not measured",
        score=r_score,
        status=r_status,
        details=r_details
    )

    # 4. Environmental Comfort
    e_score, e_status, e_details = calculate_environmental_comfort_score(climate)
    factor_env = FactorScore(
        factor_id="environmental_comfort",
        name="Environmental Comfort",
        weight=0.20,
        raw_value=climate.get("temperature_max_c", 32.0),
        unit="deg C peak",
        score=e_score,
        status=e_status,
        details=e_details
    )

    # 5. Facility Proximity (modelled proxy, honestly labelled, reduced weight)
    p_score, p_status, p_details = calculate_facility_score(lat, lon)
    factor_facility = FactorScore(
        factor_id="facility_proximity",
        name="Proximity to Facilities (Modelled Proxy)",
        weight=0.10,
        raw_value=p_score,
        unit="modelled index (0-100)",
        score=p_score,
        status=p_status,
        details=p_details
    )

    factors = [factor_slope, factor_flood, factor_road, factor_env, factor_facility]

    overall_score = round(
        factor_slope.score * factor_slope.weight +
        factor_flood.score * factor_flood.weight +
        factor_road.score * factor_road.weight +
        factor_env.score * factor_env.weight +
        factor_facility.score * factor_facility.weight,
        1
    )

    if overall_score >= 70.0:
        verdict = "Suitable"
    elif overall_score >= 50.0:
        verdict = "Conditionally Suitable"
    else:
        verdict = "Challenging"

    return overall_score, verdict, factors
