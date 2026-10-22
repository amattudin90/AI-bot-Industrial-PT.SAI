# ============================================
# SIGNAL ENGINE - SMC Confluence
# ============================================

from market_scanner import scan_all
from mt5_connector import connect_mt5, disconnect_mt5

def analyze_confluence(result):
    if "error" in result:
        return {
            "symbol": result.get("symbol", "?"),
            "timeframe": result.get("tf", "?"),
            "signal": "NO TRADE",
            "score": 0,
            "reasons": ["Data error"]
        }

    symbol = result["symbol"]
    tf = result["tf"]
    close = result["close"]

    fvg_list = result.get("fvg", [])
    ob_list = result.get("ob", [])
    choch_list = result.get("choch", [])
    liq_list = result.get("liquidity", [])

    bias = None
    last_choch = None

    if choch_list:
        last_choch = choch_list[-1]
        if "Bullish" in last_choch["type"]:
            bias = "BULLISH"
        elif "Bearish" in last_choch["type"]:
            bias = "BEARISH"

    relevant_ob = None
    if bias == "BULLISH":
        for ob in reversed(ob_list):
            if "Bullish" in ob["type"]:
                relevant_ob = ob
                break
    elif bias == "BEARISH":
        for ob in reversed(ob_list):
            if "Bearish" in ob["type"]:
                relevant_ob = ob
                break

    relevant_fvg = None
    if bias == "BULLISH":
        for f in reversed(fvg_list):
            if "Bullish" in f["type"]:
                relevant_fvg = f
                break
    elif bias == "BEARISH":
        for f in reversed(fvg_list):
            if "Bearish" in f["type"]:
                relevant_fvg = f
                break

    score = 0
    reasons = []

    if bias:
        score += 2
        reasons.append("Bias: " + str(bias) + " (dari " + last_choch["type"] + ")")

    if relevant_ob:
        score += 2
        reasons.append("Order Block: " + relevant_ob["type"] + " (" + str(relevant_ob["bottom"]) + " - " + str(relevant_ob["top"]) + ")")

    if relevant_fvg:
        score += 1
        reasons.append("FVG: " + relevant_fvg["type"] + " (" + str(relevant_fvg["bottom"]) + " - " + str(relevant_fvg["top"]) + ")")

    if liq_list:
        score += 1
        reasons.append("Liquidity terdeteksi: " + str(len(liq_list)) + " level")

    signal = "NO TRADE"
    entry = None
    sl = None
    tp = None

    if score >= 4 and bias == "BULLISH" and relevant_ob is not None:
        signal = "BUY"
        entry = relevant_ob["top"]
        sl = relevant_ob["bottom"] - (relevant_ob["top"] - relevant_ob["bottom"]) * 0.3
        tp = entry + (entry - sl) * 2.5

    elif score >= 4 and bias == "BEARISH" and relevant_ob is not None:
        signal = "SELL"
        entry = relevant_ob["bottom"]
        sl = relevant_ob["top"] + (relevant_ob["top"] - relevant_ob["bottom"]) * 0.3
        tp = entry - (sl - entry) * 2.5

    return {
        "symbol": symbol,
        "timeframe": tf,
        "signal": signal,
        "score": score,
        "bias": bias,
        "entry": round(entry, 5) if entry else None,
        "sl": round(sl, 5) if sl else None,
        "tp": round(tp, 5) if tp else None,
        "reasons": reasons,
        "close": close,
        "time": result.get("time")
    }

def generate_signals(symbols=None, verbose=True):
    if verbose:
        print("\n[ Signal Engine ] Mulai analisis confluence...\n")
    results = scan_all(symbols, verbose)
    signals = []
    from filters import apply_filters
    for r in results:
        sig = analyze_confluence(r)
        sig = apply_filters(sig)          # <-- filter baru
        signals.append(sig)
    return signals

def print_signals(signals):
    print("\n" + "=" * 70)
    print("                     HASIL SIGNAL ENGINE")
    print("=" * 70)

    has_trade = False
    for s in signals:
        if s["signal"] in ["BUY", "SELL"]:
            has_trade = True
            print("\n  >> " + s["symbol"] + " " + s["timeframe"] + " --> " + s["signal"] + " (Score: " + str(s["score"]) + ")")
            print("     Bias   : " + str(s["bias"]))
            print("     Entry  : " + str(s["entry"]))
            print("     SL     : " + str(s["sl"]))
            print("     TP     : " + str(s["tp"]))
            if "htf_bias" in s:
                print("     HTF    : " + str(s.get("htf_bias")) + " | Zone: " + str(s.get("pd_zone")) + " | Killzone: " + str(s.get("in_killzone")))
            print("     Alasan :")
            for reason in s["reasons"]:
                print("       - " + reason)
        else:
            print("\n  " + s["symbol"] + " " + s["timeframe"] + " --> NO TRADE (Score: " + str(s["score"]) + ")")

    if not has_trade:
        print("\n  Tidak ada setup berkualitas tinggi saat ini.")
    print("\n" + "=" * 70)

if __name__ == "__main__":
    if connect_mt5():
        signals = generate_signals()
        print_signals(signals)
        disconnect_mt5()