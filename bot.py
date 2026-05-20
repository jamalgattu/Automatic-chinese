import os
import subprocess
import time
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "your-username/your-repo"  # Change this!
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def handle_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download Douyin video, trigger processing, return result"""
    
    if not context.args:
        await update.message.reply_text("Usage: /convert https://douyin.com/...")
        return
    
    url = context.args[0]
    user_id = update.effective_user.id
    
    await update.message.reply_text("⏳ Downloading video...")
    
    try:
        # Step 1: Download with yt-dlp to temp file
        temp_file = f"/tmp/douyin_{user_id}_{int(time.time())}.mp4"
        
        result = subprocess.run([
            'yt-dlp',
            '-f', 'best[ext=mp4]',
            '-o', temp_file,
            '--quiet',
            '--no-warnings',
            url
        ], timeout=120, capture_output=True, text=True)
        
        if result.returncode != 0 or not os.path.exists(temp_file):
            logger.error(f"Download failed: {result.stderr}")
            await update.message.reply_text(
                f"❌ Download failed. Douyin might be blocking this link.\n\n"
                f"Error: {result.stderr[:150]}"
            )
            return
        
        file_size_mb = os.path.getsize(temp_file) / (1024 * 1024)
        logger.info(f"Downloaded: {file_size_mb:.1f}MB")
        
        if file_size_mb > 100:
            os.remove(temp_file)
            await update.message.reply_text(
                f"❌ Video too large ({file_size_mb:.1f}MB). Max 100MB."
            )
            return
        
        # Step 2: Upload to Telegram (to get file_id for processing)
        await update.message.reply_text("📤 Uploading for processing...")
        
        with open(temp_file, 'rb') as f:
            sent_msg = await update.effective_chat.send_video(
                f,
                caption="Processing...",
                supports_streaming=True
            )
        
        file_id = sent_msg.video.file_id
        logger.info(f"Got file_id: {file_id}")
        
        # Step 3: Trigger GitHub Actions
        await update.message.reply_text("⚙️ Processing to Shorts format...")
        
        trigger_ok = await trigger_github_actions(
            file_id=file_id,
            user_id=user_id,
            chat_id=update.effective_chat.id
        )
        
        if not trigger_ok:
            await update.message.reply_text(
                "❌ Failed to trigger processing. Try again."
            )
            os.remove(temp_file)
            return
        
        # Step 4: Cleanup original file
        os.remove(temp_file)
        logger.info("Cleanup done")
        
    except subprocess.TimeoutExpired:
        await update.message.reply_text(
            "⏱️ Download timed out (video too large or slow connection)"
        )
    except Exception as e:
        logger.error(f"Exception: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:150]}")


async def trigger_github_actions(file_id: str, user_id: int, chat_id: int) -> bool:
    """Trigger GitHub Actions workflow with file_id"""
    
    url = f"https://api.github.com/repos/{GITHUB_REPO}/dispatches"
    
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    payload = {
        "event_type": "process_video",
        "client_payload": {
            "file_id": file_id,
            "user_id": str(user_id),
            "chat_id": str(chat_id)
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        logger.info(f"GitHub trigger response: {response.status_code}")
        return response.status_code == 204
    except Exception as e:
        logger.error(f"GitHub trigger error: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Douyin → Shorts Converter\n\n"
        "Send a Douyin link:\n"
        "`/convert https://douyin.com/...`\n\n"
        "I'll download, convert to 9:16 format, and send back!"
    )


def main():
    """Start the bot using polling (simple, no webhook needed)"""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("convert", handle_video_link))
    
    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
