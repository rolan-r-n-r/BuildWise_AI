import asyncio
import hashlib
import json
import math
import uuid
import time
import logging
import threading
from collections import defaultdict, OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from typing import Any, Dict, List, Optional, Tuple
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
from app.schemas.blueprint_ai import BlueprintAIAnalysisRequest, BlueprintAIAnalysisResponse
from app.schemas.multi_floor_plan import ExtractedClientConstraints
from app.schemas.remediation import AdvisoryIn, RemediationIn
from app.services.report_service import generate_pdf_report_with_cache
from app.services import (
    fetch_reverse_geocode,
    fetch_elevation_and_slope,
    fetch_climate_data,
    evaluate_land_suitability,
    calculate_building_orientation,
    calculate_construction_cost,
    identify_site_risks,
    evaluate_hazard_profile,
    calculate_land_value,
    evaluate_vastu_advisory,
    generate_recommendations,
    get_top_severity_recommendations,
    analyze_site_vision,
)

from app.ai import get_ai_adapter, generate_room_program
from app.auth import AuthenticatedUser, get_current_user, get_optional_current_user, auth_router
from app.ai.routes import router as ai_router
from app.ai.execution_resolver import ExecutionResolver
from app.services.geocode_service import geocode_search, reverse_geocode_probe
from app.services.hazard_service import (
    fetch_usgs_seismic_data,
    fetch_open_meteo_flood_data,
    fetch_era5_storm_data,
)
from app.services.methodology import methodology_notes
from app.services.external_data_service import fetch_elevation_samples
from app.services.road_service import fetch_nearest_road, fetch_facility_count
from app.schemas.site_intelligence import (
    NearestRoadResponse,
    RoadHit,
    RoadProvenance,
    SitePreviewRequest,
    SitePreviewResponse,
)
from app.services.site_preview_service import (
    BoundaryStatutoryViolation,
    compute_site_preview,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        f"Starting BuildWise backend engine: env={settings.ENVIRONMENT}, "
        f"default_ai={settings.DEFAULT_AI_PROVIDER}, "
        f"trusted_proxies={len(settings.TRUSTED_PROXIES)}"
    )
    for warning in settings.validate_security():
        logger.warning(warning)
    try:
        from app.db import init_db
        try:
            init_db()
            logger.info("Initialized BuildWise persistence layer.")
        except Exception as db_err:
            logger.error(f"Database initialization warning (server will start and retry on request): {db_err}")
        yield
    finally:
        logger.info("Shutting down BuildWise backend cleanly.")
        try:
            from app.db import close_pg_pool
            close_pg_pool()
        except Exception as pool_err:
            logger.warning(f"Error closing PostgreSQL connection pool: {pool_err}")


app = FastAPI(
    title="BuildWise AI API",
    description="Geo-based intelligent construction feasibility, orientation, cost estimation, hazard, land value, and Vastu advisory engine.",
    version="1.1.0",
    lifespan=lifespan,
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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled server exception on {request.method} {request.url.path}: {exc}")
    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred."},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) or "Internal server error"},
    )


# CORS configuration: strict configured origins in production, localhost permissible in dev
if settings.is_production:
    ALLOWED_ORIGINS = [o for o in settings.CORS_ORIGINS if o and o != "*"]
else:
    ALLOWED_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]
    for origin in settings.CORS_ORIGINS:
        if origin and origin != "*" and origin not in ALLOWED_ORIGINS:
            ALLOWED_ORIGINS.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # The download probe (and the client) reads this to confirm reuse without
    # exposing any report content.
    expose_headers=["X-Buildwise-Report-Cache"],
)


@app.middleware("http")
async def set_security_headers(request: Request, call_next):
    """Enforce production HTTP security headers across all API endpoints."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

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

    # Enforce body size limits during streaming / chunked transfers
    request.state.body_size_exceeded = False
    if request.method in ("POST", "PUT", "PATCH"):
        received_bytes = 0
        original_receive = request.receive

        async def limited_receive():
            nonlocal received_bytes
            message = await original_receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                received_bytes += len(body)
                if received_bytes > MAX_REQUEST_BODY_BYTES:
                    request.state.body_size_exceeded = True
                    raise HTTPException(
                        status_code=413,
                        detail=f"Request body exceeds maximum size limit of {MAX_REQUEST_BODY_BYTES} bytes.",
                    )
            return message

        request._receive = limited_receive

    try:
        response = await call_next(request)
    except Exception as exc:
        if getattr(request.state, "body_size_exceeded", False):
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body exceeds maximum size limit of {MAX_REQUEST_BODY_BYTES} bytes."},
            )
        if isinstance(exc, HTTPException) and exc.status_code == 413:
            return JSONResponse(status_code=413, content={"detail": exc.detail})
        raise

    if getattr(request.state, "body_size_exceeded", False):
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds maximum size limit of {MAX_REQUEST_BODY_BYTES} bytes."},
        )
    return response

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
    for store in (_client_request_history, _proxy_request_history, _wakeup_request_history):
        idle = [ip for ip, ts in store.items() if not ts or now - ts[-1] >= RATE_LIMIT_WINDOW_SEC]
        for ip in idle:
            store.pop(ip, None)

def _client_ip(request: Request) -> str:
    """Client IP with secure trusted reverse proxy verification.

    X-Forwarded-For is only parsed when the direct peer connection originates
    from a configured trusted proxy, preventing client-side IP spoofing and rate
    limit evasion.
    """
    direct_host = request.client.host if request.client else "127.0.0.1"
    trusted = getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1", "testclient", "localhost"])
    if "*" in trusted or direct_host in trusted:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    return direct_host

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

# Sliding-window rate limit for wake-up requests: protects cold-start wake triggers from spam
WAKEUP_RATE_LIMIT_WINDOW_SEC = 60.0
WAKEUP_RATE_LIMIT_MAX_REQUESTS = 45
_wakeup_request_history = defaultdict(list)

def check_wakeup_rate_limit(client_ip: str):
    now = time.time()
    _prune_rate_histories(now)
    timestamps = _wakeup_request_history[client_ip]
    _wakeup_request_history[client_ip] = [t for t in timestamps if now - t < WAKEUP_RATE_LIMIT_WINDOW_SEC]
    if len(_wakeup_request_history[client_ip]) >= WAKEUP_RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many wake-up attempts. Please wait before retrying."
        )
    _wakeup_request_history[client_ip].append(now)

@app.get("/api/wake-up")
@app.post("/api/wake-up")
@app.head("/api/wake-up")
async def wake_up_endpoint(request: Request):
    """
    Wake-up probe for sleeping instances (Render free-tier cold-starts or manual wake triggers).
    Confirms backend availability, applies rate-limiting to prevent request flooding,
    and returns immediate operational status without exposing internal infrastructure details.
    """
    client_ip = _client_ip(request)
    check_wakeup_rate_limit(client_ip)
    return {
        "status": "online",
        "message": "BuildWise backend is operational",
        "service": "buildwise-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/status")
async def api_status(
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
):
    """
    Lightweight status endpoint indicating configured LLM keys, BYOK capabilities,
    and user-specific provider states.
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

    from app.db.ai_credential_repository import AICredentialRepository
    ai_repo = AICredentialRepository()
    user_configured = []
    preferred = "deterministic"
    preferred_model = None
    configured_models = {}
    if current_user and current_user.id:
        user_creds = ai_repo.list_credentials(current_user.id)
        user_configured = [c.provider for c in user_creds if c.status == "connected"]
        configured_models = {
            c.provider: c.selected_model
            for c in user_creds
            if c.status == "connected" and c.selected_model
        }
        pref = ai_repo.get_preference(current_user.id)
        preferred = pref.preferred_provider
        preferred_model = pref.preferred_model

    return {
        "status": "online",
        "groq": has_groq or ("groq" in user_configured),
        "gemini": has_gemini or ("gemini" in user_configured),
        "openai": ("openai" in user_configured),
        "anthropic": ("anthropic" in user_configured),
        "ollama": ("ollama" in user_configured),
        "default_provider": settings.DEFAULT_AI_PROVIDER,
        "deterministic_engine": True,
        "byok_supported": True,
        "user_configured_providers": user_configured,
        "user_preferred_provider": preferred,
        "user_preferred_model": preferred_model,
        "configured_models": configured_models,
    }

@app.get("/", response_model=HealthResponse)
@app.head("/")
@app.get("/health", response_model=HealthResponse)
@app.head("/health")
@app.get("/api/health", response_model=HealthResponse)
@app.head("/api/health")
async def health_check():
    """
    Returns system status, active version, and AI provider availability.
    Lightweight liveness probe that avoids database or external network I/O.
    """
    return HealthResponse(
        status="healthy",
        version="1.1.0",
        message="BuildWise backend is operational",
        ai_adapters_available=["mock", "groq", "gemini", "openai", "anthropic", "ollama"],
        active_default_ai=settings.DEFAULT_AI_PROVIDER
    )


@app.get("/ready")
@app.get("/api/ready")
async def readiness_check():
    """
    Readiness probe: validates database connectivity with a bounded 2-second timeout.
    Used by orchestrators to confirm the backend is ready to accept client traffic.
    """
    from app.db.database import get_connection
    try:
        def _db_ping():
            with get_connection() as conn:
                cursor = conn.execute("SELECT 1")
                cursor.fetchone()
        await asyncio.wait_for(asyncio.to_thread(_db_ping), timeout=2.0)
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        logger.warning(f"Readiness check failed: {exc}")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable", "detail": "Database is not currently reachable."},
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
async def analyze_site(
    req: AnalysisRequest,
    request: Request,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
):
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
    # ALL 8 INDEPENDENT UPSTREAMS RUN CONCURRENTLY FROM T=0.
    # Geocode, elevation, microclimate, nearest road, facilities, USGS seismic,
    # GloFAS flood discharge, and ERA5 storm history share no inputs and are all
    # launched simultaneously so the cold telemetry fetch costs only the single
    # slowest source.
    geocode_task = asyncio.create_task(fetch_reverse_geocode(req.latitude, req.longitude))
    elevation_task = asyncio.create_task(fetch_elevation_and_slope(req.latitude, req.longitude))
    climate_task = asyncio.create_task(fetch_climate_data(req.latitude, req.longitude))
    road_task = asyncio.create_task(fetch_nearest_road(req.latitude, req.longitude))
    facility_task = asyncio.create_task(fetch_facility_count(req.latitude, req.longitude))
    seismic_task = asyncio.create_task(fetch_usgs_seismic_data(req.latitude, req.longitude))
    flood_task = asyncio.create_task(fetch_open_meteo_flood_data(req.latitude, req.longitude))
    storm_task = asyncio.create_task(fetch_era5_storm_data(req.latitude, req.longitude))

    address, address_fallback = await geocode_task
    elevation_m, slope_pct, elev_fallback = await elevation_task

    # Collect the pre-started hazard telemetry tasks and resolve hazard profile
    async def _resolve_hazard_profile():
        raw_telemetry = (
            await seismic_task,
            await flood_task,
            await storm_task,
        )
        return await evaluate_hazard_profile(
            lat=req.latitude,
            lon=req.longitude,
            elevation_m=elevation_m,
            address=address,
            raw_telemetry=raw_telemetry,
        )

    hazard_task = asyncio.create_task(_resolve_hazard_profile())

    # Real cardinal elevation samples (cache hit after
    # the call above) are threaded into the Vastu slope reading.
    elevation_samples, _samples_fallback = await fetch_elevation_samples(req.latitude, req.longitude)
    # Vastu needs only the terrain samples, and its own road-approach lookup is
    # a second Overpass round trip. Starting it here runs that call alongside
    # climate, road, facilities, and hazard work.
    vastu_task = asyncio.create_task(
        evaluate_vastu_advisory(
            lat=req.latitude,
            lon=req.longitude,
            elevation_m=elevation_m,
            elevation_samples=elevation_samples,
        )
    )

    climate, climate_fallback = await climate_task
    road_result, _road_cache_hit, road_warning = await road_task
    facility_count, facility_fallback = await facility_task

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

    data_sources["facilities"] = {
        "source": "OpenStreetMap Overpass API (amenities within 1.5 km)",
        "fetched_at": None if facility_fallback else now_utc.isoformat(),
        "is_fallback": facility_fallback,
    }

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
        flood_profile=hazard_profile.flood,
        facility_count=facility_count,
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

    # 8. Generate engineering commentary via ExecutionResolver (Hybrid BYOK + Deterministic Engine)
    provider_name = req.ai_provider or settings.DEFAULT_AI_PROVIDER
    resolver = ExecutionResolver()
    summary, ai_recs, ai_meta = await resolver.execute_explanation(
        intermediate_data,
        user=current_user,
        requested_provider=provider_name,
        requested_model=getattr(req, "ai_model", None),
    )

    if ai_meta.get("fallback_reason"):
        warnings.append(f"Engine note: {ai_meta.get('fallback_reason')}")

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

    # Resolve structured AI narrative
    from app.schemas.response import SiteFeasibilityAIAnalysis
    validated_structured_narrative = None
    structured_narrative_raw = ai_meta.get("structured_narrative")
    if structured_narrative_raw and isinstance(structured_narrative_raw, dict):
        try:
            validated_structured_narrative = SiteFeasibilityAIAnalysis.model_validate(structured_narrative_raw)
        except Exception as _sn_err:
            logger.debug(f"Could not validate structured_narrative: {_sn_err}")

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
            data_sources=data_sources,
            structured_narrative=validated_structured_narrative
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
        fallback_sn = None
        if mock_meta.get("structured_narrative"):
            try:
                fallback_sn = SiteFeasibilityAIAnalysis.model_validate(mock_meta["structured_narrative"])
            except Exception:
                fallback_sn = None
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
            degraded_mode=is_degraded,
            warnings=warnings,
            parameter_reflection=mock_meta.get("parameter_reflection"),
            methodology=methodology_notes(),
            feasibility_score=feasibility_score_val,
            structural_recommendations=mock_recs,
            cost_breakdown=cost_breakdown_val,
            vastu_compliance=vastu_compliance_val,
            boundary_summary=boundary_summary,
            storeys=int(req.floors),
            building_typology=req.building_typology,
            data_sources=data_sources,
            structured_narrative=fallback_sn
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
        pdf_stream, cache_hit = await asyncio.to_thread(
            generate_pdf_report_with_cache,
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
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Buildwise-Report-Cache": "hit" if cache_hit else "miss",
            },
        )
    except Exception as e:
        logger.exception("PDF generation error")
        raise HTTPException(status_code=500, detail="An internal error occurred during PDF report generation.")

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
        logger.exception("Site vision analysis error")
        raise HTTPException(status_code=500, detail="An internal error occurred during site vision analysis.")


_BLUEPRINT_SEMAPHORE = asyncio.Semaphore(1)

# In-flight deduplication and short-lived caching for generative floorplans
_FLOORPLAN_CACHE: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
_FLOORPLAN_CACHE_LOCK = threading.Lock()
_FLOORPLAN_CACHE_TTL = 300.0  # 5 minutes
_FLOORPLAN_CACHE_MAX = 32

_IN_FLIGHT_FLOORPLANS: Dict[str, asyncio.Future] = {}
_IN_FLIGHT_LOCK = asyncio.Lock()


def _compute_floorplan_fingerprint(req: FloorPlanRequest) -> str:
    # Serialize all input parameters into a canonical sorted JSON dictionary
    data = req.model_dump(mode="json", exclude={"bypass_cache"})
    if isinstance(data.get("required_rooms"), list):
        data["required_rooms"] = sorted(data["required_rooms"])
    raw = json.dumps(data, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_rss_mb() -> float:
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
    except Exception:
        return 0.0


@app.post("/api/generate-floorplan")
async def create_generative_floorplan(
    req: FloorPlanRequest,
    format: Optional[str] = Query(default=None, description="Output format: 'json' or 'pdf'"),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
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

    req_id = f"fp_{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()
    stage = "request_received"

    logger.info(
        f"[BLUEPRINT][{req_id}] Request received: format={format or 'json'}, "
        f"typology={req.building_typology or 'default'}, floors={req.floors or 1}, "
        f"area_sqft={req.built_up_area_sqft}, rooms={len(req.required_rooms or [])}, "
        f"provider={req.ai_provider or 'default'} (rss={_get_rss_mb()}MB)"
    )

    fingerprint = _compute_floorplan_fingerprint(req) if format != "pdf" else None
    bypass = bool(req.bypass_cache) or (format == "pdf")
    leader_future: Optional[asyncio.Future] = None

    if not bypass and fingerprint:
        now = time.time()
        with _FLOORPLAN_CACHE_LOCK:
            cached_entry = _FLOORPLAN_CACHE.get(fingerprint)
            if cached_entry is not None:
                cached_time, cached_resp = cached_entry
                if now - cached_time < _FLOORPLAN_CACHE_TTL:
                    _FLOORPLAN_CACHE.move_to_end(fingerprint)
                    logger.info(f"[BLUEPRINT][{req_id}] Cache hit: returning cached blueprint (fingerprint={fingerprint[:8]})")
                    return cached_resp
                else:
                    _FLOORPLAN_CACHE.pop(fingerprint, None)

        async with _IN_FLIGHT_LOCK:
            if fingerprint in _IN_FLIGHT_FLOORPLANS:
                logger.info(f"[BLUEPRINT][{req_id}] Coalescing with in-flight generation task (fingerprint={fingerprint[:8]})")
                existing_future = _IN_FLIGHT_FLOORPLANS[fingerprint]
            else:
                existing_future = None
                loop = asyncio.get_running_loop()
                leader_future = loop.create_future()
                _IN_FLIGHT_FLOORPLANS[fingerprint] = leader_future

        if existing_future is not None:
            return await asyncio.shield(existing_future)

    try:
        stage = "validation"
        logger.info(f"[BLUEPRINT][{req_id}] Input validation completed (rss={_get_rss_mb()}MB)")
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
            _stable_seed = str(req.multi_storey.seed if req.multi_storey else "GEN-F01")
            mock_analysis = {
                "request_id": f"BW-FP-{_stable_seed}",
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
            _cache_key_data = {
                key: value for key, value in mock_analysis.items()
                if key not in ("request_id", "timestamp")
            }
            pdf_stream, cache_hit = await asyncio.to_thread(
                generate_pdf_report_with_cache,
                mock_analysis,
                floor_plan=fp_payload,
                dossier_only=True,
                include_construction_schedules=True,
                cache_key_data=_cache_key_data,
            )
            return StreamingResponse(
                pdf_stream,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": 'attachment; filename="BuildWise_Architectural_Floorplan_Dossier.pdf"',
                    "X-Buildwise-Report-Cache": "hit" if cache_hit else "miss",
                },
            )

        # Pre-compute or resolve RoomProgram via LLM before solver execution if not provided
        if req.room_program is None:
            stage = "ai_room_program"
            t_ai_start = time.perf_counter()
            typology = req.building_typology or "residential_single"
            grade = req.quality_grade or "standard"
            storeys = req.floors or 1
            coverage = req.ground_coverage_ratio or 0.60
            built_up_area = req.built_up_area_sqft or ((req.plot_width_m or 10.0) * (req.plot_depth_m or 12.0) * 10.764 * coverage)
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
            resolver = ExecutionResolver()
            plan = resolver.resolve_plan(current_user, req.ai_provider, getattr(req, "ai_model", None))
            logger.info(f"[BLUEPRINT][{req_id}] AI room program resolution started: provider={plan.provider}, model={plan.model}")
            prog, prog_source = await generate_room_program(
                params,
                provider=plan.provider,
                api_key=plan.api_key,
                model=plan.model,
                base_url=plan.base_url,
            )
            ai_duration_ms = (time.perf_counter() - t_ai_start) * 1000
            logger.info(
                f"[BLUEPRINT][{req_id}] AI room program resolution completed: "
                f"{len(prog.rooms)} rooms resolved from source='{prog_source}' in {ai_duration_ms:.1f}ms (rss={_get_rss_mb()}MB)"
            )
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

        stage = "geometry_calculation"
        logger.info(f"[BLUEPRINT][{req_id}] Geometry calculations started (concurrency lock acquired, rss={_get_rss_mb()}MB)")
        t_solve_start = time.perf_counter()

        await asyncio.sleep(0)  # Yield execution slice to event loop for /health checks
        try:
            async with asyncio.timeout(45.0):
                async with _BLUEPRINT_SEMAPHORE:
                    from app.services.floorplan.strategy_escalation import solve_with_escalation
                    response = await asyncio.wait_for(
                        asyncio.to_thread(solve_with_escalation, req),
                        timeout=35.0,
                    )
        except (asyncio.TimeoutError, TimeoutError):
            duration_s = time.perf_counter() - t_solve_start
            logger.error(f"[BLUEPRINT][{req_id}] Geometry calculations timed out after {duration_s:.1f}s (rss={_get_rss_mb()}MB)")
            raise HTTPException(
                status_code=504,
                detail="Floor plan generation timed out on server (exceeded 35s limit). Please simplify constraints or select a different typology.",
            )
        await asyncio.sleep(0)  # Yield execution slice again

        solve_duration_ms = (time.perf_counter() - t_solve_start) * 1000

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

        logger.info(
            f"[BLUEPRINT][{req_id}] Geometry calculations completed: "
            f"status={response.status}, verdict={response.plan_verdict or 'N/A'}, "
            f"duration={solve_duration_ms:.1f}ms (rss={_get_rss_mb()}MB)"
        )

        if format == "pdf":
            stage = "pdf_export"
            # Stream architectural multi-page PDF dossier directly
            typ_label = (req.building_typology or "Architectural").replace("_", " ").title()
            _generated_ms = getattr(response, "generated_at", None)
            _issued = (
                datetime.fromtimestamp(float(_generated_ms) / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                if isinstance(_generated_ms, (int, float)) and not isinstance(_generated_ms, bool)
                else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            )
            mock_analysis = {
                "request_id": f"BW-FP-{getattr(response, 'generation_id', None) or 'DRAFT'}",
                "timestamp": _issued,
                # Use the caller's actual site coordinates when provided.
                "coordinates": {"latitude": req.latitude if req.latitude is not None else 0.0, "longitude": req.longitude if req.longitude is not None else 0.0},
                "formatted_address": (
                    f"{typ_label} Floor Plan Dossier"
                    + (f" (WGS84 {req.latitude:.5f}, {req.longitude:.5f})" if req.latitude is not None and req.longitude is not None else "")
                ),
                "overall_suitability_score": 90.0,
                "suitability_verdict": "Architectural Design Complete",
                "built_up_area_sqft": req.built_up_area_sqft or ((req.plot_width_m or 10.0) * (req.plot_depth_m or 12.0) * 10.764 * (req.ground_coverage_ratio or 0.6)),
                "quality_grade": req.quality_grade or "standard",
                "floors": req.floors or 1,
                "building_typology": req.building_typology or "residential_single",
                "plot_width_m": req.plot_width_m,
                "plot_depth_m": req.plot_depth_m,
                "seed": str(getattr(response, "seed", None) or (response.multi_storey.seed if response.multi_storey else "GEN-F01")),
                "engineering_summary": req.client_notes or f"Autonomous architectural spatial allocation generated by BuildWise CF-HSA Multi-Storey Solver for {typ_label}.",
            }
            _cache_key_data = {
                key: value for key, value in mock_analysis.items()
                if key not in ("request_id", "timestamp")
            }
            pdf_stream, cache_hit = await asyncio.to_thread(
                generate_pdf_report_with_cache,
                mock_analysis,
                floor_plan=response.model_dump(),
                dossier_only=True,
                include_construction_schedules=True,
                cache_key_data=_cache_key_data,
            )
            total_duration_ms = (time.perf_counter() - t0) * 1000
            logger.info(f"[BLUEPRINT][{req_id}] Response successfully returned (PDF): total_duration={total_duration_ms:.1f}ms (rss={_get_rss_mb()}MB)")
            return StreamingResponse(
                pdf_stream,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": 'attachment; filename="BuildWise_Architectural_Floorplan_Dossier.pdf"',
                    "X-Buildwise-Report-Cache": "hit" if cache_hit else "miss",
                },
            )

        # Cache result and resolve leader future for coalesced requests
        if fingerprint and not bypass:
            with _FLOORPLAN_CACHE_LOCK:
                _FLOORPLAN_CACHE[fingerprint] = (time.time(), response)
                _FLOORPLAN_CACHE.move_to_end(fingerprint)
                while len(_FLOORPLAN_CACHE) > _FLOORPLAN_CACHE_MAX:
                    _FLOORPLAN_CACHE.popitem(last=False)
            async with _IN_FLIGHT_LOCK:
                f = _IN_FLIGHT_FLOORPLANS.pop(fingerprint, None)
                if f is not None and not f.done():
                    f.set_result(response)

        total_duration_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"[BLUEPRINT][{req_id}] Response successfully returned: total_duration={total_duration_ms:.1f}ms (rss={_get_rss_mb()}MB)")
        return response
    except HTTPException as e:
        if fingerprint:
            async with _IN_FLIGHT_LOCK:
                f = _IN_FLIGHT_FLOORPLANS.pop(fingerprint, None)
                if f is not None and not f.done():
                    f.set_exception(e)
        raise
    except DesignInfeasibleError as e:
        if fingerprint:
            async with _IN_FLIGHT_LOCK:
                f = _IN_FLIGHT_FLOORPLANS.pop(fingerprint, None)
                if f is not None and not f.done():
                    f.set_exception(e)
        logger.warning(f"[BLUEPRINT][{req_id}] Design infeasible at stage '{stage}': [{e.code}] {e.reason}")
        raise HTTPException(
            status_code=422,
            detail=f"Floor plan design infeasible [{e.code}]: {e.reason}",
        )
    except ValueError as e:
        if fingerprint:
            async with _IN_FLIGHT_LOCK:
                f = _IN_FLIGHT_FLOORPLANS.pop(fingerprint, None)
                if f is not None and not f.done():
                    f.set_exception(e)
        msg = str(e)
        logger.warning(f"[BLUEPRINT][{req_id}] Constraint/validation error at stage '{stage}': {msg}")
        if "Hard Constraint Violation" in msg or "RULE-FP-" in msg:
            raise HTTPException(status_code=422, detail=f"Floor plan constraint violation: {msg}")
        logger.exception(f"[BLUEPRINT][{req_id}] Floor plan generation invalid value error at stage '{stage}'")
        raise HTTPException(status_code=500, detail="An internal error occurred during floor plan generation.")
    except Exception as e:
        if fingerprint:
            async with _IN_FLIGHT_LOCK:
                f = _IN_FLIGHT_FLOORPLANS.pop(fingerprint, None)
                if f is not None and not f.done():
                    f.set_exception(e)
        logger.exception(f"[BLUEPRINT][{req_id}] Floor plan generation unexpected error at stage '{stage}': {e}")
        raise HTTPException(status_code=500, detail="An internal error occurred during floor plan generation.")


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
        logger.exception("Remediation dry-run failed")
        raise HTTPException(status_code=500, detail="An internal error occurred during remediation dry-run.")


@app.post("/api/floorplan/advisory")
async def floorplan_advisory(
    req: AdvisoryIn,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
):
    """Advisory narrative for the plan's blocking reasons and measured options.

    Labelled ``advisory_non_certified``; cached per plan hash; on timeout or a
    missing key it returns ``narrative=None`` and a disclosed reason so the
    deterministic summary stands alone.
    """
    from app.ai.floorplan_advisor import advise
    resolver = ExecutionResolver()
    plan = resolver.resolve_plan(current_user, req.provider)

    try:
        return await advise(req, api_key=plan.api_key)
    except Exception as exc:  # noqa: BLE001 - the advisor must never break the plan
        logger.warning(f"Floorplan advisor failed: {exc}")
        from app.schemas.remediation import AdvisoryMeta, AdvisoryOut

        return AdvisoryOut(
            narrative=None,
            meta=AdvisoryMeta(
                provider_requested=plan.provider,
                provider_used="deterministic_only",
                fallback_reason=f"advisor error: {str(exc)[:120]}",
            ),
        )


@app.post("/api/floorplan/ai-analysis", response_model=BlueprintAIAnalysisResponse)
async def analyze_blueprint_warnings_endpoint(
    req: BlueprintAIAnalysisRequest,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    """
    AI-powered plan warning analysis and architectural review.
    Categorizes technical solver warnings into 7 standard categories, explains root causes,
    groups interrelated issues, and provides prioritized action recommendations.
    Supports BYOK AI providers with instant deterministic fallback.
    """
    from app.services.blueprint_ai_advisor import BlueprintAIAdvisorService
    service = BlueprintAIAdvisorService()
    return await service.analyze_blueprint(req, user=current_user)


class ParseRequirementsRequest(BaseModel):
    requirements_text: str
    ai_provider: Optional[str] = "groq"
    ai_model: Optional[str] = None


@app.post("/api/parse-requirements", response_model=ExtractedClientConstraints)
async def parse_requirements_endpoint(
    req: ParseRequirementsRequest,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user)
):
    """
    Extracts structured architectural design constraints from free-text client notes.
    """
    try:
        resolver = ExecutionResolver()
        plan = resolver.resolve_plan(current_user, req.ai_provider, req.ai_model)
        from app.ai.requirements_parser import parse_client_requirements
        return await parse_client_requirements(
            req.requirements_text,
            ai_provider=plan.provider,
            api_key=plan.api_key,
            model=plan.model
        )
    except Exception as e:
        logger.warning(f"Error parsing requirements: {e}")
        from app.ai.requirements_parser import parse_client_requirements_fallback
        return parse_client_requirements_fallback(req.requirements_text)


# ============================================================================
# Project Feasibility Study Persistence Endpoints (SQLite)
# ============================================================================
from app.schemas.project import (  # noqa: E402
    ProjectCreate,
    ProjectDetail,
    ProjectListResponse,
    ProjectUpdate,
)
from app.db import ProjectRepository  # noqa: E402

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(ai_router)


@app.get("/api/auth/me")
async def get_my_profile(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Return the profile of the verified authenticated user."""
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "email_verified": current_user.email_verified,
        "image": current_user.image,
    }


@app.post("/api/projects", response_model=ProjectDetail, status_code=201)
async def create_project(
    project: ProjectCreate,
    overwrite: bool = Query(default=False),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Save an analysis session as a named project study owned by the authenticated user."""
    try:
        return await asyncio.to_thread(
            ProjectRepository.create,
            project,
            user_id=current_user.id,
            overwrite=overwrite,
        )
    except HTTPException:
        raise
    except ValueError as e:
        msg = str(e)
        if msg.startswith("PROJECT_EXISTS:"):
            parts = msg.split(":", 2)
            existing_id = parts[1]
            existing_name = parts[2] if len(parts) > 2 else project.name
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROJECT_NAME_EXISTS",
                    "message": f"A study named '{existing_name}' already exists in your account.",
                    "existing_id": existing_id,
                },
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Failed to create project")
        raise HTTPException(status_code=500, detail="Failed to save project study.")


@app.put("/api/projects/{project_id}", response_model=ProjectDetail)
async def overwrite_project(
    project_id: str,
    project: ProjectCreate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Overwrite an existing project study with updated parameters and analysis."""
    try:
        updated = await asyncio.to_thread(
            ProjectRepository.overwrite,
            project_id,
            project,
            user_id=current_user.id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Project not found.")
        return updated
    except HTTPException:
        raise
    except ValueError as e:
        msg = str(e)
        if msg.startswith("PROJECT_EXISTS:"):
            parts = msg.split(":", 2)
            existing_id = parts[1]
            existing_name = parts[2] if len(parts) > 2 else project.name
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROJECT_NAME_EXISTS",
                    "message": f"A study named '{existing_name}' already exists in your account.",
                    "existing_id": existing_id,
                },
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Failed to overwrite project")
        raise HTTPException(status_code=500, detail="Failed to overwrite project study.")


@app.get("/api/projects", response_model=ProjectListResponse)
async def list_projects(
    bookmarked: bool = Query(default=False),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """List saved projects owned by the authenticated user with optional bookmark filtering and keyword search."""
    try:
        items, total = await asyncio.to_thread(
            ProjectRepository.list,
            user_id=current_user.id,
            bookmarked_only=bookmarked,
            search=search,
            limit=limit,
            offset=offset,
        )
        return ProjectListResponse(items=items, total=total)
    except Exception:
        logger.exception("Failed to list projects")
        raise HTTPException(status_code=500, detail="Failed to retrieve projects.")


@app.get("/api/projects/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Retrieve full details of a saved project study owned by the authenticated user (IDOR protected)."""
    project = await asyncio.to_thread(ProjectRepository.get_by_id, project_id, user_id=current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@app.patch("/api/projects/{project_id}", response_model=ProjectDetail)
async def update_project(
    project_id: str,
    patch: ProjectUpdate,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Update project metadata or toggle bookmark on an owned project (IDOR protected)."""
    try:
        project = await asyncio.to_thread(
            ProjectRepository.update,
            project_id,
            patch,
            user_id=current_user.id,
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found.")
        return project
    except HTTPException:
        raise
    except ValueError as e:
        msg = str(e)
        if msg.startswith("PROJECT_EXISTS:"):
            parts = msg.split(":", 2)
            existing_id = parts[1]
            existing_name = parts[2] if len(parts) > 2 else patch.name
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROJECT_NAME_EXISTS",
                    "message": f"A study named '{existing_name}' already exists in your account.",
                    "existing_id": existing_id,
                },
            )
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/projects/{project_id}")
async def delete_project(
    project_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Delete a saved project study owned by the authenticated user (IDOR protected)."""
    deleted = await asyncio.to_thread(ProjectRepository.delete, project_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"status": "deleted", "id": project_id}


@app.get("/api/projects/{project_id}/report")
async def export_project_report(
    project_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Export a high-resolution PDF feasibility report for an owned project (IDOR protected)."""
    project = await asyncio.to_thread(ProjectRepository.get_by_id, project_id, user_id=current_user.id)
    if not project or not project.analysis_data:
        raise HTTPException(status_code=404, detail="Project not found or lacks analysis data.")

    try:
        pdf_stream, cache_hit = await asyncio.to_thread(
            generate_pdf_report_with_cache,
            project.analysis_data,
            site_vision=project.site_vision_data,
            floor_plan=project.floor_plan_data,
        )
        safe_name = "".join(c for c in project.name if c.isalnum() or c in ("-", "_")).strip() or "Report"
        filename = f"BuildWise_{safe_name}.pdf"
        return StreamingResponse(
            pdf_stream,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Buildwise-Report-Cache": "hit" if cache_hit else "miss",
            },
        )
    except Exception:
        logger.exception("Project PDF generation error")
        raise HTTPException(status_code=500, detail="Failed to generate project PDF report.")


