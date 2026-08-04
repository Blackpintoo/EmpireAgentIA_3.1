# -*- coding: utf-8 -*-
"""
Entonnoir : instrumenter l'etage AMONT des refus (2026-08-04).

Mesure du 03/08, marche ouvert : XAUUSD a produit 471 decisions pour seulement
111 refus traces dans guards.log — soit 76 % de l'attrition invisible a
tools/entonnoir.py. La lecture « direction_filter domine sur XAUUSD » portait
donc sur un quart de l'echantillon.

Les abandons anterieurs a la chaine des 20 gardes (score, confluence,
calendrier economique, RR aberrant, momentum inverse, volatilite, regime…)
n'ecrivaient qu'un texte libre dans le journal applicatif. Ils emettent
desormais la meme ligne `garde:<nom>` que les autres.
"""
from types import SimpleNamespace

import orchestrator.orchestrator as O


def _faux_orchestrateur():
    return SimpleNamespace(symbol="XAUUSD", _send_telegram=lambda *a, **k: None)


def test_un_refus_amont_ecrit_une_ligne_garde(monkeypatch):
    ecrits = []
    monkeypatch.setattr(O, "_record_guard_event",
                        lambda sym, tag, msg: ecrits.append((sym, tag, msg)))

    O.Orchestrator._tracer_refus_amont(_faux_orchestrateur(),
                                       "rr_safety", "RR aberrant")

    assert ecrits == [("XAUUSD", "garde:rr_safety", "RR aberrant")]


def test_le_prefixe_garde_rend_la_ligne_agregeable(monkeypatch):
    """tools/entonnoir.py ne compte que les lignes commencant par 'garde:'."""
    ecrits = []
    monkeypatch.setattr(O, "_record_guard_event",
                        lambda sym, tag, msg: ecrits.append((sym, tag, msg)))

    O.Orchestrator._tracer_refus_amont(_faux_orchestrateur(), "amont_econ_calendar",
                                       "econ_calendar:CPI")

    assert ecrits[0][1].startswith("garde:")


def test_le_motif_est_borne_et_sur_une_seule_ligne(monkeypatch):
    """Un motif multiligne casserait le format `ts|symbole|garde|motif`."""
    ecrits = []
    monkeypatch.setattr(O, "_record_guard_event",
                        lambda sym, tag, msg: ecrits.append((sym, tag, msg)))

    O.Orchestrator._tracer_refus_amont(_faux_orchestrateur(), "amont_score",
                                       "ligne1\nligne2 " + "x" * 400)

    motif = ecrits[0][2]
    assert "\n" not in motif
    assert len(motif) <= 200


def test_une_panne_de_journalisation_ne_bloque_pas_le_refus(monkeypatch):
    """Journaliser est une observation : cela ne doit jamais lever."""
    def _explose(*a, **k):
        raise IOError("disque plein")

    monkeypatch.setattr(O, "_record_guard_event", _explose)

    O.Orchestrator._tracer_refus_amont(_faux_orchestrateur(), "amont_score", "8.1")


def test_motif_vide_reste_ecrivable(monkeypatch):
    ecrits = []
    monkeypatch.setattr(O, "_record_guard_event",
                        lambda sym, tag, msg: ecrits.append((sym, tag, msg)))

    O.Orchestrator._tracer_refus_amont(_faux_orchestrateur(), "amont_divers")

    assert ecrits == [("XAUUSD", "garde:amont_divers", "")]
