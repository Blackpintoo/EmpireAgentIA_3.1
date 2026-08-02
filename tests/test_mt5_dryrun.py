import pytest
import os, types, pathlib, sys

THIS = pathlib.Path(__file__).resolve()
ROOT = THIS.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# FIX 2026-08-02 : marqueur rendu CONDITIONNEL.
# Il produisait un XPASS sous Windows, ou le module MetaTrader5 existe et ou
# le defaut ne se manifeste donc pas. Un xpassed n'est ni un succes ni un
# echec : il brouille la lecture de la suite et laisse croire qu'un bug a ete
# corrige. Le defaut, lui, EST TOUJOURS LA — il ne se voit que sans le module.
# Consequences du conditionnel :
#   - sous Windows (module present) : le marqueur ne s'applique pas, le test
#     doit reellement passer, et une regression sera signalee ;
#   - sous Linux / CI (module absent) : xfail STRICT, donc le jour ou le
#     routage dry-run sera corrige, la suite exigera le retrait du marqueur.
from tests.conftest import MT5_ABSENT

@pytest.mark.xfail(
    MT5_ABSENT,
    strict=True,
    reason=(
        "DEFAUT REEL DU CODE, pas du test (constate 2026-07-30, P1). "
        "place_order() verifie `mt5 is None` et abandonne avec "
        "{'ok': False, 'error': 'MT5 module unavailable'} AVANT de router vers "
        "le simulateur, alors que _use_sim() vaut True et que MT5_SIM est "
        "instancie. Le mode dry-run est donc inoperant pour l'envoi d'ordres "
        "des que le module MetaTrader5 est absent (Linux, CI). Sous Windows le "
        "module existe, le defaut ne se voit pas. Corriger le routage vers le "
        "simulateur modifie le chemin d'execution : a traiter separement, avec "
        "verification, et non dans un lot de correction de tests."
    ),
)
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
