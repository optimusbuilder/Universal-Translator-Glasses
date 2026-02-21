from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from fastapi import FastAPI, Response


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    return float(raw)


@dataclass
class MockState:
    request_count: int = 0
    disconnect_start_request: int = -1
    disconnect_span_requests: int = 0
    frame_delay_seconds: float = 0.0

    def should_disconnect(self) -> bool:
        if self.disconnect_start_request < 0 or self.disconnect_span_requests <= 0:
            return False

        end = self.disconnect_start_request + self.disconnect_span_requests
        return self.disconnect_start_request <= self.request_count < end


def create_mock_app() -> FastAPI:
    app = FastAPI(title="ESP32 Mock Camera")

    state = MockState(
        disconnect_start_request=_env_int("ESP32_MOCK_DISCONNECT_START_REQUEST", -1),
        disconnect_span_requests=_env_int("ESP32_MOCK_DISCONNECT_SPAN_REQUESTS", 0),
        frame_delay_seconds=_env_float("ESP32_MOCK_FRAME_DELAY_SECONDS", 0.0),
    )
    app.state.mock_state = state

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "request_count": state.request_count,
            "disconnect_start_request": state.disconnect_start_request,
            "disconnect_span_requests": state.disconnect_span_requests,
            "frame_delay_seconds": state.frame_delay_seconds,
        }

    @app.get("/frame")
    async def frame() -> Response:
        state.request_count += 1

        if state.frame_delay_seconds > 0:
            await asyncio.sleep(state.frame_delay_seconds)

        if state.should_disconnect():
            return Response(status_code=503, content=b"camera unavailable")

        payload = f"mock-jpeg-frame-{state.request_count}".encode("utf-8")
        return Response(content=payload, media_type="image/jpeg")

    return app


app = create_mock_app()

