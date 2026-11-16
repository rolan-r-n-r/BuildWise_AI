"""
execution_resolver.py — Centralized Execution Strategy Resolver for BuildWise Hybrid AI Architecture.
Resolves whether an operation should run on the built-in deterministic engine or a user's BYOK AI provider.
Guarantees zero-key instant usage, secure key decryption, and intelligent capability-aware fallback.
"""
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple
from pydantic import BaseModel

from app.auth.models import AuthenticatedUser
from app.db.ai_credential_repository import AICredentialRepository
from app.services.ai_crypto import decrypt_api_key, CredentialDecryptionError
from app.ai.base_adapter import BaseExplanationAdapter
from app.ai.mock_adapter import MockExplanationAdapter
from app.ai.errors import classify_provider_error, ProviderErrorCode, ProviderErrorInfo
from app.ai import get_ai_adapter
from app.config import settings

logger = logging.getLogger(__name__)


class ExecutionPlan(BaseModel):
    execution_mode: str  # "deterministic" | "byok_ai"
    provider: str        # "deterministic", "groq", "gemini", "openai", "anthropic", "ollama"
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    is_developer_fallback: bool = False


# Supported operations and their deterministic capability
OPERATION_DETERMINISTIC_SUPPORT: Dict[str, bool] = {
    "feasibility_analysis": True,      # Supported by MockExplanationAdapter + civil calculation core
    "room_program_synthesis": True,    # Supported by _generate_mock_program + FALLBACK_PROGRAMS
    "requirements_parsing": True,      # Supported by parse_client_requirements_fallback
    "floorplan_advisory": True,        # Supported with narrative=None and deterministic reasons
    "floorplan_remediation": True,     # 100% deterministic re-solving engine
    "layout_critic": True,             # Supported by architectural sanity rule checks
    "placement_reasoner": True,        # Supported by Knowledge Base (get_kb_default_placement)
}


class ExecutionResolver:
    """
    Central service that decides and prepares the execution strategy for any AI/Deterministic operation.
    """
    def __init__(self, repo: Optional[AICredentialRepository] = None):
        self.repo = repo or AICredentialRepository()

    def resolve_plan(
        self,
        user: Optional[AuthenticatedUser] = None,
        requested_provider: Optional[str] = None,
        requested_model: Optional[str] = None,
    ) -> ExecutionPlan:
        """
        Resolves the appropriate execution plan based on user identity, user preferences,
        available BYOK credentials, and explicit request parameters.
        """
        # 1. Anonymous user -> Always deterministic engine
        if not user or not user.id:
            # Check if dev environment has explicitly configured developer keys for testing
            req_p = (requested_provider or "").strip().lower()
            if not settings.is_production and req_p in ("groq", "gemini"):
                dev_key = settings.GROQ_API_KEY if req_p == "groq" else settings.GEMINI_API_KEY
                if dev_key and not dev_key.startswith("your_"):
                    return ExecutionPlan(
                        execution_mode="byok_ai",
                        provider=req_p,
                        model=requested_model or (settings.GROQ_MODEL if req_p == "groq" else "gemini-2.0-flash"),
                        api_key=dev_key,
                        is_developer_fallback=True
                    )
            return ExecutionPlan(
                execution_mode="deterministic",
                provider="deterministic",
                model="built-in-rules",
                fallback_used=False
            )

        # 2. Authenticated user: Load user's preference and credentials
        user_id = user.id
        pref = self.repo.get_preference(user_id)

        target_provider = (
            requested_provider
            or (pref.preferred_provider if pref.preferred_provider != "deterministic" else None)
        )

        # Normalize target provider
        clean_target = (target_provider or "deterministic").strip().lower()

        # If user explicitly selected deterministic or has no provider set
        if clean_target in ("deterministic", "mock", "none"):
            return ExecutionPlan(
                execution_mode="deterministic",
                provider="deterministic",
                model="built-in-rules",
                fallback_used=False
            )

        # 3. Look up user's encrypted BYOK credential
        cred = self.repo.get_credential_record(user_id, clean_target)
        if not cred:
            # In development only, if no user key exists, allow environment key with explicit note
            if not settings.is_production and clean_target in ("groq", "gemini"):
                dev_key = settings.GROQ_API_KEY if clean_target == "groq" else settings.GEMINI_API_KEY
                if dev_key and not dev_key.startswith("your_"):
                    return ExecutionPlan(
                        execution_mode="byok_ai",
                        provider=clean_target,
                        model=requested_model or (settings.GROQ_MODEL if clean_target == "groq" else "gemini-2.0-flash"),
                        api_key=dev_key,
                        is_developer_fallback=True
                    )

            # No credential configured for this user -> fallback to deterministic
            return ExecutionPlan(
                execution_mode="deterministic",
                provider="deterministic",
                model="built-in-rules",
                fallback_used=True,
                fallback_reason=f"No API key configured for {clean_target.title()}. Using built-in deterministic engine."
            )

        # If provider status is known to be invalid, still try or fallback
        if cred.status == "invalid_key":
            return ExecutionPlan(
                execution_mode="deterministic",
                provider="deterministic",
                model="built-in-rules",
                fallback_used=True,
                fallback_reason=f"{clean_target.title()} API key is marked invalid. Please update credentials in Settings."
            )

        # 4. Decrypt credential
        try:
            decrypted_key = decrypt_api_key(cred.encrypted_api_key, user_id, clean_target)
        except CredentialDecryptionError as dec_err:
            logger.error(f"Decryption failure for user={user_id}, provider={clean_target}: {dec_err}")
            self.repo.update_credential_status(user_id, clean_target, "error")
            return ExecutionPlan(
                execution_mode="deterministic",
                provider="deterministic",
                model="built-in-rules",
                fallback_used=True,
                fallback_reason=f"Failed to decrypt credentials for {clean_target.title()}. Re-saving the key may resolve this."
            )

        selected_model = requested_model or cred.selected_model or pref.preferred_model
        return ExecutionPlan(
            execution_mode="byok_ai",
            provider=clean_target,
            model=selected_model,
            api_key=decrypted_key,
            base_url=cred.base_url,
            fallback_used=False
        )

    def get_adapter(self, plan: ExecutionPlan) -> BaseExplanationAdapter:
        """Instantiates the appropriate explanation adapter bound to the execution plan's credentials."""
        # Check if app.main.get_ai_adapter was monkeypatched/mocked in tests
        import sys
        main_mod = sys.modules.get("app.main")
        if main_mod and hasattr(main_mod, "get_ai_adapter"):
            main_factory = getattr(main_mod, "get_ai_adapter")
            if main_factory is not get_ai_adapter:
                try:
                    return main_factory(plan.provider)
                except TypeError:
                    return main_factory(
                        provider=plan.provider,
                        api_key=plan.api_key,
                        model=plan.model,
                        base_url=plan.base_url
                    )

        if plan.execution_mode == "deterministic" or plan.provider == "deterministic":
            return MockExplanationAdapter()
        return get_ai_adapter(
            provider=plan.provider,
            api_key=plan.api_key,
            model=plan.model,
            base_url=plan.base_url
        )

    async def execute_explanation(
        self,
        analysis_data: Dict[str, Any],
        user: Optional[AuthenticatedUser] = None,
        requested_provider: Optional[str] = None,
        requested_model: Optional[str] = None,
    ) -> Tuple[str, List[str], Dict[str, Any]]:
        """
        Executes engineering summary generation with automated error classification and deterministic fallback.
        """
        plan = self.resolve_plan(user, requested_provider, requested_model)
        adapter = self.get_adapter(plan)

        # If already resolved to deterministic, execute directly
        if plan.execution_mode == "deterministic":
            summary, recs, meta = await adapter.generate_explanation(analysis_data)
            meta["execution_mode"] = "deterministic"
            meta["provider_requested"] = requested_provider or "deterministic"
            if (requested_provider or "").lower() == "mock":
                meta["provider_used"] = "mock"
            else:
                meta["provider_used"] = "deterministic_engine"
            meta["fallback_used"] = plan.fallback_used
            if plan.fallback_reason:
                meta["fallback_reason"] = plan.fallback_reason
            return summary, recs, meta

        # Execute BYOK AI provider
        try:
            summary, recs, meta = await adapter.generate_explanation(analysis_data)
            # If the adapter itself internally triggered a mock fallback:
            if meta.get("provider_used", "").startswith("mock_fallback"):
                fallback_reason = meta.get("fallback_reason") or "AI provider invocation failed"
                meta["execution_mode"] = "deterministic"
                meta["fallback_used"] = True
                meta["fallback_reason"] = fallback_reason
                meta["provider_requested"] = plan.provider
                # Check if it was an auth failure to update DB
                if user and ("401" in fallback_reason or "invalid" in fallback_reason.lower()):
                    self.repo.update_credential_status(user.id, plan.provider, "invalid_key")
            else:
                meta["execution_mode"] = "byok_ai"
                meta["provider_requested"] = plan.provider
                meta["fallback_used"] = False
                if plan.model:
                    meta["model"] = plan.model
            return summary, recs, meta
        except Exception as exc:
            err_info = classify_provider_error(exc)
            logger.warning(f"Provider {plan.provider} failed: {err_info.message} ({err_info.code})")

            # Update DB status if credential was invalid
            if user and err_info.is_credential_failure:
                self.repo.update_credential_status(user.id, plan.provider, "invalid_key")

            # Fallback to deterministic mock
            mock_adapter = MockExplanationAdapter()
            summary, recs, meta = await mock_adapter.generate_explanation(analysis_data)
            meta["execution_mode"] = "deterministic"
            meta["provider_requested"] = plan.provider
            meta["provider_used"] = "deterministic_fallback"
            meta["fallback_used"] = True
            meta["fallback_reason"] = err_info.message
            meta["error_code"] = err_info.code
            return summary, recs, meta
