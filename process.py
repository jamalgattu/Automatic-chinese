import os
import re
import subprocess
import requests
import json
from pathlib import Path

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
SHARE_URL          = os.environ["SHARE_URL"]

WORK_DIR = Path("workdir")
WORK_DIR.mkdir(exist_ok=True)

SAMSUNG_UA = (
    "Mozilla/5.0 (Linux; Android 11; SAMSUNG SM-G973U) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "SamsungBrowser/14.2 Chrome/87.0.4280.141 Mobile Safari/537.36"
)

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

# ─── STEP 1: GET ttwid COOKIE ─────────────────────────────────────────────────
def get_ttwid():
    resp = requests.post(
        "https://ttwid.bytedance.com/ttwid/union/register/",
        json={
            "region": "cn", "aid": 1768, "needFid": False,
            "service": "www.ixigua.com",
            "migrate_info": {"ticket": "", "source": "node"},
            "cbUrlProtocol": "https", "union": True
        },
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    ttwid = resp.cookies.get("ttwid", "")
    if not ttwid:
        for part in resp.headers.get("Set-Cookie", "").split(";"):
            if "ttwid=" in part:
                ttwid = part.split("ttwid=")[-1].strip()
                break
    if not ttwid:
        raise Exception("Could not obtain ttwid cookie from ByteDance")
    print(f"ttwid obtained: {ttwid[:20]}...")
    return ttwid

# ─── STEP 2: EXTRACT VIDEO URL ────────────────────────────────────────────────
def extract_video_url(share_url: str):
    print(f"Extracting from: {share_url}")

    ttwid = get_ttwid()
    headers = {
        "User-Agent": SAMSUNG_UA,
        "Cookie": f"ttwid={ttwid}",
    }

    r = requests.get(share_url, headers=headers, allow_redirects=True, timeout=20)
    print(f"Page fetched: {len(r.text)} bytes from {r.url[:60]}")

    # Extract video URI from embedded JSON
    m = re.search(r'"video":\{"play_addr":\{"uri":"([a-z0-9]+)"', r.text)
    if not m:
        raise Exception(
            "Could not find video URI in page.\n"
            "The video may be private, deleted, or the link is invalid."
        )

    uri = m.group(1)
    video_url = f"https://www.iesdouyin.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0"
    print(f"Video URI: {uri}")

    # Extract title
    title_match = re.search(r'"desc"\s*:\s*"([^"]+)"', r.text)
    title = title_match.group(1) if title_match else "Chinese Video"

    return video_url, title

# ─── STEP 3: DOWNLOAD VIDEO ────────────────────────────────────────────────────
def download_video(video_url: str):
    print(f"Downloading video...")
    output_path = WORK_DIR / "input.mp4"

    r = requests.get(
        video_url,
        stream=True,
        timeout=120,
        headers={
            "User-Agent": SAMSUNG_UA,
            "Referer": "https://www.iesdouyin.com/",
        }
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

# ─── STEP 4: CONVERT TO 9:16 BLUR BACKGROUND ──────────────────────────────────
def convert_to_reels(video_path):
    output_path = WORK_DIR / "final.mp4"
    print("Converting to 9:16 blur background...")

    vf_filter = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:5[bg];"
        "[0:v]scale=1080:-2[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
    )

    r = subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-filter_complex", vf_filter,
        "-map", "[v]",
        "-map", "0:a?",
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

# ─── STEP 5: SEND TO TELEGRAM ─────────────────────────────────────────────────
def send_to_telegram(video_path, title=""):
    print("Sending to Telegram...")
    size_mb = os.path.getsize(video_path) / 1024 / 1024

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
        {"text": "📘 Post to Facebook", "callback_data": "post_facebook"},
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
    notify("⚙️ <b>Processing your video...</b>\nExtracting video... ⏳")

    try:
        video_url, title = extract_video_url(SHARE_URL)
        notify(f"⬇️ Downloading: <b>{title[:70]}</b>")
        video_path = download_video(video_url)
        final      = convert_to_reels(video_path)
        send_to_telegram(final, title)

    except Exception as e:
        print(f"Pipeline error: {e}")
        notify(f"❌ Processing failed:\n{str(e)[:200]}")

if __name__ == "__main__":
    main()
