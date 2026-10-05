"""Custom transcript-feed adapter for installations that own their STT service."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Mapping, Optional

from providers.configuration import STTConfig
from voice.base import VoiceInputProvider


TranscriptTransport = Callable[[str, Mapping[str, str], float], object]


class CustomAPITranscriptProvider(VoiceInputProvider):
    """
    Poll a user-controlled LIGHT transcript-feed API.

    This adapter deliberately consumes completed transcript events, matching the
    existing VoiceInputProvider contract. It does not pretend that LIGHT owns an
    audio capture stream. The API contract is documented in docs/ARCHITECTURE.md.
    """

    def __init__(self, config: STTConfig, transport: TranscriptTransport | None = None):
        if config.provider != "custom_api" or not config.base_url:
            raise ValueError("CustomAPITranscriptProvider requires custom_api STT configuration.")
        self.config = config
        self._transport = transport

    @property
    def provider_name(self) -> str:
        return "custom_api"

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.config.credential_env:
            credential = os.environ.get(self.config.credential_env, "").strip()
            if not credential:
                raise RuntimeError(
                    f"Custom STT credential environment variable {self.config.credential_env} is not set."
                )
            headers["Authorization"] = f"Bearer {credential}"
        return headers

    def _request(self, path: str, params: dict[str, object] | None = None) -> object:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{self.config.base_url}{path}{query}"
        headers = self._headers()
        if self._transport is not None:
            return self._transport(url, headers, self.config.timeout)
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                body = response.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as err:
            raise RuntimeError(f"Custom STT API request failed with HTTP {err.code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError("Custom STT API is unavailable or timed out.") from None
        except json.JSONDecodeError:
            raise RuntimeError("Custom STT API returned a non-JSON response.") from None

    @staticmethod
    def _normalise_item(item: object) -> dict | None:
        if not isinstance(item, dict) or "id" not in item:
            return None
        try:
            item_id = int(item["id"])
        except (TypeError, ValueError):
            return None
        text = item.get("text")
        if text is None:
            text = item.get("transcription_text")
        if text is None:
            return None
        return {"id": item_id, "text": str(text)}

    def is_available(self) -> bool:
        try:
            response = self._request("/v1/transcriptions/latest")
            return isinstance(response, dict)
        except RuntimeError:
            return False

    def get_latest_transcription(self) -> Optional[dict]:
        response = self._request("/v1/transcriptions/latest")
        if not isinstance(response, dict):
            raise RuntimeError("Custom STT API returned an invalid latest-transcription response.")
        raw_item = response.get("transcription", response)
        if raw_item in ({}, None):
            return None
        item = self._normalise_item(raw_item)
        if item is None:
            raise RuntimeError("Custom STT API returned a malformed transcription event.")
        return item

    def get_transcriptions_since(self, last_id: Optional[int]) -> list[dict]:
        if last_id is None:
            latest = self.get_latest_transcription()
            return [latest] if latest is not None else []
        response = self._request("/v1/transcriptions", {"after_id": int(last_id)})
        if not isinstance(response, dict) or not isinstance(response.get("transcriptions"), list):
            raise RuntimeError("Custom STT API returned an invalid transcription list.")
        items: list[dict] = []
        for raw_item in response["transcriptions"]:
            item = self._normalise_item(raw_item)
            if item is None:
                raise RuntimeError("Custom STT API returned a malformed transcription event.")
            items.append(item)
        return sorted(items, key=lambda item: item["id"])

    def get_status_message(self) -> str:
        model = self.config.model or "service-managed"
        return f"Custom transcript API ({model}) at {self.config.base_url}"
