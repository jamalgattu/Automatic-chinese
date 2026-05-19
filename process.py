import os
import subprocess
import requests
import json
from pathlib import Path

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
VIDEO_URL          = os.environ["VIDEO_URL"]

WORK_DIR = Path("workdir")
WORK_DIR.mkdir(exist_ok=True)

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def notify(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Notify failed: {e}")

# ─── STEP 1: DOWNLOAD VIDEO ────────────────────────────────────────────────────
def download_video():
    print(f"Downloading: {VIDEO_URL}")
    output_path = WORK_DIR / "input.mp4"

    r = requests.get(
        VIDEO_URL,
        stream=True,
        timeout=120,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    if r.status_code != 200:
        raise Exception(f"Download failed: HTTP {r.status_code}")

    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"Downloaded ({size_mb:.1f} MB)")

    if size_mb < 0.1:
        raise Exception("Downloaded file too small — invalid video!")

    return output_path

# ─── STEP 2: CONVERT TO 9:16 BLUR BACKGROUND ──────────────────────────────────
def convert_to_reels(video_path):
    output_path = WORK_DIR / "final.mp4"
    print("Converting to 9:16 blur background...")

    vf_filter = (
        # Blurred background
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:5[bg];"
        # Original video centered
        "[0:v]scale=1080:-2[fg];"
        # Overlay
        "[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )

    r = subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-t", "59",
        str(output_path)
    ], capture_output=True, text=True)

    if r.returncode != 0:
        raise Exception(f"Conversion failed: {r.stderr[-300:]}")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"Converted! ({size_mb:.1f} MB)")
    return output_path

# ─── STEP 3: SEND TO TELEGRAM WITH BUTTONS ────────────────────────────────────
def send_to_telegram(video_path):
    print("Sending to Telegram...")
    size_mb = os.path.getsize(video_path) / 1024 / 1024

    # Compress if over 50MB Telegram limit
    if size_mb > 50:
        print(f"Compressing ({size_mb:.1f}MB → under 50MB)...")
        compressed = WORK_DIR / "final_small.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", "scale=720:-2",
            "-c:v", "libx264", "-crf", "28", "-preset", "fast",
            "-c:a", "aac", "-b:a", "96k",
            str(compressed)
        ], capture_output=True)
        video_path = compressed

    caption = (
        "🎬 <b>Your Short is Ready!</b>\n\n"
        "📐 9:16 portrait format\n"
        "⏱ Under 60 seconds\n\n"
        "Where do you want to post it?"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "▶️ YouTube Shorts", "callback_data": "post_youtube"},
            {"text": "📸 Instagram Reels", "callback_data": "post_instagram"},
        ], [
            {"text": "📱 Just send me", "callback_data": "just_send"},
        ]]
    }

    with open(video_path, "rb") as f:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": caption,
                "parse_mode": "HTML",
                "reply_markup": json.dumps(keyboard)
            },
            files={"video": f},
            timeout=180
        )

    if resp.status_code == 200:
        print("Sent to Telegram!")
    else:
        raise Exception(f"Telegram error: {resp.text[:300]}")

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    notify("⚙️ <b>Processing your video...</b>\nConverting to Reels format... ⏳")

    try:
        video_path = download_video()
        final      = convert_to_reels(video_path)
        send_to_telegram(final)

    except Exception as e:
        print(f"Pipeline error: {e}")
        notify(f"❌ Processing failed: {str(e)[:200]}")

if __name__ == "__main__":
    main()

