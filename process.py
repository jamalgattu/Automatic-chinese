import os
import subprocess
import requests
import json
import yt_dlp
from pathlib import Path

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
SHARE_URL          = os.environ["SHARE_URL"]

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

# ─── STEP 1: EXTRACT DIRECT VIDEO URL ─────────────────────────────────────────
def extract_video_url(share_url: str):
    print(f"Extracting URL from: {share_url}")

    mobile_ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.0 Mobile/15E148 Safari/604.1"
    )

    # Expand short URL first
    try:
        r = requests.get(
            share_url,
            headers={"User-Agent": mobile_ua},
            allow_redirects=True,
            timeout=15
        )
        expanded_url = r.url
        print(f"Expanded URL: {expanded_url}")
    except Exception as e:
        print(f"URL expansion failed, using original: {e}")
        expanded_url = share_url

    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "extract_flat": False,
        "http_headers": {"User-Agent": mobile_ua},
    }

    urls_to_try = list(dict.fromkeys([expanded_url, share_url]))

    for url in urls_to_try:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "Chinese Video")
                video_url = info.get("url")

                if not video_url:
                    for fmt in reversed(info.get("formats", [])):
                        if fmt.get("url"):
                            video_url = fmt["url"]
                            break

                if video_url:
                    print(f"Extracted URL successfully. Title: {title}")
                    return video_url, title

        except Exception as e:
            print(f"yt-dlp failed for {url}: {e}")

    raise Exception(
        "Could not extract video URL.\n"
        "Possible reasons: video is private, region-locked, or the link is invalid."
    )

# ─── STEP 2: DOWNLOAD VIDEO ────────────────────────────────────────────────────
def download_video(video_url: str):
    print(f"Downloading: {video_url}")
    output_path = WORK_DIR / "input.mp4"

    r = requests.get(
        video_url,
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

# ─── STEP 3: CONVERT TO 9:16 BLUR BACKGROUND ──────────────────────────────────
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

# ─── STEP 4: SEND TO TELEGRAM WITH BUTTONS ────────────────────────────────────
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
    notify("⚙️ <b>Processing your video...</b>\nExtracting and converting to Reels format... ⏳")

    try:
        video_url, title = extract_video_url(SHARE_URL)
        notify(f"⬇️ Downloading: <b>{title[:70]}</b>")
        video_path = download_video(video_url)
        final      = convert_to_reels(video_path)
        send_to_telegram(final)

    except Exception as e:
        print(f"Pipeline error: {e}")
        notify(f"❌ Processing failed:\n{str(e)[:200]}")

if __name__ == "__main__":
    main()
