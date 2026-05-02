import os
import logging
import requests
import json
import asyncio
from flask import Flask, request as flask_request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
GITHUB_TOKEN       = os.environ["GH_TOKEN"]
GITHUB_REPO        = os.environ["GITHUB_REPO"]
SPACE_URL          = os.environ.get("SPACE_URL", "")

flask_app = Flask(__name__)

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def trigger_github(workflow: str, inputs: dict):
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow}/dispatches"
    resp = requests.post(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }, json={"ref": "main", "inputs": inputs}, timeout=15)
    return resp.status_code == 204

def upload_to_tmpfiles(video_bytes: bytes) -> str:
    resp = requests.post(
        "https://tmpfiles.org/api/v1/upload",
        files={"file": ("video.mp4", video_bytes, "video/mp4")},
        timeout=120
    )
    url = resp.json()["data"]["url"]
    return url.replace("tmpfiles.org/", "tmpfiles.org/dl/")

# ─── HANDLERS ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *Chinese Shorts Bot*\n\n"
        "Send me any Chinese video and I'll:\n"
        "✅ Translate to Hinglish\n"
        "✅ Add funny subtitles\n"
        "✅ Convert to 9:16 Reels\n"
        "✅ Upload to YouTube Shorts!\n\n"
        "Just send a video! 🚀",
        parse_mode="Markdown"
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != TELEGRAM_CHAT_ID:
        return

    msg = await update.message.reply_text("📥 Got it! Uploading... ⏳")

    try:
        video = update.message.video or update.message.document
        if not video:
            await msg.edit_text("❌ Send a video file!")
            return

        if video.file_size > 50 * 1024 * 1024:
            await msg.edit_text("❌ Too large! Keep under 50MB.")
            return

        await msg.edit_text("📤 Uploading to temp server... ⏳")
        file        = await context.bot.get_file(video.file_id)
        video_bytes = await file.download_as_bytearray()
        temp_url    = upload_to_tmpfiles(bytes(video_bytes))

        await msg.edit_text("🚀 Triggering pipeline... ⏳")
        caption = update.message.caption or ""
        success = trigger_github("process.yml", {"video_url": temp_url, "caption": caption})

        if success:
            await msg.edit_text(
                "✅ *Processing started!*\n\n"
                "⏱ Takes ~5 minutes\n"
                "📱 Final Short incoming soon!\n\n"
                "Sit back bhai ☕",
                parse_mode="Markdown"
            )
        else:
            await msg.edit_text("❌ Failed to start pipeline. Check GitHub Actions!")

    except Exception as e:
        logger.error(f"Video handler error: {e}")
        await msg.edit_text(f"❌ Error: {str(e)[:200]}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("upload_yt:"):
        video_id = query.data.split(":", 1)[1]
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n⏳ Uploading to YouTube...",
            parse_mode="HTML"
        )
        success = trigger_github("youtube.yml", {"video_id": video_id})
        suffix  = "✅ Uploading! Check your channel in ~2 mins 🎉" if success else "❌ Upload failed."
        await query.edit_message_caption(
            caption=query.message.caption.replace("⏳ Uploading to YouTube...", suffix),
            parse_mode="HTML"
        )

    elif query.data == "skip":
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n⏭ Skipped upload.",
            parse_mode="HTML"
        )

# ─── BUILD PTB APP ─────────────────────────────────────────────────────────────
ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
ptb_app.add_handler(CallbackQueryHandler(handle_callback))

# ─── FLASK ROUTES ──────────────────────────────────────────────────────────────
@flask_app.route("/", methods=["GET"])
def index():
    return "🎬 Bot is alive!", 200

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
        logger.warning("SPACE_URL not set! Webhook not configured.")
        return
    webhook_url = f"{SPACE_URL}/webhook"
    resp = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
        json={"url": webhook_url, "drop_pending_updates": True},
        timeout=10
    )
    logger.info(f"Webhook set to {webhook_url}: {resp.json()}")

if __name__ == "__main__":
    setup_webhook()
    flask_app.run(host="0.0.0.0", port=7860, debug=False)

