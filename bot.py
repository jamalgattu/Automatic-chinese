import os
import logging
import requests
import re
import asyncio

from flask import Flask, request as flask_request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── ENV ───────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
GH_TOKEN           = os.environ.get("GH_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "")
SPACE_URL          = os.environ.get("SPACE_URL", "")

# ─── STATE ─────────────────────────────────────────────────────────────────────
pending_facebook = {}

flask_app = Flask(__name__)

# ─── GITHUB DISPATCH ───────────────────────────────────────────────────────────
def _dispatch(workflow: str, inputs: dict) -> bool:
    try:
        r = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{workflow}/dispatches",
            headers={
                "Authorization": f"Bearer {GH_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            json={"ref": "main", "inputs": inputs},
            timeout=20,
        )
        logger.info(f"{workflow} dispatch → {r.status_code}")
        return r.status_code == 204
    except Exception as e:
        logger.error(f"Dispatch error: {e}")
        return False

def trigger_process(share_url: str)   -> bool: return _dispatch("process.yml",  {"share_url": share_url})
def trigger_facebook(fid, caption)    -> bool: return _dispatch("facebook.yml", {"file_id": fid, "caption": caption})

# ─── HELPERS ───────────────────────────────────────────────────────────────────
def is_douyin_link(text: str) -> bool:
    return bool(re.search(r'https?://[^\s]*(douyin|tiktok|iesdouyin)[^\s]*', text))

def extract_link(text: str) -> str:
    m = re.search(r'https?://[^\s]+', text)
    return m.group(0) if m else text.strip()

def get_video_file_id(message) -> str | None:
    if message is None:
        return None
    if message.video:
        return message.video.file_id
    if message.document and message.document.mime_type == "video/mp4":
        return message.document.file_id
    return None

# ─── HANDLERS ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 <b>Chinese Shorts Bot</b>\n\n"
        "Send a Douyin or TikTok link and I'll:\n"
        "✅ Download &amp; convert to 9:16\n"
        "✅ Send it back to you\n"
        "✅ Post to Facebook Page!\n\n"
        "🚀 Paste a link to begin!\n\n"
        "<i>Commands:</i>\n"
        "/uploadfb — upload last video to Facebook\n"
        "/start — show this message",
        parse_mode="HTML",
    )

async def cmd_uploadfb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.chat_id) != str(TELEGRAM_CHAT_ID):
        return

    file_id = get_video_file_id(update.message.reply_to_message)

    if not file_id:
        await update.message.reply_text(
            "⚠️ Reply to a video with this command.\n\n"
            "Example: reply to the processed video and send:\n"
            "<code>/uploadfb Your caption here #Reels</code>",
            parse_mode="HTML",
        )
        return

    caption = update.message.text.partition(" ")[2].strip()

    if caption:
        msg = await update.message.reply_text("📘 Starting Facebook upload...")
        if trigger_facebook(file_id, caption):
            await msg.edit_text(
                "✅ <b>Facebook upload started!</b>\n\n"
                f"📝 {caption[:100]}\n\n"
                "⏱ ~1-2 mins. I'll send the post link when live!",
                parse_mode="HTML",
            )
        else:
            await msg.edit_text("❌ Failed to start Facebook upload.")
    else:
        pending_facebook[str(update.message.chat_id)] = file_id
        await update.message.reply_text(
            "📘 <b>Facebook Post Caption</b>\n\n"
            "Reply with your caption:\n\n"
            "<i>Example:</i>\n"
            "<code>Viral Chinese video 🔥 #Shorts #Viral</code>",
            parse_mode="HTML",
        )

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "just_send":
        return

    file_id = get_video_file_id(query.message)
    if not file_id:
        await query.message.reply_text("❌ Could not find video. Try again.")
        return

    chat_id = str(query.message.chat_id)

    if query.data == "post_facebook":
        pending_facebook[chat_id] = file_id
        await query.message.reply_text(
            "📘 <b>Facebook Post Caption</b>\n\n"
            "Send your caption:\n\n"
            "<i>Example:</i>\n"
            "<code>Viral Chinese video 🔥 #Shorts #Viral</code>",
            parse_mode="HTML",
        )

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = str(update.message.chat_id)
        if chat_id != str(TELEGRAM_CHAT_ID):
            return

        text = (update.message.text or "").strip()

        # ── Facebook caption pending ─────────────
        if chat_id in pending_facebook:
            file_id = pending_facebook.pop(chat_id)
            msg = await update.message.reply_text("📘 Starting Facebook upload...")
            if trigger_facebook(file_id, text):
                await msg.edit_text(
                    "✅ <b>Facebook upload started!</b>\n\n"
                    f"📝 {text[:100]}\n\n"
                    "⏱ ~1-2 mins. Post link incoming!",
                    parse_mode="HTML",
                )
            else:
                await msg.edit_text("❌ Failed to start Facebook upload.")
            return

        # ── Douyin / TikTok link ─────────────────
        if not is_douyin_link(text):
            await update.message.reply_text(
                "❌ Send a Douyin or TikTok link.\n\n"
                "Example:\nhttps://v.douyin.com/xxxxx/"
            )
            return

        link = extract_link(text)
        msg  = await update.message.reply_text("🚀 Sending to processor...")
        if trigger_process(link):
            await msg.edit_text(
                "✅ <b>Processing started!</b>\n\n"
                f"🔗 {link[:70]}\n\n"
                "⏱ 2-5 mins — video incoming!",
                parse_mode="HTML",
            )
        else:
            await msg.edit_text("❌ Failed to trigger processing.")

    except Exception as e:
        logger.error(f"Message error: {e}")
        try:
            await update.message.reply_text(f"❌ Error: {str(e)[:200]}")
        except Exception:
            pass

# ─── PTB APP ───────────────────────────────────────────────────────────────────
_bot_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_bot_loop)

ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
ptb_app.add_handler(CommandHandler("start",      cmd_start))
ptb_app.add_handler(CommandHandler("uploadfb",   cmd_uploadfb))
ptb_app.add_handler(CallbackQueryHandler(on_button))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

_bot_loop.run_until_complete(ptb_app.initialize())

# ─── FLASK ─────────────────────────────────────────────────────────────────────
@flask_app.route("/", methods=["GET"])
def home():
    return "Chinese Shorts Bot Running", 200

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data   = flask_request.get_json(force=True)
        update = Update.de_json(data, ptb_app.bot)
        _bot_loop.run_until_complete(ptb_app.process_update(update))
        return "ok", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "error", 500

def setup_webhook():
    if not SPACE_URL:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={"url": f"{SPACE_URL}/webhook", "drop_pending_updates": True},
            timeout=20,
        )
        logger.info(f"Webhook: {r.text}")
    except Exception as e:
        logger.error(f"Webhook setup failed: {e}")

setup_webhook()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False)
