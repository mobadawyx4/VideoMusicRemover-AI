"""Automated backend test suite for VideoMusicRemover AI."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.config import PROJECT_ROOT, settings
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
    # Model weights are downloaded lazily on first processing, so installation
    # and health checks must not require them to be present yet.
    assert isinstance(data["ai_model_ready"], bool)
    assert data["ai_model_ready"] == separator_service.is_model_available()
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
            "VideoMusicRemover AI is ready!",
            "http://localhost:5173",
        ):
            assert step in content, f"Missing '{step}' in {installer}"


def test_installers_defer_model_download_until_first_use() -> None:
    for installer in ("install.sh", "install.ps1"):
        content = (PROJECT_ROOT / installer).read_text(encoding="utf-8")
        assert "ensure_model_cached" not in content, (
            f"{installer} must not download the AI model during installation"
        )
        assert "first video-processing run" in content, (
            f"{installer} must tell users the AI model downloads on first use"
        )
        assert "assert separator_service.is_model_available()" not in content, (
            f"{installer} must not fail validation when model weights are not cached yet"
        )


def test_windows_installer_supports_robust_prerequisites() -> None:
    content = (PROJECT_ROOT / "install.ps1").read_text(encoding="utf-8")

    expected_fragments = (
        "Is64BitOperatingSystem",
        "PROCESSOR_ARCHITECTURE",
        "Python.Python.3.12",
        "OpenJS.NodeJS.LTS",
        "Gyan.FFmpeg",
        "nvidia-smi",
        "torch.cuda.is_available()",
        "https://download.pytorch.org/whl/cu121",
        "https://download.pytorch.org/whl/cpu",
        "-TorchMode",
        "check_requirements.py",
        "first video-processing run",
    )
    for fragment in expected_fragments:
        assert fragment in content, f"install.ps1 is missing: {fragment}"

    assert "Set-ExecutionPolicy" not in content
    assert "Windows on ARM" in content
    assert "CUDA is not usable at runtime" in content
    assert "CPU fallback" in content


def test_windows_start_and_update_are_safe() -> None:
    start = (PROJECT_ROOT / "start.ps1").read_text(encoding="utf-8")
    update = (PROJECT_ROOT / "update.ps1").read_text(encoding="utf-8")

    # First-run install must not recursively launch start.ps1 again.
    assert '"install.ps1") -NoLaunch' in start
    assert "Installation did not complete successfully" in start

    # Updates must guard local changes and preserve user/model data.
    assert "git status --porcelain" in update
    assert "data\\models" in update
    assert "preserved" in update
    assert "-NoPull" in update
    for script in (start, update):
        assert "Set-ExecutionPolicy" not in script


def test_linux_start_avoids_installer_recursion() -> None:
    start = (PROJECT_ROOT / "start.sh").read_text(encoding="utf-8")
    assert 'install.sh" --no-launch' in start
    assert "Installation did not complete successfully" in start


def test_bundled_binary_resolution_respects_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import config

    bundled_dir = tmp_path / "tools" / "ffmpeg"
    bundled_dir.mkdir(parents=True)
    posix_binary = bundled_dir / "ffmpeg"
    windows_binary = bundled_dir / "ffmpeg.exe"
    posix_binary.write_text("posix", encoding="utf-8")
    windows_binary.write_text("windows", encoding="utf-8")

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("FFMPEG_PATH", raising=False)

    resolved = Path(config._resolve_binary("ffmpeg", "FFMPEG_PATH"))
    if os.name == "nt":
        assert resolved == windows_binary.resolve()
    else:
        assert resolved == posix_binary.resolve()


def test_requirement_checker_verifies_installed_versions(tmp_path: Path) -> None:
    checker = PROJECT_ROOT / "scripts" / "check_requirements.py"
    req_file = tmp_path / "requirements.txt"

    req_file.write_text("pytest>=8.0.0\n", encoding="utf-8")
    satisfied = subprocess.run(
        [sys.executable, str(checker), str(req_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert satisfied.returncode == 0, satisfied.stderr

    req_file.write_text(
        "definitely-not-installed-package==1.0.0\n", encoding="utf-8"
    )
    missing = subprocess.run(
        [sys.executable, str(checker), str(req_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 1
    assert "MISSING" in missing.stderr


def test_requirement_checker_version_semantics() -> None:
    import importlib.util

    checker = PROJECT_ROOT / "scripts" / "check_requirements.py"
    spec = importlib.util.spec_from_file_location("check_requirements", checker)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Local build labels satisfy a plain == pin (PyTorch 2.5.1+cu121).
    assert module.satisfies("2.5.1+cu121", "==", "2.5.1")
    # PEP 440 trailing zeros are equivalent.
    assert module.satisfies("2.0", "==", "2.0.0")
    assert not module.satisfies("2.0", "!=", "2.0.0")
    assert module.satisfies("1.4.2", ">=", "1.4")
    assert module.satisfies("2.10.4", "~=", "2.10")
    assert not module.satisfies("3.0.0", "~=", "2.10")
    assert module.satisfies("1.2.9", "~=", "1.2.3")
    assert not module.satisfies("1.3.0", "~=", "1.2.3")


def test_model_download_is_lazy_and_cached_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.separation.tiger_separator as tiger_module

    models_dir = tmp_path / "models"
    fake_snapshot = (
        models_dir
        / f"models--{settings.MODEL_REPO_ID.replace('/', '--')}"
        / "snapshots"
        / "test-revision"
    )
    monkeypatch.setattr(settings, "MODELS_DIR", models_dir)

    download_calls = []

    def fake_snapshot_download(**kwargs):
        download_calls.append(kwargs)
        fake_snapshot.mkdir(parents=True)
        (fake_snapshot / "config.json").write_text("{}", encoding="utf-8")
        (fake_snapshot / "model.safetensors").write_bytes(b"fake-weights")
        return str(fake_snapshot)

    monkeypatch.setattr(tiger_module, "snapshot_download", fake_snapshot_download)

    service = tiger_module.TigerSeparatorService()
    service._device = "cpu"

    # Merely constructing the service must not download model weights.
    assert download_calls == []
    assert service.is_model_available() is False

    class FakeModel:
        def to(self, device):
            return self

        def eval(self):
            return self

    load_calls = []

    def fake_from_pretrained(path, **kwargs):
        load_calls.append((path, kwargs))
        return FakeModel()

    monkeypatch.setattr(
        tiger_module.TIGERDNR, "from_pretrained", fake_from_pretrained
    )

    # First actual use downloads and loads exactly once; later calls reuse memory/cache.
    first = service.load_model()
    second = service.load_model()
    assert first is second
    assert service.is_model_available() is True
    assert len(download_calls) == 1
    assert len(load_calls) == 1
    assert load_calls[0] == (str(fake_snapshot), {"local_files_only": True})


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
