"""Shared configuration, integrations, prompts, and process state for the Telegram bot.

Handler functions live in bot_app.handlers; this module intentionally contains no
Telegram handler registration to avoid import cycles.
"""

import os
import re
import json
import time
import uuid
import asyncio
import logging
import io
from core.skill_manager import SkillManager
from skills.battery_monitor import BatteryMonitorSkill
from skills.laptop_control import LaptopControlSkill
from skills.system_monitor import SystemMonitorSkill
from skills.screenshot import ScreenshotSkill
from datetime import date, datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from google import genai
from google.genai import types

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

import keuangan   # logika pencatat & pembaca sheet (keuangan.py, satu folder dengan bot.py)
import penasihat  # kartu status & analisis keuangan personal (penasihat.py)
import sheetutil  # utilitas Google Sheets bersama (sheetutil.py)
import tugas      # TASK MANAGER (tugas.py)
import habit      # HABIT BUILDER (habit.py)
import profil     # nama bot & sebutan untuk user (profil.py)
import trading_bot  # scan market + trading MT5 (trading_bot.py)
import config       # pengaturan trading (config.py), termasuk skor minimum yang bisa diubah lewat Telegram

load_dotenv()
# === MODULAR SKILL MANAGER ===
skill_manager = SkillManager()
skill_manager.register(BatteryMonitorSkill())
skill_manager.register(LaptopControlSkill())
skill_manager.register(SystemMonitorSkill())
skill_manager.register(ScreenshotSkill())

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
SHEET_ID = os.environ.get("SHEET_ID")  # database log Kaizen/jadwal (tetap seperti sebelumnya)
BUDGET_SHEET_ID = os.environ.get("BUDGET_SHEET_ID")  # ID file Budget_TRACKING
TASK_SHEET_ID = os.environ.get("TASK_SHEET_ID")      # ID file TASK MANAGER
HABIT_SHEET_ID = os.environ.get("HABIT_SHEET_ID")    # ID file HABIT BUILDER
# Opsional: daftar ID Telegram yang boleh memakai bot (pisahkan dengan koma). Kosong = semua orang boleh.
ALLOWED_USERS = {int(x) for x in re.findall(r"\d+", os.environ.get("TELEGRAM_ALLOWED_USERS", ""))}
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
TZ = ZoneInfo("Asia/Jakarta")

client = genai.Client(api_key=GEMINI_API_KEY)
chat_sessions = {}
last_undo = {}  # chat_id -> info aksi terakhir yang bisa dibatalkan dengan /undo
habit_kata = {"ts": 0.0, "kata": set()}  # cache kata dari nama habit (untuk mendeteksi pesan soal habit)

# === battery notify debounce (chat ids + interval persisted di SkillManager) ===
_battery_notify = {"last_alert_state": None, "last_percent": None}
# default interval dari .env; bisa diubah runtime lewat /skill_interval dan disimpan
BATTERY_POLL_SEC_DEFAULT = int(os.environ.get("BATTERY_POLL_SEC", "120") or 120)


def diizinkan(user_id):
    return (not ALLOWED_USERS) or (user_id in ALLOWED_USERS)

# === SYSTEM INSTRUCTION ===
BASE_INSTRUCTION = """
Anda adalah Shakeel, AI Agent Asisten Boss
1. Jika user meminta "Analisis KAIZEN", buat laporan (KONDISI, WASTE, COUNTERMEASURE) dan awali dengan tag "[DOKUMEN KAIZEN]".
2. Jika user meminta jadwal meeting, respons dengan JSON: [JADWALKAN_KALENDER] {"summary": "Judul", "description": "Deskripsi", "start_time": "YYYY-MM-DDTHH:MM:SS", "end_time": "YYYY-MM-DDTHH:MM:SS"}
3. Jawab pertanyaan soal analisis data berdasarkan [INFO INTERNAL DATABASE] yang disematkan dalam pesan.
"""

TX_INSTRUCTION = (
    "4. Jika user menyebut pengeluaran, pemasukan, cicilan, atau tabungan (lewat teks atau foto struk/bukti bayar), "
    "respons dengan tag [CATAT_TRANSAKSI] diikuti SATU array JSON (boleh lebih dari satu transaksi), tanpa markdown/code fence. "
    'Format tiap item: {"tanggal": "YYYY-MM-DD", "grup": "Debt|Needs|Wants|Income|Savings", "kategori": "...", "jumlah": 12345, "catatan": "..."}. '
    "'grup' adalah kolom Type di Transaction List. 'kategori' HARUS dipilih persis (ejaan sama) dari [DAFTAR KATEGORI BULAN INI] pada grup yang sama. "
    "Jika tidak ada kategori yang cocok persis, pilih yang paling dekat maknanya dari daftar itu dan tulis SATU kalimat singkat SEBELUM tag yang menjelaskan pilihan tersebut. Jangan membuat kategori baru. "
    "Income = pemasukan, Savings = tabungan, Debt = cicilan/kartu kredit/paylater, sisanya Needs atau Wants. "
    "Ubah singkatan angka ke rupiah utuh: 25rb = 25000, 1,5jt = 1500000. "
    "'catatan' singkat: nama toko/barang plus keterangan dari user (contoh: 'Indomaret - belanja bulanan'). "
    "Jika tanggal tidak disebut, pakai tanggal hari ini dari [KONTEKS WAKTU]; 'kemarin' = hari ini dikurangi 1 hari. Untuk struk/bukti bayar, pakai tanggal di struk dan total akhir. "
    "Jika jumlah atau maksud transaksi tidak jelas, JANGAN memakai tag; tanyakan dulu ke user dengan singkat. "
    "Jika user hanya bertanya soal keuangan (sisa budget, total bulan ini), jawab dari [RINGKASAN KEUANGAN BULAN INI] tanpa tag; "
    "untuk 'sisa budget' utamakan angka 'menurut dashboard sheet' jika ada."
)
ADVISOR_INSTRUCTION = (
    "\n5. PERAN PENASIHAT KEUANGAN PRIBADI. Jika user bertanya soal kondisi keuangan, boros/hemat, tren, proyeksi, rasio, atau meminta saran, "
    "jawab berdasarkan [ANALISIS KEUANGAN] tanpa tag apa pun. Aturan: "
    "(a) pakai angka persis dari analisis, jangan menghitung ulang dan jangan mengarang angka; "
    "(b) jika data bulan ini masih sedikit (awal bulan), belum ada bulan pembanding, atau tab bukan bulan berjalan, katakan keterbatasan itu dengan jelas; "
    "(c) susunan jawaban: kondisi singkat 2-3 kalimat, maksimal 3 temuan penting, lalu 2-3 opsi tindakan konkret yang bisa dipilih user beserta perkiraan dampaknya dalam rupiah, bukan perintah; "
    "(d) patokan umum yang boleh dipakai: 50/30/20 (kebutuhan termasuk cicilan / wants / tabungan), total cicilan sebaiknya di bawah sekitar 30-35% pemasukan, dana darurat ideal 3-6 bulan pengeluaran wajib; "
    "saldo tabungan TIDAK diketahui, jadi sebutkan asumsi atau tanyakan singkat; "
    "(e) hindari menghakimi; gaya bahasa santai dan sopan; teks biasa tanpa ** (bold ganda), bullet pakai tanda •; "
    "(f) tutup dengan satu kalimat pendek bahwa ini gambaran dari data catatan, bukan nasihat keuangan profesional."
)
TASK_HABIT_INSTRUCTION = (
    "\n6. TUGAS (TASK MANAGER). Jika user meminta menambah tugas/to-do/deadline (bukan meeting berjam), respons dengan tag [TAMBAH_TUGAS] "
    "diikuti SATU array JSON tanpa markdown: "
    '{"tugas": "...", "due": "YYYY-MM-DD atau kosong", "priority": "...", "category": "...", "status": "...", "catatan": "..."}. '
    "Nilai priority, status, dan category HARUS persis salah satu dari [OPSI & DAFTAR TUGAS]; jika user tidak menyebut priority pakai Medium, status pakai Planned. "
    "Pilih category yang paling cocok; jika benar-benar tidak ada yang cocok, tanyakan dulu tanpa tag. "
    "Tanggal relatif ('besok', 'Jumat') diubah ke YYYY-MM-DD memakai [KONTEKS WAKTU]. "
    'Jika user menyatakan tugas sudah selesai, respons [SELESAI_TUGAS] diikuti array JSON [{"tugas": "judul tugas dari daftar tugas terbuka"}]. '
    "Jadwal meeting/acara dengan jam tetap tetap memakai tag kalender (aturan 2), bukan tugas. "
    "\n7. HABIT. Jika user melaporkan habit harian sudah atau belum dilakukan (mis. 'sudah subuh dan gym pagi'), respons [CATAT_HABIT] diikuti array JSON "
    '[{"tanggal": "YYYY-MM-DD", "habit": "nama persis dari [DAFTAR HABIT]", "selesai": true}] satu item per habit; tanpa tanggal berarti hari ini. '
    "Jika ada nominal uang, utamakan pencatatan keuangan (aturan 4), bukan habit. Jika nama habit tidak jelas, tanyakan dulu tanpa tag."
)
TRADING_INSTRUCTION = (
    "\n8. TRADING (MT5). Jika user meminta membuka posisi trading (mis. 'buy EURUSD sl 15 tp 30', 'sell gold'), "
    "tulis SATU kalimat singkat lalu tag [ORDER_TRADING] diikuti SATU objek JSON tanpa markdown: "
    '{"aksi": "BUY atau SELL", "symbol": "...", "sl_pips": angka atau null, "tp_pips": angka atau null}. '
    "symbol HARUS dari [DAFTAR SYMBOL TRADING]; 'gold'/'emas' = XAUUSD bila ada di daftar. "
    "JANGAN pernah menyatakan order sudah dieksekusi: sistem akan meminta user menekan tombol konfirmasi. "
    "Jangan menjanjikan profit. Jika arah atau symbol tidak jelas, tanyakan dulu tanpa tag. "
    "Untuk menutup posisi pakai [TUTUP_POSISI] diikuti JSON {\"ticket\": 123} atau {\"symbol\": \"EURUSD\"} atau {\"semua\": true}. "
    "Pertanyaan soal posisi, akun, atau scan market dijawab program (bukan lewat tag). "
    "Pesan belanja/nominal rupiah tetap pencatatan keuangan (aturan 4), bukan trading. "
    "PENTING: perintah seperti 'jalankan trading' / 'mulai trading' tanpa arah dan symbol BUKAN order manual. "
    "Itu perintah menyalakan radar otomatis yang memakai aturan scoring di program. "
    "JANGAN tanya arah, symbol, SL, atau TP untuk perintah itu dan jangan pakai tag order; cukup jawab satu kalimat singkat. "
    "Pengaturan skor (mis. 'ubah score 5', 'jalankan trading score 5', 'cek score') dikerjakan PROGRAM, bukan kamu. "
    "Kamu TIDAK bisa mengubah skor, menyalakan radar, atau mengeksekusi order sendiri. "
    "JANGAN pernah bilang 'sudah diatur/diterapkan/akan dieksekusi'. Kalau user bertanya soal skor atau radar, "
    "arahkan ke perintah: 'ubah score N', 'cek score', 'radar status', '/auto off'."
)
SYSTEM_INSTRUCTION = BASE_INSTRUCTION + TX_INSTRUCTION + ADVISOR_INSTRUCTION + TASK_HABIT_INSTRUCTION + TRADING_INSTRUCTION


def instruksi_lengkap():
    """Identitas (nama bot + sebutan user) di depan, lalu aturan-aturan agen."""
    return profil.instruksi() + "\n" + SYSTEM_INSTRUCTION

# Pemicu analisis mendalam (dihitung dari beberapa tab bulan). Sengaja tidak memuat kata seperti "cicilan"/"gaji"
# supaya pesan pencatatan transaksi biasa tidak memicunya. Status, budget, simulasi, debt, dan savings ditangani penasihat.py.
ANALISIS_KUNCI = re.compile(
    r"(analisis (keuangan|budget)|saran (keuangan|hemat|budget)|evaluasi|boros|bisa hemat|\btren\b|\btrend\b|proyeksi|"
    r"bandingkan|dibanding(kan)? bulan lalu|rasio|50/30/20)", re.I)

# Pemicu konteks tugas/habit (konteks hanya dibaca dari sheet kalau pesan terlihat membahasnya).
TUGAS_KUNCI = re.compile(r"(tugas|task|to-?do|deadline|tenggat|\bdue\b|ingatkan|selesai|kerjakan|dikerjakan)", re.I)
HABIT_KUNCI = re.compile(r"(habit|kebiasaan|centang)", re.I)
KATA_UMUM = {"take", "care", "work", "night", "morning", "with", "from"}
# Pemicu konteks trading (daftar symbol hanya disematkan kalau pesan terlihat membahas trading).
TRADING_KUNCI = re.compile(r"(\b(buy|sell|long|short|scalp)\b|tutup (posisi|semua|order)|close (posisi|position|all)|trading)", re.I)
# "jalankan trading" = nyalakan radar otomatis (scoring), BUKAN order manual yang butuh arah/symbol/SL/TP.
TRADING_AUTO_KUNCI = re.compile(
    r"(\b(jalan(kan)?|mulai(kan)?|aktifkan|nyalakan|start|gas)\b.{0,25}\btrading\b"
    r"|\b(open|buka|set|atur|ubah|ganti|pakai|jalan(kan)?)\b.{0,30}\bscor[e]?\s*\d+)", re.I)
BATTERY_KUNCI = re.compile(
    r"(cek\s*batr|status\s*batr|level\s*batr|baterai|battery)", re.I)
LOCK_KUNCI = re.compile(
    r"(kunci\s*laptop|lock\s*laptop|kunci\s*layar|win\s*\+\s*l)", re.I)
SYS_KUNCI = re.compile(
    r"(cek\s*(cpu|ram|disk|sistem|system)|status\s*(cpu|ram|disk|sistem))", re.I)
SS_KUNCI = re.compile(
    r"(screenshot|ss\s*layar|ambil\s*layar|capture\s*screen)", re.I)
TRADING_ORDER_MANUAL = re.compile(r"\b(buy|sell|long|short|scalp)\b", re.I)

TEMP_DIR = "temp_media"
os.makedirs(TEMP_DIR, exist_ok=True)
TELEGRAM_MAX_LEN = 4096


def get_google_services():
    SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/calendar.events']
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    return build('drive', 'v3', credentials=creds), build('sheets', 'v4', credentials=creds), build('calendar', 'v3', credentials=creds)


def simpan_ke_drive(drive_service, konten, nama):
    media = MediaIoBaseUpload(io.BytesIO(konten.encode('utf-8')), mimetype='text/plain')
    return drive_service.files().create(body={'name': nama, 'parents': [DRIVE_FOLDER_ID]}, media_body=media, fields='id').execute().get('id')


def catat_ke_sheets(sheets_service, tanggal, deskripsi, status):
    body = {'values': [[tanggal, deskripsi, status]]}
    sheets_service.spreadsheets().values().append(spreadsheetId=SHEET_ID, range='Sheet1!A:C', valueInputOption='RAW', body=body).execute()


def buat_jadwal_kalender(calendar_service, jadwal):
    event = {'summary': jadwal.get('summary'), 'description': jadwal.get('description'),
             'start': {'dateTime': jadwal.get('start_time') or jadwal.get('startTime'), 'timeZone': 'Asia/Jakarta'},
             'end': {'dateTime': jadwal.get('end_time') or jadwal.get('endTime'), 'timeZone': 'Asia/Jakarta'}}
    return calendar_service.events().insert(calendarId='primary', body=event).execute().get('htmlLink')


def baca_dari_sheets(sheets_service):
    try:
        result = sheets_service.spreadsheets().values().get(spreadsheetId=SHEET_ID, range='Sheet1!A:C').execute()
        rows = result.get('values', [])
        if not rows: return "Database masih kosong."
        recent = rows[-10:]  # Ambil 10 baris terakhir
        return "\n".join([f"- {r[0]}: {r[1]} ({r[2]})" for r in recent if len(r) >= 3])
    except Exception as e: return f"Gagal membaca database: {e}"


# Shared Telegram menu markup.
MENU_ANGKA = InlineKeyboardMarkup([[InlineKeyboardButton(str(i), callback_data=f"aksi:{kode}")
                                    for i, (kode, _) in enumerate(penasihat.MENU, 1)]])
MENU_LENGKAP = InlineKeyboardMarkup([[InlineKeyboardButton(f"{i}. {label}", callback_data=f"aksi:{kode}")]
                                     for i, (kode, label) in enumerate(penasihat.MENU, 1)])


# Shared radar score patterns.
SCORE_ANGKA = re.compile(r"\bs[ck]or[e]?\s*(?:minimum\s*|min\s*|ke\s*|jadi\s*|=\s*)?(\d{1,2})\b", re.I)
SCORE_CEK = re.compile(r"\b(cek|lihat|berapa|status)\b.{0,20}\bs[ck]or[e]?\b|\bs[ck]or[e]?\b.{0,20}\b(sekarang|saat ini|berapa)\b", re.I)
SCORE_KONTEKS = re.compile(r"\b(trading|posisi|radar|auto|otomatis|open|buka|order|market|sinyal|signal|ubah|ganti|set|atur|pakai|jalan\w*|mulai\w*|aktifkan|nyalakan)\b", re.I)
SCORE_MULAI = re.compile(r"\b(jalan\w*|mulai\w*|aktifkan|nyalakan|start|gas|open|buka)\b", re.I)

