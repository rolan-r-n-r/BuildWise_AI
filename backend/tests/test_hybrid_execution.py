"""
test_hybrid_execution.py — Comprehensive tests for the Hybrid AI Architecture execution scenarios.
Verifies Scenarios A, B, C, D, E of the Hybrid BYOK specification.
"""
import pytest
from app.auth.models import AuthenticatedUser
from app.ai.execution_resolver import ExecutionResolver, ExecutionPlan
from app.db.ai_credential_repository import AICredentialRepository
from app.db.database import get_connection, init_db
from app.services.ai_crypto import encrypt_api_key
import httpx


@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    now = "2026-11-16T12:00:00Z"
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user (id, name, email, emailVerified, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?)",
            ("user_hybrid_1", "Hybrid Tester", "hybrid@buildwise.ai", 1, now, now)
        )
        conn.commit()


@pytest.mark.asyncio
async def test_scenario_a_user_without_key_uses_deterministic_engine():
    """Scenario A: User has not configured an API key -> uses built-in deterministic engine without warnings."""
    resolver = ExecutionResolver()
    user = AuthenticatedUser(
        id="user_hybrid_1",
        name="Hybrid Tester",
        email="hybrid@buildwise.ai",
        email_verified=True,
        image=None,
        session_id="sess_h1",
        token="tok_h1"
    )

    plan = resolver.resolve_plan(user=user)
    assert plan.execution_mode == "deterministic"
    assert plan.provider == "deterministic"
    assert plan.fallback_used is False

    mock_analysis_data = {
        "overall_suitability_score": 75.0,
        "suitability_verdict": "Suitable",
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "formatted_address": "Bengaluru, Karnataka",
        "built_up_area_sqft": 2000.0,
        "quality_grade": "standard",
        "floors": 1,
    }

    summary, recs, meta = await resolver.execute_explanation(mock_analysis_data, user=user)
    assert meta["execution_mode"] == "deterministic"
    assert meta["provider_used"] == "deterministic_engine"
    assert meta["fallback_used"] is False
    assert len(summary) > 20
    assert len(recs) >= 1


@pytest.mark.asyncio
async def test_scenario_b_user_with_configured_provider_executes_ai(monkeypatch):
    """Scenario B: User has configured AI provider -> executes with user's own credentials."""
    repo = AICredentialRepository()
    user_id = "user_hybrid_1"
    user = AuthenticatedUser(
        id=user_id,
        name="Hybrid Tester",
        email="hybrid@buildwise.ai",
        email_verified=True,
        image=None,
        session_id="sess_h1",
        token="tok_h1"
    )

    encrypted_key = encrypt_api_key("sk-proj-byok-secret-user-key-9999", user_id, "openai")
    repo.upsert_credential(
        user_id=user_id,
        provider="openai",
        encrypted_api_key=encrypted_key,
        key_hint="sk-p...9999",
        selected_model="gpt-4o-mini"
    )
    repo.upsert_preference(user_id=user_id, preferred_provider="openai", preferred_model="gpt-4o-mini")

    resolver = ExecutionResolver(repo=repo)
    plan = resolver.resolve_plan(user=user)
    assert plan.execution_mode == "byok_ai"
    assert plan.provider == "openai"
    assert plan.api_key == "sk-proj-byok-secret-user-key-9999"
    assert plan.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_scenario_c_provider_failure_falls_back_to_deterministic_with_disclosure(monkeypatch):
    """Scenario C: Configured provider fails (e.g. rate limit / network error) -> falls back to deterministic."""
    repo = AICredentialRepository()
    user_id = "user_hybrid_1"
    user = AuthenticatedUser(
        id=user_id,
        name="Hybrid Tester",
        email="hybrid@buildwise.ai",
        email_verified=True,
        image=None,
        session_id="sess_h1",
        token="tok_h1"
    )

    encrypted_key = encrypt_api_key("gsk_failing_key_12345", user_id, "groq")
    repo.upsert_credential(
        user_id=user_id,
        provider="groq",
        encrypted_api_key=encrypted_key,
        key_hint="gsk_...2345",
        selected_model="llama-3.3-70b-versatile"
    )
    repo.upsert_preference(user_id=user_id, preferred_provider="groq")

    # Mock Groq to simulate HTTP 429 rate limit
    async def mock_groq_fail(self, analysis_data):
        raise httpx.HTTPStatusError(
            "Rate limit exceeded",
            request=httpx.Request("POST", "https://api.groq.com/v1"),
            response=httpx.Response(429, text='{"error": {"message": "Rate limit reached"}}')
        )

    monkeypatch.setattr("app.ai.groq_adapter.GroqExplanationAdapter.generate_explanation", mock_groq_fail)

    resolver = ExecutionResolver(repo=repo)
    mock_analysis_data = {
        "overall_suitability_score": 80.0,
        "suitability_verdict": "Suitable",
        "coordinates": {"latitude": 13.0, "longitude": 80.0},
        "formatted_address": "Chennai, Tamil Nadu",
    }

    summary, recs, meta = await resolver.execute_explanation(mock_analysis_data, user=user)
    assert meta["execution_mode"] == "deterministic"
    assert meta["provider_requested"] == "groq"
    assert meta["provider_used"] == "deterministic_fallback"
    assert meta["fallback_used"] is True
    assert "rate limit" in meta["fallback_reason"].lower()


@pytest.mark.asyncio
async def test_scenario_d_user_removes_key_returns_to_deterministic():
    """Scenario D: User removes their API key -> immediately returns to deterministic execution."""
    repo = AICredentialRepository()
    user_id = "user_hybrid_1"
    user = AuthenticatedUser(
        id=user_id,
        name="Hybrid Tester",
        email="hybrid@buildwise.ai",
        email_verified=True,
        image=None,
        session_id="sess_h1",
        token="tok_h1"
    )

    # Delete credentials
    repo.delete_credential(user_id, "groq")
    repo.delete_credential(user_id, "openai")

    resolver = ExecutionResolver(repo=repo)
    plan = resolver.resolve_plan(user=user)
    assert plan.execution_mode == "deterministic"
    assert plan.provider == "deterministic"
    assert plan.fallback_used is False


@pytest.mark.asyncio
async def test_scenario_e_multiple_providers_preferred_selection():
    """Scenario E: User has multiple providers configured -> respects user's preferred choice."""
    repo = AICredentialRepository()
    user_id = "user_hybrid_1"
    user = AuthenticatedUser(
        id=user_id,
        name="Hybrid Tester",
        email="hybrid@buildwise.ai",
        email_verified=True,
        image=None,
        session_id="sess_h1",
        token="tok_h1"
    )

    # Configure Groq and Anthropic
    repo.upsert_credential(
        user_id=user_id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("gsk_key_1", user_id, "groq"),
        key_hint="gsk_...key1"
    )
    repo.upsert_credential(
        user_id=user_id,
        provider="anthropic",
        encrypted_api_key=encrypt_api_key("sk-ant-key_2", user_id, "anthropic"),
        key_hint="sk-a...key2"
    )

    # User chooses Anthropic as preferred
    repo.upsert_preference(user_id=user_id, preferred_provider="anthropic", preferred_model="claude-3-5-haiku-20241022")

    resolver = ExecutionResolver(repo=repo)
    plan = resolver.resolve_plan(user=user)
    assert plan.provider == "anthropic"
    assert plan.api_key == "sk-ant-key_2"
    assert plan.model == "claude-3-5-haiku-20241022"


@pytest.mark.asyncio
async def test_anonymous_user_fallback_with_invalid_message_no_crash():
    """
    Regression test for operator precedence bug in execution_resolver.py:
    Anonymous user (user=None) encountering an adapter fallback containing 'invalid'
    must not crash with AttributeError: 'NoneType' object has no attribute 'id'.
    """
    resolver = ExecutionResolver()
    mock_analysis_data = {
        "overall_suitability_score": 80.0,
        "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
        "built_up_area_sqft": 1800.0,
        "quality_grade": "standard",
        "floors": 1,
    }

    # Request provider directly without authenticated user
    summary, recs, meta = await resolver.execute_explanation(
        mock_analysis_data,
        user=None,
        requested_provider="groq"
    )
    # Must cleanly return deterministic fallback or execution without throwing exception
    assert meta["execution_mode"] in ("deterministic", "byok_ai")
    assert len(summary) > 0


@pytest.mark.asyncio
async def test_ollama_adapter_honors_configured_model():
    """Verifies that OllamaExplanationAdapter uses its configured model parameter."""
    from app.ai.ollama_adapter import OllamaExplanationAdapter
    adapter = OllamaExplanationAdapter(base_url="http://127.0.0.1:11434", model="mistral:latest")
    assert adapter.model == "mistral:latest"


@pytest.mark.asyncio
async def test_gemini_adapter_uses_modern_model_and_dynamic_discovery(monkeypatch):
    """
    Verifies that Gemini adapter defaults to modern gemini-2.5-flash
    and avoids deprecated models.
    """
    from app.ai.gemini_adapter import GeminiExplanationAdapter, validate_gemini_key

    adapter = GeminiExplanationAdapter(api_key="AIzaSyDummyKeyForTesting", model="gemini-2.5-flash")
    assert adapter.model == "gemini-2.5-flash"

    # Test key validation model parser
    class MockResponse:
        status_code = 200
        def json(self):
            return {
                "models": [
                    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
                ]
            }

    class MockClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def get(self, url):
            return MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: MockClient())

    is_valid, msg, live_models = await validate_gemini_key("AIzaSyDummyKeyForTesting")
    assert is_valid is True
    assert "gemini-2.5-flash" in live_models
    assert "gemini-2.5-pro" in live_models
    assert "embedding-001" not in live_models
    assert live_models[0] == "gemini-2.5-flash"
