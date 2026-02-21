from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/status")
def get_ingest_status(request: Request) -> dict[str, Any]:
    ingest_manager = request.app.state.ingest_manager
    return ingest_manager.snapshot()

