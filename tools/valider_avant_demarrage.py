# -*- coding: utf-8 -*-
"""
tools/valider_avant_demarrage.py — valide le code AVANT de lancer le bot.

AJOUT 2026-08-02.

Pourquoi ce fichier existe
--------------------------
Le garde-fou de démarrage (P1, 30/07) lançait `pytest` DEPUIS le processus du
bot, dans le répertoire de production. Les tests écrivaient donc dans les vrais
`data/` et `logs/` :

  - `data/compte_111/`, `compte_222/`, `compte_888/`, `compte_12345678/`,
    `compte_inconnu/` — créés par les tests de cloisonnement par compte ;
  - des lignes de test dans `logs/empire_agent.log`, mêlées aux vraies ;
  - des ordres simulés et des tickets fictifs dans les journaux.

Résultat : toute vérification ultérieure devait d'abord démêler le réel du
factice. C'était une pollution de la production par l'outil censé la protéger.

Ce que fait ce script
---------------------
Il exécute la suite dans un répertoire temporaire jetable : `config/` y est
recopié, `data/` et `logs/` y sont vides et détruits à la fin. Le code est
importé depuis le dépôt via PYTHONPATH, mais tout chemin relatif écrit par les
tests atterrit dans le bac à sable.

En cas de succès, il écrit `data/selftest_state.json` — le seul fichier de
production qu'il touche, et c'est lui qui l'écrit, pas les tests. Le bot lit
ensuite ce jeton au démarrage et refuse de se lancer s'il est absent, périmé
ou en échec. Le bot ne lance plus jamais pytest lui-même.

    python tools/valider_avant_demarrage.py          # valide si le code a change
    python tools/valider_avant_demarrage.py --force  # revalide dans tous les cas
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
os.chdir(RACINE)
sys.path.insert(0, str(RACINE))

from utils.startup_selftest import code_fingerprint, _read_state, _write_state  # noqa: E402

DELAI_MAX_S = 600


def _bac_a_sable(tmp: Path) -> Path:
    """Répertoire de travail jetable : config recopié, data/ et logs/ vides."""
    (tmp / "data").mkdir(parents=True, exist_ok=True)
    (tmp / "logs").mkdir(parents=True, exist_ok=True)
    (tmp / "reports").mkdir(parents=True, exist_ok=True)
    if (RACINE / "config").exists():
        shutil.copytree(RACINE / "config", tmp / "config", dirs_exist_ok=True)
    for nom in (".env",):                      # lu par les tests via load_dotenv
        if (RACINE / nom).exists():
            shutil.copy2(RACINE / nom, tmp / nom)
    return tmp


def executer_suite(verbeux: bool = False):
    """Renvoie (succes, sortie). N'écrit rien hors du bac à sable."""
    with tempfile.TemporaryDirectory(prefix="empire_validation_") as tmpdir:
        tmp = _bac_a_sable(Path(tmpdir))
        env = dict(os.environ)
        env["PYTHONPATH"] = str(RACINE) + os.pathsep + env.get("PYTHONPATH", "")
        env["EMPIRE_SELFTEST"] = "1"
        # EMPIRE_CONSOLE n'est PAS force ici : tests/conftest.py le met a 1,
        # et test_redaction capture la sortie console pour verifier le
        # masquage des secrets. Le forcer a 0 cassait trois tests.
        env["EMPIRE_LOG_FILE"] = str(tmp / "logs" / "validation.log")
        env["MT5_DRY_RUN"] = "1"
        cmd = [sys.executable, "-m", "pytest", str(RACINE / "tests"),
               "-q", "--tb=short", "-p", "no:cacheprovider",
               "--basetemp", str(tmp / "pytest_tmp")]
        try:
            proc = subprocess.run(cmd, cwd=str(tmp), env=env, timeout=DELAI_MAX_S,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except FileNotFoundError:
            return False, "pytest introuvable (python -m pytest n'a pas pu etre lance)."
        except subprocess.TimeoutExpired:
            return False, "la suite de tests a depasse %d s." % DELAI_MAX_S
        sortie = (proc.stdout or b"").decode("utf-8", "replace")
        if verbeux:
            print(sortie)
        # Le bac à sable, et tout ce que les tests y ont écrit, disparaît ici.
        return proc.returncode == 0, sortie


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="revalide meme si le code n'a pas change")
    ap.add_argument("--verbeux", action="store_true")
    a = ap.parse_args()

    empreinte = code_fingerprint(str(RACINE))
    etat = _read_state(str(RACINE))

    if not a.force and etat.get("fingerprint") == empreinte and etat.get("ok") is True:
        print("[VALIDATION] Code inchange depuis la derniere validation reussie "
              "(%s). Rien a faire." % etat.get("ts_utc", "?"))
        return 0

    print("[VALIDATION] Execution de la suite dans un repertoire temporaire...")
    t0 = time.time()
    ok, sortie = executer_suite(verbeux=a.verbeux)
    duree = time.time() - t0

    _write_state(str(RACINE), {
        "fingerprint": empreinte,
        "ok": bool(ok),
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "tail": sortie[-2000:],
        "isole": True,
    })

    derniere = [l for l in sortie.strip().splitlines() if l.strip()]
    resume = derniere[-1] if derniere else "(aucune sortie)"
    if ok:
        print("[VALIDATION] OK en %.1f s — %s" % (duree, resume))
        print("[VALIDATION] Aucun fichier de production n'a ete touche par les tests.")
        return 0

    print("[VALIDATION] ECHEC en %.1f s" % duree)
    print(sortie[-4000:])
    print()
    print("Le bot refusera de demarrer tant que la suite ne passe pas.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
