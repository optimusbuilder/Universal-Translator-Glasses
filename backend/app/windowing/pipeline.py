from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from backend.app.landmarks.types import LandmarkResult
from backend.app.settings import Settings
from backend.app.windowing.types import LandmarkWindow


@dataclass
class WindowingMetrics:
    started_at: str | None = None
    running: bool = False
    healthy: bool = False
    landmarks_received: int = 0
    queue_drops: int = 0
    windows_emitted: int = 0
    out_of_order_count: int = 0
    last_window_emitted_at: str | None = None
    last_error: str | None = None
    queue_size: int = 0
    buffer_size: int = 0
    next_window_start: str | None = None


class WindowingPipeline:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger
        self._queue: asyncio.Queue[LandmarkResult] = asyncio.Queue(
            maxsize=max(1, settings.window_queue_maxsize)
        )
        self._metrics = WindowingMetrics()
        self._buffer: deque[LandmarkResult] = deque()
        self._recent_windows: deque[LandmarkWindow] = deque(
            maxlen=max(1, settings.window_recent_results_limit)
        )
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._lock = asyncio.Lock()
        self._window_handlers: list[Callable[[LandmarkWindow], Awaitable[None]]] = []

        self._window_duration = timedelta(
            seconds=max(0.1, settings.window_duration_seconds)
        )
        self._window_slide = timedelta(seconds=max(0.05, settings.window_slide_seconds))
        self._next_window_start: datetime | None = None
        self._window_id = 0

    def register_window_handler(
        self, handler: Callable[[LandmarkWindow], Awaitable[None]]
    ) -> None:
        self._window_handlers.append(handler)

    async def start(self) -> None:
        if not self._settings.windowing_enabled:
            self._logger.info(
                "windowing_pipeline_disabled",
                extra={
                    "event": "windowing_disabled",
                    "service_name": self._settings.service_name,
                    "service_version": self._settings.service_version,
                },
            )
            return

        if self._task is not None and not self._task.done():
            return

        self._stopping = False
        async with self._lock:
            self._metrics.running = True
            self._metrics.healthy = True
            self._metrics.started_at = datetime.now(timezone.utc).isoformat()
            self._metrics.last_error = None

        self._logger.info(
            "windowing_pipeline_started",
            extra={
                "event": "windowing_started",
                "service_name": self._settings.service_name,
                "service_version": self._settings.service_version,
                "window_duration_seconds": self._settings.window_duration_seconds,
                "window_slide_seconds": self._settings.window_slide_seconds,
            },
        )

        self._task = asyncio.create_task(self._run(), name="windowing-pipeline-loop")

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
            self._metrics.buffer_size = len(self._buffer)

        self._buffer.clear()
        self._next_window_start = None
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    async def enqueue_landmark_result(self, result: LandmarkResult) -> None:
        if not self._settings.windowing_enabled:
            return

        try:
            self._queue.put_nowait(result)
        except asyncio.QueueFull:
            async with self._lock:
                self._metrics.queue_drops += 1
                self._metrics.queue_size = self._queue.qsize()
                self._metrics.last_error = "windowing_queue_full"
            return

        async with self._lock:
            self._metrics.landmarks_received += 1
            self._metrics.queue_size = self._queue.qsize()

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self._metrics)
        payload["windowing_enabled"] = self._settings.windowing_enabled
        payload["running"] = bool(self._task is not None and not self._task.done())
        payload["queue_size"] = self._queue.qsize()
        payload["buffer_size"] = len(self._buffer)
        payload["recent_windows_count"] = len(self._recent_windows)
        payload["window_duration_seconds"] = self._settings.window_duration_seconds
        payload["window_slide_seconds"] = self._settings.window_slide_seconds
        payload["next_window_start"] = (
            self._next_window_start.isoformat() if self._next_window_start else None
        )
        return payload

    def recent_windows(self, limit: int = 5) -> list[dict[str, object]]:
        bounded = max(1, min(limit, 100))
        return [window.to_dict() for window in list(self._recent_windows)[-bounded:]][::-1]

    async def _run(self) -> None:
        while not self._stopping:
            result = await self._queue.get()
            try:
                await self._process_result(result)
            finally:
                self._queue.task_done()

    async def _process_result(self, result: LandmarkResult) -> None:
        if self._buffer and result.captured_at < self._buffer[-1].captured_at:
            async with self._lock:
                self._metrics.out_of_order_count += 1

        self._buffer.append(result)

        if self._next_window_start is None:
            self._next_window_start = result.captured_at

        await self._emit_windows_if_ready()

        async with self._lock:
            self._metrics.queue_size = self._queue.qsize()
            self._metrics.buffer_size = len(self._buffer)
            self._metrics.next_window_start = (
                self._next_window_start.isoformat() if self._next_window_start else None
            )

    async def _emit_windows_if_ready(self) -> None:
        if not self._buffer or self._next_window_start is None:
            return

        newest_time = self._buffer[-1].captured_at

        while newest_time >= self._next_window_start + self._window_duration:
            start = self._next_window_start
            end = start + self._window_duration

            frames = [
                frame
                for frame in self._buffer
                if start <= frame.captured_at < end
            ]
            frames.sort(key=lambda item: item.captured_at)

            if frames:
                self._window_id += 1
                window = LandmarkWindow(
                    window_id=self._window_id,
                    window_start=start,
                    window_end=end,
                    frame_count=len(frames),
                    frames=frames,
                )
                self._recent_windows.append(window)
                for handler in self._window_handlers:
                    try:
                        await handler(window)
                    except Exception as exc:  # pragma: no cover - safety net
                        self._logger.error(
                            "window_handler_error",
                            extra={
                                "event": "window_handler_error",
                                "service_name": self._settings.service_name,
                                "service_version": self._settings.service_version,
                                "reason": str(exc),
                                "window_id": window.window_id,
                            },
                        )
                async with self._lock:
                    self._metrics.windows_emitted += 1
                    self._metrics.last_window_emitted_at = datetime.now(
                        timezone.utc
                    ).isoformat()
                    self._metrics.healthy = True
                    self._metrics.last_error = None

            buffer_cutoff = start - self._window_slide
            while self._buffer and self._buffer[0].captured_at < buffer_cutoff:
                self._buffer.popleft()

            self._next_window_start = self._next_window_start + self._window_slide
