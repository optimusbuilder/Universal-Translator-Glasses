from __future__ import annotations

import os
import time
import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class Phase3LandmarkApiTest(unittest.TestCase):
    def test_landmark_routes_contract(self) -> None:
        os.environ["CAMERA_SOURCE_MODE"] = "simulated"
        os.environ["SIMULATED_DISCONNECT_AFTER_SECONDS"] = "-1"
        os.environ["LANDMARK_MODE"] = "mock"
        os.environ["MOCK_LANDMARK_DETECTION_RATE"] = "1.0"

        app = create_app()
        with TestClient(app) as client:
            time.sleep(0.35)

            status_response = client.get("/landmarks/status")
            self.assertEqual(status_response.status_code, 200)
            status_payload = status_response.json()

            for key in (
                "mode",
                "extractor_name",
                "frames_enqueued",
                "frames_processed",
                "frames_with_hands",
                "average_processing_ms",
                "landmark_enabled",
                "running",
                "healthy",
            ):
                self.assertIn(key, status_payload)

            recent_response = client.get("/landmarks/recent?limit=3")
            self.assertEqual(recent_response.status_code, 200)
            recent_payload = recent_response.json()
            self.assertIn("results", recent_payload)
            self.assertIn("count", recent_payload)


if __name__ == "__main__":
    unittest.main()

