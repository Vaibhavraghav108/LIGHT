"""AI provider adapters used by LIGHT's planner and autonomous browser agent."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Mapping

from providers.configuration import AIConfig, ProviderConfigurationError


JsonTransport = Callable[[str, str, dict | None, Mapping[str, str], float], object]


class ProviderRequestError(RuntimeError):
    """A sanitized provider request failure safe to show in logs or the CLI."""


@dataclass(frozen=True)
class ProviderStatus:
    kind: str
    provider: str
    runtime: str
    model: str | None
    available: bool
    message: str


def _resolve_credential(config: AIConfig, default_env: str | None, required: bool) -> str | None:
    env_name = config.credential_env or default_env
    value = os.environ.get(env_name, "").strip() if env_name else ""
    if required and not value:
        raise ProviderConfigurationError(
            f"{config.provider} requires a credential in environment variable {env_name}."
        )
    return value or None


class AIProvider(ABC):
    """Small provider-neutral interface for structured planner completions."""

    def __init__(self, config: AIConfig, transport: JsonTransport | None = None):
        self.config = config
        self._transport = transport

    @property
    def provider_name(self) -> str:
        return self.config.provider

    @property
    def runtime_name(self) -> str:
        return self.config.runtime

    @property
    def model(self) -> str:
        return self.config.model

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        safe_headers = dict(headers or {})
        if self._transport is not None:
            return self._transport(method, url, payload, safe_headers, self.config.timeout)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers=safe_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                body = response.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as err:
            raise ProviderRequestError(
                f"{self.provider_name} request failed with HTTP {err.code}."
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderRequestError(
                f"{self.provider_name} endpoint is unavailable or timed out."
            ) from None
        except json.JSONDecodeError:
            raise ProviderRequestError(
                f"{self.provider_name} returned a non-JSON response."
            ) from None

    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> object:
        """Return the provider's assistant content or structured object."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return model identifiers reported by the configured endpoint."""

    @abstractmethod
    def create_browser_use_llm(self, timeout: float | None = None):
        """Create Browser Use's native LLM wrapper for this provider."""

    def validate(self) -> ProviderStatus:
        try:
            models = self.list_models()
            if models and self.model not in models:
                return ProviderStatus(
                    "ai",
                    self.provider_name,
                    self.runtime_name,
                    self.model,
                    False,
                    f"Configured model '{self.model}' was not reported by the endpoint.",
                )
            return ProviderStatus(
                "ai",
                self.provider_name,
                self.runtime_name,
                self.model,
                True,
                "Provider reachable and configured model is available.",
            )
        except (ProviderConfigurationError, ProviderRequestError) as err:
            return ProviderStatus(
                "ai",
                self.provider_name,
                self.runtime_name,
                self.model,
                False,
                str(err),
            )


class OllamaAIProvider(AIProvider):
    def _base_url(self) -> str:
        return self.config.base_url or "http://127.0.0.1:11434"

    def complete(self, system_prompt: str, user_prompt: str) -> object:
        response = self._request_json(
            "POST",
            f"{self._base_url()}/api/chat",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {"temperature": 0.0, "num_predict": 180},
            },
            {"Content-Type": "application/json"},
        )
        if not isinstance(response, dict):
            raise ProviderRequestError("ollama returned an invalid response object.")
        return response.get("message", {}).get("content") or response.get("response") or "{}"

    def list_models(self) -> list[str]:
        response = self._request_json("GET", f"{self._base_url()}/api/tags")
        if not isinstance(response, dict):
            raise ProviderRequestError("ollama returned an invalid model list.")
        return sorted(
            str(item.get("name")).strip()
            for item in response.get("models", [])
            if isinstance(item, dict) and item.get("name")
        )

    def create_browser_use_llm(self, timeout: float | None = None):
        from browser_use.llm import ChatOllama

        return ChatOllama(
            model=self.model,
            host=self._base_url(),
            timeout=timeout or self.config.timeout,
        )


class OpenAICompatibleProvider(AIProvider):
    default_base_url = "https://api.openai.com/v1"
    default_credential_env: str | None = "OPENAI_API_KEY"
    credential_required = True

    def _base_url(self) -> str:
        return self.config.base_url or self.default_base_url

    def _headers(self) -> dict[str, str]:
        credential = _resolve_credential(
            self.config,
            self.default_credential_env,
            self.credential_required,
        )
        headers = {"Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        return headers

    def complete(self, system_prompt: str, user_prompt: str) -> object:
        response = self._request_json(
            "POST",
            f"{self._base_url()}/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
                "response_format": {"type": "json_object"},
            },
            self._headers(),
        )
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderRequestError(
                f"{self.provider_name} returned an invalid completion response."
            ) from None

    def list_models(self) -> list[str]:
        response = self._request_json("GET", f"{self._base_url()}/models", headers=self._headers())
        if not isinstance(response, dict):
            raise ProviderRequestError(f"{self.provider_name} returned an invalid model list.")
        return sorted(
            str(item.get("id")).strip()
            for item in response.get("data", [])
            if isinstance(item, dict) and item.get("id")
        )

    def create_browser_use_llm(self, timeout: float | None = None):
        from browser_use.llm import ChatOpenAI

        credential = _resolve_credential(
            self.config,
            self.default_credential_env,
            self.credential_required,
        )
        return ChatOpenAI(
            model=self.model,
            api_key=credential or "local-no-secret",
            base_url=self._base_url(),
            timeout=timeout or self.config.timeout,
        )


class LMStudioAIProvider(OpenAICompatibleProvider):
    default_base_url = "http://127.0.0.1:1234/v1"
    default_credential_env = None
    credential_required = False


class OpenAIAIProvider(OpenAICompatibleProvider):
    pass


class CustomAPIAIProvider(OpenAICompatibleProvider):
    default_base_url = ""
    default_credential_env = None
    credential_required = False


class ClaudeAIProvider(AIProvider):
    def _base_url(self) -> str:
        return self.config.base_url or "https://api.anthropic.com/v1"

    def _headers(self) -> dict[str, str]:
        credential = _resolve_credential(self.config, "ANTHROPIC_API_KEY", True)
        return {
            "Content-Type": "application/json",
            "x-api-key": credential or "",
            "anthropic-version": "2023-06-01",
        }

    def complete(self, system_prompt: str, user_prompt: str) -> object:
        response = self._request_json(
            "POST",
            f"{self._base_url()}/messages",
            {
                "model": self.model,
                "max_tokens": 512,
                "temperature": 0.0,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            self._headers(),
        )
        try:
            return next(
                item["text"]
                for item in response["content"]
                if isinstance(item, dict) and item.get("type") == "text"
            )
        except (KeyError, StopIteration, TypeError):
            raise ProviderRequestError("claude returned an invalid completion response.") from None

    def list_models(self) -> list[str]:
        response = self._request_json("GET", f"{self._base_url()}/models", headers=self._headers())
        if not isinstance(response, dict):
            raise ProviderRequestError("claude returned an invalid model list.")
        return sorted(
            str(item.get("id")).strip()
            for item in response.get("data", [])
            if isinstance(item, dict) and item.get("id")
        )

    def create_browser_use_llm(self, timeout: float | None = None):
        from browser_use.llm import ChatAnthropic

        return ChatAnthropic(
            model=self.model,
            api_key=_resolve_credential(self.config, "ANTHROPIC_API_KEY", True),
            base_url=self._base_url(),
            timeout=timeout or self.config.timeout,
        )


class GeminiAIProvider(AIProvider):
    def _base_url(self) -> str:
        return self.config.base_url or "https://generativelanguage.googleapis.com/v1beta"

    def _credential(self) -> str:
        return _resolve_credential(self.config, "GEMINI_API_KEY", True) or ""

    def _url(self, path: str) -> str:
        # The provider request layer guarantees that URLs and exception bodies are
        # never included in surfaced errors, so query-string credentials stay redacted.
        return f"{self._base_url()}/{path}?{urllib.parse.urlencode({'key': self._credential()})}"

    def complete(self, system_prompt: str, user_prompt: str) -> object:
        response = self._request_json(
            "POST",
            self._url(f"models/{self.model}:generateContent"),
            {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": 0.0,
                    "responseMimeType": "application/json",
                    "maxOutputTokens": 512,
                },
            },
            {"Content-Type": "application/json"},
        )
        try:
            return response["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            raise ProviderRequestError("gemini returned an invalid completion response.") from None

    def list_models(self) -> list[str]:
        response = self._request_json("GET", self._url("models"))
        if not isinstance(response, dict):
            raise ProviderRequestError("gemini returned an invalid model list.")
        models: list[str] = []
        for item in response.get("models", []):
            if isinstance(item, dict) and item.get("name"):
                models.append(str(item["name"]).removeprefix("models/"))
        return sorted(models)

    def create_browser_use_llm(self, timeout: float | None = None):
        from browser_use.llm import ChatGoogle

        if self.config.base_url:
            raise ProviderConfigurationError(
                "Browser Use does not support a custom Gemini base URL in this LIGHT release."
            )
        return ChatGoogle(
            model=self.model,
            api_key=self._credential(),
        )


def build_ai_provider(config: AIConfig, transport: JsonTransport | None = None) -> AIProvider:
    """Build exactly the configured provider; never select or fall back implicitly."""
    if config.provider == "local":
        if config.runtime == "ollama":
            return OllamaAIProvider(config, transport=transport)
        if config.runtime == "lm_studio":
            return LMStudioAIProvider(config, transport=transport)
    elif config.provider == "openai":
        return OpenAIAIProvider(config, transport=transport)
    elif config.provider == "claude":
        return ClaudeAIProvider(config, transport=transport)
    elif config.provider == "gemini":
        return GeminiAIProvider(config, transport=transport)
    elif config.provider == "custom_api":
        return CustomAPIAIProvider(config, transport=transport)
    raise ProviderConfigurationError(
        f"No AI adapter is registered for provider={config.provider}, runtime={config.runtime}."
    )
