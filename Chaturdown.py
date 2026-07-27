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
All connection errors are shown directly in the TUI status bar.
"""

import curses
import datetime
import json
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

VIDEOS_DIR_STR   = "./Videos"
DOWNLOAD_LOG_STR = "./Chaturdown_logs.txt"

# If yt-dlp is installed globally, leave as "yt-dlp".
YTDLP_EXE_STR    = "./Chaturdown_Venv/bin/yt-dlp"

# yt-dlp self-update interval (seconds). 0 = disabled. Default: once per day.
YTDLP_UPDATE_INTERVAL = 86400

# The list of usernames to watch lives in models.txt, in the same folder as
# this script — one username per line. It's checked periodically for changes
# (no restart needed). See models.txt.example for the format, including how
# to set the refresh interval from inside that file.
MODELS_FILE_STR = "./models.txt"

# Used only if models.txt doesn't itself specify an "interval=" line.
DEFAULT_MODELS_RELOAD_INTERVAL = 120  # seconds (2 minutes)

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
MODELS_FILE  = resolve_path(MODELS_FILE_STR)

COOKIES_FILE = BASE_DIR / "Chaturdown_Cookies.txt"

_INTERVAL_LINE_RE = re.compile(r"^interval\s*=\s*(\d+)\s*$", re.IGNORECASE)
_STOP_REMOVED_LINE_RE = re.compile(r"^stop_removed\s*=\s*(true|false)\s*$", re.IGNORECASE)

def load_models_file(path: Path, default_interval: int, default_stop_removed: bool = False) -> tuple[list[str], int, bool]:
    """Read usernames and optional settings from the models file.

    Format: one username per line. Blank lines, lines starting with #, and
    anything after a # on any line (inline comments) are ignored.
      - 'interval=90' sets how often (in seconds) this file itself is
        re-checked for changes — if omitted, default_interval is used.
      - 'stop_removed=true' immediately stops an in-progress download for
        any username removed from the file. If omitted or 'false', a
        removed username's download is left to finish naturally instead.

    Returns (usernames, interval_seconds, stop_removed). usernames is an
    empty list if the file is missing, empty, or unreadable — the caller
    decides what to do with that (this script requires at least one
    username to run).
    """
    if not path.exists():
        return [], default_interval, default_stop_removed

    usernames: list[str] = []
    interval = default_interval
    stop_removed = default_stop_removed
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            # Strip inline comments too, not just full-line ones — usernames
            # never contain '#', so anything after it is safe to drop.
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            m = _INTERVAL_LINE_RE.match(line)
            if m:
                interval = int(m.group(1))
                continue
            m2 = _STOP_REMOVED_LINE_RE.match(line)
            if m2:
                stop_removed = m2.group(1).lower() == "true"
                continue
            usernames.append(line)
    except Exception:
        return [], default_interval, default_stop_removed

    return usernames, interval, stop_removed

CB_USERNAMES, MODELS_RELOAD_INTERVAL, STOP_REMOVED_DOWNLOADS = load_models_file(
    MODELS_FILE, DEFAULT_MODELS_RELOAD_INTERVAL
)

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_LOG.parent.mkdir(parents=True, exist_ok=True)

# ============================================================================
# ERROR PHRASES (clean user-facing messages)
# ============================================================================
ERROR_PHRASES = {
    "DNS":       "Network/DNS error",
    "TIMEOUT":   "Connection timeout",
    "SSL":       "SSL certificate error",
    "403":       "Forbidden / Cloudflare",
    "404":       "Username not found",
    "BAD_JSON":  "Invalid API response (Cloudflare?)",
    "EMPTY":     "Empty API response",
    "REQ_ERR":   "Request error",
    "UNKNOWN":   "Unexpected error",
}

def get_error_phrase(code: str) -> str:
    """Return a user-friendly phrase for a given error code."""
    return ERROR_PHRASES.get(code, f"{code} error")

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
# LIVE DETECTION (with detailed error reporting, no log file)
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

def check_is_live(username: str) -> tuple[bool, str, str]:
    """
    Returns:
      - live (bool): True if room is public
      - error_code (str): short error code (e.g. 'DNS', 'TIMEOUT', '403', etc.)
      - error_msg (str): human-readable message (may be empty if no error)
    """
    try:
        r = _cb_session().get(
            f"https://chaturbate.com/api/chatvideocontext/{username}/",
            timeout=15
        )
        r.raise_for_status()
        # Check if response is valid JSON
        try:
            data = r.json()
        except json.JSONDecodeError:
            # Often means Cloudflare or a login page
            preview = r.text[:200].replace('\n', ' ').strip()
            return False, "BAD_JSON", f"API returned non-JSON (maybe Cloudflare). Preview: {preview}"

        if not data:  # empty dict
            return False, "EMPTY", "API response was empty — session may be expired."

        room_status = data.get("room_status")
        if room_status == "public":
            return True, "", ""
        else:
            # room may be offline, private, etc. – not an error, just not public
            return False, "", ""

    except requests.exceptions.ConnectionError:
        return False, "DNS", "Network unreachable (DNS/connection) — check internet/firewall."
    except requests.exceptions.Timeout:
        return False, "TIMEOUT", "Request timed out after 15s — Chaturbate may be slow or unreachable."
    except requests.exceptions.SSLError:
        return False, "SSL", "SSL certificate verification failed. Update CA certs or check proxy."
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 403:
            return False, "403", "HTTP 403 Forbidden — Cloudflare blocking or cookies invalid. Export fresh cookies."
        elif status == 404:
            return False, "404", f"HTTP 404 Not Found — username '{username}' may be incorrect or deleted."
        else:
            return False, f"HTTP{status}", f"HTTP error {status} — check network or try re-login."
    except requests.exceptions.RequestException as e:
        return False, "REQ_ERR", f"Requests error: {str(e)[:100]}"
    except Exception as e:
        return False, "UNKNOWN", f"Unexpected error: {str(e)[:100]}"


def check_all_users(usernames: list[str]) -> list[str]:
    """Returns list of usernames that are currently live.
    Also updates SHARED_STATE with error info for each user.
    """
    live: list[str] = []
    lock = threading.Lock()

    def _check(u):
        is_live, err_code, err_msg = check_is_live(u)
        state = SHARED_STATE.setdefault(u, {})
        if err_code:
            # Store the error details
            state["error_code"] = err_code
            state["error_msg"] = err_msg
            state["last_error_time"] = time.time()
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        else:
            # Successful check – reset failure count
            state["error_code"] = ""
            state["error_msg"] = ""
            state["consecutive_failures"] = 0

        if is_live:
            with lock:
                live.append(u)

        # Update global API_STATUS with a clean message
        if err_code:
            phrase = get_error_phrase(err_code)
            set_api_status(f"Status: ⚠️ {phrase}")
        else:
            set_api_status("Status: Connected to Chaturbate API")

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
                # Print to stderr so it's visible in terminal scrollback
                print(f"⚠️ Stall detected for {self.target_file.stem} — terminating yt-dlp", file=sys.stderr)
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
    SHARED_STATE[username]["process"] = process

    watchdog = StallWatchdog(process, output_path)

    try:
        for line in process.stdout:
            clean_line = ansi_escape.sub('', line.strip())
            if not clean_line: continue
            watchdog.ping()

            if "giving up after" in clean_line.lower() or "unable to download" in clean_line.lower():
                set_api_status(f"Status: Stream error for {username}")
                print(f"⚠️ Stream error for {username}: {clean_line}", file=sys.stderr)
                watchdog.stop()
                _terminate_process(process, "Stream ended")
                break

    except KeyboardInterrupt:
        set_api_status(f"Status: Interrupted while downloading {username}")
        print(f"⚠️ Download interrupted by user for {username}", file=sys.stderr)
        _terminate_process(process, "User interrupt")
        watchdog.stop()
        SHARED_STATE[username]["target"] = None
        SHARED_STATE[username]["process"] = None
        _log_download(output_path.name)
        raise

    watchdog.stop()
    process.wait()

    if process.returncode != 0:
        set_api_status(f"Status: yt-dlp failed for {username} (code {process.returncode})")
        print(f"⚠️ yt-dlp failed for {username} with return code {process.returncode}", file=sys.stderr)

    _log_download(output_path.name)
    SHARED_STATE[username]["target"] = None
    SHARED_STATE[username]["process"] = None


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
    # Clear any leftover error when a download starts
    SHARED_STATE[username]["error_code"] = ""
    SHARED_STATE[username]["error_msg"] = ""

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
    global CB_USERNAMES, MODELS_RELOAD_INTERVAL, STOP_REMOVED_DOWNLOADS
    attempt = 0
    last_models_check = time.time()

    def _maybe_reload_models() -> bool:
        """Re-check models.txt if it's due. Returns True if the username
        list actually changed (so the caller can skip the rest of any snooze
        and re-poll live status right away)."""
        nonlocal usernames, last_models_check
        global CB_USERNAMES, MODELS_RELOAD_INTERVAL, STOP_REMOVED_DOWNLOADS

        if time.time() - last_models_check < MODELS_RELOAD_INTERVAL:
            return False
        last_models_check = time.time()

        new_usernames, new_interval, new_stop_removed = load_models_file(
            MODELS_FILE, DEFAULT_MODELS_RELOAD_INTERVAL, STOP_REMOVED_DOWNLOADS
        )

        if new_interval != MODELS_RELOAD_INTERVAL:
            set_api_status(f"Status: models.txt refresh interval changed to {new_interval}s")
            MODELS_RELOAD_INTERVAL = new_interval

        if new_stop_removed != STOP_REMOVED_DOWNLOADS:
            set_api_status(f"Status: models.txt stop_removed changed to {new_stop_removed}")
            STOP_REMOVED_DOWNLOADS = new_stop_removed

        if not new_usernames:
            # File went missing/empty mid-run — keep watching the current
            # list rather than dropping everyone.
            set_api_status("Status: ⚠️ models.txt is empty or unreadable — keeping current list")
            return False

        if new_usernames == usernames:
            return False

        current_set = set(usernames)
        new_set = set(new_usernames)
        added = new_set - current_set
        removed = current_set - new_set

        for u in added:
            SHARED_STATE[u] = {
                "status": "Offline",
                "progress": "",
                "start_t": time.time(),
                "target": None,
                "process": None,
                "error_code": "",
                "error_msg": "",
                "consecutive_failures": 0,
                "last_error_time": 0,
            }
        for u in removed:
            if _is_active(u):
                if STOP_REMOVED_DOWNLOADS:
                    proc = SHARED_STATE.get(u, {}).get("process")
                    if proc is not None:
                        set_api_status(f"Status: {u} removed from models.txt — stopping download")
                        # Terminate in a background thread: _terminate_process can
                        # block waiting for a graceful SIGINT exit, and we don't
                        # want to stall the watcher loop while it does.
                        threading.Thread(
                            target=_terminate_process,
                            args=(proc, "Removed from models.txt"),
                            daemon=True,
                        ).start()
                # else: leave it running, matches previous default behavior.
            else:
                # Not downloading — safe to drop its state entirely.
                SHARED_STATE.pop(u, None)

        usernames = new_usernames
        CB_USERNAMES = new_usernames
        set_api_status(f"Status: models.txt reloaded — {len(usernames)} user(s) "
                        f"(+{len(added)}/-{len(removed)})")
        return True

    try:
        while not _STOP.is_set():
            _maybe_reload_models()

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
                if _maybe_reload_models():
                    # List changed mid-snooze — go re-poll live status now
                    # instead of waiting out the rest of this snooze.
                    break
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
            SHARED_STATE[u] = {
                "status": "Offline",
                "progress": "",
                "start_t": time.time(),
                "target": None,
                "process": None,
                "error_code": "",
                "error_msg": "",
                "consecutive_failures": 0,
                "last_error_time": 0
            }

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
                    # Offline: show error icon if there's a recent error
                    err_code = s.get("error_code", "")
                    if err_code:
                        line = f"🔴 {name_pad} | ⚠️ {err_code[:8]}"
                    else:
                        line = f"🔴 {name_pad} | Offline"

                stdscr.addstr(row, 4, line[:max_x-6])
                row += 1

            stdscr.addstr(row + 1, 4, "─" * (max_x - 8))

            # Show API status
            status_line = API_STATUS[:max_x-6]
            stdscr.addstr(max_y - 2, 4, status_line, curses.A_BOLD)
            stdscr.addstr(max_y - 1, 4, "Press 'q' to stop", curses.A_DIM)

        except curses.error:
            pass # Ignore render errors caused by dragging/resizing terminal window

        key = stdscr.getch()
        if key == ord('q') or key == ord('Q'):
            _STOP.set()
            break

# ============================================================================
# STARTUP CHECK (no log file, prints once to terminal)
# ============================================================================
def perform_startup_check(usernames: list[str]) -> tuple[bool, str]:
    """
    Checks if the API is reachable for all usernames.
    Returns (ok, error_message).
    If any error other than 404 occurs, returns False with a message.
    If all errors are 404 or no errors, returns True.
    """
    for u in usernames:
        _, err_code, err_msg = check_is_live(u)
        if err_code and err_code != "404":
            phrase = get_error_phrase(err_code)
            return False, f"Cannot connect to Chaturbate API: {phrase} — {err_msg}"
    return True, ""

# ============================================================================
# EXECUTION
# ============================================================================
def main():
    usernames = [u.strip() for u in CB_USERNAMES if u.strip()]
    if not usernames:
        print("❌ Error: No usernames found.")
        print(f"   Add at least one Chaturbate username to: {MODELS_FILE}")
        print("   (one per line — see models.txt.example for the format)")
        sys.exit(1)

    if not COOKIES_FILE.exists() or COOKIES_FILE.stat().st_size < 100:
        print("❌ No cookie file for Chaturbate found, please add one to the current folder.")
        print(f"   Expected: {COOKIES_FILE}")
        sys.exit(1)

    # Pre-flight check: ensure API is reachable (ignore 404s)
    ok, msg = perform_startup_check(usernames)
    if not ok:
        print(f"❌ {msg}")
        sys.exit(1)

    # All good – launch the TUI
    watcher_thread = threading.Thread(target=watch_loop, args=(usernames,), daemon=True)
    watcher_thread.start()

    # Start the TUI – no goodbye message after exit
    curses.wrapper(draw_dashboard)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _STOP.set()
        pass
    except Exception:
        try:
            curses.endwin()
        except Exception:
            pass
        print("\n💥 The script encountered an unexpected error.")
        print("   A full traceback should appear above (or in your terminal scrollback).")
        raise
