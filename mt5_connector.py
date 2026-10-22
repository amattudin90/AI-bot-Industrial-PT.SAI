# ============================================
# MT5 CONNECTOR - Source of Truth
# ============================================

import time
import MetaTrader5 as mt5
import config

def account_type_name(info) -> str:
    """Nama tipe akun: DEMO / CONTEST / REAL."""
    mode = getattr(info, "trade_mode", None)
    if mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0):
        return "DEMO"
    if mode == getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1):
        return "CONTEST"
    if mode == getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2):
        return "REAL"
    return "UNKNOWN"

def is_netting_account() -> bool:
    """True jika akun NETTING/EXCHANGE (hanya 1 posisi per symbol, order berlawanan akan menutup posisi)."""
    info = mt5.account_info()
    mode = getattr(info, "margin_mode", None)
    return mode in (getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_NETTING", 0), getattr(mt5, "ACCOUNT_MARGIN_MODE_EXCHANGE", 1))

def is_real_account_blocked() -> bool:
    """True jika akun REAL dan config belum mengizinkan trading di akun REAL."""
    info = mt5.account_info()
    if info is None:
        return True
    return account_type_name(info) == "REAL" and not config.ALLOW_REAL_ACCOUNT

def is_algo_trading_enabled() -> bool:
    """Cek tombol Algo Trading di terminal MT5."""
    term = mt5.terminal_info()
    return bool(term is not None and term.trade_allowed)

def connect_mt5(retries: int = 3, wait: int = 5) -> bool:
    """
    Menghubungkan ke MetaTrader 5 (dengan retry, karena MT5 butuh waktu login).
    Return True jika berhasil, False jika gagal.
    """
    account_info = None
    for attempt in range(1, retries + 1):
        if mt5.initialize():
            account_info = mt5.account_info()
            if account_info is not None:
                break
            print(f"[WARN] Percobaan {attempt}/{retries}: info akun belum tersedia: {mt5.last_error()}")
            mt5.shutdown()
        else:
            print(f"[WARN] Percobaan {attempt}/{retries}: initialize gagal: {mt5.last_error()}")
        if attempt < retries:
            time.sleep(wait)

    if account_info is None:
        print("[ERROR] Gagal terhubung ke MT5. Pastikan MT5 terbuka dan sudah login (jalankan mt5-open dulu).")
        return False

    print("=" * 50)
    print("MT5 CONNECTED SUCCESSFULLY")
    print("=" * 50)
    print(f"Account        : {account_info.login}")
    print(f"Name           : {account_info.name}")
    print(f"Server         : {account_info.server}")
    print(f"Account Type   : {account_type_name(account_info)}")
    print(f"Margin Mode    : {'NETTING' if is_netting_account() else 'HEDGING'}")
    print(f"Balance        : {account_info.balance:.2f} {account_info.currency}")
    print(f"Equity         : {account_info.equity:.2f}")
    print(f"Margin Free    : {account_info.margin_free:.2f}")
    print(f"Leverage       : 1:{account_info.leverage}")
    print(f"Trade Allowed  : {account_info.trade_allowed}")
    print(f"Algo Trading   : {is_algo_trading_enabled()}")
    print("=" * 50)
    return True

def disconnect_mt5():
    """Memutus koneksi MT5."""
    mt5.shutdown()
    print("[INFO] MT5 disconnected.")

def is_symbol_available(symbol: str) -> bool:
    """Cek apakah symbol tersedia dan bisa di-trade."""
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"[WARNING] Symbol {symbol} tidak ditemukan")
        return False

    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            print(f"[WARNING] Gagal mengaktifkan symbol {symbol}")
            return False

    return True

def get_account_summary() -> dict:
    """Ambil ringkasan akun."""
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "login": info.login,
        "balance": info.balance,
        "equity": info.equity,
        "margin_free": info.margin_free,
        "profit": info.profit,
        "currency": info.currency
    }

# Test langsung jika dijalankan
if __name__ == "__main__":
    if connect_mt5():
        for sym in config.SYMBOLS:
            status = "OK" if is_symbol_available(sym) else "NOT AVAILABLE"
            print(f"Symbol {sym}: {status}")
        disconnect_mt5()
