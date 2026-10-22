# ============================================
# MARKET SCANNER - SMC / ICT Style
# Liquidity | FVG | CHoCH | Order Block
# ============================================

import pandas as pd
import numpy as np
from data_collector import get_candles
import MetaTrader5 as mt5
import config

def is_bullish(c):
    return c['close'] > c['open']

def is_bearish(c):
    return c['close'] < c['open']

def body(c):
    return abs(c['close'] - c['open'])

def detect_fvg(df, lookback=60):
    fvgs = []
    data = df.tail(lookback)

    for i in range(2, len(data)):
        c0 = data.iloc[i-2]
        c2 = data.iloc[i]

        if c2['low'] > c0['high']:
            fvgs.append({
                "type": "Bullish FVG",
                "time": str(data.index[i]),
                "top": round(c2['low'], 5),
                "bottom": round(c0['high'], 5),
                "size": round(c2['low'] - c0['high'], 5)
            })

        if c2['high'] < c0['low']:
            fvgs.append({
                "type": "Bearish FVG",
                "time": str(data.index[i]),
                "top": round(c0['low'], 5),
                "bottom": round(c2['high'], 5),
                "size": round(c0['low'] - c2['high'], 5)
            })
    return fvgs

def detect_order_blocks(df, lookback=80):
    obs = []
    data = df.tail(lookback)

    for i in range(6, len(data)-2):
        if (data.iloc[i]['close'] > data.iloc[i-1]['high'] and
            body(data.iloc[i]) > body(data.iloc[i-1]) * 1.4):
            for j in range(i-1, max(i-7, 0), -1):
                if is_bearish(data.iloc[j]):
                    obs.append({
                        "type": "Bullish OB",
                        "time": str(data.index[j]),
                        "top": round(data.iloc[j]['high'], 5),
                        "bottom": round(data.iloc[j]['low'], 5)
                    })
                    break

        if (data.iloc[i]['close'] < data.iloc[i-1]['low'] and
            body(data.iloc[i]) > body(data.iloc[i-1]) * 1.4):
            for j in range(i-1, max(i-7, 0), -1):
                if is_bullish(data.iloc[j]):
                    obs.append({
                        "type": "Bearish OB",
                        "time": str(data.index[j]),
                        "top": round(data.iloc[j]['high'], 5),
                        "bottom": round(data.iloc[j]['low'], 5)
                    })
                    break
    return obs

def detect_choch(df):
    chochs = []
    data = df.tail(100).copy()

    data['sh'] = data['high'][(data['high'] == data['high'].rolling(11, center=True).max())]
    data['sl'] = data['low'][(data['low'] == data['low'].rolling(11, center=True).min())]

    swings = []
    for idx, row in data.iterrows():
        if not pd.isna(row['sh']):
            swings.append({"t": "H", "p": row['sh'], "time": idx})
        if not pd.isna(row['sl']):
            swings.append({"t": "L", "p": row['sl'], "time": idx})

    for i in range(2, len(swings)):
        a, b, c = swings[i-2], swings[i-1], swings[i]

        if a['t'] == "H" and b['t'] == "L" and c['t'] == "H" and c['p'] > a['p']:
            chochs.append({
                "type": "Bullish CHoCH",
                "time": str(c['time']),
                "price": round(c['p'], 5)
            })

        if a['t'] == "L" and b['t'] == "H" and c['t'] == "L" and c['p'] < a['p']:
            chochs.append({
                "type": "Bearish CHoCH",
                "time": str(c['time']),
                "price": round(c['p'], 5)
            })
    return chochs

def detect_liquidity(df, tol=0.00012):
    liq = []
    data = df.tail(50)
    highs = data['high'].values
    lows = data['low'].values
    times = data.index

    for i in range(len(data)-3):
        if abs(highs[i] - highs[i+1]) <= tol or abs(highs[i] - highs[i+2]) <= tol:
            liq.append({
                "type": "Equal Highs (SSL)",
                "time": str(times[i]),
                "price": round(highs[i], 5)
            })
        if abs(lows[i] - lows[i+1]) <= tol or abs(lows[i] - lows[i+2]) <= tol:
            liq.append({
                "type": "Equal Lows (BSL)",
                "time": str(times[i]),
                "price": round(lows[i], 5)
            })

    seen = set()
    unique = []
    for x in liq:
        key = (x['type'], x['price'])
        if key not in seen:
            seen.add(key)
            unique.append(x)
    return unique

def scan_symbol(symbol, tf_name="M5"):
    tf = config.TIMEFRAMES[tf_name]
    df = get_candles(symbol, tf, config.CANDLES_COUNT)

    if df.empty:
        return {"symbol": symbol, "tf": tf_name, "error": "No data"}

    liq_tol = 0.00012
    if config.LIQUIDITY_SCALE_BY_POINT:
        sym_info = mt5.symbol_info(symbol)
        if sym_info is not None and sym_info.point > 0:
            liq_tol = config.LIQUIDITY_TOL_POINTS * sym_info.point

    return {
        "symbol": symbol,
        "tf": tf_name,
        "time": str(df.index[-1]),
        "close": round(df['close'].iloc[-1], 5),
        "fvg": detect_fvg(df)[-4:],
        "ob": detect_order_blocks(df)[-4:],
        "choch": detect_choch(df)[-3:],
        "liquidity": detect_liquidity(df, liq_tol)[-4:]
    }

def scan_all(symbols=None, verbose=True):
    results = []
    for symbol in (symbols or config.SYMBOLS):
        for tf in config.TIMEFRAMES:
            if verbose:
                print("  -> Scanning " + symbol + " " + tf + " ...")
            results.append(scan_symbol(symbol, tf))
    return results

def print_result(r):
    print("\n" + "=" * 65)
    print("  " + r['symbol'] + "  |  " + r['tf'] + "  |  " + str(r.get('time', '')) + "  |  Close: " + str(r.get('close')))
    print("=" * 65)

    if "error" in r:
        print("  Error: " + r["error"])
        return

    def show(title, items):
        print("\n  " + title + " (" + str(len(items)) + ")")
        if not items:
            print("    - tidak ada")
            return
        for x in items:
            if "top" in x:
                print("    - " + x['type'] + "  " + x['time'][11:16] + "  " + str(x['bottom']) + " - " + str(x['top']))
            else:
                print("    - " + x['type'] + "  " + x['time'][11:16] + "  @ " + str(x.get('price', '')))

    show("Fair Value Gap", r["fvg"])
    show("Order Block", r["ob"])
    show("CHoCH", r["choch"])
    show("Liquidity", r["liquidity"])

if __name__ == "__main__":
    from mt5_connector import connect_mt5, disconnect_mt5

    print("\n[ Shakeel Trading Scanner ]\n")
    if connect_mt5():
        results = scan_all()
        for r in results:
            print_result(r)
        disconnect_mt5()
        print("\n[ Scan selesai ]")