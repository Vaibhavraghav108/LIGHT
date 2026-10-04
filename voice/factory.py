"""
voice/factory.py
Factory to resolve and instantiate the active VoiceInputProvider.
"""

import sys
from pathlib import Path
from config import HANDY_DB_PATH
from voice.base import VoiceInputProvider
from voice.handy_provider import HandyVoiceProvider
from voice.unavailable_provider import UnavailableVoiceProvider
from utils.logger import log_warning


def get_voice_provider(db_path: str | Path | None = None) -> VoiceInputProvider:
    """
    Resolve and return the appropriate VoiceInputProvider for the current environment.
    If Handy database is found, returns HandyVoiceProvider.
    Otherwise returns UnavailableVoiceProvider with a diagnostic message without crashing.
    """
    target_path = Path(db_path) if db_path is not None else HANDY_DB_PATH
    if target_path.exists():
        try:
            return HandyVoiceProvider(db_path=target_path)
        except Exception as err:
            log_warning(f"Failed initializing Handy voice provider at {target_path}: {err}")

    if sys.platform == "darwin":
        reason = (
            "Handy voice input is not currently verified or available on macOS. "
            f"Expected database location: {target_path}. Voice listener will remain idle."
        )
    else:
        reason = f"Handy database not found at {target_path}. Voice listener will remain idle."

    return UnavailableVoiceProvider(reason=reason)
