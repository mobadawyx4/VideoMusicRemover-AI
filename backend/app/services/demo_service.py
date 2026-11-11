"""Synthetic sample video generator with mixed speech-like voice, environmental sound, and background music."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.media_service import MediaProcessingError, save_wav


def generate_sample_video(output_path: Path, duration_sec: float = 4.0) -> Path:
    """Create a real MP4 test video containing distinct voice-like cadences, ambient chime/rain SFX, and background music chords."""
    sr = 44100
    n_samples = int(duration_sec * sr)
    t = np.linspace(0.0, duration_sec, n_samples, endpoint=False, dtype=np.float32)

    # 1. Simulated speech cadence (syllabic formant bursts around 140Hz fundamental + 500/1500/2500Hz formants)
    f0 = 135.0 + 15.0 * np.sin(2.0 * np.pi * 1.8 * t)
    glottal = (
        0.45 * np.sin(2.0 * np.pi * f0 * t)
        + 0.35 * np.sin(2.0 * np.pi * 4.0 * f0 * t)
        + 0.20 * np.sin(2.0 * np.pi * 11.0 * f0 * t)
        + 0.10 * np.sin(2.0 * np.pi * 18.0 * f0 * t)
    )
    syllable_env = np.clip(np.sin(2.0 * np.pi * 3.2 * t) + 0.2, 0.0, 1.0) ** 2
    speech_sig = 0.32 * glottal * syllable_env

    # 2. Environmental sound effects (footstep/door-knock transients + subtle rain texture)
    rng = np.random.default_rng(42)
    rain = 0.03 * rng.normal(0.0, 1.0, size=n_samples).astype(np.float32)
    transients = np.zeros_like(t)
    for hit_time in [0.6, 1.4, 2.3, 3.1]:
        idx = int(hit_time * sr)
        length = min(int(0.12 * sr), n_samples - idx)
        if length > 0:
            local_t = np.linspace(0.0, 0.12, length, dtype=np.float32)
            impact = np.exp(-35.0 * local_t) * np.sin(2.0 * np.pi * 220.0 * local_t)
            transients[idx : idx + length] += 0.35 * impact
    effects_sig = rain + transients

    # 3. Background music (sustained stereo synth pad & bass chord progression: A minor -> F major)
    music_l = (
        0.22 * np.sin(2.0 * np.pi * 220.0 * t)
        + 0.18 * np.sin(2.0 * np.pi * 261.63 * t)
        + 0.18 * np.sin(2.0 * np.pi * 329.63 * t)
        + 0.14 * np.sin(2.0 * np.pi * 440.0 * t)
    )
    music_r = (
        0.22 * np.sin(2.0 * np.pi * 110.0 * t)
        + 0.18 * np.sin(2.0 * np.pi * 261.63 * t + 0.4)
        + 0.18 * np.sin(2.0 * np.pi * 329.63 * t - 0.3)
        + 0.14 * np.sin(2.0 * np.pi * 659.25 * t)
    )

    left = speech_sig + effects_sig + music_l
    right = speech_sig + effects_sig + music_r
    stereo = np.stack([left, right], axis=0).astype(np.float32)

    tmp_wav = output_path.parent / "sample_gen_audio.wav"
    save_wav(tmp_wav, stereo, sr)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.FFMPEG_PATH,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size=1280x720:rate=30:duration={duration_sec}",
        "-i",
        str(tmp_wav),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    tmp_wav.unlink(missing_ok=True)

    if res.returncode != 0 or not output_path.is_file():
        raise MediaProcessingError(
            f"Failed to generate sample video: {(res.stderr or '')[-300:]}"
        )
    return output_path
