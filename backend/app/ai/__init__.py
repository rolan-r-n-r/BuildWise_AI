from typing import Optional
from app.ai.base_adapter import BaseExplanationAdapter
from app.ai.mock_adapter import MockExplanationAdapter
from app.ai.groq_adapter import GroqExplanationAdapter
from app.ai.gemini_adapter import GeminiExplanationAdapter
from app.ai.ollama_adapter import OllamaExplanationAdapter
from app.ai.openai_adapter import OpenAIExplanationAdapter
from app.ai.anthropic_adapter import AnthropicExplanationAdapter

def get_ai_adapter(
    provider: Optional[str] = "mock",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None
) -> BaseExplanationAdapter:
    """
    Factory function returning the appropriate explanation adapter.
    Supports user BYOK credentials, custom models, and base URLs.
    Defaults to MockExplanationAdapter (deterministic engine) if unrecognized, unspecified, or mock.
    """
    selected = (provider or "mock").lower().strip()
    if selected == "groq":
        return GroqExplanationAdapter(api_key=api_key, model=model)
    elif selected == "gemini":
        return GeminiExplanationAdapter(api_key=api_key, model=model)
    elif selected == "openai":
        return OpenAIExplanationAdapter(api_key=api_key, model=model)
    elif selected == "anthropic":
        return AnthropicExplanationAdapter(api_key=api_key, model=model)
    elif selected == "ollama":
        return OllamaExplanationAdapter(base_url=base_url, model=model)
    return MockExplanationAdapter()

from app.ai.blueprint_program import generate_room_program, FALLBACK_PROGRAMS
from app.ai.layout_critic import evaluate_layout_critic
from app.ai.placement_reasoner import reason_placement_sync

__all__ = [
    "BaseExplanationAdapter",
    "MockExplanationAdapter",
    "GroqExplanationAdapter",
    "GeminiExplanationAdapter",
    "OpenAIExplanationAdapter",
    "AnthropicExplanationAdapter",
    "OllamaExplanationAdapter",
    "get_ai_adapter",
    "generate_room_program",
    "FALLBACK_PROGRAMS",
    "evaluate_layout_critic",
    "reason_placement_sync"
]

