#!/usr/bin/env python3
"""
native_fetch.py -- standalone segment fetcher for a single Chaturbate
model, replacing ffmpeg's own HLS fetching with a purpose-built one.

WHY: confirmed live (see NAS_ISSUE.md) that ffmpeg's HLS demuxer never
uses the CDN's LL-HLS blocking-reload delivery directive (_HLS_msn),
despite Chaturbate's edges explicitly advertising
CAN-BLOCK-RELOAD=YES support for it -- a request for a segment that
doesn't exist yet is held open by the server and answered the instant
it's ready (~1.5s hold observed, matching real segment cadence exactly),
instead of the client having to guess a poll interval and either waste
requests polling too early or add latency polling too late. ffmpeg's own
debug log shows zero _HLS_msn requests ever -- confirmed directly, not
assumed. This is believed to be a real, previously-undocumented
contributor to the "falls behind the live window, skips segments ahead"
pace-lag problem, on top of the network-variance root cause that no
client-side fix can fully remove.

Also fetches full segments only (never LL-HLS parts) -- matches
ffmpeg's own granularity exactly (its demuxer explicitly logs
"Skip" on every #EXT-X-PART line), so this targets efficient segment
discovery for recording, not sub-second playback latency.

Each of the video and audio tracks gets exactly ONE persistent
connection (one requests.Session each) -- deliberately NOT concurrent
multi-connection prefetching, which is what caused the streamlink
experiment to lose under real degraded conditions (more connections =
more exposure to a flaky path; see NAS_ISSUE.md). Every segment fetch
is verified against its Content-Length header and retried on a
mismatch/incomplete body -- the specific gap identified and verified in
keepalive_recycle_test.py: a segment that opens fine but dies mid-
transfer is never retried today by ffmpeg or by -seg_max_retry.

Bytes are written to two named pipes; ffmpeg reads both as its two -i
inputs and does ONLY muxing/output, with the exact same locked,
audio-drift-tuned flags Chaturdown already ships
(_OUTPUT_FFMPEG_ARGS below -- kept in manual sync with Chaturdown.py's
own "ffmpeg:" downloader-args string, same convention already used for
Testing/Chaturdown.py). This script never touches that stage.

Usage (drop-in replacement for the yt-dlp subprocess Chaturdown
launches -- same argv contract, same stdout-heartbeat-for-watchdog
behavior, same SIGINT-then-30s-then-SIGKILL termination Chaturdown
already uses via _terminate_process):
    native_fetch.py <username> <output_path> [--cookies FILE] [--user-agent UA]
"""
import argparse
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

import requests

CHATVIDEOCONTEXT_URL = "https://chaturbate.com/get_edge_hls_url_ajax/"
SEGMENT_MAX_RETRIES = 5
SEGMENT_RETRY_DELAY = 0.5
REQUEST_TIMEOUT = 15
BLOCKING_RELOAD_TIMEOUT = 20  # segments land every ~1.6-2s; well above that
NO_PROGRESS_TIMEOUT = 60  # neither track landing a segment this long -> stalled, exit and let Chaturdown relaunch
PLAYLIST_RESYNC_AFTER_FAILURES = 5  # consecutive playlist-reload failures before re-resolving a fresh chunklist URL

# Locked output-side flags -- MUST stay in sync with Chaturdown.py's
# "ffmpeg:" downloader-args string. Never touched by this script's own
# fetch logic; only used verbatim to build the ffmpeg command below.
_OUTPUT_FFMPEG_ARGS = [
    "-fps_mode", "cfr",
    "-af", "aresample=async=1",
    "-c:v", "copy",
    "-c:a", "aac",
    "-copyts",
    "-avoid_negative_ts", "make_zero",
]

_stop = threading.Event()


def log(msg: str):
    print(msg, flush=True)


def resolve_hls_url(username: str, cookies_file, user_agent, proxies=None) -> tuple[str | None, str]:
    headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
    if user_agent:
        headers["User-Agent"] = user_agent
    cookies = None
    if cookies_file:
        jar = requests.cookies.RequestsCookieJar()
        with open(cookies_file) as f:
            cookie_lines = f.read().splitlines()
        for line in cookie_lines:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                domain, _flag, path, _secure, _exp, name, value = parts[:7]
                jar.set(name, value, domain=domain.lstrip("."), path=path)
        cookies = jar
    r = requests.post(CHATVIDEOCONTEXT_URL, data={"room_slug": username},
                       headers=headers, cookies=cookies, proxies=proxies, timeout=REQUEST_TIMEOUT)
    data = r.json()
    return data.get("url") or None, data.get("room_status", "")


def pick_best_variant(master_text: str, master_url: str) -> tuple[str, str]:
    """Parse the master playlist, pick the highest-BANDWIDTH video
    variant, resolve its AUDIO group to the matching chunklist URI.
    Returns (video_chunklist_url, audio_chunklist_url)."""
    audio_groups: dict[str, str] = {}
    for line in master_text.splitlines():
        if line.startswith("#EXT-X-MEDIA:") and "TYPE=AUDIO" in line:
            gid = re.search(r'GROUP-ID="([^"]+)"', line)
            uri = re.search(r'URI="([^"]+)"', line)
            if gid and uri:
                audio_groups[gid.group(1)] = urllib.parse.urljoin(master_url, uri.group(1))

    best = None  # (bandwidth, audio_group, video_uri)
    lines = master_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:"):
            bw = re.search(r"BANDWIDTH=(\d+)", line)
            ag = re.search(r'AUDIO="([^"]+)"', line)
            if i + 1 < len(lines) and bw:
                video_uri = lines[i + 1].strip()
                bandwidth = int(bw.group(1))
                if best is None or bandwidth > best[0]:
                    best = (bandwidth, ag.group(1) if ag else None, video_uri)

    if not best:
        raise RuntimeError("no #EXT-X-STREAM-INF entries found in master playlist")
    _, audio_group, video_uri = best
    video_url = urllib.parse.urljoin(master_url, video_uri)
    audio_url = audio_groups.get(audio_group)
    if not audio_url:
        raise RuntimeError(f"no matching AUDIO group '{audio_group}' found")
    return video_url, audio_url


class TrackFetcher:
    """Fetches one track (video or audio): resolves the init segment
    once, then uses LL-HLS blocking reload to discover new segments the
    instant they're ready, fetching each with Content-Length
    verification + retry, writing raw bytes to a pipe in order."""

    def __init__(self, name: str, chunklist_url: str, pipe_path: str, proxies=None,
                 role: str | None = None, username: str | None = None, cookies_file=None, user_agent=None):
        self.name = name
        self.chunklist_url = chunklist_url
        self.pipe_path = pipe_path
        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        self.proxies = proxies
        # role/username/cookies/user_agent are only needed to re-resolve a
        # fresh chunklist URL when the current one's signed token expires
        # mid-recording (see _resync_chunklist_url).
        self.role = role
        self.username = username
        self.cookies_file = cookies_file
        self.user_agent = user_agent
        self.segments_written = 0
        self.bytes_written = 0
        self.retries_used = 0
        self.failed_segments = 0
        self._pipe_fh = None

    def _fetch_with_retry(self, url: str) -> bytes | None:
        last_err = None
        for attempt in range(SEGMENT_MAX_RETRIES):
            if _stop.is_set():
                return None
            try:
                r = self.session.get(url, timeout=REQUEST_TIMEOUT)
                if r.status_code in (404, 410):
                    # Permanently gone (already evicted from the CDN's
                    # live window) -- retrying wastes time and falls
                    # further behind, unlike a transient error.
                    log(f"[{self.name}] segment gone (HTTP {r.status_code}), not retrying: {url}")
                    self.failed_segments += 1
                    return None
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(SEGMENT_RETRY_DELAY)
                    continue
                body = r.content
                expected = r.headers.get("Content-Length")
                if expected is not None and len(body) != int(expected):
                    last_err = f"incomplete body: got {len(body)}, expected {expected}"
                    self.retries_used += 1
                    time.sleep(SEGMENT_RETRY_DELAY)
                    continue
                return body
            except requests.exceptions.RequestException as e:
                last_err = str(e)
                self.retries_used += 1
                time.sleep(SEGMENT_RETRY_DELAY)
        log(f"[{self.name}] segment failed after {SEGMENT_MAX_RETRIES} attempts: {url} ({last_err})")
        self.failed_segments += 1
        return None

    def _resync_chunklist_url(self) -> bool:
        """Re-resolves this track's chunklist URL from scratch (fresh
        chatvideocontext call -> master playlist -> pick_best_variant).
        Chaturbate's chunklist URLs carry a signed token that expires
        mid-recording -- confirmed via a real NAS test where playlist
        reload started returning HTTP 403 forever on the original URL
        while segment fetches themselves stayed perfect (0 failures).
        Without this, the only recovery was NO_PROGRESS_TIMEOUT killing
        the whole recording and Chaturdown relaunching from scratch.
        Returns True and updates self.chunklist_url on success."""
        if not self.username or not self.role:
            return False
        try:
            hls_url, room_status = resolve_hls_url(self.username, self.cookies_file, self.user_agent, self.proxies)
            if not hls_url:
                log(f"[{self.name}] resync: room not public (status={room_status})")
                return False
            r = requests.get(hls_url, proxies=self.proxies, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            video_url, audio_url = pick_best_variant(r.text, hls_url)
            new_url = video_url if self.role == "video" else audio_url
        except (requests.exceptions.RequestException, RuntimeError) as e:
            log(f"[{self.name}] resync failed: {e}")
            return False
        self.chunklist_url = new_url
        log(f"[{self.name}] resync: got fresh chunklist URL")
        return True

    def _write(self, data: bytes) -> bool:
        """Returns False if the pipe is gone (ffmpeg exited/closed its
        read end) -- caller should stop, not treat it as a fetch error."""
        if self._pipe_fh is None:
            # Opening for write blocks until ffmpeg opens its end for
            # read -- ffmpeg must already be spawned (non-blocking
            # Popen) before this is called.
            self._pipe_fh = open(self.pipe_path, "wb")
        try:
            self._pipe_fh.write(data)
            self._pipe_fh.flush()
        except (BrokenPipeError, OSError):
            _stop.set()
            return False
        self.bytes_written += len(data)
        return True

    def run(self):
        try:
            r = self.session.get(self.chunklist_url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            text = r.text
            base = self.chunklist_url

            map_m = re.search(r'#EXT-X-MAP:URI="([^"]+)"', text)
            if map_m:
                init_url = urllib.parse.urljoin(base, map_m.group(1))
                init_data = self._fetch_with_retry(init_url)
                if init_data is None:
                    log(f"[{self.name}] fatal: could not fetch init segment")
                    return
                if not self._write(init_data):
                    return

            seg_m = re.search(r'-MEDIA-SEQUENCE:(\d+)', text)
            if not seg_m:
                log(f"[{self.name}] fatal: no #EXT-X-MEDIA-SEQUENCE in playlist")
                return
            next_msn = int(seg_m.group(1))

            # process whatever's already in the initial window first
            seg_urls = re.findall(r'^(?!#)(\S+\.m4s\S*)$', text, re.MULTILINE)
            seg_urls = [u for u in seg_urls if "/seg_" in u or "seg_" in u]
            for rel in seg_urls:
                if _stop.is_set():
                    return
                data = self._fetch_with_retry(urllib.parse.urljoin(base, rel))
                if data is not None:
                    if not self._write(data):
                        return
                    self.segments_written += 1
                next_msn += 1

            consecutive_playlist_failures = 0
            while not _stop.is_set():
                sep = "&" if "?" in self.chunklist_url else "?"
                blocking_url = f"{self.chunklist_url}{sep}_HLS_msn={next_msn}"
                try:
                    r = self.session.get(blocking_url, timeout=BLOCKING_RELOAD_TIMEOUT)
                except requests.exceptions.RequestException as e:
                    log(f"[{self.name}] playlist reload failed: {e}; retrying")
                    consecutive_playlist_failures += 1
                    if consecutive_playlist_failures >= PLAYLIST_RESYNC_AFTER_FAILURES:
                        self._resync_chunklist_url()
                        consecutive_playlist_failures = 0
                    time.sleep(1)
                    continue
                if r.status_code != 200:
                    log(f"[{self.name}] playlist reload HTTP {r.status_code}; retrying")
                    consecutive_playlist_failures += 1
                    if consecutive_playlist_failures >= PLAYLIST_RESYNC_AFTER_FAILURES:
                        # Most likely cause: this chunklist URL's signed
                        # token expired mid-recording -- retrying the same
                        # URL will never succeed, so get a fresh one.
                        self._resync_chunklist_url()
                        consecutive_playlist_failures = 0
                    time.sleep(1)
                    continue
                consecutive_playlist_failures = 0
                base = self.chunklist_url
                text = r.text
                seg_urls = re.findall(r'^(?!#)(\S+\.m4s\S*)$', text, re.MULTILINE)
                seg_urls = [u for u in seg_urls if "seg_" in u]
                present = []  # (msn, rel_url), in playlist order
                for rel in seg_urls:
                    m = re.search(r'seg_\d+_(\d+)_', rel)
                    if m:
                        present.append((int(m.group(1)), rel))

                if present:
                    min_msn_present = min(msn for msn, _ in present)
                    if next_msn < min_msn_present:
                        # Fallen behind -- everything between next_msn and
                        # min_msn_present has already expired from the
                        # CDN's live window. Jump ahead to the oldest
                        # segment actually still present instead of
                        # wasting retries on every expired one in between
                        # (this is exactly ffmpeg's own "skipping N
                        # segments ahead" recovery, deliberately mirrored
                        # here -- without it, falling behind once means
                        # never catching back up, confirmed the hard way).
                        skipped = min_msn_present - next_msn
                        log(f"[{self.name}] skipping {skipped} segments ahead, "
                            f"expired from playlist (was waiting for {next_msn}, "
                            f"oldest available is now {min_msn_present})")
                        next_msn = min_msn_present

                new_urls = [rel for msn, rel in present if msn >= next_msn]
                for rel in new_urls:
                    if _stop.is_set():
                        return
                    data = self._fetch_with_retry(urllib.parse.urljoin(base, rel))
                    if data is not None:
                        if not self._write(data):
                            return
                        self.segments_written += 1
                    next_msn += 1
        finally:
            if self._pipe_fh is not None:
                try:
                    self._pipe_fh.close()
                except OSError:
                    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("username")
    parser.add_argument("output_path")
    parser.add_argument("--cookies", default=None)
    parser.add_argument("--user-agent", default=None)
    parser.add_argument("--proxy", default=None)
    args = parser.parse_args()

    proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None

    def handle_sigint(signum, frame):
        log("received stop signal, shutting down cleanly...")
        _stop.set()
    signal.signal(signal.SIGINT, handle_sigint)
    if not sys.platform.startswith("win"):
        signal.signal(signal.SIGTERM, handle_sigint)

    hls_url, room_status = resolve_hls_url(args.username, args.cookies, args.user_agent, proxies)
    if not hls_url:
        log(f"room not public (status={room_status})")
        sys.exit(1)

    r = requests.get(hls_url, proxies=proxies, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    video_url, audio_url = pick_best_variant(r.text, hls_url)
    log(f"video: {video_url.split('?')[0]}")
    log(f"audio: {audio_url.split('?')[0]}")

    tmpdir = tempfile.mkdtemp(prefix="native_fetch_")
    video_pipe = os.path.join(tmpdir, "video.pipe")
    audio_pipe = os.path.join(tmpdir, "audio.pipe")
    os.mkfifo(video_pipe)
    os.mkfifo(audio_pipe)

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", video_pipe,
        "-i", audio_pipe,
        *_OUTPUT_FFMPEG_ARGS,
        args.output_path,
    ]
    log(f"launching: {' '.join(ffmpeg_cmd)}")
    ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.DEVNULL)

    video_fetcher = TrackFetcher("video", video_url, video_pipe, proxies,
                                  role="video", username=args.username,
                                  cookies_file=args.cookies, user_agent=args.user_agent)
    audio_fetcher = TrackFetcher("audio", audio_url, audio_pipe, proxies,
                                  role="audio", username=args.username,
                                  cookies_file=args.cookies, user_agent=args.user_agent)
    t1 = threading.Thread(target=video_fetcher.run, daemon=True)
    t2 = threading.Thread(target=audio_fetcher.run, daemon=True)
    t1.start()
    t2.start()

    last_report = time.time()
    last_progress_total = -1
    last_progress_time = time.time()
    exit_code_override = None
    try:
        while t1.is_alive() or t2.is_alive():
            if ffmpeg_proc.poll() is not None:
                log(f"ffmpeg exited early with code {ffmpeg_proc.returncode}")
                _stop.set()
                break

            current_total = video_fetcher.segments_written + audio_fetcher.segments_written
            if current_total != last_progress_total:
                last_progress_total = current_total
                last_progress_time = time.time()
            elif time.time() - last_progress_time > NO_PROGRESS_TIMEOUT:
                # Neither track has landed a new segment in a while --
                # don't keep printing a heartbeat that would mask this
                # from Chaturdown's own external stall watchdog. Exit
                # non-zero so the normal relaunch-on-next-poll path picks
                # this back up (or correctly stops, if the room's really
                # gone), same as a STALL_TIMEOUT trip does today.
                log(f"no new segments on either track for {NO_PROGRESS_TIMEOUT}s -- stalled, stopping")
                _stop.set()
                exit_code_override = 1
                break

            time.sleep(1)
            if time.time() - last_report >= 5:
                log(f"progress: video={video_fetcher.segments_written} segs "
                    f"({video_fetcher.bytes_written / 1024:.0f}KB, {video_fetcher.retries_used} retries), "
                    f"audio={audio_fetcher.segments_written} segs "
                    f"({audio_fetcher.bytes_written / 1024:.0f}KB, {audio_fetcher.retries_used} retries)")
                last_report = time.time()
    except KeyboardInterrupt:
        _stop.set()

    _stop.set()
    t1.join(timeout=10)
    t2.join(timeout=10)

    try:
        ffmpeg_proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        ffmpeg_proc.terminate()
        try:
            ffmpeg_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ffmpeg_proc.kill()

    log(f"final: video={video_fetcher.segments_written} segs written, "
        f"{video_fetcher.failed_segments} failed, {video_fetcher.retries_used} retries; "
        f"audio={audio_fetcher.segments_written} segs written, "
        f"{audio_fetcher.failed_segments} failed, {audio_fetcher.retries_used} retries")

    for p in (video_pipe, audio_pipe):
        try:
            os.unlink(p)
        except OSError:
            pass
    try:
        os.rmdir(tmpdir)
    except OSError:
        pass

    sys.exit(exit_code_override if exit_code_override is not None else (ffmpeg_proc.returncode or 0))


if __name__ == "__main__":
    main()
