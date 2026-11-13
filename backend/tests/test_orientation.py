from app.services.orientation_service import calculate_building_orientation

def test_orientation_northern_hemisphere():
    # Bengaluru latitude ~ 12.97 deg N
    orient = calculate_building_orientation(latitude=12.97, wind_dir_deg=240.0)
    assert 75.0 <= orient.optimal_axis_degrees <= 105.0
    assert "East-West" in orient.axis_label
    assert "North" in orient.solar_exposure_summary
    assert orient.cross_ventilation_rating in ["Excellent", "Good", "Moderate"]

def test_orientation_southern_hemisphere():
    # Sydney latitude ~ -33.86 deg S
    orient = calculate_building_orientation(latitude=-33.86, wind_dir_deg=90.0)
    assert 75.0 <= orient.optimal_axis_degrees <= 105.0
    assert "South" in orient.solar_exposure_summary


def test_orientation_wind_deflection_amplitude_and_bounds():
    # Peak positive deflection at 45 deg wind: sin(90 deg) = 1.0 -> 90 + 15 = 105.0
    orient_45 = calculate_building_orientation(latitude=15.0, wind_dir_deg=45.0)
    assert orient_45.optimal_axis_degrees == 105.0
    assert "South of East" in orient_45.axis_label

    # Peak negative deflection at 135 deg wind: sin(270 deg) = -1.0 -> 90 - 15 = 75.0
    orient_135 = calculate_building_orientation(latitude=15.0, wind_dir_deg=135.0)
    assert orient_135.optimal_axis_degrees == 75.0
    assert "North of East" in orient_135.axis_label

    # Cardinal wind at 0 deg (North) -> zero deflection
    orient_0 = calculate_building_orientation(latitude=15.0, wind_dir_deg=0.0)
    assert orient_0.optimal_axis_degrees == 90.0
    assert "Pure 90 deg" in orient_0.axis_label
