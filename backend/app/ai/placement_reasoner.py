"""
BuildWise AI - LLM Placement Reasoner (v13)
Calls configured AI provider (temperature 0) to reason room placement, band allocation,
and architectural adjacencies under Vastu Shastra and NBC 2016 canon.
Guaranteed safe: pipe output through validate_and_repair_placement before solver execution.
"""

import json
import logging
from typing import Dict, List, Any, Optional

import httpx
from app.config import settings
from app.placement.kb import get_kb_default_placement
from app.placement.validator import validate_and_repair_placement, ValidatedPlacementResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a licensed Indian residential architect placing rooms per Vastu canon and NBC 2016. "
    "Never place a bathroom adjacent to a pooja room or kitchen, never on the entry axis or frontage band, "
    "never centrally. The living room always receives the main entry. Reason zone by zone, then output JSON only."
)


def _build_user_prompt(
    room_ids: List[str],
    plot_w: float,
    plot_d: float,
    frontage_side: str = "North",
    vastu_entrance_scores: Optional[List[str]] = None,
    solar_axis: Optional[float] = None
) -> str:
    return json.dumps({
        "plot": {
            "width_m": plot_w,
            "depth_m": plot_d,
            "frontage_side": frontage_side,
            "solar_axis_degrees": solar_axis or 90.0,
            "vastu_entrance_zones": vastu_entrance_scores or ["N", "E"]
        },
        "required_rooms": room_ids,
        "instructions": (
            "Return JSON only: "
            "{\"rooms\": {\"<room_id>\": {\"zone\": \"...\", \"band\": \"front|middle|rear|flank\", "
            "\"adjacent_to\": [\"...\"], \"door_opens_onto\": \"corridor|exterior|living\", "
            "\"placement_rationale\": \"1 sentence architectural rationale\"}}}"
        )
    }, indent=2)


def reason_placement_sync(
    room_ids: List[str],
    plot_w: float,
    plot_d: float,
    frontage_side: str = "North",
    vastu_entrance_scores: Optional[List[str]] = None,
    solar_axis: Optional[float] = None,
    ai_provider: Optional[str] = "mock"
) -> ValidatedPlacementResult:
    """
    Synchronously reasons room placement using LLM at temperature 0,
    then deterministically validates and repairs against the Placement Knowledge Base.
    """
    provider = (ai_provider or "mock").lower().strip()

    if provider in ("mock", "none", "off"):
        default_res = get_kb_default_placement(room_ids, plot_w, plot_d, frontage_side)
        return validate_and_repair_placement(
            raw_spec=default_res["placement"],
            room_ids=room_ids,
            plot_w=plot_w,
            plot_d=plot_d,
            facing=frontage_side
        )

    user_prompt = _build_user_prompt(room_ids, plot_w, plot_d, frontage_side, vastu_entrance_scores, solar_axis)
    raw_spec: Optional[Dict[str, Any]] = None

    if provider == "groq":
        api_key = getattr(settings, "GROQ_API_KEY", None)
        if api_key and not api_key.startswith("your_"):
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": "llama-3.3-70b-versatile",
                            "messages": [
                                {"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt}
                            ],
                            "temperature": 0.0,
                            "response_format": {"type": "json_object"}
                        }
                    )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    raw_spec = json.loads(content)
            except Exception as e:
                logger.warning(f"Groq placement reasoning failed: {e}; falling back to KB standard.")

    elif provider in ("gemini", "google"):
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if api_key and not api_key.startswith("your_"):
            try:
                candidate_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash-lite"]
                with httpx.Client(timeout=10.0) as client:
                    for target_model in candidate_models:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
                        headers = {
                            "x-goog-api-key": api_key,
                            "Content-Type": "application/json",
                        }
                        payload = {
                            "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{user_prompt}"}]}],
                            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"}
                        }
                        resp = client.post(url, headers=headers, json=payload)
                        if resp.status_code == 200:
                            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                            raw_spec = json.loads(text)
                            break
            except Exception as e:
                logger.warning(f"Gemini placement reasoning failed: {e}; falling back to KB standard.")

    # Validate and repair against KB rules
    return validate_and_repair_placement(
        raw_spec=raw_spec,
        room_ids=room_ids,
        plot_w=plot_w,
        plot_d=plot_d,
        facing=frontage_side
    )
