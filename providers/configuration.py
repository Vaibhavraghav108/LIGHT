"""Typed, user-owned configuration for STT and AI providers."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse


AI_PROVIDER_CHOICES = ("local", "gemini", "openai", "claude", "custom_api")
LOCAL_AI_RUNTIMES = ("ollama", "lm_studio")
STT_PROVIDER_CHOICES = ("local", "custom_api")
LOCAL_STT_RUNTIMES = ("handy",)


class ProviderConfigurationError(ValueError):
    """Raised when a provider configuration is invalid or incomplete."""


def _normalise_url(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    url = str(value).strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderConfigurationError("Provider base_url must be an http:// or https:// URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderConfigurationError(
            "Provider base_url may not contain credentials, query parameters, or fragments. "
            "Use credential_env for secrets."
        )
    return url


def _positive_timeout(value: object, default: float = 8.0) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as err:
        raise ProviderConfigurationError("Provider timeout must be numeric.") from err
    if timeout <= 0:
        raise ProviderConfigurationError("Provider timeout must be greater than zero.")
    return timeout if timeout else default


def _credential_env_name(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    name = value.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ProviderConfigurationError(
            "credential_env must be a valid environment-variable name."
        )
    return name


@dataclass(frozen=True)
class STTConfig:
    provider: str = "local"
    runtime: str = "handy"
    model: str | None = None
    base_url: str | None = None
    credential_env: str | None = None
    timeout: float = 1.5
    db_path: str | None = None

    def __post_init__(self):
        provider = self.provider.strip().lower()
        runtime = self.runtime.strip().lower()
        if provider not in STT_PROVIDER_CHOICES:
            raise ProviderConfigurationError(
                f"Unknown STT provider '{provider}'. Choose one of: {', '.join(STT_PROVIDER_CHOICES)}."
            )
        if provider == "local" and runtime not in LOCAL_STT_RUNTIMES:
            raise ProviderConfigurationError(
                "The current audio pipeline supports Handy as its local STT runtime. "
                "Direct microphone model runtimes are not yet available."
            )
        if provider == "custom_api" and not self.base_url:
            raise ProviderConfigurationError("Custom API STT requires base_url.")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "base_url", _normalise_url(self.base_url))
        object.__setattr__(self, "timeout", _positive_timeout(self.timeout, 1.5))
        object.__setattr__(self, "credential_env", _credential_env_name(self.credential_env))


@dataclass(frozen=True)
class AIConfig:
    enabled: bool = True
    provider: str = "local"
    runtime: str = ""
    model: str = ""
    base_url: str | None = None
    credential_env: str | None = None
    timeout: float = 8.0

    def __post_init__(self):
        provider = self.provider.strip().lower()
        runtime = self.runtime.strip().lower()
        model = self.model.strip()
        if provider not in AI_PROVIDER_CHOICES:
            raise ProviderConfigurationError(
                f"Unknown AI provider '{provider}'. Choose one of: {', '.join(AI_PROVIDER_CHOICES)}."
            )
        base_url = self.base_url
        if provider == "local":
            runtime = runtime or "ollama"
            if runtime not in LOCAL_AI_RUNTIMES:
                raise ProviderConfigurationError(
                    f"Unknown local AI runtime '{runtime}'. Choose one of: {', '.join(LOCAL_AI_RUNTIMES)}."
                )
            if runtime == "ollama":
                model = model or "qwen3:1.7b"
                base_url = base_url or "http://127.0.0.1:11434"
            elif base_url is None:
                base_url = "http://127.0.0.1:1234/v1"
        elif runtime:
            raise ProviderConfigurationError(
                f"AI runtime '{runtime}' is only valid with provider=local."
            )
        if not model:
            raise ProviderConfigurationError("AI model must be explicit and non-empty.")
        if provider == "custom_api" and not base_url:
            raise ProviderConfigurationError("Custom API AI requires base_url.")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "runtime", runtime)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "base_url", _normalise_url(base_url))
        object.__setattr__(self, "timeout", _positive_timeout(self.timeout))
        object.__setattr__(self, "credential_env", _credential_env_name(self.credential_env))


@dataclass(frozen=True)
class ProviderSettings:
    stt: STTConfig
    ai: AIConfig


def get_provider_config_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get("LIGHT_PROVIDER_CONFIG")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / ".light" / "providers.json"


def _env_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _defaults_from_environment(env: Mapping[str, str]) -> ProviderSettings:
    # Legacy LLM_* and HANDY_DB_PATH variables remain supported so existing
    # installations keep identical behavior after this architecture change.
    explicit_ai_provider = "LIGHT_AI_PROVIDER" in env
    legacy_provider = env.get("LLM_PROVIDER", "ollama").strip().lower()
    legacy_ai_provider = "local" if legacy_provider in LOCAL_AI_RUNTIMES else legacy_provider
    selected_ai_provider = env.get("LIGHT_AI_PROVIDER", legacy_ai_provider).strip().lower()
    if "LIGHT_AI_RUNTIME" in env:
        selected_ai_runtime = env["LIGHT_AI_RUNTIME"]
    elif not explicit_ai_provider and selected_ai_provider == "local":
        selected_ai_runtime = legacy_provider if legacy_provider in LOCAL_AI_RUNTIMES else "ollama"
    else:
        selected_ai_runtime = ""
    if "LIGHT_AI_BASE_URL" in env:
        selected_ai_base_url = env["LIGHT_AI_BASE_URL"]
    elif not explicit_ai_provider and "LLM_BASE_URL" in env:
        selected_ai_base_url = env["LLM_BASE_URL"]
    else:
        selected_ai_base_url = None
    if "LIGHT_AI_MODEL" in env:
        selected_ai_model = env["LIGHT_AI_MODEL"]
    elif not explicit_ai_provider:
        selected_ai_model = env.get("LLM_MODEL", "")
    else:
        selected_ai_model = ""
    return ProviderSettings(
        stt=STTConfig(
            provider=env.get("LIGHT_STT_PROVIDER", "local"),
            runtime=env.get("LIGHT_STT_RUNTIME", "handy"),
            model=env.get("LIGHT_STT_MODEL") or None,
            base_url=env.get("LIGHT_STT_BASE_URL") or None,
            credential_env=env.get("LIGHT_STT_CREDENTIAL_ENV") or None,
            timeout=float(env.get("LIGHT_STT_TIMEOUT", "1.5")),
            db_path=env.get("HANDY_DB_PATH") or None,
        ),
        ai=AIConfig(
            enabled=_env_bool(env.get("LIGHT_AI_ENABLED", env.get("LLM_ENABLED")), True),
            provider=selected_ai_provider,
            runtime=selected_ai_runtime,
            model=selected_ai_model,
            base_url=selected_ai_base_url,
            credential_env=env.get("LIGHT_AI_CREDENTIAL_ENV") or None,
            timeout=float(env.get("LIGHT_AI_TIMEOUT", env.get("LLM_TIMEOUT", "8.0"))),
        ),
    )


def _merge_section(defaults: object, raw: object) -> dict:
    values = asdict(defaults)
    if raw is None:
        return values
    if not isinstance(raw, dict):
        raise ProviderConfigurationError("Each provider configuration section must be a JSON object.")
    unknown = set(raw) - set(values)
    if unknown:
        raise ProviderConfigurationError(
            f"Unknown provider configuration field(s): {', '.join(sorted(unknown))}."
        )
    values.update(raw)
    return values


def _merge_ai_section(defaults: AIConfig, raw: object) -> dict:
    values = _merge_section(defaults, raw)
    if not isinstance(raw, dict):
        return values

    selected_provider = str(raw.get("provider", defaults.provider)).strip().lower()
    selected_runtime = str(raw.get("runtime", defaults.runtime)).strip().lower()
    provider_changed = selected_provider != defaults.provider
    runtime_changed = selected_runtime != defaults.runtime
    if provider_changed and "runtime" not in raw:
        values["runtime"] = ""
    if provider_changed or runtime_changed:
        if "model" not in raw:
            values["model"] = ""
        if "base_url" not in raw:
            values["base_url"] = None
    return values


def load_provider_settings(
    path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> ProviderSettings:
    env = os.environ if environ is None else environ
    defaults = _defaults_from_environment(env)
    config_path = Path(path) if path is not None else get_provider_config_path(env)
    try:
        config_exists = config_path.exists()
    except OSError as err:
        raise ProviderConfigurationError(
            f"Could not access provider configuration path {config_path}: {err}"
        ) from err
    if not config_exists:
        return defaults
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise ProviderConfigurationError(
            f"Could not read provider configuration at {config_path}: {err}"
        ) from err
    if not isinstance(raw, dict):
        raise ProviderConfigurationError("Provider configuration root must be a JSON object.")
    unknown = set(raw) - {"stt", "ai"}
    if unknown:
        raise ProviderConfigurationError(
            f"Unknown provider configuration section(s): {', '.join(sorted(unknown))}."
        )
    return ProviderSettings(
        stt=STTConfig(**_merge_section(defaults.stt, raw.get("stt"))),
        ai=AIConfig(**_merge_ai_section(defaults.ai, raw.get("ai"))),
    )


def save_provider_settings(settings: ProviderSettings, path: str | Path | None = None) -> Path:
    config_path = Path(path) if path is not None else get_provider_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    payload = {"stt": asdict(settings.stt), "ai": asdict(settings.ai)}
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config_path)
    return config_path
