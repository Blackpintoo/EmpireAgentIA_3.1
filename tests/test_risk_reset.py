# tests/test_risk_reset.py
import os, sys, types
from datetime import datetime, timezone
import pytz

# --- Bootstrap chemin projet (ajoute la racine au sys.path) ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Deal factice (mimique de l'objet retourné par mt5.history_deals_get)
class Deal:
    def __init__(self, symbol: str, profit: float, ts_utc_seconds: float):
        self.symbol = symbol
        self.profit = profit
        # Dans MT5, .time est un timestamp (seconds since epoch, UTC)
        self.time = ts_utc_seconds

def test_daily_loss_reset_and_limit(monkeypatch):
    # --- 1) Prépare le faux backend MT5 AVANT d'importer RiskManager
    fake_deals = []

    def fake_history_deals_get(start_dt, end_dt):
        # start_dt / end_dt sont des datetimes aware UTC (comme MT5)
        start_ts = start_dt.timestamp()
        end_ts = end_dt.timestamp()
        return [d for d in fake_deals if start_ts <= d.time <= end_ts]

    # Patch du module utils.risk_manager: remplace la variable mt5 par notre stub
    import utils.risk_manager as rm_mod
    rm_mod.mt5 = types.SimpleNamespace(history_deals_get=fake_history_deals_get)

    # --- 2) Maintenant on peut importer RiskManager et l'instancier
    from utils.risk_manager import RiskManager

    rm = RiskManager(symbol="BTCUSD")
    rm._tz = pytz.timezone("Europe/Zurich")
    rm.get_equity = lambda: 10000.0  # 10'000 CHF d'equity
    # S'il utilise un mapping broker, on force pour matcher le deal
    if not hasattr(rm, "broker_symbol") or not rm.broker_symbol:
        rm.broker_symbol = "BTCUSD"

    # 3) Aucun deal aujourd'hui => perte du jour 0 et pas de limite atteinte
    assert abs(rm._today_loss_pct()) < 1e-9
    assert rm.is_daily_limit_reached() is False

    # 4) Ajoute une perte aujourd'hui de -250 CHF (~ -2.5% sur 10k)
    now_utc_ts = datetime.now(timezone.utc).timestamp()
    fake_deals.append(Deal("BTCUSD", -250.0, now_utc_ts))

    loss_pct = rm._today_loss_pct()
    print("today_loss_pct:", loss_pct)  # attendu ≈ -0.025
    assert loss_pct < 0

    # 5) Seuil 2% => la limite journalière doit être atteinte
    rm.daily_loss_limit_pct = 0.02
    assert rm.is_daily_limit_reached() is True
