from __future__ import annotations

import unittest

import httpx

from backend.app.ingest.sources.base import CameraSourceDisconnected
from backend.app.ingest.sources.esp32_http import ESP32HttpCameraSource


class Phase2BESP32SourceMockTest(unittest.IsolatedAsyncioTestCase):
    async def test_esp32_http_source_contract(self) -> None:
        request_counter = {"count": 0}

        async def handler(request: httpx.Request) -> httpx.Response:
            request_counter["count"] += 1
            current = request_counter["count"]

            if request.url.path != "/frame":
                return httpx.Response(status_code=404, content=b"not found")

            if 3 <= current <= 4:
                return httpx.Response(status_code=503, content=b"unavailable")

            return httpx.Response(
                status_code=200,
                headers={"content-type": "image/jpeg"},
                content=f"mock-frame-{current}".encode("utf-8"),
            )

        transport = httpx.MockTransport(handler)
        source = ESP32HttpCameraSource(
            base_url="http://esp32.mock",
            frame_path="/frame",
            request_timeout_seconds=1.0,
            poll_interval_seconds=0.0,
            client_factory=lambda: httpx.AsyncClient(
                base_url="http://esp32.mock",
                transport=transport,
                timeout=1.0,
            ),
        )

        await source.connect()
        frame_1 = await source.read_frame()
        frame_2 = await source.read_frame()
        self.assertTrue(frame_1.payload.startswith(b"mock-frame-"))
        self.assertTrue(frame_2.payload.startswith(b"mock-frame-"))

        with self.assertRaises(CameraSourceDisconnected):
            await source.read_frame()

        with self.assertRaises(CameraSourceDisconnected):
            await source.read_frame()

        frame_3 = await source.read_frame()
        self.assertTrue(frame_3.payload.startswith(b"mock-frame-"))

        await source.disconnect()


if __name__ == "__main__":
    unittest.main()
