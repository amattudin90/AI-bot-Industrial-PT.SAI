import os
import json

# ============================================
# FILTER BARU
# ============================================

# 1. Session / Killzone Filter (waktu PC / server MT5 biasanya UTC+2 atau UTC+3)
# Format: (jam_mulai, jam_selesai) dalam 24 jam
USE_SESSION_FILTER = True
KILLZONES = [
    (7, 11),    # London Open
    (12, 16),   # New York Open / overlap
]
# Di luar jam di atas → sinyal ditolak

# 2. Higher Timeframe Bias (H1)
USE_HTF_BIAS = True
HTF_TIMEFRAME = "H1"          # H1 = 60 menit
HTF_LOOKBACK = 50           # jumlah candle H1 yang dianalisis

# 3. Premium / Discount Filter
USE_PREMIUM_DISCOUNT = True
PD_LOOKBACK = 50            # swing lookback untuk tentukan equilibrium

# ============================================
# CONFIGURATION - TRADING SKILL
# ============================================

# Symbol yang akan di-scan (scalping)
SYMBOLS = [
    "USDJPY",
    "EURUSD",
    "USDCHF",
    "GBPUSD"
]

# Timeframe untuk scalping
TIMEFRAMES = {
    "M5": 5,      # 5 menit
    "M15": 15     # 15 menit
}

# Jumlah candle yang diambil untuk analisis
CANDLES_COUNT = 300

# Pengaturan Risk
RISK_PERCENT = 0.5          # 0.5% per trade
MAX_OPEN_TRADES = 10         # mode uji: banyak posisi sekaligus (turunkan lagi setelah evaluasi)
MAX_DAILY_LOSS = 2.0        # 2% max daily loss (realized hari ini + floating)

# --- Pengaman tambahan (baru) ---
ALLOW_REAL_ACCOUNT = False  # False = bot menolak trading di akun REAL. Ubah ke True hanya setelah lolos tes di DEMO.
MAX_LOT = 0.50              # batas atas lot per order (jaring pengaman jika perhitungan lot keliru)
MAX_SPREAD_POINTS = 30      # tolak order jika spread (dalam point) lebih besar dari ini
MIN_SL_PIPS = 3             # tolak order jika jarak SL kurang dari ini (pips) agar lot tidak meledak
ENTRY_ZONE_BUFFER = 0.5     # harga boleh melewati level entry maksimal 0.5x jarak entry-SL, lebih dari itu setup dianggap basi
MAX_RISK_OVERSHOOT = 2.0    # jika lot minimum broker membuat risiko > 2x RISK_PERCENT, order ditolak
ONE_POSITION_PER_SYMBOL = False   # False = boleh beberapa setup di symbol sama (beda timeframe), arah harus sama
MAX_POSITIONS_PER_SYMBOL = 2      # batas posisi per symbol (misalnya satu M5 + satu M15)
ALLOW_OPPOSITE_ON_SYMBOL = False  # False = dilarang buka posisi berlawanan di symbol yang sama (menghindari hedge sendiri)

# Magic Number (untuk mengidentifikasi order dari bot ini)
MAGIC_NUMBER = 20251005

# Path log
LOG_FILE = "trading_log.txt"


# ============================================
# RADAR SHAKEEL
# ============================================
RADAR_USE_FOREX = True       # scan pasangan forex
RADAR_USE_METALS = True      # scan logam (emas, perak)

FOREX_SYMBOLS = [
    # Major
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
    # Cross
    "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY",
    "EURGBP", "EURAUD", "EURCAD", "EURCHF", "EURNZD",
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
    "AUDCAD", "AUDCHF", "AUDNZD", "NZDCAD", "NZDCHF", "CADCHF"
]
METALS_SYMBOLS = ["XAUUSD", "XAGUSD"]   # emas, perak

RADAR_SYMBOLS = (FOREX_SYMBOLS if RADAR_USE_FOREX else []) + (METALS_SYMBOLS if RADAR_USE_METALS else [])

RADAR_MIN_SCORE_DEFAULT = 6  # skor dasar bila belum pernah diubah lewat Telegram
RADAR_MIN_SCORE = RADAR_MIN_SCORE_DEFAULT   # nilai aktif; ditimpa otomatis dari runtime_settings.json (lihat bagian bawah file)
RADAR_INTERVAL_SEC = 60      # jeda antar scan pada mode radar-loop
RADAR_COOLDOWN_MIN = 180     # setup (zona OB) yang sudah dibuka tidak dibuka lagi selama ini
RADAR_LOOP_MAX_HOURS = 12    # radar-loop berhenti otomatis setelah sekian jam (jaring pengaman)

# File data (disimpan di folder skill)
JOURNAL_FILE = "trade_journal.csv"
RADAR_FILE = "radar.json"
STATE_FILE = "radar_state.json"
HALT_FILE = "trading_halt.json"      # dibuat oleh perintah halt ("STOP trading hari ini")
HEARTBEAT_FILE = "radar_heartbeat.json"
LOOP_LOG_FILE = "radar_loop.log"
STOP_FILE = "radar.stop"     # buat file ini untuk menghentikan radar-loop
LOOP_LOG = "radar_loop.log"            # log radar yang berjalan di latar belakang


# ============================================
# ATURAN PER SYMBOL (menimpa nilai default MAX_SPREAD_POINTS dan MIN_SL_PIPS)
# 1 pip = 10 point. Emas: 1 pip = 0.10 USD. Perak: 1 pip = 0.01 USD.
# ============================================
SYMBOL_RULES = {
    "XAUUSD": {"max_spread": 80, "min_sl_pips": 20},   # SL minimal sekitar 2.0 USD
    "XAGUSD": {"max_spread": 80, "min_sl_pips": 20},   # SL minimal sekitar 0.20 USD
}

def rule(symbol: str, name: str):
    """Ambil aturan per symbol; jika tidak ada, pakai default global."""
    defaults = {"max_spread": MAX_SPREAD_POINTS, "min_sl_pips": MIN_SL_PIPS}
    return SYMBOL_RULES.get(symbol, {}).get(name, defaults[name])

# Toleransi equal high/low (likuiditas) dalam point, disesuaikan dengan skala harga tiap symbol.
# True = 12 point untuk semua symbol (EURUSD sama seperti dulu 0.00012; JPY, emas, perak ikut skala sendiri).
# False = pakai toleransi lama 0.00012 untuk semua symbol.
LIQUIDITY_SCALE_BY_POINT = True
LIQUIDITY_TOL_POINTS = 12


# ============================================
# PENGATURAN YANG BISA DIUBAH LEWAT TELEGRAM (runtime)
# ============================================
# Skor minimum disimpan di runtime_settings.json (di folder yang sama dengan config.py),
# jadi tetap berlaku setelah bot / radar di-restart. Ubah lewat Telegram:
#   "ubah score 5", "jalankan trading score 5", "/score 5", "cek score"
SCORE_ALLOWED_MIN = 3      # batas bawah yang boleh diminta dari Telegram
SCORE_ALLOWED_MAX = 10     # batas atas; sesuaikan dengan skor maksimum di market_scanner.py
SCORE_WARN_BELOW = 5       # di bawah angka ini bot memberi peringatan (setup makin banyak tapi kualitas turun)
RUNTIME_FILE = "runtime_settings.json"

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def data_path(name: str) -> str:
    """Path absolut sebuah file data di folder config.py (supaya bot dan proses radar membaca file yang sama)."""
    return name if os.path.isabs(name) else os.path.join(_BASE_DIR, name)


def _read_runtime() -> dict:
    try:
        with open(data_path(RUNTIME_FILE), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_runtime(d: dict) -> None:
    path = data_path(RUNTIME_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)   # tulis atomik supaya tidak ada file setengah jadi


def get_min_score() -> int:
    """Skor minimum yang sedang berlaku."""
    return int(RADAR_MIN_SCORE)


def set_min_score(n) -> int:
    """Ubah skor minimum: tersimpan ke file dan langsung berlaku di proses ini. Melempar ValueError bila di luar batas."""
    global RADAR_MIN_SCORE
    n = int(n)
    if not (SCORE_ALLOWED_MIN <= n <= SCORE_ALLOWED_MAX):
        raise ValueError(f"Skor harus antara {SCORE_ALLOWED_MIN} dan {SCORE_ALLOWED_MAX}.")
    d = _read_runtime()
    d["radar_min_score"] = n
    _write_runtime(d)
    RADAR_MIN_SCORE = n
    return n


def _muat_runtime() -> None:
    global RADAR_MIN_SCORE
    v = _read_runtime().get("radar_min_score")
    if isinstance(v, (int, float)) and SCORE_ALLOWED_MIN <= int(v) <= SCORE_ALLOWED_MAX:
        RADAR_MIN_SCORE = int(v)


_muat_runtime()   # dipanggil saat config di-import (termasuk oleh proses radar yang baru dinyalakan)