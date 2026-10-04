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
from providers.cli import main as provider_cli_main


class TestProviderConfiguration(unittest.TestCase):
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
