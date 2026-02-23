# utils/sync_history.py
# FIX 2026-02-23: Ajout déduplication raw parsing (Directive 3)
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

    # FIX 2026-02-23: write_header si fichier inexistant OU vide
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0

    # FIX 2026-02-23: Lire les deals existants avec raw parsing pour déduplication
    existing_ids = set()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("time,"):
                        continue
                    parts = line.split(",")
                    if len(parts) >= 13:
                        key = f"{parts[0]}_{parts[11]}_{parts[12]}"
                        existing_ids.add(key)
        except Exception:
            pass

    # FIX 2026-02-23: Vérifier chaque deal MT5 contre existing_ids avant écriture
    new_deals = 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header: w.writeheader()
        for d in deals:
            key = f"{getattr(d, 'time', 0)}_{getattr(d, 'position_id', 0)}_{getattr(d, 'order', 0)}"
            if key in existing_ids:
                continue
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
            new_deals += 1

    # FIX 2026-02-23: Statistiques finales
    print(f"[SYNC] {new_deals} deals ajoutés sur {len(deals)} récupérés ({len(existing_ids)} existants)")

if __name__ == "__main__":
    main(30)
