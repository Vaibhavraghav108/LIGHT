"""Command-line configuration and diagnostics for LIGHT providers."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from providers.ai import build_ai_provider
from providers.configuration import (
    AI_PROVIDER_CHOICES,
    LOCAL_AI_RUNTIMES,
    ProviderConfigurationError,
    STT_PROVIDER_CHOICES,
    AIConfig,
    ProviderSettings,
    STTConfig,
    load_provider_settings,
    save_provider_settings,
)
from voice.factory import get_voice_provider


def _settings_for_display(settings: ProviderSettings) -> dict:
    # Configuration stores only the credential environment-variable name. The
    # secret value is never read into this display payload.
    return {"stt": asdict(settings.stt), "ai": asdict(settings.ai)}


def _print_status(settings: ProviderSettings) -> int:
    voice = get_voice_provider(provider_config=settings.stt)
    stt_available = voice.is_available()
    stt_status = {
        "kind": "stt",
        "provider": settings.stt.provider,
        "runtime": settings.stt.runtime,
        "model": settings.stt.model,
        "available": stt_available,
        "message": voice.get_status_message(),
    }
    if settings.ai.enabled:
        ai_status = asdict(build_ai_provider(settings.ai).validate())
    else:
        ai_status = {
            "kind": "ai",
            "provider": settings.ai.provider,
            "runtime": settings.ai.runtime,
            "model": settings.ai.model,
            "available": False,
            "message": "AI planner is disabled; deterministic routing remains active.",
        }
    print(json.dumps({"stt": stt_status, "ai": ai_status}, indent=2))
    return 0 if stt_status["available"] and (ai_status["available"] or not settings.ai.enabled) else 2


def _default_ai_url(provider: str, runtime: str) -> str | None:
    if provider == "local" and runtime == "ollama":
        return "http://127.0.0.1:11434"
    if provider == "local" and runtime == "lm_studio":
        return "http://127.0.0.1:1234/v1"
    return None


def _set_ai(settings: ProviderSettings, args) -> int:
    provider = args.provider
    runtime = args.runtime or (settings.ai.runtime if provider == settings.ai.provider else "")
    if provider == "local" and not runtime:
        raise ProviderConfigurationError("Local AI requires --runtime ollama or lm_studio.")
    provider_changed = provider != settings.ai.provider or runtime != settings.ai.runtime
    base_url = args.base_url
    if base_url is None:
        base_url = _default_ai_url(provider, runtime) if provider_changed else settings.ai.base_url
    candidate = AIConfig(
        enabled=not args.disabled,
        provider=provider,
        runtime=runtime,
        model=args.model,
        base_url=base_url,
        credential_env=args.credential_env,
        timeout=args.timeout,
    )
    if candidate.enabled:
        status = build_ai_provider(candidate).validate()
        if not status.available:
            print(f"AI configuration was not saved: {status.message}")
            return 2
    path = save_provider_settings(replace(settings, ai=candidate), path=args.config)
    print(f"Saved AI provider={candidate.provider} runtime={candidate.runtime or 'api'} model={candidate.model} to {path}")
    return 0


def _set_stt(settings: ProviderSettings, args) -> int:
    runtime = args.runtime or ("handy" if args.provider == "local" else "custom")
    candidate = STTConfig(
        provider=args.provider,
        runtime=runtime,
        model=args.model,
        base_url=args.base_url,
        credential_env=args.credential_env,
        timeout=args.timeout,
        db_path=args.db_path,
    )
    voice = get_voice_provider(provider_config=candidate)
    if not voice.is_available():
        print(f"STT configuration was not saved: {voice.get_status_message()}")
        return 2
    path = save_provider_settings(replace(settings, stt=candidate), path=args.config)
    print(f"Saved STT provider={candidate.provider} runtime={candidate.runtime} model={candidate.model or 'service-managed'} to {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure LIGHT STT and AI providers.")
    parser.add_argument("--config", type=Path, help="Override the provider configuration path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("show", help="Show selected providers and models without contacting them.")
    subparsers.add_parser("status", help="Validate selected providers and show availability.")

    models = subparsers.add_parser("models", help="Discover models from the selected AI endpoint.")
    models.add_argument("--kind", choices=("ai",), default="ai")

    ai = subparsers.add_parser("set-ai", help="Validate and activate an AI provider/model.")
    ai.add_argument("--provider", choices=AI_PROVIDER_CHOICES, required=True)
    ai.add_argument("--runtime", choices=LOCAL_AI_RUNTIMES)
    ai.add_argument("--model", required=True)
    ai.add_argument("--base-url")
    ai.add_argument("--credential-env", help="Environment variable containing the API credential.")
    ai.add_argument("--timeout", type=float, default=8.0)
    ai.add_argument("--disabled", action="store_true")

    stt = subparsers.add_parser("set-stt", help="Validate and activate an STT transcript source.")
    stt.add_argument("--provider", choices=STT_PROVIDER_CHOICES, required=True)
    stt.add_argument("--runtime")
    stt.add_argument("--model")
    stt.add_argument("--base-url")
    stt.add_argument("--credential-env", help="Environment variable containing the API credential.")
    stt.add_argument("--timeout", type=float, default=1.5)
    stt.add_argument("--db-path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_provider_settings(path=args.config)
        if args.command == "show":
            print(json.dumps(_settings_for_display(settings), indent=2))
            return 0
        if args.command == "status":
            return _print_status(settings)
        if args.command == "models":
            for model in build_ai_provider(settings.ai).list_models():
                print(model)
            return 0
        if args.command == "set-ai":
            return _set_ai(settings, args)
        if args.command == "set-stt":
            return _set_stt(settings, args)
    except (ProviderConfigurationError, RuntimeError) as err:
        print(f"Provider configuration error: {err}")
        return 2
    parser.error(f"Unknown command: {args.command}")
    return 2
