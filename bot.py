import os
import logging
import requests
import re
import asyncio
import yt_dlp

from flask import Flask, request as flask_request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ENV VARIABLES
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GH_TOKEN = os.environ.get("GH_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
SPACE_URL = os.environ.get("SPACE_URL", "")

# ─────────────────────────────────────────────
# CHECK ENV VARIABLES
# ─────────────────────────────────────────────
required_vars = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    "GH_TOKEN": GH_TOKEN,
    "GITHUB_REPO": GITHUB_REPO,
}

for key, value in required_vars.items():
    if not value:
        raise Exception(f"Missing environment variable: {key}")

# ─────────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────────
flask_app = Flask(__name__)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def is_valid_link(text: str) -> bool:
    patterns = [
        r'https?://.*douyin\.com.*',
        r'https?://.*tiktok\.com.*',
        r'https?://v\.douyin\.com.*',
        r'https?://www\.iesdouyin\.com.*',
    ]

    return any(re.search(p, text) for p in patterns)


def extract_link(text: str) -> str:
    match = re.search(r'https?://[^\s]+', text)

    if match:
        return match.group(0)

    return text.strip()


def get_download_url(url: str):
    """
    Extract direct video URL using yt-dlp
    """

    try:
        ydl_opts = {
            "quiet": True,
            "noplaylist": True,
            "extract_flat": False,
            "http_headers": {
                "User-Agent": "Mozilla/5.0"
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:

            info = ydl.extract_info(url, download=False)

            title = info.get("title", "Chinese Video")

            video_url = info.get("url")

            if not video_url:
                formats = info.get("formats", [])

                for fmt in reversed(formats):

                    if fmt.get("url"):
                        video_url = fmt["url"]
                        break

            if not video_url:
                return None, None

            logger.info(f"Title: {title}")
            logger.info("Video URL extracted successfully")

            return video_url, title

    except Exception as e:
        logger.error(f"yt-dlp error: {e}")

        return None, None


def trigger_github(video_url: str, title: str):

    try:

        api_url = (
            f"https://api.github.com/repos/"
            f"{GITHUB_REPO}/actions/workflows/process.yml/dispatches"
        )

        response = requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json"
            },
            json={
                "ref": "main",
                "inputs": {
                    "video_url": video_url,
                    "title": title
                }
            },
            timeout=20
        )

        logger.info(f"GitHub API status: {response.status_code}")
        logger.info(response.text)

        return response.status_code == 204

    except Exception as e:
        logger.error(f"GitHub trigger error: {e}")

        return False

# ─────────────────────────────────────────────
# TELEGRAM COMMANDS
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🎬 Chinese Shorts Bot\n\n"
        "Send a Douyin or TikTok link.\n\n"
        "I'll:\n"
        "✅ Extract the video\n"
        "✅ Process it\n"
        "✅ Send it back automatically\n\n"
        "🚀 Paste a link to begin!"
    )


# ─────────────────────────────────────────────
# MAIN MESSAGE HANDLER
# ─────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        if str(update.message.chat_id) != str(TELEGRAM_CHAT_ID):
            return

        text = update.message.text or ""

        if not is_valid_link(text):

            await update.message.reply_text(
                "❌ Invalid link.\n\n"
                "Example:\n"
                "https://v.douyin.com/xxxxx/"
            )

            return

        msg = await update.message.reply_text(
            "🔍 Reading video info..."
        )

        link = extract_link(text)

        logger.info(f"Received link: {link}")

        await msg.edit_text(
            "⬇️ Extracting direct video URL..."
        )

        video_url, title = get_download_url(link)

        if not video_url:

            await msg.edit_text(
                "❌ Could not extract video.\n\n"
                "Possible reasons:\n"
                "• Video is private\n"
                "• Douyin blocked extraction\n"
                "• Invalid share link\n"
                "• Temporary failure\n\n"
                "Try another link."
            )

            return

        await msg.edit_text(
            f"🚀 Processing started!\n\n"
            f"📹 {title[:70]}"
        )

        success = trigger_github(video_url, title)

        if success:

            await msg.edit_text(
                "✅ Processing started successfully!\n\n"
                f"📹 {title[:70]}\n\n"
                "⏱ Processing time: 2-5 mins"
            )

        else:

            await msg.edit_text(
                "❌ Failed to trigger GitHub workflow."
            )

    except Exception as e:

        logger.error(f"Handler error: {e}")

        try:
            await update.message.reply_text(
                f"❌ Error:\n{str(e)[:300]}"
            )
        except:
            pass

# ─────────────────────────────────────────────
# TELEGRAM APPLICATION
# ─────────────────────────────────────────────
ptb_app = Application.builder().token(
    TELEGRAM_BOT_TOKEN
).build()

ptb_app.add_handler(
    CommandHandler("start", start)
)

ptb_app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    )
)

# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────
@flask_app.route("/", methods=["GET"])
def home():
    return "Chinese Shorts Bot Running", 200


@flask_app.route("/webhook", methods=["POST"])
def webhook():

    try:

        data = flask_request.get_json(force=True)

        update = Update.de_json(data, ptb_app.bot)

        loop = asyncio.new_event_loop()

        asyncio.set_event_loop(loop)

        loop.run_until_complete(
            ptb_app.initialize()
        )

        loop.run_until_complete(
            ptb_app.process_update(update)
        )

        return "ok", 200

    except Exception as e:

        logger.error(f"Webhook error: {e}")

        return "error", 500

# ─────────────────────────────────────────────
# SET TELEGRAM WEBHOOK
# ─────────────────────────────────────────────
def setup_webhook():

    if not SPACE_URL:

        logger.warning("SPACE_URL not set")

        return

    webhook_url = f"{SPACE_URL}/webhook"

    try:

        response = requests.post(
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={
                "url": webhook_url,
                "drop_pending_updates": True
            },
            timeout=20
        )

        logger.info(response.text)

    except Exception as e:

        logger.error(f"Webhook setup failed: {e}")

# ─────────────────────────────────────────────
# START APP
# ─────────────────────────────────────────────
if __name__ == "__main__":

    setup_webhook()

    port = int(os.environ.get("PORT", 10000))

    flask_app.run(
        host="0.0.0.0",
        port=port,
        debug=False
)
