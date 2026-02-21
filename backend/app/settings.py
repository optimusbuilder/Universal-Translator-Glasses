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


@dataclass(frozen=True)
class Settings:
    service_name: str
    service_version: str
    environment: str
    log_level: str
    host: str
    port: int
    camera_source_url: str | None
    gemini_api_key: str | None

    @property
    def camera_source_configured(self) -> bool:
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
            "camera_source_configured": self.camera_source_configured,
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
        camera_source_url=os.getenv("CAMERA_SOURCE_URL"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
    )

