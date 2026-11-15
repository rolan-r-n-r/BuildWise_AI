"""
crypto.py — Cryptographic utilities for BuildWise backend authentication.
Implements Scrypt password hashing matching Better Auth specification.
"""
import hashlib
import hmac
import secrets


def hash_password(password: str) -> str:
    """
    Hashes a password using Scrypt with Better Auth's exact parameters:
    N=16384, r=16, p=1, dklen=64.
    Format: salt_hex:hash_hex
    """
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=16,
        p=1,
        maxmem=128 * 16384 * 16 * 2,
        dklen=64,
    )
    return f"{salt.hex()}:{key.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Verifies a password against a stored Scrypt hash using constant-time comparison.
    """
    if not stored_hash or ":" not in stored_hash:
        return False
    try:
        salt_hex, key_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
        computed_key = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=16384,
            r=16,
            p=1,
            maxmem=128 * 16384 * 16 * 2,
            dklen=64,
        )
        return hmac.compare_digest(computed_key, expected_key)
    except Exception:
        return False


def generate_id() -> str:
    """Generates a secure alphanumeric identifier for users, sessions, and accounts."""
    return secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:32]


def generate_session_token() -> str:
    """Generates a high-entropy session token."""
    return secrets.token_urlsafe(32)


def generate_otp() -> str:
    """Generates a cryptographically random 6-digit numeric OTP."""
    val = secrets.randbelow(900000) + 100000
    return str(val)


def hash_otp(otp: str) -> str:
    """Hashes a numeric OTP with SHA-256 for secure storage at rest."""
    return hashlib.sha256(otp.encode("utf-8")).hexdigest()


def verify_otp(submitted_otp: str, stored_val: str) -> bool:
    """
    Constant-time comparison for OTP codes.
    Supports both modern SHA-256 hashes and legacy plaintext values.
    """
    clean_submitted = submitted_otp.strip()
    if not clean_submitted:
        return False
    if len(stored_val) == 6 and stored_val.isdigit():
        # Legacy plaintext comparison
        return hmac.compare_digest(clean_submitted, stored_val)
    computed_hash = hash_otp(clean_submitted)
    return hmac.compare_digest(computed_hash, stored_val)

