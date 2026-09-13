# -*- coding: utf-8 -*-
"""
Journal de cycles : une ligne par cycle, quoi qu'il arrive.

AJOUT 2026-09-13.

Ce qui doit etre prouve
-----------------------
1. Une ligne est ecrite pour un cycle qui finit en WAIT, et pour un cycle
   refuse par un garde — c'est-a-dire sur les chemins ou agents_snap.jsonl
   n'ecrit rien, et donc precisement ceux qui manquaient a la mesure.
2. La valeur de retour de la decision est identique avec et sans l'ecriture.
   L'enveloppe de mesure ne doit rien changer au comportement.
"""
import inspect

import pytest

from utils import journal_cycles as jc


# ------------------------------------------------------------ encodage
@pytest.mark.parametrize("entree,attendu", [
    ("LONG", "L"), ("SHORT", "S"), ("WAIT", "W"), ("long", "L"),
    (None, "-"), ("", "-"), ("NEUTRAL", "W"), (0, "W"),
])
def test_code_vote(entree, attendu):
    assert jc.code_vote(entree) == attendu


def test_votes_positionnels_dans_l_ordre_fige():
    ptf = {"structure": {"H1": "LONG"}, "smc": {"H1": "SHORT"},
           "swing": {"H1": "WAIT"}, "technical": {"M5": "LONG"}}
    gl = {"news": "SHORT"}
    # ordre : structure, smc, swing, technical, scalping, news
    assert jc.votes_du_tf(ptf, gl, "H1") == "LSW--S"
    assert jc.votes_du_tf(ptf, gl, "M5") == "---L-S"


def test_agent_absent_marque_tiret_pas_wait():
    """
    Distinction essentielle a la mesure : un agent qui n'a pas vote n'est pas
    un agent qui a vote WAIT. Les confondre effacerait le contraste
    present/absent, le seul exploitable aujourd'hui.
    """
    assert jc.votes_du_tf({}, {}, "H1") == "------"
    assert jc.votes_du_tf({"structure": {"H1": "WAIT"}}, {}, "H1") == "W-----"


@pytest.mark.parametrize("ptf,gl", [
    (None, None), ("pas un dict", []), ({"structure": "pas un dict"}, {}),
])
def test_votes_ne_levent_jamais(ptf, gl):
    assert len(jc.votes_du_tf(ptf, gl, "H1")) == len(jc.AGENTS)


# ------------------------------------------------------------ lignes
def _cycle(**kw):
    base = {"symbole": "NAS100", "ts_utc": "2026-09-13T10:06:19+00:00",
            "per_tf_signals": {"structure": {"H1": "LONG"}},
            "global_signals": {"news": "LONG"},
            "indicators": {"ATR_H1": 18.7, "ATR_M15": 9.2},
            "px": 25549.5, "score_L": 3.42, "score_S": 1.1,
            "confluence": 4.5, "direction": "LONG"}
    base.update(kw)
    return base


def test_une_ligne_par_timeframe():
    lignes = jc.lignes_du_cycle(_cycle(), ["H1", "M15", "M5"])
    assert len(lignes) == 3
    assert [l[2] for l in lignes] == ["H1", "M15", "M5"]
    assert lignes[0][10] == "18.700"        # ATR du TF
    assert lignes[2][10] == ""              # pas d'ATR_M5 -> vide, pas 0


def test_cycle_en_wait_produit_quand_meme_des_lignes():
    """Le cas que agents_snap.jsonl n'enregistre jamais."""
    lignes = jc.lignes_du_cycle(
        _cycle(direction="WAIT", score_L=1.0, score_S=1.0), ["H1", "M15"])
    assert len(lignes) == 2
    assert all(l[7] == "W" for l in lignes)


def test_cycle_refuse_par_un_garde_produit_des_lignes():
    lignes = jc.lignes_du_cycle(
        _cycle(direction="WAIT", garde="session_filter"), ["H1"])
    assert len(lignes) == 1
    assert lignes[0][8] == "session_filter"


def test_cycle_sorti_avant_tout_vote():
    """Cooldown ou garde quotidien : aucun agent n'a tourne."""
    lignes = jc.lignes_du_cycle(
        {"symbole": "SP500", "ts_utc": "2026-09-13T10:00:00+00:00",
         "garde": "daily-stop-flag"}, ["H1", "M15", "M5"])
    assert len(lignes) == 3
    assert all(l[3] == "------" for l in lignes)
    assert all(l[8] == "daily-stop-flag" for l in lignes)


def test_virgules_et_sauts_de_ligne_neutralises():
    """Un nom de garde exotique ne doit pas casser le CSV."""
    l = jc.lignes_du_cycle(_cycle(garde="a,b\nc"), ["H1"])[0]
    assert "," not in l[8] and "\n" not in l[8]


@pytest.mark.parametrize("cycle", [None, {}, "pas un dict", 42])
def test_lignes_ne_levent_jamais(cycle):
    assert isinstance(jc.lignes_du_cycle(cycle, ["H1"]), list)


# ------------------------------------------------------------ ecriture
def test_ecriture_entete_une_seule_fois(tmp_path):
    p = tmp_path / "cycles.csv"
    jc.ecrire(jc.lignes_du_cycle(_cycle(), ["H1"]), chemin=p)
    jc.ecrire(jc.lignes_du_cycle(_cycle(), ["H1", "M15"]), chemin=p)
    lignes = p.read_text(encoding="utf-8").strip().splitlines()
    assert lignes[0] == ",".join(jc.COLONNES)
    assert len(lignes) == 4
    assert sum(1 for l in lignes if l.startswith("ts_utc")) == 1


def test_chaque_ligne_a_le_bon_nombre_de_colonnes(tmp_path):
    p = tmp_path / "cycles.csv"
    jc.ecrire(jc.lignes_du_cycle(_cycle(garde="rr_blocked"), ["H1", "M15"]), chemin=p)
    for l in p.read_text(encoding="utf-8").strip().splitlines():
        assert len(l.split(",")) == len(jc.COLONNES)


def test_ecriture_impossible_ne_leve_pas(tmp_path):
    assert jc.ecrire(jc.lignes_du_cycle(_cycle(), ["H1"]), chemin=tmp_path) == 0
    assert jc.ecrire([], chemin=tmp_path / "x.csv") == 0


def test_rotation_bornee(tmp_path, monkeypatch):
    p = tmp_path / "cycles.csv"
    monkeypatch.setattr(jc, "TAILLE_MAX", 4096)
    monkeypatch.setattr(jc, "CONSERVER", 2)
    for _ in range(400):
        jc.ecrire(jc.lignes_du_cycle(_cycle(), ["H1", "M15", "M5"]), chemin=p)
    fichiers = list(tmp_path.glob("cycles.csv*"))
    assert len(fichiers) <= 3
    assert sum(f.stat().st_size for f in fichiers) <= 3 * (4096 + 4096)


# ------------------------------------------------------------ garde
def test_garde_note_puis_repris_une_seule_fois():
    jc.noter_garde("EURUSD", "session_filter")
    assert jc.reprendre_garde("EURUSD") == "session_filter"
    assert jc.reprendre_garde("EURUSD") == ""       # efface apres lecture


def test_garde_cloisonne_par_symbole():
    jc.noter_garde("SP500", "rr_blocked")
    jc.noter_garde("NAS100", "daily_loss_limit")
    assert jc.reprendre_garde("SP500") == "rr_blocked"
    assert jc.reprendre_garde("NAS100") == "daily_loss_limit"


# ------------------------------------ l'enveloppe ne change pas la decision
class _FauxOrchestrateur:
    """Le strict minimum pour exercer la vraie enveloppe."""
    symbol = "NAS100"
    tfs = ["H1", "M15", "M5"]

    def __init__(self, resultat=None, leve=None):
        self._resultat, self._leve = resultat, leve
        self.appels = 0

    async def _run_agents_and_decide_impl(self):
        self.appels += 1
        if self._leve:
            raise self._leve
        return self._resultat


def _enveloppe():
    from orchestrator.orchestrator import Orchestrator
    return Orchestrator._run_agents_and_decide


@pytest.mark.parametrize("valeur", [None, True, False, 0, "", "LONG", {"a": 1}, [1, 2]])
def test_valeur_de_retour_rendue_telle_quelle(valeur, tmp_path, monkeypatch):
    """
    Meme methode qu'en aout pour la tracabilite : on verrouille que la mesure
    est transparente. Le resultat de la decision traverse l'enveloppe sans
    etre touche.
    """
    import asyncio
    monkeypatch.setattr(jc, "chemin_journal", lambda: tmp_path / "cycles.csv")
    o = _FauxOrchestrateur(resultat=valeur)
    obtenu = asyncio.run(_enveloppe()(o))
    assert obtenu is valeur or obtenu == valeur
    assert o.appels == 1


def test_exception_de_la_decision_propagee_intacte(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setattr(jc, "chemin_journal", lambda: tmp_path / "cycles.csv")
    boum = RuntimeError("panne MT5")
    o = _FauxOrchestrateur(leve=boum)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(_enveloppe()(o))
    assert e.value is boum
    # et la ligne est ecrite malgre l'exception
    assert (tmp_path / "cycles.csv").exists()


def test_ligne_ecrite_meme_sur_sortie_anticipee(tmp_path, monkeypatch):
    """
    Le coeur du dispositif : la methode de decision compte une trentaine de
    `return` anticipes. Le `finally` doit ecrire pour chacun.
    """
    import asyncio
    p = tmp_path / "cycles.csv"
    monkeypatch.setattr(jc, "chemin_journal", lambda: p)
    o = _FauxOrchestrateur(resultat=None)       # sortie immediate, aucun vote
    asyncio.run(_enveloppe()(o))
    lignes = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lignes) == 1 + len(o.tfs)
    for l in lignes[1:]:
        ch = l.split(",")
        assert ch[1] == "NAS100"
        assert ch[3] == "------"                 # aucun agent n'a vote
        assert ch[7] == "W"


def test_echec_d_ecriture_ne_casse_pas_le_cycle(tmp_path, monkeypatch):
    """Un journal en panne ne doit jamais interrompre une decision."""
    import asyncio

    def _boum(*a, **k):
        raise OSError("disque plein")

    monkeypatch.setattr(jc, "ecrire", _boum)
    o = _FauxOrchestrateur(resultat="LONG")
    assert asyncio.run(_enveloppe()(o)) == "LONG"


def test_agregation_renvoie_toujours_le_meme_quadruplet():
    """
    Garde-fou architectural : score_long/score_short sont deposes sur
    l'instance, jamais ajoutes a la valeur de retour de l'agregation.
    """
    from orchestrator.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator._compute_aggregate_direction)
    retours = [l.strip() for l in src.splitlines()
               if l.startswith(" " * 8) and l[8:].startswith("return ")]
    assert retours == ["return direction, float(score_agr), float(confluence), details"]
    assert "self._derniers_scores_ls" in src


def test_journal_absent_de_la_chaine_de_decision():
    """
    Rien de ce que le journal ecrit ne doit etre relu par la decision : on
    verifie qu'aucune ligne ne lit self._cycle en dehors de l'enveloppe.
    """
    from orchestrator.orchestrator import Orchestrator
    src = inspect.getsource(Orchestrator._run_agents_and_decide_impl)
    for ligne in src.splitlines():
        if "self._cycle" in ligne and not ligne.strip().startswith("#"):
            assert ".update(" in ligne, (
                "self._cycle est LU par la decision : %s" % ligne.strip())
