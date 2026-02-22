from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx


@dataclass(frozen=True)
class LandmarkPoint:
    x: float
    y: float
    z: float

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LandmarkPoint":
        return cls(
            x=float(payload.get("x", 0.0)),
            y=float(payload.get("y", 0.0)),
            z=float(payload.get("z", 0.0)),
        )

    def compact(self) -> str:
        return f"({self.x:.3f}, {self.y:.3f}, {self.z:.3f})"


def emit(message: str = "") -> None:
    print(message, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stream live landmark coordinates from backend /landmarks/recent "
            "for quick hand-detection debugging."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.6,
        help="Polling interval in seconds (default: 0.6)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="Number of recent frames to fetch per poll (default: 12)",
    )
    parser.add_argument(
        "--show-empty",
        action="store_true",
        help="Also print frames where no hands were detected.",
    )
    parser.add_argument(
        "--status-every",
        type=int,
        default=10,
        help="Print landmark/translation status every N polls (default: 10).",
    )
    return parser.parse_args()


def parse_ts(iso_value: str) -> str:
    try:
        ts = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
        return ts.strftime("%H:%M:%S")
    except Exception:
        return iso_value


def first_point(points: list[dict[str, Any]], index: int) -> LandmarkPoint:
    if 0 <= index < len(points):
        return LandmarkPoint.from_payload(points[index])
    return LandmarkPoint(0.0, 0.0, 0.0)


def print_frame_payload(payload: dict[str, Any], show_empty: bool) -> None:
    frame_id = int(payload.get("frame_id", -1))
    captured_at = parse_ts(str(payload.get("captured_at", "")))
    hands = payload.get("hands", [])
    if not isinstance(hands, list):
        hands = []

    if not hands and not show_empty:
        return

    if not hands:
        emit(f"[{captured_at}] frame={frame_id} hands=0")
        return

    emit(f"[{captured_at}] frame={frame_id} hands={len(hands)}")
    for hand in hands:
        handedness = str(hand.get("handedness", "unknown"))
        confidence = float(hand.get("confidence", 0.0))
        points = hand.get("landmarks", [])
        if not isinstance(points, list):
            points = []

        wrist = first_point(points, 0)
        thumb_tip = first_point(points, 4)
        index_tip = first_point(points, 8)
        pinky_tip = first_point(points, 20)

        emit(
            "  "
            f"{handedness:>5} conf={confidence:.3f} "
            f"wrist={wrist.compact()} "
            f"thumb={thumb_tip.compact()} "
            f"index={index_tip.compact()} "
            f"pinky={pinky_tip.compact()}"
        )


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    recent_url = f"{base_url}/landmarks/recent"
    landmark_status_url = f"{base_url}/landmarks/status"
    translation_status_url = f"{base_url}/translations/status"

    emit(
        "landmark debug stream started "
        f"(base_url={base_url}, poll_interval={args.poll_interval}s)"
    )
    emit("press Ctrl+C to stop\n")

    last_seen_frame = -1
    poll_count = 0

    with httpx.Client(timeout=3.0) as client:
        try:
            while True:
                poll_count += 1
                try:
                    recent_resp = client.get(
                        recent_url,
                        params={"limit": max(1, min(args.limit, 100))},
                    )
                    recent_resp.raise_for_status()
                    payload = recent_resp.json()
                except Exception as exc:
                    emit(f"[warn] failed to fetch recent landmarks: {exc}")
                    time.sleep(max(0.1, args.poll_interval))
                    continue

                results = payload.get("results", [])
                if not isinstance(results, list):
                    results = []

                # API returns newest first; print in chronological order.
                ordered = sorted(
                    (item for item in results if isinstance(item, dict)),
                    key=lambda item: int(item.get("frame_id", -1)),
                )
                for item in ordered:
                    frame_id = int(item.get("frame_id", -1))
                    if frame_id <= last_seen_frame:
                        continue
                    print_frame_payload(item, show_empty=args.show_empty)
                    last_seen_frame = frame_id

                if args.status_every > 0 and poll_count % args.status_every == 0:
                    try:
                        lm = client.get(landmark_status_url)
                        tr = client.get(translation_status_url)
                        lm.raise_for_status()
                        tr.raise_for_status()
                        lm_payload = lm.json()
                        tr_payload = tr.json()
                        emit(
                            "\n[status] "
                            f"frames_processed={lm_payload.get('frames_processed')} "
                            f"frames_with_hands={lm_payload.get('frames_with_hands')} "
                            f"windows_enqueued={tr_payload.get('windows_enqueued')} "
                            f"windows_processed={tr_payload.get('windows_processed')} "
                            f"skipped_low_signal={tr_payload.get('windows_skipped_low_signal')} "
                            f"suppressed_unclear={tr_payload.get('windows_suppressed_unclear')}\n"
                        )
                    except Exception as exc:
                        emit(f"[warn] failed to fetch status: {exc}")

                time.sleep(max(0.1, args.poll_interval))
        except KeyboardInterrupt:
            emit("\nlandmark debug stream stopped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
