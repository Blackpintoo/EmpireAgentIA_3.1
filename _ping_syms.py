import MetaTrader5 as mt5
from utils.mt5_client import MT5Client
from utils.config import get_enabled_symbols

# Si l'orchestrateur s'attend à initialize_if_needed, expose l'alias
if not hasattr(MT5Client, "initialize_if_needed"):
    MT5Client.initialize_if_needed = MT5Client._initialize_if_needed

mt = MT5Client()

def n_bars(obj) -> int:
    """Retourne la taille pour ndarray / liste, sinon 0."""
    try:
        sz = getattr(obj, "size", None)
        if sz is not None:
            return int(sz)
        return int(len(obj))
    except Exception:
        return 0

def check(sym: str):
    real = MT5Client.resolve_symbol_name(sym)
    try:
        mt.ensure_symbol(real)
        tf = MT5Client.parse_timeframe("M5")
        bars = mt.fetch_ohlc(real, tf, 50)
        n = n_bars(bars)
        print(f"[{sym}] -> real='{real}' | OHLC M5: {n} bars")
    except Exception as e:
        print(f"[{sym}] ERREUR: {e}")
        if sym.upper().startswith("LINK"):
            try:
                hints = [s.name for s in (mt5.symbols_get() or [])
                         if ("LINK" in s.name.upper() or "LNK" in s.name.upper())]
                if hints:
                    print("  Candidats broker:", ", ".join(sorted(hints)[:10]))
            except Exception:
                pass

for s in get_enabled_symbols():
    check(s)
