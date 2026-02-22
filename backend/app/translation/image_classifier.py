from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image

try:
    import cv2  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional fallback
    cv2 = None


@dataclass(frozen=True)
class ImageClassifierPrediction:
    label: str
    confidence: float
    margin: float


@dataclass(frozen=True)
class ImageClassifierModel:
    labels: list[str]
    prototype_vectors: np.ndarray
    prototype_label_indices: np.ndarray
    feature_mean: np.ndarray
    feature_std: np.ndarray
    sample_counts: np.ndarray
    input_size: int
    knn_k: int

    def predict_feature(self, feature: np.ndarray) -> ImageClassifierPrediction:
        standardized = (feature - self.feature_mean) / self.feature_std
        feature_norm = float(np.linalg.norm(standardized))
        if feature_norm <= 1e-9:
            return ImageClassifierPrediction(label="", confidence=0.0, margin=0.0)
        query = standardized / feature_norm

        similarities = self.prototype_vectors @ query
        if similarities.size == 0:
            return ImageClassifierPrediction(label="", confidence=0.0, margin=0.0)

        k = min(max(1, self.knn_k), similarities.size)
        top_indexes = np.argpartition(similarities, -k)[-k:]
        top_scores = similarities[top_indexes]
        top_label_indexes = self.prototype_label_indices[top_indexes]

        vote_scores = np.zeros((len(self.labels),), dtype=np.float32)
        for score, label_index in zip(top_scores, top_label_indexes):
            vote_scores[int(label_index)] += max(0.0, float(score))

        best_label_index = int(np.argmax(vote_scores))
        best_vote = float(vote_scores[best_label_index])
        second_vote = float(np.partition(vote_scores, -2)[-2]) if vote_scores.size > 1 else 0.0
        total_vote = float(vote_scores.sum())
        margin = max(0.0, best_vote - second_vote)

        confidence = best_vote / max(1e-6, total_vote)
        confidence = max(0.0, min(1.0, (0.75 * confidence) + (0.25 * min(1.0, margin * 2.5))))
        return ImageClassifierPrediction(
            label=self.labels[best_label_index],
            confidence=confidence,
            margin=margin,
        )


def preprocess_image_array(image_rgb: np.ndarray, input_size: int) -> np.ndarray:
    if image_rgb.ndim != 3 or image_rgb.shape[2] < 3:
        raise ValueError("Expected image with shape (H, W, 3).")

    safe_size = max(16, int(input_size))
    hog_size = max(16, (safe_size // 8) * 8)
    if hog_size != safe_size:
        safe_size = hog_size

    image = Image.fromarray(image_rgb[:, :, :3].astype(np.uint8), mode="RGB")
    image = image.resize((safe_size, safe_size), Image.Resampling.BILINEAR)
    gray_u8 = np.asarray(image.convert("L"), dtype=np.uint8)

    if cv2 is not None:
        hog = cv2.HOGDescriptor(
            (safe_size, safe_size),
            (16, 16),
            (8, 8),
            (8, 8),
            9,
        )
        hog_feature = hog.compute(gray_u8)
        if hog_feature is not None:
            return hog_feature.reshape(-1).astype(np.float32)

    # Fallback if OpenCV HOG is unavailable.
    gray = gray_u8.astype(np.float32) / 255.0
    gx = np.gradient(gray, axis=1)
    gy = np.gradient(gray, axis=0)
    grad_mag = np.sqrt((gx * gx) + (gy * gy))
    gray_flat = gray.reshape(-1)
    grad_flat = grad_mag.reshape(-1)
    return np.concatenate([gray_flat, grad_flat], axis=0).astype(np.float32)


def train_image_classifier(
    samples: Iterable[tuple[str, np.ndarray]],
    input_size: int,
    min_samples_per_label: int = 20,
    max_prototypes_per_label: int = 300,
    knn_k: int = 5,
) -> ImageClassifierModel:
    grouped: dict[str, list[np.ndarray]] = {}
    for label, feature in samples:
        grouped.setdefault(label, []).append(feature.astype(np.float32))

    labels = sorted(
        label for label, values in grouped.items() if len(values) >= min_samples_per_label
    )
    if not labels:
        raise ValueError("No labels met the minimum sample threshold for training.")

    all_features = np.vstack([np.vstack(grouped[label]) for label in labels]).astype(np.float32)
    feature_mean = all_features.mean(axis=0)
    feature_std = all_features.std(axis=0)
    feature_std = np.where(feature_std < 1e-6, 1.0, feature_std).astype(np.float32)

    prototype_vectors: list[np.ndarray] = []
    prototype_label_indices: list[int] = []
    counts: list[int] = []

    for label_index, label in enumerate(labels):
        features = np.vstack(grouped[label]).astype(np.float32)
        counts.append(int(features.shape[0]))

        if features.shape[0] > max_prototypes_per_label:
            step = (features.shape[0] - 1) / float(max_prototypes_per_label - 1)
            selected_indexes: list[int] = []
            used_indexes: set[int] = set()
            for slot in range(max_prototypes_per_label):
                sample_index = int(round(slot * step))
                sample_index = max(0, min(sample_index, features.shape[0] - 1))
                if sample_index in used_indexes:
                    continue
                used_indexes.add(sample_index)
                selected_indexes.append(sample_index)
            features = features[selected_indexes]

        standardized = (features - feature_mean) / feature_std
        norms = np.linalg.norm(standardized, axis=1, keepdims=True)
        norms = np.clip(norms, 1e-8, None)
        normalized = standardized / norms

        prototype_vectors.append(normalized.astype(np.float32))
        prototype_label_indices.extend([label_index] * normalized.shape[0])

    vectors = np.vstack(prototype_vectors).astype(np.float32)
    label_indexes = np.asarray(prototype_label_indices, dtype=np.int32)

    return ImageClassifierModel(
        labels=labels,
        prototype_vectors=vectors,
        prototype_label_indices=label_indexes,
        feature_mean=feature_mean.astype(np.float32),
        feature_std=feature_std.astype(np.float32),
        sample_counts=np.asarray(counts, dtype=np.int32),
        input_size=max(16, int(input_size)),
        knn_k=max(1, int(knn_k)),
    )


def save_image_classifier(model: ImageClassifierModel, output_path: str) -> None:
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        labels=np.asarray(model.labels, dtype="U64"),
        prototype_vectors=model.prototype_vectors.astype(np.float32),
        prototype_label_indices=model.prototype_label_indices.astype(np.int32),
        feature_mean=model.feature_mean.astype(np.float32),
        feature_std=model.feature_std.astype(np.float32),
        sample_counts=model.sample_counts.astype(np.int32),
        input_size=np.asarray([model.input_size], dtype=np.int32),
        knn_k=np.asarray([model.knn_k], dtype=np.int32),
    )


def load_image_classifier(model_path: str) -> ImageClassifierModel:
    path = Path(model_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image classifier model file not found: {path}")

    payload = np.load(path, allow_pickle=False)
    labels = [str(item) for item in payload["labels"].tolist()]
    vectors = np.asarray(payload["prototype_vectors"], dtype=np.float32)
    label_indexes = np.asarray(payload["prototype_label_indices"], dtype=np.int32)
    feature_mean = np.asarray(payload["feature_mean"], dtype=np.float32)
    feature_std = np.asarray(payload["feature_std"], dtype=np.float32)
    sample_counts = np.asarray(payload["sample_counts"], dtype=np.int32)
    input_size_values = np.asarray(payload["input_size"], dtype=np.int32)
    knn_k_values = np.asarray(payload["knn_k"], dtype=np.int32)

    if vectors.ndim != 2:
        raise ValueError("Invalid image classifier model: prototype_vectors must be 2D")
    if feature_mean.ndim != 1 or feature_std.ndim != 1:
        raise ValueError("Invalid image classifier model: feature stats must be 1D")
    if vectors.shape[1] != feature_mean.shape[0]:
        raise ValueError("Invalid image classifier model: feature dimensions do not align")
    if label_indexes.ndim != 1 or label_indexes.shape[0] != vectors.shape[0]:
        raise ValueError(
            "Invalid image classifier model: prototype labels shape mismatch"
        )
    if len(labels) == 0:
        raise ValueError("Invalid image classifier model: no labels")
    if np.max(label_indexes) >= len(labels) or np.min(label_indexes) < 0:
        raise ValueError("Invalid image classifier model: prototype label index out of range")
    if input_size_values.size == 0 or knn_k_values.size == 0:
        raise ValueError("Invalid image classifier model: missing metadata values")

    feature_std = np.where(feature_std < 1e-6, 1.0, feature_std).astype(np.float32)

    return ImageClassifierModel(
        labels=labels,
        prototype_vectors=vectors,
        prototype_label_indices=label_indexes,
        feature_mean=feature_mean,
        feature_std=feature_std,
        sample_counts=sample_counts,
        input_size=max(16, int(input_size_values[0])),
        knn_k=max(1, int(knn_k_values[0])),
    )
