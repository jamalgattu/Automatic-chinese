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
GITHUB_REPO = "jamalgattu/Automatic-chinese"  # CHANGE THIS TO YOUR REPO
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def handle_video_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download Douyin video using proxy API"""
    
    if not context.args:
        await update.message.reply_text("Usage: /convert https://douyin.com/...")
        return
    
    url = context.args[0]
    user_id = update.effective_user.id
    
    await update.message.reply_text("⏳ Downloading video...")
    
    temp_file = None
    
    try:
        # Use douyin.wtf API (maintains cookies, handles Douyin protection)
        api_url = f"https://api.douyin.wtf/video/download?url={url}"
        
        logger.info(f"Calling API: {api_url}")
        response = requests.get(api_url, timeout=30)
        
        if response.status_code != 200:
            await update.message.reply_text(
                "❌ Download service temporarily unavailable. Try again in 1 min."
            )
            logger.error(f"API returned {response.status_code}")
            return
        
        data = response.json()
        logger.info(f"API response: {data}")
        
        if not data.get('success') or not data.get('video_url'):
            await update.message.reply_text(
                "❌ Could not download this video. Link might be invalid or expired."
            )
            return
        
        # Download video from proxy
        logger.info(f"Downloading from: {data['video_url']}")
        video_response = requests.get(data['video_url'], timeout=60, stream=True)
        
        temp_file = f"/tmp/douyin_{user_id}_{int(time.time())}.mp4"
        
        with open(temp_file, 'wb') as f:
            for chunk in video_response.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
        
        file_size_mb = os.path.getsize(temp_file) / (1024 * 1024)
        logger.info(f"Downloaded: {file_size_mb:.1f}MB")
        
        if file_size_mb > 100:
            os.remove(temp_file)
            await update.message.reply_text(f"❌ Video too large ({file_size_mb:.1f}MB). Max 100MB.")
            return
        
        # Upload to Telegram
        await update.message.reply_text("📤 Uploading for processing...")
        
        with open(temp_file, 'rb') as f:
            sent_msg = await update.effective_chat.send_video(
                f,
                caption="Processing...",
                supports_streaming=True
            )
        
        file_id = sent_msg.video.file_id
        logger.info(f"Got file_id: {file_id}")
        
        # Trigger GitHub Actions
        await update.message.reply_text("⚙️ Processing to Shorts format...")
        
        trigger_ok = await trigger_github_actions(file_id, user_id, update.effective_chat.id)
        
        if not trigger_ok:
            await update.message.reply_text("❌ Failed to trigger processing. Try again.")
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
            return
        
        # Cleanup
        if temp_file and os.path.exists(temp_file):
            os.remove(temp_file)
        logger.info("Cleanup done")
        
    except requests.exceptions.Timeout:
        await update.message.reply_text("⏱️ Download timed out. Try again.")
        logger.error("Timeout during download")
    except requests.exceptions.RequestException as e:
        await update.message.reply_text(f"❌ Network error: {str(e)[:100]}")
        logger.error(f"Request error: {e}")
    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        await update.message.reply_text(f"❌ Error: {str(e)[:150]}")
    finally:
        # Ensure cleanup
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass


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
    """Start the bot using polling"""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("convert", handle_video_link))
    
    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
