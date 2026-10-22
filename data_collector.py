# ============================================
# DATA COLLECTOR
# ============================================

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import config

def get_candles(symbol: str, timeframe: int, count: int = 300) -> pd.DataFrame:
    """
    Mengambil data candle dari MT5.
    Return DataFrame dengan kolom: time, open, high, low, close, tick_volume
    """
    # Pastikan symbol aktif di Market Watch, kalau tidak data bisa kosong
    mt5.symbol_select(symbol, True)

    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)

    if rates is None or len(rates) == 0:
        print(f"[ERROR] Gagal mengambil data {symbol} TF {timeframe}: {mt5.last_error()}")
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume']]
    df.set_index('time', inplace=True)

    return df

def get_current_price(symbol: str) -> dict:
    """Ambil harga Bid/Ask saat ini."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {}
    return {
        "bid": tick.bid,
        "ask": tick.ask,
        "last": tick.last,
        "time": datetime.fromtimestamp(tick.time)
    }

def get_symbol_info(symbol: str) -> dict:
    """Ambil informasi detail symbol."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return {}
    return {
        "digits": info.digits,
        "point": info.point,
        "spread": info.spread,
        "trade_contract_size": info.trade_contract_size,
        "volume_min": info.volume_min,
        "volume_max": info.volume_max,
        "volume_step": info.volume_step
    }

# Test
if __name__ == "__main__":
    from mt5_connector import connect_mt5, disconnect_mt5

    if connect_mt5():
        df = get_candles("EURUSD", mt5.TIMEFRAME_M5, 50)
        print(df.tail())
        print("\nCurrent price EURUSD:", get_current_price("EURUSD"))
        disconnect_mt5()
