"""
test_ai_byok_api.py — Integration and security tests for AI BYOK management endpoints.
Verifies multi-user isolation, credential validation, masked key hints, preference updates, and SSRF prevention.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db.database import get_connection, init_db
from app.auth.crypto import hash_password, generate_id, generate_session_token
from app.ai.ssrf import validate_outbound_url, SSRFValidationError

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
        json={"provider": "openai", "api_key": "sk-proj-alice-secret-key-12345", "validate_first": False},
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
