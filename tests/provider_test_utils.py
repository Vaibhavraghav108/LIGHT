"""Explicit provider fixtures for hermetic unit tests.

Tests importing this module never consult the user's persisted LIGHT provider
configuration. Tests for configuration loading should continue to pass their
own temporary configuration path directly.
"""

from brain.laya import Laya
from brain.llm import QwenPlanner
from providers.ai import OllamaAIProvider
from providers.configuration import AIConfig


def make_test_ai_provider() -> OllamaAIProvider:
    """Return LIGHT's deterministic local default without reading user state."""
    return OllamaAIProvider(
        AIConfig(
            provider="local",
            runtime="ollama",
            model="qwen3:1.7b",
            base_url="http://127.0.0.1:11434",
        )
    )


def make_test_planner(*, enabled: bool = False, transport=None) -> QwenPlanner:
    """Build a planner with an explicit provider and optional legacy test seam."""
    return QwenPlanner(
        enabled=enabled,
        transport=transport,
        ai_provider=make_test_ai_provider(),
    )


def make_test_laya(agent) -> Laya:
    """Build Laya without allowing its disabled planner to read persisted config."""
    return Laya(agent=agent, llm_planner=make_test_planner())
