from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Awaitable, Callable

from backend.app.settings import Settings
from backend.app.translation.providers.base import (
    TranslationProvider,
    TranslationProviderError,
)
from backend.app.translation.providers.gemini import GeminiTranslationProvider
from backend.app.translation.providers.mock import MockTranslationProvider
from backend.app.translation.types import TranslationPayload, TranslationResult
from backend.app.windowing.types import LandmarkWindow


@dataclass
class TranslationMetrics:
    mode: str
    provider_name: str | None = None
    started_at: str | None = None
    running: bool = False
    healthy: bool = False
    windows_enqueued: int = 0
    queue_drops: int = 0
    windows_processed: int = 0
    partial_emitted: int = 0
    final_emitted: int = 0
    retry_events: int = 0
    average_processing_ms: float = 0.0
    last_processing_ms: float = 0.0
    last_result_at: str | None = None
    last_error: str | None = None
    queue_size: int = 0


class TranslationPipeline:
    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        provider_override: TranslationProvider | None = None,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._queue: asyncio.Queue[LandmarkWindow] = asyncio.Queue(
            maxsize=max(1, settings.translation_queue_maxsize)
        )
        self._metrics = TranslationMetrics(mode=settings.translation_mode)
        self._provider = provider_override or self._build_provider(settings)
        self._metrics.provider_name = self._provider.name
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._lock = asyncio.Lock()
        self._recent_results: deque[TranslationResult] = deque(
            maxlen=max(1, settings.translation_recent_results_limit)
        )
        self._result_handlers: list[Callable[[TranslationResult], Awaitable[None]]] = []

    def register_result_handler(
        self, handler: Callable[[TranslationResult], Awaitable[None]]
    ) -> None:
        self._result_handlers.append(handler)

    async def start(self) -> None:
        if not self._settings.translation_enabled:
            self._logger.info(
                "translation_pipeline_disabled",
                extra={
                    "event": "translation_disabled",
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
            "translation_pipeline_started",
            extra={
                "event": "translation_started",
                "service_name": self._settings.service_name,
                "service_version": self._settings.service_version,
                "translation_mode": self._settings.translation_mode,
                "provider_name": self._provider.name,
            },
        )

        self._task = asyncio.create_task(self._run(), name="translation-pipeline-loop")

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

    async def enqueue_window(self, window: LandmarkWindow) -> None:
        if not self._settings.translation_enabled:
            return

        try:
            self._queue.put_nowait(window)
        except asyncio.QueueFull:
            async with self._lock:
                self._metrics.queue_drops += 1
                self._metrics.queue_size = self._queue.qsize()
                self._metrics.last_error = "translation_queue_full"
            return

        async with self._lock:
            self._metrics.windows_enqueued += 1
            self._metrics.queue_size = self._queue.qsize()

    def snapshot(self) -> dict[str, object]:
        payload = asdict(self._metrics)
        payload["translation_enabled"] = self._settings.translation_enabled
        payload["running"] = bool(self._task is not None and not self._task.done())
        payload["queue_size"] = self._queue.qsize()
        payload["recent_results_count"] = len(self._recent_results)
        return payload

    def recent_results(self, limit: int = 10) -> list[dict[str, object]]:
        bounded = max(1, min(limit, 100))
        return [item.to_dict() for item in list(self._recent_results)[-bounded:]][::-1]

    def _build_provider(self, settings: Settings) -> TranslationProvider:
        if settings.translation_mode == "mock":
            return MockTranslationProvider(
                delay_seconds=settings.mock_translation_delay_seconds
            )

        if settings.translation_mode == "gemini":
            return GeminiTranslationProvider(settings=settings)

        raise ValueError("unsupported translation mode. Expected 'mock' or 'gemini'.")

    async def _run(self) -> None:
        while not self._stopping:
            window = await self._queue.get()
            try:
                await self._process_window(window)
            finally:
                self._queue.task_done()

    async def _process_window(self, window: LandmarkWindow) -> None:
        started = monotonic()
        payload: TranslationPayload | None = None
        retry_count = 0
        last_error: str | None = None

        max_attempts = max(1, self._settings.translation_max_retries + 1)
        for attempt in range(max_attempts):
            try:
                payload = await self._provider.translate(window)
                break
            except TranslationProviderError as exc:
                retry_count = attempt
                last_error = str(exc)
                async with self._lock:
                    self._metrics.retry_events += 1

                if attempt + 1 < max_attempts:
                    await asyncio.sleep(self._settings.translation_retry_backoff_seconds)

        if payload is None:
            payload = TranslationPayload(text="[unclear]", confidence=0.2)
            async with self._lock:
                self._metrics.last_error = last_error or "translation_failed"
                self._metrics.healthy = False

        final_text, final_conf, uncertain = self._normalize_translation(payload)
        partial_text = self._build_partial_text(final_text)
        processed_at = datetime.now(timezone.utc)
        latency_ms = round((monotonic() - started) * 1000.0, 3)

        partial_result = TranslationResult(
            window_id=window.window_id,
            kind="partial",
            text=partial_text,
            confidence=final_conf,
            uncertain=uncertain,
            created_at=processed_at,
            latency_ms=latency_ms,
            source_mode=self._settings.translation_mode,
            retry_count=retry_count,
        )
        final_result = TranslationResult(
            window_id=window.window_id,
            kind="final",
            text=final_text,
            confidence=final_conf,
            uncertain=uncertain,
            created_at=processed_at,
            latency_ms=latency_ms,
            source_mode=self._settings.translation_mode,
            retry_count=retry_count,
        )

        self._recent_results.append(partial_result)
        self._recent_results.append(final_result)

        for result in (partial_result, final_result):
            for handler in self._result_handlers:
                try:
                    await handler(result)
                except Exception as exc:  # pragma: no cover - safety net
                    self._logger.error(
                        "translation_result_handler_error",
                        extra={
                            "event": "translation_result_handler_error",
                            "service_name": self._settings.service_name,
                            "service_version": self._settings.service_version,
                            "reason": str(exc),
                            "window_id": window.window_id,
                        },
                    )

        async with self._lock:
            previous_count = self._metrics.windows_processed
            previous_avg = self._metrics.average_processing_ms
            self._metrics.windows_processed += 1
            self._metrics.partial_emitted += 1
            self._metrics.final_emitted += 1
            self._metrics.last_processing_ms = latency_ms
            self._metrics.last_result_at = processed_at.isoformat()
            self._metrics.queue_size = self._queue.qsize()
            self._metrics.healthy = True
            self._metrics.last_error = None
            self._metrics.average_processing_ms = round(
                ((previous_avg * previous_count) + latency_ms)
                / max(1, self._metrics.windows_processed),
                3,
            )

    def _normalize_translation(self, payload: TranslationPayload) -> tuple[str, float, bool]:
        text = (payload.text or "").strip()
        if not text:
            text = "[unclear]"

        confidence = max(0.0, min(1.0, float(payload.confidence)))
        uncertain = confidence < self._settings.translation_uncertainty_threshold
        if uncertain and "[unclear]" not in text.lower():
            text = f"{text} [unclear]"

        return text, round(confidence, 4), uncertain

    def _build_partial_text(self, final_text: str) -> str:
        words = final_text.split()
        if len(words) <= 3:
            return final_text

        cutoff = max(2, int(len(words) * 0.6))
        partial = " ".join(words[:cutoff]).strip()
        if partial and partial != final_text:
            return f"{partial}..."
        return final_text
