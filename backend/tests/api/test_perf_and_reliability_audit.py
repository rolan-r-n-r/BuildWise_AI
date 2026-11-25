import asyncio
import time
from fastapi.testclient import TestClient
from app.main import app, _compute_floorplan_fingerprint, _FLOORPLAN_CACHE, _FLOORPLAN_CACHE_LOCK
from app.schemas.floorplan import FloorPlanRequest
from app.auth.dependencies import (
    verify_session_token,
    invalidate_session_cache,
    _SESSION_CACHE,
    _SESSION_CACHE_LOCK,
)
from app.auth.models import AuthenticatedUser
from app.db.database import _PgPool, get_connection


def test_readiness_probe_success():
    """Verify that /ready and /api/ready return 200 and healthy database status."""
    client = TestClient(app)
    r1 = client.get("/ready")
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["status"] == "ready"
    assert data1["database"] == "connected"

    r2 = client.get("/api/ready")
    assert r2.status_code == 200
    assert r2.json() == data1


def test_session_verification_caching():
    """Verify that verified sessions are cached in-memory and invalidated cleanly."""
    invalidate_session_cache()
    test_token = "audit-test-session-token-abc-123"
    test_user = AuthenticatedUser(
        id="usr_audit_test",
        name="Audit Test User",
        email="audit@example.com",
        email_verified=True,
        image=None,
        session_id="sess_audit_test",
        token=test_token,
    )

    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE[test_token] = (time.time(), test_user)

    # First lookup should hit in-memory cache directly without requiring DB
    cached = verify_session_token(test_token, db_path=None)
    assert cached is not None
    assert cached.id == "usr_audit_test"
    assert cached.email == "audit@example.com"

    # Invalidate specific token
    invalidate_session_cache(test_token)
    with _SESSION_CACHE_LOCK:
        assert test_token not in _SESSION_CACHE


def test_floorplan_fingerprinting_determinism():
    """Verify that request fingerprinting is deterministic and insensitive to dict ordering."""
    req1 = FloorPlanRequest(
        building_typology="residential_single",
        floors=1,
        built_up_area_sqft=2000.0,
        quality_grade="standard",
        required_rooms=["Living Room", "Kitchen", "Master Bedroom"],
    )
    req2 = FloorPlanRequest(
        building_typology="residential_single",
        floors=1,
        built_up_area_sqft=2000.0,
        quality_grade="standard",
        required_rooms=["Master Bedroom", "Kitchen", "Living Room"],  # Re-ordered
    )
    fp1 = _compute_floorplan_fingerprint(req1)
    fp2 = _compute_floorplan_fingerprint(req2)
    assert fp1 == fp2, "Fingerprints for identical floorplan requirements must be identical"

    req3 = FloorPlanRequest(
        building_typology="residential_single",
        floors=2,  # Different floors
        built_up_area_sqft=2000.0,
        quality_grade="standard",
        required_rooms=["Living Room", "Kitchen", "Master Bedroom"],
    )
    fp3 = _compute_floorplan_fingerprint(req3)
    assert fp1 != fp3, "Different requirements must produce different fingerprints"


def test_pg_pool_lifecycle():
    """Verify _PgPool basic queue mechanics and cleanup."""
    pool = _PgPool(max_size=3, connect_timeout=1)
    assert pool._current_size == 0
    pool.close_all()
    assert pool._current_size == 0
