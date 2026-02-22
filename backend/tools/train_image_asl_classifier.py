from __future__ import annotations

import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image

from backend.app.translation.image_classifier import (
    ImageClassifierModel,
    preprocess_image_array,
    save_image_classifier,
    train_image_classifier,
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


def _load_feature(image_path: Path, input_size: int) -> np.ndarray | None:
    try:
        image = Image.open(image_path).convert("RGB")
        rgb = np.asarray(image, dtype=np.uint8)
    except Exception:
        return None
    try:
        return preprocess_image_array(rgb, input_size=input_size)
    except Exception:
        return None


def _split_label_samples(
    features: list[np.ndarray],
    val_split: float,
    seed: int,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    if not features:
        return [], []
    if len(features) == 1:
        return features, []

    rng = random.Random(seed)
    indexes = list(range(len(features)))
    rng.shuffle(indexes)
    shuffled = [features[index] for index in indexes]

    val_count = int(round(len(shuffled) * val_split))
    val_count = min(max(1, val_count), len(shuffled) - 1)
    train_count = len(shuffled) - val_count
    return shuffled[:train_count], shuffled[train_count:]


def _evaluate_model(
    model: ImageClassifierModel,
    validation: list[tuple[str, np.ndarray]],
) -> tuple[float, dict[str, tuple[int, int]]]:
    if not validation:
        return 0.0, {}

    correct = 0
    per_label: dict[str, list[int]] = {}
    for expected, feature in validation:
        prediction = model.predict_feature(feature)
        label = prediction.label.strip().upper()
        hit = int(label == expected)
        if hit:
            correct += 1
        per_label.setdefault(expected, [0, 0])
        per_label[expected][0] += hit
        per_label[expected][1] += 1

    accuracy = correct / max(1, len(validation))
    metrics = {label: (values[0], values[1]) for label, values in per_label.items()}
    return accuracy, metrics


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

    input_size = max(16, int(args.input_size))
    max_samples = max(1, int(args.max_samples_per_class))
    min_samples = max(1, int(args.min_samples_per_class))
    val_split = max(0.05, min(0.4, float(args.val_split)))
    seed = int(args.seed)

    grouped_train: dict[str, list[np.ndarray]] = {}
    validation: list[tuple[str, np.ndarray]] = []
    decode_failures = 0

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
        sampled_images = _sample_paths(all_images, max_samples)
        if not sampled_images:
            continue

        features: list[np.ndarray] = []
        for image_path in sampled_images:
            feature = _load_feature(image_path, input_size=input_size)
            if feature is None:
                decode_failures += 1
                continue
            features.append(feature)

        train_features, val_features = _split_label_samples(
            features=features,
            val_split=val_split,
            seed=seed,
        )
        if len(train_features) < min_samples:
            print(
                f"[label={label}] skipped (insufficient usable samples: {len(train_features)})"
            )
            continue

        grouped_train[label] = train_features
        for feature in val_features:
            validation.append((label, feature))

        print(
            f"[label={label}] train={len(train_features)} val={len(val_features)} "
            f"(from {len(sampled_images)} sampled)"
        )

    train_pairs: list[tuple[str, np.ndarray]] = []
    for label, features in grouped_train.items():
        for feature in features:
            train_pairs.append((label, feature))

    if not train_pairs:
        print("no usable training samples found")
        return 2

    model = train_image_classifier(
        samples=train_pairs,
        input_size=input_size,
        min_samples_per_label=min_samples,
        max_prototypes_per_label=max(20, int(args.max_prototypes_per_label)),
        knn_k=max(1, int(args.knn_k)),
    )
    save_image_classifier(model=model, output_path=str(output_path))

    accuracy, per_label_metrics = _evaluate_model(model, validation=validation)

    print("")
    print("training complete")
    print(f"labels_trained={len(model.labels)}")
    print(f"samples_used={int(model.sample_counts.sum())}")
    print(f"validation_samples={len(validation)}")
    print(f"validation_top1_accuracy={round(accuracy * 100.0, 2)}%")
    print(f"decode_failures={decode_failures}")
    print(f"input_size={model.input_size}")
    print(f"prototypes={model.prototype_vectors.shape[0]}")
    print(f"knn_k={model.knn_k}")
    print(f"model_path={output_path}")
    print("label sample counts:")
    for label, count in zip(model.labels, model.sample_counts.tolist()):
        print(f"  {label}: {count}")
    if per_label_metrics:
        print("validation accuracy by label:")
        for label in sorted(per_label_metrics.keys()):
            correct, total = per_label_metrics[label]
            label_acc = (correct / max(1, total)) * 100.0
            print(f"  {label}: {correct}/{total} ({round(label_acc, 2)}%)")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train an image-based ASL classifier from per-label folders.",
    )
    parser.add_argument("--dataset", required=True, help="Path to dataset root.")
    parser.add_argument(
        "--output",
        default="backend/models/asl_image_classifier_v1.npz",
        help="Output model path (.npz).",
    )
    parser.add_argument(
        "--input-size",
        type=int,
        default=32,
        help="Square input size in pixels.",
    )
    parser.add_argument(
        "--max-samples-per-class",
        type=int,
        default=1200,
        help="Upper bound on sampled images per class.",
    )
    parser.add_argument(
        "--min-samples-per-class",
        type=int,
        default=40,
        help="Minimum train samples required per class.",
    )
    parser.add_argument(
        "--val-split",
        type=float,
        default=0.2,
        help="Validation split ratio (0.05 to 0.4).",
    )
    parser.add_argument(
        "--max-prototypes-per-label",
        type=int,
        default=250,
        help="Maximum stored prototype vectors per label.",
    )
    parser.add_argument(
        "--knn-k",
        type=int,
        default=5,
        help="k value for nearest-neighbor voting.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Random seed for train/validation split.",
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
