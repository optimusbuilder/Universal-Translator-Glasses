from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable

import httpx

from backend.app.ingest.sources.base import (
    CameraSource,
    CameraSourceDisconnected,
    CameraSourceError,
    FramePacket,
)


class ESP32HttpCameraSource(CameraSource):
    """HTTP polling source for ESP32 frame endpoints."""

    def __init__(
        self,
        base_url: str,
        frame_path: str,
        request_timeout_seconds: float,
        poll_interval_seconds: float,
        source_name: str = "esp32-http-camera",
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._frame_path = frame_path if frame_path.startswith("/") else f"/{frame_path}"
        self._request_timeout_seconds = request_timeout_seconds
        self._poll_interval_seconds = max(0.0, poll_interval_seconds)
        self._source_name = source_name
        self._client_factory = client_factory

        self._client: httpx.AsyncClient | None = None
        self._frame_id = 0

    @property
    def name(self) -> str:
        return self._source_name

    async def connect(self) -> None:
        if self._client is not None:
            return

        if self._client_factory is not None:
            self._client = self._client_factory()
        else:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._request_timeout_seconds,
            )

    async def read_frame(self) -> FramePacket:
        if self._client is None:
            raise CameraSourceDisconnected("esp32 client is not connected")

        try:
            response = await self._client.get(self._frame_path)
        except httpx.RequestError as exc:
            raise CameraSourceDisconnected(f"esp32_request_error:{exc}") from exc

        if response.status_code != 200:
            raise CameraSourceDisconnected(f"esp32_status_error:{response.status_code}")

        payload = response.content
        if not payload:
            raise CameraSourceError("esp32_empty_frame_payload")

        self._frame_id += 1
        packet = FramePacket(
            frame_id=self._frame_id,
            captured_at=datetime.now(timezone.utc),
            payload=payload,
            source_name=self._source_name,
        )

        if self._poll_interval_seconds > 0:
            await asyncio.sleep(self._poll_interval_seconds)

        return packet

    async def disconnect(self) -> None:
        if self._client is None:
            return

        await self._client.aclose()
        self._client = None

