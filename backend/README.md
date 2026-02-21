# Backend Phase 1 Setup

This backend uses FastAPI and implements Phase 1 from `BACKEND_README.md`:

1. Service skeleton.
2. Environment loading from `.env`.
3. Structured JSON logging.
4. Lifecycle startup/shutdown hooks.
5. `/health` endpoint.

## Files

1. `backend/app/main.py`: app entrypoint and lifecycle hooks.
2. `backend/app/settings.py`: `.env` loading and settings model.
3. `backend/app/logging_config.py`: structured logging formatter.
4. `backend/app/routes/health.py`: health route.
5. `backend/tests/test_phase1_boot.py`: Phase 1 completion test.

## Install

Use a virtual environment and install dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

## Run Backend

```bash
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Run Phase 1 Completion Test

Default test behavior:

1. Runs health checks for 60 seconds.
2. Restarts service context once.
3. Verifies startup/shutdown logs and service version metadata.

```bash
.venv/bin/python -m unittest backend.tests.test_phase1_boot
```

Optional shorter local run:

```bash
PHASE1_HEALTH_DURATION_SECONDS=10 PHASE1_RESTART_HEALTH_DURATION_SECONDS=3 .venv/bin/python -m unittest backend.tests.test_phase1_boot
```

