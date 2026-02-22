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


def _resolve_project_path(project_root: Path, raw_path: str | None) -> str | None:
    if raw_path is None:
        return None
    candidate = Path(raw_path.strip()).expanduser()
    if not raw_path.strip():
        return None
    if candidate.is_absolute():
        return str(candidate)
    return str((project_root / candidate).resolve())


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_mode(
    key: str,
    default: str,
    allowed: tuple[str, ...],
) -> str:
    value = os.getenv(key, default).strip().lower()
    if value not in allowed:
        allowed_csv = ", ".join(allowed)
        raise ValueError(f"{key} must be one of: {allowed_csv}")
    return value


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
    opencv_source: str
    opencv_poll_interval_seconds: float
    opencv_width: int
    opencv_height: int
    opencv_jpeg_quality: int
    ingest_reconnect_backoff_seconds: float
    esp32_frame_path: str
    esp32_request_timeout_seconds: float
    esp32_poll_interval_seconds: float
    landmark_enabled: bool
    landmark_mode: str
    mediapipe_hand_model_path: str | None
    landmark_queue_maxsize: int
    landmark_recent_results_limit: int
    windowing_enabled: bool
    window_duration_seconds: float
    window_slide_seconds: float
    window_queue_maxsize: int
    window_recent_results_limit: int
    translation_enabled: bool
    translation_mode: str
    translation_queue_maxsize: int
    translation_recent_results_limit: int
    translation_timeout_seconds: float
    translation_max_retries: int
    translation_retry_backoff_seconds: float
    translation_uncertainty_threshold: float
    translation_min_frames_with_hands: int
    translation_emit_unclear_captions: bool
    local_classifier_model_path: str
    local_classifier_min_confidence: float
    local_classifier_min_votes: int
    local_classifier_label_allowlist: str | None
    gemini_model: str
    gemini_api_base_url: str
    gemini_api_key: str | None
    realtime_enabled: bool = True
    realtime_client_queue_maxsize: int = 128
    realtime_recent_events_limit: int = 200
    realtime_metrics_interval_seconds: float = 1.0
    realtime_alert_cooldown_seconds: float = 3.0
    realtime_translation_latency_alert_ms: float = 2500.0
    realtime_queue_depth_alert_threshold: int = 32
    landmark_adaptive_frame_skip_enabled: bool = True
    landmark_adaptive_skip_threshold: float = 0.75
    translation_window_max_frames: int = 10
    translation_hand_confidence_threshold: float = 0.65
    translation_output_max_tokens: int = 24
    translation_temperature: float = 0.0
    translation_min_request_interval_seconds: float = 1.0
    translation_rate_limit_cooldown_seconds: float = 8.0

    @property
    def camera_source_configured(self) -> bool:
        if self.camera_source_mode == "esp32_http":
            return bool(self.camera_source_url)
        if self.camera_source_mode == "opencv_capture":
            return bool(self.opencv_source.strip())
        return False

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
            "opencv_source": self.opencv_source,
            "opencv_poll_interval_seconds": self.opencv_poll_interval_seconds,
            "opencv_width": self.opencv_width,
            "opencv_height": self.opencv_height,
            "opencv_jpeg_quality": self.opencv_jpeg_quality,
            "ingest_reconnect_backoff_seconds": self.ingest_reconnect_backoff_seconds,
            "esp32_frame_path": self.esp32_frame_path,
            "esp32_request_timeout_seconds": self.esp32_request_timeout_seconds,
            "esp32_poll_interval_seconds": self.esp32_poll_interval_seconds,
            "landmark_enabled": self.landmark_enabled,
            "landmark_mode": self.landmark_mode,
            "mediapipe_hand_model_path_configured": bool(self.mediapipe_hand_model_path),
            "landmark_queue_maxsize": self.landmark_queue_maxsize,
            "landmark_recent_results_limit": self.landmark_recent_results_limit,
            "windowing_enabled": self.windowing_enabled,
            "window_duration_seconds": self.window_duration_seconds,
            "window_slide_seconds": self.window_slide_seconds,
            "window_queue_maxsize": self.window_queue_maxsize,
            "window_recent_results_limit": self.window_recent_results_limit,
            "translation_enabled": self.translation_enabled,
            "translation_mode": self.translation_mode,
            "translation_queue_maxsize": self.translation_queue_maxsize,
            "translation_recent_results_limit": self.translation_recent_results_limit,
            "translation_timeout_seconds": self.translation_timeout_seconds,
            "translation_max_retries": self.translation_max_retries,
            "translation_retry_backoff_seconds": self.translation_retry_backoff_seconds,
            "translation_uncertainty_threshold": self.translation_uncertainty_threshold,
            "translation_min_frames_with_hands": self.translation_min_frames_with_hands,
            "translation_emit_unclear_captions": self.translation_emit_unclear_captions,
            "local_classifier_model_path": self.local_classifier_model_path,
            "local_classifier_min_confidence": self.local_classifier_min_confidence,
            "local_classifier_min_votes": self.local_classifier_min_votes,
            "local_classifier_label_allowlist": bool(
                (self.local_classifier_label_allowlist or "").strip()
            ),
            "gemini_model": self.gemini_model,
            "gemini_api_base_url": self.gemini_api_base_url,
            "gemini_key_configured": self.gemini_key_configured,
            "realtime_enabled": self.realtime_enabled,
            "realtime_client_queue_maxsize": self.realtime_client_queue_maxsize,
            "realtime_recent_events_limit": self.realtime_recent_events_limit,
            "realtime_metrics_interval_seconds": self.realtime_metrics_interval_seconds,
            "realtime_alert_cooldown_seconds": self.realtime_alert_cooldown_seconds,
            "realtime_translation_latency_alert_ms": self.realtime_translation_latency_alert_ms,
            "realtime_queue_depth_alert_threshold": self.realtime_queue_depth_alert_threshold,
            "landmark_adaptive_frame_skip_enabled": self.landmark_adaptive_frame_skip_enabled,
            "landmark_adaptive_skip_threshold": self.landmark_adaptive_skip_threshold,
            "translation_window_max_frames": self.translation_window_max_frames,
            "translation_hand_confidence_threshold": self.translation_hand_confidence_threshold,
            "translation_output_max_tokens": self.translation_output_max_tokens,
            "translation_temperature": self.translation_temperature,
            "translation_min_request_interval_seconds": self.translation_min_request_interval_seconds,
            "translation_rate_limit_cooldown_seconds": self.translation_rate_limit_cooldown_seconds,
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
        camera_source_mode=_env_mode(
            "CAMERA_SOURCE_MODE",
            "esp32_http",
            ("esp32_http", "opencv_capture"),
        ),
        camera_source_url=os.getenv("CAMERA_SOURCE_URL"),
        opencv_source=os.getenv("OPENCV_SOURCE", "0").strip(),
        opencv_poll_interval_seconds=float(
            os.getenv("OPENCV_POLL_INTERVAL_SECONDS", "0.08")
        ),
        opencv_width=int(os.getenv("OPENCV_WIDTH", "640")),
        opencv_height=int(os.getenv("OPENCV_HEIGHT", "480")),
        opencv_jpeg_quality=int(os.getenv("OPENCV_JPEG_QUALITY", "85")),
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
        landmark_enabled=_env_bool("LANDMARK_ENABLED", True),
        landmark_mode=_env_mode("LANDMARK_MODE", "mediapipe", ("mediapipe",)),
        mediapipe_hand_model_path=_resolve_project_path(
            project_root,
            os.getenv("MEDIAPIPE_HAND_MODEL_PATH"),
        ),
        landmark_queue_maxsize=int(os.getenv("LANDMARK_QUEUE_MAXSIZE", "256")),
        landmark_recent_results_limit=int(os.getenv("LANDMARK_RECENT_RESULTS_LIMIT", "50")),
        windowing_enabled=_env_bool("WINDOWING_ENABLED", True),
        window_duration_seconds=float(os.getenv("WINDOW_DURATION_SECONDS", "1.5")),
        window_slide_seconds=float(os.getenv("WINDOW_SLIDE_SECONDS", "0.5")),
        window_queue_maxsize=int(os.getenv("WINDOW_QUEUE_MAXSIZE", "128")),
        window_recent_results_limit=int(os.getenv("WINDOW_RECENT_RESULTS_LIMIT", "40")),
        translation_enabled=_env_bool("TRANSLATION_ENABLED", True),
        translation_mode=_env_mode(
            "TRANSLATION_MODE",
            "gemini",
            ("gemini", "local_classifier"),
        ),
        translation_queue_maxsize=int(os.getenv("TRANSLATION_QUEUE_MAXSIZE", "128")),
        translation_recent_results_limit=int(
            os.getenv("TRANSLATION_RECENT_RESULTS_LIMIT", "80")
        ),
        translation_timeout_seconds=float(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "4.0")),
        translation_max_retries=int(os.getenv("TRANSLATION_MAX_RETRIES", "2")),
        translation_retry_backoff_seconds=float(
            os.getenv("TRANSLATION_RETRY_BACKOFF_SECONDS", "0.25")
        ),
        translation_uncertainty_threshold=float(
            os.getenv("TRANSLATION_UNCERTAINTY_THRESHOLD", "0.6")
        ),
        translation_min_frames_with_hands=int(
            os.getenv("TRANSLATION_MIN_FRAMES_WITH_HANDS", "1")
        ),
        translation_emit_unclear_captions=_env_bool(
            "TRANSLATION_EMIT_UNCLEAR_CAPTIONS",
            False,
        ),
        local_classifier_model_path=_resolve_project_path(
            project_root,
            os.getenv(
                "LOCAL_CLASSIFIER_MODEL_PATH",
                "backend/models/asl_landmark_classifier_v1.npz",
            ),
        ),
        local_classifier_min_confidence=float(
            os.getenv("LOCAL_CLASSIFIER_MIN_CONFIDENCE", "0.55")
        ),
        local_classifier_min_votes=int(os.getenv("LOCAL_CLASSIFIER_MIN_VOTES", "2")),
        local_classifier_label_allowlist=os.getenv("LOCAL_CLASSIFIER_LABEL_ALLOWLIST"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_api_base_url=os.getenv(
            "GEMINI_API_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        ),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        realtime_enabled=_env_bool("REALTIME_ENABLED", True),
        realtime_client_queue_maxsize=int(
            os.getenv("REALTIME_CLIENT_QUEUE_MAXSIZE", "128")
        ),
        realtime_recent_events_limit=int(os.getenv("REALTIME_RECENT_EVENTS_LIMIT", "200")),
        realtime_metrics_interval_seconds=float(
            os.getenv("REALTIME_METRICS_INTERVAL_SECONDS", "1.0")
        ),
        realtime_alert_cooldown_seconds=float(
            os.getenv("REALTIME_ALERT_COOLDOWN_SECONDS", "3.0")
        ),
        realtime_translation_latency_alert_ms=float(
            os.getenv("REALTIME_TRANSLATION_LATENCY_ALERT_MS", "2500.0")
        ),
        realtime_queue_depth_alert_threshold=int(
            os.getenv("REALTIME_QUEUE_DEPTH_ALERT_THRESHOLD", "32")
        ),
        landmark_adaptive_frame_skip_enabled=_env_bool(
            "LANDMARK_ADAPTIVE_FRAME_SKIP_ENABLED", True
        ),
        landmark_adaptive_skip_threshold=float(
            os.getenv("LANDMARK_ADAPTIVE_SKIP_THRESHOLD", "0.75")
        ),
        translation_window_max_frames=int(
            os.getenv("TRANSLATION_WINDOW_MAX_FRAMES", "10")
        ),
        translation_hand_confidence_threshold=float(
            os.getenv("TRANSLATION_HAND_CONFIDENCE_THRESHOLD", "0.65")
        ),
        translation_output_max_tokens=int(
            os.getenv("TRANSLATION_OUTPUT_MAX_TOKENS", "24")
        ),
        translation_temperature=float(
            os.getenv("TRANSLATION_TEMPERATURE", "0.0")
        ),
        translation_min_request_interval_seconds=float(
            os.getenv("TRANSLATION_MIN_REQUEST_INTERVAL_SECONDS", "1.0")
        ),
        translation_rate_limit_cooldown_seconds=float(
            os.getenv("TRANSLATION_RATE_LIMIT_COOLDOWN_SECONDS", "8.0")
        ),
    )
