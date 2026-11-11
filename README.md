# SilentTrack AI — Neural Video Background Music Remover

**SilentTrack AI** is a production-ready full-stack web application that removes background music from videos using deep neural audio source separation (**TIGER-DnR**) while preserving **human speech, dialogue, and natural environmental sound effects** (footsteps, room tone, applause, nature ambience) and maintaining 100% of the original video's resolution, frame rate, and aspect ratio.

---

## Key Features

- **Drag-and-Drop Video Upload**: Supports `.MP4`, `.MOV`, `.MKV`, and `.WEBM` containers with chunked disk streaming for large files (up to 500 MB by default, configurable via environment variables).
- **3-Stem Neural Audio Source Separation (`TIGER-DnR`)**:
  - Explicitly separates audio into **Human Speech / Dialogue**, **Environmental Sounds / SFX**, and **Background Music**.
  - Preserves natural stereo imaging via STFT Wiener ratio projection (`speech + effects + music == original`).
- **Adjustable Mix & Instant Stem Remixing**:
  - **Music Removal Strength** (`0%` to `100%`)
  - **Speech / Dialogue Gain** (`0%` to `200%`)
  - **Environmental Sounds / SFX Gain** (`0%` to `200%`)
  - **Instant Remix**: Adjust sliders after processing to remix cached stems and re-mux the video in ~1 second without re-running neural network inference.
- **Lossless Video Stream Recombination**:
  - Uses FFmpeg stream copy (`-c:v copy`) whenever container-compatible so the output video retains the exact original resolution, frame rate, aspect ratio, and visual fidelity with zero re-encoding generation loss.
- **Before & After Audio Comparison Studio**:
  - Interactive dual waveform visualizer (Original Mix vs. Processed Clean Audio).
  - Real-time audition toggles for **Original Audio**, **Processed Clean Audio**, **Isolated Speech Stem**, **Isolated Environmental Stem**, and **Removed Background Music Stem**.
  - Stem RMS energy telemetry (`dBFS`) and music suppression (`dB`) metrics.
- **Security & Automatic Cleanup**:
  - Per-job UUIDv4 workspaces protected by cryptographic access tokens.
  - Automatic background TTL cleanup of temporary files.

---

## Screenshots Placeholders

> Replace these placeholders with screenshots of your deployment when publishing to GitHub:

- `docs/screenshots/01-upload-dashboard.png` — *Obsidian Dark Drag-and-Drop Upload Area & Hero Section*
- `docs/screenshots/02-ai-processing-pipeline.png` — *Real-Time Multi-Stage TIGER-DnR Progress Tracker*
- `docs/screenshots/03-video-preview-and-controls.png` — *Original vs. Music-Removed Video Preview & Mix Sliders*
- `docs/screenshots/04-audio-comparison-studio.png` — *Before/After Dual Waveform Studio & Stem Audition Toggles*

---

## Why TIGER-DnR for AI Audio Separation?

Most conventional music source separation models (such as 4-stem Demucs / HTDemucs trained on MUSDB18) partition audio into `vocals`, `drums`, `bass`, and `other`. When applied to general videos (vlogs, films, interviews, gaming, documentaries):
1. Keeping only the `vocals` stem strips out **environmental sound effects** (footsteps, doors, wind, crowd ambience, object impacts) because a music-only model routes percussive SFX into `drums` and ambient textures into `other`.
2. Singing vocals in background songs are often conflated with spoken dialogue.

**SilentTrack AI** integrates **TIGER-DnR** (*Time-frequency Interleaved Gain Extraction and Reconstruction*, trained on the cinematic Divide-and-Remaster dataset), which is purpose-built for 3-stem film/video audio separation:
1. **Dialogue / Speech Stem**
2. **Environmental Sound Effects (SFX) Stem**
3. **Background Music Stem**

### Technical Limitations & Practical Notes
- **Singing Vocals vs. Spoken Dialogue**: When background music contains loud foreground singing overlapping simultaneously with spoken dialogue in the same frequency band (300 Hz – 3.5 kHz), minor vocal bleed can occur. Reducing the Music Removal Strength slider to `85%–90%` often yields a more natural blend on heavily compressed mixes.
- **Highly Reverberant Rooms**: Heavy room reverb tails shared between music and speech may slightly attenuate during aggressive (`100%`) music suppression.

---

## Project Architecture

```text
silenttrack-ai/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes.py              # REST endpoints (upload, process, status, remix, media, health)
│   │   ├── core/
│   │   │   ├── config.py              # Environment-driven configuration & binary resolution
│   │   │   ├── schemas.py             # Pydantic request/response models
│   │   │   └── security.py            # UUID validation, token isolation, filename sanitization
│   │   ├── services/
│   │   │   ├── separation/
│   │   │   │   └── tiger_separator.py # TIGER-DnR neural inference, chunking & stereo projection
│   │   │   ├── demo_service.py        # Synthetic sample video generator
│   │   │   ├── job_manager.py         # Background worker pool & automatic TTL file cleanup
│   │   │   └── media_service.py       # FFprobe inspection, FFmpeg extraction, muxing & waveforms
│   │   ├── vendor/
│   │   │   └── tiger/                 # Vendored TIGER-DnR PyTorch architecture
│   │   └── main.py                    # FastAPI application entrypoint
│   ├── tests/
│   │   └── test_backend.py            # Automated end-to-end & unit test suite
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── AudioComparisonStudio.jsx
│   │   │   ├── Navbar.jsx
│   │   │   ├── ProgressPipeline.jsx
│   │   │   └── UploadZone.jsx
│   │   ├── lib/
│   │   │   ├── api.js
│   │   │   └── formatters.js
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   ├── index.html
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.js
├── docker/
│   ├── Dockerfile.backend
│   ├── Dockerfile.frontend
│   └── nginx.conf
├── scripts/
│   └── start_dev.sh
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

---

## Prerequisites & FFmpeg Installation

- **Python**: `3.10` – `3.12`
- **Node.js**: `18+` or `22+` (with `npm`)
- **FFmpeg & FFprobe**: Required for audio extraction, container inspection, and video stream muxing.

### Installing FFmpeg
- **Ubuntu / Debian / Linux Mint**:
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```
- **macOS (Homebrew)**:
  ```bash
  brew install ffmpeg
  ```
- **Windows (Winget)**:
  ```powershell
  winget install Gyan.FFmpeg
  ```
- **Bundled Static Binary**: SilentTrack AI also automatically checks `tools/ffmpeg/ffmpeg` and `tools/ffmpeg/ffprobe` if system-wide packages are not installed.

---

## Local Development Setup

### 1. Clone and Configure Environment
```bash
cd silenttrack-ai
cp .env.example .env
```

### 2. Backend Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 3. AI Model Setup (`JusperLee/TIGER-DnR`)
On the first separation job, SilentTrack AI automatically downloads and caches the Apache-2.0 licensed `JusperLee/TIGER-DnR` weights (~71 MB) from HuggingFace Hub into `data/models/`.
To pre-download the model manually:
```bash
PYTHONPATH=backend .venv/bin/python -c "from app.services.separation import separator_service; separator_service.load_model()"
```

### 4. Frontend Setup
```bash
cd frontend
npm install
```

### 5. Run the Application Locally

**Option A — One-command startup script:**
```bash
./scripts/start_dev.sh
```

**Option B — Start Backend and Frontend in separate terminals:**

Terminal 1 (Backend on port `8000`):
```bash
cd backend
PYTHONPATH=. ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Terminal 2 (Frontend on port `5173`):
```bash
cd frontend
npm run dev
```

Open **`http://localhost:5173`** in your browser.

---

## Running Automated Tests

```bash
cd backend
PYTHONPATH=. ../.venv/bin/pytest -v
```

---

## Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | `8000` | FastAPI backend port |
| `MAX_UPLOAD_SIZE_MB` | `500` | Maximum allowed video file size in MB |
| `MAX_VIDEO_DURATION_SEC` | `1800` | Maximum allowed video duration in seconds (30 mins) |
| `JOB_TTL_SECONDS` | `3600` | Time in seconds before temporary job files are auto-deleted |
| `CLEANUP_INTERVAL_SECONDS` | `300` | Interval between automatic cleanup sweeps |
| `MODEL_REPO_ID` | `JusperLee/TIGER-DnR` | HuggingFace repository ID for TIGER-DnR weights |
| `DEFAULT_SEPARATION_MODE` | `balanced` | Default AI precision mode (`fast`, `balanced`, `high_quality`) |
| `TORCH_NUM_THREADS` | CPU core count | Number of CPU threads allocated to PyTorch inference |
| `FFMPEG_PATH` | Auto-detected | Optional explicit path to `ffmpeg` binary |
| `FFPROBE_PATH` | Auto-detected | Optional explicit path to `ffprobe` binary |

---

## Deployment Instructions

### Docker Compose (Recommended for Self-Hosting / VPS / GPU Cloud)
```bash
docker compose up --build -d
```
- Frontend UI: `http://localhost:5173`
- Backend API: `http://localhost:8000/api/health`

### Cloud Deployment (Frontend + Backend Split)
- **Backend (Render / Railway / AWS ECS / RunPod / GCP Cloud Run)**:
  - Build using `docker/Dockerfile.backend`.
  - Mount a persistent volume to `/app/data` so model weights (`data/models`) remain cached across container restarts.
- **Frontend (Vercel / Netlify / Cloudflare Pages)**:
  - Root directory: `frontend`
  - Build command: `npm run build`
  - Output directory: `dist`
  - Set environment variable `VITE_API_BASE_URL=https://your-backend-domain.com`

---

## Troubleshooting

1. **`FFprobe binary not found` or `ffmpeg_available: false`**:
   Ensure `ffmpeg` and `ffprobe` are either in your system `PATH`, placed in `tools/ffmpeg/`, or specified via `FFMPEG_PATH` and `FFPROBE_PATH` in `.env`.
2. **`This video does not contain an audio track`**:
   The uploaded video has a video stream only. Upload a video that includes an audio stream.
3. **Slow processing on CPU**:
   Select **Fast** or **Balanced** separation mode in the UI. On CPU, **Fast** mode runs a single-pass TIGER-DnR separation with STFT spatial stereo projection, which is ~3× faster than the 3-model **High Quality** ensemble mode.
