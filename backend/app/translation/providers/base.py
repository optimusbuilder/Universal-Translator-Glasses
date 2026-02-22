from __future__ import annotations

from abc import ABC, abstractmethod

from backend.app.translation.types import TranslationPayload
from backend.app.windowing.types import LandmarkWindow


class TranslationProviderError(Exception):
    """Raised when a translation provider call fails."""


class TranslationProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def translate(self, window: LandmarkWindow) -> TranslationPayload:
        raise NotImplementedError

