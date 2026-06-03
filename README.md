# Chaturdown

Monitors multiple Chaturbate rooms simultaneously and automatically records any that go live. Designed for always-on use on servers, SBCs (Raspberry Pi, etc.), or any machine that runs in the background. A real-time curses TUI shows Online/Offline status, recording duration, and live file size per room.

---

## Features

- Polls multiple rooms in parallel via the Chaturbate public API
- Spawns a separate download thread per room — multiple streams record simultaneously
- Real-time TUI: Online/Offline status, recording duration, and live file size
- Stall detection: sends SIGINT to gracefully stop a hung yt-dlp process
- Sequential per-room file numbering (`username_001.mkv`, `username_002.mkv`, …)
- Download log with automatic 2-day pruning
- Automatic yt-dlp self-update (configurable interval)
- Cookie harvesting via Camoufox (Firefox-based, bot-detection resistant)
- User-agent fingerprint captured at login time and reused for all API requests

---

## Requirements

- Python 3.10+
- `ffmpeg` — must be installed as a system package (see below)
- All Python dependencies are installed into the venv by `setup.sh`

---

## Installation

### 1 — Install system dependencies

#### Python

- **Ubuntu/Debian:** `sudo apt install python3 python3-pip python3-venv git`
- **Arch:** `sudo pacman -Syu python python-pip git`
- **Fedora:** `sudo dnf install python3 python3-pip python3-venv git`
- **macOS:** `brew install python`

#### ffmpeg

ffmpeg is a binary and cannot be installed into a venv. It must be a system package or yt-dlp cannot mux audio and video.

```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# Arch
sudo pacman -S ffmpeg

# Fedora
sudo dnf install ffmpeg

# macOS
brew install ffmpeg
```

Verify: `ffmpeg -version`

#### Fix missing emoji (tofu squares □□□)

If the TUI shows blank boxes instead of emoji, install Nerd Font emoji support:

```bash
sudo apt install fonts-noto-color-emoji
fc-cache -fv
```

Then restart your terminal.

### 2 — Clone the repository

```bash
git clone https://github.com/yourname/chaturdown.git
cd chaturdown
```

### 3 — Run setup

```bash
./setup.sh
```

`setup.sh` will:
- Create the `Chaturdown_Venv/` virtual environment
- Install all Python dependencies (`requests`, `camoufox`, `yt-dlp`) into the venv
- Download the Camoufox browser binary (required for `ChaturLogin.py`)

### 4 — Log in

```bash
./ChaturLogin.py
```

This opens a visible Firefox (Camoufox) browser window pointed at the Chaturbate login page. Log in and solve any Cloudflare captcha, then close the browser window. The script will then:

- Extract cookies directly from the browser profile's SQLite database
- Save them as `Chaturdown_Cookies.txt`
- Capture the exact browser User-Agent and save it as `user_agent.txt`

Both files must exist before `Chaturdown.py` will start. Re-run `ChaturLogin.py` any time cookies expire or Cloudflare starts blocking requests.

> **Note:** `ChaturLogin.py` opens a real browser window, so it requires a display. On a headless server, use a screen session over RDP or VNC, or forward the display via SSH (`ssh -X`).

### 5 — Configure

Open `Chaturdown.py` and edit the configuration block near the top:

```python
CB_USERNAMES = [
    "model_username_1",
    "model_username_2",
]

VIDEOS_DIR_STR        = "./Videos"
DOWNLOAD_LOG_STR      = "./Chatur_download_logs.txt"
YTDLP_EXE_STR         = "yt-dlp"
YTDLP_UPDATE_INTERVAL = 86400  # seconds between yt-dlp self-updates (0 = disabled)

POLL_MIN      = 60    # minimum seconds between live checks
POLL_MAX      = 120   # maximum seconds between live checks
STALL_TIMEOUT = 60    # seconds of yt-dlp silence before declaring a stall
```

Add as many usernames as needed. The TUI shows one row per room.

---

## Usage

```bash
./Chaturdown.py
```

The TUI launches immediately:

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  📡 CHATURBATE MULTI-DOWNLOADER TUI                          │
│  ────────────────────────────────────────────────────────    │
│                                                              │
│  🟢 model_username_1  | Online  | ⏱️ 01:23:45 | 💾   1.2 GB │
│  🔴 model_username_2  | Offline                              │
│                                                              │
│  ────────────────────────────────────────────────────────    │
│  Status: Connected to Chaturbate API                         │
│  Press 'q' to stop the script.                               │
└──────────────────────────────────────────────────────────────┘
```

Press `q` to stop all downloads and exit.

---

## Running in the Background

### tmux (recommended)

```bash
# Start a new named session
tmux new-session -s chaturdown

# Run the script inside it
./Chaturdown.py

# Detach and leave it running (Ctrl+B, then D)

# Reattach later
tmux attach -t chaturdown
```

### screen

```bash
screen -S chaturdown
./Chaturdown.py

# Detach (Ctrl+A, then D)

# Reattach
screen -r chaturdown
```

---

## Output Structure

```
chaturdown/
├── Chaturdown.py
├── ChaturLogin.py
├── setup.sh
├── requirements.txt
├── Chaturdown_Cookies.txt       # generated by ChaturLogin.py
├── user_agent.txt               # generated by ChaturLogin.py
├── Chatur_download_logs.txt     # rolling 2-day download history
├── Chaturdown_Profile/          # Camoufox browser profile
└── Videos/
    ├── model_username_1/
    │   ├── model_username_1_001.mkv
    │   └── model_username_1_002.mkv
    └── model_username_2/
        └── model_username_2_001.mkv
```

---

## Troubleshooting

**`❌ FATAL: user_agent.txt is missing`** — Run `./ChaturLogin.py` first. This file is required before `Chaturdown.py` will start.

**`❌ FATAL: Chaturdown_Cookies.txt is missing or empty`** — Same cause. Complete the login flow via `./ChaturLogin.py` before starting the watcher.

**Status bar shows "Cloudflare blocked"** — Session cookies have expired. Run `./ChaturLogin.py` again, complete the login, then restart `Chaturdown.py`.

**TUI shows blank squares instead of emoji** — Run `sudo apt install fonts-noto-color-emoji && fc-cache -fv`, then restart your terminal.

**`ffmpeg not found` or no audio in recordings** — ffmpeg must be a system package, not a pip install. Run `sudo apt install ffmpeg` and verify with `ffmpeg -version`.

**Downloads stall immediately** — yt-dlp may be outdated. Activate the venv (`source Chaturdown_Venv/bin/activate`) and run `pip install --upgrade yt-dlp`. Alternatively, set `YTDLP_UPDATE_INTERVAL` in the config to have Chaturdown handle this automatically.

---

## Disclaimer

This tool is intended for educational and research purposes only. Recording streams without the consent of the broadcaster may violate Chaturbate's Terms of Service and applicable laws in your jurisdiction. Use responsibly and at your own risk.
