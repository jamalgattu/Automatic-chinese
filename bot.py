import os
import logging
import requests
import re
import asyncio
from flask import Flask, request as flask_request
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
GH_TOKEN           = os.environ["GH_TOKEN"]
GITHUB_REPO        = os.environ["GITHUB_REPO"]
SPACE_URL          = os.environ.get("SPACE_URL", "")

flask_app = Flask(__name__)

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def is_douyin_link(text: str) -> bool:
    patterns = [
        r'https?://.*douyin\.com.*',
        r'https?://.*tiktok\.com.*',
        r'https?://v\.douyin\.com.*',
        r'https?://www\.iesdouyin\.com.*',
    ]
    return any(re.search(p, text) for p in patterns)

def extract_link(text: str) -> str:
    match = re.search(r'https?://[^\s]+', text)
    return match.group(0) if match else text.strip()

def get_download_url(douyin_url: str) -> str:
    """Get watermark-free MP4 URL from douyin.wtf"""
    try:
        resp = requests.get(
            "https://api.douyin.wtf/api",
            params={"url": douyin_url, "minimal": "false"},
            timeout=20
        )
        data = resp.json()
        logger.info(f"douyin.wtf response: {data}")

        # Try different response fields
        video_url = (
            data.get("video_url") or
            data.get("nwm_video_url") or
            data.get("nwm_video_url_HQ") or
            data.get("play_addr", {}).get("url_list", [None])[0]
        )
        return video_url
    except Exception as e:
        logger.error(f"douyin.wtf error: {e}")
        return None

def trigger_github(video_url: str) -> bool:
    """Trigger GitHub Actions to process the video"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/process.yml/dispatches"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json"
        },
        json={"ref": "main", "inputs": {"video_url": video_url}},
        timeout=15
    )
    logger.info(f"GitHub trigger status: {resp.status_code}")
    return resp.status_code == 204

# ─── HANDLERS ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *Chinese Shorts Bot*\n\n"
        "Send me a Douyin link and I'll:\n"
        "✅ Download watermark-free\n"
        "✅ Convert to 9:16 Reels format\n"
        "✅ Send back ready to post!\n\n"
        "Just paste a Douyin link! 🚀",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != TELEGRAM_CHAT_ID:
        return

    text = update.message.text or ""

    if not is_douyin_link(text):
        await update.message.reply_text(
            "❌ Send me a Douyin link!\n\n"
            "Example:\n`https://v.douyin.com/xxxxx`",
            parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text("🔍 Got your link! Fetching video... ⏳")

    try:
        link = extract_link(text)
        logger.info(f"Processing link: {link}")

        # Get download URL
        video_url = get_download_url(link)

        if not video_url:
            await msg.edit_text(
                "❌ Could not get download URL!\n"
                "Make sure the link is a valid public Douyin video."
            )
            return

        await msg.edit_text("🚀 Triggering processing pipeline... ⏳")

        # Trigger GitHub Actions
        success = trigger_github(video_url)

        if success:
            await msg.edit_text(
                "✅ *Processing started!*\n\n"
                "⏱ Takes ~3-5 minutes\n"
                "📱 I'll send your converted Short soon!\n\n"
                "Sit back bhai ☕",
                parse_mode="Markdown"
            )
        else:
            await msg.edit_text(
                "❌ Failed to trigger processing!\n"
                "Check GitHub Actions setup."
            )

    except Exception as e:
        logger.error(f"Error: {e}")
        await msg.edit_text(f"❌ Error: {str(e)[:200]}")

# ─── BUILD PTB APP ─────────────────────────────────────────────────────────────
ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────────
@flask_app.route("/", methods=["GET"])
def index():
    return "🎬 Chinese Shorts Bot is alive!", 200

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    data   = flask_request.get_json(force=True)
    update = Update.de_json(data, ptb_app.bot)
    loop   = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ptb_app.initialize())
    loop.run_until_complete(ptb_app.process_update(update))
    return "ok", 200

# ─── STARTUP ───────────────────────────────────────────────────────────────────
def setup_webhook():
    if not SPACE_URL:
        logger.warning("SPACE_URL not set!")
        return
    webhook_url = f"{SPACE_URL}/webhook"
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
        json={"url": webhook_url, "drop_pending_updates": True},
        timeout=10
    )
    logger.info(f"Webhook: {resp.json()}")

if __name__ == "__main__":
    setup_webhook()
    flask_app.run(host="0.0.0.0", port=7860, debug=False)

