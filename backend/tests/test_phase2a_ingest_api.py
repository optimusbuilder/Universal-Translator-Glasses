from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class Phase2AIngestApiTest(unittest.TestCase):
    def test_ingest_status_contract(self) -> None:
        os.environ.setdefault("CAMERA_SOURCE_MODE", "simulated")
        os.environ.setdefault("SIMULATED_DISCONNECT_AFTER_SECONDS", "-1")
        os.environ.setdefault("SIMULATED_SOURCE_FPS", "12")

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/ingest/status")
            self.assertEqual(response.status_code, 200)

            payload = response.json()
            for key in (
                "source_mode",
                "connected",
                "healthy",
                "frames_received",
                "dropped_frames",
                "reconnect_count",
                "effective_fps",
                "ingest_enabled",
                "running",
            ):
                self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()

