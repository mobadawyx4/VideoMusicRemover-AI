"""FFmpeg and FFprobe video/audio processing utilities for VideoMusicRemover AI."""

from __future__ import annotations

import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from app.core.config import settings
from app.core.schemas import VideoMetadata


class MediaProcessingError(Exception):
    """Raised when video validation, audio extraction, or video rendering fails."""


def check_ffmpeg_installed() -> tuple[bool, bool]:
    """Return (ffmpeg_ok, ffprobe_ok) booleans."""
    ffmpeg_ok = False
    ffprobe_ok = False
    try:
        res = subprocess.run(
            [settings.FFMPEG_PATH, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        ffmpeg_ok = res.returncode == 0
    except Exception:
        ffmpeg_ok = False

    try:
        res = subprocess.run(
            [settings.FFPROBE_PATH, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        ffprobe_ok = res.returncode == 0
    except Exception:
        ffprobe_ok = False

    return ffmpeg_ok, ffprobe_ok


def _parse_frame_rate(rate_str: str) -> float:
    """Parse ffprobe frame rate fraction like '30000/1001' into float."""
    if not rate_str or rate_str == "0/0":
        return 0.0
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return 0.0
            return round(float(num) / den_f, 3)
        return round(float(rate_str), 3)
    except Exception:
        return 0.0


def _compute_aspect_ratio(width: int, height: int, dar: Optional[str]) -> str:
    if dar and dar not in ("0:1", "N/A"):
        return dar
    if width <= 0 or height <= 0:
        return "16:9"
    frac = Fraction(width, height).limit_denominator(32)
    return f"{frac.numerator}:{frac.denominator}"


def inspect_video(video_path: Path, original_filename: Optional[str] = None) -> VideoMetadata:
    """Inspect a video file with ffprobe and validate streams, format, and duration."""
    if not video_path.is_file():
        raise MediaProcessingError("Uploaded video file does not exist on disk.")

    file_size = video_path.stat().st_size
    if file_size == 0:
        raise MediaProcessingError("Uploaded video file is empty (0 bytes).")

    if file_size > settings.max_upload_size_bytes:
        raise MediaProcessingError(
            f"Video file size ({file_size / (1024 * 1024):.1f} MB) exceeds the "
            f"maximum limit of {settings.MAX_UPLOAD_SIZE_MB} MB."
        )

    cmd = [
        settings.FFPROBE_PATH,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessingError("Timed out while inspecting video metadata.") from exc
    except FileNotFoundError as exc:
        raise MediaProcessingError(
            f"FFprobe binary not found at '{settings.FFPROBE_PATH}'."
        ) from exc

    if result.returncode != 0 or not result.stdout.strip():
        raise MediaProcessingError(
            "Invalid or corrupted video file: FFprobe could not read container metadata."
        )

    try:
        probe_data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProcessingError("Failed to parse video metadata output.") from exc

    streams = probe_data.get("streams", [])
    fmt = probe_data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video_stream:
        raise MediaProcessingError(
            "The uploaded file does not contain a valid video stream."
        )

    duration = float(
        fmt.get("duration")
        or video_stream.get("duration")
        or (audio_stream.get("duration") if audio_stream else 0.0)
        or 0.0
    )
    if duration <= 0.05:
        raise MediaProcessingError(
            "Video duration could not be determined or is too short to process."
        )

    if duration > settings.MAX_VIDEO_DURATION_SEC:
        raise MediaProcessingError(
            f"Video duration ({duration:.1f}s) exceeds maximum allowed duration "
            f"of {settings.MAX_VIDEO_DURATION_SEC}s."
        )

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    fps = _parse_frame_rate(
        video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "30/1"
    )
    if fps <= 0:
        fps = _parse_frame_rate(video_stream.get("r_frame_rate") or "30/1") or 30.0

    aspect_ratio = _compute_aspect_ratio(
        width, height, video_stream.get("display_aspect_ratio")
    )
    video_codec = str(video_stream.get("codec_name") or "unknown")
    container_format = str(fmt.get("format_name") or video_path.suffix.lstrip("."))

    has_audio = audio_stream is not None
    audio_codec = str(audio_stream.get("codec_name")) if audio_stream else None
    audio_sr = int(audio_stream.get("sample_rate") or 44100) if audio_stream else None
    audio_ch = int(audio_stream.get("channels") or 2) if audio_stream else None

    return VideoMetadata(
        filename=original_filename or video_path.name,
        file_size_bytes=file_size,
        duration_seconds=round(duration, 3),
        width=width,
        height=height,
        fps=fps,
        aspect_ratio=aspect_ratio,
        video_codec=video_codec,
        audio_codec=audio_codec,
        audio_sample_rate=audio_sr,
        audio_channels=audio_ch,
        has_audio=has_audio,
        container_format=container_format,
    )


def extract_audio_from_video(
    video_path: Path,
    output_wav_path: Path,
    target_sr: int = 44100,
    channels: int = 2,
) -> Path:
    """Extract audio from a video file into uncompressed PCM WAV at target_sr."""
    output_wav_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        settings.FFMPEG_PATH,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(target_sr),
        "-ac",
        str(max(1, min(channels, 2))),
        str(output_wav_path),
    ]

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessingError("Timed out while extracting audio from video.") from exc

    if res.returncode != 0 or not output_wav_path.is_file() or output_wav_path.stat().st_size == 0:
        err_tail = (res.stderr or "")[-400:].strip()
        raise MediaProcessingError(
            f"FFmpeg failed to extract audio from video. Details: {err_tail}"
        )

    return output_wav_path


def mux_audio_with_video(
    original_video_path: Path,
    processed_audio_path: Path,
    output_video_path: Path,
    progress_callback: Optional[Callable[[float], None]] = None,
) -> Path:
    """Combine processed audio with original video stream while preserving resolution, FPS, and aspect ratio.

    Attempts lossless video stream copy (`-c:v copy`) first so video quality, resolution,
    frame rate, and aspect ratio are 100% preserved without re-encoding artifacts.
    Falls back to high-quality H.264 (`libx264 -crf 18 -preset veryfast`) if the input video
    codec is incompatible with the MP4 container (e.g. VP8/VP9 from WebM).
    """
    output_video_path.parent.mkdir(parents=True, exist_ok=True)
    if progress_callback:
        progress_callback(10.0)

    # First attempt: stream copy video + high-bitrate AAC audio
    copy_cmd = [
        settings.FFMPEG_PATH,
        "-y",
        "-i",
        str(original_video_path),
        "-i",
        str(processed_audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_video_path),
    ]

    res = subprocess.run(
        copy_cmd,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    if res.returncode == 0 and output_video_path.is_file() and output_video_path.stat().st_size > 0:
        if progress_callback:
            progress_callback(100.0)
        return output_video_path

    # Fallback for codecs like VP8/VP9/AV1 when muxing into .mp4: re-encode video preserving exact geometry & FPS
    fallback_cmd = [
        settings.FFMPEG_PATH,
        "-y",
        "-i",
        str(original_video_path),
        "-i",
        str(processed_audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_video_path),
    ]

    res_fb = subprocess.run(
        fallback_cmd,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )

    if res_fb.returncode != 0 or not output_video_path.is_file() or output_video_path.stat().st_size == 0:
        err_tail = (res_fb.stderr or "")[-400:].strip()
        raise MediaProcessingError(
            f"FFmpeg failed to render final video. Details: {err_tail}"
        )

    if progress_callback:
        progress_callback(100.0)
    return output_video_path


def compute_rms_db(audio: np.ndarray) -> float:
    """Compute RMS level in dBFS for an audio signal."""
    if audio.size == 0:
        return -100.0
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    if rms <= 1e-10:
        return -100.0
    return round(20.0 * math.log10(rms), 2)


def compute_waveform_peaks(audio: np.ndarray, num_bins: int = 140) -> list[float]:
    """Compute normalized peak envelope [0.0..1.0] across num_bins segments for UI visualization."""
    if audio.ndim == 2:
        # audio shape Either (T, C) or (C, T)
        mono = np.mean(np.abs(audio), axis=0 if audio.shape[0] <= 2 else 1)
    else:
        mono = np.abs(audio)

    total = mono.size
    if total == 0:
        return [0.0] * num_bins

    if total < num_bins:
        padded = np.zeros(num_bins, dtype=np.float32)
        padded[:total] = mono
        mono = padded
        total = num_bins

    indices = np.linspace(0, total, num_bins + 1, dtype=int)
    peaks = []
    for i in range(num_bins):
        seg = mono[indices[i] : max(indices[i] + 1, indices[i + 1])]
        peaks.append(float(np.percentile(seg, 90)) if seg.size > 0 else 0.0)

    max_val = max(peaks) if peaks else 1.0
    if max_val <= 1e-8:
        return [0.02] * num_bins

    return [round(min(1.0, max(0.02, p / max_val)), 4) for p in peaks]


def load_wav(wav_path: Path) -> tuple[np.ndarray, int]:
    """Load WAV file as float32 numpy array with shape (channels, samples)."""
    data, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    # soundfile returns (samples, channels) -> transpose to (channels, samples)
    return data.T, int(sr)


def save_wav(wav_path: Path, audio: np.ndarray, sample_rate: int = 44100) -> Path:
    """Save float32 numpy array of shape (channels, samples) or (samples,) to 16-bit PCM WAV."""
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    if audio.ndim == 2:
        data = audio.T
    else:
        data = audio
    # Soft clip / limit to [-0.99, 0.99] to prevent digital clipping on export
    peak = float(np.max(np.abs(data))) if data.size > 0 else 0.0
    if peak > 0.99:
        data = data * (0.99 / peak)
    sf.write(str(wav_path), data, sample_rate, subtype="PCM_16")
    return wav_path
