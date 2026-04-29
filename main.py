import os
import subprocess
import requests
import random
import google.generativeai as genai
from groq import Groq
from pathlib import Path

# ─── CONFIG ────────────────────────────────────────────────────────────────────
GROQ_API_KEY       = os.environ["GROQ_API_KEY"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
MAX_VIDEOS         = int(os.environ.get("MAX_VIDEOS", "3"))

# ─── INIT ──────────────────────────────────────────────────────────────────────
groq_client = Groq(api_key=GROQ_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)
gemini      = genai.GenerativeModel("gemini-1.5-flash")

WORK_DIR  = Path("workdir")
WORK_DIR.mkdir(exist_ok=True)
DONE_FILE = Path("processed_ids.txt")

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def load_processed():
    if not DONE_FILE.exists():
        return set()
    return set(DONE_FILE.read_text().strip().splitlines())

def save_processed(bvid):
    with open(DONE_FILE, "a") as f:
        f.write(bvid + "\n")

def notify(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Notify failed: {e}")

def to_srt_time(s):
    h   = int(s // 3600)
    m   = int((s % 3600) // 60)
    sec = int(s % 60)
    ms  = int((s - int(s)) * 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"

# ─── STEP 1: FETCH TRENDING ────────────────────────────────────────────────────
def fetch_trending(count=20):
    print("Fetching trending Bilibili videos...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
        "Referer":    "https://www.bilibili.com/",
    }
    try:
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/popular",
            params={"ps": count, "pn": 1},
            headers=headers,
            timeout=15
        )
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"API code {data.get('code')}")

        videos = []
        for item in data["data"]["list"]:
            videos.append({
                "bvid":  item["bvid"],
                "title": item["title"],
                "views": item["stat"]["view"],
                "url":   f"https://www.bilibili.com/video/{item['bvid']}"
            })
        print(f"Got {len(videos)} trending videos")
        return videos

    except Exception as e:
        print(f"Bilibili API failed: {e} — trying yt-dlp fallback...")
        return fetch_trending_fallback()

def fetch_trending_fallback():
    result = subprocess.run([
        "yt-dlp", "--flat-playlist",
        "--print", "%(id)s\t%(title)s",
        "--playlist-end", "10",
        "https://www.bilibili.com/v/popular/rank/all"
    ], capture_output=True, text=True)

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            bvid, title = parts
            videos.append({
                "bvid":  bvid,
                "title": title,
                "views": 0,
                "url":   f"https://www.bilibili.com/video/{bvid}"
            })
    print(f"Fallback got {len(videos)} videos")
    return videos

# ─── STEP 2: PICK NEW VIDEOS ───────────────────────────────────────────────────
def pick_new(trending, already_done, max_count):
    fresh = [v for v in trending if v["bvid"] not in already_done]
    random.shuffle(fresh)
    picked = fresh[:max_count]
    print(f"Picked {len(picked)} new video(s)")
    return picked

# ─── STEP 3: DOWNLOAD ──────────────────────────────────────────────────────────
def download_video(url, index):
    print(f"Downloading: {url}")
    out = str(WORK_DIR / f"video_{index}.%(ext)s")
    result = subprocess.run([
        "yt-dlp", "--no-playlist",
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--max-filesize", "150m",
        "-o", out, url
    ], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Download failed:\n{result.stderr[-400:]}")
        return None

    for f in WORK_DIR.glob(f"video_{index}.*"):
        if f.suffix == ".mp4":
            print(f"Downloaded ({f.stat().st_size/1024/1024:.1f} MB)")
            return f
    return None

# ─── STEP 4: EXTRACT AUDIO ─────────────────────────────────────────────────────
def extract_audio(video_path, index):
    audio_path = WORK_DIR / f"audio_{index}.mp3"
    print("Extracting audio...")
    r = subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        str(audio_path)
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print("Audio extraction failed")
        return None
    print("Audio extracted")
    return audio_path

# ─── STEP 5: TRANSCRIBE ────────────────────────────────────────────────────────
def transcribe(audio_path):
    print("Transcribing with Groq Whisper...")
    with open(audio_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            file=f,
            model="whisper-large-v3",
            language="zh",
            response_format="verbose_json",
            timestamp_granularities=["segment"]
        )
    segs = result.segments
    print(f"Transcribed {len(segs)} segment(s)")
    return segs

# ─── STEP 6: TRANSLATE TO HINGLISH ─────────────────────────────────────────────
def translate(segments, title=""):
    print("Translating to Hinglish with Gemini...")
    lines = [f"{i+1}. {s['text'].strip()}" for i, s in enumerate(segments)]

    prompt = f"""You are a funny Indian content creator dubbing Chinese videos for Instagram Reels and YouTube Shorts.

Video title: {title}

Translate each numbered line from Chinese to Hinglish (Hindi + English mixed, written in English script).

Rules:
- Sound like a desi guy casually reacting and commentating
- Naturally use: bhai, arre yaar, bro, kya kar raha hai, matlab, accha, seedha, ekdum, bas kar, dekh, sun, sach mein
- Add humor where it fits naturally, do not force it
- Keep the actual meaning intact
- Return ONLY the numbered lines, no extra text or explanation

Chinese transcript:
{chr(10).join(lines)}"""

    response = gemini.generate_content(prompt)
    translated_lines = response.text.strip().split("\n")

    result = []
    for i, seg in enumerate(segments):
        text = seg["text"]
        for line in translated_lines:
            line = line.strip()
            if line.startswith(f"{i+1}."):
                text = line.split(".", 1)[1].strip()
                break
        result.append({"start": seg["start"], "end": seg["end"], "text": text})

    print("Translation done!")
    return result

# ─── STEP 7: BUILD SRT ─────────────────────────────────────────────────────────
def build_srt(segments, index):
    srt_path = WORK_DIR / f"subs_{index}.srt"
    lines = []
    for i, seg in enumerate(segments):
        lines += [
            str(i + 1),
            f"{to_srt_time(seg['start'])} --> {to_srt_time(seg['end'])}",
            seg["text"],
            ""
        ]
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    print("SRT created")
    return srt_path

# ─── STEP 8: BURN SUBTITLES ────────────────────────────────────────────────────
def burn_subtitles(video_path, srt_path, index):
    output_path = WORK_DIR / f"final_{index}.mp4"
    print("Burning fancy subtitles...")

    sub_filter = (
        f"subtitles={srt_path}:force_style='"
        "FontName=Liberation Sans,"
        "FontSize=20,"
        "PrimaryColour=&H00FFFF00,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "Bold=1,"
        "Outline=2,"
        "Shadow=1,"
        "MarginV=35,"
        "Alignment=2'"
    )

    r = subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", sub_filter,
        "-c:a", "copy",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        str(output_path)
    ], capture_output=True, text=True)

    if r.returncode != 0:
        print(f"Subtitle burn failed:\n{r.stderr[-300:]}")
        return None

    print("Final video ready!")
    return output_path

# ─── STEP 9: SEND TO TELEGRAM ──────────────────────────────────────────────────
def send_video(video_path, title, url):
    print("Sending to Telegram...")
    size_mb = os.path.getsize(video_path) / 1024 / 1024
    print(f"Size: {size_mb:.1f} MB")

    if size_mb > 50:
        print("Compressing for Telegram 50MB limit...")
        compressed = str(video_path).replace(".mp4", "_small.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", "scale=720:-2",
            "-c:v", "libx264", "-crf", "28", "-preset", "fast",
            "-c:a", "aac", "-b:a", "96k",
            compressed
        ], capture_output=True)
        video_path = compressed

    caption = (
        f"🎬 <b>New Video Ready!</b>\n\n"
        f"📺 {title[:100]}\n\n"
        f"✅ Hinglish subtitles burned in\n"
        f"🔗 {url}\n"
        f"📱 Save and post anywhere!"
    )

    with open(video_path, "rb") as f:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"video": f},
            timeout=180
        )

    if resp.status_code == 200:
        print("Sent to Telegram!")
    else:
        print(f"Telegram error: {resp.text[:300]}")

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    notify("🤖 <b>Pipeline started!</b>\nFetching trending Chinese videos...")

    already_done = load_processed()
    trending     = fetch_trending(count=20)

    if not trending:
        notify("❌ Could not fetch any videos. Check GitHub Actions logs.")
        return

    to_process = pick_new(trending, already_done, MAX_VIDEOS)

    if not to_process:
        notify("ℹ️ No new videos today — all trending already processed!")
        return

    notify(f"🎯 Processing <b>{len(to_process)}</b> video(s)... sit back bhai! ☕")

    success = 0
    for i, vid in enumerate(to_process):
        print(f"\n{'='*55}")
        print(f"[{i+1}/{len(to_process)}] {vid['title']}")
        print(f"{'='*55}")

        try:
            video_path = download_video(vid["url"], i)
            if not video_path:
                notify(f"⚠️ Video {i+1} download failed, skipping.")
                continue

            audio_path = extract_audio(video_path, i)
            if not audio_path:
                continue

            segments = transcribe(audio_path)
            if not segments:
                notify(f"⚠️ Video {i+1} transcription empty, skipping.")
                continue

            translated = translate(segments, vid["title"])
            srt_path   = build_srt(translated, i)
            final      = burn_subtitles(video_path, srt_path, i)

            if not final:
                continue

            send_video(final, vid["title"], vid["url"])
            save_processed(vid["bvid"])
            success += 1

        except Exception as e:
            print(f"Error on video {i+1}: {e}")
            notify(f"❌ Error on video {i+1}: {str(e)[:200]}")
            continue

    notify(
        f"✅ <b>Pipeline done!</b>\n"
        f"📊 {success}/{len(to_process)} videos processed\n"
        f"🎉 Check above for your videos, bhai!"
    )
    print("\nAll done!")

if __name__ == "__main__":
    main()

