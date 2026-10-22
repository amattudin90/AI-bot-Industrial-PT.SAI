"""Task, habit, and trading-radar conversational routes."""

from bot_app.context import (
    BATTERY_KUNCI,
    ContextTypes,
    HABIT_SHEET_ID,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KATA_UMUM,
    LOCK_KUNCI,
    SCORE_ANGKA,
    SCORE_CEK,
    SCORE_KONTEKS,
    SCORE_MULAI,
    SS_KUNCI,
    SYS_KUNCI,
    TASK_SHEET_ID,
    TRADING_AUTO_KUNCI,
    TRADING_ORDER_MANUAL,
    TZ,
    Update,
    asyncio,
    config,
    date,
    datetime,
    diizinkan,
    get_google_services,
    habit,
    habit_kata,
    last_undo,
    logger,
    os,
    penasihat,
    re,
    skill_manager,
    time,
    trading_bot,
    tugas,
)

from bot_app.handlers.finance import jalankan_aksi, kirim_html, markup_dari


async def tampil_tugas(filter_, proses, sekarang):
    if not TASK_SHEET_ID:
        raise RuntimeError("TASK_SHEET_ID belum diisi di file .env")
    _, sheets_service, _ = await asyncio.to_thread(get_google_services)
    data = await asyncio.to_thread(tugas.baca_tugas, sheets_service, TASK_SHEET_ID)
    teks, tombol = tugas.kartu_tugas(data, sekarang, filter_)
    await kirim_html(proses, teks, markup_dari(tombol))

async def tampil_habit(aksi, proses, sekarang):
    if not HABIT_SHEET_ID:
        raise RuntimeError("HABIT_SHEET_ID belum diisi di file .env")
    _, sheets_service, _ = await asyncio.to_thread(get_google_services)
    tgl = sekarang.date()
    data = await asyncio.to_thread(habit.baca_habit, sheets_service, HABIT_SHEET_ID, tgl.year, tgl.month)
    if aksi == "rekap":
        await kirim_html(proses, habit.rekap_habit(data, tgl))
    else:
        teks, tombol = habit.kartu_habit(data, tgl)
        await kirim_html(proses, teks, markup_dari(tombol))

def _heartbeat_umur():
    """Umur (detik) sejak radar terakhir menulis heartbeat; None bila file belum ada."""
    path = config.data_path(config.HEARTBEAT_FILE)
    if not os.path.exists(path):
        path = config.HEARTBEAT_FILE
    try:
        return time.time() - os.path.getmtime(path)
    except OSError:
        return None

def radar_berjalan():
    umur = _heartbeat_umur()
    return umur is not None and umur < config.RADAR_INTERVAL_SEC + 20

async def _edit(proses, teks):
    try:
        await proses.edit_text(teks)
    except Exception:
        pass

async def hentikan_radar(proses, maks_tunggu=150):
    """Hentikan radar-loop lewat file radar.stop, lalu tunggu sampai heartbeat berhenti. True bila sudah berhenti."""
    stop_path = config.data_path(config.STOP_FILE)
    with open(stop_path, "w", encoding="utf-8") as f:
        f.write("stop dari Telegram\n")
    mulai = time.time()
    while time.time() - mulai < maks_tunggu:
        await asyncio.sleep(5)
        if not radar_berjalan():
            try:
                os.remove(stop_path)   # bersihkan supaya radar yang baru tidak langsung berhenti
            except OSError:
                pass
            await asyncio.sleep(2)
            return True
        await _edit(proses, f"Menghentikan radar lama... ({int(time.time() - mulai)} detik)")
    return False

async def tangani_score(teks, proses, pesan):
    """Perintah skor dari Telegram. True bila pesan sudah dijawab di sini."""
    t = teks.strip()
    if TRADING_ORDER_MANUAL.search(t):
        return False                       # order manual (buy/sell) bukan urusan skor radar
    m = SCORE_ANGKA.search(t)
    if not m:
        if t.lower().startswith("/score") or SCORE_CEK.search(t):
            skor = config.get_min_score()
            status = "berjalan" if radar_berjalan() else "tidak berjalan"
            await _edit(proses, f"Skor minimum sekarang: {skor} (batas {config.SCORE_ALLOWED_MIN}-{config.SCORE_ALLOWED_MAX}). "
                                f"Radar: {status}.\nUbah dengan: ubah score N  |  /score N")
            return True
        return False
    if not (t.lower().startswith("/score") or SCORE_KONTEKS.search(t)):
        return False
    if "?" in t:
        # pertanyaan, bukan perintah: jangan ubah apa pun
        await _edit(proses, f"Skor minimum sekarang {config.get_min_score()}. Itu terbaca sebagai pertanyaan, jadi belum saya ubah. "
                            f"Untuk mengubah kirim: ubah score {m.group(1)}  (atau /score {m.group(1)}).")
        return True
    skor = int(m.group(1))
    try:
        config.set_min_score(skor)
    except ValueError as e:
        await _edit(proses, str(e))
        return True

    catatan = f"Skor minimum diubah ke {skor}."
    if skor < config.SCORE_WARN_BELOW:
        catatan += f" Hati-hati: skor di bawah {config.SCORE_WARN_BELOW} membuat setup lebih banyak tapi kualitasnya turun."
    sedang_jalan = radar_berjalan()
    mulai = bool(SCORE_MULAI.search(t))
    if not sedang_jalan and not mulai:
        await _edit(proses, catatan + " Radar sedang tidak berjalan; kirim 'jalankan trading' untuk menyalakannya dengan skor ini.")
        return True

    uid = pesan.from_user.id if pesan.from_user else 0
    if sedang_jalan:
        await _edit(proses, catatan + " Radar sedang berjalan, saya restart supaya memakai skor baru...")
        if not await hentikan_radar(proses):
            await _edit(proses, catatan + " Radar lama belum berhenti dalam 150 detik. Kirim /auto off, tunggu berhenti, "
                                          f"lalu 'jalankan trading score {skor}'.")
            return True
    rute = trading_bot.rute_teks(f"jalankan otomatis trading dengan score {skor}")
    if not rute:
        await _edit(proses, catatan + " Tapi perintah radar otomatis belum dikenali trading_bot.py. Pakai /auto lalu cek 'radar status'.")
        return True
    await trading_bot.jalankan_rute(rute, proses, uid)
    return True

async def jalankan_rute_lokal(teks, proses, pesan):
    """Jawab langsung dari hitungan program (tanpa Gemini) kalau pesan meminta fitur lokal. True kalau sudah dijawab."""
    if await tangani_score(teks, proses, pesan):
        return True
    teks_tr = teks
    if TRADING_AUTO_KUNCI.search(teks) and not TRADING_ORDER_MANUAL.search(teks):
        # "jalankan trading" -> samakan ke perintah radar otomatis dengan score (default dari .env, atau score yang disebut user)
        m_score = re.search(r"score\s*(\d+)", teks, re.I)
        score = int(m_score.group(1)) if m_score else config.get_min_score()
        teks_tr = f"jalankan otomatis trading dengan score {score}"
    rute_tr = trading_bot.rute_teks(teks_tr)  # dicek lebih dulu supaya "status trading" tidak ditangkap kartu keuangan
    if not rute_tr and teks_tr != teks:
        # Perintah dikenali sebagai "jalankan trading" tapi trading_bot belum punya rute otomatisnya: jangan lempar ke Gemini.
        await proses.edit_text("Perintah jalankan trading terbaca, tapi radar otomatis belum tersambung di trading_bot.py. "
                               "Sementara pakai /radar, atau sambungkan rute_teks di trading_bot.py.")
        return True
    if rute_tr:
        await trading_bot.jalankan_rute(rute_tr, proses, pesan.from_user.id if pesan.from_user else 0)
        return True
    rute = penasihat.rute_teks(teks)
    if rute:
        await jalankan_aksi(rute[0], rute[1], proses, pesan)
        return True
    filter_tugas = tugas.rute_teks(teks)
    if filter_tugas:
        await tampil_tugas(filter_tugas, proses, datetime.now(TZ))
        return True
    aksi_habit = habit.rute_teks(teks)
    if aksi_habit:
        await tampil_habit(aksi_habit, proses, datetime.now(TZ))
        return True
    # kunci laptop (teks) → konfirmasi sama seperti /lock
    if LOCK_KUNCI.search(teks):
        if not skill_manager.is_enabled("laptop_control"):
            await proses.edit_text(
                "Skill laptop_control NONAKTIF. Aktifkan: /skill_on laptop_control"
            )
            return True
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Ya, kunci sekarang", callback_data="lock:yes"),
                InlineKeyboardButton("❌ Batal", callback_data="lock:no"),
            ]
        ])
        await proses.edit_text(
            "🔒 Kunci sesi Windows sekarang?\n"
            "Ini akan mengunci laptop (seperti Win+L). Pastikan kamu bisa unlock lagi.",
            reply_markup=keyboard,
        )
        return True

    if SYS_KUNCI.search(teks):
        if not skill_manager.is_enabled("system_monitor"):
            await proses.edit_text(
                "Skill system_monitor NONAKTIF. Aktifkan: /skill_on system_monitor"
            )
            return True
        result = await skill_manager.dispatch("system_monitor", "status", {})
        flag = "✅" if result.ok else "❌"
        await proses.edit_text(f"{flag} {result.message}")
        return True

    if SS_KUNCI.search(teks):
        if not skill_manager.is_enabled("screenshot"):
            await proses.edit_text(
                "Skill screenshot NONAKTIF. Aktifkan: /skill_on screenshot"
            )
            return True
        await proses.edit_text("Mengambil screenshot...")
        result = await skill_manager.dispatch("screenshot", "capture", {})
        if not result.ok:
            await proses.edit_text(f"❌ {result.message}")
            return True
        path = (result.data or {}).get("path")
        try:
            with open(path, "rb") as f:
                await pesan.reply_photo(photo=f, caption="📸 Screenshot")
            await proses.delete()
        except Exception as e:
            await proses.edit_text(f"❌ Gagal kirim foto: {e}")
        finally:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        return True

    # skill baterai lewat teks biasa (cek baterai / status baterai)
    if BATTERY_KUNCI.search(teks):
        if not skill_manager.is_enabled("battery_monitor"):
            await proses.edit_text(
                "Skill battery_monitor masih NONAKTIF. Aktifkan: /skill_on battery_monitor"
            )
            return True
        result = await skill_manager.dispatch("battery_monitor", "check_real", {})
        if result.ok:
            chat_id = pesan.chat_id if pesan else None
            if chat_id is not None:
                skill_manager.add_notify_chat(chat_id)
            await proses.edit_text(f"✅ {result.message}")
        else:
            await proses.edit_text(f"❌ {result.message}")
        return True

    return False

async def tombol_tugas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not diizinkan(q.from_user.id):
        await q.answer("Tidak diizinkan.", show_alert=True)
        return
    await q.answer()
    try:
        _, baris, crc = q.data.split(":")
        _, sheets_service, _ = await asyncio.to_thread(get_google_services)
        nama, restore = await asyncio.to_thread(tugas.selesaikan_tugas, sheets_service, TASK_SHEET_ID, int(baris), crc)
        last_undo[q.message.chat_id] = {"jenis": "pulih", "sheet_id": TASK_SHEET_ID, "data": restore,
                                        "label": f"Penyelesaian tugas '{nama}'"}
        data = await asyncio.to_thread(tugas.baca_tugas, sheets_service, TASK_SHEET_ID)
        teks, tombol = tugas.kartu_tugas(data, datetime.now(TZ))
        await kirim_html(q.message, teks, markup_dari(tombol))
        await q.message.reply_text(f"✅ Selesai: {nama}\nSalah tekan? Kirim /undo")
    except Exception as e:
        logger.exception("Gagal tombol tugas")
        await q.message.reply_text(f"Gagal menandai selesai: {e}")

async def tombol_habit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not diizinkan(q.from_user.id):
        await q.answer("Tidak diizinkan.", show_alert=True)
        return
    try:
        _, baris, ymd = q.data.split(":")
        _, sheets_service, _ = await asyncio.to_thread(get_google_services)
        nama, baru, restore = await asyncio.to_thread(habit.toggle_habit, sheets_service, HABIT_SHEET_ID, int(baris), ymd)
        last_undo[q.message.chat_id] = {"jenis": "pulih", "sheet_id": HABIT_SHEET_ID, "data": restore,
                                        "label": f"Centang habit '{nama}'"}
        tgl = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
        data = await asyncio.to_thread(habit.baca_habit, sheets_service, HABIT_SHEET_ID, tgl.year, tgl.month)
        teks, tombol = habit.kartu_habit(data, tgl)
        await kirim_html(q.message, teks, markup_dari(tombol))
        await q.answer(f"{'✅' if baru else '⬜'} {nama}")
    except Exception as e:
        logger.exception("Gagal tombol habit")
        await q.answer(f"Gagal: {e}"[:190], show_alert=True)

def kata_habit_cache(sheets_service, sekarang):
    """Kata-kata dari nama habit (diperbarui tiap 10 menit) untuk mendeteksi pesan yang membahas habit."""
    if time.time() - habit_kata["ts"] > 600:
        try:
            tgl = sekarang.date()
            data = habit.baca_habit(sheets_service, HABIT_SHEET_ID, tgl.year, tgl.month)
            habit_kata["kata"] = habit.kata_habit(data) - KATA_UMUM
        except Exception as e:
            logger.warning("Gagal memuat nama habit: %s", e)
        habit_kata["ts"] = time.time()
    return habit_kata["kata"]

