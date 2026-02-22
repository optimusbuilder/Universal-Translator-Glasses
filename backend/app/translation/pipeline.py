from __future__ import annotations

import asyncio
import logging
import re
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
from backend.app.translation.providers.image_classifier import (
    ImageClassifierTranslationProvider,
)
from backend.app.translation.providers.local_classifier import (
    LocalClassifierTranslationProvider,
)
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
    windows_skipped_low_signal: int = 0
    windows_suppressed_unclear: int = 0
    windows_processed: int = 0
    partial_emitted: int = 0
    final_emitted: int = 0
    retry_events: int = 0
    average_processing_ms: float = 0.0
    last_processing_ms: float = 0.0
    last_result_at: str | None = None
    last_model_text_preview: str | None = None
    last_normalized_text_preview: str | None = None
    last_window_frame_count: int = 0
    last_window_frames_with_hands: int = 0
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
        self._next_request_at: float = 0.0
        self._rate_limited_until: float = 0.0

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
        if self._settings.translation_mode == "local_classifier":
            payload["configured_model"] = self._settings.local_classifier_model_path
        elif self._settings.translation_mode == "image_classifier":
            payload["configured_model"] = self._settings.image_classifier_model_path
        else:
            payload["configured_model"] = self._settings.gemini_model
        payload["running"] = bool(self._task is not None and not self._task.done())
        payload["queue_size"] = self._queue.qsize()
        payload["recent_results_count"] = len(self._recent_results)
        payload["rate_limited_remaining_seconds"] = round(
            max(0.0, self._rate_limited_until - monotonic()),
            3,
        )
        return payload

    def recent_results(self, limit: int = 10) -> list[dict[str, object]]:
        bounded = max(1, min(limit, 100))
        return [item.to_dict() for item in list(self._recent_results)[-bounded:]][::-1]

    def _build_provider(self, settings: Settings) -> TranslationProvider:
        if settings.translation_mode == "gemini":
            return GeminiTranslationProvider(settings=settings)
        if settings.translation_mode == "local_classifier":
            return LocalClassifierTranslationProvider(settings=settings)
        if settings.translation_mode == "image_classifier":
            return ImageClassifierTranslationProvider(settings=settings)

        raise ValueError(
            "unsupported translation mode. Expected 'gemini', "
            "'local_classifier', or 'image_classifier'."
        )

    async def _run(self) -> None:
        while not self._stopping:
            window = await self._queue.get()
            try:
                await self._process_window(window)
            finally:
                self._queue.task_done()

    async def _process_window(self, window: LandmarkWindow) -> None:
        if self._settings.translation_mode == "gemini":
            now = monotonic()
            if now < self._rate_limited_until:
                async with self._lock:
                    self._metrics.windows_suppressed_unclear += 1
                    self._metrics.queue_size = self._queue.qsize()
                    self._metrics.healthy = True
                    self._metrics.last_error = "gemini_rate_limited_backoff"
                return

        frames_with_hands = sum(1 for frame in window.frames if frame.hands)
        async with self._lock:
            self._metrics.last_window_frame_count = len(window.frames)
            self._metrics.last_window_frames_with_hands = frames_with_hands
        if frames_with_hands < max(1, self._settings.translation_min_frames_with_hands):
            async with self._lock:
                self._metrics.windows_skipped_low_signal += 1
                self._metrics.queue_size = self._queue.qsize()
                self._metrics.healthy = True
                self._metrics.last_error = (
                    "low_signal_window:"
                    f"{frames_with_hands}/{max(1, self._settings.translation_min_frames_with_hands)}"
                )
            return

        started = monotonic()
        payload: TranslationPayload | None = None
        retry_count = 0
        last_error: str | None = None

        max_attempts = max(1, self._settings.translation_max_retries + 1)
        for attempt in range(max_attempts):
            if self._settings.translation_mode == "gemini":
                await self._apply_request_throttle()
            try:
                payload = await self._provider.translate(window)
                if self._settings.translation_mode == "gemini":
                    self._mark_request_sent()
                break
            except TranslationProviderError as exc:
                if self._settings.translation_mode == "gemini":
                    self._mark_request_sent()
                retry_count = attempt
                last_error = str(exc)
                async with self._lock:
                    self._metrics.retry_events += 1
                    self._metrics.last_error = last_error

                if (
                    self._settings.translation_mode == "gemini"
                    and last_error.startswith("gemini_rate_limited")
                ):
                    self._apply_rate_limit_backoff(last_error)
                    break

                if attempt + 1 < max_attempts:
                    await asyncio.sleep(self._settings.translation_retry_backoff_seconds)

        if payload is None:
            payload = TranslationPayload(text="[unclear]", confidence=0.2)
            async with self._lock:
                self._metrics.last_error = last_error or "translation_failed"
                self._metrics.healthy = False
                self._metrics.last_model_text_preview = None
                self._metrics.last_normalized_text_preview = "[unclear]"

        raw_preview = (payload.text or "").strip().replace("\n", " ")
        if len(raw_preview) > 120:
            raw_preview = f"{raw_preview[:117]}..."
        async with self._lock:
            self._metrics.last_model_text_preview = raw_preview or None

        final_text, final_conf, uncertain = self._normalize_translation(payload)
        async with self._lock:
            self._metrics.last_normalized_text_preview = final_text

        if final_text == "[unclear]" and not self._settings.translation_emit_unclear_captions:
            async with self._lock:
                self._metrics.windows_suppressed_unclear += 1
                self._metrics.queue_size = self._queue.qsize()
                self._metrics.healthy = True
            return

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

    async def _apply_request_throttle(self) -> None:
        min_interval = max(0.0, self._settings.translation_min_request_interval_seconds)
        if min_interval <= 0:
            return
        now = monotonic()
        if now < self._next_request_at:
            await asyncio.sleep(self._next_request_at - now)

    def _mark_request_sent(self) -> None:
        min_interval = max(0.0, self._settings.translation_min_request_interval_seconds)
        if min_interval <= 0:
            return
        self._next_request_at = monotonic() + min_interval

    def _apply_rate_limit_backoff(self, error_message: str) -> None:
        default_backoff = max(
            0.0,
            self._settings.translation_rate_limit_cooldown_seconds,
        )
        parsed_backoff = self._parse_backoff_from_error(error_message)
        cooldown = max(default_backoff, parsed_backoff)
        self._rate_limited_until = monotonic() + cooldown

    def _parse_backoff_from_error(self, error_message: str) -> float:
        if ":" not in error_message:
            return 0.0
        _, _, tail = error_message.partition(":")
        try:
            value = float(tail)
        except ValueError:
            return 0.0
        return max(0.0, value)

    def _normalize_translation(self, payload: TranslationPayload) -> tuple[str, float, bool]:
        text = (payload.text or "").strip()
        if self._settings.translation_mode in {"local_classifier", "image_classifier"}:
            text = text.replace("_", " ")
        text = text.replace("`", "").replace('"', "").strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            text = "[unclear]"

        lowered = text.lower()
        compact = lowered.strip("[](){}:;,.!? ").strip()
        prompt_leak = False
        if self._settings.translation_mode == "gemini":
            prompt_leak_markers = (
                "think",
                "window metadata",
                "frames json",
                "asl hand-landmark",
                "return exactly one line",
                "do not use brackets",
                "if uncertain",
                "translate asl",
                "no extra commentary",
            )
            prompt_leak = (
                any(marker in lowered for marker in prompt_leak_markers)
                or compact in {"think", "thought", "reasoning", "analysis"}
                or compact.startswith("think:")
            )
        alpha_count = sum(1 for char in text if char.isalpha())
        punctuation_only = all(not char.isalnum() for char in text)
        unmatched_brackets = text.count("[") != text.count("]")
        malformed_unclear = lowered.startswith("[") and "unclear" not in lowered
        short_label_tokens = {
            *{chr(code) for code in range(ord("A"), ord("Z") + 1)},
            "DEL",
            "SPACE",
            "NOTHING",
        }
        looks_like_short_label = text.strip().upper() in short_label_tokens
        tiny_token = not looks_like_short_label and (
            len(text) <= 1 or (len(text) <= 3 and alpha_count < 2)
        )
        unclear_prefix_token = (
            compact.startswith("unc")
            and len(compact) <= 8
            and " " not in compact
        )

        if (
            prompt_leak
            or "unclear" in lowered
            or unclear_prefix_token
            or lowered in {"unknown", "n/a", "na"}
            or punctuation_only
            or unmatched_brackets
            or malformed_unclear
            or tiny_token
        ):
            text = "[unclear]"

        confidence = max(0.0, min(1.0, float(payload.confidence)))
        if text == "[unclear]":
            confidence = min(confidence, 0.45)
        uncertain = confidence < self._settings.translation_uncertainty_threshold

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
