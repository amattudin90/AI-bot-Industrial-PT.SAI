# ============================================
# CONTROL - tombol stop / mulai / status untuk trading otomatis
# Perintah di sini TIDAK butuh koneksi MT5, jadi tetap jalan walau MT5 tertutup.
# ============================================

import json
import os
import subprocess
import sys
import time
from datetime import datetime
import config

BASE = os.path.dirname(os.path.abspath(__file__))

def _p(name):
    return os.path.join(BASE, name)

def _read(name):
    try:
        with open(_p(name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _write(name, data):
    with open(_p(name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=1)

# ---------- HALT ("STOP trading hari ini") ----------
def halt_today(reason: str = "") -> str:
    """Larang semua order baru sampai tengah malam (waktu PC). Radar loop ikut dihentikan."""
    _write(config.HALT_FILE, {"date": datetime.now().strftime("%Y-%m-%d"),
                              "waktu": datetime.now().strftime("%H:%M:%S"), "alasan": reason or "perintah pengguna"})
    open(_p(config.STOP_FILE), "w").close()
    return ("TRADING DIHENTIKAN untuk hari ini (" + datetime.now().strftime("%Y-%m-%d") + "). "
            "Tidak ada order baru, radar loop dihentikan. Posisi yang sudah terbuka TIDAK ditutup (tetap dijaga SL/TP).")

def is_halted():
    """Return (True, pesan) jika halt aktif untuk hari ini."""
    data = _read(config.HALT_FILE)
    if data and data.get("date") == datetime.now().strftime("%Y-%m-%d"):
        return True, "Trading dihentikan hari ini (sejak " + str(data.get("waktu")) + ")"
    return False, ""

def resume() -> str:
    for name in (config.HALT_FILE, config.STOP_FILE):
        try:
            os.remove(_p(name))
        except OSError:
            pass
    return "Halt dicabut. Order baru boleh lagi (radar loop perlu dijalankan ulang dengan radar-start)."

# ---------- radar loop di latar belakang ----------
def heartbeat(info: dict):
    info = dict(info)
    info["ts"] = time.time()
    info["waktu"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        _write(config.HEARTBEAT_FILE, info)
    except Exception:
        pass

def loop_running() -> bool:
    hb = _read(config.HEARTBEAT_FILE)
    if not hb or hb.get("state") != "running":
        return False
    return time.time() - hb.get("ts", 0) < max(config.RADAR_INTERVAL_SEC * 4, 180)

def radar_start(hours=None, min_score=None) -> str:
    halted, msg = is_halted()
    if halted:
        return "Tidak dimulai: " + msg + ". Pakai resume dulu jika ingin lanjut."
    if loop_running():
        return "Radar loop sudah berjalan (heartbeat terakhir " + str(_read(config.HEARTBEAT_FILE).get("waktu")) + ")."
    try:
        os.remove(_p(config.STOP_FILE))
    except OSError:
        pass
    cmd = [sys.executable, _p("main.py"), "radar-loop", str(hours or config.RADAR_LOOP_MAX_HOURS)]
    if min_score:
        cmd.append(str(min_score))
    log = open(_p(config.LOOP_LOG_FILE), "a", encoding="utf-8")
    env = dict(os.environ, PYTHONUTF8="1")
    kwargs = dict(stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=BASE, env=env)
    if os.name == "nt":
        base_flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(cmd, creationflags=base_flags | 0x01000000, **kwargs)   # + CREATE_BREAKAWAY_FROM_JOB
        except OSError:
            subprocess.Popen(cmd, creationflags=base_flags, **kwargs)
    else:
        subprocess.Popen(cmd, start_new_session=True, **kwargs)
    return "Radar loop dimulai di latar belakang (maks " + str(hours or config.RADAR_LOOP_MAX_HOURS) + " jam). Cek dengan radar-status."

def radar_stop() -> str:
    open(_p(config.STOP_FILE), "w").close()
    return "Perintah stop dikirim. Radar loop berhenti pada putaran berikutnya (maks sekitar " + str(config.RADAR_INTERVAL_SEC) + " detik). Posisi terbuka tidak ditutup."

def radar_status() -> str:
    hb = _read(config.HEARTBEAT_FILE)
    halted, msg = is_halted()
    lines = ["[ STATUS RADAR ]"]
    lines.append("Loop     : " + ("BERJALAN" if loop_running() else "TIDAK berjalan"))
    if hb:
        lines.append("Putaran  : " + str(hb.get("pass", "?")) + " | terakhir " + str(hb.get("waktu")) + " | dibuka sesi ini: " + str(hb.get("opened", 0)))
    lines.append("Halt     : " + (msg if halted else "tidak aktif"))
    try:
        with open(_p(config.LOOP_LOG_FILE), "r", encoding="utf-8", errors="replace") as f:
            tail = f.read().splitlines()[-4:]
        if tail:
            lines.append("Log akhir:")
            lines += ["  " + t for t in tail]
    except Exception:
        pass
    return "\n".join(lines)


# ---------- nama alternatif / bantuan ----------
def start_loop_detached(hours=None, min_score=None) -> str:
    return radar_start(hours, min_score)

def request_stop() -> str:
    return radar_stop()

def status_text() -> str:
    return radar_status()

def tail_log(n: int = 25) -> str:
    """Tampilkan n baris terakhir log radar loop."""
    try:
        with open(_p(config.LOOP_LOG_FILE), "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()[-n:]
        return "\n".join(lines) if lines else "Log kosong."
    except Exception:
        return "Belum ada log radar loop."
