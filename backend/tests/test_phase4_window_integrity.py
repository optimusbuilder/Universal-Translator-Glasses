from __future__ import annotations

import asyncio
import logging
import os
import unittest
from datetime import datetime

from backend.app.ingest.manager import IngestManager
from backend.app.landmarks.pipeline import LandmarkPipeline
from backend.app.settings import Settings
from backend.app.windowing.pipeline import WindowingPipeline


class Phase4WindowIntegrityTest(unittest.IsolatedAsyncioTestCase):
    async def test_p4_window_integrity(self) -> None:
        run_seconds = float(os.getenv("PHASE4_RUN_DURATION_SECONDS", "6"))

        settings = Settings(
            service_name="utg-backend",
            service_version="0.1.0-phase4",
            environment="test",
            log_level="INFO",
            host="127.0.0.1",
            port=8000,
            ingest_enabled=True,
            camera_source_mode="simulated",
            camera_source_url=None,
            ingest_reconnect_backoff_seconds=0.25,
            esp32_frame_path="/frame",
            esp32_request_timeout_seconds=1.0,
            esp32_poll_interval_seconds=0.08,
            simulated_fps=15.0,
            simulated_disconnect_after_seconds=-1.0,
            simulated_disconnect_duration_seconds=0.0,
            landmark_enabled=True,
            landmark_mode="mock",
            landmark_queue_maxsize=256,
            landmark_recent_results_limit=60,
            mock_landmark_detection_rate=1.0,
            windowing_enabled=True,
            window_duration_seconds=1.2,
            window_slide_seconds=0.4,
            window_queue_maxsize=256,
            window_recent_results_limit=50,
            gemini_api_key="test-key",
        )

        logger = logging.getLogger("utg.backend.test.phase4")
        windowing_pipeline = WindowingPipeline(settings=settings, logger=logger)
        landmark_pipeline = LandmarkPipeline(settings=settings, logger=logger)
        ingest_manager = IngestManager(settings=settings, logger=logger)

        landmark_pipeline.register_result_handler(windowing_pipeline.enqueue_landmark_result)
        ingest_manager.register_frame_handler(landmark_pipeline.enqueue_frame)

        await windowing_pipeline.start()
        await landmark_pipeline.start()
        await ingest_manager.start()
        await asyncio.sleep(run_seconds)
        await ingest_manager.stop()
        await landmark_pipeline.stop()
        await windowing_pipeline.stop()

        snapshot = windowing_pipeline.snapshot()
        recent_windows = windowing_pipeline.recent_windows(limit=10)

        self.assertGreater(snapshot["landmarks_received"], 0)
        self.assertGreater(snapshot["windows_emitted"], 0)
        self.assertEqual(snapshot["out_of_order_count"], 0)
        self.assertGreater(len(recent_windows), 0)

        for window in recent_windows:
            self.assertGreater(window["frame_count"], 0)
            self.assertEqual(window["frame_count"], len(window["frames"]))

            start = datetime.fromisoformat(window["window_start"])
            end = datetime.fromisoformat(window["window_end"])
            self.assertLess(start, end)

            previous_captured = None
            for frame in window["frames"]:
                captured = datetime.fromisoformat(frame["captured_at"])
                self.assertGreaterEqual(captured, start)
                self.assertLess(captured, end)
                if previous_captured is not None:
                    self.assertLessEqual(previous_captured, captured)
                previous_captured = captured


if __name__ == "__main__":
    unittest.main()

