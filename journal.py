# ============================================
# JOURNAL - catatan setiap posisi yang dibuka
# ============================================

import csv
import os
from datetime import datetime
import config

BASE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ["waktu", "ticket", "symbol", "tf", "signal", "score", "lot", "harga", "sl", "tp", "entry_plan", "alasan"]

def log_open(sig: dict, result: dict):
    """Tambah satu baris ke jurnal. Gagal menulis tidak boleh menghentikan bot."""
    try:
        path = os.path.join(BASE, config.JOURNAL_FILE)
        new_file = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            if new_file:
                w.writerow(FIELDS)
            w.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), result.get("ticket"), sig["symbol"], sig["timeframe"],
                sig["signal"], sig["score"], result.get("volume"), result.get("price"), result.get("sl"), result.get("tp"),
                sig.get("entry"), " ; ".join(sig.get("reasons", []))
            ])
    except Exception:
        pass
