# tools/setup_analytics.py
import os, csv, json
from datetime import timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REPORTS = os.path.join(ROOT, "reports")
LOGS = os.path.join(ROOT, "logs")
PRESETS = os.path.join(ROOT, "config", "presets")

TRADES_FILE     = os.path.join(DATA, "trades_log.csv")
PROPOSALS_FILE  = os.path.join(DATA, "proposals_log.csv")
PM_FILE         = os.path.join(DATA, "pm_log.csv")
EQUITY_FILE     = os.path.join(DATA, "equity_log.csv")
AGENTS_SNAP     = os.path.join(DATA, "agents_snap.jsonl")

TRADES_FIELDS = [
    "ts_utc","symbol","side","lots","entry","sl","tp",
    "retcode","ok","ticket","reqid",
    # enrichissements (facultatifs -> l’analyse les gère si absents)
    "timeframe_gate","strategy_tag","agg_score","confluence",
    "news_dir","swing_dir","scalp_dir","structure_dir",
    "rr_target","gate_reason","crypto_bucket_factor",
    "spread_at_entry","slippage_pts",
    "exit_price","pnl_ccy","rr_realized","duration_sec"
]

PROPOSALS_FIELDS = [
    "ts_utc","symbol","side","price","sl","tp","lots",
    "score","confluence","ttl_sec","expired","executed"
]

PM_FIELDS = [
    "ts_utc","symbol","event","rr_at_event","new_sl","new_tp","lot_remaining","comment"
]

EQUITY_FIELDS = ["ts_utc","balance","equity","margin","free_margin"]

def ensure_dir(p): 
    os.makedirs(p, exist_ok=True)

def ensure_csv(path, fields):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()

def main():
    for d in (DATA, REPORTS, LOGS, PRESETS):
        ensure_dir(d)

    # CSV principaux
    ensure_csv(TRADES_FILE, TRADES_FIELDS[:11])  # conserve compat si orchestrator actuel n’écrit que ces colonnes
    # fichiers annexes (analytique / PM / propositions)
    ensure_csv(PROPOSALS_FILE, PROPOSALS_FIELDS)
    ensure_csv(PM_FILE, PM_FIELDS)
    if not os.path.exists(EQUITY_FILE):
        ensure_csv(EQUITY_FILE, EQUITY_FIELDS)

    # fichier jsonl pour snapshots agents (une ligne json par événement)
    if not os.path.exists(AGENTS_SNAP):
        with open(AGENTS_SNAP, "w", encoding="utf-8") as f:
            f.write("")

    # un mini manifest pour tracer la version du “schéma d’analyse”
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": "analytics.v1",
        "files": {
            "trades_log.csv": TRADES_FIELDS,
            "proposals_log.csv": PROPOSALS_FIELDS,
            "pm_log.csv": PM_FIELDS,
            "equity_log.csv": EQUITY_FIELDS,
            "agents_snap.jsonl": "json lines"
        }
    }
    with open(os.path.join(DATA, "analytics_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print("✅ Analytics prêts. Dossiers & fichiers initialisés.")

if __name__ == "__main__":
    main()
