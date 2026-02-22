from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Any

import httpx


def emit(message: str = "") -> None:
    print(message, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Poll backend pipeline endpoints and pinpoint where data flow is stalling "
            "(ingest, landmarks, windowing, or translation)."
        )
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Backend base URL (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=20.0,
        help="How long to sample in seconds (default: 20)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds (default: 1.0)",
    )
    return parser.parse_args()


@dataclass
class Snapshot:
    ingest_frames: int = 0
    ingest_fps: float = 0.0
    landmark_processed: int = 0
    landmark_with_hands: int = 0
    windows_emitted: int = 0
    windows_landmarks_received: int = 0
    tr_enqueued: int = 0
    tr_processed: int = 0
    tr_skipped_low_signal: int = 0
    tr_suppressed_unclear: int = 0
    tr_retry_events: int = 0
    tr_last_error: str | None = None
    tr_recent_texts: list[str] | None = None


def _to_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key, 0)
    try:
        return int(value)
    except Exception:
        return 0


def _to_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key, 0.0)
    try:
        return float(value)
    except Exception:
        return 0.0


def fetch_snapshot(client: httpx.Client, base_url: str) -> Snapshot:
    ingest = client.get(f"{base_url}/ingest/status").json()
    landmark = client.get(f"{base_url}/landmarks/status").json()
    windows = client.get(f"{base_url}/windows/status").json()
    tr = client.get(f"{base_url}/translations/status").json()
    tr_recent = client.get(f"{base_url}/translations/recent", params={"limit": 8}).json()

    texts: list[str] = []
    results = tr_recent.get("results", [])
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                texts.append(text)

    return Snapshot(
        ingest_frames=_to_int(ingest, "frames_received"),
        ingest_fps=_to_float(ingest, "effective_fps"),
        landmark_processed=_to_int(landmark, "frames_processed"),
        landmark_with_hands=_to_int(landmark, "frames_with_hands"),
        windows_emitted=_to_int(windows, "windows_emitted"),
        windows_landmarks_received=_to_int(windows, "landmarks_received"),
        tr_enqueued=_to_int(tr, "windows_enqueued"),
        tr_processed=_to_int(tr, "windows_processed"),
        tr_skipped_low_signal=_to_int(tr, "windows_skipped_low_signal"),
        tr_suppressed_unclear=_to_int(tr, "windows_suppressed_unclear"),
        tr_retry_events=_to_int(tr, "retry_events"),
        tr_last_error=tr.get("last_error") if isinstance(tr.get("last_error"), str) else None,
        tr_recent_texts=texts,
    )


def diagnose(start: Snapshot, end: Snapshot) -> str:
    d_ingest = end.ingest_frames - start.ingest_frames
    d_landmark = end.landmark_processed - start.landmark_processed
    d_hands = end.landmark_with_hands - start.landmark_with_hands
    d_windows = end.windows_emitted - start.windows_emitted
    d_tr_enq = end.tr_enqueued - start.tr_enqueued
    d_tr_proc = end.tr_processed - start.tr_processed
    d_tr_skip = end.tr_skipped_low_signal - start.tr_skipped_low_signal
    d_tr_sup = end.tr_suppressed_unclear - start.tr_suppressed_unclear
    d_retry = end.tr_retry_events - start.tr_retry_events

    if d_ingest <= 0:
        return "INGEST ISSUE: backend is not receiving frames."
    if d_landmark <= 0:
        return "LANDMARK ISSUE: frames are ingested but MediaPipe is not processing."
    if d_hands <= 0:
        return "SIGNAL ISSUE: MediaPipe runs, but no hands are being detected in the sampled period."
    if d_windows <= 0:
        return "WINDOWING ISSUE: landmarks are produced, but windows are not being emitted."
    if d_tr_enq <= 0:
        return "PIPE WIRING ISSUE: windows are emitted, but not reaching translation queue."
    if d_tr_proc <= 0 and d_tr_skip > 0:
        return (
            "LOW-SIGNAL FILTERING: windows reached translation, but were skipped "
            "because too few frames had hands."
        )
    if d_tr_proc <= 0 and d_retry > 0:
        return (
            "GEMINI ISSUE: translation retries occurred without processed outputs. "
            f"last_error={end.tr_last_error!r}"
        )
    if d_tr_proc > 0 and d_tr_sup > 0:
        return (
            "TRANSLATION RUNNING: outputs are being generated, but many are suppressed "
            "as unclear/prompt-leak."
        )

    texts = end.tr_recent_texts or []
    if texts:
        return "TRANSLATION RUNNING: recent text outputs are present."

    return "TRANSLATION STALLED: ambiguous state; inspect /translations/status last_error."


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    interval = max(0.2, args.interval)
    rounds = max(3, int(max(1.0, args.duration) / interval))

    emit(
        f"pipeline diagnose started (base_url={base_url}, "
        f"duration={args.duration}s, interval={interval}s)"
    )

    with httpx.Client(timeout=4.0) as client:
        try:
            health = client.get(f"{base_url}/health")
            health.raise_for_status()
        except Exception as exc:
            emit(f"failed to reach backend health endpoint: {exc}")
            return 2

        first = fetch_snapshot(client, base_url)
        prev = first

        for idx in range(rounds):
            time.sleep(interval)
            snap = fetch_snapshot(client, base_url)
            emit(
                f"[{idx+1:02d}] "
                f"ingest={snap.ingest_frames} (+{snap.ingest_frames - prev.ingest_frames}) "
                f"fps={snap.ingest_fps:.1f} | "
                f"lm={snap.landmark_processed} (+{snap.landmark_processed - prev.landmark_processed}) "
                f"hands={snap.landmark_with_hands} (+{snap.landmark_with_hands - prev.landmark_with_hands}) | "
                f"win={snap.windows_emitted} (+{snap.windows_emitted - prev.windows_emitted}) | "
                f"tr_enq={snap.tr_enqueued} (+{snap.tr_enqueued - prev.tr_enqueued}) "
                f"tr_ok={snap.tr_processed} (+{snap.tr_processed - prev.tr_processed}) "
                f"skip={snap.tr_skipped_low_signal} (+{snap.tr_skipped_low_signal - prev.tr_skipped_low_signal}) "
                f"suppr={snap.tr_suppressed_unclear} (+{snap.tr_suppressed_unclear - prev.tr_suppressed_unclear}) "
                f"retry={snap.tr_retry_events} (+{snap.tr_retry_events - prev.tr_retry_events})"
            )
            prev = snap

        emit("")
        verdict = diagnose(first, prev)
        emit(f"VERDICT: {verdict}")
        if prev.tr_recent_texts:
            unique_recent = []
            for text in prev.tr_recent_texts:
                if text not in unique_recent:
                    unique_recent.append(text)
            emit(f"recent_texts: {unique_recent[:5]}")
        if prev.tr_last_error:
            emit(f"last_translation_error: {prev.tr_last_error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
