"""Main text/media message routing and error handling."""

from bot_app.context import (
    ANALISIS_KUNCI,
    BUDGET_SHEET_ID,
    BadRequest,
    ContextTypes,
    GEMINI_MODEL,
    HABIT_KUNCI,
    HABIT_SHEET_ID,
    TASK_SHEET_ID,
    TEMP_DIR,
    TRADING_KUNCI,
    TUGAS_KUNCI,
    TZ,
    Update,
    asyncio,
    baca_dari_sheets,
    buat_jadwal_kalender,
    catat_ke_sheets,
    chat_sessions,
    client,
    datetime,
    diizinkan,
    get_google_services,
    habit,
    instruksi_lengkap,
    json,
    keuangan,
    last_undo,
    logger,
    os,
    profil,
    re,
    sheetutil,
    simpan_ke_drive,
    time,
    trading_bot,
    tugas,
    types,
    uuid,
)

from bot_app.handlers.finance import kirim_dengan_retry, wait_for_file_active

from bot_app.handlers.tasks import jalankan_rute_lokal, kata_habit_cache


async def handle_media_or_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    chat_id = message.chat_id
    user_caption = message.caption or message.text or "Analisis ini."
    ada_media = bool(message.photo or message.video or message.document)
    minta_analisis = (not ada_media) and bool(ANALISIS_KUNCI.search(user_caption))
    processing_msg = await message.reply_text(f"Siap {profil.panggil()}, sedang diproses...")

    # Fitur penasihat keuangan (kartu status, budget, simulasi, dll) dijawab langsung dari hitungan program.
    if not ada_media:
        try:
            if await jalankan_rute_lokal(user_caption, processing_msg, message):
                return
        except Exception as e:
            logger.exception("Gagal aksi lokal")
            await processing_msg.edit_text(f"Terjadi kesalahan: {str(e)}")
            return
    file_path = None

    try:
        drive_service, sheets_service, calendar_service = get_google_services()
        sekarang = datetime.now(TZ)

        # INJEKSI DATA HISTORIS + KEUANGAN KE DALAM OTAK AI
        data_historis = await asyncio.to_thread(baca_dari_sheets, sheets_service)
        ringkasan_keuangan, daftar_kategori = await asyncio.to_thread(
            keuangan.konteks_keuangan, sheets_service, BUDGET_SHEET_ID, sekarang)
        blok_analisis = ""
        if minta_analisis:
            analisis = await asyncio.to_thread(keuangan.analisis_keuangan, sheets_service, BUDGET_SHEET_ID, sekarang)
            blok_analisis = f"\n\n[ANALISIS KEUANGAN (sudah dihitung program, jangan dihitung ulang)]:\n{analisis}"
        blok_tugas = blok_habit = ""
        if not ada_media and TASK_SHEET_ID and TUGAS_KUNCI.search(user_caption):
            konteks = await asyncio.to_thread(tugas.konteks_tugas, sheets_service, TASK_SHEET_ID, sekarang)
            blok_tugas = f"\n\n[OPSI & DAFTAR TUGAS]:\n{konteks}"
        if not ada_media and HABIT_SHEET_ID:
            kata = await asyncio.to_thread(kata_habit_cache, sheets_service, sekarang)
            if HABIT_KUNCI.search(user_caption) or (kata & set(re.findall(r"[a-z0-9]{4,}", user_caption.lower()))):
                konteks = await asyncio.to_thread(habit.konteks_habit, sheets_service, HABIT_SHEET_ID, sekarang)
                blok_habit = f"\n\n[DAFTAR HABIT]:\n{konteks}"
        blok_trading = ""
        if not ada_media and TRADING_KUNCI.search(user_caption):
            blok_trading = f"\n\n[DAFTAR SYMBOL TRADING]:\n{trading_bot.daftar_symbol()}"
        konteks_tambahan = (
            f"\n\n[INFO INTERNAL DATABASE (10 Log Terakhir)]:\n{data_historis}"
            f"\n\n[RINGKASAN KEUANGAN BULAN INI]:\n{ringkasan_keuangan}"
            f"\n\n[DAFTAR KATEGORI BULAN INI (per grup/Type)]:\n{daftar_kategori}"
            f"{blok_analisis}{blok_tugas}{blok_habit}{blok_trading}"
            f"\n\n[KONTEKS WAKTU]: Hari ini {sekarang.strftime('%Y-%m-%d %H:%M (%A)')}, zona Asia/Jakarta."
        )
        payload_text = user_caption + konteks_tambahan
        contents_payload = [payload_text]
        unique_id = uuid.uuid4().hex

        if message.photo:
            file_path = os.path.join(TEMP_DIR, f"{unique_id}.jpg")
            await (await message.photo[-1].get_file()).download_to_drive(file_path)
            contents_payload = [client.files.upload(file=file_path), payload_text]
        elif message.video:
            file_path = os.path.join(TEMP_DIR, f"{unique_id}.mp4")
            await (await message.video.get_file()).download_to_drive(file_path)
            contents_payload = [wait_for_file_active(client.files.upload(file=file_path)), payload_text]
        elif message.document:
            file_path = os.path.join(TEMP_DIR, f"{unique_id}.pdf")
            await (await message.document.get_file()).download_to_drive(file_path)
            contents_payload = [wait_for_file_active(client.files.upload(file=file_path)), "Tolong ringkas dokumen ini. " + payload_text]

        if chat_id not in chat_sessions:
            chat_sessions[chat_id] = client.chats.create(model=GEMINI_MODEL, config=types.GenerateContentConfig(system_instruction=instruksi_lengkap()))

        respons = await asyncio.to_thread(kirim_dengan_retry, chat_sessions[chat_id], contents_payload)
        result_text = respons.text or "Maaf, mesin belum merespons."
        status_tambahan = ""

        if "[DOKUMEN KAIZEN]" in result_text:
            nama = f"Laporan_{time.strftime('%Y%m%d_%H%M')}"
            bersih = result_text.replace("[DOKUMEN KAIZEN]", "").strip()
            simpan_ke_drive(drive_service, bersih, nama)
            catat_ke_sheets(sheets_service, time.strftime('%Y-%m-%d %H:%M'), f"Kaizen: {nama}", "Selesai")
            status_tambahan += f"\n\n📁 Tersimpan & Dicatat: {nama}"
            result_text = bersih

        if "[JADWALKAN_KALENDER]" in result_text:
            parts = result_text.split("[JADWALKAN_KALENDER]")
            jadwal = json.loads(parts[1].strip())
            link = buat_jadwal_kalender(calendar_service, jadwal)
            catat_ke_sheets(sheets_service, time.strftime('%Y-%m-%d %H:%M'), f"Jadwal: {jadwal.get('summary')}", "Selesai")
            status_tambahan += f"\n\n📅 [Lihat Jadwal]({link})"
            result_text = parts[0].strip()

        # === catat transaksi ke Transaction List di tab bulan ===
        if "[CATAT_TRANSAKSI]" in result_text:
            if not BUDGET_SHEET_ID:
                raise RuntimeError("BUDGET_SHEET_ID belum diisi di file .env")
            parts = result_text.split("[CATAT_TRANSAKSI]")
            items = keuangan.parse_transaksi(parts[1])
            hasil, undo = await asyncio.to_thread(keuangan.tulis_transaksi, sheets_service, BUDGET_SHEET_ID, items, sekarang)
            last_undo[chat_id] = {"jenis": "keuangan", "undo": undo}
            baris = []
            for h in hasil:
                teks = f"• {h['tab']} baris {h['baris']} | {h['tanggal']} | {h['grup']} › {h['kategori']} | {keuangan.rupiah(h['jumlah'])}"
                if h['catatan']:
                    teks += f" | {h['catatan']}"
                if h['duplikat']:
                    teks += "\n  ⚠️ tanggal & jumlahnya sama dengan transaksi yang sudah ada"
                baris.append(teks)
            status_tambahan += "\n\n✅ Tercatat:\n" + "\n".join(baris) + "\n\nSalah catat atau dobel? Kirim /undo"
            result_text = parts[0].strip()

        # === tambah tugas ke TASK MANAGER ===
        if "[TAMBAH_TUGAS]" in result_text:
            if not TASK_SHEET_ID:
                raise RuntimeError("TASK_SHEET_ID belum diisi di file .env")
            parts = result_text.split("[TAMBAH_TUGAS]")
            items = sheetutil.parse_json_array(parts[1])
            hasil, restore = await asyncio.to_thread(tugas.tambah_tugas, sheets_service, TASK_SHEET_ID, items)
            last_undo[chat_id] = {"jenis": "pulih", "sheet_id": TASK_SHEET_ID, "data": restore,
                                  "label": f"{len(hasil)} tugas baru"}
            baris = []
            for h in hasil:
                teks = f"• {h['tugas']} | {h['due'] or 'tanpa tanggal'} | {h['priority']} | {h['kategori']}"
                if h["duplikat"]:
                    teks += "\n  ⚠️ mirip dengan tugas terbuka yang sudah ada"
                baris.append(teks)
            status_tambahan += "\n\n✅ Tugas ditambahkan:\n" + "\n".join(baris) + "\n\nSalah? Kirim /undo"
            result_text = parts[0].strip()

        # === tandai tugas selesai ===
        if "[SELESAI_TUGAS]" in result_text:
            if not TASK_SHEET_ID:
                raise RuntimeError("TASK_SHEET_ID belum diisi di file .env")
            parts = result_text.split("[SELESAI_TUGAS]")
            nama_selesai, semua_restore = [], []
            for it in sheetutil.parse_json_array(parts[1]):
                nama, restore = await asyncio.to_thread(tugas.selesaikan_dengan_kata, sheets_service, TASK_SHEET_ID, str(it.get("tugas", "")))
                nama_selesai.append(nama)
                semua_restore += restore
            last_undo[chat_id] = {"jenis": "pulih", "sheet_id": TASK_SHEET_ID, "data": semua_restore,
                                  "label": f"Penyelesaian {len(nama_selesai)} tugas"}
            status_tambahan += "\n\n✅ Selesai:\n" + "\n".join(f"• {n}" for n in nama_selesai) + "\n\nSalah? Kirim /undo"
            result_text = parts[0].strip()

        # === catat habit harian ===
        if "[CATAT_HABIT]" in result_text:
            if not HABIT_SHEET_ID:
                raise RuntimeError("HABIT_SHEET_ID belum diisi di file .env")
            parts = result_text.split("[CATAT_HABIT]")
            items = sheetutil.parse_json_array(parts[1])
            hasil, restore = await asyncio.to_thread(habit.catat_habit, sheets_service, HABIT_SHEET_ID, items, sekarang)
            last_undo[chat_id] = {"jenis": "pulih", "sheet_id": HABIT_SHEET_ID, "data": restore,
                                  "label": f"Catatan {len(hasil)} habit"}
            status_tambahan += "\n\n" + "\n".join(
                f"{'✅' if h['selesai'] else '⬜'} {h['habit']} ({h['tanggal']})" for h in hasil) + "\n\nSalah? Kirim /undo"
            result_text = parts[0].strip()

        # === trading MT5: hanya membuat kartu konfirmasi, order TIDAK pernah langsung dieksekusi ===
        id_user = update.effective_user.id if update.effective_user else 0
        if "[ORDER_TRADING]" in result_text:
            parts = result_text.split("[ORDER_TRADING]")
            status_tambahan += await trading_bot.dari_tag_order(parts[1], message, id_user)
            result_text = parts[0].strip()
        if "[TUTUP_POSISI]" in result_text:
            parts = result_text.split("[TUTUP_POSISI]")
            status_tambahan += await trading_bot.dari_tag_tutup(parts[1], message, id_user)
            result_text = parts[0].strip()

        teks_akhir = (result_text[:4000] + status_tambahan).strip() or "Selesai."
        try:
            await processing_msg.edit_text(teks_akhir, parse_mode="Markdown")
        except BadRequest:
            # Markdown gagal (misal ada karakter _ atau * di nama kategori), kirim ulang sebagai teks biasa
            await processing_msg.edit_text(teks_akhir)

    except Exception as e:
        logger.exception("Gagal")
        if any(k in str(e) for k in ("503", "UNAVAILABLE")):
            await processing_msg.edit_text("Server Gemini sedang penuh (sudah dicoba beberapa kali). Kirim ulang pesan ini beberapa menit lagi ya.")
        else:
            await processing_msg.edit_text(f"Terjadi kesalahan: {str(e)}")
    finally:
        if file_path and os.path.exists(file_path): os.remove(file_path)

async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Tangani error global supaya log tidak penuh traceback panjang."""
    from telegram.error import Conflict, NetworkError
    err = context.error
    if isinstance(err, Conflict):
        logger.warning("409 Conflict: ada instance bot lain yang memakai token ini. Cek autostart ganda.")
    elif isinstance(err, NetworkError):
        logger.warning("Gangguan jaringan Telegram (akan dicoba lagi otomatis): %s", err)
    else:
        logger.error("Error tidak tertangani", exc_info=err)

