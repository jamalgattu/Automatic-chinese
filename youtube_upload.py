import os
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
TELEGRAM_FILE_ID      = os.environ["TELEGRAM_FILE_ID"]
YOUTUBE_TITLE         = os.environ.get("YOUTUBE_TITLE", "🔥 Chinese Viral Video")
YOUTUBE_DESCRIPTION   = os.environ.get("YOUTUBE_DESCRIPTION", "#Shorts #Chinese #Viral")

WORK_DIR = Path("workdir")
WORK_DIR.mkdir(exist_ok=True)

def notify(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"Notify failed: {e}")


def download_from_telegram(file_id: str) -> Path:
    print(f"Getting file path for file_id: {file_id[:20]}...")

    r = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=15
    )
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]

    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    print(f"Downloading from Telegram...")

    video_path = WORK_DIR / "upload_input.mp4"
    with requests.get(download_url, stream=True, timeout=120) as dl:
        dl.raise_for_status()
        with open(video_path, "wb") as f:
            for chunk in dl.iter_content(chunk_size=8192):
                f.write(chunk)

    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"Downloaded ({size_mb:.1f} MB)")
    return video_path


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


def upload_to_youtube(youtube, video_path: Path) -> str:
    print(f"Uploading to YouTube: {YOUTUBE_TITLE}")

    body = {
        "snippet": {
            "title":           YOUTUBE_TITLE,
            "description":     YOUTUBE_DESCRIPTION + "\n\n#Shorts",
            "tags":            ["shorts", "chinese", "viral"],
            "categoryId":      "22",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus":            "public",
            "selfDeclaredMadeForKids":  False,
            "madeForKids":              False,
        }
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024
    )

    request  = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None

    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload progress: {int(status.progress() * 100)}%")

    video_url = f"https://youtube.com/shorts/{response['id']}"
    print(f"Uploaded! {video_url}")
    return video_url


def main():
    try:
        notify("📤 <b>Downloading from Telegram...</b>")
        video_path = download_from_telegram(TELEGRAM_FILE_ID)

        notify("⬆️ <b>Uploading to YouTube Shorts...</b>\nThis takes ~1 minute!")
        youtube   = get_youtube_client()
        video_url = upload_to_youtube(youtube, video_path)

        notify(
            f"🎉 <b>Uploaded to YouTube Shorts!</b>\n\n"
            f"🎬 {YOUTUBE_TITLE}\n"
            f"🔗 {video_url}\n\n"
            f"It may take a few minutes to go public."
        )

    except Exception as e:
        print(f"Upload failed: {e}")
        notify(f"❌ YouTube upload failed:\n{str(e)[:200]}")


if __name__ == "__main__":
    main()
