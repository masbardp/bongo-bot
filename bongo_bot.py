import os
import re
import time
import subprocess
import logging
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("bongo-bot")

# ---------------- BONGO FUNCTIONS ----------------
def get_master_m3u8(bongo_url):
    chrome_options = Options()
    chrome_options.binary_location = os.getenv("CHROME_BIN", "/usr/bin/chromium")
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")

    driver = webdriver.Chrome(
        service=Service(os.getenv("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")),
        options=chrome_options
    )

    driver.get(bongo_url)
    time.sleep(6)

    html = driver.page_source
    driver.quit()

    match = re.search(r'https://[^\'" ]+\.m3u8', html)
    if match:
        return match.group(0)
    return None


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
    master_m3u8 = get_master_m3u8(bongo_url)
    if not master_m3u8:
        logger.error("Could not find master playlist.")
        return None

    chosen_m3u8 = choose_resolution(master_m3u8, resolution)
    if not chosen_m3u8:
        logger.error(f"Could not find a stream with resolution {resolution}.")
        return None

    cmd = [
        "ffmpeg",
        "-headers", "Referer: https://bongobd.com/",
        "-i", chosen_m3u8,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-threads", "0",
        output_path
    ]
    subprocess.run(cmd)
    return output_path if os.path.exists(output_path) else None


# ---------------- TELEGRAM HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 Send me a Bongo video link, and I’ll fetch it for you!")


async def handle_bongo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    logger.info(f"User {update.effective_user.id} sent: {url}")

    if "bongobd.com/watch/" not in url:
        await update.message.reply_text("❌ Please send a valid Bongo video URL.")
        return

    await update.message.reply_text("🔍 Fetching available stream... please wait ⏳")

    output_file = f"video_{int(time.time())}.mp4"
    resolution = "480"  # You can change this to 720, 1080, etc.

    video_path = download_video(url, output_file, resolution)

    if not video_path:
        await update.message.reply_text("❌ Could not extract video link. Try another URL or resolution.")
        return

    await update.message.reply_text("✅ Download complete! Uploading video...")

    with open(video_path, "rb") as video:
        await update.message.reply_video(video, caption="🎥 Here’s your Bongo video!")

    os.remove(video_path)
    logger.info(f"Sent video {video_path} to user {update.effective_user.id}")


# ---------------- MAIN ----------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bongo))
    logger.info("Starting Bongo Bot polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
