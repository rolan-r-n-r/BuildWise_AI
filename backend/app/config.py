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

settings = Settings()

