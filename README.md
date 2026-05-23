# Chaturdown

A Chaturbate watcher and downloader that runs in your terminal. Polls multiple usernames in parallel via the Chaturbate public API and automatically downloads each room as soon as it goes live — multiple streams download simultaneously.

> **Watcher script:** Chaturdown is designed to run continuously in the background alongside other scripts in this suite. See [Running in the background](#running-in-the-background) below.

## Features

- **Multi-user parallel monitoring** — checks all configured usernames at once via the Chaturbate API (no browser needed for checks)
- **Parallel downloads** — each live room gets its own download thread; multiple streams download at the same time
- **Auto-login cookie harvesting** — uses Camoufox to log in headlessly and refresh cookies every hour
- **Stall detection** — monitors yt-dlp output and automatically saves and closes a download if the stream drops
- **Clean exit on interrupt** — pressing Ctrl+C saves and muxes all partial files before exiting
- **Sequential file numbering** — saves files as `username_001.mp4`, `username_002.mp4`, etc.
- **Randomised polling** — polls between `POLL_MIN` and `POLL_MAX` seconds to avoid detection patterns

## Installation

### Step 1 — Install Python

If you don't have Python installed:
- **Windows**: Download from [python.org](https://www.python.org/downloads/) — check **"Add Python to PATH"** during install
- **macOS**: `brew install python` or download from [python.org](https://www.python.org/downloads/)
- **Ubuntu/Debian**: `sudo apt install python3 python3-pip python3-venv git curl`
- **Arch Based**: `sudo pacman -Syu python python-pip python-venv git curl`
- **Fedora**: `sudo dnf install python3 python3-pip python3-venv git curl`

### Step 2 — Download and set up Chaturdown

**Windows (Command Prompt or PowerShell):**
```
git clone https://github.com/reveler-hub/Chaturdown.git

python -m venv venv
venv\Scripts\activate
pip install yt-dlp yt-dlp-ejs deno camoufox requests
# Move Chaturdown.py into the venv folder if you want to keep everything tidy.

python Chaturdown.py
```

**macOS / Linux:**
```bash
git clone https://github.com/reveler-hub/Chaturdown.git

python3 -m venv venv
source venv/bin/activate
pip install yt-dlp yt-dlp-ejs deno camoufox requests
# Move Chaturdown.py into the venv folder if you want to keep everything tidy.

python Chaturdown.py
```

> **What is a venv?** A virtual environment is an isolated folder that holds Python packages just for this project, so they don't conflict with anything else on your system. You only need to create it once.

> **Next time you open a terminal**, activate the venv again before running: `venv\Scripts\activate` (Windows) or `source venv/bin/activate` (macOS/Linux).

### Sharing a venv with other scripts

If you're already running TikTube, DownTube, or TwiDown, you can reuse their venv instead of creating a new one. Open `Chaturdown.py` in a text editor and change the first line (the shebang) to point at your existing venv's Python:

```
#!/path/to/your/existing/venv/bin/python3
```

On Windows the path will look like `C:\path\to\venv\Scripts\python.exe`. Once set, the script always uses that venv automatically.

## Configuration

Open `Chaturdown.py` in a text editor and edit the config block near the top:

```python
YTDLP_EXE        = Path("/usr/local/bin/yt-dlp")
CAMOUFOX_PROFILE = Path("./Profiles/shared_profile")  # Shared profile — see below
CB_USERNAME      = "YOUR_USERNAME_HERE"   # Your Chaturbate username
CB_PASSWORD      = "YOUR_PASSWORD_HERE"   # Your Chaturbate password
COOKIES_FILE     = Path("./chaturdown_cookies.txt")
VIDEOS_DIR       = Path("./Videos/Chaturbate")
STREAMS_DIR      = Path("./Streams")
```

> **Security note:** Never commit `CB_USERNAME` and `CB_PASSWORD` to a public repository. Consider moving them to a `.env` file and adding `.env` to your `.gitignore`.

Add the usernames you want to monitor:

```python
CB_USERNAMES = [
    "model_username_1",
    "model_username_2",
]
```

Adjust timing and behaviour:

```python
POLL_MIN       = 60    # Minimum seconds between poll cycles
POLL_MAX       = 120   # Maximum seconds between poll cycles
MUX_TIMEOUT    = 300   # Max seconds to wait for yt-dlp to finish saving on exit
STALL_TIMEOUT  = 60    # Seconds of no output before assuming stream dropped
COOKIE_MAX_AGE = 3600  # Re-harvest cookies after 1 hour
```

### Shared browser profile

All scripts in this suite use the same browser profile for storing logins. If you're running multiple scripts, point them all at the same directory so you only need to log in once:

```python
CAMOUFOX_PROFILE = Path("/your/shared/profile/path")
```

See the other scripts in this suite: [TikTube](https://github.com/reveler-hub/TikTube) · [DownTube](https://github.com/reveler-hub/DownTube) · [TwiDown](https://github.com/reveler-hub/TwitDown)

## Usage

```bash
python Chaturdown.py
```

If `CB_USERNAMES` is empty you'll be prompted to enter usernames at startup. Chaturdown will then log in, begin polling, and spawn a download for each user that goes live.

## Running in the background

Chaturdown needs to keep running to catch streams. Here are the best ways to do that on each OS:

### Windows

**Option 1 — Run in a new window that stays open (simplest)**

Open PowerShell and run:
```powershell
Start-Process python -ArgumentList "Chaturdown.py" -WorkingDirectory "C:\path\to\chaturdown"
```

**Option 2 — Windows Terminal with a dedicated tab**

Open Windows Terminal, open a new tab, navigate to the folder and run `python Chaturdown.py`. Keep that tab open.

**Option 3 — Task Scheduler (runs on login, no window)**

1. Open **Task Scheduler** (search for it in the Start menu)
2. Click **Create Basic Task**
3. Name it `Chaturdown`, set trigger to **When I log on**
4. Action: **Start a program**
   - Program: `C:\path\to\chaturdown\venv\Scripts\pythonw.exe`
   - Arguments: `Chaturdown.py`
   - Start in: `C:\path\to\chaturdown`
5. Check **Open the Properties dialog** and tick **Run whether user is logged on or not**

**Option 4 — WSL (Windows Subsystem for Linux)**

If you have WSL installed, use tmux inside it (see Linux section below).

### Linux

**tmux** (recommended)
```bash
tmux new -s chaturdown
python Chaturdown.py
# Detach: Ctrl+B then D
# Reattach later: tmux attach -t chaturdown
```

**nohup** (simple, saves output to a log file)
```bash
nohup python Chaturdown.py > chaturdown.log 2>&1 &
tail -f chaturdown.log
```

**systemd service** (survives reboots)

Create `/etc/systemd/system/chaturdown.service`:
```ini
[Unit]
Description=Chaturdown Chaturbate Watcher

[Service]
ExecStart=/path/to/venv/bin/python3 /path/to/Chaturdown.py
WorkingDirectory=/path/to/chaturdown
Restart=on-failure
User=youruser

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now chaturdown
sudo journalctl -fu chaturdown
```

### macOS

**tmux** (recommended)
```bash
brew install tmux
tmux new -s chaturdown
python Chaturdown.py
# Detach: Ctrl+B then D
# Reattach later: tmux attach -t chaturdown
```

**launchd** (runs on login, survives reboots)

Create `~/Library/LaunchAgents/com.user.chaturdown.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.user.chaturdown</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/python3</string>
        <string>/path/to/Chaturdown.py</string>
    </array>
    <key>WorkingDirectory</key><string>/path/to/chaturdown</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/tmp/chaturdown.log</string>
    <key>StandardErrorPath</key><string>/tmp/chaturdown.log</string>
</dict>
</plist>
```
```bash
launchctl load ~/Library/LaunchAgents/com.user.chaturdown.plist
tail -f /tmp/chaturdown.log
```

### Running all watcher scripts at once (Linux/macOS with tmux)

```bash
tmux new-session -d -s watchers
tmux new-window -t watchers -n downtube   'python DownTube.py'
tmux new-window -t watchers -n chaturdown 'python Chaturdown.py'
tmux new-window -t watchers -n twidown    'python TwiDown.py'
tmux attach -t watchers
# Switch between windows: Ctrl+B then 0, 1, 2
```

## Output structure

```
./Videos/Chaturbate/
├── username1/
│   ├── username1_001.mp4
│   └── username1_002.mp4
└── username2/
    └── username2_001.mp4
```

Streams save to `./Streams/<username>/` while downloading, then move to `./Videos/Chaturbate/<username>/` on completion.

## Console output

Each active download shows a single updating line:
```
[username] [download]  38.4% of ~512MiB at  8.2MiB/s ETA 01:45
```

Poll status appears above it:
```
[2024-01-01 14:30:00] Check #12
[2024-01-01 14:30:00]    username1: LIVE [downloading]
[2024-01-01 14:30:00]    username2: offline
```

## Stopping

Press `Ctrl+C`. Chaturdown sends a stop signal to all active downloads, waits for them to save and mux their files, then exits cleanly.

## Troubleshooting

**Cloudflare verification / `CB API non-JSON`** — Chaturbate is blocking the request. Re-run the script to trigger a fresh login.

**Auto-login failed** — double-check `CB_USERNAME` and `CB_PASSWORD`. If Cloudflare keeps blocking, try temporarily setting `headless=False` in the login function to complete it manually in a browser window.

**Stream shows live but download fails** — the room may be private, password-protected, or geo-restricted. Check the output for the yt-dlp error message.

**Stall detected** — the stream dropped mid-download. Chaturdown automatically saves the partial file and will pick the stream back up on the next poll if it's still live.
