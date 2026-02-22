from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class Phase6WebSocketDeliveryTest(unittest.TestCase):
    def test_p6_websocket_delivery(self) -> None:
        os.environ["CAMERA_SOURCE_MODE"] = "simulated"
        os.environ["SIMULATED_SOURCE_FPS"] = "14.0"
        os.environ["SIMULATED_DISCONNECT_AFTER_SECONDS"] = "1.8"
        os.environ["SIMULATED_DISCONNECT_DURATION_SECONDS"] = "0.8"
        os.environ["INGEST_RECONNECT_BACKOFF_SECONDS"] = "0.4"
        os.environ["LANDMARK_MODE"] = "mock"
        os.environ["MOCK_LANDMARK_DETECTION_RATE"] = "1.0"
        os.environ["WINDOW_DURATION_SECONDS"] = "0.9"
        os.environ["WINDOW_SLIDE_SECONDS"] = "0.3"
        os.environ["TRANSLATION_MODE"] = "mock"
        os.environ["REALTIME_METRICS_INTERVAL_SECONDS"] = "0.1"
        os.environ["REALTIME_ALERT_COOLDOWN_SECONDS"] = "0.1"

        app = create_app()
        required_events = {
            "caption.partial",
            "caption.final",
            "system.metrics",
            "system.alert",
        }

        with TestClient(app) as client:
            with client.websocket_connect("/ws/events") as socket:
                received_events: set[str] = set()

                for _ in range(120):
                    message = socket.receive_json()
                    self.assertIn("event", message)
                    self.assertIn("timestamp", message)
                    self.assertIn("payload", message)

                    event_type = message["event"]
                    received_events.add(event_type)

                    if event_type == "system.alert":
                        self.assertIn("severity", message["payload"])
                        self.assertIn("component", message["payload"])
                        self.assertIn("reason", message["payload"])

                    if required_events.issubset(received_events):
                        break

        self.assertTrue(
            required_events.issubset(received_events),
            msg=f"missing events: {sorted(required_events - received_events)}",
        )


if __name__ == "__main__":
    unittest.main()
