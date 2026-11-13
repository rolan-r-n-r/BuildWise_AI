import math
import httpx
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple
from app.utils.geo_utils import get_cardinal_offsets, calculate_synthetic_elevation
from app.utils.cache_utils import cache
from app.services.geocode_service import _nominatim_throttle

USER_AGENT = "BuildWise-Civil-Engineering-Engine/1.0"
DEFAULT_TIMEOUT_SECONDS = 3.5


async def fetch_reverse_geocode(lat: float, lon: float) -> Tuple[str, bool]:
    """
    Retrieves human-readable address from OpenStreetMap Nominatim.
    Returns (address_string, is_fallback).
    """
    cached = cache.get(lat, lon, "geocode")
    if cached:
        return cached, False

    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=14&addressdetails=1"
    headers = {"User-Agent": USER_AGENT}

    try:
        await _nominatim_throttle()
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                display_name = data.get("display_name")
                if display_name:
                    # Clean up and shorten address
                    parts = [p.strip() for p in display_name.split(",")]
                    shortened = ", ".join(parts[:4]) if len(parts) > 4 else display_name
                    cache.set(lat, lon, "geocode", shortened)
                    return shortened, False
    except Exception:
        pass

    fallback_name = f"Site Location ({abs(lat):.4f}{'N' if lat>=0 else 'S'}, {abs(lon):.4f}{'E' if lon>=0 else 'W'})"
    return fallback_name, True

async def fetch_elevation_samples(lat: float, lon: float) -> Tuple[Dict[str, float], bool]:
    """
    Fetches real elevation for the center and 4 cardinal
    offset points (33 m spacing) and returns the full sample set so downstream
    modules (e.g. Vastu slope reading) consume measured terrain, not the
    synthetic fallback.

    Returns (samples_dict, is_fallback) where samples_dict keys are
    center/north/south/east/west (metres AMSL). is_fallback=True means every
    consumer MUST treat the values as a synthetic mathematical model.
    """
    cached = cache.get(lat, lon, "elevation_samples")
    if cached:
        return cached, False

    offsets = get_cardinal_offsets(lat, lon, distance_meters=33.0)
    lats = [offsets["center"][0], offsets["north"][0], offsets["south"][0], offsets["east"][0], offsets["west"][0]]
    lons = [offsets["center"][1], offsets["north"][1], offsets["south"][1], offsets["east"][1], offsets["west"][1]]

    lat_str = ",".join(f"{coord:.5f}" for coord in lats)
    lon_str = ",".join(f"{coord:.5f}" for coord in lons)
    url = f"https://api.open-meteo.com/v1/elevation?latitude={lat_str}&longitude={lon_str}"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                elevations = resp.json().get("elevation", [])
                if len(elevations) == 5:
                    samples = {
                        "center": float(elevations[0]),
                        "north": float(elevations[1]),
                        "south": float(elevations[2]),
                        "east": float(elevations[3]),
                        "west": float(elevations[4]),
                    }
                    cache.set(lat, lon, "elevation_samples", samples)
                    return samples, False
    except Exception:
        pass

    # Deterministic synthetic fallback - flagged as such
    samples = {
        "center": calculate_synthetic_elevation(lat, lon),
        "north": calculate_synthetic_elevation(offsets["north"][0], offsets["north"][1]),
        "south": calculate_synthetic_elevation(offsets["south"][0], offsets["south"][1]),
        "east": calculate_synthetic_elevation(offsets["east"][0], offsets["east"][1]),
        "west": calculate_synthetic_elevation(offsets["west"][0], offsets["west"][1]),
    }
    return samples, True


async def fetch_elevation_and_slope(lat: float, lon: float) -> Tuple[float, float, bool]:
    """
    Fetches elevation for center and 4 cardinal offset points (33m distance)
    to calculate true topographic slope.
    Returns (center_elevation_m, slope_percentage, is_fallback).
    """
    samples, is_fallback = await fetch_elevation_samples(lat, lon)
    h0 = samples["center"]
    max_dh = max(
        abs(samples["north"] - h0),
        abs(samples["south"] - h0),
        abs(samples["east"] - h0),
        abs(samples["west"] - h0),
    )
    # Slope percentage = (rise / run) * 100
    slope_pct = round((max_dh / 33.0) * 100.0, 2)
    return h0, slope_pct, is_fallback

async def fetch_climate_data(lat: float, lon: float) -> Tuple[Dict[str, float], bool]:
    """
    Fetches microclimate metrics: temperature, prevailing wind direction, wind speed, precipitation.
    Returns (climate_dict, is_fallback).
    """
    cached = cache.get(lat, lon, "climate")
    if cached:
        return cached, False

    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat:.4f}&longitude={lon:.4f}"
        "&current=temperature_2m,wind_speed_10m,wind_direction_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
        "&timezone=auto"
    )

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current", {})
                daily = data.get("daily", {})

                wind_dir = float(current.get("wind_direction_10m", 240.0))
                wind_speed = float(current.get("wind_speed_10m", 12.0))
                temp_now = float(current.get("temperature_2m", 28.0))

                max_temps = daily.get("temperature_2m_max", [32.0])
                min_temps = daily.get("temperature_2m_min", [20.0])
                precips = daily.get("precipitation_sum", [5.0])

                avg_max = sum(max_temps) / max(len(max_temps), 1)
                avg_min = sum(min_temps) / max(len(min_temps), 1)
                est_annual_precip = sum(precips) * 52.0  # approximate annual mm
                precip_source = "7day_forecast_extrapolation"
                wind_source = "current_telemetry"

                # Prefer the ERA5 archive's observed
                # 365-day precipitation total and dominant wind vector over short extrapolations.
                try:
                    end_date = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
                    start_date = (datetime.now(timezone.utc) - timedelta(days=366)).strftime("%Y-%m-%d")
                    archive_url = (
                        f"https://archive-api.open-meteo.com/v1/archive?latitude={lat:.4f}&longitude={lon:.4f}"
                        f"&start_date={start_date}&end_date={end_date}&daily=precipitation_sum,wind_direction_10m_dominant&timezone=auto"
                    )
                    arch_resp = await client.get(archive_url, headers={"User-Agent": USER_AGENT})
                    if arch_resp.status_code == 200:
                        arch_daily = arch_resp.json().get("daily", {})
                        arch_precips = [float(v) for v in arch_daily.get("precipitation_sum", []) if v is not None]
                        if len(arch_precips) >= 300:
                            est_annual_precip = round(sum(arch_precips), 1)
                            precip_source = "era5_observed_365d"

                        arch_winds = [float(v) for v in arch_daily.get("wind_direction_10m_dominant", []) if v is not None]
                        if len(arch_winds) >= 300:
                            s_sum = sum(math.sin(math.radians(d)) for d in arch_winds)
                            c_sum = sum(math.cos(math.radians(d)) for d in arch_winds)
                            if abs(s_sum) > 1e-4 or abs(c_sum) > 1e-4:
                                wind_dir = round((math.degrees(math.atan2(s_sum, c_sum)) + 360.0) % 360.0, 1)
                                wind_source = "era5_observed_365d_dominant"
                except Exception:
                    pass  # keep forecast estimate, source label discloses it

                climate = {
                    "temperature_current_c": round(temp_now, 1),
                    "temperature_max_c": round(avg_max, 1),
                    "temperature_min_c": round(avg_min, 1),
                    "wind_direction_deg": round(wind_dir, 1),
                    "wind_speed_kmh": round(wind_speed, 1),
                    "annual_precipitation_mm": round(est_annual_precip, 1),
                    "annual_precipitation_source": precip_source,
                    "wind_direction_source": wind_source,
                }
                cache.set(lat, lon, "climate", climate)
                return climate, False
    except Exception:
        pass

    # Latitudinal synthetic fallback
    # Approximate tropical/subtropical Indian climate base
    lat_factor = abs(lat) / 90.0
    fallback_climate = {
        "temperature_current_c": round(32.0 - lat_factor * 20.0, 1),
        "temperature_max_c": round(36.0 - lat_factor * 18.0, 1),
        "temperature_min_c": round(22.0 - lat_factor * 22.0, 1),
        "wind_direction_deg": 240.0,  # Southwest monsoon baseline for India
        "wind_speed_kmh": 14.5,
        "annual_precipitation_mm": 950.0,
        "annual_precipitation_source": "latitudinal_synthetic_fallback"
    }
    return fallback_climate, True
