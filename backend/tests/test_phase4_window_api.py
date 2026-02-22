from __future__ import annotations

import os
import time
import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class Phase4WindowApiTest(unittest.TestCase):
    def test_window_routes_contract(self) -> None:
        os.environ["CAMERA_SOURCE_MODE"] = "simulated"
        os.environ["SIMULATED_DISCONNECT_AFTER_SECONDS"] = "-1"
        os.environ["LANDMARK_MODE"] = "mock"
        os.environ["MOCK_LANDMARK_DETECTION_RATE"] = "1.0"
        os.environ["WINDOW_DURATION_SECONDS"] = "1.0"
        os.environ["WINDOW_SLIDE_SECONDS"] = "0.4"

        app = create_app()
        with TestClient(app) as client:
            time.sleep(1.2)

            status_response = client.get("/windows/status")
            self.assertEqual(status_response.status_code, 200)
            status_payload = status_response.json()

            for key in (
                "windowing_enabled",
                "running",
                "healthy",
                "landmarks_received",
                "windows_emitted",
                "queue_size",
                "buffer_size",
            ):
                self.assertIn(key, status_payload)

            recent_response = client.get("/windows/recent?limit=3")
            self.assertEqual(recent_response.status_code, 200)
            recent_payload = recent_response.json()
            self.assertIn("results", recent_payload)
            self.assertIn("count", recent_payload)

            if recent_payload["count"] > 0:
                first = recent_payload["results"][0]
                for key in ("window_id", "window_start", "window_end", "frame_count", "frames"):
                    self.assertIn(key, first)


if __name__ == "__main__":
    unittest.main()

