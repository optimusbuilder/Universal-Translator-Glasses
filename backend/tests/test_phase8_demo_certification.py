from __future__ import annotations

import os
import time
import unittest
from datetime import datetime
from statistics import mean
from typing import Any

from fastapi.testclient import TestClient

from backend.app.main import create_app


def _to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _parse_iso(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


class Phase8DemoCertificationTest(unittest.TestCase):
    def _collect_run_kpis(
        self,
        client: TestClient,
        run_seconds: float,
        require_interruption_recovery: bool,
    ) -> dict[str, Any]:
        final_times: list[datetime] = []
        fps_samples: list[float] = []
        translation_latency_samples: list[float] = []
        queue_depth_samples: list[int] = []
        saw_disconnect_state = False
        saw_recovered_state = False
        partial_count = 0
        final_count = 0

        end_time = time.monotonic() + run_seconds
        with client.websocket_connect("/ws/events") as socket:
            while time.monotonic() < end_time:
                message = socket.receive_json()
                event_type = message.get("event")
                payload = message.get("payload", {})

                if event_type == "caption.partial":
                    partial_count += 1
                elif event_type == "caption.final":
                    final_count += 1
                    event_timestamp = str(message.get("timestamp", ""))
                    if event_timestamp:
                        final_times.append(_parse_iso(event_timestamp))
                elif event_type == "system.metrics" and isinstance(payload, dict):
                    ingest = payload.get("ingest", {}) if isinstance(payload.get("ingest"), dict) else {}
                    landmark = (
                        payload.get("landmark", {}) if isinstance(payload.get("landmark"), dict) else {}
                    )
                    windowing = (
                        payload.get("windowing", {}) if isinstance(payload.get("windowing"), dict) else {}
                    )
                    translation = (
                        payload.get("translation", {})
                        if isinstance(payload.get("translation"), dict)
                        else {}
                    )

                    fps_samples.append(_to_float(ingest.get("effective_fps"), 0.0))
                    translation_latency_samples.append(
                        _to_float(translation.get("last_processing_ms"), 0.0)
                    )
                    queue_depth_samples.append(
                        _to_int(landmark.get("queue_size"), 0)
                        + _to_int(windowing.get("queue_size"), 0)
                        + _to_int(translation.get("queue_size"), 0)
                    )

                    reconnect_count = _to_int(ingest.get("reconnect_count"), 0)
                    connected = bool(ingest.get("connected", False))
                    if reconnect_count > 0 and not connected:
                        saw_disconnect_state = True
                    if reconnect_count > 0 and connected:
                        saw_recovered_state = True

        gaps: list[float] = []
        if len(final_times) >= 2:
            for idx in range(1, len(final_times)):
                gaps.append((final_times[idx] - final_times[idx - 1]).total_seconds())

        if require_interruption_recovery:
            self.assertTrue(saw_disconnect_state, "expected interruption state was not observed")
            self.assertTrue(saw_recovered_state, "expected recovery state was not observed")

        return {
            "partial_count": partial_count,
            "final_count": final_count,
            "fps_samples": fps_samples,
            "translation_latency_samples": translation_latency_samples,
            "queue_depth_samples": queue_depth_samples,
            "final_gaps_seconds": gaps,
        }

    def test_p8_demo_certification_run(self) -> None:
        run_seconds = float(os.getenv("PHASE8_RUN_DURATION_SECONDS", "18"))
        repeat_seconds = float(os.getenv("PHASE8_REPEAT_DURATION_SECONDS", "6"))

        os.environ["CAMERA_SOURCE_MODE"] = "simulated"
        os.environ["SIMULATED_SOURCE_FPS"] = "14.0"
        os.environ["SIMULATED_DISCONNECT_AFTER_SECONDS"] = "4.0"
        os.environ["SIMULATED_DISCONNECT_DURATION_SECONDS"] = "1.3"
        os.environ["INGEST_RECONNECT_BACKOFF_SECONDS"] = "0.3"
        os.environ["LANDMARK_MODE"] = "mock"
        os.environ["MOCK_LANDMARK_DETECTION_RATE"] = "1.0"
        os.environ["MOCK_LANDMARK_EXTRACTION_DELAY_SECONDS"] = "0.0"
        os.environ["LANDMARK_QUEUE_MAXSIZE"] = "256"
        os.environ["LANDMARK_ADAPTIVE_FRAME_SKIP_ENABLED"] = "true"
        os.environ["LANDMARK_ADAPTIVE_SKIP_THRESHOLD"] = "0.75"
        os.environ["WINDOW_DURATION_SECONDS"] = "1.0"
        os.environ["WINDOW_SLIDE_SECONDS"] = "0.3"
        os.environ["WINDOW_QUEUE_MAXSIZE"] = "128"
        os.environ["TRANSLATION_MODE"] = "mock"
        os.environ["MOCK_TRANSLATION_DELAY_SECONDS"] = "0.12"
        os.environ["TRANSLATION_QUEUE_MAXSIZE"] = "128"
        os.environ["REALTIME_METRICS_INTERVAL_SECONDS"] = "0.2"
        os.environ["REALTIME_ALERT_COOLDOWN_SECONDS"] = "0.2"
        os.environ["REALTIME_TRANSLATION_LATENCY_ALERT_MS"] = "2500"
        os.environ["REALTIME_QUEUE_DEPTH_ALERT_THRESHOLD"] = "64"

        app = create_app()
        with TestClient(app) as client:
            primary = self._collect_run_kpis(
                client=client,
                run_seconds=run_seconds,
                require_interruption_recovery=True,
            )

            self.assertGreaterEqual(
                primary["final_count"],
                max(4, int(run_seconds / 4)),
                "insufficient finalized captions during certification run",
            )
            self.assertGreaterEqual(primary["partial_count"], primary["final_count"])
            self.assertGreater(len(primary["fps_samples"]), 0)
            self.assertGreater(len(primary["translation_latency_samples"]), 0)
            self.assertGreater(len(primary["queue_depth_samples"]), 0)

            peak_fps = max(primary["fps_samples"])
            avg_translation_latency = mean(primary["translation_latency_samples"])
            max_translation_latency = max(primary["translation_latency_samples"])
            max_queue_depth = max(primary["queue_depth_samples"])

            self.assertGreaterEqual(peak_fps, 12.0, "ingest fps gate not met")
            self.assertLessEqual(avg_translation_latency, 3000.0, "average latency too high")
            self.assertLessEqual(max_translation_latency, 3000.0, "latency spike above threshold")
            self.assertLess(max_queue_depth, 128, "queue depth indicates runaway growth")

            if primary["final_gaps_seconds"]:
                avg_gap = mean(primary["final_gaps_seconds"])
                self.assertLessEqual(avg_gap, 3.0, "caption cadence gate not met")

            repeat = self._collect_run_kpis(
                client=client,
                run_seconds=repeat_seconds,
                require_interruption_recovery=False,
            )
            self.assertGreaterEqual(
                repeat["final_count"],
                1,
                "repeatability check failed: no final captions in follow-up run",
            )

            health_response = client.get("/health")
            self.assertEqual(health_response.status_code, 200)
            health_payload = health_response.json()
            self.assertEqual(health_payload["status"], "ok")
            self.assertTrue(health_payload["checks"]["ingest_running"])
            self.assertTrue(health_payload["checks"]["translation_running"])
            self.assertTrue(health_payload["checks"]["realtime_running"])


if __name__ == "__main__":
    unittest.main()
