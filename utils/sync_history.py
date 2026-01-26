# utils/sync_history.py
import os, csv
from datetime import datetime, timedelta, timezone
import MetaTrader5 as mt5
from utils.mt5_client import MT5Client

def main(days: int = 30):
    MT5Client.initialize_if_needed()
    cli = MT5Client()
    ai = mt5.account_info()
    if not ai:
        raise SystemExit("MT5 account_info indisponible.")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    deals = mt5.history_deals_get(start, end) or []

    os.makedirs("data", exist_ok=True)
    path = os.path.join("data", "deals_history.csv")
    fields = ["time","symbol","type","entry","volume","price","profit","commission","swap","magic","comment","position_id","order"]
    write_header = not os.path.exists(path)

    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header: w.writeheader()
        for d in deals:
            w.writerow({
                "time": getattr(d, "time", 0),
                "symbol": getattr(d, "symbol", ""),
                "type": getattr(d, "type", ""),
                "entry": getattr(d, "entry", ""),
                "volume": float(getattr(d, "volume", 0.0) or 0.0),
                "price": float(getattr(d, "price", 0.0) or 0.0),
                "profit": float(getattr(d, "profit", 0.0) or 0.0),
                "commission": float(getattr(d, "commission", 0.0) or 0.0),
                "swap": float(getattr(d, "swap", 0.0) or 0.0),
                "magic": getattr(d, "magic", 0),
                "comment": getattr(d, "comment", ""),
                "position_id": getattr(d, "position_id", 0),
                "order": getattr(d, "order", 0),
            })

if __name__ == "__main__":
    main(30)
