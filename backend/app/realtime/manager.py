from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable

from fastapi import WebSocket

from backend.app.settings import Settings
from backend.app.translation.types import TranslationResult


@dataclass
class RealtimeMetrics:
    started_at: str | None = None
    running: bool = False
    healthy: bool = False
    connected_clients: int = 0
    total_clients_seen: int = 0
    events_emitted: int = 0
    events_dropped: int = 0
    last_event_at: str | None = None
    last_error: str | None = None
    by_type: dict[str, int] = field(default_factory=dict)


@dataclass
class _ClientSession:
    client_id: int
    websocket: WebSocket
    queue: asyncio.Queue[dict[str, Any]]
    sender_task: asyncio.Task[None] | None = None


class RealtimeEventManager:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger
        self._metrics = RealtimeMetrics()
        self._clients: dict[int, _ClientSession] = {}
        self._recent_events: deque[dict[str, Any]] = deque(
            maxlen=max(1, settings.realtime_recent_events_limit)
        )
        self._event_type_counts: defaultdict[str, int] = defaultdict(int)
        self._client_id_counter = 0
        self._stopping = False
        self._lock = asyncio.Lock()
        self._monitor_task: asyncio.Task[None] | None = None
        self._metrics_provider: Callable[[], dict[str, Any]] | None = None
        self._last_alert_at: dict[str, float] = {}

    def set_metrics_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        self._metrics_provider = provider

    async def start(self) -> None:
        if not self._settings.realtime_enabled:
            self._logger.info(
                "realtime_disabled",
                extra={
                    "event": "realtime_disabled",
                    "service_name": self._settings.service_name,
                    "service_version": self._settings.service_version,
                },
            )
            return

        if self._monitor_task is not None and not self._monitor_task.done():
            return

        self._stopping = False
        async with self._lock:
            self._metrics.started_at = datetime.now(timezone.utc).isoformat()
            self._metrics.running = True
            self._metrics.healthy = True
            self._metrics.last_error = None

        self._monitor_task = asyncio.create_task(
            self._monitor_loop(),
            name="realtime-monitor-loop",
        )

    async def stop(self) -> None:
        self._stopping = True

        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            finally:
                self._monitor_task = None

        for client_id in list(self._clients.keys()):
            await self.disconnect(client_id)

        async with self._lock:
            self._metrics.running = False
            self._metrics.healthy = False
            self._metrics.connected_clients = 0

    async def connect(self, websocket: WebSocket) -> int | None:
        if not self._settings.realtime_enabled:
            await websocket.close(code=1013)
            return None

        await websocket.accept()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=max(1, self._settings.realtime_client_queue_maxsize)
        )

        self._client_id_counter += 1
        client_id = self._client_id_counter
        session = _ClientSession(
            client_id=client_id,
            websocket=websocket,
            queue=queue,
        )

        async with self._lock:
            self._clients[client_id] = session
            self._metrics.connected_clients = len(self._clients)
            self._metrics.total_clients_seen += 1

        session.sender_task = asyncio.create_task(
            self._sender_loop(session),
            name=f"realtime-client-sender-{client_id}",
        )
        return client_id

    async def disconnect(self, client_id: int) -> None:
        session: _ClientSession | None = None
        async with self._lock:
            session = self._clients.pop(client_id, None)
            self._metrics.connected_clients = len(self._clients)

        if session is None:
            return

        if session.sender_task is not None and session.sender_task is not asyncio.current_task():
            session.sender_task.cancel()
            try:
                await session.sender_task
            except asyncio.CancelledError:
                pass

        try:
            await session.websocket.close()
        except Exception:
            pass

    async def publish_translation_result(self, result: TranslationResult) -> None:
        event_type = "caption.final" if result.kind == "final" else "caption.partial"
        await self.publish(event_type=event_type, payload=result.to_dict())

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self._settings.realtime_enabled:
            return

        event = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        self._recent_events.append(event)

        async with self._lock:
            self._event_type_counts[event_type] += 1
            self._metrics.events_emitted += 1
            self._metrics.last_event_at = event["timestamp"]
            self._metrics.by_type = dict(self._event_type_counts)
            clients = list(self._clients.values())

        for client in clients:
            if client.queue.full():
                try:
                    client.queue.get_nowait()
                    client.queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                async with self._lock:
                    self._metrics.events_dropped += 1

            try:
                client.queue.put_nowait(event)
            except asyncio.QueueFull:
                async with self._lock:
                    self._metrics.events_dropped += 1

    def snapshot(self) -> dict[str, Any]:
        payload = asdict(self._metrics)
        payload["realtime_enabled"] = self._settings.realtime_enabled
        payload["running"] = bool(self._monitor_task is not None and not self._monitor_task.done())
        payload["recent_events_count"] = len(self._recent_events)
        payload["connected_client_ids"] = list(self._clients.keys())
        return payload

    def recent_events(self, limit: int = 20) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 200))
        return list(self._recent_events)[-bounded:][::-1]

    async def _sender_loop(self, session: _ClientSession) -> None:
        while not self._stopping:
            has_item = False
            try:
                event = await session.queue.get()
                has_item = True
                await session.websocket.send_json(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                async with self._lock:
                    self._metrics.last_error = str(exc)
                    self._metrics.healthy = False
                break
            finally:
                if has_item:
                    session.queue.task_done()

        await self.disconnect(session.client_id)

    async def _monitor_loop(self) -> None:
        interval = max(0.1, self._settings.realtime_metrics_interval_seconds)
        while not self._stopping:
            await asyncio.sleep(interval)
            if self._metrics_provider is None:
                continue

            try:
                metrics_payload = self._metrics_provider()
                await self.publish(event_type="system.metrics", payload=metrics_payload)

                for alert in self._build_alerts(metrics_payload):
                    now = monotonic()
                    key = alert["key"]
                    last_alert = self._last_alert_at.get(key, 0.0)
                    if now - last_alert < self._settings.realtime_alert_cooldown_seconds:
                        continue
                    self._last_alert_at[key] = now
                    alert_payload = dict(alert)
                    alert_payload.pop("key", None)
                    await self.publish(event_type="system.alert", payload=alert_payload)

                async with self._lock:
                    self._metrics.healthy = True
                    self._metrics.last_error = None
            except Exception as exc:  # pragma: no cover - safety net
                async with self._lock:
                    self._metrics.healthy = False
                    self._metrics.last_error = str(exc)

    def _build_alerts(self, metrics_payload: dict[str, Any]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        components = (
            ("ingest", "ingest_enabled"),
            ("landmark", "landmark_enabled"),
            ("windowing", "windowing_enabled"),
            ("translation", "translation_enabled"),
        )

        for component, enabled_key in components:
            snapshot = metrics_payload.get(component) or {}
            enabled = bool(snapshot.get(enabled_key, True))
            running = bool(snapshot.get("running", False))
            healthy = bool(snapshot.get("healthy", True))
            if enabled and running and not healthy:
                alerts.append(
                    {
                        "key": f"{component}:unhealthy",
                        "severity": "warning",
                        "component": component,
                        "reason": snapshot.get("last_error") or "component_unhealthy",
                    }
                )

        return alerts
