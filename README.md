[README.md](https://github.com/user-attachments/files/29078801/README.md)
# Chaturdown

Monitors multiple Chaturbate rooms simultaneously and automatically records any that go live. Designed for always-on use on servers, SBCs (Raspberry Pi, etc.), or any machine that runs in the background. A real-time curses TUI shows Online/Offline status, recording duration, and live file size per room.

<img width="872" height="575" alt="Chaturdown_Screenshot" src="https://github.com/user-attachments/assets/c510fb94-d338-48b9-a384-90bed65b0765" />


---

## Features

- Polls multiple rooms in parallel via the Chaturbate public API
- Spawns a separate download thread per room — multiple streams record simultaneously
- Real-time TUI: Online/Offline status, recording duration, and live file size
- Stall detection: sends SIGINT to gracefully stop a hung yt-dlp process
- Sequential per-room file numbering (`username_001.mkv`, `username_002.mkv`, …)
- Download log with automatic 2-day pruning
- Automatic yt-dlp self-update (configurable interval)

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
chmod +x *
```

### 3 — Run setup

```bash
./setup.sh
```

`setup.sh` will:
- Create the `Chaturdown_Venv/` virtual environment
- Install all Python dependencies (`requests`, `yt-dlp`) into the venv

### 4 — Add cookies

Chaturdown requires a Netscape-format cookies file to authenticate with Chaturbate. Export this from your browser after logging in to Chaturbate:

1. Install a browser extension such as [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (Chrome)
https://addons.mozilla.org/en-US/firefox/addon/get-cookies-txt-locally/ (Firefox)
2. Navigate to `chaturbate.com` while logged in
3. Use the extension to export cookies for the current site
4. Save the file as `Chaturdown_Cookies.txt` in the same folder as `Chaturdown.py`

If Cloudflare ever starts blocking requests, simply export fresh cookies from your browser and replace the file — no restart needed on the next poll cycle.

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
├── setup.sh
├── requirements.txt
├── Chaturdown_Cookies.txt       # your exported browser cookies
├── Chatur_download_logs.txt     # rolling 2-day download history
└── Videos/
    ├── model_username_1/
    │   ├── model_username_1_001.mkv
    │   └── model_username_1_002.mkv
    └── model_username_2/
        └── model_username_2_001.mkv
```

---

## Troubleshooting

**`❌ No cookie file for Chaturbate found`** — Export your Chaturbate cookies from your browser and save them as `Chaturdown_Cookies.txt` in the same folder as the script (see Step 4 above).

**Status bar shows "Cloudflare blocked"** — Session cookies have expired. Export fresh cookies from your browser, replace `Chaturdown_Cookies.txt`, and Chaturdown will pick them up on the next poll cycle.

**TUI shows blank squares instead of emoji** — Run `sudo apt install fonts-noto-color-emoji && fc-cache -fv`, then restart your terminal.

**`ffmpeg not found` or no audio in recordings** — ffmpeg must be a system package, not a pip install. Run `sudo apt install ffmpeg` and verify with `ffmpeg -version`.

**Downloads stall immediately** — yt-dlp may be outdated. Activate the venv (`source Chaturdown_Venv/bin/activate`) and run `pip install --upgrade yt-dlp`. Alternatively, set `YTDLP_UPDATE_INTERVAL` in the config to have Chaturdown handle this automatically.

---

## Disclaimer

This tool is intended for educational and research purposes only. Recording streams without the consent of the broadcaster may violate Chaturbate's Terms of Service and applicable laws in your jurisdiction. Use responsibly and at your own risk.
