"""URL validation, SSRF prevention, and video downloading via yt-dlp and direct streaming."""

from __future__ import annotations

import contextvars
import ipaddress
import logging
import re
import socket
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
import urllib3
import urllib3.util.connection as conn
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
import yt_dlp
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.schemas import JobResponse
from app.core.security import sanitize_filename
from app.services.job_manager import job_manager
from app.services.media_service import MediaProcessingError, inspect_video

logger = logging.getLogger(__name__)

# Reserved / internal domain suffixes to block early
BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".lan",
    ".home.arpa",
    ".invalid",
    ".test",
    ".corp",
)

BLOCKED_HOSTNAMES = {
    "localhost",
    "0.0.0.0",
    "127.0.0.1",
    "::1",
    "[::1]",
    "metadata.google.internal",
    "instance-data",
}

MAX_REDIRECTS = 5
CHUNK_SIZE = 64 * 1024  # 64 KB streaming chunks
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0

# Context variable to activate connection-time socket security guard
_ssrf_guard_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_ssrf_guard_active", default=False
)


class SSRFProtectionError(ValueError):
    """Raised when a URL targets a private, loopback, or internal address."""


class VideoDownloadError(Exception):
    """Raised when downloading a video fails."""


class NotDirectVideoError(VideoDownloadError):
    """Raised when a direct download target returns HTML instead of a media stream."""


class FileSizeLimitError(VideoDownloadError):
    """Raised when a video exceeds maximum upload/download size."""


def is_private_or_internal_ip(ip_str: str) -> bool:
    """Check if an IP address belongs to loopback, private, link-local, or reserved ranges."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True

    # Handle IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return is_private_or_internal_ip(str(ip.ipv4_mapped))

    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True

    # Check IPv4 Carrier-Grade NAT (100.64.0.0/10)
    if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
        return True

    return False


@contextmanager
def ssrf_guard_context():
    """Context manager that activates connection-time socket blocking for SSRF defense."""
    token = _ssrf_guard_active.set(True)
    try:
        yield
    finally:
        _ssrf_guard_active.reset(token)


def _ssrf_audit_hook(event: str, args: tuple) -> None:
    """Audit hook that intercepts socket connections and enforces destination validation in real-time."""
    if event == "socket.connect" and _ssrf_guard_active.get():
        if len(args) >= 2 and isinstance(args[1], tuple):
            sock_addr = args[1]
            if sock_addr:
                ip_str = str(sock_addr[0])
                if is_private_or_internal_ip(ip_str):
                    raise SSRFProtectionError(
                        f"Access to private/internal IP {ip_str} is prohibited."
                    )


try:
    sys.addaudithook(_ssrf_audit_hook)
except Exception:
    pass


def safe_create_connection(
    address: tuple[str, int],
    timeout: float = conn._DEFAULT_TIMEOUT,
    source_address: Optional[tuple[str, int]] = None,
    socket_options: Optional[list] = None,
) -> socket.socket:
    """Resolve destination and verify IP address immediately before socket connect, preventing DNS rebinding."""
    host, port = address
    if host.startswith("["):
        host = host.strip("[]")

    family = conn.allowed_gai_family()
    exceptions = []

    for res in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res
        ip_str = sa[0]
        if is_private_or_internal_ip(ip_str):
            raise SSRFProtectionError(
                f"Access to private/internal IP {ip_str} is prohibited."
            )
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            conn._set_socket_options(sock, socket_options)
            if timeout is not conn._DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            return sock
        except OSError as exc:
            exceptions.append(exc)
            if sock is not None:
                sock.close()

    if exceptions:
        raise exceptions[0]
    raise OSError(f"Could not connect to {host}:{port}")


class SafeHTTPConnection(HTTPConnection):
    def _new_conn(self) -> socket.socket:
        return safe_create_connection(
            (self._dns_host, self.port),
            self.timeout,
            source_address=self.source_address,
            socket_options=self.socket_options,
        )


class SafeHTTPSConnection(HTTPSConnection):
    def _new_conn(self) -> socket.socket:
        return safe_create_connection(
            (self._dns_host, self.port),
            self.timeout,
            source_address=self.source_address,
            socket_options=self.socket_options,
        )


class SafeHTTPConnectionPool(HTTPConnectionPool):
    ConnectionCls = SafeHTTPConnection


class SafeHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = SafeHTTPSConnection


class SafeHTTPAdapter(HTTPAdapter):
    """Custom HTTP adapter that validates the target IP at connection time while preserving TLS SNI."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        self.poolmanager = urllib3.PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            **pool_kwargs,
        )
        self.poolmanager.pool_classes_by_scheme = {
            "http": SafeHTTPConnectionPool,
            "https": SafeHTTPSConnectionPool,
        }


def validate_url_security(url: str) -> tuple[str, str, int]:
    """Validate URL scheme and ensure target destination is not internal or SSRF-vulnerable."""
    if not url or not isinstance(url, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL is required and must be a valid string.",
        )

    clean_url = url.strip()
    try:
        parsed = urlsplit(clean_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed URL: {exc}",
        ) from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported protocol '{scheme}'. Only HTTP and HTTPS URLs are allowed.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must contain a valid hostname.",
        )

    lower_host = hostname.lower()
    if lower_host in BLOCKED_HOSTNAMES or lower_host.endswith(BLOCKED_HOST_SUFFIXES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access to private, loopback, or internal network destinations is not allowed.",
        )

    port = parsed.port or (443 if scheme == "https" else 80)
    if port < 1 or port > 65535:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL port is out of valid range (1-65535).",
        )

    # Resolve all DNS records for host and verify none resolve to internal / private addresses
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not resolve host '{hostname}'. Please check the URL.",
        ) from exc

    if not addr_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No IP addresses resolved for host '{hostname}'.",
        )

    for *_, sockaddr in addr_info:
        ip_str = sockaddr[0]
        if is_private_or_internal_ip(ip_str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Access to private, loopback, or internal network destinations is not allowed.",
            )

    return scheme, hostname, port


def sanitize_error_detail(error_str: str) -> str:
    """Strip internal filesystem paths, credentials, and technical clutter from error messages."""
    text = str(error_str)
    # Strip UNIX paths like /home/... or /tmp/...
    text = re.sub(r"/(?:[a-zA-Z0-9_. -]+/)+[a-zA-Z0-9_. -]*", "[file]", text)
    # Strip Windows paths like C:\...
    text = re.sub(r"[A-Za-z]:\\(?:[a-zA-Z0-9_. -]+\\)+[a-zA-Z0-9_. -]*", "[file]", text)
    # Strip yt-dlp error prefixes
    text = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?", "", text).strip()
    return text or "An error occurred while processing the video."


def map_download_exception_to_http(exc: Exception) -> HTTPException:
    """Map download and validation exceptions to clean user-facing HTTPExceptions."""
    if isinstance(exc, HTTPException):
        return exc

    msg = str(exc)
    lower = msg.lower()

    if isinstance(exc, (SSRFProtectionError, PermissionError)) or "private" in lower or "loopback" in lower or "internal" in lower or "ssrf" in lower:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Access to private, loopback, or internal network destinations is not allowed.",
        )

    if isinstance(exc, FileSizeLimitError) or "exceeds maximum" in lower or "is larger than" in lower:
        return HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Video file size exceeds maximum allowed limit of {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    if "exceeded maximum allowed redirects" in lower:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Exceeded maximum allowed redirects ({MAX_REDIRECTS}).",
        )

    if "duration" in lower and ("exceeds" in lower or "too long" in lower):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video duration exceeds maximum allowed duration of {settings.MAX_VIDEO_DURATION_SEC} seconds.",
        )

    if "audio" in lower and ("does not contain" in lower or "no audio" in lower):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This video does not contain an audio track to process.",
        )

    if "private" in lower or "sign in" in lower or "login" in lower or "account is required" in lower:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This video is private, restricted, or requires account sign-in.",
        )

    if "drm" in lower or "protected" in lower or "copyright" in lower:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This video is protected by DRM or copyright restrictions and cannot be downloaded.",
        )

    if "geo" in lower or "country" in lower or "region" in lower:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This video is geographically restricted and not available in this region.",
        )

    if "not found" in lower or "404" in lower or "unavailable" in lower or "deleted" in lower:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The requested video was not found or is unavailable.",
        )

    if "unsupported" in lower or "not supported" in lower or "no video formats" in lower:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The provided link is not supported or does not contain a downloadable video.",
        )

    if "timed out" in lower or "timeout" in lower:
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connection timed out while downloading the video. Please try again.",
        )

    clean = sanitize_error_detail(msg)
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=clean,
    )


def download_direct_video_stream(
    url: str,
    output_path: Path,
    max_bytes: int,
    timeout_sec: float = 30.0,
) -> Path:
    """Download a direct video link in chunks, validating SSRF on every redirect and enforcing size limits."""
    current_url = url
    session = requests.Session()
    adapter = SafeHTTPAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    resp: Optional[requests.Response] = None
    redirect_count = 0

    try:
        with ssrf_guard_context():
            while True:
                validate_url_security(current_url)
                resp = session.get(
                    current_url,
                    stream=True,
                    allow_redirects=False,
                    timeout=(CONNECT_TIMEOUT, timeout_sec),
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                        )
                    },
                )

                if 300 <= resp.status_code < 400:
                    redirect_count += 1
                    location = resp.headers.get("Location")
                    resp.close()
                    resp = None
                    if not location:
                        raise VideoDownloadError("Redirect response was missing Location header.")
                    if redirect_count > MAX_REDIRECTS:
                        raise VideoDownloadError(f"Exceeded maximum allowed redirects ({MAX_REDIRECTS}).")
                    current_url = urljoin(current_url, location)
                    continue

                break

            if resp is None:
                raise VideoDownloadError("Failed to initiate connection.")

            if resp.status_code != 200:
                sc = resp.status_code
                resp.close()
                resp = None
                raise VideoDownloadError(f"Remote server returned HTTP {sc}.")

            # Check content length header if provided
            cl_header = resp.headers.get("Content-Length")
            if cl_header and cl_header.isdigit():
                if int(cl_header) > max_bytes:
                    resp.close()
                    resp = None
                    raise FileSizeLimitError(
                        f"Video file size ({int(cl_header) / (1024 * 1024):.1f} MB) exceeds limit of "
                        f"{settings.MAX_UPLOAD_SIZE_MB} MB."
                    )

            # Stream chunks to output file and enforce byte limit
            bytes_written = 0
            first_chunk = True
            with open(output_path, "wb") as out_file:
                for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    if first_chunk:
                        # Check if body appears to be HTML error page rather than a video container
                        prefix = chunk[:128].lower()
                        if b"<!doctype html" in prefix or b"<html" in prefix:
                            resp.close()
                            resp = None
                            raise NotDirectVideoError("Direct download target returned an HTML page instead of a video stream.")
                        first_chunk = False

                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        resp.close()
                        resp = None
                        output_path.unlink(missing_ok=True)
                        raise FileSizeLimitError(
                            f"Downloaded content exceeds maximum limit of {settings.MAX_UPLOAD_SIZE_MB} MB."
                        )
                    out_file.write(chunk)

            if bytes_written == 0:
                output_path.unlink(missing_ok=True)
                raise VideoDownloadError("Downloaded video is empty (0 bytes).")

            return output_path

    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass
        session.close()


def _is_direct_video_extension(url: str) -> bool:
    """Check if the URL path ends with an allowed video extension."""
    try:
        path = urlsplit(url).path.lower()
        return any(path.endswith(ext) for ext in settings.ALLOWED_EXTENSIONS)
    except Exception:
        return False


def download_with_ytdlp(
    url: str,
    temp_dir: Path,
    max_bytes: int,
    max_duration_sec: int,
) -> tuple[Path, str]:
    """Download video using yt-dlp Python API with SSRF request interception and safety constraints."""
    download_id = uuid.uuid4().hex
    outtmpl_pattern = str(temp_dir / f"ytdl_{download_id}.%(ext)s")

    def match_filter_cb(info_dict: dict, *, incomplete: bool = False) -> Optional[str]:
        duration = info_dict.get("duration")
        if duration and duration > max_duration_sec:
            return (
                f"Video duration ({duration:.1f}s) exceeds maximum allowed duration "
                f"of {max_duration_sec}s."
            )
        size = info_dict.get("filesize") or info_dict.get("filesize_approx")
        if size and size > max_bytes:
            return (
                f"Video file size exceeds maximum limit of "
                f"{settings.MAX_UPLOAD_SIZE_MB} MB."
            )
        return None

    def progress_hook_cb(d: dict) -> None:
        if d.get("status") == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            if downloaded > max_bytes:
                raise FileSizeLimitError(
                    f"Video file size exceeds the maximum limit of {settings.MAX_UPLOAD_SIZE_MB} MB."
                )

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": {"default": outtmpl_pattern},
        "ffmpeg_location": settings.FFMPEG_PATH,
        "max_filesize": max_bytes,
        "socket_timeout": 20,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": False,
        "match_filter": match_filter_cb,
        "progress_hooks": [progress_hook_cb],
        "hls_prefer_native": True,
        "enable_file_urls": False,
    }

    ydl = yt_dlp.YoutubeDL(ydl_opts)

    # Intercept all outbound HTTP requests inside yt-dlp (manifests, fragments, media streams, API calls)
    if hasattr(ydl, "_request_director") and hasattr(ydl._request_director, "send"):
        orig_send = ydl._request_director.send

        def safe_send(req):
            if hasattr(req, "url") and req.url:
                parsed = urlsplit(req.url)
                if parsed.scheme.lower() not in ("http", "https"):
                    raise SSRFProtectionError(
                        f"Unsupported protocol '{parsed.scheme}'. Only HTTP and HTTPS are allowed."
                    )
                try:
                    validate_url_security(req.url)
                except HTTPException as exc:
                    raise SSRFProtectionError(exc.detail) from exc
            return orig_send(req)

        ydl._request_director.send = safe_send

    try:
        with ssrf_guard_context():
            info_dict = ydl.extract_info(url, download=True)
    except Exception as exc:
        # Clean up any leftover files matching download_id
        for partial in temp_dir.glob(f"ytdl_{download_id}*"):
            partial.unlink(missing_ok=True)
        raise exc

    # Find resulting output file on disk
    downloaded_files = [
        f for f in temp_dir.glob(f"ytdl_{download_id}.*")
        if not f.name.endswith((".part", ".ytdl", ".temp"))
    ]

    if not downloaded_files:
        raise VideoDownloadError("Downloaded video file was not found on disk.")

    downloaded_path = downloaded_files[0]
    file_size = downloaded_path.stat().st_size

    if file_size == 0:
        downloaded_path.unlink(missing_ok=True)
        raise VideoDownloadError("Downloaded video file is empty (0 bytes).")

    if file_size > max_bytes:
        downloaded_path.unlink(missing_ok=True)
        raise FileSizeLimitError(
            f"Downloaded video file ({file_size / (1024 * 1024):.1f} MB) exceeds maximum allowed limit of "
            f"{settings.MAX_UPLOAD_SIZE_MB} MB."
        )

    title = "video"
    if isinstance(info_dict, dict):
        title = info_dict.get("title") or info_dict.get("id") or "video"

    return downloaded_path, title


def import_video_from_url(url: str) -> JobResponse:
    """Validate URL, download video safely via yt-dlp or direct stream, and create a job."""
    settings.ensure_dirs()
    validate_url_security(url)

    temp_path: Optional[Path] = None
    original_title = "imported_video"

    try:
        # If it has a direct video extension, try direct chunked streaming first
        if _is_direct_video_extension(url):
            ext = Path(urlsplit(url).path).suffix.lower()
            if ext not in settings.ALLOWED_EXTENSIONS:
                ext = ".mp4"
            candidate_temp = settings.JOBS_DIR / f"url_direct_{uuid.uuid4().hex}{ext}"
            try:
                temp_path = download_direct_video_stream(
                    url=url,
                    output_path=candidate_temp,
                    max_bytes=settings.max_upload_size_bytes,
                    timeout_sec=READ_TIMEOUT,
                )
                original_title = Path(urlsplit(url).path).stem or "direct_video"
            except NotDirectVideoError as html_err:
                candidate_temp.unlink(missing_ok=True)
                temp_path = None
                logger.info("Direct stream target returned HTML (%s); falling back to yt-dlp.", html_err)
            except VideoDownloadError:
                candidate_temp.unlink(missing_ok=True)
                raise

        # Use yt-dlp for platform URLs or when direct streaming is not applicable / falls back
        if temp_path is None:
            temp_path, original_title = download_with_ytdlp(
                url=url,
                temp_dir=settings.JOBS_DIR,
                max_bytes=settings.max_upload_size_bytes,
                max_duration_sec=settings.MAX_VIDEO_DURATION_SEC,
            )

        # Validate video integrity and audio track
        ext = temp_path.suffix.lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            ext = ".mp4"
        safe_filename = sanitize_filename(f"{original_title}{ext}")

        # Inspect video with FFprobe
        metadata = inspect_video(temp_path, original_filename=safe_filename)
        if not metadata.has_audio:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This video does not contain an audio track to process.",
            )

        if metadata.duration_seconds > settings.MAX_VIDEO_DURATION_SEC:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Video duration ({metadata.duration_seconds:.1f}s) exceeds maximum allowed duration "
                    f"of {settings.MAX_VIDEO_DURATION_SEC}s."
                ),
            )

        # Create job using existing job_manager method (moves temp_path into job_dir)
        job = job_manager.create_job(
            uploaded_temp_path=temp_path,
            original_filename=safe_filename,
        )
        return job

    except Exception as exc:
        if temp_path and temp_path.is_file():
            temp_path.unlink(missing_ok=True)
        raise map_download_exception_to_http(exc) from exc
