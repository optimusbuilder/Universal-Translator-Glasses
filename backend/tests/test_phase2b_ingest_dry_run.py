from __future__ import annotations

import asyncio
import logging
import os
import unittest

import httpx

from backend.app.ingest.manager import IngestManager
from backend.app.ingest.sources.esp32_http import ESP32HttpCameraSource
from backend.app.settings import Settings


class Phase2BIngestDryRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_phase2b_dry_run_with_mock_transport(self) -> None:
        soak_seconds = float(os.getenv("PHASE2B_DRY_RUN_DURATION_SECONDS", "4"))
        request_counter = {"count": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            request_counter["count"] += 1
            current = request_counter["count"]

            if request.url.path != "/frame":
                return httpx.Response(status_code=404, content=b"not found")

            if 8 <= current <= 16:
                return httpx.Response(status_code=503, content=b"temporary outage")

            return httpx.Response(
                status_code=200,
                headers={"content-type": "image/jpeg"},
                content=f"esp32-dryrun-frame-{current}".encode("utf-8"),
            )

        transport = httpx.MockTransport(handler)

        settings = Settings(
            service_name="utg-backend",
            service_version="0.1.0-phase2b-dryrun",
            environment="test",
            log_level="INFO",
            host="127.0.0.1",
            port=8000,
            ingest_enabled=True,
            camera_source_mode="esp32_http",
            camera_source_url="http://esp32.mock",
            ingest_reconnect_backoff_seconds=0.2,
            esp32_frame_path="/frame",
            esp32_request_timeout_seconds=1.0,
            esp32_poll_interval_seconds=0.02,
            simulated_fps=12.0,
            simulated_disconnect_after_seconds=-1.0,
            simulated_disconnect_duration_seconds=0.0,
            landmark_enabled=True,
            landmark_mode="mock",
            landmark_queue_maxsize=128,
            landmark_recent_results_limit=20,
            mock_landmark_detection_rate=0.9,
            windowing_enabled=True,
            window_duration_seconds=1.5,
            window_slide_seconds=0.5,
            window_queue_maxsize=128,
            window_recent_results_limit=40,
            gemini_api_key="test-key",
        )

        def source_factory() -> ESP32HttpCameraSource:
            return ESP32HttpCameraSource(
                base_url=settings.camera_source_url or "",
                frame_path=settings.esp32_frame_path,
                request_timeout_seconds=settings.esp32_request_timeout_seconds,
                poll_interval_seconds=settings.esp32_poll_interval_seconds,
                client_factory=lambda: httpx.AsyncClient(
                    base_url=settings.camera_source_url or "",
                    transport=transport,
                    timeout=settings.esp32_request_timeout_seconds,
                ),
            )

        logger = logging.getLogger("utg.backend.test.phase2b")
        manager = IngestManager(
            settings=settings,
            logger=logger,
            source_factory_override=source_factory,
        )

        await manager.start()
        await asyncio.sleep(soak_seconds)
        await manager.stop()

        snapshot = manager.snapshot()
        self.assertTrue(snapshot["ingest_enabled"])
        self.assertGreater(snapshot["frames_received"], 0)
        self.assertGreater(snapshot["effective_fps"], 0.0)
        self.assertGreaterEqual(snapshot["reconnect_count"], 1)
        self.assertGreaterEqual(snapshot["dropped_frames"], 1)
        self.assertIsNotNone(snapshot["last_frame_at"])
        self.assertFalse(snapshot["connected"])
        self.assertFalse(snapshot["healthy"])


if __name__ == "__main__":
    unittest.main()
