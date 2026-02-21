from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Callable

from backend.app.ingest.sources.base import FramePacket
from backend.app.landmarks.extractors.base import HandLandmarkExtractor, LandmarkExtractorError
from backend.app.landmarks.extractors.mediapipe import MediaPipeHandLandmarkExtractor
from backend.app.landmarks.extractors.mock import MockHandLandmarkExtractor
from backend.app.landmarks.types import LandmarkResult
from backend.app.settings import Settings


@dataclass
class LandmarkMetrics:
    mode: str
    extractor_name: str | None = None
    started_at: str | None = None
    running: bool = False
    healthy: bool = False
    frames_enqueued: int = 0
    queue_drops: int = 0
    frames_processed: int = 0
    frames_with_hands: int = 0
    average_processing_ms: float = 0.0
    last_processing_ms: float = 0.0
    last_result_at: str | None = None
    last_frame_id: int | None = None
    last_error: str | None = None
    queue_size: int = 0


class LandmarkPipeline:
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        extractor_override: HandLandmarkExtractor | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._queue: asyncio.Queue[FramePacket] = asyncio.Queue(
            maxsize=max(1, settings.landmark_queue_maxsize)
        )
        self._metrics = LandmarkMetrics(mode=settings.landmark_mode)
        self._extractor = extractor_override or self._build_extractor(settings)
        self._metrics.extractor_name = self._extractor.name

        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._lock = asyncio.Lock()
        self._recent_results: deque[LandmarkResult] = deque(
            maxlen=max(1, settings.landmark_recent_results_limit)
        )

    async def start(self) -> None:
        if not self._settings.landmark_enabled:
            self._logger.info(
                "landmark_pipeline_disabled",
                extra={
                    "event": "landmark_disabled",
                    "service_name": self._settings.service_name,
                    "service_version": self._settings.service_version,
                },
            )
            return

        if self._task is not None and not self._task.done():
            return

        self._stopping = False
        async with self._lock:
            self._metrics.started_at = datetime.now(timezone.utc).isoformat()
            self._metrics.running = True
            self._metrics.healthy = True
            self._metrics.last_error = None

        self._logger.info(
            "landmark_pipeline_started",
            extra={
                "event": "landmark_started",
                "service_name": self._settings.service_name,
                "service_version": self._settings.service_version,
                "landmark_mode": self._settings.landmark_mode,
                "extractor_name": self._extractor.name,
            },
        )

        self._task = asyncio.create_task(self._run(), name="landmark-pipeline-loop")

    async def stop(self) -> None:
        self._stopping = True

        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None

        async with self._lock:
            self._metrics.running = False
            self._metrics.healthy = False
            self._metrics.queue_size = 0

        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def enqueue_frame(self, frame: FramePacket) -> None:
        if not self._settings.landmark_enabled:
            return

        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            async with self._lock:
                self._metrics.queue_drops += 1
                self._metrics.queue_size = self._queue.qsize()
                self._metrics.last_error = "landmark_queue_full"
            return

        async with self._lock:
            self._metrics.frames_enqueued += 1
            self._metrics.queue_size = self._queue.qsize()

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self._metrics)
        payload["landmark_enabled"] = self._settings.landmark_enabled
        payload["running"] = bool(self._task is not None and not self._task.done())
        payload["recent_results_count"] = len(self._recent_results)
        payload["queue_size"] = self._queue.qsize()
        return payload

    def recent_results(self, limit: int = 5) -> list[dict[str, object]]:
        bounded_limit = max(1, min(limit, 100))
        return [result.to_dict() for result in list(self._recent_results)[-bounded_limit:]][::-1]

    def _build_extractor(self, settings: Settings) -> HandLandmarkExtractor:
        if settings.landmark_mode == "mock":
            return MockHandLandmarkExtractor(
                detection_rate=settings.mock_landmark_detection_rate
            )

        if settings.landmark_mode == "mediapipe":
            return MediaPipeHandLandmarkExtractor()

        raise ValueError(
            "unsupported landmark mode. Expected 'mock' or 'mediapipe'."
        )

    async def _run(self) -> None:
        while not self._stopping:
            frame = await self._queue.get()
            try:
                await self._process_frame(frame)
            finally:
                self._queue.task_done()

    async def _process_frame(self, frame: FramePacket) -> None:
        started = monotonic()
        processed_at = datetime.now(timezone.utc)

        try:
            hands = await self._extractor.extract(frame)
            processing_ms = (monotonic() - started) * 1000.0
            result = LandmarkResult(
                frame_id=frame.frame_id,
                source_name=frame.source_name,
                captured_at=frame.captured_at,
                processed_at=processed_at,
                processing_ms=round(processing_ms, 3),
                hands=hands,
            )
            self._recent_results.append(result)

            async with self._lock:
                previous_count = self._metrics.frames_processed
                previous_avg = self._metrics.average_processing_ms
                self._metrics.frames_processed += 1
                self._metrics.last_frame_id = frame.frame_id
                self._metrics.last_result_at = processed_at.isoformat()
                self._metrics.last_processing_ms = round(processing_ms, 3)
                self._metrics.queue_size = self._queue.qsize()
                self._metrics.healthy = True
                self._metrics.last_error = None
                if hands:
                    self._metrics.frames_with_hands += 1

                self._metrics.average_processing_ms = round(
                    ((previous_avg * previous_count) + processing_ms)
                    / max(1, self._metrics.frames_processed),
                    3,
                )
        except LandmarkExtractorError as exc:
            async with self._lock:
                self._metrics.last_error = str(exc)
                self._metrics.healthy = False
                self._metrics.queue_size = self._queue.qsize()

            self._logger.error(
                "landmark_extraction_error",
                extra={
                    "event": "landmark_error",
                    "service_name": self._settings.service_name,
                    "service_version": self._settings.service_version,
                    "reason": str(exc),
                    "frame_id": frame.frame_id,
                },
            )
        except Exception as exc:  # pragma: no cover - safety net
            async with self._lock:
                self._metrics.last_error = f"unexpected_landmark_error:{exc}"
                self._metrics.healthy = False
                self._metrics.queue_size = self._queue.qsize()

            self._logger.error(
                "landmark_unexpected_error",
                extra={
                    "event": "landmark_unexpected_error",
                    "service_name": self._settings.service_name,
                    "service_version": self._settings.service_version,
                    "reason": str(exc),
                    "frame_id": frame.frame_id,
                },
            )

