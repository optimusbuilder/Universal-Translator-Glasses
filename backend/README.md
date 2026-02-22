# Backend Setup (Phase 1 + Phase 2A + Phase 2B Dry-Run + Phase 3 + Phase 4 + Phase 5 + Phase 6)

This backend currently implements:

1. Phase 1: service skeleton, lifecycle hooks, structured logging, `/health`.
2. Phase 2A: source-agnostic ingest manager with simulated camera source, reconnect logic, and ingest metrics.
3. Phase 2B dry-run: ESP32 HTTP adapter with mock-driven validation (no hardware required).
4. Phase 3: landmark extraction pipeline with queueing, mock extractor, and status endpoints.
5. Phase 4: temporal windowing pipeline over landmark results with window status endpoints.
6. Phase 5: translation orchestration over windows with retry/timeout policy and partial/final outputs.
7. Phase 6: realtime WebSocket broadcast layer for caption and system events.

## Implemented Endpoints

1. `GET /health`: service health + ingest health summary.
2. `GET /ingest/status`: ingest metrics snapshot.
3. `GET /landmarks/status`: landmark pipeline metrics snapshot.
4. `GET /landmarks/recent?limit=<n>`: recent landmark extraction payloads.
5. `GET /windows/status`: windowing pipeline metrics snapshot.
6. `GET /windows/recent?limit=<n>`: recent emitted landmark windows.
7. `GET /translations/status`: translation pipeline metrics snapshot.
8. `GET /translations/recent?limit=<n>`: recent partial/final translation results.
9. `GET /realtime/status`: realtime manager status snapshot.
10. `GET /realtime/recent?limit=<n>`: recent emitted websocket event envelopes.
11. `WS /ws/events`: live event stream for `caption.partial`, `caption.final`, `system.metrics`, `system.alert`.

## Backend Files

1. `backend/app/main.py`: FastAPI app, lifespan, ingest manager start/stop.
2. `backend/app/settings.py`: `.env` loading and runtime config.
3. `backend/app/logging_config.py`: structured JSON logs.
4. `backend/app/routes/health.py`: health endpoint.
5. `backend/app/routes/ingest.py`: ingest status endpoint.
6. `backend/app/ingest/manager.py`: reconnecting ingest loop and metrics.
7. `backend/app/ingest/sources/base.py`: source contract.
8. `backend/app/ingest/sources/simulated.py`: synthetic source for pre-hardware testing.
9. `backend/app/ingest/sources/esp32_http.py`: ESP32 HTTP source adapter.
10. `backend/mock/esp32_mock_app.py`: optional FastAPI mock ESP32 frame server.
11. `backend/app/landmarks/pipeline.py`: frame-to-landmark processing pipeline.
12. `backend/app/landmarks/types.py`: landmark result schema.
13. `backend/app/landmarks/extractors/mock.py`: deterministic mock hand landmark extractor.
14. `backend/app/landmarks/extractors/mediapipe.py`: mediapipe-mode placeholder extractor.
15. `backend/app/routes/landmarks.py`: landmark status/result endpoints.
16. `backend/app/windowing/pipeline.py`: landmark-sequence window builder.
17. `backend/app/windowing/types.py`: window schema.
18. `backend/app/routes/windows.py`: window status/result endpoints.
19. `backend/app/translation/pipeline.py`: translation queue, retry policy, and result emission.
20. `backend/app/translation/types.py`: translation result schema.
21. `backend/app/translation/providers/mock.py`: mock translation provider.
22. `backend/app/translation/providers/gemini.py`: Gemini translation provider.
23. `backend/app/routes/translations.py`: translation status/result endpoints.
24. `backend/app/realtime/manager.py`: websocket connection manager and system event monitor.
25. `backend/app/routes/realtime.py`: websocket endpoint and realtime status/recent endpoints.

## Tests

1. `backend/tests/test_phase1_boot.py`: Phase 1 completion test.
2. `backend/tests/test_phase2a_source_ingest.py`: Phase 2A soak/reconnect test.
3. `backend/tests/test_phase2a_ingest_api.py`: ingest API contract test.
4. `backend/tests/test_phase2b_esp32_source_mock.py`: ESP32 source adapter contract test.
5. `backend/tests/test_phase2b_ingest_dry_run.py`: Phase 2B dry-run soak test (mock transport).
6. `backend/tests/test_phase3_landmark_quality.py`: Phase 3 landmark quality test.
7. `backend/tests/test_phase3_landmark_api.py`: Phase 3 API contract test.
8. `backend/tests/test_phase4_window_integrity.py`: Phase 4 window integrity test.
9. `backend/tests/test_phase4_window_api.py`: Phase 4 API contract test.
10. `backend/tests/test_phase5_translation_contract.py`: Phase 5 translation contract test.
11. `backend/tests/test_phase5_translation_api.py`: Phase 5 translation API contract test.
12. `backend/tests/test_phase6_websocket_delivery.py`: Phase 6 websocket delivery completion test.
13. `backend/tests/test_phase6_realtime_api.py`: Phase 6 realtime API contract test.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

## Run Backend

```bash
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Phase 1 Completion Test (`P1-Backend-Boot-Test`)

Default run:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase1_boot
```

Shorter local run:

```bash
PHASE1_HEALTH_DURATION_SECONDS=10 PHASE1_RESTART_HEALTH_DURATION_SECONDS=3 PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase1_boot
```

## Phase 2A Completion Test (`P2A-Source-Ingest-Soak-Test`)

Default run (simulated source with forced disconnect and reconnect):

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase2a_source_ingest
```

Optional custom duration:

```bash
PHASE2A_SOAK_DURATION_SECONDS=12 PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase2a_source_ingest
```

## Phase 2A API Contract Test

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase2a_ingest_api
```

## Phase 2B Dry-Run Tests

Adapter contract test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase2b_esp32_source_mock
```

Ingest manager dry-run soak test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase2b_ingest_dry_run
```

## Phase 3 Tests (`P3-Landmark-Quality-Test`)

Landmark quality test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase3_landmark_quality
```

Landmark API contract test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase3_landmark_api
```

## Phase 4 Tests (`P4-Window-Integrity-Test`)

Window integrity test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase4_window_integrity
```

Window API contract test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase4_window_api
```

## Phase 5 Tests (`P5-Translation-Contract-Test`)

Translation contract test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase5_translation_contract
```

Translation API contract test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase5_translation_api
```

## Phase 6 Tests (`P6-WebSocket-Delivery-Test`)

WebSocket delivery completion test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase6_websocket_delivery
```

Realtime API contract test:

```bash
PYTHONPATH=. .venv/bin/python -m unittest backend.tests.test_phase6_realtime_api
```

## Optional Manual ESP32 Mock Server

Run a local mock ESP32 frame server:

```bash
.venv/bin/uvicorn backend.mock.esp32_mock_app:app --host 127.0.0.1 --port 8090
```

Then point ingest at it:

```bash
CAMERA_SOURCE_MODE=esp32_http CAMERA_SOURCE_URL=http://127.0.0.1:8090 ESP32_FRAME_PATH=/frame .venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Relevant Environment Variables

1. `INGEST_ENABLED` (default `true`)
2. `CAMERA_SOURCE_MODE` (default `simulated`)
3. `CAMERA_SOURCE_URL` (required for `esp32_http` mode)
4. `INGEST_RECONNECT_BACKOFF_SECONDS` (default `1.0`)
5. `SIMULATED_SOURCE_FPS` (default `12.0`)
6. `SIMULATED_DISCONNECT_AFTER_SECONDS` (default `-1.0`, disabled)
7. `SIMULATED_DISCONNECT_DURATION_SECONDS` (default `10.0`)
8. `ESP32_FRAME_PATH` (default `/frame`)
9. `ESP32_REQUEST_TIMEOUT_SECONDS` (default `2.0`)
10. `ESP32_POLL_INTERVAL_SECONDS` (default `0.08`)
11. `GEMINI_API_KEY` (already set in your `.env`)
12. `LANDMARK_ENABLED` (default `true`)
13. `LANDMARK_MODE` (default `mock`)
14. `LANDMARK_QUEUE_MAXSIZE` (default `256`)
15. `LANDMARK_RECENT_RESULTS_LIMIT` (default `50`)
16. `MOCK_LANDMARK_DETECTION_RATE` (default `0.85`)
17. `WINDOWING_ENABLED` (default `true`)
18. `WINDOW_DURATION_SECONDS` (default `1.5`)
19. `WINDOW_SLIDE_SECONDS` (default `0.5`)
20. `WINDOW_QUEUE_MAXSIZE` (default `128`)
21. `WINDOW_RECENT_RESULTS_LIMIT` (default `40`)
22. `TRANSLATION_ENABLED` (default `true`)
23. `TRANSLATION_MODE` (default `mock`)
24. `TRANSLATION_QUEUE_MAXSIZE` (default `128`)
25. `TRANSLATION_RECENT_RESULTS_LIMIT` (default `80`)
26. `TRANSLATION_TIMEOUT_SECONDS` (default `4.0`)
27. `TRANSLATION_MAX_RETRIES` (default `2`)
28. `TRANSLATION_RETRY_BACKOFF_SECONDS` (default `0.25`)
29. `TRANSLATION_UNCERTAINTY_THRESHOLD` (default `0.6`)
30. `GEMINI_MODEL` (default `gemini-1.5-flash`)
31. `GEMINI_API_BASE_URL` (default `https://generativelanguage.googleapis.com/v1beta`)
32. `REALTIME_ENABLED` (default `true`)
33. `REALTIME_CLIENT_QUEUE_MAXSIZE` (default `128`)
34. `REALTIME_RECENT_EVENTS_LIMIT` (default `200`)
35. `REALTIME_METRICS_INTERVAL_SECONDS` (default `1.0`)
36. `REALTIME_ALERT_COOLDOWN_SECONDS` (default `3.0`)

## Notes

1. Phase 2A intentionally does not depend on ESP32 hardware.
2. Phase 2B dry-run is available now via mock tests; final Phase 2B sign-off still requires real hardware.
3. Current Phase 3 runs use `LANDMARK_MODE=mock` until MediaPipe integration is turned on.
4. Phase 4 windows currently feed inspection endpoints and are ready for Phase 5 translation integration.
5. For Phase 5, keep `TRANSLATION_MODE=mock` for local validation; switch to `gemini` for real model calls.
6. Phase 6 now publishes realtime websocket events from translation output and periodic health snapshots.
