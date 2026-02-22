from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/windows", tags=["windows"])


@router.get("/status")
def get_window_status(request: Request) -> dict[str, Any]:
    windowing_pipeline = request.app.state.windowing_pipeline
    return windowing_pipeline.snapshot()


@router.get("/recent")
def get_recent_windows(
    request: Request,
    limit: int = Query(default=5, ge=1, le=100),
) -> dict[str, Any]:
    windowing_pipeline = request.app.state.windowing_pipeline
    windows = windowing_pipeline.recent_windows(limit=limit)
    return {"results": windows, "count": len(windows)}

