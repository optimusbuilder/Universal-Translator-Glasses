from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from backend.app.landmarks.types import HandLandmarks, LandmarkPoint
from backend.app.settings import build_settings
from backend.app.translation.local_classifier import (
    hand_to_feature,
    save_local_classifier,
    train_local_classifier,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_label(raw: str) -> str:
    return raw.strip().upper().replace(" ", "_")


def _sample_paths(paths: list[Path], max_count: int) -> list[Path]:
    if max_count <= 0 or len(paths) <= max_count:
        return paths
    step = (len(paths) - 1) / float(max_count - 1)
    selected: list[Path] = []
    used: set[int] = set()
    for slot in range(max_count):
        index = int(round(slot * step))
        index = max(0, min(index, len(paths) - 1))
        if index in used:
            continue
        used.add(index)
        selected.append(paths[index])
    return selected


class _StaticImageHandDetector:
    def __init__(self, model_path: str | None) -> None:
        import mediapipe as mp

        self._mp = mp
        self._mode = "solutions"
        self._landmarker: Any = None
        self._hands: Any = None

        tasks = getattr(mp, "tasks", None)
        vision = getattr(tasks, "vision", None) if tasks is not None else None
        base_options = getattr(tasks, "BaseOptions", None) if tasks is not None else None
        if vision is not None and base_options is not None and model_path:
            model_file = Path(model_path).expanduser()
            if model_file.exists():
                try:
                    options = vision.HandLandmarkerOptions(
                        base_options=base_options(
                            model_asset_path=str(model_file),
                            delegate=base_options.Delegate.CPU,
                        ),
                        running_mode=vision.RunningMode.IMAGE,
                        num_hands=2,
                        min_hand_detection_confidence=0.4,
                        min_hand_presence_confidence=0.4,
                        min_tracking_confidence=0.4,
                    )
                    self._landmarker = vision.HandLandmarker.create_from_options(options)
                    self._mode = "tasks"
                    return
                except Exception:
                    # Fall back to solutions API when tasks initialization is not supported.
                    self._landmarker = None

        self._hands = mp.solutions.hands.Hands(
            static_image_mode=True,
            max_num_hands=2,
            min_detection_confidence=0.35,
            min_tracking_confidence=0.35,
        )

    def detect(self, image_path: Path) -> list[HandLandmarks]:
        image = Image.open(image_path).convert("RGB")
        image_np = np.asarray(image)

        if self._mode == "tasks":
            mp_image = self._mp.Image(
                image_format=self._mp.ImageFormat.SRGB,
                data=image_np,
            )
            results = self._landmarker.detect(mp_image)
            return self._from_tasks(results)

        results = self._hands.process(image_np)
        return self._from_solutions(results)

    def _from_solutions(self, results: Any) -> list[HandLandmarks]:
        if not results or not results.multi_hand_landmarks:
            return []
        handedness_list: list[Any] = list(results.multi_handedness or [])
        output: list[HandLandmarks] = []
        for hand_index, hand_landmarks in enumerate(results.multi_hand_landmarks):
            handedness = "unknown"
            confidence = 0.0
            if hand_index < len(handedness_list):
                classified = handedness_list[hand_index].classification
                if classified:
                    handedness = str(classified[0].label).lower()
                    confidence = max(0.0, min(1.0, float(classified[0].score)))
            points = [
                LandmarkPoint(x=float(p.x), y=float(p.y), z=float(p.z))
                for p in hand_landmarks.landmark
            ]
            output.append(
                HandLandmarks(
                    hand_index=hand_index,
                    handedness=handedness,
                    confidence=confidence,
                    landmarks=points,
                )
            )
        return output

    def _from_tasks(self, results: Any) -> list[HandLandmarks]:
        hand_landmarks_list: list[Any] = list(getattr(results, "hand_landmarks", []) or [])
        handedness_list: list[Any] = list(getattr(results, "handedness", []) or [])
        if not hand_landmarks_list:
            return []

        output: list[HandLandmarks] = []
        for hand_index, hand_landmarks in enumerate(hand_landmarks_list):
            handedness = "unknown"
            confidence = 0.0
            if hand_index < len(handedness_list):
                categories = handedness_list[hand_index]
                first = categories[0] if categories else None
                if first is not None:
                    handedness = str(
                        getattr(first, "category_name", None)
                        or getattr(first, "display_name", None)
                        or "unknown"
                    ).lower()
                    confidence = max(
                        0.0,
                        min(1.0, float(getattr(first, "score", 0.0))),
                    )
            points = [
                LandmarkPoint(x=float(p.x), y=float(p.y), z=float(p.z))
                for p in hand_landmarks
            ]
            output.append(
                HandLandmarks(
                    hand_index=hand_index,
                    handedness=handedness,
                    confidence=confidence,
                    landmarks=points,
                )
            )
        return output


def _extract_features(
    dataset_dir: Path,
    detector: _StaticImageHandDetector,
    max_samples_per_class: int,
    min_hand_confidence: float,
    allowed_labels: set[str],
    skipped_labels: set[str],
) -> tuple[list[tuple[str, np.ndarray]], dict[str, int], dict[str, int], int]:
    samples: list[tuple[str, np.ndarray]] = []
    detected_per_label: dict[str, int] = defaultdict(int)
    attempted_per_label: dict[str, int] = defaultdict(int)
    failed_images = 0

    class_dirs = [path for path in sorted(dataset_dir.iterdir()) if path.is_dir()]
    for class_dir in class_dirs:
        label = _normalize_label(class_dir.name)
        if allowed_labels and label not in allowed_labels:
            continue
        if label in skipped_labels:
            continue

        all_images = [
            path
            for path in sorted(class_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ]
        sampled_images = _sample_paths(all_images, max_samples_per_class)
        if not sampled_images:
            continue

        print(f"[label={label}] scanning {len(sampled_images)} images")

        for image_path in sampled_images:
            attempted_per_label[label] += 1
            try:
                hands = detector.detect(image_path)
            except Exception:
                failed_images += 1
                continue

            if not hands:
                continue

            best_hand = max(hands, key=lambda item: item.confidence)
            if best_hand.confidence < min_hand_confidence:
                continue

            feature = hand_to_feature(best_hand)
            if feature is None:
                continue

            samples.append((label, feature))
            detected_per_label[label] += 1

        print(
            f"[label={label}] detected={detected_per_label[label]} / attempted={attempted_per_label[label]}"
        )

    return samples, dict(detected_per_label), dict(attempted_per_label), failed_images


def _run(args: argparse.Namespace) -> int:
    dataset_dir = Path(args.dataset).expanduser()
    if not dataset_dir.exists() or not dataset_dir.is_dir():
        print(f"dataset not found or not a directory: {dataset_dir}")
        return 1

    output_path = Path(args.output).expanduser()
    if not output_path.is_absolute():
        output_path = (_project_root() / output_path).resolve()

    allowed_labels = (
        {_normalize_label(item) for item in args.classes.split(",") if item.strip()}
        if args.classes
        else set()
    )
    skipped_labels = (
        {_normalize_label(item) for item in args.skip_labels.split(",") if item.strip()}
        if args.skip_labels
        else set()
    )

    settings = build_settings(_project_root())
    detector = _StaticImageHandDetector(settings.mediapipe_hand_model_path)

    print(f"training dataset: {dataset_dir}")
    print(f"output model: {output_path}")
    samples, detected, attempted, failed_images = _extract_features(
        dataset_dir=dataset_dir,
        detector=detector,
        max_samples_per_class=max(1, args.max_samples_per_class),
        min_hand_confidence=max(0.0, min(1.0, args.min_hand_confidence)),
        allowed_labels=allowed_labels,
        skipped_labels=skipped_labels,
    )

    if not samples:
        print("no usable samples were extracted")
        return 2

    model = train_local_classifier(
        samples=samples,
        min_samples_per_label=max(1, args.min_samples_per_class),
    )
    save_local_classifier(model=model, output_path=str(output_path))

    total_detected = sum(detected.values())
    total_attempted = sum(attempted.values())
    print("")
    print("training complete")
    print(f"labels_trained={len(model.labels)}")
    print(f"samples_used={int(model.sample_counts.sum())}")
    print(f"samples_detected={total_detected} / samples_attempted={total_attempted}")
    print(f"decode_or_extract_failures={failed_images}")
    print(f"model_path={output_path}")
    print("label sample counts:")
    for label, count in zip(model.labels, model.sample_counts.tolist()):
        print(f"  {label}: {count}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train a local ASL landmark classifier from image folders.",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to dataset root containing per-label folders.",
    )
    parser.add_argument(
        "--output",
        default="backend/models/asl_landmark_classifier_v1.npz",
        help="Path to output model .npz file.",
    )
    parser.add_argument(
        "--max-samples-per-class",
        type=int,
        default=700,
        help="Upper bound on sampled images per label folder.",
    )
    parser.add_argument(
        "--min-samples-per-class",
        type=int,
        default=40,
        help="Minimum extracted samples required to keep a label.",
    )
    parser.add_argument(
        "--min-hand-confidence",
        type=float,
        default=0.45,
        help="Minimum landmark confidence for using an image sample.",
    )
    parser.add_argument(
        "--classes",
        default="",
        help="Optional comma-separated label allowlist.",
    )
    parser.add_argument(
        "--skip-labels",
        default="",
        help="Optional comma-separated labels to skip.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
