"""
voice/unavailable_provider.py
Fallback VoiceInputProvider for platforms or environments where no voice input
source (e.g. Handy SQLite database) is currently available.
"""

from typing import Optional
from voice.base import VoiceInputProvider


class UnavailableVoiceProvider(VoiceInputProvider):
    """
    Fallback provider when no voice provider is configured or available on the current OS.
    Does not crash; cleanly reports unavailable status.
    """

    def __init__(self, reason: str = "Voice input provider is not available on this platform."):
        self.reason = reason

    @property
    def provider_name(self) -> str:
        return "unavailable"

    def is_available(self) -> bool:
        return False

    def get_latest_transcription(self) -> Optional[dict]:
        return None

    def get_transcriptions_since(self, last_id: Optional[int]) -> list[dict]:
        return []

    def get_status_message(self) -> str:
        return self.reason
