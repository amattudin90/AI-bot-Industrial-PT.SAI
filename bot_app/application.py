"""Build and run the Telegram bot application."""

from bot_app.context import (
    ALLOWED_USERS,
    ApplicationBuilder,
    BATTERY_POLL_SEC_DEFAULT,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TELEGRAM_BOT_TOKEN,
    filters,
    profil,
    skill_manager,
    trading_bot,
)
from bot_app.handlers.skills import cmd_battery, cmd_lock, cmd_screenshot, cmd_skill_interval, cmd_skill_off, cmd_skill_on, cmd_skill_test, cmd_skills, cmd_sys, job_cek_baterai, tombol_lock
from bot_app.handlers.finance import cmd_namai, cmd_panggil, tombol_aksi, undo_transaksi
from bot_app.handlers.tasks import tombol_habit, tombol_tugas
from bot_app.handlers.messages import error_handler, handle_media_or_text


def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(trading_bot.post_init).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("skill_on", cmd_skill_on))
    app.add_handler(CommandHandler("skill_off", cmd_skill_off))
    app.add_handler(CommandHandler("skill_test", cmd_skill_test))
    app.add_handler(CommandHandler("skill_interval", cmd_skill_interval))
    app.add_handler(CommandHandler("battery", cmd_battery))
    app.add_handler(CommandHandler("sys", cmd_sys))
    app.add_handler(CommandHandler("screenshot", cmd_screenshot))
    app.add_handler(CommandHandler("lock", cmd_lock))
    app.add_handler(CommandHandler("undo", undo_transaksi))
    app.add_handler(CommandHandler("namai", cmd_namai))
    app.add_handler(CommandHandler("panggil", cmd_panggil))
    trading_bot.daftar(app, ALLOWED_USERS)  # /trading /akun /posisi /radar /scan /buy /sell /tutup + tombol konfirmasi
    app.add_handler(CommandHandler(["kondisi", "status", "tugas", "habit", "rekaphabit", "score"], handle_media_or_text))
    app.add_handler(CallbackQueryHandler(tombol_lock, pattern=r"^lock:"))
    app.add_handler(CallbackQueryHandler(tombol_aksi, pattern=r"^aksi:"))
    app.add_handler(CallbackQueryHandler(tombol_tugas, pattern=r"^td:"))
    app.add_handler(CallbackQueryHandler(tombol_habit, pattern=r"^hb:"))
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO | filters.TEXT | filters.Document.ALL) & ~filters.COMMAND, handle_media_or_text))
    # job baterai: interval dari state/env; notifikasi hanya saat skill AKTIF
    poll_sec = skill_manager.get_battery_poll_sec(BATTERY_POLL_SEC_DEFAULT)
    if app.job_queue is not None:
        app.job_queue.run_repeating(job_cek_baterai, interval=poll_sec, first=30, name="battery_monitor")
        print(f"Job baterai aktif (tiap {poll_sec}s, hanya saat skill AKTIF).")
    else:
        print('PERINGATAN: job_queue tidak tersedia. Install: pip install "python-telegram-bot[job-queue]"')
    for item in skill_manager.describe():
        st = "AKTIF" if item["enabled"] else "NONAKTIF"
        print(f"  skill {item['name']}: {st}")
    if not ALLOWED_USERS:
        print("PERINGATAN: TELEGRAM_ALLOWED_USERS kosong, siapa pun yang menemukan bot ini bisa memakainya.")
    print(f"{profil.nama()} (Keuangan + Tugas + Habit + Trading MT5 + Skills) berjalan, siap melayani {profil.panggil()}...")
    app.run_polling()


if __name__ == "__main__":
    main()
