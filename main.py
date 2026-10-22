# ============================================
# MAIN - Entry Point untuk Shakeel
# Mode: status | scan | dry | trade | trade-high | radar | radar-dry | radar-loop | radar-start | radar-stop | radar-status | radar-log | halt (stop-today) | resume | report | lot
# ============================================

import os
import sys
import traceback
from datetime import datetime

# Paksa output UTF-8 (WSL -> Windows Python memakai cp1252 secara default)
os.environ.setdefault("PYTHONUTF8", "1")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import MetaTrader5 as mt5
import config
from mt5_connector import connect_mt5, disconnect_mt5
from signal_engine import generate_signals, print_signals
from trade_executor import send_order
from journal import log_open
from radar import run_radar_once, run_radar_loop
from report import build_report
import control
from risk_manager import preview_lots

def _log(text: str):
    """Catat ke file log (UTF-8). Gagal menulis log tidak boleh menghentikan bot."""
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, config.LOG_FILE), "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " | " + text + "\n")
    except Exception:
        pass

def run_status():
    """Cek koneksi, akun, dan posisi terbuka (tanpa scan, tanpa order)."""
    positions = mt5.positions_get()
    print("\n[MODE] Status")
    print(control.status_text())
    print("Posisi terbuka : " + str(len(positions) if positions else 0))
    for p in (positions or []):
        print("  - " + p.symbol + " | ticket " + str(p.ticket) + " | vol " + str(p.volume) + " | profit " + str(p.profit))

def run_scan_only():
    """Hanya scan + tampilkan signal (tidak open posisi)."""
    print("\n[MODE] Scan Only")
    signals = generate_signals()
    print_signals(signals)
    return signals

def run_auto_trade(min_score: int = 5, dry_run: bool = False):
    """Scan + otomatis open posisi jika score >= min_score (dry_run: validasi saja)."""
    label = "DRY RUN" if dry_run else "Auto Trade"
    print("\n[MODE] " + label + " (min score: " + str(min_score) + ")")
    signals = generate_signals()
    print_signals(signals)

    candidates = [s for s in signals if s["signal"] in ["BUY", "SELL"] and s["score"] >= min_score]
    candidates.sort(key=lambda x: x["score"], reverse=True)

    executed = 0
    opened_lines = []
    for s in candidates:
        print("\n-> Mencoba " + ("(dry) " if dry_run else "") + "open " + s["signal"] + " " + s["symbol"] + " " + s["timeframe"] + "...")
        result = send_order(
            symbol=s["symbol"],
            signal=s["signal"],
            entry=s["entry"],
            sl=s["sl"],
            tp=s["tp"],
            dry_run=dry_run,
            timeframe=s["timeframe"],
            score=s["score"]
        )
        if result["success"]:
            if dry_run:
                print("  LOLOS (dry run) | Lot: " + str(result["volume"]) + " | SL: " + str(result["sl"]) + " | TP: " + str(result["tp"]))
                _log("DRY OK " + s["signal"] + " " + s["symbol"] + " " + s["timeframe"] + " lot " + str(result["volume"]))
            else:
                print("  BERHASIL! Ticket: " + str(result["ticket"]) + " | Lot: " + str(result["volume"]))
                log_open(s, result)
                _log("OPEN " + s["signal"] + " " + s["symbol"] + " " + s["timeframe"] + " ticket " + str(result["ticket"]) + " lot " + str(result["volume"]) + " sl " + str(result["sl"]) + " tp " + str(result["tp"]))
            executed += 1
            if not dry_run:
                opened_lines.append("DIBUKA " + s["signal"] + " " + s["symbol"] + " " + s["timeframe"] + " ticket " + str(result["ticket"]) + " lot " + str(result["volume"]))
        else:
            print("  GAGAL: " + result["message"])
            _log("SKIP " + s["signal"] + " " + s["symbol"] + " " + s["timeframe"] + " : " + result["message"])

    print("\nTotal posisi " + ("lolos validasi: " if dry_run else "dibuka: ") + str(executed))
    if not dry_run:
        print("=== HASIL (laporkan persis seperti ini) ===")
        print("\n".join(opened_lines) if opened_lines else "Tidak ada posisi baru dibuka.")
    return executed

def main():
    mode = "scan"
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()

    # Perintah kontrol: TIDAK butuh MT5 (kill switch harus selalu bisa dipakai)
    num = lambda i: (float(sys.argv[i]) if len(sys.argv) > i else None)
    if mode in ("halt", "stop-today"):
        print(control.halt_today())
        _log("HALT aktif (STOP trading hari ini)")
        return
    if mode == "resume":
        print(control.resume())
        _log("RESUME (halt dicabut)")
        return
    if mode == "radar-stop":
        print(control.radar_stop())
        return
    if mode == "radar-status":
        print(control.radar_status())
        return
    if mode == "radar-log":
        print(control.tail_log(int(sys.argv[2]) if len(sys.argv) > 2 else 25))
        return
    if mode == "radar-start":
        ms = num(3)
        print(control.radar_start(num(2), int(ms) if ms else None))
        return

    if not connect_mt5():
        print("Gagal koneksi MT5")
        sys.exit(1)

    exit_code = 0
    try:
        if mode == "status":
            run_status()
        elif mode == "scan":
            run_scan_only()
        elif mode == "dry":
            run_auto_trade(min_score=5, dry_run=True)
        elif mode == "trade":
            run_auto_trade(min_score=5)
        elif mode == "trade-high":
            run_auto_trade(min_score=6)
        elif mode == "radar":
            ms = num(2)
            run_radar_once(min_score=int(ms) if ms else None)
        elif mode == "radar-dry":
            run_radar_once(dry_run=True)
        elif mode == "radar-loop":
            ms = num(3)
            run_radar_loop(hours=num(2), min_score=int(ms) if ms else None)
        elif mode == "lot":
            sl_pips = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
            print(preview_lots(config.RADAR_SYMBOLS[:8] + config.METALS_SYMBOLS, sl_pips))
        elif mode == "report":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            print(build_report(days))
        else:
            print("Mode tidak dikenal. Gunakan: status | scan | dry | trade | trade-high | radar | radar-dry | radar-loop | radar-start | radar-stop | radar-status | radar-log | halt (stop-today) | resume | report | lot")
            exit_code = 2
    except Exception:
        print("[ERROR] Terjadi kesalahan saat menjalankan mode " + mode)
        traceback.print_exc()
        _log("ERROR mode " + mode + " : " + traceback.format_exc().splitlines()[-1])
        exit_code = 1
    finally:
        disconnect_mt5()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
