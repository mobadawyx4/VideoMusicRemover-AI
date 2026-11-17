# VideoMusicRemover AI

**Remove background music from videos while preserving speech and natural ambience — locally, with AI.**

VideoMusicRemover AI is a local web application that separates a video's soundtrack into **speech**, **environmental sound**, and **background music**, then rebuilds the audio without the music. Processing runs entirely on your computer, FFmpeg handles the media, and the **TIGER-DnR** neural audio separation model performs the stem separation.

## Contents

- [How it works](#how-it-works)
- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
  - [Windows 10 / 11](#windows-10--11)
  - [Linux](#linux)
- [First run and model download](#first-run-and-model-download)
- [Using the application](#using-the-application)
- [Supported formats and limits](#supported-formats-and-limits)
- [Starting, stopping, and updating](#starting-stopping-and-updating)
- [Configuration](#configuration)
- [Privacy](#privacy)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)
- [Support](#support)

## How it works

1. FFmpeg extracts the audio track as 44.1 kHz stereo PCM.
2. TIGER-DnR separates it into speech, environmental effects, and music stems.
3. Your mix settings are applied to the stems and the result is normalized to avoid clipping.
4. FFmpeg combines the new audio with the original video and writes an MP4 file.

Processing is local. Runtime network access is limited to the one-time model download from Hugging Face, the optional video URL import, and the interface's web-font request. Video and audio data never leave your machine.

## Features

- **Three-stem separation** — isolates dialogue, environmental sounds, and music instead of applying a generic audio filter.
- **Adjustable mix** — set music removal from 0% (keep music) to 100% (remove music), and boost or reduce speech and environmental sound independently.
- **Three processing modes** — Fast (single pass with 10 s chunks), Balanced (default; single pass with 8 s chunks and a 1.5 s crossfade), and High Quality (three separate passes over the dialogue, effects, and music branches).
- **Instant remix** — adjust the mix on a completed job without running the neural network again.
- **Flexible input** — upload a file, import a public video URL, or try the built-in sample video.
- **Useful outputs** — download the processed MP4, the original video, the processed WAV, and each separated stem as WAV.
- **CPU or NVIDIA GPU** — CUDA is used when a compatible GPU and driver are available, with automatic CPU fallback if CUDA execution fails at runtime.
- **Local-first** — no account, no cloud processing, and temporary job files are deleted automatically.
- **Optional LAN access** — expose the web interface to other devices on your trusted network.

## Requirements

| Component | Requirement |
|---|---|
| Operating system | Windows 10/11 (64-bit x64) or a supported 64-bit Linux distribution |
| Python | 3.10, 3.11, or 3.12, 64-bit |
| Node.js | 18, 20, or 22+ with npm (required by Vite 6) |
| FFmpeg | `ffmpeg` and `ffprobe` available on `PATH`, or placed in `tools/ffmpeg` |
| RAM | 8 GB or more recommended for typical 1080p videos |
| Disk space | 2 GB minimum on Windows; 6 GB or more recommended, especially for CUDA |
| GPU | Optional NVIDIA GPU for CUDA 12.1: driver 527.41+ and compute capability 5.0+ (Maxwell or newer) |

Notes:

- The Windows PyTorch 2.5.1 wheels are x64 only. **Windows on ARM is not supported** and the installer stops with a clear message.
- Python 3.13 and 32-bit Python are not supported by the pinned dependency set.
- The Linux installer checks for at least 500 MB free; the Windows installer requires at least 2 GB and warns below 6 GB.
- No hard RAM check is performed. Memory use depends on video resolution, duration, and processing mode.
- The complete TIGER-DnR download is about 17 MB (a 17.1 MB `model.safetensors` file plus a small config). The application also requires at least 300 MB free (`MIN_DISK_SPACE_MB`) before starting a model download.
- FFmpeg binaries in `tools/ffmpeg` are optional and are not included in the repository. On Windows they must be `ffmpeg.exe` and `ffprobe.exe`; on Linux they must be executable `ffmpeg` and `ffprobe`.

## Quick start

Choose your platform. Both installers create or reuse `.venv`, install the correct PyTorch build, verify dependency versions, and launch the application.

### Windows 10 / 11

**1. Get the project**

```powershell
git clone https://github.com/mobadawyx4/VideoMusicRemover-AI.git
cd VideoMusicRemover-AI
```

Git is only needed to clone or update. You can also download the repository ZIP from GitHub.

**2. Run the installer**

```powershell
.\install.ps1
```

The installer checks:

- Windows 10/11, 64-bit x64
- Python 3.10–3.12, 64-bit
- Node.js LTS and npm
- Working FFmpeg and FFprobe executables
- NVIDIA driver version and CUDA capability
- Free disk space

If a supported prerequisite is missing and Winget is available, the installer asks before installing it from the official Winget source:

| Missing component | Winget package |
|---|---|
| Python 3.12 (64-bit) | `Python.Python.3.12` |
| Node.js LTS | `OpenJS.NodeJS.LTS` |
| FFmpeg and FFprobe | `Gyan.FFmpeg` |

The prompt defaults to yes. Winget may display a Windows UAC permission prompt for some packages; this comes from the package installer. The installer itself does not request elevation, does not change the system-wide `PATH`, and does not modify Windows security settings.

After prerequisites are ready, the installer creates or reuses `.venv`, creates `.env` from `.env.example` if needed, selects a PyTorch build, verifies the application, and starts it.

**PyTorch selection (`-TorchMode`)**

| Mode | Behavior |
|---|---|
| `Auto` (default) | Uses CUDA 12.1 when `nvidia-smi` reports a compatible NVIDIA GPU and driver; otherwise uses the CPU build. If CUDA installation or runtime verification fails, it falls back to the CPU build. |
| `CPU` | Forces the official PyTorch 2.5.1 CPU build. |
| `CUDA` | Requires a compatible NVIDIA GPU and driver. Installation or runtime verification failures are reported as errors instead of being silently downgraded. |

The installer verifies the actual installed build. CUDA mode requires `torch.cuda.is_available()` to be true and `torch.version.cuda` to report 12.1. After CPU fallback, it verifies that CUDA is disabled.

**Options**

| Option | Purpose |
|---|---|
| `-AutoInstallPrerequisites` | Install any missing supported prerequisite with Winget without prompting |
| `-AutoInstallFfmpeg` | Install only FFmpeg/FFprobe with Winget without prompting |
| `-NonInteractive` | Never prompt; missing prerequisites must already be installed unless an auto-install flag is set |
| `-TorchMode Auto\|CPU\|CUDA` | Select the PyTorch build |
| `-NoLaunch` | Finish installation without starting the application |

For unattended installation:

```powershell
.\install.ps1 -AutoInstallPrerequisites -NonInteractive -NoLaunch
```

**Manual prerequisite installation**

If Winget is unavailable, install 64-bit versions manually:

```powershell
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Gyan.FFmpeg -e
```

Official downloads:

- Python 3.12 (64-bit): <https://www.python.org/downloads/windows/>
- Node.js LTS: <https://nodejs.org/en/download>
- FFmpeg: <https://ffmpeg.org/download.html>

Close and reopen PowerShell after installing prerequisites so `PATH` changes take effect, then run `.\install.ps1` again.

If PowerShell blocks local scripts, use a process-scoped policy and unblock the downloaded files instead of disabling security permanently:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
Unblock-File .\install.ps1, .\start.ps1, .\stop.ps1, .\update.ps1
.\install.ps1
```

### Linux

The Linux installer supports Ubuntu, Debian, Linux Mint, Pop!_OS, Fedora, Arch Linux, and compatible distributions. It does **not** install system packages or run `sudo`; install the prerequisites with your package manager first.

**Ubuntu / Debian / Linux Mint / Pop!_OS**

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg git
```

**Fedora**

```bash
sudo dnf install -y python3 python3-pip ffmpeg git nodejs npm
```

FFmpeg may require the RPM Fusion repositories on Fedora.

**Arch Linux**

```bash
sudo pacman -S python python-pip ffmpeg git nodejs npm
```

**Node.js version**

Install Node.js 18, 20, or 22+ with npm. The Node.js version in older distribution repositories may be too old for Vite 6; use the official Node.js LTS packages or a version manager such as nvm.

**Install and launch**

```bash
git clone https://github.com/mobadawyx4/VideoMusicRemover-AI.git
cd VideoMusicRemover-AI
chmod +x install.sh
./install.sh
```

The installer:

1. Detects the distribution and checks Python 3.10–3.12, the `venv` module, Node.js, npm, FFmpeg, FFprobe, and free disk space.
2. Creates or reuses `.venv` and `.env`.
3. Installs the official PyTorch 2.5.1 CUDA 12.1 build when `nvidia-smi` is available; otherwise installs the CPU build.
4. Verifies Python dependency versions against `backend/requirements.txt`.
5. Checks the model cache without downloading weights.
6. Installs frontend npm dependencies and validates the application.
7. Launches the application unless `--no-launch` is used.

```bash
./install.sh --no-launch   # install only
./install.sh --help        # show options
```

On Linux, CUDA selection is based on whether `nvidia-smi` is available. The installer does not perform the Windows-style driver compatibility gate or automatic installation fallback. The CUDA build still runs on CPU when `torch.cuda.is_available()` is false, and the backend selects CPU at runtime in that case.

## First run and model download

The TIGER-DnR model is **not downloaded during installation**.

- Installation only checks whether a complete model cache already exists.
- The first time you start processing a video (the **Remove Music** action), the application downloads the model from [JusperLee/TIGER-DnR](https://huggingface.co/JusperLee/TIGER-DnR) into `data/models`.
- Later jobs reuse the local cache. Once the cache is complete, local file processing works offline.
- Concurrent first-use requests are serialized, so the model is downloaded only once.
- An interrupted download resumes into the same cache when you retry.
- Existing model files are preserved by updates and reinstalls.

The application requires at least 300 MB free before downloading and reports an error if space is insufficient. The complete model download is about 17 MB, but keep additional free space for job files and PyTorch.

Video URL import still requires an internet connection; only the model cache works offline.

## Using the application

1. Start the application with `.\start.ps1` (Windows) or `./start.sh` (Linux).
2. Open <http://localhost:5173>.
3. Upload a video, paste a public video URL, or click **Try Instant Sample Video**.
4. Adjust **Music Removal Strength**, **Human Speech & Dialogue Level**, and **Environmental Sounds & SFX Level** if needed.
5. Choose a precision mode: **Fast**, **Balanced**, or **High Quality**.
6. Click **Remove Music** and wait for processing to complete.
7. Download the processed MP4, the original video, the processed WAV, or the individual speech, effects, and music stems.

After a job completes, **Apply Instant Stem Remix** rebuilds the mix with new level settings without repeating the AI separation step.

### Input sources

| Source | Details |
|---|---|
| File upload | Drag and drop or browse for a supported video file |
| Video URL | Public YouTube, Instagram, Vimeo, TikTok, X (Twitter), Facebook, and other links supported by yt-dlp, plus direct HTTP/HTTPS video URLs |
| Sample video | Generates a short local sample job for trying the workflow |

Private videos, DRM-protected streams, and downloads that require login credentials are not supported.

## Supported formats and limits

| Item | Value |
|---|---|
| Input containers | `.mp4`, `.mov`, `.mkv`, `.webm` |
| Required streams | One video stream and one audio stream |
| Maximum upload size | 500 MB |
| Maximum duration | 30 minutes |
| Processed video output | MP4 (video stream copied when compatible, otherwise H.264 CRF 18) with AAC 192 kbps audio |
| Audio outputs | WAV: processed mix, speech stem, effects stem, music stem |
| Job retention | 1 hour by default, cleaned up every 5 minutes |

Upload size, duration, and retention are configurable in `.env` (see [Configuration](#configuration)). The processed video is always written as MP4; WebM or MKV input may require re-encoding because those codecs are not always compatible with the MP4 container.

## Starting, stopping, and updating

Both start scripts verify the installation, run the installer automatically on first use if necessary, start the backend and frontend, and wait for both health checks to pass.

### Windows

```powershell
.\start.ps1                 # start and open the browser
.\start.ps1 -NoBrowser      # start without opening the browser
.\start.ps1 -Detach         # start in the background
.\start.ps1 -Lan            # allow access from other devices on your network

.\stop.ps1                  # stop the processes started by this project
```

### Linux

```bash
./start.sh                  # start and open the browser when a desktop is available
./start.sh --no-browser     # start without opening the browser
./start.sh --daemon         # start in the background
./start.sh --lan            # allow access from other devices on your network

./stop.sh                   # stop the processes started by this project
```

Use `Ctrl+C` in the terminal running `start.ps1`/`start.sh` to stop the application, or run the stop script from another terminal. The stop scripts only terminate processes recorded in `.runtime`.

### Updating

**Windows**

```powershell
.\update.ps1
```

| Option | Purpose |
|---|---|
| `-NoPull` | Skip `git pull` and refresh dependencies from the current local files |
| `-NoLaunch` | Update without launching the application |
| `-TorchMode Auto\|CPU\|CUDA` | Forwarded to the installer; `Auto` selects CUDA when compatible, otherwise CPU |

The Windows updater stops the application, backs up `.env` to `.runtime\backups`, preserves `data\models` and job data, and skips `git pull` when the working tree has local changes. It then reruns the installer, which reuses `.venv` and only reinstalls dependencies whose versions or lock files have changed.

**Linux**

```bash
./update.sh
```

The Linux updater stops the application, backs up `.env`, pulls with `git pull --ff-only`, and reruns `install.sh`, which launches the application again. A fast-forward-only pull fails safely if local changes conflict with upstream changes. Do not rely on the Linux updater to merge local modifications.

Your `.env` configuration, cached model in `data/models`, and job data are preserved during normal updates. Neither updater deletes `.venv`, `frontend/node_modules`, or user data.

## Configuration

The installers create `.env` from `.env.example` if it does not already exist. Edit `.env` and restart the application to apply changes.

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Backend port |
| `FRONTEND_PORT` | `5173` | Frontend port |
| `ENABLE_LAN_ACCESS` | `false` | Expose the frontend to your local network |
| `MAX_UPLOAD_SIZE_MB` | `500` | Maximum upload/download size |
| `MAX_VIDEO_DURATION_SEC` | `1800` | Maximum video duration in seconds |
| `JOB_TTL_SECONDS` | `3600` | How long completed jobs are retained |
| `CLEANUP_INTERVAL_SECONDS` | `300` | Expired-job cleanup interval |
| `MIN_DISK_SPACE_MB` | `300` | Free space required before a model download |
| `DEFAULT_SEPARATION_MODE` | `balanced` | Initial separation mode |
| `DEFAULT_MUSIC_REMOVAL_STRENGTH` | `1.0` | Initial music removal strength |
| `DEFAULT_SPEECH_GAIN` | `1.0` | Initial speech level multiplier |
| `DEFAULT_EFFECTS_GAIN` | `1.0` | Initial effects level multiplier |
| `TORCH_NUM_THREADS` | `4` in `.env.example`; CPU count if unset | PyTorch CPU thread count |
| `FFMPEG_PATH` | auto-detected | Explicit FFmpeg binary path |
| `FFPROBE_PATH` | auto-detected | Explicit FFprobe binary path |

When LAN access is enabled, the frontend is exposed on the network while the backend remains bound to localhost and is reached through the Vite proxy. Only enable LAN mode on a trusted network.

## Privacy

- Video and audio processing happens on your computer. Files are not uploaded to a third-party processing service.
- The application itself has no accounts, analytics, telemetry, or tracking.
- The interface loads the Inter and JetBrains Mono fonts from Google Fonts, which makes a request to `fonts.googleapis.com` and `fonts.gstatic.com`.
- Video URL import downloads the source video directly from the platform or URL you provide.
- The model weights are downloaded once from Hugging Face and then stored locally.
- Temporary job files under `data/jobs` are deleted automatically after the configured job lifetime (1 hour by default).
- `.env`, job data, and the model cache remain on your machine.

## Troubleshooting

### PowerShell blocks the installer

Use a process-scoped policy and unblock the scripts:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
Unblock-File .\install.ps1, .\start.ps1, .\stop.ps1, .\update.ps1
.\install.ps1
```

The installer never changes execution policy or Windows Defender settings.

### Winget is unavailable or shows a permission prompt

Winget ships with modern Windows 10/11. If it is missing, install the prerequisites manually using the commands in the [Windows section](#windows-10--11), then rerun `.\install.ps1`.

Some packages display a UAC prompt. The project does not request elevation itself and does not change the system-wide `PATH`.

### Python is missing, 32-bit, or has an unsupported version

Install 64-bit Python 3.10, 3.11, or 3.12:

```powershell
winget install --id Python.Python.3.12 -e
```

Or use the official installer from <https://www.python.org/downloads/windows/> and enable **Add Python to PATH**. Close and reopen PowerShell before retrying.

### Node.js or npm is missing or too old

Vite 6 requires Node.js 18, 20, or 22+ with npm:

```powershell
winget install --id OpenJS.NodeJS.LTS -e
```

On Linux, use the official Node.js LTS packages or nvm if your distribution provides an older version.

### FFmpeg or FFprobe is missing

**Windows**

```powershell
winget install --id Gyan.FFmpeg -e
```

**Ubuntu / Debian / Linux Mint**

```bash
sudo apt install ffmpeg
```

**Fedora**

```bash
sudo dnf install ffmpeg
```

**Arch Linux**

```bash
sudo pacman -S ffmpeg
```

Restart the terminal after installation. Alternatively, place working binaries in `tools/ffmpeg` (`ffmpeg.exe` and `ffprobe.exe` on Windows, `ffmpeg` and `ffprobe` on Linux).

### The AI model download fails on first use

1. Confirm that you have internet access and enough free disk space.
2. Keep `data/models` intact so the partial download can resume.
3. Retry processing.
4. If you use a proxy or corporate firewall, allow `huggingface.co` and `cdn-lfs.huggingface.co`.

Once the cache is complete, local file processing works offline.

### NVIDIA GPU acceleration is not enabled

The Windows installer selects CUDA 12.1 only when it verifies:

- An NVIDIA GPU is present.
- The driver is version 527.41 or newer.
- Compute capability is 5.0 (Maxwell) or newer.
- PyTorch can access the GPU at runtime.

Steps:

1. Run `nvidia-smi` in PowerShell. If it fails, install or update the NVIDIA driver from <https://www.nvidia.com/Download/index.aspx>.
2. Rerun `.\install.ps1` and read the acceleration line in the summary.
3. Use `.\install.ps1 -TorchMode CUDA` to require CUDA and fail clearly instead of falling back.
4. Use `.\install.ps1 -TorchMode CPU` to force CPU mode.

An NVIDIA GPU alone is not sufficient: an old driver or a pre-Maxwell GPU results in CPU mode. If CUDA model loading fails at runtime, the backend automatically falls back to CPU and logs the reason.

### A video is rejected

The application accepts `.mp4`, `.mov`, `.mkv`, and `.webm` files that contain both a video stream and an audio stream, up to 500 MB and 30 minutes. Rename or remux the file if its extension does not match its container, and add an audio track if it has none.

### The application does not open or a port is in use

The default ports are:

- Frontend: `5173`
- Backend: `8000`

Stop any previous instance, then restart:

```powershell
.\stop.ps1
.\start.ps1
```

```bash
./stop.sh
./start.sh
```

If another service uses a port, change `FRONTEND_PORT` or `PORT` in `.env` and restart. Linux writes startup logs to `.runtime/backend.log` and `.runtime/frontend.log`; Windows writes `.runtime/backend.out.log`, `.runtime/backend.err.log`, `.runtime/frontend.out.log`, and `.runtime/frontend.err.log`.

### The existing .venv cannot be reused

The installers never delete `.venv`, `frontend/node_modules`, user data, or model caches. If `.venv` is corrupted or was created with an unsupported Python version, rename it and rerun the installer:

```powershell
Rename-Item .venv .venv.broken
.\install.ps1
```

```bash
mv .venv .venv.broken
./install.sh
```

You can remove the renamed folder yourself after confirming that the new environment works.

### The update skips `git pull`

The Windows updater skips `git pull` when local uncommitted changes are present so it cannot overwrite your work. Commit or stash your changes, then run `.\update.ps1` again, or use `-NoPull` to only refresh dependencies from the current files.

## Development

Backend development:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
python -m pip install "torch==2.5.1+cpu" --index-url https://download.pytorch.org/whl/cpu
```

On Windows, activate with `.venv\Scripts\Activate.ps1`.

Run the backend test suite from the repository root:

```bash
python -m pytest -q
```

`pytest.ini` restricts discovery to `backend/tests`.

Frontend development:

```bash
cd frontend
npm install
npm run build      # production build
npm run dev        # Vite dev server on port 5173
```

The simplest way to run the full stack is `./start.sh` or `.\start.ps1`, which starts the FastAPI backend and the Vite frontend together.

## License

This repository does not currently include a project-level `LICENSE` file.

Third-party components retain their own terms:

- Vendored TIGER model code: MIT License — <https://github.com/JusperLee/TIGER>
- TIGER-DnR model weights: see the model card at <https://huggingface.co/JusperLee/TIGER-DnR>

## Support

- GitHub repository: <https://github.com/mobadawyx4/VideoMusicRemover-AI>
- Report bugs and request features through GitHub Issues.
- Star the repository if you find the project useful.
