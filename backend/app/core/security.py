"""Security utilities for file validation, job isolation, and path traversal prevention."""

from __future__ import annotations

import hmac
import re
import secrets
import uuid
from pathlib import Path

from fastapi import HTTPException, status

from .config import settings

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

SAFE_FILENAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]")


def generate_job_id() -> str:
    """Generate a cryptographically random UUIDv4 job identifier."""
    return str(uuid.uuid4())


def generate_job_token() -> str:
    """Generate a secret per-job access token to prevent unauthorized access."""
    return secrets.token_urlsafe(24)


def verify_job_token(expected_token: str | None, provided_token: str | None) -> bool:
    """Constant-time token comparison when a job token is enforced."""
    if not expected_token:
        return True
    if not provided_token:
        return False
    return hmac.compare_digest(expected_token, provided_token)


def validate_job_id(job_id: str) -> str:
    """Ensure job_id is a strict UUIDv4 string and cannot traverse directories."""
    if not job_id or not UUID_PATTERN.match(job_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job ID format.",
        )
    return job_id.lower()


def resolve_job_dir(job_id: str, must_exist: bool = True) -> Path:
    """Resolve and validate the directory for a specific job inside JOBS_DIR."""
    clean_id = validate_job_id(job_id)
    base_dir = settings.JOBS_DIR.resolve()
    job_dir = (base_dir / clean_id).resolve()

    if base_dir not in job_dir.parents:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: invalid job path.",
        )

    if must_exist and not job_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{clean_id}' was not found or has expired.",
        )

    return job_dir


def sanitize_filename(filename: str) -> str:
    """Sanitize a user-supplied filename to prevent path injection."""
    base = Path(filename or "video.mp4").name
    stem = SAFE_FILENAME_PATTERN.sub("_", Path(base).stem).strip("._") or "video"
    ext = Path(base).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        ext = ".mp4"
    return f"{stem[:80]}{ext}"
