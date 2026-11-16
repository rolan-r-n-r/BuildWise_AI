import os
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
from app.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]


async def validate_groq_key(api_key: str) -> Tuple[bool, str, List[str]]:
    """Validates a Groq API key by querying the /openai/v1/models endpoint."""
    clean_key = (api_key or "").strip()
    if not clean_key:
        return False, "Groq API key cannot be empty.", []

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {clean_key}"}
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                return True, "Groq credentials successfully verified.", raw_models or SUPPORTED_GROQ_MODELS
            elif resp.status_code in (401, 403):
                return False, "Invalid Groq API key. Authentication failed.", []
            elif resp.status_code == 429:
                return False, "Groq rate limit exceeded.", []
            else:
                return False, f"Groq verification failed with status {resp.status_code}.", []
    except Exception as exc:
        return False, f"Connection to Groq API failed: {str(exc)[:120]}", []


class GroqExplanationAdapter(BaseExplanationAdapter):
    """
    Adapter for Groq LLM inference with strict JSON enforcement, Pydantic schema validation,
    markdown stripping, and automatic deterministic mock fallback.
    Supports user BYOK credentials and server-side fallback.
    """
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.mock = MockExplanationAdapter()
        self.api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self.model = model or getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")

    async def generate_explanation(
        self,
        analysis_data: Dict[str, Any]
    ) -> Tuple[str, List[str], Dict[str, str]]:
        api_key = self.api_key or os.getenv("GROQ_API_KEY") or getattr(settings, "GROQ_API_KEY", "")
        if not api_key:
            summary, recs, meta = await self.mock.generate_explanation(analysis_data)
            meta["provider_requested"] = "groq"
            meta["provider_used"] = "mock_fallback"
            meta["fallback_reason"] = "GROQ_API_KEY is not configured"
            return summary, recs, meta

        start_time = time.time()

        # 1. Format User Prompt with explicit parameters
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

        # 2. System prompt with explicit required fields and Pydantic JSON schema representation
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
            f"You must strictly output a valid JSON object matching this JSON Schema:\n"
            f"{schema_repr}"
        )

        candidate_models = [
            os.getenv("GROQ_MODEL") or self.model or "openai/gpt-oss-120b",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
        ]

        # Deduplicate while preserving order
        seen = set()
        deduped_models = []
        for m in candidate_models:
            if m and m not in seen:
                seen.add(m)
                deduped_models.append(m)

        last_error = "Groq API call failed or timed out"
        for target_model in deduped_models:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": target_model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 3000
                    }
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers=headers,
                        json=payload
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_content = data["choices"][0]["message"]["content"]

                        # Extract JSON object between first { and last }
                        json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
                        if not json_match:
                            raise ValueError(f"No JSON object found in Groq response: {raw_content[:100]}")
                        cleaned_json = json_match.group(0).strip()

                        # Parse and validate into Pydantic AnalysisResponse
                        try:
                            report = AnalysisResponse.model_validate_json(cleaned_json)
                        except ValidationError as val_err:
                            logger.warning(f"Groq output failed AnalysisResponse Pydantic validation on model {target_model}: {val_err}")
                            raise val_err

                        summary = report.engineering_summary or (
                            f"{report.parameter_reflection}\n\n"
                            f"Feasibility Score: {report.feasibility_score}/100 based on IS 456 / IS 1893. "
                            f"Key structural considerations: {'; '.join(report.structural_recommendations[:2])}."
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
                            "provider_requested": "groq",
                            "provider_used": f"groq ({target_model})",
                            "generation_time_ms": str(duration_ms),
                            "parameter_reflection": report.parameter_reflection,
                            "feasibility_score": str(report.feasibility_score),
                            "cost_breakdown": json.dumps(report.cost_breakdown),
                            "vastu_compliance": json.dumps(report.vastu_compliance),
                            "structured_narrative": structured_narrative
                        }
                    else:
                        last_error = f"Groq status {resp.status_code}: {resp.text[:100]}"
                        logger.warning(f"Groq API error on model {target_model}: {last_error}")
            except ValidationError as v_err:
                last_error = f"Pydantic ValidationError on model {target_model}: {str(v_err)[:150]}"
                logger.warning(last_error)
            except Exception as e:
                last_error = f"Groq request exception on model {target_model}: {type(e).__name__} ({str(e)})"
                logger.warning(last_error)

        # Fallback to deterministic mock on error or validation failure
        logger.warning(f"Groq failed completely. Falling back to deterministic mock. Reason: {last_error}")
        summary, recs, meta = await self.mock.generate_explanation(analysis_data)
        meta["provider_requested"] = "groq"
        meta["provider_used"] = "mock_fallback"
        meta["fallback_reason"] = last_error
        return summary, recs, meta
