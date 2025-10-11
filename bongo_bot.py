from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ApplicationBuilder, ContextTypes
from bongo_downloader import download_video  # import the above file

async def handle_bongo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if "bongobd.com" not in url:
        await update.message.reply_text("⚠️ Please send a valid BongoBD video link.")
        return

    await update.message.reply_text("🔍 Fetching available resolutions…")
    success = download_video(url, "bongo_video.mp4", "720")

    if success:
        await update.message.reply_video(open("bongo_video.mp4", "rb"))
    else:
        await update.message.reply_text("❌ Could not process this link.")
