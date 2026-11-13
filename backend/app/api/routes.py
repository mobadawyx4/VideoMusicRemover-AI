"""API endpoints for SilentTrack AI."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.schemas import (
    HealthResponse,
    JobResponse,
    ProcessOptions,
    RemixRequest,
    UrlImportRequest,
)
from app.core.security import resolve_job_dir, sanitize_filename, verify_job_token
from app.services.demo_service import generate_sample_video
from app.services.job_manager import job_manager
from app.services.media_service import MediaProcessingError, check_ffmpeg_installed
from app.services.separation import separator_service
from app.services.url_service import import_video_from_url

router = APIRouter(prefix="/api", tags=["SilentTrack AI"])

CHUNK_SIZE = 1024 * 1024  # 1 MB streaming chunks


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return system, FFmpeg, and AI model health status."""
    ffmpeg_ok, ffprobe_ok = check_ffmpeg_installed()
    return HealthResponse(
        status="ok" if (ffmpeg_ok and ffprobe_ok) else "degraded",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        ffmpeg_available=ffmpeg_ok,
        ffprobe_available=ffprobe_ok,
        ai_model_name=f"{settings.MODEL_REPO_ID} (Speech / Effects / Music)",
        ai_model_ready=separator_service.is_model_available(),
        device=separator_service.device,
        max_upload_size_mb=settings.MAX_UPLOAD_SIZE_MB,
        max_video_duration_sec=settings.MAX_VIDEO_DURATION_SEC,
        allowed_extensions=sorted(settings.ALLOWED_EXTENSIONS),
    )


@router.post(
    "/jobs/upload",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_video(file: UploadFile = File(...)) -> JobResponse:
    """Stream-upload a video file, validate format/size/duration, and initialize a job."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is missing from upload.",
        )

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        allowed_str = ", ".join(sorted(settings.ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported video format '{ext}'. Supported formats: {allowed_str}",
        )

    settings.ensure_dirs()
    temp_path = settings.JOBS_DIR / f"upload_{uuid.uuid4().hex}{ext}"
    bytes_written = 0
    max_bytes = settings.max_upload_size_bytes

    try:
        async with aiofiles.open(temp_path, "wb") as out_file:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            f"Uploaded file exceeds maximum allowed size of "
                            f"{settings.MAX_UPLOAD_SIZE_MB} MB."
                        ),
                    )
                await out_file.write(chunk)
    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded video: {exc}",
        ) from exc
    finally:
        await file.close()

    if bytes_written == 0:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )

    try:
        job = job_manager.create_job(
            uploaded_temp_path=temp_path, original_filename=file.filename
        )
        return job
    except MediaProcessingError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/jobs/demo",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_demo_job() -> JobResponse:
    """Generate a real 4-second sample video containing speech, environmental sounds, and music."""
    settings.ensure_dirs()
    temp_path = settings.JOBS_DIR / f"demo_{uuid.uuid4().hex}.mp4"
    try:
        generate_sample_video(temp_path, duration_sec=4.0)
        return job_manager.create_job(
            uploaded_temp_path=temp_path,
            original_filename="sample_interview_with_music.mp4",
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create sample video: {exc}",
        ) from exc


@router.post(
    "/jobs/from-url",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_job_from_url(req: UrlImportRequest) -> JobResponse:
    """Download video from YouTube, social platforms, or direct HTTP/HTTPS link and initialize a job."""
    return await asyncio.to_thread(import_video_from_url, req.url)


@router.post("/jobs/{job_id}/process", response_model=JobResponse)
async def process_video(
    job_id: str,
    options: Optional[ProcessOptions] = None,
    token: Optional[str] = Query(default=None),
) -> JobResponse:
    """Start AI background music removal for an uploaded video job."""
    proc_opts = options or ProcessOptions()
    return job_manager.start_processing(job_id=job_id, options=proc_opts, token=token)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    token: Optional[str] = Query(default=None),
) -> JobResponse:
    """Retrieve the current status, progress, metrics, and media URLs of a job."""
    return job_manager.get_job(job_id=job_id, token=token, require_token=False)


@router.post("/jobs/{job_id}/remix", response_model=JobResponse)
async def remix_job_audio(
    job_id: str,
    remix_req: RemixRequest,
    token: Optional[str] = Query(default=None),
) -> JobResponse:
    """Instantly remix separated stems with adjusted music removal strength or stem gains."""
    return job_manager.remix_completed_job(
        job_id=job_id, remix_req=remix_req, token=token
    )


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    token: Optional[str] = Query(default=None),
) -> dict[str, str]:
    """Delete a job and clean up its temporary files immediately."""
    job_manager.delete_job(job_id=job_id, token=token)
    return {"status": "deleted", "job_id": job_id}


MEDIA_KIND_MAP = {
    "original_video": ("input_video.*", "video/mp4", "original"),
    "processed_video": ("processed_video.mp4", "video/mp4", "silenttrack_clean"),
    "original_audio": ("original_audio.wav", "audio/wav", "original_audio"),
    "processed_audio": ("processed_audio.wav", "audio/wav", "clean_audio"),
    "speech_stem": ("speech_stem.wav", "audio/wav", "speech_stem"),
    "effects_stem": ("effects_stem.wav", "audio/wav", "environmental_stem"),
    "music_stem": ("music_stem.wav", "audio/wav", "removed_music_stem"),
}


@router.get("/jobs/{job_id}/media/{media_kind}")
async def get_job_media(
    job_id: str,
    media_kind: str,
    token: Optional[str] = Query(default=None),
    download: bool = Query(default=False),
) -> FileResponse:
    """Stream or download video/audio assets for a specific job."""
    if media_kind not in MEDIA_KIND_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown media type '{media_kind}'.",
        )

    job = job_manager.get_job(job_id=job_id, token=token, require_token=True)
    job_dir = resolve_job_dir(job_id, must_exist=True)

    pattern, default_mime, suffix_label = MEDIA_KIND_MAP[media_kind]
    if "*" in pattern:
        matches = list(job_dir.glob(pattern))
        if not matches:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Requested media file not found.",
            )
        file_path = matches[0]
    else:
        file_path = job_dir / pattern

    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media asset '{media_kind}' is not ready yet.",
        )

    ext = file_path.suffix.lower()
    mime_map = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
        ".wav": "audio/wav",
    }
    media_type = mime_map.get(ext, default_mime)

    orig_stem = Path(job.metadata.filename).stem if job.metadata else "video"
    safe_stem = sanitize_filename(f"{orig_stem}.mp4").rsplit(".", 1)[0]
    download_name = f"{safe_stem}_{suffix_label}{ext}"

    headers = {"Cache-Control": "no-cache"}
    if download:
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=download_name,
            headers=headers,
        )
    return FileResponse(
        path=file_path,
        media_type=media_type,
        headers=headers,
    )
