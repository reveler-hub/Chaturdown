#!/usr/bin/env bash
""":"
exec "$(dirname "$0")/Chaturdown_Venv/bin/python3" "$0" "$@"
":"""

"""
Chaturdown (Proxy/UA Edition) — Chaturbate Multi-User Watcher & Downloader (TUI)
-------------------------------------------------------------------------
Polls multiple Chaturbate usernames via the public API.
Features a clean, interactive Terminal User Interface (TUI) to monitor
downloads in real-time without scrolling logs.

This version adds optional PROXY and USER_AGENT settings (see the
CONFIGURATION section below) for setups where Chaturbate/Cloudflare
blocks a plain connection — e.g. behind certain VPNs/proxies, or in
regions where requests need to look like they're coming from a real
browser session.

Errors and crashes surface in the terminal via standard Python tracebacks.
All connection errors are shown directly in the TUI status bar.
"""

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")

# ============================================================
# SELF-RELAUNCH — always run under this project's own venv Python, no
# matter how the script was started (double-click, system Python, a
# bare `python Chaturdown.py`, etc). Must happen before any non-stdlib
# import (curses on Windows, requests) — those only exist inside the venv.
# ============================================================
_script_dir = Path(__file__).resolve().parent
_venv_dir = _script_dir / "Chaturdown_Venv"
if IS_WINDOWS:
    _target_python = _venv_dir / "Scripts" / "python.exe"
    _already_there = Path(sys.executable).resolve() == _target_python.resolve()
else:
    _target_python = _venv_dir / "bin" / "python3"
    _already_there = Path(sys.prefix).resolve() == _venv_dir.resolve()

if not _already_there:
    if not _target_python.exists():
        print(f"Chaturdown_Venv not found at {_target_python}")
        print("Run setup.sh (Unix) or setup_windows.bat (Windows) first.")
        if IS_WINDOWS:
            input("\nPress Enter to close this window...")
        sys.exit(1)
    os.execv(str(_target_python), [str(_target_python), str(Path(__file__).resolve()), *sys.argv[1:]])

import datetime
import json
import random
import re
import shutil
import signal
import string
import subprocess
import threading
import time

try:
    import curses
except ImportError:
    print("❌ Missing dependency: 'curses' not found.")
    if IS_WINDOWS:
        print("👉 Did you forget to run setup_windows.bat first? It installs windows-curses.")
        input("\nPress Enter to close this window...")
    else:
        print("👉 Did you forget to run ./setup.sh first?")
    sys.exit(1)

_STOP = threading.Event()

try:
    import requests
except ImportError:
    print("❌ Missing dependency: 'requests' not found.")
    if IS_WINDOWS:
        print("👉 Did you forget to run setup_windows.bat first?")
        input("\nPress Enter to close this window...")
    else:
        print("👉 Did you forget to run ./setup.sh first?")
    sys.exit(1)


# ============================================================
# CONFIGURATION
# ============================================================

VIDEOS_DIR_STR   = "./Videos"
DOWNLOAD_LOG_STR = "./Chaturdown_logs.txt"

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
# RECORDING SEGMENT LIMITS (optional — 0 disables, matching today's
# unlimited-length-single-file behavior)
# ============================================================
# Stop the current recording segment once it has been running this long,
# and immediately start a new numbered segment for the same still-live
# model (e.g. {username}_002.mkv, _003.mkv, ...). 0 = no duration limit.
# Since this is plain Python, you can write an expression instead of a
# raw number for readability, e.g. 2 * 3600 for a 2-hour limit.
MAX_RECORDING_DURATION = 0    # seconds

# Stop the current recording segment once its on-disk size (the same
# total shown in the TUI's 💾 column) reaches this many megabytes, and
# start a new segment. 0 = no size limit.
MAX_RECORDING_SIZE_MB = 0     # megabytes. Example: 2000 for ~2GB segments.

# ============================================================
# FILENAME FORMAT (optional — leave as default for today's exact
# {username}_{index:03d}.mkv naming)
# ============================================================
# Template for each recording's filename, WITHOUT the extension — the
# extension is always .mkv (set by --merge-output-format above) and
# can't be changed here.
#
# Placeholders available:
#   {username}   - the model's username
#   {index:03d}  - auto-incrementing per-user segment number
#                  (use :04d etc. for different zero-padding)
#   {date}       - segment start date, YYYY-MM-DD
#   {time}       - segment start time, HH-MM-SS
#
# Chaturdown finds the next free number for a user by matching this
# template against existing filenames and capturing {index} specifically
# (not by guessing from digits in the filename), so {date}/{time}/
# {index} can appear in any order without confusing the count. The one
# real requirement: {index} must always appear somewhere in the
# template, or every segment renders to the same filename and
# overwrite/collide.
#
# Changing FILENAME_FORMAT mid-run (or between runs) is safe — files
# left over from a previous, differently-shaped template are simply
# ignored by the scan rather than affecting the new numbering.
FILENAME_FORMAT = "{username}_{index:03d}"

# ============================================================
# LOW DISK SPACE PROTECTION (optional — 0 disables, matching today's
# behavior of never checking free space)
# ============================================================
# Once free space on the drive holding VIDEOS_DIR drops below this many
# megabytes: (1) no NEW downloads are started (they show as Offline with
# a "LOW_DISK" marker in the dashboard until space recovers), and
# (2) any download ALREADY IN PROGRESS is stopped gracefully too, using
# the same 10s-interval check as the stall/duration/size watchdog. 0 =
# disabled, no checks at all.
LOW_DISK_SPACE_MB = 0

# ============================================================
# PROXY / USER-AGENT (optional — leave both blank if you don't need them)
# ============================================================
# If Chaturbate blocks your connection (a 403 error, "Cloudflare blocked",
# etc.) even with valid cookies, it's often because your IP/network looks
# suspicious to Cloudflare (VPN, proxy, certain regions), or because
# requests are missing a real browser's User-Agent. Setting both of these
# to match an actual browser session usually fixes it.
#
# PROXY: your local proxy address, if you use one. Leave as "" to disable.
#   Examples: "http://127.0.0.1:8080"  or  "socks5://127.0.0.1:1080"
PROXY = ""

# USER_AGENT: a real browser's User-Agent string. Leave as "" to disable.
# For best results, use the exact browser you used to export your cookies —
# Cloudflare can tie your session to it.
#
# To find your current browser's User-Agent, use EITHER of these:
#   1. Google: search "what is my user agent" — copy the result from the
#      AI-generated answer box at the top.
#   2. Visit https://whatsmyua.info/ — it's shown right at the top, under
#      "Enter a user-agent string:".
USER_AGENT = ""

# ============================================================
# BULK ONLINE CHECK (optional — advanced, leave False unless you know you
# want it)
# ============================================================
# By default Chaturdown checks each username in models.txt individually.
# If True, it instead makes a single request to Chaturbate's own "followed
# cams" endpoint, which reports every currently-online room the account
# tied to Chaturdown_Cookies.txt follows — much lighter on rate limits
# when watching many rooms.
#
# IMPORTANT: this only reports rooms that account actually FOLLOWS. A
# models.txt username that isn't followed there will never be detected as
# online under this mode — it will look permanently offline, silently.
# Leave this False unless every username in models.txt is followed on
# that account.
USE_FOLLOWED_ROOMS_BULK_CHECK = False

# If True (only takes effect when USE_FOLLOWED_ROOMS_BULK_CHECK is also
# True — otherwise there's no "who else is followed" data to draw from),
# any followed room the bulk check reports online is automatically
# watched too, even if it isn't listed in models.txt. This costs nothing
# extra: the bulk check already fetches every currently-online followed
# room on every poll cycle just to answer "is X in models.txt online?" —
# this setting just also uses that same response to grow the in-memory
# watch list, instead of only checking it against your models.txt
# entries.
#
# Nothing is ever written to models.txt — your file stays exactly as you
# left it, and still works normally for anyone you want to watch who
# ISN'T followed. Auto-added usernames live only in memory for this run:
# they appear on the dashboard once discovered online, and disappear
# again once they're no longer in the online-followed list — whether
# they went offline or you unfollowed them (this endpoint can't tell the
# two apart, and it doesn't matter: either way they stop being watched,
# same as normal). An active download in progress is never forced to
# stop when this happens — it's left to finish naturally, exactly like
# any other model's download when they go offline mid-recording.
AUTO_WATCH_FOLLOWED_ONLINE = False

# ============================================================
# TUI DISPLAY OPTIONS
# ============================================================
# If True, offline models are left off the dashboard entirely instead of
# showing as a red row — useful once models.txt gets long and most of it
# is usually offline. They still get checked/recorded normally either
# way; this only affects what's drawn on screen.
HIDE_OFFLINE_MODELS = False

# Show a live estimated download speed (e.g. "3.2 MB/s") next to each
# active download's size in the dashboard. yt-dlp doesn't report a
# usable speed number with the current ffmpeg-based downloader, so this
# is estimated indirectly from on-disk file-size deltas sampled every
# SPEED_SAMPLE_INTERVAL seconds.
SHOW_DOWNLOAD_SPEED = False

# How often (seconds) to resample size for the speed estimate above.
# Only used if SHOW_DOWNLOAD_SPEED is True.
SPEED_SAMPLE_INTERVAL = 2

# ============================================================
# END OF CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

def resolve_path(p_str: str) -> Path:
    p = Path(p_str).expanduser()
    return p if p.is_absolute() else (BASE_DIR / p).resolve()

VIDEOS_DIR   = resolve_path(VIDEOS_DIR_STR)
DOWNLOAD_LOG = resolve_path(DOWNLOAD_LOG_STR)
MODELS_FILE  = resolve_path(MODELS_FILE_STR)

# yt-dlp: the copy installed into Chaturdown_Venv by setup, or a global
# install on PATH otherwise — no manual configuration needed.
_venv_ytdlp = BASE_DIR / "Chaturdown_Venv" / ("Scripts/yt-dlp.exe" if IS_WINDOWS else "bin/yt-dlp")
YTDLP_EXE = str(_venv_ytdlp) if _venv_ytdlp.exists() else (shutil.which("yt-dlp") or "yt-dlp")

COOKIES_FILE = BASE_DIR / "Chaturdown_Cookies.txt"

_INTERVAL_LINE_RE = re.compile(r"^interval\s*=\s*(\d+)\s*$", re.IGNORECASE)
_STOP_REMOVED_LINE_RE = re.compile(r"^stop_removed\s*=\s*(true|false)\s*$", re.IGNORECASE)

def load_models_file(path: Path, default_interval: int, default_stop_removed: bool = False) -> tuple[list[str], int, bool]:
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

NAME_COL_WIDTH = 18

def format_name(username: str) -> str:
    """Fixed-width username column so the '|' separators after it always
    line up between rows — a plain ljust() alone doesn't truncate names
    longer than the width, which staggers every column to its right on
    any row with a long username."""
    if len(username) > NAME_COL_WIDTH:
        return username[:NAME_COL_WIDTH - 1] + "~"
    return username.ljust(NAME_COL_WIDTH)

def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable MB or GB."""
    if size_bytes <= 0:
        return "0.0 MB"
    mb = size_bytes / (1024 * 1024)
    if mb >= 1024:
        return f"{mb/1024:.2f} GB"
    return f"{mb:.1f} MB"

def format_speed(bytes_per_sec: float) -> str:
    """Format a bytes/sec rate as human-readable KB/s or MB/s."""
    if bytes_per_sec <= 0:
        return "0.0 KB/s"
    kb = bytes_per_sec / 1024
    if kb >= 1024:
        return f"{kb/1024:.2f} MB/s"
    return f"{kb:.1f} KB/s"

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
    if USER_AGENT:
        session.headers["User-Agent"] = USER_AGENT
    if PROXY:
        session.proxies.update({"http": PROXY, "https": PROXY})
    return session

def _classified_get(url: str, **kwargs) -> tuple[requests.Response | None, str, str]:
    """GET url via _cb_session(), classifying any failure into the same
    (error_code, error_msg) shape used throughout the TUI's error
    reporting. Returns (response, "", "") on success (2xx) — the caller
    still owns parsing the body. Shared by check_is_live (per-username)
    and check_followed_rooms_bulk (single bulk request), so both modes
    report failures identically.
    """
    try:
        r = _cb_session().get(url, timeout=15, **kwargs)
        r.raise_for_status()
        return r, "", ""
    except requests.exceptions.ConnectionError:
        return None, "DNS", "Network unreachable (DNS/connection) — check internet/firewall."
    except requests.exceptions.Timeout:
        return None, "TIMEOUT", "Request timed out after 15s — Chaturbate may be slow or unreachable."
    except requests.exceptions.SSLError:
        return None, "SSL", "SSL certificate verification failed. Update CA certs or check proxy."
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code
        if status == 403:
            return None, "403", "HTTP 403 Forbidden — Cloudflare blocking or cookies invalid. Export fresh cookies."
        elif status == 404:
            return None, "404", "HTTP 404 Not Found."
        else:
            return None, f"HTTP{status}", f"HTTP error {status} — check network or try re-login."
    except requests.exceptions.RequestException as e:
        return None, "REQ_ERR", f"Requests error: {str(e)[:100]}"
    except Exception as e:
        return None, "UNKNOWN", f"Unexpected error: {str(e)[:100]}"

def check_is_live(username: str) -> tuple[bool, str, str]:
    """
    Returns:
      - live (bool): True if room is public
      - error_code (str): short error code (e.g. 'DNS', 'TIMEOUT', '403', etc.)
      - error_msg (str): human-readable message (may be empty if no error)
    """
    r, err_code, err_msg = _classified_get(f"https://chaturbate.com/api/chatvideocontext/{username}/")
    if err_code:
        if err_code == "404":
            err_msg = f"HTTP 404 Not Found — username '{username}' may be incorrect or deleted."
        return False, err_code, err_msg

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

# The same endpoint chaturbate.com/followed-cams/ itself polls to find out
# which followed rooms are online — one small request instead of one per
# username. See USE_FOLLOWED_ROOMS_BULK_CHECK's config comment for the
# tradeoff (it only reports rooms the cookie's account actually follows).
FOLLOWED_ROOMS_URL = "https://chaturbate.com/follow/api/online_followed_rooms/"

def check_followed_rooms_bulk(usernames: list[str]) -> tuple[list[str], set[str]]:
    """Bulk alternative to check_all_users(): one request instead of one
    per username. Returns (live, online_set):
      - live: the subset of `usernames` currently online, intersected
        against the account's followed+online rooms — same contract as
        before. Updates SHARED_STATE/API_STATUS the same way
        check_all_users does, so the TUI doesn't need to know which mode
        is active.
      - online_set: the FULL set of currently online+followed rooms,
        unfiltered by `usernames` — used by AUTO_WATCH_FOLLOWED_ONLINE to
        discover followed models beyond what's explicitly listed. Callers
        that don't use that feature can ignore it.
    """
    response, err_code, err_msg = _classified_get(
        FOLLOWED_ROOMS_URL,
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://chaturbate.com/followed-cams/",
        },
    )

    if err_code:
        # One failed request affects every username this cycle, unlike
        # check_all_users where a failure is per-username.
        for u in usernames:
            state = SHARED_STATE.setdefault(u, {})
            state["error_code"] = err_code
            state["error_msg"] = err_msg
            state["last_error_time"] = time.time()
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        set_api_status(f"Status: ⚠️ {get_error_phrase(err_code)}")
        return [], set()

    try:
        data = response.json()
        online_set = {room["room"] for room in data.get("online_rooms", [])}
    except (json.JSONDecodeError, KeyError, TypeError):
        preview = response.text[:200].replace("\n", " ").strip()
        for u in usernames:
            state = SHARED_STATE.setdefault(u, {})
            state["error_code"] = "BAD_JSON"
            state["error_msg"] = f"followed-rooms API returned unexpected data. Preview: {preview}"
            state["last_error_time"] = time.time()
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        set_api_status(f"Status: ⚠️ {get_error_phrase('BAD_JSON')}")
        return [], set()

    live: list[str] = []
    for u in usernames:
        state = SHARED_STATE.setdefault(u, {})
        state["error_code"] = ""
        state["error_msg"] = ""
        state["consecutive_failures"] = 0
        if u in online_set:
            live.append(u)

    set_api_status("Status: Connected to Chaturbate API")
    return live, online_set

# ============================================================================
# FILE SIZE HELPER
# ============================================================================
def get_download_size(target_file: Path) -> int:
    """Return total size in bytes of all files matching the target stem."""
    try:
        return sum(f.stat().st_size for f in target_file.parent.glob(f"{target_file.stem}*") if f.is_file())
    except Exception:
        return 0

def _free_disk_mb() -> float:
    """Free space in MB on the drive holding VIDEOS_DIR. Returns inf on
    error so a transient stat failure never blocks/stops downloads."""
    try:
        return shutil.disk_usage(VIDEOS_DIR).free / (1024 * 1024)
    except Exception:
        return float("inf")

# ============================================================================
# DOWNLOAD WATCHDOG (stall / duration / size / low-disk)
# ============================================================================
class DownloadWatchdog:
    def __init__(self, process: subprocess.Popen, target_file: Path):
        self.process = process
        self.target_file = target_file
        self._stopped = False
        self._lock = threading.Lock()
        self.last_output_t = time.time()
        self.start_t = time.time()
        # Set by _run() when it trips a limit; read by download_stream()
        # after the process exits to tell a deliberate rotation
        # (duration/size — start the next segment immediately) apart from
        # a stall/low-disk/real stream end (fall through to the normal
        # next-poll-cycle relaunch).
        self.stop_reason = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        with self._lock: self._stopped = True

    def ping(self):
        with self._lock: self.last_output_t = time.time()

    def _trip(self, reason: str, status_msg: str, log_prefix: str):
        with self._lock:
            if self._stopped: return
            self.stop_reason = reason
        set_api_status(f"Status: {status_msg}")
        # Print to stderr so it's visible in terminal scrollback
        print(f"⚠️ {log_prefix} for {self.target_file.stem} — terminating yt-dlp", file=sys.stderr)
        _terminate_process(self.process, status_msg)

    def _run(self):
        while True:
            time.sleep(10)
            with self._lock:
                if self._stopped: return
                silence = time.time() - self.last_output_t
            if self.process.poll() is not None: return

            if silence > STALL_TIMEOUT:
                self._trip("stall", "Stall detected — download stopped", "Stall detected")
                return

            if MAX_RECORDING_DURATION > 0 and (time.time() - self.start_t) > MAX_RECORDING_DURATION:
                self._trip("duration", "Duration limit reached — starting new segment", "Duration limit reached")
                return

            if MAX_RECORDING_SIZE_MB > 0:
                size_b = get_download_size(self.target_file)
                if size_b > MAX_RECORDING_SIZE_MB * 1024 * 1024:
                    self._trip("size", "Size limit reached — starting new segment", "Size limit reached")
                    return

            if LOW_DISK_SPACE_MB > 0 and _free_disk_mb() < LOW_DISK_SPACE_MB:
                self._trip("low_disk", "Low disk space — download stopped", "Low disk space")
                return

def _get_child_pids(pid: int) -> list[int]:
    """Direct child PIDs of pid, right now. Must be captured BEFORE the
    parent exits — once it does, its children are reparented elsewhere
    (typically to PID 1, or the equivalent on Windows) and can no longer
    be found by "children of this pid", which is why _terminate_process
    snapshots this early rather than querying it after the parent is
    already gone."""
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter \"ParentProcessId={pid}\").ProcessId"],
                capture_output=True, text=True, timeout=5,
            )
        else:
            result = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True, timeout=5)
        return [int(p) for p in result.stdout.split()]
    except Exception:
        return []

def _terminate_process(process: subprocess.Popen, reason: str):
    """Send a graceful stop signal to yt-dlp (SIGINT on Unix,
    CTRL_BREAK_EVENT on Windows — plain SIGINT isn't a valid targeted
    signal there); force-kill after 30 seconds if still running. Either
    way, any child process it had at the start (the ffmpeg process
    yt-dlp delegates the actual downloading to via --downloader ffmpeg)
    is explicitly killed afterward too if it's still alive — yt-dlp
    doesn't always reliably kill that child itself before exiting, and a
    plain force-kill of just the parent PID never propagates to children
    at all either way, otherwise ffmpeg can be left running and still
    writing to disk indefinitely on its own."""
    if process.poll() is not None:
        return

    children_pids = _get_child_pids(process.pid)

    try:
        process.send_signal(signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGINT)
    except Exception:
        pass

    # Wait up to 30 seconds for clean exit after the graceful signal
    for _ in range(30):
        if process.poll() is not None:
            break
        time.sleep(1)
    else:
        # Still alive after 30s → hard kill
        try:
            process.kill()
        except Exception:
            pass

    for child_pid in children_pids:
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/PID", str(child_pid)], capture_output=True, timeout=5)
            else:
                os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # already exited on its own — the common/expected case
        except Exception:
            pass

# ============================================================================
# DOWNLOAD ENGINE
# ============================================================================
def _validate_filename_format() -> tuple[bool, str]:
    if "{index" not in FILENAME_FORMAT:
        return False, "FILENAME_FORMAT must contain {index} — otherwise every segment renders to the same filename."
    try:
        FILENAME_FORMAT.format(username="test", index=1, date="2026-01-01", time="00-00-00")
    except Exception as e:
        return False, f"FILENAME_FORMAT is invalid: {e}"
    return True, ""

def _filename_index_pattern(username: str) -> re.Pattern:
    """Build a regex that matches only filenames actually shaped like
    FILENAME_FORMAT for this username, capturing {index} specifically —
    rather than guessing from "the biggest digit-run anywhere in the
    filename" (which used to misfire whenever two adjacent placeholders
    rendered with no separator between them, e.g. {time}{index} both
    being digits fusing into one bogus number). Files that don't match
    the current template's shape (e.g. left over from an earlier,
    different FILENAME_FORMAT) are simply ignored instead of corrupting
    the count.
    """
    parts = [r"^"]
    for literal_text, field_name, _format_spec, _ in string.Formatter().parse(FILENAME_FORMAT):
        parts.append(re.escape(literal_text))
        if field_name == "index":
            parts.append(r"(\d+)")
        elif field_name == "username":
            parts.append(re.escape(username))
        elif field_name == "date":
            parts.append(r"\d{4}-\d{2}-\d{2}")
        elif field_name == "time":
            parts.append(r"\d{2}-\d{2}-\d{2}")
        elif field_name is not None:
            parts.append(r".+?")
    parts.append(r"\.mkv$")
    return re.compile("".join(parts))

def _next_filename(username: str) -> Path:
    out_folder = VIDEOS_DIR / username
    out_folder.mkdir(parents=True, exist_ok=True)

    pattern = _filename_index_pattern(username)
    existing_numbers = []
    for f in out_folder.iterdir():
        if not f.is_file():
            continue
        m = pattern.match(f.name)
        if m:
            existing_numbers.append(int(m.group(1)))

    next_n = (max(existing_numbers) + 1) if existing_numbers else 1

    now = datetime.datetime.now()
    name = FILENAME_FORMAT.format(
        username=username,
        index=next_n,
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H-%M-%S"),
    )
    return out_folder / f"{name}.mkv"

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
    if USER_AGENT:
        cmd += ["--user-agent", USER_AGENT]
    if PROXY:
        cmd += ["--proxy", PROXY]
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


def download_stream(username: str) -> bool:
    """Runs one recording segment. Returns True if the segment ended
    because a duration/size limit tripped (caller should immediately
    start the next segment), False otherwise (stall, low disk, real
    stream end, or non-zero exit — caller waits for the next poll)."""
    output_path = _next_filename(username)
    SHARED_STATE[username]["target"] = output_path

    process = subprocess.Popen(
        _build_ytdlp_cmd(username, output_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        # On Windows, isolates this process (and its ffmpeg child) into
        # its own process group so a later CTRL_BREAK_EVENT can target
        # just it, instead of the whole console. No effect on Unix.
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0),
    )
    SHARED_STATE[username]["process"] = process

    watchdog = DownloadWatchdog(process, output_path)

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

    if watchdog.stop_reason:
        # We deliberately stopped this ourselves (stall/duration/size/
        # low-disk) — DownloadWatchdog._trip() already set an accurate
        # status message when it tripped. yt-dlp exiting non-zero (often
        # a signal-termination code, e.g. Windows' STATUS_CONTROL_C_EXIT
        # after CTRL_BREAK_EVENT) is the expected, normal result of that,
        # not a real failure — don't clobber that message with a scary
        # "yt-dlp failed" one.
        pass
    elif process.returncode != 0:
        if get_download_size(output_path) == 0:
            # Nothing was ever written — almost always means the room
            # wasn't actually public anymore by the time yt-dlp connected
            # (it went offline/private in the gap between the last poll
            # and this launch). Not worth alarming the live status bar
            # over; still logged to the terminal for anyone diagnosing a
            # real, persistent problem.
            print(f"ℹ️ {username}: yt-dlp exited (code {process.returncode}) without writing any "
                  f"data — likely wasn't actually public by connection time.", file=sys.stderr)
        else:
            set_api_status(f"Status: yt-dlp failed for {username} (code {process.returncode})")
            print(f"⚠️ yt-dlp failed for {username} with return code {process.returncode}", file=sys.stderr)

    _log_download(output_path.name)
    SHARED_STATE[username]["target"] = None
    SHARED_STATE[username]["process"] = None

    return watchdog.stop_reason in ("duration", "size")


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
            while True:
                rotate = download_stream(username)
                if not rotate or _STOP.is_set():
                    break
                # Duration/size limit tripped and the model is still the
                # same live session — start the next segment immediately
                # rather than waiting out the next poll cycle.
                SHARED_STATE[username]["start_t"] = time.time()
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

def _shutdown_active_downloads() -> None:
    """Stops every in-progress download — called once the TUI loop exits
    (whether via 'q' or a fatal watcher error). Without this, a download
    that's active at shutdown time is left running as a fully orphaned
    process: the Python script exiting does NOT kill child processes it
    spawned via subprocess.Popen, and none of that download's watchdog
    logic (stall detection, duration/size limits) is supervising it
    anymore either, since that lived in this now-dead script.
    """
    with _active_lock:
        active_usernames = list(_active.keys())
        threads = list(_active.values())
    if not active_usernames:
        return

    print(f"Stopping {len(active_usernames)} active download(s)...")
    for u in active_usernames:
        proc = SHARED_STATE.get(u, {}).get("process")
        if proc is not None and proc.poll() is None:
            # Terminate in background threads so multiple active
            # downloads' up-to-30s graceful-SIGINT waits (see
            # _terminate_process) happen in parallel, not serialized.
            threading.Thread(
                target=_terminate_process,
                args=(proc, "App shutdown"),
                daemon=True,
            ).start()

    for t in threads:
        t.join(timeout=35)
    print("All downloads stopped.")

def watch_loop(usernames: list[str]):
    global CB_USERNAMES, MODELS_RELOAD_INTERVAL, STOP_REMOVED_DOWNLOADS
    attempt = 0
    last_models_check = time.time()
    auto_watched: set[str] = set()

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

    def _sync_auto_watched(online_set: set[str]) -> None:
        """Grows/shrinks the in-memory watch list with followed rooms the
        bulk check reports online, on top of whatever's explicitly in
        models.txt. Only called when AUTO_WATCH_FOLLOWED_ONLINE is on.
        Mirrors _maybe_reload_models's add/remove diffing, but the source
        of truth is this cycle's online-followed set instead of the file.
        """
        nonlocal auto_watched
        global CB_USERNAMES

        explicit = set(usernames)
        auto_online_now = online_set - explicit

        newly = auto_online_now - auto_watched
        for u in newly:
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

        dropped = auto_watched - auto_online_now
        still_finishing = set()
        for u in dropped:
            if _is_active(u):
                # Still downloading — leave it running and keep tracking
                # it until the download finishes naturally, exactly like
                # any other model's in-progress download when they go
                # offline mid-recording (never forcibly stopped by a
                # status change alone).
                still_finishing.add(u)
            else:
                SHARED_STATE.pop(u, None)

        auto_watched = auto_online_now | still_finishing
        CB_USERNAMES = usernames + sorted(auto_watched - explicit)

    try:
        while not _STOP.is_set():
            _maybe_reload_models()

            attempt += 1
            _maybe_update_yt_dlp()
            if USE_FOLLOWED_ROOMS_BULK_CHECK:
                live_users, online_set = check_followed_rooms_bulk(usernames)
            else:
                live_users = check_all_users(usernames)
                online_set = set(live_users)

            if USE_FOLLOWED_ROOMS_BULK_CHECK and AUTO_WATCH_FOLLOWED_ONLINE:
                _sync_auto_watched(online_set)

            for u in CB_USERNAMES:
                is_live = u in online_set
                is_dl = _is_active(u)

                if is_live or is_dl:
                    if is_live and not is_dl:
                        if LOW_DISK_SPACE_MB > 0 and _free_disk_mb() < LOW_DISK_SPACE_MB:
                            # The dashboard's low-disk banner (drawn in
                            # draw_dashboard) already covers this clearly
                            # and persistently — no need to also spam the
                            # bottom status bar once per affected model.
                            SHARED_STATE[u]["status"] = "Offline"
                            SHARED_STATE[u]["error_code"] = "LOW_DISK"
                            SHARED_STATE[u]["error_msg"] = "Low disk space — download not started"
                            continue
                        SHARED_STATE[u]["status"] = "Online"
                        _launch(u)
                    else:
                        SHARED_STATE[u]["status"] = "Online"
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
# windows-curses (PDCurses-based) uses a 16-bit wchar_t, so it can't
# represent any codepoint above U+FFFF — which is most of the colorful
# emoji used on Unix below (📡🟢🔴💾🚀 are all astral-plane U+1Fxxx).
# ⏱️ happens to render fine there since its base codepoint (U+23F1) is
# in the BMP, but is swapped too for a consistent look with the rest.
if IS_WINDOWS:
    ICON_HEADER, ICON_ONLINE, ICON_OFFLINE = "", "●", "●"
    ICON_TIMER, ICON_DISK, ICON_SPEED, ICON_WARN = "Time:", "Size:", "Speed:", "!"
else:
    ICON_HEADER, ICON_ONLINE, ICON_OFFLINE = "📡", "🟢", "🔴"
    ICON_TIMER, ICON_DISK, ICON_SPEED, ICON_WARN = "⏱️", "💾", "🚀", "⚠️"

_ASTRAL_RE = re.compile(r"[\U00010000-\U0010FFFF]")

def _win_safe_text(text: str) -> str:
    """Makes arbitrary, dynamically-built status text (API_STATUS is
    constructed by many call sites throughout this file, each embedding
    their own emoji inline) safe for windows-curses. No-op on Unix."""
    if not IS_WINDOWS:
        return text
    return _ASTRAL_RE.sub("", text.replace("⚠️", ICON_WARN))

# username -> (last_sample_t, last_sample_bytes, last_bps). Render-thread-only
# state for the speed estimate — resampled every SPEED_SAMPLE_INTERVAL
# seconds so the reading isn't noisy at the 500ms render tick.
_speed_state: dict[str, tuple[float, int, float]] = {}

def _sample_speed(username: str, size_b: int) -> float:
    now = time.time()
    prev = _speed_state.get(username)
    if prev is None:
        _speed_state[username] = (now, size_b, 0.0)
        return 0.0
    prev_t, prev_bytes, prev_bps = prev
    if now - prev_t < SPEED_SAMPLE_INTERVAL:
        return prev_bps
    dt = now - prev_t
    bps = max(size_b - prev_bytes, 0) / dt
    _speed_state[username] = (now, size_b, bps)
    return bps

def _max_row_width() -> int:
    """Worst-case on-screen width of one model row (SHOW_DOWNLOAD_SPEED
    on — the longest case), used to auto-fit how many side-by-side
    columns the dashboard uses. Measured from a sample rather than
    hardcoded, so it tracks the real row format automatically. Padded a
    little extra on Unix since emoji commonly render double-width in a
    terminal but len() only counts them as one character each — exact
    measurement isn't possible without knowing the specific terminal/
    font, so this errs slightly generous rather than risk columns
    overlapping.
    """
    sample = (f"{ICON_ONLINE} {format_name('sample_user')} | Online  | "
              f"{ICON_TIMER} 23:59:59 | {ICON_DISK} {'999.9 MB'.rjust(8)} | "
              f"{ICON_SPEED} {'999.9 KB/s'.rjust(9)}")
    width = len(sample)
    return width + (6 if not IS_WINDOWS else 0)

def draw_dashboard(stdscr):
    curses.curs_set(0)
    stdscr.timeout(500)

    # Windows loses the emoji's built-in color-coding (see ICON_ONLINE/
    # ICON_OFFLINE above), so make up for it with real curses colors on
    # the replacement ● character instead. Unix doesn't need this — its
    # emoji already convey online=green/offline=red on their own.
    online_attr = curses.A_NORMAL
    offline_attr = curses.A_NORMAL
    if IS_WINDOWS and curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_RED, -1)
        online_attr = curses.color_pair(1) | curses.A_BOLD
        offline_attr = curses.color_pair(2) | curses.A_BOLD

    col_target_width = _max_row_width()

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
            stdscr.addstr(2, 4, f"{ICON_HEADER} CHATURBATE MULTI-DOWNLOADER TUI".strip(), curses.A_BOLD)
            stdscr.addstr(3, 4, "─" * (max_x - 8))

            header_row = 5
            # Low disk space is a system-wide condition (checked against
            # the whole VIDEOS_DIR drive, not per-model), so it's shown
            # as one banner here in the list area instead of repeating a
            # per-row warning on whichever models happen to be affected.
            if LOW_DISK_SPACE_MB > 0 and _free_disk_mb() < LOW_DISK_SPACE_MB:
                banner = f"{ICON_WARN}  LOW DISK SPACE — NOT STARTING DOWNLOADS"
                stdscr.addstr(header_row, 4, banner[:max_x-6], curses.A_BOLD)
                header_row += 2

            display_usernames = [
                u for u in CB_USERNAMES
                if not HIDE_OFFLINE_MODELS or SHARED_STATE.get(u, {}).get("status", "Offline") != "Offline"
            ]
            hidden_count = len(CB_USERNAMES) - len(display_usernames)

            # Arrange rows into side-by-side columns instead of one tall
            # list — fills column 1 top-to-bottom, then column 2, etc.
            # Auto-fit from the terminal's actual width, so a narrow
            # terminal still gets exactly 1 column (today's behavior)
            # while a wide one uses the space a single column used to
            # leave empty. There's still a hard cutoff once every column
            # is full (see the "+N more not shown" footer note below for
            # why that's no longer silent).
            rows_per_column = max(1, (max_y - 4) - header_row)
            num_columns = max(1, (max_x - 8) // col_target_width)
            col_width = (max_x - 8) // num_columns

            shown = 0
            for idx, u in enumerate(display_usernames):
                col = idx // rows_per_column
                row_in_col = idx % rows_per_column
                if col >= num_columns: break

                s = SHARED_STATE.get(u, {})
                status = s.get("status", "Offline")
                name_pad = format_name(u)

                if status == "Online":
                    elapsed = time.time() - s.get("start_t", time.time())
                    t_str = format_time(elapsed)

                    target = s.get("target")
                    size_b = get_download_size(Path(target)) if target else 0
                    size_str = format_size(size_b).rjust(8)

                    speed_str = ""
                    if SHOW_DOWNLOAD_SPEED and target:
                        bps = _sample_speed(u, size_b)
                        speed_str = f" | {ICON_SPEED} {format_speed(bps).rjust(9)}"

                    icon, icon_attr = ICON_ONLINE, online_attr
                    rest = f" {name_pad} | Online  | {ICON_TIMER} {t_str} | {ICON_DISK} {size_str}{speed_str}"
                else:
                    _speed_state.pop(u, None)
                    # Offline: show error icon if there's a recent error
                    err_code = s.get("error_code", "")
                    icon, icon_attr = ICON_OFFLINE, offline_attr
                    if err_code:
                        rest = f" {name_pad} | {ICON_WARN} {err_code[:8]}"
                    else:
                        rest = f" {name_pad} | Offline"

                x = 4 + col * col_width
                y = header_row + row_in_col
                if IS_WINDOWS:
                    # Split so the online/offline dot can carry its own
                    # color — safe here since these replacement icons are
                    # single-width; the Unix emoji below are not, so this
                    # column math is intentionally NOT used on Unix.
                    stdscr.addstr(y, x, icon, icon_attr)
                    stdscr.addstr(y, x + len(icon), rest[:col_width-2-len(icon)])
                else:
                    stdscr.addstr(y, x, (icon + rest)[:col_width-2])
                shown += 1

            separator_row = header_row + rows_per_column + 1
            stdscr.addstr(separator_row, 4, "─" * (max_x - 8))

            # Show API status
            status_line = _win_safe_text(API_STATUS)[:max_x-6]
            stdscr.addstr(max_y - 2, 4, status_line, curses.A_BOLD)
            footer = "Press 'q' to stop"
            if HIDE_OFFLINE_MODELS and hidden_count:
                footer += f"  ({hidden_count} offline hidden)"
            truncated = len(display_usernames) - shown
            if truncated > 0:
                footer += f"  (+{truncated} more not shown)"
            stdscr.addstr(max_y - 1, 4, footer[:max_x-6], curses.A_DIM)

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
    if USE_FOLLOWED_ROOMS_BULK_CHECK:
        # No per-username 404 concept for this single fixed endpoint —
        # just confirm it's reachable at all.
        response, err_code, err_msg = _classified_get(
            FOLLOWED_ROOMS_URL,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://chaturbate.com/followed-cams/",
            },
        )
        if err_code:
            phrase = get_error_phrase(err_code)
            return False, f"Cannot connect to Chaturbate API: {phrase} — {err_msg}"

        # Cheap sanity check: if the account follows fewer rooms than
        # models.txt lists, at least some entries can't possibly be
        # detected as online under bulk mode — surface that now rather
        # than have it look like a silent, permanent "Offline".
        try:
            total_followed = response.json().get("total", 0)
            if total_followed < len(usernames):
                print(f"⚠️  Warning: this account follows {total_followed} room(s), but "
                      f"models.txt lists {len(usernames)}. USE_FOLLOWED_ROOMS_BULK_CHECK "
                      f"only detects rooms this account follows — some models.txt entries "
                      f"may never be detected as online. Follow them on this account, or "
                      f"set USE_FOLLOWED_ROOMS_BULK_CHECK = False.")
        except (json.JSONDecodeError, AttributeError):
            pass  # non-fatal — the reachability check above already passed
        return True, ""

    for u in usernames:
        _, err_code, err_msg = check_is_live(u)
        if err_code and err_code != "404":
            phrase = get_error_phrase(err_code)
            return False, f"Cannot connect to Chaturbate API: {phrase} — {err_msg}"
    return True, ""

# ============================================================================
# EXECUTION
# ============================================================================
def _fail(*lines: str) -> None:
    """Print an error and exit. On Windows, pauses for a keypress first —
    the console closes the instant the process exits there, unlike a
    Unix terminal's scrollback, so without this the message would flash
    and vanish before anyone could read it (e.g. on a double-click launch)."""
    for line in lines:
        print(line)
    if IS_WINDOWS:
        input("\nPress Enter to close this window...")
    sys.exit(1)

def main():
    usernames = [u.strip() for u in CB_USERNAMES if u.strip()]
    if not usernames:
        _fail(
            "❌ Error: No usernames found.",
            f"   Add at least one Chaturbate username to: {MODELS_FILE}",
            "   (one per line — see models.txt.example for the format)",
        )

    if not COOKIES_FILE.exists() or COOKIES_FILE.stat().st_size < 100:
        _fail(
            "❌ No cookie file for Chaturbate found, please add one to the current folder.",
            f"   Expected: {COOKIES_FILE}",
        )

    ok, msg = _validate_filename_format()
    if not ok:
        _fail(f"❌ {msg}")

    # Pre-flight check: ensure API is reachable (ignore 404s)
    ok, msg = perform_startup_check(usernames)
    if not ok:
        _fail(f"❌ {msg}")

    # All good – launch the TUI
    watcher_thread = threading.Thread(target=watch_loop, args=(usernames,), daemon=True)
    watcher_thread.start()

    # Start the TUI – no goodbye message after exit
    curses.wrapper(draw_dashboard)

    # 'q' (or a fatal watcher error) means stop everything, not just the
    # TUI — see _shutdown_active_downloads' docstring for why this matters.
    _shutdown_active_downloads()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _STOP.set()
        _shutdown_active_downloads()
    except Exception:
        try:
            curses.endwin()
        except Exception:
            pass
        _STOP.set()
        _shutdown_active_downloads()
        print("\n💥 The script encountered an unexpected error.")
        import traceback
        traceback.print_exc()
        if IS_WINDOWS:
            input("\nPress Enter to close this window...")
        sys.exit(1)
