"""Automated backend test suite for SilentTrack AI."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT
from app.core.schemas import ProcessOptions, SeparationMode
from app.core.security import sanitize_filename, validate_job_id
from app.main import app
from app.services.demo_service import generate_sample_video
from app.services.media_service import (
    compute_rms_db,
    compute_waveform_peaks,
    extract_audio_from_video,
    inspect_video,
)
from app.services.separation import separator_service


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_health_endpoint(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["ffmpeg_available"] is True
    assert data["ffprobe_available"] is True
    assert data["ai_model_ready"] is True
    assert ".mp4" in data["allowed_extensions"]


def test_security_helpers() -> None:
    valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
    assert validate_job_id(valid_uuid) == valid_uuid

    with pytest.raises(Exception):
        validate_job_id("../../etc/passwd")

    assert sanitize_filename("../../evil name!@#.mp4") == "evil_name.mp4"
    assert sanitize_filename("clip.mov") == "clip.mov"
    assert sanitize_filename("bad.exe") == "bad.mp4"


def test_cross_platform_scripts_and_model_cache() -> None:
    # Verify model cache and disk space helpers
    free_mb = separator_service.check_available_disk_space_mb()
    assert free_mb > 100
    cached_path = separator_service.ensure_model_cached()
    assert cached_path.is_dir()
    assert (cached_path / "config.json").is_file()

    # Verify Linux Bash scripts exist and pass bash -n syntax validation
    bash_scripts = [
        "install.sh",
        "start.sh",
        "stop.sh",
        "update.sh",
        "scripts/start_dev.sh",
    ]
    for rel in bash_scripts:
        script_path = PROJECT_ROOT / rel
        assert script_path.is_file(), f"Missing script: {rel}"
        res = subprocess.run(
            ["bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"bash -n failed for {rel}: {res.stderr}"

    # Verify Windows PowerShell scripts exist and pass structural/delimiter validation
    ps_scripts = ["install.ps1", "start.ps1", "stop.ps1", "update.ps1"]
    for name in ps_scripts:
        ps_path = PROJECT_ROOT / name
        assert ps_path.is_file(), f"Missing PowerShell script: {name}"
        text = ps_path.read_text(encoding="utf-8")
        no_block = re.sub(r"<#.*?#>", "", text, flags=re.S)
        no_str = re.sub(r"\"(?:\\.|[^\"])*\"|'[^']*'", "\"\"", no_block)
        clean = "\n".join(re.sub(r"#.*$", "", ln) for ln in no_str.splitlines())
        assert text.count("<#") == text.count("#>")
        assert clean.count("{") == clean.count("}")
        assert clean.count("(") == clean.count(")")
        assert clean.count("[") == clean.count("]")

    # Verify required user-facing step messages in install.sh and install.ps1
    for installer in ("install.sh", "install.ps1"):
        content = (PROJECT_ROOT / installer).read_text(encoding="utf-8")
        for step in (
            "[1/5] Checking prerequisites...",
            "[2/5] Setting up Python environment...",
            "[3/5] Installing backend dependencies...",
            "[4/5] Installing frontend dependencies...",
            "[5/5] Validating installation...",
            "SilentTrack AI is ready!",
            "http://localhost:5173",
        ):
            assert step in content, f"Missing '{step}' in {installer}"


def test_upload_validation_errors(client: TestClient) -> None:
    # Unsupported format
    resp = client.post(
        "/api/jobs/upload",
        files={"file": ("test.txt", b"not a video", "text/plain")},
    )
    assert resp.status_code == 400
    assert "Unsupported video format" in resp.json()["detail"]

    # Empty file
    resp_empty = client.post(
        "/api/jobs/upload",
        files={"file": ("empty.mp4", b"", "video/mp4")},
    )
    assert resp_empty.status_code == 400
    assert "empty" in resp_empty.json()["detail"].lower()

    # Corrupted video file
    resp_corrupt = client.post(
        "/api/jobs/upload",
        files={"file": ("corrupt.mp4", b"fake-mp4-bytes-12345", "video/mp4")},
    )
    assert resp_corrupt.status_code == 400


def test_waveform_and_rms_utilities() -> None:
    t = np.linspace(0, 1.0, 44100, dtype=np.float32)
    sine = 0.5 * np.sin(2 * np.pi * 440 * t)
    rms = compute_rms_db(sine)
    assert -10.0 < rms < -8.0

    peaks = compute_waveform_peaks(sine, num_bins=50)
    assert len(peaks) == 50
    assert all(0.0 <= p <= 1.0 for p in peaks)


def test_media_inspection_and_extraction(tmp_path: Path) -> None:
    sample_mp4 = tmp_path / "sample.mp4"
    generate_sample_video(sample_mp4, duration_sec=2.0)
    assert sample_mp4.is_file()

    meta = inspect_video(sample_mp4, original_filename="sample.mp4")
    assert meta.width == 1280
    assert meta.height == 720
    assert meta.aspect_ratio == "16:9"
    assert abs(meta.fps - 30.0) < 0.5
    assert meta.has_audio is True
    assert 1.8 <= meta.duration_seconds <= 2.3

    wav_out = tmp_path / "extracted.wav"
    extract_audio_from_video(sample_mp4, wav_out, target_sr=44100, channels=2)
    assert wav_out.is_file()
    assert wav_out.stat().st_size > 10000


def test_end_to_end_upload_ai_separation_remix_and_download(
    client: TestClient, tmp_path: Path
) -> None:
    # 1. Generate a compact 2.0s video with speech, environmental SFX, and music
    video_path = tmp_path / "e2e_clip.mp4"
    generate_sample_video(video_path, duration_sec=2.0)

    with video_path.open("rb") as f:
        up_resp = client.post(
            "/api/jobs/upload",
            files={"file": ("e2e_clip.mp4", f, "video/mp4")},
        )
    assert up_resp.status_code == 201, up_resp.text
    job_data = up_resp.json()
    job_id = job_data["job_id"]
    token = job_data["access_token"]
    assert job_data["status"] == "uploaded"
    assert job_data["metadata"]["width"] == 1280
    assert job_data["metadata"]["height"] == 720

    # 2. Trigger AI processing in FAST mode
    proc_resp = client.post(
        f"/api/jobs/{job_id}/process?token={token}",
        json=ProcessOptions(
            music_removal_strength=1.0,
            speech_gain=1.0,
            effects_gain=1.0,
            separation_mode=SeparationMode.FAST,
        ).model_dump(mode="json"),
    )
    assert proc_resp.status_code == 200

    # 3. Poll until completed
    deadline = time.time() + 180.0
    final_job = None
    while time.time() < deadline:
        status_resp = client.get(f"/api/jobs/{job_id}?token={token}")
        assert status_resp.status_code == 200
        cur = status_resp.json()
        if cur["status"] == "completed":
            final_job = cur
            break
        if cur["status"] == "failed":
            pytest.fail(f"AI processing job failed: {cur.get('error')}")
        time.sleep(1.0)

    assert final_job is not None, "Job timed out waiting for AI separation"
    assert final_job["progress"] == 100.0
    assert final_job["metrics"] is not None
    assert final_job["waveform"] is not None
    assert len(final_job["waveform"]["original_peaks"]) == 140
    assert len(final_job["waveform"]["processed_peaks"]) == 140

    # 4. Verify job isolation (missing/wrong token rejected on media download)
    unauth_resp = client.get(
        f"/api/jobs/{job_id}/media/processed_video?token=wrong_token"
    )
    assert unauth_resp.status_code == 403

    # 5. Download processed video and verify resolution, FPS, and aspect ratio are preserved
    dl_resp = client.get(
        f"/api/jobs/{job_id}/media/processed_video?token={token}&download=true"
    )
    assert dl_resp.status_code == 200
    assert len(dl_resp.content) > 5000

    downloaded_mp4 = tmp_path / "downloaded_output.mp4"
    downloaded_mp4.write_bytes(dl_resp.content)
    out_meta = inspect_video(downloaded_mp4)
    assert out_meta.width == 1280
    assert out_meta.height == 720
    assert out_meta.aspect_ratio == "16:9"
    assert abs(out_meta.fps - 30.0) < 0.5
    assert out_meta.has_audio is True

    # 6. Test instant remix with 65% music removal strength
    remix_resp = client.post(
        f"/api/jobs/{job_id}/remix?token={token}",
        json={
            "music_removal_strength": 0.65,
            "speech_gain": 1.15,
            "effects_gain": 1.0,
        },
    )
    assert remix_resp.status_code == 200
    remixed_job = remix_resp.json()
    assert remixed_job["options"]["music_removal_strength"] == 0.65

    # 7. Clean up job
    del_resp = client.delete(f"/api/jobs/{job_id}?token={token}")
    assert del_resp.status_code == 200
