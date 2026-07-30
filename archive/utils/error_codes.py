# utils/error_codes.py
MT5_RETCODES = {
    10009: "TRADE_RETCODE_DONE",
    10016: "TRADE_RETCODE_INVALID_STOPS",
    10018: "TRADE_RETCODE_MARKET_CLOSED",
    10030: "TRADE_RETCODE_INVALID_FILL",
}

def classify_mt5_error(retcode: int) -> str:
    return MT5_RETCODES.get(int(retcode), f"RET_{retcode}")
