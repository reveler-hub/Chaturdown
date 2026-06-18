#!/usr/bin/env bash
""":"
exec "$(dirname "$0")/Chaturdown_Venv/bin/python3" "$0" "$@"
":"""

"""
Chaturdown — Chaturbate Multi-User Watcher & Downloader (TUI Edition)
-------------------------------------------------------------------------
Polls multiple Chaturbate usernames via the public API.
Features a clean, interactive Terminal User Interface (TUI) to monitor
downloads in real-time without scrolling logs.

Errors and crashes surface in the terminal via standard Python tracebacks.
"""

import curses
import datetime
import random
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_STOP = threading.Event()

try:
    import requests
except ImportError:
    print("❌ Missing dependency: 'requests' not found.")
    print("👉 Did you forget to run the ./setup.sh file first?")
    sys.exit(1)


# ============================================================
# CONFIGURATION
# ============================================================

CB_USERNAMES = [
    "Model_name",
    "Model_name_2",
]

VIDEOS_DIR_STR   = "./Videos"
DOWNLOAD_LOG_STR = "./Chaturdown_logs.txt"

# If yt-dlp is installed globally, leave as "yt-dlp".
YTDLP_EXE_STR    = "./Chaturdown_Venv/bin/yt-dlp"

# yt-dlp self-update interval (seconds). 0 = disabled. Default: once per day.
YTDLP_UPDATE_INTERVAL = 86400

# Polling and Timeout Settings (in seconds)
POLL_MIN      = 60
POLL_MAX      = 120
STALL_TIMEOUT = 60     # seconds of stdout silence before declaring a stall

# ============================================================
# END OF CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

def resolve_path(p_str: str) -> Path:
    p = Path(p_str).expanduser()
    return p if p.is_absolute() else (BASE_DIR / p).resolve()

VIDEOS_DIR   = resolve_path(VIDEOS_DIR_STR)
DOWNLOAD_LOG = resolve_path(DOWNLOAD_LOG_STR)
YTDLP_EXE    = resolve_path(YTDLP_EXE_STR) if ("/" in YTDLP_EXE_STR or "\\" in YTDLP_EXE_STR) else YTDLP_EXE_STR

COOKIES_FILE = BASE_DIR / "Chaturdown_Cookies.txt"

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_LOG.parent.mkdir(parents=True, exist_ok=True)

# ============================================================================
# TUI SHARED STATE
# ============================================================================
SHARED_STATE = {}

API_STATUS = "Status: Connected to Chaturbate API"

def set_api_status(msg: str) -> None:
    global API_STATUS
    API_STATUS = msg

def format_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0: return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable MB or GB."""
    if size_bytes <= 0:
        return "0.0 MB"
    mb = size_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb/1024:.2f} GB"
    return f"{mb:.1f} MB"

# Strip ANSI escape codes from yt-dlp output to prevent curses rendering issues
ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


# ============================================================================
# LIVE DETECTION
# ============================================================================
def _cb_session() -> requests.Session:
    session = requests.Session()
    if COOKIES_FILE.exists():
        for line in COOKIES_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain, _, path_, _, _, name, value = parts[:7]
                session.cookies.set(name, value, domain=domain.lstrip("."), path=path_)
    return session

def check_is_live(username: str) -> bool:
    try:
        r = _cb_session().get(f"https://chaturbate.com/api/chatvideocontext/{username}/", timeout=15)
        r.raise_for_status()
        if not r.text.strip():
            set_api_status("Status: Session may need re-login (empty API response)")
            return False
        set_api_status("Status: Connected to Chaturbate API")
        return r.json().get("room_status") == "public"
    except ValueError:
        set_api_status("Status: Cloudflare blocked — replace Chaturdown_Cookies.txt with fresh cookies")
        _STOP.set()
        return False
    except Exception as e:
        set_api_status("Status: Unable to connect, check connection or try re-logging back in.")
        return False

def check_all_users(usernames: list[str]) -> list[str]:
    live: list[str] = []
    lock = threading.Lock()

    def _check(u):
        if check_is_live(u):
            with lock:
                live.append(u)

    threads = [threading.Thread(target=_check, args=(u,)) for u in usernames if u]
    for t in threads: t.start()
    for t in threads: t.join()
    return live

# ============================================================================
# FILE SIZE HELPER
# ============================================================================
def get_download_size(target_file: Path) -> int:
    """Return total size in bytes of all files matching the target stem."""
    try:
        return sum(f.stat().st_size for f in target_file.parent.glob(f"{target_file.stem}*") if f.is_file())
    except Exception:
        return 0

# ============================================================================
# STALL WATCHDOG
# ============================================================================
class StallWatchdog:
    def __init__(self, process: subprocess.Popen, target_file: Path):
        self.process = process
        self.target_file = target_file
        self._stopped = False
        self._lock = threading.Lock()
        self.last_output_t = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        with self._lock: self._stopped = True

    def ping(self):
        with self._lock: self.last_output_t = time.time()

    def _run(self):
        while True:
            time.sleep(10)
            with self._lock:
                if self._stopped: return
                silence = time.time() - self.last_output_t
            if self.process.poll() is not None: return
            if silence > STALL_TIMEOUT:
                set_api_status("Status: Stall detected — download stopped")
                _terminate_process(self.process, "Stall detected")
                return

def _terminate_process(process: subprocess.Popen, reason: str):
    """Send SIGINT to yt-dlp for a graceful stop; force-kill after 30 seconds if still running."""
    if process.poll() is not None:
        return
    try:
        process.send_signal(signal.SIGINT)
    except Exception:
        pass

    # Wait up to 30 seconds for clean exit after SIGINT
    for _ in range(30):
        if process.poll() is not None:
            return
        time.sleep(1)

    # Still alive → hard kill
    try:
        process.kill()
    except Exception:
        pass

# ============================================================================
# DOWNLOAD ENGINE
# ============================================================================
def _next_filename(username: str) -> Path:
    out_folder = VIDEOS_DIR / username
    out_folder.mkdir(parents=True, exist_ok=True)

    existing = []
    for f in out_folder.glob(f"{username}_*.mkv"):
        m = re.match(rf"^{re.escape(username)}_(\d+)\.mkv$", f.name)
        if m: existing.append(int(m.group(1)))

    next_n = (max(existing) + 1) if existing else 1
    return out_folder / f"{username}_{next_n:03d}.mkv"

def _build_ytdlp_cmd(username: str, output_path: Path) -> list[str]:
    cmd = [
        str(YTDLP_EXE),
        f"https://chaturbate.com/{username}/",
        "--output",              str(output_path),
        "--hls-use-mpegts",
        "--merge-output-format", "mkv",
        "--fragment-retries",    "5",
        "--retries",             "5",
        "--no-part",
        "--downloader", "ffmpeg",
        "--downloader-args", "ffmpeg:-fps_mode cfr -af aresample=async=1 -c:v copy -c:a aac -copyts -avoid_negative_ts make_zero",
    ]
    if COOKIES_FILE.exists():
        cmd += ["--cookies", str(COOKIES_FILE)]
    return cmd

def _maybe_update_yt_dlp():
    """Upgrade yt-dlp at most once per YTDLP_UPDATE_INTERVAL seconds. Failures are silently ignored."""
    if YTDLP_UPDATE_INTERVAL <= 0:
        return
    last_file = BASE_DIR / ".last_yt_dlp_update"
    now = time.time()
    if last_file.exists():
        try:
            last = float(last_file.read_text().strip())
            if now - last < YTDLP_UPDATE_INTERVAL:
                return
        except Exception:
            pass

    try:
        # sys.executable ensures the correct pip inside the venv
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
            check=False, capture_output=True, text=True, timeout=180
        )
        last_file.write_text(str(now))
    except Exception:
        pass

def _log_download(filename: str) -> None:
    today = datetime.date.today()
    date_str = f"{today.day}/{today.month}/{today.year}"
    cutoff = today - datetime.timedelta(days=2)

    existing = DOWNLOAD_LOG.read_text() if DOWNLOAD_LOG.exists() else ""
    lines = existing.rstrip("\n").split("\n") if existing.strip() else []
    if lines and lines[-1] == date_str:
        lines.append(filename)
    else:
        if lines: lines.append("")
        lines.extend([date_str, filename])

    pruned: list[str] = []
    skip_block = False
    for ln in lines:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", ln)
        if m:
            try:
                block_date = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                skip_block = block_date < cutoff
            except ValueError:
                skip_block = False
        if not skip_block:
            pruned.append(ln)

    while pruned and pruned[0] == "": pruned.pop(0)
    DOWNLOAD_LOG.write_text("\n".join(pruned) + "\n")


def download_stream(username: str) -> None:
    output_path = _next_filename(username)
    SHARED_STATE[username]["target"] = output_path

    process = subprocess.Popen(
        _build_ytdlp_cmd(username, output_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    watchdog = StallWatchdog(process, output_path)

    try:
        for line in process.stdout:
            clean_line = ansi_escape.sub('', line.strip())
            if not clean_line: continue
            watchdog.ping()

            if "giving up after" in clean_line.lower() or "unable to download" in clean_line.lower():
                set_api_status(f"Status: Stream error for {username}")
                watchdog.stop()
                _terminate_process(process, "Stream ended")
                break

    except KeyboardInterrupt:
        set_api_status(f"Status: Interrupted while downloading {username}")
        _terminate_process(process, "User interrupt")
        watchdog.stop()
        SHARED_STATE[username]["target"] = None
        _log_download(output_path.name)
        raise

    watchdog.stop()
    process.wait()

    if process.returncode != 0:
        set_api_status(f"Status: yt-dlp failed for {username} (code {process.returncode})")

    _log_download(output_path.name)
    SHARED_STATE[username]["target"] = None



# ============================================================================
# WATCHER LOOP
# ============================================================================
_active: dict[str, threading.Thread] = {}
_active_lock = threading.Lock()

def _is_active(username: str) -> bool:
    with _active_lock:
        t = _active.get(username)
        if t is None: return False
        if not t.is_alive():
            del _active[username]
            return False
        return True

def _launch(username: str):
    SHARED_STATE[username]["start_t"] = time.time()

    def _run():
        try:
            download_stream(username)
        except Exception:
            import traceback
            traceback.print_exc()
            set_api_status(f"Status: Crash in download thread for {username} (see terminal)")
            _STOP.set()
        finally:
            with _active_lock: _active.pop(username, None)
            SHARED_STATE[username]["status"] = "Offline"
            SHARED_STATE[username]["progress"] = ""
            SHARED_STATE[username]["target"] = None

    t = threading.Thread(target=_run, daemon=True)
    with _active_lock: _active[username] = t
    t.start()

def watch_loop(usernames: list[str]):
    attempt = 0
    try:
        while not _STOP.is_set():
            attempt += 1
            _maybe_update_yt_dlp()
            live_users = check_all_users(usernames)

            for u in usernames:
                is_live = u in live_users
                is_dl = _is_active(u)

                if is_live or is_dl:
                    SHARED_STATE[u]["status"] = "Online"
                    if is_live and not is_dl:
                        _launch(u)
                else:
                    SHARED_STATE[u]["status"] = "Offline"
                    SHARED_STATE[u]["progress"] = ""
                    SHARED_STATE[u]["target"] = None

            snooze = random.randint(POLL_MIN, POLL_MAX)
            for _ in range(snooze):
                if _STOP.is_set(): break
                time.sleep(1)
    except Exception:
        import traceback
        traceback.print_exc()
        set_api_status("Status: Fatal error in watcher thread (see terminal for details)")
        _STOP.set()

# ============================================================================
# TUI DISPLAY LOGIC
# ============================================================================
def draw_dashboard(stdscr):
    curses.curs_set(0)
    stdscr.timeout(500)

    for u in CB_USERNAMES:
        if u not in SHARED_STATE:
            SHARED_STATE[u] = {"status": "Offline", "progress": "", "start_t": time.time(), "target": None}

    while not _STOP.is_set():
        max_y, max_x = stdscr.getmaxyx()
        stdscr.clear()

        try:
            stdscr.box()
            stdscr.addstr(2, 4, "📡 CHATURBATE MULTI-DOWNLOADER TUI", curses.A_BOLD)
            stdscr.addstr(3, 4, "─" * (max_x - 8))

            row = 5
            for u in CB_USERNAMES:
                if row >= max_y - 4: break

                s = SHARED_STATE.get(u, {})
                status = s.get("status", "Offline")
                name_pad = u.ljust(16)

                if status == "Online":
                    elapsed = time.time() - s.get("start_t", time.time())
                    t_str = format_time(elapsed)

                    target = s.get("target")
                    size_b = get_download_size(Path(target)) if target else 0
                    size_str = format_size(size_b).rjust(8)
                    line = f"🟢 {name_pad} | Online  | ⏱️ {t_str} | 💾 {size_str}"
                else:
                    line = f"🔴 {name_pad} | Offline"

                stdscr.addstr(row, 4, line[:max_x-6])
                row += 1

            stdscr.addstr(row + 1, 4, "─" * (max_x - 8))

            stdscr.addstr(max_y - 2, 4, API_STATUS[:max_x-6], curses.A_BOLD)
            stdscr.addstr(max_y - 1, 4, "Press 'q' to stop the script.", curses.A_DIM)

        except curses.error:
            pass # Ignore render errors caused by dragging/resizing terminal window

        key = stdscr.getch()
        if key == ord('q') or key == ord('Q'):
            _STOP.set()
            break

# ============================================================================
# EXECUTION
# ============================================================================
def main():
    usernames = [u.strip() for u in CB_USERNAMES if u.strip()]
    if not usernames:
        print("❌ Error: No usernames found in the CB_USERNAMES list.")
        sys.exit(1)

    if not COOKIES_FILE.exists() or COOKIES_FILE.stat().st_size < 100:
        print("❌ No cookie file for Chaturbate found, please add one to the current folder.")
        print(f"   Expected: {COOKIES_FILE}")
        sys.exit(1)

    watcher_thread = threading.Thread(target=watch_loop, args=(usernames,), daemon=True)
    watcher_thread.start()

    curses.wrapper(draw_dashboard)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _STOP.set()
    except Exception:
        try:
            curses.endwin()
        except Exception:
            pass
        print("\n💥 The script encountered an unexpected error.")
        print("   A full traceback should appear above (or in your terminal scrollback).")
        raise
    finally:
        print("\n👋 TUI Closed. Terminal restored cleanly!")
