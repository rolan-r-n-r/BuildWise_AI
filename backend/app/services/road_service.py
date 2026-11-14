"""
Road service — shared Overpass nearest-road capability.
================================================================
Extracted from vastu_service: the Overpass query, cache,
rate-limit, and honest offline fallback now live in ONE place so both the
vastu advisory and the public /api/nearest-road proxy consume the same
implementation.

Policy compliance (mirrors geocode_service):
- Overpass API: server-side <=1 req/s throttle, identifying User-Agent, and a
  timeout budget ordered so the SERVER gives up before the client does.
  Ref: https://operations.osmfoundation.org/policies/overpass/ (be
  nice: cache aggressively; this service answers from cache when possible).
- Results cached in the 24h hazard cache keyed on a rounded coordinate grid
  (category/precision chosen by the caller).
- AMENDMENT 1 (no fabricated geometry): when Overpass is unreachable or
  returns nothing usable, the fallback NEVER synthesizes a bearing. It
  returns is_fallback=True, bearing_degrees=None, approach_side='unknown'
  and provenance annotation 'ASSUMED' with a user-facing warning.
- Attribution: OpenStreetMap contributors (ODbL), via Overpass API.

Timeout budget (regression pin — see _ATTEMPT_READ_TIMEOUT_S ordering):
the previous client timeout (3.5 s, equal to the query's own `[timeout:4]`)
was SHORTER than a normal Overpass answer, so every lookup aborted
client-side and degraded to ASSUMED even while Overpass was healthy. The
budget below keeps `QL_TIMEOUT < client read timeout` (the server answers
with its own 504 instead of the client timing out blind) and caps the whole
lookup with a wall-clock deadline so a slow upstream cannot stall the
frontage step indefinitely.
"""

import asyncio
import time
import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from app.utils.cache_utils import hazard_cache
from app.utils.geo_utils import (
    haversine_distance,
    calculate_bearing,
    azimuth_to_cardinal_8,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
#  Constants                                                                   #
# --------------------------------------------------------------------------- #

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_OVERPASS_UA = "BuildWise-Civil-Engineering-Engine/1.2"
_RATE_INTERVAL = 1.0     # minimum seconds between Overpass calls (<=1 req/s)
_QUERY_RADIUS_M = 500

# Vehicular road classes we score frontage from. Filtered CLIENT-SIDE on
# purpose: a `[highway~"^(primary|...)$"]` regex filter makes Overpass scan
# every road in the area instead of using its tag index, which measurably
# pushes the public instance past its own query budget (measured 2026-10-14:
# regex filter -> 3/3 responses 504 at 6.3-9.3 s; plain `[highway]` tag filter
# -> 200 in 3.9-5.1 s returning 362 ways).
_ROAD_CLASSES = frozenset({"primary", "secondary", "tertiary", "residential", "service"})

# Timeout budget. Invariant: _QL_TIMEOUT_S < _ATTEMPT_READ_TIMEOUT_S, i.e. the
# server-side query budget expires first and Overpass answers us with an
# explicit 504 (which we log and retry) instead of the client aborting a query
# the server is still working on (which surfaces as a message-less
# httpx.ReadTimeout — the "query failed:" with nothing after it).
_QL_TIMEOUT_S = 7.0             # [timeout:...] inside the Overpass QL
_ATTEMPT_READ_TIMEOUT_S = 9.0   # per-attempt client read timeout (backstop)
_ATTEMPT_CONNECT_TIMEOUT_S = 3.0
_ATTEMPT_WRITE_TIMEOUT_S = 5.0
_TOTAL_BUDGET_S = 17.0          # wall-clock ceiling for the whole lookup
_MAX_ATTEMPTS = 2               # the public instance 504s are usually transient
# A retry only earns its own server window plus slack; below this the attempt
# would be cut short by the deadline and the retry would be wasted.
_MIN_RETRY_BUDGET_S = _QL_TIMEOUT_S + 1.5

# Overpass outages arrive in bursts (the public instance answers 429/504 for
# minutes at a time). A failed lookup already costs up to _TOTAL_BUDGET_S, and
# the frontage step would pay that again on every pin/edge change, so a short
# cooldown answers those calls instantly with the SAME honest ASSUMED fallback
# they would have reached anyway - and spares the upstream while it recovers.
_FAILURE_COOLDOWN_S = 30.0
# Retryable upstream statuses. The public instance answers 429 when we exceed
# its slot budget and 504 when its own query timeout fires; both clear on a
# second attempt. Other 4xx mean OUR query is wrong — retrying is pointless.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Cache categories:
# - vastu path preserves its historical 0.1-deg (~11 km) grid behaviour;
# - the /api/nearest-road proxy uses a 1e-4 deg (~11 m) grid so neighbouring
#   pins get honest per-location answers instead of an 11 km-shared guess.
VASTU_CACHE_CATEGORY = "osm_road_approach"
VASTU_CACHE_PRECISION = 1
PROXY_CACHE_CATEGORY = "nearest_road"
PROXY_CACHE_PRECISION = 4


# --------------------------------------------------------------------------- #
#  Overpass throttle: asyncio lock + timestamp (1 req/s)                      #
# --------------------------------------------------------------------------- #

_overpass_lock = asyncio.Lock()
_overpass_last_call: float = 0.0

# Monotonic deadline until which we treat Overpass as unhealthy (see
# _FAILURE_COOLDOWN_S). Cleared by the next successful lookup.
_upstream_down_until: float = 0.0


def _upstream_cooldown_remaining() -> float:
    return max(_upstream_down_until - time.monotonic(), 0.0)


def _mark_upstream_healthy() -> None:
    global _upstream_down_until
    _upstream_down_until = 0.0


def _mark_upstream_failed() -> None:
    global _upstream_down_until
    _upstream_down_until = time.monotonic() + _FAILURE_COOLDOWN_S


_UNAVAILABLE_WARNING = (
    "Road network telemetry unavailable. Confirm the frontage edge manually - "
    "no bearing has been assumed."
)


async def _overpass_throttle() -> None:
    """
    Ensures at most 1 Overpass call per second (shared across the app).

    The steady-state wait happens OUTSIDE the lock so
    concurrent callers do not serialize behind a sleep; the lock only guards
    the timestamp stamp itself (with a final re-check for racing callers).

    A retry therefore waits out the remainder of the 1 s slot before it
    re-posts, which is the policy-correct backoff for this upstream.
    """
    global _overpass_last_call
    now = time.monotonic()
    wait = _RATE_INTERVAL - (now - _overpass_last_call)
    if wait > 0:
        await asyncio.sleep(wait)

    async with _overpass_lock:
        now = time.monotonic()
        if now - _overpass_last_call < _RATE_INTERVAL:
            await asyncio.sleep(_RATE_INTERVAL - (now - _overpass_last_call))
        _overpass_last_call = time.monotonic()


# --------------------------------------------------------------------------- #
#  Core query                                                                  #
# --------------------------------------------------------------------------- #

def _build_query(lat: float, lon: float) -> str:
    """Index-driven Overpass QL: tag filter (not regex), geometry inline."""
    return (
        f"[out:json][timeout:{int(_QL_TIMEOUT_S)}];"
        f"way[\"highway\"](around:{_QUERY_RADIUS_M},{lat:.5f},{lon:.5f});"
        f"out geom;"
    )


def _is_road_way(tags: Dict[str, Any]) -> bool:
    """True when an element carries one of the vehicular classes we score."""
    highway = tags.get("highway")
    if not isinstance(highway, str):
        return False
    # Compound values ("residential;service") are legal in OSM.
    return any(part.strip() in _ROAD_CLASSES for part in highway.split(";"))


def _describe_failure(exc: BaseException) -> str:
    """
    Actionable one-line label for an upstream failure.

    httpx timeout exceptions stringify to '' (ReadTimeout('')), which is why
    this used to log as a bare "Overpass nearest-road query failed:" with no
    cause attached. The exception TYPE is the useful half, so it is always
    included.
    """
    detail = str(exc).strip() or "no message"
    return f"{type(exc).__name__}: {detail}"


async def _post_query(query: str, read_timeout: float) -> httpx.Response:
    """Single Overpass POST with the per-attempt connect/read budget."""
    timeout = httpx.Timeout(
        connect=_ATTEMPT_CONNECT_TIMEOUT_S,
        read=read_timeout,
        write=_ATTEMPT_WRITE_TIMEOUT_S,
        pool=_ATTEMPT_CONNECT_TIMEOUT_S,
    )
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(
            OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": _OVERPASS_UA},
        )


def _fallback_result(warning: str) -> Dict[str, Any]:
    """AMENDMENT 1: explicit unknown fallback - never a synthesized bearing."""
    return {
        "bearing_degrees": None,
        "approach_side": "unknown",
        "distance_meters": None,
        "nearest_point": None,
        "highway_class": None,
        "road_name": None,
        "is_fallback": True,
        "source": "assumed_fallback",
        "annotation": "ASSUMED",
        "warning": warning,
    }


def _parse_overpass_elements(data: Dict[str, Any], lat: float, lon: float) -> Optional[Dict[str, Any]]:
    """Finds the closest highway geometry vertex; None when nothing usable."""
    closest_pt = None
    min_dist_m = float("inf")
    closest_tags: Dict[str, Any] = {}

    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        if not _is_road_way(tags):
            continue
        for pt in el.get("geometry", []) or []:
            pt_lat = pt.get("lat")
            pt_lon = pt.get("lon")
            if pt_lat is None or pt_lon is None:
                continue
            d = haversine_distance(lat, lon, pt_lat, pt_lon)
            if d < min_dist_m:
                min_dist_m = d
                closest_pt = (pt_lat, pt_lon)
                closest_tags = tags

    if closest_pt is None:
        return None

    bearing = round(calculate_bearing(lat, lon, closest_pt[0], closest_pt[1]), 1)
    return {
        "bearing_degrees": bearing,
        "approach_side": azimuth_to_cardinal_8(bearing),
        "distance_meters": round(min_dist_m, 1),
        "nearest_point": {"lat": round(closest_pt[0], 6), "lon": round(closest_pt[1], 6)},
        "highway_class": closest_tags.get("highway"),
        "road_name": closest_tags.get("name"),
        "is_fallback": False,
        "source": "osm_overpass",
        "annotation": "VERIFIED",
        "warning": None,
    }


async def fetch_nearest_road(
    lat: float,
    lon: float,
    *,
    cache_category: str = PROXY_CACHE_CATEGORY,
    cache_precision: int = PROXY_CACHE_PRECISION,
) -> Tuple[Dict[str, Any], bool, Optional[str]]:
    """
    Nearest OSM road within the query radius, honouring cache + rate policy.

    Returns (result, cache_hit, warning) where *result* is a plain dict with
    keys: bearing_degrees, approach_side, distance_meters, nearest_point,
    highway_class, road_name, is_fallback, source, annotation, warning.
    Never raises; unreachable upstream degrades to the ASSUMED fallback.

    The lookup is bounded by _TOTAL_BUDGET_S: up to _MAX_ATTEMPTS POSTs (a
    transient Overpass 429/504 is retried once, spaced by the 1 req/s
    throttle) and the per-attempt read timeout is trimmed to whatever budget
    is left, so the frontage step degrades predictably instead of hanging.
    """
    cached = hazard_cache.get(lat, lon, cache_category, precision=cache_precision)
    if cached is not None:
        return dict(cached), True, None

    # Upstream known-bad right now: answer instantly and honestly rather than
    # spending the whole budget to reach the identical fallback.
    cooldown_left = _upstream_cooldown_remaining()
    if cooldown_left > 0:
        logger.info(
            "Overpass nearest-road lookup skipped: upstream cooldown active (%.0fs left)",
            cooldown_left,
        )
        return _fallback_result(_UNAVAILABLE_WARNING), False, _UNAVAILABLE_WARNING

    query = _build_query(lat, lon)
    deadline = time.monotonic() + _TOTAL_BUDGET_S
    attempts = 0
    failure: Optional[str] = None
    # True only for failures that say "the upstream is unwell" (transport error,
    # 429/5xx, unparseable body). A 4xx means OUR query is wrong, so it must
    # not open the outage cooldown and mask the next (correct) lookup.
    outage = False

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        remaining = deadline - time.monotonic()
        if attempt > 1 and remaining < _MIN_RETRY_BUDGET_S:
            logger.warning(
                "Overpass nearest-road retry skipped: %.1fs of budget left (< %.1fs)",
                max(remaining, 0.0), _MIN_RETRY_BUDGET_S,
            )
            break
        if remaining <= 0:
            break

        started = time.monotonic()
        try:
            await _overpass_throttle()
            # Trim the read timeout to the remaining budget (never below 1 s so
            # httpx still gets a usable timeout object). _MIN_RETRY_BUDGET_S
            # guarantees this stays above the server-side window.
            read_timeout = min(_ATTEMPT_READ_TIMEOUT_S, max(deadline - started, 1.0))
            resp = await _post_query(query, read_timeout)
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            attempts += 1
            outage = True
            failure = _describe_failure(exc)
            logger.warning(
                "Overpass nearest-road query failed (attempt %d/%d, %.1fs): %s",
                attempt, _MAX_ATTEMPTS, time.monotonic() - started, failure,
            )
            continue

        attempts += 1
        elapsed = time.monotonic() - started

        if resp.status_code == 200:
            try:
                parsed = _parse_overpass_elements(resp.json(), lat, lon)
            except Exception as exc:  # noqa: BLE001 - malformed upstream body
                outage = True
                failure = f"unparseable response ({_describe_failure(exc)})"
                logger.warning(
                    "Overpass nearest-road query failed (attempt %d/%d, %.1fs): %s",
                    attempt, _MAX_ATTEMPTS, elapsed, failure,
                )
                continue

            if parsed is not None:
                hazard_cache.set(lat, lon, cache_category, parsed, precision=cache_precision)
                _mark_upstream_healthy()
                return parsed, False, None

            # Reachable but no highway in radius: honest empty answer.
            warning = (
                f"No mapped road within {_QUERY_RADIUS_M} m in OpenStreetMap. "
                "Confirm the frontage edge manually."
            )
            fallback = _fallback_result(warning)
            hazard_cache.set(lat, lon, cache_category, fallback, precision=cache_precision)
            _mark_upstream_healthy()
            return fallback, False, warning

        failure = f"HTTP {resp.status_code}"
        logger.warning(
            "Overpass nearest-road query failed (attempt %d/%d, %.1fs): %s",
            attempt, _MAX_ATTEMPTS, elapsed, failure,
        )
        # A retryable status IS an outage: 429/5xx come from the public instance
        # refusing or timing out our slot, not from our query.  This used to stay
        # False (only the transport-error branch set it), so a 502 opened no
        # cooldown and the NEXT lookup - every pin move, every re-analysis -
        # paid the full ~10 s timeout again to reach the same ASSUMED fallback.
        # Measured before the fix: two consecutive analyses both burned the whole
        # read budget on a 502; the cooldown never engaged.
        outage = resp.status_code in _RETRYABLE_STATUS
        if not outage:
            break  # 4xx (other than 429): the query itself is wrong, not the weather

    if failure:
        logger.warning(
            "Overpass nearest-road lookup giving up after %d attempt(s) (last: %s)%s",
            attempts, failure,
            f"; upstream cooldown for the next {_FAILURE_COOLDOWN_S:.0f}s" if outage else "",
        )
    if outage:
        _mark_upstream_failed()

    return _fallback_result(_UNAVAILABLE_WARNING), False, _UNAVAILABLE_WARNING


async def fetch_facility_count(lat: float, lon: float) -> Tuple[Optional[int], bool]:
    """
    Queries OpenStreetMap Overpass for count of civic facilities (amenities) within 1500m.
    Returns (count, is_fallback). Returns (None, True) on upstream outage or timeout.
    """
    cache_cat = "osm_facility_count"
    cached = hazard_cache.get(lat, lon, cache_cat, precision=2)
    if cached is not None:
        return cached, False

    if _upstream_cooldown_remaining() > 0.0:
        return None, True

    query = (
        f"[out:json][timeout:{int(_QL_TIMEOUT_S)}];"
        f"(node[\"amenity\"](around:1500,{lat:.5f},{lon:.5f});"
        f"way[\"amenity\"](around:1500,{lat:.5f},{lon:.5f}););"
        f"out count;"
    )
    try:
        await _overpass_throttle()
        resp = await _post_query(query, _ATTEMPT_READ_TIMEOUT_S)
        if resp.status_code == 200:
            data = resp.json()
            count_val = None
            elements = data.get("elements", [])
            for el in elements:
                if el.get("type") == "count":
                    count_val = int(el.get("tags", {}).get("total", 0))
                    break
            if count_val is None:
                count_val = len(elements)
            hazard_cache.set(lat, lon, cache_cat, count_val, precision=2)
            _mark_upstream_healthy()
            return count_val, False
    except Exception as exc:
        logger.debug("Overpass facility query failed: %s", exc)

    return None, True

