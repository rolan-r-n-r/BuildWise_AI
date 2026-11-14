import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import httpx

from app.schemas.response import (
    SeismicEvent,
    SeismicProfile,
    FloodProfile,
    StormCycloneProfile,
    HazardProfile
)
from app.utils.cache_utils import hazard_cache
from app.utils.geo_utils import haversine_distance

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DEFAULT_TIMEOUT_SECONDS = 3.5
USER_AGENT = "BuildWise-Civil-Engineering-Engine/1.0"

_SEISMIC_DATA: Optional[Dict[str, Any]] = None
_NDMA_DATA: Optional[Dict[str, Any]] = None

def _load_seismic_table() -> Dict[str, Any]:
    global _SEISMIC_DATA
    if _SEISMIC_DATA is None:
        file_path = DATA_DIR / "seismic_zones.json"
        with open(file_path, "r", encoding="utf-8") as f:
            _SEISMIC_DATA = json.load(f)
    return _SEISMIC_DATA

def _load_ndma_table() -> Dict[str, Any]:
    global _NDMA_DATA
    if _NDMA_DATA is None:
        file_path = DATA_DIR / "ndma_hazard_districts.json"
        with open(file_path, "r", encoding="utf-8") as f:
            _NDMA_DATA = json.load(f)
    return _NDMA_DATA


async def fetch_usgs_seismic_data(lat: float, lon: float) -> Tuple[Dict[str, Any], bool]:
    """
    Queries USGS FDSN event API for earthquakes within 250km, magnitude >= 4.5, past 50 years.
    Returns (data_dict, is_fallback).
    """
    cached = hazard_cache.get(lat, lon, "usgs_seismic", precision=1)
    if cached is not None:
        return cached, False

    now_utc = datetime.now(timezone.utc)
    current_year = now_utc.year
    start_year = current_year - 50
    start_date = f"{start_year}-01-01"
    end_date = now_utc.strftime("%Y-%m-%d")

    url = (
        f"https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
        f"&latitude={lat:.4f}&longitude={lon:.4f}&maxradiuskm=250"
        f"&minmagnitude=4.5&starttime={start_date}&endtime={end_date}"
        f"&orderby=magnitude&limit=250"
    )

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                event_count = len(features)
                is_capped = (event_count >= 250)

                events: List[Dict[str, Any]] = []
                max_mag: Optional[float] = None
                most_recent_ms: Optional[int] = None

                for f in features:
                    props = f.get("properties", {})
                    geom = f.get("geometry", {})
                    mag = props.get("mag")
                    if mag is None:
                        continue
                    mag = float(mag)
                    if max_mag is None or mag > max_mag:
                        max_mag = mag

                    time_ms = props.get("time")
                    if time_ms is not None:
                        if most_recent_ms is None or time_ms > most_recent_ms:
                            most_recent_ms = time_ms

                    coords = geom.get("coordinates", [0, 0, 0])
                    ev_lon, ev_lat = coords[0], coords[1]
                    dist_km = round(haversine_distance(lat, lon, ev_lat, ev_lon) / 1000.0, 1)

                    date_iso = datetime.fromtimestamp(time_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d") if time_ms else "Unknown"

                    events.append({
                        "magnitude": round(mag, 1),
                        "date_iso": date_iso,
                        "distance_km": dist_km,
                        "place": props.get("place", "Regional epicenter")
                    })

                years_since_last: Optional[float] = None
                if most_recent_ms is not None:
                    now_ms = now_utc.timestamp() * 1000.0
                    diff_ms = max(0.0, now_ms - most_recent_ms)
                    years_since_last = round(diff_ms / (365.25 * 86400 * 1000.0), 1)

                top_5 = events[:5]

                result = {
                    "event_count": event_count,
                    "is_capped": is_capped,
                    "event_count_display": "250+" if is_capped else str(event_count),
                    "max_magnitude": max_mag,
                    "years_since_last_event": years_since_last,
                    "recent_major_events": top_5
                }
                hazard_cache.set(lat, lon, "usgs_seismic", result, precision=1)
                return result, False
    except Exception:
        pass

    # Deterministic offline fallback
    result = {
        "event_count": 0,
        "is_capped": False,
        "event_count_display": "0",
        "max_magnitude": None,
        "years_since_last_event": None,
        "recent_major_events": []
    }
    return result, True


async def fetch_open_meteo_flood_data(lat: float, lon: float) -> Tuple[Optional[float], bool]:
    """
    Queries Open-Meteo Flood API for the past 365 days of river discharge (m3/s).
    Returns (peak_to_mean_ratio, is_fallback).
    Guarded by: mean discharge >= 0.1 m3/s, ratio capped at 20.0.
    """
    cached = hazard_cache.get(lat, lon, "open_meteo_flood", precision=1)
    if cached is not None:
        return cached, False

    url = (
        f"https://flood-api.open-meteo.com/v1/flood?latitude={lat:.4f}&longitude={lon:.4f}"
        f"&daily=river_discharge&past_days=365&forecast_days=0"
    )

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                daily = resp.json().get("daily", {})
                raw_discharges = daily.get("river_discharge", [])
                discharges = [float(v) for v in raw_discharges if v is not None]

                if discharges and len(discharges) >= 10:
                    mean_discharge = sum(discharges) / len(discharges)
                    if mean_discharge >= 0.1:
                        peak_discharge = max(discharges)
                        ratio = round(peak_discharge / mean_discharge, 1)
                        clamped_ratio = min(20.0, ratio)
                        hazard_cache.set(lat, lon, "open_meteo_flood", clamped_ratio, precision=1)
                        return clamped_ratio, False
                    else:
                        # Negligible flow / dry channel guard (Amendment 3)
                        hazard_cache.set(lat, lon, "open_meteo_flood", None, precision=1)
                        return None, False
    except Exception:
        pass

    return None, True


async def fetch_era5_storm_data(lat: float, lon: float) -> Tuple[float, float, bool]:
    """
    Queries Open-Meteo ERA5 archive for the past 10 complete calendar years.
    Returns (mean_annual_max_gust_kmh, mean_annual_extreme_rainfall_days, is_fallback).
    """
    cached = hazard_cache.get(lat, lon, "era5_storm", precision=1)
    if cached is not None:
        return cached[0], cached[1], False

    current_year = datetime.now(timezone.utc).year
    start_year = current_year - 10
    end_year = current_year - 1
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"

    url = (
        f"https://archive-api.open-meteo.com/v1/archive?latitude={lat:.4f}&longitude={lon:.4f}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=wind_gusts_10m_max,precipitation_sum&timezone=auto"
    )

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 200:
                daily = resp.json().get("daily", {})
                times = daily.get("time", [])
                gusts = daily.get("wind_gusts_10m_max", [])
                precips = daily.get("precipitation_sum", [])

                if times and len(times) == len(gusts) == len(precips):
                    yearly_max_gusts: Dict[int, float] = {}
                    yearly_extreme_days: Dict[int, int] = {}

                    for t_str, g_val, p_val in zip(times, gusts, precips):
                        try:
                            y = int(t_str[:4])
                        except Exception:
                            continue

                        if y not in yearly_max_gusts:
                            yearly_max_gusts[y] = 0.0
                            yearly_extreme_days[y] = 0

                        if g_val is not None:
                            g_num = float(g_val)
                            if g_num > yearly_max_gusts[y]:
                                yearly_max_gusts[y] = g_num

                        if p_val is not None and float(p_val) >= 50.0:
                            yearly_extreme_days[y] += 1

                    years_count = max(len(yearly_max_gusts), 1)
                    mean_max_gust = round(sum(yearly_max_gusts.values()) / years_count, 1)
                    mean_ext_days = round(sum(yearly_extreme_days.values()) / years_count, 1)

                    result = (mean_max_gust, mean_ext_days)
                    hazard_cache.set(lat, lon, "era5_storm", result, precision=1)
                    return mean_max_gust, mean_ext_days, False
    except Exception:
        pass

    # Deterministic fallback based on latitudinal coastal proximity
    lat_factor = abs(lat) / 90.0
    fallback_gust = round(52.0 + lat_factor * 15.0, 1)
    fallback_ext_days = 1.5
    return fallback_gust, fallback_ext_days, True


def match_seismic_zone(address: str, lat: float, lon: float) -> Tuple[Optional[str], Optional[float], str, str, Optional[str]]:
    """
    Matches district/city/state against BIS IS 1893:2016 static catalog.
    Returns (zone, zone_factor, standard, district_name, confidence_warning).

    Coordinates outside the IS 1893:2016 (India)
    mapping extent return zone=None ("Not Assessed") - never a default Zone.
    Regional coordinate-cluster matches carry an explicit moderate-confidence warning.
    """
    # IS 1893 applies to Indian territory only. Extent gate: approximate
    # national bounding box (lat 6.0-37.5, lon 68.0-97.5).
    if not (6.0 <= lat <= 37.5 and 68.0 <= lon <= 97.5):
        warning = (
            "Site coordinates are outside the IS 1893:2016 (India) mapping extent. "
            "No seismic zone was assigned; engage the governing national seismic code "
            "for the site jurisdiction."
        )
        return None, None, "Outside IS 1893:2016 extent", "Outside IS 1893 Jurisdiction", warning

    table = _load_seismic_table()
    city_overrides = table.get("city_district_overrides", {})
    state_baselines = table.get("state_baselines", {})
    fallback_zone = table["_meta"].get("default_fallback_zone", "Zone III")
    fallback_factor = table["_meta"].get("default_fallback_factor", 0.16)

    addr_lower = address.lower()

    # 1. Match city/district override
    for key, val in city_overrides.items():
        if key in addr_lower:
            return val["zone"], val["factor"], "BIS IS 1893:2016", key.title(), None

    # 2. Match state baseline
    for st_key, st_val in state_baselines.items():
        if st_key in addr_lower:
            return st_val["zone"], st_val["factor"], "BIS IS 1893:2016", st_key.title(), None

    # 3. Known regional coordinate clusters (moderate confidence only)
    # Guwahati / Assam box: lat 25.5 - 27.5, lon 90.0 - 94.0
    box_warning = (
        "Seismic zone matched via regional coordinate cluster, not a jurisdiction name. "
        "Moderate confidence - verify against the official IS 1893:2016 zone map."
    )
    if 25.0 <= lat <= 28.5 and 89.5 <= lon <= 96.0:
        return "Zone V", 0.36, "BIS IS 1893:2016", "Northeast Tectonic Belt", box_warning
    # Delhi NCR box: lat 28.2 - 28.9, lon 76.8 - 77.5
    if 28.0 <= lat <= 29.0 and 76.5 <= lon <= 77.8:
        return "Zone IV", 0.24, "BIS IS 1893:2016", "Delhi National Capital Region", box_warning
    # Bengaluru box: lat 12.7 - 13.3, lon 77.3 - 77.9
    if 12.5 <= lat <= 13.5 and 77.0 <= lon <= 78.0:
        return "Zone II", 0.10, "BIS IS 1893:2016", "Bengaluru Urban", box_warning

    warning = (
        f"Site jurisdiction was not matched in IS 1893:2016 version 1.0.0 registry. "
        f"Default {fallback_zone} (Zone Factor {fallback_factor}) applied with moderate confidence."
    )
    return fallback_zone, fallback_factor, "BIS IS 1893:2016", "Uncataloged District", warning


def check_ndma_flags(address: str) -> Tuple[bool, bool]:
    """
    Checks static NDMA flood-prone and cyclone-prone district flags.
    Returns (is_flood_prone, is_cyclone_prone).
    """
    table = _load_ndma_table()
    addr_lower = address.lower()

    flood_prone = any(item["name"] in addr_lower for item in table.get("flood_prone_districts", []))
    cyclone_prone = any(item["name"] in addr_lower for item in table.get("cyclone_prone_districts", []))
    return flood_prone, cyclone_prone


def compute_overall_hazard_level(
    flood_level: str,
    storm_level: str,
    seismic_zone: str,
    seismic_events_count: int
) -> str:
    """
    Deterministic overall hazard aggregation per Amendment 7:
    - Starts at max(flood pressure level, storm exposure level) ['low' < 'moderate' < 'high']
    - Upgrades one level if seismic zone is Zone IV
    - Is at least 'high' if Zone V with event_count_50yr_250km > 0
    - Is 'critical' ONLY when Zone V combines with high flood or high storm
    """
    rank = {"low": 1, "moderate": 2, "high": 3, "critical": 4}
    inv_rank = {1: "low", 2: "moderate", 3: "high", 4: "critical"}

    base_score = max(rank.get(flood_level, 1), rank.get(storm_level, 1))

    # Zone IV upgrade (+1 level up to high)
    if seismic_zone == "Zone IV":
        base_score = min(3, base_score + 1)

    # Zone V baseline
    if seismic_zone == "Zone V":
        if seismic_events_count > 0:
            base_score = max(3, base_score)
        # Critical condition: Zone V combines with high flood or high storm
        if flood_level == "high" or storm_level == "high":
            base_score = 4

    return inv_rank[base_score]


async def evaluate_hazard_profile(
    lat: float,
    lon: float,
    elevation_m: float,
    address: str,
    raw_telemetry: Optional[Tuple[Any, Any, Any]] = None,
) -> Tuple[HazardProfile, List[str]]:
    """
    Evaluates comprehensive hazard history and climate stress profile.
    Returns (hazard_profile_object, warning_strings).
    """
    warnings: List[str] = []

    # The three hazard telemetry sources are independent upstreams with their
    # own caches and timeouts. When raw_telemetry is supplied (started concurrently
    # at the API route level), the pre-fetched results are consumed directly.
    if raw_telemetry is not None:
        (
            (seismic_res, s_fallback),
            (flood_ratio, f_fallback),
            (storm_gust, storm_extreme_days, st_fallback),
        ) = raw_telemetry
    else:
        (
            (seismic_res, s_fallback),
            (flood_ratio, f_fallback),
            (storm_gust, storm_extreme_days, st_fallback),
        ) = await asyncio.gather(
            fetch_usgs_seismic_data(lat, lon),
            fetch_open_meteo_flood_data(lat, lon),
            fetch_era5_storm_data(lat, lon),
        )

    # 1. Seismic
    if s_fallback:
        warnings.append("USGS earthquake catalog unreachable. Regional seismic baseline applied.")

    zone, z_factor, std_cit, district_name, z_warn = match_seismic_zone(address, lat, lon)
    if z_warn:
        warnings.append(z_warn)

    if seismic_res.get("is_capped"):
        warnings.append("Earthquake catalog query reached 250 event limit. Regional seismic event count capped at 250+.")

    s_confidence = "high" if not s_fallback and not z_warn else ("moderate" if not s_fallback else "low")
    if zone is None:
        # "Not Assessed" jurisdiction - lowest confidence by definition
        s_confidence = "low"
    recent_events = [SeismicEvent(**e) for e in seismic_res.get("recent_major_events", [])]

    seismic_profile = SeismicProfile(
        zone=zone,
        zone_factor=z_factor,
        standard=std_cit,
        district=district_name,
        event_count_50yr_250km=seismic_res.get("event_count", 0),
        is_capped=seismic_res.get("is_capped", False),
        event_count_display=seismic_res.get("event_count_display", "0"),
        max_magnitude=seismic_res.get("max_magnitude"),
        years_since_last_event=seismic_res.get("years_since_last_event"),
        recent_major_events=recent_events,
        confidence=s_confidence,
        confidence_warning=z_warn
    )

    # 2. Flood & River Discharge
    # When reverse geocoding failed, the address is a
    # synthetic coordinate identifier - jurisdiction/NDMA name matching would
    # silently mis-fire, so district flags are skipped with an explicit warning.
    geocode_unavailable = (not address) or address.startswith("Site Location (")
    if geocode_unavailable:
        warnings.append(
            "Reverse geocoding unavailable: jurisdiction name matching was skipped, "
            "so NDMA district hazard flags may be incomplete for this site."
        )
        flood_prone_ndma = False
        cyclone_prone_ndma = False
    else:
        flood_prone_ndma, cyclone_prone_ndma = check_ndma_flags(address)
    ratio = flood_ratio

    f_warning: Optional[str] = None
    f_confidence = "low"
    if geocode_unavailable:
        f_warning = (
            "Reverse geocoding unavailable: flood assessment relies on terrain elevation "
            "and discharge telemetry only (NDMA district flags not applied)."
        )
        warnings.append(f_warning)
        f_confidence = "low"
    elif f_fallback:
        f_warning = "Open-Meteo Flood API unavailable. Inferred from elevation AMSL and NDMA atlas."
        warnings.append(f_warning)
        f_confidence = "low"
    elif ratio is None:
        f_warning = "River discharge telemetry indicates dry channel or negligible flow (<0.1 m3/s). Flood pressure derived from terrain elevation and NDMA atlas proxies only."
        warnings.append(f_warning)
        f_confidence = "low"
    else:
        f_confidence = "high"

    # Evaluate flood pressure level
    if ratio is not None:
        if ratio >= 5.0 or (ratio >= 3.0 and (flood_prone_ndma or elevation_m < 15.0)):
            flood_pressure = "high"
        elif ratio >= 2.5 or elevation_m < 25.0:
            flood_pressure = "moderate"
        else:
            flood_pressure = "low"
    else:
        # Proxy evaluation when discharge is null or negligible
        if flood_prone_ndma or elevation_m < 12.0:
            flood_pressure = "high"
        elif elevation_m < 35.0:
            flood_pressure = "moderate"
        else:
            flood_pressure = "low"

    flood_profile = FloodProfile(
        discharge_peak_to_mean_ratio=ratio,
        pressure_level=flood_pressure,
        ndma_flood_prone=flood_prone_ndma,
        elevation_amsl_m=round(elevation_m, 1),
        confidence=f_confidence,
        confidence_warning=f_warning
    )

    # 3. Storm & Cyclone Exposure
    max_gust, ext_days = storm_gust, storm_extreme_days
    st_warning = None
    if st_fallback:
        st_warning = "ERA5 historical climate archive unreachable. Regional wind model applied."
        warnings.append(st_warning)
        st_confidence = "low"
    else:
        st_confidence = "high"

    if cyclone_prone_ndma or max_gust >= 90.0 or ext_days >= 4.0:
        storm_level = "high"
    elif max_gust >= 65.0 or ext_days >= 2.0:
        storm_level = "moderate"
    else:
        storm_level = "low"

    storm_profile = StormCycloneProfile(
        max_annual_gust_kmh=max_gust,
        extreme_rainfall_days=ext_days,
        exposure_level=storm_level,
        ndma_cyclone_prone=cyclone_prone_ndma,
        confidence=st_confidence,
        confidence_warning=st_warning
    )

    # 4. Overall Aggregation (Amendment 7)
    overall_level = compute_overall_hazard_level(
        flood_level=flood_pressure,
        storm_level=storm_level,
        seismic_zone=zone,
        seismic_events_count=seismic_profile.event_count_50yr_250km
    )

    hazard_profile = HazardProfile(
        seismic=seismic_profile,
        flood=flood_profile,
        storm_cyclone=storm_profile,
        overall_hazard_level=overall_level,
        warnings=warnings,
        source_fetches={
            "seismic": None if s_fallback else datetime.now(timezone.utc).isoformat(),
            "flood": None if f_fallback else datetime.now(timezone.utc).isoformat(),
            "storm_cyclone": None if st_fallback else datetime.now(timezone.utc).isoformat(),
        },
    )

    return hazard_profile, warnings
