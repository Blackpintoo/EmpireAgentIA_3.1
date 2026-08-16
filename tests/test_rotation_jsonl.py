# -*- coding: utf-8 -*-
"""
Tests de utils/rotation_jsonl.py.

AJOUT 2026-08-16. Preuve que la borne de taille tient, et que la rotation ne
perd pas de contenu.
"""
import json

import pytest

from utils.rotation_jsonl import rouler_si_besoin


def _ecrire(p, octets):
    p.write_bytes(b"x" * octets)
    return p


def test_ne_roule_pas_sous_le_seuil(tmp_path):
    f = _ecrire(tmp_path / "s.jsonl", 100)
    assert rouler_si_besoin(f, taille_max=1000) is False
    assert f.exists()
    assert not (tmp_path / "s.jsonl.1").exists()


def test_ne_roule_pas_si_absent(tmp_path):
    assert rouler_si_besoin(tmp_path / "absent.jsonl", taille_max=1) is False


def test_roule_au_dessus_du_seuil(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text("contenu original\n", encoding="utf-8")
    assert rouler_si_besoin(f, taille_max=5) is True
    # Le fichier principal a disparu : l'appelant le recreera en ajout.
    assert not f.exists()
    assert (tmp_path / "s.jsonl.1").read_text(encoding="utf-8") == "contenu original\n"


def test_cascade_et_purge_du_plus_ancien(tmp_path):
    f = tmp_path / "s.jsonl"
    for i in range(1, 4):
        (tmp_path / ("s.jsonl.%d" % i)).write_text("gen%d" % i, encoding="utf-8")
    f.write_text("courant", encoding="utf-8")

    assert rouler_si_besoin(f, taille_max=1, conserver=3) is True

    assert (tmp_path / "s.jsonl.1").read_text(encoding="utf-8") == "courant"
    assert (tmp_path / "s.jsonl.2").read_text(encoding="utf-8") == "gen1"
    assert (tmp_path / "s.jsonl.3").read_text(encoding="utf-8") == "gen2"
    # gen3 etait le plus ancien : supprime, pas decale vers un .4
    assert not (tmp_path / "s.jsonl.4").exists()


def test_plafond_dur_apres_rotations_repetees(tmp_path):
    """
    Le point qui compte vraiment : le total sur disque reste borne, meme si
    on ecrit indefiniment. C'est ce qui manquait a agents_snap.jsonl.
    """
    f = tmp_path / "s.jsonl"
    taille_max = 1024
    for _ in range(40):
        with f.open("a", encoding="utf-8") as fh:
            fh.write("y" * 600 + "\n")
        rouler_si_besoin(f, taille_max=taille_max, conserver=3)

    total = sum(p.stat().st_size for p in tmp_path.glob("s.jsonl*"))
    # 4 fichiers au plus (courant + 3), chacun borne par taille_max + un
    # enregistrement en cours d'ecriture.
    assert len(list(tmp_path.glob("s.jsonl*"))) <= 4
    assert total <= 4 * (taille_max + 601)


def test_conserver_zero_supprime_sans_historique(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text("jetable", encoding="utf-8")
    assert rouler_si_besoin(f, taille_max=1, conserver=0) is True
    assert not f.exists()
    assert not (tmp_path / "s.jsonl.1").exists()


@pytest.mark.parametrize("taille_max,conserver", [(0, 3), (-1, 3), (10, -1)])
def test_parametres_absurdes_ne_font_rien(tmp_path, taille_max, conserver):
    f = tmp_path / "s.jsonl"
    f.write_text("intact", encoding="utf-8")
    assert rouler_si_besoin(f, taille_max=taille_max, conserver=conserver) is False
    assert f.read_text(encoding="utf-8") == "intact"


def test_erreur_avalee_jamais_de_levee(tmp_path):
    """
    Ce journal sert au diagnostic. Une rotation qui echoue ne doit jamais
    remonter jusqu'a la boucle de decision.
    """
    assert rouler_si_besoin(tmp_path) is False          # un repertoire
    assert rouler_si_besoin(None) is False              # type invalide
    assert rouler_si_besoin("") is False


def test_lignes_jsonl_restent_lisibles_apres_rotation(tmp_path):
    """La rotation coupe entre deux ecritures, jamais au milieu d'une ligne."""
    f = tmp_path / "s.jsonl"
    for i in range(30):
        rouler_si_besoin(f, taille_max=200, conserver=3)
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"i": i, "bourrage": "z" * 50}) + "\n")

    for p in sorted(tmp_path.glob("s.jsonl*")):
        for ligne in p.read_text(encoding="utf-8").splitlines():
            json.loads(ligne)          # leve si une ligne a ete tronquee
