import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote
from fastapi import Cookie, Header, HTTPException, Request, status
from app.auth.models import AuthenticatedUser
from app.db.database import get_connection

logger = logging.getLogger("buildwise.auth")


def extract_token_from_request(
    request: Request,
    better_auth_cookie: Optional[str] = None,
    secure_cookie: Optional[str] = None,
    authorization: Optional[str] = None,
) -> Optional[str]:
    """Extract and normalize the raw Better Auth session token from cookies or Authorization header."""
    # 1. Check Authorization Bearer header
    if authorization and authorization.strip():
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw = parts[1].strip()
            # Better Auth may format signed tokens as token.signature
            return raw.split(".")[0]
        elif len(parts) == 1:
            return parts[0].strip().split(".")[0]

    # 2. Check cookies
    cookie_candidate = better_auth_cookie or secure_cookie
    if not cookie_candidate:
        # Fallback to direct request cookie access in case cookie name variations exist
        cookie_candidate = (
            request.cookies.get("better-auth.session_token")
            or request.cookies.get("__Secure-better-auth.session_token")
        )

    if cookie_candidate:
        decoded = unquote(cookie_candidate).strip()
        # Better Auth signed cookies are structured as: <session_token>.<signature>
        return decoded.split(".")[0]

    return None


def _parse_iso_datetime(val: str) -> Optional[datetime]:
    if not val:
        return None
    try:
        # Handle ISO strings like 2026-11-21T19:58:43.098Z or with timezone offset
        clean_val = val.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def verify_session_token(token: str, db_path: Optional[str] = None) -> Optional[AuthenticatedUser]:
    """Look up active session and user in SQLite and verify validity."""
    if not token or not token.strip():
        return None

    clean_token = token.strip()
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT
                s.id AS session_id,
                s.token AS session_token,
                s.expiresAt AS expires_at,
                s.userId AS user_id,
                u.name AS user_name,
                u.email AS user_email,
                u.emailVerified AS email_verified,
                u.image AS user_image
            FROM session s
            JOIN user u ON s.userId = u.id
            WHERE s.token = ?
            LIMIT 1
            """,
            (clean_token,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        # Check expiration
        expires_at_dt = _parse_iso_datetime(row["expires_at"])
        if expires_at_dt:
            now_utc = datetime.now(timezone.utc)
            if now_utc > expires_at_dt:
                logger.info(f"Session {row['session_id']} expired at {row['expires_at']}.")
                return None

        return AuthenticatedUser(
            id=row["user_id"],
            name=row["user_name"],
            email=row["user_email"],
            email_verified=bool(row["email_verified"]),
            image=row["user_image"],
            session_id=row["session_id"],
            token=row["session_token"],
        )


async def get_current_user(
    request: Request,
    better_auth_cookie: Optional[str] = Cookie(None, alias="better-auth.session_token"),
    secure_cookie: Optional[str] = Cookie(None, alias="__Secure-better-auth.session_token"),
    authorization: Optional[str] = Header(None),
) -> AuthenticatedUser:
    """FastAPI dependency: verifies authenticated session and returns current user, or raises 401."""
    token = extract_token_from_request(
        request=request,
        better_auth_cookie=better_auth_cookie,
        secure_cookie=secure_cookie,
        authorization=authorization,
    )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access this resource.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = verify_session_token(token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_optional_current_user(
    request: Request,
    better_auth_cookie: Optional[str] = Cookie(None, alias="better-auth.session_token"),
    secure_cookie: Optional[str] = Cookie(None, alias="__Secure-better-auth.session_token"),
    authorization: Optional[str] = Header(None),
) -> Optional[AuthenticatedUser]:
    """FastAPI dependency: returns current user if authenticated, or None if anonymous."""
    token = extract_token_from_request(
        request=request,
        better_auth_cookie=better_auth_cookie,
        secure_cookie=secure_cookie,
        authorization=authorization,
    )
    if not token:
        return None
    return verify_session_token(token)
