import time
import json
import re
import logging
import httpx
from typing import Dict, List, Tuple, Any
from pydantic import ValidationError

from app.ai.base_adapter import BaseExplanationAdapter
from app.ai.mock_adapter import MockExplanationAdapter
from app.ai.prompts import CIVIL_ENGINEER_SYSTEM_PROMPT, build_user_prompt
from app.schemas.analysis import AnalysisResponse
from app.config import settings

logger = logging.getLogger(__name__)


def to_gemini_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transforms Pydantic's JSON Schema into Google Gemini's REST Schema proto specification.
    Removes unsupported keywords ('additionalProperties', 'title', 'default', 'anyOf')
    which cause HTTP 400 'Invalid JSON payload received. Unknown name additionalProperties'.
    """
    clean: Dict[str, Any] = {}

    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        if non_null:
            sub = to_gemini_schema(non_null[0])
            clean.update(sub)
            clean["nullable"] = True
            return clean

    type_val = schema.get("type")
    if type_val:
        clean["type"] = type_val.upper() if isinstance(type_val, str) else type_val

    if "description" in schema:
        clean["description"] = schema["description"]

    if "nullable" in schema:
        clean["nullable"] = schema["nullable"]

    if "enum" in schema:
        clean["enum"] = schema["enum"]

    if "required" in schema and isinstance(schema["required"], list):
        clean["required"] = schema["required"]

    if "items" in schema and isinstance(schema["items"], dict):
        clean["items"] = to_gemini_schema(schema["items"])

    if "properties" in schema and isinstance(schema["properties"], dict):
        clean["properties"] = {}
        for k, v in schema["properties"].items():
            if k == "cost_breakdown":
                clean["properties"][k] = {
                    "type": "OBJECT",
                    "description": "CPWD DSR benchmark costs in INR, strictly calculated based on the provided Plinth Area and Specification Grade",
                    "properties": {
                        "base_rate_per_sqft": {
                            "type": "NUMBER",
                            "description": "Rate in INR per sq ft based on specification grade (e.g. 3500 for Premium, 1600 for Basic)"
                        },
                        "total_estimated_cost_inr": {
                            "type": "NUMBER",
                            "description": "Total estimated CPWD construction cost in INR (Plinth Area * base_rate_per_sqft)"
                        },
                        "civil_structure_inr": {
                            "type": "NUMBER",
                            "description": "Structural framing cost (~50% of total base cost)"
                        },
                        "finishes_inr": {
                            "type": "NUMBER",
                            "description": "Finishes cost (~25% of total base cost)"
                        },
                        "mep_services_inr": {
                            "type": "NUMBER",
                            "description": "MEP services cost (~15% of total base cost)"
                        }
                    },
                    "required": ["base_rate_per_sqft", "total_estimated_cost_inr"]
                }
            elif k == "vastu_compliance":
                clean["properties"][k] = {
                    "type": "OBJECT",
                    "description": "Orientation analysis based on NBC 2016 and the provided Lat/Lon solar path",
                    "properties": {
                        "orientation_axis": {
                            "type": "STRING",
                            "description": "Optimal longitudinal axis (e.g. East-West)"
                        },
                        "primary_entrance": {
                            "type": "STRING",
                            "description": "Auspicious entrance direction (e.g. North-East)"
                        },
                        "compliance_rating": {
                            "type": "STRING",
                            "description": "Compliance level (High, Moderate, or Requires Remedy)"
                        }
                    }
                }
            else:
                clean["properties"][k] = to_gemini_schema(v)

    return clean


class GeminiExplanationAdapter(BaseExplanationAdapter):
    """
    Adapter for Google Gemini REST API with strict JSON mode,
    Pydantic response schema enforcement, markdown stripping, and automatic deterministic mock fallback.
    """
    def __init__(self):
        self.mock = MockExplanationAdapter()
        self.api_key = settings.GEMINI_API_KEY

    async def generate_explanation(
        self,
        analysis_data: Dict[str, Any]
    ) -> Tuple[str, List[str], Dict[str, str]]:
        if not self.api_key or self.api_key.startswith("your_"):
            summary, recs, meta = await self.mock.generate_explanation(analysis_data)
            meta["provider_requested"] = "gemini"
            meta["provider_used"] = "mock_fallback"
            meta["fallback_reason"] = "GEMINI_API_KEY is not configured in environment"
            return summary, recs, meta

        start_time = time.time()

        # 1. Format User Prompt with explicit user parameters
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

        user_prompt = build_user_prompt(
            lat=lat,
            lon=lon,
            area=area,
            grade=grade,
            typology=typology,
            storeys=storeys,
            coverage=coverage,
            client_requirements=analysis_data.get("client_requirements"),
        )

        gemini_schema = to_gemini_schema(AnalysisResponse.model_json_schema())

        candidate_models = [
            "gemini-2.0-flash",
            "gemini-1.5-flash",
        ]

        last_error = "Gemini API call failed or timed out"
        for target_model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
            headers = {
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json"
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    payload = {
                        "systemInstruction": {
                            "parts": [{"text": CIVIL_ENGINEER_SYSTEM_PROMPT}]
                        },
                        "contents": [{"parts": [{"text": user_prompt}]}],
                        "generationConfig": {
                            "temperature": 0.2,
                            "maxOutputTokens": 2048,
                            "responseMimeType": "application/json",
                            "responseSchema": gemini_schema
                        }
                    }
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")

                            # Extract JSON object
                            json_match = re.search(r'\{.*\}', text, re.DOTALL)
                            if not json_match:
                                raise ValueError(f"No JSON object found in Gemini response: {text[:100]}")
                            cleaned_json = json_match.group(0).strip()

                            # Parse and validate with Pydantic AnalysisResponse
                            try:
                                report = AnalysisResponse.model_validate_json(cleaned_json)
                            except ValidationError as val_err:
                                logger.warning(f"Gemini output failed AnalysisResponse Pydantic validation on model {target_model}: {val_err}")
                                raise val_err

                            summary = report.engineering_summary or (
                                f"{report.parameter_reflection}\n\n"
                                f"Feasibility Score: {report.feasibility_score}/100 based on IS 456 / IS 1893. "
                                f"Key structural considerations: {'; '.join(report.structural_recommendations[:2])}."
                            )
                            recs = report.structural_recommendations or report.detailed_recommendations or []

                            duration_ms = round((time.time() - start_time) * 1000.0, 2)
                            return summary, recs, {
                                "provider_requested": "gemini",
                                "provider_used": f"gemini ({target_model})",
                                "generation_time_ms": str(duration_ms),
                                "parameter_reflection": report.parameter_reflection,
                                "feasibility_score": str(report.feasibility_score),
                                "cost_breakdown": json.dumps(report.cost_breakdown),
                                "vastu_compliance": json.dumps(report.vastu_compliance)
                            }
                    else:
                        last_error = f"Gemini status {resp.status_code} on {target_model}: {resp.text[:100]}"
                        logger.warning(last_error)
            except ValidationError as v_err:
                last_error = f"Pydantic ValidationError on model {target_model}: {str(v_err)[:150]}"
                logger.warning(last_error)
            except Exception as e:
                last_error = f"Gemini exception on {target_model}: {type(e).__name__} ({str(e)})"
                logger.warning(last_error)

        # Fallback to deterministic mock on error or validation failure
        logger.warning(f"Gemini failed completely. Falling back to deterministic mock. Reason: {last_error}")
        summary, recs, meta = await self.mock.generate_explanation(analysis_data)
        meta["provider_requested"] = "gemini"
        meta["provider_used"] = "mock_fallback"
        meta["fallback_reason"] = last_error
        return summary, recs, meta
