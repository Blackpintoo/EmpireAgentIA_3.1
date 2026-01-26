import sys, os, types, json, pathlib

# bootstrap
THIS = pathlib.Path(__file__).resolve()
ROOT = THIS.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def test_compare_ok(monkeypatch, tmp_path):
    from scripts.symbol_validator import compare, _extract_expected

    # profil attendu
    profile = {"instrument":{
        "digits": 2, "point": 0.01, "contract_size": 1.0, "lot_min": 0.01, "lot_step": 0.01, "stops_level": 0
    }, "broker":{"symbol":"BTCUSD"}}
    expected = _extract_expected(profile)
    # actual simulé
    actual = {"digits":2,"point":0.01,"contract_size":1.0,"lot_min":0.01,"lot_step":0.01,"stops_level":0}
    res = compare("BTCUSD", expected, actual)
    assert res["ok"] is True and not res["diffs"]

def test_compare_mismatch(monkeypatch):
    from scripts.symbol_validator import compare

    expected = {"digits": 2, "point": 0.01, "contract_size": 1.0, "lot_min": 0.01, "lot_step": 0.01, "stops_level": 0}
    actual   = {"digits": 3, "point": 0.001, "contract_size": 1.0, "lot_min": 0.01, "lot_step": 0.01, "stops_level": 5}
    res = compare("BTCUSD", expected, actual)
    assert res["ok"] is False
    fields = {d["field"] for d in res["diffs"]}
    assert {"digits","point","stops_level"}.issubset(fields)
