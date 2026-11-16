"""
BuildWise AI - Client Requirements Parser (Milestone 1)
Extracts structured architectural design constraints from raw free-text client notes.
Integrates Groq Cloud LLM (Llama 3.3 70B) with an ultra-reliable, deterministic
keyword and regex fallback engine.
"""

import json
import logging
import re
from typing import List, Optional
import httpx

from app.config import settings
from app.schemas.multi_floor_plan import (
    ExtractedClientConstraints,
    SpatialAdjacencyConstraint,
    OrientationPreferenceConstraint
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a licensed Indian architectural space planner trained on NBC 2016 and Vastu Shastra.\n"
    "Your task is to analyze the client's design requirements free-text and extract structured architectural design constraints.\n"
    "Output ONLY a valid JSON object matching the ExtractedClientConstraints schema:\n"
    "{\n"
    '  "target_bedroom_count": int (1 to 6),\n'
    '  "target_bathroom_count": int (1 to 6),\n'
    '  "specialized_spaces": string[] (subset of ["home_office", "study", "pooja_room", "powder_room", "utility_room", "servant_room", "gym", "home_theatre", "balcony", "terrace", "open_kitchen"]),\n'
    '  "spatial_adjacencies": [{"room_a": str, "room_b": str, "relationship": "connected"|"adjacent"|"separated"}],\n'
    '  "orientation_preferences": [{"space": str, "preferred_facing": "North"|"East"|"South"|"West"|"North-East"|"South-East"|"South-West"|"North-West"}],\n'
    '  "explicit_exclusions": string[]\n'
    "}\n"
    "Strict extraction rules:\n"
    "1. Bedroom count: If client says '3 BHK', '3 bed', '3 bedroom', count is 3. Default is 2.\n"
    "2. Bathroom count: If client says '3 baths', '3 toilets', count is 3. If powder room is requested, count as an additional bath. Default is 2.\n"
    "3. Specialized spaces: Map 'office'/'wfh' -> 'home_office'; 'library'/'study' -> 'study'; 'mandir'/'prayer' -> 'pooja_room'; 'guest bath'/'powder' -> 'powder_room'; 'wash'/'laundry' -> 'utility_room'; 'deck'/'verandah' -> 'balcony'; 'open kitchen' -> 'open_kitchen'.\n"
    "4. Adjacencies: If 'open kitchen' -> kitchen connected to dining. If 'quiet study' -> study separated from living.\n"
    "5. Orientations: Map directional wishes (e.g. 'north-facing study' -> space: 'study', preferred_facing: 'North').\n"
    "6. Exclusions: Note items like 'no puja', 'no balcony', 'avoid stairs in front'.\n"
    "Do NOT output markdown fences or commentary; output ONLY valid JSON."
)


def parse_client_requirements_fallback(text: str) -> ExtractedClientConstraints:
    """
    Deterministic rule-based and regular-expression parser.
    Guarantees 100% availability offline or when LLM API keys are unconfigured.
    """
    if not text or not text.strip():
        return ExtractedClientConstraints(
            target_bedroom_count=2,
            target_bathroom_count=2,
            specialized_spaces=[],
            spatial_adjacencies=[],
            orientation_preferences=[],
            explicit_exclusions=[],
            raw_notes="",
            extraction_source="regex_fallback"
        )

    clean = text.lower()

    # 1. Bedroom count
    bed_match = re.search(r'(\d+)(?:-|\s+)?(?:bhk|bed|bedroom|br)', clean)
    if bed_match:
        bed_count = int(bed_match.group(1))
    elif "one bed" in clean or "single bed" in clean:
        bed_count = 1
    elif "two bed" in clean:
        bed_count = 2
    elif "three bed" in clean:
        bed_count = 3
    elif "four bed" in clean:
        bed_count = 4
    elif "five bed" in clean:
        bed_count = 5
    else:
        # Check if master and guest bedrooms are mentioned
        has_guest = "guest" in clean
        has_kids = "kids" in clean or "children" in clean
        bed_count = 2 + (1 if has_guest else 0) + (1 if has_kids else 0)
    bed_count = max(1, min(6, bed_count))

    # 2. Bathroom count
    bath_match = re.search(r'(\d+)(?:-|\s+)?(?:bath|bathroom|toilet|wc|washroom)', clean)
    if bath_match:
        bath_count = int(bath_match.group(1))
    elif "one bath" in clean:
        bath_count = 1
    elif "two bath" in clean:
        bath_count = 2
    elif "three bath" in clean:
        bath_count = 3
    elif "four bath" in clean:
        bath_count = 4
    else:
        bath_count = 2 if bed_count >= 2 else 1
        if "powder room" in clean or "powder" in clean or "guest toilet" in clean:
            bath_count += 1
    bath_count = max(1, min(6, bath_count))

    # 3. Specialized spaces
    spaces: List[str] = []
    if any(k in clean for k in ("home office", "work from home", "wfh", "office")):
        spaces.append("home_office")
    if any(k in clean for k in ("study", "library", "reading room")):
        spaces.append("study")
    if any(k in clean for k in ("pooja", "puja", "mandir", "prayer room", "prayer")):
        if not any(neg in clean for neg in ("no pooja", "no puja", "without pooja", "without puja")):
            spaces.append("pooja_room")
    if any(k in clean for k in ("powder room", "powder", "guest toilet", "half bath")):
        spaces.append("powder_room")
    if any(k in clean for k in ("utility", "wash area", "laundry", "service balcony")):
        spaces.append("utility_room")
    if any(k in clean for k in ("servant", "maid room", "maid's")):
        spaces.append("servant_room")
    if any(k in clean for k in ("gym", "fitness", "workout")):
        spaces.append("gym")
    if any(k in clean for k in ("theatre", "theater", "media room", "cinema")):
        spaces.append("home_theatre")
    if any(k in clean for k in ("balcony", "balconies", "deck", "decks", "verandah", "sitout", "patio")):
        if not any(neg in clean for neg in ("no balcony", "without balcony")):
            spaces.append("balcony")
    if any(k in clean for k in ("terrace", "terrace garden", "rooftop")):
        spaces.append("terrace")
    if any(k in clean for k in ("open kitchen", "kitchen counter", "breakfast bar", "island kitchen")):
        spaces.append("open_kitchen")

    # 4. Adjacencies
    adjacencies: List[SpatialAdjacencyConstraint] = []
    if "open_kitchen" in spaces or "kitchen open" in clean or "kitchen attached to dining" in clean:
        adjacencies.append(SpatialAdjacencyConstraint(room_a="kitchen", room_b="dining", relationship="connected"))
    if "quiet study" in clean or "study away" in clean or "office away" in clean:
        adjacencies.append(SpatialAdjacencyConstraint(room_a="study", room_b="living", relationship="separated"))
    if "attached bath" in clean or "ensuite" in clean:
        adjacencies.append(SpatialAdjacencyConstraint(room_a="bath", room_b="master_bed", relationship="adjacent"))
    if "kitchen near dining" in clean or "dining near kitchen" in clean:
        if not any(a.room_a == "kitchen" and a.room_b == "dining" for a in adjacencies):
            adjacencies.append(SpatialAdjacencyConstraint(room_a="kitchen", room_b="dining", relationship="adjacent"))

    # 5. Orientation preferences
    orientations: List[OrientationPreferenceConstraint] = []
    if (
        re.search(r'north(?:-|\s+)?facing\s+(?:home\s+)?(?:study|office|desk)(?:\s+room)?', clean)
        or re.search(r'(?:home\s+)?(?:study|office|desk)(?:\s+room)?\s+(?:is\s+)?(?:in|facing)\s+north', clean)
        or "north study" in clean
        or "north office" in clean
    ):
        orientations.append(OrientationPreferenceConstraint(space="home_office" if "office" in clean else "study", preferred_facing="North"))

    if re.search(r'north(?:-|\s+)?facing\s+(?:entry|entrance|living)', clean) or "north entry" in clean or "north facing" in clean:
        orientations.append(OrientationPreferenceConstraint(space="living", preferred_facing="North"))

    # East orientations
    if re.search(r'east(?:-|\s+)?facing\s+kitchen', clean) or re.search(r'kitchen\s+(?:is\s+)?(?:in|facing)\s+east', clean) or "kitchen in east" in clean or "morning sunlight in kitchen" in clean:
        orientations.append(OrientationPreferenceConstraint(space="kitchen", preferred_facing="East"))
    if "puja in east" in clean or "east puja" in clean or "pooja in east" in clean:
        orientations.append(OrientationPreferenceConstraint(space="pooja_room", preferred_facing="East"))

    # North-East orientations
    if "northeast" in clean or "north-east" in clean:
        if "puja" in clean or "pooja" in clean or "mandir" in clean:
            orientations.append(OrientationPreferenceConstraint(space="pooja_room", preferred_facing="North-East"))

    # South-West orientations
    if "southwest" in clean or "south-west" in clean:
        if "master" in clean or "bedroom" in clean:
            orientations.append(OrientationPreferenceConstraint(space="master_bed", preferred_facing="South-West"))

    # South orientations
    if re.search(r'south(?:-|\s+)?facing\s+(?:master|bed|bedroom)', clean) or re.search(r'(?:master|bed|bedroom)\s+(?:is\s+)?(?:in|facing)\s+south', clean):
        if not any(o.preferred_facing in ("South-West", "South-East") for o in orientations):
            orientations.append(OrientationPreferenceConstraint(space="master_bed", preferred_facing="South"))

    # South-East orientations
    if "southeast" in clean or "south-east" in clean:
        if "kitchen" in clean:
            orientations.append(OrientationPreferenceConstraint(space="kitchen", preferred_facing="South-East"))

    # 6. Exclusions
    exclusions: List[str] = []
    if "no puja" in clean or "without puja" in clean or "no pooja" in clean:
        exclusions.append("no_pooja")
    if "no balcony" in clean or "without balcony" in clean:
        exclusions.append("no_balcony")
    if "no bathtub" in clean or "without bathtub" in clean:
        exclusions.append("no_bathtub")
    if "avoid stairs in front" in clean:
        exclusions.append("no_front_staircase")

    return ExtractedClientConstraints(
        target_bedroom_count=bed_count,
        target_bathroom_count=bath_count,
        specialized_spaces=list(dict.fromkeys(spaces)),
        spatial_adjacencies=adjacencies,
        orientation_preferences=orientations,
        explicit_exclusions=exclusions,
        raw_notes=text.strip(),
        extraction_source="regex_fallback"
    )


async def parse_client_requirements(
    text: str,
    ai_provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> ExtractedClientConstraints:
    """
    Parses client requirements via configured AI provider (Groq, Gemini, OpenAI, Anthropic).
    Gracefully and instantly falls back to deterministic regex parser on any network,
    validation, or authentication failure.
    """
    if not text or not text.strip():
        return parse_client_requirements_fallback("")

    provider = (ai_provider or getattr(settings, "DEFAULT_AI_PROVIDER", "groq")).lower().strip()
    schema_json = json.dumps(ExtractedClientConstraints.model_json_schema(), indent=2)
    user_msg = f"Client Requirements Text:\n\"\"\"{text}\"\"\"\nExtract structured constraints JSON."

    # 1. Attempt Groq
    if provider in ("groq", "default"):
        target_key = api_key or settings.GROQ_API_KEY
        if target_key and not target_key.startswith("your_"):
            try:
                candidate_models = [
                    model or getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
                    "llama-3.3-70b-versatile",
                    "llama-3.1-8b-instant"
                ]
                for target_model in candidate_models:
                    async with httpx.AsyncClient(timeout=4.0) as client:
                        headers = {
                            "Authorization": f"Bearer {target_key}",
                            "Content-Type": "application/json"
                        }
                        payload = {
                            "model": target_model,
                            "response_format": {"type": "json_object"},
                            "messages": [
                                {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nSchema:\n{schema_json}"},
                                {"role": "user", "content": user_msg}
                            ],
                            "temperature": 0.1,
                            "max_tokens": 800
                        }
                        resp = await client.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers=headers,
                            json=payload
                        )
                        if resp.status_code == 200:
                            content = resp.json()["choices"][0]["message"]["content"]
                            match = re.search(r'\{.*\}', content, re.DOTALL)
                            if match:
                                data = json.loads(match.group(0))
                                data["raw_notes"] = text.strip()
                                data["extraction_source"] = "groq_llm"
                                return ExtractedClientConstraints.model_validate(data)
            except Exception as e:
                logger.warning(f"Groq client requirements extraction failed: {e}; applying regex fallback.")

    # 2. Attempt OpenAI
    elif provider == "openai":
        target_key = api_key
        if target_key:
            try:
                target_model = model or "gpt-4o-mini"
                async with httpx.AsyncClient(timeout=5.0) as client:
                    headers = {
                        "Authorization": f"Bearer {target_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": target_model,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nSchema:\n{schema_json}"},
                            {"role": "user", "content": user_msg}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 800
                    }
                    resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        match = re.search(r'\{.*\}', content, re.DOTALL)
                        if match:
                            data = json.loads(match.group(0))
                            data["raw_notes"] = text.strip()
                            data["extraction_source"] = "openai_llm"
                            return ExtractedClientConstraints.model_validate(data)
            except Exception as e:
                logger.warning(f"OpenAI client requirements extraction failed: {e}; applying regex fallback.")

    # 3. Attempt Anthropic
    elif provider == "anthropic":
        target_key = api_key
        if target_key:
            try:
                target_model = model or "claude-3-5-haiku-20241022"
                async with httpx.AsyncClient(timeout=6.0) as client:
                    headers = {
                        "x-api-key": target_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": target_model,
                        "system": f"{SYSTEM_PROMPT}\n\nSchema:\n{schema_json}",
                        "messages": [{"role": "user", "content": user_msg}],
                        "temperature": 0.1,
                        "max_tokens": 800
                    }
                    resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
                    if resp.status_code == 200:
                        blocks = resp.json().get("content", [])
                        content = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                        match = re.search(r'\{.*\}', content, re.DOTALL)
                        if match:
                            data = json.loads(match.group(0))
                            data["raw_notes"] = text.strip()
                            data["extraction_source"] = "anthropic_llm"
                            return ExtractedClientConstraints.model_validate(data)
            except Exception as e:
                logger.warning(f"Anthropic client requirements extraction failed: {e}; applying regex fallback.")

    # 4. Attempt Gemini
    elif provider == "gemini":
        target_key = api_key or settings.GEMINI_API_KEY
        if target_key and not target_key.startswith("your_"):
            try:
                active_model = model if model and model not in ("gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash") else "gemini-2.5-flash-lite"
                candidate_models = [
                    active_model,
                    "gemini-2.5-flash-lite",
                    "gemini-3.5-flash",
                    "gemini-3.5-flash-lite",
                ]
                seen_m = set()
                candidate_models = [m for m in candidate_models if not (m in seen_m or seen_m.add(m))]

                for target_model in candidate_models:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent"
                    headers = {
                        "x-goog-api-key": target_key,
                        "Content-Type": "application/json",
                    }
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        gemini_payload = {
                            "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\nSchema:\n{schema_json}\n\n{user_msg}"}]}],
                            "generationConfig": {
                                "responseMimeType": "application/json",
                                "temperature": 0.1,
                                "maxOutputTokens": 800
                            }
                        }
                        resp = await client.post(url, headers=headers, json=gemini_payload)
                        if resp.status_code == 200:
                            candidates = resp.json().get("candidates", [])
                            if candidates:
                                raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                match = re.search(r'\{.*\}', raw_text, re.DOTALL)
                                if match:
                                    data = json.loads(match.group(0))
                                    data["raw_notes"] = text.strip()
                                    data["extraction_source"] = "gemini_llm"
                                    return ExtractedClientConstraints.model_validate(data)
            except Exception as e:
                logger.warning(f"Gemini client requirements extraction failed: {e}; applying regex fallback.")

    # Fallback to deterministic regex parser
    return parse_client_requirements_fallback(text)


def parse_client_requirements_sync(
    text: str,
    ai_provider: Optional[str] = "mock"
) -> ExtractedClientConstraints:
    """Synchronous interface using deterministic regex parser."""
    return parse_client_requirements_fallback(text)
