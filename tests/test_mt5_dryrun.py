import os, types, pathlib, sys

THIS = pathlib.Path(__file__).resolve()
ROOT = THIS.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def test_dry_run_basic(monkeypatch):
    os.environ["MT5_DRY_RUN"] = "1"
    from utils.mt5_client import MT5Client, _use_sim
    assert _use_sim() is True

    c = MT5Client(cfg={"execution":{"dry_run": True}})
    # stub tick
    from utils import mt5_sim
    sim = mt5_sim.MT5Sim()
    sim.set_tick("BTCUSD", bid=100.0, ask=100.2)
    monkeypatch.setattr("utils.mt5_client._SIM", sim, raising=False)

    r = c.place_order("BTCUSD", "BUY", 0.01, price=100.2, sl=99.0, tp=101.0, comment="dry")
    assert r["ok"] is True and r["retcode"] == 10009
