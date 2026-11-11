"""Job lifecycle, background processing pipeline, and automatic temporary file cleanup."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status

from app.core.config import settings
from app.core.schemas import (
    JobResponse,
    JobStatus,
    ProcessOptions,
    RemixRequest,
    VideoMetadata,
    WaveformData,
)
from app.core.security import (
    generate_job_id,
    generate_job_token,
    resolve_job_dir,
    sanitize_filename,
    verify_job_token,
)
from app.services.media_service import (
    MediaProcessingError,
    compute_rms_db,
    compute_waveform_peaks,
    extract_audio_from_video,
    inspect_video,
    load_wav,
    mux_audio_with_video,
)
from app.services.separation import SeparationError, separator_service

logger = logging.getLogger(__name__)


class JobManager:
    """Thread-safe manager for video music removal jobs and temporary storage cleanup."""

    def __init__(self, max_workers: int = 2) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, JobResponse] = {}
        self._tokens: dict[str, str] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="silenttrack-worker"
        )
        self._load_existing_jobs()

    def _load_existing_jobs(self) -> None:
        """Restore non-expired job states from disk on startup."""
        settings.ensure_dirs()
        now = time.time()
        for entry in settings.JOBS_DIR.iterdir():
            if not entry.is_dir():
                continue
            state_file = entry / "job_state.json"
            if not state_file.is_file():
                continue
            try:
                raw = json.loads(state_file.read_text(encoding="utf-8"))
                job = JobResponse.model_validate(raw.get("job", raw))
                token = raw.get("token") or job.access_token or ""
                if job.expires_at < now:
                    shutil.rmtree(entry, ignore_errors=True)
                    continue
                self._jobs[job.job_id] = job
                self._tokens[job.job_id] = token
            except Exception as exc:
                logger.warning("Skipping unreadable job state in %s: %s", entry, exc)

    def _persist_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            token = self._tokens.get(job_id, "")
            if not job:
                return
            try:
                job_dir = resolve_job_dir(job_id, must_exist=False)
                if not job_dir.is_dir():
                    return
                state_path = job_dir / "job_state.json"
                payload = {
                    "token": token,
                    "job": job.model_dump(mode="json"),
                }
                state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning("Failed to persist state for job %s: %s", job_id, exc)

    def create_job(self, uploaded_temp_path: Path, original_filename: str) -> JobResponse:
        """Create a new isolated job directory, validate video with FFprobe, and store metadata."""
        job_id = generate_job_id()
        token = generate_job_token()
        safe_name = sanitize_filename(original_filename)
        ext = Path(safe_name).suffix.lower()

        job_dir = resolve_job_dir(job_id, must_exist=False)
        job_dir.mkdir(parents=True, exist_ok=True)

        input_video_path = job_dir / f"input_video{ext}"
        try:
            shutil.move(str(uploaded_temp_path), str(input_video_path))
            metadata: VideoMetadata = inspect_video(
                input_video_path, original_filename=safe_name
            )
            if not metadata.has_audio:
                raise MediaProcessingError(
                    "This video does not contain an audio track to process."
                )
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

        now = time.time()
        job = JobResponse(
            job_id=job_id,
            access_token=token,
            status=JobStatus.UPLOADED,
            progress=0.0,
            stage_message="Video uploaded and validated. Ready to remove background music.",
            created_at=now,
            updated_at=now,
            expires_at=now + settings.JOB_TTL_SECONDS,
            metadata=metadata,
            options=ProcessOptions(
                music_removal_strength=settings.DEFAULT_MUSIC_REMOVAL_STRENGTH,
                speech_gain=settings.DEFAULT_SPEECH_GAIN,
                effects_gain=settings.DEFAULT_EFFECTS_GAIN,
            ),
            original_video_url=f"/api/jobs/{job_id}/media/original_video?token={token}",
        )

        with self._lock:
            self._jobs[job_id] = job
            self._tokens[job_id] = token
            self._persist_job(job_id)

        return job

    def get_job(
        self, job_id: str, token: Optional[str] = None, require_token: bool = False
    ) -> JobResponse:
        """Retrieve job state, enforcing job isolation."""
        resolve_job_dir(job_id, must_exist=True)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job '{job_id}' not found.",
                )
            expected_token = self._tokens.get(job_id)
            if require_token and not verify_job_token(expected_token, token):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or missing job access token.",
                )
            return job.model_copy(deep=True)

    def get_job_token(self, job_id: str) -> Optional[str]:
        with self._lock:
            return self._tokens.get(job_id)

    def _update_job(
        self,
        job_id: str,
        *,
        status_val: Optional[JobStatus] = None,
        progress: Optional[float] = None,
        stage_message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if status_val is not None:
                job.status = status_val
            if progress is not None:
                job.progress = round(min(100.0, max(0.0, progress)), 1)
            if stage_message is not None:
                job.stage_message = stage_message
            if error is not None:
                job.error = error
            job.updated_at = time.time()
            job.expires_at = time.time() + settings.JOB_TTL_SECONDS
            self._persist_job(job_id)

    def start_processing(
        self,
        job_id: str,
        options: ProcessOptions,
        token: Optional[str] = None,
    ) -> JobResponse:
        """Queue and start background AI audio separation and video rendering."""
        job_dir = resolve_job_dir(job_id, must_exist=True)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job '{job_id}' not found.",
                )
            if token and not verify_job_token(self._tokens.get(job_id), token):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid job access token.",
                )
            if job.status in (
                JobStatus.QUEUED,
                JobStatus.EXTRACTING_AUDIO,
                JobStatus.SEPARATING_STEMS,
                JobStatus.RECONSTRUCTING_AUDIO,
                JobStatus.RENDERING_VIDEO,
            ):
                return job.model_copy(deep=True)

            job.options = options
            job.error = None
            job.status = JobStatus.QUEUED
            job.progress = 2.0
            job.stage_message = "Job queued for AI audio separation..."
            job.updated_at = time.time()
            self._persist_job(job_id)
            snapshot = job.model_copy(deep=True)

        self._executor.submit(self._run_pipeline, job_id, job_dir, options)
        return snapshot

    def _find_input_video(self, job_dir: Path) -> Path:
        for ext in settings.ALLOWED_EXTENSIONS:
            candidate = job_dir / f"input_video{ext}"
            if candidate.is_file():
                return candidate
        matches = list(job_dir.glob("input_video.*"))
        if matches:
            return matches[0]
        raise MediaProcessingError("Original uploaded video file was not found in job directory.")

    def _run_pipeline(
        self, job_id: str, job_dir: Path, options: ProcessOptions
    ) -> None:
        """Full background workflow: Extract Audio -> AI Separation -> Reconstruct -> Render Video."""
        try:
            input_video = self._find_input_video(job_dir)
            original_wav = job_dir / "original_audio.wav"

            # Step 3: Extract original audio using FFmpeg
            self._update_job(
                job_id,
                status_val=JobStatus.EXTRACTING_AUDIO,
                progress=6.0,
                stage_message="Extracting high-resolution audio stream from video with FFmpeg...",
            )
            extract_audio_from_video(
                input_video,
                original_wav,
                target_sr=44100,
                channels=2,
            )

            # Step 4 & 5: Run AI audio source separation (Speech, Environmental SFX, Music)
            self._update_job(
                job_id,
                status_val=JobStatus.SEPARATING_STEMS,
                progress=15.0,
                stage_message="Running TIGER-DnR neural separation (Dialogue, Environment, Music)...",
            )

            def _sep_progress(p: float, msg: str) -> None:
                mapped = 15.0 + (p / 100.0) * 65.0  # maps 0..100 -> 15..80
                self._update_job(
                    job_id,
                    status_val=JobStatus.SEPARATING_STEMS,
                    progress=mapped,
                    stage_message=msg,
                )

            stem_paths, metrics = separator_service.separate_audio_file(
                input_wav_path=original_wav,
                output_dir=job_dir,
                options=options,
                progress_callback=_sep_progress,
            )

            # Step 6: Compute waveform envelopes for before/after visual comparison
            self._update_job(
                job_id,
                status_val=JobStatus.RECONSTRUCTING_AUDIO,
                progress=83.0,
                stage_message="Analyzing before/after audio waveforms and stem energy...",
            )
            orig_audio, _ = load_wav(original_wav)
            proc_audio, _ = load_wav(stem_paths["processed"])
            speech_audio, _ = load_wav(stem_paths["speech"])
            effects_audio, _ = load_wav(stem_paths["effects"])
            music_audio, _ = load_wav(stem_paths["music"])

            waveform = WaveformData(
                original_peaks=compute_waveform_peaks(orig_audio, num_bins=140),
                processed_peaks=compute_waveform_peaks(proc_audio, num_bins=140),
                speech_peaks=compute_waveform_peaks(speech_audio, num_bins=140),
                effects_peaks=compute_waveform_peaks(effects_audio, num_bins=140),
                music_peaks=compute_waveform_peaks(music_audio, num_bins=140),
            )

            # Step 7 & 8: Synchronize processed audio with original video and export via FFmpeg
            self._update_job(
                job_id,
                status_val=JobStatus.RENDERING_VIDEO,
                progress=90.0,
                stage_message="Synchronizing clean audio with original video stream (lossless video copy)...",
            )
            output_video = job_dir / "processed_video.mp4"
            mux_audio_with_video(
                original_video_path=input_video,
                processed_audio_path=stem_paths["processed"],
                output_video_path=output_video,
            )

            with self._lock:
                job = self._jobs.get(job_id)
                token = self._tokens.get(job_id, "")
                if job:
                    job.status = JobStatus.COMPLETED
                    job.progress = 100.0
                    job.stage_message = "Background music removed! Speech and environmental audio preserved."
                    job.metrics = metrics
                    job.waveform = waveform
                    job.original_video_url = f"/api/jobs/{job_id}/media/original_video?token={token}"
                    job.processed_video_url = f"/api/jobs/{job_id}/media/processed_video?token={token}"
                    job.original_audio_url = f"/api/jobs/{job_id}/media/original_audio?token={token}"
                    job.processed_audio_url = f"/api/jobs/{job_id}/media/processed_audio?token={token}"
                    job.speech_stem_url = f"/api/jobs/{job_id}/media/speech_stem?token={token}"
                    job.effects_stem_url = f"/api/jobs/{job_id}/media/effects_stem?token={token}"
                    job.music_stem_url = f"/api/jobs/{job_id}/media/music_stem?token={token}"
                    job.updated_at = time.time()
                    job.expires_at = time.time() + settings.JOB_TTL_SECONDS
                    self._persist_job(job_id)

        except (MediaProcessingError, SeparationError) as exc:
            logger.error("Job %s failed: %s", job_id, exc)
            self._update_job(
                job_id,
                status_val=JobStatus.FAILED,
                stage_message="Processing failed.",
                error=str(exc),
            )
        except Exception as exc:
            logger.exception("Unexpected error in job %s", job_id)
            self._update_job(
                job_id,
                status_val=JobStatus.FAILED,
                stage_message="Unexpected processing error.",
                error=f"Internal processing error: {exc}",
            )

    def remix_completed_job(
        self,
        job_id: str,
        remix_req: RemixRequest,
        token: Optional[str] = None,
    ) -> JobResponse:
        """Instantly remix separated stems with new music removal strength / gains and re-mux video."""
        job_dir = resolve_job_dir(job_id, must_exist=True)
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Job '{job_id}' not found.",
                )
            if token and not verify_job_token(self._tokens.get(job_id), token):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid job access token.",
                )

        try:
            processed_wav = separator_service.remix_existing_stems(
                job_dir=job_dir,
                music_removal_strength=remix_req.music_removal_strength,
                speech_gain=remix_req.speech_gain,
                effects_gain=remix_req.effects_gain,
            )
            input_video = self._find_input_video(job_dir)
            output_video = job_dir / "processed_video.mp4"
            mux_audio_with_video(
                original_video_path=input_video,
                processed_audio_path=processed_wav,
                output_video_path=output_video,
            )

            proc_audio, _ = load_wav(processed_wav)
            proc_rms = compute_rms_db(proc_audio)
            proc_peaks = compute_waveform_peaks(proc_audio, num_bins=140)
            residual_factor = max(1e-3, 1.0 - remix_req.music_removal_strength)
            suppression_db = round(min(45.0, abs(20.0 * float(__import__("math").log10(residual_factor)))), 1)

            with self._lock:
                job = self._jobs[job_id]
                job.options.music_removal_strength = remix_req.music_removal_strength
                job.options.speech_gain = remix_req.speech_gain
                job.options.effects_gain = remix_req.effects_gain
                if job.metrics:
                    job.metrics.processed_rms_db = proc_rms
                    job.metrics.music_suppression_db = suppression_db
                if job.waveform:
                    job.waveform.processed_peaks = proc_peaks
                job.updated_at = time.time()
                job.stage_message = (
                    f"Remixed audio ({int(remix_req.music_removal_strength * 100)}% music removed) "
                    "and updated video."
                )
                self._persist_job(job_id)
                return job.model_copy(deep=True)
        except (SeparationError, MediaProcessingError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    def delete_job(self, job_id: str, token: Optional[str] = None) -> bool:
        """Delete a job and all its temporary files immediately."""
        job_dir = resolve_job_dir(job_id, must_exist=False)
        with self._lock:
            if token and job_id in self._tokens:
                if not verify_job_token(self._tokens.get(job_id), token):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Invalid job access token.",
                    )
            self._jobs.pop(job_id, None)
            self._tokens.pop(job_id, None)

        if job_dir.is_dir():
            shutil.rmtree(job_dir, ignore_errors=True)
            return True
        return False

    def cleanup_expired_jobs(self) -> int:
        """Delete temporary directories and job records that have exceeded JOB_TTL_SECONDS."""
        now = time.time()
        removed = 0
        with self._lock:
            expired_ids = [
                jid for jid, job in self._jobs.items() if job.expires_at < now
            ]
            for jid in expired_ids:
                self._jobs.pop(jid, None)
                self._tokens.pop(jid, None)
                job_dir = settings.JOBS_DIR / jid
                if job_dir.is_dir():
                    shutil.rmtree(job_dir, ignore_errors=True)
                removed += 1

        # Also clean up any orphaned directories on disk older than JOB_TTL_SECONDS
        if settings.JOBS_DIR.is_dir():
            for entry in settings.JOBS_DIR.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name not in self._jobs:
                    try:
                        age = now - entry.stat().st_mtime
                        if age > settings.JOB_TTL_SECONDS:
                            shutil.rmtree(entry, ignore_errors=True)
                            removed += 1
                    except Exception:
                        pass
        return removed


job_manager = JobManager()
