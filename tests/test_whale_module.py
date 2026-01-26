import math
from pathlib import Path
import time

import pandas as pd

from utils.whale_scoring import compute_signal_score, compute_trust_score, ScoreBundle
from utils.latency_guard import LatencyGuard
from agents.whale_agent import WhaleAgent


class DummyRiskManager:
    def size_by_scores(self, *, symbol, side, price, atr, scores):
        return {
            "lots": 0.12,
            "sl": price - 1.0 if side == "LONG" else price + 1.0,
            "tp": price + 2.0 if side == "LONG" else price - 2.0,
        }


def test_compute_trust_score_bounds():
    score = compute_trust_score(
        winrate_30d=0.7,
        pnl_ratio_30d=2.5,
        followers=12000,
        age_days=90,
        verified_social=True,
        blacklist_hits=0,
    )
    assert 0.0 <= score <= 1.0


def test_signal_score_age_decay():
    base_args = dict(
        entry_confidence=0.8,
        volume_usd=1_000_000,
        price_impact_bps=5,
        slippage_bps=6,
        setup_quality=0.7,
        volatility_zscore=0.5,
    )
    recent = compute_signal_score(age_sec=15, **base_args)
    stale = compute_signal_score(age_sec=900, **base_args)
    assert recent > stale


def test_latency_guard_filters_old_events():
    guard = LatencyGuard(max_latency_ms=200)
    now = time.time()
    status_ok = guard.check(now - 0.05)
    status_old = guard.check(now - 1.0)
    assert status_ok.ok
    assert not status_old.ok


def test_whale_agent_generates_signal(tmp_path):
    output_csv = tmp_path / "decisions.csv"

    agent = WhaleAgent(
        cfg={
            "enabled": True,
            "min_trust": 0.0,
            "min_signal": 0.0,
            "storage": {"decisions_csv": str(output_csv)},
        },
        market_ctx_provider=lambda sym: {"atr": 1.5},
        stats_provider=lambda wallet: {"followers": 15000, "winrate_30d": 0.7, "pnl_ratio_30d": 2.0},
        risk_manager=DummyRiskManager(),
    )

    payload = {
        "ts": time.time(),
        "wallet": "0xabc123456789",
        "symbol": "BTCUSD",
        "side": "LONG",
        "price": 28500.0,
        "volume_usd": 2_000_000,
        "price_impact_bps": 8,
        "slippage_bps": 6,
        "volatility_zscore": 0.8,
        "setup_quality": 0.7,
        "entry_confidence": 0.75,
        "stats": {
            "winrate_30d": 0.75,
            "pnl_ratio_30d": 3.0,
            "followers": 50000,
            "age_days": 200,
            "verified": True,
        },
    }

    agent.ingest_event(payload)
    signal = agent.generate_signal()
    df = pd.read_csv(output_csv)
    last_reason = str(df.iloc[-1].get("reason", ""))
    assert signal and signal.get("signal") == "LONG", f"Decision blocked: {last_reason}"
    assert signal.get("lots", 0) > 0

    # ensure CSV was written
    assert output_csv.exists()
    df = pd.read_csv(output_csv)
    assert not df.empty


from utils.risk_manager import RiskManager


def test_risk_manager_size_by_scores_basic():
    profile = {
        "instrument": {"point": 0.01, "min_lot": 0.01, "lot_step": 0.01, "contract_size": 1.0},
        "risk": {"risk_per_trade": 0.01},
    }
    cfg = {
        "broker_costs": {
            "commission_per_lot": 0.0,
            "point_value_per_lot": 1.0,
            "spread_points": 10,
            "slippage_points_entry": 2,
            "slippage_points_exit": 2,
        },
        "risk": {
            "reset_limits_daily": True,
            "timezone": "Europe/Zurich",
            "daily_loss_limit_pct": 0.02,
            "tiers": [
                {
                    "name": "base",
                    "equity_min": 0,
                    "equity_max": 1e9,
                    "risk_per_trade_pct": 0.01,
                    "max_daily_loss_pct": 2.0,
                    "max_parallel_positions": 3,
                }
            ],
        },
    }
    rm = RiskManager(symbol="TESTUSD", profile=profile, cfg=cfg)
    scores = ScoreBundle(trust_score=0.7, signal_score=0.65)
    price = 100.0
    res = rm.size_by_scores(symbol="TESTUSD", side="LONG", price=price, atr=1.5, scores=scores)
    assert res and res.get("lots", 0) > 0
    rr = (res["tp"] - price) / max(price - res["sl"], 1e-9)
    assert rr >= 1.6






