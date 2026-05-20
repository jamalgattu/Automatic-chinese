import os
import subprocess
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import requests

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "your-username/your-repo"

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
            await update.message.reply_text(
                f"❌ Download failed. Douyin might be blocking this link.\n\n"
                f"Error: {result.stderr[:150]}"
            )
            return
        
        file_size_mb = os.path.getsize(temp_file) / (1024 * 1024)
        
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
        
        # Step 3: Trigger GitHub Actions
        await update.message.reply_text("⚙️ Processing to Shorts format...")
        
        trigger_response = await trigger_github_actions(
            file_id=file_id,
            user_id=user_id,
            chat_id=update.effective_chat.id
        )
        
        if not trigger_response:
            await update.message.reply_text(
                "❌ Failed to trigger processing. Try again."
            )
        
        # Step 4: Cleanup original file
        os.remove(temp_file)
        
    except subprocess.TimeoutExpired:
        await update.message.reply_text(
            "⏱️ Download timed out (video too large or slow connection)"
        )
    except Exception as e:
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
        return response.status_code == 204
    except Exception as e:
        print(f"GitHub trigger error: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Douyin → Shorts Converter\n\n"
        "Send a Douyin link:\n"
        "`/convert https://douyin.com/...`\n\n"
        "I'll download, convert to 9:16 format, and send back!"
    )


async def main():
    app = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("convert", handle_video_link))
    
    # Webhook for Render
    await app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        url_path="telegram",
        webhook_url=f"{os.getenv('WEBHOOK_URL')}/telegram"
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
