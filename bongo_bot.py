import os, time, subprocess, json, shutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ✅ Load token from Render environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8443))

if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN missing! Please set it in Render Environment Variables.")

# store user choices temporarily
user_links = {}

# ---------- yt-dlp helpers ----------
def get_formats(url):
    """Return available resolutions using yt-dlp."""
    cmd = ["yt-dlp", "-F", url, "--dump-json"]
    try:
        result = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        data = json.loads(result)
        formats = []
        for f in data.get("formats", []):
            if f.get("vcodec") != "none" and f.get("height"):
                label = f"{f['height']}p"
                formats.append((label, f["format_id"]))
        unique = list({r[0]: r for r in formats}.values())
        return sorted(unique, key=lambda x: int(x[0][:-1]), reverse=True)
    except Exception:
        return []

def download_video(url, fmt, output_path):
    """Download chosen format."""
    cmd = [
        "yt-dlp", "-f", fmt,
        "-N", "16",
        "-o", output_path,
        url
    ]
    subprocess.run(cmd)

# ---------- Telegram handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a Bongo video link to begin.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.startswith("http"):
        await update.message.reply_text("⚠️ Please send a valid link.")
        return

    await update.message.reply_text("🔍 Fetching available resolutions…")
    formats = get_formats(url)
    if not formats:
        await update.message.reply_text("❌ No resolutions found or link invalid.")
        return

    user_links[update.effective_user.id] = (url, formats)

    keyboard = [
        [InlineKeyboardButton(res[0], callback_data=res[1])] for res in formats
    ]
    await update.message.reply_text(
        "🎚️ Choose a resolution:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fmt = query.data
    user_id = query.from_user.id
    if user_id not in user_links:
        await query.edit_message_text("⚠️ Send a video link first.")
        return

    url, formats = user_links[user_id]
    label = next((r[0] for r in formats if r[1] == fmt), fmt)
    output_file = f"bongo_{int(time.time())}.mp4"

    await query.edit_message_text(f"⬇️ Downloading {label}… please wait.")
    download_video(url, fmt, output_file)

    if os.path.exists(output_file):
        await query.message.reply_video(video=open(output_file, "rb"))
        os.remove(output_file)
    else:
        await query.message.reply_text("❌ Download failed.")

# ---------- Run bot ----------
def main():
    print("🔍 Starting Bongo Bot with token:", BOT_TOKEN[:10] + "…")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{os.getenv('RENDER_EXTERNAL_URL')}/{BOT_TOKEN}"
    )

if __name__ == "__main__":
    main()

