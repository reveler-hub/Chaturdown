#!/usr/bin/env python3
"""
chaturdown.py — Multi-User Chaturbate Downloader
------------------------------------------------
Polls multiple Chaturbate usernames via the public API (no browser needed).
When a room goes live, a download thread is spawned so multiple streams
can download in parallel.

Each download shows a single updating line:
  [username] [download]  38.4% of ~512MiB at  8.2MiB/s ETA 01:45

Cookies are harvested via Camoufox at startup and refreshed hourly.

Usage:
    python3 chaturdown.py
"""

import datetime
import random
import re
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

_STOP = threading.Event()  # set to stop all threads cleanly

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests")
    sys.exit(1)

# ========================== CONFIG ==========================
# Update these paths to match your local environment
YTDLP_EXE          = Path("/usr/local/bin/yt-dlp")
CAMOUFOX_PROFILE   = Path("./Profiles/chaturdown_profile")
CB_USERNAME        = "YOUR_USERNAME_HERE"
CB_PASSWORD        = "YOUR_PASSWORD_HERE"
COOKIES_FILE       = Path("./chaturdown_cookies.txt")
VIDEOS_DIR         = Path("./Videos/Chaturbate")
DOWNLOAD_LOG       = Path("./chaturdown_log.txt")
STREAMS_DIR        = Path("./Streams")

CB_USERNAMES = [
    "model_username_1",
    "model_username_2",
]

# Seconds between poll cycles
POLL_MIN = 60
POLL_MAX = 120

# Seconds to wait for yt-dlp to stop after SIGINT
MUX_TIMEOUT = 300

# Seconds of silence from yt-dlp before assuming stream has stalled
STALL_TIMEOUT = 60

# How old cookies can be before re-harvesting (seconds)
COOKIE_MAX_AGE = 3600  # 1 hour

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
STREAMS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================================
# LOGGING
# ============================================================================

def log(msg: str):
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)

# ============================================================================
# COOKIE HARVESTING
# ============================================================================

def harvest_cookies() -> bool:
    """
    Open Chaturbate, log in if necessary, and extract cookies for yt-dlp.
    Skips if cookies are still fresh (< COOKIE_MAX_AGE seconds old).
    """
    if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 100:
        age = time.time() - COOKIES_FILE.stat().st_mtime
        if age < COOKIE_MAX_AGE:
            log(f"   Cookies fresh ({int(age)}s old) — skipping harvest")
            return True
    elif COOKIES_FILE.exists():
        log("   Cookie file exists but is empty — forcing re-harvest")

    log("Harvesting/Refreshing Chaturbate cookies via Camoufox...")
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        log("   camoufox not installed — skipping cookie harvest")
        return False

    try:
        with Camoufox(
            headless=True,
            persistent_context=True,
            user_data_dir=str(CAMOUFOX_PROFILE),
        ) as context:
            page = context.pages[0] if context.pages else context.new_page()

            # Go straight to login page to bypass 18+ splash
            page.goto("https://chaturbate.com/auth/login/", wait_until="domcontentloaded", timeout=55_000)
            page.wait_for_timeout(3_000)

            content = page.content().lower()

            # If we see the login form, we need to log in
            if "name=\"username\"" in content and "type=\"password\"" in content:
                log("   Session expired or logged out. Attempting auto-login...")
                page.locator("input[name='username']").fill(CB_USERNAME)
                page.locator("input[name='password']").fill(CB_PASSWORD)
                page.locator("input[type='submit']").first.click()

                # Take time to process the login and Cloudflare
                log("   Waiting for login to process...")
                page.wait_for_timeout(10_000)

                # Navigate somewhere safe to verify
                page.goto("https://chaturbate.com/messages/", wait_until="domcontentloaded", timeout=55_000)
                page.wait_for_timeout(3_000)

                if "messages" not in page.content().lower():
                    log("   Auto-login failed! Check credentials or Cloudflare might be blocking.")
                    return False
                log("   Auto-login successful!")
            elif "log out" not in content and "my_account" not in content:
                log("   Page didn't load correctly or stuck on a challenge. Cannot harvest.")
                return False

            # Harvest the cookies
            cookies = context.cookies()
            lines = ["# Netscape HTTP Cookie File\n"]
            saved = 0
            for c in cookies:
                d = c.get("domain", "")
                if "chaturbate" not in d:
                    continue
                flag    = "TRUE" if d.startswith(".") else "FALSE"
                path    = c.get("path", "/")
                secure  = "TRUE" if c.get("secure", False) else "FALSE"
                exp_raw = c.get("expires", -1)
                expires = "0" if exp_raw == -1 else str(int(exp_raw))
                lines.append(f"{d}\t{flag}\t{path}\t{secure}\t{expires}\t{c['name']}\t{c['value']}\n")
                saved += 1

            if saved == 0:
                log("   No Chaturbate cookies found after login attempt.")
                return False

            COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(COOKIES_FILE, "w") as f:
                f.writelines(lines)
            log(f"   Saved {saved} Chaturbate cookies → {COOKIES_FILE.name}")
            return True

    except Exception as e:
        log(f"   Camoufox error during harvest: {e}")
        return False

# ============================================================================
# LIVE DETECTION
# ============================================================================

def _cb_session() -> requests.Session:
    """Build a requests Session with Chaturbate cookies from chaturdown_cookies.txt."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
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
    """Hit the Chaturbate API with session cookies. Returns True if the room is publicly live."""
    try:
        r = _cb_session().get(
            f"https://chaturbate.com/api/chatvideocontext/{username}/",
            timeout=15,
        )
        r.raise_for_status()
        if not r.text.strip():
            log(f"   CB API empty response ({username}) — session may need re-login")
            return False
        return r.json().get("room_status") == "public"
    except ValueError:
        log(f"   CB API non-JSON ({username}) — verification page may be blocking requests")
        log("   Stopping script — re-login required.")
        _STOP.set()
        return False
    except Exception as e:
        log(f"   CB check error ({username}): {e}")
        return False


def check_all_users(usernames: list[str]) -> list[str]:
    """Check all usernames in parallel (plain HTTP — safe to do concurrently)."""
    live: list[str] = []
    lock  = threading.Lock()

    def _check(u):
        if check_is_live(u):
            with lock:
                live.append(u)

    threads = [threading.Thread(target=_check, args=(u,)) for u in usernames if u]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return live

# ============================================================================
# STALL WATCHDOG
# ============================================================================

class StallWatchdog:
    """Triggers a SIGINT if yt-dlp produces no output for STALL_TIMEOUT seconds."""

    def __init__(self, process: subprocess.Popen, temp_folder: Path):
        self.process       = process
        self.temp_folder   = temp_folder
        self._stopped      = False
        self._lock         = threading.Lock()
        self.last_output_t = time.time()
        self._thread       = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        with self._lock:
            self._stopped = True

    def ping(self):
        with self._lock:
            self.last_output_t = time.time()

    def _run(self):
        while True:
            time.sleep(10)
            with self._lock:
                if self._stopped:
                    return
                silence = time.time() - self.last_output_t
            if self.process.poll() is not None:
                return
            if silence > STALL_TIMEOUT:
                log(f"   No output for {int(silence)}s — stall detected, stopping")
                _sigint_and_wait(self.process, "Stall detected", self.temp_folder)
                return

# ============================================================================
# SIGINT HELPER
# ============================================================================

def _sigint_and_wait(process: subprocess.Popen, reason: str, temp_folder: Path):
    if process.poll() is not None:
        return
    log(f"   {reason} — sending SIGINT...")
    try:
        process.send_signal(signal.SIGINT)
    except Exception as e:
        log(f"   Error sending SIGINT: {e}")
        process.kill()
        return

    start_t          = time.time()
    last_size        = -1
    last_size_change = time.time()
    STALL_S          = 60

    while True:
        time.sleep(5)
        if process.poll() is not None:
            return
        elapsed = int(time.time() - start_t)
        if elapsed > MUX_TIMEOUT:
            log(f"   Timeout ({MUX_TIMEOUT // 60} min) — force killing.")
            process.kill()
            return
        try:
            files = [f for f in temp_folder.iterdir() if f.is_file()]
            current_size = sum(f.stat().st_size for f in files) if files else 0
        except Exception:
            current_size = 0
        if current_size != last_size:
            log(f"   Stopping... {current_size / 1024 / 1024:.1f} MB  [{elapsed}s]")
            last_size        = current_size
            last_size_change = time.time()
        elif time.time() - last_size_change > STALL_S:
            log(f"   No progress for {STALL_S}s — force killing.")
            process.kill()
            return

# ============================================================================
# DOWNLOAD
# ============================================================================

def _next_filename(username: str, temp_folder: Path) -> Path:
    out_folder = VIDEOS_DIR / username
    existing   = []
    if out_folder.exists():
        for f in out_folder.glob(f"{username}_*.mp4"):
            m = re.match(rf"^{re.escape(username)}_(\d+)\.mp4$", f.name)
            if m:
                existing.append(int(m.group(1)))
    next_n = (max(existing) + 1) if existing else 1
    return temp_folder / f"{username}_{next_n:03d}.mp4"


def _build_ytdlp_cmd(username: str, output_path: Path) -> list[str]:
    cmd = [
        str(YTDLP_EXE),
        f"https://chaturbate.com/{username}/",
        "--output",     str(output_path),
        "--user-agent", USER_AGENT,
        "--hls-use-mpegts",
        "--merge-output-format", "mp4",
        "--fragment-retries", "5",
        "--retries",    "5",
        "--no-part",
    ]
    if COOKIES_FILE.exists():
        cmd += ["--cookies", str(COOKIES_FILE)]
    return cmd


def _log_download(filename: str) -> None:
    """Append filename to the download log, then prune entries older than 2 days."""
    today     = datetime.date.today()
    date_str  = f"{today.day}/{today.month}/{today.year}"
    cutoff    = today - datetime.timedelta(days=2)

    existing = DOWNLOAD_LOG.read_text() if DOWNLOAD_LOG.exists() else ""

    lines = existing.rstrip("\n").split("\n") if existing.strip() else []
    if lines and lines[-1] == date_str:
        lines.append(filename)
    else:
        if lines:
            lines.append("")
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

    while pruned and pruned[0] == "":
        pruned.pop(0)

    DOWNLOAD_LOG.write_text("\n".join(pruned) + "\n")


def _move_to_final(username: str, temp_folder: Path, log_it: bool = True) -> None:
    out_folder = VIDEOS_DIR / username
    out_folder.mkdir(parents=True, exist_ok=True)
    for src in [f for f in temp_folder.iterdir() if f.is_file()]:
        dest = out_folder / src.name
        log(f"   Moving → {username}/{dest.name}")
        shutil.move(str(src), str(dest))
        if log_it:
            _log_download(dest.name)


def download_stream(username: str) -> None:
    """Download one CB stream. Blocks until complete."""
    temp_folder = STREAMS_DIR / username
    temp_folder.mkdir(parents=True, exist_ok=True)
    output_path = _next_filename(username, temp_folder)
    prefix      = f"[{username}] "

    log(f"{prefix}Starting — https://chaturbate.com/{username}/")
    log(f"{prefix}Output: {output_path.name}  |  Stall timeout: {STALL_TIMEOUT}s")

    process = subprocess.Popen(
        _build_ytdlp_cmd(username, output_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    watchdog      = StallWatchdog(process, temp_folder)
    _on_progress  = False

    try:
        for line in process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            watchdog.ping()

            if "[download]" in stripped and ("%" in stripped or "frag" in stripped or " at " in stripped):
                print(f"\r\033[K{prefix}{stripped}", end="", flush=True)
                _on_progress = True
            else:
                if _on_progress:
                    print()
                    _on_progress = False
                if "giving up after" in stripped.lower() or "unable to download" in stripped.lower():
                    log(f"{prefix}Stream error — triggering stop.")
                    watchdog.stop()
                    _sigint_and_wait(process, "Stream ended", temp_folder)
                    break
                else:
                    print(f"{prefix}{stripped}", flush=True)
    except KeyboardInterrupt:
        if _on_progress:
            print()
        log(f"\n{prefix}Interrupted — muxing and saving partial file...")
        _sigint_and_wait(process, "User interrupt", temp_folder)
        watchdog.stop()
        _move_to_final(username, temp_folder, log_it=False)
        raise

    if _on_progress:
        print()

    watchdog.stop()
    process.wait()

    if process.returncode == 0:
        log(f"{prefix}Download complete.")
    else:
        log(f"{prefix}yt-dlp exited with code {process.returncode}.")

    _move_to_final(username, temp_folder)

# ============================================================================
# ACTIVE DOWNLOAD TRACKING
# ============================================================================

_active: dict[str, threading.Thread] = {}
_active_lock = threading.Lock()


def _is_active(username: str) -> bool:
    with _active_lock:
        t = _active.get(username)
        if t is None:
            return False
        if not t.is_alive():
            del _active[username]
            return False
        return True


def _launch(username: str):
    def _run():
        download_stream(username)
        with _active_lock:
            _active.pop(username, None)

    t = threading.Thread(target=_run, daemon=True)
    with _active_lock:
        _active[username] = t
    t.start()

# ============================================================================
# MAIN LOOP
# ============================================================================

_last_harvest = 0.0


def watch_loop(usernames: list[str]):
    global _last_harvest

    log("=" * 60)
    log("Chaturdown Watcher")
    for u in usernames:
        log(f"  {u}")
    log(f"  Poll: {POLL_MIN}–{POLL_MAX}s")
    log("=" * 60)

    # Initial cookie harvest
    harvest_cookies()
    _last_harvest = time.time()

    attempt = 0

    while True:
        attempt += 1
        log(f"\nCheck #{attempt}")

        # Refresh cookies if they've gone stale
        if time.time() - _last_harvest > COOKIE_MAX_AGE:
            success = harvest_cookies()
            if success:
                _last_harvest = time.time()
            else:
                log("   [!] Cookie harvest failed. Retrying in 5 minutes...")
                _last_harvest = time.time() - COOKIE_MAX_AGE + 300

        live_users = check_all_users(usernames)

        for u in usernames:
            is_live   = u in live_users
            is_dl     = _is_active(u)
            status    = "LIVE" if is_live else "offline"
            dl_status = " [downloading]" if is_dl else ""
            log(f"   {u}: {status}{dl_status}")

            if is_live and not is_dl:
                log(f"   → Launching download for {u}")
                _launch(u)

        if _STOP.is_set():
            log("Verification block detected — exiting.")
            sys.exit(1)
        snooze = random.randint(POLL_MIN, POLL_MAX)
        next_t = time.strftime("%H:%M:%S", time.localtime(time.time() + snooze))
        log(f"   Next check in {snooze}s (~{next_t})")
        time.sleep(snooze)


def main():
    print()
    print("Chaturdown — Multi-User Chaturbate Downloader")
    print("-" * 50)

    usernames = [u for u in CB_USERNAMES if u]
    if not usernames:
        raw = input("Chaturbate username(s), comma-separated: ").strip()
        if not raw:
            print("No usernames provided. Exiting.")
            sys.exit(1)
        usernames = [u.strip().lower() for u in raw.split(",") if u.strip()]

    print()
    watch_loop(usernames)


if __name__ == "__main__":
    main()
