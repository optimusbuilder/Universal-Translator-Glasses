from __future__ import annotations

import random
import zlib

from backend.app.ingest.sources.base import FramePacket
from backend.app.landmarks.extractors.base import HandLandmarkExtractor
from backend.app.landmarks.types import HandLandmarks, LandmarkPoint


class MockHandLandmarkExtractor(HandLandmarkExtractor):
    """Deterministic pseudo-landmarks for non-hardware/non-mediapipe testing."""

    def __init__(self, detection_rate: float = 0.85) -> None:
        self._detection_rate = max(0.0, min(1.0, detection_rate))

    @property
    def name(self) -> str:
        return "mock-hands-extractor"

    async def extract(self, frame: FramePacket) -> list[HandLandmarks]:
        seed = zlib.crc32(frame.payload) ^ frame.frame_id
        rng = random.Random(seed)

        if rng.random() > self._detection_rate:
            return []

        hand_count = 1 if rng.random() < 0.9 else 2
        hands: list[HandLandmarks] = []
        for hand_index in range(hand_count):
            handedness = "right" if (hand_index + frame.frame_id) % 2 == 0 else "left"
            confidence = round(0.55 + (rng.random() * 0.45), 4)
            landmarks = [
                LandmarkPoint(
                    x=round(rng.random(), 6),
                    y=round(rng.random(), 6),
                    z=round((rng.random() * 0.4) - 0.2, 6),
                )
                for _ in range(21)
            ]
            hands.append(
                HandLandmarks(
                    hand_index=hand_index,
                    handedness=handedness,
                    confidence=confidence,
                    landmarks=landmarks,
                )
            )

        return hands

