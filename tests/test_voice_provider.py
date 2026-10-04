"""
tests/test_voice_provider.py
Unit tests for VoiceInputProvider abstractions, HandyVoiceProvider, UnavailableVoiceProvider,
and provider factory logic.
"""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from voice.base import VoiceInputProvider
from voice.handy_provider import HandyVoiceProvider
from voice.unavailable_provider import UnavailableVoiceProvider
from voice.factory import get_voice_provider
from voice.handy import Handy
from providers.configuration import STTConfig


class TestVoiceProviders(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "history.db"

        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE transcription_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcription_text TEXT
            )
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_unavailable_provider_behavior(self):
        provider = UnavailableVoiceProvider("Testing unavailable voice input")
        self.assertEqual(provider.provider_name, "unavailable")
        self.assertFalse(provider.is_available())
        self.assertIsNone(provider.get_latest_transcription())
        self.assertEqual(provider.get_transcriptions_since(10), [])
        self.assertEqual(provider.get_status_message(), "Testing unavailable voice input")

    def test_handy_provider_success(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO transcription_history (transcription_text) VALUES (?)", ("Scroll down",))
        conn.commit()
        conn.close()

        provider = HandyVoiceProvider(db_path=self.db_path)
        self.assertTrue(provider.is_available())
        self.assertEqual(provider.provider_name, "handy")

        latest = provider.get_latest_transcription()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["text"], "Scroll down")

    def test_handy_backward_compatibility_class(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO transcription_history (transcription_text) VALUES (?)", ("Open Chrome",))
        conn.commit()
        conn.close()

        handy = Handy(db_path=self.db_path)
        self.assertIsInstance(handy, VoiceInputProvider)
        latest = handy.get_latest_transcription()
        self.assertIsNotNone(latest)
        self.assertEqual(latest["text"], "Open Chrome")

    def test_factory_returns_handy_when_db_exists(self):
        provider = get_voice_provider(db_path=self.db_path)
        self.assertIsInstance(provider, HandyVoiceProvider)
        self.assertTrue(provider.is_available())

    def test_factory_returns_unavailable_when_db_missing_without_crashing(self):
        missing_db = Path(self.temp_dir.name) / "does_not_exist.db"
        provider = get_voice_provider(db_path=missing_db)
        self.assertIsInstance(provider, UnavailableVoiceProvider)
        self.assertFalse(provider.is_available())
        msg = provider.get_status_message().lower()
        self.assertTrue("not found" in msg or "not currently verified" in msg or "unavailable" in msg)

    def test_factory_returns_unavailable_when_handy_path_is_inaccessible(self):
        with patch("voice.factory.Path.exists", side_effect=PermissionError("access denied")):
            provider = get_voice_provider(
                db_path=self.db_path,
                provider_config=STTConfig(provider="local", runtime="handy"),
            )
        self.assertIsInstance(provider, UnavailableVoiceProvider)
        self.assertFalse(provider.is_available())


if __name__ == "__main__":
    unittest.main()
