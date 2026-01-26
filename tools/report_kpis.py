# tools/report_kpis.py
import os, io, base64
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA     = os.path.join(ROOT, "data")
REPORTS  = os.path.join(ROOT, "reports")

EQUITY_CSV = os.path.join(DATA, "equity_log.csv")       # equity snapshots
TRADES_CSV = os.path.join(DATA, "trades_log.csv")       # log d’ordres (pas forcément de PnL)
DEALS_CSV  = os.path.join(DATA, "deals_history.csv")    # historique MT5 (contient généralement profit)

# Objectif mensuel (modifiable)
MONTHLY_TARGET = 5000.0


# ============================================================================
# Utils I/O
# ============================================================================
def read_csv_safe(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


# ============================================================================
# Timezone-safe helpers
# ============================================================================
def ts_localized_no_tz(series: pd.Series, tz: str = "Europe/Zurich") -> pd.Series:
    """
    Retourne une série datetime *sans tz* mais correctement localisée.
    Gère les cas non-datetime et tz-aware, et évite les deprecations.
    """
    s = series
    if not pd.api.types.is_datetime64_any_dtype(s):
        s = pd.to_datetime(s, utc=True, errors="coerce")

    try:
        # Remplace is_datetime64tz_dtype déprécié
        if isinstance(s.dtype, pd.DatetimeTZDtype):
            s = s.dt.tz_convert(tz).dt.tz_localize(None)
        else:
            # si naive on la laisse telle quelle
            s = s
    except Exception:
        s = s
    return s


# ============================================================================
# KPI helpers
# ============================================================================
def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    """
    Renvoie (mdd_abs, mdd_pct) en valeurs positives (ex: 1500, 0.12)
    """
    e = pd.to_numeric(equity, errors="coerce").dropna()
    if e.empty:
        return 0.0, 0.0
    roll_max = e.cummax()
    dd_abs = (e - roll_max)               # négatif ou 0
    dd_pct = (e / roll_max) - 1.0         # négatif ou 0
    mdd_abs = float(dd_abs.min())         # négatif
    mdd_pct = float(dd_pct.min())         # négatif
    return abs(mdd_abs), abs(mdd_pct)


def daily_pnl_from_equity(df_eq: pd.DataFrame) -> pd.Series:
    """
    Approxime le PnL quotidien à partir des variations d’équity.
    Retourne une Series indexée par date (YYYY-MM-DD) avec le PnL du jour.
    """
    if df_eq.empty or "equity" not in df_eq.columns:
        return pd.Series(dtype="float64")

    ts = pd.to_datetime(df_eq["ts_utc"], errors="coerce")
    eq = pd.to_numeric(df_eq["equity"], errors="coerce").ffill()
    df = pd.DataFrame({"ts": ts, "equity": eq}).dropna()

    if df.empty:
        return pd.Series(dtype="float64")

    # on prend la dernière equity de chaque jour et on diffe
    ts_local = ts_localized_no_tz(df["ts"], tz="Europe/Zurich")
    df["d"] = ts_local.dt.date
    day_last = df.groupby("d", as_index=True)["equity"].last()
    return day_last.diff().fillna(0.0)


# ============================================================================
# Figures -> base64
# ============================================================================
def fig_to_base64() -> str:
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close()
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


# ============================================================================
# Plots
# ============================================================================
def plot_equity(df_eq: pd.DataFrame) -> str | None:
    if df_eq.empty or "equity" not in df_eq.columns:
        return None
    ts = pd.to_datetime(df_eq["ts_utc"], errors="coerce")
    eq = pd.to_numeric(df_eq["equity"], errors="coerce").ffill()
    if eq.dropna().empty:
        return None
    plt.figure(figsize=(9, 4.8))
    plt.plot(ts, eq)
    plt.title("Courbe d’équity")
    plt.xlabel("Temps")
    plt.ylabel("Equity")
    return fig_to_base64()


def plot_daily_pnl(df_tr: pd.DataFrame, df_eq: pd.DataFrame, df_deals: pd.DataFrame) -> str | None:
    """
    Priorité:
      1) deals_history (profit par deal, groupé par jour)
      2) trades_log (pnl_ccy si existe)
      3) equity (diff par jour)
    """
    # 1) deals
    if not df_deals.empty and "profit" in df_deals.columns:
        ts = pd.to_datetime(df_deals.get("time") or df_deals.get("ts_utc"), errors="coerce")
        pnl = pd.to_numeric(df_deals["profit"], errors="coerce").fillna(0.0)
        d = ts_localized_no_tz(ts).dt.date
        g = pd.DataFrame({"d": d, "pnl": pnl}).groupby("d", as_index=True)["pnl"].sum()
    # 2) trades
    elif not df_tr.empty and "pnl_ccy" in df_tr.columns:
        ts = pd.to_datetime(df_tr.get("ts_utc") or df_tr.get("ts"), errors="coerce")
        pnl = pd.to_numeric(df_tr["pnl_ccy"], errors="coerce").fillna(0.0)
        d = ts_localized_no_tz(ts).dt.date
        g = pd.DataFrame({"d": d, "pnl": pnl}).groupby("d", as_index=True)["pnl"].sum()
    else:
        # 3) equity
        g = daily_pnl_from_equity(df_eq)

    if g is None or g.empty:
        return None

    plt.figure(figsize=(9, 4.8))
    plt.bar(g.index.astype(str), g.values)
    plt.xticks(rotation=45, ha="right")
    plt.title("PnL quotidien")
    plt.xlabel("Jour")
    plt.ylabel("PnL (devise)")
    return fig_to_base64()


def plot_symbol_perf(df_tr: pd.DataFrame, df_deals: pd.DataFrame) -> str | None:
    """
    Bar chart PnL net par symbole.
    Priorité:
      1) deals_history (profit par symbol)
      2) trades_log (pnl_ccy par symbol) si dispo
      sinon -> None
    """
    series = None

    if not df_deals.empty and {"symbol", "profit"}.issubset(df_deals.columns):
        pnl = pd.to_numeric(df_deals["profit"], errors="coerce").fillna(0.0)
        sym = df_deals["symbol"].astype(str).fillna("(inconnu)")
        series = pd.DataFrame({"symbol": sym, "pnl": pnl}).groupby("symbol", as_index=True)["pnl"].sum()
    elif not df_tr.empty and {"symbol", "pnl_ccy"}.issubset(df_tr.columns):
        pnl = pd.to_numeric(df_tr["pnl_ccy"], errors="coerce").fillna(0.0)
        sym = df_tr["symbol"].astype(str).fillna("(inconnu)")
        series = pd.DataFrame({"symbol": sym, "pnl": pnl}).groupby("symbol", as_index=True)["pnl"].sum()

    if series is None or series.empty:
        return None

    series = series.sort_values(ascending=False)
    plt.figure(figsize=(9, 4.8))
    plt.bar(series.index.astype(str), series.values)
    plt.xticks(rotation=30, ha="right")
    plt.title("PnL par symbole (net)")
    plt.ylabel("Devise du compte")
    return fig_to_base64()


# ============================================================================
# KPIs
# ============================================================================
def compute_kpis(df_tr: pd.DataFrame, df_eq: pd.DataFrame, df_deals: pd.DataFrame) -> dict:
    """
    Calcule KPIs avec fallbacks:
      - stats de trade depuis deals_history si dispo, sinon trades_log (pnl_ccy)
      - MTD PnL depuis deals/trades, sinon delta d’équity du mois
    """
    k: dict = {}

    # ---------- Equity ----------
    if not df_eq.empty and "equity" in df_eq.columns:
        eq = pd.to_numeric(df_eq["equity"], errors="coerce").ffill()
        k["equity_last"] = float(eq.dropna().iloc[-1]) if not eq.dropna().empty else None
        dd_abs, dd_pct = max_drawdown(eq)
        k["max_dd"] = dd_abs
        k["max_dd_pct"] = dd_pct
    else:
        k["equity_last"] = None
        k["max_dd"] = 0.0
        k["max_dd_pct"] = 0.0

    # ---------- Source PnL trades ----------
    # deals en priorité
    pnl_series = None
    if not df_deals.empty and "profit" in df_deals.columns:
        pnl_series = pd.to_numeric(df_deals["profit"], errors="coerce").fillna(0.0)
        k["trades"] = int((~pnl_series.isna()).sum())
    elif not df_tr.empty and "pnl_ccy" in df_tr.columns:
        pnl_series = pd.to_numeric(df_tr["pnl_ccy"], errors="coerce").fillna(0.0)
        k["trades"] = int((~pnl_series.isna()).sum())
    else:
        pnl_series = pd.Series(dtype="float64")
        k["trades"] = 0

    if not pnl_series.empty:
        wins = int((pnl_series > 0).sum())
        losses = int((pnl_series < 0).sum())
        k["win_rate"] = float(wins) / max(wins + losses, 1)

        gross_profit = float(pnl_series[pnl_series > 0].sum())
        gross_loss   = float(-pnl_series[pnl_series < 0].sum())
        k["gross_profit"] = gross_profit
        k["gross_loss"]   = gross_loss
        k["net_pnl"]      = float(pnl_series.sum())

        avg_gain = float(pnl_series[pnl_series > 0].mean()) if (pnl_series > 0).any() else 0.0
        avg_loss = float(pnl_series[pnl_series < 0].mean()) if (pnl_series < 0).any() else 0.0
        k["profit_factor"] = (gross_profit / gross_loss) if gross_loss > 0 else np.inf
        k["expectancy"]    = k["win_rate"] * avg_gain - (1 - k["win_rate"]) * abs(avg_loss)
    else:
        k.update({
            "win_rate": None,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "net_pnl": 0.0,
            "profit_factor": None,
            "expectancy": None,
        })

    # ---------- MTD PnL ----------
    # Mois local (Europe/Zurich)
    # 1) deals/trades du mois ; 2) fallback delta equity du mois
    mtd_pnl = 0.0
    if not df_deals.empty and {"profit", "time"}.issubset(df_deals.columns):
        ts = ts_localized_no_tz(pd.to_datetime(df_deals["time"], errors="coerce"))
        this_month = ts.dt.to_period("M").max()
        m = df_deals[ts.dt.to_period("M") == this_month]
        mtd_pnl = float(pd.to_numeric(m["profit"], errors="coerce").fillna(0.0).sum())
    elif not df_tr.empty and {"pnl_ccy", "ts_utc"}.issubset(df_tr.columns):
        ts = ts_localized_no_tz(pd.to_datetime(df_tr["ts_utc"], errors="coerce"))
        this_month = ts.dt.to_period("M").max()
        m = df_tr[ts.dt.to_period("M") == this_month]
        mtd_pnl = float(pd.to_numeric(m["pnl_ccy"], errors="coerce").fillna(0.0).sum())
    else:
        # equity fallback
        if not df_eq.empty and {"ts_utc", "equity"}.issubset(df_eq.columns):
            ts = ts_localized_no_tz(pd.to_datetime(df_eq["ts_utc"], errors="coerce"))
            eq = pd.to_numeric(df_eq["equity"], errors="coerce").ffill()
            df = pd.DataFrame({"ts": ts, "equity": eq}).dropna()
            if not df.empty:
                this_month = df["ts"].dt.to_period("M").max()
                m = df[df["ts"].dt.to_period("M") == this_month]
                if not m.empty:
                    # delta equity entre 1er et dernier point du mois
                    mtd_pnl = float(m["equity"].iloc[-1] - m["equity"].iloc[0])

    k["mtd_pnl"] = float(mtd_pnl)
    k["monthly_target"] = float(MONTHLY_TARGET)
    k["target_delta"] = float(MONTHLY_TARGET) - k["mtd_pnl"]

    return k


# ============================================================================
# HTML
# ============================================================================
def render_html(k: dict, img_equity: str | None, img_daily: str | None, img_sym: str | None) -> str:
    def img_tag(b64: str | None) -> str:
        return (f'<img src="data:image/png;base64,{b64}" '
                f'style="max-width:100%;height:auto;border:1px solid #ddd;'
                f'padding:6px;border-radius:8px;margin:8px 0;" />') if b64 else "<em>Donnée insuffisante</em>"

    rows = [
        f"<li>Trades: <b>{k.get('trades','—')}</b></li>",
        f"<li>Win rate: <b>{k.get('win_rate',0):.1%}</b></li>" if k.get("win_rate") is not None else "<li>Win rate: —</li>",
        f"<li>Profit Factor: <b>{k.get('profit_factor'):.2f}</b></li>" if k.get("profit_factor") not in (None, np.inf) else "<li>Profit Factor: —</li>",
        f"<li>Expectancy/trade: <b>{k.get('expectancy',0):.2f}</b></li>" if k.get("expectancy") is not None else "<li>Expectancy/trade: —</li>",
        f"<li>Net PnL: <b>{k.get('net_pnl',0):.2f}</b> (Gross +:<b>{k.get('gross_profit',0):.2f}</b> / -:<b>{k.get('gross_loss',0):.2f}</b>)</li>",
        f"<li>Max Drawdown: <b>{k.get('max_dd',0):.2f}</b> ({k.get('max_dd_pct',0):.1%})</li>",
        f"<li>MTD PnL: <b>{k.get('mtd_pnl',0):.2f}</b> / Objectif: <b>{k.get('monthly_target',0):.2f}</b> → Reste: <b>{k.get('target_delta',0):.2f}</b></li>",
    ]

    html = f"""<!doctype html>
<html lang="fr"><meta charset="utf-8"><title>Empire – Rapport</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;padding:24px;max-width:1100px;margin:0 auto;}}
h1,h2{{margin:8px 0 12px}}
.card{{border:1px solid #e7e7e7;border-radius:12px;padding:16px;margin:12px 0;box-shadow:0 2px 8px rgba(0,0,0,.04)}}
small{{color:#666}}
</style>

<h1>Empire – Rapport analytique</h1>
<small>Généré le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small>

<div class="card">
  <h2>KPIs</h2>
  <ul>
    {''.join(rows)}
  </ul>
</div>

<div class="card">
  <h2>Courbe d’équity</h2>
  {img_tag(img_equity)}
</div>

<div class="card">
  <h2>PnL quotidien</h2>
  {img_tag(img_daily)}
</div>

<div class="card">
  <h2>PnL par symbole</h2>
  {img_tag(img_sym)}
</div>

</html>"""
    return html


# ============================================================================
# Main
# ============================================================================
def main():
    os.makedirs(REPORTS, exist_ok=True)

    df_eq    = read_csv_safe(EQUITY_CSV)
    df_tr    = read_csv_safe(TRADES_CSV)
    df_deals = read_csv_safe(DEALS_CSV)  # optionnel mais très utile

    # KPIs + Graphs
    k          = compute_kpis(df_tr, df_eq, df_deals)
    img_equity = plot_equity(df_eq)
    img_daily  = plot_daily_pnl(df_tr, df_eq, df_deals)
    img_sym    = plot_symbol_perf(df_tr, df_deals)

    html = render_html(k, img_equity, img_daily, img_sym)
    out = os.path.join(REPORTS, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ Rapport généré → {out}")


if __name__ == "__main__":
    main()
