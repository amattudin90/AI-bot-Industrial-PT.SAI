"""Skill, laptop-control, and system utility commands."""

from bot_app.context import (
    ALLOWED_USERS,
    BATTERY_POLL_SEC_DEFAULT,
    ContextTypes,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    _battery_notify,
    diizinkan,
    logger,
    os,
    skill_manager,
)


async def cmd_skills(update, context):
    user = update.effective_user

    if not diizinkan(user.id if user else 0):
        return

    items = skill_manager.describe()

    teks = ["DAFTAR SKILL FACTORY AI", ""]

    for item in items:
        status = "AKTIF" if item["enabled"] else "NONAKTIF"
        teks.append(f"- {item['name']}: {status}")
        teks.append(f"  {item['description']}")

    poll = skill_manager.get_battery_poll_sec(BATTERY_POLL_SEC_DEFAULT)
    teks.append("")
    teks.append(f"Interval cek baterai: {poll} detik")
    teks.append("(Ubah: /skill_interval 60  |  minimal 30, maksimal 3600)")

    await update.effective_message.reply_text("\n".join(teks))

async def cmd_skill_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /skill_on <nama_skill>  — aktifkan skill """
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Pakai: /skill_on <nama>\nContoh: /skill_on battery_monitor"
        )
        return
    nama = context.args[0].strip().lower()
    if skill_manager.enable(nama):
        await update.effective_message.reply_text(f"✅ Skill '{nama}' sekarang AKTIF.")
    else:
        await update.effective_message.reply_text(
            f"❌ Skill '{nama}' tidak ditemukan.\nKirim /skills untuk daftar nama."
        )

async def cmd_skill_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /skill_off <nama_skill>  — nonaktifkan skill """
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Pakai: /skill_off <nama>\nContoh: /skill_off battery_monitor"
        )
        return
    nama = context.args[0].strip().lower()
    if skill_manager.disable(nama):
        await update.effective_message.reply_text(f"⏹️ Skill '{nama}' sekarang NONAKTIF.")
    else:
        await update.effective_message.reply_text(
            f"❌ Skill '{nama}' tidak ditemukan.\nKirim /skills untuk daftar nama."
        )

async def cmd_skill_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /skill_interval [detik] — lihat atau ubah interval poll baterai (persisted). """
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not context.args:
        poll = skill_manager.get_battery_poll_sec(BATTERY_POLL_SEC_DEFAULT)
        await update.effective_message.reply_text(
            f"Interval cek baterai sekarang: {poll} detik.\n"
            f"Ubah: /skill_interval 60"
        )
        return
    try:
        sec = int(context.args[0])
        sec = skill_manager.set_battery_poll_sec(sec)
    except ValueError as e:
        await update.effective_message.reply_text(f"❌ {e}")
        return
    jq = context.application.job_queue if context.application else None
    if jq is not None:
        for job in jq.get_jobs_by_name("battery_monitor"):
            job.schedule_removal()
        jq.run_repeating(job_cek_baterai, interval=sec, first=sec, name="battery_monitor")
        await update.effective_message.reply_text(
            f"✅ Interval baterai diubah ke {sec} detik (job dijadwal ulang)."
        )
    else:
        await update.effective_message.reply_text(
            f"✅ Interval disimpan: {sec} detik. Restart bot agar job memakai nilai baru "
            f"(job_queue tidak tersedia)."
        )

async def cmd_skill_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /skill_test battery [persen]  |  /skill_test battery   |  /skill_test lock
        Tanpa angka: baca baterai Windows asli lalu evaluasi threshold.
        Dengan angka: uji threshold manual (tanpa hardware).
        lock: cek scaffold (TIDAK mengunci; pakai /lock untuk aksi nyata). """
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Pakai:\n"
            "  /skill_test battery       → baca baterai Windows + threshold\n"
            "  /skill_test battery 8     → uji threshold manual\n"
            "  /skill_test lock          → cek skill lock (tidak mengunci)"
        )
        return

    target = context.args[0].strip().lower()

    if target in ("battery", "battery_monitor"):
        if len(context.args) >= 2:
            try:
                persen = float(context.args[1])
            except ValueError:
                await update.effective_message.reply_text("Persen harus angka, contoh: 8")
                return
            result = await skill_manager.dispatch(
                "battery_monitor", "check_threshold", {"percent": persen}
            )
        else:
            result = await skill_manager.dispatch("battery_monitor", "check_real", {})
        await update.effective_message.reply_text(
            f"{'✅' if result.ok else '❌'} {result.message}"
        )
        return

    if target in ("lock", "laptop", "laptop_control"):
        result = await skill_manager.dispatch("laptop_control", "lock", {})
        await update.effective_message.reply_text(
            f"{'✅' if result.ok else '❌'} {result.message}"
        )
        return

    await update.effective_message.reply_text(
        "Target tidak dikenal. Pakai: battery  atau  lock"
    )

async def cmd_battery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /battery — baca level baterai Windows sekarang (butuh skill AKTIF). """
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    result = await skill_manager.dispatch("battery_monitor", "read", {})
    if result.ok:
        chat_id = update.effective_message.chat_id
        skill_manager.add_notify_chat(chat_id)
        extra = ""
        if result.data.get("percent") is not None:
            check = await skill_manager.dispatch(
                "battery_monitor", "check_threshold", {"percent": result.data["percent"]}
            )
            if check.ok and check.data.get("alert"):
                extra = "\n" + check.message
        await update.effective_message.reply_text(
            f"✅ {result.message}{extra}\n"
            f"(Chat ini akan menerima notifikasi otomatis saat skill AKTIF.)"
        )
    else:
        await update.effective_message.reply_text(f"❌ {result.message}")

async def cmd_sys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /sys — status CPU/RAM/disk (skill system_monitor harus AKTIF). """
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not skill_manager.is_enabled("system_monitor"):
        await update.effective_message.reply_text(
            "Skill system_monitor NONAKTIF. Aktifkan: /skill_on system_monitor"
        )
        return
    result = await skill_manager.dispatch("system_monitor", "status", {})
    await update.effective_message.reply_text(
        f"{'✅' if result.ok else '❌'} {result.message}"
    )

async def cmd_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /screenshot — ambil layar dan kirim ke chat ini. """
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not skill_manager.is_enabled("screenshot"):
        await update.effective_message.reply_text(
            "Skill screenshot NONAKTIF. Aktifkan: /skill_on screenshot"
        )
        return
    proses = await update.effective_message.reply_text("Mengambil screenshot...")
    result = await skill_manager.dispatch("screenshot", "capture", {})
    if not result.ok:
        await proses.edit_text(f"❌ {result.message}")
        return
    path = (result.data or {}).get("path")
    try:
        with open(path, "rb") as f:
            await update.effective_message.reply_photo(photo=f, caption="📸 Screenshot")
        await proses.delete()
    except Exception as e:
        await proses.edit_text(f"❌ Gagal kirim foto: {e}")
    finally:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

async def cmd_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ /lock — minta konfirmasi sebelum mengunci sesi Windows. """
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not skill_manager.is_enabled("laptop_control"):
        await update.effective_message.reply_text(
            "Skill laptop_control masih NONAKTIF. Aktifkan dulu: /skill_on laptop_control"
        )
        return
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Ya, kunci sekarang", callback_data="lock:yes"),
            InlineKeyboardButton("❌ Batal", callback_data="lock:no"),
        ]
    ])
    await update.effective_message.reply_text(
        "🔒 Kunci sesi Windows sekarang?\n"
        "Ini akan mengunci laptop (seperti Win+L). Pastikan kamu bisa unlock lagi.",
        reply_markup=keyboard,
    )

async def tombol_lock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback konfirmasi /lock."""
    q = update.callback_query
    if not diizinkan(q.from_user.id if q.from_user else 0):
        await q.answer("Tidak diizinkan.", show_alert=True)
        return
    await q.answer()
    aksi = (q.data or "").split(":")[-1]
    if aksi != "yes":
        await q.edit_message_text("Lock dibatalkan.")
        return
    result = await skill_manager.dispatch(
        "laptop_control", "lock", {"confirm": True}
    )
    await q.edit_message_text(
        f"{'✅' if result.ok else '❌'} {result.message}"
    )

async def job_cek_baterai(context: ContextTypes.DEFAULT_TYPE):
    """Job berkala: baca baterai, kirim notifikasi jika threshold + skill AKTIF."""
    if not skill_manager.is_enabled("battery_monitor"):
        return
    chat_ids = skill_manager.notify_chat_ids()
    if not chat_ids and ALLOWED_USERS:
        chat_ids = list(ALLOWED_USERS)
    if not chat_ids:
        return

    result = await skill_manager.dispatch("battery_monitor", "check_real", {})
    if not result.ok:
        logger.warning("job baterai: %s", result.message)
        return

    state = result.data.get("state")
    percent = result.data.get("percent")
    alert = bool(result.data.get("alert"))
    _battery_notify["last_percent"] = percent

    if not alert:
        _battery_notify["last_alert_state"] = None
        return

    if _battery_notify["last_alert_state"] == state:
        return
    _battery_notify["last_alert_state"] = state

    teks = f"🔋 {result.message}"
    for cid in chat_ids:
        try:
            await context.bot.send_message(chat_id=cid, text=teks)
        except Exception as e:
            logger.warning("Gagal kirim notifikasi baterai ke %s: %s", cid, e)

