from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from backend.app.ingest.sources.base import (
    CameraSource,
    CameraSourceDisconnected,
    CameraSourceError,
    FramePacket,
)


class OpenCVCameraSource(CameraSource):
    """Camera source backed by cv2.VideoCapture (device index or stream URL)."""

    def __init__(
        self,
        source: str,
        poll_interval_seconds: float,
        width: int,
        height: int,
        jpeg_quality: int,
        source_name: str = "opencv-capture-camera",
    ) -> None:
        self._source_raw = source.strip()
        self._poll_interval_seconds = max(0.0, poll_interval_seconds)
        self._width = max(0, int(width))
        self._height = max(0, int(height))
        self._jpeg_quality = max(10, min(100, int(jpeg_quality)))
        self._source_name = source_name
        self._capture: Any = None
        self._cv2: Any = None
        self._frame_id = 0

    @property
    def name(self) -> str:
        return self._source_name

    def _source_for_cv2(self) -> int | str:
        if self._source_raw.isdigit():
            return int(self._source_raw)
        return self._source_raw

    async def connect(self) -> None:
        if self._capture is not None:
            return

        try:
            import cv2  # type: ignore[import-not-found]
        except Exception as exc:
            raise CameraSourceError(f"opencv_import_error:{exc}") from exc

        self._cv2 = cv2
        source = self._source_for_cv2()
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            # macOS can require explicit AVFoundation backend.
            if isinstance(source, int):
                capture.release()
                capture = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)

        if not capture.isOpened():
            capture.release()
            raise CameraSourceDisconnected(
                f"opencv_capture_open_failed:source={self._source_raw}"
            )

        if self._width > 0:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self._width))
        if self._height > 0:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self._height))
        # Keep latency low for OBS/virtual-camera streams by limiting internal buffering.
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1.0)
        except Exception:
            pass

        self._capture = capture

    async def read_frame(self) -> FramePacket:
        if self._capture is None or self._cv2 is None:
            raise CameraSourceDisconnected("opencv_capture_not_connected")

        ok, frame = await asyncio.to_thread(self._capture.read)
        if not ok or frame is None:
            raise CameraSourceDisconnected("opencv_capture_read_failed")

        encode_params = [self._cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        encoded_ok, encoded = self._cv2.imencode(".jpg", frame, encode_params)
        if not encoded_ok:
            raise CameraSourceError("opencv_jpeg_encode_failed")

        self._frame_id += 1
        packet = FramePacket(
            frame_id=self._frame_id,
            captured_at=datetime.now(timezone.utc),
            payload=bytes(encoded.tobytes()),
            source_name=self._source_name,
        )

        if self._poll_interval_seconds > 0:
            await asyncio.sleep(self._poll_interval_seconds)

        return packet

    async def disconnect(self) -> None:
        if self._capture is not None:
            await asyncio.to_thread(self._capture.release)
            self._capture = None
