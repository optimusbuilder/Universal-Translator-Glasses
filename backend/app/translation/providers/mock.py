from __future__ import annotations

import hashlib

from backend.app.translation.providers.base import TranslationProvider
from backend.app.translation.types import TranslationPayload
from backend.app.windowing.types import LandmarkWindow

MOCK_PHRASES = [
    "Hello, nice to meet you.",
    "Can you help me with directions?",
    "Please wait a moment.",
    "I need assistance.",
    "Thank you for your help.",
    "Where is the nearest exit?",
    "I understand.",
]


class MockTranslationProvider(TranslationProvider):
    @property
    def name(self) -> str:
        return "mock-translation-provider"

    async def translate(self, window: LandmarkWindow) -> TranslationPayload:
        confidence_values: list[float] = []
        for frame in window.frames:
            for hand in frame.hands:
                confidence_values.append(float(hand.confidence))

        avg_conf = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        seed = hashlib.sha256(f"{window.window_id}:{window.frame_count}".encode("utf-8")).hexdigest()
        phrase_index = int(seed[:8], 16) % len(MOCK_PHRASES)
        text = MOCK_PHRASES[phrase_index]

        if avg_conf < 0.45:
            text = f"{text} [unclear]"

        return TranslationPayload(text=text, confidence=round(avg_conf, 4))

