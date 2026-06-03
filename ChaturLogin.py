#!/usr/bin/env bash
""":"
exec "$(dirname "$0")/Chaturdown_Venv/bin/python3" "$0" "$@"
":"""
import sqlite3
import shutil
from pathlib import Path
from camoufox.sync_api import Camoufox

BASE_DIR = Path(__file__).resolve().parent

# Folder layout (relative to this script)
PLAYWRIGHT_PROFILE = BASE_DIR / "Chaturdown_Profile"
OUTPUT_TXT = BASE_DIR / "Chaturdown_Cookies.txt"
UA_TXT = BASE_DIR / "user_agent.txt"
DB_PATH = PLAYWRIGHT_PROFILE / "cookies.sqlite"

print(f"Opening Chaturbate with profile: {PLAYWRIGHT_PROFILE}")
print("1. Please log in (or verify you are logged in).")
print("2. Solve any Cloudflare captchas.")
print("3. CLOSE the browser window when finished.\n")

with Camoufox(
    headless=False,
    persistent_context=True,
    user_data_dir=str(PLAYWRIGHT_PROFILE),
) as context:
    page = context.pages[0] if context.pages else context.new_page()
    page.goto("https://chaturbate.com/auth/login", wait_until="domcontentloaded")

    # Capture the browser's User-Agent so Chaturdown can use the same signature
    try:
        current_ua = page.evaluate("navigator.userAgent")
        UA_TXT.write_text(current_ua)
        print(f"Captured Browser Signature: {current_ua[:50]}...")
    except Exception as e:
        print(f"Could not capture User-Agent: {e}")

    print("Browser is open. Waiting for you to close it...")
    try:
        page.wait_for_event("close", timeout=0)
    except Exception:
        pass

print("\nBrowser closed. Extracting cookies directly from database...")

# Export cookies from the browser profile into Netscape format for yt-dlp
if not DB_PATH.exists():
    print(f"❌ Error: Database not found at {DB_PATH}")
else:
    temp_db = BASE_DIR / "temp_cookies.sqlite"
    shutil.copy2(DB_PATH, temp_db)

    try:
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT host, path, isSecure, expiry, name, value FROM moz_cookies WHERE host LIKE '%chaturbate.com%'")

        lines = ["# Netscape HTTP Cookie File\n"]
        saved = 0
        for host, path, secure_int, expiry, name, value in cursor.fetchall():
            flag = "TRUE" if host.startswith(".") else "FALSE"
            secure = "TRUE" if secure_int else "FALSE"
            lines.append(f"{host}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n")
            saved += 1

        OUTPUT_TXT.write_text("".join(lines))
        print(f"✅ Successfully exported {saved} Chaturbate cookies to {OUTPUT_TXT.name}")
        print("You are now ready to run Chaturdown.")

    except Exception as e:
        print(f"❌ Error reading database: {e}")
    finally:
        if 'conn' in locals(): conn.close()
        temp_db.unlink(missing_ok=True)
