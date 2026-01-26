#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest & Gating Runner
- Charge un ou plusieurs CSV(s) de trades (export MT5 Strategy Tester ou équivalent)
- Calcule les métriques clés (PF, MaxDD, Expectancy, Sharpe, Sortino, R:R proxy, hit-rate)
- Walk-Forward (splits chronologiques)
- Monte Carlo (bootstrap des trades)
- Génère un rapport CSV + HTML et un fichier JSON de gating (pass/fail)
- Code compatible "offline" (pas besoin de MT5 pour l'analyse)

Usage (exemples):
  python scripts/backtest_runner.py --csv data/backtests/BTCUSD_2024.csv --symbol BTCUSD --tf H1 --strategy MTF_V1 --outdir reports/backtests --wf-splits 4 --mc 2000
  python scripts/backtest_runner.py --csv data/*.csv --symbol XAUUSD --tf M15 --strategy SentimentV2 --pip-value 1.0

CSV attendu (flexible):
- colonnes minimales: open_time, close_time, symbol, side, entry, exit, lots, profit
- colonnes optionnelles: sl, tp, commission, swap, pips, risk (par trade), rr (réalisé)
- open_time/close_time en ISO (ou timestamps); symbol/side strings; nombres float ailleurs
"""
from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from glob import glob
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ----------------------------- Utilitaires ---------------------------------- #

def _ensure_outdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _read_one_table(path: str, verbose: bool = False) -> pd.DataFrame:
    """
    Lit un fichier de trades:
      - CSV: auto-détection du séparateur (',' ou ';'), encodage (utf-8/latin1), decimal (',' ou '.')
      - XLSX: via pandas.read_excel
    """
    ext = os.path.splitext(path)[1].lower()
    df = None
    if ext in (".xlsx", ".xls"):
        if verbose: print(f"[read] Excel: {path}")
        df = pd.read_excel(path)
    else:
        # Essais multiples encodage/séparateur/decimal
        tried = []
        for enc in ("utf-8", "latin1"):
            for sep in (None, ",", ";"):                
                for dec in (".", ","):
                    try:
                        # sep=None + engine='python' => sniffing automatique
                        if verbose:
                            tried.append(f"enc={enc} sep={sep} dec={dec}")
                        df = pd.read_csv(
                            path,
                            sep=sep,
                            engine="python" if sep is None else "c",
                            encoding=enc,
                            decimal=dec,
                        )
                        if df is not None and len(df.columns) > 0:
                            raise StopIteration  # succès -> sortir des boucles
                    except StopIteration:
                        break
                    except Exception:
                        df = None
                if df is not None:
                    break
            if df is not None:
                break
        if df is None and verbose:
            print(f"[read] ECHEC lecture CSV: {path} | tried: {', '.join(tried)}")
    if df is None:
        raise ValueError(f"Impossible de lire le fichier: {path}")
    # normalise les noms de colonnes
    df.columns = [c.strip().lower() for c in df.columns]
    # alias classiques
    alias = {
        "time_open": "open_time",
        "time_close": "close_time",
        "open": "entry",
        "close": "exit",
        "volume": "lots",
        "vol": "lots",
        "symbol_name": "symbol",
    }
    for a, b in alias.items():
        if a in df.columns and b not in df.columns:
            df[b] = df[a]

    # parsing dates si dispo
    for tcol in ("open_time", "close_time"):
        if tcol in df.columns:
            try:
                df[tcol] = pd.to_datetime(df[tcol], utc=True, errors="coerce")
            except Exception:
                pass

    # normalise side
    if "side" in df.columns:
        df["side"] = df["side"].astype(str).str.upper().str.strip()
        df["side"] = df["side"].replace({"BUY": "LONG", "SELL": "SHORT"})

    # impose colonnes clés si manquantes
    required = ["symbol", "entry", "exit", "lots", "profit"]
    for col in required:
        if col not in df.columns:
            df[col] = np.nan

    return df

def _load_trades(csv_paths: List[str], verbose: bool = False) -> pd.DataFrame:
    frames = []
    matched_files: List[str] = []
    for p in csv_paths:
        g = glob(p)
        if verbose:
            print(f"[glob] {p} -> {len(g)} fichier(s)")
        matched_files.extend(g)
        for file in g:
            try:
                frames.append(_read_one_table(file, verbose=verbose))
                if verbose:
                    print(f"[ok] {file} ({len(frames[-1])} lignes)")
            except Exception as e:
                if verbose:
                    print(f"[skip] {file} ({e})")
                continue
    if not matched_files:
        raise SystemExit("Aucun fichier trouvé par les motifs fournis (--csv). Vérifie le chemin/l'emplacement.")
    if not frames:
        raise SystemExit("Aucun CSV valide chargé (format ou encodage non reconnus). Utilise --verbose pour diagnostiquer.")
    df = pd.concat(frames, ignore_index=True)
    # drop lignes sans profit
    if "profit" in df.columns:
        df = df[~df["profit"].isna()].copy()
        df["profit"] = df["profit"].astype(float)
    # ordonne par close_time si dispo, sinon par index
    if "close_time" in df.columns and not df["close_time"].isna().all():
        df = df.sort_values("close_time").reset_index(drop=True)
    return df

def _equity_curve_from_trades(profits: pd.Series, start_equity: float = 10_000.0) -> pd.Series:
    """Cumul simple sur la devise du compte."""
    eq = start_equity + profits.cumsum()
    return eq

def _max_drawdown(equity: pd.Series) -> Tuple[float, float]:
    """Retourne (max_drawdown_abs, max_drawdown_pct) sur la courbe equity."""
    roll_max = equity.cummax()
    dd = equity - roll_max
    max_dd_abs = dd.min()
    max_dd_pct = float(0.0 if equity.iloc[0] == 0 else (max_dd_abs / equity.cummax().max()))
    return float(max_dd_abs), max_dd_pct

def _sharpe(trade_returns: np.ndarray, rf: float = 0.0) -> float:
    """Sharpe sur rendements par trade (annualisation ~sqrt(N) optionnelle)."""
    x = np.array(trade_returns, dtype=float)
    if x.size < 2:
        return 0.0
    mu, sd = x.mean(), x.std(ddof=1)
    if sd == 0:
        return 0.0
    return float((mu - rf) / sd * math.sqrt(max(1, len(x))))

def _sortino(trade_returns: np.ndarray, rf: float = 0.0) -> float:
    x = np.array(trade_returns, dtype=float)
    if x.size < 2:
        return 0.0
    downside = np.where(x - rf < 0, x - rf, 0.0)
    dd = downside.std(ddof=1)
    if dd == 0:
        return 0.0
    return float((x.mean() - rf) / dd * math.sqrt(max(1, len(x))))

def _expectancy(profits: np.ndarray) -> float:
    """Expectancy en devise/trade = mean(profit). Alternatif si 'risk' dispo → mean(R)."""
    return float(np.mean(profits)) if profits.size else 0.0

def _profit_factor(profits: np.ndarray) -> float:
    gains = profits[profits > 0].sum()
    losses = -profits[profits < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)

def _rr_proxy(profits: np.ndarray) -> float:
    """Proxy R:R = taille moyenne gain / taille moyenne perte (en devise)."""
    g = profits[profits > 0]
    l = -profits[profits < 0]
    if len(g) == 0 or len(l) == 0:
        return 0.0
    return float(g.mean() / l.mean())

def _walk_forward_splits(df: pd.DataFrame, k: int) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """Crée k splits chronologiques (train/test) 60/40 pour inspection. (Pas de tuning ici, seulement reporting.)"""
    if k <= 1 or len(df) < 10:
        return []
    splits = []
    n = len(df)
    for i in range(1, k + 1):
        cut = int((i / (k + 1)) * n)
        train = df.iloc[:cut]
        test = df.iloc[cut:]
        if len(train) >= 5 and len(test) >= 5:
            splits.append((train, test))
    return splits

def _monte_carlo(profits: np.ndarray, n_iter: int = 1000, start_equity: float = 10_000.0) -> Dict[str, float]:
    """Bootstrap des profits par trade pour estimer PF et MaxDD distributions."""
    if profits.size < 5 or n_iter <= 0:
        return {"pf_p5": np.nan, "pf_p50": np.nan, "pf_p95": np.nan, "dd_abs_p95": np.nan}
    rng = np.random.default_rng(12345)
    pf_vals = []
    dd_vals = []
    for _ in range(n_iter):
        sample = rng.choice(profits, size=profits.size, replace=True)
        pf_vals.append(_profit_factor(sample))
        eq = _equity_curve_from_trades(pd.Series(sample), start_equity=start_equity)
        dd_abs, _ = _max_drawdown(eq)
        dd_vals.append(dd_abs)
    return {
        "pf_p5": float(np.nanpercentile(pf_vals, 5)),
        "pf_p50": float(np.nanpercentile(pf_vals, 50)),
        "pf_p95": float(np.nanpercentile(pf_vals, 95)),
        "dd_abs_p95": float(np.nanpercentile(dd_vals, 95)),
    }


# ----------------------------- Dataclasses ----------------------------------- #

@dataclass
class Metrics:
    n_trades: int
    hit_rate: float
    pf: float
    maxdd_abs: float
    maxdd_pct: float
    expectancy: float
    sharpe: float
    sortino: float
    rr_proxy: float

    def as_dict(self) -> Dict[str, float]:
        d = asdict(self)
        return {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in d.items()}


# ----------------------------- Calculs métriques ----------------------------- #

def _metrics_from_df(df: pd.DataFrame, start_equity: float = 10_000.0, risk_col: Optional[str] = None) -> Metrics:
    profits = df["profit"].to_numpy(dtype=float)
    n = len(profits)
    n_win = int((profits > 0).sum())
    hit = 100.0 * n_win / n if n > 0 else 0.0
    eq = _equity_curve_from_trades(pd.Series(profits), start_equity=start_equity)
    maxdd_abs, maxdd_pct = _max_drawdown(eq)
    pf = _profit_factor(profits)
    # expectancy: si 'risk' ou 'rr' dispo, calcule en R; sinon devise
    if risk_col and risk_col in df.columns and (df[risk_col].abs() > 0).any():
        r = (df["profit"] / df[risk_col].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
        expectancy = float(np.mean(r)) if r.size else 0.0
        sharpe_v = _sharpe(r)
        sortino_v = _sortino(r)
    elif "rr" in df.columns:
        r = df["rr"].replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
        expectancy = float(np.mean(r)) if r.size else 0.0
        sharpe_v = _sharpe(r)
        sortino_v = _sortino(r)
    else:
        expectancy = _expectancy(profits)
        # normalise en "par trade" pour sharpe/sortino
        if np.std(profits) > 0:
            r = (profits - profits.mean()) / (profits.std(ddof=1) + 1e-12)
        else:
            r = profits * 0.0
        sharpe_v = _sharpe(r)
        sortino_v = _sortino(r)
    rr_v = _rr_proxy(profits)
    return Metrics(
        n_trades=n,
        hit_rate=hit,
        pf=pf,
        maxdd_abs=float(maxdd_abs),
        maxdd_pct=float(maxdd_pct),
        expectancy=float(expectancy),
        sharpe=float(sharpe_v),
        sortino=float(sortino_v),
        rr_proxy=float(rr_v),
    )


# ----------------------------- Gating ---------------------------------------- #

@dataclass
class GatingThresholds:
    pf_min: float = 1.30
    maxdd_pct_max: float = 0.12   # 12%
    expectancy_min: float = 0.0
    sharpe_min: float = 1.2
    sortino_min: float = 1.0
    rr_proxy_min: float = 1.5
    min_trades: int = 200         # robustesse

    @classmethod
    def from_config(cls, cfg_path: Optional[str]) -> "GatingThresholds":
        if not cfg_path or not os.path.exists(cfg_path):
            return cls()
        try:
            import yaml
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            gt = ((cfg.get("backtest") or {}).get("gating") or {})
            return cls(
                pf_min=float(gt.get("pf_min", cls.pf_min)),
                maxdd_pct_max=float(gt.get("maxdd_pct_max", cls.maxdd_pct_max)),
                expectancy_min=float(gt.get("expectancy_min", cls.expectancy_min)),
                sharpe_min=float(gt.get("sharpe_min", cls.sharpe_min)),
                sortino_min=float(gt.get("sortino_min", cls.sortino_min)),
                rr_proxy_min=float(gt.get("rr_proxy_min", cls.rr_proxy_min)),
                min_trades=int(gt.get("min_trades", cls.min_trades)),
            )
        except Exception:
            return cls()

def gate_metrics(m: Metrics, thr: GatingThresholds) -> Tuple[bool, Dict[str, bool]]:
    checks = {
        "n_trades": m.n_trades >= thr.min_trades,
        "pf": m.pf >= thr.pf_min,
        "maxdd_pct": (0 if m.maxdd_pct is None else m.maxdd_pct) <= thr.maxdd_pct_max,
        "expectancy": m.expectancy > thr.expectancy_min,
        "sharpe": m.sharpe >= thr.sharpe_min,
        "sortino": m.sortino >= thr.sortino_min,
        "rr_proxy": m.rr_proxy >= thr.rr_proxy_min,
    }
    return all(checks.values()), checks


# ----------------------------- Rapport & I/O --------------------------------- #

def save_reports(outdir: str, tag: str, df: pd.DataFrame, overall: Metrics,
                 wf_rows: List[Dict[str, float]], mc_stats: Dict[str, float],
                 gating: Dict[str, object]) -> Dict[str, str]:
    _ensure_outdir(outdir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(outdir, f"{tag}_{ts}")

    # CSV trades enrichi
    csv_path = base + "_trades.csv"
    df.to_csv(csv_path, index=False)

    # CSV métriques split WF
    wf_csv = base + "_wf.csv"
    if wf_rows:
        pd.DataFrame(wf_rows).to_csv(wf_csv, index=False)
    else:
        wf_csv = ""

    # JSON gating
    gating_path = base + "_gating.json"
    with open(gating_path, "w", encoding="utf-8") as f:
        json.dump(gating, f, indent=2, ensure_ascii=False)

    # HTML simple
    html_path = base + "_report.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_html_report(tag, overall, wf_rows, mc_stats, gating))
    return {"csv": csv_path, "wf_csv": wf_csv, "json": gating_path, "html": html_path}

def _fmt_pct(x: float) -> str:
    return f"{x*100:.1f}%" if not np.isnan(x) else "N/A"

def _html_report(tag: str, overall: Metrics, wf_rows: List[Dict[str, float]],
                 mc: Dict[str, float], gating: Dict[str, object]) -> str:
    ok = gating.get("pass", False)
    checks = gating.get("checks", {})
    rows = "".join(
        f"<tr><td>{k}</td><td>{'✅' if v else '❌'}</td></tr>"
        for k, v in checks.items()
    )
    wf_table = ""
    if wf_rows:
        heads = wf_rows[0].keys()
        wf_table = "<h3>Walk-Forward</h3><table><tr>" + "".join(f"<th>{h}</th>" for h in heads) + "</tr>"
        for r in wf_rows:
            wf_table += "<tr>" + "".join(f"<td>{r[h]}</td>" for h in heads) + "</tr>"
        wf_table += "</table>"

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Backtest Report - {tag}</title>
<style>
body{{font-family:Arial,sans-serif;padding:16px;background:#0b1020;color:#e9eef6}}
h1,h2,h3{{margin:0.6em 0}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}
th,td{{border:1px solid #2b3353;padding:6px;text-align:left}}
.badge{{display:inline-block;padding:6px 10px;border-radius:8px;background:{'#0f5132' if ok else '#842029'};color:white}}
.small{{opacity:0.8;font-size:12px}}
</style>
</head><body>
<h1>Backtest Report</h1>
<div class="badge">{'PASS' if ok else 'FAIL'}</div>
<p class="small">{tag} — généré le {_now_utc_iso()}</p>

<h2>Métriques globales</h2>
<table>
<tr><th>Trades</th><th>Hit-Rate</th><th>PF</th><th>MaxDD abs</th><th>MaxDD %</th><th>Expectancy</th><th>Sharpe</th><th>Sortino</th><th>R:R (proxy)</th></tr>
<tr>
<td>{overall.n_trades}</td>
<td>{overall.hit_rate:.1f}%</td>
<td>{overall.pf:.2f}</td>
<td>{overall.maxdd_abs:.2f}</td>
<td>{_fmt_pct(overall.maxdd_pct)}</td>
<td>{overall.expectancy:.2f}</td>
<td>{overall.sharpe:.2f}</td>
<td>{overall.sortino:.2f}</td>
<td>{overall.rr_proxy:.2f}</td>
</tr>
</table>

{wf_table}

<h3>Monte Carlo (bootstrap)</h3>
<table>
<tr><th>PF p5</th><th>PF p50</th><th>PF p95</th><th>MaxDD abs p95</th></tr>
<tr><td>{mc.get('pf_p5','')}</td><td>{mc.get('pf_p50','')}</td><td>{mc.get('pf_p95','')}</td><td>{mc.get('dd_abs_p95','')}</td></tr>
</table>

<h2>Gating</h2>
<table>
<tr><th>Critère</th><th>OK</th></tr>
{rows}
</table>

<p class="small">NB: R:R proxy = moyenne gains / moyenne pertes en devise. Pour un R en unités de risque, fournissez une colonne 'risk' ou 'rr' dans le CSV.</p>
</body></html>"""

# ----------------------------- Main runner ----------------------------------- #

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", nargs="+", required=True, help="Fichier(s) CSV de trades (wildcards ok)")
    ap.add_argument("--symbol", default="", help="Filtrer par symbole (optionnel)")
    ap.add_argument("--tf", "--timeframe", dest="tf", default="", help="Timeframe label (optionnel)")
    ap.add_argument("--strategy", default="", help="Nom de stratégie (optionnel)")
    ap.add_argument("--outdir", default="reports/backtests", help="Répertoire de sortie")
    ap.add_argument("--start-equity", type=float, default=10_000.0, help="Equity de départ pour l'équity curve")
    ap.add_argument("--wf-splits", type=int, default=0, help="Nombre de splits Walk-Forward (0=off)")
    ap.add_argument("--mc", "--montecarlo", dest="mc", type=int, default=0, help="Iterations Monte Carlo (0=off)")
    ap.add_argument("--config", default="config/config.yaml", help="Chemin config YAML (seuils gating)")
    ap.add_argument("--risk-col", default="", help="Nom de la colonne 'risk' si dispo (R par trade).")
    ap.add_argument("--pip-value", type=float, default=0.0, help="Valeur du pip/point par lot (si calculs custom). (Optionnel)")
    ap.add_argument("--verbose", action="store_true", help="Log détaillé du chargement des fichiers")
    args = ap.parse_args()

    df = _load_trades(args.csv, verbose=args.verbose)

    if args.symbol:
        df = df[df["symbol"].astype(str).str.upper() == args.symbol.upper()].copy()
        if df.empty:
            raise SystemExit(f"Aucun trade pour {args.symbol}")

    # métriques globales
    risk_col = args.risk_col if args.risk_col else None
    overall = _metrics_from_df(df, start_equity=args.start_equity, risk_col=risk_col)

    # walk-forward
    wf = []
    if args.wf_splits and args.wf_splits > 0:
        splits = _walk_forward_splits(df, args.wf_splits)
        for i, (train, test) in enumerate(splits, 1):
            m_tr = _metrics_from_df(train, start_equity=args.start_equity, risk_col=risk_col)
            m_te = _metrics_from_df(test, start_equity=args.start_equity, risk_col=risk_col)
            wf.append({
                "split": i,
                "train_trades": m_tr.n_trades, "train_pf": round(m_tr.pf, 3), "train_maxdd": round(m_tr.maxdd_abs, 2),
                "test_trades": m_te.n_trades, "test_pf": round(m_te.pf, 3), "test_maxdd": round(m_te.maxdd_abs, 2),
            })

    # monte carlo
    mc_stats = _monte_carlo(df["profit"].to_numpy(float), n_iter=args.mc, start_equity=args.start_equity) if args.mc else {}

    # gating
    thr = GatingThresholds.from_config(args.config)
    ok, checks = gate_metrics(overall, thr)
    tag = f"{args.strategy or 'STRAT'}_{args.symbol or 'ALL'}_{args.tf or 'TF'}"
    gating = {
        "pass": ok,
        "checks": checks,
        "thresholds": asdict(thr),
        "generated_at": _now_utc_iso(),
        "tag": tag,
        "n_trades": overall.n_trades,
    }

    # Enregistre les rapports
    paths = save_reports(args.outdir, tag, df, overall, wf, mc_stats, gating)

    # Impression console
    print(f"[Backtest] {tag} | PASS={ok}")
    for k, v in overall.as_dict().items():
        print(f"  - {k}: {v}")
    if args.wf_splits and wf:
        print(f"  - WF splits: {len(wf)} (CSV: {paths['wf_csv']})")
    if args.mc:
        print(f"  - MC: {args.mc} iters → pf_p5={mc_stats.get('pf_p5')}, dd_abs_p95={mc_stats.get('dd_abs_p95')}")

    # Code de sortie ≠ 0 si gating échoue (utile en CI)
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
