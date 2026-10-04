"""
voice/factory.py
Factory to resolve and instantiate the active VoiceInputProvider.
"""

import sys
from pathlib import Path
from config import HANDY_DB_PATH
from providers.configuration import STTConfig, load_provider_settings
from voice.base import VoiceInputProvider
from voice.custom_api_provider import CustomAPITranscriptProvider
from voice.handy_provider import HandyVoiceProvider
from voice.unavailable_provider import UnavailableVoiceProvider
from utils.logger import log_warning


def get_voice_provider(
    db_path: str | Path | None = None,
    provider_config: STTConfig | None = None,
    transport=None,
) -> VoiceInputProvider:
    """
    Resolve and return the appropriate VoiceInputProvider for the current environment.
    If Handy database is found, returns HandyVoiceProvider.
    Otherwise returns UnavailableVoiceProvider with a diagnostic message without crashing.
    """
    config = provider_config or load_provider_settings().stt
    if config.provider == "custom_api":
        try:
            return CustomAPITranscriptProvider(config, transport=transport)
        except Exception as err:
            return UnavailableVoiceProvider(
                reason=f"Configured custom STT provider could not be initialized: {err}"
            )

    target_path = Path(db_path or config.db_path) if (db_path or config.db_path) else HANDY_DB_PATH
    try:
        target_exists = target_path.exists()
    except OSError as err:
        target_exists = False
        log_warning(f"Cannot access configured Handy database path {target_path}: {err}")

    if target_exists:
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
        reason = f"Handy database unavailable at {target_path}. Voice listener will remain idle."

    return UnavailableVoiceProvider(reason=reason)
