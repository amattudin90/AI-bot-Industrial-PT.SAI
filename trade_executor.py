# ============================================
# TRADE EXECUTOR
# ============================================

import MetaTrader5 as mt5
from risk_manager import calculate_lot_size, can_open_trade, check_daily_loss, position_conflict
from mt5_connector import is_real_account_blocked, is_algo_trading_enabled
from control import is_halted
import config

def _fail(msg: str) -> dict:
    return {"success": False, "message": msg}

def send_order(symbol: str, signal: str, entry: float, sl: float, tp: float, dry_run: bool = False,
               timeframe: str = None, score: int = None) -> dict:
    """
    Kirim market order ke MT5 dengan validasi berlapis.
    dry_run=True: jalankan semua validasi + hitung lot, tetapi TIDAK mengirim order.
    """
    if signal not in ("BUY", "SELL"):
        return _fail("Signal bukan BUY/SELL")

    halted, halt_msg = is_halted()
    if halted:
        return _fail(halt_msg)

    if is_real_account_blocked():
        return _fail("Akun REAL diblokir (config.ALLOW_REAL_ACCOUNT = False)")

    if not is_algo_trading_enabled():
        return _fail("Algo Trading di MT5 mati (aktifkan tombol Algo Trading)")

    if not can_open_trade():
        return _fail("Max open trades reached")

    conflict = position_conflict(symbol, signal, timeframe)
    if conflict:
        return _fail(conflict)

    if not check_daily_loss():
        return _fail("Max daily loss reached")

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return _fail(f"Symbol {symbol} not found")

    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return _fail("Failed to get tick")

    point = symbol_info.point
    digits = symbol_info.digits

    max_spread = config.rule(symbol, "max_spread")
    if symbol_info.spread > max_spread:
        return _fail(f"Spread terlalu lebar: {symbol_info.spread} point (maks {max_spread})")

    entry = float(entry)
    sl = float(sl)
    tp = float(tp)
    price = tick.ask if signal == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL

    # --- Validasi setup masih relevan (tidak basi) ---
    plan_risk = abs(entry - sl)
    buffer = plan_risk * config.ENTRY_ZONE_BUFFER
    if signal == "BUY":
        if price <= sl:
            return _fail("Harga sudah menembus SL rencana, setup batal")
        if price > entry + buffer:
            return _fail("Harga sudah terlalu jauh di atas zona entry, setup basi")
    else:
        if price >= sl:
            return _fail("Harga sudah menembus SL rencana, setup batal")
        if price < entry - buffer:
            return _fail("Harga sudah terlalu jauh di bawah zona entry, setup basi")

    # --- Validasi jarak stop (SL/TP) ---
    min_distance = symbol_info.trade_stops_level * point
    if min_distance == 0:
        min_distance = 10 * point

    pip = point * 10
    min_sl = config.rule(symbol, "min_sl_pips")
    if abs(price - sl) < min_sl * pip:
        return _fail(f"Jarak SL terlalu dekat (< {min_sl} pips)")
    if abs(price - sl) < min_distance:
        return _fail("Jarak SL lebih kecil dari stops level broker")
    if abs(tp - price) < min_distance:
        return _fail("Jarak TP lebih kecil dari stops level broker")

    price = round(price, digits)
    sl = round(sl, digits)
    tp = round(tp, digits)

    lot = calculate_lot_size(symbol, price, sl)
    if lot <= 0:
        return _fail("Invalid lot size")

    if dry_run:
        return {
            "success": True, "dry_run": True, "ticket": None, "volume": lot,
            "price": price, "sl": sl, "tp": tp,
            "message": "DRY RUN: lolos semua validasi, order TIDAK dikirim"
        }

    comment = f"SHK|{timeframe}|{score}" if timeframe else "Shakeel SMC"

    filling_modes = [
        mt5.ORDER_FILLING_IOC,
        mt5.ORDER_FILLING_FOK,
        mt5.ORDER_FILLING_RETURN
    ]

    last_error = ""
    for filling in filling_modes:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 30,
            "magic": config.MAGIC_NUMBER,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }

        result = mt5.order_send(request)

        if result is None:
            last_error = str(mt5.last_error())
            continue

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return {
                "success": True,
                "ticket": result.order,
                "volume": lot,
                "price": result.price,
                "sl": sl,
                "tp": tp,
                "message": "Order executed successfully"
            }

        last_error = f"{result.retcode} - {result.comment}"

        # 10030 = filling mode tidak didukung -> coba mode berikutnya; selain itu berhenti
        if result.retcode != 10030:
            break

    return _fail(f"Order failed: {last_error}")

def close_position(ticket: int) -> dict:
    """Tutup posisi berdasarkan ticket."""
    position = mt5.positions_get(ticket=ticket)
    if not position:
        return {"success": False, "message": "Position not found"}

    pos = position[0]
    symbol = pos.symbol
    volume = pos.volume

    if pos.type == mt5.POSITION_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(symbol).ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": config.MAGIC_NUMBER,
        "comment": "Shakeel Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        return {"success": False, "message": str(mt5.last_error())}

    return {"success": True, "message": "Position closed"}
