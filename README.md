# Chaturdown

Monitors multiple Chaturbate rooms simultaneously and automatically records any that go live. Designed for always-on use on servers, SBCs (Raspberry Pi, etc.), or any machine that runs in the background. A real-time curses TUI shows Online/Offline status, recording duration, and live file size per room.

## Linux/MacOs:

<img width="872" height="575" alt="Chaturdown_Screenshot" src="https://github.com/user-attachments/assets/c510fb94-d338-48b9-a384-90bed65b0765" />

## Windows:

<img width="1075" height="564" alt="Chaturdown_Windows" src="https://github.com/user-attachments/assets/c9f156b4-b6f5-4a2e-9964-29016cf0539b" />


---

## Features

- Polls multiple rooms in parallel via the Chaturbate public API
- Usernames live in `models.txt` and are re-checked automatically — add or remove rooms without restarting
- Optional proxy and User-Agent support for connections that Chaturbate/Cloudflare would otherwise block
- Spawns a separate download thread per room — multiple streams record simultaneously
- Real-time TUI: Online/Offline status, recording duration, and live file size
- Stall detection: gracefully stops a hung yt-dlp process (SIGINT on Linux/macOS, Ctrl+Break on Windows)
- Sequential per-room file numbering (`username_001.mkv`, `username_002.mkv`, …)
- Download log with automatic 2-day pruning
- Automatic yt-dlp self-update (configurable interval)
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

5. Continue with [Add cookies](#add-cookies) below.

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

4. Continue with [Add cookies](#add-cookies) below.

### Add cookies

Chaturdown requires a Netscape-format cookies file to authenticate with Chaturbate. Export this from your browser after logging in to Chaturbate:

1. Install a browser extension such as [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (Chrome)
https://addons.mozilla.org/en-US/firefox/addon/get-cookies-txt-locally/ (Firefox)
2. Navigate to `chaturbate.com` while logged in
3. Use the extension to export cookies for the current site
4. Save the file as `Chaturdown_Cookies.txt` in the same folder as `Chaturdown.py`

If Cloudflare ever starts blocking requests, simply export fresh cookies from your browser and replace the file — no restart needed on the next poll cycle.

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
STALL_TIMEOUT = 60    # seconds of yt-dlp silence before declaring a stall
```

(yt-dlp itself doesn't need configuring — Chaturdown finds it automatically: the copy installed into `Chaturdown_Venv` by setup, or a global install on PATH otherwise.)

---

## Usage

```bash
./Chaturdown.py
```

On Windows, just double-click `Chaturdown.py` instead (it automatically relaunches itself under `Chaturdown_Venv`'s own Python).

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

**If `interval=...` or `stop_removed=...` shows up as a row in the TUI** (treated as a literal username instead of a setting), you're running an outdated copy of `Chaturdown.py` that predates that directive. Update to the latest version of the script — older versions only recognize directives that existed at the time, so a newer `models.txt` used with an older script will have unrecognized lines fall through and get treated as usernames.

---

## Proxy / User-Agent

Most people don't need this — leave both settings blank and Chaturdown behaves exactly as before. This is only for cases where Chaturbate/Cloudflare blocks your connection even though your cookies are valid: a `403` error, a "Cloudflare blocked" status message, or similar.

This usually happens because of one or both of:
- **Your network looks suspicious to Cloudflare** — common with certain VPNs, proxies, hosting/datacenter IPs, or connections from regions Cloudflare treats with extra scrutiny.
- **Your requests don't look like they're coming from a real browser** — Chaturdown doesn't send a User-Agent by default, which combined with the above can be enough to get blocked.

If you're running into this, open `Chaturdown.py` and fill in the `PROXY` and `USER_AGENT` values near the top of the config section:

```python
PROXY = ""       # e.g. "http://127.0.0.1:8080" or "socks5://127.0.0.1:1080"
USER_AGENT = ""  # e.g. "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."
```

**Getting your User-Agent:** for best results, use the *exact* browser you used to export your cookies — Chaturbate can tie your session to it, so a mismatched or generic User-Agent may not help. Either of these works:

1. Google: search **"what is my user agent"** and copy the string from under the AI-generated answer.
2. Visit **[whatsmyua.info](https://whatsmyua.info/)** — your User-Agent is shown right at the top, under "Enter a user-agent string:".

Both settings apply consistently to everything Chaturdown does — the live status checks and the actual yt-dlp download — so there's no risk of one working through the proxy while the other doesn't.

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

### Windows

There's no native tmux/screen equivalent on Windows. Just launch Chaturdown normally (double-click `Chaturdown.py`, or run `Chaturdown_Venv\Scripts\python.exe Chaturdown.py`) and **minimize the console window** instead of closing it — it keeps running in the background while you're logged in.

Note this isn't a true detach: closing that window, logging off, or rebooting stops it, unlike tmux/screen. If you specifically want real detach/reattach, run Chaturdown inside **WSL** (Windows Subsystem for Linux) instead and follow the tmux/screen instructions above — WSL is a real Linux environment, so both work normally there.

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
└── Videos/
    ├── model_username_1/
    │   ├── model_username_1_001.mkv
    │   └── model_username_1_002.mkv
    └── model_username_2/
        └── model_username_2_001.mkv
```

---

## Troubleshooting

**`❌ No cookie file for Chaturbate found`** — Export your Chaturbate cookies from your browser and save them as `Chaturdown_Cookies.txt` in the same folder as the script (see [Add cookies](#add-cookies) above).

**`❌ Error: No usernames found`** — Add at least one Chaturbate username to `models.txt`, one per line (see [Live Model List](#live-model-list)).

**`interval=...` or `stop_removed=...` appears as a row in the TUI** — You're running an older version of `Chaturdown.py` that doesn't recognize that directive yet. Update the script to the latest version (see [Live Model List](#live-model-list)).

**Status bar shows "Cloudflare blocked"** — Session cookies have expired. Export fresh cookies from your browser, replace `Chaturdown_Cookies.txt`, and Chaturdown will pick them up on the next poll cycle. If fresh cookies still get blocked (common on certain VPNs/proxies or in some regions), see [Proxy / User-Agent](#proxy--user-agent).

**TUI shows blank squares instead of emoji** — Run `sudo apt install fonts-noto-color-emoji && fc-cache -fv`, then restart your terminal.

**`ffmpeg not found` or no audio in recordings** — ffmpeg must be a system package, not a pip install. Install it with your OS's package manager (see [Installation](#installation)) and verify with `ffmpeg -version`.

**Downloads stall immediately** — yt-dlp may be outdated. On Linux/macOS, activate the venv (`source Chaturdown_Venv/bin/activate`) and run `pip install --upgrade yt-dlp`; on Windows, run `Chaturdown_Venv\Scripts\pip install --upgrade yt-dlp`. Alternatively, set `YTDLP_UPDATE_INTERVAL` in the config to have Chaturdown handle this automatically.

---

## Disclaimer

This tool is intended for educational and research purposes only. Recording streams without the consent of the broadcaster may violate Chaturbate's Terms of Service and applicable laws in your jurisdiction. Use responsibly and at your own risk.
