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


# ══════════════════════════════════════════════════════════════════════════
# FIX 2026-07-30 : classification des actifs.
# SP500, UK100 et USDCAD n'appartenaient a aucune classe. AssetManager
# retournait (True, "no_config") : le filtre de session PHASE4 ne
# s'appliquait pas a eux, dont SP500 qui trade en reel.
# ══════════════════════════════════════════════════════════════════════════

def test_tous_les_symboles_actifs_ont_une_classe_dactif():
    from utils.asset_manager import AssetManager
    from utils.config import get_enabled_symbols

    am = AssetManager()
    orphelins = [s for s in get_enabled_symbols() if not am.get_asset_type(s)]
    assert not orphelins, (
        "symboles actifs sans classe d'actif (leur filtre de session est "
        "inerte) : %s" % orphelins)


def test_chaque_indice_a_un_horaire():
    """
    Un indice liste dans INDICES.symbols mais absent de
    INDICES.schedules est bloque 24h/24 sans que rien ne le signale.
    """
    from utils.asset_manager import AssetManager

    am = AssetManager()
    cfg = am.config.get("INDICES", {})
    horaires = cfg.get("trading_sessions", {}).get("schedules", {})
    sans = [s for s in cfg.get("symbols", []) if not horaires.get(s)]
    assert not sans, "indices sans horaire, donc bloques en permanence : %s" % sans


def test_indice_sans_horaire_donne_un_motif_explicite():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from utils.asset_manager import AssetManager

    am = AssetManager()
    am.symbol_to_type["FAKE100"] = "INDICES"
    autorise, motif = am.is_trading_allowed(
        "FAKE100", datetime(2026, 7, 30, 16, 0, tzinfo=ZoneInfo("Europe/Zurich")))
    assert autorise is False
    assert motif == "no_schedule_configured"   # et pas "outside_trading_hours"


def test_sp500_suit_la_seance_us():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from utils.asset_manager import AssetManager

    am = AssetManager()
    Z = ZoneInfo("Europe/Zurich")
    assert am.is_trading_allowed("SP500", datetime(2026, 7, 30, 16, 0, tzinfo=Z))[0] is True
    assert am.is_trading_allowed("SP500", datetime(2026, 7, 30, 3, 0, tzinfo=Z))[0] is False
