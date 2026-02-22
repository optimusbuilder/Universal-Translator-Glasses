from __future__ import annotations

import os
import time
import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class Phase5TranslationApiTest(unittest.TestCase):
    def test_translation_routes_contract(self) -> None:
        os.environ["CAMERA_SOURCE_MODE"] = "simulated"
        os.environ["SIMULATED_DISCONNECT_AFTER_SECONDS"] = "-1"
        os.environ["LANDMARK_MODE"] = "mock"
        os.environ["MOCK_LANDMARK_DETECTION_RATE"] = "1.0"
        os.environ["WINDOW_DURATION_SECONDS"] = "1.0"
        os.environ["WINDOW_SLIDE_SECONDS"] = "0.4"
        os.environ["TRANSLATION_MODE"] = "mock"

        app = create_app()
        with TestClient(app) as client:
            time.sleep(1.5)

            status_response = client.get("/translations/status")
            self.assertEqual(status_response.status_code, 200)
            status_payload = status_response.json()
            for key in (
                "translation_enabled",
                "running",
                "healthy",
                "windows_enqueued",
                "windows_processed",
                "partial_emitted",
                "final_emitted",
                "provider_name",
            ):
                self.assertIn(key, status_payload)

            recent_response = client.get("/translations/recent?limit=4")
            self.assertEqual(recent_response.status_code, 200)
            recent_payload = recent_response.json()
            self.assertIn("results", recent_payload)
            self.assertIn("count", recent_payload)

            if recent_payload["count"] > 0:
                first = recent_payload["results"][0]
                for key in (
                    "window_id",
                    "kind",
                    "text",
                    "confidence",
                    "uncertain",
                    "created_at",
                    "latency_ms",
                ):
                    self.assertIn(key, first)


if __name__ == "__main__":
    unittest.main()

