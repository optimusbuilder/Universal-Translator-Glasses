from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/landmarks", tags=["landmarks"])


@router.get("/status")
def get_landmark_status(request: Request) -> dict[str, Any]:
    landmark_pipeline = request.app.state.landmark_pipeline
    return landmark_pipeline.snapshot()


@router.get("/recent")
def get_recent_landmarks(
    request: Request,
    limit: int = Query(default=5, ge=1, le=100),
) -> dict[str, Any]:
    landmark_pipeline = request.app.state.landmark_pipeline
    results = landmark_pipeline.recent_results(limit=limit)
    return {"results": results, "count": len(results)}

