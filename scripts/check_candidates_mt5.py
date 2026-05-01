# scripts/check_candidates_mt5.py
# FIX 2026-04-19 D5: Vérification accès MT5 aux symboles candidats shadow mode
"""
Vérifie la disponibilité des symboles candidats (DJ30, UK100, GBPUSD, USDCAD, GER40, XAGUSD)
sur le broker MT5 courant. Produit un rapport Markdown daté avec un verdict par symbole :
  - PROMOUVOIR : visible + hist + tick récent
  - AJUSTER   : visible mais données incomplètes
  - INDISPONIBLE : pas dans la liste broker

Exécution : python scripts/check_candidates_mt5.py
Sortie    : reports/candidates_mt5_<YYYY-MM-DD>.md
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CANDIDATES = ["DJ30", "UK100", "GBPUSD", "USDCAD", "GER40", "XAGUSD"]
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _fmt_filling_modes(mask: int) -> str:
    # SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2, SYMBOL_FILLING_RETURN=4 (flags bitmask)
    parts = []
    if mask & 1:
        parts.append("FOK")
    if mask & 2:
        parts.append("IOC")
    if mask & 4:
        parts.append("RETURN")
    return ",".join(parts) if parts else f"raw={mask}"


def _resolve_broker_symbol(mt5, canonical: str) -> str | None:
    """Essaye des variantes connues si le nom canonique n'existe pas directement."""
    direct = mt5.symbol_info(canonical)
    if direct is not None:
        return canonical
    variants = {
        "DJ30": ["US30", "US30.cash", "DJI30", "WallStreet30"],
        "UK100": ["UK100.cash", "FTSE100"],
        "GER40": ["DE40", "DAX40", "GER40.cash", "DE30"],
        "XAGUSD": ["SILVER"],
        "USDCAD": ["USDCAD.", "USDCADm"],
        "GBPUSD": ["GBPUSD.", "GBPUSDm"],
    }
    for v in variants.get(canonical, []):
        if mt5.symbol_info(v) is not None:
            return v
    return None


def _check_symbol(mt5, canonical: str) -> dict:
    res: dict = {"canonical": canonical, "verdict": "INDISPONIBLE", "notes": []}
    broker_name = _resolve_broker_symbol(mt5, canonical)
    if broker_name is None:
        res["notes"].append("Symbole introuvable dans la liste broker (ni variantes connues)")
        return res

    res["broker_symbol"] = broker_name
    info = mt5.symbol_info(broker_name)
    if not info:
        res["notes"].append("symbol_info a renvoyé None après résolution")
        return res

    # Activation visibility Market Watch
    activated_now = False
    if not info.visible:
        activated_now = mt5.symbol_select(broker_name, True)
        info = mt5.symbol_info(broker_name)
        if not activated_now or not info.visible:
            res["verdict"] = "AJUSTER"
            res["notes"].append(f"Échec activation Market Watch (symbol_select={activated_now})")
            return res
        res["notes"].append("Symbole activé dans Market Watch par le script")

    res["spec"] = {
        "spread": getattr(info, "spread", None),
        "point": getattr(info, "point", None),
        "digits": getattr(info, "digits", None),
        "trade_contract_size": getattr(info, "trade_contract_size", None),
        "volume_min": getattr(info, "volume_min", None),
        "volume_max": getattr(info, "volume_max", None),
        "volume_step": getattr(info, "volume_step", None),
        "trade_stops_level": getattr(info, "trade_stops_level", None),
        "trade_freeze_level": getattr(info, "trade_freeze_level", None),
        "filling_modes": _fmt_filling_modes(getattr(info, "filling_mode", 0) or 0),
        "currency_profit": getattr(info, "currency_profit", None),
        "currency_margin": getattr(info, "currency_margin", None),
    }

    # Session courante
    try:
        sess_from = getattr(info, "session_deals_from", None)
        sess_to = getattr(info, "session_deals_to", None)
        if sess_from and sess_to:
            res["spec"]["session_today"] = f"{sess_from}→{sess_to}"
    except Exception:
        pass

    # Historique M15 (100 barres)
    hist_ok = False
    try:
        bars = mt5.copy_rates_from_pos(broker_name, mt5.TIMEFRAME_M15, 0, 100)
        if bars is not None and len(bars) >= 50:
            hist_ok = True
            res["spec"]["m15_bars_read"] = int(len(bars))
        else:
            res["notes"].append(f"Historique M15 insuffisant (lu={0 if bars is None else len(bars)})")
    except Exception as e:
        res["notes"].append(f"Erreur lecture historique: {e}")

    # Tick courant
    tick_ok = False
    try:
        tick = mt5.symbol_info_tick(broker_name)
        if tick and tick.time:
            tick_dt = datetime.fromtimestamp(tick.time, tz=timezone.utc)
            age = datetime.now(timezone.utc) - tick_dt
            res["spec"]["last_tick_utc"] = tick_dt.isoformat()
            res["spec"]["tick_age_sec"] = int(age.total_seconds())
            if age <= timedelta(minutes=5):
                tick_ok = True
            else:
                res["notes"].append(f"Tick vieux de {age.total_seconds():.0f}s (>5min)")
        else:
            res["notes"].append("Aucun tick disponible")
    except Exception as e:
        res["notes"].append(f"Erreur tick: {e}")

    if hist_ok and tick_ok:
        res["verdict"] = "PROMOUVOIR"
    else:
        res["verdict"] = "AJUSTER"

    return res


def _render_markdown(results: list[dict]) -> str:
    lines = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines.append(f"# Rapport vérification symboles candidats MT5")
    lines.append("")
    lines.append(f"- Généré : {now}")
    lines.append(f"- Directive : D5 (2026-04-19)")
    lines.append(f"- Candidats testés : {', '.join(CANDIDATES)}")
    lines.append("")
    # Résumé
    lines.append("## Résumé")
    lines.append("")
    lines.append("| Symbole | Verdict | Broker name | Spread | Point | Filling |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        spec = r.get("spec") or {}
        lines.append(
            f"| {r['canonical']} | **{r['verdict']}** | "
            f"{r.get('broker_symbol', '—')} | {spec.get('spread', '—')} | "
            f"{spec.get('point', '—')} | {spec.get('filling_modes', '—')} |"
        )
    lines.append("")
    # Détail
    for r in results:
        lines.append(f"## {r['canonical']} — {r['verdict']}")
        lines.append("")
        if r.get("broker_symbol"):
            lines.append(f"- Broker name : `{r['broker_symbol']}`")
        spec = r.get("spec") or {}
        if spec:
            lines.append("- Spécifications :")
            for k, v in spec.items():
                lines.append(f"  - `{k}` : {v}")
        if r.get("notes"):
            lines.append("- Notes :")
            for n in r["notes"]:
                lines.append(f"  - {n}")
        lines.append("")
    # Gate
    gate_required = {"DJ30", "UK100", "GBPUSD"}
    promoted = {r["canonical"] for r in results if r["verdict"] == "PROMOUVOIR"}
    gate_ok = gate_required.issubset(promoted)
    lines.append("## Gate directive 5")
    lines.append("")
    lines.append(
        f"- PROMOUVOIR ≥ {{DJ30, UK100, GBPUSD}} requis : "
        f"**{'OK' if gate_ok else 'KO'}** (promus={sorted(promoted)})"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("[ERREUR] module MetaTrader5 non installé (pip install MetaTrader5)")
        return 2

    try:
        from utils.config import load_config
    except Exception as e:
        print(f"[ERREUR] chargement utils.config : {e}")
        return 2

    cfg = load_config()
    mt5_cfg = cfg.get("mt5", {}) or {}
    account = mt5_cfg.get("account")
    password = mt5_cfg.get("password")
    server = mt5_cfg.get("server")

    init_ok = mt5.initialize()
    if not init_ok:
        print(f"[ERREUR] mt5.initialize: {mt5.last_error()}")
        return 3

    if account and password and server:
        if not mt5.login(login=int(account), password=str(password), server=str(server)):
            print(f"[ERREUR] mt5.login({account}@{server}): {mt5.last_error()}")
            mt5.shutdown()
            return 4

    results = [_check_symbol(mt5, s) for s in CANDIDATES]
    mt5.shutdown()

    md = _render_markdown(results)
    out = REPORT_DIR / f"candidates_mt5_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.md"
    out.write_text(md, encoding="utf-8")
    print(f"Rapport écrit : {out}")

    for r in results:
        print(f"  - {r['canonical']:<7} -> {r['verdict']}")

    gate = {"DJ30", "UK100", "GBPUSD"}
    promoted = {r["canonical"] for r in results if r["verdict"] == "PROMOUVOIR"}
    if not gate.issubset(promoted):
        print("[GATE KO] Les directives 6/7 ne doivent pas être appliquées tant que DJ30+UK100+GBPUSD ne sont pas PROMOUVOIR.")
        return 5
    print("[GATE OK] DJ30+UK100+GBPUSD en PROMOUVOIR — feu vert pour Directives 6 à 8.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
