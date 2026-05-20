# scripts/audit_shadow_analysis.py
# Directive 14 — audit méthodologique du rapport reports/shadow_analysis_2026-05-19.md
#
# Quatre questions :
#   Q1. Borne basse de la fenêtre vs commit d727913 (fix point_value, 30 avril).
#   Q2. Position du log proposals_log.csv vs hard_filters → ré-simuler en
#       appliquant les filtres manuellement.
#   Q3. Distribution R:R théorique par symbole (min, p25, médiane, p75, max).
#   Q4. Déduplication temporelle 60 min (symbole × direction) + critère d'alerte.
#
# N'altère pas scripts/analyze_shadow_propositions.py. Sortie : reports/shadow_audit_data.json
"""
Usage:
  python scripts/audit_shadow_analysis.py
  python scripts/audit_shadow_analysis.py --no-mt5
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SHADOW_SYMBOLS = ["DJ30", "UK100", "GBPUSD", "USDCAD", "GER40", "XAGUSD", "BNBUSD", "SOLUSD"]
CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD", "LTCUSD", "BNBUSD", "ADAUSD", "SOLUSD"}

# Bornes par défaut (alignées sur le rapport initial)
DEFAULT_START = datetime(2026, 5, 1, 4, 16, 10, tzinfo=timezone.utc)
DEFAULT_END = datetime(2026, 5, 19, 23, 59, 59, tzinfo=timezone.utc)
COMMIT_D727913_TS = datetime(2026, 4, 30, 19, 43, 44, tzinfo=timezone.utc)  # heure UTC

SIM_HORIZON_HOURS = 6
SIM_BARS = SIM_HORIZON_HOURS * 12
DEDUP_WINDOW_SEC = 60 * 60  # 60 min

# Hard filters (extraits de config/config.yaml et orchestrator.py)
HF_MIN_SCORE = 3.8
HF_MIN_CONFLUENCE = 2.5
HF_MIN_RR = 1.0
HF_SHORT_SCORE_PENALTY = 1.5  # SHORT exige score >= 3.8 + 1.5 = 5.3
GLOBAL_BLOCKED_HOURS_UTC = [3, 4, 7, 10, 11, 12, 13, 14]

PROPOSALS_CSV = ROOT / "data" / "proposals_log.csv"
REPORT_DIR = ROOT / "reports"
JSON_OUT = REPORT_DIR / "shadow_audit_data.json"

BROKER_VARIANTS = {
    "DJ30": ["US30", "US30.cash", "DJI30", "WallStreet30"],
    "UK100": ["UK100.cash", "FTSE100"],
    "GER40": ["DE40", "DAX40", "GER40.cash", "DE30"],
    "XAGUSD": ["SILVER"],
    "USDCAD": ["USDCAD.", "USDCADm"],
    "GBPUSD": ["GBPUSD.", "GBPUSDm"],
}


# --- Loading -------------------------------------------------------------------

def load_proposals(start: datetime, end: datetime) -> dict:
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    with PROPOSALS_CSV.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                ts = datetime.fromisoformat(row["ts_utc"])
            except Exception:
                continue
            if not (start <= ts <= end):
                continue
            sym = row.get("symbol", "")
            if sym not in SHADOW_SYMBOLS:
                continue
            try:
                price = float(row["price"])
                sl = float(row["sl"])
                tp = float(row["tp"])
                score = float(row.get("score") or 0)
                conf = float(row.get("confluence") or 0)
            except Exception:
                continue
            side = (row.get("side") or "").upper().strip()
            if side not in ("LONG", "SHORT"):
                continue
            if not (math.isfinite(price) and math.isfinite(sl) and math.isfinite(tp)):
                continue
            if price == 0 or sl == 0 or tp == 0 or abs(price - sl) < 1e-12:
                continue
            if side == "LONG" and not (sl < price < tp):
                continue
            if side == "SHORT" and not (tp < price < sl):
                continue
            rr = abs(tp - price) / abs(price - sl)
            by_symbol[sym].append({
                "ts": ts, "side": side, "price": price, "sl": sl, "tp": tp,
                "score": score, "confluence": conf, "rr_theo": rr,
            })
    return dict(by_symbol)


# --- Hard filters --------------------------------------------------------------

def apply_hard_filters(symbol: str, p: dict) -> tuple[bool, str]:
    """Retourne (pass, raison_rejet)."""
    is_crypto = symbol in CRYPTO_SYMBOLS

    if p["score"] < HF_MIN_SCORE:
        return False, "min_score"
    if p["confluence"] < HF_MIN_CONFLUENCE:
        return False, "min_confluence"
    if p["rr_theo"] < HF_MIN_RR:
        return False, "min_rr"
    if p["side"] == "SHORT" and p["score"] < (HF_MIN_SCORE + HF_SHORT_SCORE_PENALTY):
        return False, "short_penalty"

    hour = p["ts"].hour
    if not is_crypto and hour in GLOBAL_BLOCKED_HOURS_UTC:
        return False, "blocked_hour_global"
    return True, ""


# --- MT5 helpers ---------------------------------------------------------------

def init_mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return None
    if not mt5.initialize():
        return None
    return mt5


def resolve_broker_symbol(mt5, canonical: str):
    if mt5.symbol_info(canonical) is not None:
        return canonical
    for v in BROKER_VARIANTS.get(canonical, []):
        if mt5.symbol_info(v) is not None:
            return v
    return None


def fetch_bars_range(mt5, broker_sym, dt_from, dt_to):
    rates = mt5.copy_rates_range(broker_sym, mt5.TIMEFRAME_M5, dt_from, dt_to)
    if rates is None or len(rates) == 0:
        return []
    return [{
        "time": int(r["time"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
    } for r in rates]


# --- Simulation ----------------------------------------------------------------

def simulate_first_touch(side, sl, tp, bars):
    for bar in bars:
        high, low = bar["high"], bar["low"]
        if side == "LONG":
            sl_hit = low <= sl
            tp_hit = high >= tp
        else:
            sl_hit = high >= sl
            tp_hit = low <= tp
        if sl_hit and tp_hit:
            return "SL_HIT"
        if sl_hit:
            return "SL_HIT"
        if tp_hit:
            return "TP_HIT"
    return "TIMEOUT"


def slice_bars_after(bars, times_index, ts, max_bars):
    if not bars:
        return []
    idx = bisect_left(times_index, int(ts.timestamp()))
    return bars[idx: idx + max_bars]


def simulate_pool(proposals, bars):
    times_index = [b["time"] for b in bars] if bars else []
    sl_hit = tp_hit = timeout = no_data = 0
    rr_winners = []
    for p in proposals:
        sliced = slice_bars_after(bars, times_index, p["ts"], SIM_BARS)
        if not sliced:
            no_data += 1
            continue
        r = simulate_first_touch(p["side"], p["sl"], p["tp"], sliced)
        if r == "SL_HIT":
            sl_hit += 1
        elif r == "TP_HIT":
            tp_hit += 1
            rr_winners.append(p["rr_theo"])
        else:
            timeout += 1
    decided = sl_hit + tp_hit
    wr = (tp_hit / decided) if decided else 0.0
    rr_w = sum(rr_winners) / len(rr_winners) if rr_winners else 0.0
    if 0.0 < wr < 1.0:
        rr_eff = (rr_w * wr) / (1.0 - wr)
    elif wr >= 1.0:
        rr_eff = float("inf")
    else:
        rr_eff = 0.0
    return {
        "n": len(proposals),
        "sl_hit": sl_hit,
        "tp_hit": tp_hit,
        "timeout": timeout,
        "no_bars": no_data,
        "wr_sim": wr,
        "rr_winners_avg": rr_w,
        "rr_eff_sim": rr_eff,
    }


# --- Q1 ------------------------------------------------------------------------

def q1_pre_commit_check(by_symbol):
    """UK100 et GER40 : combien de propositions ANTERIEURES au commit d727913 ?"""
    out = {}
    for s in ["UK100", "GER40"]:
        props = by_symbol.get(s, [])
        pre = [p for p in props if p["ts"] < COMMIT_D727913_TS]
        post = [p for p in props if p["ts"] >= COMMIT_D727913_TS]
        first_ts = min((p["ts"] for p in props), default=None)
        last_ts = max((p["ts"] for p in props), default=None)
        out[s] = {
            "pre_count": len(pre),
            "post_count": len(post),
            "first_proposal_ts": first_ts.isoformat() if first_ts else None,
            "last_proposal_ts": last_ts.isoformat() if last_ts else None,
            "commit_ts": COMMIT_D727913_TS.isoformat(),
        }
    return out


# --- Q2 ------------------------------------------------------------------------

def q2_hard_filters_resim(by_symbol, bars_by_symbol):
    """Pour chaque symbole, ré-évaluer après application manuelle des hard_filters."""
    out = {}
    for s in SHADOW_SYMBOLS:
        props = by_symbol.get(s, [])
        bars = bars_by_symbol.get(s, [])
        if not props:
            continue
        kept = []
        rejections = Counter()
        for p in props:
            ok, reason = apply_hard_filters(s, p)
            if ok:
                kept.append(p)
            else:
                rejections[reason] += 1
        sim = simulate_pool(kept, bars) if bars else {"n": len(kept), "sl_hit": 0, "tp_hit": 0,
                                                       "timeout": 0, "no_bars": len(kept),
                                                       "wr_sim": 0.0, "rr_winners_avg": 0.0, "rr_eff_sim": 0.0}
        out[s] = {
            "n_input": len(props),
            "n_kept_after_filters": len(kept),
            "rejection_breakdown": dict(rejections),
            "filtered_simulation": sim,
        }
    return out


# --- Q3 ------------------------------------------------------------------------

def percentile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = max(0, min(len(sorted_vals) - 1, int(round((q / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[idx]


def q3_rr_distribution(by_symbol):
    out = {}
    for s in SHADOW_SYMBOLS:
        props = by_symbol.get(s, [])
        if not props:
            continue
        rrs = sorted(p["rr_theo"] for p in props)
        out[s] = {
            "n": len(rrs),
            "min": rrs[0],
            "p25": percentile(rrs, 25),
            "median": percentile(rrs, 50),
            "p75": percentile(rrs, 75),
            "max": rrs[-1],
            "mean": sum(rrs) / len(rrs),
        }
    return out


# --- Q4 ------------------------------------------------------------------------

def dedup_by_window(proposals, window_sec):
    """Première proposition par (side) sur fenêtres de `window_sec`."""
    out = []
    last_kept_ts = {"LONG": None, "SHORT": None}
    for p in sorted(proposals, key=lambda x: x["ts"]):
        side = p["side"]
        prev = last_kept_ts[side]
        if prev is None or (p["ts"] - prev).total_seconds() >= window_sec:
            out.append(p)
            last_kept_ts[side] = p["ts"]
    return out


def q4_dedup_resim(by_symbol, bars_by_symbol, initial_metrics):
    out = {}
    for s in SHADOW_SYMBOLS:
        props = by_symbol.get(s, [])
        bars = bars_by_symbol.get(s, [])
        if not props:
            continue
        deduped = dedup_by_window(props, DEDUP_WINDOW_SEC)
        sim = simulate_pool(deduped, bars) if bars else None

        init = initial_metrics.get(s, {})
        init_wr = init.get("wr_sim", 0.0)
        init_rr = init.get("rr_eff_sim", 0.0)
        new_wr = sim["wr_sim"] if sim else 0.0
        new_rr = sim["rr_eff_sim"] if sim else 0.0
        delta_wr_pp = (new_wr - init_wr) * 100
        if init_rr in (0.0, None) or init_rr == float("inf"):
            delta_rr_pct = None
        else:
            delta_rr_pct = ((new_rr - init_rr) / init_rr) * 100

        alert = False
        if abs(delta_wr_pp) > 10.0:
            alert = True
        if delta_rr_pct is not None and abs(delta_rr_pct) > 30.0:
            alert = True

        out[s] = {
            "n_initial": len(props),
            "n_deduped": len(deduped),
            "deduped_simulation": sim,
            "delta_wr_pp": delta_wr_pp,
            "delta_rr_pct": delta_rr_pct,
            "alert_triggered": alert,
            "initial_wr": init_wr,
            "initial_rr_eff": init_rr,
        }
    return out


# --- Main ----------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START.isoformat())
    ap.add_argument("--end", default=DEFAULT_END.isoformat())
    ap.add_argument("--no-mt5", action="store_true")
    ap.add_argument("--initial-json", default=str(REPORT_DIR / "shadow_analysis_data.json"))
    ap.add_argument("--output-json", default=str(JSON_OUT))
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    print(f"[INFO] Fenetre: {start.isoformat()} -> {end.isoformat()}")

    # Q1 nécessite borne avant commit d727913, on étend la lecture si nécessaire
    extended_start = min(start, COMMIT_D727913_TS - timedelta(days=2))
    print(f"[INFO] Lecture étendue pour Q1: {extended_start.isoformat()} -> {end.isoformat()}")

    by_symbol = load_proposals(extended_start, end)
    for s in SHADOW_SYMBOLS:
        print(f"  {s:8s}: {len(by_symbol.get(s, []))} props (lecture étendue)")

    # Q1
    print("[Q1] Vérification borne basse vs commit d727913")
    q1 = q1_pre_commit_check(by_symbol)
    for s, d in q1.items():
        print(f"  {s}: pre={d['pre_count']}, post={d['post_count']}, "
              f"first={d['first_proposal_ts']}")

    # Restreindre by_symbol à la vraie fenêtre pour Q2/Q3/Q4
    by_symbol_window = {s: [p for p in plist if start <= p["ts"] <= end]
                        for s, plist in by_symbol.items()}

    # MT5 bars
    bars_by_symbol = {}
    if not args.no_mt5:
        mt5 = init_mt5()
        if mt5:
            print("[INFO] MT5 OK — fetch barres M5")
            for s in SHADOW_SYMBOLS:
                props = by_symbol_window.get(s, [])
                if not props:
                    continue
                broker = resolve_broker_symbol(mt5, s)
                if not broker:
                    bars_by_symbol[s] = []
                    continue
                try:
                    mt5.symbol_select(broker, True)
                except Exception:
                    pass
                t_from = min(p["ts"] for p in props) - timedelta(minutes=10)
                t_to = max(p["ts"] for p in props) + timedelta(hours=SIM_HORIZON_HOURS + 1)
                bars = fetch_bars_range(mt5, broker, t_from, t_to)
                bars_by_symbol[s] = bars
                print(f"  {s:8s}: {len(bars)} barres")
            try:
                mt5.shutdown()
            except Exception:
                pass
        else:
            print("[WARN] MT5 indispo — Q2/Q4 simulations dégradées")

    # Q2
    print("[Q2] Re-simulation après hard_filters")
    q2 = q2_hard_filters_resim(by_symbol_window, bars_by_symbol)

    # Q3
    print("[Q3] Distribution R:R théorique")
    q3 = q3_rr_distribution(by_symbol_window)

    # Q4
    print("[Q4] Déduplication 60min + re-simulation")
    initial_metrics = {}
    try:
        with open(args.initial_json, encoding="utf-8") as f:
            init_data = json.load(f)
            initial_metrics = init_data.get("per_symbol", {})
    except Exception as e:
        print(f"[WARN] Impossible de charger {args.initial_json}: {e}")
    q4 = q4_dedup_resim(by_symbol_window, bars_by_symbol, initial_metrics)

    # Sortie
    out = {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "extended_window_start": extended_start.isoformat(),
        "hard_filters_applied": {
            "min_score": HF_MIN_SCORE,
            "min_confluence": HF_MIN_CONFLUENCE,
            "min_rr": HF_MIN_RR,
            "short_score_penalty": HF_SHORT_SCORE_PENALTY,
            "global_blocked_hours_utc": GLOBAL_BLOCKED_HOURS_UTC,
        },
        "Q1_pre_commit_check": q1,
        "Q2_hard_filters_resim": q2,
        "Q3_rr_distribution": q3,
        "Q4_dedup_resim": q4,
    }
    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output_json).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"[DONE] {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
