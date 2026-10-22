# ============================================
# TRADING BOT - jembatan Telegram <-> MT5
# Scan market | Posisi | Order (dengan konfirmasi) | Tutup posisi
# Semua order tetap lewat trade_executor.send_order (validasi berlapis + risk manager).
# ============================================

import asyncio
import csv
import json
import logging
import os
import re
import threading
import time
import uuid

import MetaTrader5 as mt5
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler, CommandHandler

import config
import control
import market_scanner
import mt5_connector
import trade_executor
import profil

logger = logging.getLogger(__name__)

_allowed = set()                  # diisi dari bot.py (TELEGRAM_ALLOWED_USERS), WAJIB tidak kosong
_state = {"aktif": False}         # trading lewat bot selalu OFF saat bot baru jalan; nyalakan dengan /trading on
_pending = {}                     # token -> data konfirmasi
_mt5_lock = threading.Lock()      # MT5 API tidak aman dipanggil paralel
PENDING_TTL = 120                 # detik; konfirmasi kedaluwarsa kalau tidak ditekan
TAG_KOMENTAR = "TG"               # masuk ke komentar order: SHK|TG|0
HEARTBEAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "radar_heartbeat.json")


# ---------- keamanan & utilitas ----------
def _izin(user_id):
    """Trading SELALU butuh daftar ID yang diizinkan. Kalau kosong, semua perintah trading ditolak."""
    return bool(_allowed) and user_id in _allowed


def _pesan_tolak():
    if not _allowed:
        return ("🔒 Fitur trading dikunci. Isi TELEGRAM_ALLOWED_USERS di file .env dengan ID Telegram "
                f"{profil.panggil()} (cek lewat @userinfobot), lalu restart bot.")
    return "🔒 Maaf, akun ini tidak punya izin untuk trading."


def _penjaga(fn):
    async def bungkus(update, context):
        uid = update.effective_user.id if update.effective_user else 0
        if not _izin(uid):
            await update.effective_message.reply_text(_pesan_tolak())
            return
        await fn(update, context)
    return bungkus


def _konek():
    if mt5.terminal_info() is not None and mt5.account_info() is not None:
        return True
    return mt5_connector.connect_mt5(retries=2, wait=2)


async def _mt5(fn, *args, **kw):
    """Jalankan fungsi sinkron yang memakai MT5 di thread terpisah, dengan lock dan koneksi otomatis."""
    def kerja():
        with _mt5_lock:
            if not _konek():
                raise RuntimeError("MT5 tidak terhubung. Pastikan terminal MT5 terbuka dan sudah login.")
            return fn(*args, **kw)
    return await asyncio.to_thread(kerja)


def _semua_symbol():
    """SYMBOLS (scalping) + RADAR_SYMBOLS (forex & logam), tanpa duplikat."""
    urut = []
    for x in list(config.SYMBOLS) + list(getattr(config, "RADAR_SYMBOLS", [])):
        if x not in urut:
            urut.append(x)
    return urut


def _norm_symbol(s):
    """Hanya symbol yang ada di config (SYMBOLS / RADAR_SYMBOLS) yang boleh ditradingkan."""
    s = str(s or "").strip().upper()
    peta = {x.upper(): x for x in _semua_symbol()}
    if s in peta:
        return peta[s]
    if s in ("GOLD", "EMAS") and "XAUUSD" in peta:
        return peta["XAUUSD"]
    return None


def _angka(v):
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return x if 0 < x <= 5000 else None


def daftar_symbol():
    return ", ".join(_semua_symbol())


def _bersihkan_pending():
    sekarang = time.time()
    for k in [k for k, v in _pending.items() if sekarang - v["ts"] > PENDING_TTL]:
        _pending.pop(k, None)


async def _kirim_panjang(proses, teks, markup=None):
    """Edit pesan 'proses' dengan hasil; potong per 4000 karakter bila panjang."""
    potongan, buf = [], ""
    for baris in teks.split("\n"):
        if len(buf) + len(baris) + 1 > 4000:
            potongan.append(buf)
            buf = ""
        buf += baris + "\n"
    if buf.strip():
        potongan.append(buf)
    potongan = potongan or ["(kosong)"]
    for i, p in enumerate(potongan):
        mk = markup if i == len(potongan) - 1 else None
        if i == 0:
            await proses.edit_text(p.rstrip(), reply_markup=mk)
        else:
            await proses.reply_text(p.rstrip(), reply_markup=mk)


# ---------- scan market ----------
def _ringkas(r):
    if "error" in r:
        return f"{r['symbol']} {r['tf']}: {r['error']}"
    out = [f"{r['symbol']} | {r['tf']} | close {r['close']}"]

    def item(x):
        if "top" in x:
            return f"{x['type']} {x['time'][11:16]} {x['bottom']}-{x['top']}"
        return f"{x['type']} {x['time'][11:16]} @ {x.get('price', '')}"

    for judul, key in (("FVG", "fvg"), ("OB", "ob"), ("CHoCH", "choch"), ("Liquidity", "liquidity")):
        items = r.get(key) or []
        out.append(f"• {judul}: " + ("; ".join(item(x) for x in items[-2:]) if items else "-"))
    return "\n".join(out)


def teks_scan(symbol=None, tf=None):
    symbols = [symbol] if symbol else list(config.SYMBOLS)
    tfs = [tf] if tf else list(config.TIMEFRAMES)
    return "\n\n".join(_ringkas(market_scanner.scan_symbol(s, t)) for s in symbols for t in tfs)


# ---------- akun & posisi ----------
def teks_akun():
    info = mt5.account_info()
    if info is None:
        return "Info akun MT5 tidak tersedia."
    try:
        from control import is_halted
        halted, halt_msg = is_halted()
    except Exception:
        halted, halt_msg = False, ""
    baris = [
        "📊 AKUN MT5",
        f"Login {info.login} | {mt5_connector.account_type_name(info)} | {'NETTING' if mt5_connector.is_netting_account() else 'HEDGING'}",
        f"Balance {info.balance:.2f} {info.currency} | Equity {info.equity:.2f}",
        f"Floating {info.profit:+.2f} | Margin bebas {info.margin_free:.2f}",
        f"Algo Trading MT5: {'ON' if mt5_connector.is_algo_trading_enabled() else 'OFF'}",
        f"Trading via bot: {'ON ✅' if _state['aktif'] else 'OFF ⛔'}",
        f"Risk per trade {config.RISK_PERCENT}% | Maks posisi {config.MAX_OPEN_TRADES} | Maks rugi harian {config.MAX_DAILY_LOSS}%",
    ]
    if halted:
        baris.append(f"⛔ HALT aktif: {halt_msg}")
    return "\n".join(baris)


def _posisi_semua():
    return list(mt5.positions_get() or [])


def _arah(p):
    return "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL"


def teks_posisi():
    """Return (teks, daftar_ticket)."""
    posisi = _posisi_semua()
    if not posisi:
        return "Tidak ada posisi terbuka.", []
    total = sum(p.profit for p in posisi)
    baris = [f"📈 POSISI TERBUKA ({len(posisi)}) | floating {total:+.2f}"]
    for p in posisi:
        baris.append(f"#{p.ticket} {_arah(p)} {p.symbol} {p.volume} lot @ {p.price_open} | SL {p.sl or '-'} TP {p.tp or '-'} | {p.profit:+.2f}")
    return "\n".join(baris), [p.ticket for p in posisi]


def teks_radar():
    try:
        with open(HEARTBEAT, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return "File radar_heartbeat.json tidak ditemukan/terbaca di folder bot."
    umur = time.time() - float(d.get("ts", 0))
    menit = int(umur // 60)
    baris = [f"📡 RADAR: {d.get('state')} | pass {d.get('pass')} | order dibuka {d.get('opened')}",
             f"Update terakhir {d.get('waktu')} ({menit} menit lalu)"]
    if umur > 600:
        baris.append("⚠️ Heartbeat tidak diperbarui lebih dari 10 menit, radar mungkin berhenti.")
    return "\n".join(baris)


# ---------- order: siapkan, konfirmasi, eksekusi ----------
def _siapkan(symbol, signal, sl_pips, tp_pips):
    """Hitung SL/TP dari harga sekarang lalu dry-run lewat send_order. Dipanggil di dalam _mt5()."""
    if not mt5_connector.is_symbol_available(symbol):
        return {"ok": False, "pesan": f"Symbol {symbol} tidak tersedia di broker."}
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return {"ok": False, "pesan": "Gagal membaca harga sekarang."}

    pip = info.point * 10                                   # sama dengan definisi pip di trade_executor
    min_sl = config.rule(symbol, "min_sl_pips")
    sl_pips = sl_pips or getattr(config, "DEFAULT_SL_PIPS", None) or min_sl * 2
    tp_pips = tp_pips or sl_pips * getattr(config, "DEFAULT_RR", 2.0)

    harga = tick.ask if signal == "BUY" else tick.bid
    arah = 1 if signal == "BUY" else -1
    sl = round(harga - arah * sl_pips * pip, info.digits)
    tp = round(harga + arah * tp_pips * pip, info.digits)

    hasil = trade_executor.send_order(symbol, signal, harga, sl, tp, dry_run=True, timeframe=TAG_KOMENTAR, score=0)
    if not hasil.get("success"):
        return {"ok": False, "pesan": hasil.get("message", "Ditolak oleh validasi.")}

    lot = hasil["volume"]
    per_lot = (abs(harga - sl) / info.trade_tick_size) * info.trade_tick_value
    reward_lot = (abs(tp - harga) / info.trade_tick_size) * info.trade_tick_value
    akun = mt5.account_info()
    return {
        "ok": True, "symbol": symbol, "signal": signal, "entry": hasil["price"], "sl": hasil["sl"], "tp": hasil["tp"],
        "lot": lot, "risiko": lot * per_lot, "potensi": lot * reward_lot, "sl_pips": sl_pips, "tp_pips": tp_pips,
        "digits": info.digits, "mata_uang": akun.currency, "tipe": mt5_connector.account_type_name(akun),
        "spread": info.spread,
    }


def _kartu_order(d):
    f = f"{{:.{d['digits']}f}}"
    return "\n".join([
        f"📝 ORDER {d['signal']} {d['symbol']}",
        f"Akun {d['tipe']} | Harga {f.format(d['entry'])} | Spread {d['spread']} pt",
        f"SL {f.format(d['sl'])} ({d['sl_pips']:g} pip)",
        f"TP {f.format(d['tp'])} ({d['tp_pips']:g} pip)",
        f"Lot {d['lot']} | Risiko ≈ {d['risiko']:.2f} | Potensi ≈ {d['potensi']:.2f} {d['mata_uang']}",
        f"Eksekusi sekarang, {profil.panggil()}? (berlaku {PENDING_TTL} detik)",
    ])


def _markup_konfirmasi(token, label_ok="✅ Eksekusi"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(label_ok, callback_data=f"tr:ok:{token}"),
                                  InlineKeyboardButton("❌ Batal", callback_data=f"tr:no:{token}")]])


async def _buat_kartu_order(message, user_id, symbol, signal, sl_pips, tp_pips):
    if not _state["aktif"]:
        await message.reply_text(f"Trading lewat bot sedang OFF, {profil.panggil()}. Kirim /trading on untuk mengaktifkan.")
        return
    proses = await message.reply_text("Memeriksa setup & menghitung lot...")
    try:
        d = await _mt5(_siapkan, symbol, signal, sl_pips, tp_pips)
    except Exception as e:
        logger.exception("Gagal menyiapkan order")
        await proses.edit_text(f"Gagal menyiapkan order: {e}")
        return
    if not d["ok"]:
        await proses.edit_text("❌ " + d["pesan"])
        return
    _bersihkan_pending()
    token = uuid.uuid4().hex[:8]
    _pending[token] = {"jenis": "order", "user": user_id, "ts": time.time(), "data": d}
    await proses.edit_text(_kartu_order(d), reply_markup=_markup_konfirmasi(token))


def _eksekusi_order(d):
    return trade_executor.send_order(d["symbol"], d["signal"], d["entry"], d["sl"], d["tp"],
                                     dry_run=False, timeframe=TAG_KOMENTAR, score=0)


# ---------- tutup posisi ----------
def _pilih_tiket(ticket=None, symbol=None, semua=False):
    posisi = _posisi_semua()
    if ticket is not None:
        posisi = [p for p in posisi if p.ticket == ticket]
    elif symbol:
        posisi = [p for p in posisi if p.symbol == symbol]
    elif not semua:
        posisi = []
    return [(p.ticket, f"#{p.ticket} {_arah(p)} {p.symbol} {p.volume} lot ({p.profit:+.2f})") for p in posisi], sum(p.profit for p in posisi)


def _tutup_banyak(tickets):
    hasil = []
    for t in tickets:
        try:
            r = trade_executor.close_position(t)
            hasil.append((t, r.get("success"), r.get("message", "")))
        except Exception as e:  # satu tiket gagal tidak boleh menghentikan penutupan tiket lain
            hasil.append((t, False, str(e)))
    return hasil


async def _kartu_tutup(message, user_id, ticket=None, symbol=None, semua=False):
    try:
        daftar, total = await _mt5(_pilih_tiket, ticket, symbol, semua)
    except Exception as e:
        await message.reply_text(f"Gagal membaca posisi: {e}")
        return
    if not daftar:
        await message.reply_text("Tidak ada posisi yang cocok untuk ditutup.")
        return
    _bersihkan_pending()
    token = uuid.uuid4().hex[:8]
    _pending[token] = {"jenis": "tutup", "user": user_id, "ts": time.time(), "tickets": [t for t, _ in daftar]}
    teks = f"🧹 TUTUP {len(daftar)} POSISI (floating {total:+.2f})\n" + "\n".join(x for _, x in daftar) + \
           f"\nLanjut tutup, {profil.panggil()}?"
    await message.reply_text(teks, reply_markup=_markup_konfirmasi(token, "✅ Tutup"))


# ---------- tombol ----------
async def tombol(update, context):
    q = update.callback_query
    if not _izin(q.from_user.id):
        await q.answer("Tidak diizinkan.", show_alert=True)
        return
    await q.answer()
    try:
        _, aksi, arg = q.data.split(":", 2)
    except ValueError:
        return

    if aksi == "no":
        _pending.pop(arg, None)
        await q.edit_message_text("Dibatalkan.")
        return

    if aksi == "cl":                                    # tombol dari daftar /tutup: satu tiket, langsung tutup
        try:
            hasil = await _mt5(_tutup_banyak, [int(arg)])
        except Exception as e:
            await q.message.reply_text(f"Gagal menutup: {e}")
            return
        _, ok, pesan = hasil[0]
        await q.message.reply_text(f"✅ Posisi #{arg} ditutup." if ok else f"❌ Gagal menutup #{arg}: {pesan}")
        return

    if aksi != "ok":
        return
    p = _pending.get(arg)
    if p and p["user"] != q.from_user.id:
        await q.message.reply_text("Konfirmasi ini milik pengguna lain.")
        return
    p = _pending.pop(arg, None)                         # pop dulu supaya dobel-tap tidak mengeksekusi dua kali
    if not p or time.time() - p["ts"] > PENDING_TTL:
        await q.edit_message_text("Konfirmasi sudah kedaluwarsa. Kirim ulang perintahnya.")
        return

    try:
        if p["jenis"] == "order":
            if not _state["aktif"]:
                await q.edit_message_text("Trading lewat bot sudah di-OFF-kan. Order dibatalkan.")
                return
            await q.edit_message_text("Mengirim order...")
            r = await _mt5(_eksekusi_order, p["data"])
            d = p["data"]
            if r.get("success"):
                await q.edit_message_text(
                    f"✅ {d['signal']} {d['symbol']} tereksekusi\nTiket #{r['ticket']} | {r['volume']} lot @ {r['price']}\n"
                    f"SL {r['sl']} | TP {r['tp']}")
            else:
                await q.edit_message_text(f"❌ Order ditolak: {r.get('message')}")
        else:
            hasil = await _mt5(_tutup_banyak, p["tickets"])
            baris = [f"{'✅' if ok else '❌'} #{t} {'ditutup' if ok else pesan}" for t, ok, pesan in hasil]
            await q.edit_message_text("Hasil penutupan:\n" + "\n".join(baris))
    except Exception as e:
        logger.exception("Gagal eksekusi dari tombol")
        await q.edit_message_text(f"Terjadi kesalahan: {e}")


# ---------- perintah slash ----------
async def cmd_trading(update, context):
    m = update.effective_message
    arg = (context.args[0].lower() if context.args else "")
    if arg == "on":
        try:
            tipe = await _mt5(lambda: mt5_connector.account_type_name(mt5.account_info()))
        except Exception as e:
            await m.reply_text(f"Tidak bisa mengaktifkan: {e}")
            return
        if tipe == "REAL" and (len(context.args) < 2 or context.args[1].lower() != "real"):
            await m.reply_text("⚠️ Akun ini REAL. Untuk mengaktifkan kirim: /trading on real")
            return
        _state["aktif"] = True
        await m.reply_text(f"✅ Trading lewat bot ON (akun {tipe}). Setiap order tetap minta konfirmasi tombol.")
    elif arg == "off":
        _state["aktif"] = False
        _pending.clear()
        await m.reply_text("⛔ Trading lewat bot OFF. Semua konfirmasi yang menunggu dibatalkan.")
    else:
        await m.reply_text(
            f"Trading via bot: {'ON ✅' if _state['aktif'] else 'OFF ⛔'}\n\n"
            "/trading on | off  (order manual dengan konfirmasi)\n/akun  /posisi  /radar\n/scan [SYMBOL] [TF]\n"
            "/buy SYMBOL [sl_pip] [tp_pip]\n/sell SYMBOL [sl_pip] [tp_pip]\n/tutup [tiket|SYMBOL|semua]\n\n"
            "MODE OTOMATIS (langsung open tanpa konfirmasi):\n"
            "/auto on [score] [jam] | off | status | halt | resume\n"
            "atau ketik: jalankan otomatis trading dengan score 7\n\n"
            f"Symbol: {daftar_symbol()}")


async def cmd_akun(update, context):
    proses = await update.effective_message.reply_text("Membaca akun...")
    try:
        await _kirim_panjang(proses, await _mt5(teks_akun))
    except Exception as e:
        await proses.edit_text(f"Gagal: {e}")


async def cmd_posisi(update, context):
    proses = await update.effective_message.reply_text("Membaca posisi...")
    await _tampil_posisi(proses)


async def _tampil_posisi(proses):
    try:
        teks, tickets = await _mt5(teks_posisi)
    except Exception as e:
        await proses.edit_text(f"Gagal: {e}")
        return
    markup = None
    if tickets:
        baris = [[InlineKeyboardButton(f"Tutup #{t}", callback_data=f"tr:cl:{t}")] for t in tickets[:8]]
        markup = InlineKeyboardMarkup(baris)
    await _kirim_panjang(proses, teks, markup)


async def cmd_radar(update, context):
    await update.effective_message.reply_text(teks_radar())


async def _scan(proses, symbol, tf):
    try:
        await _kirim_panjang(proses, await _mt5(teks_scan, symbol, tf))
    except Exception as e:
        logger.exception("Gagal scan")
        await proses.edit_text(f"Gagal scan: {e}")


async def cmd_scan(update, context):
    m = update.effective_message
    symbol = tf = None
    for a in context.args:
        if a.upper() in config.TIMEFRAMES:
            tf = a.upper()
        elif _norm_symbol(a):
            symbol = _norm_symbol(a)
        else:
            await m.reply_text(f"'{a}' tidak dikenal. Symbol: {daftar_symbol()} | TF: {', '.join(config.TIMEFRAMES)}")
            return
    proses = await m.reply_text("Memindai market...")
    await _scan(proses, symbol, tf)


async def _cmd_arah(update, context, signal):
    m = update.effective_message
    if not context.args:
        await m.reply_text(f"Format: /{signal.lower()} SYMBOL [sl_pip] [tp_pip]\nContoh: /{signal.lower()} {config.SYMBOLS[0]} 15 30\n"
                           "Tanpa angka, SL/TP otomatis dari config.")
        return
    symbol = _norm_symbol(context.args[0])
    if not symbol:
        await m.reply_text(f"Symbol tidak dikenal. Pilihan: {daftar_symbol()}")
        return
    sl = _angka(context.args[1]) if len(context.args) > 1 else None
    tp = _angka(context.args[2]) if len(context.args) > 2 else None
    if (len(context.args) > 1 and sl is None) or (len(context.args) > 2 and tp is None):
        await m.reply_text("Angka SL/TP tidak valid (harus lebih dari 0, satuan pip).")
        return
    await _buat_kartu_order(m, update.effective_user.id, symbol, signal, sl, tp)


async def cmd_buy(update, context):
    await _cmd_arah(update, context, "BUY")


async def cmd_sell(update, context):
    await _cmd_arah(update, context, "SELL")


async def cmd_tutup(update, context):
    m = update.effective_message
    uid = update.effective_user.id
    if not context.args:
        proses = await m.reply_text("Membaca posisi...")
        await _tampil_posisi(proses)
        return
    a = context.args[0]
    if a.lower() == "semua":
        await _kartu_tutup(m, uid, semua=True)
    elif a.isdigit():
        await _kartu_tutup(m, uid, ticket=int(a))
    elif _norm_symbol(a):
        await _kartu_tutup(m, uid, symbol=_norm_symbol(a))
    else:
        await m.reply_text("Format: /tutup [tiket | SYMBOL | semua]")


# ---------- MODE OTOMATIS (radar-loop dari control.py) ----------
# Bot hanya menyalakan/mematikan radar-loop yang sudah ada (control.radar_start/radar_stop).
# Skor dan keputusan open dihitung oleh radar sendiri; order tetap lewat send_order (semua validasi berlaku).
async def _auto_on(proses, skor, jam, real):
    batas_min = int(getattr(config, "RADAR_MIN_SCORE", 1))
    skor = batas_min if skor is None else int(skor)
    if skor < batas_min:
        await proses.edit_text(f"Skor {skor} di bawah RADAR_MIN_SCORE ({batas_min}) di config.py, ditolak. "
                               f"Pakai skor ≥ {batas_min}, atau ubah config bila memang disengaja.")
        return
    if skor > 20:
        await proses.edit_text("Skor tidak masuk akal (maks 20).")
        return
    maks_jam = int(getattr(config, "RADAR_LOOP_MAX_HOURS", 12))
    catatan_jam = ""
    if jam is None:
        jam = maks_jam
    elif jam > maks_jam or jam < 1:
        catatan_jam = f" (jam dibatasi ke {maks_jam}, sesuai RADAR_LOOP_MAX_HOURS)"
        jam = maks_jam
    try:
        tipe = await _mt5(lambda: mt5_connector.account_type_name(mt5.account_info()))
    except Exception as e:
        await proses.edit_text(f"Tidak bisa memastikan tipe akun MT5, mode otomatis tidak dinyalakan: {e}")
        return
    if tipe == "REAL":
        if not config.ALLOW_REAL_ACCOUNT:
            await proses.edit_text("Akun REAL diblokir (ALLOW_REAL_ACCOUNT = False di config.py). Mode otomatis tidak dinyalakan.")
            return
        if not real:
            await proses.edit_text(f"⚠️ Akun ini REAL. Untuk menyalakan mode otomatis di akun REAL, tulis lagi dengan kata 'real', "
                                   f"mis. /auto on {skor} real")
            return
    pesan = await asyncio.to_thread(control.radar_start, jam, skor)
    if "sudah berjalan" in pesan:
        pesan += f"\nSkor tidak berubah. Kirim /auto off, tunggu radar berhenti, lalu nyalakan lagi dengan skor {skor}."
    elif pesan.startswith("Tidak dimulai"):
        await proses.edit_text("⛔ " + pesan)
        return
    elif pesan.startswith("Radar loop dimulai"):
        _state["auto"] = {"ts": time.time(), "skor": skor, "jam": jam}
    await proses.edit_text(
        f"🤖 MODE OTOMATIS ({tipe})\n{pesan}{catatan_jam}\n"
        f"Skor minimum {skor} | maks {jam} jam | risk {config.RISK_PERCENT}%/trade | maks posisi {config.MAX_OPEN_TRADES} | "
        f"rugi harian maks {config.MAX_DAILY_LOSS}%\n"
        f"Tiap order yang dibuka radar akan dikabarkan di sini, {profil.panggil()}. Hentikan kapan saja: /auto off")


async def _auto_off(proses):
    await proses.edit_text("⛔ " + await asyncio.to_thread(control.radar_stop))


async def _auto_status(proses):
    teks = await asyncio.to_thread(control.radar_status)
    await _kirim_panjang(proses, teks)


async def _auto_halt(proses):
    await proses.edit_text("⛔ " + await asyncio.to_thread(control.halt_today, "perintah dari Telegram"))


async def _auto_resume(proses):
    await proses.edit_text("✅ " + await asyncio.to_thread(control.resume))


async def cmd_auto(update, context):
    m = update.effective_message
    a = [x.lower() for x in context.args]
    proses = await m.reply_text("Memproses...")
    if not a or a[0] == "status":
        await _auto_status(proses)
    elif a[0] == "on":
        angka = [x for x in a[1:] if x.isdigit()]
        await _auto_on(proses, int(angka[0]) if angka else None, int(angka[1]) if len(angka) > 1 else None, "real" in a)
    elif a[0] == "off":
        await _auto_off(proses)
    elif a[0] == "halt":
        await _auto_halt(proses)
    elif a[0] == "resume":
        await _auto_resume(proses)
    else:
        await proses.edit_text("Format: /auto on [score] [jam] | off | status | halt | resume")


# ---------- pantau jurnal & radar (notifikasi otomatis) ----------
def _baca_baris(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return None


def format_jurnal(baris):
    """Satu baris trade_journal.csv -> teks notifikasi. None kalau tidak terbaca."""
    try:
        r = next(csv.reader([baris]))
        waktu, ticket, symbol, tf, signal, skor, lot, harga, sl, tp = r[:10]
        alasan = r[11] if len(r) > 11 else ""
    except (StopIteration, ValueError):
        return None
    return (f"🤖 Radar membuka {signal} {symbol} {tf} | skor {skor}\n"
            f"Tiket #{ticket} | {lot} lot @ {harga} | SL {sl} | TP {tp}\n{alasan}")[:900]


async def _beritahu(app, teks):
    for uid in _allowed:
        try:
            await app.bot.send_message(uid, teks)
        except Exception as e:
            logger.warning("Gagal kirim notifikasi ke %s: %s", uid, e)


async def _pantau(app):
    path = os.path.join(control.BASE, config.JOURNAL_FILE)
    baris = await asyncio.to_thread(_baca_baris, path)
    terakhir = len(baris) if baris is not None else 0
    hidup_sebelumnya = control.loop_running()
    while True:
        await asyncio.sleep(30)
        try:
            baris = await asyncio.to_thread(_baca_baris, path)
            if baris is not None:
                if len(baris) > terakhir:
                    baru, terakhir = baris[terakhir:], len(baris)
                    for b in baru[:5]:
                        teks = format_jurnal(b)
                        if teks:
                            await _beritahu(app, teks)
                    if len(baru) > 5:
                        await _beritahu(app, f"... dan {len(baru) - 5} order lain. Cek /posisi.")
                elif len(baris) < terakhir:
                    terakhir = len(baris)
            hidup = control.loop_running()
            if hidup_sebelumnya and not hidup:
                await _beritahu(app, "⚠️ Radar-loop berhenti (heartbeat tidak diperbarui). Cek /auto status.")
            hidup_sebelumnya = hidup
        except Exception:
            logger.exception("Pemantau jurnal error")


async def post_init(app):
    """Dipasang lewat ApplicationBuilder().post_init(trading_bot.post_init)."""
    app.bot_data["pantau_task"] = asyncio.create_task(_pantau(app))


# ---------- dari tag Gemini ----------
def _json_pertama(teks):
    for pola in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pola, teks or "", re.S)
        if m:
            try:
                d = json.loads(m.group(0))
                return d[0] if isinstance(d, list) and d else d
            except ValueError:
                continue
    return None


async def dari_tag_order(teks, message, user_id):
    """Dipanggil bot.py saat Gemini mengeluarkan [ORDER_TRADING]. Hanya membuat kartu konfirmasi, tidak pernah langsung eksekusi."""
    if not _izin(user_id):
        return "\n\n" + _pesan_tolak()
    d = _json_pertama(teks)
    if not isinstance(d, dict):
        return "\n\n⚠️ Perintah order tidak terbaca. Pakai /buy atau /sell."
    signal = str(d.get("aksi", "")).upper()
    symbol = _norm_symbol(d.get("symbol"))
    if signal not in ("BUY", "SELL") or not symbol:
        return f"\n\n⚠️ Arah/symbol belum jelas. Contoh: /buy {config.SYMBOLS[0]} 15 30"
    await _buat_kartu_order(message, user_id, symbol, signal, _angka(d.get("sl_pips")), _angka(d.get("tp_pips")))
    return ""


async def dari_tag_tutup(teks, message, user_id):
    if not _izin(user_id):
        return "\n\n" + _pesan_tolak()
    d = _json_pertama(teks)
    if not isinstance(d, dict):
        return "\n\n⚠️ Perintah tutup tidak terbaca. Pakai /tutup."
    ticket = d.get("ticket")
    if ticket is not None and str(ticket).isdigit():
        await _kartu_tutup(message, user_id, ticket=int(ticket))
    elif _norm_symbol(d.get("symbol")):
        await _kartu_tutup(message, user_id, symbol=_norm_symbol(d.get("symbol")))
    elif d.get("semua"):
        await _kartu_tutup(message, user_id, semua=True)
    else:
        return "\n\n⚠️ Posisi mana yang ditutup? Pakai /tutup untuk melihat daftar."
    return ""


# ---------- rute teks bebas (tanpa Gemini) ----------
def rute_teks(teks):
    t = (teks or "").lower()
    # Mode otomatis: SENGAJA ketat (harus menyebut trading/radar/score) supaya kalimat lain tidak menyalakan trading.
    if re.search(r"\b(halt|stop trading hari ini|berhenti trading hari ini|hentikan trading hari ini)\b", t):
        return ("auto_halt",)
    if re.search(r"\b(trading|radar|score|skor)\b", t):
        if re.search(r"\b(stop|matikan|hentikan|berhenti|nonaktifkan|off)\b", t) and re.search(r"\b(otomatis|auto|radar)\b", t):
            return ("auto_off",)
        if re.search(r"\b(jalankan|aktifkan|mulai|nyalakan|hidupkan|start|on)\b", t) and re.search(r"\b(otomatis|auto|radar)\b", t):
            m_skor = re.search(r"(?:score|skor)\s*(\d+)", t)
            m_jam = re.search(r"(\d+)\s*jam", t)
            return ("auto_on", int(m_skor.group(1)) if m_skor else None, int(m_jam.group(1)) if m_jam else None,
                    bool(re.search(r"\breal\b", t)))
        if re.search(r"\bstatus\b", t) and re.search(r"\b(radar|otomatis|auto)\b", t):
            return ("auto_status",)
    if re.search(r"\b(scan|pindai)\b", t):
        symbol = next((x for x in _semua_symbol() if x.lower() in t), None)
        if symbol is None and re.search(r"\b(gold|emas)\b", t):
            symbol = _norm_symbol("XAUUSD")
        tf = next((k for k in config.TIMEFRAMES if re.search(rf"\b{re.escape(k.lower())}\b", t)), None)
        if symbol or tf or re.search(r"\b(market|pasar|chart|semua)\b", t):
            return ("scan", symbol, tf)
    if re.search(r"posisi (terbuka|trading|saya|aktif)|open position|floating", t):
        return ("posisi",)
    if re.search(r"(akun|saldo|equity) (trading|mt5|metatrader)|status (trading|mt5)|\bmt5\b", t):
        return ("akun",)
    if re.search(r"\bradar\b", t):
        return ("radar",)
    return None


async def jalankan_rute(rute, proses, user_id):
    if not _izin(user_id):
        await proses.edit_text(_pesan_tolak())
        return
    aksi = rute[0]
    if aksi == "scan":
        await proses.edit_text("Memindai market...")
        await _scan(proses, rute[1], rute[2])
    elif aksi == "posisi":
        await _tampil_posisi(proses)
    elif aksi == "akun":
        try:
            await _kirim_panjang(proses, await _mt5(teks_akun))
        except Exception as e:
            await proses.edit_text(f"Gagal: {e}")
    elif aksi == "radar":
        await proses.edit_text(teks_radar())
    elif aksi == "auto_on":
        await _auto_on(proses, rute[1], rute[2], rute[3])
    elif aksi == "auto_off":
        await _auto_off(proses)
    elif aksi == "auto_status":
        await _auto_status(proses)
    elif aksi == "auto_halt":
        await _auto_halt(proses)


# ---------- pendaftaran handler ----------
def daftar(app, allowed_users):
    global _allowed
    _allowed = set(allowed_users or [])
    for nama, fn in (("trading", cmd_trading), ("akun", cmd_akun), ("posisi", cmd_posisi), ("radar", cmd_radar),
                     ("scan", cmd_scan), ("auto", cmd_auto), ("buy", cmd_buy), ("sell", cmd_sell), ("tutup", cmd_tutup)):
        app.add_handler(CommandHandler(nama, _penjaga(fn)))
    app.add_handler(CallbackQueryHandler(tombol, pattern=r"^tr:"))
    if not _allowed:
        print("PERINGATAN: TELEGRAM_ALLOWED_USERS kosong, semua perintah trading DIKUNCI sampai diisi.")
