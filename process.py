import os
import subprocess
import requests
import json
import uuid
from groq import Groq
from google import genai
from pathlib import Path

# ─── CONFIG ────────────────────────────────────────────────────────────────────
GROQ_API_KEY        = os.environ["GROQ_API_KEY"]
GEMINI_API_KEY      = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]
VIDEO_URL           = os.environ["VIDEO_URL"]
CAPTION             = os.environ.get("CAPTION", "")

# ─── INIT ──────────────────────────────────────────────────────────────────────
groq_client = Groq(api_key=GROQ_API_KEY)
gemini      = genai.Client(api_key=GEMINI_API_KEY)

WORK_DIR = Path("workdir")
WORK_DIR.mkdir(exist_ok=True)

VIDEO_ID = str(uuid.uuid4())[:8]  # unique ID for this video

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

def to_srt_time(s):
    h   = int(s // 3600)
    m   = int((s % 3600) // 60)
    sec = int(s % 60)
    ms  = int((s - int(s)) * 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"

# ─── STEP 1: DOWNLOAD VIDEO ────────────────────────────────────────────────────
def download_video():
    print(f"Downloading video from: {VIDEO_URL}")
    output_path = WORK_DIR / "input.mp4"

    r = requests.get(VIDEO_URL, stream=True, timeout=120)
    if r.status_code != 200:
        raise Exception(f"Download failed: HTTP {r.status_code}")

    with open(output_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"Downloaded ({size_mb:.1f} MB)")
    return output_path

# ─── STEP 2: EXTRACT AUDIO ─────────────────────────────────────────────────────
def extract_audio(video_path):
    audio_path = WORK_DIR / "audio.mp3"
    print("Extracting audio...")
    r = subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        str(audio_path)
    ], capture_output=True, text=True)
    if r.returncode != 0:
        raise Exception(f"Audio extraction failed: {r.stderr[-200:]}")
    print("Audio extracted")
    return audio_path

# ─── STEP 3: TRANSCRIBE ────────────────────────────────────────────────────────
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

# ─── STEP 4: TRANSLATE TO HINGLISH ─────────────────────────────────────────────
def translate(segments):
    print("Translating to Hinglish with Gemini...")
    lines = [f"{i+1}. {s['text'].strip()}" for i, s in enumerate(segments)]

    prompt = f"""You are a funny Indian content creator dubbing Chinese videos for YouTube Shorts.

Translate each numbered line from Chinese to Hinglish (Hindi + English mixed, written in English script).

Rules:
- Sound like a desi guy casually reacting and commentating
- Naturally use: bhai, arre yaar, bro, kya kar raha hai, matlab, accha, seedha, ekdum, bas kar, dekh, sun, sach mein
- Add humor where it fits naturally
- Keep meaning intact
- Max 6 words per line
- Return ONLY numbered lines, no extra text

Chinese transcript:
{chr(10).join(lines)}"""

    response = gemini.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt
    )
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

# ─── STEP 5: BUILD SRT ─────────────────────────────────────────────────────────
def build_srt(segments):
    srt_path = WORK_DIR / "subs.srt"
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

# ─── STEP 6: CONVERT TO REELS + BURN SUBS ─────────────────────────────────────
def convert_to_reels(video_path, srt_path):
    output_path = WORK_DIR / f"final_{VIDEO_ID}.mp4"
    print("Converting to 9:16 blur background Reels...")

    srt_abs = str(srt_path.resolve())
    subtitle_style = (
        "FontName=Liberation Sans,"
        "FontSize=18,"
        "PrimaryColour=&H00FFFF00,"
        "OutlineColour=&H00000000,"
        "BackColour=&H80000000,"
        "Bold=1,"
        "Outline=2,"
        "Shadow=1,"
        "MarginV=60,"
        "Alignment=2"
    )

    vf_filter = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:5[bg];"
        "[0:v]scale=1080:-2[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        f"subtitles={srt_abs}:force_style='{subtitle_style}'"
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
        raise Exception(f"Reels conversion failed: {r.stderr[-300:]}")

    print(f"Reels ready! ({output_path.stat().st_size/1024/1024:.1f} MB)")
    return output_path

# ─── STEP 7: SEND TO TELEGRAM WITH BUTTONS ────────────────────────────────────
def send_to_telegram(video_path):
    print("Sending to Telegram...")
    size_mb = os.path.getsize(video_path) / 1024 / 1024

    if size_mb > 50:
        print("Compressing...")
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
        f"🎬 <b>Your Short is Ready!</b>\n\n"
        f"✅ Hinglish subtitles added\n"
        f"📐 9:16 portrait format\n"
        f"⏱ Under 60 seconds\n\n"
        f"Upload to YouTube Shorts?"
    )

    # Inline keyboard for YouTube upload or skip
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Upload to YouTube", "callback_data": f"upload_yt:{VIDEO_ID}"},
            {"text": "❌ Skip", "callback_data": "skip"}
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
        print("Sent to Telegram with YouTube upload button!")
    else:
        print(f"Telegram error: {resp.text[:300]}")

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    notify("⚙️ <b>Processing your video...</b>\nThis takes 3-5 minutes ☕")

    try:
        video_path  = download_video()
        audio_path  = extract_audio(video_path)
        segments    = transcribe(audio_path)
        translated  = translate(segments)
        srt_path    = build_srt(translated)
        final       = convert_to_reels(video_path, srt_path)
        send_to_telegram(final)

    except Exception as e:
        print(f"Pipeline error: {e}")
        notify(f"❌ Processing failed: {str(e)[:200]}")

if __name__ == "__main__":
    main()
