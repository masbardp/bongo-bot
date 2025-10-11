import os
import re
import time
import subprocess
import tempfile
import requests
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


# ===================== CONFIG ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN missing! Add it in Render Environment Variables.")
# ===================================================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bongo-bot")

# ===================================================
# Core scraping logic (your working version)
# ===================================================

def get_master_m3u8(bongo_url):
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--log-level=3")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.get(bongo_url)
    time.sleep(5)
    html = driver.page_source
    driver.quit()

    match = re.search(r'https://[^\'" ]+\.m3u8', html)
    return match.group(0) if match else None


def choose_resolution(master_url, resolution):
    r = requests.get(master_url, headers={"Referer": "https://bongobd.com/"})
    lines = r.text.splitlines()
    for line in lines:
        if resolution in line and line.endswith(".m3u8"):
            if not line.startswith("http"):
                base = "/".join(master_url.split("/")[:-1])
                return base + "/" + line
            return line
    return None


def download_video(bongo_url, output_path, resolution):
    log.info("🔍 Loading Bongo page and finding master playlist...")
    master_m3u8 = get_master_m3u8(bongo_url)
    if not master_m3u8:
        log.error("❌ Could not find master playlist.")
        return False

    log.info(f"✅ Master playlist found: {master_m3u8}")
    chosen_m3u8 = choose_resolution(master_m3u8, resolution)
    if not chosen_m3u8:
        log.error(f"❌ Could not find a stream with resolution {resolution}.")
        return False

    log.info(f"🎬 Downloading {resolution} stream: {chosen_m3u8}")
    cmd = [
        "ffmpeg",
        "-headers", "Referer: https://bongobd.com/",
        "-i", chosen_m3u8,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-threads", "0",
        output_path,
    ]
    subprocess.run(cmd)
    return os.path.exists(output_path)


# ===================================================
# Telegram Bot Handlers
# ===================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a BongoBD link and I’ll fetch available resolutions!")


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if "bongobd.com/watch" not in url:
        await update.message.reply_text("❌ Please send a valid BongoBD video link.")
        return

    await update.message.reply_text("🔍 Fetching available resolutions… please wait ⏳")

    master = get_master_m3u8(url)
    if not master:
        await update.message.reply_text("❌ Could not detect a video link or master playlist.")
        return

    # Find all resolutions in master.m3u8
    r = requests.get(master, headers={"Referer": "https://bongobd.com/"})
    lines = r.text.splitlines()
    resolutions = [l.split("x")[-1].replace(",", "") + "p" for l in lines if "RESOLUTION=" in l]
    resolutions = list(set(resolutions)) or ["360p", "480p", "720p"]

    keyboard = [
        [InlineKeyboardButton(res, callback_data=f"{url}|{res}")] for res in resolutions
    ]
    await update.message.reply_text(
        "🎞 Choose resolution:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def resolution_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")
    url, res = data[0], data[1]
    await query.edit_message_text(f"🎬 Downloading {res}… Please wait.")

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        success = download_video(url, tmp.name, res)
        if not success:
            await query.edit_message_text("❌ Failed to download the video.")
            return

        await query.edit_message_text("✅ Uploading to Telegram…")
        await query.message.reply_video(video=open(tmp.name, "rb"), caption=f"{res} Video")
        os.remove(tmp.name)


# ===================================================
# Bot Start
# ===================================================

def main():
    log.info("🚀 Starting Bongo Bot polling...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(resolution_callback))
    app.run_polling()


if __name__ == "__main__":
    main()
