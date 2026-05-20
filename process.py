import os
import subprocess
import requests
from telegram import Bot
from pathlib import Path

async def main():
    file_id = os.getenv("FILE_ID")
    user_id = int(os.getenv("USER_ID"))
    chat_id = int(os.getenv("CHAT_ID"))
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    bot = Bot(token=token)
    
    try:
        # Step 1: Download from Telegram
        print("📥 Downloading from Telegram...")
        file = await bot.get_file(file_id)
        input_file = f"/tmp/original_{file_id}.mp4"
        await file.download_to_drive(input_file)
        
        # Step 2: Convert to 9:16 with blur background
        print("⚙️ Converting to 9:16 format...")
        output_file = f"/tmp/processed_{file_id}.mp4"
        
        subprocess.run([
            'ffmpeg',
            '-i', input_file,
            '-vf', (
                "scale=1080:1920:force_original_aspect_ratio=decrease,"
                "boxblur=40:2,"
                "[0]scale=1080:1920:force_original_aspect_ratio=decrease"
                "[scaled];"
                "[1:v][scaled]overlay=(W-w)/2:(H-h)/2"
            ),
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'aac',
            output_file
        ], check=True, capture_output=True)
        
        # Step 3: Send back to user
        print("📤 Sending processed video...")
        with open(output_file, 'rb') as f:
            await bot.send_video(
                chat_id=chat_id,
                video=f,
                caption=f"✅ Done! Ready for Shorts/Reels",
                supports_streaming=True
            )
        
        # Step 4: Delete files (both original + processed)
        os.remove(input_file)
        os.remove(output_file)
        print("✅ Cleanup done")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        # Try to notify user
        try:
            await bot.send_message(chat_id, f"❌ Processing failed: {str(e)[:150]}")
        except:
            pass


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
