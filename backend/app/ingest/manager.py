from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Awaitable, Callable

from backend.app.ingest.sources.base import (
    CameraSource,
    CameraSourceDisconnected,
    CameraSourceError,
    FramePacket,
)
from backend.app.ingest.sources.esp32_http import ESP32HttpCameraSource
from backend.app.settings import Settings


@dataclass
class IngestMetrics:
    source_mode: str
    source_name: str | None = None
    started_at: str | None = None
    connected: bool = False
    healthy: bool = False
    frames_received: int = 0
    dropped_frames: int = 0
    reconnect_count: int = 0
    effective_fps: float = 0.0
    last_frame_at: str | None = None
    last_error: str | None = None


class IngestManager:
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        source_factory_override: Callable[[], CameraSource] | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._metrics = IngestMetrics(source_mode=settings.camera_source_mode)
        self._fps_window_seconds = 5.0
        self._recent_frame_times: deque[float] = deque()
        self._source_factory = source_factory_override or self._build_source_factory(settings)
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._lock = asyncio.Lock()
        self._frame_handlers: list[Callable[[FramePacket], Awaitable[None]]] = []

    def register_frame_handler(
        self, handler: Callable[[FramePacket], Awaitable[None]]
    ) -> None:
        self._frame_handlers.append(handler)

    async def start(self) -> None:
        if not self._settings.ingest_enabled:
            self._logger.info(
                "ingest_disabled",
                extra={
                    "event": "ingest_disabled",
                    "service_name": self._settings.service_name,
                    "service_version": self._settings.service_version,
                },
            )
            return

        if self._task is not None and not self._task.done():
            return

        self._stopping = False
        self._metrics.started_at = datetime.now(timezone.utc).isoformat()
        self._task = asyncio.create_task(self._run(), name="camera-ingest-loop")

    async def stop(self) -> None:
        self._stopping = True

        if self._task is None:
            self._metrics.connected = False
            self._metrics.healthy = False
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

        async with self._lock:
            self._metrics.connected = False
            self._metrics.healthy = False

    def snapshot(self) -> dict[str, object]:
        metrics = asdict(self._metrics)
        metrics["ingest_enabled"] = self._settings.ingest_enabled
        metrics["running"] = self._task is not None and not self._task.done()
        return metrics

    def _build_source_factory(self, settings: Settings) -> Callable[[], CameraSource]:
        if settings.camera_source_mode == "esp32_http":
            if not settings.camera_source_url:
                raise ValueError(
                    "camera_source_url is required for CAMERA_SOURCE_MODE=esp32_http"
                )

            return lambda: ESP32HttpCameraSource(
                base_url=settings.camera_source_url or "",
                frame_path=settings.esp32_frame_path,
                request_timeout_seconds=settings.esp32_request_timeout_seconds,
                poll_interval_seconds=settings.esp32_poll_interval_seconds,
            )

        raise ValueError(
            "unsupported camera source mode. Expected 'esp32_http'."
        )

    async def _run(self) -> None:
        while not self._stopping:
            source: CameraSource | None = None

            try:
                source = self._source_factory()
                await source.connect()
                async with self._lock:
                    self._metrics.connected = True
                    self._metrics.healthy = True
                    self._metrics.source_name = source.name
                    self._metrics.last_error = None

                self._logger.info(
                    "ingest_source_connected",
                    extra={
                        "event": "ingest_connected",
                        "service_name": self._settings.service_name,
                        "service_version": self._settings.service_version,
                        "source_name": source.name,
                        "source_mode": self._settings.camera_source_mode,
                    },
                )

                while not self._stopping:
                    try:
                        frame = await source.read_frame()
                    except CameraSourceDisconnected as exc:
                        await self._record_disconnect(str(exc), dropped_frame=True)
                        break
                    except CameraSourceError as exc:
                        await self._record_disconnect(str(exc), dropped_frame=True)
                        break
                    except Exception as exc:  # pragma: no cover - safety net
                        await self._record_error(f"unexpected_frame_error:{exc}", dropped_frame=True)
                        continue

                    await self._record_frame(frame)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._record_disconnect(f"source_connect_error:{exc}", dropped_frame=False)
            finally:
                if source is not None:
                    await source.disconnect()

            if not self._stopping:
                await asyncio.sleep(self._settings.ingest_reconnect_backoff_seconds)

    async def _record_frame(self, frame: FramePacket) -> None:
        now = monotonic()
        self._recent_frame_times.append(now)
        cutoff = now - self._fps_window_seconds
        while self._recent_frame_times and self._recent_frame_times[0] < cutoff:
            self._recent_frame_times.popleft()

        effective_fps = len(self._recent_frame_times) / self._fps_window_seconds

        async with self._lock:
            self._metrics.frames_received += 1
            self._metrics.last_frame_at = frame.captured_at.isoformat()
            self._metrics.effective_fps = round(effective_fps, 3)
            self._metrics.connected = True
            self._metrics.healthy = True
            self._metrics.last_error = None

        for handler in self._frame_handlers:
            try:
                await handler(frame)
            except Exception as exc:  # pragma: no cover - safety net
                await self._record_error(
                    f"frame_handler_error:{type(exc).__name__}:{exc}",
                    dropped_frame=False,
                )

    async def _record_disconnect(self, reason: str, dropped_frame: bool) -> None:
        async with self._lock:
            self._metrics.reconnect_count += 1
            self._metrics.connected = False
            self._metrics.healthy = False
            self._metrics.last_error = reason
            if dropped_frame:
                self._metrics.dropped_frames += 1

        self._logger.warning(
            "ingest_disconnected",
            extra={
                "event": "ingest_disconnected",
                "service_name": self._settings.service_name,
                "service_version": self._settings.service_version,
                "reason": reason,
                "reconnect_count": self._metrics.reconnect_count,
            },
        )

    async def _record_error(self, message: str, dropped_frame: bool) -> None:
        async with self._lock:
            self._metrics.last_error = message
            if dropped_frame:
                self._metrics.dropped_frames += 1

        self._logger.error(
            "ingest_error",
            extra={
                "event": "ingest_error",
                "service_name": self._settings.service_name,
                "service_version": self._settings.service_version,
                "reason": message,
            },
        )
