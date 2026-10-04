"""
voice/handy.py
Backward-compatible wrapper for Handy voice input.
Inherits from HandyVoiceProvider so all existing callers and tests continue to work identically.
"""

from pathlib import Path
from voice.handy_provider import HandyVoiceProvider


class Handy(HandyVoiceProvider):
    """
    Speech-to-Text provider reading from Handy SQLite history database.
    Retains exact backward-compatible class name and interface.
    """
    pass