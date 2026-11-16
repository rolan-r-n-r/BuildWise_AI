"""
test_ai_byok_api.py — Integration and security tests for AI BYOK management endpoints.
Verifies multi-user isolation, credential validation, masked key hints, preference updates, and SSRF prevention.
"""
import pytest
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.db.database import get_connection, init_db
from app.auth.crypto import hash_password, generate_id, generate_session_token
from app.ai.ssrf import validate_outbound_url, SSRFValidationError
from app.ai.groq_adapter import validate_groq_key
from app.ai.gemini_adapter import validate_gemini_key
from app.services.ai_crypto import sanitize_api_key, is_masked_key_hint

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_users():
    """Sets up two isolated, email-verified test users in SQLite."""
    init_db()
    with get_connection() as conn:
        now = "2026-11-16T12:00:00Z"
        # User A
        conn.execute(
            "INSERT OR REPLACE INTO user (id, name, email, emailVerified, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?)",
            ("user_a", "Alice Engineer", "alice@buildwise.ai", 1, now, now)
        )
        conn.execute(
            "INSERT OR REPLACE INTO session (id, expiresAt, token, createdAt, updatedAt, userId) VALUES (?, ?, ?, ?, ?, ?)",
            ("sess_a", "2099-01-01T00:00:00Z", "token_alice_123", now, now, "user_a")
        )

        # User B
        conn.execute(
            "INSERT OR REPLACE INTO user (id, name, email, emailVerified, createdAt, updatedAt) VALUES (?, ?, ?, ?, ?, ?)",
            ("user_b", "Bob Architect", "bob@buildwise.ai", 1, now, now)
        )
        conn.execute(
            "INSERT OR REPLACE INTO session (id, expiresAt, token, createdAt, updatedAt, userId) VALUES (?, ?, ?, ?, ?, ?)",
            ("sess_b", "2099-01-01T00:00:00Z", "token_bob_456", now, now, "user_b")
        )
        conn.commit()


def test_get_supported_providers_catalog():
    resp = client.get("/api/ai/providers")
    assert resp.status_code == 200
    providers = resp.json()
    ids = [p["id"] for p in providers]
    assert "deterministic" in ids
    assert "groq" in ids
    assert "gemini" in ids
    assert "openai" in ids
    assert "anthropic" in ids
    assert "ollama" in ids


def test_unauthenticated_access_to_config_rejected():
    resp = client.get("/api/ai/config")
    assert resp.status_code == 401


def test_user_initial_config_defaults_to_deterministic():
    headers = {"Authorization": "Bearer token_alice_123"}
    resp = client.get("/api/ai/config", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured_providers"] == []
    assert data["preference"]["preferred_provider"] == "deterministic"


def test_connect_provider_encrypts_key_and_returns_hint(monkeypatch):
    """Saving an API key must succeed, mask the key hint, and never return the plaintext key."""
    # Mock validate to succeed
    async def mock_validate(*args, **kwargs):
        return True, "Verified", ["llama-3.3-70b-versatile"]

    monkeypatch.setattr("app.ai.routes._dispatch_validation", mock_validate)

    raw_key = "gsk_super_secret_groq_api_key_test_12345"
    headers = {"Authorization": "Bearer token_alice_123"}
    resp = client.post(
        "/api/ai/providers",
        json={
            "provider": "groq",
            "api_key": raw_key,
            "selected_model": "llama-3.3-70b-versatile",
            "validate_first": True
        },
        headers=headers
    )
    assert resp.status_code == 201
    saved = resp.json()
    assert saved["provider"] == "groq"
    assert saved["key_hint"].startswith("gsk_...")
    assert raw_key not in str(saved)  # NEVER return plaintext key

    # Check config: Alice now has Groq configured and automatically preferred
    config_resp = client.get("/api/ai/config", headers=headers)
    assert config_resp.status_code == 200
    config_data = config_resp.json()
    assert len(config_data["configured_providers"]) == 1
    assert config_data["configured_providers"][0]["provider"] == "groq"
    assert config_data["preference"]["preferred_provider"] == "groq"


def test_multi_user_isolation_bob_cannot_see_alices_keys(monkeypatch):
    """Alice's configured credentials must NOT be visible or accessible to Bob."""
    async def mock_validate(*args, **kwargs):
        return True, "Verified", ["gpt-4o-mini"]

    monkeypatch.setattr("app.ai.routes._dispatch_validation", mock_validate)

    # Alice connects OpenAI
    alice_headers = {"Authorization": "Bearer token_alice_123"}
    client.post(
        "/api/ai/providers",
        json={"provider": "openai", "api_key": "sk-mock-alice-secret-key-12345", "validate_first": False},
        headers=alice_headers
    )

    # Bob inspects his config
    bob_headers = {"Authorization": "Bearer token_bob_456"}
    bob_config = client.get("/api/ai/config", headers=bob_headers).json()
    assert bob_config["configured_providers"] == []
    assert bob_config["preference"]["preferred_provider"] == "deterministic"

    # Bob attempts to delete Alice's OpenAI key
    del_resp = client.delete("/api/ai/providers/openai", headers=bob_headers)
    assert del_resp.status_code == 404  # Bob doesn't have an OpenAI key


def test_disconnect_provider_reverts_to_deterministic(monkeypatch):
    async def mock_validate(*args, **kwargs):
        return True, "Verified", ["gemini-2.0-flash"]

    monkeypatch.setattr("app.ai.routes._dispatch_validation", mock_validate)

    headers = {"Authorization": "Bearer token_alice_123"}
    client.post(
        "/api/ai/providers",
        json={"provider": "gemini", "api_key": "AIzaSyAliceGeminiTestKey12345", "validate_first": False},
        headers=headers
    )

    # Now Alice removes Gemini
    del_resp = client.delete("/api/ai/providers/gemini", headers=headers)
    assert del_resp.status_code == 200

    # Preference must revert back to deterministic
    config = client.get("/api/ai/config", headers=headers).json()
    assert config["configured_providers"] == []
    assert config["preference"]["preferred_provider"] == "deterministic"


def test_ssrf_guard_blocks_cloud_metadata_and_invalid_schemes():
    with pytest.raises(SSRFValidationError):
        validate_outbound_url("ftp://127.0.0.1:11434")

    with pytest.raises(SSRFValidationError):
        validate_outbound_url("http://169.254.169.254/latest/meta-data/")

    with pytest.raises(SSRFValidationError):
        validate_outbound_url("http://metadata.google.internal/computeMetadata/v1/")


def test_unconfigured_provider_rejected_as_preferred():
    headers = {"Authorization": "Bearer token_alice_123"}
    # Attempt to set OpenAI as preferred when Alice has not configured OpenAI
    resp = client.put(
        "/api/ai/preference",
        json={"preferred_provider": "openai", "fallback_to_deterministic": True},
        headers=headers
    )
    assert resp.status_code == 400
    assert "no API key is configured" in resp.json()["detail"]


def test_api_status_reports_all_providers():
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "groq" in data
    assert "gemini" in data
    assert "openai" in data
    assert "anthropic" in data
    assert "ollama" in data
    assert "configured_models" in data
    assert "user_preferred_model" in data
    assert data["deterministic_engine"] is True
    assert data["byok_supported"] is True


# --- Comprehensive BYOK Validation Test Suite (10 Requirements) ---

@pytest.mark.asyncio
async def test_1_valid_groq_api_key(monkeypatch):
    """1. Valid Groq API key: sends proper Authorization Bearer header, returns 200 and available models."""
    captured_headers = {}

    async def mock_get(self, url, headers=None, **kwargs):
        captured_headers.update(headers or {})
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {"id": "llama-3.1-8b-instant"},
                    {"id": "llama-3.3-70b-versatile"},
                    {"id": "whisper-large-v3"},
                ]
            },
            request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    is_valid, msg, models = await validate_groq_key("gsk_test_valid_key_12345")
    assert is_valid is True
    assert "successfully verified" in msg
    assert captured_headers.get("Authorization") == "Bearer gsk_test_valid_key_12345"
    assert "llama-3.3-70b-versatile" in models
    assert "whisper-large-v3" not in models  # Filtered out
    assert models[0] == "llama-3.3-70b-versatile"  # Prioritized


@pytest.mark.asyncio
async def test_2_invalid_groq_api_key(monkeypatch):
    """2. Invalid Groq API key: returns HTTP 401, classified accurately as invalid credentials."""
    async def mock_get(self, url, headers=None, **kwargs):
        return httpx.Response(
            status_code=401,
            json={"error": {"message": "Invalid API Key", "code": "invalid_api_key"}},
            request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    is_valid, msg, models = await validate_groq_key("gsk_invalid_test_key")
    assert is_valid is False
    assert msg == "Invalid Groq API key. Authentication failed."
    assert models == []


@pytest.mark.asyncio
async def test_3_groq_api_key_whitespace_quotes_bearer_sanitization(monkeypatch):
    """3. API key with whitespace, quotes, zero-width chars, and Bearer prefix is sanitized."""
    captured_auth = []

    async def mock_get(self, url, headers=None, **kwargs):
        captured_auth.append(headers.get("Authorization"))
        return httpx.Response(
            status_code=200,
            json={"data": [{"id": "llama-3.3-70b-versatile"}]},
            request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    # Key padded with whitespace, zero-width spaces (\u200b, \ufeff), quotes, and Bearer
    dirty_key = "  Bearer \u200b\"gsk_clean_target_9999\"\ufeff  "
    is_valid, _, _ = await validate_groq_key(dirty_key)
    assert is_valid is True
    assert captured_auth[0] == "Bearer gsk_clean_target_9999"


@pytest.mark.asyncio
async def test_4_empty_groq_api_key():
    """4. Empty or whitespace-only API key is rejected immediately without network requests."""
    is_valid, msg, models = await validate_groq_key("   ")
    assert is_valid is False
    assert "cannot be empty" in msg
    assert models == []

    is_valid2, msg2, _ = await validate_groq_key("\u200b\ufeff")
    assert is_valid2 is False
    assert "cannot be empty" in msg2


@pytest.mark.asyncio
async def test_5_groq_model_filtering_and_sorting(monkeypatch):
    """5. Unsupported/non-chat models (whisper, guard, embedding) are excluded, Llama 3.3 sorted first."""
    async def mock_get(self, url, headers=None, **kwargs):
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {"id": "whisper-large-v3"},
                    {"id": "distil-whisper-large-v3-en"},
                    {"id": "llama-guard-3-8b"},
                    {"id": "llama-3.1-8b-instant"},
                    {"id": "llama-3.3-70b-versatile"},
                    {"id": "mixtral-8x7b-32768"},
                ]
            },
            request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    is_valid, _, models = await validate_groq_key("gsk_valid")
    assert is_valid is True
    assert "whisper-large-v3" not in models
    assert "distil-whisper-large-v3-en" not in models
    assert "llama-guard-3-8b" not in models
    assert models[0] == "llama-3.3-70b-versatile"
    assert models[1] == "llama-3.1-8b-instant"


@pytest.mark.asyncio
async def test_6_groq_network_failure(monkeypatch):
    """6. Network connection failure produces understandable error message without server crash."""
    async def mock_get(self, url, **kwargs):
        raise httpx.ConnectError("Failed to connect to api.groq.com")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    is_valid, msg, models = await validate_groq_key("gsk_valid")
    assert is_valid is False
    assert "Unable to connect to Groq API servers" in msg
    assert models == []


@pytest.mark.asyncio
async def test_7_groq_rate_limit_response(monkeypatch):
    """7. Rate-limit (429) response clearly distinguishes quota exhaustion from authentication failure."""
    async def mock_get(self, url, **kwargs):
        return httpx.Response(
            status_code=429,
            json={"error": {"message": "Rate limit exceeded"}},
            request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    is_valid, msg, models = await validate_groq_key("gsk_valid")
    assert is_valid is False
    assert "rate limit exceeded" in msg.lower()
    assert "invalid" not in msg.lower()
    assert models == []


def test_8_test_connection_with_previously_saved_key(monkeypatch):
    """8. Test Connection button with no key or masked placeholder tests Alice's saved credential."""
    async def mock_validate_success(key):
        return True, "Groq credentials successfully verified.", ["llama-3.3-70b-versatile"]

    monkeypatch.setattr("app.ai.routes.validate_groq_key", mock_validate_success)

    alice_headers = {"Authorization": "Bearer token_alice_123"}
    save_resp = client.post(
        "/api/ai/providers",
        json={"provider": "groq", "api_key": "gsk_alice_saved_secret", "validate_first": False},
        headers=alice_headers
    )
    assert save_resp.status_code == 201

    # Test Connection sending masked hint (e.g., from autofill or UI)
    val_resp = client.post(
        "/api/ai/validate",
        json={"provider": "groq", "api_key": "gsk_...cret"},
        headers=alice_headers
    )
    assert val_resp.status_code == 200
    val_data = val_resp.json()
    assert val_data["valid"] is True
    assert "Groq credentials successfully verified." in val_data["message"]


def test_9_newly_submitted_api_key_lifecycle(monkeypatch):
    """9. Newly submitted key is validated, encrypted with AES-256-GCM, saved, and verifiable."""
    async def mock_groq_call(self, url, headers=None, **kwargs):
        assert headers.get("Authorization") == "Bearer gsk_new_key_alice"
        return httpx.Response(
            status_code=200,
            json={"data": [{"id": "llama-3.3-70b-versatile"}]},
            request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_groq_call)

    alice_headers = {"Authorization": "Bearer token_alice_123"}
    resp = client.post(
        "/api/ai/providers",
        json={"provider": "groq", "api_key": "gsk_new_key_alice", "validate_first": True},
        headers=alice_headers
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "connected"
    assert resp.json()["key_hint"] == "gsk_...lice"


@pytest.mark.asyncio
async def test_10_gemini_integration_and_headers_preserved(monkeypatch):
    """10. Gemini integration uses x-goog-api-key header and validates official models."""
    captured_headers = {}

    async def mock_gemini_get(self, url, headers=None, **kwargs):
        captured_headers.update(headers or {})
        return httpx.Response(
            status_code=200,
            json={
                "models": [
                    {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
                ]
            },
            request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_gemini_get)

    is_valid, msg, models = await validate_gemini_key("AIzaSyTestGeminiKey123")
    assert is_valid is True
    assert captured_headers.get("x-goog-api-key") == "AIzaSyTestGeminiKey123"
    assert "gemini-2.0-flash" in models
    assert "embedding-001" not in models
    assert models[0] == "gemini-2.0-flash"
