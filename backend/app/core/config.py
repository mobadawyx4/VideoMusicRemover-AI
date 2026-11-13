"""Application configuration for VideoMusicRemover AI backend."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Set

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _resolve_binary(name: str, env_var: str) -> str:
    """Resolve binary path from environment variable, bundled tools dir, or PATH."""
    explicit = os.environ.get(env_var)
    if explicit and Path(explicit).is_file():
        return str(Path(explicit).resolve())

    # Check Windows .exe as well as POSIX binary name inside tools/ffmpeg
    for candidate_name in (name, f"{name}.exe"):
        bundled = PROJECT_ROOT / "tools" / "ffmpeg" / candidate_name
        if bundled.is_file():
            return str(bundled.resolve())

    found = shutil.which(name)
    if found:
        return found

    return str(PROJECT_ROOT / "tools" / "ffmpeg" / name)


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(BACKEND_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "VideoMusicRemover AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Network & Localhost Security Settings (localhost by default)
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    FRONTEND_HOST: str = "127.0.0.1"
    FRONTEND_PORT: int = 5173
    ENABLE_LAN_ACCESS: bool = False

    # CORS settings
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    # Upload and processing limits (configurable via env vars)
    MAX_UPLOAD_SIZE_MB: int = 500
    MAX_VIDEO_DURATION_SEC: int = 1800  # 30 minutes default max duration
    ALLOWED_EXTENSIONS: Set[str] = Field(
        default_factory=lambda: {".mp4", ".mov", ".mkv", ".webm"}
    )

    # Storage paths
    DATA_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data")
    JOBS_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "jobs")
    MODELS_DIR: Path = Field(default_factory=lambda: PROJECT_ROOT / "data" / "models")
    MIN_DISK_SPACE_MB: int = 300

    # Automatic temporary file cleanup
    JOB_TTL_SECONDS: int = 3600  # 1 hour retention by default
    CLEANUP_INTERVAL_SECONDS: int = 300  # Check every 5 minutes

    # AI Model configuration
    MODEL_REPO_ID: str = "JusperLee/TIGER-DnR"
    DEFAULT_SEPARATION_MODE: str = "balanced"  # "fast", "balanced", "high_quality"
    DEFAULT_MUSIC_REMOVAL_STRENGTH: float = 1.0  # 0.0 (keep all music) to 1.0 (remove all music)
    DEFAULT_SPEECH_GAIN: float = 1.0
    DEFAULT_EFFECTS_GAIN: float = 1.0
    TORCH_NUM_THREADS: int = Field(
        default_factory=lambda: max(1, (os.cpu_count() or 4))
    )

    # Media tools
    FFMPEG_PATH: str = Field(
        default_factory=lambda: _resolve_binary("ffmpeg", "FFMPEG_PATH")
    )
    FFPROBE_PATH: str = Field(
        default_factory=lambda: _resolve_binary("ffprobe", "FFPROBE_PATH")
    )

    @property
    def effective_backend_host(self) -> str:
        return "0.0.0.0" if self.ENABLE_LAN_ACCESS else self.HOST

    @property
    def effective_frontend_host(self) -> str:
        return "0.0.0.0" if self.ENABLE_LAN_ACCESS else self.FRONTEND_HOST

    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    def ensure_dirs(self) -> None:
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self.MODELS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
