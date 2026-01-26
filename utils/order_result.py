# utils/order_result.py
from __future__ import annotations

def to_dict(res) -> dict:
    """Normalise un résultat d'ordre MT5 en dict, qu'il vienne de mt5.order_send ou d'un wrapper."""
    if res is None:
        return {"retcode": None, "comment": "no_result"}
    if isinstance(res, dict):
        return res
    # objet OrderSendResult (MetaTrader5)
    out = {
        "retcode": getattr(res, "retcode", None),
        "comment": getattr(res, "comment", ""),
        "order": getattr(res, "order", None),
        "deal": getattr(res, "deal", None),
        "volume": getattr(res, "volume", None),
        "price": getattr(res, "price", None),
        "request_id": getattr(res, "request_id", None),
    }
    ext = getattr(res, "retcode_external", None)
    if ext is not None:
        out["retcode_external"] = ext
    return out

def get(res, key, default=None):
    """Accès sûr à un champ du résultat normalisé ou brut."""
    try:
        if isinstance(res, dict):
            return res.get(key, default)
        return getattr(res, key, default)
    except Exception:
        return default
