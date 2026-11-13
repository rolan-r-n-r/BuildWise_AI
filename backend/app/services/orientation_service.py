import math
from app.schemas.response import OrientationData

def calculate_building_orientation(latitude: float, wind_dir_deg: float) -> OrientationData:
    """
    Computes passive solar building orientation and aerodynamic ventilation axis.
    
    Principles:
    1. Solar Control: Long facades should ideally orient North-South (axis East-West at 90 deg)
       to minimize direct low-angle solar heat gain from East and West facades.
    2. Aerodynamic Cross-Ventilation: Windows and primary apertures should capture prevailing wind
       at an incident angle between 45 and 90 degrees.
    3. Deflection: A minor skew (+/- 15 deg) from pure East-West is applied depending on the wind vector.
    """
    is_northern = latitude >= 0.0

    # Base optimal longitudinal axis is 90 degrees (East-West axis)
    base_axis = 90.0
    max_deflection = 15.0  # Permissible NBC 2016 skew (+/- 15 deg)

    # Wind deflection: Calculate acute angle difference to wind direction
    # Normal to East-West facade is 0 deg (North) or 180 deg (South)
    wind_rad = math.radians(wind_dir_deg)
    # Deflect toward wind normal to encourage positive pressure on opening
    wind_offset = round(max_deflection * math.sin(wind_rad * 2.0), 1)
    
    # Constrain axis within [75.0, 105.0] degrees relative to true North
    optimal_axis = round(max(base_axis - max_deflection, min(base_axis + max_deflection, base_axis + wind_offset)), 1)

    # Label generation
    if optimal_axis == 90.0:
        axis_label = "East-West (Pure 90 deg)"
    elif optimal_axis < 90.0:
        axis_label = f"East-West ({90.0 - optimal_axis:.1f} deg North of East)"
    else:
        axis_label = f"East-West ({optimal_axis - 90.0:.1f} deg South of East)"

    # Solar exposure summary
    if is_northern:
        solar_summary = (
            "Sun path traverses the southern sky. Major glazed openings should face North (glare-free ambient daylight) "
            "and South (deep winter solar heat gain with horizontal overhang protection)."
        )
    else:
        solar_summary = (
            "Sun path traverses the northern sky. Major glazed openings should face South (diffuse light) "
            "and North with appropriate shading overhangs."
        )

    # Ventilation assessment
    # Check angle between wind and normal to building axis (optimal_axis + 90)
    normal_1 = (optimal_axis + 90.0) % 360.0
    normal_2 = (optimal_axis + 270.0) % 360.0
    diff_1 = min(abs(wind_dir_deg - normal_1), 360.0 - abs(wind_dir_deg - normal_1))
    diff_2 = min(abs(wind_dir_deg - normal_2), 360.0 - abs(wind_dir_deg - normal_2))
    min_diff = min(diff_1, diff_2)

    if min_diff <= 35.0:
        vent_rating = "Excellent"
        vent_detail = "Prevailing wind strikes broad facade at near-perpendicular angles, creating strong positive-negative pressure differential for natural cross-ventilation."
    elif min_diff <= 60.0:
        vent_rating = "Good"
        vent_detail = "Oblique incident wind vector. Wing walls or casement window apertures recommended to direct airflow into living zones."
    else:
        vent_rating = "Moderate"
        vent_detail = "Wind travels predominantly parallel to long facades. Staggered facade articulation or roof wind-catchers beneficial."

    rationale = (
        f"A principal longitudinal axis along {optimal_axis} deg ({axis_label}) provides optimal balance between "
        f"solar heat reduction and natural cross-ventilation from the prevailing {wind_dir_deg:.0f} deg wind vector. "
        f"{vent_detail}"
    )

    return OrientationData(
        optimal_axis_degrees=optimal_axis,
        axis_label=axis_label,
        prevailing_wind_direction_degrees=round(wind_dir_deg, 1),
        solar_exposure_summary=solar_summary,
        cross_ventilation_rating=vent_rating,
        passive_design_rationale=rationale
    )
