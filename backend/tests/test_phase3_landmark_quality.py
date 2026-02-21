from __future__ import annotations

import asyncio
import logging
import os
import unittest

from backend.app.ingest.manager import IngestManager
from backend.app.landmarks.pipeline import LandmarkPipeline
from backend.app.settings import Settings


class Phase3LandmarkQualityTest(unittest.IsolatedAsyncioTestCase):
    async def test_p3_landmark_quality_test(self) -> None:
        run_seconds = float(os.getenv("PHASE3_RUN_DURATION_SECONDS", "4"))

        settings = Settings(
            service_name="utg-backend",
            service_version="0.1.0-phase3",
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
            simulated_fps=14.0,
            simulated_disconnect_after_seconds=-1.0,
            simulated_disconnect_duration_seconds=0.0,
            landmark_enabled=True,
            landmark_mode="mock",
            landmark_queue_maxsize=128,
            landmark_recent_results_limit=25,
            mock_landmark_detection_rate=1.0,
            gemini_api_key="test-key",
        )

        logger = logging.getLogger("utg.backend.test.phase3")
        landmark_pipeline = LandmarkPipeline(settings=settings, logger=logger)
        ingest_manager = IngestManager(settings=settings, logger=logger)
        ingest_manager.register_frame_handler(landmark_pipeline.enqueue_frame)

        await landmark_pipeline.start()
        await ingest_manager.start()
        await asyncio.sleep(run_seconds)
        await ingest_manager.stop()
        await landmark_pipeline.stop()

        snapshot = landmark_pipeline.snapshot()
        recent = landmark_pipeline.recent_results(limit=5)

        self.assertGreater(snapshot["frames_processed"], 0)
        self.assertGreater(snapshot["frames_with_hands"], 0)
        self.assertGreaterEqual(snapshot["average_processing_ms"], 0.0)
        self.assertGreater(len(recent), 0)

        sample = recent[0]
        self.assertIn("frame_id", sample)
        self.assertIn("hands", sample)
        self.assertGreater(len(sample["hands"]), 0)

        hand = sample["hands"][0]
        self.assertIn("confidence", hand)
        self.assertGreaterEqual(hand["confidence"], 0.0)
        self.assertLessEqual(hand["confidence"], 1.0)
        self.assertEqual(len(hand["landmarks"]), 21)

        point = hand["landmarks"][0]
        self.assertIn("x", point)
        self.assertIn("y", point)
        self.assertIn("z", point)


if __name__ == "__main__":
    unittest.main()

