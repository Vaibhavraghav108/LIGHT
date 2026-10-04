"""
voice/base.py
Abstract base class defining the speech-to-text input provider interface for LIGHT.
Providers can be Handy (SQLite), mock streams, or future local speech providers.
"""

from abc import ABC, abstractmethod
from typing import Optional


class VoiceInputProvider(ABC):
    """Abstract interface for speech-to-text input providers in LIGHT."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the identifier of this voice provider."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this provider is supported, configured, and ready to ingest transcripts."""
        ...

    @abstractmethod
    def get_latest_transcription(self) -> Optional[dict]:
        """
        Return the most recent transcription as a dict:
        {"id": int, "text": str} or None if no transcriptions exist.
        """
        ...

    @abstractmethod
    def get_transcriptions_since(self, last_id: Optional[int]) -> list[dict]:
        """
        Return all transcriptions with id > last_id in ascending chronological order.
        If last_id is None, returns a list containing the single latest transcription (if any).
        """
        ...

    def get_status_message(self) -> str:
        """Return human-readable diagnostic status of this provider."""
        return "Available" if self.is_available() else "Unavailable"
