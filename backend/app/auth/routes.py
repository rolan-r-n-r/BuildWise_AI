"""
routes.py — FastAPI Authentication Router compatible with Better Auth Client.
Runs 100% on the backend inside FastAPI.
All logs appear in the backend terminal.
"""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import logging
import os
import re
import sqlite3
import time
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.config import settings
from app.db.database import get_db
from app.auth.crypto import (
    hash_password,
    verify_password,
    generate_id,
    generate_session_token,
    generate_otp,
    hash_otp,
    verify_otp,
)
from app.auth.brevo import send_brevo_otp_email

logger = logging.getLogger(__name__)

router = APIRouter()

SESSION_COOKIE_NAME = "better-auth.session_token"
SECURE_SESSION_COOKIE_NAME = "__Secure-better-auth.session_token"
SESSION_TTL_DAYS = 7
MAX_OTP_ATTEMPTS = 5

# Pre-computed dummy hash to guarantee constant-time execution on invalid logins
_DUMMY_SCRYPT_HASH = hash_password("dummy_constant_timing_scrypt_probe_salt")

# Module hook for automated test suites to inspect the generated OTP
_test_last_otp: Optional[str] = None


class SimpleRateLimiter:
    """Sliding-window in-memory rate limiter per IP / identity with auto-pruning."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
        self._last_prune = 0.0

    def _prune(self, now: float) -> None:
        """Prunes stale keys periodically to prevent unbounded memory growth."""
        if now - self._last_prune < 30.0:
            return
        self._last_prune = now
        cutoff = now - self.window_seconds
        stale_keys = [k for k, timestamps in self.requests.items() if not timestamps or timestamps[-1] <= cutoff]
        for k in stale_keys:
            self.requests.pop(k, None)

    def check(self, key: str) -> bool:
        # In test mode, bypass by default so large test suites are not throttled
        if settings.ENVIRONMENT.lower() in ("test", "testing") or os.getenv("PYTEST_CURRENT_TEST"):
            return True
        now = time.time()
        self._prune(now)
        cutoff = now - self.window_seconds
        self.requests[key] = [t for t in self.requests[key] if t > cutoff]
        if len(self.requests[key]) >= self.limit:
            return False
        self.requests[key].append(now)
        return True

    def check_forced(self, key: str) -> bool:
        """Forces rate limiting evaluation regardless of environment (for unit testing)."""
        now = time.time()
        self._prune(now)
        cutoff = now - self.window_seconds
        self.requests[key] = [t for t in self.requests[key] if t > cutoff]
        if len(self.requests[key]) >= self.limit:
            return False
        self.requests[key].append(now)
        return True

    def reset(self):
        self.requests.clear()
        self._last_prune = 0.0


sign_in_limiter = SimpleRateLimiter(limit=5, window_seconds=60)
sign_up_limiter = SimpleRateLimiter(limit=5, window_seconds=60)
send_otp_limiter = SimpleRateLimiter(limit=3, window_seconds=60)
reset_pw_limiter = SimpleRateLimiter(limit=5, window_seconds=60)


def reset_rate_limiters():
    sign_in_limiter.reset()
    sign_up_limiter.reset()
    send_otp_limiter.reset()
    reset_pw_limiter.reset()


def _get_client_ip(request: Request) -> str:
    """Extract client IP with trusted reverse proxy verification.

    X-Forwarded-For is only parsed when the direct peer connection originates
    from a configured trusted proxy, preventing IP spoofing and rate limit bypass.
    """
    direct_host = request.client.host if request.client else "127.0.0.1"
    trusted = getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1", "testclient", "localhost"])
    if "*" in trusted or direct_host in trusted:
        xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    return direct_host


def _mask_email(email: str) -> str:
    """Mask email for safe logging in production (e.g. j***e@e***e.com)."""
    if not email or "@" not in email:
        return "[redacted]"
    if settings.ENVIRONMENT.lower() != "production":
        return email
    try:
        user_part, domain_part = email.split("@", 1)
        if len(user_part) <= 2:
            masked_user = user_part[0] + "***"
        else:
            masked_user = user_part[0] + "***" + user_part[-1]

        if "." in domain_part:
            d_name, d_tld = domain_part.rsplit(".", 1)
            masked_domain = (d_name[0] + "***" if len(d_name) > 1 else "***") + "." + d_tld
        else:
            masked_domain = "***"
        return f"{masked_user}@{masked_domain}"
    except Exception:
        return "[redacted]"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _expires_iso(days: int = 7) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _otp_expires_iso(seconds: int = 300) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _is_expired(expires_at_str: str) -> bool:
    """
    Robust ISO-8601 UTC datetime expiration check.
    Fixes SQLite string comparison flaw where ' ' < 'T' evaluated expiration as false.
    """
    try:
        clean_str = expires_at_str.replace("Z", "+00:00")
        exp_dt = datetime.fromisoformat(clean_str)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp_dt
    except Exception:
        return True


def _set_session_cookie(response: Response, token: str, remember_me: bool = True):
    is_prod = settings.ENVIRONMENT.lower() == "production"
    cookie_name = SECURE_SESSION_COOKIE_NAME if is_prod else SESSION_COOKIE_NAME
    max_age = 60 * 60 * 24 * SESSION_TTL_DAYS if remember_me else 60 * 60 * 24
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=is_prod,
        path="/",
    )


def _clear_session_cookie(response: Response):
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=SECURE_SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )



# =============================================================================
# Request Schemas
# =============================================================================

class SignUpRequest(BaseModel):
    name: str
    email: str
    password: str


class SignInRequest(BaseModel):
    email: str
    password: str
    rememberMe: Optional[bool] = False


class SendOtpRequest(BaseModel):
    email: str
    type: str = "forget-password"


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    password: str


# =============================================================================
# Routes
# =============================================================================

@router.get("/ok")
def auth_ok():
    return {"ok": True}


@router.post("/sign-up/email")
def sign_up_email(
    req: SignUpRequest,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
):
    ip = _get_client_ip(request)
    if not sign_up_limiter.check(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"message": "Too many registration attempts. Please try again later.", "code": "TOO_MANY_REQUESTS"},
        )

    email_clean = req.email.strip().lower()
    name_clean = req.name.strip()
    if len(name_clean) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Name cannot be empty", "code": "INVALID_NAME"},
        )
    if len(req.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Password must be at least 8 characters long", "code": "PASSWORD_TOO_SHORT"},
        )

    cursor = db.cursor()
    cursor.execute("SELECT id FROM user WHERE LOWER(email) = ?", (email_clean,))
    if cursor.fetchone():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "An account with this email already exists", "code": "USER_ALREADY_EXISTS"},
        )

    now = _now_iso()
    user_id = generate_id()
    account_id = generate_id()
    session_id = generate_id()
    session_token = generate_session_token()
    session_expiry = _expires_iso(SESSION_TTL_DAYS)

    pw_hash = hash_password(req.password)

    cursor.execute(
        """
        INSERT INTO user (id, name, email, emailVerified, createdAt, updatedAt)
        VALUES (?, ?, ?, 0, ?, ?)
        """,
        (user_id, name_clean, email_clean, now, now),
    )

    cursor.execute(
        """
        INSERT INTO account (id, accountId, providerId, userId, password, createdAt, updatedAt)
        VALUES (?, ?, 'credential', ?, ?, ?, ?)
        """,
        (account_id, email_clean, user_id, pw_hash, now, now),
    )

    cursor.execute(
        """
        INSERT INTO session (id, expiresAt, token, createdAt, updatedAt, userId)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, session_expiry, session_token, now, now, user_id),
    )
    db.commit()

    _set_session_cookie(response, session_token, remember_me=True)
    logger.info("[Auth] New user registered: %s (id: %s)", _mask_email(email_clean), user_id)

    return {
        "redirect": False,
        "token": session_token,
        "user": {
            "id": user_id,
            "name": name_clean,
            "email": email_clean,
            "emailVerified": False,
            "createdAt": now,
            "updatedAt": now,
        },
    }


@router.post("/sign-in/email")
def sign_in_email(
    req: SignInRequest,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
):
    ip = _get_client_ip(request)
    email_clean = req.email.strip().lower()

    # Dual-key rate limiting: evaluates both client IP and user identity
    if not sign_in_limiter.check(ip) or not sign_in_limiter.check(f"user:{email_clean}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"message": "Too many sign in attempts. Please try again later.", "code": "TOO_MANY_REQUESTS"},
        )

    cursor = db.cursor()

    cursor.execute(
        """
        SELECT u.id, u.name, u.email, u.emailVerified, u.createdAt, u.updatedAt, a.password
        FROM user u
        JOIN account a ON u.id = a.userId
        WHERE LOWER(u.email) = ? AND a.providerId = 'credential'
        """,
        (email_clean,),
    )
    row = cursor.fetchone()

    if not row:
        # Constant-time dummy Scrypt computation to prevent user enumeration via timing
        verify_password(req.password, _DUMMY_SCRYPT_HASH)
        logger.warning("[Auth] Invalid login attempt for non-existent user: %s", _mask_email(email_clean))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid email or password", "code": "INVALID_EMAIL_OR_PASSWORD"},
        )

    if not verify_password(req.password, row[6]):
        logger.warning("[Auth] Invalid login attempt for: %s", _mask_email(email_clean))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid email or password", "code": "INVALID_EMAIL_OR_PASSWORD"},
        )

    user_id, name, email, email_verified, created_at, updated_at, _ = row
    now = _now_iso()
    session_id = generate_id()
    session_token = generate_session_token()
    session_days = SESSION_TTL_DAYS if req.rememberMe else 1
    session_expiry = _expires_iso(session_days)

    cursor.execute(
        """
        INSERT INTO session (id, expiresAt, token, createdAt, updatedAt, userId)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (session_id, session_expiry, session_token, now, now, user_id),
    )
    db.commit()

    _set_session_cookie(response, session_token, remember_me=bool(req.rememberMe))
    logger.info("[Auth] User logged in: %s (id: %s)", _mask_email(email_clean), user_id)

    return {
        "redirect": False,
        "token": session_token,
        "user": {
            "id": user_id,
            "name": name,
            "email": email,
            "emailVerified": bool(email_verified),
            "createdAt": created_at,
            "updatedAt": updated_at,
        },
    }


@router.post("/sign-out")
def sign_out(
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_db),
):
    cookie_token = (
        request.cookies.get(SESSION_COOKIE_NAME)
        or request.cookies.get(SECURE_SESSION_COOKIE_NAME)
    )
    auth_header = request.headers.get("Authorization")
    token = None
    if cookie_token:
        token = cookie_token.split(".")[0]
    elif auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip().split(".")[0]

    if token:
        cursor = db.cursor()
        cursor.execute("DELETE FROM session WHERE token = ?", (token,))
        db.commit()

    _clear_session_cookie(response)
    logger.info("[Auth] User signed out cleanly.")
    return {"success": True}


@router.get("/get-session")
def get_session(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    cookie_token = (
        request.cookies.get(SESSION_COOKIE_NAME)
        or request.cookies.get(SECURE_SESSION_COOKIE_NAME)
    )
    auth_header = request.headers.get("Authorization")
    token = None
    if cookie_token:
        token = cookie_token.split(".")[0]
    elif auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip().split(".")[0]

    if not token:
        return None

    cursor = db.cursor()
    cursor.execute(
        """
        SELECT s.id, s.userId, s.token, s.expiresAt, s.createdAt, s.updatedAt,
               u.id, u.name, u.email, u.emailVerified, u.createdAt, u.updatedAt
        FROM session s
        JOIN user u ON s.userId = u.id
        WHERE s.token = ?
        """,
        (token,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    # Check expiration using robust Python UTC check
    expires_at = row[3]
    if _is_expired(expires_at):
        return None

    return {
        "session": {
            "id": row[0],
            "userId": row[1],
            "token": row[2],
            "expiresAt": row[3],
            "createdAt": row[4],
            "updatedAt": row[5],
        },
        "user": {
            "id": row[6],
            "name": row[7],
            "email": row[8],
            "emailVerified": bool(row[9]),
            "createdAt": row[10],
            "updatedAt": row[11],
        },
    }


@router.post("/email-otp/send-verification-otp")
async def send_verification_otp(
    req: SendOtpRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    global _test_last_otp
    ip = _get_client_ip(request)
    email_clean = req.email.strip().lower()

    if not send_otp_limiter.check(f"{ip}:{email_clean}"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"message": "Too many OTP requests. Please wait a moment before requesting another.", "code": "TOO_MANY_REQUESTS"},
        )

    cursor = db.cursor()
    cursor.execute("SELECT id FROM user WHERE LOWER(email) = ?", (email_clean,))
    user_row = cursor.fetchone()

    # Generate 6-digit cryptographically secure OTP
    otp = generate_otp()
    if settings.ENVIRONMENT.lower() in ("test", "testing", "development") or os.getenv("PYTEST_CURRENT_TEST"):
        _test_last_otp = otp
    identifier = f"forget-password-otp-{email_clean}"
    now = _now_iso()
    expires_at = _otp_expires_iso(300)  # 5 minutes
    otp_hash = hash_otp(otp)

    # If user exists, record the verification OTP with hash and 0 attempts
    if user_row:
        cursor.execute("DELETE FROM verification WHERE identifier = ?", (identifier,))
        cursor.execute(
            """
            INSERT INTO verification (id, identifier, value, expiresAt, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (generate_id(), identifier, f"{otp_hash}:0", expires_at, now, now),
        )
        db.commit()

        # Dispatch email in background so the response time is constant
        # SECURITY POLICY: The OTP code is NEVER printed in logs
        background_tasks.add_task(send_brevo_otp_email, email_clean, otp, req.type)

    # Always return 200 OK to prevent user enumeration
    return {"success": True}


@router.post("/email-otp/reset-password")
def reset_password(
    req: ResetPasswordRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
):
    ip = _get_client_ip(request)
    if not reset_pw_limiter.check(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"message": "Too many reset attempts. Please try again later.", "code": "TOO_MANY_REQUESTS"},
        )

    email_clean = req.email.strip().lower()
    submitted_otp = req.otp.strip()

    if len(req.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Password must be at least 8 characters long", "code": "PASSWORD_TOO_SHORT"},
        )

    identifier = f"forget-password-otp-{email_clean}"
    cursor = db.cursor()
    cursor.execute(
        """
        SELECT id, value, expiresAt FROM verification WHERE identifier = ?
        """,
        (identifier,),
    )
    row = cursor.fetchone()
    if not row:
        logger.warning("[Auth] Password reset attempted with no active OTP for: %s", _mask_email(email_clean))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "The verification code is invalid or has expired.", "code": "INVALID_OTP"},
        )

    verif_id, stored_val, expires_at = row
    if _is_expired(expires_at):
        cursor.execute("DELETE FROM verification WHERE id = ?", (verif_id,))
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "The verification code has expired. Please request a new one.", "code": "OTP_EXPIRED"},
        )

    # Parse stored OTP hash and attempt counter
    parts = stored_val.split(":")
    stored_otp_or_hash = parts[0]
    attempts = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    if attempts >= MAX_OTP_ATTEMPTS:
        cursor.execute("DELETE FROM verification WHERE id = ?", (verif_id,))
        db.commit()
        logger.warning("[Auth] OTP attempt limit reached (%d) for: %s. OTP locked.", attempts, _mask_email(email_clean))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Too many failed attempts. This code has been invalidated. Please request a new one.", "code": "OTP_LOCKED"},
        )

    if not verify_otp(submitted_otp, stored_otp_or_hash):
        new_attempts = attempts + 1
        new_now = _now_iso()
        if new_attempts >= MAX_OTP_ATTEMPTS:
            cursor.execute("DELETE FROM verification WHERE id = ?", (verif_id,))
            db.commit()
            logger.warning("[Auth] Max OTP attempts exceeded for: %s. Code deleted.", _mask_email(email_clean))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Too many failed attempts. This code has been invalidated. Please request a new one.", "code": "OTP_LOCKED"},
            )
        else:
            new_val = f"{stored_otp_or_hash}:{new_attempts}"
            cursor.execute("UPDATE verification SET value = ?, updatedAt = ? WHERE id = ?", (new_val, new_now, verif_id))
            db.commit()
            remaining = MAX_OTP_ATTEMPTS - new_attempts
            logger.warning("[Auth] Incorrect OTP entered for: %s (%d/%d attempts)", _mask_email(email_clean), new_attempts, MAX_OTP_ATTEMPTS)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": f"Invalid verification code. {remaining} attempt{'s' if remaining != 1 else ''} remaining.", "code": "INVALID_OTP"},
            )

    # Get user
    cursor.execute("SELECT id FROM user WHERE LOWER(email) = ?", (email_clean,))
    user_row = cursor.fetchone()
    if not user_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user_id = user_row[0]
    new_pw_hash = hash_password(req.password)
    now = _now_iso()

    # Update password
    cursor.execute(
        """
        UPDATE account SET password = ?, updatedAt = ? WHERE userId = ? AND providerId = 'credential'
        """,
        (new_pw_hash, now, user_id),
    )

    # Revoke ALL active sessions for this user on password reset
    cursor.execute("DELETE FROM session WHERE userId = ?", (user_id,))

    # Invalidate used verification OTP
    cursor.execute("DELETE FROM verification WHERE id = ?", (verif_id,))
    db.commit()

    logger.info("[Auth] Password successfully reset for: %s. All previous sessions revoked.", _mask_email(email_clean))
    return {"success": True}

