from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class ImageClassifierPrediction:
    label: str
    confidence: float
    margin: float


@dataclass(frozen=True)
class ImageClassifierModel:
    labels: list[str]
    centroids: np.ndarray
    feature_mean: np.ndarray
    feature_std: np.ndarray
    sample_counts: np.ndarray
    input_size: int

    def predict_feature(self, feature: np.ndarray) -> ImageClassifierPrediction:
        standardized = (feature - self.feature_mean) / self.feature_std
        feature_norm = float(np.linalg.norm(standardized))
        if feature_norm <= 1e-9:
            return ImageClassifierPrediction(label="", confidence=0.0, margin=0.0)

        unit_feature = standardized / feature_norm
        similarities = self.centroids @ unit_feature
        if similarities.size == 0:
            return ImageClassifierPrediction(label="", confidence=0.0, margin=0.0)

        best_index = int(np.argmax(similarities))
        best_similarity = float(similarities[best_index])
        second_similarity = float(
            np.partition(similarities, -2)[-2] if similarities.size > 1 else -1.0
        )
        margin = max(0.0, best_similarity - second_similarity)
        score = (best_similarity + 1.0) * 0.5
        confidence = max(0.0, min(1.0, (0.7 * score) + (0.3 * min(1.0, margin * 5.0))))
        return ImageClassifierPrediction(
            label=self.labels[best_index],
            confidence=confidence,
            margin=margin,
        )


def preprocess_image_array(image_rgb: np.ndarray, input_size: int) -> np.ndarray:
    if image_rgb.ndim != 3 or image_rgb.shape[2] < 3:
        raise ValueError("Expected image with shape (H, W, 3).")

    safe_size = max(16, int(input_size))
    image = Image.fromarray(image_rgb[:, :, :3].astype(np.uint8), mode="RGB")
    image = image.resize((safe_size, safe_size), Image.Resampling.BILINEAR)

    gray = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
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

    centroids: list[np.ndarray] = []
    counts: list[int] = []
    for label in labels:
        features = np.vstack(grouped[label]).astype(np.float32)
        standardized = (features - feature_mean) / feature_std
        centroid = standardized.mean(axis=0)
        norm = float(np.linalg.norm(centroid))
        if norm > 1e-9:
            centroid = centroid / norm
        centroids.append(centroid.astype(np.float32))
        counts.append(features.shape[0])

    return ImageClassifierModel(
        labels=labels,
        centroids=np.vstack(centroids).astype(np.float32),
        feature_mean=feature_mean.astype(np.float32),
        feature_std=feature_std.astype(np.float32),
        sample_counts=np.asarray(counts, dtype=np.int32),
        input_size=max(16, int(input_size)),
    )


def save_image_classifier(model: ImageClassifierModel, output_path: str) -> None:
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        labels=np.asarray(model.labels, dtype="U64"),
        centroids=model.centroids.astype(np.float32),
        feature_mean=model.feature_mean.astype(np.float32),
        feature_std=model.feature_std.astype(np.float32),
        sample_counts=model.sample_counts.astype(np.int32),
        input_size=np.asarray([model.input_size], dtype=np.int32),
    )


def load_image_classifier(model_path: str) -> ImageClassifierModel:
    path = Path(model_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image classifier model file not found: {path}")

    payload = np.load(path, allow_pickle=False)
    labels = [str(item) for item in payload["labels"].tolist()]
    centroids = np.asarray(payload["centroids"], dtype=np.float32)
    feature_mean = np.asarray(payload["feature_mean"], dtype=np.float32)
    feature_std = np.asarray(payload["feature_std"], dtype=np.float32)
    sample_counts = np.asarray(payload["sample_counts"], dtype=np.int32)
    input_size_values = np.asarray(payload["input_size"], dtype=np.int32)

    if input_size_values.size == 0:
        raise ValueError("Invalid image classifier model: missing input_size")

    if centroids.ndim != 2:
        raise ValueError("Invalid image classifier model: centroids must be 2D")
    if feature_mean.ndim != 1 or feature_std.ndim != 1:
        raise ValueError("Invalid image classifier model: feature stats must be 1D")
    if centroids.shape[1] != feature_mean.shape[0]:
        raise ValueError("Invalid image classifier model: feature dimensions do not align")
    if len(labels) != centroids.shape[0]:
        raise ValueError("Invalid image classifier model: label and centroid counts mismatch")

    feature_std = np.where(feature_std < 1e-6, 1.0, feature_std).astype(np.float32)

    return ImageClassifierModel(
        labels=labels,
        centroids=centroids,
        feature_mean=feature_mean,
        feature_std=feature_std,
        sample_counts=sample_counts,
        input_size=max(16, int(input_size_values[0])),
    )
