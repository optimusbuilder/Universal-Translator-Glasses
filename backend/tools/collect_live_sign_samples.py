from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2  # type: ignore[import-not-found]
from PIL import Image

from backend.app.ingest.sources.base import FramePacket
from backend.app.landmarks.extractors.mediapipe import MediaPipeHandLandmarkExtractor


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_label(raw: str) -> str:
    return raw.strip().upper().replace(" ", "_")


def _parse_phrase_tokens(raw: str) -> list[str]:
    return [token.strip() for token in raw.split(",") if token.strip()]


def _load_phrases_file(path: str) -> list[str]:
    phrases: list[str] = []
    file_path = Path(path).expanduser()
    if not file_path.exists():
        return phrases
    for line in file_path.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        phrases.append(cleaned)
    return phrases


def _resolve_labels(args: argparse.Namespace) -> list[str]:
    raw_labels: list[str] = []
    if args.phrases:
        raw_labels.extend(_parse_phrase_tokens(args.phrases))
    if args.phrases_file:
        raw_labels.extend(_load_phrases_file(args.phrases_file))

    labels: list[str] = []
    seen: set[str] = set()
    for item in raw_labels:
        normalized = _normalize_label(item)
        if normalized in seen:
            continue
        labels.append(normalized)
        seen.add(normalized)
    return labels


def _crop_hand_region(
    rgb_image,
    landmarks,
    padding: float = 0.5,
):
    height, width = rgb_image.shape[0], rgb_image.shape[1]
    xs = [float(point.x) for point in landmarks]
    ys = [float(point.y) for point in landmarks]
    if not xs or not ys:
        return rgb_image

    min_x = max(0.0, min(xs))
    max_x = min(1.0, max(xs))
    min_y = max(0.0, min(ys))
    max_y = min(1.0, max(ys))
    span_x = max(1e-3, max_x - min_x)
    span_y = max(1e-3, max_y - min_y)

    x0 = int(max(0, (min_x - (span_x * padding)) * width))
    x1 = int(min(width, (max_x + (span_x * padding)) * width))
    y0 = int(max(0, (min_y - (span_y * padding)) * height))
    y1 = int(min(height, (max_y + (span_y * padding)) * height))

    if x1 - x0 < 16 or y1 - y0 < 16:
        return rgb_image
    return rgb_image[y0:y1, x0:x1, :]


def _open_capture(source_raw: str, *, width: int, height: int):
    source = int(source_raw) if source_raw.isdigit() else source_raw
    capture = cv2.VideoCapture(source)
    if isinstance(source, int) and not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"failed to open source: {source_raw}")

    if width > 0:
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
    if height > 0:
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    return capture, source


def _build_extractor() -> MediaPipeHandLandmarkExtractor:
    return MediaPipeHandLandmarkExtractor(
        model_path=str(_project_root() / "backend/models/hand_landmarker.task")
    )


def _next_image_index(output_dir: Path, label: str) -> int:
    max_seen = -1
    for path in output_dir.glob(f"{label}_*.jpg"):
        stem = path.stem
        tail = stem.removeprefix(f"{label}_")
        if tail.isdigit():
            max_seen = max(max_seen, int(tail))
    return max_seen + 1


def _wait_for_enter(prompt: str, *, enabled: bool) -> None:
    if not enabled:
        return
    try:
        input(prompt)
    except EOFError:
        return


async def _countdown(seconds: float) -> None:
    wait_seconds = max(0.0, float(seconds))
    if wait_seconds <= 0.0:
        return

    whole_seconds = int(wait_seconds)
    fractional = wait_seconds - whole_seconds
    for remaining in range(whole_seconds, 0, -1):
        print(f"  capture starts in {remaining}...")
        await asyncio.sleep(1.0)
    if fractional > 0:
        await asyncio.sleep(fractional)


async def _capture_best_hand_crop(
    *,
    capture,
    extractor: MediaPipeHandLandmarkExtractor,
    frame_id: int,
    frame_stride: int,
    min_conf: float,
    capture_seconds: float,
) -> tuple[int, Any | None, float, int]:
    deadline = time.monotonic() + max(0.1, capture_seconds)
    attempted = 0
    best_conf = 0.0
    best_crop = None

    while time.monotonic() < deadline:
        ok, frame_bgr = capture.read()
        if not ok or frame_bgr is None:
            await asyncio.sleep(0.01)
            continue

        frame_id += 1
        if frame_id % frame_stride != 0:
            continue
        attempted += 1

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        ok_jpg, encoded = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok_jpg:
            continue
        payload = bytes(encoded.tobytes())

        packet = FramePacket(
            frame_id=frame_id,
            captured_at=datetime.now(timezone.utc),
            payload=payload,
            source_name="live-capture",
        )
        hands = await extractor.extract(packet)
        if not hands:
            continue

        best_hand = max(hands, key=lambda item: item.confidence)
        if best_hand.confidence < min_conf:
            continue

        crop = _crop_hand_region(frame_rgb, best_hand.landmarks)
        if best_hand.handedness.lower() == "left":
            crop = crop[:, ::-1, :]

        if best_hand.confidence >= best_conf:
            best_conf = best_hand.confidence
            best_crop = crop.copy()

    return frame_id, best_crop, best_conf, attempted


async def _run_repetition_mode(args: argparse.Namespace) -> int:
    labels = _resolve_labels(args)
    if not labels:
        print("repetition mode requested, but no labels were resolved from --phrases/--phrases-file")
        return 2

    frame_stride = max(1, int(args.frame_stride))
    min_conf = max(0.0, min(1.0, float(args.min_confidence)))
    repetitions = max(1, int(args.repetitions))
    capture_seconds = max(0.2, float(args.capture_seconds))
    max_attempts = max(1, int(args.max_attempts_per_repetition))
    countdown_seconds = max(0.0, float(args.countdown_seconds))
    prompt_enabled = not bool(args.no_prompt)
    base_output = Path(args.output_dir).expanduser()
    base_output.mkdir(parents=True, exist_ok=True)

    try:
        capture, source = _open_capture(
            args.source.strip(),
            width=int(args.width),
            height=int(args.height),
        )
    except RuntimeError as exc:
        print(str(exc))
        return 1

    extractor = _build_extractor()
    frame_id = 0
    attempted = 0
    total_saved = 0
    per_label_saved: dict[str, int] = {}
    incomplete_labels: list[str] = []

    print("")
    print("phrase collection session")
    print(f"source={args.source.strip()} ({source})")
    print(f"labels={', '.join(labels)}")
    print(
        f"repetitions_per_label={repetitions} capture_seconds={capture_seconds} "
        f"min_confidence={min_conf} frame_stride={frame_stride}"
    )
    print("")

    try:
        for label_index, label in enumerate(labels):
            output_dir = base_output / label
            output_dir.mkdir(parents=True, exist_ok=True)
            next_index = _next_image_index(output_dir, label)
            before_count = len(list(output_dir.glob("*.jpg")))
            saved_for_label = 0

            print(f"=== phrase {label_index + 1}/{len(labels)}: {label} ===")
            print(f"target_repetitions={repetitions} existing_samples={before_count}")

            for rep in range(1, repetitions + 1):
                print(f"[{label}] repetition {rep}/{repetitions}")
                saved_this_rep = False

                for attempt_no in range(1, max_attempts + 1):
                    _wait_for_enter(
                        "  press Enter and hold the sign steady...",
                        enabled=prompt_enabled,
                    )
                    await _countdown(countdown_seconds)
                    frame_id, crop, conf, rep_attempted = await _capture_best_hand_crop(
                        capture=capture,
                        extractor=extractor,
                        frame_id=frame_id,
                        frame_stride=frame_stride,
                        min_conf=min_conf,
                        capture_seconds=capture_seconds,
                    )
                    attempted += rep_attempted

                    if crop is None:
                        print(
                            f"  no valid hand captured (attempt {attempt_no}/{max_attempts})"
                        )
                        continue

                    image = Image.fromarray(crop.astype("uint8"), mode="RGB")
                    filename = output_dir / f"{label}_{next_index:05d}.jpg"
                    image.save(filename, format="JPEG", quality=92)
                    next_index += 1
                    saved_for_label += 1
                    total_saved += 1
                    saved_this_rep = True
                    print(
                        f"  saved repetition {rep}/{repetitions} -> {filename.name} "
                        f"(confidence={round(conf, 3)})"
                    )
                    break

                if not saved_this_rep:
                    print(
                        f"  failed to capture repetition {rep}/{repetitions} for {label} "
                        f"after {max_attempts} attempts"
                    )

            after_count = len(list(output_dir.glob("*.jpg")))
            added = max(0, after_count - before_count)
            per_label_saved[label] = saved_for_label
            print(
                f"phrase complete: {label} saved_now={saved_for_label}/{repetitions} "
                f"files_added={added} total_files={after_count}"
            )
            if saved_for_label < repetitions:
                incomplete_labels.append(label)

            if (label_index + 1) < len(labels) and not args.auto_continue:
                _wait_for_enter("press Enter to continue to the next phrase...", enabled=prompt_enabled)
            print("")
    finally:
        capture.release()

    print("session summary")
    for label in labels:
        print(f"  {label}: {per_label_saved.get(label, 0)}/{repetitions} saved")
    print(f"total_saved={total_saved} attempted_frames={attempted}")
    if incomplete_labels:
        print(f"incomplete_labels={', '.join(incomplete_labels)}")
        return 2
    return 0


async def _run_timed_mode(args: argparse.Namespace) -> int:
    label = _normalize_label(args.label)
    output_dir = Path(args.output_dir).expanduser() / label
    output_dir.mkdir(parents=True, exist_ok=True)

    extractor = _build_extractor()
    source_raw = args.source.strip()
    try:
        capture, source = _open_capture(source_raw, width=int(args.width), height=int(args.height))
    except RuntimeError as exc:
        print(str(exc))
        return 1

    duration_seconds = max(1.0, float(args.duration_seconds))
    frame_stride = max(1, int(args.frame_stride))
    min_conf = max(0.0, min(1.0, float(args.min_confidence)))
    max_images = max(1, int(args.max_images))

    print(
        f"collecting label={label} source={source_raw} ({source}) duration={duration_seconds}s "
        f"stride={frame_stride} max_images={max_images}"
    )
    start = datetime.now(timezone.utc)
    frame_id = 0
    saved = 0
    attempted = 0

    try:
        while True:
            now = datetime.now(timezone.utc)
            elapsed = (now - start).total_seconds()
            if elapsed >= duration_seconds or saved >= max_images:
                break

            ok, frame_bgr = capture.read()
            if not ok or frame_bgr is None:
                await asyncio.sleep(0.02)
                continue

            frame_id += 1
            if frame_id % frame_stride != 0:
                continue
            attempted += 1

            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            ok_jpg, encoded = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok_jpg:
                continue
            payload = bytes(encoded.tobytes())

            packet = FramePacket(
                frame_id=frame_id,
                captured_at=now,
                payload=payload,
                source_name="live-capture",
            )
            hands = await extractor.extract(packet)
            if not hands:
                continue

            best = max(hands, key=lambda item: item.confidence)
            if best.confidence < min_conf:
                continue

            crop = _crop_hand_region(frame_rgb, best.landmarks)
            if best.handedness.lower() == "left":
                crop = crop[:, ::-1, :]

            image = Image.fromarray(crop.astype("uint8"), mode="RGB")
            filename = output_dir / f"{label}_{saved:05d}.jpg"
            image.save(filename, format="JPEG", quality=92)
            saved += 1

            if saved % 20 == 0:
                print(f"saved={saved} attempted={attempted} elapsed={round(elapsed,1)}s")

    finally:
        capture.release()

    print(f"done: saved={saved} attempted={attempted} output={output_dir}")
    return 0 if saved > 0 else 2


async def _run(args: argparse.Namespace) -> int:
    phrase_mode_requested = bool(args.phrases or args.phrases_file)
    if phrase_mode_requested:
        return await _run_repetition_mode(args)
    if not args.label:
        print("missing required label. Use --label for timed mode, or --phrases/--phrases-file.")
        return 2
    return await _run_timed_mode(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect labeled hand crops from a live camera/OBS source. "
        "Supports timed single-label capture and phrase-by-phrase repetition capture.",
    )
    parser.add_argument(
        "--label",
        help="Label to capture for timed mode (e.g. A, B, HELLO).",
    )
    parser.add_argument(
        "--phrases",
        help="Comma-separated labels for repetition mode (e.g. HELLO,THANK_YOU,I_LOVE_YOU).",
    )
    parser.add_argument(
        "--phrases-file",
        help="Text file with one phrase label per line for repetition mode.",
    )
    parser.add_argument("--source", default="0", help="OpenCV source index or stream URL.")
    parser.add_argument(
        "--output-dir",
        default="backend/data/live_calibration",
        help="Base output directory where label folders are stored.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=15.0,
        help="Timed mode: capture duration for this label.",
    )
    parser.add_argument(
        "--frame-stride",
        type=int,
        default=2,
        help="Process every Nth frame.",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.6,
        help="Minimum hand confidence to save a crop.",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=220,
        help="Timed mode: maximum images to save for this run.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=7,
        help="Repetition mode: target captures per label.",
    )
    parser.add_argument(
        "--capture-seconds",
        type=float,
        default=2.4,
        help="Repetition mode: capture window duration per attempt.",
    )
    parser.add_argument(
        "--max-attempts-per-repetition",
        type=int,
        default=4,
        help="Repetition mode: max retries for each repetition.",
    )
    parser.add_argument(
        "--countdown-seconds",
        type=float,
        default=1.0,
        help="Repetition mode: countdown before each capture attempt.",
    )
    parser.add_argument(
        "--auto-continue",
        action="store_true",
        help="Repetition mode: do not pause between phrases.",
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Repetition mode: disable Enter prompts (useful for scripted runs).",
    )
    parser.add_argument("--width", type=int, default=640, help="Requested capture width.")
    parser.add_argument("--height", type=int, default=480, help="Requested capture height.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
