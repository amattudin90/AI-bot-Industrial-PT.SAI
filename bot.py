import asyncio
import os
import re
import uuid
from pathlib import Path
from dotenv import load_dotenv  # <-- Tambahkan import ini

# Muat variabel environment dari file .env
load_dotenv() 

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
...
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, CallbackQueryHandler, filters
)
from google import genai

from core.config import *
from core.ai_engine import AIEngine
from core.data_engine import FactoryData
from core.database import add_message, get_history, log_activity
from core.workflow import parse_calendar_action, clean_kaizen, split_telegram
from integrations.google_services import get_google_services, save_text_to_drive, append_sheet, create_calendar_event

TEMP_DIR = Path(DATA_DIR) / "temp_media"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

ai = AIEngine()
pending_calendar = {}

def allowed(user_id):
    return not TELEGRAM_ALLOWED_USERS or user_id in TELEGRAM_ALLOWED_USERS

def load_factory():
    engine = FactoryData()
    v1 = Path(DATA_DIR) / V1_FILE
    v2 = Path(DATA_DIR) / V2_FILE
    engine.load(str(v1) if v1.exists() else None, str(v2) if v2.exists() else None)
    return engine

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "🏭 Factory AI Operations System\n\n"
        "Saya siap membantu Capacity, IE, Lean, Kaizen, machine planning, "
        "analisis Excel/PDF/media, dan workflow Google.\n\n"
        "Commands: /help /status"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "Contoh:\n"
        "• Analisis shortage minggu ini\n"
        "• Berapa risiko capacity model 608?\n"
        "• Buat analisis Kaizen dari foto ini\n"
        "• Jadwalkan Gemba walk besok jam 09:00\n"
        "• Kirim Excel ini dan analisis bottleneck-nya"
    )

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user.id):
        return
    f = load_factory()
    m = f.metrics()
    await update.message.reply_text(
        f"🟢 AI: {'READY' if ai.active else 'OFFLINE'}\n"
        f"V1 processes: {m['v1_processes']}\n"
        f"V2 rows: {m['v2_rows']}\n"
        f"Shortage rows: {m['shortage_rows']}\n"
        f"Model: {ai.model}"
    )

async def process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or not allowed(user.id):
        return

    user_id = str(user.id)
    caption = msg.caption or msg.text or "Analisis file/media ini."
    await msg.reply_text("⚙️ Factory AI sedang memproses...")

    local_path = None
    try:
        contents = [caption]
        unique = uuid.uuid4().hex

        if msg.document:
            file = await msg.document.get_file()
            name = Path(msg.document.file_name or "document.bin").name
            local_path = TEMP_DIR / f"{unique}_{name}"
            await file.download_to_drive(str(local_path))
            contents = [f"File lokal tersedia: {local_path}\n{caption}"]
        elif msg.photo:
            file = await msg.photo[-1].get_file()
            local_path = TEMP_DIR / f"{unique}.jpg"
            await file.download_to_drive(str(local_path))
            contents = [f"Photo lokal tersedia: {local_path}\n{caption}"]
        elif msg.video:
            file = await msg.video.get_file()
            local_path = TEMP_DIR / f"{unique}.mp4"
            await file.download_to_drive(str(local_path))
            contents = [f"Video lokal tersedia: {local_path}\n{caption}"]
        elif msg.voice or msg.audio:
            media = msg.voice or msg.audio
            file = await media.get_file()
            local_path = TEMP_DIR / f"{unique}.ogg"
            await file.download_to_drive(str(local_path))
            contents = [f"Audio lokal tersedia: {local_path}\n{caption}"]

        # Upload the original Telegram file to Gemini so the AI can inspect
        # the actual content, not merely the local filename.
        if local_path and local_path.exists():
            try:
                uploaded = ai.client.files.upload(file=str(local_path))
                contents = [uploaded]
            except Exception as upload_exc:
                log_activity("telegram", user_id, "FILE_UPLOAD", "FAILED", str(upload_exc))
                contents = []

        factory = load_factory()
        history = get_history("telegram", user_id, 8)
        prompt = caption + "\n\nIMPORTANT: If this is a file/media, analyze the attached content first."

        answer = ai.ask(
            prompt, factory.compact_context(), history,
            {"gross_hours":"Telegram session","working_days":"Telegram session",
             "downtime":"Use loaded factory parameters if available","allowance":"Use loaded factory parameters if available"},
            contents=contents if local_path else None
        )

        add_message("telegram", user_id, "user", caption)
        add_message("telegram", user_id, "assistant", answer)

        calendar_data, clean_answer = parse_calendar_action(answer)
        if calendar_data:
            pending_calendar[user_id] = calendar_data
            keyboard = [[
                InlineKeyboardButton("✅ CONFIRM SCHEDULE", callback_data="calendar_confirm"),
                InlineKeyboardButton("❌ CANCEL", callback_data="calendar_cancel")
            ]]
            clean_answer += (
                "\n\n📅 *Draft jadwal siap.*\n"
                f"*{calendar_data['summary']}*\n"
                f"{calendar_data['start_time']} → {calendar_data['end_time']}\n"
                "Tekan CONFIRM untuk membuat event."
            )
            await msg.reply_text(clean_answer, parse_mode="Markdown",
                                 reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if "[DOKUMEN KAIZEN]" in answer:
            clean_answer = clean_kaizen(answer)
            try:
                drive, sheets, _ = get_google_services()
                name = f"Laporan_KAIZEN_{uuid.uuid4().hex[:8]}"
                _, link = save_text_to_drive(drive, clean_answer, name + ".txt")
                append_sheet(sheets, [user_id, "KAIZEN", name, "SUCCESS"])
                clean_answer += f"\n\n📁 Drive: {link or name}"
                log_activity("telegram", user_id, "KAIZEN_SAVE", "SUCCESS", name)
            except Exception as exc:
                clean_answer += f"\n\n⚠️ Google workflow gagal: {exc}"
                log_activity("telegram", user_id, "KAIZEN_SAVE", "FAILED", str(exc))

        for chunk in split_telegram(clean_answer):
            try:
                await msg.reply_text(chunk, parse_mode="Markdown")
            except BadRequest:
                await msg.reply_text(chunk)
        log_activity("telegram", user_id, "AI_QUERY", "SUCCESS", caption)

    except Exception as exc:
        log_activity("telegram", user_id, "AI_QUERY", "FAILED", str(exc))
        await msg.reply_text(f"❌ Terjadi error: {exc}")
    finally:
        if local_path and local_path.exists():
            try: local_path.unlink()
            except OSError: pass

async def calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    if not allowed(query.from_user.id):
        return

    data = pending_calendar.pop(user_id, None)
    if query.data == "calendar_cancel":
        await query.edit_message_text("❌ Jadwal dibatalkan.")
        log_activity("telegram", user_id, "CALENDAR", "CANCELLED", "")
        return

    if not data:
        await query.edit_message_text("⚠️ Draft jadwal sudah tidak tersedia.")
        return

    try:
        _, _, calendar = get_google_services()
        event = create_calendar_event(calendar, data)
        link = event.get("htmlLink", "")
        await query.edit_message_text(f"✅ Jadwal berhasil dibuat.\n{link}")
        log_activity("telegram", user_id, "CALENDAR", "SUCCESS", data["summary"])
    except Exception as exc:
        await query.edit_message_text(f"❌ Gagal membuat kalender: {exc}")
        log_activity("telegram", user_id, "CALENDAR", "FAILED", str(exc))

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum tersedia.")
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(calendar_callback))
    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO | filters.TEXT | filters.VOICE |
         filters.AUDIO | filters.Document.ALL) & ~filters.COMMAND,
        process
    ))
    print(f"Factory AI Telegram {APP_VERSION} running...")
    app.run_polling()

if __name__ == "__main__":
    main()
