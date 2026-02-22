from __future__ import annotations

import os
import time
import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class Phase6RealtimeApiTest(unittest.TestCase):
    def test_realtime_routes_contract(self) -> None:
        os.environ["CAMERA_SOURCE_MODE"] = "simulated"
        os.environ["SIMULATED_DISCONNECT_AFTER_SECONDS"] = "-1"
        os.environ["LANDMARK_MODE"] = "mock"
        os.environ["MOCK_LANDMARK_DETECTION_RATE"] = "1.0"
        os.environ["WINDOW_DURATION_SECONDS"] = "0.9"
        os.environ["WINDOW_SLIDE_SECONDS"] = "0.3"
        os.environ["TRANSLATION_MODE"] = "mock"
        os.environ["REALTIME_METRICS_INTERVAL_SECONDS"] = "0.15"

        app = create_app()
        with TestClient(app) as client:
            time.sleep(1.2)

            status_response = client.get("/realtime/status")
            self.assertEqual(status_response.status_code, 200)
            status_payload = status_response.json()

            for key in (
                "realtime_enabled",
                "running",
                "healthy",
                "connected_clients",
                "events_emitted",
                "events_dropped",
                "recent_events_count",
            ):
                self.assertIn(key, status_payload)

            recent_response = client.get("/realtime/recent?limit=10")
            self.assertEqual(recent_response.status_code, 200)
            recent_payload = recent_response.json()
            self.assertIn("results", recent_payload)
            self.assertIn("count", recent_payload)

            if recent_payload["count"] > 0:
                first = recent_payload["results"][0]
                for key in ("event", "timestamp", "payload"):
                    self.assertIn(key, first)


if __name__ == "__main__":
    unittest.main()
