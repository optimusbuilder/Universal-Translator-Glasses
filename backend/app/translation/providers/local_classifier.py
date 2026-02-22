from __future__ import annotations

from collections import defaultdict

from backend.app.settings import Settings
from backend.app.translation.local_classifier import (
    hand_to_feature,
    load_local_classifier,
)
from backend.app.translation.providers.base import (
    TranslationProvider,
    TranslationProviderError,
)
from backend.app.translation.types import TranslationPayload
from backend.app.windowing.types import LandmarkWindow


class LocalClassifierTranslationProvider(TranslationProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        try:
            self._model = load_local_classifier(settings.local_classifier_model_path)
        except Exception as exc:
            raise TranslationProviderError(
                f"local_classifier_model_load_error:{exc}"
            ) from exc

        allowlist_raw = (settings.local_classifier_label_allowlist or "").strip()
        self._allowlist = {
            token.strip().upper() for token in allowlist_raw.split(",") if token.strip()
        }

    @property
    def name(self) -> str:
        return "local-landmark-classifier-provider"

    async def translate(self, window: LandmarkWindow) -> TranslationPayload:
        label_scores: dict[str, float] = defaultdict(float)
        label_votes: dict[str, int] = defaultdict(int)
        total_weight = 0.0

        for frame in window.frames:
            for hand in frame.hands:
                if hand.confidence < self._settings.translation_hand_confidence_threshold:
                    continue

                feature = hand_to_feature(hand)
                if feature is None:
                    continue

                prediction = self._model.predict_feature(feature)
                label = prediction.label.strip().upper()
                if not label:
                    continue
                if self._allowlist and label not in self._allowlist:
                    continue

                vote_weight = max(0.0, min(1.0, hand.confidence)) * prediction.confidence
                if vote_weight <= 0:
                    continue

                label_scores[label] += vote_weight
                label_votes[label] += 1
                total_weight += vote_weight

        if not label_scores:
            return TranslationPayload(text="UNCLEAR", confidence=0.2)

        best_label, best_score = max(label_scores.items(), key=lambda item: item[1])
        best_votes = label_votes.get(best_label, 0)
        if best_votes < max(1, self._settings.local_classifier_min_votes):
            return TranslationPayload(text="UNCLEAR", confidence=0.3)

        confidence = best_score / max(total_weight, 1e-6)
        if confidence < self._settings.local_classifier_min_confidence:
            return TranslationPayload(text="UNCLEAR", confidence=confidence)

        return TranslationPayload(text=best_label, confidence=confidence)
