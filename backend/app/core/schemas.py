"""Pydantic data models for SilentTrack AI API."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    EXTRACTING_AUDIO = "extracting_audio"
    SEPARATING_STEMS = "separating_stems"
    RECONSTRUCTING_AUDIO = "reconstructing_audio"
    RENDERING_VIDEO = "rendering_video"
    COMPLETED = "completed"
    FAILED = "failed"


class SeparationMode(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    HIGH_QUALITY = "high_quality"


class VideoMetadata(BaseModel):
    filename: str
    file_size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float
    aspect_ratio: str
    video_codec: str
    audio_codec: Optional[str] = None
    audio_sample_rate: Optional[int] = None
    audio_channels: Optional[int] = None
    has_audio: bool = True
    container_format: str


class StemMetrics(BaseModel):
    speech_rms_db: float = Field(description="RMS energy of separated speech stem in dBFS")
    effects_rms_db: float = Field(description="RMS energy of separated environmental effects stem in dBFS")
    music_rms_db: float = Field(description="RMS energy of separated background music stem in dBFS")
    original_rms_db: float = Field(description="RMS energy of original audio track in dBFS")
    processed_rms_db: float = Field(description="RMS energy of final music-removed audio in dBFS")
    music_suppression_db: float = Field(description="Estimated music energy reduction in dB")
    processing_time_seconds: float = Field(description="Total AI separation and rendering time in seconds")
    model_used: str = Field(default="TIGER-DnR (Speech + Effects + Music)")
    device_used: str = Field(default="cpu")


class ProcessOptions(BaseModel):
    music_removal_strength: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="0.0 keeps 100% of background music, 1.0 removes 100% of detected background music",
    )
    speech_gain: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Multiplier for human speech / dialogue stem (default 1.0)",
    )
    effects_gain: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Multiplier for natural environmental sounds & SFX stem (default 1.0)",
    )
    separation_mode: SeparationMode = Field(
        default=SeparationMode.BALANCED,
        description="AI separation mode: fast (single-pass), balanced (overlap chunking), high_quality (multi-pass ensemble)",
    )


class RemixRequest(BaseModel):
    music_removal_strength: float = Field(default=1.0, ge=0.0, le=1.0)
    speech_gain: float = Field(default=1.0, ge=0.0, le=2.0)
    effects_gain: float = Field(default=1.0, ge=0.0, le=2.0)


class UrlImportRequest(BaseModel):
    url: str = Field(
        ...,
        min_length=1,
        description="Public HTTP or HTTPS video URL to download and process",
    )


class WaveformData(BaseModel):
    original_peaks: list[float] = Field(default_factory=list)
    processed_peaks: list[float] = Field(default_factory=list)
    speech_peaks: list[float] = Field(default_factory=list)
    music_peaks: list[float] = Field(default_factory=list)
    effects_peaks: list[float] = Field(default_factory=list)


class JobResponse(BaseModel):
    job_id: str
    access_token: Optional[str] = None
    status: JobStatus
    progress: float = Field(ge=0.0, le=100.0, default=0.0)
    stage_message: str = ""
    created_at: float
    updated_at: float
    expires_at: float
    metadata: Optional[VideoMetadata] = None
    options: ProcessOptions = Field(default_factory=ProcessOptions)
    metrics: Optional[StemMetrics] = None
    waveform: Optional[WaveformData] = None
    error: Optional[str] = None
    original_video_url: Optional[str] = None
    processed_video_url: Optional[str] = None
    original_audio_url: Optional[str] = None
    processed_audio_url: Optional[str] = None
    speech_stem_url: Optional[str] = None
    effects_stem_url: Optional[str] = None
    music_stem_url: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    app_name: str
    version: str
    ffmpeg_available: bool
    ffprobe_available: bool
    ai_model_name: str
    ai_model_ready: bool
    device: str
    max_upload_size_mb: int
    max_video_duration_sec: int
    allowed_extensions: list[str]
