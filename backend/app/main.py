"""Main FastAPI application entry point for SilentTrack AI."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.core.config import settings
from app.services.job_manager import job_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("silenttrack")


async def _periodic_cleanup_loop() -> None:
    """Background task to automatically delete expired job directories."""
    while True:
        try:
            await asyncio.sleep(settings.CLEANUP_INTERVAL_SECONDS)
            removed = job_manager.cleanup_expired_jobs()
            if removed > 0:
                logger.info("Automatically cleaned up %d expired temporary jobs.", removed)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Cleanup loop error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    cleanup_task = asyncio.create_task(_periodic_cleanup_loop())
    logger.info(
        "%s v%s started (FFmpeg=%s, ModelsDir=%s)",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.FFMPEG_PATH,
        settings.MODELS_DIR,
    )
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "AI-powered Video Background Music Remover that preserves human speech, "
        "dialogue, and natural environmental sounds using TIGER-DnR source separation."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/api/health",
    }
