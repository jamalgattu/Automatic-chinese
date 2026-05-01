import os
import json
import requests
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN    = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID      = os.environ["TELEGRAM_CHAT_ID"]
YOUTUBE_CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]
VIDEO_ID              = os.environ["VIDEO_ID"]

WORK_DIR = Path("workdir")

def notify(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Notify failed: {e}")

def get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

def upload_to_youtube(youtube, video_path):
    print(f"Uploading {video_path} to YouTube...")

    body = {
        "snippet": {
            "title": "🔥 Chinese Viral Video | Hinglish Subtitles",
            "description": (
                "Viral Chinese video with Hinglish subtitles!\n\n"
                "#Shorts #Chinese #Viral #Hinglish #Funny"
            ),
            "tags": ["shorts", "chinese", "viral", "hinglish", "funny", "reels"],
            "categoryId": "22",  # People & Blogs
            "defaultLanguage": "hi",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
            "madeForKids": False
        }
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024*1024
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    video_url = f"https://youtube.com/shorts/{response['id']}"
    print(f"Uploaded! URL: {video_url}")
    return video_url

def main():
    # Find the processed video
    videos = list(WORK_DIR.glob(f"final_{VIDEO_ID}*.mp4"))
    if not videos:
        # Try downloading from GitHub Actions artifacts
        notify("❌ Could not find processed video to upload.")
        return

    video_path = videos[0]

    try:
        notify("📤 Uploading to YouTube... This takes ~1 minute!")
        youtube    = get_youtube_client()
        video_url  = upload_to_youtube(youtube, video_path)

        notify(
            f"🎉 <b>Uploaded to YouTube!</b>\n\n"
            f"🔗 {video_url}\n\n"
            f"It may take a few minutes to appear publicly!"
        )

    except Exception as e:
        print(f"Upload failed: {e}")
        notify(f"❌ YouTube upload failed: {str(e)[:200]}")

if __name__ == "__main__":
    main()

