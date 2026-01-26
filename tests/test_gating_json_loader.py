import json, pathlib
from utils.gating import _find_latest_metrics
def test_loads_gating_json(tmp_path):
    p = tmp_path / "reports" / "backtests"
    p.mkdir(parents=True, exist_ok=True)
    g = {"metrics":{"pf":1.6,"maxdd_pct":0.08,"expectancy":0.15,"rr_proxy":1.7,"sharpe":1.3,"n_trades":250}}
    (p/"MultiAgent_BTCUSD_H1_20250101_gating.json").write_text(json.dumps(g), encoding="utf-8")
    m = _find_latest_metrics(str(tmp_path/"reports"/"backtests"), "BTCUSD")
    assert m["profit_factor"] == 1.6 and m["avg_rr"] == 1.7 and m["n_trades"] == 250
