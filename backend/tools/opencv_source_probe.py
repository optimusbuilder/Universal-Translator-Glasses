from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe local OpenCV capture indices and report which are readable."
    )
    parser.add_argument(
        "--max-index",
        type=int,
        default=10,
        help="Highest camera index to probe (default: 10).",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=20,
        help="Frames to sample per source for motion estimate (default: 20).",
    )
    parser.add_argument(
        "--save-dir",
        default="",
        help="Optional directory to save one snapshot per readable source.",
    )
    return parser.parse_args()


def main() -> int:
    try:
        import cv2  # type: ignore[import-not-found]
    except Exception as exc:
        print(f"opencv import failed: {exc}")
        return 1

    args = parse_args()
    max_index = max(0, args.max_index)
    sample_frames = max(3, args.frames)
    save_dir = Path(args.save_dir).expanduser() if args.save_dir else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
    print(f"probing camera indices 0..{max_index}")

    found = 0
    for idx in range(max_index + 1):
        capture: Any = cv2.VideoCapture(idx)
        if not capture.isOpened():
            capture.release()
            print(f"[{idx}] closed")
            continue

        frames: list[Any] = []
        for _ in range(sample_frames):
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            frames.append(frame)

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        capture.release()

        if len(frames) < 3:
            print(f"[{idx}] opened but no frame ({width}x{height})")
            continue

        gray_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in frames]
        target_h, target_w = gray_frames[0].shape
        normalized_frames: list[Any] = []
        for gray in gray_frames:
            if gray.shape != (target_h, target_w):
                gray = cv2.resize(
                    gray,
                    (target_w, target_h),
                    interpolation=cv2.INTER_AREA,
                )
            normalized_frames.append(gray)

        motion_samples: list[float] = []
        for a, b in zip(normalized_frames, normalized_frames[1:]):
            try:
                motion_samples.append(float(cv2.absdiff(a, b).mean()))
            except Exception:
                # Some virtual devices can output transient invalid frames.
                continue

        if not motion_samples:
            print(f"[{idx}] opened but motion estimate unavailable ({width}x{height})")
            continue

        motion = sum(motion_samples) / max(1, len(motion_samples))
        brightness = float(normalized_frames[-1].mean())

        if save_dir:
            snapshot_path = save_dir / f"camera_index_{idx}.jpg"
            cv2.imwrite(str(snapshot_path), frames[-1])

        found += 1
        saved_suffix = f" saved={snapshot_path}" if save_dir else ""
        print(
            f"[{idx}] OK {width}x{height} "
            f"motion={motion:.2f} brightness={brightness:.1f}{saved_suffix}"
        )

    if found == 0:
        print("no readable camera indices found")
        return 2

    print(f"readable sources found: {found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
