import hashlib
import json
import logging
import time
from typing import Dict, List, Tuple, Any, Optional

import httpx
from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a licensed Indian residential architect. Review this rectangle layout for architectural sanity. "
    "Reject: bathrooms/kitchens in central or through-traffic positions, strip rooms narrower than 2.4m, "
    "rooms without exterior walls where required, entry opening into service spaces, circulation through private rooms. "
    "Respond ONLY JSON: {\"verdict\": \"pass\"|\"fail\", \"violations\": [\"str\"]}."
)

# 1-hour in-memory cache for critic evaluations: layout_hash -> (timestamp, verdict, violations)
_CRITIC_CACHE: Dict[str, Tuple[float, str, List[str]]] = {}
CACHE_TTL = 3600.0


def _compute_layout_hash(rect_model: Any, plot_w: float, plot_d: float) -> str:
    """Computes a deterministic hash of the layout geometry for caching."""
    rooms = getattr(rect_model, "rooms", [])
    doors = getattr(rect_model, "doors", [])
    room_tokens = sorted(
        (round(r.x, 2), round(r.y, 2), round(r.width, 2), round(r.height, 2), r.room_id)
        for r in rooms
    )
    door_tokens = sorted(
        (round(d.x1, 2), round(d.y1, 2), d.from_room, d.to_room)
        for d in doors
    )
    raw = json.dumps({"plot": [plot_w, plot_d], "rooms": room_tokens, "doors": door_tokens}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _format_critic_payload(rect_model: Any, plot_w: float, plot_d: float) -> Dict[str, Any]:
    """Formats layout geometry into the architect review format."""
    rooms = getattr(rect_model, "rooms", [])
    doors = getattr(rect_model, "doors", [])

    # Build door connections per room
    room_doors: Dict[str, List[str]] = {r.room_id: [] for r in rooms}
    for d in doors:
        if d.door_id == "main_entry":
            continue
        if d.from_room in room_doors and d.to_room in room_doors:
            room_doors[d.from_room].append(d.to_room)
            room_doors[d.to_room].append(d.from_room)

    main_door = next((d for d in doors if d.door_id == "main_entry"), None)
    entry_info = {}
    if main_door:
        entry_info = {
            "x": main_door.x1,
            "y": main_door.y1,
            "wall": "north",
            "opens_into": main_door.to_room
        }

    formatted_rooms = []
    for r in rooms:
        formatted_rooms.append({
            "name": r.room_name,
            "id": r.room_id,
            "x": round(r.x, 2),
            "y": round(r.y, 2),
            "w": round(r.width, 2),
            "h": round(r.height, 2),
            "area_sqm": r.area_sqm,
            "zone": r.zone,
            "doors_to": list(set(room_doors.get(r.room_id, [])))
        })

    return {
        "plot": {"width_m": plot_w, "depth_m": plot_d},
        "frontage": "north",
        "entry": entry_info,
        "rooms": formatted_rooms
    }


def evaluate_layout_critic(
    rect_model: Any,
    plot_w: float,
    plot_d: float,
    ai_provider: Optional[str] = "mock"
) -> Tuple[str, List[str]]:
    """
    LLM Layout Critic (Blueprint Spatial Logic v12).
    Evaluates layout geometry against architectural sanity rules using the configured LLM provider.
    Returns: (verdict: 'pass' | 'fail' | 'skipped', violations: List[str])
    """
    provider = (ai_provider or "mock").lower().strip()

    # Skip in mock mode or zero-config
    if provider in ("mock", "none", "off"):
        return "skipped", []

    # Check cache
    layout_hash = _compute_layout_hash(rect_model, plot_w, plot_d)
    now = time.time()
    if layout_hash in _CRITIC_CACHE:
        ts, cached_verdict, cached_violations = _CRITIC_CACHE[layout_hash]
        if now - ts < CACHE_TTL:
            return cached_verdict, cached_violations

    payload = _format_critic_payload(rect_model, plot_w, plot_d)
    user_prompt = f"Layout Geometry to evaluate:\n{json.dumps(payload, indent=2)}"

    # Dispatch to configured provider
    if provider == "groq":
        api_key = getattr(settings, "GROQ_API_KEY", None)
        if not api_key or api_key.startswith("your_"):
            return "skipped", []
        try:
            with httpx.Client(timeout=4.0) as client:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                body = {
                    "model": getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 400
                }
                resp = client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    verdict = parsed.get("verdict", "pass").lower()
                    violations = parsed.get("violations", [])
                    _CRITIC_CACHE[layout_hash] = (now, verdict, violations)
                    return verdict, violations
        except Exception as e:
            logger.warning(f"Groq layout critic evaluation failed: {e}")
            return "skipped", []

    elif provider == "gemini":
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if not api_key or api_key.startswith("your_"):
            return "skipped", []
        try:
            with httpx.Client(timeout=4.0) as client:
                url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
                headers = {
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                }
                body = {
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": 400,
                        "responseMimeType": "application/json"
                    }
                }
                resp = client.post(url, headers=headers, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    cands = data.get("candidates", [])
                    if cands:
                        text = cands[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        parsed = json.loads(text)
                        verdict = parsed.get("verdict", "pass").lower()
                        violations = parsed.get("violations", [])
                        _CRITIC_CACHE[layout_hash] = (now, verdict, violations)
                        return verdict, violations
        except Exception as e:
            logger.warning(f"Gemini layout critic evaluation failed: {e}")
            return "skipped", []

    return "skipped", []
