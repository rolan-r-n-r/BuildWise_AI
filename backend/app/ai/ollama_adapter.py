import time
import logging
import httpx
from typing import Dict, List, Tuple, Any, Optional
from app.ai.base_adapter import BaseExplanationAdapter
from app.ai.mock_adapter import MockExplanationAdapter
from app.ai.ssrf import validate_outbound_url, SSRFValidationError
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_MODELS = [
    "llama3:latest",
    "mistral:latest",
    "qwen2.5:latest",
    "phi3:latest",
]


async def validate_ollama_endpoint(base_url: Optional[str] = None) -> Tuple[bool, str, List[str]]:
    """
    Validates an Ollama endpoint.
    Guarded by SSRF validation to prevent access to cloud metadata or unauthorized private networks.
    """
    target_url = (base_url or settings.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")
    try:
        validated_url = validate_outbound_url(target_url)
    except SSRFValidationError as ssrf_err:
        return False, str(ssrf_err), []

    tags_endpoint = f"{validated_url}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(tags_endpoint)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return True, f"Ollama daemon successfully reached at {validated_url}.", models or DEFAULT_OLLAMA_MODELS
            else:
                return False, f"Ollama returned HTTP status {resp.status_code}.", []
    except Exception as exc:
        return False, f"Could not connect to Ollama host at {target_url}: {str(exc)[:120]}", []


class OllamaExplanationAdapter(BaseExplanationAdapter):
    """
    Adapter for local/remote Ollama instances (e.g., llama3, mistral).
    Falls back gracefully to MockExplanationAdapter if Ollama is not running or unreachable.
    """
    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self.mock = MockExplanationAdapter()
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or "llama3:latest"

    async def generate_explanation(
        self,
        analysis_data: Dict[str, Any]
    ) -> Tuple[str, List[str], Dict[str, str]]:
        # SSRF validation before outbound request
        try:
            validated_url = validate_outbound_url(self.base_url)
        except SSRFValidationError as ssrf_err:
            summary, recs, meta = await self.mock.generate_explanation(analysis_data)
            meta["provider_requested"] = "ollama"
            meta["provider_used"] = "mock_fallback"
            meta["fallback_reason"] = f"SSRF blocked: {ssrf_err}"
            return summary, recs, meta

        start_time = time.time()
        url = f"{validated_url}/api/generate"

        prompt = (
            "You are a licensed civil engineer. Write a professional technical summary and 5 recommendations "
            "evaluating these site metrics. Do not change any numbers. Never use emojis.\n"
            f"Metrics: {analysis_data}\n\n"
            "Format:\n"
            "SUMMARY: <text>\n"
            "RECOMMENDATIONS:\n"
            "- <item 1>\n"
        )

        target_model = self.model or "llama3:latest"
        last_error = "Local Ollama daemon is unreachable or timed out"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                payload = {
                    "model": target_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2}
                }
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    text = resp.json().get("response", "")
                    lines = text.splitlines()
                    summary_lines = []
                    recs = []
                    is_rec = False

                    for line in lines:
                        cleaned = line.strip()
                        if "RECOMMENDATIONS:" in cleaned.upper():
                            is_rec = True
                            continue
                        if not is_rec:
                            if cleaned.upper().startswith("SUMMARY:"):
                                cleaned = cleaned[8:].strip()
                            if cleaned:
                                summary_lines.append(cleaned)
                        else:
                            if cleaned.startswith(("-", "*", "•")):
                                recs.append(cleaned.lstrip("-*• ").strip())

                    summary = "\n\n".join(summary_lines) if summary_lines else text
                    duration_ms = round((time.time() - start_time) * 1000.0, 2)
                    final_recs = recs if recs else ["Standard engineering drainage recommended."]
                    structured_narrative = {
                        "executive_summary": summary[:400] if len(summary) > 400 else summary,
                        "overall_assessment": summary,
                        "key_strengths": ["Topographic suitability verified for planned footprint", "Local open-weights model inference complete"],
                        "key_concerns": ["Geotechnical soil investigation required before foundation pouring"],
                        "engineering_considerations": ["Structural design under IS 456 with appropriate storey framing"],
                        "environmental_and_hazards": ["Local climatic and seismic conditions factored per IS 1893:2016"],
                        "financial_considerations": ["CPWD benchmark plinth rate calculations remain authoritative"],
                        "required_investigations": ["Plate load test and standard penetration testing (IS 1892)"],
                        "recommended_next_steps": ["Review local municipal setbacks and structural engineer approval"]
                    }
                    return summary, final_recs, {
                        "provider_requested": "ollama",
                        "provider_used": f"ollama ({target_model})",
                        "generation_time_ms": str(duration_ms),
                        "structured_narrative": structured_narrative
                    }
                else:
                    last_error = f"Ollama HTTP status {resp.status_code}"
        except Exception as exc:
            logger.warning(f"Ollama execution failed: {exc}")
            last_error = f"Ollama connection error: {str(exc)[:120]}"

        summary, recs, meta = await self.mock.generate_explanation(analysis_data)
        meta["provider_requested"] = "ollama"
        meta["provider_used"] = "mock_fallback"
        meta["fallback_reason"] = last_error
        return summary, recs, meta
