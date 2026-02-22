from __future__ import annotations

import httpx
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

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


class TtsRequest(BaseModel):
    text: str


@router.post("/tts")
async def synthesize_translation_audio(
    request: Request,
    body: TtsRequest,
) -> Response:
    settings = request.app.state.settings
    api_key = (settings.elevenlabs_api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="ELEVENLABS_API_KEY not configured")

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if len(text) > 400:
        raise HTTPException(status_code=400, detail="text too long (max 400 chars)")

    lowered = text.lower()
    if lowered in {"[unclear]", "unclear"}:
        raise HTTPException(status_code=400, detail="cannot synthesize unclear caption")

    voice_id = settings.elevenlabs_voice_id.strip()
    model_id = settings.elevenlabs_model_id.strip()
    endpoint = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": model_id,
    }
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    timeout = httpx.Timeout(20.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream = await client.post(endpoint, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"elevenlabs_request_error:{exc}") from exc

    if upstream.status_code >= 400:
        detail = f"elevenlabs_http_{upstream.status_code}"
        try:
            error_payload = upstream.json()
            message = str(error_payload.get("detail") or error_payload.get("message") or "").strip()
            if message:
                detail = f"{detail}:{message}"
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail)

    return Response(
        content=upstream.content,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )
