import os
import json
import requests
import time
from pathlib import Path

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_FILE_ID   = os.environ["TELEGRAM_FILE_ID"]
INSTAGRAM_USERNAME = os.environ["INSTAGRAM_USERNAME"]
INSTAGRAM_PASSWORD = os.environ["INSTAGRAM_PASSWORD"]
INSTAGRAM_SESSION  = os.environ.get("INSTAGRAM_SESSION", "")   # preferred
INSTA_CAPTION      = os.environ.get("INSTA_CAPTION", "#Shorts #Viral #Chinese")

WORK_DIR = Path("workdir")
WORK_DIR.mkdir(exist_ok=True)


def notify(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"Notify failed: {e}")


def download_from_telegram(file_id: str) -> Path:
    print("Getting Telegram file path...")
    r = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=15,
    )
    r.raise_for_status()
    file_path    = r.json()["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

    print("Downloading video from Telegram...")
    video_path = WORK_DIR / "insta_input.mp4"
    with requests.get(download_url, stream=True, timeout=120) as dl:
        dl.raise_for_status()
        with open(video_path, "wb") as f:
            for chunk in dl.iter_content(chunk_size=8192):
                f.write(chunk)

    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"Downloaded ({size_mb:.1f} MB)")
    return video_path


def login_instagram():
    from instagrapi import Client

    cl = Client()
    cl.delay_range = [2, 5]

    if INSTAGRAM_SESSION:
        print("Using saved session (no fresh login needed)...")
        cl.set_settings(json.loads(INSTAGRAM_SESSION))
        # Reuse session — login() will validate without a new IP-based auth
        cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
    else:
        print(f"No session found — fresh login as {INSTAGRAM_USERNAME}...")
        print("WARNING: This may be blocked if the server IP is blacklisted by Instagram.")
        cl.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)

    print("Logged in!")
    return cl


def upload_reel(cl, video_path: Path, caption: str) -> str:
    print("Uploading Reel...")
    time.sleep(3)
    media     = cl.clip_upload(path=video_path, caption=caption)
    url       = f"https://www.instagram.com/reel/{media.code}/"
    print(f"Uploaded! {url}")
    return url


def main():
    try:
        notify("📥 <b>Downloading video for Instagram...</b>")
        video_path = download_from_telegram(TELEGRAM_FILE_ID)

        notify(
            f"📸 <b>Uploading to Instagram Reels...</b>\n"
            f"@{INSTAGRAM_USERNAME}\n\n"
            "This takes 1-2 minutes..."
        )

        cl  = login_instagram()
        url = upload_reel(cl, video_path, INSTA_CAPTION)

        notify(
            f"🎉 <b>Posted to Instagram!</b>\n\n"
            f"👤 @{INSTAGRAM_USERNAME}\n"
            f"🔗 {url}\n\n"
            f"📝 <i>{INSTA_CAPTION[:100]}</i>"
        )

    except Exception as e:
        print(f"Instagram upload failed: {e}")
        notify(f"❌ Instagram upload failed:\n{str(e)[:300]}")


if __name__ == "__main__":
    main()
