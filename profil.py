# ============================================
# PROFIL BOT - nama bot & sebutan untuk user
# Disimpan di bot_profile.json (satu folder dengan bot.py)
# ============================================

import json
import os
import re
import threading

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_profile.json")
_kunci = threading.Lock()

# Nilai awal bisa diatur lewat .env: BOT_NAME dan BOT_PANGGIL
_DEFAULT = {
    "nama": os.environ.get("BOT_NAME", "Asisten"),
    "panggil": os.environ.get("BOT_PANGGIL", "Boss"),
}


def bersihkan(teks, maks=24):
    """Hanya huruf/angka/spasi/. _ - ' (supaya aman masuk ke instruksi AI). None kalau tidak valid."""
    teks = re.sub(r"\s+", " ", str(teks or "")).strip()
    if not teks or len(teks) > maks:
        return None
    if not re.fullmatch(r"[\w .'\-]+", teks, re.UNICODE):
        return None
    return teks


def muat():
    data = dict(_DEFAULT)
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            tersimpan = json.load(f)
        for k in ("nama", "panggil"):
            v = bersihkan(tersimpan.get(k))
            if v:
                data[k] = v
    except (OSError, ValueError):
        pass
    return data


def simpan(nama=None, panggil=None):
    """Simpan nama/sebutan baru. Return nilai yang tersimpan, atau None kalau input tidak valid."""
    with _kunci:
        data = muat()
        if nama is not None:
            v = bersihkan(nama)
            if not v:
                return None
            data["nama"] = v
        if panggil is not None:
            v = bersihkan(panggil)
            if not v:
                return None
            data["panggil"] = v
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return data


def nama():
    return muat()["nama"]


def panggil():
    return muat()["panggil"]


def instruksi():
    """Kalimat identitas yang ditaruh di depan system instruction Gemini."""
    d = muat()
    return (
        f'Nama kamu adalah "{d["nama"]}". Panggil user dengan sebutan "{d["panggil"]}" secara natural '
        f"(tidak perlu di setiap kalimat). Sebut namamu hanya jika ditanya atau saat perkenalan."
    )
