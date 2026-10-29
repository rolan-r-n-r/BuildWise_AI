import asyncio
import math
import uuid
import time
import logging
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ValidationError

from app.config import settings

from app.services.boundary_service import (
    BoundaryValidationError,
    summarize_boundary,
)

logger = logging.getLogger(__name__)
from app.schemas.request import AnalysisRequest, ReportRequest
from app.schemas.response import (
    AnalysisResponse,
    HealthResponse
)
from app.schemas.site_vision import (
    SiteVisionRequest,
    SiteVisionResponse
)
from app.schemas.floorplan import FloorPlanRequest
from app.schemas.multi_floor_plan import ExtractedClientConstraints
from app.schemas.remediation import AdvisoryIn, RemediationIn
from app.services import (
    fetch_reverse_geocode,
    fetch_elevation_and_slope,
    fetch_climate_data,
    evaluate_land_suitability,
    calculate_building_orientation,
    calculate_construction_cost,
    identify_site_risks,
    generate_pdf_report,
    evaluate_hazard_profile,
    calculate_land_value,
    evaluate_vastu_advisory,
    generate_recommendations,
    get_top_severity_recommendations,
    analyze_site_vision,
)

from app.ai import get_ai_adapter, generate_room_program
from app.services.geocode_service import geocode_search, reverse_geocode_probe
from app.services.methodology import methodology_notes
from app.services.external_data_service import fetch_elevation_samples
from app.services.road_service import fetch_nearest_road
from app.schemas.site_intelligence import (
    NearestRoadResponse,
    RoadHit,
    RoadProvenance,
    SitePreviewRequest,
    SitePreviewResponse,
)
from app.services.road_service import fetch_nearest_road
from app.services.site_preview_service import (
    BoundaryStatutoryViolation,
    compute_site_preview,
)

app = FastAPI(
    title="BuildWise AI API",
    description="Geo-based intelligent construction feasibility, orientation, cost estimation, hazard, land value, and Vastu advisory engine.",
    version="1.1.0"
)


def _json_safe_validation_detail(value: Any) -> Any:
    """Replace non-finite floats in a validation detail tree.

    Starlette's JSONResponse refuses ``NaN``/``Infinity``.  FastAPI's default
    422 handler echoes the rejected input, so a raw ``NaN`` vertex made the
    handler itself raise and the client saw a 500 with a traceback instead of a
    field-named 422.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, dict):
        return {key: _json_safe_validation_detail(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_validation_detail(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe_validation_detail(jsonable_encoder(exc.errors()))},
    )

# CORS configuration with exact origin matching for Vite dev server (Crucial for Local Dev)
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
for origin in settings.CORS_ORIGINS:
    if origin and origin != "*" and origin not in ALLOWED_ORIGINS:
        ALLOWED_ORIGINS.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Reject oversized request bodies early - the PDF
# and floorplan endpoints accept large nested JSON payloads, and unbounded
# bodies are a memory-exhaustion vector.
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MB

@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_REQUEST_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body too large ({content_length} bytes; limit {MAX_REQUEST_BODY_BYTES} bytes)."},
        )
    return await call_next(request)

# Sliding window in-memory rate limiter: 30 requests per 60 seconds per IP
RATE_LIMIT_WINDOW_SEC = 60.0
RATE_LIMIT_MAX_REQUESTS = 30
_client_request_history = defaultdict(list)

# Global sweep removes idle IP buckets so the
# in-memory history maps cannot grow without bound under IP scanning.
_LAST_HISTORY_PRUNE = [0.0]

def _prune_rate_histories(now: float) -> None:
    if now - _LAST_HISTORY_PRUNE[0] < 60.0:
        return
    _LAST_HISTORY_PRUNE[0] = now
    for store in (_client_request_history, _proxy_request_history):
        idle = [ip for ip, ts in store.items() if not ts or now - ts[-1] >= RATE_LIMIT_WINDOW_SEC]
        for ip in idle:
            store.pop(ip, None)

def _client_ip(request: Request) -> str:
    """Client IP with X-Forwarded-For support for deployments behind a proxy."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "127.0.0.1"

def check_rate_limit(client_ip: str):
    now = time.time()
    _prune_rate_histories(now)
    timestamps = _client_request_history[client_ip]
    # Prune timestamps older than window
    _client_request_history[client_ip] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_SEC]
    if len(_client_request_history[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded (maximum 30 requests per minute). Please wait before running another analysis."
        )
    _client_request_history[client_ip].append(now)

# Separate sliding-window budget for the lightweight map-proxy endpoints
# (nearest-road / site preview): keeps /api/analyze's 30/min budget intact.
PROXY_RATE_LIMIT_WINDOW_SEC = 60.0
PROXY_RATE_LIMIT_MAX_REQUESTS = 60
_proxy_request_history = defaultdict(list)

def check_proxy_rate_limit(client_ip: str):
    now = time.time()
    _prune_rate_histories(now)
    timestamps = _proxy_request_history[client_ip]
    _proxy_request_history[client_ip] = [t for t in timestamps if now - t < PROXY_RATE_LIMIT_WINDOW_SEC]
    if len(_proxy_request_history[client_ip]) >= PROXY_RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded (maximum 60 requests per minute) for map preview endpoints."
        )
    _proxy_request_history[client_ip].append(now)

@app.get("/api/status")
async def api_status():
    """
    Lightweight status endpoint indicating configured LLM keys and engine availability.
    """
    has_groq = bool(
        settings.GROQ_API_KEY
        and settings.GROQ_API_KEY.strip()
        and not settings.GROQ_API_KEY.startswith("your_")
    )
    has_gemini = bool(
        settings.GEMINI_API_KEY
        and settings.GEMINI_API_KEY.strip()
        and not settings.GEMINI_API_KEY.startswith("your_")
    )
    return {
        "status": "online",
        "groq": has_groq,
        "gemini": has_gemini,
        "default_provider": settings.DEFAULT_AI_PROVIDER
    }

@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """
    Returns system status, active version, and AI provider availability.
    """
    return HealthResponse(
        status="healthy",
        version="1.1.0",
        ai_adapters_available=["mock", "groq", "gemini", "ollama"],
        active_default_ai=settings.DEFAULT_AI_PROVIDER
    )

@app.get("/api/geocode")
async def geocode_endpoint(q: str = Query(..., min_length=1, description="Free-text location search query")):
    """
    Forward-geocoding proxy: searches Nominatim (primary) with Photon fallback.

    Policy:
    - Server-side 1 req/s throttle for Nominatim (OSM usage policy).
    - User-Agent identifies BuildWise.
    - Results cached server-side (LRU, 24h TTL) to minimise upstream calls.
    - Client should additionally cache in localStorage (24h).
    - Attribution: Nominatim / OpenStreetMap contributors; Photon / Komoot.
    - No API key, no paid service.
    """
    result = await geocode_search(q.strip())
    return result

@app.get("/api/geocode/reverse")
async def reverse_geocode_endpoint(
    request: Request,
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude to probe"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="Longitude to probe"),
):
    """Reverse-geocode one manual coordinate so the client can warn when it
    falls on open water (the classic lat/lon swap).  Shares the map-proxy rate
    limit; never raises and reports ``is_fallback`` when it could not answer."""
    check_proxy_rate_limit(_client_ip(request))
    return await reverse_geocode_probe(lat, lon)

@app.get("/api/nearest-road", response_model=NearestRoadResponse)
async def nearest_road_endpoint(request: Request, lat: float = Query(..., ge=-90.0, le=90.0), lon: float = Query(..., ge=-180.0, le=180.0)):
    """
    Overpass nearest-road proxy for the frontage suggestion.

    Policy:
    - Server-side cache (24h hazard cache, ~11 m grid) and a shared <=1 req/s
      Overpass throttle; frontend additionally debounces 400 ms.
    - AMENDMENT 1: the fallback NEVER fabricates a bearing. When Overpass is
      unreachable or maps no road within 500 m, found=false with an explicit
      user-facing warning and the frontage stays manual (ASSUMED annotation).
    - Attribution: © OpenStreetMap contributors (Overpass API).
    """
    client_ip = _client_ip(request)
    check_proxy_rate_limit(client_ip)
    request_id = f"BW-NR-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()

    result, cache_hit, warning = await fetch_nearest_road(lat, lon)

    road = RoadHit(
        bearing_degrees=result["bearing_degrees"],
        approach_side=result["approach_side"],
        distance_meters=result["distance_meters"],
        nearest_point=result.get("nearest_point"),
        highway_class=result.get("highway_class"),
        road_name=result.get("road_name"),
        is_fallback=result["is_fallback"],
    )
    return NearestRoadResponse(
        request_id=request_id,
        timestamp=timestamp,
        lat=lat,
        lon=lon,
        found=not result["is_fallback"],
        road=road,
        provenance=RoadProvenance(
            source=result["source"],
            annotation=result["annotation"],
            cache="hit" if cache_hit else "miss",
        ),
        cached=cache_hit,
        degraded=bool(result["is_fallback"]),
        warning=warning,
    )

@app.post("/api/site/preview", response_model=SitePreviewResponse)
async def site_preview_endpoint(req: SitePreviewRequest):
    """
    Deterministic site geometry preview (setbacks -> buildable -> footprint ->
    parking/wedges) for the map overlay.

    Contracts: NO floor solve, NO LLM, NO network in this path; responses are
    SHA-256 hash-cached and byte-identical for identical inputs; p95 < 150 ms.
    Every annotation carries an explicit CALCULATED/ASSUMED/RECOMMENDED/VERIFIED
    status - ASSUMED never renders as CALCULATED.
    """
    try:
        return compute_site_preview(req)
    except BoundaryStatutoryViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))

@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_site(req: AnalysisRequest, request: Request):
    """
    Executes full multi-criteria site feasibility, orientation optimization,
    CPWD construction cost estimation, risk synthesis, hazard profiling,
    indicative circle rate land valuation, Vastu advisory, and traceable engineering recommendations.
    """
    client_ip = _client_ip(request)
    check_rate_limit(client_ip)
    request_id = f"BW-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()
    warnings = []
    is_degraded = False

    # Server-side boundary validation (the client payload is advisory;
    # area/perimeter recomputed here are authoritative).
    boundary_summary = None
    if req.boundary is not None:
        try:
            boundary_summary = summarize_boundary(req.boundary)
        except BoundaryValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if boundary_summary["area_delta_pct"] is not None and boundary_summary["area_delta_pct"] > 1.0:
            warnings.append(
                f"BOUNDARY-AREA: the client reported "
                f"{boundary_summary['client_area_sqm']:,.1f} m² but the server shoelace "
                f"area is {boundary_summary['area_sqm']:,.1f} m² "
                f"({boundary_summary['area_delta_pct']:.1f}% apart); the server area is "
                "authoritative."
            )

    # 1. Fetch geospatial, elevation, and climate data with fallback tracking
    now_utc = datetime.now(timezone.utc)
    # Per-source fetch provenance: ISO8601 UTC when the upstream was consulted,
    # None when the response carries a deterministic fallback model instead.
    # Emitted on the response so the report disclosures show REAL fetch times.
    data_sources: Dict[str, Any] = {}

    # THE INDEPENDENT UPSTREAMS RUN TOGETHER.  Geocode, elevation, microclimate
    # and the nearest road share no inputs, but were awaited in sequence, so a
    # cold analysis paid for all four back to back (measured: 0.8 + 1.0 + 2.2 +
    # 9.7 s before the hazard block had even started).  They are started as
    # tasks here and collected in dependency order below, so this block costs
    # the slowest source.  The response assembly is untouched and still runs in
    # the original order, so warnings, provenance timestamps and degraded-mode
    # flags read exactly as before.
    geocode_task = asyncio.create_task(fetch_reverse_geocode(req.latitude, req.longitude))
    elevation_task = asyncio.create_task(fetch_elevation_and_slope(req.latitude, req.longitude))
    climate_task = asyncio.create_task(fetch_climate_data(req.latitude, req.longitude))
    road_task = asyncio.create_task(fetch_nearest_road(req.latitude, req.longitude))

    address, address_fallback = await geocode_task
    elevation_m, slope_pct, elev_fallback = await elevation_task
    # The hazard profile needs only the address and the elevation, both of which
    # land in ~1 s; the road lookup is the slow leg (up to its 17 s budget).
    # Starting the hazard fetch HERE lets it overlap that wait instead of
    # queueing behind it: cold analysis measured 22.5 s sequential -> 13.2 s
    # gathered -> 9.7 s with this overlap.
    hazard_task = asyncio.create_task(
        evaluate_hazard_profile(
            lat=req.latitude,
            lon=req.longitude,
            elevation_m=elevation_m,
            address=address,
        )
    )
    climate, climate_fallback = await climate_task
    road_result, _road_cache_hit, road_warning = await road_task

    data_sources["geocode"] = {
        "source": "OpenStreetMap Nominatim (reverse)",
        "fetched_at": None if address_fallback else now_utc.isoformat(),
        "is_fallback": address_fallback,
    }
    if address_fallback:
        warnings.append("Reverse geocoding service timed out. Coordinate identifier applied.")
        is_degraded = True

    data_sources["elevation"] = {
        "source": "Open-Meteo Elevation API (5-point DEM)",
        "fetched_at": None if elev_fallback else now_utc.isoformat(),
        "is_fallback": elev_fallback,
    }
    if elev_fallback:
        warnings.append("Topographic elevation service unreachable. Synthetic contour gradient applied.")
        is_degraded = True

    # Real cardinal elevation samples (cache hit after
    # the call above) are threaded into the Vastu slope reading.
    elevation_samples, _samples_fallback = await fetch_elevation_samples(req.latitude, req.longitude)
    # Vastu needs only the terrain samples, and its own road-approach lookup is
    # a second Overpass round trip.  Starting it here runs that call alongside
    # the MCDA/hazard work instead of adding it after them.
    vastu_task = asyncio.create_task(
        evaluate_vastu_advisory(
            lat=req.latitude,
            lon=req.longitude,
            elevation_m=elevation_m,
            elevation_samples=elevation_samples,
        )
    )

    data_sources["climate"] = {
        "source": "Open-Meteo Forecast + ERA5 Archive",
        "fetched_at": None if climate_fallback else now_utc.isoformat(),
        "is_fallback": climate_fallback,
    }
    if climate_fallback:
        warnings.append("Microclimate telemetry unavailable. Latitudinal climate averages applied.")
        is_degraded = True
    elif climate.get("annual_precipitation_source") == "7day_forecast_extrapolation":
        # Disclose the quality of the rainfall estimate
        warnings.append(
            "Annual rainfall estimated from a short forecast window; verify against "
            "IMD climatological normals before design decisions."
        )

    # 1b. Real nearest-road measurement for the MCDA road factor.
    # Shared Overpass service; result also feeds the Vastu approach cache.
    road_is_fallback = bool(road_result["is_fallback"])
    data_sources["road"] = {
        "source": "OpenStreetMap Overpass API (nearest highway)",
        "fetched_at": None if road_is_fallback else now_utc.isoformat(),
        "is_fallback": road_is_fallback,
    }
    if not road_result["is_fallback"]:
        road_service_available = True
        road_distance_m = road_result["distance_meters"]
    else:
        # Overpass reachable but no road within 500 m is still a real answer
        road_service_available = "No mapped road" in (road_warning or "")
        road_distance_m = None

    # 2. Module 1: Hazard History & Climate Stress Profile (moved ahead of MCDA
    # so the river-discharge flood signal can be fused into the suitability
    # flood factor).  Started above, alongside the road lookup.
    hazard_profile, hazard_warnings = await hazard_task
    for w in hazard_warnings:
        if w not in warnings:
            warnings.append(w)
    if any("unreachable" in w.lower() or "unavailable" in w.lower() for w in hazard_warnings):
        is_degraded = True

    # Hazard telemetry fetch provenance (seismic / flood / storm sources);
    # None means the fallback model was applied for that upstream.
    for _hz_key, _hz_ts in (hazard_profile.source_fetches or {}).items():
        data_sources[_hz_key] = {
            "source": {
                "seismic": "USGS FDSN Earthquake Catalog (250 km, 50 yr)",
                "flood": "Open-Meteo GloFAS River Discharge + NDMA Atlas",
                "storm_cyclone": "ECMWF ERA5 Archive (10-yr gust & rainfall extremes)",
            }.get(_hz_key, _hz_key),
            "fetched_at": _hz_ts,
            "is_fallback": _hz_ts is None,
        }

    # 3. Deterministic calculations (MCDA, orientation, CPWD costs, risks)
    overall_score, verdict, factors = evaluate_land_suitability(
        lat=req.latitude,
        lon=req.longitude,
        elevation_m=elevation_m,
        slope_pct=slope_pct,
        climate=climate,
        road_distance_m=road_distance_m,
        road_service_available=road_service_available,
        flood_profile=hazard_profile.flood
    )

    orientation = calculate_building_orientation(
        latitude=req.latitude,
        wind_dir_deg=climate.get("wind_direction_deg", 240.0)
    )

    cost_estimate = calculate_construction_cost(
        area_sqft=req.built_up_area_sqft,
        quality_grade=req.quality_grade,
        slope_pct=slope_pct,
        floors=req.floors
    )

    # Road and facility scores from factors: an unmeasured road
    # factor carries a neutral 70.0 into the locality multiplier instead of
    # an unknown score, and never triggers a fabricated access risk.
    road_factor = next((f for f in factors if f.factor_id == "road_access"), None)
    road_measured = road_factor is not None and road_factor.status != "unknown"
    road_score = road_factor.score if road_factor else 75.0
    road_score_for_value = road_score if road_measured else 70.0

    facility_factor = next((f for f in factors if f.factor_id == "facility_proximity"), None)
    facility_score = facility_factor.score if facility_factor else 75.0

    risks = identify_site_risks(
        slope_pct=slope_pct,
        elevation_m=elevation_m,
        climate=climate,
        road_score=road_score,
        floors=req.floors,
        road_score_measured=road_measured
    )

    # 4. Module 2: Indicative Land Value Engine
    land_value = calculate_land_value(
        lat=req.latitude,
        lon=req.longitude,
        address=address,
        road_score=road_score_for_value,
        facility_score=facility_score,
        built_up_area_sqft=req.built_up_area_sqft,
        floors=req.floors,
        total_construction_cost_inr=cost_estimate.total_estimated_cost_inr,
        override_rate_per_sqft=req.override_land_rate_per_sqft,
        plot_area_sqft=req.plot_area_sqft,
        ground_coverage_ratio=req.ground_coverage_ratio or 0.60,
        # The captured boundary - not a coverage-derived estimate - is the
        # Plot area the report and the valuation must share.
        boundary_area_sqm=(
            boundary_summary["area_sqm"] if boundary_summary is not None else None
        ),
    )
    if land_value.confidence_warning and land_value.confidence_warning not in warnings:
        warnings.append(land_value.confidence_warning)
    for _plot_warning in land_value.plot_area_warnings:
        if _plot_warning not in warnings:
            warnings.append(_plot_warning)

    # 5. Module 3: Vastu & Functional Planning Advisory (started above)
    vastu_advisory, vastu_warnings = await vastu_task
    for w in vastu_warnings:
        if w not in warnings:
            warnings.append(w)
    if vastu_advisory.road_approach.is_fallback:
        is_degraded = True

    # 6. Module 4: Ranked Traceable Recommendation Engine
    recommendation_items = generate_recommendations(
        factors=factors,
        hazard_profile=hazard_profile,
        land_value=land_value,
        vastu_advisory=vastu_advisory,
        orientation=orientation,
        cost_estimate=cost_estimate
    )
    detailed_recs = [item.recommendation_text for item in recommendation_items]

    # Cap recommendations passed to AI payload to top 8 severity-ranked (Amendment 10)
    top_8_recs = get_top_severity_recommendations(recommendation_items, limit=8)

    # 7. Assemble structured data for AI adapter
    intermediate_data = {
        "request_id": request_id,
        "coordinates": {"latitude": req.latitude, "longitude": req.longitude},
        "formatted_address": address,
        "overall_suitability_score": overall_score,
        "suitability_verdict": verdict,
        "factors": [f.model_dump() for f in factors],
        "orientation": orientation.model_dump(),
        "cost_estimate": cost_estimate.model_dump(),
        "risks": [r.model_dump() for r in risks],
        "hazard_profile": hazard_profile.model_dump(),
        "land_value": land_value.model_dump(),
        "vastu_advisory": vastu_advisory.model_dump(),
        "recommendations": [r.model_dump() for r in top_8_recs],
        "built_up_area_sqft": req.built_up_area_sqft,
        "quality_grade": req.quality_grade,
        "floors": req.floors,
        "client_requirements": req.client_requirements
    }

    # 8. Generate engineering commentary via requested AI adapter
    provider_name = req.ai_provider or settings.DEFAULT_AI_PROVIDER
    adapter = get_ai_adapter(provider_name)
    summary, ai_recs, ai_meta = await adapter.generate_explanation(intermediate_data)

    if ai_meta.get("fallback_reason"):
        warnings.append(f"AI Provider note: {ai_meta.get('fallback_reason')}")

    # AI adapters narrate only. Numeric report fields are
    # NEVER sourced from LLM metadata - feasibility_score always mirrors the
    # deterministic MCDA result, and cost/vastu blocks always come from the
    # deterministic engines (base_adapter contract in app/ai/base_adapter.py).
    # LLM boundary: the narrative may describe the site, but any
    # score / rate / total / seismic zone it asserts is removed before it is
    # returned.  Those values exist only in the deterministic fields above, so
    # no reader can mistake a model guess for a certified number.
    from app.services.ai_narrative import sanitize_narrative

    _narrative_redactions: List[str] = []
    if ai_meta.get("parameter_reflection"):
        _clean_narrative, _redactions = sanitize_narrative(str(ai_meta.get("parameter_reflection")))
        ai_meta = {**ai_meta, "parameter_reflection": _clean_narrative}
        _narrative_redactions.extend(_redactions)
    if summary:
        _clean_summary, _summary_redactions = sanitize_narrative(str(summary))
        summary = _clean_summary
        _narrative_redactions.extend(r for r in _summary_redactions if r not in _narrative_redactions)
    # The model's self-reported score is not a report value and must not travel
    # beside one; the certified score is `feasibility_score` (deterministic).
    ai_meta.pop("feasibility_score", None)
    ai_meta["narrative_class"] = "advisory_non_certified"
    ai_meta["narrative_redactions"] = ",".join(dict.fromkeys(_narrative_redactions))

    param_reflection = ai_meta.get("parameter_reflection") or (
        f"Site analysis reflects {req.built_up_area_sqft:,.0f} sq ft built-up area with {req.quality_grade.capitalize()} "
        f"specification grade and {f'G+{req.floors-1}' if req.floors > 1 else 'G'} storeys."
    )
    feasibility_score_val = int(round(overall_score))
    cost_breakdown_val = cost_estimate.model_dump()
    vastu_compliance_val = vastu_advisory.model_dump()

    try:
        return AnalysisResponse(
            request_id=request_id,
            timestamp=timestamp,
            coordinates={"latitude": req.latitude, "longitude": req.longitude},
            formatted_address=address,
            overall_suitability_score=overall_score,
            suitability_verdict=verdict,
            factors=factors,
            orientation=orientation,
            cost_estimate=cost_estimate,
            risks=risks,
            hazard_profile=hazard_profile,
            land_value=land_value,
            vastu_advisory=vastu_advisory,
            recommendation_items=recommendation_items,
            detailed_recommendations=detailed_recs,
            engineering_summary=summary,
            ai_metadata=ai_meta,
            degraded_mode=is_degraded,
            warnings=warnings,
            parameter_reflection=param_reflection,
            methodology=methodology_notes(),
            feasibility_score=feasibility_score_val,
            structural_recommendations=ai_recs,
            cost_breakdown=cost_breakdown_val,
            vastu_compliance=vastu_compliance_val,
            boundary_summary=boundary_summary,
            storeys=int(req.floors),
            building_typology=req.building_typology,
            data_sources=data_sources
        )
    except ValidationError as val_err:
        logger.warning(f"Pydantic validation error constructing AnalysisResponse: {val_err}")
        # Discard LLM output, return deterministic mock data with provider_used='mock_fallback_validation_error'
        mock_adapter = get_ai_adapter("mock")
        mock_summary, mock_recs, mock_meta = await mock_adapter.generate_explanation(intermediate_data)
        mock_meta["provider_requested"] = provider_name
        mock_meta["provider_used"] = "mock_fallback_validation_error"
        mock_meta["fallback_reason"] = f"Pydantic ValidationError: {str(val_err)[:100]}"
        warnings.append("AI response validation error. Applied deterministic mock calculations.")
        return AnalysisResponse(
            request_id=request_id,
            timestamp=timestamp,
            coordinates={"latitude": req.latitude, "longitude": req.longitude},
            formatted_address=address,
            overall_suitability_score=overall_score,
            suitability_verdict=verdict,
            factors=factors,
            orientation=orientation,
            cost_estimate=cost_estimate,
            risks=risks,
            hazard_profile=hazard_profile,
            land_value=land_value,
            vastu_advisory=vastu_advisory,
            recommendation_items=recommendation_items,
            detailed_recommendations=detailed_recs,
            engineering_summary=mock_summary,
            ai_metadata=mock_meta,
            degraded_mode=True,
            warnings=warnings,
            parameter_reflection=mock_meta.get("parameter_reflection", param_reflection),
            methodology=methodology_notes(),
            boundary_summary=boundary_summary,
            feasibility_score=int(round(overall_score)),
            structural_recommendations=mock_recs,
            cost_breakdown=cost_estimate.model_dump(),
            vastu_compliance=vastu_advisory.model_dump(),
            storeys=int(req.floors),
            building_typology=req.building_typology,
            data_sources=data_sources
        )

@app.post("/api/report")
async def create_pdf_report(req: ReportRequest):
    """
    Compiles and streams a high-resolution, vector PDF engineering feasibility report.
    """
    if not req.analysis_data:
        raise HTTPException(status_code=400, detail="Invalid request: Missing analysis data payload.")

    # Structural sanity validation of the
    # client-supplied payload before it is rendered into the PDF dossier.
    analysis = req.analysis_data
    if not isinstance(analysis, dict):
        raise HTTPException(status_code=422, detail="analysis_data must be a JSON object.")
    coords = analysis.get("coordinates")
    if coords is not None:
        if not isinstance(coords, dict):
            raise HTTPException(status_code=422, detail="analysis_data.coordinates must be an object.")
        lat_v = coords.get("latitude")
        lon_v = coords.get("longitude")
        if lat_v is not None and (not isinstance(lat_v, (int, float)) or not -90.0 <= lat_v <= 90.0):
            raise HTTPException(status_code=422, detail="analysis_data.coordinates.latitude must be a number in [-90, 90].")
        if lon_v is not None and (not isinstance(lon_v, (int, float)) or not -180.0 <= lon_v <= 180.0):
            raise HTTPException(status_code=422, detail="analysis_data.coordinates.longitude must be a number in [-180, 180].")
    score_v = analysis.get("overall_suitability_score")
    if score_v is not None and (not isinstance(score_v, (int, float)) or isinstance(score_v, bool)):
        raise HTTPException(status_code=422, detail="analysis_data.overall_suitability_score must be a number.")

    try:
        fp_payload = req.floor_plan
        if not fp_payload and isinstance(req.analysis_data, dict):
            fp_payload = req.analysis_data.get("floor_plan") or req.analysis_data.get("floorplan")

        # ReportLab is synchronous and CPU-bound; on the event loop it stalls
        # every other request for the duration of the PDF build.
        pdf_stream = await asyncio.to_thread(
            generate_pdf_report,
            req.analysis_data,
            site_vision=req.site_vision,
            floor_plan=fp_payload,
        )
        coords = req.analysis_data.get("coordinates") or {}
        lat_val = coords.get('latitude') if isinstance(coords.get('latitude'), (int, float)) else 0.0
        lon_val = coords.get('longitude') if isinstance(coords.get('longitude'), (int, float)) else 0.0
        lat_str = f"{lat_val:.2f}"
        lon_str = f"{lon_val:.2f}"
        filename = f"BuildWise_Report_{lat_str}_{lon_str}.pdf"

        return StreamingResponse(
            pdf_stream,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF generation error: {str(e)}")

@app.post("/api/site-vision", response_model=SiteVisionResponse)
async def site_vision_analysis(req: SiteVisionRequest):
    """
    Executes ecological satellite vision analysis over Copernicus Sentinel-2 L2A imagery.
    Computes Green Cover Index, water detection, built-up ratio, and Tree Preservation Plan.
    """
    try:
        response = await analyze_site_vision(
            latitude=req.latitude,
            longitude=req.longitude,
            plot_area_sqft=req.plot_area_sqft,
            mode_override=req.mode_override,
            orientation_deg=req.orientation_deg
        )
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Site vision analysis error: {str(e)}")

@app.post("/api/generate-floorplan")
async def create_generative_floorplan(
    req: FloorPlanRequest,
    format: Optional[str] = Query(default=None, description="Output format: 'json' or 'pdf'")
):
    """
    Executes the universal ontology-driven sole geometry engine (SoleGeometryEngine) for
    all typologies (T1–T4), enforcing Vastu Shastra zoning, NBC 2016 statutory minima,
    plumbing wet-wall adjacency, BFS egress reachability, and vertical core stacking invariants.
    Returns 2D matrix, placements, metrics, and production-grade SVG blueprint (JSON),
    or streams a multi-page PDF architectural dossier when format='pdf'.
    """
    from app.services.floorplan.errors import DesignInfeasibleError
    from app.services.plan_verdict import compute_plan_verdict, plan_verdict_reasons

    try:
        if format == "pdf" and req.multi_storey is not None:
            # Direct export of pre-generated multi-storey model (skips solver re-run)
            ms_dict = req.multi_storey.model_dump()
            typology = req.building_typology or req.multi_storey.building_typology or "residential_single"
            typ_label = typology.replace("_", " ").title()
            total_floors = req.multi_storey.total_storeys
            built_up_sqft = req.built_up_area_sqft or (req.multi_storey.total_built_up_area_sqm * 10.764)
            first_floor = ms_dict["floors"][0] if ms_dict.get("floors") else {}
            # Metrics for a re-exported model are MEASURED from that model, not
            # Copied from constants. A metric the floormodel does not
            # carry stays None and prints as “—”.
            _ms_floors = ms_dict.get("floors") or []
            _ms_rooms = [r for _f in _ms_floors for r in (_f.get("rooms") or [])]
            _ms_usable = sum(
                float(r.get("area_sqm") or 0.0) for r in _ms_rooms
                if r.get("zone_category") not in ("circulation", "terrace")
            )
            _ms_circulation = sum(
                float(r.get("area_sqm") or 0.0) for r in _ms_rooms
                if r.get("zone_category") == "circulation"
            )
            _ms_util_num = sum(float(_f.get("built_up_area_sqm") or 0.0) for _f in _ms_floors)
            _ms_util_den = sum(
                float((_f.get("envelope") or {}).get("area_sqm") or 0.0) for _f in _ms_floors
            )
            _ms_vastu = [
                float(_f["vastu_score_pct"]) for _f in _ms_floors
                if isinstance(_f.get("vastu_score_pct"), (int, float))
            ]
            _ms_plumb = [
                float(_f["plumbing_stack_alignment_pct"]) for _f in _ms_floors
                if isinstance(_f.get("plumbing_stack_alignment_pct"), (int, float))
            ]
            fp_payload = {
                "plan_verdict": compute_plan_verdict({
                    "multi_storey": ms_dict,
                    "mathematical_certificate": ms_dict.get("mathematical_certificate"),
                }),
                "multi_storey": ms_dict,
                "plot_width_m": req.plot_width_m or (req.multi_storey.plot_width_m if req.multi_storey else None),
                "plot_depth_m": req.plot_depth_m or (req.multi_storey.plot_depth_m if req.multi_storey else None),
                "seed": str(req.multi_storey.seed if req.multi_storey else "GEN-F01"),
                "metrics": {
                    "vastu_compliance_pct": (round(sum(_ms_vastu) / len(_ms_vastu), 1) if _ms_vastu else None),
                    "plumbing_adjacency_score": (round(sum(_ms_plumb) / len(_ms_plumb), 1) if _ms_plumb else None),
                    "space_utilization_pct": (
                        round(100.0 * _ms_util_num / _ms_util_den, 1) if _ms_util_den > 0 else None
                    ),
                    "plot_coverage_pct": (req.ground_coverage_ratio or 0.6) * 100,
                    "total_built_up_sqm": req.multi_storey.total_built_up_area_sqm,
                    "circulation_efficiency_pct": (
                        round(100.0 * _ms_usable / (_ms_usable + _ms_circulation), 1)
                        if (_ms_usable + _ms_circulation) > 0 else None
                    ),
                },
                "rectangles": {
                    "envelope": first_floor.get("envelope", {}),
                    "rooms": first_floor.get("rooms", []),
                    "doors": first_floor.get("doors", []),
                    "windows": first_floor.get("windows", []),
                },
                "placements": [
                    {
                        "room_id": r.get("room_id", ""),
                        "room_name": r.get("room_name", ""),
                        "row": 0,
                        "col": 0,
                        "width": int(r.get("width_m", 1)),
                        "height": int(r.get("depth_m", 1)),
                        "area_sqm": r.get("area_sqm", 0),
                        "width_m": r.get("width_m", 0),
                        "depth_m": r.get("depth_m", 0),
                        "zone": r.get("zone", ""),
                        "vastu_compliant": r.get("vastu_compliant", True),
                    }
                    for r in first_floor.get("rooms", [])
                ]
            }
            mock_analysis = {
                "request_id": f"BW-FP-{int(time.time())}",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                # Use the caller's actual site coordinates when
                # provided instead of a hardcoded Bengaluru placeholder.
                "coordinates": {"latitude": req.latitude if req.latitude is not None else 0.0, "longitude": req.longitude if req.longitude is not None else 0.0},
                "formatted_address": (
                    f"{typ_label} Multi-Storey Architectural Dossier"
                    + (f" (WGS84 {req.latitude:.5f}, {req.longitude:.5f})" if req.latitude is not None and req.longitude is not None else "")
                ),
                "overall_suitability_score": 90.0,
                "suitability_verdict": "Architectural Design Complete",
                "built_up_area_sqft": built_up_sqft,
                "quality_grade": req.quality_grade or "standard",
                "floors": total_floors,
                "building_typology": typology,
                "plot_width_m": req.plot_width_m or (req.multi_storey.plot_width_m if req.multi_storey else None),
                "plot_depth_m": req.plot_depth_m or (req.multi_storey.plot_depth_m if req.multi_storey else None),
                "seed": str(req.multi_storey.seed if req.multi_storey else "GEN-F01"),
                "engineering_summary": req.client_notes or f"Autonomous architectural spatial allocation generated by BuildWise CF-HSA Multi-Storey Solver for {typ_label}.",
            }
            pdf_stream = await asyncio.to_thread(
                generate_pdf_report,
                mock_analysis,
                floor_plan=fp_payload,
                dossier_only=True,
                include_construction_schedules=True,
            )
            return StreamingResponse(
                pdf_stream,
                media_type="application/pdf",
                headers={"Content-Disposition": 'attachment; filename="BuildWise_Architectural_Floorplan_Dossier.pdf"'}
            )

        # Pre-compute or resolve RoomProgram via LLM before solver execution if not provided
        if req.room_program is None:
            typology = req.building_typology or "residential_single"
            grade = req.quality_grade or "standard"
            storeys = req.floors or 1
            coverage = req.ground_coverage_ratio or 0.60
            built_up_area = req.built_up_area_sqft or (req.plot_width_m * req.plot_depth_m * 10.764 * coverage)
            notes = req.client_notes
            params = {
                "typology": typology,
                "building_typology": typology,
                "grade": grade,
                "quality_grade": grade,
                "storeys": storeys,
                "floors": storeys,
                "coverage": coverage,
                "ground_coverage": coverage,
                "built_up_area": built_up_area,
                "built_up_area_sqft": built_up_area,
                "client_notes": notes,
                "solar_axis_degrees": req.solar_axis_degrees,
                "prevailing_wind_direction_degrees": req.prevailing_wind_direction_degrees,
                "top_vastu_entrances": req.top_vastu_entrances,
                "required_rooms": req.required_rooms,
                "plot_width_m": req.plot_width_m,
                "plot_depth_m": req.plot_depth_m,
                "vastu_strictness": req.vastu_strictness,
                "bypass_cache": req.bypass_cache or False,
            }
            prog, prog_source = await generate_room_program(params, req.ai_provider)
            # Programme contract at the API boundary: a generated room programme
            # must actually shape the plate. The single-storey T1 partitioner keys
            # on required_rooms, so a caller that supplied only the plinth area
            # used to get the ontology's default plate while the generated
            # programme was silently discarded (the plinth-area control then had no
            # visible effect on the drawing). Derive the required-room list from
            # the programme so the two agree; explicit caller lists still win.
            _req_update: Dict[str, Any] = {"room_program": prog, "program_source": prog_source}
            if not req.required_rooms and storeys <= 1 and prog.rooms:
                from app.services.floorplan.engine import SoleGeometryEngine as _SGE

                _mapped: List[str] = []
                for _room in prog.rooms:
                    _mid = _SGE._map_client_room_token(_room.name)  # noqa: SLF001 - shared mapping
                    if _mid not in _mapped:
                        _mapped.append(_mid)
                if len(_mapped) >= 3:
                    _req_update["required_rooms"] = _mapped
            req = req.model_copy(update=_req_update)

        # The solver is a pure, synchronous CSP/geometry engine (2-8 s for a
        # multi-storey programme).  Run it in a worker thread so a blueprint
        # request cannot freeze the analysis, site-vision or report endpoints
        # that the same page fires concurrently.
        # Solve the ladder before stamping FAIL: S0 as-is, then the ordered
        # S1-S5 strategies.  Certified S0 short-circuits, so good plans are not
        # churned; every tried strategy stays on the response as a chain.
        from app.services.floorplan.strategy_escalation import solve_with_escalation
        response = await asyncio.to_thread(solve_with_escalation, req)

        # ONE verdict for this generation, computed from the certificate, the
        # gate and the page-1 plan warnings.  Card, certificate panel and PDF
        # all render this string verbatim.
        _verdict_payload = response.model_dump()
        response = response.model_copy(
            update={
                "plan_verdict": compute_plan_verdict(_verdict_payload),
                "plan_verdict_reasons": plan_verdict_reasons(_verdict_payload),
            }
        )

        if format == "pdf":
            # Stream architectural multi-page PDF dossier directly
            typ_label = (req.building_typology or "Architectural").replace("_", " ").title()
            mock_analysis = {
                "request_id": f"BW-FP-{int(time.time())}",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                # Use the caller's actual site coordinates when provided.
                "coordinates": {"latitude": req.latitude if req.latitude is not None else 0.0, "longitude": req.longitude if req.longitude is not None else 0.0},
                "formatted_address": (
                    f"{typ_label} Floor Plan Dossier"
                    + (f" (WGS84 {req.latitude:.5f}, {req.longitude:.5f})" if req.latitude is not None and req.longitude is not None else "")
                ),
                "overall_suitability_score": 90.0,
                "suitability_verdict": "Architectural Design Complete",
                "built_up_area_sqft": req.built_up_area_sqft or (req.plot_width_m * req.plot_depth_m * 10.764 * (req.ground_coverage_ratio or 0.6)),
                "quality_grade": req.quality_grade or "standard",
                "floors": req.floors or 1,
                "building_typology": req.building_typology or "residential_single",
                "plot_width_m": req.plot_width_m,
                "plot_depth_m": req.plot_depth_m,
                "seed": str(getattr(response, "seed", None) or (response.multi_storey.seed if response.multi_storey else "GEN-F01")),
                "engineering_summary": req.client_notes or f"Autonomous architectural spatial allocation generated by BuildWise CF-HSA Multi-Storey Solver for {typ_label}.",
            }
            pdf_stream = await asyncio.to_thread(
                generate_pdf_report,
                mock_analysis,
                floor_plan=response.model_dump(),
                dossier_only=True,
                include_construction_schedules=True,
            )
            return StreamingResponse(
                pdf_stream,
                media_type="application/pdf",
                headers={"Content-Disposition": 'attachment; filename="BuildWise_Architectural_Floorplan_Dossier.pdf"'}
            )

        return response
    except DesignInfeasibleError as e:
        # A measured, client-fixable design refusal: the request is valid, the
        # site is real, and the engine has measured that the requested layout
        # cannot be drawn on the legal plate.  Answer 422 with the named reason
        # instead of turning a design answer into a server fault.
        raise HTTPException(
            status_code=422,
            detail=f"Floor plan design infeasible [{e.code}]: {e.reason}",
        )
    except ValueError as e:
        # Client-fixable design-constraint violations (RULE-FP-*, Hard Constraint
        # Violation, vertical stacking) are bad requests (422), not server faults.
        msg = str(e)
        if "Hard Constraint Violation" in msg or "RULE-FP-" in msg:
            raise HTTPException(status_code=422, detail=f"Floor plan constraint violation: {msg}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Floor plan generation error: {msg}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Floor plan generation error: {str(e)}")


@app.post("/api/floorplan/remediation")
async def floorplan_remediation(req: RemediationIn):
    """Deterministic next steps for a plan, each with an ENGINE-measured effect.

    The browser sends the plan's own warnings plus the request that produced it;
    the server derives the options and re-solves each one with only that option's
    validated input changed. Nothing here is generated by an LLM.
    """
    from app.services.floorplan.remediation import build_options

    try:
        return await asyncio.to_thread(build_options, req)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Remediation dry-run failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Remediation dry-run failed: {exc}")


@app.post("/api/floorplan/advisory")
async def floorplan_advisory(req: AdvisoryIn):
    """Advisory narrative for the plan's blocking reasons and measured options.

    Labelled ``advisory_non_certified``; cached per plan hash; on timeout or a
    missing key it returns ``narrative=None`` and a disclosed reason so the
    deterministic summary stands alone.
    """
    from app.ai.floorplan_advisor import advise

    try:
        return await advise(req)
    except Exception as exc:  # noqa: BLE001 - the advisor must never break the plan
        logger.warning(f"Floorplan advisor failed: {exc}")
        from app.schemas.remediation import AdvisoryMeta, AdvisoryOut

        return AdvisoryOut(
            narrative=None,
            meta=AdvisoryMeta(
                provider_requested="groq",
                provider_used="deterministic_only",
                fallback_reason=f"advisor error: {str(exc)[:120]}",
            ),
        )


class ParseRequirementsRequest(BaseModel):
    requirements_text: str
    ai_provider: Optional[str] = "groq"


@app.post("/api/parse-requirements", response_model=ExtractedClientConstraints)
async def parse_requirements_endpoint(req: ParseRequirementsRequest):
    """
    Extracts structured architectural design constraints from free-text client notes.
    """
    try:
        from app.ai.requirements_parser import parse_client_requirements
        return await parse_client_requirements(req.requirements_text, req.ai_provider)
    except Exception as e:
        logger.warning(f"Error parsing requirements: {e}")
        from app.ai.requirements_parser import parse_client_requirements_fallback
        return parse_client_requirements_fallback(req.requirements_text)

