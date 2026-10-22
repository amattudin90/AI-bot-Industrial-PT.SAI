# ============================================
# RADAR SHAKEEL
# Scan banyak market, pantau setup, buka posisi saat harga masuk zona entry.
# Status: OPENED | DRY_OK | WATCH (menunggu harga ke zona) | INVALID (menembus SL)
#         COOLDOWN (zona sudah pernah dibuka) | SKIP (ditolak validasi)
# ============================================

import json
import os
import time
from datetime import datetime
import MetaTrader5 as mt5
import config
from signal_engine import generate_signals
from trade_executor import send_order
from journal import log_open
from control import heartbeat, is_halted

BASE = os.path.dirname(os.path.abspath(__file__))

_AVAILABLE = None

def _available_symbols() -> list:
    """Cek ketersediaan symbol sekali saja per proses; symbol yang tidak ada di broker dilewati."""
    global _AVAILABLE
    if _AVAILABLE is None:
        ok, missing = [], []
        for sym in config.RADAR_SYMBOLS:
            info = mt5.symbol_info(sym)
            if info is not None and (info.visible or mt5.symbol_select(sym, True)):
                ok.append(sym)
            else:
                missing.append(sym)
        if missing:
            print("[RADAR] symbol tidak tersedia di broker, dilewati: " + ", ".join(missing))
        _AVAILABLE = ok
    return _AVAILABLE

def _path(name):
    return os.path.join(BASE, name)

def _load_state() -> dict:
    try:
        with open(_path(config.STATE_FILE), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    cutoff = time.time() - config.RADAR_COOLDOWN_MIN * 60
    return {k: v for k, v in data.items() if v >= cutoff}

def _save_json(name, data):
    try:
        with open(_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=True, indent=1)
    except Exception:
        pass

def _setup_key(s) -> str:
    return s["symbol"] + "|" + s["timeframe"] + "|" + s["signal"] + "|" + str(s["entry"])

def zone_status(s):
    """Return (status, jarak_pips): IN_ZONE | WAITING | INVALID | NO_TICK."""
    tick = mt5.symbol_info_tick(s["symbol"])
    info = mt5.symbol_info(s["symbol"])
    if tick is None or info is None:
        return "NO_TICK", None
    pip = info.point * 10
    entry, sl = s["entry"], s["sl"]
    buffer = abs(entry - sl) * config.ENTRY_ZONE_BUFFER
    if s["signal"] == "BUY":
        price = tick.ask
        if price <= sl:
            return "INVALID", None
        if price > entry + buffer:
            return "WAITING", (price - entry) / pip
    else:
        price = tick.bid
        if price >= sl:
            return "INVALID", None
        if price < entry - buffer:
            return "WAITING", (entry - price) / pip
    return "IN_ZONE", abs(price - entry) / pip

def run_radar_once(dry_run: bool = False, min_score: int = None, verbose: bool = True) -> dict:
    """Satu putaran radar. Return ringkasan hitungan."""
    min_score = min_score or config.RADAR_MIN_SCORE
    symbols = _available_symbols()
    signals = generate_signals(symbols, verbose=False)
    cands = [s for s in signals if s["signal"] in ("BUY", "SELL") and s["score"] >= min_score]
    cands.sort(key=lambda x: x["score"], reverse=True)

    state = _load_state()
    radar, counts = [], {"OPENED": 0, "DRY_OK": 0, "WATCH": 0, "INVALID": 0, "COOLDOWN": 0, "SKIP": 0}

    for s in cands:
        item = {"symbol": s["symbol"], "tf": s["timeframe"], "signal": s["signal"], "score": s["score"],
                "entry": s["entry"], "sl": s["sl"], "tp": s["tp"]}
        status, dist = zone_status(s)
        key = _setup_key(s)
        if status == "WAITING":
            item["status"] = "WATCH"
            item["info"] = str(round(dist, 1)) + " pip dari zona entry"
        elif status in ("INVALID", "NO_TICK"):
            item["status"] = "INVALID"
            item["info"] = "harga menembus SL" if status == "INVALID" else "tidak ada tick"
        elif key in state:
            item["status"] = "COOLDOWN"
            item["info"] = "zona ini sudah dibuka"
        else:
            r = send_order(s["symbol"], s["signal"], s["entry"], s["sl"], s["tp"],
                           dry_run=dry_run, timeframe=s["timeframe"], score=s["score"])
            if r["success"]:
                item["status"] = "DRY_OK" if dry_run else "OPENED"
                item["info"] = "lot " + str(r["volume"]) + (" ticket " + str(r["ticket"]) if r.get("ticket") else "")
                if not dry_run:
                    state[key] = time.time()
                    log_open(s, r)
            else:
                item["status"] = "SKIP"
                item["info"] = r["message"]
        counts[item["status"]] += 1
        radar.append(item)

    _save_json(config.RADAR_FILE, {"waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "setup": radar})
    if not dry_run:
        _save_json(config.STATE_FILE, state)

    stamp = datetime.now().strftime("%H:%M:%S")
    print("[RADAR " + stamp + "] " + str(len(symbols)) + " symbol | kandidat skor>=" + str(min_score) + ": " + str(len(cands)))
    for it in radar:
        if verbose or it["status"] in ("OPENED", "DRY_OK"):
            print("  " + it["status"].ljust(9) + it["signal"] + " " + it["symbol"] + " " + it["tf"] + " (skor " + str(it["score"]) + ") " + it["info"])
    print("  Ringkas: dibuka " + str(counts["OPENED"] + counts["DRY_OK"]) + " | dipantau " + str(counts["WATCH"]) +
          " | batal " + str(counts["INVALID"]) + " | cooldown " + str(counts["COOLDOWN"]) + " | ditolak " + str(counts["SKIP"]), flush=True)
    return counts

def run_radar_loop(dry_run: bool = False, hours: float = None, min_score: int = None):
    """
    Ulangi radar tiap RADAR_INTERVAL_SEC. Berhenti jika: batas jam habis, file radar.stop dibuat,
    perintah halt ("STOP trading hari ini") aktif, atau error beruntun.
    """
    hours = hours or config.RADAR_LOOP_MAX_HOURS
    stop_path = _path(config.STOP_FILE)
    halted, halt_msg = is_halted()
    if halted:
        print("[RADAR LOOP] " + halt_msg + ". Radar tidak dijalankan.", flush=True)
        return
    if os.path.exists(stop_path):
        os.remove(stop_path)

    end = time.time() + hours * 3600
    print("[RADAR LOOP] mulai, maks " + str(hours) + " jam, interval " + str(config.RADAR_INTERVAL_SEC) +
          " dtk. Stop: perintah radar-stop / halt, atau buat file " + config.STOP_FILE, flush=True)
    errors, passes, opened = 0, 0, 0
    reason = "batas waktu"
    try:
        while time.time() < end:
            halted, halt_msg = is_halted()
            if halted:
                reason = "STOP trading hari ini"
                break
            if os.path.exists(stop_path):
                reason = "permintaan stop"
                break
            try:
                c = run_radar_once(dry_run=dry_run, min_score=min_score, verbose=False)
                passes += 1
                opened += c["OPENED"] + c["DRY_OK"]
                errors = 0
            except Exception as e:
                errors += 1
                print("[RADAR LOOP] error " + str(errors) + "/5: " + type(e).__name__ + ": " + str(e), flush=True)
                if errors >= 5:
                    reason = "terlalu banyak error beruntun"
                    break
            heartbeat({"state": "running", "pass": passes, "opened": opened})
            time.sleep(config.RADAR_INTERVAL_SEC)
    finally:
        heartbeat({"state": "stopped", "pass": passes, "opened": opened})
        print("[RADAR LOOP] berhenti (" + reason + "). Putaran: " + str(passes) + ", posisi dibuka: " + str(opened), flush=True)
