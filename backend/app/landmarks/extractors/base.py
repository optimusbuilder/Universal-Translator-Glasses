from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.ingest.sources.base import FramePacket
from backend.app.landmarks.types import HandLandmarks


class LandmarkExtractorError(Exception):
    """Raised when landmark extraction fails."""


class HandLandmarkExtractor(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def extract(self, frame: FramePacket) -> list[HandLandmarks]:
        raise NotImplementedError

