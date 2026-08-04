# -*- coding: utf-8 -*-
"""
Garde-fou de fraicheur du code (AJOUT 2026-08-04).

Reproduit la situation du 2026-08-02 : un fichier source reecrit APRES le
demarrage du processus, dont l'ancienne version reste chargee en memoire.
"""
import os
import time

import pytest

from utils import fraicheur_code as FC


def _ecrire(tmp_path, nom, contenu="# vide\n"):
    p = tmp_path / nom
    p.write_text(contenu, encoding="utf-8")
    return p


def test_aucun_fichier_plus_recent_ne_declenche_rien(tmp_path):
    _ecrire(tmp_path, "a.py")
    _ecrire(tmp_path, "b.py")
    # Reference posterieure a l'ecriture : rien n'a bouge depuis.
    t_ref = time.time() + 5
    assert FC.fichiers_modifies_depuis(t_ref, str(tmp_path)) == []
    assert FC.verifier_fraicheur_code(str(tmp_path), t_ref, sortir=True) == []


def test_un_fichier_reecrit_apres_le_demarrage_est_detecte(tmp_path):
    t_demarrage = time.time()
    # Un fichier deja en place au demarrage : mtime force AVANT la reference,
    # sans quoi la granularite du systeme de fichiers le rend indistinguable.
    stable = _ecrire(tmp_path, "stable.py")
    os.utime(stable, (t_demarrage - 60, t_demarrage - 60))
    # Le checkout arrive apres le demarrage — cas Finnhub du 02/08.
    cible = _ecrire(tmp_path, "retardataire.py", "# nouvelle version\n")
    os.utime(cible, (t_demarrage + 4, t_demarrage + 4))

    trouves = FC.fichiers_modifies_depuis(t_demarrage, str(tmp_path))
    noms = [rel for rel, _ in trouves]
    assert noms == ["retardataire.py"], noms


def test_le_demarrage_est_refuse_quand_le_code_a_bouge(tmp_path):
    t_demarrage = time.time()
    cible = _ecrire(tmp_path, "tardif.py")
    os.utime(cible, (t_demarrage + 3, t_demarrage + 3))

    with pytest.raises(SystemExit) as exc:
        FC.verifier_fraicheur_code(str(tmp_path), t_demarrage)
    assert exc.value.code == FC.CODE_SORTIE


def test_contournement_explicite_laisse_passer(tmp_path, monkeypatch):
    t_demarrage = time.time()
    cible = _ecrire(tmp_path, "tardif.py")
    os.utime(cible, (t_demarrage + 3, t_demarrage + 3))

    monkeypatch.setenv("EMPIRE_SKIP_FRAICHEUR", "1")
    # Ne leve pas, mais renvoie quand meme la liste : la trace reste visible.
    divergents = FC.verifier_fraicheur_code(str(tmp_path), t_demarrage)
    assert [rel for rel, _ in divergents] == ["tardif.py"]


def test_un_fichier_non_python_est_ignore(tmp_path):
    t_demarrage = time.time()
    cible = tmp_path / "donnees.json"
    cible.write_text("{}", encoding="utf-8")
    os.utime(cible, (t_demarrage + 3, t_demarrage + 3))
    assert FC.fichiers_modifies_depuis(t_demarrage, str(tmp_path)) == []
