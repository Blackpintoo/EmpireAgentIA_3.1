# scripts/analyze_shadow_propositions.py
# Directive 12 (2026-05-19) — analyse rétroactive des propositions shadow.
#
# Lit data/proposals_log.csv, simule SL/TP via barres MT5 M5 sur 6h post-emission,
# produit des agrégations par symbole et, pour BNBUSD/SOLUSD, un comparatif des
# multiplicateurs ATR (1.5x, 2.0x, 2.5x, 3.0x).
#
# Sortie : reports/shadow_analysis_data.json (idempotent, pas d'ecriture data/).
# Idempotent et reexecutable sans effet de bord.
"""
Usage:
  python scripts/analyze_shadow_propositions.py
  python scripts/analyze_shadow_propositions.py --no-mt5      # metriques statiques uniquement
  python scripts/analyze_shadow_propositions.py --start 2026-05-01T04:16:10+00:00 --end 2026-05-19T23:59:59+00:00
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

# --- Constants -----------------------------------------------------------------

SHADOW_SYMBOLS = ["DJ30", "UK100", "GBPUSD", "USDCAD", "GER40", "XAGUSD", "BNBUSD", "SOLUSD"]
CRYPTO_OPT = ["BNBUSD", "SOLUSD"]
ATR_MULTIPLIERS = [1.5, 2.0, 2.5, 3.0]

SIM_HORIZON_HOURS = 6
M5_BARS_PER_HOUR = 12
SIM_BARS = SIM_HORIZON_HOURS * M5_BARS_PER_HOUR  # 72 barres M5

# Borne basse = horodatage commit e706932 (push Phase 1+2)
DEFAULT_START = datetime(2026, 5, 1, 4, 16, 10, tzinfo=timezone.utc)
DEFAULT_END = datetime(2026, 5, 19, 23, 59, 59, tzinfo=timezone.utc)

PROPOSALS_CSV = ROOT / "data" / "proposals_log.csv"
REPORT_DIR = ROOT / "reports"
JSON_OUT = REPORT_DIR / "shadow_analysis_data.json"

# Variantes broker (alignées sur check_candidates_mt5.py)
BROKER_VARIANTS = {
    "DJ30": ["US30", "US30.cash", "DJI30", "WallStreet30"],
    "UK100": ["UK100.cash", "FTSE100"],
    "GER40": ["DE40", "DAX40", "GER40.cash", "DE30"],
    "XAGUSD": ["SILVER"],
    "USDCAD": ["USDCAD.", "USDCADm"],
    "GBPUSD": ["GBPUSD.", "GBPUSDm"],
}


# --- Loading -------------------------------------------------------------------

def load_proposals(start: datetime, end: datetime) -> tuple[dict, dict]:
    """Renvoie ({symbol: [proposals]}, {symbol: skip_count}). Skipper plutot que crasher."""
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    skipped: dict[str, int] = defaultdict(int)
    skip_reasons: dict[str, int] = defaultdict(int)
    total_rows = 0
    with PROPOSALS_CSV.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            total_rows += 1
            try:
                ts = datetime.fromisoformat(row["ts_utc"])
            except Exception:
                skip_reasons["bad_ts"] += 1
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
                lots = float(row.get("lots") or 0)
            except Exception:
                skipped[sym] += 1
                skip_reasons["bad_numeric"] += 1
                continue
            side = (row.get("side") or "").upper().strip()
            if side not in ("LONG", "SHORT"):
                skipped[sym] += 1
                skip_reasons["bad_side"] += 1
                continue
            if not (math.isfinite(price) and math.isfinite(sl) and math.isfinite(tp)):
                skipped[sym] += 1
                skip_reasons["nan_inf"] += 1
                continue
            if price == 0.0 or sl == 0.0 or tp == 0.0:
                skipped[sym] += 1
                skip_reasons["zero_value"] += 1
                continue
            if abs(price - sl) < 1e-12:
                skipped[sym] += 1
                skip_reasons["sl_eq_price"] += 1
                continue
            # Coherence side/sl/tp
            if side == "LONG" and not (sl < price < tp):
                skipped[sym] += 1
                skip_reasons["long_incoherent"] += 1
                continue
            if side == "SHORT" and not (tp < price < sl):
                skipped[sym] += 1
                skip_reasons["short_incoherent"] += 1
                continue
            by_symbol[sym].append({
                "ts": ts,
                "side": side,
                "price": price,
                "sl": sl,
                "tp": tp,
                "lots": lots,
                "score": score,
                "confluence": conf,
                "executed_flag": (row.get("executed", "").strip().lower() == "true"),
            })
    return by_symbol, {"per_symbol": dict(skipped), "reasons": dict(skip_reasons), "total_rows": total_rows}


# --- MT5 helpers ---------------------------------------------------------------

def resolve_broker_symbol(mt5, canonical: str):
    """Retourne le nom broker si trouvé, sinon None."""
    if mt5.symbol_info(canonical) is not None:
        return canonical
    for v in BROKER_VARIANTS.get(canonical, []):
        if mt5.symbol_info(v) is not None:
            return v
    return None


def fetch_bars_range(mt5, broker_sym: str, dt_from: datetime, dt_to: datetime):
    rates = mt5.copy_rates_range(broker_sym, mt5.TIMEFRAME_M5, dt_from, dt_to)
    if rates is None or len(rates) == 0:
        return []
    out = []
    for r in rates:
        out.append({
            "time": int(r["time"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
        })
    return out


# --- Simulation ----------------------------------------------------------------

def slice_bars_after(bars_sorted, times_index, ts: datetime, max_bars: int):
    """Renvoie jusqu'a max_bars barres dont time >= ts (epoch)."""
    if not bars_sorted:
        return []
    ts_epoch = int(ts.timestamp())
    idx = bisect_left(times_index, ts_epoch)
    return bars_sorted[idx: idx + max_bars]


def simulate_first_touch(side: str, sl: float, tp: float, bars) -> str:
    """Retourne 'SL_HIT', 'TP_HIT' ou 'TIMEOUT'. Convention conservatrice : si SL+TP touches
    dans la meme barre, on attribue SL_HIT (pessimiste)."""
    for bar in bars:
        high = bar["high"]
        low = bar["low"]
        if side == "LONG":
            sl_hit = low <= sl
            tp_hit = high >= tp
        else:  # SHORT
            sl_hit = high >= sl
            tp_hit = low <= tp
        if sl_hit and tp_hit:
            return "SL_HIT"  # conservateur
        if sl_hit:
            return "SL_HIT"
        if tp_hit:
            return "TP_HIT"
    return "TIMEOUT"


def widen_sl(side: str, price: float, sl: float, mult: float) -> float:
    """SL elargi = entry + (entry - sl_initial) * mult pour LONG ; inverse pour SHORT."""
    if side == "LONG":
        # price - sl > 0 (LONG : sl sous price). On veut new_sl plus bas.
        return price - (price - sl) * mult
    # SHORT : sl - price > 0. On veut new_sl plus haut.
    return price + (sl - price) * mult


# --- Aggregations --------------------------------------------------------------

def analyze_symbol(symbol: str, proposals: list[dict], bars: list[dict]) -> dict:
    n = len(proposals)
    side_long = sum(1 for p in proposals if p["side"] == "LONG")
    side_short = n - side_long

    score_bins: Counter = Counter()
    hour_counts: Counter = Counter()
    rrs = []
    for p in proposals:
        b = int(p["score"] // 2) * 2
        score_bins[f"[{b},{b + 2})"] += 1
        hour_counts[p["ts"].hour] += 1
        rr = abs(p["tp"] - p["price"]) / abs(p["price"] - p["sl"])
        p["rr_theo"] = rr
        rrs.append(rr)

    rr_mean = sum(rrs) / len(rrs) if rrs else 0.0
    top_hours = hour_counts.most_common(5)

    times_index = [b["time"] for b in bars] if bars else []
    sl_hit = tp_hit = timeout = 0
    insufficient_bars = 0
    no_bars_at_all = 0
    rr_winners = []

    for p in proposals:
        if not bars:
            no_bars_at_all += 1
            p["simulated"] = "NO_DATA"
            continue
        sliced = slice_bars_after(bars, times_index, p["ts"], SIM_BARS)
        if not sliced:
            no_bars_at_all += 1
            p["simulated"] = "NO_DATA"
            continue
        if len(sliced) < SIM_BARS:
            insufficient_bars += 1
        result = simulate_first_touch(p["side"], p["sl"], p["tp"], sliced)
        p["simulated"] = result
        if result == "SL_HIT":
            sl_hit += 1
        elif result == "TP_HIT":
            tp_hit += 1
            rr_winners.append(p["rr_theo"])
        else:
            timeout += 1

    decided = sl_hit + tp_hit
    wr = (tp_hit / decided) if decided else 0.0
    avg_rr_winners = (sum(rr_winners) / len(rr_winners)) if rr_winners else 0.0
    if 0.0 < wr < 1.0:
        rr_eff = (avg_rr_winners * wr) / (1.0 * (1.0 - wr))
    elif wr >= 1.0:
        rr_eff = float("inf")
    else:
        rr_eff = 0.0

    return {
        "n_proposals": n,
        "side_long": side_long,
        "side_short": side_short,
        "score_bins": dict(score_bins),
        "top_hours_utc": top_hours,
        "rr_theo_mean": rr_mean,
        "sl_hit": sl_hit,
        "tp_hit": tp_hit,
        "timeout": timeout,
        "no_bars": no_bars_at_all,
        "insufficient_bars": insufficient_bars,
        "wr_sim": wr,
        "rr_winners_avg": avg_rr_winners,
        "rr_eff_sim": rr_eff,
    }


def analyze_alt_sl(proposals: list[dict], bars: list[dict], mults: list[float]) -> dict:
    out: dict = {}
    times_index = [b["time"] for b in bars] if bars else []
    for m in mults:
        sl_h = tp_h = to = no_data = 0
        rrs_w = []
        for p in proposals:
            if not bars:
                no_data += 1
                continue
            sliced = slice_bars_after(bars, times_index, p["ts"], SIM_BARS)
            if not sliced:
                no_data += 1
                continue
            new_sl = widen_sl(p["side"], p["price"], p["sl"], m)
            new_rr = abs(p["tp"] - p["price"]) / abs(p["price"] - new_sl)
            result = simulate_first_touch(p["side"], new_sl, p["tp"], sliced)
            if result == "SL_HIT":
                sl_h += 1
            elif result == "TP_HIT":
                tp_h += 1
                rrs_w.append(new_rr)
            else:
                to += 1
        decided = sl_h + tp_h
        wr = (tp_h / decided) if decided else 0.0
        avg_rr_w = (sum(rrs_w) / len(rrs_w)) if rrs_w else 0.0
        if 0.0 < wr < 1.0:
            rr_eff = (avg_rr_w * wr) / (1.0 - wr)
        elif wr >= 1.0:
            rr_eff = float("inf")
        else:
            rr_eff = 0.0
        out[f"{m:.1f}x"] = {
            "sl_hit": sl_h,
            "tp_hit": tp_h,
            "timeout": to,
            "no_bars": no_data,
            "wr_sim": wr,
            "rr_winners_avg": avg_rr_w,
            "rr_eff_sim": rr_eff,
        }
    return out


# --- Main ----------------------------------------------------------------------

def init_mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("[ERREUR] module MetaTrader5 non installe (pip install MetaTrader5)")
        return None
    if not mt5.initialize():
        print(f"[ERREUR] mt5.initialize: {mt5.last_error()}")
        return None
    # Login optionnel
    try:
        from utils.config import load_config  # type: ignore
        mt5_cfg = (load_config() or {}).get("mt5", {}) or {}
        if mt5_cfg.get("account") and mt5_cfg.get("password") and mt5_cfg.get("server"):
            if not mt5.login(login=int(mt5_cfg["account"]),
                             password=str(mt5_cfg["password"]),
                             server=str(mt5_cfg["server"])):
                print(f"[WARN] mt5.login: {mt5.last_error()} (on continue avec la session courante)")
    except Exception as e:
        print(f"[INFO] Config MT5 non chargee ({e}); on utilise la session existante")
    return mt5


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyse retroactive des propositions shadow")
    ap.add_argument("--start", default=DEFAULT_START.isoformat())
    ap.add_argument("--end", default=DEFAULT_END.isoformat())
    ap.add_argument("--no-mt5", action="store_true",
                    help="Ne pas se connecter a MT5 (sortie statique uniquement)")
    ap.add_argument("--output-json", default=str(JSON_OUT))
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    print(f"[INFO] Fenetre observation: {start.isoformat()} -> {end.isoformat()}")
    print(f"[INFO] Lecture {PROPOSALS_CSV}")

    by_symbol, skip_stats = load_proposals(start, end)
    print(f"[INFO] Lignes brutes parcourues: {skip_stats['total_rows']}")
    print(f"[INFO] Skips: {skip_stats['reasons']}")
    for s in SHADOW_SYMBOLS:
        print(f"  {s:8s} : {len(by_symbol.get(s, [])):>5d} propositions")

    # MT5
    mt5 = None if args.no_mt5 else init_mt5()
    mt5_used = mt5 is not None
    if not mt5_used:
        print("[INFO] Mode statique uniquement (pas de simulation SL/TP)")

    bars_by_symbol: dict[str, list[dict]] = {}
    broker_resolved: dict[str, str | None] = {}
    bars_diag: dict[str, dict] = {}

    if mt5_used:
        for s in SHADOW_SYMBOLS:
            props = by_symbol.get(s, [])
            if not props:
                continue
            try:
                broker = resolve_broker_symbol(mt5, s)
            except Exception as e:
                print(f"[WARN] {s}: resolve_broker_symbol exception {e}")
                broker = None
            broker_resolved[s] = broker
            if broker is None:
                print(f"[WARN] {s}: introuvable broker, simulation skip")
                bars_by_symbol[s] = []
                continue
            try:
                mt5.symbol_select(broker, True)
            except Exception:
                pass
            t_from = min(p["ts"] for p in props) - timedelta(minutes=10)
            t_to = max(p["ts"] for p in props) + timedelta(hours=SIM_HORIZON_HOURS + 1)
            try:
                bars = fetch_bars_range(mt5, broker, t_from, t_to)
            except Exception as e:
                print(f"[WARN] {s}: copy_rates_range exception {e}")
                bars = []
            bars_by_symbol[s] = bars
            bars_diag[s] = {
                "broker": broker,
                "n_bars": len(bars),
                "from": t_from.isoformat(),
                "to": t_to.isoformat(),
            }
            print(f"  {s:8s} ({broker:>10s}) : {len(bars):>5d} barres M5")
        try:
            mt5.shutdown()
        except Exception:
            pass

    # Analyses
    print("[INFO] Agregations...")
    per_symbol: dict[str, dict] = {}
    alt_sl: dict[str, dict] = {}
    for s in SHADOW_SYMBOLS:
        props = by_symbol.get(s, [])
        if not props:
            continue
        bars = bars_by_symbol.get(s, [])
        per_symbol[s] = analyze_symbol(s, props, bars)
        if s in CRYPTO_OPT:
            alt_sl[s] = analyze_alt_sl(props, bars, ATR_MULTIPLIERS) if bars else {}

    output = {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "shadow_symbols": SHADOW_SYMBOLS,
        "skip_stats": skip_stats,
        "mt5_used": mt5_used,
        "bars_diag": bars_diag,
        "broker_resolved": broker_resolved,
        "per_symbol": per_symbol,
        "alt_sl_results": alt_sl,
    }
    out_path = Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(f"[DONE] Ecrit : {out_path}")

    # Petit recap console
    print("\n--- RECAP SIMULATION ---")
    for s, d in per_symbol.items():
        wr = d["wr_sim"]
        rr = d["rr_eff_sim"]
        rr_disp = "inf" if rr == float("inf") else f"{rr:.2f}"
        print(f"  {s:8s} n={d['n_proposals']:>4d}  WR={wr * 100:5.1f}%  R:Reff={rr_disp:>6s}  "
              f"TP={d['tp_hit']:>3d} SL={d['sl_hit']:>3d} TO={d['timeout']:>3d}  "
              f"no_bars={d['no_bars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
