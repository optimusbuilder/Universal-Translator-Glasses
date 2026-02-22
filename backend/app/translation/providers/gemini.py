from __future__ import annotations

import json
import math
from typing import Any

import httpx

from backend.app.landmarks.types import LandmarkPoint
from backend.app.landmarks.types import LandmarkResult
from backend.app.settings import Settings
from backend.app.translation.providers.base import (
    TranslationProvider,
    TranslationProviderError,
)
from backend.app.translation.types import TranslationPayload
from backend.app.windowing.types import LandmarkWindow

_KEYPOINT_ORDER = (0, 4, 8, 12, 16, 20, 5, 9, 13, 17, 2)


class GeminiTranslationProvider(TranslationProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise TranslationProviderError("GEMINI_API_KEY is required for gemini mode")
        self._settings = settings
        self._model_name = settings.gemini_model.removeprefix("models/")

    @property
    def name(self) -> str:
        return "gemini-translation-provider"

    async def translate(self, window: LandmarkWindow) -> TranslationPayload:
        prompt = self._build_prompt(window)
        endpoint = (
            f"{self._settings.gemini_api_base_url}/models/"
            f"{self._model_name}:generateContent"
        )
        headers = {"x-goog-api-key": self._settings.gemini_api_key}
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self._settings.translation_temperature,
                "maxOutputTokens": self._settings.translation_output_max_tokens,
                "responseMimeType": "text/plain",
            },
        }

        timeout = httpx.Timeout(self._settings.translation_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, headers=headers, json=body)
        except httpx.RequestError as exc:
            raise TranslationProviderError(f"gemini_request_error:{exc}") from exc

        if response.status_code == 429:
            retry_after = self._parse_retry_after_seconds(response.headers.get("retry-after"))
            if retry_after is not None:
                raise TranslationProviderError(
                    f"gemini_rate_limited:{round(retry_after, 3)}"
                )
            raise TranslationProviderError("gemini_rate_limited")

        if response.status_code != 200:
            raise TranslationProviderError(f"gemini_status_error:{response.status_code}")

        payload = response.json()
        text, finish_reason = self._extract_text(payload)
        if not text:
            reason = f":{finish_reason}" if finish_reason else ""
            raise TranslationProviderError(f"gemini_empty_text_response{reason}")

        confidence = self._estimate_confidence(text)
        return TranslationPayload(text=text, confidence=confidence)

    def _build_prompt(self, window: LandmarkWindow) -> str:
        sampled_frames = self._sample_frames(window)
        frame_summary: list[dict[str, Any]] = []
        previous_tips: dict[str, tuple[float, float, float]] = {}

        for frame in sampled_frames:
            compact_hands: list[dict[str, Any]] = []

            for hand in sorted(frame.hands, key=lambda item: item.confidence, reverse=True):
                if hand.confidence < self._settings.translation_hand_confidence_threshold:
                    continue

                compact_points = self._normalize_points(hand.landmarks)
                if not compact_points:
                    continue

                index_tip = tuple(compact_points[2])
                cache_key = hand.handedness.lower()
                motion = 0.0
                if cache_key in previous_tips:
                    motion = self._distance(index_tip, previous_tips[cache_key])
                previous_tips[cache_key] = index_tip

                compact_hands.append(
                    {
                        "side": cache_key,
                        "c": round(hand.confidence, 2),
                        "m": round(motion, 3),
                        "p": compact_points,
                    }
                )

            if compact_hands:
                frame_summary.append(
                    {
                        "t": round((frame.captured_at - window.window_start).total_seconds(), 3),
                        "h": compact_hands,
                    }
                )

        if not frame_summary:
            return (
                "No reliable hand landmarks detected in this window. "
                "Return exactly: UNCLEAR"
            )

        keypoint_names = (
            "wrist, thumb_tip, index_tip, middle_tip, ring_tip, pinky_tip, "
            "index_mcp, middle_mcp, ring_mcp, pinky_mcp, thumb_mcp"
        )
        return (
            "Translate ASL motion into plain English.\n"
            "Each frame has: t(seconds), h(hands).\n"
            "Each hand has: side, c(confidence), m(index-tip motion), "
            "p(normalized 3D points).\n"
            f"Point order is fixed: {keypoint_names}.\n"
            "Output one short phrase (1-4 words) only.\n"
            "If uncertain, output exactly UNCLEAR.\n"
            "Never output THINK, analysis, markdown, JSON, or punctuation wrappers.\n"
            f"Frames: {json.dumps(frame_summary, separators=(',', ':'))}"
        )

    def _extract_text(self, payload: dict[str, Any]) -> tuple[str, str | None]:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return "", None

        first = candidates[0]
        finish_reason = first.get("finishReason")
        content = first.get("content", {})
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            return "", str(finish_reason) if finish_reason else None

        segments: list[str] = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                segments.append(part["text"])

        text = " ".join(segment.strip() for segment in segments if segment.strip()).strip()
        return text, str(finish_reason) if finish_reason else None

    def _parse_retry_after_seconds(self, raw: str | None) -> float | None:
        if not raw:
            return None
        value = raw.strip()
        if not value:
            return None
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed < 0:
            return None
        return parsed

    def _sample_frames(self, window: LandmarkWindow) -> list[LandmarkResult]:
        frames_with_hands = [frame for frame in window.frames if frame.hands]
        if not frames_with_hands:
            return []

        max_frames = max(3, self._settings.translation_window_max_frames)
        if len(frames_with_hands) <= max_frames:
            return frames_with_hands

        step = (len(frames_with_hands) - 1) / float(max_frames - 1)
        sampled: list[LandmarkResult] = []
        used_indexes: set[int] = set()
        for slot in range(max_frames):
            index = int(round(slot * step))
            index = min(len(frames_with_hands) - 1, max(0, index))
            if index in used_indexes:
                continue
            used_indexes.add(index)
            sampled.append(frames_with_hands[index])
        return sampled

    def _normalize_points(
        self,
        landmarks: list[LandmarkPoint],
    ) -> list[list[float]]:
        if len(landmarks) < 21:
            return []

        wrist = landmarks[0]
        index_mcp = landmarks[5]
        pinky_mcp = landmarks[17]
        scale = self._distance_xyz(index_mcp, pinky_mcp)
        if scale <= 1e-6:
            scale = 1.0

        normalized: list[list[float]] = []
        for point_index in _KEYPOINT_ORDER:
            point = landmarks[point_index]
            normalized.append(
                [
                    round((point.x - wrist.x) / scale, 3),
                    round((point.y - wrist.y) / scale, 3),
                    round((point.z - wrist.z) / scale, 3),
                ]
            )
        return normalized

    def _distance(
        self,
        left: tuple[float, float, float],
        right: tuple[float, float, float],
    ) -> float:
        dx = left[0] - right[0]
        dy = left[1] - right[1]
        dz = left[2] - right[2]
        return math.sqrt((dx * dx) + (dy * dy) + (dz * dz))

    def _distance_xyz(self, left: LandmarkPoint, right: LandmarkPoint) -> float:
        dx = left.x - right.x
        dy = left.y - right.y
        dz = left.z - right.z
        return math.sqrt((dx * dx) + (dy * dy) + (dz * dz))

    def _estimate_confidence(self, text: str) -> float:
        lowered = text.lower().strip()
        if "unclear" in lowered or lowered in {"unknown", "n/a", "na"}:
            return 0.45
        if len("".join(ch for ch in text if ch.isalpha())) < 2:
            return 0.4
        return 0.75
