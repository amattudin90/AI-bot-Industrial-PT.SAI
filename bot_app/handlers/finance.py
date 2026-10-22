"""Financial actions, profile commands, and shared Telegram formatting helpers."""

from bot_app.context import (
    BUDGET_SHEET_ID,
    BadRequest,
    ContextTypes,
    GEMINI_MODEL,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MENU_ANGKA,
    MENU_LENGKAP,
    TZ,
    Update,
    asyncio,
    chat_sessions,
    client,
    datetime,
    diizinkan,
    get_google_services,
    keuangan,
    last_undo,
    logger,
    penasihat,
    profil,
    sheetutil,
    time,
)


async def undo_transaksi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Batalkan aksi terakhir (transaksi, tugas baru/selesai, centang habit)."""
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    chat_id = update.message.chat_id
    info = last_undo.pop(chat_id, None)
    if not info:
        await update.message.reply_text("Tidak ada aksi terakhir yang bisa dibatalkan.")
        return
    try:
        _, sheets_service, _ = await asyncio.to_thread(get_google_services)
        if info["jenis"] == "keuangan":
            n = await asyncio.to_thread(keuangan.hapus_transaksi, sheets_service, BUDGET_SHEET_ID, info["undo"])
            await update.message.reply_text(f"↩️ {n} transaksi terakhir dibatalkan (isi selnya dikosongkan di Transaction List).")
        else:
            await asyncio.to_thread(sheetutil.tulis, sheets_service, info["sheet_id"], info["data"])
            await update.message.reply_text(f"↩️ {info['label']} dibatalkan (isi sel dikembalikan seperti semula).")
    except Exception as e:
        logger.exception("Gagal undo")
        await update.message.reply_text(f"Gagal membatalkan: {e}")

async def cmd_namai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/namai NamaBaru : ganti nama bot."""
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not context.args:
        await update.message.reply_text(f"Namaku sekarang {profil.nama()}. Ganti dengan: /namai NamaBaru")
        return
    if not profil.simpan(nama=" ".join(context.args)):
        await update.message.reply_text("Nama tidak valid (huruf/angka, maksimal 24 karakter).")
        return
    chat_sessions.clear()  # sesi Gemini dibuat ulang supaya identitas baru terpakai
    await update.message.reply_text(f"Siap {profil.panggil()}, mulai sekarang namaku {profil.nama()}.")

async def cmd_panggil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/panggil Sebutan : ganti panggilan untuk user (default Boss)."""
    if not diizinkan(update.effective_user.id if update.effective_user else 0):
        return
    if not context.args:
        await update.message.reply_text(f"Aku memanggilmu {profil.panggil()}. Ganti dengan: /panggil Sebutan")
        return
    if not profil.simpan(panggil=" ".join(context.args)):
        await update.message.reply_text("Sebutan tidak valid (huruf/angka, maksimal 24 karakter).")
        return
    chat_sessions.clear()
    await update.message.reply_text(f"Siap, mulai sekarang aku panggil {profil.panggil()}.")

def wait_for_file_active(uploaded_file):
    elapsed = 0
    while uploaded_file.state.name == "PROCESSING" and elapsed < 120:
        time.sleep(2)
        elapsed += 2
        uploaded_file = client.files.get(name=uploaded_file.name)
    return uploaded_file

def kirim_dengan_retry(sesi, payload, maks=4):
    """Kirim ke Gemini; ulangi otomatis kalau server sedang penuh (503/429/500)."""
    for i in range(maks):
        try:
            return sesi.send_message(payload)
        except Exception as e:
            pesan = str(e)
            sementara = any(k in pesan for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL"))
            if not sementara or i == maks - 1:
                raise
            tunggu = 2 ** (i + 1)  # 2, 4, 8 detik
            logger.warning("Gemini sibuk (percobaan %d/%d), coba lagi dalam %d detik", i + 1, maks, tunggu)
            time.sleep(tunggu)

def saran_ai(kartu_html):
    """Saran singkat dari Gemini di atas angka yang sudah dihitung program. None kalau gagal (kartu tetap terkirim)."""
    prompt = (
        "Kamu penasihat keuangan pribadi yang santai dan sopan. Di bawah ini hasil hitungan program: jangan dihitung ulang dan jangan mengarang angka. "
        "Tulis SARAN SINGKAT dalam bahasa Indonesia: maksimal 4 poin diawali •, total di bawah 110 kata, berupa opsi yang bisa dipilih user (bukan perintah), "
        "sertakan dampak dalam rupiah hanya jika ada di data. Jangan pakai tanda ** atau markdown. "
        "Tutup dengan satu kalimat pendek bahwa ini gambaran dari data catatan, bukan nasihat keuangan profesional.\n\n"
        + penasihat.strip_html(kartu_html))
    for i in range(3):
        try:
            hasil = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            return (hasil.text or "").strip() or None
        except Exception as e:
            sementara = any(k in str(e) for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL"))
            if sementara and i < 2:
                time.sleep(2 ** (i + 1))
                continue
            logger.warning("Saran AI gagal: %s", e)
            return None

async def kirim_html(pesan, teks, markup=None):
    try:
        await pesan.edit_text(teks, parse_mode="HTML", reply_markup=markup)
    except BadRequest:
        await pesan.edit_text(penasihat.strip_html(teks), reply_markup=markup)

async def jalankan_aksi(aksi, params, proses, balas):
    """proses: pesan 'sedang menghitung' yang diedit jadi kartu; balas: pesan untuk membalas saran."""
    if not BUDGET_SHEET_ID:
        raise RuntimeError("BUDGET_SHEET_ID belum diisi di file .env")
    _, sheets_service, _ = await asyncio.to_thread(get_google_services)
    sekarang = datetime.now(TZ)
    riwayat, _gagal = await asyncio.to_thread(keuangan.baca_riwayat, sheets_service, BUDGET_SHEET_ID, sekarang)
    m = keuangan.hitung_metrik(riwayat, sekarang)
    if not m:
        await proses.edit_text("Belum ada tab bulan dengan data transaksi untuk dianalisis.")
        return
    kartu = penasihat.kartu(aksi, m, riwayat, sekarang, params)
    if aksi == "status":
        await kirim_html(proses, kartu, MENU_ANGKA)
        return
    await kirim_html(proses, kartu)
    saran = await asyncio.to_thread(saran_ai, kartu)
    await balas.reply_text(saran or "Mau lanjut ke analisis lain?", reply_markup=MENU_LENGKAP)

async def tombol_aksi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not diizinkan(q.from_user.id):
        await q.answer("Tidak diizinkan.", show_alert=True)
        return
    await q.answer()
    aksi = (q.data or "").split(":", 1)[-1]
    proses = await q.message.reply_text("Menghitung...")
    try:
        await jalankan_aksi(aksi, {}, proses, q.message)
    except Exception as e:
        logger.exception("Gagal aksi tombol")
        await proses.edit_text(f"Terjadi kesalahan: {str(e)}")

def markup_dari(baris_tombol):
    if not baris_tombol:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in baris]
                                 for baris in baris_tombol])

