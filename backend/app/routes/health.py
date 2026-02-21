from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    started_at = request.app.state.started_at
    ingest_manager = request.app.state.ingest_manager
    landmark_pipeline = request.app.state.landmark_pipeline
    ingest_snapshot = ingest_manager.snapshot()
    landmark_snapshot = landmark_pipeline.snapshot()
    now = datetime.now(timezone.utc)
    uptime_seconds = max(0.0, (now - started_at).total_seconds())

    return {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.service_version,
        "environment": settings.environment,
        "started_at": started_at.isoformat(),
        "uptime_seconds": round(uptime_seconds, 3),
        "checks": {
            "camera_source_configured": settings.camera_source_configured,
            "gemini_key_configured": settings.gemini_key_configured,
            "ingest_enabled": ingest_snapshot["ingest_enabled"],
            "ingest_running": ingest_snapshot["running"],
            "ingest_connected": ingest_snapshot["connected"],
            "ingest_healthy": ingest_snapshot["healthy"],
            "landmark_enabled": landmark_snapshot["landmark_enabled"],
            "landmark_running": landmark_snapshot["running"],
            "landmark_healthy": landmark_snapshot["healthy"],
        },
    }
