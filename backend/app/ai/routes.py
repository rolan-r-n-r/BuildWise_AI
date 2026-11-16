"""
routes.py — REST API router for AI provider management and Bring Your Own API Key (BYOK) configurations.
Enforces authenticated multi-user isolation, credential encryption at rest, and zero exposure of plaintext keys.
"""
import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, get_current_user
from app.db.ai_credential_repository import (
    AICredentialRepository,
    UserAICredentialSummary,
    UserAIPreferenceRecord,
)
from app.services.ai_crypto import encrypt_api_key, mask_api_key, decrypt_api_key
from app.ai.groq_adapter import validate_groq_key, SUPPORTED_GROQ_MODELS
from app.ai.gemini_adapter import validate_gemini_key, SUPPORTED_GEMINI_MODELS
from app.ai.openai_adapter import validate_openai_key, SUPPORTED_OPENAI_MODELS
from app.ai.anthropic_adapter import validate_anthropic_key, SUPPORTED_ANTHROPIC_MODELS
from app.ai.ollama_adapter import validate_ollama_endpoint, DEFAULT_OLLAMA_MODELS
from app.ai.ssrf import validate_outbound_url, SSRFValidationError
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai-providers"])
repo = AICredentialRepository()

_VALIDATE_RATE_LIMIT_WINDOW = 60.0
_VALIDATE_MAX_REQUESTS = 20
_validate_request_history = defaultdict(list)


def _check_ai_rate_limit(user_id: str) -> None:
    now = time.time()
    history = _validate_request_history[user_id]
    _validate_request_history[user_id] = [t for t in history if now - t < _VALIDATE_RATE_LIMIT_WINDOW]
    if len(_validate_request_history[user_id]) >= _VALIDATE_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for AI provider configuration. Please wait 60 seconds."
        )
    _validate_request_history[user_id].append(now)

SUPPORTED_PROVIDERS = {
    "deterministic": {
        "id": "deterministic",
        "name": "Built-in Deterministic Engine",
        "description": "Calculates engineering metrics and generates technical commentary using local verified civil engineering formulas (NBC 2016, IS 1893, CPWD DSR). Operates with zero external API keys, zero latency, and 100% availability.",
        "models": ["built-in-rules"],
        "requires_api_key": False,
        "supports_custom_url": False,
        "icon": "shield",
    },
    "groq": {
        "id": "groq",
        "name": "Groq Cloud",
        "description": "Ultra-low latency inference engine running open-weights engineering models (Llama 3.3 70B, GPT-OSS 120B, Qwen 2.5).",
        "models": SUPPORTED_GROQ_MODELS,
        "requires_api_key": True,
        "supports_custom_url": False,
        "icon": "zap",
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "description": "Google Gemini Multimodal AI models (Gemini 2.5 Flash, Gemini 2.5 Pro) with structured schema constraint outputs.",
        "models": SUPPORTED_GEMINI_MODELS,
        "requires_api_key": True,
        "supports_custom_url": False,
        "icon": "sparkles",
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "description": "Flagship generative reasoning models (GPT-4o, GPT-4o-mini) with structured architectural synthesis capabilities.",
        "models": SUPPORTED_OPENAI_MODELS,
        "requires_api_key": True,
        "supports_custom_url": False,
        "icon": "cpu",
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "description": "Advanced technical reasoners (Claude 3.5 Sonnet, Claude 3.5 Haiku) with nuanced civil engineering analysis.",
        "models": SUPPORTED_ANTHROPIC_MODELS,
        "requires_api_key": True,
        "supports_custom_url": False,
        "icon": "box",
    },
    "ollama": {
        "id": "ollama",
        "name": "Ollama (Self-Hosted / Local)",
        "description": "Self-hosted local or private cloud Ollama server running open models. In production, requires a public HTTPS tunnel.",
        "models": DEFAULT_OLLAMA_MODELS,
        "requires_api_key": False,
        "supports_custom_url": True,
        "icon": "server",
    },
}


# --- Request and Response Schemas ---

class ProviderCatalogItem(BaseModel):
    id: str
    name: str
    description: str
    models: List[str]
    requires_api_key: bool
    supports_custom_url: bool
    icon: str


class ValidateCredentialRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


class ValidateCredentialResponse(BaseModel):
    valid: bool
    message: str
    available_models: List[str] = []


class ConnectProviderRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    selected_model: Optional[str] = None
    validate_first: bool = True


class UpdatePreferenceRequest(BaseModel):
    preferred_provider: str
    preferred_model: Optional[str] = None
    fallback_to_deterministic: bool = True


class UserAIConfigResponse(BaseModel):
    configured_providers: List[UserAICredentialSummary]
    preference: UserAIPreferenceRecord
    is_production: bool
    server_default_provider: str


# --- Helper Validation Dispatcher ---

async def _dispatch_validation(
    provider: str,
    api_key: Optional[str],
    base_url: Optional[str]
) -> Tuple[bool, str, List[str]]:
    p = provider.strip().lower()
    if p == "deterministic":
        return True, "Built-in deterministic engine is always available.", ["built-in-rules"]
    elif p == "groq":
        if not api_key:
            return False, "Groq API key is required.", []
        return await validate_groq_key(api_key)
    elif p == "gemini":
        if not api_key:
            return False, "Google Gemini API key is required.", []
        return await validate_gemini_key(api_key)
    elif p == "openai":
        if not api_key:
            return False, "OpenAI API key is required.", []
        return await validate_openai_key(api_key)
    elif p == "anthropic":
        if not api_key:
            return False, "Anthropic API key is required.", []
        return await validate_anthropic_key(api_key)
    elif p == "ollama":
        return await validate_ollama_endpoint(base_url)
    return False, f"Unsupported provider '{provider}'.", []


# --- Endpoints ---

@router.get("/providers", response_model=List[ProviderCatalogItem])
async def get_supported_providers():
    """Returns the catalog of all supported AI providers and their metadata."""
    return list(SUPPORTED_PROVIDERS.values())


@router.get("/config", response_model=UserAIConfigResponse)
async def get_user_ai_configuration(user: AuthenticatedUser = Depends(get_current_user)):
    """
    Returns the authenticated user's configured AI providers (safe summaries only)
    and their active execution preferences. Never exposes decrypted API keys.
    """
    configured = repo.list_credentials(user.id)
    preference = repo.get_preference(user.id)
    return UserAIConfigResponse(
        configured_providers=configured,
        preference=preference,
        is_production=settings.is_production,
        server_default_provider=settings.DEFAULT_AI_PROVIDER,
    )


@router.post("/validate", response_model=ValidateCredentialResponse)
async def validate_provider_credentials(
    req: ValidateCredentialRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Validates an API key or custom endpoint with the remote provider.
    Can validate a newly submitted key or test an already saved key for the current user.
    """
    _check_ai_rate_limit(user.id)
    clean_p = req.provider.strip().lower()
    if clean_p not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown AI provider '{req.provider}'."
        )

    # If no key submitted (or only mask dots sent), attempt to test existing saved key for this user
    key_to_test = (req.api_key or "").strip()
    if key_to_test and all(ch in "•●*.\t " for ch in key_to_test):
        key_to_test = ""
    base_url_to_test = req.base_url

    if not key_to_test and clean_p != "ollama" and clean_p != "deterministic":
        existing = repo.get_credential_record(user.id, clean_p)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No saved credentials found for {clean_p}. Please provide an API key to validate."
            )
        try:
            key_to_test = decrypt_api_key(existing.encrypted_api_key, user.id, clean_p)
            base_url_to_test = existing.base_url
        except Exception as e:
            logger.error(f"Could not decrypt saved credentials for user={user.id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not decrypt saved credentials. Please re-enter your API key."
            )

    is_valid, message, models = await _dispatch_validation(clean_p, key_to_test, base_url_to_test)

    # If testing existing saved credential, update its status in DB
    if not req.api_key:
        new_status = "connected" if is_valid else "invalid_key"
        repo.update_credential_status(user.id, clean_p, new_status)

    return ValidateCredentialResponse(
        valid=is_valid,
        message=message,
        available_models=models
    )


@router.post("/providers", response_model=UserAICredentialSummary, status_code=status.HTTP_201_CREATED)
async def connect_or_update_provider(
    req: ConnectProviderRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Saves an encrypted API key for the authenticated user (BYOK).
    Optionally validates credentials before saving.
    Cryptographically binds the ciphertext to the user and provider using AES-256-GCM.
    """
    _check_ai_rate_limit(user.id)
    clean_p = req.provider.strip().lower()
    if clean_p not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown AI provider '{req.provider}'."
        )

    if clean_p == "deterministic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The deterministic engine is built-in and does not require credentials."
        )

    clean_key = (req.api_key or "").strip()
    if clean_key and all(ch in "•●*.\t " for ch in clean_key):
        clean_key = ""
    clean_url = (req.base_url or "").strip() if req.base_url else None
    clean_model = (req.selected_model or "").strip() if req.selected_model else None

    # If key is empty, check if existing record exists (e.g. updating model or base_url only)
    existing_rec = repo.get_credential_record(user.id, clean_p)
    if not clean_key and clean_p != "ollama":
        if not existing_rec:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"API key is required to connect {SUPPORTED_PROVIDERS[clean_p]['name']}."
            )
        try:
            clean_key = decrypt_api_key(existing_rec.encrypted_api_key, user.id, clean_p)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not decrypt existing credentials to update provider."
            )

    # Ollama requires SSRF URL validation
    if clean_p == "ollama" and clean_url:
        try:
            clean_url = validate_outbound_url(clean_url)
        except SSRFValidationError as ssrf_err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(ssrf_err)
            )

    # Optional Pre-Save Validation
    status_label = "connected"
    if req.validate_first:
        is_valid, message, live_models = await _dispatch_validation(clean_p, clean_key, clean_url)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Validation failed: {message}"
            )
        # Auto-bind to the best live discovered model if user hasn't chosen one or chose an invalid one
        if live_models:
            if not clean_model or clean_model not in live_models:
                clean_model = live_models[0]

    # Encrypt the API key at rest
    # For Ollama without key, store a dummy or empty key encrypted
    key_for_storage = clean_key if clean_key else "ollama_endpoint_no_key"
    try:
        encrypted_key = encrypt_api_key(key_for_storage, user.id, clean_p)
    except Exception as enc_err:
        logger.error(f"Encryption failed for user={user.id}, provider={clean_p}: {enc_err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to encrypt API key securely."
        )

    key_hint = mask_api_key(clean_key) if clean_key else (clean_url or "Local Host")

    # Save to database
    summary = repo.upsert_credential(
        user_id=user.id,
        provider=clean_p,
        encrypted_api_key=encrypted_key,
        key_hint=key_hint,
        base_url=clean_url,
        selected_model=clean_model,
        status=status_label
    )

    # Automatically set newly connected or updated provider as active preference
    repo.upsert_preference(
        user_id=user.id,
        preferred_provider=clean_p,
        preferred_model=clean_model,
        fallback_to_deterministic=True
    )

    return summary


@router.delete("/providers/{provider}")
async def disconnect_provider(
    provider: str,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Disconnects and permanently removes an AI provider credential for the current user.
    If the removed provider was preferred, automatically resets preference to the built-in deterministic engine.
    """
    clean_p = provider.strip().lower()
    if clean_p not in SUPPORTED_PROVIDERS or clean_p == "deterministic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot remove provider '{provider}'."
        )

    deleted = repo.delete_credential(user.id, clean_p)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No configured credentials found for provider '{clean_p}'."
        )

    return {
        "success": True,
        "message": f"{SUPPORTED_PROVIDERS[clean_p]['name']} successfully disconnected. Reverted to built-in deterministic engine."
    }


@router.put("/preference", response_model=UserAIPreferenceRecord)
async def update_user_ai_preference(
    req: UpdatePreferenceRequest,
    user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Updates the authenticated user's preferred AI provider, model, and fallback strategy.
    Guarantees that a user cannot set a preferred provider without having a valid configuration for it.
    """
    clean_p = req.preferred_provider.strip().lower()
    if clean_p not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider '{req.preferred_provider}'."
        )

    # If not deterministic, ensure user has configured this provider
    if clean_p != "deterministic":
        cred = repo.get_credential_record(user.id, clean_p)
        has_dev_key = (not settings.is_production) and (
            (clean_p == "groq" and settings.GROQ_API_KEY and not settings.GROQ_API_KEY.startswith("your_")) or
            (clean_p == "gemini" and settings.GEMINI_API_KEY and not settings.GEMINI_API_KEY.startswith("your_"))
        )
        if not cred and not has_dev_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot set {SUPPORTED_PROVIDERS[clean_p]['name']} as preferred because no API key is configured. Please connect the provider first."
            )

    updated_pref = repo.upsert_preference(
        user_id=user.id,
        preferred_provider=clean_p,
        preferred_model=req.preferred_model,
        fallback_to_deterministic=req.fallback_to_deterministic
    )
    return updated_pref
