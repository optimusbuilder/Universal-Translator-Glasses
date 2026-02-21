from __future__ import annotations

import logging
import os
import time
import unittest

from fastapi.testclient import TestClient

from backend.app.main import create_app


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class Phase1BootTest(unittest.TestCase):
    def _health_loop(self, client: TestClient, duration_seconds: float, interval_seconds: float) -> dict:
        end_time = time.monotonic() + duration_seconds
        samples = 0
        latest_payload: dict | None = None

        while time.monotonic() < end_time:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)

            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertIn("version", payload)
            self.assertIn("started_at", payload)
            self.assertIn("uptime_seconds", payload)
            self.assertIn("checks", payload)

            latest_payload = payload
            samples += 1
            time.sleep(interval_seconds)

        self.assertGreater(samples, 0)
        assert latest_payload is not None
        return latest_payload

    def _run_boot_cycle(
        self,
        duration_seconds: float,
        interval_seconds: float,
        capture_handler: _CaptureHandler,
    ) -> dict:
        root_logger = logging.getLogger()
        app = create_app()
        root_logger.addHandler(capture_handler)

        try:
            with TestClient(app) as client:
                payload = self._health_loop(client, duration_seconds, interval_seconds)
        finally:
            root_logger.removeHandler(capture_handler)

        return payload

    def test_p1_backend_boot_test(self) -> None:
        duration_seconds = float(os.getenv("PHASE1_HEALTH_DURATION_SECONDS", "60"))
        interval_seconds = float(os.getenv("PHASE1_HEALTH_INTERVAL_SECONDS", "1"))
        restart_duration_seconds = float(
            os.getenv("PHASE1_RESTART_HEALTH_DURATION_SECONDS", "10")
        )

        capture_handler = _CaptureHandler()

        first_payload = self._run_boot_cycle(duration_seconds, interval_seconds, capture_handler)
        second_payload = self._run_boot_cycle(
            restart_duration_seconds, interval_seconds, capture_handler
        )

        self.assertNotEqual(first_payload["started_at"], second_payload["started_at"])

        startup_records = [r for r in capture_handler.records if r.getMessage() == "service_startup"]
        shutdown_records = [r for r in capture_handler.records if r.getMessage() == "service_shutdown"]

        self.assertGreaterEqual(len(startup_records), 2)
        self.assertGreaterEqual(len(shutdown_records), 2)

        for record in startup_records + shutdown_records:
            self.assertTrue(hasattr(record, "service_version"))
            self.assertTrue(hasattr(record, "service_name"))
            self.assertIsNotNone(record.created)


if __name__ == "__main__":
    unittest.main()

