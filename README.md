# Chaturdown

Monitors multiple Chaturbate rooms simultaneously and automatically records any that go live. Designed for always-on use on servers, NAS, SBCs (Raspberry Pi, etc.), or any machine that runs in the background. A real-time curses TUI shows Online/Offline status, recording duration, and live file size per room.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)

## Linux/MacOs:

<img width="1887" height="918" alt="Linux_TUI" src="https://github.com/user-attachments/assets/1d815fb1-b201-4f26-958c-b77f83ba1bcc" />

## Windows:

<img width="1908" height="914" alt="Windows_TUI" src="https://github.com/user-attachments/assets/38617f78-98e0-4380-aa24-4a7e530869a8" />




---

## Features

- Polls multiple rooms in parallel via the Chaturbate public API
- Usernames live in `models.txt` and are re-checked automatically — add or remove rooms without restarting
- Sends a matching User-Agent (required to pass Chaturbate/Cloudflare's bot checks), with optional proxy support
- Spawns a separate download thread per room — multiple streams record simultaneously
- Real-time TUI: Online/Offline status, recording duration, and live file size
- Dashboard auto-arranges into multiple side-by-side columns on a wide enough terminal instead of one tall list that runs out of room — scales much better to watching hundreds of rooms at once, and says so if any still don't fit
- Stall detection: gracefully stops a hung yt-dlp process (SIGINT on Linux/macOS, Ctrl+Break on Windows)
- Sequential per-room file numbering (`username_001.mkv`, `username_002.mkv`, …) or the naming can be manually set
- Download log with automatic 2-day pruning
- Automatic yt-dlp self-update (configurable interval)
- Checks GitHub for new Chaturdown releases on startup and lets you know — one prompt to permanently silence it if you don't want it
- Debugging messages

---

## Requirements

- Python 3.10+
- `ffmpeg` — must be installed as a system package (see below)
- All Python dependencies are installed into the venv automatically by the setup script for your OS
- **Runs natively on Linux, macOS, and Windows** — no WSL needed. On Windows, `curses` is provided by the `windows-curses` package (installed automatically by `setup_windows.bat`), and `Chaturdown.py` can be launched by double-clicking it once setup has run.

---

## Installation

### Windows

1. **Install Python**, if you don't already have it: [python.org/downloads](https://www.python.org/downloads/)

   > **Important:** on the first screen of the installer, tick **"Add python.exe to PATH"** before clicking Install — it's off by default on some versions. If you already installed Python without it, re-run the installer, choose "Modify", and enable it from there.

2. **Install ffmpeg** (a binary, not a pip package — yt-dlp needs it on PATH to mux audio and video):
   ```
   winget install ffmpeg
   ```
   Run that from a terminal (PowerShell or Command Prompt). Afterward, **close and reopen** any terminal windows before running Chaturdown — Windows won't recognize the new install in a window that was already open.

3. **Download this project** (green "Code" button → "Download ZIP" if you're not using git) and unzip it somewhere, or:
   ```
   git clone https://github.com/reveler-hub/chaturdown.git
   cd chaturdown
   ```

4. **Run `setup_windows.bat`** — double-click it, or run it from a terminal in that folder. It creates the `Chaturdown_Venv\` virtual environment and installs all Python dependencies (`requests`, `yt-dlp`, `windows-curses`) into it.

5. Continue with [Add cookies and set your User-Agent](#add-cookies-and-set-your-user-agent) below.

### macOS / Linux

1. **Install system dependencies** — installs Python and ffmpeg together. ffmpeg is a binary and cannot be installed into a venv — it must be a system package, or yt-dlp cannot mux audio and video.

   ```bash
   # Ubuntu / Debian
   sudo apt install python3 python3-pip python3-venv ffmpeg git

   # Arch
   sudo pacman -Syu python python-pip ffmpeg git

   # Fedora
   sudo dnf install python3 python3-pip python3-venv ffmpeg git

   # macOS
   brew install python ffmpeg
   ```

   Verify ffmpeg installed correctly: `ffmpeg -version`

   #### Fix missing emoji (tofu squares □□□)

   If the TUI shows blank boxes instead of emoji, install Nerd Font emoji support:

   ```bash
   sudo apt install fonts-noto-color-emoji
   fc-cache -fv
   ```

   Then restart your terminal.

2. **Clone the repository**

   ```bash
   git clone https://github.com/reveler-hub/chaturdown.git
   cd chaturdown
   chmod +x *
   ```

3. **Run setup**

   ```bash
   ./setup.sh
   ```

   `setup.sh` will:
   - Create the `Chaturdown_Venv/` virtual environment
   - Install all Python dependencies (`requests`, `yt-dlp`) into the venv

4. Continue with [Add cookies and set your User-Agent](#add-cookies-and-set-your-user-agent) below.

### Add cookies and set your User-Agent

Chaturdown requires a Netscape-format cookies file to authenticate with Chaturbate, **and** a matching User-Agent — both are required, not optional. Chaturbate's Cloudflare protection ties your session to the specific browser that exported the cookies, and will block every request with a `403 Forbidden` error if the User-Agent doesn't match, even with valid, freshly-exported cookies.

1. Install a browser extension such as [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (Chrome) or
https://addons.mozilla.org/en-US/firefox/addon/get-cookies-txt-locally/ (Firefox)
2. Navigate to `chaturbate.com` while logged in
3. Use the extension to export cookies for the current site
4. Save the file as `Chaturdown_Cookies.txt` in the same folder as `Chaturdown.py`
5. Get that **same browser's** User-Agent string — either:
   - Google: search **"what is my user agent"** and copy the string from under the AI-generated answer.
   - Visit **[whatsmyua.info](https://whatsmyua.info/)** — shown right at the top, under "Enter a user-agent string:".
6. Open `Chaturdown.py` and set `USER_AGENT` near the top of the config section to that exact string:
   ```python
   USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."
   ```

**Important:** match the browser that *exported the cookies*, not the machine `Chaturdown.py` happens to be running on. If you exported cookies from Chrome on your everyday desktop but run Chaturdown somewhere else (a VM, a headless server, etc.), `USER_AGENT` should still describe that original Chrome — not the OS actually running the script.

If Cloudflare ever starts blocking requests later, export a fresh cookies file from that same browser and replace `Chaturdown_Cookies.txt` — no restart needed, Chaturdown picks it up on the next poll cycle. If it's still blocked with fresh cookies and a correctly matching User-Agent, see [Proxy](https://github.com/reveler-hub/Chaturdown/wiki/Proxy) on the wiki — you may also need one.

### Add your models

Create a `models.txt` file in the same folder as `Chaturdown.py`, one username per line:

```
model_username_1
model_username_2
```

Blank lines and lines starting with `#` are ignored. This file is checked automatically for changes — add or remove usernames anytime and Chaturdown picks them up without a restart. See [Live Model List](#live-model-list) below for details, including how to change the check frequency.

### Configure

Open `Chaturdown.py` and edit the configuration block near the top if you want to change any defaults:

```python
VIDEOS_DIR_STR                  = "./Videos"
DOWNLOAD_LOG_STR                = "./Chaturdown_logs.txt"
YTDLP_UPDATE_INTERVAL           = 86400  # seconds between yt-dlp self-updates (0 = disabled)
DEFAULT_MODELS_RELOAD_INTERVAL  = 120    # used if models.txt doesn't set its own interval=

POLL_MIN      = 60    # minimum seconds between live checks
POLL_MAX      = 120   # maximum seconds between live checks
STALL_TIMEOUT = 180   # seconds of yt-dlp silence before declaring a stall
```

(yt-dlp itself doesn't need configuring — Chaturdown finds it automatically: the copy installed into `Chaturdown_Venv` by setup, or a global install on PATH otherwise.)

Everything above is all most people ever need to touch. There's a further set of optional, power-user settings — see [Advanced Mode](https://github.com/reveler-hub/Chaturdown/wiki/Advanced-Mode) on the wiki.

---

## Usage

```bash
./Chaturdown.py
```

On Windows, just double-click `Chaturdown.py` instead (it automatically relaunches itself under `Chaturdown_Venv`'s own Python).

The TUI launches immediately:

<img width="786" height="441" alt="TUI_small" src="https://github.com/user-attachments/assets/c49b57e6-89e9-4ded-8dff-1dc409651d0e" />


(On Windows this looks slightly different — plain-text labels like `Time:`/`Size:` and a colored `●` instead of emoji, since Windows' terminal support can't render most of them. Functionally identical either way; see the Windows screenshot above.)

The mockup above is the single-column view (a narrow terminal, or a small `models.txt`). On a wide enough terminal, rooms automatically arrange into multiple side-by-side columns instead — no configuration needed, it just uses however much width is available. If a list is large enough to still overflow every column, a `(+N more not shown)` note appears in the footer rather than quietly dropping them.

<img width="1887" height="918" alt="Linux_TUI" src="https://github.com/user-attachments/assets/1d815fb1-b201-4f26-958c-b77f83ba1bcc" />

Press `q` to stop all downloads and exit.

---

## Live Model List

Chaturdown reads the list of usernames to watch from `models.txt`, in the same folder as the script:

```
# One username per line. Blank lines and lines starting with # are ignored.
interval=120
stop_removed=false

model_username_1
model_username_2
```

- **Add or remove usernames anytime** — save the file and Chaturdown picks up the change automatically, no restart needed. New usernames start getting polled right away.
- **`interval=N`** (optional) sets how often, in seconds, Chaturdown re-checks the file for changes. If omitted, it defaults to `DEFAULT_MODELS_RELOAD_INTERVAL` in the script (120s / 2 minutes). You can change this value later too — it takes effect on the next check, no restart required.
- **`stop_removed=true`** (optional, defaults to `false`) controls what happens when you remove a username that's currently downloading:
  - `false` (default) — the in-progress download is left alone and finishes naturally; only new activity for that username stops being watched.
  - `true` — the download is stopped immediately (same graceful SIGINT-then-kill behavior as a normal stall/interrupt) as soon as the removal is detected.
- If `models.txt` is deleted or ends up empty while Chaturdown is running, it keeps using the last known-good list and shows a warning in the status bar, rather than dropping every room.
- If the file is missing entirely on startup, Chaturdown won't launch — add at least one username first.

**Note:** there's a small delay between saving the file and the change actually appearing — Chaturdown reads on a timer (`interval=N`), it doesn't watch the file live. A one- or few-second gap between the interval elapsing and the update showing up in the TUI is normal.

---

## Proxy

Most people don't need this — leave it blank and Chaturdown behaves exactly as before. Only needed if Chaturbate/Cloudflare still blocks your connection even with valid, fresh cookies and a correctly matching `USER_AGENT`.

Full details, including the `PROXY` config option: see [Proxy](https://github.com/reveler-hub/Chaturdown/wiki/Proxy) on the wiki.

---

## Advanced Mode

**You almost certainly don't need this.** Chaturdown works completely fine, indefinitely, on plain `models.txt` watching alone. A further set of optional, off-by-default settings exists for specific situations — watching enough rooms to hit rate limits, splitting long recordings, low disk space, custom filenames, extra dashboard info.

Full details: see [Advanced Mode](https://github.com/reveler-hub/Chaturdown/wiki/Advanced-Mode) on the wiki.

---

## Running in the Background

For always-on use (servers, SBCs, etc.), run Chaturdown inside `tmux` or `screen` on Linux/macOS so it keeps running after you disconnect; on Windows, minimize the console window instead (see the wiki for the WSL option if you want true detach/reattach there too).

Full details: see [Running in the Background](https://github.com/reveler-hub/Chaturdown/wiki/Running-in-the-Background) on the wiki.

---

## Output Structure

```
chaturdown/
├── Chaturdown.py
|── Chaturdown_Venv
├── setup.sh                     # Linux/macOS setup
├── setup_windows.bat             # Windows setup
├── requirements.txt
├── models.txt                   # usernames to watch, checked automatically for changes
├── Chaturdown_Cookies.txt       # your exported browser cookies
├── Chaturdown_logs.txt     # rolling 2-day download history
├── native_fetch.py        # doesn't work on Windows
└── Videos/
    ├── model_username_1/
    │   ├── model_username_1_001.mkv
    │   └── model_username_1_002.mkv
    └── model_username_2/
        └── model_username_2_001.mkv
```

---

## Troubleshooting

**Status bar shows "Cloudflare blocked" / 403 Forbidden** — Almost always a missing or mismatched `USER_AGENT`: it's required, and must exactly match the browser you exported cookies from — not the OS actually running the script (see [Add cookies and set your User-Agent](#add-cookies-and-set-your-user-agent)). If it's already set correctly and the cookies are freshly exported, see [Proxy](https://github.com/reveler-hub/Chaturdown/wiki/Proxy) — you may also need one.

For every other error message (missing cookie file, no usernames found, blank emoji squares, ffmpeg not found, stalled downloads, etc.): see [Troubleshooting](https://github.com/reveler-hub/Chaturdown/wiki/Troubleshooting) on the wiki.

---

## Disclaimer

This tool is intended for educational and research purposes only. Recording streams without the consent of the broadcaster may violate Chaturbate's Terms of Service and applicable laws in your jurisdiction. Use responsibly and at your own risk.
