from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FramePacket:
    frame_id: int
    captured_at: datetime
    payload: bytes
    source_name: str


class CameraSourceError(Exception):
    """Base camera-source exception."""


class CameraSourceDisconnected(CameraSourceError):
    """Raised when a source disconnects and should be reconnected."""


class CameraSource(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def read_frame(self) -> FramePacket:
        raise NotImplementedError

    @abstractmethod
    async def disconnect(self) -> None:
        raise NotImplementedError

