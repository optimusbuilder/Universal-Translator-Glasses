from __future__ import annotations

import asyncio
import logging
import os
import unittest
from datetime import datetime, timedelta, timezone

from backend.app.landmarks.types import HandLandmarks, LandmarkPoint, LandmarkResult
from backend.app.settings import Settings
from backend.app.translation.pipeline import TranslationPipeline
from backend.app.translation.providers.base import TranslationProvider, TranslationProviderError
from backend.app.translation.types import TranslationPayload
from backend.app.windowing.types import LandmarkWindow


class _FlakyProvider(TranslationProvider):
    def __init__(self) -> None:
        self._attempts = 0

    @property
    def name(self) -> str:
        return "flaky-provider"

    async def translate(self, window: LandmarkWindow) -> TranslationPayload:
        self._attempts += 1
        if self._attempts == 1:
            raise TranslationProviderError("simulated timeout")
        return TranslationPayload(text="Please wait a moment.", confidence=0.73)


class Phase5TranslationContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_p5_translation_contract(self) -> None:
        run_seconds = float(os.getenv("PHASE5_RUN_DURATION_SECONDS", "1.2"))

        settings = Settings(
            service_name="utg-backend",
            service_version="0.1.0-phase5",
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
            simulated_fps=12.0,
            simulated_disconnect_after_seconds=-1.0,
            simulated_disconnect_duration_seconds=0.0,
            landmark_enabled=True,
            landmark_mode="mock",
            landmark_queue_maxsize=128,
            landmark_recent_results_limit=20,
            mock_landmark_detection_rate=1.0,
            windowing_enabled=True,
            window_duration_seconds=1.2,
            window_slide_seconds=0.4,
            window_queue_maxsize=128,
            window_recent_results_limit=20,
            translation_enabled=True,
            translation_mode="mock",
            translation_queue_maxsize=64,
            translation_recent_results_limit=30,
            translation_timeout_seconds=2.0,
            translation_max_retries=2,
            translation_retry_backoff_seconds=0.05,
            translation_uncertainty_threshold=0.6,
            gemini_model="gemini-1.5-flash",
            gemini_api_base_url="https://generativelanguage.googleapis.com/v1beta",
            gemini_api_key="test-key",
        )

        pipeline = TranslationPipeline(
            settings=settings,
            logger=logging.getLogger("utg.backend.test.phase5"),
            provider_override=_FlakyProvider(),
        )
        await pipeline.start()

        now = datetime.now(timezone.utc)
        sample_hand = HandLandmarks(
            hand_index=0,
            handedness="right",
            confidence=0.82,
            landmarks=[LandmarkPoint(x=0.1, y=0.2, z=0.0) for _ in range(21)],
        )
        frame = LandmarkResult(
            frame_id=1,
            source_name="simulated-camera",
            captured_at=now,
            processed_at=now + timedelta(milliseconds=5),
            processing_ms=5.0,
            hands=[sample_hand],
        )
        window = LandmarkWindow(
            window_id=101,
            window_start=now,
            window_end=now + timedelta(seconds=1),
            frame_count=1,
            frames=[frame],
        )

        await pipeline.enqueue_window(window)
        await asyncio.sleep(run_seconds)
        await pipeline.stop()

        snapshot = pipeline.snapshot()
        recent = pipeline.recent_results(limit=5)

        self.assertGreaterEqual(snapshot["windows_processed"], 1)
        self.assertGreaterEqual(snapshot["partial_emitted"], 1)
        self.assertGreaterEqual(snapshot["final_emitted"], 1)
        self.assertGreaterEqual(snapshot["retry_events"], 1)
        self.assertGreater(len(recent), 0)

        kinds = {item["kind"] for item in recent}
        self.assertIn("partial", kinds)
        self.assertIn("final", kinds)

        final_items = [item for item in recent if item["kind"] == "final"]
        self.assertGreater(len(final_items), 0)
        self.assertTrue(final_items[0]["text"])
        self.assertGreaterEqual(final_items[0]["confidence"], 0.0)
        self.assertLessEqual(final_items[0]["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()

