import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from brain.commands import Action, Command
from brain.llm import QwenPlanner
from providers.ai import (
    ClaudeAIProvider,
    GeminiAIProvider,
    LMStudioAIProvider,
    OllamaAIProvider,
    OpenAIAIProvider,
    ProviderRequestError,
    ProviderStatus,
    build_ai_provider,
)
from providers.configuration import (
    AI_PROVIDER_CHOICES,
    STT_PROVIDER_CHOICES,
    AIConfig,
    ProviderConfigurationError,
    ProviderSettings,
    STTConfig,
    load_provider_settings,
    save_provider_settings,
)
from voice.custom_api_provider import CustomAPITranscriptProvider
from voice.factory import get_voice_provider
from voice.handy_provider import HandyVoiceProvider
from browser.agent import AutonomousBrowserAgent
from core.executor import Executor
from providers.cli import main as provider_cli_main
from tests.provider_test_utils import make_test_ai_provider, make_test_laya, make_test_planner


class TestProviderConfiguration(unittest.TestCase):
    def test_explicit_test_dependencies_ignore_persisted_provider_changes(self):
        persisted_configs = (
            {
                "ai": {
                    "provider": "local",
                    "runtime": "ollama",
                    "model": "qwen2.5:1.5b",
                    "base_url": "http://127.0.0.1:11434",
                }
            },
            {
                "ai": {
                    "provider": "openai",
                    "runtime": "",
                    "model": "gpt-test",
                    "base_url": "https://api.openai.com/v1",
                }
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "providers.json"
            for persisted_config in persisted_configs:
                config_path.write_text(json.dumps(persisted_config), encoding="utf-8")
                with patch.dict(
                    "os.environ",
                    {"LIGHT_PROVIDER_CONFIG": str(config_path)},
                    clear=False,
                ):
                    provider = make_test_ai_provider()
                    planner = make_test_planner()
                    executor = Executor(ai_provider=make_test_ai_provider())
                    agent = AutonomousBrowserAgent(ai_provider=make_test_ai_provider())
                    laya = make_test_laya(MagicMock())

                self.assertEqual((provider.runtime_name, provider.model), ("ollama", "qwen3:1.7b"))
                self.assertEqual((planner.runtime, planner.model), ("ollama", "qwen3:1.7b"))
                self.assertEqual(executor.browser_agent.ai_provider.model, "qwen3:1.7b")
                self.assertEqual(agent.ai_provider.model, "qwen3:1.7b")
                self.assertEqual(laya.llm.model, "qwen3:1.7b")

    def test_user_facing_provider_choices_are_explicit_and_bounded(self):
        self.assertEqual(STT_PROVIDER_CHOICES, ("local", "custom_api"))
        self.assertEqual(
            AI_PROVIDER_CHOICES,
            ("local", "gemini", "openai", "claude", "custom_api"),
        )

    def test_provider_and_model_are_independent_fields(self):
        config = AIConfig(
            provider="local",
            runtime="lm_studio",
            model="my-local-model",
            base_url="http://127.0.0.1:1234/v1",
        )
        self.assertEqual(config.provider, "local")
        self.assertEqual(config.runtime, "lm_studio")
        self.assertEqual(config.model, "my-local-model")

    def test_unknown_provider_and_unsupported_direct_stt_runtime_fail_closed(self):
        with self.assertRaises(ProviderConfigurationError):
            AIConfig(provider="automatic", runtime="", model="surprise")
        with self.assertRaisesRegex(ProviderConfigurationError, "audio pipeline"):
            STTConfig(provider="local", runtime="faster_whisper", model="small")
        with self.assertRaisesRegex(ProviderConfigurationError, "only valid with provider=local"):
            STTConfig(
                provider="custom_api",
                runtime="handy",
                base_url="https://stt.example.test",
            )

    def test_endpoint_secrets_must_use_credential_environment_reference(self):
        with self.assertRaisesRegex(ProviderConfigurationError, "credential_env"):
            AIConfig(
                provider="custom_api",
                runtime="",
                model="model-a",
                base_url="https://user:secret@example.test/v1?api_key=secret",
            )
        with self.assertRaisesRegex(ProviderConfigurationError, "environment-variable"):
            AIConfig(
                provider="openai",
                runtime="",
                model="model-a",
                base_url=None,
                credential_env="not valid",
            )

    def test_settings_round_trip_and_switch_stt_ai_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "providers.json"
            first = ProviderSettings(
                stt=STTConfig(provider="local", runtime="handy", db_path="history.db"),
                ai=AIConfig(
                    provider="local",
                    runtime="ollama",
                    model="qwen3:1.7b",
                    base_url="http://127.0.0.1:11434",
                ),
            )
            save_provider_settings(first, path=path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            raw["ai"] = {
                **raw["ai"],
                "runtime": "lm_studio",
                "model": "local-model-b",
                "base_url": "http://127.0.0.1:1234/v1",
            }
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded = load_provider_settings(path=path, environ={})
            self.assertEqual(loaded.stt, first.stt)
            self.assertEqual(loaded.ai.runtime, "lm_studio")
            self.assertEqual(loaded.ai.model, "local-model-b")

    def test_legacy_environment_configuration_remains_compatible(self):
        settings = load_provider_settings(
            path=Path("definitely-missing-provider-config.json"),
            environ={
                "LLM_PROVIDER": "ollama",
                "LLM_MODEL": "legacy-model",
                "LLM_BASE_URL": "http://127.0.0.1:9999",
                "LLM_ENABLED": "false",
            },
        )
        self.assertEqual(settings.ai.provider, "local")
        self.assertEqual(settings.ai.runtime, "ollama")
        self.assertEqual(settings.ai.model, "legacy-model")
        self.assertFalse(settings.ai.enabled)

    def test_cloud_environment_selection_does_not_inherit_ollama_endpoint(self):
        settings = load_provider_settings(
            path=Path("definitely-missing-provider-config.json"),
            environ={
                "LIGHT_AI_PROVIDER": "openai",
                "LIGHT_AI_MODEL": "model-a",
            },
        )
        self.assertEqual(settings.ai.provider, "openai")
        self.assertEqual(settings.ai.runtime, "")
        self.assertIsNone(settings.ai.base_url)

    def test_explicit_non_ollama_providers_ignore_all_legacy_ollama_defaults(self):
        cases = (
            ("openai", "openai-model", None),
            ("claude", "claude-model", None),
            ("gemini", "gemini-model", None),
            ("custom_api", "custom-model", "https://models.example.test/v1"),
        )
        for provider, model, base_url in cases:
            with self.subTest(provider=provider):
                environ = {
                    "LIGHT_AI_PROVIDER": provider,
                    "LIGHT_AI_MODEL": model,
                    "LLM_PROVIDER": "ollama",
                    "LLM_MODEL": "qwen3:1.7b",
                    "LLM_BASE_URL": "http://127.0.0.1:11434",
                }
                if base_url is not None:
                    environ["LIGHT_AI_BASE_URL"] = base_url
                settings = load_provider_settings(
                    path=Path("definitely-missing-provider-config.json"),
                    environ=environ,
                )
                self.assertEqual(settings.ai.provider, provider)
                self.assertEqual(settings.ai.runtime, "")
                self.assertEqual(settings.ai.model, model)
                self.assertEqual(settings.ai.base_url, base_url)

    def test_explicit_local_ollama_selection_receives_ollama_defaults(self):
        settings = load_provider_settings(
            path=Path("definitely-missing-provider-config.json"),
            environ={"LIGHT_AI_PROVIDER": "local"},
        )
        self.assertEqual(settings.ai.runtime, "ollama")
        self.assertEqual(settings.ai.model, "qwen3:1.7b")
        self.assertEqual(settings.ai.base_url, "http://127.0.0.1:11434")

    def test_partial_provider_file_cannot_inherit_ollama_runtime_or_endpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "providers.json"
            path.write_text(
                json.dumps({"ai": {"provider": "openai", "model": "gpt-test"}}),
                encoding="utf-8",
            )
            settings = load_provider_settings(path=path, environ={})
        self.assertEqual(settings.ai.provider, "openai")
        self.assertEqual(settings.ai.runtime, "")
        self.assertIsNone(settings.ai.base_url)

    def test_partial_ai_provider_switches_clear_previous_provider_state(self):
        switches = (
            ("local", "gemini"),
            ("local", "openai"),
            ("local", "claude"),
            ("local", "custom_api"),
            ("gemini", "openai"),
            ("openai", "claude"),
            ("claude", "gemini"),
            ("custom_api", "openai"),
            ("gemini", "local"),
            ("openai", "local"),
            ("claude", "local"),
            ("custom_api", "local"),
            ("openai", "gemini"),
            ("claude", "openai"),
            ("gemini", "claude"),
            ("openai", "custom_api"),
        )
        for source, destination in switches:
            with self.subTest(source=source, destination=destination), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "providers.json"
                destination_model = "qwen3:1.7b" if destination == "local" else f"{destination}-model"
                ai_section = {"provider": destination, "model": destination_model}
                if destination == "custom_api":
                    ai_section["base_url"] = "https://destination.example.test/v1"
                path.write_text(json.dumps({"ai": ai_section}), encoding="utf-8")
                source_runtime = "ollama" if source == "local" else ""
                source_base_url = (
                    "http://127.0.0.1:11434"
                    if source == "local"
                    else "https://source.example.test/v1"
                )
                settings = load_provider_settings(
                    path=path,
                    environ={
                        "LIGHT_AI_PROVIDER": source,
                        "LIGHT_AI_RUNTIME": source_runtime,
                        "LIGHT_AI_MODEL": f"{source}-model",
                        "LIGHT_AI_BASE_URL": source_base_url,
                        "LIGHT_AI_CREDENTIAL_ENV": "LIGHT_OLD_PROVIDER_KEY",
                    },
                )

                self.assertEqual(settings.ai.provider, destination)
                self.assertEqual(settings.ai.model, destination_model)
                self.assertIsNone(settings.ai.credential_env)
                if destination == "local":
                    self.assertEqual(settings.ai.runtime, "ollama")
                    self.assertEqual(settings.ai.base_url, "http://127.0.0.1:11434")
                else:
                    self.assertEqual(settings.ai.runtime, "")
                    expected_url = (
                        "https://destination.example.test/v1"
                        if destination == "custom_api"
                        else None
                    )
                    self.assertEqual(settings.ai.base_url, expected_url)

    def test_explicit_new_provider_fields_survive_partial_switch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "providers.json"
            path.write_text(
                json.dumps(
                    {
                        "ai": {
                            "provider": "claude",
                            "model": "claude-model",
                            "base_url": "https://claude.example.test/v1",
                            "credential_env": "LIGHT_NEW_CLAUDE_KEY",
                        }
                    }
                ),
                encoding="utf-8",
            )
            settings = load_provider_settings(
                path=path,
                environ={
                    "LIGHT_AI_PROVIDER": "openai",
                    "LIGHT_AI_MODEL": "openai-model",
                    "LIGHT_AI_CREDENTIAL_ENV": "LIGHT_OLD_OPENAI_KEY",
                },
            )
        self.assertEqual(settings.ai.base_url, "https://claude.example.test/v1")
        self.assertEqual(settings.ai.credential_env, "LIGHT_NEW_CLAUDE_KEY")

    def test_partial_stt_provider_switches_clear_provider_specific_state(self):
        cases = (
            (
                {
                    "LIGHT_STT_PROVIDER": "local",
                    "LIGHT_STT_RUNTIME": "handy",
                    "LIGHT_STT_MODEL": "old-local-model",
                    "LIGHT_STT_CREDENTIAL_ENV": "LIGHT_OLD_STT_KEY",
                    "HANDY_DB_PATH": "old-history.db",
                    "LIGHT_STT_TIMEOUT": "2.5",
                },
                {"provider": "custom_api", "base_url": "https://stt.example.test"},
                "custom",
            ),
            (
                {
                    "LIGHT_STT_PROVIDER": "custom_api",
                    "LIGHT_STT_RUNTIME": "custom-v1",
                    "LIGHT_STT_MODEL": "old-custom-model",
                    "LIGHT_STT_BASE_URL": "https://old-stt.example.test",
                    "LIGHT_STT_CREDENTIAL_ENV": "LIGHT_OLD_STT_KEY",
                    "LIGHT_STT_TIMEOUT": "2.5",
                },
                {"provider": "local"},
                "handy",
            ),
        )
        for environ, stt_section, expected_runtime in cases:
            with self.subTest(destination=stt_section["provider"]), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "providers.json"
                path.write_text(json.dumps({"stt": stt_section}), encoding="utf-8")
                settings = load_provider_settings(path=path, environ=environ)

                self.assertEqual(settings.stt.runtime, expected_runtime)
                self.assertIsNone(settings.stt.model)
                self.assertIsNone(settings.stt.credential_env)
                self.assertIsNone(settings.stt.db_path)
                self.assertEqual(settings.stt.timeout, 2.5)

    def test_explicit_custom_stt_fields_survive_partial_switch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "providers.json"
            path.write_text(
                json.dumps(
                    {
                        "stt": {
                            "provider": "custom_api",
                            "runtime": "feed-v2",
                            "model": "transcript-events-v2",
                            "base_url": "https://stt.example.test",
                            "credential_env": "LIGHT_NEW_STT_KEY",
                        }
                    }
                ),
                encoding="utf-8",
            )
            settings = load_provider_settings(
                path=path,
                environ={
                    "LIGHT_STT_PROVIDER": "local",
                    "LIGHT_STT_RUNTIME": "handy",
                    "HANDY_DB_PATH": "old-history.db",
                },
            )
        self.assertEqual(settings.stt.runtime, "feed-v2")
        self.assertEqual(settings.stt.model, "transcript-events-v2")
        self.assertEqual(settings.stt.base_url, "https://stt.example.test")
        self.assertEqual(settings.stt.credential_env, "LIGHT_NEW_STT_KEY")
        self.assertIsNone(settings.stt.db_path)

    def test_inaccessible_provider_config_has_clear_configuration_error(self):
        with patch(
            "providers.configuration.Path.exists",
            side_effect=PermissionError("access denied"),
        ):
            with self.assertRaisesRegex(ProviderConfigurationError, "Could not access"):
                load_provider_settings(path="providers.json", environ={})

    def test_cli_does_not_activate_unvalidated_ai_configuration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "providers.json"
            adapter = MagicMock()
            adapter.validate.return_value = ProviderStatus(
                "ai", "openai", "", "model-a", False, "authentication failed"
            )
            with patch("providers.cli.build_ai_provider", return_value=adapter):
                result = provider_cli_main(
                    [
                        "--config",
                        str(path),
                        "set-ai",
                        "--provider",
                        "openai",
                        "--model",
                        "model-a",
                        "--credential-env",
                        "OPENAI_API_KEY",
                    ]
                )
            self.assertEqual(result, 2)
            self.assertFalse(path.exists())


class TestSTTProviders(unittest.TestCase):
    def test_handy_remains_supported_local_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "history.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE transcription_history (id INTEGER PRIMARY KEY, transcription_text TEXT)"
            )
            connection.commit()
            connection.close()
            provider = get_voice_provider(
                provider_config=STTConfig(
                    provider="local",
                    runtime="handy",
                    db_path=str(db_path),
                )
            )
            self.assertIsInstance(provider, HandyVoiceProvider)

    def test_custom_api_transcript_feed_preserves_event_order(self):
        seen_urls = []

        def transport(url, headers, timeout):
            seen_urls.append(url)
            if url.endswith("/latest"):
                return {"transcription": {"id": 3, "text": "latest"}}
            return {
                "transcriptions": [
                    {"id": 5, "text": "second"},
                    {"id": 4, "text": "first"},
                ]
            }

        provider = CustomAPITranscriptProvider(
            STTConfig(
                provider="custom_api",
                runtime="custom",
                model="remote-stt-v1",
                base_url="http://127.0.0.1:9090",
            ),
            transport=transport,
        )
        self.assertEqual(provider.get_latest_transcription(), {"id": 3, "text": "latest"})
        self.assertEqual(
            provider.get_transcriptions_since(3),
            [{"id": 4, "text": "first"}, {"id": 5, "text": "second"}],
        )
        self.assertIn("after_id=3", seen_urls[-1])

    def test_invalid_custom_stt_does_not_fall_back_to_handy(self):
        provider = get_voice_provider(
            provider_config=STTConfig(
                provider="custom_api",
                runtime="custom",
                base_url="http://127.0.0.1:9090",
            ),
            transport=lambda *_: (_ for _ in ()).throw(RuntimeError("offline")),
        )
        self.assertIsInstance(provider, CustomAPITranscriptProvider)
        self.assertFalse(provider.is_available())
        self.assertNotIsInstance(provider, HandyVoiceProvider)


class TestAIProviders(unittest.TestCase):
    def test_provider_switch_never_sends_previous_provider_credential(self):
        captured_headers = []

        def transport(method, url, payload, headers, timeout):
            captured_headers.append(headers)
            return {"data": [{"id": "claude-model"}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "providers.json"
            path.write_text(
                json.dumps({"ai": {"provider": "claude", "model": "claude-model"}}),
                encoding="utf-8",
            )
            settings = load_provider_settings(
                path=path,
                environ={
                    "LIGHT_AI_PROVIDER": "openai",
                    "LIGHT_AI_MODEL": "openai-model",
                    "LIGHT_AI_CREDENTIAL_ENV": "LIGHT_OLD_OPENAI_KEY",
                },
            )

        self.assertIsNone(settings.ai.credential_env)
        with patch.dict(
            "os.environ",
            {
                "LIGHT_OLD_OPENAI_KEY": "wrong-provider-secret",
                "ANTHROPIC_API_KEY": "correct-claude-secret",
            },
            clear=True,
        ):
            status = build_ai_provider(settings.ai, transport=transport).validate()

        self.assertTrue(status.available)
        self.assertEqual(captured_headers[0]["x-api-key"], "correct-claude-secret")
        self.assertNotIn("wrong-provider-secret", captured_headers[0].values())

    def test_ollama_model_discovery_and_completion(self):
        calls = []

        def transport(method, url, payload, headers, timeout):
            calls.append((method, url, payload))
            if url.endswith("/api/tags"):
                return {"models": [{"name": "qwen3:1.7b"}]}
            return {"message": {"content": '{"actions": []}'}}

        provider = OllamaAIProvider(
            AIConfig(
                provider="local",
                runtime="ollama",
                model="qwen3:1.7b",
                base_url="http://127.0.0.1:11434",
            ),
            transport=transport,
        )
        self.assertEqual(provider.list_models(), ["qwen3:1.7b"])
        self.assertEqual(provider.complete("system", "user"), '{"actions": []}')
        self.assertFalse(calls[-1][2]["stream"])
        self.assertFalse(calls[-1][2]["think"])

    def test_lm_studio_uses_openai_compatible_protocol_without_secret(self):
        captured = []

        def transport(method, url, payload, headers, timeout):
            captured.append((method, url, headers))
            return {"data": [{"id": "local-a"}]}

        provider = build_ai_provider(
            AIConfig(
                provider="local",
                runtime="lm_studio",
                model="local-a",
                base_url="http://127.0.0.1:1234/v1",
            ),
            transport=transport,
        )
        self.assertIsInstance(provider, LMStudioAIProvider)
        self.assertEqual(provider.list_models(), ["local-a"])
        self.assertNotIn("Authorization", captured[0][2])

    def test_openai_credential_is_read_from_named_environment_variable(self):
        captured = []

        def transport(method, url, payload, headers, timeout):
            captured.append(headers)
            return {"choices": [{"message": {"content": '{"actions": []}'}}]}

        config = AIConfig(
            provider="openai",
            runtime="",
            model="test-model",
            base_url=None,
            credential_env="LIGHT_TEST_OPENAI_KEY",
        )
        with patch.dict("os.environ", {"LIGHT_TEST_OPENAI_KEY": "secret-value"}, clear=False):
            provider = OpenAIAIProvider(config, transport=transport)
            self.assertEqual(provider.complete("system", "user"), '{"actions": []}')
        self.assertEqual(captured[0]["Authorization"], "Bearer secret-value")

    def test_missing_cloud_credential_fails_without_fallback(self):
        config = AIConfig(
            provider="claude",
            runtime="",
            model="claude-test",
            base_url=None,
            credential_env="LIGHT_MISSING_CLAUDE_KEY",
        )
        with patch.dict("os.environ", {}, clear=True):
            provider = build_ai_provider(config, transport=MagicMock())
            self.assertIsInstance(provider, ClaudeAIProvider)
            with self.assertRaisesRegex(ProviderConfigurationError, "LIGHT_MISSING_CLAUDE_KEY"):
                provider.list_models()

    def test_empty_model_discovery_cannot_validate_configured_model(self):
        provider = OllamaAIProvider(
            AIConfig(),
            transport=lambda *_: {"models": []},
        )
        status = provider.validate()
        self.assertFalse(status.available)
        self.assertIn("returned no models", status.message)

    def test_configured_model_absent_from_discovery_fails_validation(self):
        provider = OllamaAIProvider(
            AIConfig(),
            transport=lambda *_: {"models": [{"name": "different-model"}]},
        )
        status = provider.validate()
        self.assertFalse(status.available)
        self.assertIn("was not reported", status.message)

    def test_explicit_optional_credential_env_missing_fails_validation(self):
        provider = build_ai_provider(
            AIConfig(
                provider="custom_api",
                model="custom-model",
                base_url="https://models.example.test/v1",
                credential_env="LIGHT_MISSING_CUSTOM_KEY",
            ),
            transport=MagicMock(),
        )
        with patch.dict("os.environ", {}, clear=True):
            status = provider.validate()
        self.assertFalse(status.available)
        self.assertIn("LIGHT_MISSING_CUSTOM_KEY", status.message)

    def test_valid_credential_and_discovered_model_pass_validation(self):
        provider = OpenAIAIProvider(
            AIConfig(
                provider="openai",
                model="gpt-test",
                credential_env="LIGHT_TEST_OPENAI_KEY",
            ),
            transport=lambda *_: {"data": [{"id": "gpt-test"}]},
        )
        with patch.dict("os.environ", {"LIGHT_TEST_OPENAI_KEY": "secret-value"}, clear=True):
            status = provider.validate()
        self.assertTrue(status.available)
        self.assertEqual(status.model, "gpt-test")

    def test_claude_and_gemini_response_shapes(self):
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_API_KEY": "a", "GEMINI_API_KEY": "g"},
            clear=False,
        ):
            claude = ClaudeAIProvider(
                AIConfig(provider="claude", runtime="", model="claude-test", base_url=None),
                transport=lambda *_: {"content": [{"type": "text", "text": '{"actions": []}'}]},
            )
            gemini = GeminiAIProvider(
                AIConfig(provider="gemini", runtime="", model="gemini-test", base_url=None),
                transport=lambda *_: {
                    "candidates": [{"content": {"parts": [{"text": '{"actions": []}'}]}}]
                },
            )
            self.assertEqual(claude.complete("s", "u"), '{"actions": []}')
            self.assertEqual(gemini.complete("s", "u"), '{"actions": []}')

    def test_provider_http_errors_do_not_expose_secret_url_or_body(self):
        config = AIConfig(
            provider="gemini",
            runtime="",
            model="gemini-test",
            base_url=None,
            credential_env="LIGHT_TEST_GEMINI_KEY",
        )
        error = urllib.error.HTTPError(
            "https://example.test?key=top-secret",
            401,
            "top-secret invalid",
            {},
            None,
        )
        with patch.dict("os.environ", {"LIGHT_TEST_GEMINI_KEY": "top-secret"}, clear=False), patch(
            "providers.ai.urllib.request.urlopen",
            side_effect=error,
        ):
            with self.assertRaises(ProviderRequestError) as raised:
                GeminiAIProvider(config).list_models()
        self.assertNotIn("top-secret", str(raised.exception))
        self.assertNotIn("example.test", str(raised.exception))

    def test_qwen_planner_accepts_provider_adapter_without_changing_action_validation(self):
        provider = MagicMock()
        provider.provider_name = "openai"
        provider.runtime_name = ""
        provider.model = "planner-model"
        provider.config = AIConfig(
            provider="openai",
            runtime="",
            model="planner-model",
            base_url=None,
            credential_env="LIGHT_TEST_OPENAI_KEY",
        )
        provider.complete.return_value = (
            '{"actions": [{"action": "CLICK_ELEMENT", "target": "Subscribe"}]}'
        )
        planner = QwenPlanner(enabled=True, ai_provider=provider)
        commands = planner.plan_actions("Click the Subscribe banner")
        self.assertEqual(commands, [Command(Action.CLICK_ELEMENT, "Subscribe")])
        provider.complete.assert_called_once()

    def test_ollama_planner_inference_delegates_to_selected_provider_adapter(self):
        provider = OllamaAIProvider(
            AIConfig(),
            transport=lambda *_: {
                "message": {
                    "content": '{"actions": [{"action": "CLICK_ELEMENT", "target": "Subscribe"}]}'
                }
            },
        )
        with patch.object(provider, "complete", wraps=provider.complete) as complete:
            commands = QwenPlanner(enabled=True, ai_provider=provider).plan_actions(
                "Click the Subscribe banner"
            )
        self.assertEqual(commands, [Command(Action.CLICK_ELEMENT, "Subscribe")])
        complete.assert_called_once()

    def test_browser_agent_uses_selected_provider_without_implicit_fallback(self):
        provider = MagicMock()
        provider.provider_name = "claude"
        provider.runtime_name = ""
        provider.model = "claude-test"
        provider.config = AIConfig(
            provider="claude",
            runtime="",
            model="claude-test",
            base_url=None,
            credential_env="LIGHT_TEST_CLAUDE_KEY",
        )
        provider.create_browser_use_llm.return_value = object()
        agent = AutonomousBrowserAgent(ai_provider=provider)
        self.assertIsNotNone(agent._get_llm())
        provider.create_browser_use_llm.assert_called_once_with(timeout=180.0)

    def test_browser_agent_redacts_third_party_initialization_errors(self):
        provider = MagicMock()
        provider.provider_name = "openai"
        provider.runtime_name = ""
        provider.model = "model-a"
        provider.config = AIConfig(
            provider="openai",
            runtime="",
            model="model-a",
            base_url=None,
        )
        provider.create_browser_use_llm.side_effect = RuntimeError("secret-value in SDK error")
        with self.assertRaises(RuntimeError) as raised:
            AutonomousBrowserAgent(ai_provider=provider)._get_llm()
        self.assertNotIn("secret-value", str(raised.exception))

    def test_browser_use_native_wrappers_cover_every_ai_choice(self):
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "openai-secret",
                "ANTHROPIC_API_KEY": "claude-secret",
                "GEMINI_API_KEY": "gemini-secret",
            },
            clear=False,
        ), patch("browser_use.llm.ChatOpenAI") as chat_openai, patch(
            "browser_use.llm.ChatAnthropic"
        ) as chat_anthropic, patch("browser_use.llm.ChatGoogle") as chat_google:
            lm_studio = build_ai_provider(
                AIConfig(
                    provider="local",
                    runtime="lm_studio",
                    model="local-model",
                    base_url="http://127.0.0.1:1234/v1",
                )
            )
            openai = build_ai_provider(
                AIConfig(provider="openai", runtime="", model="openai-model", base_url=None)
            )
            custom = build_ai_provider(
                AIConfig(
                    provider="custom_api",
                    runtime="",
                    model="custom-model",
                    base_url="https://models.example.test/v1",
                )
            )
            claude = build_ai_provider(
                AIConfig(provider="claude", runtime="", model="claude-model", base_url=None)
            )
            gemini = build_ai_provider(
                AIConfig(provider="gemini", runtime="", model="gemini-model", base_url=None)
            )

            lm_studio.create_browser_use_llm(timeout=180)
            openai.create_browser_use_llm(timeout=180)
            custom.create_browser_use_llm(timeout=180)
            claude.create_browser_use_llm(timeout=180)
            gemini.create_browser_use_llm(timeout=180)

        self.assertEqual(chat_openai.call_count, 3)
        self.assertEqual(chat_anthropic.call_args.kwargs["model"], "claude-model")
        self.assertEqual(chat_google.call_args.kwargs["model"], "gemini-model")


if __name__ == "__main__":
    unittest.main()
