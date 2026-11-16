"""
errors.py — Centralized error classification and normalization for AI providers and BYOK execution.
"""
from typing import Optional
from pydantic import BaseModel


class ProviderErrorCode:
    INVALID_KEY = "invalid_api_key"
    EXPIRED_KEY = "expired_api_key"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    RATE_LIMITED = "rate_limit_exceeded"
    MODEL_UNAVAILABLE = "model_unavailable"
    TIMEOUT = "provider_timeout"
    NETWORK_ERROR = "network_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    VALIDATION_ERROR = "validation_error"
    SSRF_BLOCKED = "ssrf_destination_blocked"
    UNSUPPORTED_OPERATION = "unsupported_operation"
    UNKNOWN_ERROR = "unknown_provider_error"


class ProviderErrorInfo(BaseModel):
    code: str
    message: str
    status_code: Optional[int] = None
    retryable: bool = False
    is_credential_failure: bool = False
    details: Optional[str] = None


def classify_provider_error(
    error: Exception,
    status_code: Optional[int] = None,
    raw_response: Optional[str] = None
) -> ProviderErrorInfo:
    """
    Classifies raw HTTP/SDK exceptions into standardized, actionable ProviderErrorInfo.
    Ensures clear distinction between credential invalidity, rate limits, timeouts, and network errors.
    """
    err_str = str(error).lower()
    raw_resp = (raw_response or "").lower()
    combined = f"{err_str} {raw_resp}"

    # 1. Credential invalidity / unauthorized
    if status_code in (401, 403) or "unauthorized" in combined or "invalid_api_key" in combined or "authentication_error" in combined or "api_key_invalid" in combined or "permission denied" in combined:
        return ProviderErrorInfo(
            code=ProviderErrorCode.INVALID_KEY,
            message="The provided API key is invalid, inactive, or unauthorized for this model.",
            status_code=status_code or 401,
            retryable=False,
            is_credential_failure=True,
            details=err_str[:200]
        )

    # 2. Insufficient credits / quota
    if status_code == 402 or "quota" in combined or "insufficient_quota" in combined or "balance" in combined or "credit" in combined or "billing" in combined:
        return ProviderErrorInfo(
            code=ProviderErrorCode.INSUFFICIENT_CREDITS,
            message="The AI provider account has exhausted its usage credits or billing quota.",
            status_code=status_code or 402,
            retryable=False,
            is_credential_failure=False,
            details=err_str[:200]
        )

    # 3. Rate limiting
    if status_code == 429 or "rate_limit" in combined or "too many requests" in combined:
        return ProviderErrorInfo(
            code=ProviderErrorCode.RATE_LIMITED,
            message="Provider request limit reached. Rate limit exceeded for this API key.",
            status_code=status_code or 429,
            retryable=True,
            is_credential_failure=False,
            details=err_str[:200]
        )

    # 4. Model not found or unsupported
    if status_code == 404 or "model_not_found" in combined or "does not exist" in combined or "not found" in combined:
        return ProviderErrorInfo(
            code=ProviderErrorCode.MODEL_UNAVAILABLE,
            message="The requested model is unavailable, retired, or not accessible with your key.",
            status_code=status_code or 404,
            retryable=False,
            is_credential_failure=False,
            details=err_str[:200]
        )

    # 5. Timeouts
    if "timeout" in err_str or "timed out" in err_str:
        return ProviderErrorInfo(
            code=ProviderErrorCode.TIMEOUT,
            message="AI provider connection timed out. The remote service took too long to answer.",
            status_code=504,
            retryable=True,
            is_credential_failure=False,
            details=err_str[:200]
        )

    # 6. SSRF / Security restrictions
    if "ssrf" in err_str or "private address" in err_str or "loopback" in err_str or "forbidden host" in err_str:
        return ProviderErrorInfo(
            code=ProviderErrorCode.SSRF_BLOCKED,
            message="The provided endpoint URL points to a restricted internal or private address.",
            status_code=403,
            retryable=False,
            is_credential_failure=False,
            details=err_str[:200]
        )

    # 7. Service unavailable / Bad gateway
    if status_code in (500, 502, 503, 504) or "overloaded" in combined or "internal_error" in combined:
        return ProviderErrorInfo(
            code=ProviderErrorCode.SERVICE_UNAVAILABLE,
            message="The AI provider service is temporarily overloaded or experiencing an outage.",
            status_code=status_code or 503,
            retryable=True,
            is_credential_failure=False,
            details=err_str[:200]
        )

    # 8. Network connectivity errors
    if "connect" in err_str or "failed to establish a new connection" in err_str or "name resolution" in err_str:
        return ProviderErrorInfo(
            code=ProviderErrorCode.NETWORK_ERROR,
            message="Could not connect to the remote AI provider endpoint. Please check network connectivity or URL.",
            status_code=502,
            retryable=True,
            is_credential_failure=False,
            details=err_str[:200]
        )

    return ProviderErrorInfo(
        code=ProviderErrorCode.UNKNOWN_ERROR,
        message=f"An unexpected AI provider error occurred: {err_str[:120]}",
        status_code=status_code or 500,
        retryable=False,
        is_credential_failure=False,
        details=err_str[:200]
    )
