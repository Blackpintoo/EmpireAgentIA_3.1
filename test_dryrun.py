# test_dryrun.py
import logging, types
from orchestrator.orchestrator import Orchestrator

# --- logger lisible
logging.getLogger().setLevel(logging.INFO)

# --- Orchestrator minimal en dry-run
o = Orchestrator(symbol="BTCUSD", cfg={}, dry_run=True)

# Simule un _last_proposal incomplet (pas de "price")
o._last_proposal = {
    "symbol": "BTCUSD",
    "side": "BUY",
    # "price" manquant volontairement
    "sl": 0.0,
    "tp": 0.0,
    "lots": 0.01,
}

# Monkey-patch MT5 pour vérifier qu'il N'EST PAS appelé en dry-run
called = {"place_order": 0}
def fake_place_order(*a, **k):
    called["place_order"] += 1
    return {"retcode": 0, "order": None, "fake": True}
o.mt5.place_order = fake_place_order  # type: ignore

# Monkey-patch _log_trade_execution pour voir ce qui est envoyé
logged = {"args": None, "kwargs": None}
orig_log_trade_exec = o._log_trade_execution
def spy_log_exec(*a, **k):
    logged["args"] = a
    logged["kwargs"] = k
    return orig_log_trade_exec(*a, **k)
o._log_trade_execution = spy_log_exec  # type: ignore

# --- Exécute "un trade" en dry-run
# paramètres calculés “comme si”
direction = "BUY"
price = 12345.6
sl = 12200.0
tp = 12500.0
lots = 0.01

try:
    # appelle la méthode patchée (le return dry-run doit empêcher tout envoi MT5)
    # NB: execute_trade est async → créons une petite boucle synchrone
    import asyncio
    asyncio.run(o.execute_trade(direction))
    print("[OK] execute_trade(dry-run) terminé sans exception.")
except Exception as e:
    print("[ERR] execute_trade a levé une exception:", repr(e))

# --- Vérifs
if called["place_order"] == 0:
    print("[OK] place_order N'A PAS été appelé (dry-run).")
else:
    print("[ERR] place_order a été appelé", called["place_order"], "fois (NE DOIT PAS en dry-run).")

# On attend que _log_trade_execution ait reçu des valeurs fusionnées
print("[INFO] _log_trade_execution args:", logged["args"])
print("[INFO] _log_trade_execution kwargs:", logged["kwargs"])

# Vérifie que 'price' est bien présent et numérique
try:
    price_arg = logged["args"][2]  # symbol, side, price, sl, tp, lots, ...
    assert isinstance(price_arg, (int, float)), "price doit être float/int"
    print("[OK] 'price' fourni à _log_trade_execution:", price_arg)
except Exception as e:
    print("[ERR] 'price' manquant ou invalide dans _log_trade_execution:", repr(e))

print("[DONE] Tests terminés.")
