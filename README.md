# Chaturdown

Monitors multiple Chaturbate rooms simultaneously and automatically records any that go live. Designed for always-on use on servers, SBCs (Raspberry Pi, etc.), or any machine that runs in the background. A real-time curses TUI shows Online/Offline status, recording duration, and live file size per room.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-GPL--3.0-green)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)

## Linux/MacOs:

<img width="872" height="575" alt="Chaturdown_Screenshot" src="https://github.com/user-attachments/assets/c510fb94-d338-48b9-a384-90bed65b0765" />

## Windows:

<img width="1075" height="564" alt="Chaturdown_Windows" src="https://github.com/user-attachments/assets/c9f156b4-b6f5-4a2e-9964-29016cf0539b" />


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

If Cloudflare ever starts blocking requests later, export a fresh cookies file from that same browser and replace `Chaturdown_Cookies.txt` — no restart needed, Chaturdown picks it up on the next poll cycle. If it's still blocked with fresh cookies and a correctly matching User-Agent, see [Proxy](#proxy) below — you may also need one.

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

Everything above is all most people ever need to touch. There's a further set of optional, power-user settings below — see [Advanced Mode](#advanced-mode).

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
│  🟢 model_username_1  | Online  | ⏱️ 01:23:45 | 💾  1.2 GB   │
│  🔴 model_username_2  | Offline                              │
│                                                              │
│  ────────────────────────────────────────────────────────    │
│  Status: Connected to Chaturbate API                         │
│  Press 'q' to stop the script.                               │
└──────────────────────────────────────────────────────────────┘
```

(On Windows this looks slightly different — plain-text labels like `Time:`/`Size:` and a colored `●` instead of emoji, since Windows' terminal support can't render most of them. Functionally identical either way; see the Windows screenshot above.)

The mockup above is the single-column view (a narrow terminal, or a small `models.txt`). On a wide enough terminal, rooms automatically arrange into multiple side-by-side columns instead — no configuration needed, it just uses however much width is available. If a list is large enough to still overflow every column, a `(+N more not shown)` note appears in the footer rather than quietly dropping them.

<img width="1885" height="914" alt="Multi_Column" src="https://github.com/user-attachments/assets/653c7c42-5b1a-4a79-abb4-f41eae944965" />

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

Most people don't need this — leave it blank and Chaturdown behaves exactly as before. (Looking for User-Agent setup? That's a required step, covered in [Add cookies and set your User-Agent](#add-cookies-and-set-your-user-agent) during installation, not here.)

A proxy is only needed if Chaturbate/Cloudflare still blocks your connection even with valid, fresh cookies and a correctly matching `USER_AGENT` — usually because your network itself looks suspicious to Cloudflare: certain VPNs, proxies, hosting/datacenter IPs, or connections from regions Cloudflare treats with extra scrutiny.

If you're running into this, open `Chaturdown.py` and fill in `PROXY` near the top of the config section:

```python
PROXY = ""  # e.g. "http://127.0.0.1:8080" or "socks5://127.0.0.1:1080"
```

This applies consistently to everything Chaturdown does — the live status checks and the actual yt-dlp download — so there's no risk of one working through the proxy while the other doesn't.

Both settings apply consistently to everything Chaturdown does — the live status checks and the actual yt-dlp download — so there's no risk of one working through the proxy while the other doesn't.

---

## Advanced Mode

**You almost certainly don't need this section.** Chaturdown works completely fine, indefinitely, without touching anything below — everyone starts on plain `models.txt` watching, and that's a perfectly good place to stay. This section exists for a handful of specific situations: you're watching a lot of rooms and hitting rate limits, you want long recordings automatically split into smaller files, you're tight on disk space, or you just want a more detailed dashboard. If none of that sounds like you, skip straight to [Usage](#usage).

Every setting below lives in the same configuration block near the top of `Chaturdown.py`, further down from the basics covered in [Configure](#configure). Every one of them defaults to being **off** — an unmodified `Chaturdown.py` behaves identically with or without this whole section existing.

### Checking many rooms without hitting rate limits

```python
USE_FOLLOWED_ROOMS_BULK_CHECK = False
```

By default, Chaturdown checks each `models.txt` username one at a time. If you're watching a lot of rooms, that's a lot of individual requests every poll cycle, which can occasionally trip Chaturbate's rate limiting. Setting this to `True` switches to a single request instead — the same one `chaturbate.com/followed-cams/` itself uses — that reports every currently-online room the account behind `Chaturdown_Cookies.txt` **follows**.

The catch, and the reason this isn't the default: it only reports rooms that account actually follows. A `models.txt` username that isn't followed there will never be detected as online under this mode — it'll just look permanently offline, with no error to warn you. Only turn this on if every username in `models.txt` is followed on that account, or use it together with the next setting instead.

### Watching everyone you follow, without listing them

```python
AUTO_WATCH_FOLLOWED_ONLINE = False   # only does anything if USE_FOLLOWED_ROOMS_BULK_CHECK is also True
```

This solves the catch above a different way: instead of requiring `models.txt` to match your follow list, it automatically watches *any* followed room the bulk check above finds online — whether or not it's in `models.txt` — and stops watching it again once it's no longer online-and-followed. Nothing is ever written to `models.txt`; this only affects what Chaturdown watches in memory for the current run. Anything you *do* list in `models.txt` still works normally alongside it, followed or not.

Practical guidance — pick one of these two setups, not something in between:

- **Manual control:** both settings `False`. List exactly who you want in `models.txt`. No following required.
- **Set-and-forget:** both settings `True`. Follow whoever you want watched on the account behind `Chaturdown_Cookies.txt`; Chaturdown finds and records them automatically the moment they go live, and `models.txt` is only needed for anyone you want watched *without* following them.

Turning on `AUTO_WATCH_FOLLOWED_ONLINE` alone, without bulk-check, does nothing — there's no "who's followed" data to work from without it.

### Splitting long recordings into multiple files

```python
MAX_RECORDING_DURATION = 0    # seconds, 0 = unlimited (today's behavior: one continuous file)
MAX_RECORDING_SIZE_MB   = 0    # megabytes, 0 = unlimited
```

By default, a recording runs as one file for as long as the room stays live — that can mean a single multi-hour, multi-gigabyte file. Setting either of these starts a fresh, sequentially-numbered file (`username_002.mkv`, `_003.mkv`, …) once the current one hits the limit, with no gap in recording — useful if huge single files are awkward to move, edit, or upload. You can set one, the other, or both; whichever is hit first triggers the split. Note that the size limit can overshoot by a small amount — it's checked periodically, not on every byte written, so it can't cut off at the exact number.

### Custom filenames

```python
FILENAME_FORMAT = "{username}_{index:03d}"   # default naming, unchanged
```

Change how recordings are named. Available placeholders: `{username}`, `{index}` (auto-incrementing segment number — `{index:03d}` zero-pads it to 3 digits, e.g. `007`), `{date}` (`YYYY-MM-DD`), and `{time}` (`HH-MM-SS`), all usable in any order. The only rule: `{index}` must always appear somewhere in the template, or every segment would render to the same filename and overwrite each other.

Example: `FILENAME_FORMAT = "{username}_{date}_{index:03d}"` → `some_model_2026-08-06_001.mkv`, numbering restarting fresh each new date automatically.

### Stopping before you run out of disk space

```python
LOW_DISK_SPACE_MB = 0    # megabytes, 0 = disabled (never checks free space)
```

Once free space on the drive holding your `Videos/` folder drops below this many megabytes, Chaturdown stops starting new downloads (shown as `LOW_DISK` in the dashboard) *and* stops any download already in progress, gracefully — same as a normal stall. Recovers automatically once space frees up again. A typical real-world value is somewhere around `5000`–`10000` (5–10 GB) — enough headroom to avoid actually filling the disk, adjust to taste for how much buffer you want.

### Dashboard extras

```python
HIDE_OFFLINE_MODELS   = False   # hide offline rows entirely instead of showing them in red
SHOW_DOWNLOAD_SPEED   = False   # show an estimated MB/s next to each active download
SPEED_SAMPLE_INTERVAL = 2       # how often (seconds) the speed estimate re-samples; only matters if the above is True
```

Two independent cosmetic toggles for the TUI, useful once `models.txt` (or your follow list, under auto-watch) gets long — hiding offline rows keeps the dashboard to just what's actually recording, and the speed estimate gives a rough sense of transfer rate. The speed number is *estimated* from how fast the file on disk is growing, sampled every `SPEED_SAMPLE_INTERVAL` seconds — yt-dlp doesn't report a real speed figure with the downloader Chaturdown uses, so treat it as a useful approximation, not an exact reading.

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

**`❌ No cookie file for Chaturbate found`** — Export your Chaturbate cookies from your browser and save them as `Chaturdown_Cookies.txt` in the same folder as the script (see [Add cookies and set your User-Agent](#add-cookies-and-set-your-user-agent) above).

**`❌ Error: No usernames found`** — Add at least one Chaturbate username to `models.txt`, one per line (see [Live Model List](#live-model-list)).

**`interval=...` or `stop_removed=...` appears as a row in the TUI** — You're running an older version of `Chaturdown.py` that doesn't recognize that directive yet. Update the script to the latest version (see [Live Model List](#live-model-list)).

**Status bar shows "Cloudflare blocked" / 403 Forbidden** — Almost always a missing or mismatched `USER_AGENT`: it's required, and must exactly match the browser you exported cookies from — not the OS actually running the script (see [Add cookies and set your User-Agent](#add-cookies-and-set-your-user-agent)). If it's already set correctly and the cookies are freshly exported, see [Proxy](#proxy) next — you may also need one.

**TUI shows blank squares instead of emoji** — Run `sudo apt install fonts-noto-color-emoji && fc-cache -fv`, then restart your terminal.

**`ffmpeg not found` or no audio in recordings** — ffmpeg must be a system package, not a pip install. Install it with your OS's package manager (see [Installation](#installation)) and verify with `ffmpeg -version`.

**Downloads stall immediately** — yt-dlp may be outdated. On Linux/macOS, activate the venv (`source Chaturdown_Venv/bin/activate`) and run `pip install --upgrade yt-dlp`; on Windows, run `Chaturdown_Venv\Scripts\pip install --upgrade yt-dlp`. Alternatively, set `YTDLP_UPDATE_INTERVAL` in the config to have Chaturdown handle this automatically.

---

## Disclaimer

This tool is intended for educational and research purposes only. Recording streams without the consent of the broadcaster may violate Chaturbate's Terms of Service and applicable laws in your jurisdiction. Use responsibly and at your own risk.
