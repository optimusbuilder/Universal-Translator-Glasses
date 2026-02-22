from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/translations", tags=["translations"])


@router.get("/status")
def get_translation_status(request: Request) -> dict[str, Any]:
    translation_pipeline = request.app.state.translation_pipeline
    return translation_pipeline.snapshot()


@router.get("/recent")
def get_recent_translations(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    translation_pipeline = request.app.state.translation_pipeline
    results = translation_pipeline.recent_results(limit=limit)
    return {"results": results, "count": len(results)}

