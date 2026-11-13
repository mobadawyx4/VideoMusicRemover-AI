"""Automated tests for Video URL Import (yt-dlp, direct stream, SSRF protection)."""

from __future__ import annotations

import io
import shutil
import socket
import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
import yt_dlp

from app.core.config import settings
from app.main import app
from app.services.demo_service import generate_sample_video
from app.services.job_manager import job_manager
from app.services.media_service import inspect_video
from app.services.url_service import (
    FileSizeLimitError,
    SSRFProtectionError,
    VideoDownloadError,
    download_direct_video_stream,
    is_private_or_internal_ip,
    validate_url_security,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_video_with_audio(tmp_path: Path) -> Path:
    """Generate a real 2.0s valid sample video containing audio for mocking downloads."""
    sample_path = tmp_path / "valid_sample.mp4"
    generate_sample_video(sample_path, duration_sec=2.0)
    return sample_path


@pytest.fixture
def mock_video_without_audio(tmp_path: Path) -> Path:
    """Generate a real video with NO audio stream."""
    no_audio_path = tmp_path / "no_audio.mp4"
    cmd = [
        settings.FFMPEG_PATH,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=25",
        "-c:v",
        "libx264",
        str(no_audio_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0
    return no_audio_path


def test_ip_validation_helpers() -> None:
    # Loopback
    assert is_private_or_internal_ip("127.0.0.1") is True
    assert is_private_or_internal_ip("127.0.0.2") is True
    assert is_private_or_internal_ip("::1") is True

    # Private RFC1918 & RFC4193
    assert is_private_or_internal_ip("10.0.0.1") is True
    assert is_private_or_internal_ip("172.16.0.1") is True
    assert is_private_or_internal_ip("192.168.1.1") is True
    assert is_private_or_internal_ip("fd00::1") is True

    # Link-local & Cloud Metadata
    assert is_private_or_internal_ip("169.254.169.254") is True
    assert is_private_or_internal_ip("fe80::1") is True

    # Carrier Grade NAT & Unspecified
    assert is_private_or_internal_ip("100.64.0.1") is True
    assert is_private_or_internal_ip("0.0.0.0") is True

    # Public Safe IPs
    assert is_private_or_internal_ip("8.8.8.8") is False
    assert is_private_or_internal_ip("1.1.1.1") is False


def test_invalid_url(client: TestClient) -> None:
    # Empty string
    resp = client.post("/api/jobs/from-url", json={"url": ""})
    assert resp.status_code in (400, 422)

    # Missing scheme / plain string
    resp2 = client.post("/api/jobs/from-url", json={"url": "not_a_valid_url"})
    assert resp2.status_code == 400
    assert "Only HTTP and HTTPS" in resp2.json()["detail"] or "protocol" in resp2.json()["detail"].lower()

    # Incomplete URL
    resp3 = client.post("/api/jobs/from-url", json={"url": "https://"})
    assert resp3.status_code == 400


def test_non_http_https_protocols(client: TestClient) -> None:
    for proto_url in [
        "file:///etc/passwd",
        "ftp://ftp.example.com/video.mp4",
        "gopher://evil.com/video",
        "data:text/plain;base64,SGVsbG8=",
        "javascript:alert(1)",
    ]:
        resp = client.post("/api/jobs/from-url", json={"url": proto_url})
        assert resp.status_code == 400
        assert "Only HTTP and HTTPS" in resp.json()["detail"]


def test_localhost_and_internal_domain_rejection(client: TestClient) -> None:
    for local_url in [
        "http://localhost/video.mp4",
        "http://localhost:8000/api/health",
        "http://test.localhost/video.mp4",
        "http://service.local/clip.mov",
        "http://cluster.internal/clip.mp4",
        "http://router.lan/video.mkv",
        "http://0.0.0.0/video.mp4",
        "http://[::1]/video.mp4",
    ]:
        resp = client.post("/api/jobs/from-url", json={"url": local_url})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "private, loopback, or internal" in detail.lower() or "not allowed" in detail.lower()


def test_private_ip_rejection(client: TestClient) -> None:
    for private_url in [
        "http://127.0.0.1:8000/api/health",
        "http://127.0.0.5/video.mp4",
        "http://10.0.0.50/video.mp4",
        "http://172.16.10.10/video.mp4",
        "http://192.168.1.100/video.mp4",
        "http://169.254.169.254/latest/meta-data",
        "http://2130706433/video.mp4",  # decimal 127.0.0.1
    ]:
        resp = client.post("/api/jobs/from-url", json={"url": private_url})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "private, loopback, or internal" in detail.lower()


def test_dns_rebinding_ssrf_protection(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate a domain that resolves to 127.0.0.1
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    resp = client.post("/api/jobs/from-url", json={"url": "https://public-looking-domain.com/video.mp4"})
    assert resp.status_code == 400
    assert "private, loopback, or internal" in resp.json()["detail"].lower()


def test_unsupported_platform(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock DNS resolution for test domain
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_extract_info(self, url, download=True):
        raise yt_dlp.utils.UnsupportedError(f"Unsupported URL: {url}")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", mock_extract_info)

    resp = client.post("/api/jobs/from-url", json={"url": "https://unsupported-platform.org/watch?id=999"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "not supported" in detail.lower()
    # Ensure no internal file paths leaked
    assert "/home" not in detail and "\\Users" not in detail


def test_download_failure_private_or_restricted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.190.46", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_extract_info(self, url, download=True):
        raise yt_dlp.utils.DownloadError("ERROR: [youtube] 12345: Private video. Sign in to view.")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", mock_extract_info)

    resp = client.post("/api/jobs/from-url", json={"url": "https://www.youtube.com/watch?v=private123"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "private" in detail.lower() or "restricted" in detail.lower()
    assert "/home" not in detail


def test_download_failure_unavailable(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.190.46", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_extract_info(self, url, download=True):
        raise yt_dlp.utils.DownloadError("ERROR: [youtube] abcde: Video unavailable. This video has been removed.")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", mock_extract_info)

    resp = client.post("/api/jobs/from-url", json={"url": "https://www.youtube.com/watch?v=deleted_clip"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "unavailable" in detail.lower() or "not found" in detail.lower()


def test_oversized_download(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_extract_info(self, url, download=True):
        raise FileSizeLimitError("Video file size exceeds maximum allowed limit.")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", mock_extract_info)

    resp = client.post("/api/jobs/from-url", json={"url": "https://example.com/huge_video_5gb"})
    assert resp.status_code == 413
    assert "exceeds maximum allowed limit" in resp.json()["detail"]


def test_corrupted_downloaded_video(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    # Mock download to return a file containing garbage non-video bytes
    def mock_download_with_ytdlp(url, temp_dir, max_bytes, max_duration_sec):
        corrupt_file = temp_dir / f"ytdl_corrupt_{uuid.uuid4().hex}.mp4"
        corrupt_file.write_bytes(b"NOT_A_VALID_MP4_FILE_RANDOM_GARBAGE")
        return corrupt_file, "corrupt_video"

    monkeypatch.setattr("app.services.url_service.download_with_ytdlp", mock_download_with_ytdlp)

    resp = client.post("/api/jobs/from-url", json={"url": "https://example.com/corrupt_clip"})
    assert resp.status_code == 400
    assert "corrupted" in resp.json()["detail"].lower() or "invalid" in resp.json()["detail"].lower()

    # Ensure no leftover files
    leftover = list(settings.JOBS_DIR.glob("ytdl_corrupt_*"))
    assert len(leftover) == 0


def test_video_without_audio(
    client: TestClient, mock_video_without_audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_download_with_ytdlp(url, temp_dir, max_bytes, max_duration_sec):
        dest = temp_dir / f"ytdl_silent_{uuid.uuid4().hex}.mp4"
        shutil.copyfile(str(mock_video_without_audio), str(dest))
        return dest, "silent_video"

    monkeypatch.setattr("app.services.url_service.download_with_ytdlp", mock_download_with_ytdlp)

    resp = client.post("/api/jobs/from-url", json={"url": "https://example.com/video_no_audio"})
    assert resp.status_code == 400
    assert "audio track" in resp.json()["detail"].lower()

    # Ensure no leftover files
    leftover = list(settings.JOBS_DIR.glob("ytdl_silent_*"))
    assert len(leftover) == 0


def test_successful_job_creation_mocked(
    client: TestClient, mock_video_with_audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.190.46", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_download_with_ytdlp(url, temp_dir, max_bytes, max_duration_sec):
        dest = temp_dir / f"ytdl_success_{uuid.uuid4().hex}.mp4"
        shutil.copyfile(str(mock_video_with_audio), str(dest))
        return dest, "Sample Interview Clip"

    monkeypatch.setattr("app.services.url_service.download_with_ytdlp", mock_download_with_ytdlp)

    resp = client.post(
        "/api/jobs/from-url",
        json={"url": "https://www.youtube.com/watch?v=valid_mock_video"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert "job_id" in data
    assert "access_token" in data
    assert data["status"] == "uploaded"
    assert data["metadata"]["has_audio"] is True
    assert data["metadata"]["width"] == 1280
    assert data["metadata"]["height"] == 720
    assert "Sample_Interview_Clip" in data["metadata"]["filename"]

    # Verify no orphan temporary download files remain in jobs dir
    assert len(list(settings.JOBS_DIR.glob("ytdl_success_*"))) == 0

    # Cleanup job
    del_resp = client.delete(f"/api/jobs/{data['job_id']}?token={data['access_token']}")
    assert del_resp.status_code == 200


def test_direct_stream_download_chunked_success(
    client: TestClient, mock_video_with_audio: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    video_bytes = mock_video_with_audio.read_bytes()

    class MockStreamResponse:
        status_code = 200
        headers = {
            "Content-Type": "video/mp4",
            "Content-Length": str(len(video_bytes)),
        }

        def iter_content(self, chunk_size=65536):
            bio = io.BytesIO(video_bytes)
            while True:
                chunk = bio.read(chunk_size)
                if not chunk:
                    break
                yield chunk

        def close(self):
            pass

    def mock_get(self, url, **kwargs):
        return MockStreamResponse()

    monkeypatch.setattr("requests.Session.get", mock_get)

    resp = client.post(
        "/api/jobs/from-url",
        json={"url": "https://cdn.example.com/direct_sample.mp4"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "uploaded"
    assert data["metadata"]["has_audio"] is True

    # Cleanup job
    client.delete(f"/api/jobs/{data['job_id']}?token={data['access_token']}")


def test_ssrf_redirect_destination_rejection(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        # Initial host is public
        if "redirector" in host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        # Loopback target
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    class MockRedirectResponse:
        status_code = 302
        headers = {"Location": "http://127.0.0.1:8000/api/health"}

        def close(self):
            pass

    def mock_get(self, url, **kwargs):
        return MockRedirectResponse()

    monkeypatch.setattr("requests.Session.get", mock_get)

    resp = client.post(
        "/api/jobs/from-url",
        json={"url": "https://redirector.example.com/video.mp4"},
    )
    assert resp.status_code == 400
    assert "private, loopback, or internal" in resp.json()["detail"].lower()


def test_temporary_file_cleanup_on_download_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mock_getaddrinfo(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_extract_info(self, url, download=True):
        outtmpl = self.params["outtmpl"]["default"]
        partial_file = Path(outtmpl.replace("%(ext)s", "part"))
        partial_file.write_bytes(b"partial video stream interrupted")
        assert partial_file.is_file()
        raise yt_dlp.utils.DownloadError("Connection reset by peer mid-download")

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", mock_extract_info)

    resp = client.post(
        "/api/jobs/from-url",
        json={"url": "https://example.com/network_fail_video"},
    )
    assert resp.status_code == 400

    # Verify partial files were cleaned up
    leftover_partials = list(settings.JOBS_DIR.glob("ytdl_*part*"))
    assert len(leftover_partials) == 0


def test_dns_rebinding_at_connection_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test TOCTOU / DNS rebinding where domain resolves to public IP during initial check,

    but resolves to 127.0.0.1 at socket connection time.
    """
    call_count = 0

    def mock_getaddrinfo(host, port, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # First call is preliminary check: return public IP
        if call_count == 1:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        # Subsequent call (connection time): return loopback address!
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    resp = client.post(
        "/api/jobs/from-url",
        json={"url": "https://rebind.attacker.com/video.mp4"},
    )
    assert resp.status_code == 400
    assert "private, loopback, or internal" in resp.json()["detail"].lower()


def test_ytdlp_media_urls_resolving_to_private_address(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test yt-dlp extracting formats whose media stream URLs point to private or internal addresses."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        if "youtube" in host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("142.250.190.46", port))]
        # Extracted media CDN host resolves to internal private IP
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.99", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    def mock_extract_info(self, url, download=True):
        # yt-dlp extractor succeeds, but then tries to download media from a private destination
        media_req = yt_dlp.networking.Request("http://10.0.0.99:8000/extracted_stream.mp4")
        # Hand this request to request director (as yt-dlp native downloaders do)
        self._request_director.send(media_req)
        return {"id": "test", "title": "test"}

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", mock_extract_info)

    resp = client.post(
        "/api/jobs/from-url",
        json={"url": "https://www.youtube.com/watch?v=extracted_private_media"},
    )
    assert resp.status_code == 400
    assert "private, loopback, or internal" in resp.json()["detail"].lower()


def test_excessive_redirect_chains(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that redirect chains exceeding MAX_REDIRECTS (5) are rejected and responses closed."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    closed_count = 0
    redirect_idx = 0

    class MockLoopResponse:
        status_code = 302

        def __init__(self, idx: int):
            self.idx = idx
            self.headers = {"Location": f"https://example.com/loop_{idx + 1}.mp4"}

        def close(self):
            nonlocal closed_count
            closed_count += 1

    def mock_get(self, url, **kwargs):
        nonlocal redirect_idx
        redirect_idx += 1
        return MockLoopResponse(redirect_idx)

    monkeypatch.setattr("requests.Session.get", mock_get)

    resp = client.post(
        "/api/jobs/from-url",
        json={"url": "https://example.com/infinite_redirect_loop.mp4"},
    )
    assert resp.status_code == 400
    assert "exceeded maximum allowed redirects" in resp.json()["detail"].lower()
    # Ensure all intermediate redirect responses were properly closed
    assert closed_count > 5


def test_response_objects_and_temp_files_closed_on_server_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that when remote server returns 500 or error, response is closed and temp files deleted."""
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    response_closed = False

    class MockErrorResponse:
        status_code = 500

        def close(self):
            nonlocal response_closed
            response_closed = True

    def mock_get(self, url, **kwargs):
        return MockErrorResponse()

    monkeypatch.setattr("requests.Session.get", mock_get)

    resp = client.post(
        "/api/jobs/from-url",
        json={"url": "https://example.com/server_error.mp4"},
    )
    assert resp.status_code == 400
    assert response_closed is True
    # Ensure no leftover temp files
    assert len(list(settings.JOBS_DIR.glob("url_direct_*"))) == 0
