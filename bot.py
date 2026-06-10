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

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ENV
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
GH_TOKEN           = os.environ.get("GH_TOKEN", "")
GITHUB_REPO        = os.environ.get("GITHUB_REPO", "")
SPACE_URL          = os.environ.get("SPACE_URL", "")

for key, val in {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID":   TELEGRAM_CHAT_ID,
    "GH_TOKEN":           GH_TOKEN,
    "GITHUB_REPO":        GITHUB_REPO,
}.items():
    if not val:
        logger.error(f"Missing env var: {key}")

# ─────────────────────────────────────────────
# STATE  { chat_id: file_id }
# ─────────────────────────────────────────────
pending_youtube   = {}
pending_instagram = {}

# ─────────────────────────────────────────────
# FLASK
# ─────────────────────────────────────────────
flask_app = Flask(__name__)

# ─────────────────────────────────────────────
# GITHUB TRIGGERS
# ─────────────────────────────────────────────
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
        logger.error(f"Dispatch error ({workflow}): {e}")
        return False


def trigger_process(share_url: str)     -> bool: return _dispatch("process.yml",   {"share_url": share_url})
def trigger_youtube(fid, title, desc)   -> bool: return _dispatch("upload.yml",    {"file_id": fid, "title": title, "description": desc})
def trigger_instagram(fid, caption)     -> bool: return _dispatch("instagram.yml", {"file_id": fid, "caption": caption})

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def is_douyin_link(text: str) -> bool:
    return bool(re.search(r'https?://[^\s]*(douyin|tiktok|iesdouyin)[^\s]*', text))

def extract_link(text: str) -> str:
    m = re.search(r'https?://[^\s]+', text)
    return m.group(0) if m else text.strip()

def get_video_file_id(message) -> str | None:
    """Extract file_id from a message that contains a video."""
    if message is None:
        return None
    if message.video:
        return message.video.file_id
    if message.document and message.document.mime_type == "video/mp4":
        return message.document.file_id
    return None

# ─────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 <b>Chinese Shorts Bot</b>\n\n"
        "Send a Douyin or TikTok link and I'll:\n"
        "✅ Download &amp; convert to 9:16\n"
        "✅ Send it back to you\n"
        "✅ Let you post to YouTube / Instagram\n\n"
        "🚀 Paste a link to begin!\n\n"
        "<i>Commands:</i>\n"
        "/uploadinsta — upload last video to Instagram\n"
        "/start — show this message",
        parse_mode="HTML",
    )


async def cmd_uploadinsta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Usage (reply to the video):
        /uploadinsta My caption here #Shorts
    Or just:
        /uploadinsta
    and the bot will ask for a caption.
    """
    if str(update.message.chat_id) != str(TELEGRAM_CHAT_ID):
        return

    # Try to get file_id from replied-to message
    file_id = get_video_file_id(update.message.reply_to_message)

    if not file_id:
        await update.message.reply_text(
            "⚠️ Please <b>reply to a video</b> with this command.\n\n"
            "Example: reply to the processed video and send:\n"
            "<code>/uploadinsta Your caption here #Reels</code>",
            parse_mode="HTML",
        )
        return

    # Caption = everything after "/uploadinsta "
    caption = update.message.text.partition(" ")[2].strip()

    if caption:
        # Caption provided inline — start upload immediately
        msg = await update.message.reply_text("📸 Starting Instagram upload...")
        if trigger_instagram(file_id, caption):
            await msg.edit_text(
                "✅ <b>Instagram upload started!</b>\n\n"
                f"📝 {caption[:100]}\n\n"
                "⏱ ~1-2 mins. I'll send the Reel link when it's live!",
                parse_mode="HTML",
            )
        else:
            await msg.edit_text("❌ Failed to start Instagram upload. Check GitHub secrets.")
    else:
        # No caption — ask for it
        pending_instagram[str(update.message.chat_id)] = file_id
        await update.message.reply_text(
            "📸 <b>Instagram Reel Caption</b>\n\n"
            "Reply with your caption:\n\n"
            "<i>Example:</i>\n"
            "<code>Viral Chinese dance 🔥 #Shorts #Viral #Reels</code>",
            parse_mode="HTML",
        )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline button taps (post_youtube / post_instagram / just_send)."""
    query = update.callback_query
    await query.answer()

    if query.data == "just_send":
        return  # video was already sent — nothing to do

    file_id = get_video_file_id(query.message)
    if not file_id:
        await query.message.reply_text("❌ Could not find the video file. Please try again.")
        return

    chat_id = str(query.message.chat_id)

    if query.data == "post_youtube":
        pending_youtube[chat_id] = file_id
        await query.message.reply_text(
            "📝 <b>YouTube Upload</b>\n\n"
            "Reply with title and description:\n"
            "<code>Title | Description</code>\n\n"
            "<i>Example:</i>\n"
            "<code>Viral Chinese dance 🔥 | Funny clip #Shorts</code>",
            parse_mode="HTML",
        )

    elif query.data == "post_instagram":
        pending_instagram[chat_id] = file_id
        await query.message.reply_text(
            "📸 <b>Instagram Reel</b>\n\n"
            "Reply with your caption:\n\n"
            "<i>Example:</i>\n"
            "<code>Viral Chinese dance 🔥 #Shorts #Viral #Reels</code>",
            parse_mode="HTML",
        )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = str(update.message.chat_id)
        if chat_id != str(TELEGRAM_CHAT_ID):
            return

        text = (update.message.text or "").strip()

        # ── Instagram caption pending ────────────
        if chat_id in pending_instagram:
            file_id = pending_instagram.pop(chat_id)
            msg = await update.message.reply_text("📸 Starting Instagram upload...")
            if trigger_instagram(file_id, text):
                await msg.edit_text(
                    "✅ <b>Instagram upload started!</b>\n\n"
                    f"📝 {text[:100]}\n\n"
                    "⏱ ~1-2 mins. I'll send the Reel link when it's live!",
                    parse_mode="HTML",
                )
            else:
                await msg.edit_text("❌ Failed to start Instagram upload. Check GitHub secrets.")
            return

        # ── YouTube details pending ──────────────
        if chat_id in pending_youtube:
            if "|" not in text:
                await update.message.reply_text(
                    "⚠️ Use the format: <code>Title | Description</code>",
                    parse_mode="HTML",
                )
                return
            title, _, description = text.partition("|")
            file_id = pending_youtube.pop(chat_id)
            msg = await update.message.reply_text("📤 Starting YouTube upload...")
            if trigger_youtube(file_id, title.strip(), description.strip()):
                await msg.edit_text(
                    "✅ <b>YouTube upload started!</b>\n\n"
                    f"🎬 {title.strip()}\n"
                    f"📝 {description.strip()[:80]}\n\n"
                    "⏱ ~1-2 mins. I'll send the YouTube link when it's done!",
                    parse_mode="HTML",
                )
            else:
                await msg.edit_text("❌ Failed to start YouTube upload. Check GitHub secrets.")
            return

        # ── Douyin / TikTok link ─────────────────
        if not is_douyin_link(text):
            await update.message.reply_text(
                "❌ Send a Douyin or TikTok link.\n\nExample:\nhttps://v.douyin.com/xxxxx/"
            )
            return

        link = extract_link(text)
        msg  = await update.message.reply_text("🚀 Sending to processor...")
        if trigger_process(link):
            await msg.edit_text(
                "✅ <b>Processing started!</b>\n\n"
                f"🔗 {link[:70]}\n\n"
                "⏱ 2-5 mins — you'll get the video when it's ready.",
                parse_mode="HTML",
            )
        else:
            await msg.edit_text("❌ Failed to trigger GitHub workflow.")

    except Exception as e:
        logger.error(f"Message handler error: {e}")
        try:
            await update.message.reply_text(f"❌ Error: {str(e)[:200]}")
        except Exception:
            pass

# ─────────────────────────────────────────────
# BUILD PTB APPLICATION
# One persistent event loop — never closed.
# httpx (used by ptb v20+) binds to the loop it
# was created in; closing it kills all connections.
# ─────────────────────────────────────────────
_bot_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_bot_loop)

ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
ptb_app.add_handler(CommandHandler("start",        cmd_start))
ptb_app.add_handler(CommandHandler("uploadinsta",  cmd_uploadinsta))
ptb_app.add_handler(CallbackQueryHandler(on_button))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

_bot_loop.run_until_complete(ptb_app.initialize())

# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# WEBHOOK REGISTRATION
# ─────────────────────────────────────────────
def setup_webhook():
    if not SPACE_URL:
        logger.warning("SPACE_URL not set — webhook not registered")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
            json={"url": f"{SPACE_URL}/webhook", "drop_pending_updates": True},
            timeout=20,
        )
        logger.info(f"Webhook set: {r.text}")
    except Exception as e:
        logger.error(f"Webhook setup failed: {e}")

setup_webhook()

# ─────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False)
