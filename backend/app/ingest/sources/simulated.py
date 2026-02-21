from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import monotonic

from backend.app.ingest.sources.base import (
    CameraSource,
    CameraSourceDisconnected,
    FramePacket,
)


class SimulatedCameraSource(CameraSource):
    """Synthetic camera source for ingest testing before hardware is connected."""

    def __init__(
        self,
        fps: float,
        disconnect_after_seconds: float,
        disconnect_duration_seconds: float,
        source_name: str = "simulated-camera",
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be > 0")

        self._source_name = source_name
        self._frame_interval = 1.0 / fps
        self._disconnect_after_seconds = disconnect_after_seconds
        self._disconnect_duration_seconds = max(0.0, disconnect_duration_seconds)

        self._connected = False
        self._started_at = 0.0
        self._next_frame_at = 0.0
        self._frame_id = 0
        self._disconnect_window_end = 0.0
        self._disconnect_injected = False

    @property
    def name(self) -> str:
        return self._source_name

    async def connect(self) -> None:
        self._connected = True
        now = monotonic()
        self._started_at = now
        self._next_frame_at = now
        self._disconnect_window_end = 0.0

    async def read_frame(self) -> FramePacket:
        if not self._connected:
            raise CameraSourceDisconnected("source is not connected")

        now = monotonic()
        elapsed = now - self._started_at

        if (
            self._disconnect_after_seconds >= 0
            and not self._disconnect_injected
            and elapsed >= self._disconnect_after_seconds
        ):
            self._disconnect_window_end = now + self._disconnect_duration_seconds
            self._disconnect_injected = True

        if self._disconnect_window_end > now:
            raise CameraSourceDisconnected("simulated network interruption")

        delay = self._next_frame_at - now
        if delay > 0:
            await asyncio.sleep(delay)

        emit_time = monotonic()
        self._next_frame_at = emit_time + self._frame_interval
        self._frame_id += 1

        return FramePacket(
            frame_id=self._frame_id,
            captured_at=datetime.now(timezone.utc),
            payload=f"simulated-frame-{self._frame_id}".encode("utf-8"),
            source_name=self._source_name,
        )

    async def disconnect(self) -> None:
        self._connected = False

