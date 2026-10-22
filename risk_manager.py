# ============================================
# RISK MANAGER
# ============================================

import math
from datetime import datetime, timedelta
import MetaTrader5 as mt5
import config

def calculate_lot_size(symbol: str, entry: float, sl: float, risk_percent: float = None) -> float:
    """
    Hitung lot size berdasarkan risk percent.
    Return 0.0 jika tidak aman / tidak bisa dihitung.
    """
    if risk_percent is None:
        risk_percent = config.RISK_PERCENT

    account = mt5.account_info()
    if account is None:
        return 0.0

    risk_amount = account.balance * (risk_percent / 100)

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return 0.0

    tick_value = symbol_info.trade_tick_value
    tick_size = symbol_info.trade_tick_size
    if tick_size == 0 or tick_value == 0:
        return 0.0

    sl_distance = abs(entry - sl)
    if sl_distance == 0:
        return 0.0

    # Kerugian (dalam mata uang akun) untuk 1 lot jika SL kena
    money_per_lot = (sl_distance / tick_size) * tick_value
    if money_per_lot == 0:
        return 0.0

    raw_lot = risk_amount / money_per_lot

    # Bulatkan KE BAWAH ke volume step supaya risiko tidak melebihi target
    step = symbol_info.volume_step
    lot = math.floor(raw_lot / step + 1e-9) * step

    # Lot minimum broker: boleh dipakai hanya jika risikonya masih wajar
    if lot < symbol_info.volume_min:
        lot = symbol_info.volume_min
        actual_risk = lot * money_per_lot
        if actual_risk > risk_amount * config.MAX_RISK_OVERSHOOT:
            print(f"[RISK] Lot minimum {lot} berisiko {actual_risk:.2f} (target {risk_amount:.2f}), order ditolak")
            return 0.0

    lot = min(lot, symbol_info.volume_max, config.MAX_LOT)
    return round(lot, 2)

def can_open_trade() -> bool:
    """Cek apakah masih boleh open trade baru."""
    positions = mt5.positions_get()
    if positions is None:
        return True

    open_count = len(positions)
    if open_count >= config.MAX_OPEN_TRADES:
        print(f"[RISK] Sudah mencapai max open trades ({config.MAX_OPEN_TRADES})")
        return False

    return True

def position_conflict(symbol: str, signal: str, timeframe: str = None):
    """
    Return None jika aman, atau teks alasan jika posisi baru bentrok dengan posisi yang ada.
    """
    from mt5_connector import is_netting_account
    positions = mt5.positions_get(symbol=symbol)
    positions = [p for p in (positions or []) if p.symbol == symbol]
    if not positions:
        return None
    if config.ONE_POSITION_PER_SYMBOL or is_netting_account():
        return f"Sudah ada posisi terbuka di {symbol}"
    if len(positions) >= config.MAX_POSITIONS_PER_SYMBOL:
        return f"Batas {config.MAX_POSITIONS_PER_SYMBOL} posisi per symbol tercapai di {symbol}"
    want = getattr(mt5, "POSITION_TYPE_BUY", 0) if signal == "BUY" else getattr(mt5, "POSITION_TYPE_SELL", 1)
    for p in positions:
        if p.type != want and not config.ALLOW_OPPOSITE_ON_SYMBOL:
            return f"Ada posisi berlawanan di {symbol} (hedge dilarang)"
        comment = getattr(p, "comment", "") or ""
        if getattr(p, "magic", None) == config.MAGIC_NUMBER and not comment.startswith("SHK|"):
            return f"Posisi lama (tanpa tag setup) masih terbuka di {symbol}"
        if timeframe and ("|" + timeframe + "|") in comment:
            return f"Setup {symbol} {timeframe} sudah terbuka"
    return None

def check_daily_loss() -> bool:
    """
    Cek batas rugi harian: profit/loss yang sudah ditutup hari ini + floating.
    Return False jika batas tercapai atau data akun tidak tersedia.
    """
    account = mt5.account_info()
    if account is None:
        return False

    closed_today = 0.0
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        deals = mt5.history_deals_get(start, datetime.now() + timedelta(days=1))
    except Exception:
        deals = None
    if deals:
        trade_types = (getattr(mt5, "DEAL_TYPE_BUY", 0), getattr(mt5, "DEAL_TYPE_SELL", 1))
        for d in deals:
            if d.type in trade_types:
                closed_today += d.profit + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0) + getattr(d, "fee", 0.0)

    total_pnl = closed_today + account.profit
    start_balance = account.balance - closed_today
    if start_balance <= 0:
        return False

    if total_pnl < -(start_balance * config.MAX_DAILY_LOSS / 100):
        print(f"[RISK] Max daily loss tercapai (PnL hari ini {total_pnl:.2f})")
        return False
    return True


def preview_lots(symbols, sl_pips: float = 10.0) -> str:
    """Tabel perkiraan lot untuk SL tertentu, tanpa membuka order (untuk mengatur RISK_PERCENT / MAX_LOT)."""
    account = mt5.account_info()
    if account is None:
        return "Info akun tidak tersedia"
    risk_amount = account.balance * config.RISK_PERCENT / 100
    lines = ["[ PREVIEW LOT ] saldo " + str(round(account.balance, 2)) + " | RISK_PERCENT " + str(config.RISK_PERCENT) +
             "% (= " + str(round(risk_amount, 2)) + ") | MAX_LOT " + str(config.MAX_LOT) + " | SL " + str(sl_pips) + " pip"]
    for sym in symbols:
        info = mt5.symbol_info(sym)
        if info is None or not info.trade_tick_size or not info.trade_tick_value:
            continue
        sl_dist = sl_pips * info.point * 10
        per_lot = (sl_dist / info.trade_tick_size) * info.trade_tick_value
        if per_lot <= 0:
            continue
        step = info.volume_step
        by_risk = math.floor(risk_amount / per_lot / step + 1e-9) * step
        used = max(0.0, min(by_risk, info.volume_max, config.MAX_LOT))
        note = "  <- dibatasi MAX_LOT" if by_risk > config.MAX_LOT else ""
        lines.append("  " + sym.ljust(8) + "lot sesuai risiko " + str(round(by_risk, 2)).rjust(7) + " | dipakai " + str(round(used, 2)).rjust(5) + note)
    return "\n".join(lines)
