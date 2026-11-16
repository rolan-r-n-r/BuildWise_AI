"""
test_ai_crypto.py — Security tests for BYOK API key authenticated encryption at rest (AES-256-GCM).
"""
import pytest
from app.services.ai_crypto import (
    encrypt_api_key,
    decrypt_api_key,
    mask_api_key,
    CredentialDecryptionError,
)


def test_encryption_and_decryption_roundtrip():
    api_key = "gsk_live_test_secret_key_1234567890abcdef"
    user_id = "user_test_abc123"
    provider = "groq"

    encrypted = encrypt_api_key(api_key, user_id, provider)
    assert encrypted.startswith("v1:")
    assert api_key not in encrypted  # Key is encrypted, never plaintext

    decrypted = decrypt_api_key(encrypted, user_id, provider)
    assert decrypted == api_key


def test_cryptographic_binding_prevents_cross_user_transplantation():
    """An encrypted key belonging to User A must fail to decrypt if requested as User B."""
    api_key = "sk-mock-test-secret-openai-key"
    user_a = "user_alice_1"
    user_b = "user_bob_2"
    provider = "openai"

    encrypted_for_alice = encrypt_api_key(api_key, user_a, provider)

    with pytest.raises(CredentialDecryptionError):
        decrypt_api_key(encrypted_for_alice, user_b, provider)


def test_cryptographic_binding_prevents_cross_provider_transplantation():
    """An encrypted key for Groq must fail to decrypt if requested as Gemini."""
    api_key = "AIzaSyTest_Gemini_Secret_Key"
    user = "user_charlie"

    encrypted_for_gemini = encrypt_api_key(api_key, user, "gemini")

    with pytest.raises(CredentialDecryptionError):
        decrypt_api_key(encrypted_for_gemini, user, "groq")


def test_tampered_ciphertext_fails_decryption():
    """Any byte tampering in ciphertext or tag must cause authentication failure."""
    api_key = "anthropic_test_key_sk_ant_12345"
    user = "user_dan"
    provider = "anthropic"

    encrypted = encrypt_api_key(api_key, user, provider)
    parts = encrypted.split(":")
    # Tamper with the last byte of ciphertext
    corrupted_ct = parts[2][:-2] + ("00" if parts[2][-2:] != "00" else "ff")
    tampered = f"v1:{parts[1]}:{corrupted_ct}"

    with pytest.raises(CredentialDecryptionError):
        decrypt_api_key(tampered, user, provider)


def test_empty_key_rejected():
    with pytest.raises(ValueError):
        encrypt_api_key("", "user_1", "groq")


def test_key_masking_never_exposes_full_key():
    groq_key = "gsk_mock_groq_api_test_key_sample_1234567890WtBe"
    masked_groq = mask_api_key(groq_key)
    assert masked_groq.startswith("gsk_...")
    assert masked_groq.endswith("tBe")
    assert "api_test_key_sample" not in masked_groq

    openai_key = "sk-mock-1234567890abcdef123456"
    masked_openai = mask_api_key(openai_key)
    assert masked_openai.startswith("sk-m...")
    assert masked_openai.endswith("3456")

    short_key = "abc12"
    assert mask_api_key(short_key) == "***"
