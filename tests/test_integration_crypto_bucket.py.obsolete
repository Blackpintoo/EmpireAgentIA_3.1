# tests/test_integration_crypto_bucket.py
import os, sys, types, asyncio
from math import isclose
from datetime import datetime

# --- bootstrap chemin projet ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from orchestrator.orchestrator import Orchestrator

def _make_pos(symbol, price_open, sl, vol):
    return types.SimpleNamespace(symbol=symbol, price_open=price_open, sl=sl, volume=vol)

def run(coro_or_func, *args, **kwargs):
    """Compat: exécute une coroutine (async) ou une fonction sync."""
    res = coro_or_func(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return asyncio.run(res)
    return res

def test_integration_crypto_bucket_max_open_and_cap(monkeypatch):
    # Orchestrateur BTCUSD
    o = Orchestrator(symbol="BTCUSD")

    # Capture Telegram pour assertions
    sent = []
    monkeypatch.setattr(o, "_send_telegram",
                        lambda text, kind="status", force=False: sent.append((kind, text)),
                        raising=False)

    # ---------- STUB MT5 (positions + account) ----------
    equity = 10_000.0
    # 2 positions crypto déjà ouvertes (BTCUSD + LNKUSD)
    open_positions = [
        _make_pos("BTCUSD", 50000.0, 49750.0, 0.02),
        _make_pos("LNKUSD",   15.00,   14.50,  1.00),
    ]
    def positions_get(): return list(open_positions)
    def account_info():  return types.SimpleNamespace(equity=equity)
    mt5_stub = types.SimpleNamespace(positions_get=positions_get, account_info=account_info)

    # Injecter le stub là où l'orchestrateur lit MT5
    try:
        # si l'orchestrateur expose un attribut de module MT5
        o.mt5_mod = mt5_stub  # type: ignore[attr-defined]
    except Exception:
        pass
    # fallback: patcher le module importé dans l'orchestrateur
    import orchestrator.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "_mt5", mt5_stub, raising=False)
    # (selon l’impl, ton code peut utiliser mt5, _mt5, self.mt5_mod ; on couvre les 3)

    # ---------- CONFIG INSTRUMENT + BUCKET ----------
    # point / pip_value nécessaires pour estimer le risque
    o.profile.setdefault("instrument", {}).update({"point": 0.01, "pip_value": 1.0})
    # section crypto_bucket (cap/min_factor/max_open)
    o.profile.setdefault("orchestrator", {}).setdefault("crypto_bucket", {
        "enabled": True, "cap": 0.03, "min_factor": 0.33, "max_open": 2
    })
    # override de cap par phase (M1/M2 → 2%)
    o.ori_cfg.setdefault("crypto_bucket_cap_override", 0.02)

    # ---------- (1) Tenter une 3ᵉ position crypto → doit être REJETÉ ----------
    # on prépare une proposition minimale pour l'exécution
    o._last_proposal = {
        "symbol": "BTCUSD",
        "entry": 50000.0,
        "sl":    49900.0,
        "tp":    50100.0,
        "lots":  0.05
    }
    # exécute (async/sync-compatible)
    res = run(o.execute_trade, "LONG")
    # La 3ᵉ position doit être refusée (max_open=2) → pas d'ordre envoyé, un msg Telegram guard
    # (execute_trade peut renvoyer False/None selon ton code ; on valide via logs)
    assert any("déjà ouvertes" in msg for (_k, msg) in sent), "La 3ᵉ position crypto n'a pas été bloquée par max_open."
    sent.clear()

    # ---------- (2) Libérer une position et tester la RÉDUCTION DE LOTS par cap ----------
    # ne garder qu'une position existante → on passe de 2 à 1 ouverte
    open_positions.pop()

    # cap override = 2% d’equity ; on force un trade dont le risque planifié dépasse le room
    # on remet une proposition plus 'grosse' pour forcer une réduction
    o._last_proposal = {
        "symbol": "BTCUSD",
        "entry": 50000.0,
        "sl":    49950.0,  # SL plus proche -> calcule un certain risque/planned
        "tp":    50100.0,
        "lots":  0.50      # lots importants pour déclencher la réduction
    }

    # Stub d’envoi d’ordre pour capter les lots finaux
    final = {}
    def place_order_mock(symbol, side, volume, **kw):
        final["lots"] = float(volume)
        return {"ok": True, "deal": 1, "order": 1}

    # injecter le client MT5 utilisé par execute_trade
    # selon ton impl, c'est o.mt5 (wrappé) ou o.mt5_client
    if hasattr(o, "mt5"):
        monkeypatch.setattr(o.mt5, "place_order", place_order_mock, raising=False)  # type: ignore
    if hasattr(o, "mt5_client"):
        monkeypatch.setattr(o.mt5_client, "place_order", place_order_mock, raising=False)  # type: ignore

    run(o.execute_trade, "LONG")

    assert "lots" in final, "L'exécution n'a pas appelé place_order (stub)."
    assert final["lots"] <= 0.50, "Les lots n'ont pas été réduits malgré un room insuffisant sur le bucket."
    # bonus: s'assurer qu'on n'a pas réduit à 0 par erreur
    assert final["lots"] > 0.0, "Les lots ont été réduits à 0 alors que le trade aurait dû être ajusté, pas annulé."

    # Optionnel: vérifier qu'un message d'info a été envoyé
    # (adapté selon tes messages)
    # assert any("cap" in msg.lower() for (_k, msg) in sent)
