# ============================================
# FILTERS - Session, HTF Bias, Premium/Discount
# ============================================

from datetime import datetime
import pandas as pd
import MetaTrader5 as mt5
import config
from data_collector import get_candles

def is_in_killzone() -> bool:
    """True jika saat ini berada di dalam killzone yang diizinkan."""
    if not config.USE_SESSION_FILTER:
        return True
    hour = datetime.now().hour
    for start, end in config.KILLZONES:
        if start <= hour < end:
            return True
    return False

def get_htf_bias(symbol: str) -> str:
    """
    Return "BULLISH", "BEARISH", atau "NEUTRAL" berdasarkan struktur H1.
    Sederhana: bandingkan close terakhir vs midpoint range lookback.
    """
    if not config.USE_HTF_BIAS:
        return "NEUTRAL"

    import MetaTrader5 as mt5
    tf_map = {"H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    tf = tf_map.get(config.HTF_TIMEFRAME, mt5.TIMEFRAME_H1)
    df = get_candles(symbol, tf, config.HTF_LOOKBACK)
    if df.empty or len(df) < 10:
        return "NEUTRAL"

    recent = df.tail(20)
    high = recent["high"].max()
    low = recent["low"].min()
    mid = (high + low) / 2
    close = recent["close"].iloc[-1]

    if close > mid + (high - low) * 0.15:
        return "BULLISH"
    elif close < mid - (high - low) * 0.15:
        return "BEARISH"
    return "NEUTRAL"

def get_premium_discount(symbol: str, timeframe: int) -> str:
    """
    Return "PREMIUM", "DISCOUNT", atau "EQUILIBRIUM".
    """
    if not config.USE_PREMIUM_DISCOUNT:
        return "EQUILIBRIUM"

    df = get_candles(symbol, timeframe, config.PD_LOOKBACK)
    if df.empty or len(df) < 10:
        return "EQUILIBRIUM"

    high = df["high"].max()
    low = df["low"].min()
    mid = (high + low) / 2
    close = df["close"].iloc[-1]

    range_size = high - low
    if range_size == 0:
        return "EQUILIBRIUM"

    pos = (close - low) / range_size

    if pos >= 0.6:
        return "PREMIUM"
    elif pos <= 0.4:
        return "DISCOUNT"
    return "EQUILIBRIUM"

def apply_filters(signal: dict) -> dict:
    """
    Terapkan semua filter ke satu signal.
    Return signal yang sudah ditambah field filter + mungkin diubah jadi NO TRADE.
    """
    symbol = signal["symbol"]
    tf_name = signal["timeframe"]
    tf = config.TIMEFRAMES.get(tf_name, 5)

    # 1. Session filter
    in_session = is_in_killzone()
    signal["in_killzone"] = in_session

    # 2. HTF Bias
    htf_bias = get_htf_bias(symbol)
    signal["htf_bias"] = htf_bias

    # 3. Premium / Discount
    pd_zone = get_premium_discount(symbol, tf)
    signal["pd_zone"] = pd_zone

    # --- Keputusan filter ---
    reasons = signal.get("reasons", [])

    if signal["signal"] in ("BUY", "SELL"):
        # Session
        if not in_session:
            signal["signal"] = "NO TRADE"
            signal["score"] = 0
            reasons.append("Ditolak: di luar Killzone")
            signal["reasons"] = reasons
            return signal

        # HTF Bias harus sejalan
        if htf_bias != "NEUTRAL":
            if signal["signal"] == "BUY" and htf_bias != "BULLISH":
                signal["signal"] = "NO TRADE"
                signal["score"] = max(0, signal["score"] - 2)
                reasons.append("Ditolak: HTF Bias berlawanan (" + htf_bias + ")")
            elif signal["signal"] == "SELL" and htf_bias != "BEARISH":
                signal["signal"] = "NO TRADE"
                signal["score"] = max(0, signal["score"] - 2)
                reasons.append("Ditolak: HTF Bias berlawanan (" + htf_bias + ")")

        # Premium / Discount
        if signal["signal"] == "BUY" and pd_zone == "PREMIUM":
            signal["signal"] = "NO TRADE"
            signal["score"] = max(0, signal["score"] - 1)
            reasons.append("Ditolak: Buy di Premium zone")
        elif signal["signal"] == "SELL" and pd_zone == "DISCOUNT":
            signal["signal"] = "NO TRADE"
            signal["score"] = max(0, signal["score"] - 1)
            reasons.append("Ditolak: Sell di Discount zone")

    signal["reasons"] = reasons
    return signal