# bongo_bot.py
import os
import time
import tempfile
import shutil
import logging
import yt_dlp
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# ---------- Config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN missing! Set it in Render environment variables.")

# max file size to send (bytes) — Telegram bots commonly limited (50-200MB depending)
MAX_UPLOAD_BYTES = 190 * 1024 * 1024  # 190 MB to be safe

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bongo-bot")

# ---------- Helpers using yt-dlp ----------
def list_formats(url):
    """
    Return a list of (label, format_id, filesize) sorted by resolution desc.
    filesize may be None.
    """
    ydl_opts = {"quiet": True, "skip_download": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        log.exception("yt-dlp extract_info failed")
        return []

    formats = []
    for f in info.get("formats", []):
        # skip audio-only formats
        if f.get("vcodec") == "none":
            continue
        height = f.get("height") or 0
        fmt_id = f.get("format_id")
        # size estimate: use filesize if available
        filesize = f.get("filesize") or f.get("filesize_approx")
        label = f"{height}p" if height else (f.get("format_note") or f.get("ext"))
        formats.append((label, fmt_id, filesize, height))

    # remove duplicates by label keeping highest height
    seen = {}
    for label, fid, sz, h in formats:
        if label not in seen or h > seen[label][3]:
            seen[label] = (label, fid, sz, h)
    uniq = list(seen.values())
    # sort by height desc (so highest resolution first)
    uniq.sort(key=lambda x: x[3] or 0, reverse=True)
    return uniq

def download_with_ytdlp(url, format_id, out_path):
    """
    Download using yt-dlp into out_path (filename).
    Returns True on success.
    """
    ydl_opts = {
        "format": format_id,
        "outtmpl": out_path,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 10,
        "continuedl": True,
        "concurrent_fragment_downloads": 16,  # speed up HLS/dash fragments
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception:
        log.exception("yt-dlp download failed")
        return False

# ---------- Bot handlers ----------
user_state = {}  # user_id -> {"url":..., "formats":[...]}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send me a Bongo (or other) video URL and I'll list qualities for you.")

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    if not url or not url.startswith("http"):
        await update.message.reply_text("⚠️ Please send a valid video link (starting with http...).")
        return

    log.info("User %s requested url: %s", update.effective_user.id, url)
    msg = await update.message.reply_text("🔍 Fetching available resolutions, please wait...")

    formats = list_formats(url)
    if not formats:
        await msg.edit_text("❌ No playable video formats found or link invalid.")
        return

    # Save user state
    user_state[update.effective_user.id] = {"url": url, "formats": formats}

    # Build keyboard with top 6 formats
    buttons = []
    for label, fid, sz, h in formats[:8]:
        display = label
        if sz:
            display += f" ({round(sz/1024/1024,1)}MB)"
        buttons.append([InlineKeyboardButton(display, callback_data=fid)])

    reply_markup = InlineKeyboardMarkup(buttons)
    await msg.edit_text("🎚 Choose a resolution to download:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    state = user_state.get(user_id)
    if not state:
        await query.edit_message_text("⚠️ Please send a video link first.")
        return

    fid = query.data
    url = state["url"]
    label = next((lbl for lbl, f, s, h in state["formats"] if f == fid), fid)
    await query.edit_message_text(f"⬇️ Downloading {label} — this may take a while...")

    # prepare temp file
    tmpdir = tempfile.mkdtemp(prefix="bongobot_")
    out_file = os.path.join(tmpdir, "video.%(ext)s")  # yt-dlp will replace ext
    log.info("Downloading %s format %s to %s", url, fid, out_file)

    ok = download_with_ytdlp(url, fid, out_file)
    # find downloaded file
    downloaded = None
    if ok:
        # find a file in tmpdir
        files = list(Path(tmpdir).iterdir())
        if files:
            downloaded = str(files[0])
            log.info("Downloaded file path: %s", downloaded)

    if not downloaded or not os.path.exists(downloaded):
        await query.message.reply_text("❌ Download failed.")
        shutil.rmtree(tmpdir, ignore_errors=True)
        return

    size = os.path.getsize(downloaded)
    log.info("Downloaded size: %d bytes", size)
    if size > MAX_UPLOAD_BYTES:
        await query.message.reply_text(
            f"⚠️ Downloaded file is too large to send via Telegram ({round(size/1024/1024,1)} MB)."
        )
        # optionally: upload to external host / provide link — skipped here
        shutil.rmtree(tmpdir, ignore_errors=True)
        return

    # send video (as document if large or to preserve quality)
    try:
        with open(downloaded, "rb") as f:
            await query.message.reply_video(video=f)
        await query.message.reply_text("✅ Done — enjoy!")
    except Exception:
        log.exception("Failed to send file")
        await query.message.reply_text("❌ Failed to send the video.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is running.")

# ---------- Run ----------
def main():
    log.info("Starting Bongo Bot")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(button))
    # Polling mode (Render recommended)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
