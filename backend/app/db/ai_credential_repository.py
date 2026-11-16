"""
ai_credential_repository.py — Data access repository for BYOK AI credentials and preferences.
Encapsulates all SQLite CRUD operations with user isolation. Never exposes encrypted keys in summaries.
"""
from datetime import datetime, timezone
import sqlite3
import uuid
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from app.db.database import get_connection


class UserAICredentialSummary(BaseModel):
    provider: str
    key_hint: str
    base_url: Optional[str] = None
    selected_model: Optional[str] = None
    status: str = "connected"
    last_validated_at: Optional[str] = None
    created_at: str
    updated_at: str


class UserAICredentialRecord(BaseModel):
    id: str
    user_id: str
    provider: str
    encrypted_api_key: str
    key_hint: str
    base_url: Optional[str] = None
    selected_model: Optional[str] = None
    status: str = "connected"
    last_validated_at: Optional[str] = None
    created_at: str
    updated_at: str


class UserAIPreferenceRecord(BaseModel):
    user_id: str
    preferred_provider: str = "deterministic"
    preferred_model: Optional[str] = None
    fallback_to_deterministic: bool = True
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AICredentialRepository:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def list_credentials(self, user_id: str) -> List[UserAICredentialSummary]:
        """Returns safe summaries of all configured AI providers for the given user."""
        clean_user = (user_id or "").strip()
        if not clean_user:
            return []

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT provider, key_hint, base_url, selected_model, status, last_validated_at, created_at, updated_at
                FROM user_ai_credentials
                WHERE user_id = ?
                ORDER BY created_at ASC
                """,
                (clean_user,)
            )
            rows = cursor.fetchall()
            return [
                UserAICredentialSummary(
                    provider=row["provider"],
                    key_hint=row["key_hint"],
                    base_url=row["base_url"],
                    selected_model=row["selected_model"],
                    status=row["status"],
                    last_validated_at=row["last_validated_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                )
                for row in rows
            ]

    def get_credential_record(self, user_id: str, provider: str) -> Optional[UserAICredentialRecord]:
        """Retrieves raw encrypted record for server-side decryption and execution."""
        clean_user = (user_id or "").strip()
        clean_provider = (provider or "").strip().lower()
        if not clean_user or not clean_provider:
            return None

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT id, user_id, provider, encrypted_api_key, key_hint, base_url, selected_model, status, last_validated_at, created_at, updated_at
                FROM user_ai_credentials
                WHERE user_id = ? AND provider = ?
                LIMIT 1
                """,
                (clean_user, clean_provider)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return UserAICredentialRecord(
                id=row["id"],
                user_id=row["user_id"],
                provider=row["provider"],
                encrypted_api_key=row["encrypted_api_key"],
                key_hint=row["key_hint"],
                base_url=row["base_url"],
                selected_model=row["selected_model"],
                status=row["status"],
                last_validated_at=row["last_validated_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            )

    def upsert_credential(
        self,
        user_id: str,
        provider: str,
        encrypted_api_key: str,
        key_hint: str,
        base_url: Optional[str] = None,
        selected_model: Optional[str] = None,
        status: str = "connected",
    ) -> UserAICredentialSummary:
        """Saves or updates an encrypted credential for a user."""
        clean_user = user_id.strip()
        clean_provider = provider.strip().lower()
        now = self._utc_now()

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_ai_credentials (
                    id, user_id, provider, encrypted_api_key, key_hint, base_url, selected_model, status, last_validated_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, provider) DO UPDATE SET
                    encrypted_api_key = excluded.encrypted_api_key,
                    key_hint = excluded.key_hint,
                    base_url = excluded.base_url,
                    selected_model = excluded.selected_model,
                    status = excluded.status,
                    last_validated_at = excluded.last_validated_at,
                    updated_at = excluded.updated_at
                """,
                (
                    str(uuid.uuid4()),
                    clean_user,
                    clean_provider,
                    encrypted_api_key,
                    key_hint,
                    base_url.strip() if base_url else None,
                    selected_model.strip() if selected_model else None,
                    status,
                    now,
                    now,
                    now
                )
            )
            conn.commit()

        return UserAICredentialSummary(
            provider=clean_provider,
            key_hint=key_hint,
            base_url=base_url,
            selected_model=selected_model,
            status=status,
            last_validated_at=now,
            created_at=now,
            updated_at=now
        )

    def update_credential_status(self, user_id: str, provider: str, status: str) -> None:
        """Updates connection status (e.g., 'invalid_key', 'connected', 'error') without altering credentials."""
        now = self._utc_now()
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE user_ai_credentials
                SET status = ?, updated_at = ?
                WHERE user_id = ? AND provider = ?
                """,
                (status, now, user_id.strip(), provider.strip().lower())
            )
            conn.commit()

    def delete_credential(self, user_id: str, provider: str) -> bool:
        """Deletes user's credential and clears preferences if it was the selected provider."""
        clean_user = user_id.strip()
        clean_provider = provider.strip().lower()
        now = self._utc_now()

        with get_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM user_ai_credentials WHERE user_id = ? AND provider = ?",
                (clean_user, clean_provider)
            )
            deleted = cursor.rowcount > 0

            # If this was their preferred provider, revert to deterministic engine
            cursor.execute(
                "SELECT preferred_provider FROM user_ai_preferences WHERE user_id = ? LIMIT 1",
                (clean_user,)
            )
            row = cursor.fetchone()
            if row and row["preferred_provider"].lower() == clean_provider:
                cursor.execute(
                    """
                    UPDATE user_ai_preferences
                    SET preferred_provider = 'deterministic', preferred_model = NULL, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (now, clean_user)
                )

            conn.commit()
            return deleted

    def get_preference(self, user_id: str) -> UserAIPreferenceRecord:
        """Gets user's active AI preference, defaulting to built-in deterministic engine."""
        clean_user = (user_id or "").strip()
        if not clean_user:
            return UserAIPreferenceRecord(user_id="anonymous", preferred_provider="deterministic")

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT user_id, preferred_provider, preferred_model, fallback_to_deterministic, updated_at
                FROM user_ai_preferences
                WHERE user_id = ?
                LIMIT 1
                """,
                (clean_user,)
            )
            row = cursor.fetchone()
            if not row:
                return UserAIPreferenceRecord(
                    user_id=clean_user,
                    preferred_provider="deterministic",
                    preferred_model=None,
                    fallback_to_deterministic=True,
                    updated_at=self._utc_now()
                )
            return UserAIPreferenceRecord(
                user_id=row["user_id"],
                preferred_provider=row["preferred_provider"],
                preferred_model=row["preferred_model"],
                fallback_to_deterministic=bool(row["fallback_to_deterministic"]),
                updated_at=row["updated_at"]
            )

    def upsert_preference(
        self,
        user_id: str,
        preferred_provider: str,
        preferred_model: Optional[str] = None,
        fallback_to_deterministic: bool = True
    ) -> UserAIPreferenceRecord:
        """Updates user's preferred execution strategy and model."""
        clean_user = user_id.strip()
        clean_provider = (preferred_provider or "deterministic").strip().lower()
        now = self._utc_now()

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO user_ai_preferences (
                    user_id, preferred_provider, preferred_model, fallback_to_deterministic, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    preferred_provider = excluded.preferred_provider,
                    preferred_model = excluded.preferred_model,
                    fallback_to_deterministic = excluded.fallback_to_deterministic,
                    updated_at = excluded.updated_at
                """,
                (
                    clean_user,
                    clean_provider,
                    preferred_model.strip() if preferred_model else None,
                    1 if fallback_to_deterministic else 0,
                    now,
                    now
                )
            )
            conn.commit()

        return UserAIPreferenceRecord(
            user_id=clean_user,
            preferred_provider=clean_provider,
            preferred_model=preferred_model,
            fallback_to_deterministic=fallback_to_deterministic,
            updated_at=now
        )
