import os, io, time, yaml, inspect
import utils.config as cfg

# Résoudre le chemin
path = getattr(cfg, "PROFILES_PATH", None) or "profiles.yaml"
if not os.path.exists(path):
    for cand in ("config/profiles.yaml", "profiles.yaml"):
        if os.path.exists(cand):
            path = cand
            break

print("Using profiles at:", path)
with open(path, "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}

data.setdefault("enabled_symbols", [])
profiles = data.setdefault("profiles", {})

# Assurer LINKUSD activé
if "LINKUSD" not in data["enabled_symbols"]:
    data["enabled_symbols"].append("LINKUSD")

# Ajouter le profil si manquant
if "LINKUSD" not in profiles:
    profiles["LINKUSD"] = {
        "symbol": "LINKUSD",
        "instrument": {"contract_size": 1.0, "slippage": 15, "point": 0.01, "pip_value": 1.0},
        "risk": {"tier": "phase3", "risk_per_trade": 0.015, "max_daily_loss": 0.035, "max_consec_loss": 3},
        "orchestrator": {
            "votes_required": 1, "min_confluence": 1, "min_score_for_proposal": 1.0,
            "require_scalping_entry": False, "require_swing_confirm": False,
            "atr_sl_mult": 1.5, "atr_tp_mult": 2.5,
            "timeframes": {"orchestrator": 60, "scalping": "M1", "swing": "H1"},
            "multi_timeframes": {
                "enabled": True,
                "tfs": ["D1","H4","H1","M30","M15","M5","M1"],
                "tf_weights": {"D1":1.2,"H4":1.1,"H1":1.0,"M30":0.9,"M15":0.85,"M5":0.8,"M1":0.7}
            },
        },
        "agents": {
            "technical": {
                "timeframe":"M15","lookback":300,"ema_period":50,"rsi_period":14,
                "rsi_oversold":30,"rsi_overbought":70,"atr_period":14,
                "obv_window":50,"obv_win_fast":20,"obv_win_slow":50,
                "macd_fast":12,"macd_slow":26,"macd_signal":9,"macd_eps":0.0003,
                "obv_z_deadzone":0.20,"votes_required":2,"sl_mult":1.5,"tp_mult":2.5,
                "notify_telegram":False
            },
            "scalping": {
                "timeframe":"M1","rsi_period":14,"rsi_oversold":30,"rsi_overbought":70,
                "ema_period":21,"atr_period":14,"vol_window":50,"vol_spike_ratio":1.8,
                "session_hours":[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23],
                "notify_telegram":False
            },
            "swing": {
                "timeframe":"H1","lookback":400,"ema_period":50,"atr_period":14,"rsi_period":14,
                "trend_rsi_long":52,"trend_rsi_short":48,"trend_sl_mult":1.2,"trend_tp_mult":1.8,
                "range_rsi_long":40,"range_rsi_short":60,"range_sl_mult":1.2,"range_tp_mult":1.8,
                "slope_level":0.0,"atr_level_val":0.0,"notify_telegram":False
            },
            "news": {
                "news_feeds":[
                    "https://www.coindesk.com/arc/outboundfeeds/rss/",
                    "https://cointelegraph.com/rss",
                    "https://bitcoinmagazine.com/feed",
                    "https://finance.yahoo.com/rss/topstories",
                    "https://cryptoslate.com/feed/",
                    "https://coinjournal.net/news/feed/",
                    "https://news.google.com/rss/search?q=chainlink%20OR%20LINK%20OR%20crypto"
                ],
                "source_weight":{"coindesk":3,"cointelegraph":3,"bitcoinmagazine":2,"yahoo":1,"cryptoslate":1,"coinjournal":1,"google":1},
                "keywords_bullish":["etf","adoption","regulation","bullish","uptrend","buy","growth","rally","approval","partnership","institutional","invest","expansion","spot etf","sec approval"],
                "keywords_bearish":["hack","ban","scam","bearish","downtrend","sell","collapse","fraud","lawsuit","liquidation","delisting","sec charges","probe","freeze"],
                "sentiment_threshold":0.15,"keyword_weight":2.0,"signal_threshold":2.0,
                "lookback_hours":12,"http_timeout":8,"retry":0,"max_per_feed":15,
                "cache_ttl":900,"warn_every":600,"notify_telegram":False
            }
        }
    }

# Backup + write
bak = f"{path}.{time.strftime('%Y%m%d_%H%M%S')}.bak"
import shutil; shutil.copy2(path, bak)
with open(path, "w", encoding="utf-8") as f:
    yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
print("Patched. Backup:", bak)
