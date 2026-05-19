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

# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GH_TOKEN = os.environ["GH_TOKEN"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
SPACE_URL = os.environ.get("SPACE_URL", "")

flask_app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
def is_valid_link(text: str) -> bool:
    patterns = [
        r'https?://.*douyin\.com.*',
        r'https?://.*tiktok\.com.*',
        r'https?://v\.douyin\.com.*',
        r'https?://www\.iesdouyin\.com.*',
    ]
    return any(re.search(p, text))


def extract_link(text: str) -> str:
    match = re.search(r'https?://[^\s]+', text)
    return match.group(0) if match else text.strip()


def get_download_url(url: str) -> tuple:
    """
    Extract direct video URL using yt-dlp
    Returns (video_url, title)
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

            video_url = (
                info.get("url")
                or info.get("play_url")
            )

            if not video_url:
                formats = info.get("formats", [])

                for f in reversed(formats):
                    if f.get("url"):
                        video_url = f["url"]
                        break

            logger.info(f"Extracted title: {title}")
            logger.info(f"Extracted video URL successfully")

            return video_url, title

    except Exception as e:
        logger.error(f"yt-dlp extraction error: {e}")
        return None, None


def trigger_github(video_url: str, title: str) -> bool:
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/process.yml/dispatches"

        resp = requests.post(
            url,
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

        logger.info(f"GitHub trigger status: {resp.status_code}")
        logger.info(resp.text)

        return resp.status_code == 204

    except Exception as e:
        logger.error(f"GitHub trigger error: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *Chinese Shorts Bot*\n\n"
        "Send me a Douyin or TikTok link and I'll:\n"
        "✅ Download the video\n"
        "✅ Process it automatically\n"
        "✅ Send it back ready to post\n\n"
        "🚀 Paste a link to begin!",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────────
# MESSAGE HANDLER
# ─────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if str(update.message.chat_id) != TELEGRAM_CHAT_ID:
        return

    text = update.message.text or ""

    if not is_valid_link(text):
        await update.message.reply_text(
            "❌ Please send a valid Douyin/TikTok link.\n\n"
            "Example:\n"
            "`https://v.douyin.com/xxxxx/`",
            parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text(
        "🔍 Reading video info... ⏳"
    )

    try:
        link = extract_link(text)

        logger.info(f"Received link: {link}")

        await msg.edit_text(
            "⬇️ Extracting download URL... ⏳"
        )

        video_url, title = get_download_url(link)

        if not video_url:
            await msg.edit_text(
                "❌ Could not get download URL!\n\n"
                "Try:\n"
                "• Make sure video is public\n"
                "• Copy full share link from app\n"
                "• Try again later"
            )
            return

        await msg.edit_text(
            f"🚀 Processing started!\n\n"
            f"📹 *{title[:60]}*",
            parse_mode="Markdown"
        )

        success = trigger_github(video_url, title)

        if success:
            await msg.edit_text(
                "✅ *Processing Started Successfully!*\n\n"
                f"📹 *{title[:60]}*\n\n"
                "⏱ Usually takes 2-5 minutes.\n"
                "📱 Video will arrive automatically.\n\n"
                "☕ Sit tight bhai",
                parse_mode="Markdown"
            )
        else:
            await msg.edit_text(
                "❌ Failed to trigger GitHub workflow!"
            )

    except Exception as e:
        logger.error(f"Handler error: {e}")

        await msg.edit_text(
            f"❌ Error:\n`{str(e)[:300]}`",
            parse_mode="Markdown"
        )


# ─────────────────────────────────────────────────────────────
# TELEGRAM APP
# ─────────────────────────────────────────────────────────────
ptb_app = Application.builder().token(
    TELEGRAM_BOT_TOKEN
).build()

ptb_app.add_handler(CommandHandler("start", start))

ptb_app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    )
)

# ─────────────────────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────────────────────
@flask_app.route("/", methods=["GET"])
def index():
    return "🎬 Chinese Shorts Bot is running!", 200


@flask_app.route("/webhook", methods=["POST"])
def webhook():

    data = flask_request.get_json(force=True)

    update = Update.de_json(data, ptb_app.bot)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(ptb_app.initialize())
    loop.run_until_complete(ptb_app.process_update(update))

    return "ok", 200


# ─────────────────────────────────────────────────────────────
# WEBHOOK SETUP
# ─────────────────────────────────────────────────────────────
def setup_webhook():

    if not SPACE_URL:
        logger.warning("SPACE_URL not set!")
        return

    webhook_url = f"{SPACE_URL}/webhook"

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={
                "url": webhook_url,
                "drop_pending_updates": True
            },
            timeout=15
        )

        logger.info(f"Webhook response: {resp.json()}")

    except Exception as e:
        logger.error(f"Webhook setup error: {e}")


# ─────────────────────────────────────────────────────────────
# START SERVER
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":

    setup_webhook()

    port = int(os.environ.get("PORT", 10000))

    flask_app.run(
        host="0.0.0.0",
        port=port,
        debug=False
            )
