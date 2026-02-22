from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class Phase7FaultInjectionTest(unittest.TestCase):
    def test_p7_fault_injection(self) -> None:
        os.environ["CAMERA_SOURCE_MODE"] = "simulated"
        os.environ["SIMULATED_SOURCE_FPS"] = "72.0"
        os.environ["SIMULATED_DISCONNECT_AFTER_SECONDS"] = "0.8"
        os.environ["SIMULATED_DISCONNECT_DURATION_SECONDS"] = "2.2"
        os.environ["INGEST_RECONNECT_BACKOFF_SECONDS"] = "0.25"
        os.environ["LANDMARK_MODE"] = "mock"
        os.environ["MOCK_LANDMARK_DETECTION_RATE"] = "1.0"
        os.environ["MOCK_LANDMARK_EXTRACTION_DELAY_SECONDS"] = "0.03"
        os.environ["LANDMARK_QUEUE_MAXSIZE"] = "12"
        os.environ["LANDMARK_ADAPTIVE_FRAME_SKIP_ENABLED"] = "true"
        os.environ["LANDMARK_ADAPTIVE_SKIP_THRESHOLD"] = "0.15"
        os.environ["WINDOW_DURATION_SECONDS"] = "0.7"
        os.environ["WINDOW_SLIDE_SECONDS"] = "0.08"
        os.environ["WINDOW_QUEUE_MAXSIZE"] = "12"
        os.environ["TRANSLATION_MODE"] = "mock"
        os.environ["MOCK_TRANSLATION_DELAY_SECONDS"] = "0.45"
        os.environ["TRANSLATION_QUEUE_MAXSIZE"] = "6"
        os.environ["REALTIME_METRICS_INTERVAL_SECONDS"] = "0.1"
        os.environ["REALTIME_ALERT_COOLDOWN_SECONDS"] = "0.1"
        os.environ["REALTIME_TRANSLATION_LATENCY_ALERT_MS"] = "120"
        os.environ["REALTIME_QUEUE_DEPTH_ALERT_THRESHOLD"] = "2"

        app = create_app()
        saw_ingest_alert = False
        saw_latency_alert = False
        saw_overload_alert = False

        with TestClient(app) as client:
            with client.websocket_connect("/ws/events") as socket:
                for _ in range(300):
                    message = socket.receive_json()
                    if message.get("event") != "system.alert":
                        continue

                    payload = message.get("payload", {})
                    if not isinstance(payload, dict):
                        continue

                    component = payload.get("component")
                    reason = str(payload.get("reason", ""))
                    severity = payload.get("severity")

                    if component == "ingest" and severity == "warning":
                        saw_ingest_alert = True
                    if component == "translation" and reason.startswith(
                        "high_translation_latency:"
                    ):
                        saw_latency_alert = True
                    if component == "system" and reason.startswith("queue_depth_high:"):
                        saw_overload_alert = True

                    if saw_ingest_alert and saw_latency_alert and saw_overload_alert:
                        break

            health_response = client.get("/health")
            self.assertEqual(health_response.status_code, 200)
            health_payload = health_response.json()
            self.assertEqual(health_payload["status"], "ok")

            landmark_status = client.get("/landmarks/status").json()
            realtime_status = client.get("/realtime/status").json()

            self.assertGreaterEqual(int(landmark_status.get("adaptive_skips", 0)), 1)
            self.assertGreater(int(realtime_status.get("events_emitted", 0)), 0)

        self.assertTrue(saw_ingest_alert, "missing ingest fault alert")
        self.assertTrue(saw_latency_alert, "missing translation latency alert")
        self.assertTrue(saw_overload_alert, "missing queue overload alert")


if __name__ == "__main__":
    unittest.main()
