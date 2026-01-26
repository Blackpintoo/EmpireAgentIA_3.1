# verify_empire.py
import argparse
import sys
from typing import Any, Dict, List, Tuple, Optional
from pprint import pprint

from utils.config import get_enabled_symbols
from utils.logger import logger

# On importe l'Orchestrator tel qu'on l'a mis à jour
from orchestrator.orchestrator import Orchestrator, _norm


def _fmt(v: Any, nd: int = 2) -> str:
    """Formatte proprement une valeur potentiellement None."""
    if v is None:
        return "N/A"
    if isinstance(v, float):
        try:
            return f"{v:.{nd}f}"
        except Exception:
            return str(v)
    return str(v)


def _dry_viability_check(
    orch: Orchestrator,
    per_tf_signals: Dict[str, Dict[str, str]],
    global_signals: Dict[str, str],
    indicators: Dict[str, float],
    market: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any]]:
    """
    Rejoue la logique décisionnelle (sans scheduler ni Telegram) pour dire :
    - direction/score/confluence
    - SL/TP/lots (avec fallback ATR)
    - reasons de blocage s'il y en a
    """
    # 1) Calcul agrégé de base (comme dans l’orchestrateur)
    direction, score_agr, confluence, details = orch._compute_aggregate_direction(
        per_tf_signals, global_signals, indicators
    )

    price = (market or {}).get("price")
    point = float(orch.profile.get("instrument", {}).get("point", 0.01))

    if price is None:
        return False, {
            "reasons": ["pas_de_prix"],
            "direction": direction,
            "score": score_agr,
            "confluence": confluence,
            "details": details,
            "indicators": indicators,
            "market": market or {},
            "SL": None,
            "TP": None,
            "lots": None,
            "news_dir": _norm((global_signals or {}).get("news")) or "None",
            "swing_dir": _norm((global_signals or {}).get("swing")) or "None",
            "scalp_dir": _norm((global_signals or {}).get("scalping")) or "None",
            "tech_majority": f"0/0",
            "price": None,
        }

    # 2) Fast-track (mêmes règles abrégées que dans _run_agents_and_decide)
    tech_signals = (per_tf_signals or {}).get("technical", {}) or {}
    news_dir = _norm((global_signals or {}).get("news"))
    tech_majority_long = sum(1 for sig in tech_signals.values() if _norm(sig) == "LONG")
    tech_majority_short = sum(1 for sig in tech_signals.values() if _norm(sig) == "SHORT")

    if tech_majority_long >= 4 and news_dir == "LONG":
        direction = "LONG"
        score_agr = max(score_agr, 2.1)
        confluence = max(confluence, 2)
    elif tech_majority_short >= 4 and news_dir == "SHORT":
        direction = "SHORT"
        score_agr = max(score_agr, 2.1)
        confluence = max(confluence, 2)
    else:
        has_tech_dir = any(_norm(sig) in ("LONG", "SHORT") for sig in tech_signals.values())
        swing_dir = _norm((global_signals or {}).get("swing"))
        if not has_tech_dir and swing_dir and swing_dir == news_dir and swing_dir in ("LONG", "SHORT"):
            direction = swing_dir
            score_agr = max(score_agr, 1.9)
            confluence = max(confluence, 2)

    # 3) Seuils / confirmations
    reasons: List[str] = []
    if direction not in ("LONG", "SHORT"):
        reasons.append("direction_indeterminee")
    if score_agr < orch.min_score_for_proposal:
        reasons.append(f"score({score_agr:.2f})<min({orch.min_score_for_proposal:.2f})")
    if confluence < orch.min_confluence:
        reasons.append(f"confluence({confluence})<min({orch.min_confluence})")

    swing_sig = _norm((global_signals or {}).get("swing"))
    scalping_sig = _norm((global_signals or {}).get("scalping"))
    if orch.require_swing_confirm and swing_sig != direction:
        reasons.append("swing_non_confirme")
    if orch.require_scalping_entry and scalping_sig != direction:
        reasons.append("scalping_non_confirme")

    # 4) Fallback ATR → calc SL/TP/Lots s’il manque
    sl = (details or {}).get("sl")
    tp = (details or {}).get("tp")
    lots = (details or {}).get("lots")

    if direction in ("LONG", "SHORT"):
        atr = (indicators or {}).get("ATR_H1") or (indicators or {}).get("ATR_M30")
        if atr is None:
            # essaie de calculer via le helper
            atr = orch._compute_atr(orch.symbol, timeframe="H1") or orch._compute_atr(orch.symbol, timeframe="M30")

        if atr:
            if sl is None or tp is None:
                mul_sl = float(orch.ori_cfg.get("atr_sl_mult", 1.5))
                mul_tp = float(orch.ori_cfg.get("atr_tp_mult", 2.5))
                if direction == "LONG":
                    sl = price - mul_sl * atr if sl is None else sl
                    tp = price + mul_tp * atr if tp is None else tp
                else:
                    sl = price + mul_sl * atr if sl is None else sl
                    tp = price - mul_tp * atr if tp is None else tp

            if (lots is None or lots <= 0) and sl is not None:
                equity = (market or {}).get("equity", 100000.0)
                try:
                    stop_distance_points = abs(price - sl) / max(point, 1e-9)
                except Exception:
                    stop_distance_points = None
                if stop_distance_points and stop_distance_points > 0:
                    lots = orch.risk.compute_position_size(equity=equity, stop_distance_points=stop_distance_points)
                    if lots is None or lots <= 0:
                        reasons.append("lot<=0")
                else:
                    reasons.append("stop_distance_points_invalide")

    # 5) Champs critiques
    missing = []
    if direction in ("LONG", "SHORT"):
        if sl is None: missing.append("SL")
        if tp is None: missing.append("TP")
        if lots is None or lots <= 0: missing.append("lots")
        if missing:
            reasons.append(f"champs_manquants:{','.join(missing)}")

    ok = len(reasons) == 0
    report = {
        "direction": direction,
        "score": score_agr,
        "confluence": confluence,
        "price": price,
        "SL": sl,
        "TP": tp,
        "lots": lots,
        "news_dir": news_dir or "None",
        "swing_dir": swing_sig or "None",
        "scalp_dir": scalping_sig or "None",
        "tech_majority": f"{max(tech_majority_long, tech_majority_short)}/{len(tech_signals) or 0}",
        "reasons": reasons,
        "indicators": indicators or {},
        "market": market or {},
    }
    return ok, report


def _diag_empty_agents(per_tf_signals: Dict[str, Dict[str, str]], global_signals: Dict[str, str]) -> List[str]:
    reasons = []
    if not per_tf_signals and not global_signals:
        reasons.append("aucun_agent_actif_ou_sorties_vides")
    else:
        # Détail par agent
        for agent_name, tf_map in (per_tf_signals or {}).items():
            if not any(_norm(v) for v in (tf_map or {}).values()):
                reasons.append(f"{agent_name}:aucun_signal_tf")
        if not any(global_signals.values()) if global_signals else True:
            reasons.append("signaux_globaux_vides")
    return reasons


def verify_symbol(symbol: str) -> int:
    logger.info(f"[VERIFY] Démarre vérification pour {symbol}")
    orch = Orchestrator(symbol)

    # Collecte brute
    per_tf_signals, global_signals, indicators, market = orch._gather_agent_signals(symbol)

    # Rapport des signaux
    print("\n" + "=" * 80)
    print(f"SYMBOL: {symbol}")
    print("=" * 80)
    print("per_tf_signals:")
    pprint(per_tf_signals or {})
    print("\nglobal_signals:")
    pprint(global_signals or {})
    print("\nindicators:")
    pprint(indicators or {})
    print("\nmarket:")
    pprint(market or {})

    # Diagnostics rapides si vide
    diag = _diag_empty_agents(per_tf_signals, global_signals)
    p = (market or {}).get("price")
    e = (market or {}).get("equity")
    if p is None:
        diag.append("prix_mt5_non_disponible")
    if e is None:
        diag.append("equity_non_disponible")

    # Viabilité
    ok, report = _dry_viability_check(orch, per_tf_signals or {}, global_signals or {}, indicators or {}, market or {})

    print("\n" + "-" * 80)
    print("SYNTHÈSE")
    print("-" * 80)
    print(f"Direction    : {report.get('direction') or 'None'}")
    print(f"Score/Conf   : {_fmt(report.get('score'))} / {report.get('confluence', 0)}")
    print(f"Prix         : {_fmt(report.get('price'))}")
    print(f"SL / TP      : {_fmt(report.get('SL'))} / {_fmt(report.get('TP'))}")
    print(f"Lots         : {_fmt(report.get('lots'), nd=3)}")
    print(f"Tech majority: {report.get('tech_majority', '0/0')}")
    print(f"News|Swing|Sc: {report.get('news_dir', 'None')} | {report.get('swing_dir', 'None')} | {report.get('scalp_dir', 'None')}")

    if diag:
        print("\nℹ️  Diagnostics:")
        for r in diag:
            print(f"  - {r}")

    if ok:
        print("\n✅ Proposition possible (aucun blocage détecté).")
        return 0
    else:
        print("\n⛔ Proposition bloquée. Raisons :")
        reasons = report.get("reasons", [])
        if not reasons:
            print("  - (aucune raison explicite — vérifier configuration/agents)")
        else:
            for r in reasons:
                print(f"  - {r}")
        return 1


def main():
    parser = argparse.ArgumentParser(description="Vérification à sec de l'Empire (agents, confluence, risk).")
    parser.add_argument("--symbols", nargs="*", help="Liste des symboles à vérifier (sinon profiles.enabled_symbols).")
    args = parser.parse_args()

    symbols = args.symbols if args.symbols else get_enabled_symbols()
    if not symbols:
        print("Aucun symbole. Complète `enabled_symbols` dans profiles.yaml ou utilise --symbols.")
        sys.exit(2)

    overall_rc = 0
    for sym in symbols:
        rc = verify_symbol(sym)
        # on cumule le pire code retour
        overall_rc = rc if rc != 0 else overall_rc

    sys.exit(overall_rc)


if __name__ == "__main__":
    main()
