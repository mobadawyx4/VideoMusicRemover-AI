# SilentTrack AI — Neural Video Background Music Remover

**SilentTrack AI** is an AI-powered web application that removes background music from videos (`MP4`, `MOV`, `MKV`, `WEBM`) while preserving **human speech, dialogue, and natural environmental sounds** (footsteps, room ambience, applause, nature sounds) using the **TIGER-DnR** 3-stem neural source separation model. Everything runs locally on your own computer.

---

## Quick Start Summary

### Windows (PowerShell)
```powershell
.\install.ps1
.\start.ps1
```

### Linux (Ubuntu / Debian / Linux Mint)
```bash
chmod +x install.sh start.sh stop.sh update.sh
./install.sh
./start.sh
```

Once started, SilentTrack AI opens automatically at:
- **Application UI**: [`http://localhost:5173`](http://localhost:5173)
- **Backend API**: [`http://127.0.0.1:8000`](http://127.0.0.1:8000)
- **API Health Check**: [`http://127.0.0.1:8000/api/health`](http://127.0.0.1:8000/api/health)

---

## Table of Contents

1. [Hardware Requirements](#1-hardware-requirements)
2. [Windows Installation (PowerShell)](#2-windows-installation-powershell)
3. [Linux Installation](#3-linux-installation)
4. [Manual Installation](#4-manual-installation)
5. [One-Command Startup](#5-one-command-startup)
6. [Stopping the Application](#6-stopping-the-application)
7. [Updating the Application](#7-updating-the-application)
8. [AI Model Download & Offline Mode](#8-ai-model-download--offline-mode)
9. [FFmpeg Setup](#9-ffmpeg-setup)
10. [Localhost Access](#10-localhost-access)
11. [LAN Access for Other Devices](#11-lan-access-for-other-devices)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Hardware Requirements

| Component | Minimum Requirement | Recommended Specification |
| :--- | :--- | :--- |
| **Operating System** | Windows 10/11 (64-bit) or Ubuntu 20.04+ / Debian 11+ / Linux Mint 21+ | Windows 11 or Ubuntu 22.04 / 24.04 LTS / Linux Mint 22 |
| **Processor (CPU)** | 4-core x86_64 CPU | 8+ core modern Intel Core / AMD Ryzen CPU |
| **Memory (RAM)** | 4 GB RAM | 8 GB – 16 GB RAM |
| **GPU (Optional)** | None required (automatic CPU mode) | NVIDIA CUDA-capable GPU (4 GB+ VRAM) for faster inference |
| **Disk Space** | 1.5 GB free space (for Python `.venv`, `node_modules`, and ~71 MB AI model cache) | 5 GB+ SSD space (for temporary video processing jobs) |

---

## 2. Windows Installation (PowerShell)

### Step 1: Open PowerShell in the Project Folder
1. Download or clone the repository and open **Windows PowerShell** inside the `silenttrack-ai` folder:
   ```powershell
   git clone https://github.com/<your-username>/silenttrack-ai.git
   cd silenttrack-ai
   ```
2. If Windows blocks local script execution, allow scripts for the current PowerShell session only:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```

### Step 2: Run the Automated Installer
```powershell
.\install.ps1
```

What `.\install.ps1` does automatically:
- `[1/5] Checking prerequisites...` — Detects your Windows version, checks free disk space, and verifies **Python 3.10–3.12**, **Node.js**, **npm**, and **FFmpeg/FFprobe**. If FFmpeg is missing, it offers to install it automatically via **Winget** (`Gyan.FFmpeg`).
- `[2/5] Setting up Python environment...` — Creates an isolated `.venv` virtual environment and initializes `.env` from `.env.example` (preserving any existing `.env`).
- `[3/5] Installing backend dependencies...` — Installs FastAPI, PyTorch, and audio libraries into `.venv` (skipping reinstallation if already up to date) and caches the **TIGER-DnR** AI model weights locally.
- `[4/5] Installing frontend dependencies...` — Installs React, Vite, and Tailwind CSS packages in `frontend/` (skipping reinstallation if already up to date).
- `[5/5] Validating installation...` — Verifies that FastAPI, FFmpeg, the AI model, and the frontend are ready.

---

## 3. Linux Installation

Supported out of the box on **Ubuntu**, **Debian**, **Linux Mint**, **Pop!_OS**, **Fedora**, and **Arch Linux**.

### Step 1: Install System Prerequisites (If Not Already Installed)
On **Ubuntu / Debian / Linux Mint**:
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm ffmpeg git curl
```

### Step 2: Run the Automated Installer
```bash
cd silenttrack-ai
chmod +x install.sh start.sh stop.sh update.sh
./install.sh
```

What `./install.sh` does automatically:
- `[1/5] Checking prerequisites...` — Checks your Linux distribution, free disk space, Python 3.10–3.12, Node.js, npm, and FFmpeg/FFprobe.
- `[2/5] Setting up Python environment...` — Creates `.venv` and `.env` (without overwriting existing configuration).
- `[3/5] Installing backend dependencies...` — Installs Python packages and caches the **TIGER-DnR** AI model weights in `data/models/`.
- `[4/5] Installing frontend dependencies...` — Installs frontend packages in `frontend/`.
- `[5/5] Validating installation...` — Verifies the complete backend, FFmpeg, AI model, and frontend stack.

---

## 4. Manual Installation

If you prefer to run every installation step manually instead of using the automated scripts:

### 1. Create `.env` Configuration
```bash
cp .env.example .env
```

### 2. Set Up Python Virtual Environment & Backend Packages
**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
```

**Windows (PowerShell):**
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

### 3. Install Frontend Dependencies
```bash
cd frontend
npm install
cd ..
```

---

## 5. One-Command Startup

### Windows (PowerShell)
```powershell
.\start.ps1
```

### Linux
```bash
./start.sh
```

What happens when you run the startup script:
1. Verifies that the virtual environment and frontend packages are installed (running the installer automatically if needed).
2. Starts the **FastAPI backend** on `http://127.0.0.1:8000`.
3. Starts the **React/Vite frontend** on `http://localhost:5173`.
4. Polls `http://127.0.0.1:8000/api/health` and `http://localhost:5173` until both services are verified healthy.
5. Prints the application URL (`http://localhost:5173`) and opens your default web browser automatically.
6. Keeps both services running until you press `Ctrl+C` or run the stop script.

### Useful Startup Flags
| Action | Windows PowerShell | Linux |
| :--- | :--- | :--- |
| Standard startup (opens browser) | `.\start.ps1` | `./start.sh` |
| Start without opening browser | `.\start.ps1 -NoBrowser` | `./start.sh --no-browser` |
| Start with LAN access enabled | `.\start.ps1 -Lan` | `./start.sh --lan` |
| Start in background (daemon mode) | `.\start.ps1 -Detach` | `./start.sh --daemon` |

---

## 6. Stopping the Application

You can stop SilentTrack AI at any time either by pressing **`Ctrl+C`** in the terminal where it is running, or by running the dedicated stop script from another terminal window:

### Windows (PowerShell)
```powershell
.\stop.ps1
```

### Linux
```bash
./stop.sh
```

> **Safety Guarantee**: Both `stop.ps1` and `stop.sh` track the exact Process IDs (`.runtime/backend.pid` and `.runtime/frontend.pid`) and verify the process command line before stopping them. Unrelated Python or Node.js programs running on your computer are never affected.

---

## 7. Updating the Application

To update SilentTrack AI to the latest version while keeping your custom `.env` settings and cached AI models intact:

### Windows (PowerShell)
```powershell
.\update.ps1
```

### Linux
```bash
./update.sh
```

The update script safely stops any running SilentTrack AI instance, backs up `.env`, pulls the latest Git changes (if a remote repository is configured), refreshes Python and npm dependencies only if `requirements.txt` or `package-lock.json` changed, and re-validates the installation.

---

## 8. AI Model Download & Offline Mode

SilentTrack AI uses the **TIGER-DnR** (*Time-frequency Interleaved Gain Extraction and Reconstruction*, `JusperLee/TIGER-DnR`) neural network to separate audio into **Speech**, **Environmental Sounds**, and **Music**.

- **Automatic Caching**: During `./install.sh` / `.\install.ps1` (or automatically on the first video job), the ~71 MB `model.safetensors` weights are downloaded once from HuggingFace Hub and cached inside `data/models/`.
- **No Repeated Downloads**: Before downloading, SilentTrack AI checks `data/models/`. If the snapshot is already present, it loads directly from disk in under 1 second.
- **Disk Space Protection**: SilentTrack AI verifies that at least `300 MB` of free disk space is available before downloading model weights.
- **100% Offline Operation**: Once the model weights are cached in `data/models/`, SilentTrack AI loads them with `local_files_only=True` and operates completely offline without requiring an internet connection.

---

## 9. FFmpeg Setup

FFmpeg and FFprobe are required to inspect video containers, extract lossless PCM audio, and remux the cleaned audio onto the original video stream.

### Windows
- **Automatic via Installer**: Run `.\install.ps1` and choose **`Y`** when prompted to install FFmpeg via Winget.
- **Manual via Winget**:
  ```powershell
  winget install --id Gyan.FFmpeg -e
  ```
  *(Close and reopen PowerShell after installing so the updated `PATH` takes effect.)*
- **Portable Binary Option**: You can also place `ffmpeg.exe` and `ffprobe.exe` directly inside `tools\ffmpeg\`.

### Linux
- **Ubuntu / Debian / Linux Mint**:
  ```bash
  sudo apt update && sudo apt install -y ffmpeg
  ```
- **Fedora**:
  ```bash
  sudo dnf install -y ffmpeg
  ```
- **Arch Linux**:
  ```bash
  sudo pacman -S ffmpeg
  ```
- **Portable Binary Option**: You can also place static `ffmpeg` and `ffprobe` binaries inside `tools/ffmpeg/`.

---

## 10. Localhost Access

By default, SilentTrack AI is configured for **strict localhost security**:
- **Frontend UI**: [`http://localhost:5173`](http://localhost:5173)
- **Backend API**: [`http://127.0.0.1:8000`](http://127.0.0.1:8000)
- **API Health**: [`http://127.0.0.1:8000/api/health`](http://127.0.0.1:8000/api/health)

> **What does `localhost` / `127.0.0.1` mean?**
> `localhost` (`127.0.0.1`) is your computer's private loopback address. When running in default localhost mode, **only the browser on the same computer** can access SilentTrack AI. No other device on your Wi-Fi or the internet can connect to it.

---

## 11. LAN Access for Other Devices

If you want to use SilentTrack AI from another device on the **same local Wi-Fi / LAN network** (for example, uploading a video from your phone, tablet, or second laptop while your main PC performs the AI processing):

### Step 1: Start SilentTrack AI in LAN Mode

**Option A — Pass the LAN flag at startup:**
- **Windows (PowerShell):**
  ```powershell
  .\start.ps1 -Lan
  ```
- **Linux:**
  ```bash
  ./start.sh --lan
  ```

**Option B — Enable persistently in `.env`:**
Edit `.env` and set:
```ini
ENABLE_LAN_ACCESS=true
```

When LAN mode is enabled, the Vite frontend binds to `0.0.0.0:5173` and securely proxies `/api` requests to the local FastAPI backend (`127.0.0.1:8000`), and the startup script prints your computer's LAN URL, such as:
```text
LAN Access URL: http://192.168.1.50:5173
```

### Step 2: Configure Firewall Safely (Private Network Only)

If another device on your Wi-Fi cannot reach `http://<YOUR-LAN-IP>:5173`, allow inbound TCP port `5173` on your **Private / Local Network** only:

- **Windows (Run PowerShell as Administrator):**
  ```powershell
  New-NetFirewallRule -DisplayName "SilentTrack AI LAN (Port 5173)" -Direction Inbound -LocalPort 5173 -Protocol TCP -Profile Private -Action Allow
  ```
- **Linux (UFW Firewall):**
  ```bash
  sudo ufw allow from 192.168.0.0/16 to any port 5173 proto tcp
  ```

### Step 3: Open on Your Other Device
On your phone, tablet, or second computer connected to the same Wi-Fi network, open the browser and visit:
```text
http://<YOUR-PC-LAN-IP>:5173
```

---

## 12. Troubleshooting

### 1. PowerShell says `running scripts is disabled on this system`
Run this command in PowerShell before running `.\install.ps1` or `.\start.ps1`:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 2. `Python 3.10, 3.11, or 3.12 was not found`
- **Windows**: Install Python 3.12 with `winget install --id Python.Python.3.12 -e`, then close and reopen PowerShell.
- **Linux**: Run `sudo apt update && sudo apt install -y python3 python3-venv python3-pip`.

### 3. `FFmpeg / FFprobe not found`
- Verify FFmpeg is installed by running `ffmpeg -version`.
- If you just installed FFmpeg via Winget on Windows, close and reopen your PowerShell window so the updated `PATH` is loaded, or place `ffmpeg` and `ffprobe` inside `tools/ffmpeg/`.

### 4. Port `5173` or `8000` is already in use
Run `./stop.sh` (Linux) or `.\stop.ps1` (Windows) to stop any previous background instance of SilentTrack AI. You can also customize `PORT` and `FRONTEND_PORT` in `.env`.

### 5. `This video does not contain an audio track`
The uploaded video has a video stream only (muted container). Upload a video that contains an audio track, or click **"Try Instant Sample Video"** in the web interface to test with a generated sample clip.
