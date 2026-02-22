from __future__ import annotations

import io
from collections import defaultdict

import numpy as np
from PIL import Image

from backend.app.landmarks.types import LandmarkPoint
from backend.app.settings import Settings
from backend.app.translation.image_classifier import (
    load_image_classifier,
    preprocess_image_array,
)
from backend.app.translation.providers.base import (
    TranslationProvider,
    TranslationProviderError,
)
from backend.app.translation.types import TranslationPayload
from backend.app.windowing.types import LandmarkWindow


class ImageClassifierTranslationProvider(TranslationProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        try:
            self._model = load_image_classifier(settings.image_classifier_model_path)
        except Exception as exc:
            raise TranslationProviderError(
                f"image_classifier_model_load_error:{exc}"
            ) from exc

        allowlist_raw = (settings.image_classifier_label_allowlist or "").strip()
        self._allowlist = {
            token.strip().upper() for token in allowlist_raw.split(",") if token.strip()
        }

    @property
    def name(self) -> str:
        return "image-classifier-provider"

    async def translate(self, window: LandmarkWindow) -> TranslationPayload:
        label_scores: dict[str, float] = defaultdict(float)
        label_votes: dict[str, int] = defaultdict(int)
        total_weight = 0.0

        for frame in window.frames:
            if not frame.hands or not frame.frame_payload:
                continue

            best_hand = max(frame.hands, key=lambda item: item.confidence)
            if best_hand.confidence < self._settings.translation_hand_confidence_threshold:
                continue

            image_crop = self._crop_hand_region(frame.frame_payload, best_hand.landmarks)
            if image_crop is None:
                continue

            feature = preprocess_image_array(
                image_crop,
                input_size=self._model.input_size,
            )
            prediction = self._model.predict_feature(feature)
            label = prediction.label.strip().upper()
            if not label:
                continue
            if self._allowlist and label not in self._allowlist:
                continue

            vote_weight = max(0.0, min(1.0, best_hand.confidence)) * prediction.confidence
            if vote_weight <= 0:
                continue

            label_scores[label] += vote_weight
            label_votes[label] += 1
            total_weight += vote_weight

        if not label_scores:
            return TranslationPayload(text="UNCLEAR", confidence=0.2)

        best_label, best_score = max(label_scores.items(), key=lambda item: item[1])
        best_votes = label_votes.get(best_label, 0)
        if best_votes < max(1, self._settings.image_classifier_min_votes):
            return TranslationPayload(text="UNCLEAR", confidence=0.3)

        confidence = best_score / max(total_weight, 1e-6)
        if confidence < self._settings.image_classifier_min_confidence:
            return TranslationPayload(text="UNCLEAR", confidence=confidence)

        return TranslationPayload(text=best_label, confidence=confidence)

    def _crop_hand_region(
        self,
        jpeg_payload: bytes,
        landmarks: list[LandmarkPoint],
    ) -> np.ndarray | None:
        try:
            image = Image.open(io.BytesIO(jpeg_payload)).convert("RGB")
            rgb = np.asarray(image, dtype=np.uint8)
        except Exception:
            return None

        if rgb.ndim != 3 or rgb.shape[2] < 3:
            return None

        height, width = rgb.shape[0], rgb.shape[1]
        if height <= 0 or width <= 0:
            return None

        xs: list[float] = []
        ys: list[float] = []
        for point in landmarks:
            x = float(getattr(point, "x", 0.5))
            y = float(getattr(point, "y", 0.5))
            xs.append(x)
            ys.append(y)

        if not xs or not ys:
            return rgb

        min_x = max(0.0, min(xs))
        max_x = min(1.0, max(xs))
        min_y = max(0.0, min(ys))
        max_y = min(1.0, max(ys))
        span_x = max(1e-3, max_x - min_x)
        span_y = max(1e-3, max_y - min_y)

        padding = 0.35
        x0 = int(max(0, (min_x - (span_x * padding)) * width))
        x1 = int(min(width, (max_x + (span_x * padding)) * width))
        y0 = int(max(0, (min_y - (span_y * padding)) * height))
        y1 = int(min(height, (max_y + (span_y * padding)) * height))

        if x1 - x0 < 16 or y1 - y0 < 16:
            return rgb

        return rgb[y0:y1, x0:x1, :]
