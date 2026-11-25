import os
import tempfile
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.db.database import init_db, get_connection


@pytest.fixture
def multi_user_env():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    orig_path = settings.DATABASE_PATH
    settings.DATABASE_PATH = path
    init_db(db_path=path)

    now = datetime.now(timezone.utc)
    future = now + timedelta(days=7)
    past = now - timedelta(days=1)

    now_str = now.isoformat()
    future_str = future.isoformat()
    past_str = past.isoformat()

    # Seed User A and User B
    with get_connection(path) as conn:
        # User A
        conn.execute(
            "INSERT INTO user (id, name, email, emailVerified, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?)",
            ("user_a", "Alice Architect", "alice@example.com", 1, now_str, now_str),
        )
        conn.execute(
            "INSERT INTO session (id, expiresAt, token, createdAt, updatedAt, userId) VALUES (?, ?, ?, ?, ?, ?)",
            ("sess_a", future_str, "token_alice_valid", now_str, now_str, "user_a"),
        )

        # User B
        conn.execute(
            "INSERT INTO user (id, name, email, emailVerified, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?)",
            ("user_b", "Bob Builder", "bob@example.com", 1, now_str, now_str),
        )
        conn.execute(
            "INSERT INTO session (id, expiresAt, token, createdAt, updatedAt, userId) VALUES (?, ?, ?, ?, ?, ?)",
            ("sess_b", future_str, "token_bob_valid", now_str, now_str, "user_b"),
        )

        # Expired Session for User A
        conn.execute(
            "INSERT INTO session (id, expiresAt, token, createdAt, updatedAt, userId) VALUES (?, ?, ?, ?, ?, ?)",
            ("sess_a_expired", past_str, "token_alice_expired", past_str, past_str, "user_a"),
        )

        conn.commit()

    with TestClient(app) as client:
        yield {
            "client": client,
            "db_path": path,
            "token_a": "token_alice_valid",
            "token_b": "token_bob_valid",
            "token_expired": "token_alice_expired",
        }

    settings.DATABASE_PATH = orig_path
    try:
        os.remove(path)
    except OSError:
        pass


def test_unauthenticated_request_rejected(multi_user_env):
    client = multi_user_env["client"]
    # Attempt to list projects with no credentials
    resp = client.get("/api/projects")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


def test_expired_session_rejected(multi_user_env):
    client = multi_user_env["client"]
    token = multi_user_env["token_expired"]
    resp = client.get("/api/projects", cookies={"better-auth.session_token": f"{token}.sig"})
    assert resp.status_code == 401
    assert "Invalid or expired session" in resp.json()["detail"]


def test_invalid_token_rejected(multi_user_env):
    client = multi_user_env["client"]
    resp = client.get("/api/projects", headers={"Authorization": "Bearer non_existent_token_12345"})
    assert resp.status_code == 401


def test_multi_user_project_and_report_isolation(multi_user_env):
    client = multi_user_env["client"]
    token_a = multi_user_env["token_a"]
    token_b = multi_user_env["token_b"]

    auth_a = {"cookies": {"better-auth.session_token": f"{token_a}.sig"}}
    auth_b = {"headers": {"Authorization": f"Bearer {token_b}"}}

    # Verify profile endpoints
    me_a = client.get("/api/auth/me", **auth_a).json()
    assert me_a["email"] == "alice@example.com"
    assert me_a["id"] == "user_a"

    me_b = client.get("/api/auth/me", **auth_b).json()
    assert me_b["email"] == "bob@example.com"
    assert me_b["id"] == "user_b"

    # Step 1: User A creates Project Alpha with report analysis data
    create_payload_a = {
        "name": "Project Alpha",
        "description": "Alice's secret villa",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "formatted_address": "Indiranagar, Bengaluru",
        "parameters": {"floors": 2, "quality_grade": "premium"},
        "analysis_data": {
            "overall_suitability_score": 85.0,
            "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
            "cost_estimate": {"total_cost_inr": 8500000.0},
        },
        "is_bookmarked": True,
    }
    resp_create_a = client.post("/api/projects", json=create_payload_a, **auth_a)
    assert resp_create_a.status_code == 201
    proj_a = resp_create_a.json()
    proj_a_id = proj_a["id"]
    assert proj_a["name"] == "Project Alpha"
    assert proj_a["user_id"] == "user_a"

    # Step 2: User B creates Project Beta
    create_payload_b = {
        "name": "Project Beta",
        "description": "Bob's commercial plaza",
        "latitude": 12.9352,
        "longitude": 77.6245,
        "formatted_address": "Koramangala, Bengaluru",
        "parameters": {"floors": 4, "building_typology": "commercial"},
        "analysis_data": {
            "overall_suitability_score": 92.0,
            "coordinates": {"latitude": 12.9352, "longitude": 77.6245},
        },
        "is_bookmarked": False,
    }
    resp_create_b = client.post("/api/projects", json=create_payload_b, **auth_b)
    assert resp_create_b.status_code == 201
    proj_b = resp_create_b.json()
    proj_b_id = proj_b["id"]
    assert proj_b["user_id"] == "user_b"

    # Step 3: Verify User B can also create a project named "Project Alpha" without collision
    # (Per-user namespace)
    resp_create_b_same_name = client.post("/api/projects", json=create_payload_a, **auth_b)
    assert resp_create_b_same_name.status_code == 201
    assert resp_create_b_same_name.json()["id"] != proj_a_id
    assert resp_create_b_same_name.json()["user_id"] == "user_b"

    # Step 4: User A lists projects -> sees ONLY User A's projects
    list_a = client.get("/api/projects", **auth_a).json()
    assert list_a["total"] == 1
    assert list_a["items"][0]["id"] == proj_a_id
    assert list_a["items"][0]["name"] == "Project Alpha"

    # User B lists projects -> sees ONLY User B's projects (2 items)
    list_b = client.get("/api/projects", **auth_b).json()
    assert list_b["total"] == 2
    b_ids = [item["id"] for item in list_b["items"]]
    assert proj_a_id not in b_ids
    assert proj_b_id in b_ids

    # Step 5: IDOR Protection — User B attempts to read User A's Project Alpha
    idor_read = client.get(f"/api/projects/{proj_a_id}", **auth_b)
    assert idor_read.status_code == 404
    assert idor_read.json()["detail"] == "Project not found."

    # Step 6: IDOR Protection — User B attempts to edit User A's Project Alpha
    idor_patch = client.patch(
        f"/api/projects/{proj_a_id}",
        json={"name": "Hacked Name", "description": "Tampered description"},
        **auth_b,
    )
    assert idor_patch.status_code == 404

    # Step 7: IDOR Protection — User B attempts to overwrite User A's Project Alpha
    idor_overwrite = client.put(f"/api/projects/{proj_a_id}", json=create_payload_b, **auth_b)
    assert idor_overwrite.status_code == 404

    # Step 8: IDOR Protection — User B attempts to delete User A's Project Alpha
    idor_del = client.delete(f"/api/projects/{proj_a_id}", **auth_b)
    assert idor_del.status_code == 404

    # Step 9: IDOR Protection — User B attempts to download report of User A's Project Alpha
    idor_report = client.get(f"/api/projects/{proj_a_id}/report", **auth_b)
    assert idor_report.status_code == 404

    # Step 10: Verify User A's project remains completely untampered and intact
    get_a = client.get(f"/api/projects/{proj_a_id}", **auth_a)
    assert get_a.status_code == 200
    detail_a = get_a.json()
    assert detail_a["name"] == "Project Alpha"
    assert detail_a["description"] == "Alice's secret villa"
    assert detail_a["is_bookmarked"] is True

    # User A can export their own report
    report_a = client.get(f"/api/projects/{proj_a_id}/report", **auth_a)
    assert report_a.status_code == 200
    assert report_a.headers["content-type"] == "application/pdf"
    assert len(report_a.content) > 1000

    # Step 11: User A deletes their project
    del_a = client.delete(f"/api/projects/{proj_a_id}", **auth_a)
    assert del_a.status_code == 200
    assert del_a.json()["status"] == "deleted"

    # User A verified 404 after deletion
    assert client.get(f"/api/projects/{proj_a_id}", **auth_a).status_code == 404


def test_auth_endpoints_full_cycle(multi_user_env):
    client = multi_user_env["client"]
    from app.auth import routes

    # 1. Sign up new user (requires email verification)
    signup_resp = client.post(
        "/api/auth/sign-up/email",
        json={
            "name": "Diana Prince",
            "email": "diana@themyscira.gov",
            "password": "AmazonianWarrior999!",
        },
    )
    assert signup_resp.status_code == 200, signup_resp.text
    signup_data = signup_resp.json()
    assert signup_data["requiresVerification"] is True
    assert signup_data["token"] is None
    assert signup_data["user"]["email"] == "diana@themyscira.gov"
    assert signup_data["user"]["emailVerified"] is False
    assert "better-auth.session_token" not in signup_resp.cookies

    # 2. Unverified sign in rejected with 403 EMAIL_NOT_VERIFIED
    unverified_login = client.post(
        "/api/auth/sign-in/email",
        json={"email": "diana@themyscira.gov", "password": "AmazonianWarrior999!"},
    )
    assert unverified_login.status_code == 403
    assert unverified_login.json()["detail"]["code"] == "EMAIL_NOT_VERIFIED"

    # 3. Inspect DB to verify verification OTP was securely generated and hashed
    with get_connection(multi_user_env["db_path"]) as conn:
        verif_row = conn.execute(
            "SELECT value FROM verification WHERE identifier = 'email-verification-otp-diana@themyscira.gov'"
        ).fetchone()
        assert verif_row is not None
        stored_hash = verif_row[0].split(":")[0]
        assert len(stored_hash) == 64
        otp = routes._test_last_otp
        assert otp is not None
        assert len(otp) == 6

    # 4. Reject bad OTP for email verification
    bad_otp_resp = client.post(
        "/api/auth/email-otp/verify-email",
        json={
            "email": "diana@themyscira.gov",
            "otp": "000000",
        },
    )
    assert bad_otp_resp.status_code == 400
    assert bad_otp_resp.json()["detail"]["code"] == "INVALID_OTP"

    # 5. Verify email with valid OTP -> establishes session and returns session cookie
    verify_resp = client.post(
        "/api/auth/email-otp/verify-email",
        json={
            "email": "diana@themyscira.gov",
            "otp": otp,
        },
    )
    assert verify_resp.status_code == 200
    verify_data = verify_resp.json()
    assert verify_data["status"] is True
    assert verify_data["user"]["emailVerified"] is True
    token = verify_data["token"]
    assert "better-auth.session_token" in verify_resp.cookies

    # 6. Replay attempt with same OTP is rejected (single-use OTP)
    replay_resp = client.post(
        "/api/auth/email-otp/verify-email",
        json={
            "email": "diana@themyscira.gov",
            "otp": otp,
        },
    )
    assert replay_resp.status_code == 400
    assert replay_resp.json()["detail"]["code"] == "INVALID_OTP"

    # 7. Duplicate registration rejected now that account is verified
    dup_resp = client.post(
        "/api/auth/sign-up/email",
        json={
            "name": "Diana Clone",
            "email": "diana@themyscira.gov",
            "password": "DifferentPass999!",
        },
    )
    assert dup_resp.status_code == 422

    # 8. Get session now works and shows verified user
    sess_resp = client.get("/api/auth/get-session", cookies={"better-auth.session_token": token})
    assert sess_resp.status_code == 200
    sess_data = sess_resp.json()
    assert sess_data["user"]["name"] == "Diana Prince"
    assert sess_data["user"]["emailVerified"] is True

    # 9. Sign in with bad password
    bad_login = client.post(
        "/api/auth/sign-in/email",
        json={"email": "diana@themyscira.gov", "password": "WrongPassword!"},
    )
    assert bad_login.status_code == 401

    # 10. Sign in with correct password succeeds now that account is verified
    good_login = client.post(
        "/api/auth/sign-in/email",
        json={"email": "diana@themyscira.gov", "password": "AmazonianWarrior999!"},
    )
    assert good_login.status_code == 200
    new_token = good_login.json()["token"]

    # 11. Request password reset OTP
    otp_req = client.post(
        "/api/auth/email-otp/send-verification-otp",
        json={"email": "diana@themyscira.gov", "type": "forget-password"},
    )
    assert otp_req.status_code == 200
    assert otp_req.json() == {"success": True}

    with get_connection(multi_user_env["db_path"]) as conn:
        verif_row = conn.execute(
            "SELECT value FROM verification WHERE identifier = 'forget-password-otp-diana@themyscira.gov'"
        ).fetchone()
        assert verif_row is not None
        stored_hash = verif_row[0].split(":")[0]
        assert len(stored_hash) == 64
        pw_reset_otp = routes._test_last_otp
        assert pw_reset_otp is not None
        assert len(pw_reset_otp) == 6

    # 12. Reject bad reset OTP
    bad_reset_otp = client.post(
        "/api/auth/email-otp/reset-password",
        json={
            "email": "diana@themyscira.gov",
            "otp": "000000",
            "password": "BrandNewSecretPassword123!",
        },
    )
    assert bad_reset_otp.status_code == 400

    # 13. Accept valid reset OTP and update password
    reset_resp = client.post(
        "/api/auth/email-otp/reset-password",
        json={
            "email": "diana@themyscira.gov",
            "otp": pw_reset_otp,
            "password": "BrandNewSecretPassword123!",
        },
    )
    assert reset_resp.status_code == 200
    assert reset_resp.json() == {"success": True}

    # 14. Verify pre-reset session was revoked
    old_sess_resp = client.get("/api/auth/get-session", cookies={"better-auth.session_token": new_token})
    assert old_sess_resp.status_code == 200
    assert old_sess_resp.json() is None

    # 15. Login with new password succeeds, old password fails
    assert client.post(
        "/api/auth/sign-in/email",
        json={"email": "diana@themyscira.gov", "password": "AmazonianWarrior999!"},
    ).status_code == 401

    final_login = client.post(
        "/api/auth/sign-in/email",
        json={"email": "diana@themyscira.gov", "password": "BrandNewSecretPassword123!"},
    )
    assert final_login.status_code == 200


def test_otp_attempt_lockout(multi_user_env):
    """Verifies that 5 incorrect OTP attempts lock and invalidate the verification code."""
    client = multi_user_env["client"]
    from app.auth import routes

    # 1. Request OTP for Alice
    resp = client.post(
        "/api/auth/email-otp/send-verification-otp",
        json={"email": "alice@example.com", "type": "forget-password"},
    )
    assert resp.status_code == 200

    # 2. Submit 4 incorrect attempts -> returns 400 with remaining attempts count
    for attempt in range(1, 5):
        bad_resp = client.post(
            "/api/auth/email-otp/reset-password",
            json={
                "email": "alice@example.com",
                "otp": f"99999{attempt}",
                "password": "NewSecurePassword123!",
            },
        )
        assert bad_resp.status_code == 400
        assert "attempt" in bad_resp.json()["detail"]["message"].lower()

    # 3. 5th incorrect attempt -> locks and invalidates OTP
    fifth_resp = client.post(
        "/api/auth/email-otp/reset-password",
        json={
            "email": "alice@example.com",
            "otp": "999995",
            "password": "NewSecurePassword123!",
        },
    )
    assert fifth_resp.status_code == 400
    assert fifth_resp.json()["detail"]["code"] == "OTP_LOCKED"

    # 4. Verify record was deleted from verification table
    with get_connection(multi_user_env["db_path"]) as conn:
        verif = conn.execute(
            "SELECT id FROM verification WHERE identifier = 'forget-password-otp-alice@example.com'"
        ).fetchone()
        assert verif is None

    # 5. Even with the previously valid OTP, attempts now fail because code is locked/deleted
    valid_otp = routes._test_last_otp
    stale_resp = client.post(
        "/api/auth/email-otp/reset-password",
        json={
            "email": "alice@example.com",
            "otp": valid_otp,
            "password": "NewSecurePassword123!",
        },
    )
    assert stale_resp.status_code == 400
    assert stale_resp.json()["detail"]["code"] == "INVALID_OTP"


def test_otp_iso_expiration(multi_user_env):
    """Verifies that ISO-8601 timestamps with 'T' properly expire in Python UTC comparison."""
    client = multi_user_env["client"]
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Manually seed an expired OTP with an ISO-8601 'T' format
    with get_connection(multi_user_env["db_path"]) as conn:
        conn.execute(
            """
            INSERT INTO verification (id, identifier, value, expiresAt, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("expired_otp_test", "forget-password-otp-bob@example.com", "dummyhash:0", past_iso, past_iso, past_iso),
        )
        conn.commit()

    # Attempt reset with expired record -> must return OTP_EXPIRED
    resp = client.post(
        "/api/auth/email-otp/reset-password",
        json={
            "email": "bob@example.com",
            "otp": "123456",
            "password": "NewPasswordForBob123!",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "OTP_EXPIRED"

    # Verify expired record was pruned
    with get_connection(multi_user_env["db_path"]) as conn:
        verif = conn.execute(
            "SELECT id FROM verification WHERE id = 'expired_otp_test'"
        ).fetchone()
        assert verif is None


def test_rate_limiter_enforcement():
    """Verifies in-memory sliding window rate limiter logic."""
    from app.auth.routes import SimpleRateLimiter

    limiter = SimpleRateLimiter(limit=3, window_seconds=60)
    key = "192.168.1.100"

    assert limiter.check_forced(key) is True
    assert limiter.check_forced(key) is True
    assert limiter.check_forced(key) is True
    # 4th request exceeds limit of 3
    assert limiter.check_forced(key) is False

    # Different key is still allowed
    assert limiter.check_forced("192.168.1.101") is True


def test_security_headers_present(multi_user_env):
    """Verifies that security headers are emitted on API responses."""
    client = multi_user_env["client"]
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "geolocation=(self)" in resp.headers.get("Permissions-Policy", "")


def test_rate_limiter_pruning():
    """Verifies that SimpleRateLimiter evicts expired entries."""
    from app.auth.routes import SimpleRateLimiter
    import time

    limiter = SimpleRateLimiter(limit=5, window_seconds=1)
    limiter.check_forced("stale_ip_1")
    limiter.check_forced("stale_ip_2")
    assert "stale_ip_1" in limiter.requests
    assert "stale_ip_2" in limiter.requests

    # Advance time beyond window + prune interval
    future_time = time.time() + 35.0
    limiter._prune(future_time)
    assert "stale_ip_1" not in limiter.requests
    assert "stale_ip_2" not in limiter.requests


def test_email_masking_production():
    """Verifies that PII email masking works as expected."""
    from app.auth.routes import _mask_email

    orig_env = settings.ENVIRONMENT
    try:
        settings.ENVIRONMENT = "production"
        masked = _mask_email("architect.alice@buildwise.ai")
        assert "architect.alice" not in masked
        assert masked == "a***e@b***e.ai"
        assert masked.startswith("a***e@")
        assert masked.endswith(".ai")

        masked_short = _mask_email("bo@ex.com")
        assert "bo" not in masked_short
        assert "@" in masked_short
    finally:
        settings.ENVIRONMENT = orig_env


def test_registration_email_otp_attempt_lockout(multi_user_env):
    """Verifies that 5 incorrect attempts on email verification lock and delete the OTP code."""
    client = multi_user_env["client"]
    from app.auth import routes

    # Register new user
    client.post(
        "/api/auth/sign-up/email",
        json={
            "name": "Lockout User",
            "email": "lockout@example.com",
            "password": "SecurePassword123!",
        },
    )

    # 4 incorrect attempts
    for attempt in range(1, 5):
        resp = client.post(
            "/api/auth/email-otp/verify-email",
            json={"email": "lockout@example.com", "otp": f"11111{attempt}"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "INVALID_OTP"
        assert f"{5 - attempt} attempt" in resp.json()["detail"]["message"].lower()

    # 5th incorrect attempt -> locks and invalidates OTP
    fifth_resp = client.post(
        "/api/auth/email-otp/verify-email",
        json={"email": "lockout@example.com", "otp": "999999"},
    )
    assert fifth_resp.status_code == 400
    assert fifth_resp.json()["detail"]["code"] == "OTP_LOCKED"

    # Verify verification row was wiped
    with get_connection(multi_user_env["db_path"]) as conn:
        verif = conn.execute(
            "SELECT id FROM verification WHERE identifier = 'email-verification-otp-lockout@example.com'"
        ).fetchone()
        assert verif is None

    # Even previously valid OTP fails because code is locked and deleted
    valid_otp = routes._test_last_otp
    stale_resp = client.post(
        "/api/auth/email-otp/verify-email",
        json={"email": "lockout@example.com", "otp": valid_otp},
    )
    assert stale_resp.status_code == 400
    assert stale_resp.json()["detail"]["code"] == "INVALID_OTP"


def test_registration_email_otp_expiration(multi_user_env):
    """Verifies that expired registration OTPs are rejected with OTP_EXPIRED."""
    client = multi_user_env["client"]
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Seed an expired verification OTP
    with get_connection(multi_user_env["db_path"]) as conn:
        conn.execute(
            """
            INSERT INTO user (id, name, email, emailVerified, createdAt, updatedAt)
            VALUES ('exp_user', 'Expired Guy', 'expired@example.com', 0, ?, ?)
            """,
            (past_iso, past_iso),
        )
        conn.execute(
            """
            INSERT INTO verification (id, identifier, value, expiresAt, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("exp_verif_id", "email-verification-otp-expired@example.com", "dummyhash:0", past_iso, past_iso, past_iso),
        )
        conn.commit()

    resp = client.post(
        "/api/auth/email-otp/verify-email",
        json={"email": "expired@example.com", "otp": "123456"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "OTP_EXPIRED"

    # Verification record should be pruned
    with get_connection(multi_user_env["db_path"]) as conn:
        row = conn.execute("SELECT id FROM verification WHERE id = 'exp_verif_id'").fetchone()
        assert row is None


def test_registration_email_otp_resend(multi_user_env):
    """Verifies that resending verification OTP generates a fresh code and invalidates the previous code."""
    client = multi_user_env["client"]
    from app.auth import routes

    # Register user
    client.post(
        "/api/auth/sign-up/email",
        json={
            "name": "Resend Tester",
            "email": "resend@example.com",
            "password": "Password12345!",
        },
    )
    first_otp = routes._test_last_otp
    assert first_otp is not None

    # Resend OTP
    resend_resp = client.post(
        "/api/auth/email-otp/send-verification-otp",
        json={"email": "resend@example.com", "type": "email-verification"},
    )
    assert resend_resp.status_code == 200
    assert resend_resp.json() == {"success": True}

    second_otp = routes._test_last_otp
    assert second_otp is not None

    # First OTP must fail if different from second
    if first_otp != second_otp:
        bad_first = client.post(
            "/api/auth/email-otp/verify-email",
            json={"email": "resend@example.com", "otp": first_otp},
        )
        assert bad_first.status_code == 400

    # Second OTP succeeds
    good_second = client.post(
        "/api/auth/email-otp/verify-email",
        json={"email": "resend@example.com", "otp": second_otp},
    )
    assert good_second.status_code == 200
    assert good_second.json()["status"] is True


def test_unverified_account_direct_api_access_blocked(multi_user_env):
    """Verifies that unverified sessions cannot access protected endpoints (e.g. /api/projects or /api/auth/me)."""
    client = multi_user_env["client"]
    now = datetime.now(timezone.utc)
    future_str = (now + timedelta(days=7)).isoformat()
    now_str = now.isoformat()

    # Seed an unverified user with an active session token directly in the database
    with get_connection(multi_user_env["db_path"]) as conn:
        conn.execute(
            """
            INSERT INTO user (id, name, email, emailVerified, createdAt, updatedAt)
            VALUES ('unverified_user', 'Unverified Sam', 'sam@unverified.org', 0, ?, ?)
            """,
            (now_str, now_str),
        )
        conn.execute(
            """
            INSERT INTO session (id, expiresAt, token, createdAt, updatedAt, userId)
            VALUES ('unverified_sess', ?, 'unverified_session_token', ?, ?, 'unverified_user')
            """,
            (future_str, now_str, now_str),
        )
        conn.commit()

    # Calling /api/projects with unverified session token must return 403 Forbidden
    resp = client.get(
        "/api/projects",
        headers={"Authorization": "Bearer unverified_session_token"},
    )
    assert resp.status_code == 403
    assert "verification required" in resp.json()["detail"].lower()

    # Calling /api/auth/me with unverified session token must return 403 Forbidden
    me_resp = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer unverified_session_token"},
    )
    assert me_resp.status_code == 403
    assert "verification required" in me_resp.json()["detail"].lower()


def test_unverified_user_reregistration_updates_credentials(multi_user_env):
    """Verifies that abandoned unverified accounts can re-register with updated credentials."""
    client = multi_user_env["client"]
    from app.auth import routes

    # 1. First registration attempt
    r1 = client.post(
        "/api/auth/sign-up/email",
        json={"name": "Initial Name", "email": "abandoned@example.com", "password": "OldPassword123!"},
    )
    assert r1.status_code == 200

    # 2. Second registration attempt with new name and new password
    r2 = client.post(
        "/api/auth/sign-up/email",
        json={"name": "Corrected Name", "email": "abandoned@example.com", "password": "NewBetterPassword123!"},
    )
    assert r2.status_code == 200
    otp = routes._test_last_otp

    # 3. Verify with fresh OTP
    v_resp = client.post(
        "/api/auth/email-otp/verify-email",
        json={"email": "abandoned@example.com", "otp": otp},
    )
    assert v_resp.status_code == 200
    assert v_resp.json()["user"]["name"] == "Corrected Name"

    # 4. Old password fails, new password succeeds
    assert client.post(
        "/api/auth/sign-in/email",
        json={"email": "abandoned@example.com", "password": "OldPassword123!"},
    ).status_code == 401

    assert client.post(
        "/api/auth/sign-in/email",
        json={"email": "abandoned@example.com", "password": "NewBetterPassword123!"},
    ).status_code == 200


def test_existing_account_grandfathering():
    """Verifies that init_db() grandfathers existing accounts with emailVerified = 1 so existing users never lose access."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    # Initialize a fresh DB without user_version=2 yet, containing a pre-existing user with emailVerified = 0
    now_str = datetime.now(timezone.utc).isoformat()
    with get_connection(path) as conn:
        from app.db.database import SCHEMA_SQL
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO user (id, name, email, emailVerified, createdAt, updatedAt) VALUES (?, ?, ?, 0, ?, ?)",
            ("legacy_user_1", "Legacy User", "legacy@buildwise.ai", now_str, now_str),
        )
        conn.commit()

    # Run init_db() which executes migration to bump user_version and grandfather existing users
    init_db(db_path=path)

    with get_connection(path) as conn:
        row = conn.execute("SELECT emailVerified FROM user WHERE id = 'legacy_user_1'").fetchone()
        assert row["emailVerified"] == 1

        v_row = conn.execute("PRAGMA user_version;").fetchone()
        assert v_row[0] == 2

    try:
        os.remove(path)
    except OSError:
        pass


