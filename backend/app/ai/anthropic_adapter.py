"""
anthropic_adapter.py — BYOK Anthropic adapter with strict Pydantic JSON schema validation and mock fallback.
Supports standard Anthropic Claude models (claude-3-5-haiku-20241022, claude-3-5-sonnet-20241022, claude-3-haiku-20240307).
"""
import time
import json
import re
import logging
import httpx
from typing import Dict, List, Tuple, Any, Optional
from pydantic import ValidationError

from app.ai.base_adapter import BaseExplanationAdapter
from app.ai.mock_adapter import MockExplanationAdapter
from app.ai.prompts import CIVIL_ENGINEER_SYSTEM_PROMPT, build_user_prompt, build_rich_site_analysis_prompt
from app.schemas.analysis import AnalysisResponse
from app.services.ai_crypto import sanitize_api_key

logger = logging.getLogger(__name__)

SUPPORTED_ANTHROPIC_MODELS = [
    "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet-20241022",
    "claude-3-haiku-20240307",
]


async def validate_anthropic_key(api_key: str) -> Tuple[bool, str, List[str]]:
    """Validates an Anthropic API key by querying the /v1/models endpoint."""
    clean_key = sanitize_api_key(api_key)
    if not clean_key:
        return False, "Anthropic API key cannot be empty.", []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": clean_key,
                    "anthropic-version": "2023-06-01",
                    "User-Agent": "BuildWise-AI/1.0"
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                return True, "Anthropic credentials successfully verified.", raw_models or SUPPORTED_ANTHROPIC_MODELS
            elif resp.status_code in (401, 403):
                return False, "Invalid Anthropic API key. Authentication failed.", []
            elif resp.status_code == 429:
                return False, "Anthropic rate limit exceeded or credit balance exhausted. Please try again shortly.", []
            else:
                return False, f"Anthropic verification failed with status {resp.status_code}.", []
    except httpx.TimeoutException:
        return False, "Connection to Anthropic API timed out after 10 seconds. Please check your network connection.", []
    except httpx.ConnectError:
        return False, "Network error: Unable to connect to Anthropic API servers. Please check your network connection.", []
    except Exception as exc:
        return False, f"Connection to Anthropic API failed: {str(exc)[:120]}", []


class AnthropicExplanationAdapter(BaseExplanationAdapter):
    """
    Adapter for Anthropic Claude messages API with structured JSON output.
    Falls back gracefully to MockExplanationAdapter if API calls fail or keys are invalid.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.mock = MockExplanationAdapter()
        self.api_key = api_key or ""
        self.model = model or "claude-3-5-haiku-20241022"

    async def generate_explanation(
        self,
        analysis_data: Dict[str, Any]
    ) -> Tuple[str, List[str], Dict[str, str]]:
        api_key = self.api_key
        if not api_key:
            summary, recs, meta = await self.mock.generate_explanation(analysis_data)
            meta["provider_requested"] = "anthropic"
            meta["provider_used"] = "mock_fallback"
            meta["fallback_reason"] = "Anthropic API key is not configured"
            return summary, recs, meta

        start_time = time.time()

        coords = analysis_data.get("coordinates", {})
        lat = coords.get("latitude", 12.9716)
        lon = coords.get("longitude", 77.5946)
        area = analysis_data.get("built_up_area_sqft", 2000.0)
        grade = analysis_data.get("quality_grade", "standard")
        typology = analysis_data.get("building_typology", "residential_single")
        floors_val = analysis_data.get("floors", 1)
        storeys = f"G+{floors_val - 1}" if isinstance(floors_val, int) and floors_val > 1 else ("G" if floors_val == 1 else str(floors_val))
        cov_val = analysis_data.get("ground_coverage_ratio", 0.60)
        coverage = round(cov_val * 100) if cov_val <= 1.0 else round(cov_val)

        user_prompt = build_rich_site_analysis_prompt(analysis_data)

        schema_repr = json.dumps(AnalysisResponse.model_json_schema(), indent=2)
        system_prompt = (
            f"{CIVIL_ENGINEER_SYSTEM_PROMPT}\n\n"
            f"REQUIRED JSON KEYS (All are mandatory):\n"
            f"- 'feasibility_score': integer (0-100)\n"
            f"- 'structural_recommendations': array of strings (min 1 recommendation)\n"
            f"- 'cost_breakdown': object (CPWD benchmark costs)\n"
            f"- 'vastu_compliance': object (orientation and entrance analysis)\n"
            f"- 'parameter_reflection': string (2-sentence reflection of user inputs)\n"
            f"- 'engineering_summary': string (synthesis of structural feasibility)\n"
            f"- 'structured_analysis': object (executive_summary, overall_assessment, key_strengths, key_concerns, engineering_considerations, environmental_and_hazards, financial_considerations, required_investigations, recommended_next_steps)\n\n"
            f"You must strictly output a valid JSON object matching this schema:\n"
            f"{schema_repr}"
        )

        target_model = self.model or "claude-3-5-haiku-20241022"
        last_error = "Anthropic request failed"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": target_model,
                    "system": system_prompt,
                    "messages": [
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 3000
                }
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=payload
                )

                if resp.status_code == 200:
                    data = resp.json()
                    content_blocks = data.get("content", [])
                    raw_content = ""
                    for block in content_blocks:
                        if block.get("type") == "text":
                            raw_content += block.get("text", "")

                    json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
                    if not json_match:
                        raise ValueError("No JSON object found in Anthropic response")
                    cleaned_json = json_match.group(0).strip()

                    report = AnalysisResponse.model_validate_json(cleaned_json)
                    summary = report.engineering_summary or (
                        f"{report.parameter_reflection}\n\n"
                        f"Feasibility Score: {report.feasibility_score}/100. "
                        f"Recommendations: {'; '.join(report.structural_recommendations[:2])}."
                    )
                    recs = report.structural_recommendations or report.detailed_recommendations or []

                    structured_narrative = None
                    if report.structured_analysis:
                        structured_narrative = report.structured_analysis.model_dump()
                    else:
                        structured_narrative = {
                            "executive_summary": report.executive_summary or summary,
                            "overall_assessment": report.overall_assessment or summary,
                            "key_strengths": report.key_strengths or [
                                "Topographic suitability verified for planned footprint",
                                "Bioclimatic axis aligned with natural ventilation paths",
                            ],
                            "key_concerns": report.key_concerns or [
                                "Substructure load distribution must adhere to IS 456 code guidelines"
                            ],
                            "engineering_considerations": report.engineering_considerations or report.structural_recommendations or [],
                            "environmental_and_hazards": report.environmental_and_hazards or [
                                "Seismic ductile detailing required per IS 1893:2016"
                            ],
                            "financial_considerations": report.financial_considerations or [
                                "Civil structural framing represents approximately 50% of construction outlay"
                            ],
                            "required_investigations": report.required_investigations or [
                                "Geotechnical borehole testing for Safe Bearing Capacity (SBC)",
                                "Total station topographic contour survey",
                                "Soil percolation rate testing"
                            ],
                            "recommended_next_steps": report.recommended_next_steps or recs[:4]
                        }

                    duration_ms = round((time.time() - start_time) * 1000.0, 2)

                    return summary, recs, {
                        "provider_requested": "anthropic",
                        "provider_used": f"anthropic ({target_model})",
                        "generation_time_ms": str(duration_ms),
                        "parameter_reflection": report.parameter_reflection,
                        "feasibility_score": str(report.feasibility_score),
                        "structured_narrative": structured_narrative
                    }
                else:
                    last_error = f"Anthropic HTTP {resp.status_code}: {resp.text[:120]}"
                    logger.warning(last_error)
        except ValidationError as val_err:
            last_error = f"Pydantic ValidationError on Anthropic output: {str(val_err)[:120]}"
            logger.warning(last_error)
        except Exception as exc:
            last_error = f"Anthropic exception: {type(exc).__name__} ({str(exc)[:120]})"
            logger.warning(last_error)

        # Fallback to deterministic mock
        logger.warning(f"Anthropic call failed. Falling back to deterministic mock. Reason: {last_error}")
        summary, recs, meta = await self.mock.generate_explanation(analysis_data)
        meta["provider_requested"] = "anthropic"
        meta["provider_used"] = "mock_fallback"
        meta["fallback_reason"] = last_error
        return summary, recs, meta
