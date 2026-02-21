from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :]

        key, separator, value = line.partition("=")
        if not separator:
            continue

        env_key = key.strip()
        if not env_key:
            continue

        env_value = _strip_quotes(value.strip())
        os.environ.setdefault(env_key, env_value)


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    service_name: str
    service_version: str
    environment: str
    log_level: str
    host: str
    port: int
    ingest_enabled: bool
    camera_source_mode: str
    camera_source_url: str | None
    ingest_reconnect_backoff_seconds: float
    esp32_frame_path: str
    esp32_request_timeout_seconds: float
    esp32_poll_interval_seconds: float
    simulated_fps: float
    simulated_disconnect_after_seconds: float
    simulated_disconnect_duration_seconds: float
    landmark_enabled: bool
    landmark_mode: str
    landmark_queue_maxsize: int
    landmark_recent_results_limit: int
    mock_landmark_detection_rate: float
    gemini_api_key: str | None

    @property
    def camera_source_configured(self) -> bool:
        if self.camera_source_mode == "simulated":
            return True
        return bool(self.camera_source_url)

    @property
    def gemini_key_configured(self) -> bool:
        return bool(self.gemini_api_key)

    def redacted(self) -> dict[str, str | int | bool | None]:
        return {
            "service_name": self.service_name,
            "service_version": self.service_version,
            "environment": self.environment,
            "log_level": self.log_level,
            "host": self.host,
            "port": self.port,
            "ingest_enabled": self.ingest_enabled,
            "camera_source_mode": self.camera_source_mode,
            "camera_source_configured": self.camera_source_configured,
            "ingest_reconnect_backoff_seconds": self.ingest_reconnect_backoff_seconds,
            "esp32_frame_path": self.esp32_frame_path,
            "esp32_request_timeout_seconds": self.esp32_request_timeout_seconds,
            "esp32_poll_interval_seconds": self.esp32_poll_interval_seconds,
            "simulated_fps": self.simulated_fps,
            "simulated_disconnect_after_seconds": self.simulated_disconnect_after_seconds,
            "simulated_disconnect_duration_seconds": self.simulated_disconnect_duration_seconds,
            "landmark_enabled": self.landmark_enabled,
            "landmark_mode": self.landmark_mode,
            "landmark_queue_maxsize": self.landmark_queue_maxsize,
            "landmark_recent_results_limit": self.landmark_recent_results_limit,
            "mock_landmark_detection_rate": self.mock_landmark_detection_rate,
            "gemini_key_configured": self.gemini_key_configured,
        }


def build_settings(project_root: Path) -> Settings:
    load_env_file(project_root / ".env")

    return Settings(
        service_name=os.getenv("BACKEND_SERVICE_NAME", "utg-backend"),
        service_version=os.getenv("BACKEND_SERVICE_VERSION", "0.1.0-phase1"),
        environment=os.getenv("BACKEND_ENV", "development"),
        log_level=os.getenv("BACKEND_LOG_LEVEL", "INFO").upper(),
        host=os.getenv("BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        ingest_enabled=_env_bool("INGEST_ENABLED", True),
        camera_source_mode=os.getenv("CAMERA_SOURCE_MODE", "simulated").strip().lower(),
        camera_source_url=os.getenv("CAMERA_SOURCE_URL"),
        ingest_reconnect_backoff_seconds=float(
            os.getenv("INGEST_RECONNECT_BACKOFF_SECONDS", "1.0")
        ),
        esp32_frame_path=os.getenv("ESP32_FRAME_PATH", "/frame").strip() or "/frame",
        esp32_request_timeout_seconds=float(
            os.getenv("ESP32_REQUEST_TIMEOUT_SECONDS", "2.0")
        ),
        esp32_poll_interval_seconds=float(
            os.getenv("ESP32_POLL_INTERVAL_SECONDS", "0.08")
        ),
        simulated_fps=float(os.getenv("SIMULATED_SOURCE_FPS", "12.0")),
        simulated_disconnect_after_seconds=float(
            os.getenv("SIMULATED_DISCONNECT_AFTER_SECONDS", "-1.0")
        ),
        simulated_disconnect_duration_seconds=float(
            os.getenv("SIMULATED_DISCONNECT_DURATION_SECONDS", "10.0")
        ),
        landmark_enabled=_env_bool("LANDMARK_ENABLED", True),
        landmark_mode=os.getenv("LANDMARK_MODE", "mock").strip().lower(),
        landmark_queue_maxsize=int(os.getenv("LANDMARK_QUEUE_MAXSIZE", "256")),
        landmark_recent_results_limit=int(os.getenv("LANDMARK_RECENT_RESULTS_LIMIT", "50")),
        mock_landmark_detection_rate=float(os.getenv("MOCK_LANDMARK_DETECTION_RATE", "0.85")),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
    )
