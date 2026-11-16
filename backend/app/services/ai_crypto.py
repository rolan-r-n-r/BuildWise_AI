"""
ai_crypto.py — Cryptographic service for Bring Your Own API Key (BYOK) credential storage.
Uses AES-256-GCM authenticated encryption with user and provider contextual binding.
"""
import os
import hashlib
import logging
from typing import Optional

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTOGRAPHY = True
except ImportError:
    AESGCM = None  # type: ignore
    HAS_CRYPTOGRAPHY = False

from app.config import settings

logger = logging.getLogger(__name__)

class CredentialDecryptionError(Exception):
    """Raised when an encrypted API key cannot be authenticated or decrypted."""
    pass


def _derive_encryption_key() -> bytes:
    """
    Derives a consistent 256-bit (32-byte) AES key from settings.AI_CREDENTIAL_ENCRYPTION_KEY.
    Uses SHA-256 with a domain-separated salt to guarantee exact 32-byte key size regardless
    of passphrase format.
    """
    raw_secret = getattr(
        settings,
        "AI_CREDENTIAL_ENCRYPTION_KEY",
        "buildwise-byok-default-dev-encryption-key-min-32-bytes"
    ) or "buildwise-byok-default-dev-encryption-key-min-32-bytes"
    
    salt = b"buildwise-byok-encryption-v1"
    # Derive key via HKDF or SHA-256 domain-separation
    return hashlib.sha256(salt + raw_secret.encode("utf-8")).digest()


def encrypt_api_key(api_key: str, user_id: str, provider: str) -> str:
    """
    Encrypts an API key using AES-256-GCM.
    Cryptographically binds the ciphertext to the user_id and provider using GCM Associated Data (AAD)
    to prevent ciphertext transplantation across accounts or provider slots.
    
    Format: v1:{nonce_hex}:{ciphertext_with_tag_hex}
    """
    clean_key = (api_key or "").strip()
    if not clean_key:
        raise ValueError("Cannot encrypt an empty API key")
    
    if not HAS_CRYPTOGRAPHY or AESGCM is None:
        raise RuntimeError(
            "The 'cryptography' package is required for BYOK API key encryption. "
            "Please install it using: pip install cryptography"
        )
    
    key_bytes = _derive_encryption_key()
    aesgcm = AESGCM(key_bytes)
    
    # 96-bit (12-byte) cryptographically secure random nonce
    nonce = os.urandom(12)
    
    # Associated Data binds this payload to the specific user and provider
    aad = f"user:{user_id.strip()}:provider:{provider.strip().lower()}".encode("utf-8")
    
    ciphertext = aesgcm.encrypt(nonce, clean_key.encode("utf-8"), aad)
    return f"v1:{nonce.hex()}:{ciphertext.hex()}"


def decrypt_api_key(encrypted_str: str, user_id: str, provider: str) -> str:
    """
    Decrypts an API key using AES-256-GCM.
    Validates authenticity tag and user/provider binding. Fails safely on tampering or mismatched context.
    """
    if not encrypted_str or not encrypted_str.startswith("v1:"):
        raise CredentialDecryptionError("Invalid or unsupported ciphertext format.")
    
    parts = encrypted_str.split(":")
    if len(parts) != 3:
        raise CredentialDecryptionError("Malformed ciphertext structure.")
    
    _, nonce_hex, ct_hex = parts
    try:
        nonce = bytes.fromhex(nonce_hex)
        ciphertext = bytes.fromhex(ct_hex)
    except ValueError as hex_err:
        raise CredentialDecryptionError(f"Corrupted ciphertext hex encoding: {hex_err}") from hex_err
    
    if not HAS_CRYPTOGRAPHY or AESGCM is None:
        raise RuntimeError(
            "The 'cryptography' package is required for BYOK API key decryption. "
            "Please install it using: pip install cryptography"
        )
    
    key_bytes = _derive_encryption_key()
    aesgcm = AESGCM(key_bytes)
    aad = f"user:{user_id.strip()}:provider:{provider.strip().lower()}".encode("utf-8")
    
    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, aad)
        return plaintext_bytes.decode("utf-8")
    except Exception as exc:
        logger.warning(f"Failed to decrypt BYOK credential for user={user_id}, provider={provider}: {exc}")
        raise CredentialDecryptionError(
            "Failed to decrypt credential. The key may have been encrypted with a different secret or tampered with."
        ) from exc


def mask_api_key(api_key: str) -> str:
    """
    Generates a secure display hint for an API key without revealing the secret.
    Examples:
      'gsk_mock_groq_api_test_key_sample_1234567890WtBe' -> 'gsk_...WtBe'
      'sk-mock-sample-openai-key-sample-cdef' -> 'sk-m...cdef'
    """
    clean = (api_key or "").strip()
    if not clean:
        return ""
    if len(clean) <= 8:
        return "***"
    if clean.startswith("gsk_") and len(clean) >= 12:
        return f"gsk_...{clean[-4:]}"
    if clean.startswith("sk-") and len(clean) >= 12:
        return f"{clean[:4]}...{clean[-4:]}"
    if len(clean) >= 10:
        return f"{clean[:4]}...{clean[-4:]}"
    return f"{clean[:2]}...{clean[-2:]}"
