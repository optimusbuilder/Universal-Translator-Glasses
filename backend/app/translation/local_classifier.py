from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from backend.app.landmarks.types import HandLandmarks


@dataclass(frozen=True)
class LocalClassifierPrediction:
    label: str
    confidence: float
    margin: float


@dataclass(frozen=True)
class LocalLandmarkClassifierModel:
    labels: list[str]
    centroids: np.ndarray
    feature_mean: np.ndarray
    feature_std: np.ndarray
    sample_counts: np.ndarray

    def predict_feature(self, feature: np.ndarray) -> LocalClassifierPrediction:
        standardized = (feature - self.feature_mean) / self.feature_std
        feature_norm = float(np.linalg.norm(standardized))
        if feature_norm <= 1e-9:
            return LocalClassifierPrediction(label="", confidence=0.0, margin=0.0)

        unit_feature = standardized / feature_norm
        similarities = self.centroids @ unit_feature
        if similarities.size == 0:
            return LocalClassifierPrediction(label="", confidence=0.0, margin=0.0)

        best_index = int(np.argmax(similarities))
        best_similarity = float(similarities[best_index])
        second_similarity = float(
            np.partition(similarities, -2)[-2] if similarities.size > 1 else -1.0
        )
        margin = max(0.0, best_similarity - second_similarity)

        # Convert cosine similarity into a stable confidence score.
        score = (best_similarity + 1.0) * 0.5
        confidence = max(0.0, min(1.0, (0.75 * score) + (0.25 * min(1.0, margin * 4.0))))
        return LocalClassifierPrediction(
            label=self.labels[best_index],
            confidence=confidence,
            margin=margin,
        )


def hand_to_feature(hand: HandLandmarks) -> np.ndarray | None:
    if len(hand.landmarks) < 21:
        return None

    wrist = hand.landmarks[0]
    index_mcp = hand.landmarks[5]
    pinky_mcp = hand.landmarks[17]
    scale = float(
        np.linalg.norm(
            np.array(
                [
                    index_mcp.x - pinky_mcp.x,
                    index_mcp.y - pinky_mcp.y,
                    index_mcp.z - pinky_mcp.z,
                ],
                dtype=np.float32,
            )
        )
    )
    if scale <= 1e-6:
        return None

    mirrored = hand.handedness.lower() == "left"
    feature: list[float] = []
    for point in hand.landmarks:
        x = (point.x - wrist.x) / scale
        y = (point.y - wrist.y) / scale
        z = (point.z - wrist.z) / scale
        if mirrored:
            x = -x
        feature.extend((x, y, z))
    return np.asarray(feature, dtype=np.float32)


def train_local_classifier(
    samples: Iterable[tuple[str, np.ndarray]],
    min_samples_per_label: int = 20,
) -> LocalLandmarkClassifierModel:
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

    return LocalLandmarkClassifierModel(
        labels=labels,
        centroids=np.vstack(centroids).astype(np.float32),
        feature_mean=feature_mean.astype(np.float32),
        feature_std=feature_std.astype(np.float32),
        sample_counts=np.asarray(counts, dtype=np.int32),
    )


def save_local_classifier(model: LocalLandmarkClassifierModel, output_path: str) -> None:
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        destination,
        labels=np.asarray(model.labels, dtype="U32"),
        centroids=model.centroids.astype(np.float32),
        feature_mean=model.feature_mean.astype(np.float32),
        feature_std=model.feature_std.astype(np.float32),
        sample_counts=model.sample_counts.astype(np.int32),
    )


def load_local_classifier(model_path: str) -> LocalLandmarkClassifierModel:
    path = Path(model_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Local classifier model file not found: {path}")

    payload = np.load(path, allow_pickle=False)
    labels = [str(item) for item in payload["labels"].tolist()]
    centroids = np.asarray(payload["centroids"], dtype=np.float32)
    feature_mean = np.asarray(payload["feature_mean"], dtype=np.float32)
    feature_std = np.asarray(payload["feature_std"], dtype=np.float32)
    sample_counts = np.asarray(payload["sample_counts"], dtype=np.int32)

    if centroids.ndim != 2:
        raise ValueError("Invalid local classifier model: centroids must be 2D")
    if feature_mean.ndim != 1 or feature_std.ndim != 1:
        raise ValueError("Invalid local classifier model: feature stats must be 1D")
    if centroids.shape[1] != feature_mean.shape[0]:
        raise ValueError("Invalid local classifier model: feature dimensions do not align")
    if len(labels) != centroids.shape[0]:
        raise ValueError("Invalid local classifier model: label and centroid counts mismatch")

    feature_std = np.where(feature_std < 1e-6, 1.0, feature_std).astype(np.float32)

    return LocalLandmarkClassifierModel(
        labels=labels,
        centroids=centroids,
        feature_mean=feature_mean,
        feature_std=feature_std,
        sample_counts=sample_counts,
    )
