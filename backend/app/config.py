import json
import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Explicitly load .env from the backend directory, then fallback to current working directory
_backend_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_backend_env_path)
load_dotenv()


def _parse_cors_origins(raw: str) -> List[str]:
    raw = (raw or "").strip()
    if not raw:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(o).strip().strip("'\"") for o in parsed if str(o).strip()]
        except Exception:
            pass
    # Comma-separated fallback, stripping stray brackets and quotation marks
    origins = []
    for item in raw.split(","):
        cleaned = item.strip().strip("[]'\"").strip()
        if cleaned:
            origins.append(cleaned)
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


class Settings:
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", os.getenv("ENV", "development"))
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    CORS_ORIGINS: List[str] = _parse_cors_origins(
        os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    )
    TRUSTED_PROXIES: List[str] = [
        ip.strip()
        for ip in os.getenv("TRUSTED_PROXIES", "127.0.0.1,::1,testclient,localhost").split(",")
        if ip.strip()
    ]
    DEFAULT_AI_PROVIDER: str = os.getenv("DEFAULT_AI_PROVIDER", "mock").lower()
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    # Groq retired llama-3.3-70b-versatile; gpt-oss-120b is the first model the
    # adapter's fallback chain actually succeeds on (audit F34). Keeping the
    # retired id here made every live call waste a request before falling back.
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    DATABASE_PATH: str = os.getenv(
        "DATABASE_PATH",
        str(Path(__file__).resolve().parent.parent / "data" / "buildwise.db"),
    )
    BETTER_AUTH_SECRET: str = os.getenv(
        "BETTER_AUTH_SECRET",
        "buildwise-production-master-secret-key-change-in-prod-min-32-chars",
    )
    BETTER_AUTH_URL: str = os.getenv("BETTER_AUTH_URL", "http://localhost:5173")
    BREVO_API_KEY: str = os.getenv("BREVO_API_KEY", "")
    BREVO_SENDER_EMAIL: str = os.getenv("BREVO_SENDER_EMAIL", "security@buildwise.ai")
    BREVO_SENDER_NAME: str = os.getenv("BREVO_SENDER_NAME", "BuildWise AI")
    AI_CREDENTIAL_ENCRYPTION_KEY: str = os.getenv(
        "AI_CREDENTIAL_ENCRYPTION_KEY",
        "buildwise-byok-default-dev-encryption-key-min-32-bytes",
    )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    def validate_security(self) -> List[str]:
        warnings = []
        if self.is_production:
            if self.BETTER_AUTH_SECRET == "buildwise-production-master-secret-key-change-in-prod-min-32-chars":
                warnings.append("SECURITY CRITICAL: BETTER_AUTH_SECRET is set to the default placeholder in production.")
            elif len(self.BETTER_AUTH_SECRET) < 32:
                warnings.append("SECURITY WARNING: BETTER_AUTH_SECRET is shorter than 32 characters in production.")
            if self.AI_CREDENTIAL_ENCRYPTION_KEY == "buildwise-byok-default-dev-encryption-key-min-32-bytes":
                warnings.append("SECURITY CRITICAL: AI_CREDENTIAL_ENCRYPTION_KEY is set to the default placeholder in production.")
            elif len(self.AI_CREDENTIAL_ENCRYPTION_KEY) < 32:
                warnings.append("SECURITY WARNING: AI_CREDENTIAL_ENCRYPTION_KEY is shorter than 32 characters in production.")
        return warnings

settings = Settings()

