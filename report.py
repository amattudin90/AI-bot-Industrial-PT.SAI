# ============================================
# REPORT - statistik hasil trading bot (berdasarkan magic number)
# ============================================

from datetime import datetime, timedelta
import MetaTrader5 as mt5
import config

def _stat_line(name, rows):
    n = len(rows)
    wins = sum(1 for r in rows if r["net"] > 0)
    net = sum(r["net"] for r in rows)
    return "  " + str(name).ljust(10) + str(n).rjust(3) + " trade | WR " + str(round(100.0 * wins / n)).rjust(3) + "% | net " + str(round(net, 2))

def build_report(days: int = 7) -> str:
    now = datetime.now()
    deals = mt5.history_deals_get(now - timedelta(days=days), now + timedelta(days=1))
    deals = [d for d in (deals or []) if getattr(d, "magic", 0) == config.MAGIC_NUMBER]

    IN = getattr(mt5, "DEAL_ENTRY_IN", 0)
    OUT = getattr(mt5, "DEAL_ENTRY_OUT", 1)
    R_SL = getattr(mt5, "DEAL_REASON_SL", 4)
    R_TP = getattr(mt5, "DEAL_REASON_TP", 5)

    positions = {}
    for d in deals:
        p = positions.setdefault(d.position_id, {"symbol": d.symbol, "tf": "?", "score": "?", "net": 0.0, "closed": False, "exit": "?"})
        p["net"] += d.profit + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0) + getattr(d, "fee", 0.0)
        if d.entry == IN:
            parts = (d.comment or "").split("|")
            if len(parts) == 3 and parts[0] == "SHK":
                p["tf"], p["score"] = parts[1], parts[2]
        elif d.entry == OUT:
            p["closed"] = True
            p["exit"] = "SL" if d.reason == R_SL else ("TP" if d.reason == R_TP else "lain")

    closed = [p for p in positions.values() if p["closed"]]
    open_pos = [p for p in (mt5.positions_get() or []) if getattr(p, "magic", 0) == config.MAGIC_NUMBER]
    lines = ["[ LAPORAN BOT - " + str(days) + " hari terakhir ]"]

    if not closed:
        lines.append("Belum ada posisi tertutup.")
    else:
        wins = [p["net"] for p in closed if p["net"] > 0]
        losses = [p["net"] for p in closed if p["net"] <= 0]
        gp, gl = sum(wins), -sum(losses)
        net = gp - gl
        lines.append("Posisi tertutup : " + str(len(closed)) + "  (menang " + str(len(wins)) + ", kalah " + str(len(losses)) + ")")
        lines.append("Win rate        : " + str(round(100.0 * len(wins) / len(closed), 1)) + "%")
        lines.append("Net profit      : " + str(round(net, 2)))
        lines.append("Profit factor   : " + (str(round(gp / gl, 2)) if gl > 0 else "tak terhingga"))
        lines.append("Rata2 menang    : " + (str(round(gp / len(wins), 2)) if wins else "-") + " | rata2 kalah: " + (str(round(-gl / len(losses), 2)) if losses else "-"))
        lines.append("Ekspektasi/trade: " + str(round(net / len(closed), 2)))
        exits = {}
        for p in closed:
            exits[p["exit"]] = exits.get(p["exit"], 0) + 1
        lines.append("Cara keluar     : " + ", ".join(k + " " + str(v) for k, v in sorted(exits.items())))

        for title, key in (("Per symbol", "symbol"), ("Per timeframe", "tf"), ("Per skor", "score")):
            groups = {}
            for p in closed:
                groups.setdefault(p[key], []).append(p)
            lines.append(title + ":")
            for g in sorted(groups):
                lines.append(_stat_line(g, groups[g]))

        if len(closed) < 30:
            lines.append("Catatan: sampel baru " + str(len(closed)) + " trade. Butuh >= 30 sebelum menarik kesimpulan.")

    lines.append("Posisi masih terbuka: " + str(len(open_pos)) + " | floating " + str(round(sum(p.profit for p in open_pos), 2)))
    return "\n".join(lines)
