# Backend Setup (Phase 1 + Phase 2A)

This backend currently implements:

1. Phase 1: service skeleton, lifecycle hooks, structured logging, `/health`.
2. Phase 2A: source-agnostic ingest manager with simulated camera source, reconnect logic, and ingest metrics.

## Implemented Endpoints

1. `GET /health`: service health + ingest health summary.
2. `GET /ingest/status`: ingest metrics snapshot.

## Backend Files

1. `backend/app/main.py`: FastAPI app, lifespan, ingest manager start/stop.
2. `backend/app/settings.py`: `.env` loading and runtime config.
3. `backend/app/logging_config.py`: structured JSON logs.
4. `backend/app/routes/health.py`: health endpoint.
5. `backend/app/routes/ingest.py`: ingest status endpoint.
6. `backend/app/ingest/manager.py`: reconnecting ingest loop and metrics.
7. `backend/app/ingest/sources/base.py`: source contract.
8. `backend/app/ingest/sources/simulated.py`: synthetic source for pre-hardware testing.

## Tests

1. `backend/tests/test_phase1_boot.py`: Phase 1 completion test.
2. `backend/tests/test_phase2a_source_ingest.py`: Phase 2A soak/reconnect test.
3. `backend/tests/test_phase2a_ingest_api.py`: ingest API contract test.

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

## Relevant Environment Variables

1. `INGEST_ENABLED` (default `true`)
2. `CAMERA_SOURCE_MODE` (default `simulated`)
3. `INGEST_RECONNECT_BACKOFF_SECONDS` (default `1.0`)
4. `SIMULATED_SOURCE_FPS` (default `12.0`)
5. `SIMULATED_DISCONNECT_AFTER_SECONDS` (default `-1.0`, disabled)
6. `SIMULATED_DISCONNECT_DURATION_SECONDS` (default `10.0`)
7. `GEMINI_API_KEY` (already set in your `.env`)

## Notes

1. Phase 2A intentionally does not depend on ESP32 hardware.
2. ESP32 binding happens in Phase 2B by swapping source adapter while preserving ingest manager behavior.
