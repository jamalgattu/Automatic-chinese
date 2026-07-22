import os
import requests
import time
from pathlib import Path

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]
TELEGRAM_FILE_ID    = os.environ["TELEGRAM_FILE_ID"]
FB_PAGE_TOKEN       = os.environ["FB_PAGE_TOKEN"]
FB_PAGE_ID          = os.environ["FB_PAGE_ID"]
FB_CAPTION          = os.environ.get("FB_CAPTION", "#Shorts #Viral #Chinese")

WORK_DIR = Path("workdir")
WORK_DIR.mkdir(exist_ok=True)

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def notify(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"Notify failed: {e}")

# ─── STEP 1: DOWNLOAD FROM TELEGRAM ───────────────────────────────────────────
def download_from_telegram(file_id: str) -> Path:
    print("Getting file path from Telegram...")
    r = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=15,
    )
    r.raise_for_status()
    file_path    = r.json()["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"

    print("Downloading video...")
    video_path = WORK_DIR / "fb_input.mp4"
    with requests.get(download_url, stream=True, timeout=120) as dl:
        dl.raise_for_status()
        with open(video_path, "wb") as f:
            for chunk in dl.iter_content(chunk_size=8192):
                f.write(chunk)

    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"Downloaded ({size_mb:.1f} MB)")
    return video_path

# ─── STEP 2: UPLOAD TO FACEBOOK PAGE ──────────────────────────────────────────
def upload_to_facebook(video_path: Path, caption: str) -> str:
    """
    Uses Facebook Graph API to upload a Reel to a Facebook Page.
    Step 1 — Initialize upload session
    Step 2 — Upload the video file
    Step 3 — Publish the reel
    """
    base_url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}"

    # ── Step 1: Initialize upload session ──────────────────────────────────────
    print("Initializing Facebook upload session...")
    file_size = video_path.stat().st_size

    init_resp = requests.post(
        f"{base_url}/video_reels",
        data={
            "upload_phase": "start",
            "access_token": FB_PAGE_TOKEN,
        },
        timeout=30,
    )
    init_data = init_resp.json()
    print(f"Init response: {init_data}")

    if "error" in init_data:
        raise Exception(f"Init failed: {init_data['error']['message']}")

    video_id     = init_data["video_id"]
    upload_url   = init_data["upload_url"]

    # ── Step 2: Upload video bytes ─────────────────────────────────────────────
    print(f"Uploading video ({file_size/1024/1024:.1f} MB) to Facebook...")
    with open(video_path, "rb") as f:
        upload_resp = requests.post(
            upload_url,
            headers={
                "Authorization":        f"OAuth {FB_PAGE_TOKEN}",
                "offset":               "0",
                "file_size":            str(file_size),
                "Content-Type":         "application/octet-stream",
            },
            data=f,
            timeout=300,
        )
    upload_data = upload_resp.json()
    print(f"Upload response: {upload_data}")

    if not upload_data.get("success"):
        raise Exception(f"Upload failed: {upload_data}")

    # ── Step 3: Wait for processing then publish ───────────────────────────────
    print("Waiting for Facebook to process video...")
    time.sleep(10)

    publish_resp = requests.post(
        f"{base_url}/video_reels",
        data={
            "upload_phase":  "finish",
            "access_token":  FB_PAGE_TOKEN,
            "video_id":      video_id,
            "video_state":   "PUBLISHED",
            "description":   caption,
        },
        timeout=60,
    )
    publish_data = publish_resp.json()
    print(f"Publish response: {publish_data}")

    if "error" in publish_data:
        raise Exception(f"Publish failed: {publish_data['error']['message']}")

    # Return public URL
    post_url = f"https://www.facebook.com/reel/{video_id}"
    return post_url

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    try:
        notify("📥 <b>Downloading video for Facebook...</b>")
        video_path = download_from_telegram(TELEGRAM_FILE_ID)

        notify(
            "📘 <b>Uploading to Facebook Reels...</b>\n\n"
            "This takes 1-2 minutes... ⏳"
        )

        post_url = upload_to_facebook(video_path, FB_CAPTION)

        notify(
            f"🎉 <b>Posted to Facebook!</b>\n\n"
            f"🔗 {post_url}\n\n"
            f"📝 <i>{FB_CAPTION[:100]}</i>"
        )

    except Exception as e:
        print(f"Facebook upload failed: {e}")
        notify(f"❌ Facebook upload failed:\n{str(e)[:300]}")

if __name__ == "__main__":
    main()

