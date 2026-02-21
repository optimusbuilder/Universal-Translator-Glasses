from __future__ import annotations

from backend.app.ingest.sources.base import FramePacket
from backend.app.landmarks.extractors.base import HandLandmarkExtractor, LandmarkExtractorError
from backend.app.landmarks.types import HandLandmarks


class MediaPipeHandLandmarkExtractor(HandLandmarkExtractor):
    """
    Placeholder for MediaPipe-based extraction.

    This class fails fast if mediapipe integration is not installed/configured yet.
    It keeps the Phase 3 interface stable while we iterate on integration details.
    """

    @property
    def name(self) -> str:
        return "mediapipe-hands-extractor"

    async def extract(self, frame: FramePacket) -> list[HandLandmarks]:
        raise LandmarkExtractorError(
            "mediapipe extractor is not yet enabled in this environment. "
            "Use LANDMARK_MODE=mock for current Phase 3 runs."
        )

