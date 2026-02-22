from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["realtime"])


@router.get("/realtime/status")
def get_realtime_status(request: Request) -> dict[str, Any]:
    realtime_manager = request.app.state.realtime_manager
    return realtime_manager.snapshot()


@router.get("/realtime/recent")
def get_recent_realtime_events(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    realtime_manager = request.app.state.realtime_manager
    results = realtime_manager.recent_events(limit=limit)
    return {"results": results, "count": len(results)}


@router.websocket("/ws/events")
async def events_websocket(websocket: WebSocket) -> None:
    realtime_manager = websocket.app.state.realtime_manager
    client_id = await realtime_manager.connect(websocket)
    if client_id is None:
        return

    try:
        while True:
            await websocket.receive()
    except WebSocketDisconnect:
        pass
    finally:
        await realtime_manager.disconnect(client_id)
