from __future__ import annotations

import json
from typing import Any

import httpx

from backend.app.settings import Settings
from backend.app.translation.providers.base import (
    TranslationProvider,
    TranslationProviderError,
)
from backend.app.translation.types import TranslationPayload
from backend.app.windowing.types import LandmarkWindow


class GeminiTranslationProvider(TranslationProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise TranslationProviderError("GEMINI_API_KEY is required for gemini mode")
        self._settings = settings
        self._model_name = settings.gemini_model.removeprefix("models/")

    @property
    def name(self) -> str:
        return "gemini-translation-provider"

    async def translate(self, window: LandmarkWindow) -> TranslationPayload:
        prompt = self._build_prompt(window)
        endpoint = (
            f"{self._settings.gemini_api_base_url}/models/"
            f"{self._model_name}:generateContent"
        )
        headers = {"x-goog-api-key": self._settings.gemini_api_key}
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 120,
            },
        }

        timeout = httpx.Timeout(self._settings.translation_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, headers=headers, json=body)
        except httpx.RequestError as exc:
            raise TranslationProviderError(f"gemini_request_error:{exc}") from exc

        if response.status_code != 200:
            raise TranslationProviderError(f"gemini_status_error:{response.status_code}")

        payload = response.json()
        text = self._extract_text(payload)
        if not text:
            raise TranslationProviderError("gemini_empty_text_response")

        confidence = self._estimate_confidence(text)
        return TranslationPayload(text=text, confidence=confidence)

    def _build_prompt(self, window: LandmarkWindow) -> str:
        frame_summary: list[dict[str, Any]] = []
        for frame in window.frames:
            hands = [
                {
                    "handedness": hand.handedness,
                    "confidence": hand.confidence,
                    "landmarks": [point.to_dict() for point in hand.landmarks],
                }
                for hand in frame.hands
            ]
            frame_summary.append(
                {
                    "frame_id": frame.frame_id,
                    "captured_at": frame.captured_at.isoformat(),
                    "hands": hands,
                }
            )

        return (
            "You are translating ASL hand-landmark sequences to plain English.\n"
            "Return only the best concise English translation.\n"
            "If uncertain, include '[unclear]'.\n"
            f"Window metadata: id={window.window_id}, frame_count={window.frame_count}\n"
            f"Frames JSON: {json.dumps(frame_summary, separators=(',', ':'))}"
        )

    def _extract_text(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return ""

        first = candidates[0]
        content = first.get("content", {})
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            return ""

        segments: list[str] = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                segments.append(part["text"])

        return " ".join(segment.strip() for segment in segments if segment.strip()).strip()

    def _estimate_confidence(self, text: str) -> float:
        if "[unclear]" in text.lower():
            return 0.45
        return 0.75
