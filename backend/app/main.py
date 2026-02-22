from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.ingest.manager import IngestManager
from backend.app.landmarks.pipeline import LandmarkPipeline
from backend.app.logging_config import configure_logging
from backend.app.routes.health import router as health_router
from backend.app.routes.ingest import router as ingest_router
from backend.app.routes.landmarks import router as landmarks_router
from backend.app.routes.realtime import router as realtime_router
from backend.app.routes.translations import router as translations_router
from backend.app.routes.windows import router as windows_router
from backend.app.realtime.manager import RealtimeEventManager
from backend.app.settings import build_settings
from backend.app.translation.pipeline import TranslationPipeline
from backend.app.windowing.pipeline import WindowingPipeline


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _service_logger() -> logging.Logger:
    return logging.getLogger("utg.backend")


def create_app() -> FastAPI:
    settings = build_settings(_project_root())
    configure_logging(settings.log_level)
    logger = _service_logger()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.started_at = datetime.now(timezone.utc)
        app.state.realtime_manager = RealtimeEventManager(settings=settings, logger=logger)
        app.state.translation_pipeline = TranslationPipeline(settings=settings, logger=logger)
        app.state.translation_pipeline.register_result_handler(
            app.state.realtime_manager.publish_translation_result
        )
        app.state.windowing_pipeline = WindowingPipeline(settings=settings, logger=logger)
        app.state.windowing_pipeline.register_window_handler(
            app.state.translation_pipeline.enqueue_window
        )
        app.state.landmark_pipeline = LandmarkPipeline(settings=settings, logger=logger)
        app.state.landmark_pipeline.register_result_handler(
            app.state.windowing_pipeline.enqueue_landmark_result
        )
        app.state.ingest_manager = IngestManager(settings=settings, logger=logger)
        app.state.ingest_manager.register_frame_handler(
            app.state.landmark_pipeline.enqueue_frame
        )

        def _system_metrics() -> dict[str, object]:
            return {
                "service": settings.service_name,
                "version": settings.service_version,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "ingest": app.state.ingest_manager.snapshot(),
                "landmark": app.state.landmark_pipeline.snapshot(),
                "windowing": app.state.windowing_pipeline.snapshot(),
                "translation": app.state.translation_pipeline.snapshot(),
                "realtime": app.state.realtime_manager.snapshot(),
            }

        app.state.realtime_manager.set_metrics_provider(_system_metrics)

        logger.info(
            "service_startup",
            extra={
                "event": "startup",
                "service_name": settings.service_name,
                "service_version": settings.service_version,
            },
        )
        logger.info(
            "service_config_loaded",
            extra={
                "event": "config_loaded",
                "service_name": settings.service_name,
                "service_version": settings.service_version,
                "config": settings.redacted(),
            },
        )
        await app.state.realtime_manager.start()
        await app.state.translation_pipeline.start()
        await app.state.windowing_pipeline.start()
        await app.state.landmark_pipeline.start()
        await app.state.ingest_manager.start()
        yield
        await app.state.ingest_manager.stop()
        await app.state.landmark_pipeline.stop()
        await app.state.windowing_pipeline.stop()
        await app.state.translation_pipeline.stop()
        await app.state.realtime_manager.stop()
        logger.info(
            "service_shutdown",
            extra={
                "event": "shutdown",
                "service_name": settings.service_name,
                "service_version": settings.service_version,
            },
        )

    app = FastAPI(
        title=settings.service_name,
        version=settings.service_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root() -> dict[str, str]:
        return {"message": "Universal Translator Glasses backend is running."}

    app.include_router(health_router)
    app.include_router(ingest_router)
    app.include_router(landmarks_router)
    app.include_router(windows_router)
    app.include_router(translations_router)
    app.include_router(realtime_router)
    return app


app = create_app()
